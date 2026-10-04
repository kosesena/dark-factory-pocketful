from probe_stage3 import *

def sweep():
    reset(histfixture());page=statement(known_at=D4,limit=1)[1];token=page['snapshot'];original=state()
    def coherent_wrong_amount(x):
        sn=x['state']['snapshots'][0];sn['entries'][0][2]+=1;sn['entries'][0][6]+=1
        for e in sn['entries']:e[3]+=1
        sn['closing_balance']+=1
    mutations=[
      ('unknown-owner',lambda x:x['state']['snapshots'][0].update(user_id='missing')),
      ('unrelated-owner',lambda x:x['state']['snapshots'][0].update(user_id='u_o')),
      ('unknown-payment',lambda x:x['state']['snapshots'][0]['entries'][0].__setitem__(0,'missing')),
      ('unknown-revision',lambda x:x['state']['snapshots'][0]['entries'][0].__setitem__(1,99)),
      ('boolean-revision',lambda x:x['state']['snapshots'][0]['entries'][0].__setitem__(1,True)),
      ('wrong-delta',lambda x:x['state']['snapshots'][0]['entries'][0].__setitem__(2,999)),
      ('wrong-balance-after',lambda x:x['state']['snapshots'][0]['entries'][0].__setitem__(3,999)),
      ('bad-effective-time',lambda x:x['state']['snapshots'][0]['entries'][0].__setitem__(4,'bad-time')),
      ('wrong-effective-time',lambda x:x['state']['snapshots'][0]['entries'][0].__setitem__(4,D0)),
      ('bad-recorded-time',lambda x:x['state']['snapshots'][0]['entries'][0].__setitem__(5,'bad-time')),
      ('wrong-recorded-time',lambda x:x['state']['snapshots'][0]['entries'][0].__setitem__(5,D0)),
      ('wrong-selected-amount',lambda x:x['state']['snapshots'][0]['entries'][0].__setitem__(6,999)),
      ('coherent-wrong-selected-amount',coherent_wrong_amount),
      ('wrong-opening',lambda x:x['state']['snapshots'][0].update(opening_balance=999)),
      ('wrong-closing',lambda x:x['state']['snapshots'][0].update(closing_balance=999)),
      ('boolean-opening',lambda x:x['state']['snapshots'][0].update(opening_balance=True)),
      ('reverse-order',lambda x:x['state']['snapshots'][0]['entries'].reverse()),
      ('duplicate-entry',lambda x:x['state']['snapshots'][0]['entries'].append(x['state']['snapshots'][0]['entries'][0])),
      ('short-entry',lambda x:x['state']['snapshots'][0]['entries'].__setitem__(0,[])),
      ('invalid-echo',lambda x:x['state']['snapshots'][0]['echo'].update(known_at='bad-time')),
      ('knowledge-before-selected-revision',lambda x:x['state']['snapshots'][0]['echo'].update(known_at=D0)),
      ('entries-outside-echo-window',lambda x:x['state']['snapshots'][0]['echo'].update(to=D0)),
      ('duplicate-token',lambda x:x['state']['snapshots'].append(x['state']['snapshots'][0])),
      ('empty-token',lambda x:x['state']['snapshots'][0].update(token='')),
    ]
    for name,mut in mutations:
        call('POST','/_test/import',original);before=state();bad=copy.deepcopy(original);mut(bad);r=call('POST','/_test/import',bad);expect('snapshot-invalid-'+name,r,422,'validation_failed');check('snapshot-atomic-'+name,state()==before)
        if r[0]==204:
            who='o' if name=='unrelated-owner' else 'a';rr=statement(who,snapshot=token);check('diagnostic-'+name,False,{'status':rr[0],'body':rr[1]})
    call('POST','/_test/import',original)
    # Genuine older snapshots still import after later revisions and holds.
    correct();a=call('POST','/authorizations',{'to_handle':'b','amount':100},'a','hold')[1];call('POST','/authorizations/'+a['authorization_id']+'/void',{},'a')
    export=state();expect('old-snapshot-import-after-writes',call('POST','/_test/import',export),204);check('old-page-identical',statement(snapshot=token,limit=1)[1]==page)
    # Completed key/receipt corruption must remain rejected with snapshots present.
    bad=copy.deepcopy(export);bad['state']['idempotency'][0][4]['amount']=999;before=state();expect('receipt-with-snapshot-invalid',call('POST','/_test/import',bad),422,'validation_failed');check('receipt-with-snapshot-atomic',state()==before)

if __name__=='__main__':
    try:sweep()
    except Exception as e:check('sweep-uncaught',False,str(e))
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-snapshot-import.json'),'w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
