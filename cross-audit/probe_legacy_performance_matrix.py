"""Independent HTTP-only real-495d5d6 migration and multi-snapshot timing oracle."""
from probe_stage3 import *

def run():
    old=os.environ['OLD_LEGACY'];f=copy.deepcopy(FIX)
    f['users'][0]['balance']=20000
    reset(f,base=old)
    tok=call('POST','/auth/login',{'email':'a@example.com','password':'eight chars'},base=old)[1]['token']
    pages=[call('GET','/statement',user=tok,base=old)[1] for _ in range(10)]
    expect('first-payment',call('POST','/payments',{'to_handle':'b','amount':1},user=tok,key='first',base=old),201)
    pages += [call('GET','/statement',user=tok,base=old)[1] for _ in range(10)]
    for i in range(1,10001):
        r=call('POST','/payments',{'to_handle':'b','amount':1},user=tok,key='later-'+str(i),base=old)
        if r[0]!=201:raise AssertionError(('source-payment',i,r[0]))
        if i not in [4000,5000,6000,10000]:continue
        export=state(old)
        for count in [10,20]:
            selected=pages[:count//2]+pages[10:10+count//2]
            tokens={p['snapshot'] for p in selected}
            data=copy.deepcopy(export)
            data['state']['snapshots']=[s for s in data['state']['snapshots'] if s['token'] in tokens]
            label=f'{i}-facts-{count}-snapshots'
            r=call('POST','/_test/import',data)
            expect(label+'-genuine',r,204)
            check(label+'-genuine-time',r[3]<5,{'seconds':r[3]})
            for page in selected:
                got=call('GET','/statement?'+urlencode({'snapshot':page['snapshot']}),user=tok)[1]
                check(label+'-exact-page-'+page['snapshot'],got==page)
            before=state();bad=copy.deepcopy(data)
            s=next(s for s in bad['state']['snapshots'] if s['token']==selected[-1]['snapshot'])
            s['opening_balance']+=1;s['closing_balance']+=1
            for e in s['entries']:e[3]+=1
            r=call('POST','/_test/import',bad)
            expect(label+'-shifted',r,422,'validation_failed')
            check(label+'-shifted-time',r[3]<5,{'seconds':r[3]})
            check(label+'-shifted-atomic',state()==before)
        print('CHECKPOINT',i,flush=True)

if __name__=='__main__':
    try:run()
    except Exception as e:check('matrix-uncaught',False,repr(e))
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-legacy-performance-matrix.json'),'w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
