from probe_stage3 import *

def older_exports():
    for old in ['http://cross-s1upgrade-999fda2:8080','http://cross-s2upgrade-d78f1bd:8080']:
        reset(base=old);tok=call('POST','/auth/login',{'email':'a@example.com','password':'eight chars'},base=old)[1]['token'];tb=call('POST','/auth/login',{'email':'b@example.com','password':'eight chars'},base=old)[1]['token']
        original=call('POST','/payments',{'to_handle':'b','amount':50},user=tok,key='legacy-pay',base=old)[1]
        call('POST','/requests',{'payer_handle':'a','amount':100},user=tb,key='legacy-req',base=old)
        if 's2' in old:
            a=call('POST','/authorizations',{'to_handle':'b','amount':1000},user=tok,key='legacy-auth',base=old)[1]
            cp=call('POST','/authorizations/'+a['authorization_id']+'/capture',{'amount':300,'final':False},user=tb,key='legacy-cap',base=old)[1]
        export=state(old);expect('legacy-import-'+old,call('POST','/_test/import',export),204);TOK['a']=tok;TOK['b']=tb
        check('legacy-token-balance',shape(me(),9650,700) if 's2' in old else shape(me(),9950,0),me())
        check('legacy-retry-original',payment('legacy-pay',amount=50)[1]==original)
        s=statement()[1];check('legacy-opening',s['opening_balance']==10000 and len(s['entries'])==(2 if 's2' in old else 1),s)
        rs=revisions(original['payment_id'])[1]['revisions'];check('legacy-revision-one',rs[0]['amount']==50 and rs[0]['effective_at']==rs[0]['recorded_at']==original['created_at'])
        r=reqs('a')[0];expect('legacy-request-pay',call('POST','/requests/'+r['request_id']+'/pay',{},'a','legacy-payreq'),201)
        if 's2' in old:
            expect('legacy-capture-immutable',correct(p=cp['payment_id'],amount=200,effective_at=cp['created_at']),422,'linked_payment_immutable')
            expect('legacy-remainder-capture',call('POST','/authorizations/'+a['authorization_id']+'/capture',{},'b','finish'),201)

def more_idem_and_lifecycle():
    reset();p=payment('new',amount=100)[1];pid=p['payment_id'];when=p['created_at']
    raw=('{'+'"expected_revision":1.0,"amount":5e1,"effective_at":"'+when+'","reason":"  é 🪷  ","extra":0.10}').encode()
    r=call('POST','/payments/'+pid+'/corrections',user='a',key='nums',raw=raw);c=expect('integral-correction-encodings',r,201);check('reason-verbatim',c['reason']=='  é 🪷  ')
    expect('correction-numeric-body-replay',call('POST','/payments/'+pid+'/corrections',user='a',key='nums',raw=raw.replace(b'0.10',b'0.1').replace(b'5e1',b'50.0')),200)
    expect('correction-numeric-v-string',call('POST','/payments/'+pid+'/corrections',user='a',key='nums',raw=raw.replace(b'0.10',b'"0.1"')),409,'idempotency_key_reuse')
    p2=payment('new2',amount=100)[1];expect('same-key-distinct-path',correct(p=p2['payment_id'],key='nums',amount=50,effective_at=when),201)
    for rev in ['1e400','9'*5000,'1.0000000000000001']:
        b=('{'+'"expected_revision":'+rev+',"amount":50,"effective_at":"'+when+'","reason":"x"}').encode();expect('huge-exact-expected-revision',call('POST','/payments/'+pid+'/corrections',user='a',key='huge',raw=b),422 if '.' in rev else 409,'validation_failed' if '.' in rev else 'stale_revision')
    # original request/split idempotent receipts survive corrections to their payment.
    rq=request('request')[1];p=call('POST','/requests/'+rq['request_id']+'/pay',{},'a','payreq')[1];expect('request-linked-correction-eligible',correct(p=p['payment_id'],amount=5,effective_at=p['created_at'],key='request-corr'),201)
    export=state();expect('genuine-request-correction-import',call('POST','/_test/import',export),204);check('original-request-retry',request('request')[1]==rq);check('request-payment-retry-original',call('POST','/requests/'+rq['request_id']+'/pay',{},'a','payreq')[1]==p)
    # Snapshot remains frozen through every hold lifecycle action.
    snap=statement()[1];token=snap['snapshot']
    a=call('POST','/authorizations',{'to_handle':'b','amount':1000},'a','hold')[1];aid=a['authorization_id'];check('snapshot-after-authorize',statement(snapshot=token)[1]==snap)
    call('POST','/authorizations/'+aid+'/capture',{'amount':200,'final':False},'b','part');check('snapshot-after-partial',statement(snapshot=token)[1]==snap)
    call('POST','/authorizations/'+aid+'/void',{},'a');check('snapshot-after-void',statement(snapshot=token)[1]==snap)
    # Partial capture then expiry preserves historical remainder and timestamp.
    f=copy.deepcopy(FIX);f['authorization_ttl_seconds']=3;reset(f);a=call('POST','/authorizations',{'to_handle':'b','amount':1000},'a','hold')[1];time.sleep(1.05);p=call('POST','/authorizations/'+a['authorization_id']+'/capture',{'amount':300,'final':False},'b','part')[1]
    check('partial-expiry-future',shape(me(as_of=a['expires_at']),9700,0));check('partial-before-expiry',shape(me(as_of=shift(a['expires_at'],-.000001)),9700,700))
    time.sleep(2.1);ar=get('/authorizations')[1]['authorizations'][0];check('partial-expiry-records',ar['closed_at']==a['expires_at'] and ar['payment_ids']==[p['payment_id']] and ar['captured_amount']==300,ar)
    # Independent snapshot reads are not allowed to mutate frozen snapshots.
    s=statement()[1];before=state();call('GET','/_test/export');check('export-readonly',state()==before)
    check('expiry-history-before-capture-known',shape(me(as_of=a['expires_at'],known_at=a['created_at']),10000,0))

def invalid_history_import():
    reset();p=payment('base',amount=10)[1];correct(p=p['payment_id'],amount=5,effective_at=p['created_at']);a=call('POST','/authorizations',{'to_handle':'b','amount':100},'a','hold')[1];call('POST','/authorizations/'+a['authorization_id']+'/void',{},'a')
    original=state();base=copy.deepcopy(original);base['state']['idempotency']=[]
    mutations=[
      ('revision-reason-too-long',lambda s:s['payments'][0]['revisions'][1].update(reason='x'*201)),
      ('revision-reason-wrong-type',lambda s:s['payments'][0]['revisions'][1].update(reason=None)),
      ('revision-amount-fraction',lambda s:s['payments'][0]['revisions'][1].update(amount=5.5)),
      ('revision-amount-negative',lambda s:s['payments'][0]['revisions'][1].update(amount=-1)),
      ('revision-amount-too-large',lambda s:s['payments'][0]['revisions'][1].update(amount=1000000001)),
      ('revision-number-gap',lambda s:s['payments'][0]['revisions'][1].update(revision=3)),
      ('revision-number-boolean',lambda s:s['payments'][0]['revisions'][1].update(revision=True)),
      ('revision-recorded-nonincreasing',lambda s:s['payments'][0]['revisions'][1].update(recorded_at=s['payments'][0]['revisions'][0]['recorded_at'])),
      ('revision-effective-subsecond-mismatch',lambda s:s['payments'][0]['revisions'][1].update(effective_at=shift(s['payments'][0]['revisions'][1]['effective_at'],.5))),
      ('hold-close-subsecond-mismatch',lambda s:s['authorizations'][0].update(closed_at=shift(s['authorizations'][0]['closed_at'],.5))),
      ('revision-effective-invalid',lambda s:s['payments'][0]['revisions'][1].update(effective_at='not-a-date')),
      ('revision-recorded-future',lambda s:s['payments'][0]['revisions'][1].update(recorded_at='2090-01-01T00:00:00Z')),
      ('revision-effective-future',lambda s:s['payments'][0]['revisions'][1].update(effective_at='2090-01-01T00:00:00Z')),
      ('original-revision-amount-mismatch',lambda s:s['payments'][0]['revisions'][0].update(amount=9)),
      ('original-revision-effective-mismatch',lambda s:s['payments'][0]['revisions'][0].update(effective_at=D0)),
      ('opening-inconsistent',lambda s:s['users'][0].update(opening=s['users'][0]['opening']+1)),
      ('current-balance-inconsistent-history',lambda s:s['users'][0].update(balance=s['users'][0]['balance']+1)),
      ('closed-hold-no-close-time',lambda s:s['authorizations'][0].update(closed_at=None)),
      ('closed-hold-before-creation',lambda s:s['authorizations'][0].update(closed_at=D0)),
    ]
    for name,mut in mutations:
        call('POST','/_test/import',original);dest_before=state();bad=copy.deepcopy(base);mut(bad['state']);r=call('POST','/_test/import',bad);expect('invalid-history-'+name,r,422,'validation_failed');check('invalid-history-atomic-'+name,state()==dest_before)
    call('POST','/_test/import',original)

def imported_historical_overdraft():
    f=copy.deepcopy(FIX)
    for u,b in zip(f['users'],[0,100,0,0]):u['balance']=b
    f['payments']=[{'id':'ab','from_user_id':'u_a','to_user_id':'u_b','amount':100,'note':'','visibility':'public','created_at':D1},{'id':'bc','from_user_id':'u_b','to_user_id':'u_c','amount':100,'note':'','visibility':'public','created_at':D2},{'id':'cb','from_user_id':'u_c','to_user_id':'u_b','amount':100,'note':'','visibility':'public','created_at':D3}]
    reset(f);original=state();bad=copy.deepcopy(original);s=bad['state'];r=copy.deepcopy(s['payments'][0]['revisions'][0]);r.update(revision=2,amount=0,recorded_at=D4,recorded_ts=instant(D4).timestamp(),reason='reversal');s['payments'][0]['revisions'].append(r);s['users'][0]['balance']=100;s['users'][1]['balance']=0
    rr=call('POST','/_test/import',bad);expect('import-historical-overdraft',rr,422,'validation_failed');check('import-historical-overdraft-atomic',state()==original)
    if rr[0]==204:check('diagnostic-negative-history',False,me('b',as_of=D2))
    call('POST','/_test/import',original)

def imported_held_overdraft():
    f=copy.deepcopy(FIX);f['users'][0]['balance']=100;f['users'][1]['balance']=100;reset(f)
    a=call('POST','/authorizations',{'to_handle':'b','amount':80},'a','held')[1];time.sleep(1.05);call('POST','/authorizations/'+a['authorization_id']+'/void',{},'a');time.sleep(1.05);p=payment('after-release',amount=50)[1]
    original=state();bad=copy.deepcopy(original);bad['state']['idempotency']=[];r=copy.deepcopy(bad['state']['payments'][0]['revisions'][0]);now=stamp();r.update(revision=2,amount=50,effective_at=a['created_at'],effective_ts=instant(a['created_at']).timestamp(),recorded_at=now,recorded_ts=instant(now).timestamp(),reason='backdate');bad['state']['payments'][0]['revisions'].append(r)
    rr=call('POST','/_test/import',bad);expect('import-historical-held-overdraft',rr,422,'validation_failed');check('import-historical-held-overdraft-atomic',state()==original)
    if rr[0]==204:check('diagnostic-negative-available-history',False,me(as_of=a['created_at']))
    call('POST','/_test/import',original)

if __name__=='__main__':
    groups=sys.argv[1:] or ['older_exports','more_idem_and_lifecycle','invalid_history_import','imported_historical_overdraft','imported_held_overdraft']
    for g in groups:
        try:globals()[g]()
        except Exception as e:check(g+'-uncaught',False,str(e))
        print('DONE',g,flush=True)
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-stage3-extra-'+('-'.join(groups))+'.json'),'w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
