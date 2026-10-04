from probe_stage3 import *

def refund(pid,amount=10,u='b',key='refund',**extra):return call('POST','/payments/'+pid+'/refunds',{'amount':amount,**extra},u,key)
def item(p,amount=0,revision=1,effective=None,**x):return {'payment_id':p['payment_id'],'expected_revision':revision,'amount':amount,'effective_at':effective or p['created_at'],'reason':'batch fix',**x}
def batch(items,u='o',key='batch',**x):return call('POST','/correction-batches',{'corrections':items,**x},u,key)
def ordinary_receipts():
    reset();p=payment('original',amount=100,note='  é 🪷  ',visibility='private')[1];pid=p['payment_id'];check('ordinary-refund-null',p.get('refund_of','MISSING') is None)
    for user in [None,'a','c','o']:expect('refund-auth-'+str(user),refund(pid,u=user),401 if user is None else 403,'unauthenticated' if user is None else 'forbidden')
    expect('refund-unknown',refund('missing'),404,'not_found')
    for k in [None,'']:expect('refund-key-required',refund(pid,key=k),400,'missing_idempotency_key')
    expect('refund-key-long',refund(pid,key='x'*256),422,'validation_failed')
    for amount in [0,-1,1.5,True,'1',None,[],1000000001]:expect('refund-invalid-amount-'+str(amount),refund(pid,amount,key='bad'),422,'validation_failed')
    expect('refund-amount-required',call('POST','/payments/'+pid+'/refunds',{},'b','bad'),422,'validation_failed')
    for value in ['1.0000000000000001','1e400','1e-400','9'*5000]:expect('refund-exact-number',call('POST','/payments/'+pid+'/refunds',user='b',key='raw',raw=('{"amount":'+value+'}').encode()),422,'validation_failed')
    before=state();expect('refund-too-large',refund(pid,101,key='too-large'),422,'refund_exceeds_payment');check('exceeds-atomic',state()==before)
    r=expect('refund-create',refund(pid,40,unknown={'ignored':True}),201);check('refund-receipt',r['from_user_id']=='u_b' and r['to_user_id']=='u_a' and r['from_handle']=='b' and r['to_handle']=='a' and r['refund_of']==pid and r['request_id'] is None and r['authorization_id'] is None and r['note']==p['note'] and r['visibility']==p['visibility'] and r['amount']==40,r)
    check('refund-balances',[bal(u) for u in ['a','b']]==[9940,1060]);check('refund-private-feed',not any(x['payment_id']==r['payment_id'] for x in feed('c')))
    replay=expect('refund-replay',refund(pid,40,unknown={'ignored':True}),200);check('refund-original-response',r==replay)
    expect('refund-key-conflict-before-validation',refund(pid,-1),409,'idempotency_key_reuse')
    expect('refund-of-refund',refund(r['payment_id'],1,u='a',key='nested'),422,'invalid_refund_target')
    expect('correct-refund-immutable',correct(p=r['payment_id'],u='b',amount=1,effective_at=r['created_at']),422,'linked_payment_immutable')
    expect('correct-below-refunded',correct(p=pid,amount=39,effective_at=p['created_at']),422,'refund_exceeds_payment')
    expect('correct-to-refunded',correct(p=pid,amount=40,effective_at=p['created_at']),201)
    expect('refund-current-corrected-cap',refund(pid,1,key='more'),422,'refund_exceeds_payment')
    expect('correct-increase-capacity',correct(p=pid,key='increase',expected_revision=2,amount=80,effective_at=p['created_at']),201)
    expect('refund-new-capacity',refund(pid,40,key='more'),201);expect('refund-cumulative-exceeds',refund(pid,1,key='extra'),422,'refund_exceeds_payment')
    check('original-payment-retry-unchanged',payment('original',amount=100,note=p['note'],visibility='private')[1]==p)
    check('refund-old-replay-after-correction',refund(pid,40,unknown={'ignored':True})[1]==r)
    ss=statement()[1];check('refund-statement-opposite',any(e['payment']['payment_id']==r['payment_id'] and e['delta']==40 for e in ss['entries']))

def targets_funds():
    reset();rq=request('request',amount=100)[1];p=call('POST','/requests/'+rq['request_id']+'/pay',{'visibility':'private'},'a','pay')[1]
    rr=expect('refund-request-payment',refund(p['payment_id'],100),201);check('request-stays-paid',reqs('a')[0]['status']=='paid' and reqs('a')[0]['payment_id']==p['payment_id'])
    a=call('POST','/authorizations',{'to_handle':'b','amount':1000,'note':'capture note','visibility':'private'},'a','auth')[1];aid=a['authorization_id'];p=call('POST','/authorizations/'+aid+'/capture',{'amount':400},'b','cap')[1]
    r=expect('refund-capture',refund(p['payment_id'],400,key='capture-refund'),201)
    ar=get('/authorizations')[1]['authorizations'][0];check('capture-stays-closed',ar['status']=='captured' and ar['captured_amount']==400 and ar['remaining_amount']==0 and ar['payment_ids']==[p['payment_id']],ar)
    check('refund-no-reopened-hold',me()['held']==0)
    # Held funds cannot fund refunds.
    reset();p=payment('pay',amount=100)[1];call('POST','/authorizations',{'to_handle':'a','amount':1100},'b','b-hold');before=state();expect('refund-uses-available',refund(p['payment_id'],1),409,'insufficient_funds');check('refund-insufficient-atomic',state()==before)
    ar=get('/authorizations','b')[1]['authorizations'][0];call('POST','/authorizations/'+ar['authorization_id']+'/void',{},'b');expect('failed-refund-key-reusable',refund(p['payment_id'],1),201)
    # A settlement receipt remains member after refund and batch correction.
    reset();body={'transfers':[{'from_handle':'a','to_handle':'b','amount':100},{'from_handle':'b','to_handle':'c','amount':50}]};s=call('POST','/settlements',body,'o','settle')[1];p=s['payments'][0];r=expect('settlement-refund',refund(p['payment_id'],40),201)
    check('refund-not-settlement-member',r.get('settlement_id') is None and next(x for x in feed('a') if x['payment_id']==p['payment_id'])['settlement_id']==s['settlement_id'])
    expect('batch-below-refunded',batch([item(s['payments'][0],39),item(s['payments'][1],50)]),422,'refund_exceeds_payment')
    expect('batch-at-refund-floor',batch([item(s['payments'][0],40),item(s['payments'][1],50)]),201)
    check('settlement-retry-original',call('POST','/settlements',body,'o','settle')[1]==s)

def batch_validation():
    reset();p=payment('one',amount=100)[1];pi=item(p,50)
    for user in [None,'a','b','c']:expect('batch-auth-'+str(user),batch([pi],u=user),401 if user is None else 403,'unauthenticated' if user is None else 'forbidden')
    for key in [None,'']:expect('batch-key-required',batch([pi],key=key),400,'missing_idempotency_key')
    expect('batch-key-long',batch([pi],key='x'*256),422,'validation_failed')
    for cs in [None,{},'',[],[None],[1],[[]],[pi,pi],[{**pi,'payment_id':'x'+str(i)} for i in range(33)]]:expect('batch-shape',batch(cs),422,'validation_failed')
    expect('batch-required',call('POST','/correction-batches',{},'o','b'),422,'validation_failed')
    for field in pi:
        x=dict(pi);del x[field];expect('batch-required-'+field,batch([x]),422,'validation_failed')
    for field,values in [('payment_id',[None,1,[],{}]),('expected_revision',[None,False,0,-1,1.5,'1']),('amount',[-1,1000000001,True,'1',1.5]),('reason',['','x'*201,None,1]),('effective_at',['bad','2090-01-01T00:00:00Z',None,1])]:
        for v in values:expect('batch-field-'+field,batch([{**pi,field:v}]),422,'validation_failed')
    expect('batch-unknown',batch([{**pi,'payment_id':'missing'}]),404,'not_found');expect('batch-stale',batch([{**pi,'expected_revision':2}]),409,'stale_revision')
    before=state();expect('item-order-unknown-first',batch([{**pi,'payment_id':'missing'},{**pi,'amount':-1}]),404,'not_found');check('batch-invalid-atomic',state()==before)
    expect('item-order-validation-first',batch([{**pi,'amount':-1},{**pi,'payment_id':'missing'}]),422,'validation_failed')
    r=expect('operator-corrects-other-sender',batch([{**pi,'unknown':'ignored'}],unknown=True),201);check('batch-response',isinstance(r.get('correction_batch_id'),str) and len(r['revisions'])==1 and r['revisions'][0]['payment_id']==p['payment_id'] and r['revisions'][0]['correction_batch_id']==r['correction_batch_id'] and r['revisions'][0]['recorded_at']==r['recorded_at'],r)
    expect('batch-conflict-before-validation',batch([{'amount':-1}]),409,'idempotency_key_reuse')
    expect('batch-replay',batch([{**pi,'unknown':'ignored'}],unknown=True),200)
    expect('ordinary-single-after-batch',correct(p=p['payment_id'],expected_revision=2,amount=40,effective_at=p['created_at'],key='single'),201);check('batch-replay-after-newer',batch([{**pi,'unknown':'ignored'}],unknown=True)[1]==r)

def settlements_and_net():
    f=copy.deepcopy(FIX)
    for u,b in zip(f['users'],[100,0,0,0]):u['balance']=b
    reset(f);body={'transfers':[{'from_handle':'a','to_handle':'b','amount':100},{'from_handle':'b','to_handle':'a','amount':100}]};s=call('POST','/settlements',body,'o','net')[1];ps=s['payments'];cs=[item(p,0,effective=D1) for p in ps]
    before=state();expect('incomplete-settlement',batch(cs[:1]),422,'incomplete_settlement');check('incomplete-atomic',state()==before)
    expect('item-before-completeness',batch([cs[0],{**cs[1],'payment_id':'missing'}]),404,'not_found')
    expect('settlement-different-effective',batch([cs[0],{**cs[1],'effective_at':D2}]),422,'validation_failed')
    snap=statement()[1];orig=feed('a');r=expect('combined-affordable-reversal',batch([cs[0],{**cs[1],'effective_at':'2020-01-02T02:00:00+02:00'}]),201)
    check('net-no-balance-change',[bal(u) for u in ['a','b']]==[100,0]);check('batch-original-feed',feed('a')==orig);check('batch-frozen-snapshot',statement(snapshot=snap['snapshot'])[1]==snap)
    check('batch-input-order',[x['payment_id'] for x in r['revisions']]==[p['payment_id'] for p in ps]);check('batch-common-recorded',all(x['recorded_at']==r['recorded_at'] and instant(x['recorded_at'])>instant(ps[i]['created_at']) for i,x in enumerate(r['revisions'])))
    check('batch-new-statement',all(e['revision']==2 and e['delta']==0 for e in statement()[1]['entries']))
    check('settlement-replay-original',call('POST','/settlements',body,'o','net')[1]==s)
    # Current net debit exceeds funds, then same key reusable after failure.
    cs2=[item(ps[0],101,2,D1),item(ps[1],0,2,D1)];before=state();expect('batch-current-insufficient',batch(cs2,key='next'),409,'insufficient_funds');check('batch-current-atomic',state()==before)
    expect('batch-failed-key-reusable',batch([item(ps[0],100,2,D1),item(ps[1],100,2,D1)],key='next'),201)
    # 32 distinct ordinary payments can be corrected together.
    reset();ps=[payment('max'+str(i),amount=1)[1] for i in range(32)];expect('batch-max32',batch([item(p,0) for p in ps]),201)

def batch_history():
    f=copy.deepcopy(FIX)
    for u,b in zip(f['users'],[0,100,0,0]):u['balance']=b
    f['payments']=[{'id':'ab','from_user_id':'u_a','to_user_id':'u_b','amount':100,'note':'','visibility':'public','created_at':D1},{'id':'bc','from_user_id':'u_b','to_user_id':'u_c','amount':100,'note':'','visibility':'public','created_at':D2},{'id':'cb','from_user_id':'u_c','to_user_id':'u_b','amount':100,'note':'','visibility':'public','created_at':D3}]
    reset(f);before=state();expect('batch-historical-overdraft',batch([{'payment_id':'ab','expected_revision':1,'amount':0,'effective_at':D1,'reason':'reverse'}]),409,'historical_overdraft');check('batch-history-atomic',state()==before)
    # A batch can repair the intermediate overdraft collectively.
    expect('batch-historical-net-valid',batch([{'payment_id':pid,'expected_revision':1,'amount':0,'effective_at':D1,'reason':'reverse'} for pid in ['ab','bc','cb']]),201)
    f=copy.deepcopy(FIX);f['users'][0]['balance']=100;reset(f);a=call('POST','/authorizations',{'to_handle':'b','amount':80},'a','hold')[1];time.sleep(1.05);call('POST','/authorizations/'+a['authorization_id']+'/void',{},'a');time.sleep(1.05);p=payment('late',amount=50)[1];before=state()
    expect('batch-historical-available',batch([item(p,50,effective=a['created_at'])]),409,'historical_overdraft');check('batch-held-atomic',state()==before)
    call('POST','/authorizations',{'to_handle':'b','amount':50},'a','held-now');expect('batch-current-before-historical',batch([item(p,60,effective=a['created_at'])]),409,'insufficient_funds')

def concurrency():
    reset();p=payment('p',amount=100)[1];pid=p['payment_id']
    with cf.ThreadPoolExecutor(max_workers=50) as pool:rs=list(pool.map(lambda i:refund(pid,1,key='one'),range(50)))
    check('refund-identical-once',sum(r[0]==201 for r in rs)==1 and sum(r[0]==200 for r in rs)==49);check('refund-identical-body',all(r[1]==rs[0][1] for r in rs))
    reset();p=payment('p',amount=20)[1]
    with cf.ThreadPoolExecutor(max_workers=50) as pool:rs=list(pool.map(lambda i:refund(p['payment_id'],1,key='many'+str(i)),range(50)))
    check('refund-capacity-concurrent',sum(r[0]==201 for r in rs)==20 and sum(r[0]==422 and r[1]['error']['code']=='refund_exceeds_payment' for r in rs)==30);check('refund-conservation',bal('a')+bal('b')==11000)
    reset();ps=[payment('p'+str(i),amount=100)[1] for i in range(3)];cs=[item(p,50) for p in ps]
    with cf.ThreadPoolExecutor(max_workers=50) as pool:rs=list(pool.map(lambda i:batch(cs,key='identical'),range(50)))
    check('batch-identical-once',sum(r[0]==201 for r in rs)==1 and sum(r[0]==200 for r in rs)==49);check('batch-identical-body',all(r[1]==rs[0][1] for r in rs))
    with cf.ThreadPoolExecutor(max_workers=2) as pool:rs=list(pool.map(lambda inds:batch([item(ps[i],25,2) for i in inds],key='overlap'+str(inds)),[[0,1],[1,2]]))
    check('overlap-only-one',sum(r[0]==201 for r in rs)==1 and sum(r[0]==409 and r[1]['error']['code']=='stale_revision' for r in rs)==1,[r[0] for r in rs])

def migration_import():
    old='http://cross-s3-495d5d6:8080';reset(histfixture(),base=old);tok=call('POST','/auth/login',{'email':'a@example.com','password':'eight chars'},base=old)[1]['token'];call('POST','/payments/p_b/corrections',{'expected_revision':1,'amount':150,'effective_at':D0,'reason':'legacy'},user=tok,key='legacy',base=old)
    snap=call('GET','/statement',user=tok,base=old)[1];export=state(old);expect('stage3-upgrade',call('POST','/_test/import',export),204);TOK['a']=tok
    actual=statement(snapshot=snap['snapshot'])[1];expected=copy.deepcopy(snap)
    for e in expected['entries']:e['payment'].setdefault('refund_of',None)
    check('stage3-snapshot-preserved',actual==expected,{'actual':actual,'expected':expected} if actual!=expected else None);check('stage3-correction-preserved',me()['balance']==680 and revisions('p_b')[1]['revisions'][-1]['amount']==150)
    # New stage4 state/receipts survives cross-process import unchanged.
    reset();p=payment('p',amount=100)[1];r=refund(p['payment_id'],40)[1];b=batch([item(p,60)])[1];snap=statement()[1];export=state();expect('stage4-import',call('POST','/_test/import',export,base=DEST),204);check('stage4-export-identical',state(DEST)==export)
    check('imported-refund-retry',call('POST','/payments/'+p['payment_id']+'/refunds',{'amount':40},'b','refund',base=DEST)[1]==r);check('imported-batch-retry',call('POST','/correction-batches',{'corrections':[item(p,60)]},'o','batch',base=DEST)[1]==b)
    check('imported-stage4-snapshot',call('GET','/statement?'+urlencode({'snapshot':snap['snapshot']}),user='a',base=DEST)[1]==snap)

if __name__=='__main__':
    groups=sys.argv[1:] or ['ordinary_receipts','targets_funds','batch_validation','settlements_and_net','batch_history','concurrency','migration_import']
    for g in groups:
        try:globals()[g]()
        except Exception as e:check(g+'-uncaught',False,str(e))
        print('DONE',g,flush=True)
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-stage4-'+('-'.join(groups))+'.json'),'w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
