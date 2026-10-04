"""Unchanged-amount revisions leave count/sum screening invariant; HTTP-only."""
from probe_stage3 import *

def run():
    old=os.environ['OLD_LEGACY'];reset(base=old)
    tok=call('POST','/auth/login',{'email':'a@example.com','password':'eight chars'},base=old)[1]['token']
    first=None
    for i in range(1000):
        r=call('POST','/payments',{'to_handle':'b','amount':1},user=tok,key='p-'+str(i),base=old)
        if r[0]!=201:raise AssertionError(('payment',i,r[0]))
        if first is None:first=r[1]
    pages=[call('GET','/statement',user=tok,base=old)[1] for _ in range(int(os.getenv('SNAPSHOTS','1')))];page=pages[0]
    for i in range(1,5001):
        r=call('POST','/payments/'+first['payment_id']+'/corrections',{'expected_revision':i,'amount':1,'effective_at':first['created_at'],'reason':'same amount '+str(i)},user=tok,key='c-'+str(i),base=old)
        if r[0]!=201:raise AssertionError(('correction',i,r[0],r[1]))
        if i not in ([5000] if len(pages)>1 else [1000,3000,5000]):continue
        exported=state(old);r=call('POST','/_test/import',exported)
        expect('same-amount-'+str(i)+'-import',r,204)
        check('same-amount-'+str(i)+'-time',r[3]<10,{'seconds':r[3]})
        if r[0]==204:
            got=call('GET','/statement?'+urlencode({'snapshot':page['snapshot']}),user=tok)[1]
            check('same-amount-'+str(i)+'-frozen',got==page)
        print('CORRECTIONS',i,'IMPORT',r[0],r[3],flush=True)

if __name__=='__main__':
    try:run()
    except Exception as e:check('correction-scale-uncaught',False,repr(e))
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-legacy-correction-scale.json'),'w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
