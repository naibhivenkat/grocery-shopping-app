#!/usr/bin/env python3
"""Actual Flask HTTP + Firestore emulator subscription enforcement proof.

Requires a fresh demo- project and loopback emulator. No provider credentials,
production users, messages, purchases or payments. Dates use an explicit test
clock to exercise boundaries without modifying immutable grant documents.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import threading
import tempfile
import subprocess
import uuid
from verify_emulator_journeys import guard_environment, isolate_environment, Http


def run(output, flutter_bin=None, mobile_root=None):
    project = guard_environment(os.environ)
    isolate_environment(project)
    from db import col, doc
    from auth_utils import create_token
    import subscription_service as service
    from main import app
    from werkzeug.serving import make_server
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    report = {'environment': 'loopback Flask HTTP and actual Firestore emulator', 'project_id': project,
              'provider_calls': 0, 'production_business_mutations': 0, 'test_clock': True, 'checks': []}
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    api = Http('http://127.0.0.1:' + str(server.server_port), report)
    suffix = uuid.uuid4().hex[:10]
    ids = {name: name + '_' + suffix for name in ('admin', 'vendor', 'other', 'customer')}
    for name, identifier in ids.items():
        doc('users', identifier).set({'role': 'vendor' if name in {'vendor','other'} else name,
            'full_name': name.title() + ' fixture', 'shop_name': name.title() + ' isolated shop',
            'is_suspended': False, 'email': name + '@example.invalid'})
    for name in ('vendor','other'):
        account = service._empty_account(ids[name])
        account['usage'].update(initialized=True, reconciliation_id='isolated-fixture')
        doc(service.ACCOUNTS, ids[name]).set(account)
    doc(service.SETTINGS, 'control').set({'phase':'enforced','enforcement_enabled':True,'revision':1})
    tokens = {name:create_token(identifier,'vendor' if name in {'vendor','other'} else name) for name,identifier in ids.items()}
    call = api.call
    def key(): return 'journey-' + uuid.uuid4().hex
    def ent(name='vendor'):
        return call('vendor reads authoritative capabilities','GET','/subscriptions/entitlements',token=tokens[name])
    def action(kind, **extra):
        state=ent()
        return call('admin '+kind,'POST','/admin/vendors/'+ids['vendor']+'/subscription',
                    {'action':kind,'expected_account_revision':state['revision'],'reason':'Isolated proof '+kind,**extra},tokens['admin'],key=key())
    try:
        call('anonymous plan management denied','GET','/admin/subscription-plans',expected=401)
        call('vendor plan management denied','GET','/admin/subscription-plans',token=tokens['vendor'],expected=403)
        call('customer subscription access denied','GET','/subscriptions/entitlements',token=tokens['customer'],expected=403)
        body={'name':'Emulator Basic','description':'Isolated test plan','price_paise':0,'duration_days':30,
              'trial_days':7,'grace_days':3,'renewal_rule':'manual','is_active':True,'is_visible':True,
              'entitlements':{'max_items':2,'catalog_growth':True,'product_import':True,'promotions':False},'reason':'Isolated plan creation'}
        create_key=key()
        plan=call('admin creates plan','POST','/admin/subscription-plans',body,tokens['admin'],201,create_key)
        replay=call('plan creation retry','POST','/admin/subscription-plans',body,tokens['admin'],201,create_key)
        api.assertion('duplicate plan create has one identity',plan['uid']==replay['uid'])
        version=plan['current_version_id']; plan_id=plan['uid']
        state=ent()
        request=call('vendor requests exact plan terms','POST','/subscriptions/requests',{'plan_id':plan_id,'plan_version_id':version,
            'request_kind':'subscription','expected_account_revision':state['revision']},tokens['vendor'],201,key())
        request=request.get('request',request)
        api.assertion('request alone grants no access',not ent()['capabilities']['catalog_growth'])
        call('vendor cannot self approve','POST','/admin/subscription-requests/'+request['uid']+'/decision',
            {'decision':'approved','revision':request['revision'],'expected_account_revision':ent()['revision'],'reason':'Unauthorized'},tokens['vendor'],403,key())
        call('foreign vendor cannot cancel request','POST','/subscriptions/requests/'+request['uid']+'/cancel',
            {'revision':request['revision'],'expected_account_revision':ent('other')['revision']},tokens['other'],404,key())
        call('admin approves free request','POST','/admin/subscription-requests/'+request['uid']+'/decision',
            {'decision':'approved','revision':request['revision'],'expected_account_revision':ent()['revision'],'reason':'Verified isolated request'},tokens['admin'],key=key())
        active=ent(); api.assertion('admin approval changes actual vendor capabilities',active['status']=='active' and active['capabilities']['catalog_growth'])
        api.assertion('free access is not a received payment',active['payment_state'] in {'not_required','not_charged'})
        updated=call('admin changes future plan limits','PUT','/admin/subscription-plans/'+plan_id,
            {'revision':plan['revision'],'reason':'Future version only','entitlements':{'max_items':5,'catalog_growth':True,'product_import':True,'promotions':True}},tokens['admin'],key=key())
        old=ent();api.assertion('historical grant retains old limits and features',old['plan_version_id']==version and old['usage']['max_items']==2 and not old['capabilities']['promotions'])
        product={'name':'Isolated rice','description':'Fixture','price':5,'category':'Groceries','stock_quantity':0,'is_available':False}
        call('unavailable product consumes quota','POST','/vendors/items',product,tokens['vendor'],201)
        def racing(i):
            local=Http(api.base,report)
            try:return local.call('concurrent quota insertion '+str(i),'POST','/vendors/items',{**product,'name':'Race '+str(i)},tokens['vendor'],201)
            except AssertionError:return None
        with ThreadPoolExecutor(max_workers=2) as executor: results=list(executor.map(racing,[1,2]))
        # Capture expected conflict statuses without counting an expected denial as a failure.
        races=[row for row in report['checks'] if row.get('label','').startswith('concurrent quota insertion')]
        api.assertion('only one concurrent insertion fits last slot',sorted(row['status'] for row in races)==[201,409])
        for row in races: row['passed']=row['status'] in {201,409}
        api.assertion('quota count exactly matches persisted catalog',ent()['usage']['product_count']==2 and len(list(col('shop_items').where('vendor_id','==',ids['vendor']).stream()))==2)
        action('suspend')
        api.assertion('admin suspension visible in vendor HTTP response',ent()['status']=='suspended')
        call('suspended catalog growth denied','POST','/vendors/items',product,tokens['vendor'],403)
        call('suspended vendor retains order history','GET','/vendors/orders',token=tokens['vendor'])
        call('suspended vendor retains Khata history','GET','/khata/ledgers',token=tokens['vendor'])
        action('reactivate');api.assertion('reactivation returns current valid grant',ent()['status']=='active')
        saved_now=service._now
        grant=doc(service.GRANTS,ent()['current_grant_id']).get().to_dict()
        end=datetime.fromisoformat(grant['ends_at'])
        service._now=lambda:end+timedelta(days=1)
        api.assertion('frozen grace period applies at expiry',ent()['status']=='grace')
        service._now=lambda:end+timedelta(days=4)
        api.assertion('past grace access expires without deleting products',ent()['status']=='expired' and ent()['usage']['product_count']==2)
        service._now=saved_now
        history=call('admin reads immutable subscription history','GET','/admin/vendors/'+ids['vendor']+'/subscription',token=tokens['admin'])
        api.assertion('history includes retained grant page',bool(history['history']['items']))
        current_plan=call('admin reads latest plan','GET','/admin/subscription-plans/'+plan_id,token=tokens['admin'])
        call('referenced plan cannot be deleted','DELETE','/admin/subscription-plans/'+plan_id,
            {'revision':current_plan['revision'],'reason':'Proof deletion denied'},tokens['admin'],409,key())
        archived=call('admin archives referenced plan','POST','/admin/subscription-plans/'+plan_id+'/archive',
            {'revision':current_plan['revision'],'reason':'Archive proof'},tokens['admin'],key=key())
        visible=call('vendor loads available plans','GET','/subscriptions/plans',token=tokens['vendor'])
        api.assertion('archived plan hidden while current historical access persists',not any(p['uid']==plan_id for p in visible) and ent()['status']=='active')
        audits=list(col('audit_logs').where('vendor_id','==',ids['vendor']).stream())
        api.assertion('administrative audit records actor reason timestamp before after',any((a.to_dict() or {}).get('actor_id')==ids['admin'] and (a.to_dict() or {}).get('reason') and 'before' in (a.to_dict() or {}) and 'after' in (a.to_dict() or {}) for a in audits))
        if flutter_bin and mobile_root:
            with tempfile.TemporaryDirectory(prefix='alllocal-subscription-client-') as fixture_dir:
                fixture_path=Path(fixture_dir)/'emulator-fixture.json'
                fixture_path.write_text(json.dumps({'base_url':api.base,'project_id':project,'vendor_id':ids['vendor'],
                    'vendor_token':tokens['vendor'],'admin_token':tokens['admin']}))
                fixture_path.chmod(0o600)
                result=subprocess.run([flutter_bin,'test','--no-pub','--dart-define=SUBSCRIPTION_HTTP_PROOF_FIXTURE='+str(fixture_path),
                    'test/integration/vendor_subscription_http_test.dart','--reporter','expanded'],cwd=mobile_root,
                    capture_output=True,text=True,timeout=180)
                # This fixture contains only synthetic emulator tokens. Never print it.
                Path(output).with_suffix('.flutter.log').write_text(result.stdout+result.stderr)
                api.assertion('actual active Flutter subscription service HTTP journey',result.returncode==0)
                report['active_flutter_client_executed']=True
        try:
            collection=Path(mobile_root or Path(__file__).resolve().parents[5])/'postman/collections/vendor-subscriptions'
            if collection.exists():
                command=['postman','collection','run',str(collection),'--env-var','base_url='+api.base,'--no-report-events']
            else:
                command=['postman','request',api.base+'/subscriptions/plans','--no-report-events','--script-post-request',
                    'pm.test("available plans are served as an array", function () { pm.response.to.have.status(200); pm.expect(pm.response.json()).to.be.an("array"); });']
            result=subprocess.run(command,capture_output=True,text=True,timeout=45)
            Path(output).with_suffix('.postman.log').write_text(result.stdout+result.stderr)
            api.assertion('Postman actual HTTP subscription contract assertions',result.returncode==0)
            report['postman_executed']=True
        except FileNotFoundError:
            report['postman_executed']=False
        report['passed']=all(item['passed'] for item in report['checks'])
    finally:
        server.shutdown();thread.join(timeout=5);server.server_close()
        report['server_stopped']=not thread.is_alive()
        report['check_count']=len(report['checks'])
        Path(output).write_text(json.dumps(report,indent=2)+'\n')
    if not report.get('passed'):raise AssertionError('Subscription journey did not pass')
    print(json.dumps({'passed':True,'checks':report['check_count'],'provider_calls':0,'server_stopped':report['server_stopped']}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    parser.add_argument('--flutter-bin');parser.add_argument('--mobile-root')
    args=parser.parse_args();run(args.output,args.flutter_bin,args.mobile_root)
