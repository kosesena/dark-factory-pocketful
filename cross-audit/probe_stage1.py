"""Independent HTTP-only probes; never import service or shipped-check source."""
import concurrent.futures as cf
import copy
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get('AUDIT_BASE','http://127.0.0.1:18081')
DEST = os.environ.get('AUDIT_DEST','http://127.0.0.1:18082')
REV = os.environ.get('AUDIT_REV','69289b3')
RESULTS = []
TOK = {}
FIX = {'currency':'EUR','minor_units':2,'users':[
    {'id':'u_a','email':'a@example.com','password':'eight chars','display_name':'A','handle':'a','balance':10000},
    {'id':'u_b','email':'b@example.com','password':'eight chars','display_name':'B','handle':'b','balance':1000},
    {'id':'u_c','email':'c@example.com','password':'eight chars','display_name':'C','handle':'c','balance':0},
    {'id':'u_o','email':'o@example.com','password':'eight chars','display_name':'O','handle':'o','balance':0}],
    'payments':[], 'requests':[], 'settlement_operator_ids':['u_o']}

def call(method,path,body=None,user=None,key=None,raw=None,base=BASE,headers=None):
    h={'Content-Type':'application/json; charset=utf-8'}
    if user: h['Authorization']='Bearer '+TOK.get(user,user)
    if key is not None: h['Idempotency-Key']=key
    if headers: h.update(headers)
    data=raw if raw is not None else (json.dumps(body,ensure_ascii=True).encode() if body is not None else None)
    start=time.monotonic()
    try:
        r=urllib.request.urlopen(urllib.request.Request(base+path,data=data,method=method,headers=h),timeout=10 if path.startswith('/_test/') else 5)
    except urllib.error.HTTPError as e: r=e
    except Exception as e: return (0,{'transport_error':str(e)}, {},time.monotonic()-start)
    data=r.read()
    try: parsed=json.loads(data) if data else None
    except Exception: parsed={'non_json':data[:300].decode(errors='replace')}
    return r.status,parsed,dict(r.headers),time.monotonic()-start

def check(name,cond,detail=None):
    RESULTS.append({'probe':name,'passed':bool(cond),'detail':detail})
    if not cond: print('FAIL',name,json.dumps(detail,ensure_ascii=True),flush=True)

def expect(name,r,status,code=None):
    ok=r[0]==status and (code is None or isinstance(r[1],dict) and r[1].get('error',{}).get('code')==code)
    if status>=400: ok=ok and isinstance(r[1],dict) and isinstance(r[1].get('error',{}).get('message'),str) and bool(r[1]['error']['message'])
    check(name,ok,{'status':r[0],'body':r[1]} if not ok else None)
    return r[1]

def reset(f=None,base=BASE):
    expect('reset',call('POST','/_test/reset',f or FIX,base=base),204)
    if base==BASE:
        TOK.clear()
        for u in (f or FIX)['users']:
            r=call('POST','/auth/login',{'email':u['email'],'password':u['password']})
            if r[0]==200: TOK[u['handle']]=r[1]['token']
            else: expect('seed-login-'+u['handle'],r,200)

def bal(user,base=BASE): return call('GET','/me',user=user,base=base)[1]['balance']
def state(base=BASE): return call('GET','/_test/export',base=base)[1]
def payment(key='p',**extra): return call('POST','/payments',{'to_handle':'b','amount':10,**extra},'a',key)
def request(key='r',**extra): return call('POST','/requests',{'payer_handle':'a','amount':10,**extra},'b',key)
def feed(user): return call('GET','/activity',user=user)[1]['payments']
def reqs(user): return call('GET','/requests',user=user)[1]['requests']

def basic():
    r=call('GET','/health'); expect('health',r,200); check('health-body',r[1]=={'status':'ok'})
    check('json-content-type','application/json' in r[2].get('Content-Type','') and 'charset=utf-8' in r[2].get('Content-Type','').lower(),r[2])
    reset()
    for path,method,body in [('/me','GET',None),('/activity','GET',None),('/requests','GET',None),('/payments','POST',{}),('/requests','POST',{}),('/splits','POST',{}),('/settlements','POST',{}),('/requests/no/pay','POST',{}),('/requests/no/cancel','POST',{}),('/requests/no/decline','POST',{})]:
        for auth in [None,'unknown']:
            expect('auth-'+method+path+str(auth),call(method,path,body,auth,'k'),401,'unauthenticated')
    for h in ['Basic '+TOK['a'],'Bearer','Bearer bogus','Bearer '+TOK['a']+' junk']:
        expect('malformed-auth',call('GET','/me',headers={'Authorization':h}),401,'unauthenticated')
    expect('unknown-endpoint',call('GET','/not-an-endpoint',user='a'),404,'not_found')
    m=call('GET','/me',user='a')[1]
    check('me-fields',m=={'user_id':'u_a','display_name':'A','handle':'a','balance':10000,'currency':'EUR','minor_units':2},m)
    for body,code,status in [({'email':'a@example.com','password':'abcdefgh','display_name':'X'},'email_taken',409),({'email':'bad','password':'abcdefgh','display_name':'X'},'validation_failed',422),({'email':'@example.com','password':'abcdefgh','display_name':'X'},'validation_failed',422),({'email':'x@','password':'abcdefgh','display_name':'X'},'validation_failed',422),({'email':'x@example.com','password':'1234567','display_name':'X'},'validation_failed',422),({'email':8,'password':'abcdefgh','display_name':'X'},'malformed_request',400),({'email':'x@example.com','password':False,'display_name':'X'},'malformed_request',400),({'email':'x@example.com','password':'abcdefgh','display_name':None},'malformed_request',400),({'email':'x@example.com','password':'abcdefgh'},'validation_failed',422)]:
        expect('signup-invalid-'+str(body),call('POST','/auth/signup',body),status,code)
    for body in [{'email':'a@example.com','password':'wrongpass'},{'email':'none@example.com','password':'eight chars'}]: expect('bad-login',call('POST','/auth/login',body),401,'unauthenticated')
    r=call('POST','/auth/login',{'email':'a@example.com','password':'eight chars'}); expect('multiple-login',r,200)
    expect('old-token-valid',call('GET','/me',user='a'),200)
    expect('new-token-valid',call('GET','/me',user=r[1]['token']),200)
    body={'email':'Ab.C+def_12345678901234567890@example.com','password':'abcdefgh','display_name':'Unicode 🪷','handle':'ignore_me','unknown':False}
    r=call('POST','/auth/signup',body); expect('derived-signup',r,201)
    TOK['new']=r[1]['token']; nm=call('GET','/me',user='new')[1]
    handle='ab_c_def_12345678901'; check('derive-and-zero',nm['handle']==handle and nm['balance']==0,nm)
    expect('new-receives',payment('newpay',to_handle=handle),201)
    expect('new-requestable',request('newreq',payer_handle=handle,amount=1000000000),201)
    duplicate={**body,'email':'ab-c+def_123456789012ZZ@example.net'}
    expect('handle-collision',call('POST','/auth/signup',duplicate),409,'handle_taken')
    expect('collision-no-account',call('POST','/auth/login',{'email':duplicate['email'],'password':'abcdefgh'}),401,'unauthenticated')
    neg=copy.deepcopy(FIX); neg['users'][0]['balance']=-1; before=state()
    expect('negative-reset',call('POST','/_test/reset',neg),422,'validation_failed'); check('negative-reset-atomic',state()==before)
    old=TOK['a']; reset(); expect('reset-clears-token',call('GET','/me',user=old),401,'unauthenticated')
    for currency,units in [('EUR',2),('JPY',0),('BHD',3)]:
        f=copy.deepcopy(FIX); f.update(currency=currency,minor_units=units)
        f['payments']=[{'id':'seeded','from_user_id':'u_a','to_user_id':'u_b','amount':99,'note':'seed','visibility':'private'}]
        reset(f); check('seed-no-replay-'+currency,bal('a')==10000 and bal('b')==1000)
        check('currency-'+currency,call('GET','/me',user='a')[1]['minor_units']==units)
        check('seed-feed-private-'+currency,len(feed('a'))==1 and not feed('c'))

def validation():
    reset()
    paths=[('/payments',{'to_handle':'b','amount':10},'a'),('/requests',{'payer_handle':'a','amount':10},'b'),('/splits',{'participant_handles':['a','b'],'amount':10},'a')]
    rid=request('pay-test')[1]['request_id']; paths.append(('/requests/'+rid+'/pay',{},'a'))
    paths.append(('/settlements',{'transfers':[{'from_handle':'a','to_handle':'b','amount':10}]},'o'))
    for path,body,user in paths:
        for key in [None,'']: expect('missing-key-'+path,call('POST',path,body,user,key),400,'missing_idempotency_key')
        expect('long-key-'+path,call('POST',path,body,user,'k'*256),422,'validation_failed')
        for raw in [b'{',b'[]',b'null',b'1',b'true',b'"abc"']:
            expect('bad-json-root-'+path+raw.decode(),call('POST',path,user=user,key='raw',raw=raw),400,'malformed_request')
    idx=0
    for path,body,user in paths[:3]:
        for amount in [0,-1,1000000001,1.5,True,False,'1',None,[],{}]:
            idx+=1; expect('amount-'+path+'-'+str(amount),call('POST',path,{**body,'amount':amount},user,str(idx)),422,'validation_failed')
        for note in [None,5,False,[],{},'x'*201,'🪷'*201]:
            idx+=1; expect('note-'+path+'-'+str(note)[:30],call('POST',path,{**body,'note':note},user,str(idx)),422,'validation_failed')
        missing=dict(body); missing.pop('amount'); expect('missing-amount-'+path,call('POST',path,missing,user,'miss'),422,'validation_failed')
    for path,body,user in [paths[0],paths[3]]:
        for v in [None,1,True,{},[],'PUBLIC','']:
            idx+=1; expect('visibility-'+path+str(v),call('POST',path,{**body,'visibility':v},user,str(idx)),422,'validation_failed')
    for path,body,user,field in [(*paths[0],'to_handle'),(*paths[1],'payer_handle'),(*paths[2],'participant_handles')]:
        for val in [None,1,True,{}]: expect('wrong-type-'+field+str(val),call('POST',path,{**body,field:val},user,'type'),400,'malformed_request')
    expect('self-payment',payment('self',to_handle='a'),422,'self_payment')
    expect('self-request',request('self',payer_handle='b'),422,'self_request')
    expect('unknown-payment',payment('unknown',to_handle='zzz'),404,'not_found')
    expect('unknown-request',request('unknown',payer_handle='zzz'),404,'not_found')
    for parts,status,code in [([],422,'validation_failed'),(['a','a'],422,'validation_failed'),(['a','zzz'],404,'not_found')]:
        expect('split-parts-'+str(parts),call('POST','/splits',{'amount':10,'participant_handles':parts},'a','parts'),status,code)
    for path in ['/activity','/requests']:
        for field,vals in [('limit',['0','201','-1','4.0','1e2','%2B4','','abc','true']),('offset',['-1','1e9','4.0','%2B4','','abc','true'])]:
            for val in vals: expect('query-'+path+'-'+field+val,call('GET',path+'?'+field+'='+val,user='a'),422,'validation_failed')
        for q in ['limit=1&offset=0','limit=200&offset=9999999999999999999999999','limit=01&offset=00','weird=yes']:
            expect('valid-query-'+path+q,call('GET',path+'?'+q,user='a'),200)
    for q in ['direction=oops','status=oops']:
        expect('bad-filter-'+q,call('GET','/requests?'+q,user='a'),422,'validation_failed')

def money():
    reset(); before=state()
    expect('insufficient-payment',payment('poor',amount=10001),409,'insufficient_funds'); check('failed-payment-no-trace',state()==before)
    for i,raw in enumerate([b'{"to_handle":"b","amount":1000}',b'{"to_handle":"b","amount":1000.0}',b'{"to_handle":"b","amount":1e3}']):
        expect('integral-spelling-'+str(i),call('POST','/payments',user='a',key='spelling'+str(i),raw=raw),201)
    note='  e\u0301 é \n\t <>&" 🪷 '+chr(0)+'  '
    p=expect('unicode-payment',payment('unicode',note=note,visibility='private',unknown={'x':1}),201)
    check('note-verbatim',p['note']==note)
    check('payment-fields',set(['payment_id','from_user_id','from_handle','to_user_id','to_handle','amount','currency','note','visibility','request_id','settlement_id','created_at'])<=p.keys(),p)
    check('payment-linkage',p['request_id'] is None and p.get('settlement_id') is None)
    check('time-offset',bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})',p['created_at'])))
    check('id-bound',isinstance(p['payment_id'],str) and len(p['payment_id'])<=64)
    expect('note-200-emoji',payment('emoji',note='🪷'*200),201)
    check('private-both-parties',p in feed('a') and p in feed('b') and p not in feed('c'))
    p2=expect('defaults',payment('default'),201); check('defaults-values',p2['note']=='' and p2['visibility']=='public')
    check('public-third-party',p2 in feed('c'))
    check('money-conserved',sum(bal(u) for u in ['a','b','c','o'])==11000)
    f=copy.deepcopy(FIX); f['users'][0]['balance']=2**53-1000000000; f['users'][1]['balance']=1000000000
    reset(f); expect('upper-exact-balance',call('POST','/payments',{'to_handle':'a','amount':1000000000},'b','max'),201)
    check('upper-exact-observed',bal('a')==2**53 and bal('b')==0)

def idem():
    reset()
    p=expect('idem-first',payment('k'),201)
    check('idem-replay-exact',expect('idem-replay',payment('k'),200)==p)
    expect('idem-invalid-precedence',payment('k',amount=False),409,'idempotency_key_reuse')
    r=call('POST','/payments',raw=b' { "amount": 10.0, "to_handle":"b" } ',user='a',key='k')
    check('idem-numeric-and-order',expect('idem-order',r,200)==p)
    expect('idem-unknown-diff',payment('k',ignored=True),409,'idempotency_key_reuse')
    expect('idem-user-scope',call('POST','/payments',{'to_handle':'a','amount':10},'b','k'),201)
    expect('idem-path-scope',call('POST','/requests',{'payer_handle':'b','amount':10},'a','k'),201)
    expect('idem-failure',payment('retry',amount=1000000000),409,'insufficient_funds')
    expect('idem-failure-reuse',payment('retry',amount=10),201)
    expect('key-255',payment('K'*255),201); expect('key-1',payment('K'),201)
    rq=expect('request-first',request('replayreq'),201)
    expect('cancel-request',call('POST','/requests/'+rq['request_id']+'/cancel',{},'b'),200)
    check('request-replay-after-cancel',expect('request-replay',request('replayreq'),200)==rq)
    rq2=request('pay-r')[1]; path='/requests/'+rq2['request_id']+'/pay'
    pay=expect('pay-first',call('POST',path,{},'a','pay'),201)
    check('pay-replay-exact',expect('pay-replay',call('POST',path,{},'a','pay'),200)==pay)
    expect('pay-default-different-body',call('POST',path,{'visibility':'public'},'a','pay'),409,'idempotency_key_reuse')
    spbody={'amount':1,'participant_handles':['a','b','c']}
    sp=expect('split-idem-first',call('POST','/splits',spbody,'a','split'),201)
    check('split-idem-replay',expect('split-idem-repeat',call('POST','/splits',spbody,'a','split'),200)==sp)
    expect('split-precedence',call('POST','/splits',{},'a','split'),409,'idempotency_key_reuse')
    expect('request-precedence',call('POST','/requests',{},'b','replayreq'),409,'idempotency_key_reuse')
    # JSON booleans must remain different from numeric values, including unknown fields.
    pbool=expect('bool-extra-first',payment('bool-extra',extra=1),201)
    expect('bool-not-number-idem',payment('bool-extra',extra=True),409,'idempotency_key_reuse')

def requests_splits():
    reset()
    rq=expect('overdrawn-request',request('large',payer_handle='c',amount=1200,visibility='private'),201)
    path='/requests/'+rq['request_id']
    check('request-no-visibility',rq.get('visibility') is None and rq['status']=='pending' and rq['payment_id'] is None)
    before=state(); expect('overdrawn-pay',call('POST',path+'/pay',{},'c','later'),409,'insufficient_funds'); check('overdrawn-pay-nochange',state()==before)
    expect('fund-payer',payment('fund',to_handle='c',amount=1200),201)
    expect('pay-wrong-user',call('POST',path+'/pay',{},'a','later'),403,'forbidden')
    paid=expect('later-pay',call('POST',path+'/pay',{'visibility':'private'},'c','later'),201)
    check('paid-roles',paid['from_user_id']=='u_c' and paid['to_user_id']=='u_b' and paid['request_id']==rq['request_id'])
    check('paid-link',any(x['payment_id']==paid['payment_id'] and x['status']=='paid' for x in reqs('b')))
    check('payer-visibility',paid in feed('b') and paid in feed('c') and paid not in feed('a'))
    expect('paid-again-other-key',call('POST',path+'/pay',{},'c','another'),409,'request_not_pending')
    expect('paid-decline',call('POST',path+'/decline',{},'c'),409,'request_not_pending')
    expect('paid-cancel',call('POST',path+'/cancel',{},'b'),409,'request_not_pending')
    for terminal,owner,opposite,other in [('decline','a','cancel','b'),('cancel','b','decline','a')]:
        rr=request(terminal)[1]; pp='/requests/'+rr['request_id']; expected='declined' if terminal=='decline' else 'cancelled'
        expect('wrong-'+terminal,call('POST',pp+'/'+terminal,{},'c'),403,'forbidden')
        first=expect(terminal,call('POST',pp+'/'+terminal,{},owner),200); check(terminal+'-status',first['status']==expected)
        check('repeat-'+terminal,expect('repeat-'+terminal,call('POST',pp+'/'+terminal,{},owner),200)==first)
        expect('terminal-conflict-'+terminal,call('POST',pp+'/'+opposite,{},other),409,'request_not_pending')
        expect('terminal-pay-'+terminal,call('POST',pp+'/pay',{},'a','new'),409,'request_not_pending')
    for action in ['pay','cancel','decline']: expect('unknown-'+action,call('POST','/requests/no/'+action,{},'a','unknown'),404,'not_found')
    check('request-privacy',not reqs('o'))
    for amt,n,expected in [(1000,3,[334,333,333]),(1,3,[1,0,0]),(10,3,[4,3,3]),(999,3,[333,333,333]),(5,3,[2,2,1])]:
        sp=expect('split-round-'+str(amt),call('POST','/splits',{'amount':amt,'participant_handles':['a','b','c'],'note':'🪷'},'a','s'+str(amt)),201)
        check('shares-'+str(amt),[s['amount'] for s in sp['shares']]==expected and [s['handle'] for s in sp['shares']]==['a','b','c'])
        check('split-requests-'+str(amt),[r['payer_handle'] for r in sp['requests']]==['b','c'] and [r['amount'] for r in sp['requests']]==expected[1:])
        if amt==1:
            for r in sp['requests']: expect('pay-zero-share',call('POST','/requests/'+r['request_id']+'/pay',{},r['payer_handle'],'zero'),201)
    sp=expect('split-only-self',call('POST','/splits',{'amount':1000000000,'participant_handles':['c']},'c','self'),201)
    check('split-only-self-empty',sp['requests']==[] and sp['shares']==[{'handle':'c','amount':1000000000}])
    sp=expect('split-caller-omitted',call('POST','/splits',{'amount':10,'participant_handles':['c','b']},'a','omitted'),201)
    check('omitted-shares',sp['shares']==[{'handle':'c','amount':5},{'handle':'b','amount':5}] and len(sp['requests'])==2)
    sp=expect('split-reorder',call('POST','/splits',{'amount':1,'participant_handles':['c','b','a']},'a','reorder'),201)
    check('split-first-extra',sp['shares'][0]=={'handle':'c','amount':1})
    check('split-conservation',sum(bal(u) for u in ['a','b','c','o'])==11000)
    check('no-request-feed',all('payment_id' in x and 'split_id' not in x for x in feed('a')))

def pagination():
    reset()
    for i in range(53): payment(str(i)); request(str(i))
    for path,field in [('/activity','payments'),('/requests','requests')]:
        r=call('GET',path,user='a')[1]; check('default-page-'+path,len(r[field])==50 and r['has_more'])
        r=call('GET',path+'?offset=50&limit=3',user='a')[1]; check('last-page-'+path,len(r[field])==3 and not r['has_more'])
        r=call('GET',path+'?offset=53',user='a')[1]; check('empty-page-'+path,r[field]==[] and not r['has_more'])
        rows=call('GET',path+'?limit=200',user='a')[1][field]
        check('newest-first-'+path,[x['created_at'] for x in rows]==sorted([x['created_at'] for x in rows],reverse=True))
    for user,direction,count in [('a','incoming',53),('a','outgoing',0),('b','incoming',0),('b','outgoing',53)]:
        rows=call('GET','/requests?limit=200&direction='+direction,user=user)[1]['requests']; check('direction-'+user+direction,len(rows)==count)
    rq=reqs('a')[0]; call('POST','/requests/'+rq['request_id']+'/decline',{},'a')
    check('status-filter',len(call('GET','/requests?status=declined',user='a')[1]['requests'])==1)

def concurrency():
    reset()
    cases=[('/payments',{'to_handle':'b','amount':100},'a'),('/requests',{'payer_handle':'a','amount':100},'b'),('/splits',{'amount':100,'participant_handles':['a','b','c']},'a'),('/settlements',{'transfers':[{'from_handle':'a','to_handle':'b','amount':100}]},'o')]
    rq=request('cpay')[1]; cases.append(('/requests/'+rq['request_id']+'/pay',{},'a'))
    for i,(path,body,user) in enumerate(cases):
        with cf.ThreadPoolExecutor(max_workers=50) as pool: rs=list(pool.map(lambda _:call('POST',path,body,user,'conc'+str(i)),range(50)))
        statuses=[r[0] for r in rs]; check('concurrent-idem-'+path,statuses.count(201)==1 and statuses.count(200)==49 and all(r[1]==rs[0][1] for r in rs),statuses)
        check('concurrent-timeout-'+path,max(r[3] for r in rs)<5,max(r[3] for r in rs))
    check('concurrent-conservation',sum(bal(u) for u in ['a','b','c','o'])==11000)
    f=copy.deepcopy(FIX); f['users'][0]['balance']=10; f['users'][1]['balance']=0; reset(f)
    with cf.ThreadPoolExecutor(max_workers=50) as pool: rs=list(pool.map(lambda i:payment('race'+str(i),amount=1),range(50)))
    check('overspend-race',[r[0] for r in rs].count(201)==10 and [r[0] for r in rs].count(409)==40,[r[0] for r in rs]); check('overspend-balances',bal('a')==0 and bal('b')==10)
    reset(); rq=request('race')[1]; path='/requests/'+rq['request_id']
    actions=[('pay','a'),('decline','a'),('cancel','b')]
    with cf.ThreadPoolExecutor(max_workers=50) as pool:
        rs=list(pool.map(lambda i:call('POST',path+'/'+actions[i%3][0],{},actions[i%3][1],'race'+str(i)),range(50)))
    check('request-terminal-race',all(r[0] in (200,201,409) for r in rs) and sum(r[0]==201 for r in rs)<=1,[r[0] for r in rs])
    check('request-race-conservation',bal('a')+bal('b')==11000)

def settlements():
    reset(); body={'transfers':[{'from_handle':'a','to_handle':'b','amount':20}]}
    expect('operator-required',call('POST','/settlements',body,'a','s'),403,'forbidden')
    for trs in [None,{},'x',[],[None],[1],[{}],body['transfers']*33]:
        expect('batch-shape-'+str(trs)[:30],call('POST','/settlements',{'transfers':trs},'o','invalid'),422,'validation_failed')
    for extra,code,status in [({'amount':True},'validation_failed',422),({'amount':0},'validation_failed',422),({'amount':1000000001},'validation_failed',422),({'note':None},'validation_failed',422),({'visibility':None},'validation_failed',422),({'to_handle':'a'},'self_payment',422),({'to_handle':'none'},'not_found',404)]:
        expect('batch-entry-'+str(extra),call('POST','/settlements',{'transfers':[{**body['transfers'][0],**extra}]},'o','invalid'),status,code)
    a={'from_handle':'c','to_handle':'a','amount':100}; invalid={'from_handle':'a','to_handle':'none','amount':1}
    expect('validation-before-funds',call('POST','/settlements',{'transfers':[a,invalid]},'o','invalid'),404,'not_found')
    expect('entry-input-order',call('POST','/settlements',{'transfers':[invalid,{'from_handle':'a','to_handle':'a','amount':1}]},'o','invalid'),404,'not_found')
    expect('entry-input-order-reverse',call('POST','/settlements',{'transfers':[{'from_handle':'a','to_handle':'a','amount':1},invalid]},'o','invalid'),422,'self_payment')
    before=state(); expect('net-insufficient',call('POST','/settlements',{'transfers':[a]},'o','failed'),409,'insufficient_funds'); check('failed-net-atomic',state()==before)
    circle={'transfers':[{'from_handle':'c','to_handle':'a','amount':100,'visibility':'private'},{'from_handle':'a','to_handle':'c','amount':100}]}
    out=expect('net-funded-cycle',call('POST','/settlements',circle,'o','failed'),201)
    check('net-unchanged-balances',bal('a')==10000 and bal('c')==0)
    check('settlement-members',len(out['payments'])==2 and all(p['settlement_id']==out['settlement_id'] and p['request_id'] is None and p['created_at']==out['committed_at'] for p in out['payments']))
    check('settlement-order',[p['from_handle'] for p in out['payments']]==['c','a'])
    check('settlement-private',out['payments'][0] not in feed('o') and out['payments'][0] in feed('a') and out['payments'][1] in feed('o'))
    check('settlement-replay-exact',expect('settlement-replay',call('POST','/settlements',circle,'o','failed'),200)==out)
    expect('settlement-precedence',call('POST','/settlements',{},'o','failed'),409,'idempotency_key_reuse')
    request('private-request'); check('operator-no-request-access',not reqs('o'))
    expect('32-entry-batch',call('POST','/settlements',{'transfers':body['transfers']*32},'o','32'),201)
    f=copy.deepcopy(FIX); del f['settlement_operator_ids']; reset(f)
    expect('no-default-operators',call('POST','/settlements',body,'o','s'),403,'forbidden')

def imports():
    reset()
    p=payment('persist-p',note='persist 🪷',visibility='private')[1]
    rq=request('persist-r')[1]; path='/requests/'+rq['request_id']+'/pay'
    pp=call('POST',path,{'visibility':'private'},'a','persist-pay')[1]
    sb={'amount':1,'participant_handles':['a','b','c']}; sp=call('POST','/splits',sb,'a','persist-sp')[1]
    sebody={'transfers':[{'from_handle':'c','to_handle':'a','amount':10},{'from_handle':'a','to_handle':'c','amount':10,'visibility':'private'}]}
    se=call('POST','/settlements',sebody,'o','persist-se')[1]
    expect('failed-export-key',payment('unclaimed',amount=1000000000),409,'insufficient_funds')
    snapshot=state(); check('export-envelope',snapshot.get('track')=='pocketful' and snapshot.get('format_version')==1 and isinstance(snapshot.get('state'),dict))
    check('export-readonly',state()==snapshot)
    # Do not print private state or tokens.
    check('no-plaintext-export',not any(u['password'] in json.dumps(snapshot) for u in FIX['users']))
    f=copy.deepcopy(FIX); f['users']=[{'id':'dest','email':'dest@example.com','password':'different pass','display_name':'Dest','handle':'dest','balance':99}]; f['settlement_operator_ids']=[]
    reset(f,DEST)
    dr=call('POST','/auth/login',{'email':'dest@example.com','password':'different pass'},base=DEST); dt=dr[1]['token']
    payment('source-after-export',amount=5)
    for n in range(2):
        expect('import-cross-process-'+str(n),call('POST','/_test/import',snapshot,base=DEST),204)
        check('import-exact-state-'+str(n),state(DEST)==snapshot)
        expect('old-dest-token-invalid',call('GET','/me',user=dt,base=DEST),401,'unauthenticated')
        expect('old-dest-login-invalid',call('POST','/auth/login',{'email':'dest@example.com','password':'different pass'},base=DEST),401,'unauthenticated')
        expect('import-token-valid',call('GET','/me',user='a',base=DEST),200)
        expect('import-hashed-login',call('POST','/auth/login',{'email':'a@example.com','password':'eight chars'},base=DEST),200)
        for path2,b,u,k,original in [('/payments',{'to_handle':'b','amount':10,'note':'persist 🪷','visibility':'private'},'a','persist-p',p),('/requests',{'payer_handle':'a','amount':10},'b','persist-r',rq),(path,{'visibility':'private'},'a','persist-pay',pp),('/splits',sb,'a','persist-sp',sp),('/settlements',sebody,'o','persist-se',se)]:
            check('import-replay-'+path2,expect('import-replay-status',call('POST',path2,b,u,k,base=DEST),200)==original)
        expect('import-failed-key-reusable',call('POST','/payments',{'to_handle':'b','amount':1},'a','unclaimed',base=DEST),201)
        expect('import-permissions',call('POST','/settlements',sebody,'o','new-op',base=DEST),201)
    before=state(DEST)
    for obj in [{},{'track':'wrong','format_version':1,'state':{}},{'track':'pocketful','format_version':2,'state':{}},{'track':'pocketful','format_version':1,'state':{}},{'track':'pocketful','format_version':1,'state':None}]:
        expect('invalid-import-'+str(obj),call('POST','/_test/import',obj,base=DEST),422,'validation_failed'); check('invalid-import-unchanged',state(DEST)==before)
    expect('malformed-import',call('POST','/_test/import',raw=b'{',base=DEST),400,'malformed_request')
    reset(FIX,DEST); expect('reset-imported-token',call('GET','/me',user='a',base=DEST),401,'unauthenticated')

def unusual():
    reset()
    for raw in [b'{"to_handle":"b","amount":1e999}',b'{"to_handle":"b","amount":1e-999}',b'{"to_handle":"b","amount":1000000000.00000001}',b'{"to_handle":"b","amount":1.0000000000000001}']:
        expect('exact-numeric-'+raw.decode(),call('POST','/payments',raw=raw,user='a',key=raw.decode()),422,'validation_failed')
    # Wholly invalid JSON numeric literals, unlike valid JSON exponent forms.
    for val in ['NaN','Infinity','-Infinity']:
        expect('non-json-number-'+val,call('POST','/payments',raw=('{"to_handle":"b","amount":'+val+'}').encode(),user='a',key=val),400,'malformed_request')
    for val in ['1e999','-1e999']:
        expect('unknown-large-numeric-'+val,call('POST','/payments',raw=('{"to_handle":"b","amount":1,"extra":'+val+'}').encode(),user='a',key='unknown'+val),201)
    # Numeric body equality has arbitrary decimal precision; unknown data still belongs to the body.
    for k,a,b in [('precision','100000000000000000001','100000000000000000002'),('precision-fraction','1.0000000000000001','1.0000000000000002')]:
        for i,val in enumerate([a,b]):
            expect('idem-'+k+str(i),call('POST','/payments',raw=('{"to_handle":"b","amount":1,"extra":'+val+'}').encode(),user='a',key=k),201 if i==0 else 409,None if i==0 else 'idempotency_key_reuse')

if __name__=='__main__':
    selected=sys.argv[1:] or ['basic','validation','money','idem','requests_splits','pagination','concurrency','settlements','imports','unusual']
    for name in selected:
        start=time.monotonic()
        try: globals()[name]()
        except Exception as e:
            check(name+'-uncaught',False,repr(e))
        print('DONE',name,round(time.monotonic()-start,3),flush=True)
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-'+'-'.join(selected)+'.json'),'w') as f: json.dump(out,f,indent=2,ensure_ascii=True)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
