"""Independent multi-owner/window migration oracle with both adversarial patterns combined."""
from probe_stage3 import *

def run():
    old=os.environ['OLD_LEGACY'];f=copy.deepcopy(FIX)
    for u in f['users']:u['balance']=100000
    f['payments']=[]
    for i,(a,b,amt) in enumerate([('a','b',1),('b','c',1),('c','a',1),('a','b',2),('b','c',2),('c','a',2)]):
        f['payments'].append({'id':'seed'+str(i),'from_user_id':'u_'+a,'to_user_id':'u_'+b,'amount':amt,'created_at':D1,'note':'tie','visibility':'private'})
    reset(f,base=old)
    toks={u:call('POST','/auth/login',{'email':u+'@example.com','password':'eight chars'},base=old)[1]['token'] for u in ['a','b','c']}
    for i in range(1000):
        r=call('POST','/payments',{'to_handle':'b','amount':1},user=toks['a'],key='initial'+str(i),base=old)
        if r[0]!=201:raise AssertionError(('initial',i,r[0]))
    qs=[{}, {'from':D0,'to':D4}, {'from':D0,'to':D4,'known_at':'2090-01-01T00:00:00Z'},
        {'known_at':D4}, {'from':D1,'to':D2,'known_at':D4}, {'from':D0,'to':'2090-01-01T00:00:00Z'}, {'from':D4,'known_at':'2090-01-01T00:00:00Z'}]
    pages=[]
    for u in toks:
        for q in qs:
            r=call('GET','/statement?'+urlencode(q),user=toks[u],base=old)
            if r[0]!=200:raise AssertionError(('statement',u,q,r[0]))
            pages.append((u,q,r[1]))
    for i in range(1,int(os.getenv('CORRECTIONS','5000'))+1):
        r=call('POST','/payments/seed0/corrections',{'expected_revision':i,'amount':1,'effective_at':D1,'reason':'same '+str(i)},user=toks['a'],key='correction'+str(i),base=old)
        if r[0]!=201:raise AssertionError(('correction',i,r[0]))
    for i in range(1,10001):
        u,v=[('a','b'),('b','c'),('c','a')][i%3]
        r=call('POST','/payments',{'to_handle':v,'amount':1},user=toks[u],key='later'+str(i),base=old)
        if r[0]!=201:raise AssertionError(('later',i,r[0]))
        if i not in [6000,10000]:continue
        data=state(old);label='combined-'+str(i)
        r=call('POST','/_test/import',data);expect(label+'-genuine',r,204)
        check(label+'-genuine-time',r[3]<5,{'seconds':r[3]})
        for n,(u,q,page) in enumerate(pages):
            got=call('GET','/statement?'+urlencode({'snapshot':page['snapshot']}),user=toks[u])[1]
            check(label+'-frozen-'+str(n),got==page)
        before=state()
        target=next(p['snapshot'] for u,q,p in pages if u=='a' and q=={'from':D0,'to':D4})
        for mutation in ['swap','shift','wrong-revision']:
            bad=copy.deepcopy(data);s=next(s for s in bad['state']['snapshots'] if s['token']==target)
            if mutation=='swap':
                s['entries'][0],s['entries'][1]=s['entries'][1],s['entries'][0]
                running=s['opening_balance']
                for e in s['entries']:running+=e[2];e[3]=running
            elif mutation=='shift':
                s['opening_balance']+=1;s['closing_balance']+=1
                for e in s['entries']:e[3]+=1
            else:s['entries'][0][1]=999999
            r=call('POST','/_test/import',bad);expect(label+'-'+mutation,r,422,'validation_failed')
            check(label+'-'+mutation+'-time',r[3]<5,{'seconds':r[3]})
            check(label+'-'+mutation+'-atomic',state()==before)
        print('COMBINED',i,flush=True)

if __name__=='__main__':
    try:run()
    except Exception as e:check('combined-uncaught',False,repr(e))
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-legacy-combined.json'),'w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
