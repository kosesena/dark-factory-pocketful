from probe_stage3 import *

def run():
    reset(histfixture());page=statement(**{'from':D0,'to':D4,'known_at':D4})[1];original=state()
    for legacy in [False,True]:
        for mode in ['drop-last','empty','shift-balances']:
            bad=copy.deepcopy(original);sn=bad['state']['snapshots'][0]
            if legacy:
                sn.pop('taken_ts',None);sn.pop('taken_seq',None)
                sn.pop('view',None)  # A pre-stage4 snapshot has no view marker either.
            if mode=='drop-last':sn['entries'].pop();sn['closing_balance']=sn['entries'][-1][3]
            elif mode=='empty':sn['entries']=[];sn['closing_balance']=sn['opening_balance']
            else:
                sn['opening_balance']+=1;sn['closing_balance']+=1
                for e in sn['entries']:e[3]+=1
            call('POST','/_test/import',original);before=state();r=call('POST','/_test/import',bad)
            expect('snapshot-completeness-'+str(legacy)+'-'+mode,r,422,'validation_failed');check('snapshot-completeness-atomic',state()==before)
            if r[0]==204:
                got=statement(snapshot=page['snapshot'])[1];check('diagnostic-inconsistent-snapshot',False,{'mode':mode,'legacy':legacy,'snapshot':got})
    call('POST','/_test/import',original)

if __name__=='__main__':
    try:run()
    except Exception as e:check('snapshot-completeness-uncaught',False,str(e))
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-snapshot-completeness.json'),'w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
