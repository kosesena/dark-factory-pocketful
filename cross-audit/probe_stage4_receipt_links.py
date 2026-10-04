from probe_stage4 import *

def run():
    reset();p=payment('direct',amount=100)[1];q=payment('other',amount=100)[1]
    refund(p['payment_id'],10);correct(p['payment_id'],amount=90,effective_at=p['created_at']);batch([item(q,80)])
    original=state()
    for path_suffix in ['/refunds','/corrections','/correction-batches']:
        for field,value in [('owner','u_c'),('path','/not-a-write'),('receipt-type',[]),('receipt-time','bad-time')]:
            bad=copy.deepcopy(original);row=next(r for r in bad['state']['idempotency'] if r[2].endswith(path_suffix))
            if field=='owner':row[0]=value
            elif field=='path':row[2]=value
            elif field=='receipt-type':row[4]=value
            elif field=='receipt-time':row[4]['recorded_at' if path_suffix!='/refunds' else 'created_at']=value
            before=state();expect('receipt-'+path_suffix+'-'+field,call('POST','/_test/import',bad),422,'validation_failed');check('receipt-mutation-atomic',state()==before)
    # A receipt cannot be replayed on a path naming a different real target.
    for suffix in ['/refunds','/corrections']:
        bad=copy.deepcopy(original);row=next(r for r in bad['state']['idempotency'] if r[2].endswith(suffix));row[2]='/payments/'+q['payment_id']+suffix
        before=state();expect('receipt-different-target-'+suffix,call('POST','/_test/import',bad),422,'validation_failed');check('target-mutation-atomic',state()==before)
    expect('genuine-all-receipts-import',call('POST','/_test/import',original,base=DEST),204)
    check('genuine-receipts-state-identical',state(DEST)==original)

if __name__=='__main__':
    try:run()
    except Exception as e:check('receipt-links-uncaught',False,str(e))
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-receipt-links.json'),'w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
