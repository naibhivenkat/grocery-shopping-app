"""Authenticated internal support journeys; strict transactions, no mail providers."""
import copy
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch
import unittest
from flask import Flask
import auth_utils
import db as storage
from routes import support, notifications
from test_core_routes import CoreStore


class InAppSupportTests(unittest.TestCase):
    def setUp(self):
        self.store = CoreStore()
        self.store.data = {
            ('users', 'customer'): {'role': 'customer', 'email': 'private@example.test', 'full_name': 'Customer'},
            ('users', 'other'): {'role': 'customer'}, ('users', 'vendor'): {'role': 'vendor'},
            ('users', 'service'): {'role': 'service'}, ('users', 'pending_vendor'): {'role': 'vendor', 'status': 'pending'},
            ('users', 'admin'): {'role': 'admin'}, ('users', 'suspended'): {'role': 'customer', 'is_suspended': True},
        }
        push = patch.object(support, 'deliver_push')
        self.push = push.start(); self.addCleanup(push.stop)
        self.gmail = MagicMock()
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.register_blueprint(support.support_bp)
        self.app.register_blueprint(notifications.notifications_bp)
        patches = [patch.object(storage, 'doc', self.store.doc),
            patch.object(auth_utils, 'decode_token', lambda token: {'sub': token, 'role': 'super_admin'}),
            patch.object(support, 'gmail_service', self.gmail),
            patch.object(support.firestore, 'transactional', self.store.transactional)]
        for module in (support, notifications):
            patches += [patch.object(module, 'doc', self.store.doc), patch.object(module, 'col', self.store.col),
                patch.object(module, 'db', lambda: self.store)]
        for item in patches:
            item.start(); self.addCleanup(item.stop)
        self.client = self.app.test_client()
        self.addCleanup(self.gmail.send_email.assert_not_called)
        self.addCleanup(self.gmail.find_sent_message.assert_not_called)

    def call(self, path, body=None, method='POST', user='customer', key='support-request-1'):
        headers = {'Authorization': f'Bearer {user}'} if user else {}
        if key is not None: headers['Idempotency-Key'] = key
        return self.client.open(path, method=method, json=body, headers=headers)

    def create(self, user='customer', key='support-request-1', **changes):
        return self.call('/support/tickets', {'subject': 'Order help', 'message': 'Please help with my order',
            'category': 'order', **changes}, user=user, key=key)

    def ticket(self):
        response = self.create()
        self.assertEqual(response.status_code, 201)
        return response.json['ticket_id']

    def values(self, collection):
        return [value for (name, _), value in self.store.data.items() if name == collection]

    def reply_admin(self, ticket, body='Here is the answer', key='admin-reply-1', user='admin'):
        return self.call(f'/admin/support/{ticket}/reply', {'reply': body}, user=user, key=key)

    def test_public_deletion_page_identifies_app_operator_and_safe_request_instructions(self):
        before = copy.deepcopy(self.store.data)
        response = self.call('/account-deletion', method='GET', user=None)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content_type.startswith('text/html'))
        page = response.get_data(as_text=True)
        for expected in ['ALL LOCAL', 'Swasthik Enterprises', 'support@alllocal.in',
            'Account deletion request', 'registered email address', 'account identifier',
            'password, OTP, or payment details', 'Help &amp; Support',
            'Request account &amp; data deletion', 'manually verified and processed',
            'account profile and contact details', 'uploaded avatar', 'which data is erased',
            'Legal, financial, order, transaction, and security records', 'retention period',
            'not an automatic erasure', 'https://alllocal.in/pages/privacy-policy.html']:
            self.assertIn(expected, page)
        self.assertIn('mailto:support@alllocal.in?subject=Account%20deletion%20request', page)
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn("form-action 'none'", response.headers['Content-Security-Policy'])
        self.assertEqual(self.store.data, before)
        self.gmail.send_email.assert_not_called()

    def test_creation_records_server_owner_internal_ticket_and_initial_message_atomically(self):
        response = self.create()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json['delivery_channel'], 'internal')
        self.assertEqual(response.json['status'], 'open')
        ticket = self.values('support_tickets')[0]
        self.assertEqual(ticket['customer_id'], 'customer')
        self.assertNotIn('customer_email', ticket)
        self.assertEqual(ticket['category'], 'order')
        message = self.values('support_messages')[0]
        self.assertEqual(message['sender_id'], 'customer')
        self.assertEqual(message['ticket_id'], response.json['ticket_id'])
        self.assertEqual(message['status'], 'recorded')
        self.assertEqual(self.values('notifications'), [])

    def test_replay_once_and_conflicting_subject_message_or_category_rejected(self):
        first = self.create(); before = copy.deepcopy(self.store.data)
        second = self.create()
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json['ticket_id'], second.json['ticket_id'])
        for field, value in [('subject', 'Another'), ('message', 'Different'), ('category', 'general')]:
            self.assertEqual(self.create(**{field: value}).status_code, 409)
        self.assertEqual(self.store.data, before)

    def test_same_key_for_different_accounts_never_shares_ticket(self):
        own = self.create(); other = self.create(user='other')
        self.assertEqual(other.status_code, 201)
        self.assertNotEqual(own.json['ticket_id'], other.json['ticket_id'])
        self.assertEqual(len(self.values('support_tickets')), 2)

    def test_missing_deleted_suspended_accounts_cannot_create_read_or_reply(self):
        ticket = self.ticket()
        for user, expected in [(None, 401), ('deleted', 401), ('suspended', 403)]:
            self.assertEqual(self.create(user=user).status_code, expected)
            self.assertEqual(self.call('/support/tickets', method='GET', user=user).status_code, expected)
            self.assertEqual(self.call(f'/support/tickets/{ticket}', method='GET', user=user).status_code, expected)
            self.assertEqual(self.call(f'/support/tickets/{ticket}/messages', {'message': 'Text'}, user=user).status_code, expected)
        self.assertEqual(len(self.values('support_tickets')), 1)

    def test_pending_vendor_customer_and_service_can_request_help_without_privilege(self):
        for user in ['customer', 'vendor', 'service', 'pending_vendor']:
            self.assertEqual(self.create(user=user).status_code, 201)
            self.assertEqual(len(self.call('/support/tickets', method='GET', user=user).json), 1)
            ticket = self.values('support_tickets')[-1]['uid']
            self.assertEqual(self.reply_admin(ticket, user=user).status_code, 403)

    def test_strict_payload_bounds_types_category_and_idempotency(self):
        for payload in [None, [], {}, {'subject': 'A', 'message': 'B', 'customer_id': 'other'},
            {'subject': 'A', 'message': 'B', 'delivery_channel': 'gmail'},
            {'subject': 'A', 'message': 'B', 'category': []}, {'subject': 'A', 'message': 'B', 'category': 'delete_now'},
            {'subject': 'x' * 161, 'message': 'B'}, {'subject': 'A', 'message': 'x' * 4001},
            {'subject': [], 'message': 'B'}, {'subject': 'A', 'message': True}, {'subject': ' ', 'message': 'B'},
            {'subject': 'A\nB', 'message': 'B'}, {'subject': 'A', 'message': 'Null\x00body'}]:
            self.assertEqual(self.call('/support/tickets', payload).status_code, 422, payload)
        for key in [None, '', 'short', ' ', 'x' * 129, 'with spaces', 'unicode_é']:
            self.assertEqual(self.create(key=key).status_code, 422, key)
        self.assertEqual(self.values('support_tickets'), [])
        self.assertEqual(self.values('support_messages'), [])

    def test_deletion_category_is_request_only_and_does_not_delete_account(self):
        before = copy.deepcopy(self.store.data[('users', 'customer')])
        response = self.create(category='account_deletion')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json['status'], 'open')
        self.assertEqual(self.store.data[('users', 'customer')], before)
        self.assertEqual(self.values('support_tickets')[0]['category'], 'account_deletion')

    def test_own_list_and_detail_whitelist_private_notes_email_headers_and_other_tickets(self):
        ticket = self.ticket(); self.create(user='other')
        self.store.data[('support_tickets', ticket)].update(customer_email='private@example.test',
            gmail_thread_id='provider-thread', admin_reply='private admin summary', send_request={'secret': 'private'})
        self.store.data[('support_internal_notes', 'private')] = {'ticket_id': ticket, 'note': 'Admin only'}
        first = self.values('support_messages')[0]
        first.update(admin_email='staff@example.test', send_request={'private': True}, gmail_message_id='private')
        self.store.data[('support_tickets', 'gmail-private')] = {'customer_id': 'customer', 'customer_email': 'private@example.test', 'subject': 'Private email', 'status': 'open'}
        listing = self.call('/support/tickets', method='GET')
        self.assertEqual(len(listing.json), 1)
        detail = self.call(f'/support/tickets/{ticket}', method='GET')
        self.assertEqual(len(detail.json['messages']), 1)
        for private in ['private@example.test', 'provider-thread', 'staff@example.test', 'Admin only', 'send_request', 'gmail_message_id', 'admin_reply', 'customer_id']:
            self.assertNotIn(private, listing.get_data(as_text=True))
            self.assertNotIn(private, detail.get_data(as_text=True))
        for user in ['other', 'vendor', 'admin']:
            self.assertEqual(self.call(f'/support/tickets/{ticket}', method='GET', user=user).status_code, 404)
        self.assertEqual(self.call('/support/tickets/gmail-private', method='GET').status_code, 404)

    def test_internal_admin_reply_records_reply_notification_audit_once_without_gmail(self):
        ticket = self.ticket()
        # Explicit internal channel wins even if an old email field later appears.
        self.store.data[('support_tickets', ticket)]['customer_email'] = 'private@example.test'
        first = self.reply_admin(ticket)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json['status'], 'recorded')
        self.assertEqual(first.json['delivery_channel'], 'internal')
        self.assertNotIn('gmail_message_id', first.json)
        notification = self.values('notifications')[0]
        self.assertEqual(notification['user_id'], 'customer')
        self.assertEqual(notification['type'], 'support_reply')
        self.assertEqual(notification['reference_id'], ticket)
        notification['is_read'] = True
        before = copy.deepcopy(self.store.data)
        replay = self.reply_admin(ticket)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json['delivery_channel'], 'internal')
        self.assertEqual(self.store.data, before)
        self.assertEqual(len(self.values('audit_logs')), 1)
        self.assertEqual(len(self.values('notifications')), 1)
        self.assertEqual(self.push.call_count, 1)
        self.assertEqual(self.push.call_args.args[0]['reference_id'], ticket)
        detail = self.call(f'/support/tickets/{ticket}', method='GET').json
        self.assertEqual(detail['status'], 'resolved')
        self.assertEqual(detail['messages'][-1]['bodyText'], 'Here is the answer')
        self.assertEqual(self.call('/notifications', method='GET').json[0]['type'], 'support_reply')
        self.assertEqual(self.call('/notifications', method='GET', user='other').json, [])

    def test_user_followup_reopens_once_and_replay_does_not_undo_later_admin_resolution(self):
        ticket = self.ticket(); self.reply_admin(ticket)
        path = f'/support/tickets/{ticket}/messages'
        body = {'message': 'I need more help'}
        reply = self.call(path, body, key='customer-message-1')
        self.assertEqual(reply.status_code, 201)
        self.assertEqual(self.store.data[('support_tickets', ticket)]['status'], 'open')
        self.assertIsNone(self.store.data[('support_tickets', ticket)]['resolved_at'])
        self.assertEqual(self.reply_admin(ticket, key='admin-reply-2').status_code, 200)
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.call(path, body, key='customer-message-1').status_code, 200)
        self.assertEqual(self.store.data, before)
        self.assertEqual(self.store.data[('support_tickets', ticket)]['status'], 'resolved')
        self.assertEqual(self.call(path, {'message': 'Altered'}, key='customer-message-1').status_code, 409)
        self.assertEqual(len(self.values('support_messages')), 4)
        self.assertEqual(len(self.values('notifications')), 2)

    def test_other_account_cannot_reopen_send_or_inject_actor_on_ticket(self):
        ticket = self.ticket(); before = copy.deepcopy(self.store.data)
        self.assertEqual(self.call(f'/support/tickets/{ticket}/messages', {'message': 'Forgery'}, user='other').status_code, 404)
        self.assertEqual(self.call('/support/tickets/missing/messages', {'message': 'Forgery'}).status_code, 404)
        for payload in [{'message': 'Hi', 'sender_id': 'admin'}, {'message': 'Hi', 'status': 'resolved'}, {'message': []}, {'message': ' '}]:
            self.assertEqual(self.call(f'/support/tickets/{ticket}/messages', payload).status_code, 422)
        self.assertEqual(self.store.data, before)

    def test_atomic_write_failures_leave_no_ticket_message_audit_notification_or_status_change(self):
        before = copy.deepcopy(self.store.data); self.store.fail_commit = True
        with self.assertRaises(RuntimeError): self.create()
        self.assertEqual(self.store.data, before)
        self.store.fail_commit = False; ticket = self.ticket()
        before = copy.deepcopy(self.store.data); self.store.fail_commit = True
        with self.assertRaises(RuntimeError): self.reply_admin(ticket)
        self.assertEqual(self.store.data, before)
        with self.assertRaises(RuntimeError): self.call(f'/support/tickets/{ticket}/messages', {'message': 'Followup'})
        self.assertEqual(self.store.data, before)

    def test_concurrent_same_ticket_and_admin_reply_commit_once(self):
        with ThreadPoolExecutor(max_workers=4) as workers:
            replies = list(workers.map(lambda _: self.create(), range(6)))
        self.assertEqual(sorted(reply.status_code for reply in replies), [200, 200, 200, 200, 200, 201])
        self.assertEqual(len(self.values('support_tickets')), 1)
        ticket = replies[0].json['ticket_id']
        with ThreadPoolExecutor(max_workers=4) as workers:
            replies = list(workers.map(lambda _: self.reply_admin(ticket), range(6)))
        self.assertTrue(all(reply.status_code == 200 for reply in replies))
        self.assertEqual(len(self.values('support_messages')), 2)
        self.assertEqual(len(self.values('notifications')), 1)
        self.assertEqual(len(self.values('audit_logs')), 1)


if __name__ == '__main__': unittest.main()
