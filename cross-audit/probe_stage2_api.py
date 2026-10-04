from probe_stage1 import *
from datetime import datetime,timezone,timedelta
import random

def me(u): return call('GET','/me',user=u)[1]
def auths(u,q=''):return call('GET','/authorizations'+q,user=u)[1]['authorizations']
def authorize(k='a',**extra):return call('POST','/authorizations',{'to_handle':'b','amount':2000,**extra},'a',k)
def capture(a,body=None,k='c',u='b'):return call('POST','/authorizations/'+a+'/capture',{} if body is None else body,u,k)
def void(a,u='a'):return call('POST','/authorizations/'+a+'/void',{},u)
def holds(a,total,held):
    m=me(a);check('wallet-'+a,m['balance']==m['total']==total and m['held']==held and m['available']==total-held,m)

def api_contract():
    reset();holds('a',10000,0)
    for p in ['/authorizations','/requests']:
        expect('api-negotiation-'+p,call('GET',p,user='a'),200)
        r=call('GET',p,headers={'Accept':'text/html'});check('html-negotiation-'+p,r[0]==200 and 'text/html' in r[2].get('Content-Type',''))
    for p in ['/','/split','/signup','/login','/authorizations','/requests']:
        r=call('GET',p,headers={'Accept':'text/html'});check('route-'+p,r[0]==200)
    for method,path,b in [('GET','/authorizations',None),('POST','/authorizations',{}),('POST','/authorizations/no/capture',{}),('POST','/authorizations/no/void',{})]:expect('auth-required-'+path,call(method,path,b,key='k'),401,'unauthenticated')
    a=expect('authorize',authorize(),201);aid=a['authorization_id']
    check('auth-response',a['from_handle']=='a' and a['to_handle']=='b' and a['amount']==2000 and a['captured_amount']==0 and a['remaining_amount']==2000 and a['status']=='open' and a['payment_id'] is None and a['payment_ids']==[])
    check('ttl-default',(datetime.fromisoformat(a['expires_at'])-datetime.fromisoformat(a['created_at'])).total_seconds()==600)
    holds('a',10000,2000);check('hold-no-feed',not feed('a'));check('auth-list-privacy',len(auths('a'))==1 and len(auths('b'))==1 and not auths('c'))
    for u in ['a','c','o']:expect('capture-permission-'+u,capture(aid,u=u),403,'forbidden')
    for u in ['b','c','o']:expect('void-permission-'+u,void(aid,u),403,'forbidden')
    for action in ['capture','void']:expect('unknown-'+action,call('POST','/authorizations/missing/'+action,{},'b','k'),404,'not_found')
    for amt in [0,-1,1.5,True,'1',None,1000000001]:expect('invalid-authorize-'+str(amt),authorize('bad'+str(amt),amount=amt),422,'validation_failed')
    for x in [None,False,[],201*'🪷']:expect('invalid-auth-note',authorize('bad-note',note=x),422,'validation_failed')
    for x in [None,True,'invalid']:expect('invalid-auth-visibility',authorize('bad-visibility',visibility=x),422,'validation_failed')
    expect('self-auth',authorize('self',to_handle='a'),422,'self_payment');expect('unknown-auth',authorize('unknown',to_handle='none'),404,'not_found')
    for key in [None,'']:expect('auth-key-required',authorize(key),400,'missing_idempotency_key')
    expect('auth-key-long',authorize('x'*256),422,'validation_failed')
    for key in [None,'']:expect('capture-key-required',capture(aid,k=key),400,'missing_idempotency_key')
    expect('capture-key-long',capture(aid,k='x'*256),422,'validation_failed')
    for body in [{'amount':0},{'amount':-1},{'amount':1.1},{'amount':True},{'amount':'1'},{'amount':None}]:expect('bad-capture-amount',capture(aid,body,k='bad'),422,'validation_failed')
    for x in [1,0,'false',None,[],{}]:expect('bad-final',capture(aid,{'amount':1,'final':x},k='final'),400,'malformed_request')
    expect('capture-exceeds',capture(aid,{'amount':2001},k='large'),422,'capture_exceeds_authorization')
    expect('auth-insufficient',authorize('insufficient',amount=8001),409,'insufficient_funds')
    expect('payment-uses-available',payment('held',amount=8001),409,'insufficient_funds')
    rq=request('held-r',amount=8001)[1];expect('request-uses-available',call('POST','/requests/'+rq['request_id']+'/pay',{},'a','held-pay'),409,'insufficient_funds')
    batch={'transfers':[{'from_handle':'a','to_handle':'b','amount':8001}]};expect('settlement-uses-available',call('POST','/settlements',batch,'o','held-se'),409,'insufficient_funds')
    p=expect('final-partial',capture(aid,{'amount':1500}),201)
    check('capture-fields',p['authorization_id']==aid and p['request_id'] is None and p['amount']==1500 and p['note']==a['note'] and p['visibility']==a['visibility'])
    holds('a',8500,0);holds('b',2500,0)
    ar=auths('a')[0];check('closed-fields',ar['captured_amount']==1500 and ar['remaining_amount']==0 and ar['status']=='captured' and ar['payment_ids']==[p['payment_id']] and ar['payment_id']==p['payment_id'])
    expect('second-final',capture(aid,k='second'),409,'authorization_not_open');expect('void-captured',void(aid),409,'authorization_not_open')
    check('capture-replay',expect('capture-replay-status',capture(aid,{'amount':1500}),200)==p)
    expect('capture-invalid-replay',capture(aid,{'amount':False}),409,'idempotency_key_reuse')
    check('auth-original-replay',expect('auth-original-replay-status',authorize(),200)==a)
    expect('auth-invalid-replay',authorize(amount=False),409,'idempotency_key_reuse')
    ordinary=payment('ordinary')[1];check('ordinary-null-auth',ordinary['authorization_id'] is None and me('a')['held']==0)
    for path in ['/authorizations']:
        for q in ['limit=0','limit=201','offset=-1','limit=1e2','limit=4.0','limit=%2B4','direction=bad','status=bad','limit='+'9'*5000]:expect('bad-auth-query-'+q[:25],call('GET',path+'?'+q,user='a'),422,'validation_failed')
        expect('large-auth-offset',call('GET',path+'?offset='+'9'*5000,user='a'),200)

def lifecycle():
    reset();a=authorize(note=' 🪷 ',visibility='private')[1];aid=a['authorization_id'];payments=[]
    for i,amt in enumerate([700,500]):payments.append(expect('nonfinal-'+str(i),capture(aid,{'amount':amt,'final':False},k='part'+str(i)),201))
    holds('a',8800,800);holds('b',2200,0)
    ar=auths('a')[0];check('nonfinal-fields',ar['status']=='open' and ar['captured_amount']==1200 and ar['remaining_amount']==800 and ar['payment_ids']==[p['payment_id'] for p in payments])
    expect('above-remainder',capture(aid,{'amount':801},k='large'),422,'capture_exceeds_authorization')
    v=expect('void-partial',void(aid),200);holds('a',8800,0)
    check('void-keeps-captures',v['status']=='voided' and v['captured_amount']==1200 and v['remaining_amount']==0 and v['payment_ids']==ar['payment_ids'])
    check('repeat-void',expect('repeat-void-status',void(aid),200)==v)
    expect('capture-voided',capture(aid,k='after-void'),409,'authorization_not_open')
    check('capture-private',all(p in feed('a') and p in feed('b') and p not in feed('c') for p in payments))
    a2=authorize('entire',amount=100)[1];p=capture(a2['authorization_id'],{'final':False},k='entire')[1]
    check('full-nonfinal-closes',next(x for x in auths('a') if x['authorization_id']==a2['authorization_id'])['status']=='captured')
    expect('empty-vs-explicit-body',capture(a2['authorization_id'],{'amount':100,'final':False},k='entire'),409,'idempotency_key_reuse')
    check('conservation',sum(me(u)['total'] for u in ['a','b','c','o'])==11000)
    # Short lifetime expiry with no requests across the deadline.
    f=copy.deepcopy(FIX);f['authorization_ttl_seconds']=1;reset(f)
    a=authorize()[1];aid=a['authorization_id'];p=capture(aid,{'amount':500,'final':False})[1]
    time.sleep(1.3)
    holds('a',9500,0);ar=auths('a','?status=expired')[0]
    check('expiry-keeps-capture',ar['status']=='expired' and ar['remaining_amount']==0 and ar['captured_amount']==500 and ar['payment_ids']==[p['payment_id']])
    check('expiry-not-open',not auths('a','?status=open'))
    expect('expired-capture',capture(aid,k='late'),409,'authorization_expired');expect('expired-void',void(aid),409,'authorization_not_open')
    check('expired-original-replay',expect('expired-replay-status',capture(aid,{'amount':500,'final':False}),200)==p)

def seed_import():
    f=copy.deepcopy(FIX);f['authorization_ttl_seconds']=7
    future=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat();past=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
    f['authorizations']=[{'id':'seed-'+s,'from_user_id':'u_a','to_user_id':'u_b','amount':100,'note':'seed','visibility':'public','status':s,'expires_at':past if s=='expired' else future} for s in ['open','captured','voided','expired']]
    reset(f);holds('a',10000,100);check('seed-statuses',{x['status'] for x in auths('a')}=={'open','captured','voided','expired'})
    fbad=copy.deepcopy(f);fbad['authorizations'][0]['amount']=10001;before=state();expect('overheld-seed',call('POST','/_test/reset',fbad),422,'validation_failed');check('overheld-atomic',state()==before)
    for ttl in [0,-1,1.5,True,'1',None]:
        bad=copy.deepcopy(FIX);bad['authorization_ttl_seconds']=ttl
        r=call('POST','/_test/reset',bad);check('invalid-ttl-'+str(ttl),r[0]==422,{'status':r[0],'body':r[1]});check('invalid-ttl-atomic',state()==before)
    a=authorize('ttl')[1];check('custom-ttl',(datetime.fromisoformat(a['expires_at'])-datetime.fromisoformat(a['created_at'])).total_seconds()==7)
    p=capture(a['authorization_id'],{'amount':700,'final':False},k='migrate')[1]
    snap=state();expect('auth-import',call('POST','/_test/import',snap,base=DEST),204);check('auth-import-exact',state(DEST)==snap)
    check('import-auth-original',expect('import-auth-replay',call('POST','/authorizations',{'to_handle':'b','amount':2000},'a','ttl',base=DEST),200)==a)
    check('import-capture-original',expect('import-capture-replay',call('POST','/authorizations/'+a['authorization_id']+'/capture',{'amount':700,'final':False},'b','migrate',base=DEST),200)==p)
    expect('import-remainder-capture',call('POST','/authorizations/'+a['authorization_id']+'/capture',{},'b','remainder',base=DEST),201)
    # Import corrupt state and ensure all target monetary invariants are transactional.
    if 'authorizations' in snap['state']:
        for field,val in [('note','x'*201),('amount',1000000001),('from_user_id','missing'),('captured_amount',999999)]:
            bad=copy.deepcopy(snap);records=bad['state']['authorizations'];rec=next(iter(records.values())) if isinstance(records,dict) else records[0];rec[field]=val
            before=state();expect('invalid-authorization-state-'+field,call('POST','/_test/import',bad),422,'validation_failed');check('invalid-auth-import-atomic',state()==before)

def concurrency_auth():
    reset()
    with cf.ThreadPoolExecutor(max_workers=50) as pool:rs=list(pool.map(lambda _:authorize('race'),range(50)))
    check('concurrent-auth-idem',[r[0] for r in rs].count(201)==1 and [r[0] for r in rs].count(200)==49 and all(r[1]==rs[0][1] for r in rs));holds('a',10000,2000)
    aid=rs[0][1]['authorization_id']
    with cf.ThreadPoolExecutor(max_workers=50) as pool:rs=list(pool.map(lambda _:capture(aid,{'amount':500,'final':False},k='race'),range(50)))
    check('concurrent-capture-idem',[r[0] for r in rs].count(201)==1 and [r[0] for r in rs].count(200)==49 and all(r[1]==rs[0][1] for r in rs));holds('a',9500,1500)
    with cf.ThreadPoolExecutor(max_workers=50) as pool:rs=list(pool.map(lambda i:capture(aid,{'amount':100,'final':False},k='many'+str(i)),range(50)))
    check('concurrent-limit',[r[0] for r in rs].count(201)==15 and all(r[0] in [201,409] for r in rs),[r[0] for r in rs]);holds('a',8000,0);holds('b',3000,0)
    reset()
    with cf.ThreadPoolExecutor(max_workers=50) as pool:rs=list(pool.map(lambda i:authorize('oversub'+str(i),amount=1000),range(50)))
    check('concurrent-hold-limit',[r[0] for r in rs].count(201)==10 and [r[0] for r in rs].count(409)==40);holds('a',10000,10000)
    # Authorization pagination and filters.
    reset()
    for i in range(53): authorize(str(i),amount=1)
    r=call('GET','/authorizations',user='a')[1];check('authorization-default-page',len(r['authorizations'])==50 and r['has_more'])
    r=call('GET','/authorizations?limit=3&offset=50',user='a')[1];check('authorization-last-page',len(r['authorizations'])==3 and not r['has_more'])
    check('auth-direction',not auths('a','?direction=incoming') and len(auths('b','?direction=incoming&limit=200'))==53)

for group in [api_contract,lifecycle,seed_import,concurrency_auth]:
    try:group()
    except Exception as e:check(group.__name__+'-uncaught',False,repr(e))
    print('DONE',group.__name__,flush=True)
out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-stage2-api.json'),'w') as f:json.dump(out,f,indent=2)
print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
