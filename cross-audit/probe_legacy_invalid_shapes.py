from probe_stage3 import *

def run():
    reset(histfixture());page=statement(**{'from':D0,'to':D4,'known_at':D4})[1];original=state()
    def drop(sn,index):
        sn['entries'].pop(index);balance=sn['opening_balance']
        for entry in sn['entries']:balance+=entry[2];entry[3]=balance
        sn['closing_balance']=balance
    mutations=[
        ('drop-first-coherent',lambda s:drop(s,0)),
        ('drop-middle-coherent',lambda s:drop(s,1)),
        ('reverse',lambda s:s['entries'].reverse()),
        ('duplicate',lambda s:s['entries'].append(copy.deepcopy(s['entries'][-1]))),
        ('other-party-owner',lambda s:s.update(user_id='u_b')),
        ('unrelated-owner',lambda s:s.update(user_id='u_o')),
        ('impossible-window',lambda s:s['echo'].update(to=D0)),
        ('unknown-revision',lambda s:s['entries'][0].__setitem__(1,999)),
        ('bad-echo',lambda s:s['echo'].update(known_at='not an instant')),
    ]
    for field in ['entries','echo']:
        for value in [None,True,123,'bad']:
            mutations.append((field+'-'+str(value),lambda s,k=field,v=value:s.__setitem__(k,v)))
    for value in [None,True,123,'bad',{},[]]:
        mutations.append(('entry-'+str(value),lambda s,v=value:s['entries'].__setitem__(0,v)))
    for legacy in [False,True]:
        for name,mutate in mutations:
            call('POST','/_test/import',original);before=state();bad=copy.deepcopy(original);sn=bad['state']['snapshots'][0]
            if legacy:
                for key in ['taken_ts','taken_seq','view']:sn.pop(key,None)
            mutate(sn);response=call('POST','/_test/import',bad)
            expect('invalid-shape-'+str(legacy)+'-'+name,response,422,'validation_failed')
            check('invalid-shape-atomic-'+str(legacy)+'-'+name,state()==before)
    call('POST','/_test/import',original)

if __name__=='__main__':
    try:run()
    except Exception as e:check('shape-uncaught',False,str(e))
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-legacy-shapes.json'),'w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
