from probe_stage3 import *

def run():
    reset(histfixture());saved=[]
    queries=[{}, {'known_at':D0},{'known_at':D1},{'known_at':'2090-01-01T00:00:00Z'}, {'from':D1,'to':D2}, {'from':D2,'to':D2}, {'from':D3,'to':D4}, {'from':'2020-01-02T02:00:00+02:00','known_at':'2090-01-01T00:00:00Z'}, {'to':D1}, {'from':D1,'to':D4,'limit':1,'offset':1}]
    for q in queries:
        r=expect('freeze-create',statement(**q),200);saved.append((q,r,statement(snapshot=r['snapshot'],limit=200)[1]))
    # Same-second new payments and later corrections must never enter existing frozen views.
    p=payment('after-snapshots',amount=10)[1];correct(amount=150,effective_at=D0);correct(key='again',expected_revision=2,amount=80,effective_at=D3)
    rq=request('after-request',amount=10)[1];call('POST','/requests/'+rq['request_id']+'/pay',{},'a','after-pay')
    a=call('POST','/authorizations',{'to_handle':'b','amount':100},'a','after-hold')[1];call('POST','/authorizations/'+a['authorization_id']+'/capture',{'amount':20,'final':False},'b','after-capture');call('POST','/authorizations/'+a['authorization_id']+'/void',{},'a')
    export=state();expect('all-genuine-snapshots-import',call('POST','/_test/import',export,base=DEST),204)
    for q,first,full in saved:
        isolated=copy.deepcopy(export)
        isolated['state']['snapshots']=[s for s in isolated['state']['snapshots'] if s['token']==first['snapshot']]
        imported=call('POST','/_test/import',isolated,base=DEST)
        expect('individual-genuine-snapshot-import-'+json.dumps(q),imported,204)
        if imported[0]!=204:continue
        params={'snapshot':first['snapshot'],'limit':q.get('limit',50),'offset':q.get('offset',0)}
        got=call('GET','/statement?'+urlencode(params),user='a',base=DEST);check('genuine-frozen-page',got[0]==200 and got[1]==first,{'q':q,'actual':got[1],'expected':first} if got[1]!=first else None)
        got=call('GET','/statement?'+urlencode({'snapshot':first['snapshot'],'limit':200}),user='a',base=DEST);check('genuine-frozen-full',got[0]==200 and got[1]==full)
    # Corrupt existing opaque bookkeeping fields by impossible types/ranges, never source code.
    for name,value in [('taken_seq',-1),('taken_seq',True),('taken_seq','bad'),('taken_ts','bad'),('taken_ts',True)]:
        bad=copy.deepcopy(export)
        if name not in bad['state']['snapshots'][0]:continue
        bad['state']['snapshots'][0][name]=value;before=state();expect('bad-frozen-metadata-'+name+'-'+str(value),call('POST','/_test/import',bad),422,'validation_failed');check('bad-frozen-metadata-atomic',state()==before)
    # Corruption at an old revision must be rejected even after a valid newer correction.
    bad=copy.deepcopy(export);sn=next(s for s in bad['state']['snapshots'] if s['entries']);sn['entries'][0][1]=999;before=state();expect('old-snapshot-corrupt-after-corrections',call('POST','/_test/import',bad),422,'validation_failed');check('old-snapshot-corrupt-atomic',state()==before)

if __name__=='__main__':
    try:run()
    except Exception as e:check('freeze-uncaught',False,str(e))
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-freeze.json'),'w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
