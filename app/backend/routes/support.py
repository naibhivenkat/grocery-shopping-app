"""Authorized Support Center with durable send identity and honest mail status."""
import base64
import binascii
import hashlib
import json
import os
from datetime import datetime,timedelta,timezone
from email.utils import parseaddr
import re
from flask import Blueprint,Response,g,jsonify,request
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from auth_utils import require_auth,require_role,require_webhook_secret
from db import SUPPORT_INTERNAL_NOTES,SUPPORT_MESSAGES,SUPPORT_SYNC,SUPPORT_TICKETS,AUDIT_LOGS,NOTIFICATIONS,USERS,col,doc,db,now_iso,to_dict
from gmail_service import gmail_service
from routes.gmail_auth import GmailAuthError

support_bp=Blueprint('support',__name__)


def _id(value):
    if not isinstance(value,str) or not value or '/' in value or len(value)>128:
        raise ValueError('Invalid ticket ID')
    return value


def _payload():
    payload=request.get_json(silent=True) or {}
    if not isinstance(payload,dict):raise ValueError('JSON object required')
    return payload


def _text(value,name,limit=4000):
    if not isinstance(value,str) or not 1<=len(value.strip())<=limit:
        raise ValueError(f'{name} must be nonempty text up to {limit} characters')
    return value.strip()




@support_bp.get('/account-deletion')
def account_deletion_instructions():
    # Public Play Console deletion-request URL; no authentication or provider call.
    page = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Account and data deletion | ALL LOCAL</title>
<style>body{font:17px/1.6 system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 22px;color:#182a21;background:#fafcfb}h1{line-height:1.2}a{color:#166534}section{margin:28px 0;padding:20px;background:#fff;border:1px solid #dce7df;border-radius:12px}</style></head>
<body><header><strong>ALL LOCAL</strong><p>Operated by Swasthik Enterprises</p></header>
<main><h1>Request account and data deletion</h1>
<p>You can request deletion of your ALL LOCAL account and associated personal data through either option below.</p>
<section><h2>Send a deletion request by email</h2>
<p>Email <a href="mailto:support@alllocal.in?subject=Account%20deletion%20request">support@alllocal.in</a> from your registered email address with the subject <strong>Account deletion request</strong>.</p>
<p>Include your account identifier, such as your registered email address or your ALL LOCAL account ID, so we can find the account.</p>
<p><strong>Do not send your password, OTP, or payment details.</strong></p></section>
<section><h2>Request deletion in the app</h2>
<p>Sign in to ALL LOCAL, open <strong>Help &amp; Support</strong>, then select <strong>Request account &amp; data deletion</strong>. Submit the request and follow its replies in the app.</p></section>
<h2>What happens next</h2><p>Requests are manually verified and processed by our support team. We may ask you to verify ownership before deleting the account and associated personal data.</p>
<h2>Data deletion and retention</h2>
<p>Your request can cover your account profile and contact details, uploaded avatar, and associated personal data. During manual processing of a verified request, support will confirm which data is erased and which data must be retained. This is a request process, not an automatic erasure of all chats, media, or order history.</p>
<p>Legal, financial, order, transaction, and security records may require retention for applicable legal or business obligations. The relevant retention period and the deletion timeline depend on those obligations; support will confirm them for your request.</p>
<p>Read the <a href="https://alllocal.in/pages/privacy-policy.html">ALL LOCAL Privacy Policy</a> for information about personal data.</p>
</main></body></html>"""
    response = Response(page, content_type='text/html; charset=utf-8')
    response.headers['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

class SupportRequestError(ValueError):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


def _app_payload(allowed):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) - set(allowed):
        raise SupportRequestError('Only the documented JSON fields are allowed')
    return payload


def _app_text(value, name, limit, single_line=False):
    value = _text(value, name, limit)
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', value) or (single_line and ('\n' in value or '\r' in value)):
        raise SupportRequestError(f'{name} contains invalid control characters')
    return value


def _request_key():
    key = request.headers.get('Idempotency-Key')
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{8,128}', key):
        raise SupportRequestError('Idempotency-Key must contain 8 to 128 identifier characters')
    return key


def _public_app_ticket(snapshot):
    data = snapshot.to_dict() or {}
    fields = ('subject', 'category', 'status', 'delivery_channel', 'created_at', 'updated_at', 'resolved_at')
    return {'uid': snapshot.id, **{name: data[name] for name in fields if name in data}}


def _own_internal(snapshot, user_id):
    data = snapshot.to_dict() or {}
    return snapshot.exists and data.get('customer_id') == user_id and data.get('delivery_channel') == 'internal'


@support_bp.post('/support/tickets')
@require_auth
def create_app_support_ticket():
    try:
        payload = _app_payload({'subject', 'message', 'category'})
        subject = _app_text(payload.get('subject'), 'subject', 160, True)
        message = _app_text(payload.get('message'), 'message', 4000)
        category = payload.get('category', 'general')
        if not isinstance(category, str) or category not in {'general', 'order', 'account_deletion'}:
            raise SupportRequestError('Invalid support category')
        key = _request_key()
        fingerprint = hashlib.sha256(json.dumps([subject, message, category], ensure_ascii=False).encode()).hexdigest()
        ticket_id = 'app_' + hashlib.sha256(f'{g.user_id}:{key}'.encode()).hexdigest()
        ticket_ref = doc(SUPPORT_TICKETS, ticket_id)
        message_ref = doc(SUPPORT_MESSAGES, ticket_id + '_initial')
        @firestore.transactional
        def create(tx):
            existing = ticket_ref.get(transaction=tx)
            initial = message_ref.get(transaction=tx)
            if existing.exists:
                ticket = existing.to_dict() or {}
                if not _own_internal(existing, g.user_id) or ticket.get('request_fingerprint') != fingerprint or not initial.exists:
                    raise SupportRequestError('Idempotency-Key belongs to another support request', 409)
                return {'success': True, 'ticket_id': ticket_id, 'status': ticket.get('status'), 'delivery_channel': 'internal'}, 200
            if initial.exists:
                raise SupportRequestError('Support request needs review', 409)
            timestamp = now_iso()
            tx.create(ticket_ref, {'uid': ticket_id, 'customer_id': g.user_id,
                'customer_name': getattr(g, 'user_name', ''), 'subject': subject, 'category': category,
                'delivery_channel': 'internal', 'status': 'open', 'request_fingerprint': fingerprint,
                'last_inbound_message_id': message_ref.id, 'created_at': timestamp, 'updated_at': timestamp})
            tx.create(message_ref, {'uid': message_ref.id, 'ticket_id': ticket_id, 'sender_id': g.user_id,
                'direction': 'inbound', 'bodyText': message, 'internal_date': timestamp,
                'delivery_channel': 'internal', 'status': 'recorded'})
            return {'success': True, 'ticket_id': ticket_id, 'status': 'open', 'delivery_channel': 'internal'}, 201
        data, status = create(db().transaction())
        return jsonify(data), status
    except ValueError as exc:
        return jsonify({'detail': str(exc)}), getattr(exc, 'status', 422)


@support_bp.get('/support/tickets')
@require_auth
def list_app_support_tickets():
    tickets = [_public_app_ticket(snap) for snap in col(SUPPORT_TICKETS).where(
        filter=FieldFilter('customer_id', '==', g.user_id)).stream() if _own_internal(snap, g.user_id)]
    tickets.sort(key=lambda ticket: (str(ticket.get('updated_at') or ''), ticket['uid']), reverse=True)
    return jsonify(tickets), 200


@support_bp.get('/support/tickets/<ticket_id>')
@require_auth
def get_app_support_ticket(ticket_id):
    try:
        ticket_id = _id(ticket_id)
    except ValueError as exc:
        return jsonify({'detail': str(exc)}), 422
    snapshot = doc(SUPPORT_TICKETS, ticket_id).get()
    if not _own_internal(snapshot, g.user_id):
        return jsonify({'detail': 'Ticket not found'}), 404
    ticket = _public_app_ticket(snapshot)
    messages = []
    for snap in col(SUPPORT_MESSAGES).where(filter=FieldFilter('ticket_id', '==', ticket_id)).stream():
        data = snap.to_dict() or {}
        if data.get('delivery_channel') != 'internal':
            continue
        messages.append({'uid': snap.id, **{key: data[key] for key in
            ('direction', 'bodyText', 'internal_date', 'status', 'delivery_channel') if key in data}})
    messages.sort(key=lambda item: (str(item.get('internal_date') or ''), item['uid']))
    ticket['messages'] = messages
    return jsonify(ticket), 200


@support_bp.post('/support/tickets/<ticket_id>/messages')
@require_auth
def reply_app_support_ticket(ticket_id):
    try:
        ticket_id = _id(ticket_id)
        payload = _app_payload({'message'})
        message = _app_text(payload.get('message'), 'message', 4000)
        key = _request_key()
        ticket_ref = doc(SUPPORT_TICKETS, ticket_id)
        message_id = 'appmsg_' + hashlib.sha256(f'{g.user_id}:{ticket_id}:{key}'.encode()).hexdigest()
        message_ref = doc(SUPPORT_MESSAGES, message_id)
        @firestore.transactional
        def add(tx):
            snapshot = ticket_ref.get(transaction=tx)
            previous = message_ref.get(transaction=tx)
            if not _own_internal(snapshot, g.user_id):
                return {'detail': 'Ticket not found'}, 404
            if previous.exists:
                data = previous.to_dict() or {}
                if data.get('bodyText') != message or data.get('sender_id') != g.user_id or data.get('ticket_id') != ticket_id:
                    raise SupportRequestError('Idempotency-Key belongs to another message', 409)
                # A replay must not reopen a ticket subsequently resolved by admin.
                return {'success': True, 'message_id': message_id, 'status': (snapshot.to_dict() or {}).get('status'), 'delivery_channel': 'internal'}, 200
            timestamp = now_iso()
            tx.create(message_ref, {'uid': message_id, 'ticket_id': ticket_id, 'sender_id': g.user_id,
                'direction': 'inbound', 'bodyText': message, 'internal_date': timestamp,
                'delivery_channel': 'internal', 'status': 'recorded'})
            tx.update(ticket_ref, {'status': 'open', 'updated_at': timestamp, 'resolved_at': None,
                'last_inbound_message_id': message_id})
            return {'success': True, 'message_id': message_id, 'status': 'open', 'delivery_channel': 'internal'}, 201
        data, status = add(db().transaction())
        return jsonify(data), status
    except ValueError as exc:
        return jsonify({'detail': str(exc)}), getattr(exc, 'status', 422)

@support_bp.post('/admin/support/webhook')
@require_webhook_secret
def support_webhook():
    try:
        payload=_payload()
        message=payload.get('message')
        if not isinstance(message,dict):raise ValueError('Webhook message required')
        data=message
        if message.get('data') is not None:
            encoded=message['data']
            if not isinstance(encoded,str) or len(encoded)>8192:raise ValueError('Invalid webhook data')
            data=json.loads(base64.b64decode(encoded+'='*(-len(encoded)%4),altchars=b'-_',validate=True))
            if not isinstance(data,dict):raise ValueError('Invalid webhook data')
        history=str(data.get('historyId') or '')
        if not history.isdigit() or len(history)>32:raise ValueError('Valid Gmail historyId required')
        mailbox=data.get('emailAddress')
        expected=os.getenv('GMAIL_MAILBOX_EMAIL')
        if expected and (not isinstance(mailbox,str) or mailbox.lower()!=expected.lower()):
            return jsonify({'detail':'Webhook mailbox mismatch'}),403
        state_ref=doc(SUPPORT_SYNC,'state')
        @firestore.transactional
        def record(tx):
            snap=state_ref.get(transaction=tx);state=snap.to_dict() or {}
            previous=str(state.get('latest_history_id') or '0')
            if previous.isdigit() and int(history)<=int(previous):return
            tx.set(state_ref,{'last_webhook_received':now_iso(),'latest_history_id':history,
                'status':'pending_sync',**({'mailbox_email':mailbox} if isinstance(mailbox,str) else {})},merge=True)
        record(db().transaction())
        return jsonify({'success':True}),200
    except (ValueError,TypeError,binascii.Error,UnicodeDecodeError):
        return jsonify({'detail':'Invalid Gmail webhook payload'}),422


@support_bp.get('/admin/support')
@require_role('admin','super_admin')
def list_support_tickets():
    status=(request.args.get('status') or '').strip()
    if status and status not in {'open','resolved','pending_reply','closed'}:
        return jsonify({'detail':'Invalid support status'}),422
    query=col(SUPPORT_TICKETS)
    if status:query=query.where(filter=FieldFilter('status','==',status))
    # Filter alone needs no composite index; sort after reading legacy documents.
    tickets=[to_dict(s) for s in query.stream()]
    tickets.sort(key=lambda t:str(t.get('updated_at') or t.get('created_at') or ''),reverse=True)
    return jsonify(tickets),200


@support_bp.get('/admin/support/<ticket_id>')
@require_role('admin','super_admin')
def get_support_ticket(ticket_id):
    try:ticket_id=_id(ticket_id)
    except ValueError as exc:return jsonify({'detail':str(exc)}),422
    snap=doc(SUPPORT_TICKETS,ticket_id).get()
    if not snap.exists:return jsonify({'detail':'Ticket not found'}),404
    ticket=to_dict(snap)
    for name,collection,sort_field in [('messages',SUPPORT_MESSAGES,'internal_date'),('notes',SUPPORT_INTERNAL_NOTES,'timestamp')]:
        ticket[name]=[to_dict(item) for item in col(collection).where(filter=FieldFilter('ticket_id','==',ticket_id)).stream()]
        ticket[name].sort(key=lambda item:str(item.get(sort_field) or ''))
    return jsonify(ticket),200


def send_ticket_reply(ticket_id,reply_body,actor_id,actor_email='',actor_name='',idempotency_key=None):
    ticket_id=_id(ticket_id);reply_body=_text(reply_body,'reply')
    if idempotency_key is not None and (not isinstance(idempotency_key,str) or not 8<=len(idempotency_key)<=128):
        raise ValueError('Idempotency-Key must contain 8 to 128 characters')
    ticket_ref=doc(SUPPORT_TICKETS,ticket_id)
    @firestore.transactional
    def acquire(tx):
        snap=ticket_ref.get(transaction=tx)
        if not snap.exists:return {'missing':True}
        ticket=snap.to_dict() or {}
        seed=idempotency_key or f"{actor_id}:{reply_body}:{ticket.get('last_inbound_message_id') or ''}"
        message_id='reply_'+hashlib.sha256(f'{ticket_id}:{seed}'.encode()).hexdigest()
        message_ref=doc(SUPPORT_MESSAGES,message_id)
        message_snap=message_ref.get(transaction=tx);existing=message_snap.to_dict() or {}
        if existing and (existing.get('bodyText')!=reply_body or existing.get('admin_id')!=actor_id):
            raise ValueError('Idempotency-Key belongs to another reply')
        if existing.get('status')=='sent' or existing.get('status')=='recorded':
            return {'skip':True,'status':existing['status'],'message_id':message_id,'gmail_message_id':existing.get('gmail_message_id'),'channel':existing.get('delivery_channel')}
        if existing.get('status') in {'sending','requires_review'}:
            if existing.get('status')=='sending':
                try:
                    started=datetime.fromisoformat(existing.get('send_started_at') or '')
                    if started>datetime.now(timezone.utc)-timedelta(minutes=5):
                        return {'skip':True,'status':'sending','message_id':message_id}
                except (ValueError,TypeError):pass
            return {'reconcile':True,'message_id':message_id,'request':existing.get('send_request') or {},'inbound_id':existing.get('inbound_id')}
        recipient=None if ticket.get('delivery_channel')=='internal' else ticket.get('customer_email')
        channel='gmail' if recipient else 'internal'
        if channel=='gmail':
            _,address=parseaddr(str(recipient))
            if not re.fullmatch(r'[^\s@,<>]+@[^\s@,<>]+\.[^\s@,<>]+',address):raise ValueError('Ticket customer email is invalid')
            subject=str(ticket.get('subject') or 'Support request')
            if '\r' in subject or '\n' in subject or len(subject)>998:raise ValueError('Ticket subject is invalid')
            original={'to':address,'subject':subject,'body':reply_body,'thread_id':ticket.get('gmail_thread_id'),
                'in_reply_to':ticket.get('last_message_id_header'),
                'message_id_header':f'<{message_id}@localshopfinder.com>'}
        else:original={}
        notification_ref=None
        notification_exists=False
        customer_id=ticket.get('customer_id')
        if channel=='internal' and isinstance(customer_id,str) and customer_id and '/' not in customer_id and len(customer_id)<=128:
            customer=doc(USERS,customer_id).get(transaction=tx)
            notification_ref=doc(NOTIFICATIONS,'support_'+message_id)
            notification_exists=notification_ref.get(transaction=tx).exists
            if not customer.exists:notification_ref=None
        timestamp=now_iso()
        tx.set(message_ref,{'uid':message_id,'ticket_id':ticket_id,'direction':'outbound','bodyText':reply_body,
            'internal_date':timestamp,'admin_id':actor_id,'admin_name':actor_name,'delivery_channel':channel,
            'status':'sending' if channel=='gmail' else 'recorded','send_started_at':timestamp,'send_request':original,
            'inbound_id':ticket.get('last_inbound_message_id')})
        tx.update(ticket_ref,{'status':'pending_reply' if channel=='gmail' else 'resolved','updated_at':timestamp,
            'last_reply_status':'sending' if channel=='gmail' else 'recorded',
            **({'admin_reply':reply_body,'resolved_at':timestamp} if channel=='internal' else {})})
        if notification_ref is not None and not notification_exists:
            tx.create(notification_ref,{'user_id':customer_id,'type':'support_reply','title':'Support replied',
                'body':'You have a new reply to your support request','reference_id':ticket_id,
                'is_read':False,'created_at':timestamp})
        if not message_snap.exists:
            tx.create(doc(AUDIT_LOGS,message_id),{'admin_id':actor_id,'admin_email':actor_email,'action':'Reply to Ticket',
                'target_id':ticket_id,'target_type':'support_ticket','created_at':timestamp})
        return {'message_id':message_id,'request':original,'channel':channel,'inbound_id':ticket.get('last_inbound_message_id')}
    acquired=acquire(db().transaction())
    if acquired.get('missing'):return {'detail':'Ticket not found'},404
    if acquired.get('skip'):
        status=acquired['status']
        return {'success':status in {'sent','recorded'},'status':status,'message_id':acquired['message_id'],**({'delivery_channel':acquired['channel']} if acquired.get('channel') else {})},202 if status=='sending' else 200
    if acquired.get('channel')=='internal':return {'success':True,'status':'recorded','delivery_channel':'internal','message_id':acquired['message_id']},200
    message_ref=doc(SUPPORT_MESSAGES,acquired['message_id']);original=acquired['request']
    sent=None;error_status=None
    try:
        if acquired.get('reconcile'):
            sent=gmail_service.find_sent_message(original.get('message_id_header') or '')
            if not sent:error_status='requires_review'
        else:sent=gmail_service.send_email(**original)
        if sent is not None and not sent.get('id'):error_status='requires_review'
    except GmailAuthError:error_status='not_sent' if not acquired.get('reconcile') else 'requires_review'
    except ValueError:error_status='not_sent' if not acquired.get('reconcile') else 'requires_review'
    except Exception:error_status='requires_review'
    @firestore.transactional
    def finish(tx):
        message_snap=message_ref.get(transaction=tx);ticket_snap=ticket_ref.get(transaction=tx)
        message=message_snap.to_dict() or {};ticket=ticket_snap.to_dict() or {}
        if message.get('status')=='sent':return {'success':True,'status':'sent','message_id':message_ref.id},200
        status=error_status or 'sent'
        tx.update(message_ref,{'status':status,'gmail_message_id':sent.get('id') if sent else None,'updated_at':now_iso()})
        if ticket_snap.exists:
            updates={'last_reply_status':status,'updated_at':now_iso()}
            # An inbound reply arriving during the send keeps the ticket open.
            if status=='sent' and ticket.get('last_inbound_message_id')==acquired.get('inbound_id'):
                updates.update({'status':'resolved','resolved_at':now_iso(),'admin_reply':reply_body})
            elif status!='sent':updates['status']='open'
            tx.update(ticket_ref,updates)
        result={'success':status=='sent','status':status,'message_id':message_ref.id}
        if status=='sent':result['gmail_message_id']=sent.get('id')
        return result,200 if status=='sent' else (503 if status=='not_sent' else 409)
    return finish(db().transaction())


@support_bp.post('/admin/support/<ticket_id>/reply')
@require_role('admin','super_admin')
def reply_support_ticket(ticket_id):
    try:
        payload=_payload()
        data,status=send_ticket_reply(ticket_id,payload.get('reply'),g.user_id,getattr(g,'user_email',''),
            getattr(g,'user_name',''),request.headers.get('Idempotency-Key'))
        return jsonify(data),status
    except ValueError as exc:return jsonify({'detail':str(exc)}),422


@support_bp.post('/admin/support/<ticket_id>/notes')
@require_role('admin','super_admin')
def add_internal_note(ticket_id):
    try:ticket_id=_id(ticket_id);text=_text(_payload().get('note'),'note')
    except ValueError as exc:return jsonify({'detail':str(exc)}),422
    ticket_ref=doc(SUPPORT_TICKETS,ticket_id);note_ref=col(SUPPORT_INTERNAL_NOTES).document()
    @firestore.transactional
    def add(tx):
        snap=ticket_ref.get(transaction=tx)
        if not snap.exists:return False
        tx.create(note_ref,{'uid':note_ref.id,'ticket_id':ticket_id,'admin_id':g.user_id,
            'admin_name':getattr(g,'user_name','Admin'),'note':text,'timestamp':now_iso()})
        return True
    if not add(db().transaction()):return jsonify({'detail':'Ticket not found'}),404
    return jsonify({'success':True,'note_id':note_ref.id}),200
