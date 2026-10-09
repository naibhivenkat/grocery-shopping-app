#!/usr/bin/env python3
"""Native HTTP journeys against ONLY a loopback Firestore emulator/demo project.

No production credentials, email delivery, Razorpay capture/refunds or mocks are
used. Run under firebase emulators:exec --only firestore --project demo-... .
"""
from __future__ import annotations
import argparse
import hashlib
from io import BytesIO
from datetime import datetime,timedelta,timezone
import ipaddress
import json
import os
import re
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid

BACKEND=Path(__file__).resolve().parents[1]


def guard_environment(environ):
    host=environ.get('FIRESTORE_EMULATOR_HOST','')
    if not host or '://' in host or '/' in host:
        raise ValueError('FIRESTORE_EMULATOR_HOST must name a loopback emulator host:port')
    parsed=urlsplit('http://'+host)
    try:
        loopback=parsed.hostname=='localhost' or ipaddress.ip_address(parsed.hostname or '').is_loopback
        valid_port=parsed.port is not None and 1<=parsed.port<=65535
    except ValueError:
        raise ValueError('Emulator host must be loopback with a valid port') from None
    if not loopback or not valid_port or parsed.username or parsed.password:
        raise ValueError('Refusing a non-loopback Firestore endpoint')
    projects=[environ[k] for k in ('GCLOUD_PROJECT','GOOGLE_CLOUD_PROJECT','FIREBASE_PROJECT_ID') if environ.get(k)]
    if not projects or any(not re.fullmatch(r'demo-[a-z0-9-]{1,50}',p) for p in projects) or len(set(projects))!=1:
        raise ValueError('All configured project IDs must match one demo- project')
    return projects[0]


def isolate_environment(project):
    # Provider credentials are discarded BEFORE importing backend/Google SDKs.
    prefixes=('RAZORPAY_','GOOGLE_','SMTP_','SENDINBLUE_','BREVO_','GMAIL_')
    for key in list(os.environ):
        if key.startswith(prefixes) or key in {'FIREBASE_CREDENTIALS_JSON','FIREBASE_STORAGE_BUCKET','WEBHOOK_SECRET','FROM_EMAIL'}:
            os.environ.pop(key,None)
    for key in ('GCLOUD_PROJECT','GOOGLE_CLOUD_PROJECT','FIREBASE_PROJECT_ID'):
        os.environ[key]=project
    os.environ.update(FLASK_ENV='development',FLASK_DEBUG='0',ENABLE_LEGACY_ROUTES='0',
        AUTH_OTP_DEBUG_RESPONSE='1',JWT_SECRET=os.environ.get('EMULATOR_JWT_SECRET') or secrets.token_hex(32))
    sys.path.insert(0,str(BACKEND))
    import firebase_admin
    from firebase_admin import credentials
    from google.auth.credentials import AnonymousCredentials
    class EmulatorCredential(credentials.Base):
        def get_credential(self):return AnonymousCredentials()
    if firebase_admin._apps:
        raise ValueError('Expected a fresh emulator-only Firebase process')
    firebase_admin.initialize_app(EmulatorCredential(),{'projectId':project})


class Http:
    def __init__(self,base,report):self.base,self.report,self.started=base,report,time.monotonic()
    def call(self,label,method,path,body=None,token=None,expected=200,key=None,*,files=None,response_format='json'):
        if time.monotonic()-self.started>180:raise AssertionError('Journey runtime exceeded 180 seconds')
        headers={'Content-Type':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        if key:headers['Idempotency-Key']=key
        if files:
            if body is not None:raise ValueError('Use either JSON body or multipart files')
            data,headers['Content-Type']=multipart_files(files)
        else:
            data=json.dumps(body).encode() if body is not None else None
        req=urllib.request.Request(self.base+path,data=data,method=method,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=20) as response:status=response.status;raw=response.read();mime=response.headers.get_content_type()
        except urllib.error.HTTPError as exc:status=exc.code;raw=exc.read();mime=exc.headers.get_content_type()
        self.report['checks'].append({'label':label,'method':method,'path':path,'status':status,'passed':status==expected})
        if status!=expected:
            try:parsed=json.loads(raw)
            except (ValueError,UnicodeDecodeError):parsed={}
            raise AssertionError(f'{label}: HTTP {status}, expected {expected}; detail={parsed.get("detail", "unexpected response") if isinstance(parsed,dict) else "unexpected response"}')
        if response_format=='pdf':
            self.assertion(label+' is an actual PDF response',mime=='application/pdf' and raw.startswith(b'%PDF-'))
            return raw
        if response_format=='text':return raw.decode('utf-8')
        if response_format!='json':raise ValueError('Unsupported response format')
        return json.loads(raw)
    def assertion(self,label,condition):
        self.report['checks'].append({'label':label,'passed':bool(condition)})
        if not condition:raise AssertionError(label)


def multipart_files(files):
    """Encode actual fixture bytes without temporary files or third-party HTTP clients."""
    boundary='localshop-'+uuid.uuid4().hex
    parts=[]
    for field,(filename,contents,mime) in files.items():
        if any(character in field+filename+mime for character in ('\r','\n','"')):
            raise ValueError('Invalid multipart fixture header')
        if not isinstance(contents,bytes):raise ValueError('Fixture contents must be bytes')
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
                      f'Content-Type: {mime}\r\n\r\n').encode()+contents+b'\r\n')
    return b''.join(parts)+f'--{boundary}--\r\n'.encode(),'multipart/form-data; boundary='+boundary


def requested_journeys(api,store,customer,vendor,other,second_vendor,items,ledger,room,suffix):
    """Exercise requested changes over real loopback HTTP and emulator storage."""
    root=store.collection('localshop').document('v1')
    balance=lambda:root.collection('khata_ledgers').document(ledger).get().to_dict()['balance']
    def payment(method,amount,key):
        body={'ledger_id':ledger,'type':'debit','amount':amount,'payment_method':method,
              'payment_reference':'EMULATOR-UPI-REFERENCE' if method=='upi' else None}
        first=api.call('customer '+method+' marks payment paid','POST','/khata/transactions',body,customer['token'],201,key)
        retry=api.call('customer '+method+' pending submission retry','POST','/khata/transactions',body,customer['token'],200,key)
        api.assertion(method+' request pending and retry same entry',first['status']=='pending' and first['uid']==retry['uid'])
        api.assertion(method+' submission does not reduce debt',balance()==40 if method=='cash' else balance()==30)
        path='/khata/transactions/'+first['uid']
        api.call('customer cannot approve own '+method+' payment','POST',path+'/approve',{},customer['token'],403)
        api.call('foreign shop cannot approve '+method+' payment','POST',path+'/approve',{},second_vendor['token'],403)
        return body,path
    cash,cashpath=payment('cash',10,'customer-cash-'+suffix)
    api.call('owner approves customer cash','POST',cashpath+'/approve',{},vendor['token'])
    api.call('owner cash approval retry','POST',cashpath+'/approve',{},vendor['token'])
    api.assertion('customer cash approval reduces debt once',balance()==30)
    retried=api.call('customer retry after approval','POST','/khata/transactions',cash,customer['token'],200,'customer-cash-'+suffix)
    api.assertion('approved submission retains confirmed status',retried['status']=='confirmed' and balance()==30)
    upi,upipath=payment('upi',10,'customer-upi-rejected-'+suffix)
    api.call('owner rejects unreceived UPI','POST',upipath+'/reject',{},vendor['token'])
    api.call('owner rejection retry','POST',upipath+'/reject',{},vendor['token'])
    api.call('rejected UPI cannot later approve','POST',upipath+'/approve',{},vendor['token'],409)
    api.assertion('rejected UPI never changes balance',balance()==30)
    approved_body={**upi,'amount':12.5}
    approved=api.call('customer submits UPI for owner review','POST','/khata/transactions',approved_body,customer['token'],201,'customer-upi-approved-'+suffix)
    api.call('owner confirms received UPI','POST','/khata/transactions/'+approved['uid']+'/approve',{},vendor['token'])
    api.assertion('UPI owner approval exact paise balance',balance()==17.5)
    api.call('customer overpayment request rejected','POST','/khata/transactions',{**upi,'amount':100},customer['token'],422)
    transactions=api.call('customer sees payment request decisions','GET','/khata/ledgers/'+ledger+'/transactions',token=customer['token'])
    statuses={entry['uid']:entry.get('status') for entry in transactions}
    api.assertion('approved and rejected payment history retained',statuses[cashpath.rsplit('/',1)[1]]=='confirmed'
                  and statuses[upipath.rsplit('/',1)[1]]=='rejected' and statuses[approved['uid']]=='confirmed')

    batchbody={'payment_method':'cash','items':[{'item_id':items[0],'quantity':2},{'item_id':items[1],'quantity':1}]}
    batch=api.call('billable cash cart placement','POST','/orders/batch',batchbody,customer['token'],201,'invoice-batch-'+suffix)
    order_id=batch['order_ids'][0];bill='/orders/'+order_id+'/invoice'
    original=api.call('customer reads full cart bill','GET',bill,token=customer['token'])
    api.assertion('bill includes whole batch and exact subtotal',len(original['lines'])==2 and original['subtotal']==44.7 and original['due']==44.7)
    api.call('foreign customer bill denied','GET',bill,token=other['token'],expected=403)
    api.call('foreign shop PDF denied','GET',bill+'.pdf',token=second_vendor['token'],expected=403)
    discount='/vendors/orders/'+order_id+'/discount'
    api.call('customer discount denied','PUT',discount,{'amount':2.35},customer['token'],403)
    api.call('foreign shop discount denied','PUT',discount,{'amount':2.35},second_vendor['token'],403)
    api.call('vendor applies bill discount','PUT',discount,{'amount':2.35},vendor['token'])
    replaced=api.call('vendor replaces previous discount','PUT',discount,{'amount':5.35},vendor['token'])
    api.assertion('discount replacement and batch total exact',replaced['subtotal']==44.7 and replaced['discount']==5.35 and replaced['total']==39.35 and replaced['due']==39.35)
    vendor_bill=api.call('owner sees identical customer bill','GET',bill,token=vendor['token'])
    api.assertion('customer and owner share identical batch bill',vendor_bill==replaced)
    sibling=api.call('another cart line resolves same full bill','GET','/orders/'+batch['order_ids'][1]+'/invoice',token=customer['token'])
    api.assertion('all cart lines resolve same invoice identity totals and lines',all(sibling[field]==replaced[field]
                  for field in ('invoice_number','lines','subtotal','discount','total','due')))
    cash_confirm='/vendors/orders/'+order_id+'/payment/confirm'
    api.call('customer cash confirmation denied','POST',cash_confirm,{},customer['token'],403)
    api.call('foreign shop cash confirmation denied','POST',cash_confirm,{},second_vendor['token'],403)
    api.call('shop confirms discounted cash received','POST',cash_confirm,{},vendor['token'])
    api.call('cash confirmation retry','POST',cash_confirm,{},vendor['token'])
    paid=root.collection('customer_orders').document(order_id).get().to_dict()
    api.assertion('discounted cash confirmation exact persisted values',paid['payment_status']=='paid' and paid['partial_amount_paid']==19.35 and paid['due_amount']==0)
    api.call('collected cash bill cannot be discounted','PUT',discount,{'amount':1},vendor['token'],409)
    api.call('paid cash cannot disappear through cancellation','POST','/orders/'+order_id+'/cancel',{},customer['token'],409)
    for oid in batch['order_ids']:
        status_url='/vendors/orders/'+oid+'/status'
        for status in ('confirmed','packed','delivered','delivered'):
            api.call('clear owner fulfillment '+status,'PUT',status_url,{'status':status},vendor['token'])
    settled=api.call('customer reads delivered paid bill','GET',bill,token=customer['token'])
    api.assertion('delivered cash bill has no amount due',settled['total']==39.35 and settled['due']==0 and all(line['payment_status']=='paid' for line in settled['lines']))
    for actor in (customer,vendor):
        contents=api.call('customer printable PDF' if actor==customer else 'owner printable PDF','GET',bill+'.pdf',token=actor['token'],response_format='pdf')
        text=subprocess.run(['pdftotext','-','-'],input=contents,capture_output=True,timeout=20,check=True).stdout.decode('utf-8')
        api.assertion('PDF contains bill identity totals and payment status',settled['invoice_number'] in text and '39.35' in text and 'paid' in text)

    # The earlier journey sent one message. Two more messages across different
    # shops exhaust one account-wide allowance; idempotent retries cost nothing.
    second_room=api.call('customer opens another shop chat','POST','/chat/rooms',{'vendor_id':second_vendor['uid']},customer['token'])['uid']
    api.call('customer second daily message','POST','/chat/rooms/'+second_room+'/messages',{'text':'Second daily message'},customer['token'],201,'message-two-'+suffix)
    api.call('customer third daily message','POST','/chat/rooms/'+room+'/messages',{'text':'Third daily message'},customer['token'],201,'message-three-'+suffix)
    api.call('third message retry does not use quota','POST','/chat/rooms/'+room+'/messages',{'text':'Third daily message'},customer['token'],200,'message-three-'+suffix)
    api.call('fourth message denied across shop rooms','POST','/chat/rooms/'+second_room+'/messages',{'text':'Fourth message'},customer['token'],429)
    api.call('shop can reply after buyer quota','POST','/chat/rooms/'+room+'/messages',{'text':'Owner reply'},vendor['token'],201)
    messages=list(root.collection('messages').where('sender_id','==',customer['uid']).stream())
    api.assertion('actual emulator stores exactly three customer messages',len(messages)==3)
    customer_events=api.call('customer receives order and message inbox events','GET','/notifications',token=customer['token'])
    vendor_events=api.call('vendor receives order and message inbox events','GET','/notifications',token=vendor['token'])
    api.assertion('customer inbox contains order status payment and chat',{'order_status','order_payment','chat_message'}.issubset({event['type'] for event in customer_events}))
    api.assertion('owner inbox contains order chat and payment review',{'new_order','chat_message','khata_payment_pending'}.issubset({event['type'] for event in vendor_events}))
    status_events=[event for event in customer_events if event['type']=='order_status' and event['reference_id']==order_id]
    api.assertion('repeat delivered status does not duplicate inbox',len(status_events)==3)

    def inventory_count():return len(list(root.collection('shop_items').where('vendor_id','==',vendor['uid']).stream()))
    initial=inventory_count()
    template=api.call('vendor downloads Excel import CSV template','GET','/vendors/items/import/template',token=vendor['token'],response_format='text')
    api.assertion('CSV template has required headers','name,category,description,price,stock_quantity' in template)
    csv_contents=b'name,category,description,price,stock_quantity\nImported CSV Rice,Groceries,Local fixture,3.25,4\nImported CSV Milk,Groceries,Local fixture,5.50,7\n'
    from openpyxl import Workbook
    workbook=Workbook();sheet=workbook.active
    sheet.append(['name','category','description','price','stock_quantity'])
    sheet.append(['Imported Excel Soap','Home','Actual XLSX fixture',7.35,5])
    sheet.append(['Imported Excel Towel','Home','Actual XLSX fixture',12.5,2])
    stream=BytesIO();workbook.save(stream);workbook.close()
    fixtures=[('products.csv',csv_contents,'text/csv'),('products.xlsx',stream.getvalue(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')]
    imported=[]
    for filename,contents,mime in fixtures:
        files={'file':(filename,contents,mime)}
        before=inventory_count()
        api.call('customer cannot import '+filename,'POST','/vendors/items/import',token=customer['token'],expected=403,files=files)
        preview=api.call(filename+' previews real file','POST','/vendors/items/import?preview=true',token=vendor['token'],files=files)
        api.assertion(filename+' preview writes no products',preview['preview'] is True and preview['count']==2 and inventory_count()==before)
        confirmed=api.call(filename+' confirms atomic import','POST','/vendors/items/import',token=vendor['token'],expected=201,files=files)
        retried=api.call(filename+' import retry','POST','/vendors/items/import',token=vendor['token'],expected=201,files=files)
        api.assertion(filename+' retry retains exact item ids and count',confirmed==retried and confirmed['count']==2 and inventory_count()==before+2)
        imported.extend(confirmed['item_ids'])
    api.assertion('CSV and XLSX created four actual vendor items',inventory_count()==initial+4 and len(set(imported))==4)
    invalid={'file':('invalid.csv',b'name,price,stock_quantity\nValid first row,3,2\nInvalid second row,NaN,2\n','text/csv')}
    api.call('invalid import preview fails full validation','POST','/vendors/items/import?preview=true',token=vendor['token'],expected=422,files=invalid)
    api.call('invalid import cannot partially create products','POST','/vendors/items/import',token=vendor['token'],expected=422,files=invalid)
    api.assertion('failed CSV import creates zero rows',inventory_count()==initial+4)

    # Register only after notification-producing actions. Fake emulator tokens
    # verify storage/ownership, and never invoke the real FCM provider.
    token='emulator-installation-'+suffix;registry='/notifications/device-token'
    api.call('emulator device registers old account','POST',registry,{'token':token},vendor['token'])
    api.call('same device switches accounts','POST',registry,{'token':token},other['token'])
    api.call('delayed old-account logout cannot revoke new owner','DELETE',registry,{'token':token},vendor['token'])
    ownership=root.collection('device_tokens').document(hashlib.sha256(token.encode()).hexdigest()).get().to_dict()
    api.assertion('device token actual registry retains new account',ownership['user_id']==other['uid'])
    api.call('current account unregisters own device','DELETE',registry,{'token':token},other['token'])
    api.assertion('device revoked in actual emulator registry',root.collection('device_tokens').document(hashlib.sha256(token.encode()).hexdigest()).get().to_dict()['user_id'] is None)


def journeys(api,store):
    suffix=uuid.uuid4().hex[:10];password=secrets.token_urlsafe(20)
    features=api.call('local feature contract','GET','/features')
    api.assertion('local contract keeps owner-approved khata and free promotions',features.get('backend_contract_version')==2
                  and features.get('khata_vendor_confirmed') is True and features.get('wallet_enabled') is False
                  and features.get('promotion_billing')=='free')
    def register(name,role='customer',otp=False):
        email=f'{name}-{suffix}@example.invalid';username=f'{name}_{suffix}'
        if otp:
            code=api.call(f'{name} request local OTP','POST','/auth/send_otp',{'email':email})['otp']
            api.call(f'{name} verify local OTP','POST','/auth/verify_otp',{'email':email,'otp':code})
        response=api.call(f'{name} signup','POST','/auth/register_after_otp' if otp else '/auth/register',
            {'email':email,'username':username,'password':password,'role':role,'full_name':name.title()},expected=201)
        login=api.call(f'{name} login','POST','/auth/login',{'email':email,'password':password})
        api.assertion(f'{name} login stable account',login['user']['uid']==response['user']['uid'])
        return {'uid':response['user']['uid'],'token':login['access_token'],'email':email}
    customer=register('customer',otp=True);vendor=register('vendor','vendor');other=register('other')
    second_vendor=register('secondvendor','vendor')
    seeded_admin=register('localadmin')
    # Explicit emulator-only privileged fixture; no production/admin role APIs.
    store.collection('localshop').document('v1').collection('users').document(seeded_admin['uid']).update({'role':'admin'})
    admin=api.call('emulator admin login','POST','/auth/login',{'email':seeded_admin['email'],'password':password})['access_token']
    city=api.call('admin creates city','POST','/cities',{'name':'Emulator City','state':'Test','country':'India'},admin,201)['uid']
    api.call('profile cannot promote customer','PUT','/profile',{'role':'admin'},customer['token'],422)
    api.assertion('stored customer role unchanged',api.call('profile role read','GET','/profile',token=customer['token'])['role']=='customer')
    api.call('vendor profile update','PUT','/profile',{'shop_name':'Emulator Grocery','city_id':city,'shop_address':'Local-only test'},vendor['token'])
    api.call('customer cannot create vendor item','POST','/vendors/items',{'name':'Forbidden','price':10},customer['token'],403)
    items=[]
    for name,price in [('Rice',12.35),('Milk',20)]:
        items.append(api.call('vendor creates '+name,'POST','/vendors/items',{'name':name,'description':'Local emulator fixture',
            'price':price,'category':'Groceries','stock_quantity':10},vendor['token'],201)['uid'])
    api.call('public item reads','GET','/shops/'+items[0])
    api.assertion('inventory reads both items',len(api.call('vendor inventory','GET','/inventory',token=vendor['token']))==2)
    api.call('customer cannot change inventory','PUT','/inventory/'+items[0]+'/stock',{'quantity':100},customer['token'],403)
    batchbody={'payment_method':'cash','items':[{'item_id':items[0],'quantity':2,'total_price':24.70},{'item_id':items[1],'quantity':1,'total_price':20}]}
    batch=api.call('cash batch atomic reserve','POST','/orders/batch',batchbody,customer['token'],201,'cash-batch-'+suffix)
    retry=api.call('cash batch retry','POST','/orders/batch',batchbody,customer['token'],201,'cash-batch-'+suffix)
    api.assertion('cash batch retries same orders',batch['order_ids']==retry['order_ids'])
    stock=lambda item:store.collection('localshop').document('v1').collection('shop_items').document(item).get().to_dict()['stock_quantity']
    api.assertion('actual emulator stock reserved once',stock(items[0])==8 and stock(items[1])==9)
    api.call('other customer cannot cancel','POST','/orders/'+batch['order_ids'][0]+'/cancel',{},other['token'],403)
    for oid in batch['order_ids']:
        api.call('cash cancel stock release','POST','/orders/'+oid+'/cancel',{},customer['token'])
        api.call('cash cancellation retry','POST','/orders/'+oid+'/cancel',{},customer['token'])
    api.assertion('actual stock restored once',stock(items[0])==10 and stock(items[1])==10)
    ledger=api.call('vendor opens customer khata','POST','/khata/ledgers',{'customer_id':customer['uid']},vendor['token'],201)['uid']
    api.call('customer cannot forge khata credit','POST','/khata/transactions',{'ledger_id':ledger,'type':'credit','amount':999},customer['token'],403)
    credit={'ledger_id':ledger,'type':'credit','amount':50,'description':'Opening debt'}
    api.call('khata credit atomic','POST','/khata/transactions',credit,vendor['token'],201,'khata-credit-'+suffix)
    api.call('khata credit retry','POST','/khata/transactions',credit,vendor['token'],200,'khata-credit-'+suffix)
    api.call('khata debit payment','POST','/khata/transactions',{'ledger_id':ledger,'type':'debit','amount':10,'payment_method':'cash'},vendor['token'],201,'khata-debit-'+suffix)
    balance=lambda:api.call('customer reads khata balance','GET','/khata/ledgers/'+ledger,token=customer['token'])['balance']
    api.assertion('khata credit/debit exact balance',balance()==40)
    khata=api.call('khata order raises debt','POST','/orders',{'item_id':items[0],'quantity':1,'total_price':12.35,'payment_method':'khata'},customer['token'],201)
    api.assertion('khata order exact paise debt',balance()==52.35)
    api.call('cancel khata order','POST','/orders/'+khata['order_id']+'/cancel',{},customer['token'])
    api.call('retry khata cancellation','POST','/orders/'+khata['order_id']+'/cancel',{},customer['token'])
    api.assertion('khata cancellation debt and stock once',balance()==40 and stock(items[0])==10)
    api.call('customer cannot fake settle ledger','POST','/khata/ledgers/'+ledger+'/settle',{},customer['token'],403)
    api.call('wallet disabled before provider','POST','/razorpayApi/orders',{'purpose':'wallet','amount':10,'reference_id':customer['uid']},customer['token'],403)
    api.call('subscription requires Play Billing','POST','/razorpayApi/orders',{'purpose':'subscription','amount':10,'reference_id':'dummy'},vendor['token'],403)
    api.call('missing Razorpay proof rejected','POST','/razorpayApi/verify',{'payment_id':'fake'},customer['token'],422)
    now=datetime.now(timezone.utc)
    promotion=api.call('vendor free product promotion','POST','/promotions',{'target_type':'product','product_id':items[0],
        'title':'Local promotion','body':'Free advertising fixture','starts_at':(now-timedelta(minutes=1)).isoformat(),
        'ends_at':(now+timedelta(days=1)).isoformat()},vendor['token'],201)
    pid=promotion['uid'];purl='/promotions/'+pid
    api.assertion('free promotion pending moderation',promotion['price_paise']==0 and promotion['status']=='pending')
    visible=lambda:api.call('public promotion feed','GET','/promotions?city_id='+city)
    api.assertion('pending promotion hidden',all(p['uid']!=pid for p in visible()))
    api.call('customer cannot approve promotion','POST',purl+'/moderation',{'decision':'approved','revision':1},customer['token'],403)
    api.call('admin approves promotion','POST',purl+'/moderation',{'decision':'approved','revision':1},admin)
    api.assertion('approved promotion visible',any(p['uid']==pid for p in visible()))
    api.call('vendor pauses promotion','PATCH',purl+'/pause',{'is_paused':True},vendor['token'])
    api.assertion('paused promotion hidden',all(p['uid']!=pid for p in visible()))
    api.call('vendor resumes promotion','PATCH',purl+'/pause',{'is_paused':False},vendor['token'])
    edited=api.call('promotion edit resets moderation','PUT',purl,{'title':'Updated local promotion'},vendor['token'])
    api.assertion('edited promotion hidden',edited['status']=='pending' and all(p['uid']!=pid for p in visible()))
    api.call('stale moderation blocked','POST',purl+'/moderation',{'decision':'approved','revision':1},admin,409)
    api.call('admin reapproves latest revision','POST',purl+'/moderation',{'decision':'approved','revision':edited['revision']},admin)
    api.assertion('reapproved promotion visible',any(p['uid']==pid for p in visible()))
    review=api.call('customer review atomic rating','POST','/reviews',{'item_id':items[0],'vendor_id':vendor['uid'],'rating':4,'comment':'Good'},customer['token'],201)
    updated=api.call('customer review updates existing','POST','/reviews',{'item_id':items[0],'vendor_id':vendor['uid'],'rating':5,'comment':'Great'},customer['token'])
    api.assertion('review same id and aggregate',review['uid']==updated['uid'] and api.call('read item rating','GET','/shops/'+items[0])['rating_count']==1)
    room=api.call('customer opens vendor chat','POST','/chat/rooms',{'vendor_id':vendor['uid']},customer['token'])['uid']
    first=api.call('chat sends message','POST','/chat/rooms/'+room+'/messages',{'text':'Hello shop'},customer['token'],201,'chat-'+suffix)
    second=api.call('chat retries message','POST','/chat/rooms/'+room+'/messages',{'text':'Hello shop'},customer['token'],200,'chat-'+suffix)
    api.assertion('chat sends once',first['uid']==second['uid'])
    api.call('foreign customer chat denied','GET','/chat/rooms/'+room+'/messages',token=other['token'],expected=403)
    api.assertion('vendor reads actual chat',len(api.call('vendor chat messages','GET','/chat/rooms/'+room+'/messages',token=vendor['token']))==1)
    code=api.call('customer generates referral','POST','/referrals/generate',{},customer['token'])['code']
    api.call('own referral rejected','POST','/referrals/apply',{'code':code},customer['token'],422)
    applied=api.call('other customer applies referral','POST','/referrals/apply',{'code':code},other['token'])
    api.call('referral repeat idempotent','POST','/referrals/apply',{'code':code},other['token'])
    api.assertion('wallet rewards disabled',applied['reward_credited'] is False)
    schedule={day:{'from':'09:00 AM','to':'05:00 PM'} for day in ('Mon','Tue','Wed','Thu','Fri','Sat','Sun')}
    api.call('vendor enables service profile','PUT','/provider/profile',{'working_schedule':schedule,'is_active':True},vendor['token'])
    service=api.call('provider creates physical service','POST','/provider/services',{'title':'Cleaning','pricing_type':'fixed','fixed_price':100},vendor['token'],201)['id']
    quote=api.call('server service quote','POST','/services/calculate-price',{'service_id':service,'duration':60})
    api.assertion('service price includes server fee and tax',quote['total_cost']==123.9)
    tomorrow=(now+timedelta(days=1)).date().isoformat()
    booking=api.call('service pending booking','POST','/bookings/create-pending',{'provider_id':vendor['uid'],'service_id':service,
        'slot_date':tomorrow,'slot_time':'09:00','duration':60},customer['token'],201)['id']
    api.call('unsettled service cannot confirm','POST','/bookings/'+booking+'/confirm',{'payment_method':'razorpay','payment_intent_id':'fake'},customer['token'],400)
    api.call('wallet service confirm disabled','POST','/bookings/'+booking+'/confirm',{'payment_method':'wallet'},customer['token'],410)
    api.call('closed time booking rejected','POST','/bookings/create-pending',{'provider_id':vendor['uid'],'service_id':service,
        'slot_date':tomorrow,'slot_time':'23:00','duration':60},customer['token'],409)
    requested_journeys(api,store,customer,vendor,other,second_vendor,items,ledger,room,suffix)
    api.assertion('no provider payment/capture records created',not list(store.collection('localshop').document('v1').collection('payment_orders').stream()))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--port',type=int,default=0,help=argparse.SUPPRESS)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    try:project=guard_environment(os.environ)
    except ValueError as exc:print(str(exc),file=sys.stderr);return 2
    isolate_environment(project)
    if args.serve:
        if not 1<=args.port<=65535:return 2
        from main import app
        app.run(host='127.0.0.1',port=args.port,debug=False,use_reloader=False,threaded=True)
        return 0
    report={'project':project,'firestore_emulator':os.environ['FIRESTORE_EMULATOR_HOST'],
        'started_at':datetime.now(timezone.utc).isoformat(),'transport':'native Flask HTTP + actual Firestore emulator',
        'proof_boundary':'No production database, real email, payments, captures, refunds or mocked providers/stores','checks':[]}
    process=None
    try:
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        child_env=dict(os.environ);child_env['EMULATOR_JWT_SECRET']=os.environ['JWT_SECRET']
        with tempfile.TemporaryFile(mode='w+') as log:
            process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--serve','--port',str(port)],env=child_env,
                cwd=BACKEND,stdout=log,stderr=log)
            base=f'http://127.0.0.1:{port}';ready=False
            for _ in range(80):
                if process.poll() is not None:raise AssertionError('Native Flask subprocess stopped before readiness')
                try:
                    with urllib.request.urlopen(base+'/health',timeout=1) as response:
                        if response.status==200:ready=True;break
                except (OSError,urllib.error.URLError):time.sleep(.1)
            if not ready:raise AssertionError('Native Flask loopback readiness timeout')
            from firebase_admin import firestore
            journeys(Http(base,report),firestore.client())
            report['passed']=True
    except Exception as exc:
        report['passed']=False;report['failure']=f'{type(exc).__name__}: {exc}'
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    report['finished_at']=datetime.now(timezone.utc).isoformat();report['check_count']=len(report['checks'])
    text=json.dumps(report,indent=2)
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text+'\n')
    if args.output:
        print(json.dumps({key:report[key] for key in ('passed','check_count','project','started_at','finished_at','failure') if key in report},indent=2))
        print('Detailed report: '+str(args.output.resolve()))
    else:
        print(text)
    return 0 if report.get('passed') else 1

if __name__=='__main__':sys.exit(main())
