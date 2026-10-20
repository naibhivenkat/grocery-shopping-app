#!/usr/bin/env python3
"""Real HTTP/Firestore proof of fenced migration, cutover and reference races.

Fresh loopback emulator and fresh demo- project only. No provider credentials,
production data, email, store purchase, charge or refund is used.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import threading
import uuid
from verify_emulator_journeys import guard_environment, isolate_environment, Http


def run(output):
    project = guard_environment(os.environ)
    isolate_environment(project)
    from auth_utils import create_token
    from db import col, doc
    import subscription_service as service
    from main import app
    from werkzeug.serving import make_server
    # Refuse to alter even another demo run's singleton rollout state.
    if doc(service.SETTINGS, 'control').get().exists or list(col('users').limit(1).stream()):
        raise ValueError('Migration proof requires a fresh empty demo project')
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    report = {'environment':'actual Firestore emulator and loopback Flask HTTP', 'project_id':project,
              'emulator_host':os.environ['FIRESTORE_EMULATOR_HOST'], 'provider_calls':0,
              'production_business_mutations':0, 'checks':[]}
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    api = Http('http://127.0.0.1:' + str(server.server_port), report)
    suffix = uuid.uuid4().hex[:8]
    ids = {name:name+'_'+suffix for name in ('admin','vendor','other','race','customer','later')}
    cutoff = datetime.now(timezone.utc)
    for name, identifier in ids.items():
        role = 'super_admin' if name == 'admin' else 'vendor' if name in {'vendor','other','race'} else 'customer'
        doc('users',identifier).set({'role':role,'full_name':'Isolated '+name,'shop_name':'Fixture '+name,
            'email':name+'@example.invalid','created_at':cutoff-timedelta(days=20) if name == 'vendor' else (cutoff-timedelta(days=20)).isoformat()})
    tokens = {name:create_token(identifier,'super_admin' if name == 'admin' else 'vendor' if name in {'vendor','other','race'} else 'customer') for name,identifier in ids.items()}
    for number in range(3):
        doc('shop_items','retained_'+str(number)).set({'vendor_id':ids['vendor'],'name':'Retained '+str(number),
            'price':5,'stock_quantity':0 if number<2 else 4,'is_available':False if number<2 else True})
    legacy = {'vendor_id':ids['vendor'],'status':'active','payment_status':'paid','price':999,'plan_id':'old_untrusted'}
    doc('vendor_subscriptions','historical').set(legacy)
    call=api.call
    def key(): return 'migration-'+uuid.uuid4().hex
    def ent(name='vendor'):
        return call(name+' reads authoritative access','GET','/subscriptions/entitlements',token=tokens[name])
    def reconcile_path(name): return '/admin/vendors/'+ids[name]+'/subscription/reconciliation'
    def step(name, action, **extra):
        return call(name+' reconciliation '+action,'POST',reconcile_path(name),
                    {'action':action,'reason':'Isolated migration proof',**extra},tokens['admin'],201 if action=='start' else 200,key())
    def scan_finish(name, job):
        while job['status']=='scanning':
            job=step(name,'scan',job_id=job['uid'],revision=job['revision'],limit=1)
        return step(name,'finish',job_id=job['uid'],revision=job['revision'])
    def reconcile(name):
        return scan_finish(name,step(name,'start',expected_account_revision=ent(name)['revision']))
    def create_plan(label):
        return call('create '+label+' plan','POST','/admin/subscription-plans',{'name':label,'description':'Fixture',
            'price_paise':0,'duration_days':30,'trial_days':7,'grace_days':0,'renewal_rule':'manual',
            'entitlements':{'max_items':5,'catalog_growth':True,'product_import':True,'promotions':True},
            'reason':'Isolated reviewed plan'},tokens['admin'],201,key())
    def assign(name, plan, expected_revision=None):
        revision=ent(name)['revision'] if expected_revision is None else expected_revision
        return call(name+' admin free assignment','POST','/admin/vendors/'+ids[name]+'/subscription',
            {'action':'assign','kind':'free','plan_id':plan['uid'],'plan_version_id':plan['current_version_id'],
             'expected_account_revision':revision,'reason':'Isolated explicit access grant'},tokens['admin'],key=key())
    def parallel(functions):
        # Http records actual statuses even on expected racing conflicts.
        with ThreadPoolExecutor(max_workers=len(functions)) as executor:
            futures=[executor.submit(fn) for fn in functions]
            results=[]
            for future in futures:
                try: results.append(future.result())
                except AssertionError: results.append(None)
            return results
    def accept_races(prefix, allowed):
        rows=[row for row in report['checks'] if row.get('label','').startswith(prefix)]
        for row in rows: row['passed']=row.get('status') in allowed
        api.assertion(prefix+' expected HTTP statuses',bool(rows) and all(row['passed'] for row in rows))
        return rows
    try:
        prepared=call('prepare explicit immutable cutoff','POST','/admin/subscriptions/rollout',
            {'action':'prepare','revision':0,'cutoff_at':cutoff.isoformat(),'reason':'Reviewed initial vendor cohort'},tokens['admin'],key=key())
        api.assertion('preparing does not enable enforcement',prepared['phase']=='preparing' and not prepared['enforcement_enabled'])
        operations_before=len(list(col(service.OPERATIONS).stream()))
        dry=step('vendor','dry_run',expected_account_revision=0,limit=2)
        api.assertion('native Firestore timestamp normalizes into reviewed legacy cohort',dry['cohort_date_status']=='valid'
            and dry['cohort_basis']=='validated_created_at' and not dry['cohort_review_required'])
        api.assertion('dry run bounded and writes no operation/account/grant',dry['would_grant_legacy'] and dry['observed_product_count']==2
            and not dry['product_count_is_complete'] and len(list(col(service.OPERATIONS).stream()))==operations_before
            and not doc(service.ACCOUNTS,ids['vendor']).get().exists)
        call('uncovered cohort cannot enable','POST','/admin/subscriptions/rollout',{'action':'enable','revision':1,
            'reason':'Coverage incomplete','security_rules_proof':'fixture','client_compatibility_proof':'fixture'},tokens['admin'],409,key())
        # The native timestamp path above is proven separately. Missing legacy
        # metadata needs an explicit reviewed manifest, retained after cutover.
        doc('users',ids['vendor']).update({'created_at':None})
        unknown=step('vendor','dry_run',expected_account_revision=0,limit=2)
        api.assertion('unknown legacy date never silently grants baseline',unknown['cohort_review_required']
            and not unknown['would_grant_legacy'])
        call('unknown legacy start requires reviewed cohort','POST',reconcile_path('vendor'),
            {'action':'start','reason':'Missing metadata has not been reviewed','expected_account_revision':0},tokens['admin'],409,key())
        job=step('vendor','start',expected_account_revision=0,cohort_review='preexisting')
        api.assertion('reviewed preexisting manifest records admin classification',job['cohort_basis']=='admin_reviewed_preexisting'
            and job['cohort_reviewed_by']==ids['admin'] and not job['cohort_review_required'])
        detail=call('recover interrupted job from admin detail','GET','/admin/vendors/'+ids['vendor']+'/subscription',token=tokens['admin'])
        api.assertion('fence recovery exposes same job and revision',detail['reconciliation_job']['uid']==job['uid'] and detail['reconciliation_job']['revision']==job['revision'])
        call('cannot finish incomplete scan','POST',reconcile_path('vendor'),{'action':'finish','job_id':job['uid'],
            'revision':job['revision'],'reason':'Incomplete'},tokens['admin'],409,key())
        product={'name':'New while fenced','price':5,'stock_quantity':0}
        parallel([lambda:call('fenced concurrent insert','POST','/vendors/items',product,tokens['vendor'],409),
                  lambda:call('fenced concurrent delete','DELETE','/vendors/items/retained_0',token=tokens['vendor'],expected=409)])
        call('stock editing remains available during count','PUT','/vendors/items/retained_0',{'stock_quantity':9},tokens['vendor'])
        api.assertion('fenced catalog definitions retained',len(list(col('shop_items').where('vendor_id','==',ids['vendor']).stream()))==3)
        scan_body={'action':'scan','job_id':job['uid'],'revision':job['revision'],'limit':1,'reason':'Idempotent page'}
        page_key=key()
        page=call('scan first page','POST',reconcile_path('vendor'),scan_body,tokens['admin'],key=page_key)
        retry=call('scan exact replay','POST',reconcile_path('vendor'),scan_body,tokens['admin'],key=page_key)
        api.assertion('scan replay counts first page once',page==retry and page['product_count']==1)
        call('scan key changed body denied','POST',reconcile_path('vendor'),{**scan_body,'limit':2},tokens['admin'],409,page_key)
        finished=scan_finish('vendor',page)
        api.assertion('baseline includes unavailable zero-stock definitions without paid claim',finished['subscription']['status']=='legacy_unrestricted'
            and finished['subscription']['usage']['product_count']==3 and finished['subscription']['payment_state']=='not_attested')
        api.assertion('old SDK-writable paid claim unchanged and untrusted',doc('vendor_subscriptions','historical').get().to_dict()==legacy)
        reconcile('vendor')
        api.assertion('repeat reconciliation creates one baseline',len(list(col(service.GRANTS).where('vendor_id','==',ids['vendor']).stream()))==1)
        doc('users',ids['other']).update({'created_at':None})
        other_job=step('other','start',expected_account_revision=0,cohort_review='post_cutoff')
        api.assertion('reviewed post-cutoff manifest cannot grant legacy',other_job['cohort_basis']=='admin_reviewed_post_cutoff'
            and not other_job['grant_baseline'])
        plan=create_plan('Access during fenced scan')
        assigned=assign('other',plan)
        other_done=scan_finish('other',other_job)
        api.assertion('finish never overwrites concurrent explicit admin grant',other_done['subscription']['current_grant_id']==assigned['current_grant_id']
            and other_done['subscription']['grant_kind']=='free' and len(list(col(service.GRANTS).where('vendor_id','==',ids['other']).stream()))==1)
        # A create concurrent with fence acquisition either commits before the
        # fence and is counted, or retries against the fence and is denied.
        race_state=ent('race')
        parallel([lambda:call('fence acquisition race start','POST',reconcile_path('race'),{'action':'start',
                    'reason':'Race fence acquisition','expected_account_revision':race_state['revision']},tokens['admin'],201,key()),
                  lambda:call('fence acquisition race insert','POST','/vendors/items',{'name':'Race definition','price':1,'stock_quantity':0},tokens['race'],201)])
        race_rows=accept_races('fence acquisition race',{201,409})
        start=next(row for row in race_rows if row['label'].endswith('start'))
        api.assertion('fence acquisition completes',start['status']==201)
        race_job=call('read race fence job','GET','/admin/vendors/'+ids['race']+'/subscription',token=tokens['admin'])['reconciliation_job']
        race_done=scan_finish('race',race_job)
        retained=len(list(col('shop_items').where('vendor_id','==',ids['race']).stream()))
        api.assertion('fence race count matches actual retained definitions',race_done['subscription']['usage']['product_count']==retained and retained in {0,1})
        # Control-document read/write conflict serializes role activation and
        # enable. New role gets either the preparing baseline or enforced none.
        enable={'action':'enable','revision':1,'reason':'All accounts reconciled','security_rules_proof':'Emulator SDK-denial evidence',
                'client_compatibility_proof':'Active HTTP client evidence'}
        parallel([lambda:call('cutover race enable','POST','/admin/subscriptions/rollout',enable,tokens['admin'],key=key()),
                  lambda:call('cutover race role activation','PUT','/admin/users/'+ids['customer'],{'role':'vendor'},tokens['admin'])])
        cutover_rows=accept_races('cutover race',{200})
        api.assertion('cutover and role activation both complete',len(cutover_rows)==2)
        activated=doc(service.ACCOUNTS,ids['customer']).get().to_dict()
        activation_mode=activated['activation_mode']
        activated_grant=doc(service.GRANTS,activated['current_grant_id']).get().to_dict() if activated.get('current_grant_id') else None
        api.assertion('activation honors transactionally observed cutover',activated['usage']['initialized'] and
            ((activation_mode=='preparing' and activated_grant['kind']=='legacy_unrestricted') or
             (activation_mode=='enforced' and activated_grant is None)))
        call('after-cutover role activation','PUT','/admin/users/'+ids['later'],{'role':'vendor'},tokens['admin'])
        later_token=create_token(ids['later'],'vendor')
        later=call('new vendor has initialized none access','GET','/subscriptions/entitlements',token=later_token)
        api.assertion('new vendor receives no silent legacy access',later['status']=='none' and later['usage']['initialized'])
        call('new vendor cannot grow without approval','POST','/vendors/items',product,later_token,403)
        for name in ('vendor','other'):
            before=list(col(service.GRANTS).where('vendor_id','==',ids[name]).stream())
            state=ent(name)
            preview=step(name,'dry_run',expected_account_revision=state['revision'])
            api.assertion(name+' retains completed cohort classification after cutover',not preview['cohort_review_required']
                and not preview['would_grant_legacy'] and preview['cohort_basis']=='admin_reviewed_'+('preexisting' if name=='vendor' else 'post_cutoff'))
            reconcile(name)
            after=list(col(service.GRANTS).where('vendor_id','==',ids[name]).stream())
            api.assertion(name+' repeat post-cutover reconciliation cannot mint access',len(after)==len(before))
        # Reference/delete races must never produce a deleted referenced plan.
        for operation in ('assign','request'):
            race_plan=create_plan('Reference race '+operation)
            state=ent('other')
            prefix='reference '+operation+' race '
            def delete():
                return call(prefix+'delete','DELETE','/admin/subscription-plans/'+race_plan['uid'],
                            {'revision':race_plan['revision'],'reason':'Unreferenced delete race'},tokens['admin'],key=key())
            def reference():
                if operation=='assign':
                    return call(prefix+'reference','POST','/admin/vendors/'+ids['other']+'/subscription',
                        {'action':'assign','kind':'free','plan_id':race_plan['uid'],'plan_version_id':race_plan['current_version_id'],
                         'expected_account_revision':state['revision'],'reason':'Reference race'},tokens['admin'],key=key())
                return call(prefix+'reference','POST','/subscriptions/requests',{'plan_id':race_plan['uid'],
                    'plan_version_id':race_plan['current_version_id'],'request_kind':'subscription',
                    'expected_account_revision':state['revision']},tokens['other'],201,key())
            parallel([delete,reference])
            rows=accept_races(prefix,{200,201,404,409})
            statuses=[row['status'] for row in rows]
            api.assertion(prefix+'only one conflicting transition commits',sum(status in {404,409} for status in statuses)==1)
            saved=doc(service.PLANS,race_plan['uid']).get().to_dict()
            refs=list(col(service.GRANTS).where('plan_id','==',race_plan['uid']).stream())+list(col(service.REQUESTS).where('plan_id','==',race_plan['uid']).stream())
            api.assertion(prefix+'deleted identities never gain references',not (saved.get('deleted_at') and refs)
                and bool(saved.get('reference_count'))==bool(refs))
        report['activation_race_outcome']=activation_mode
        report['passed']=all(row['passed'] for row in report['checks'])
    finally:
        server.shutdown();thread.join(timeout=5);server.server_close()
        report['server_stopped']=not thread.is_alive()
        report['check_count']=len(report['checks'])
        Path(output).write_text(json.dumps(report,indent=2)+'\n')
    if not report.get('passed'): raise AssertionError('Migration proof did not pass')
    print(json.dumps({'passed':True,'checks':report['check_count'],'provider_calls':0,'server_stopped':report['server_stopped'],
                      'activation_race_outcome':report['activation_race_outcome']}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    run(parser.parse_args().output)
