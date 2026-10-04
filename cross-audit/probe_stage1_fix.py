"""Specification-driven follow-ups for exact JSON identity and snapshot replacement."""
from probe_stage1 import *

reset()
# Unknown fields are still JSON values for replay equality; do not conflate types.
pairs=[('trailing-fraction','0.10','0.1',200),
       ('fraction-string','0.1','"0.1"',409),
       ('big-equivalent','1e40','10e39',200),
       ('big-int-equivalent','10000000000000000000000000000000000000000','1e40',200),
       ('big-string','1e40','"1E+40"',409),
       ('tiny-equivalent','1e-400','10e-401',200),
       ('huge-equivalent','1e400','10e399',200),
       ('negative-zero','-0.0','0',200),
       ('nested-types','{"a":[0.1,true]}','{"a":["0.1",true]}',409),
       ('nested-equality','{"a":[1.00,0.10]}','{"a":[1e0,1e-1]}',200)]
for label,left,right,want in pairs:
    raw=lambda v:('{"to_handle":"b","amount":1,"extra":'+v+'}').encode()
    first=expect('identity-first-'+label,call('POST','/payments',raw=raw(left),user='a',key=label),201)
    second=expect('identity-repeat-'+label,call('POST','/payments',raw=raw(right),user='a',key=label),want,None if want==200 else 'idempotency_key_reuse')
    if want==200: check('identity-receipt-'+label,first==second)

for path,prefix,suffix,user in [('/payments','{"to_handle":"b","amount":','}','a'),('/requests','{"payer_handle":"a","amount":','}','b'),('/splits','{"participant_handles":["a","b"],"amount":','}','a'),('/settlements','{"transfers":[{"from_handle":"a","to_handle":"b","amount":','}]}','o')]:
    for num in ['9'*5000,'1e400','1e-400','1.0000000000000000000000000000000000000001']:
        expect('exact-range-'+path+'-'+num[:30],call('POST',path,raw=(prefix+num+suffix).encode(),user=user,key='long'+num[:20]),422,'validation_failed')
expect('unknown-huge-integer',call('POST','/payments',raw=('{"to_handle":"b","amount":1,"extra":'+'9'*5000+'}').encode(),user='a',key='huge-extra'),201)

# Round-trip real zero-share records after money-moving transitions and stale receipts.
reset()
body={'amount':1,'participant_handles':['a','b','c']}
sp=expect('zero-split-create',call('POST','/splits',body,'a','zero-split'),201)
zero_receipts=[]
for r in sp['requests']:
    path='/requests/'+r['request_id']+'/pay'
    p=expect('zero-share-pay-'+r['payer_handle'],call('POST',path,{},r['payer_handle'],'zero-pay'),201)
    check('zero-receipt-amount',p['amount']==0)
    zero_receipts.append((r['payer_handle'],path,p))
snap=state()
for i in range(2):
    expect('zero-import-'+str(i),call('POST','/_test/import',snap,base=DEST),204)
    check('zero-import-exact-'+str(i),state(DEST)==snap)
    check('zero-split-original-replay',expect('zero-split-replay',call('POST','/splits',body,'a','zero-split',base=DEST),200)==sp)
    for user,path,p in zero_receipts:
        check('zero-pay-original-replay',expect('zero-pay-replay',call('POST',path,{},user,'zero-pay',base=DEST),200)==p)
    check('zero-import-conservation',sum(bal(u,DEST) for u in ['a','b','c','o'])==11000)

# A seeded terminal request may lack API-created linkage in the published fixture format.
for status in ['pending','paid','declined','cancelled']:
    f=copy.deepcopy(FIX)
    f['requests']=[{'id':'seed-r','requester_id':'u_b','payer_id':'u_a','amount':10,'note':'seed','status':status}]
    reset(f); snap=state()
    expect('seed-'+status+'-import',call('POST','/_test/import',snap,base=DEST),204)
    check('seed-'+status+'-exact',state(DEST)==snap)

# Invalid imports must not affect credentials, accounts, receipts or balances.
reset(); payment('p'); request('r'); snap=state()
mutations=[]
for v in ['2026-10-04T12:00:00','2026-02-30T00:00:00+00:00','2026-10-04 12:00:00+00:00']:
    bad=copy.deepcopy(snap);bad['state']['payments'][0]['created_at']=v;mutations.append(('timestamp-'+v,bad))
for v in [-1,2**53+1,True,0.1]:
    bad=copy.deepcopy(snap);bad['state']['users'][0]['balance']=v;mutations.append(('balance-'+str(v),bad))
bad=copy.deepcopy(snap);bad['state']['users'][1]['handle']=bad['state']['users'][0]['handle'];mutations.append(('duplicate-handle',bad))
bad=copy.deepcopy(snap);bad['state']['requests'][0]['payment_id']='no-such-payment';mutations.append(('request-link',bad))
bad=copy.deepcopy(snap);bad['state']['payments'][0]['settlement_id']='no-such-settlement';mutations.append(('settlement-link',bad))
bad=copy.deepcopy(snap);bad['state']['idempotency'][0][4]['amount']=999;mutations.append(('changed-original-receipt',bad))
for label,bad in mutations:
    expect('strict-import-'+label,call('POST','/_test/import',bad),422,'validation_failed')
    check('strict-import-atomic-'+label,state()==snap)
    if label=='changed-original-receipt' and state()!=snap:
        replay=call('POST','/payments',{'to_handle':'b','amount':10},'a','p')
        check('tampered-replay-matches-real-payment',replay[0]==200 and replay[1].get('amount')==10,{'status':replay[0],'replay_amount':replay[1].get('amount'),'recorded_amount':snap['state']['payments'][0]['amount']})
    if state()!=snap: call('POST','/_test/import',snap)

# Reset performance changed: seed 1000 independent wallets under the stated 10 seconds.
f=copy.deepcopy(FIX);f['users']=[{'id':'u'+str(i),'handle':'h'+str(i),'email':'e'+str(i)+'@test.local','password':'eight chars','display_name':'User '+str(i),'balance':i} for i in range(1000)];f['settlement_operator_ids']=[]
res=call('POST','/_test/reset',f)
expect('large-reset',res,204);check('large-reset-under-10s',res[3]<10,res[3])
for i in [0,499,999]: expect('large-seed-login-'+str(i),call('POST','/auth/login',{'email':'e'+str(i)+'@test.local','password':'eight chars'}),200)

out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-fix.json'),'w') as f: json.dump(out,f,indent=2)
print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
