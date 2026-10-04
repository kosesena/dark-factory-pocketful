"""Independent HTTP probes for real legacy snapshots and semantic echo/view changes."""
from probe_stage3 import *

def legacy_exports():
    old='http://cross-s3legacy-495d5d6:8080'
    for later in [False,True]:
        for q in [{}, {'from':D0,'to':D4,'known_at':D4}, {'known_at':'2090-01-01T00:00:00Z'}]:
            reset(histfixture(),base=old)
            tok=call('POST','/auth/login',{'email':'a@example.com','password':'eight chars'},base=old)[1]['token']
            page=call('GET','/statement?'+urlencode(q),user=tok,base=old)[1]
            if later:
                expect('legacy-source-correction',call('POST','/payments/p_b/corrections',{'expected_revision':1,'amount':150,'effective_at':D0,'reason':'after snapshot'},user=tok,key='later',base=old),201)
                expect('legacy-source-payment',call('POST','/payments',{'to_handle':'b','amount':10},user=tok,key='new',base=old),201)
            exported=state(old)
            response=call('POST','/_test/import',exported)
            name='real-495d5d6-'+str(later)+'-'+json.dumps(q)
            expect(name,response,204)
            if response[0]==204:
                got=call('GET','/statement?'+urlencode({'snapshot':page['snapshot']}),user=tok)[1]
                check(name+'-original-page',got==page,{'actual':got,'expected':page} if got!=page else None)

def echo_semantics():
    reset(histfixture());q={'from':D0,'to':D4,'known_at':D4};page=statement(**q)[1];original=state()
    for field in q:
        # Different offset spelling for exactly the same instant is valid alternate state.
        bad=copy.deepcopy(original);bad['state']['snapshots'][0]['echo'][field]=shift(q[field],0).replace('+00:00','Z')
        expect('equivalent-echo-'+field,call('POST','/_test/import',bad),204)
        got=statement(snapshot=page['snapshot'])[1];expected=copy.deepcopy(page);expected[field]=bad['state']['snapshots'][0]['echo'][field]
        check('equivalent-echo-exact-'+field,got==expected)
    for field in q:
        for invalid in [None,True,1,[],{},'', '2020-01-01T00:00:00']:
            call('POST','/_test/import',original);before=state();bad=copy.deepcopy(original);bad['state']['snapshots'][0]['echo'][field]=invalid
            expect('invalid-echo-'+field+'-'+str(invalid),call('POST','/_test/import',bad),422,'validation_failed');check('invalid-echo-atomic',state()==before)

def viewless_refunds():
    if os.getenv('IS_STAGE4')!='1':return
    reset();p=payment('pay',amount=100)[1];pid=p['payment_id']
    expect('refund-create',call('POST','/payments/'+pid+'/refunds',{'amount':20},'b','ref'),201)
    page=statement()[1];original=state()
    for legacy in [False,True]:
        bad=copy.deepcopy(original)
        for sn in bad['state']['snapshots']:
            sn.pop('view',None)
            if legacy:sn.pop('taken_ts',None);sn.pop('taken_seq',None)
        before=state();expect('viewless-refund-'+str(legacy),call('POST','/_test/import',bad),422,'validation_failed');check('viewless-refund-atomic',state()==before)
    expect('genuine-refund-snapshot-import',call('POST','/_test/import',original),204)
    check('genuine-refund-page',statement(snapshot=page['snapshot'])[1]==page)

if __name__=='__main__':
    for name in ['legacy_exports','echo_semantics','viewless_refunds']:
        try:globals()[name]()
        except Exception as e:check(name+'-uncaught',False,str(e))
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-snapshot-compatibility.json'),'w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
