"""Independent real-moment, ordering, and ruled alternative-state controls."""
from probe_stage3 import *

def stripped(s):
    for k in ['taken_ts','taken_seq','view']:s.pop(k,None)

def rejected(label,bad):
    before=state();expect(label,call('POST','/_test/import',bad),422,'validation_failed')
    check(label+'-atomic',state()==before)

def run():
    for same in [False,True]:
        f=copy.deepcopy(FIX);f['users'][0]['balance']=9970;f['users'][1]['balance']=1030
        f['payments']=[{'id':'p_late','from_user_id':'u_a','to_user_id':'u_b','amount':10,'note':'','visibility':'private','created_at':D2},
                       {'id':'p_early','from_user_id':'u_a','to_user_id':'u_b','amount':20,'note':'','visibility':'private','created_at':D2 if same else D1}]
        reset(f);page=statement()[1];orig=state()
        expect('genuine-moment-'+str(same),call('POST','/_test/import',orig),204)
        bad=copy.deepcopy(orig);s=bad['state']['snapshots'][0];stripped(s)
        if same:
            s['entries'].reverse();running=s['opening_balance']
            for e in s['entries']:running+=e[2];e[3]=running
            rejected('same-instant-swap-recomputed',bad)
        else:
            s['entries']=s['entries'][:1];s['closing_balance']=s['entries'][0][3]
            rejected('timestamp-prefix-not-sequence-prefix',bad)
    reset(histfixture());old=statement()[1];oldstate=state()
    expect('correction-before-revert',correct(),201)
    current=statement()[1];orig=state()
    target=next(s for s in orig['state']['snapshots'] if s['token']==current['snapshot'])
    oldsnap=next(s for s in oldstate['state']['snapshots'] if s['token']==old['snapshot'])
    for legacy in [False,True]:
        bad=copy.deepcopy(orig);s=next(s for s in bad['state']['snapshots'] if s['token']==current['snapshot'])
        for k in ['entries','opening_balance','closing_balance']:s[k]=copy.deepcopy(oldsnap[k])
        if not legacy:rejected('explicit-metadata-reverted-correction',bad);continue
        stripped(s);expect('legacy-earlier-revision-alternative',call('POST','/_test/import',bad),204)
        got=statement(snapshot=current['snapshot'])[1];expected=copy.deepcopy(old);expected['snapshot']=current['snapshot']
        for e in expected['entries']:e['payment'].pop('refund_of',None)
        check('legacy-earlier-revision-exact-page',got==expected,{'actual':got,'expected':expected} if got!=expected else None)

if __name__=='__main__':
    try:run()
    except Exception as e:check('moment-uncaught',False,repr(e))
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-moment-controls.json'),'w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
