"""Additional independently selected boundary and snapshot probes."""
from probe_stage1 import *
from urllib.parse import quote

reset()
for path,raw,user in [
    ('/payments','{"to_handle":"b","amount":1.0000000000000001}','a'),
    ('/requests','{"payer_handle":"a","amount":1.0000000000000001}','b'),
    ('/splits','{"participant_handles":["a","b"],"amount":1.0000000000000001}','a'),
    ('/settlements','{"transfers":[{"from_handle":"a","to_handle":"b","amount":1.0000000000000001}]}','o')]:
    before=state()
    expect('fractional-'+path,call('POST',path,raw=raw.encode(),user=user,key='fraction'),422,'validation_failed')
    check('fractional-nochange-'+path,state()==before)
for i,x in enumerate(['1.0000000000000001','1']):
    expect('exact-idem-'+str(i),call('POST','/payments',raw=('{"to_handle":"b","amount":1,"extra":'+x+'}').encode(),user='a',key='precision-collapse'),201 if i==0 else 409,None if i==0 else 'idempotency_key_reuse')
for path in ['/activity','/requests']:
    expect('huge-offset-'+path,call('GET',path+'?offset='+'9'*5000,user='a'),200)
    expect('huge-limit-'+path,call('GET',path+'?limit='+'9'*5000,user='a'),422,'validation_failed')
    expect('unicode-query-'+path,call('GET',path+'?limit='+quote('٤'),user='a'),422,'validation_failed')

# Snapshot validation is exercised by changing opaque exported state, never service code.
reset(); payment('p'); request('r')
snap=state()
mutations=[]
for name,field,value in [('negative-balance','balance',-1),('boolean-balance','balance',True),('bad-handle','handle','INVALID!'),('bad-password-hash','hash','not-hex')]:
    bad=copy.deepcopy(snap); bad['state']['users'][0][field]=value; mutations.append((name,bad))
bad=copy.deepcopy(snap); bad['state']['tokens']['fake-token']='no-user'; mutations.append(('orphan-token',bad))
bad=copy.deepcopy(snap); bad['state']['operators']=['no-user']; mutations.append(('orphan-operator',bad))
bad=copy.deepcopy(snap); bad['state']['payments'][0]['to_user_id']='no-user'; mutations.append(('orphan-payment',bad))
bad=copy.deepcopy(snap); bad['state']['requests'][0]['status']='invalid'; mutations.append(('bad-request-status',bad))
bad=copy.deepcopy(snap); bad['state']['payments'][0]['created_at']='not-a-timestamp'; mutations.append(('bad-payment-timestamp',bad))
bad=copy.deepcopy(snap); bad['state']['payments'][0]['amount']=1000000001; mutations.append(('overlimit-payment',bad))
for name,bad in mutations:
    expect('invalid-state-'+name,call('POST','/_test/import',bad),422,'validation_failed')
    check('invalid-state-nochange-'+name,state()==snap)
    # Restore after any unexpectedly accepted mutation to keep later probes independent.
    if state()!=snap: call('POST','/_test/import',snap)

for name,bad in [('boolean-version',{**snap,'format_version':True}),('fractional-version',{**snap,'format_version':1.0001})]:
    expect('invalid-envelope-'+name,call('POST','/_test/import',bad),422,'validation_failed')

# Consistent snapshots during 50 in-flight transfers and export requests.
reset()
def action(i):
    if i%2: return call('GET','/_test/export')
    return payment('snap-race-'+str(i),amount=1)
with cf.ThreadPoolExecutor(max_workers=50) as pool: rs=list(pool.map(action,range(200)))
check('snapshot-concurrency-noerrors',all(r[0] in [200,201] for r in rs))
snaps=[r[1]['state'] for r in rs if r[0]==200 and r[1].get('track')=='pocketful']
check('snapshot-conservation',all(sum(u['balance'] for u in s['users'])==11000 and all(u['balance']>=0 for u in s['users']) for s in snaps))
check('snapshot-complete-transfers',all(next(u['balance'] for u in s['users'] if u['handle']=='a')==10000-len(s['payments']) and next(u['balance'] for u in s['users'] if u['handle']=='b')==1000+len(s['payments']) for s in snaps))

# Fifty concurrent authentication operations must also meet the request budget.
with cf.ThreadPoolExecutor(max_workers=50) as pool:
    rs=list(pool.map(lambda _:call('POST','/auth/login',{'email':'a@example.com','password':'eight chars'}),range(50)))
check('50-login-success',all(r[0]==200 for r in rs),[r[0] for r in rs])
check('50-login-under-5s',max(r[3] for r in rs)<5,max(r[3] for r in rs))

out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
with open(os.path.join(os.path.dirname(__file__),'evidence-69289b3-edges.json'),'w') as f: json.dump(out,f,indent=2)
print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
