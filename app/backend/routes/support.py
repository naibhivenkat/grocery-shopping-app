"""Authorized Support Center with durable send identity and honest mail status."""
import base64
import binascii
import hashlib
import json
import os
from datetime import datetime,timedelta,timezone
from email.utils import parseaddr
import re
from flask import Blueprint,g,jsonify,request
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from auth_utils import require_role,require_webhook_secret
from db import SUPPORT_INTERNAL_NOTES,SUPPORT_MESSAGES,SUPPORT_SYNC,SUPPORT_TICKETS,AUDIT_LOGS,col,doc,db,now_iso,to_dict
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
            return {'skip':True,'status':existing['status'],'message_id':message_id,'gmail_message_id':existing.get('gmail_message_id')}
        if existing.get('status') in {'sending','requires_review'}:
            if existing.get('status')=='sending':
                try:
                    started=datetime.fromisoformat(existing.get('send_started_at') or '')
                    if started>datetime.now(timezone.utc)-timedelta(minutes=5):
                        return {'skip':True,'status':'sending','message_id':message_id}
                except (ValueError,TypeError):pass
            return {'reconcile':True,'message_id':message_id,'request':existing.get('send_request') or {},'inbound_id':existing.get('inbound_id')}
        recipient=ticket.get('customer_email')
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
        timestamp=now_iso()
        tx.set(message_ref,{'uid':message_id,'ticket_id':ticket_id,'direction':'outbound','bodyText':reply_body,
            'internal_date':timestamp,'admin_id':actor_id,'admin_name':actor_name,'delivery_channel':channel,
            'status':'sending' if channel=='gmail' else 'recorded','send_started_at':timestamp,'send_request':original,
            'inbound_id':ticket.get('last_inbound_message_id')})
        tx.update(ticket_ref,{'status':'pending_reply' if channel=='gmail' else 'resolved','updated_at':timestamp,
            'last_reply_status':'sending' if channel=='gmail' else 'recorded',
            **({'admin_reply':reply_body,'resolved_at':timestamp} if channel=='internal' else {})})
        if not message_snap.exists:
            tx.create(doc(AUDIT_LOGS,message_id),{'admin_id':actor_id,'admin_email':actor_email,'action':'Reply to Ticket',
                'target_id':ticket_id,'target_type':'support_ticket','created_at':timestamp})
        return {'message_id':message_id,'request':original,'channel':channel,'inbound_id':ticket.get('last_inbound_message_id')}
    acquired=acquire(db().transaction())
    if acquired.get('missing'):return {'detail':'Ticket not found'},404
    if acquired.get('skip'):
        status=acquired['status']
        return {'success':status in {'sent','recorded'},'status':status,'message_id':acquired['message_id']},202 if status=='sending' else 200
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
