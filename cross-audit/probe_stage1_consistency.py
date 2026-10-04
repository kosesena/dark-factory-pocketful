"""All remaining stage-1 monetary-record invariants in imported snapshots."""
from probe_stage1 import *

reset()
p=payment('p')[1]
rq=request('r')[1]
pay=call('POST','/requests/'+rq['request_id']+'/pay',{},'a','pay')[1]
sb={'transfers':[{'from_handle':'a','to_handle':'b','amount':1},{'from_handle':'b','to_handle':'c','amount':1}]}
se=call('POST','/settlements',sb,'o','se')[1]
sp=call('POST','/splits',{'amount':10,'participant_handles':['a','b'],'note':'split'},'a','sp')[1]
snap=state()
mutations=[]
def baseline():
    s=copy.deepcopy(snap);s['state']['idempotency']=[];s['state']['splits']={};return s
def pm(s,pid):return next(x for x in s['state']['payments'] if x['id']==pid)
def rm(s,rid):return next(x for x in s['state']['requests'] if x['id']==rid)
b=baseline();pm(b,p['payment_id'])['to_user_id']='u_a';mutations.append(('self-payment',b))
b=baseline();rm(b,rq['request_id'])['requester_id']='u_a';mutations.append(('self-request',b))
b=baseline();rm(b,rq['request_id'])['amount']=11;mutations.append(('request-payment-amount-mismatch',b))
b=baseline();rm(b,rq['request_id'])['status']='pending';mutations.append(('pending-request-with-fulfillment',b))
b=baseline();pm(b,se['payments'][0]['payment_id'])['created_at']='2000-01-01T00:00:00+00:00';mutations.append(('settlement-member-time-mismatch',b))
b=baseline();b['state']['settlements'][se['settlement_id']]['payment_ids'].pop();mutations.append(('settlement-member-list-mismatch',b))
b=copy.deepcopy(snap);b['state']['idempotency']=[];b['state']['splits'][sp['split_id']]['note']='x'*201;mutations.append(('split-note-overlimit',b))

for label,b in mutations:
    r=call('POST','/_test/import',b)
    expect('record-consistency-'+label,r,422,'validation_failed')
    check('record-consistency-atomic-'+label,state()==snap)
    if label=='pending-request-with-fulfillment' and r[0]==204:
        again=call('POST','/requests/'+rq['request_id']+'/pay',{},'a','second-pay')
        duplicate_count=sum(x.get('request_id')==rq['request_id'] for x in feed('a'))
        check('import-does-not-enable-second-fulfillment',again[0]!=201 and duplicate_count==1,{'pay_status':again[0],'payments_for_request':duplicate_count})
    if state()!=snap:call('POST','/_test/import',snap)

# The same record rules apply to reset fixtures, while failed reset leaves state intact.
for target in ['payments','requests']:
    f=copy.deepcopy(FIX)
    rec=({'id':'seed-p','from_user_id':'u_a','to_user_id':'u_b','amount':1,'visibility':'public','note':'x'*201} if target=='payments' else {'id':'seed-r','requester_id':'u_b','payer_id':'u_a','amount':1,'status':'pending','note':'x'*201})
    f[target]=[rec]
    expect('seed-note-overlimit-'+target,call('POST','/_test/reset',f),422,'validation_failed')
    check('seed-note-atomic-'+target,state()==snap)
    if state()!=snap:call('POST','/_test/import',snap)

out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-consistency.json'),'w') as f: json.dump(out,f,indent=2)
print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
