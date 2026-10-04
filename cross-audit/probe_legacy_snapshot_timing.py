"""Diagnostic after the 5000-fact probe: measure completion beyond the contract timeout."""
from probe_stage3 import *

def timed_import(export):
    started=time.monotonic()
    request=urllib.request.Request(BASE+'/_test/import',data=json.dumps(export).encode(),method='POST',headers={'Content-Type':'application/json'})
    try:r=urllib.request.urlopen(request,timeout=45)
    except urllib.error.HTTPError as e:r=e
    body=r.read();elapsed=time.monotonic()-started
    return r.status,json.loads(body) if body else None,dict(r.headers),elapsed

def run():
    old=os.getenv('OLD_LEGACY','http://cross-s3legacy-495d5d6:8080');export=state(old)
    check('diagnostic-source-size',len(export['state']['payments'])==5001 and len(export['state']['snapshots'])==2,{'payments':len(export['state']['payments']),'snapshots':len(export['state']['snapshots'])})
    r=timed_import(export);expect('diagnostic-genuine-status',r,204)
    check('diagnostic-genuine-contract-time',r[3]<=10,{'status':r[0],'seconds':r[3]})
    before=state();bad=copy.deepcopy(export);sn=next(s for s in bad['state']['snapshots'] if s['entries'])
    sn['opening_balance']+=1;sn['closing_balance']+=1
    for e in sn['entries']:e[3]+=1
    r=timed_import(bad);expect('diagnostic-corrupt-status',r,422,'validation_failed')
    check('diagnostic-corrupt-contract-time',r[3]<=10,{'status':r[0],'seconds':r[3]})
    check('diagnostic-corrupt-atomic',state()==before)

if __name__=='__main__':
    try:run()
    except Exception as e:check('timing-uncaught',False,str(e))
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-legacy-timing.json'),'w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
