"""Final changed-path sweep selected from numeric and state invariants."""
from probe_stage1 import *

reset()
eq_pairs=[('1e1000000','10e999999'),('1e-1000000','10e-1000001'),
          ('0e1000000','-0.000'),('1.00000000000000000000000000001','1.0000000000000000000000000000100'),
          ('1234500e-3','1234.5000'),('-0.10','-1e-1'),('1'+'0'*5000,'10e4999')]
for i,(left,right) in enumerate(eq_pairs):
    def post(v):return call('POST','/payments',raw=('{"to_handle":"b","amount":1,"x":'+v+'}').encode(),user='a',key='eq'+str(i))
    a=expect('canonical-first-'+str(i),post(left),201)
    b=expect('canonical-repeat-'+str(i),post(right),200)
    check('canonical-original-'+str(i),a==b)
for i,x in enumerate(['1e1000000','1e-1000000','-1e1000000','1e9999999999999999999','1e-9999999999999999999']):
    before=state()
    expect('extreme-amount-'+x,call('POST','/payments',raw=('{"to_handle":"b","amount":'+x+'}').encode(),user='a',key='extreme'+str(i)),422,'validation_failed')
    check('extreme-amount-atomic-'+x,state()==before)
for i,x in enumerate(['1.'+'0'*5000,'0.0000001e7','100000e-5']):
    expect('long-integral-'+str(i),call('POST','/payments',raw=('{"to_handle":"b","amount":'+x+'}').encode(),user='a',key='integral'+str(i)),201)

# Unknown fields are ignored even when their numbers are much bigger than money.
for i,x in enumerate(['1e1000000','1e9999999999999999999','9'*5000]):
    raw=json.dumps(FIX)[:-1]+',"ignored":'+x+'}'
    expect('reset-unknown-number-'+str(i),call('POST','/_test/reset',raw=raw.encode()),204)

# Build a complete legitimate state with historical receipt/current state differences.
reset()
payment('p',note='immutable',visibility='private')
created=[]
for action in ['pay','cancel','decline']:
    r=request('req-'+action)[1];created.append(r)
    who='b' if action=='cancel' else 'a'
    expect('transition-'+action,call('POST','/requests/'+r['request_id']+'/'+action,{},who,'transition-'+action),201 if action=='pay' else 200)
splitbody={'amount':1,'participant_handles':['a','b','c'],'note':'split'}
sp=call('POST','/splits',splitbody,'a','sp')[1]
for r in sp['requests']: call('POST','/requests/'+r['request_id']+'/pay',{},r['payer_handle'],'sp-pay')
batch={'transfers':[{'from_handle':'a','to_handle':'b','amount':1,'visibility':'private'},{'from_handle':'b','to_handle':'c','amount':1}]}
se=call('POST','/settlements',batch,'o','se')[1]
snap=state()
expect('full-transition-import',call('POST','/_test/import',snap,base=DEST),204)
check('full-transition-exact',state(DEST)==snap)
for action,original in zip(['pay','cancel','decline'],created):
    replay=expect('historic-request-replay-'+action,call('POST','/requests',{'payer_handle':'a','amount':10},'b','req-'+action,base=DEST),200)
    check('historic-request-exact-'+action,replay==original)

# Validate receipt structures and immutable facts independently for all write paths.
for path_label in ['/payments','/requests','/pay','/splits','/settlements']:
    found=next((i for i,x in enumerate(snap['state']['idempotency']) if (x[2].endswith('/pay') if path_label=='/pay' else x[2]==path_label)),None)
    assert found is not None,path_label
    response=snap['state']['idempotency'][found][4]
    keys=['created_at','currency','note'] if path_label!='/settlements' else ['committed_at']
    for field in keys:
        if field not in response: continue
        bad=copy.deepcopy(snap);bad['state']['idempotency'][found][4][field]=None
        expect('receipt-type-'+path_label+'-'+field,call('POST','/_test/import',bad),422,'validation_failed')
        check('receipt-type-atomic-'+path_label+'-'+field,state()==snap)
        if state()!=snap:call('POST','/_test/import',snap)
    for field,value in [(0,'missing-user'),(2,'/unsupported-write')]:
        bad=copy.deepcopy(snap);bad['state']['idempotency'][found][field]=value
        expect('receipt-owner-path-'+path_label+'-'+str(field),call('POST','/_test/import',bad),422,'validation_failed')
        check('receipt-owner-path-atomic-'+path_label+'-'+str(field),state()==snap)
        if state()!=snap:call('POST','/_test/import',snap)

# Record invariants independent of replay receipts. Remove completed requests to
# ensure import cannot merely compare invalid monetary records to their receipts.
for target in ['payments','requests']:
    for field,value in [('note','x'*201),('amount',-1),('amount',1000000001),('id','x'*65)]:
        bad=copy.deepcopy(snap);bad['state']['idempotency']=[];bad['state'][target][0][field]=value
        expect('record-rule-'+target+'-'+field+'-'+str(value)[:20],call('POST','/_test/import',bad),422,'validation_failed')
        check('record-rule-atomic-'+target+'-'+field,state()==snap)
        if state()!=snap:call('POST','/_test/import',snap)

# Reset replacement must be transactional too; reset shares the validation path.
for field,value in [('balance',-1),('balance',2**53+1),('handle','INVALID'),('id','x'*65)]:
    bad=copy.deepcopy(FIX);bad['users'][0][field]=value
    expect('reset-invalid-'+field+str(value)[:20],call('POST','/_test/reset',bad),422,'validation_failed')
    check('reset-invalid-atomic-'+field,state()==snap)
    if state()!=snap:call('POST','/_test/import',snap)

out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-final.json'),'w') as f: json.dump(out,f,indent=2)
print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
