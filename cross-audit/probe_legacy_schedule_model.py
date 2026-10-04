"""Actual old-service reads are the frozen-page oracle across randomized later histories."""
from probe_stage3 import *

def run():
    old=os.environ['OLD_LEGACY'];rng=random.Random(4291);f=copy.deepcopy(FIX)
    for u in f['users']:u['balance']=50000
    f['payments']=[{'id':'s'+str(i),'from_user_id':'u_'+a,'to_user_id':'u_'+b,'amount':100,'note':'','visibility':'private','created_at':D1} for i,(a,b) in enumerate([('a','b'),('b','c'),('c','a')])]
    reset(f,base=old)
    toks={u:call('POST','/auth/login',{'email':u+'@example.com','password':'eight chars'},base=old)[1]['token'] for u in ['a','b','c']}
    revisions_n=[1,1,1];knowns=[D0,D1,D4,'2090-01-01T00:00:00Z'];pages=[]
    for step in range(60):
        for q in [rng.choice([{}, {'from':D0,'to':D1}, {'from':D1,'to':D2}, {'from':D2,'to':D4}, {'from':D4}]), {'from':D0,'to':D4,'known_at':rng.choice(knowns)}]:
            u=rng.choice(['a','b','c']);r=call('GET','/statement?'+urlencode(q),user=toks[u],base=old)
            if r[0]!=200:raise AssertionError(('snapshot',step,r[0]))
            pages.append((u,r[1]))
        i=step%3;u=['a','b','c'][i]
        r=call('POST','/payments/s'+str(i)+'/corrections',{'expected_revision':revisions_n[i],'amount':rng.choice([0,1,100,101,300]),'effective_at':rng.choice([D0,D1,D2,D3]),'reason':'model'+str(step)},user=toks[u],key='c'+str(step),base=old)
        if r[0]!=201:raise AssertionError(('correction',step,r[0],r[1]))
        revisions_n[i]+=1;knowns.append(r[1]['recorded_at'])
        r=call('POST','/payments',{'to_handle':['b','c','a'][i],'amount':1},user=toks[u],key='p'+str(step),base=old)
        if r[0]!=201:raise AssertionError(('payment',step,r[0]))
    data=state(old);r=call('POST','/_test/import',data);expect('real-randomized-legacy-import',r,204)
    check('randomized-import-time',r[3]<5,{'seconds':r[3],'snapshots':len(pages)})
    for i,(u,page) in enumerate(pages):
        got=call('GET','/statement?'+urlencode({'snapshot':page['snapshot']}),user=toks[u])[1]
        check('randomized-frozen-'+str(i),got==page,{'actual':got,'expected':page} if got!=page else None)

if __name__=='__main__':
    try:run()
    except Exception as e:check('schedule-uncaught',False,repr(e))
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-legacy-schedule-model.json'),'w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
