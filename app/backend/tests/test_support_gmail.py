"""Support, notification and Gmail regressions; no external mail is sent."""
import base64
import copy
from datetime import datetime,timedelta,timezone
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
import unittest
from flask import Flask
from googleapiclient.errors import HttpError
import auth_utils
import db as storage
from routes import support,gmail_admin,notifications
import sync_service
from gmail_service import GmailService
from routes.gmail_auth import GmailAuthError
from test_core_routes import CoreStore

class SupportGmailTests(unittest.TestCase):
    def setUp(self):
        self.store=CoreStore()
        self.store.data={('users','admin'):{'role':'admin'},('users','customer'):{'role':'customer'},
            ('users','suspended'):{'role':'admin','is_suspended':True},
            ('support_tickets','ticket'):{'customer_email':'Customer <customer@example.test>','subject':'Help me',
                'gmail_thread_id':'thread','status':'open','last_inbound_message_id':'inbound','last_message_id_header':'<original@example.test>'}}
        self.gmail=MagicMock();self.gmail.send_email.return_value={'id':'sent'}
        self.gmail.find_sent_message.return_value=None
        self.gmail.get_profile.return_value={'historyId':'200','emailAddress':'support@example.test'}
        self.gmail.get_labels.return_value=[{'name':'Support','id':'label_support'}]
        self.gmail.list_messages.return_value=[];self.gmail.list_history.return_value=[]
        self.app=Flask(__name__);self.app.config['TESTING']=True
        for bp in (support.support_bp,gmail_admin.gmail_admin_bp,notifications.notifications_bp):self.app.register_blueprint(bp)
        patches=[patch.object(storage,'doc',self.store.doc),patch.object(auth_utils,'decode_token',lambda token:{'sub':token,'role':'admin'})]
        for module in (support,sync_service):
            patches.extend([patch.object(module,'doc',self.store.doc),patch.object(module,'col',self.store.col),
                patch.object(module,'db',lambda:self.store),patch.object(module.firestore,'transactional',self.store.transactional),
                patch.object(module,'gmail_service',self.gmail)])
        patches.extend([patch.object(gmail_admin,'gmail_service',self.gmail),patch.object(gmail_admin,'sync_service',sync_service.SyncService()),
            patch.object(notifications,'col',self.store.col),patch.object(notifications,'doc',self.store.doc),
            patch.object(notifications,'db',lambda:self.store),patch.object(CoreStore,'batch',lambda store:store.transaction(),create=True)])
        for p in patches:p.start();self.addCleanup(p.stop)
        self.client=self.app.test_client()
    def post(self,path,body,user='admin',key=None):
        headers={'Authorization':f'Bearer {user}'} if user else {}
        if key:headers['Idempotency-Key']=key
        return self.client.post(path,json=body,headers=headers)
    def reply(self,body=None,user='admin',key=None):return self.post('/admin/support/ticket/reply',body or {'reply':'Answer'},user,key)
    def test_support_and_gmail_require_current_admin_and_non_suspended_account(self):
        for user,status in [('customer',403),('suspended',403),('deleted',401),(None,401)]:
            self.assertEqual(self.reply(user=user).status_code,status)
            self.assertEqual(self.post('/admin/support/gmail/send',{'to':'x@example.test','subject':'Hello','body':'Body'},user).status_code,status)
        self.gmail.send_email.assert_not_called()
    def test_support_reply_sends_once_and_resolves_after_provider_acceptance(self):
        first=self.reply();second=self.reply()
        self.assertEqual(first.status_code,200);self.assertEqual(second.status_code,200)
        self.assertEqual(first.json['status'],'sent')
        self.assertEqual(first.json['message_id'],second.json['message_id'])
        self.gmail.send_email.assert_called_once()
        args=self.gmail.send_email.call_args.kwargs
        self.assertEqual(args['to'],'customer@example.test');self.assertEqual(args['in_reply_to'],'<original@example.test>')
        self.assertEqual(self.store.data[('support_tickets','ticket')]['status'],'resolved')
        self.assertEqual(len([k for k in self.store.data if k[0]=='audit_logs']),1)
    def test_ambiguous_send_requires_review_and_retry_only_reconciles_sent_mail(self):
        self.gmail.send_email.side_effect=TimeoutError('unknown')
        first=self.reply();second=self.reply()
        self.assertEqual(first.status_code,409);self.assertEqual(second.status_code,409)
        self.assertEqual(self.store.data[('support_tickets','ticket')]['status'],'open')
        self.gmail.send_email.assert_called_once()
        self.gmail.find_sent_message.return_value={'id':'found_sent'}
        third=self.reply();self.assertEqual(third.status_code,200)
        self.assertEqual(third.json['gmail_message_id'],'found_sent')
        self.gmail.send_email.assert_called_once()
    def test_missing_gmail_configuration_reports_not_sent_and_can_retry_after_configuration(self):
        self.gmail.send_email.side_effect=GmailAuthError('Missing Gmail configuration')
        self.assertEqual(self.reply().status_code,503)
        self.assertEqual(self.store.data[('support_tickets','ticket')]['status'],'open')
        self.gmail.send_email.side_effect=None
        self.assertEqual(self.reply().status_code,200)
        self.assertEqual(len([k for k in self.store.data if k[0]=='audit_logs']),1)
    def test_inbound_arriving_during_send_keeps_ticket_open(self):
        def send(**kwargs):
            self.store.data[('support_tickets','ticket')].update(status='open',last_inbound_message_id='new_inbound')
            return {'id':'sent'}
        self.gmail.send_email.side_effect=send
        self.assertEqual(self.reply().status_code,200)
        self.assertEqual(self.store.data[('support_tickets','ticket')]['status'],'open')
    def test_internal_ticket_is_explicitly_recorded_without_external_send(self):
        self.store.data[('support_tickets','ticket')].pop('customer_email')
        result=self.reply();self.assertEqual(result.status_code,200)
        self.assertEqual(result.json['delivery_channel'],'internal')
        self.assertEqual(result.json['status'],'recorded');self.gmail.send_email.assert_not_called()
    def test_reply_validation_idempotency_conflict_and_missing_ticket(self):
        for body in (['bad'],{'reply':[]},{'reply':' '},{'reply':'x'*4001}):
            self.assertEqual(self.reply(body).status_code,422)
        self.assertEqual(self.post('/admin/support/missing/reply',{'reply':'Answer'}).status_code,404)
        self.assertEqual(self.reply(key='stable-key').status_code,200)
        self.assertEqual(self.reply({'reply':'Different'},key='stable-key').status_code,422)
    def test_support_transaction_failure_does_not_send_or_fake_resolve(self):
        before=copy.deepcopy(self.store.data);self.store.fail_commit=True
        with self.assertRaises(RuntimeError):self.reply()
        self.assertEqual(before,self.store.data);self.gmail.send_email.assert_not_called()
    def test_webhook_decodes_pubsub_data_and_ignores_stale_history(self):
        with patch.dict(os.environ,{'WEBHOOK_SECRET':'secret','GMAIL_MAILBOX_EMAIL':'support@example.test'}):
            for history in ('200','100'):
                encoded=base64.urlsafe_b64encode(json.dumps({'emailAddress':'support@example.test','historyId':history}).encode()).decode()
                response=self.client.post('/admin/support/webhook',json={'message':{'data':encoded}},headers={'X-Webhook-Secret':'secret'})
                self.assertEqual(response.status_code,200)
            self.assertEqual(self.store.data[('support_sync','state')]['latest_history_id'],'200')
            self.assertEqual(self.client.post('/admin/support/webhook',json={'message':{'data':'***'}},headers={'X-Webhook-Secret':'secret'}).status_code,422)
            self.assertEqual(self.client.post('/admin/support/webhook',json={'message':{'historyId':'300','emailAddress':'wrong@example.test'}},headers={'X-Webhook-Secret':'secret'}).status_code,403)
    def test_webhook_without_secret_fails_closed(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(self.client.post('/admin/support/webhook',json={}).status_code,503)
    def test_sync_missing_cursor_bootstraps_and_persists_cursor(self):
        self.store.data[('support_sync','state')]={'latest_history_id':'200'}
        result=sync_service.SyncService().process_webhook_queue()
        self.assertEqual(result['status'],'idle');self.assertEqual(result['backfill_recent_limit'],100)
        self.assertEqual(self.store.data[('support_sync','state')]['last_processed_history_id'],'200')
        self.gmail.list_messages.assert_called_once_with('',100)
    def test_sync_requires_support_label_without_ingesting_private_mail(self):
        self.gmail.get_labels.return_value=[]
        with self.assertRaises(ValueError):sync_service.SyncService().process_webhook_queue()
        self.gmail.list_messages.assert_not_called()
        self.assertIsNone(self.store.data[('support_sync','state')]['sync_lease'])
    def test_sync_atomic_ingestion_deduplicates_repeated_message(self):
        self.gmail.get_message.return_value={'labelIds':['label_support']}
        self.gmail.parse_message.return_value={'threadId':'newthread','from':'x@example.test','subject':'Help','body_text':'Hi','message_id_header':'<mail@example.test>'}
        service=sync_service.SyncService()
        self.assertTrue(service._ingest_message('gmail_inbound','label_support'))
        self.assertFalse(service._ingest_message('gmail_inbound','label_support'))
        self.assertEqual(len([k for k in self.store.data if k[0]=='support_messages']),1)
        self.gmail.get_message.return_value={'labelIds':['SENT','label_support']}
        self.assertFalse(service._ingest_message('sent','label_support'))
    def test_history_page_failure_preserves_completed_record_cursor(self):
        self.store.data[('support_sync','state')]={'last_processed_history_id':'100'}
        def records(*args):
            yield {'id':'150','messagesAdded':[]}
            raise ValueError('Page limit reached')
        self.gmail.list_history.side_effect=records
        with self.assertRaises(ValueError):sync_service.SyncService().process_webhook_queue()
        self.assertEqual(self.store.data[('support_sync','state')]['last_processed_history_id'],'150')
    def test_expired_history_recovers_recent_support_mail_explicitly(self):
        self.store.data[('support_sync','state')]={'last_processed_history_id':'100'}
        self.gmail.list_history.side_effect=HttpError(SimpleNamespace(status=404,reason='expired'),b'{}')
        result=sync_service.SyncService().process_webhook_queue()
        self.assertEqual(result['backfill_recent_limit'],100)
        self.assertEqual(self.store.data[('support_sync','state')]['last_processed_history_id'],'200')
    def test_gmail_payload_and_attachment_validation_prevent_provider_send(self):
        for body in (['bad'],{'to':[]},{'to':'x@example.test','subject':'Hello','body':'Body','attachments':[{'name':'file','data':'***'}]},
            {'to':'x@example.test','subject':'Hello','body':'Body','attachments':[{'name':'../file','data':'aA=='}]},
            {'to':'x@example.test','subject':'Hello','body':'Body','attachments':[{'name':'file','data':'aA==','mime_type':'text/plain\r\nBad:yes'}]}):
            self.assertEqual(self.post('/admin/support/gmail/send',body).status_code,422)
        self.gmail.send_email.assert_not_called()
    def test_notifications_owner_check_and_chunked_bulk_read(self):
        self.store.data[('notifications','foreign')]={'user_id':'admin','is_read':False}
        self.assertEqual(self.post('/notifications/foreign/read',{},user='customer').status_code,403)
        for i in range(901):self.store.data[('notifications',f'n{i}')]={'user_id':'customer','is_read':False}
        result=self.post('/notifications/read-all',{},user='customer')
        self.assertEqual(result.status_code,200);self.assertEqual(result.json['updated'],901)
        self.assertFalse(self.store.data[('notifications','foreign')]['is_read'])
        self.assertEqual(self.post('/notifications/read-all',{},user='customer').json['updated'],0)

class GmailSdkTests(unittest.TestCase):
    def test_send_does_not_automatically_retry_and_preserves_thread_headers(self):
        api=MagicMock();service=GmailService();service._service=api
        api.users.return_value.messages.return_value.send.return_value.execute.return_value={'id':'sent'}
        service.send_email('customer@example.test','Subject','Body',thread_id='thread',in_reply_to='<original@example.test>',message_id_header='<unique@example.test>')
        send=api.users.return_value.messages.return_value.send
        send.return_value.execute.assert_called_once_with(num_retries=0)
        raw=base64.urlsafe_b64decode(send.call_args.kwargs['body']['raw']).decode()
        self.assertIn('In-Reply-To: <original@example.test>',raw)
        self.assertIn('Message-ID: <unique@example.test>',raw)
        self.assertEqual(send.call_args.kwargs['body']['threadId'],'thread')
    def test_header_injection_is_rejected_before_api(self):
        service=GmailService();service._service=MagicMock()
        with self.assertRaises(ValueError):service.send_email('customer@example.test','Hello\r\nBcc: other@example.test','Body')
        service._service.users.assert_not_called()
    def test_history_follows_next_page_token(self):
        service=GmailService();api=MagicMock();service._service=api
        listing=api.users.return_value.history.return_value.list
        listing.return_value.execute.side_effect=[{'history':[{'id':'1'}],'nextPageToken':'next'},{'history':[{'id':'2'}]}]
        self.assertEqual(list(service.list_history('0','support')), [{'id':'1'},{'id':'2'}])
        self.assertEqual(listing.call_args.kwargs['pageToken'],'next')
        self.assertEqual(listing.call_args.kwargs['labelId'],'support')

if __name__=='__main__':unittest.main()
