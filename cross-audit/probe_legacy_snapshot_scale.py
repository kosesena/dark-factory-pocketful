"""Real source HTTP exports; no implementation imports or fabricated ledger state."""
from probe_stage3 import *

def run():
    old=os.getenv('OLD_LEGACY','http://cross-s3legacy-495d5d6:8080')
    reset(base=old)
    tok=call('POST','/auth/login',{'email':'a@example.com','password':'eight chars'},base=old)[1]['token']
    empty=call('GET','/statement',user=tok,base=old)[1]
    expect('first-source-payment',call('POST','/payments',{'to_handle':'b','amount':1},user=tok,key='first',base=old),201)
    nonempty=call('GET','/statement',user=tok,base=old)[1]
    original=state(old)
    expect('real-empty-first-import',call('POST','/_test/import',original),204)
    got=call('GET','/statement?'+urlencode({'snapshot':empty['snapshot']}),user=tok)[1]
    check('real-empty-first-page',got==empty,{'actual':got,'expected':empty} if got!=empty else None)
    total=int(os.getenv('LATER_FACTS','2105'))
    statuses=[];start=time.monotonic()
    for i in range(total):
        r=call('POST','/payments',{'to_handle':'b','amount':1},user=tok,key='later-'+str(i),base=old)
        statuses.append(r[0])
        if r[0]!=201:break
    check('later-facts-created',len(statuses)==total and all(s==201 for s in statuses),{'count':len(statuses),'last_status':statuses[-1],'seconds':time.monotonic()-start})
    exported=state(old);response=call('POST','/_test/import',exported)
    expect('many-later-facts-import',response,204)
    check('many-later-facts-import-time',response[3]<10,{'seconds':response[3],'facts':total})
    if response[0]==204:
        for name,page in [('empty',empty),('nonempty',nonempty)]:
            got=call('GET','/statement?'+urlencode({'snapshot':page['snapshot']}),user=tok)[1]
            check('many-later-facts-frozen-'+name,got==page,{'actual':got,'expected':page} if got!=page else None)
    before=state();bad=copy.deepcopy(exported)
    sn=next(s for s in bad['state']['snapshots'] if s['token']==nonempty['snapshot'])
    sn['opening_balance']+=1;sn['closing_balance']+=1
    for e in sn['entries']:e[3]+=1
    response=call('POST','/_test/import',bad);expect('many-later-facts-invalid',response,422,'validation_failed')
    check('many-later-facts-invalid-time',response[3]<10,{'seconds':response[3]});check('many-later-facts-invalid-atomic',state()==before)

if __name__=='__main__':
    try:run()
    except Exception as e:check('scale-uncaught',False,str(e))
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-legacy-scale.json'),'w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
