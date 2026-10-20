"""Transport and coverage guards for verification scripts, without provider calls."""
import importlib.util
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest
from unittest.mock import patch


def load(name):
    path=Path(__file__).resolve().parents[1]/'scripts'/(name+'.py')
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


emulator=load('verify_emulator_journeys')
deployed=load('verify_deployed')


class VerificationTransportTests(unittest.TestCase):
    def setUp(self):
        self.requests=[]
        captured=self.requests
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=self.rfile.read(int(self.headers.get('Content-Length','0')))
                captured.append((self.path,self.headers,body))
                self.send_response(201);self.send_header('Content-Type','application/json');self.end_headers()
                self.wfile.write(b'{"count":1}')
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type','application/pdf' if self.path=='/valid.pdf' else 'text/plain')
                self.end_headers();self.wfile.write(b'%PDF-1.4\nfixture')
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.report={'checks':[]}
        self.api=emulator.Http('http://127.0.0.1:'+str(self.server.server_port),self.report)

    def test_real_multipart_http_preserves_binary_workbook_and_authorization(self):
        contents=b'PK\x03\x04\x00\xff\r\nactual workbook fixture bytes'
        result=self.api.call('XLSX upload','POST','/import?preview=true',token='local-token',expected=201,
            files={'file':('products.xlsx',contents,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
        self.assertEqual(result,{'count':1})
        path,headers,body=self.requests[0]
        self.assertEqual(path,'/import?preview=true')
        self.assertEqual(headers['Authorization'],'Bearer local-token')
        self.assertTrue(headers['Content-Type'].startswith('multipart/form-data; boundary='))
        self.assertIn(b'name="file"; filename="products.xlsx"',body)
        self.assertIn(contents,body)
        self.assertTrue(all(item['passed'] for item in self.report['checks']))

    def test_pdf_response_checks_mime_as_well_as_signature(self):
        self.assertTrue(self.api.call('PDF','GET','/valid.pdf',response_format='pdf').startswith(b'%PDF-'))
        with self.assertRaises(AssertionError):
            self.api.call('Invalid MIME','GET','/invalid.pdf',response_format='pdf')
        self.assertFalse(self.report['checks'][-1]['passed'])

    def test_multipart_headers_reject_injection(self):
        with self.assertRaises(ValueError):
            emulator.multipart_files({'file':('products.csv\r\nInjected: true',b'a','text/csv')})


class DeployedCoverageTests(unittest.TestCase):
    def test_ast_discovers_stacked_aliases_and_multi_method_routes(self):
        source='''
@bp.get("/first/<id>")
@bp.get("/alias/<id>")
@require_role("vendor")
def first(id): pass

@bp.route("/device", methods=["POST", "DELETE"])
@require_auth
def device(): pass

@bp.post("/public")
def public(): pass
'''
        self.assertEqual(set(deployed.protected_routes(source)),{
            ('GET','/first/<id>'),('GET','/alias/<id>'),('POST','/device'),('DELETE','/device')})

    def test_release_coverage_includes_every_new_protected_endpoint(self):
        cases=set(deployed.cases(True))
        expected={('GET','/orders/__verification__/invoice',401),
            ('GET','/orders/__verification__/invoice.pdf',401),
            ('PUT','/vendors/orders/__verification__/discount',401),
            ('POST','/vendors/items/import',401),('GET','/vendors/items/import/template',401),
            ('POST','/khata/transactions/__verification__/approve',401),
            ('POST','/khata/transactions/__verification__/reject',401),
            ('POST','/vendors/orders/__verification__/payment/confirm',401),
            ('POST','/notifications/device-token',401),('DELETE','/notifications/device-token',401),
            ('GET','/subscriptions/entitlements',401),('GET','/subscriptions/requests',401),
            ('POST','/subscriptions/requests',401),('GET','/admin/subscription-plans',401),
            ('GET','/admin/subscriptions',401),('GET','/admin/subscription-requests',401),
            ('GET','/admin/subscriptions/rollout',401),('POST','/admin/subscriptions/rollout',401),
            ('POST','/admin/vendors/__verification__/subscription/reconciliation',401),
            ('POST','/subscriptions/google-play/checkout-context',401),('POST','/subscriptions/google-play/verify',401),
            ('POST','/admin/subscriptions/google-play/reconcile',401),
            ('POST','/webhooks/google-play/rtdn',503)}
        self.assertTrue(expected.issubset(cases),expected-cases)
        self.assertEqual(len(deployed.cases(True)),len(cases))

    def test_rtdn_configuration_boundary_is_explicit_and_never_authenticated(self):
        self.assertIn(('POST','/webhooks/google-play/rtdn',503),deployed.cases(True))
        self.assertIn(('POST','/webhooks/google-play/rtdn',401),deployed.cases(True,'configured'))
        class Response:
            def __init__(self,status,code):self.status,self.code=status,code
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps({'code':self.code}).encode()
        for status,code,expected,okay in ((503,'BILLING_NOT_CONFIGURED',503,True),
                (401,'BILLING_PUSH_UNAUTHORIZED',401,True),(503,'INTERNAL_ERROR',503,False),
                (401,'BILLING_NOT_CONFIGURED',401,False)):
            with self.subTest(status=status,code=code),patch.object(deployed,'urlopen',return_value=Response(status,code)) as send:
                result=deployed.check('https://example.invalid','POST','/webhooks/google-play/rtdn',expected)
                self.assertEqual(result['ok'],okay)
                self.assertIsNone(send.call_args.args[0].get_header('Authorization'))

    def test_feature_contract_rejects_invalid_shapes_and_changed_payment_policy(self):
        class Response:
            status=200
            def __init__(self,data):self.data=data
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps(self.data).encode()
        for data,okay in ((dict(deployed.EXPECTED_FEATURES),True),([],False),
            ({**deployed.EXPECTED_FEATURES,'khata_vendor_confirmed':False},False),
            ({**deployed.EXPECTED_FEATURES,'wallet_enabled':0},False),
            ({**deployed.EXPECTED_FEATURES,'promotion_billing':'paid'},False)):
            with self.subTest(data=data),patch.object(deployed,'urlopen',return_value=Response(data)):
                self.assertEqual(deployed.check('http://127.0.0.1:1','GET','/features',200)['ok'],okay)


if __name__=='__main__':unittest.main()
