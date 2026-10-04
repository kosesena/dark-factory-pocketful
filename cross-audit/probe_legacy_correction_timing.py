"""Diagnostic continuation of correction-scale; long timeout observes eventual response."""
from probe_stage3 import *

def timed(data):
    start=time.monotonic();req=urllib.request.Request(BASE+'/_test/import',data=json.dumps(data).encode(),headers={'Content-Type':'application/json'},method='POST')
    try:r=urllib.request.urlopen(req,timeout=120)
    except urllib.error.HTTPError as e:r=e
    b=r.read();return r.status,json.loads(b) if b else None,dict(r.headers),time.monotonic()-start

def run():
    data=state(os.environ['OLD_LEGACY'])
    check('source-shape',len(data['state']['payments'])==1000 and len(data['state']['snapshots'])==20)
    # Wait for the contract-timeout request to finish before timing a fresh one.
    urllib.request.urlopen(BASE+'/_test/export',timeout=120).read()
    r=timed(data);expect('diagnostic-correction20-genuine',r,204)
    check('diagnostic-correction20-genuine-time',r[3]<=10,{'seconds':r[3]})
    print('GENUINE',r[0],r[3],flush=True)
    before=state();bad=copy.deepcopy(data);s=bad['state']['snapshots'][-1]
    # Full arithmetic remains consistent; stored ordering must still be rejected.
    s['entries'][0],s['entries'][1]=s['entries'][1],s['entries'][0]
    running=s['opening_balance']
    for e in s['entries']:running+=e[2];e[3]=running
    r=timed(bad);expect('diagnostic-correction20-reordered',r,422,'validation_failed')
    check('diagnostic-correction20-reordered-time',r[3]<=10,{'seconds':r[3]})
    check('diagnostic-correction20-reordered-atomic',state()==before)
    print('REORDERED',r[0],r[3],flush=True)

if __name__=='__main__':
    try:run()
    except Exception as e:check('timing-uncaught',False,repr(e))
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-legacy-correction-timing.json'),'w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
