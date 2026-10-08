"""Bounded Gmail Support-label sync, resumable cursors and atomic ingestion."""
import hashlib
import uuid
from datetime import datetime,timedelta,timezone
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from googleapiclient.errors import HttpError
from db import SUPPORT_MESSAGES,SUPPORT_SYNC,SUPPORT_TICKETS,col,doc,db,now_iso
from gmail_service import gmail_service


class SyncService:
    def process_webhook_queue(self):
        state_ref=doc(SUPPORT_SYNC,'state');lease=uuid.uuid4().hex
        @firestore.transactional
        def acquire(tx):
            snap=state_ref.get(transaction=tx);state=snap.to_dict() or {}
            if state.get('sync_lease'):
                try:
                    started=datetime.fromisoformat(state.get('sync_started_at') or '')
                    if started>datetime.now(timezone.utc)-timedelta(minutes=5):return None
                except (ValueError,TypeError):pass
            tx.set(state_ref,{'sync_lease':lease,'sync_started_at':now_iso(),'status':'syncing'},merge=True)
            return state
        state=acquire(db().transaction())
        if state is None:return {'ingested':0,'status':'syncing'}
        def checkpoint(cursor,status='syncing'):
            @firestore.transactional
            def save(tx):
                snap=state_ref.get(transaction=tx);current=snap.to_dict() or {}
                if current.get('sync_lease')!=lease:raise ValueError('Synchronization lease changed')
                tx.set(state_ref,{'last_processed_history_id':str(cursor),'status':status,'last_sync_time':now_iso()},merge=True)
            save(db().transaction())
        ingested=0;backfill=False;cursor=state.get('last_processed_history_id')
        try:
            labels=gmail_service.get_labels()
            support_label=next((item.get('id') for item in labels if item.get('name')=='Support'),None)
            if not support_label:raise ValueError('Create the Support label in the configured Gmail mailbox')
            profile=gmail_service.get_profile()
            latest=str(profile.get('historyId') or '')
            if not latest.isdigit():raise ValueError('Gmail profile has no valid history cursor')
            def bootstrap():
                count=0
                # Snapshot the cursor first; subsequent arrivals are collected
                # by history sync even if they race this bounded initial scan.
                for item in gmail_service.list_messages('',100):
                    if item.get('id') and self._ingest_message(item['id'],support_label):count+=1
                checkpoint(latest)
                return count
            if not cursor:
                ingested=bootstrap();cursor=latest;backfill=True
            else:
                try:
                    for record in gmail_service.list_history(str(cursor),support_label):
                        for wrapper in record.get('messagesAdded',[]) or []:
                            message_id=(wrapper.get('message') or {}).get('id')
                            if message_id and self._ingest_message(message_id,support_label):ingested+=1
                        record_id=str(record.get('id') or '')
                        if record_id.isdigit():checkpoint(record_id);cursor=record_id
                    # listHistory can return beyond profile's initial cursor;
                    # never move a completed checkpoint backwards.
                    cursor=str(max(int(cursor),int(latest)));checkpoint(cursor)
                except HttpError as exc:
                    if getattr(exc.resp,'status',None)!=404:raise
                    ingested+=bootstrap();cursor=latest;backfill=True
        except Exception:
            @firestore.transactional
            def fail(tx):
                snap=state_ref.get(transaction=tx);current=snap.to_dict() or {}
                if current.get('sync_lease')==lease:
                    tx.set(state_ref,{'sync_lease':None,'status':'sync_failed','last_sync_time':now_iso()},merge=True)
            fail(db().transaction());raise
        @firestore.transactional
        def finish(tx):
            snap=state_ref.get(transaction=tx);current=snap.to_dict() or {}
            if current.get('sync_lease')!=lease:raise ValueError('Synchronization lease changed')
            notified=str(current.get('latest_history_id') or '0')
            status='pending_sync' if notified.isdigit() and int(notified)>int(cursor) else 'idle'
            tx.set(state_ref,{'sync_lease':None,'status':status,'last_sync_time':now_iso(),
                'bootstrap_recent_limit':100 if backfill else current.get('bootstrap_recent_limit'),
                'mailbox_email':profile.get('emailAddress')},merge=True)
            return status
        result={'ingested':ingested,'status':finish(db().transaction())}
        if backfill:result['backfill_recent_limit']=100
        return result

    def _ingest_message(self,message_id,support_label=None):
        raw=gmail_service.get_message(message_id,'full')
        labels=raw.get('labelIds') or []
        if 'SENT' in labels or 'DRAFT' in labels or (support_label and support_label not in labels):return False
        parsed=gmail_service.parse_message(raw);thread_id=parsed.get('threadId')
        if not isinstance(thread_id,str) or not thread_id or '/' in thread_id:raise ValueError('Invalid Gmail thread')
        existing=next(iter(col(SUPPORT_TICKETS).where(filter=FieldFilter('gmail_thread_id','==',thread_id)).stream()),None)
        ticket_id=existing.id if existing else 'gmail_'+hashlib.sha256(thread_id.encode()).hexdigest()[:40]
        ticket_ref=doc(SUPPORT_TICKETS,ticket_id);message_ref=doc(SUPPORT_MESSAGES,message_id)
        @firestore.transactional
        def ingest(tx):
            message_snap=message_ref.get(transaction=tx);ticket_snap=ticket_ref.get(transaction=tx)
            if message_snap.exists:return False
            timestamp=now_iso()
            if not ticket_snap.exists:
                tx.create(ticket_ref,{'uid':ticket_id,'gmail_thread_id':thread_id,'subject':parsed.get('subject') or 'No Subject',
                    'customer_email':parsed.get('reply_to') or parsed.get('from') or '', 'status':'open',
                    'created_at':timestamp,'updated_at':timestamp,'last_inbound_message_id':message_id,
                    'last_message_id_header':parsed.get('message_id_header')})
            else:
                tx.update(ticket_ref,{'status':'open','updated_at':timestamp,'last_inbound_message_id':message_id,
                    'last_message_id_header':parsed.get('message_id_header')})
            tx.create(message_ref,{'uid':message_id,'ticket_id':ticket_id,'direction':'inbound','from':parsed.get('from'),
                'to':parsed.get('to'),'subject':parsed.get('subject'),'bodyText':parsed.get('body_text'),
                'bodyHtml':parsed.get('body_html'),'internal_date':timestamp,'gmail_internal_date':parsed.get('internal_date'),
                'status':'received','message_id_header':parsed.get('message_id_header')})
            return True
        return ingest(db().transaction())

sync_service=SyncService()
