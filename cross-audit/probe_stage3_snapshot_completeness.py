from probe_stage3 import *

def run():
    # Coordinator ruling: these two metadata-free collisions may describe an
    # alternative valid earlier state, NOT an equivalent of the original page.
    # Opt in only for the new stage4 migration contract; old audit runs keep their oracle.
    alternatives=os.getenv('AUDIT_LEGACY_ALTERNATIVES')=='1'
    reset(histfixture());page=statement(**{'from':D0,'to':D4,'known_at':D4})[1];original=state()
    for legacy in [False,True]:
        modes=['drop-last','empty','shift-balances']
        if alternatives:modes+=['empty-inconsistent','empty-impossible-opening']
        for mode in modes:
            bad=copy.deepcopy(original);sn=bad['state']['snapshots'][0]
            if legacy:
                sn.pop('taken_ts',None);sn.pop('taken_seq',None)
                sn.pop('view',None)  # A pre-stage4 snapshot has no view marker either.
            if mode=='drop-last':sn['entries'].pop();sn['closing_balance']=sn['entries'][-1][3]
            elif mode=='empty':sn['entries']=[];sn['closing_balance']=sn['opening_balance']
            elif mode=='empty-inconsistent':sn['entries']=[];sn['closing_balance']=sn['opening_balance']+1
            elif mode=='empty-impossible-opening':
                sn['entries']=[];sn['opening_balance']+=1;sn['closing_balance']=sn['opening_balance']
            else:
                sn['opening_balance']+=1;sn['closing_balance']+=1
                for e in sn['entries']:e[3]+=1
            call('POST','/_test/import',original);before=state();r=call('POST','/_test/import',bad)
            # This historical seeded fixture has no recorded moment before its
            # first included movement. Its cleared page must still reject.
            if alternatives and legacy and mode=='drop-last':
                expect('alternative-valid-earlier-state-'+mode,r,204)
                if r[0]==204:
                    expected=copy.deepcopy(page)
                    expected['opening_balance']=1000
                    expected['entries']=copy.deepcopy(page['entries'][:2]) if mode=='drop-last' else []
                    expected['closing_balance']=930 if mode=='drop-last' else 1000
                    expected['has_more']=False
                    # This legacy view predates the optional stage4 payment field.
                    for e in expected['entries']:e['payment'].pop('refund_of',None)
                    got=statement(snapshot=page['snapshot'])[1]
                    check('alternative-valid-earlier-page-'+mode,got==expected,{'actual':got,'expected':expected} if got!=expected else None)
                continue
            expect('snapshot-completeness-'+str(legacy)+'-'+mode,r,422,'validation_failed');check('snapshot-completeness-atomic',state()==before)
            if r[0]==204:
                got=statement(snapshot=page['snapshot'])[1];check('diagnostic-inconsistent-snapshot',False,{'mode':mode,'legacy':legacy,'snapshot':got})
    call('POST','/_test/import',original)
    if alternatives:
        # Separately exercise the approved empty-state collision on an API-created
        # history with a real empty first read, rather than assuming every cleared
        # historical window has a compatible recorded cutoff.
        reset();empty=statement()[1];expect('empty-state-source-payment',payment(),201)
        full=statement()[1];export=state();sn=next(s for s in export['state']['snapshots'] if s['token']==full['snapshot'])
        sn.pop('taken_ts',None);sn.pop('taken_seq',None);sn.pop('view',None)
        sn['entries']=[];sn['closing_balance']=sn['opening_balance']
        r=call('POST','/_test/import',export);expect('alternative-valid-empty-state',r,204)
        if r[0]==204:
            expected=copy.deepcopy(empty);expected['snapshot']=full['snapshot']
            got=statement(snapshot=full['snapshot'])[1]
            check('alternative-valid-empty-page',got==expected,{'actual':got,'expected':expected} if got!=expected else None)

if __name__=='__main__':
    try:run()
    except Exception as e:check('snapshot-completeness-uncaught',False,str(e))
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-snapshot-completeness.json'),'w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
