"""Independent HTTP temporal oracle; does not import implementation/checks."""
from probe_stage1 import *
from datetime import datetime,timezone,timedelta
from urllib.parse import urlencode
import random

D0='2020-01-01T00:00:00+00:00';D1='2020-01-02T00:00:00+00:00';D2='2020-01-03T00:00:00+00:00';D3='2020-01-04T00:00:00+00:00';D4='2020-01-05T00:00:00+00:00'
def instant(s):return datetime.fromisoformat(s.replace('Z','+00:00'))
def stamp():return datetime.now(timezone.utc).isoformat()
def shift(s,delta):return (instant(s)+timedelta(seconds=delta)).isoformat()
def get(path,u='a',**q):return call('GET',path+('?' + urlencode(q) if q else ''),user=u)
def me(u='a',**q):return get('/me',u,**q)[1]
def statement(u='a',**q):return get('/statement',u,**q)
def revisions(p,u='a'):return get('/payments/'+p+'/revisions',u)
def correct(p='p_b',u='a',key='correction',**x):return call('POST','/payments/'+p+'/corrections',{'expected_revision':1,'amount':150,'effective_at':D0,'reason':'fix',**x},u,key)
def histfixture():
    f=copy.deepcopy(FIX)
    for u,b in zip(f['users'],[730,550,720,0]):u['balance']=b
    f['payments']=[
      {'id':'p_b','from_user_id':'u_a','to_user_id':'u_b','amount':100,'note':'one','visibility':'private','created_at':D1},
      {'id':'p_a','from_user_id':'u_b','to_user_id':'u_a','amount':30,'note':'two','visibility':'public','created_at':D1},
      {'id':'p_c','from_user_id':'u_a','to_user_id':'u_c','amount':200,'note':'three','visibility':'public','created_at':D2},
      {'id':'p_pub','from_user_id':'u_b','to_user_id':'u_c','amount':20,'note':'other','visibility':'public','created_at':D3}]
    return f
def shape(m,total,held=0):return m['balance']==m['total']==total and m['held']==held and m['available']==total-held
def without_snapshot(s):return {k:v for k,v in s.items() if k!='snapshot'}

def baseline():
    f=histfixture();reset(f)
    check('seed-net-not-replayed',[bal(u) for u in ['a','b','c']]==[730,550,720])
    for t,v in [(D0,1000),(D1,930),(D2,730),(D4,730),('2090-01-01T00:00:00Z',730)]:
        m=me(as_of=t);check('asof-inclusive-'+t,shape(m,v) and m['as_of']==t,m)
    alternate='2020-01-02T02:00:00+02:00';m=me(as_of=alternate,known_at='2090-01-01T01:00:00+01:00');check('exact-query-echo',m['as_of']==alternate and m['known_at']=='2090-01-01T01:00:00+01:00' and m['balance']==930,m)
    for p in f['payments']:
        rs=expect('seed-revisions',revisions(p['id'],p['from_user_id'][2:]),200)['revisions'];check('revision-one',len(rs)==1 and rs[0]['amount']==p['amount'] and rs[0]['revision']==1 and rs[0]['reason']=='' and rs[0]['effective_at']==rs[0]['recorded_at']==p['created_at'],rs)
    full=expect('statement-default',statement(),200);es=full['entries'];check('default-full-statement',full['opening_balance']==1000 and full['closing_balance']==730 and [e['payment']['payment_id'] for e in es]==['p_a','p_b','p_c'] and [e['balance_after'] for e in es]==[1030,930,730] and [e['delta'] for e in es]==[30,-100,-200] and not full['has_more'],full)
    check('snapshot-present',isinstance(full.get('snapshot'),str) and bool(full['snapshot']))
    for e in es:check('original-statement-metadata',e['revision']==1 and e['effective_at']==e['recorded_at']==e['payment']['created_at'],e)
    win=statement(**{'from':D1,'to':D2})[1];check('half-open',win['opening_balance']==1000 and win['closing_balance']==930 and len(win['entries'])==2,win)
    for offset in [0,1,2,3,99]:
        page=statement(limit=1,offset=offset,**{'from':D0,'to':D4})[1];check('page-balances-'+str(offset),page['opening_balance']==1000 and page['closing_balance']==730 and page['entries']==es[offset:offset+1] and page['has_more']==(offset+1<len(es)),page)
    check('statement-public-not-mine',not statement('o')[1]['entries'])
    expect('statement-auth',call('GET','/statement'),401,'unauthenticated')
    expect('revisions-auth',revisions('p_b',None),401,'unauthenticated')
    expect('revisions-receiver',revisions('p_b','b'),200)
    expect('revisions-hidden-public',revisions('p_a','c'),404,'not_found')
    expect('revisions-unknown',revisions('unknown'),404,'not_found')
    for bad in ['', '2020-01-01','2020-01-01T00:00:00','no','2020-02-30T00:00:00Z','2020-01-01T24:00:00Z','2020-01-01T00:00:00+25:00']:
        for field,path in [('as_of','/me'),('known_at','/me'),('from','/statement'),('to','/statement'),('known_at','/statement')]:expect('bad-instant-'+field+'-'+bad,get(path,**{field:bad}),422,'validation_failed')
    for field,vals in [('limit',['0','201','4.0','1e2','+4','9'*5000]),('offset',['-1','4.0','1e2','+4'])]:
        for val in vals:expect('bad-pagination-'+field,get('/statement',**{field:val}),422,'validation_failed')
    huge=statement(offset='9'*5000)[1];check('huge-offset',huge['entries']==[] and not huge['has_more'],huge)
    check('unknown-query-ignored',without_snapshot(statement(ignore='x')[1])==without_snapshot(full))
    expect('new-user',call('POST','/auth/signup',{'email':'new@example.com','password':'eight chars','display_name':'New'}),201)
    nr=call('POST','/auth/login',{'email':'new@example.com','password':'eight chars'})[1];TOK['new']=nr['token'];check('new-opening-zero',me('new',as_of=D0)['balance']==statement('new')[1]['opening_balance']==0)
    before=state();bad=histfixture();bad['payments'][0]['created_at']='2090-01-01T00:00:00Z';expect('future-seed',call('POST','/_test/reset',bad),422,'validation_failed');check('future-seed-atomic',state()==before)
    reset();f=copy.deepcopy(FIX);f['payments']=[{'id':'omitted','from_user_id':'u_a','to_user_id':'u_b','amount':10,'note':'','visibility':'public'}];reset(f);seed=feed('a')[0];p=payment('after')[1];check('reset-time-before-write',instant(seed['created_at'])<=instant(p['created_at']));check('omitted-seed-revisions',revisions('omitted')[1]['revisions'][0]['effective_at']==seed['created_at'])

def corrections():
    reset(histfixture());original=feed('a');before=state()
    for user in ['b','c','o']:expect('correction-forbidden',correct(u=user),403,'forbidden')
    expect('correction-no-token',correct(u=None),401,'unauthenticated');expect('correction-unknown',correct(p='unknown'),404,'not_found')
    for key in [None,'']:expect('correction-key-required',correct(key=key),400,'missing_idempotency_key')
    expect('correction-key-long',correct(key='x'*256),422,'validation_failed')
    body={'expected_revision':1,'amount':150,'effective_at':D0,'reason':'fix'}
    for field in body:
        b=dict(body);del b[field];expect('correction-required-'+field,call('POST','/payments/p_b/corrections',b,'a','bad'),422,'validation_failed')
    for fld,vals in [('expected_revision',[0,-1,1.5,True,'1',None,[],{}]),('amount',[-1,1000000001,1.5,True,'1',None,[]]),('reason',['','x'*201,None,True,1,[]]),('effective_at',['',D0[:10],'2020-01-01T00:00:00','2090-01-01T00:00:00Z',1,None,[]])]:
        for val in vals:expect('correction-invalid-'+fld+'-'+str(val)[:25],correct(key='bad',**{fld:val}),422,'validation_failed')
    for rawamount in ['1.0000000000000001','1e400','1e-400','9'*5000]:
        raw=('{'+'"expected_revision":1,"amount":'+rawamount+',"reason":"fix","effective_at":"'+D0+'"}').encode();expect('exact-correction-amount',call('POST','/payments/p_b/corrections',user='a',key='raw',raw=raw),422,'validation_failed')
    check('failed-corrections-atomic',state()==before)
    c=expect('correction-create',correct(),201);check('revision-receipt',c['payment_id']=='p_b' and c['revision']==2 and c['amount']==150 and c['effective_at']==D0 and c['reason']=='fix' and instant(c['recorded_at'])>instant(D1),c)
    check('increase-delta',[bal(u) for u in ['a','b','c']]==[680,600,720]);check('original-feed-immutable',feed('a')==original)
    known=me(as_of=D4,known_at=D4);check('old-knowledge-original',shape(known,730),known)
    m=me(as_of=D0,known_at=c['recorded_at']);check('knowledge-inclusive-backdate',shape(m,850),m)
    m=me(as_of=D0,known_at=shift(c['recorded_at'],-.000001));check('knowledge-before-revision',shape(m,1000),m)
    m=me(as_of=D4,known_at=D0);check('unknown-payments-contribute-nothing',shape(m,1000),m)
    s=statement(**{'from':D0,'to':D1})[1];check('correction-moves-into-window',len(s['entries'])==1 and s['entries'][0]['revision']==2 and s['entries'][0]['payment']['amount']==150 and s['closing_balance']==850,s)
    expect('stale',correct(key='stale'),409,'stale_revision')
    z=expect('reverse-zero',correct(key='zero',expected_revision=2,amount=0,effective_at=D2,reason='reversal'),201);check('decrease-delta',[bal(u) for u in ['a','b','c']]==[830,450,720]);check('recorded-strict',instant(z['recorded_at'])>instant(c['recorded_at']))
    es=statement()[1]['entries'];check('zero-entry-and-order',[e['payment']['payment_id'] for e in es]==['p_a','p_b','p_c'] and [e['delta'] for e in es]==[30,0,-200] and es[1]['revision']==3,es)
    check('correction-moves-out-window',statement(**{'from':D0,'to':D1})[1]['entries']==[])
    replay=expect('correction-old-replay',correct(),200);check('correction-original-response',replay==c)
    expect('replay-before-validation',correct(amount=-1),409,'idempotency_key_reuse')
    rs=revisions('p_b')[1]['revisions'];check('revision-list',len(rs)==3 and [x['revision'] for x in rs]==[1,2,3] and rs[1]==c and rs[2]==z,rs)
    check('original-unchanged-after-reversal',feed('a')==original)
    for t in [D0,D1,D2,D3,'2090-01-01T00:00:00Z']:
        for k in [D0,D1,D4,c['recorded_at'],z['recorded_at']]:check('historical-conservation',sum(me(u,as_of=t,known_at=k)['balance'] for u in ['a','b','c','o'])==2000)
    # API receipt replay remains original even after its payment is corrected.
    p=payment('live',amount=10)[1];expect('correct-live',correct(p=p['payment_id'],amount=5,effective_at=p['created_at'],key='live-c'),201);check('payment-replay-original',payment('live',amount=10)[1]==p)

def affordability():
    # Opening A=100 B=0 C=0. A pays B100; B pays C100 later. Refund currently cannot debit B.
    f=copy.deepcopy(FIX)
    for u,b in zip(f['users'],[0,0,100,0]):u['balance']=b
    f['payments']=[{'id':'ab','from_user_id':'u_a','to_user_id':'u_b','amount':100,'note':'','visibility':'public','created_at':D1},{'id':'bc','from_user_id':'u_b','to_user_id':'u_c','amount':100,'note':'','visibility':'public','created_at':D2}]
    reset(f);before=state();expect('current-insufficient-precedence',correct(p='ab',amount=0),409,'insufficient_funds');check('insufficient-atomic',state()==before)
    # Money returns to B now, so refund is currently affordable but would overdraft B at Jan3.
    expect('fund-receiver',call('POST','/payments',{'to_handle':'b','amount':100},'c','return'),201);before=state();expect('historical-overdraft-refund',correct(p='ab',amount=0),409,'historical_overdraft');check('historical-failure-atomic',state()==before)
    # Retry failed key with a harmless time/amount is a first use.
    expect('failed-correction-key-reusable',correct(p='ab',amount=100,effective_at=D1),201)
    reset(f);before=state();expect('move-credit-after-spend',correct(p='ab',amount=100,effective_at=D3),409,'historical_overdraft');check('moving-time-failure-atomic',state()==before)
    # At one timestamp, credit and debit combine. B's id-sorted debit comes first, but net=0.
    f['payments'][1]['created_at']=D1;f['payments'][1]['id']='a_debit';f['payments'][0]['id']='z_credit';reset(f)
    expect('combined-boundary-valid',correct(p='z_credit',amount=100,effective_at=D1),201)

def snapshots_concurrency():
    reset(histfixture());s=statement(limit=1)[1];token=s['snapshot'];full=statement(snapshot=token,limit=200)[1]
    for field in ['from','to','known_at']:expect('snapshot-query-exclusion-'+field,statement(snapshot=token,**{field:D0}),422,'validation_failed')
    expect('snapshot-other-user',statement('b',snapshot=token),404,'not_found');expect('snapshot-unknown',statement(snapshot='unknown'),404,'not_found')
    check('snapshot-unknown-query-ignored',statement(snapshot=token,limit=200,unknown='x')[1]==full)
    with cf.ThreadPoolExecutor(max_workers=50) as pool:
        rs=list(pool.map(lambda i:correct(key='same',amount=150),range(50)))
    check('identical-corrections-status',[r[0] for r in rs].count(201)==1 and [r[0] for r in rs].count(200)==49,[r[0] for r in rs]);check('identical-corrections-body',all(r[1]==rs[0][1] for r in rs))
    with cf.ThreadPoolExecutor(max_workers=20) as pool:
        rs=list(pool.map(lambda i:correct(key='race'+str(i),expected_revision=2,amount=160+i),range(20)))
    check('competing-corrections-one-success',sum(r[0]==201 for r in rs)==1 and sum(r[0]==409 and r[1]['error']['code']=='stale_revision' for r in rs)==19,[r[0] for r in rs])
    payment('new-after-snapshot');check('snapshot-frozen-after-concurrent-corrections',statement(snapshot=token,limit=200)[1]==full)
    for off in [0,1,2,3,100]:
        p=statement(snapshot=token,limit=1,offset=off)[1];check('snapshot-page-'+str(off),p['entries']==full['entries'][off:off+1] and p['opening_balance']==full['opening_balance'] and p['closing_balance']==full['closing_balance'] and p['has_more']==(off+1<len(full['entries'])))
    reset();expect('snapshot-invalid-after-reset',statement(snapshot=token),404,'not_found')

def linked_and_import():
    reset();settle=call('POST','/settlements',{'transfers':[{'from_handle':'a','to_handle':'b','amount':100},{'from_handle':'b','to_handle':'c','amount':100}]},'o','net')[1]
    for p in settle['payments']:
        rs=revisions(p['payment_id'],p['from_handle'])[1]['revisions'];check('settlement-original-times',rs[0]['effective_at']==rs[0]['recorded_at']==settle['committed_at']);expect('settlement-immutable',correct(p=p['payment_id'],u=p['from_handle'],amount=50,effective_at=p['created_at']),422,'linked_payment_immutable')
    a=call('POST','/authorizations',{'to_handle':'b','amount':100},'a','auth')[1];p=call('POST','/authorizations/'+a['authorization_id']+'/capture',{'amount':30,'final':False},'b','cap')[1]
    expect('capture-immutable',correct(p=p['payment_id'],amount=20,effective_at=p['created_at']),422,'linked_payment_immutable')
    # genuine stage3 snapshot/revision/holds/idempotency state must cross processes.
    direct=payment('direct')[1];c=correct(p=direct['payment_id'],amount=5,effective_at=direct['created_at'])[1];s=statement()[1];export=state();expect('stage3-import',call('POST','/_test/import',export,base=DEST),204)
    check('stage3-export-identical',state(DEST)==export)
    imported=call('GET','/statement?'+urlencode({'snapshot':s['snapshot']}),user='a',base=DEST);check('imported-snapshot',imported[1]==s,{'actual':imported[1],'expected':s})
    check('imported-correction-replay',call('POST','/payments/'+direct['payment_id']+'/corrections',{'expected_revision':1,'amount':5,'effective_at':direct['created_at'],'reason':'fix'},'a','correction',base=DEST)[1]==c)
    check('imported-balances',call('GET','/me',user='a',base=DEST)[1]==me())

def holds_history():
    reset();before=shift(stamp(),-2)
    a=call('POST','/authorizations',{'to_handle':'b','amount':2000},'a','hold')[1];aid=a['authorization_id'];t0=a['created_at'];check('hold-open-closed-at',a.get('closed_at','MISSING') is None,a)
    time.sleep(1.05);p=call('POST','/authorizations/'+aid+'/capture',{'amount':700,'final':False},'b','partial')[1];t1=p['created_at'];time.sleep(1.05)
    v=call('POST','/authorizations/'+aid+'/void',{},'a')[1];t2=v.get('closed_at');check('void-closed-at',isinstance(t2,str),v)
    for t,total,held in [(before,10000,0),(t0,10000,2000),(t1,9300,1300),(t2,9300,0)]:
        if t:check('hold-history-'+str(t),shape(me(as_of=t),total,held),me(as_of=t))
    if t2:
        check('hold-before-capture-known',shape(me(as_of=t2,known_at=t0),10000,2000),me(as_of=t2,known_at=t0))
        check('hold-after-capture-before-void-known',shape(me(as_of=t2,known_at=t1),9300,1300),me(as_of=t2,known_at=t1))
    check('hold-unknown-before-creation',shape(me(as_of='2090-01-01T00:00:00Z',known_at=before),10000,0))
    check('statement-only-capture',len(statement()[1]['entries'])==1 and statement()[1]['entries'][0]['payment']['authorization_id']==aid)
    # final capture event and future expiry even before wall clock deadline.
    a=call('POST','/authorizations',{'to_handle':'b','amount':1000},'a','hold2')[1];aid=a['authorization_id'];time.sleep(1.05);p=call('POST','/authorizations/'+aid+'/capture',{'amount':400},'b','final')[1]
    ar=next(x for x in get('/authorizations')[1]['authorizations'] if x['authorization_id']==aid);check('final-close-time',ar['closed_at']==p['created_at'],ar)
    check('final-releases-historical',shape(me(as_of=p['created_at']),8900,0))
    f=copy.deepcopy(FIX);f['authorization_ttl_seconds']=1;reset(f);a=call('POST','/authorizations',{'to_handle':'b','amount':1000},'a','expiry')[1];aid=a['authorization_id'];snap=statement()[1]
    check('future-expiry',shape(me(as_of=a['expires_at'],known_at=a['created_at']),10000,0));check('just-before-expiry',shape(me(as_of=shift(a['expires_at'],-.000001)),10000,1000))
    time.sleep(1.1);ar=get('/authorizations')[1]['authorizations'][0];check('expiry-closed-at-deadline',ar['status']=='expired' and ar['closed_at']==a['expires_at'],ar);check('expiry-snapshot-unchanged',statement(snapshot=snap['snapshot'])[1]==snap)
    # Seed creation supplied and defaulted.
    f=copy.deepcopy(FIX);f['authorizations']=[{'id':'seed','from_user_id':'u_a','to_user_id':'u_b','amount':1000,'note':'','visibility':'public','status':'open','created_at':D1,'expires_at':'2090-01-01T00:00:00Z'}];reset(f)
    check('seed-hold-before',shape(me(as_of=D0),10000,0));check('seed-hold-at',shape(me(as_of=D1),10000,1000));check('seed-known-before',shape(me(as_of=D2,known_at=D0),10000,0))
    del f['authorizations'][0]['created_at'];reset(f);a=get('/authorizations')[1]['authorizations'][0];check('seed-default-created-at-reset',instant(a['created_at'])>instant(D4) and shape(me(as_of=D4),10000,0))

def held_overdraft():
    # A starts100, hold80, later releases, then pays B50. Backdating payment into hold is invalid though currently affordable.
    f=copy.deepcopy(FIX);f['users'][0]['balance']=100;f['users'][1]['balance']=100;reset(f)
    a=call('POST','/authorizations',{'to_handle':'b','amount':80},'a','reserve')[1];time.sleep(1.05);v=call('POST','/authorizations/'+a['authorization_id']+'/void',{},'a')[1];time.sleep(1.05);p=payment('late',amount=50)[1]
    before=state();expect('historical-available-overdraft',correct(p=p['payment_id'],amount=50,effective_at=a['created_at']),409,'historical_overdraft');check('held-history-failure-atomic',state()==before)
    # Exact release boundary is affordable, all event effects combine.
    expect('release-boundary-valid',correct(p=p['payment_id'],amount=50,effective_at=v['closed_at']),201)
    # New current hold leaves no current available for increased debit, even if history also invalid.
    call('POST','/authorizations',{'to_handle':'b','amount':50},'a','reserve2');expect('current-available-precedence',correct(p=p['payment_id'],key='larger',expected_revision=2,amount=60,effective_at=a['created_at']),409,'insufficient_funds')

def oracle():
    rng=random.Random(3094);f=copy.deepcopy(FIX)
    for u in f['users']:u['balance']=100000
    payments=[];balances={u['id']:100000 for u in f['users']};history={}
    for i in range(20):
        src,dst=rng.sample(list(balances),2);amount=rng.randrange(0,1000)+1;t=shift(D0,rng.randrange(0,10)*3600)
        p={'id':'r%02d'%i,'from_user_id':src,'to_user_id':dst,'amount':amount,'note':'oracle','visibility':'private','created_at':t};payments.append(p);balances[src]-=amount;balances[dst]+=amount;history[p['id']]=[{'revision':1,'amount':amount,'effective_at':t,'recorded_at':t}]
    f['payments']=payments
    for u in f['users']:u['balance']=balances[u['id']]
    reset(f)
    for i in range(25):
        p=rng.choice(payments);rs=history[p['id']];r=correct(p=p['id'],u=p['from_user_id'][2:],key='oracle'+str(i),expected_revision=len(rs),amount=rng.randrange(0,1500),effective_at=shift(D0,rng.randrange(0,10)*3600));body=expect('oracle-correction',r,201)
        if r[0]==201:rs.append(body)
    for known in [D0,D1,stamp()]+[history[p['id']][-1]['recorded_at'] for p in payments[:3]]:
        selected=[]
        for p in payments:
            elig=[r for r in history[p['id']] if instant(r['recorded_at'])<=instant(known)]
            if elig:selected.append((p,elig[-1]))
        for u in ['a','b','c','o']:
            uid='u_'+u
            for asof in [D0,shift(D0,4*3600),D1]:
                want=100000+sum((1 if p['to_user_id']==uid else -1)*r['amount'] for p,r in selected if uid in [p['from_user_id'],p['to_user_id']] and instant(r['effective_at'])<=instant(asof));check('oracle-balance',me(u,as_of=asof,known_at=known)['balance']==want)
            start=shift(D0,2*3600);end=shift(D0,8*3600);mine=sorted([(p,r) for p,r in selected if uid in [p['from_user_id'],p['to_user_id']]],key=lambda z:(instant(z[1]['effective_at']),z[0]['id']))
            current=100000;expected=[];opening=None
            for p,r in mine:
                delta=(1 if p['to_user_id']==uid else -1)*r['amount']
                if instant(r['effective_at'])<instant(start):current+=delta
            opening=current
            for p,r in mine:
                if instant(start)<=instant(r['effective_at'])<instant(end):
                    delta=(1 if p['to_user_id']==uid else -1)*r['amount'];current+=delta;expected.append((p['id'],r['revision'],delta,current))
            s=statement(u,known_at=known,**{'from':start,'to':end})[1];actual=[(e['payment']['payment_id'],e['revision'],e['delta'],e['balance_after']) for e in s['entries']];check('oracle-statement',s['opening_balance']==opening and s['closing_balance']==current and actual==expected,{'actual':actual,'expected':expected} if actual!=expected else None)

if __name__=='__main__':
    groups=sys.argv[1:] or ['baseline','corrections','affordability','snapshots_concurrency','linked_and_import','holds_history','held_overdraft','oracle']
    for g in groups:
        try:globals()[g]()
        except Exception as e:check(g+'-uncaught',False,str(e))
        print('DONE',g,flush=True)
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-stage3-'+('-'.join(groups))+'.json'),'w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
