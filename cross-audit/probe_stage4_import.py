from probe_stage4 import *

def import_sweep():
    reset();p=payment('direct',amount=100,note='same',visibility='private')[1];r=refund(p['payment_id'],20)[1]
    sb={'transfers':[{'from_handle':'a','to_handle':'b','amount':100},{'from_handle':'b','to_handle':'c','amount':50}]};s=call('POST','/settlements',sb,'o','settle')[1];time.sleep(.02);b=batch([item(s['payments'][0],50),item(s['payments'][1],25)])[1]
    original=state();base=copy.deepcopy(original);base['state']['idempotency']=[]
    def pay(x,pid):return next(p for p in x['state']['payments'] if p['id']==pid)
    def rp(x):return pay(x,r['payment_id'])
    def first(x):return pay(x,s['payments'][0]['payment_id'])['revisions'][-1]
    def second(x):return pay(x,s['payments'][1]['payment_id'])['revisions'][-1]
    def corrected_refund(x):
        pp=rp(x);rev=copy.deepcopy(pp['revisions'][0]);ts=stamp();rev.update(revision=2,reason='forbidden correction',recorded_at=ts,recorded_ts=instant(ts).timestamp());pp['revisions'].append(rev)
    def mismatch_recorded(x):
        rr=second(x);old=instant(rr['recorded_at']);prev=instant(pay(x,s['payments'][1]['payment_id'])['revisions'][0]['recorded_at']);ts=prev+(old-prev)/2;rr.update(recorded_at=ts.isoformat(),recorded_ts=ts.timestamp())
    mutations=[
      ('refund-unknown-target',lambda x:rp(x).update(refund_of='missing')),
      ('refund-self-target',lambda x:rp(x).update(refund_of=r['payment_id'])),
      ('refund-wrong-note',lambda x:rp(x).update(note='changed')),
      ('refund-wrong-visibility',lambda x:rp(x).update(visibility='public')),
      ('refund-corrected',corrected_refund),
      ('batch-members-different-recorded',mismatch_recorded),
      ('batch-member-wrong-id',lambda x:second(x).update(correction_batch_id='another_batch')),
      ('settlement-member-missing-batch',lambda x:second(x).update(correction_batch_id=None)),
      ('batch-id-wrong-type',lambda x:first(x).update(correction_batch_id=42)),
      ('batch-id-too-long',lambda x:first(x).update(correction_batch_id='x'*65)),
      ('settlement-member-different-effective',lambda x:second(x).update(effective_at=D0,effective_ts=instant(D0).timestamp())),
    ]
    for name,mut in mutations:
        call('POST','/_test/import',original);before=state();bad=copy.deepcopy(base);mut(bad);res=call('POST','/_test/import',bad);expect('stage4-invalid-'+name,res,422,'validation_failed');check('stage4-atomic-'+name,state()==before)
    # Receipt corruption with source records intact.
    for name,mut in [
      ('batch-receipt-id',lambda resp:resp.update(correction_batch_id='fake')),
      ('batch-receipt-recorded',lambda resp:resp.update(recorded_at=D0)),
      ('batch-receipt-member-id',lambda resp:resp['revisions'][0].update(correction_batch_id='fake')),
      ('batch-receipt-member-amount',lambda resp:resp['revisions'][0].update(amount=1)),
      ('batch-receipt-partial',lambda resp:resp['revisions'].pop()),
      ('batch-receipt-duplicate',lambda resp:resp['revisions'].__setitem__(1,copy.deepcopy(resp['revisions'][0]))),
      ('batch-receipt-reordered',lambda resp:resp['revisions'].reverse()),
    ]:
        call('POST','/_test/import',original);before=state();bad=copy.deepcopy(original);resp=next(row[4] for row in bad['state']['idempotency'] if row[2]=='/correction-batches');mut(resp);expect(name,call('POST','/_test/import',bad),422,'validation_failed');check(name+'-atomic',state()==before)
    call('POST','/_test/import',original);before=state();bad=copy.deepcopy(original);row=next(row for row in bad['state']['idempotency'] if row[2]=='/correction-batches');row[0]='u_a';expect('batch-receipt-nonoperator-owner',call('POST','/_test/import',bad),422,'validation_failed');check('batch-receipt-owner-atomic',state()==before)
    for val in [None,'missing']:
        call('POST','/_test/import',original);before=state();bad=copy.deepcopy(original);resp=next(row[4] for row in bad['state']['idempotency'] if row[2].endswith('/refunds'));resp['refund_of']=val;expect('refund-receipt-wrong-target',call('POST','/_test/import',bad),422,'validation_failed');check('refund-receipt-target-atomic',state()==before)
    call('POST','/_test/import',original)

def additional_semantics():
    # Both new paths obey exact body identity in otherwise ignored data.
    reset();p=payment('p',amount=100)[1];path='/payments/'+p['payment_id']+'/refunds'
    b=b'{"amount":1.0,"ignored":0.10}';expect('refund-decimal',call('POST',path,user='b',key='exact',raw=b),201);expect('refund-decimal-replay',call('POST',path,user='b',key='exact',raw=b.replace(b'0.10',b'0.1')),200);expect('refund-decimal-string-conflict',call('POST',path,user='b',key='exact',raw=b.replace(b'0.10',b'"0.1"')),409,'idempotency_key_reuse')
    raw=json.dumps({'corrections':[item(p,50)],'ignored':0.1}).encode();expect('batch-body-exact',call('POST','/correction-batches',user='o',key='exact',raw=raw),201);expect('batch-body-replay',call('POST','/correction-batches',user='o',key='exact',raw=raw.replace(b'0.1',b'0.10')),200);expect('batch-body-string-conflict',call('POST','/correction-batches',user='o',key='exact',raw=raw.replace(b'0.1',b'"0.1"')),409,'idempotency_key_reuse')
    # Operator can batch correct a request payment, never a capture/refund.
    rq=request('rq',amount=10)[1];pp=call('POST','/requests/'+rq['request_id']+'/pay',{},'a','rpay')[1];expect('batch-request-payment',batch([item(pp,5)],key='rqbatch'),201)
    a=call('POST','/authorizations',{'to_handle':'b','amount':10},'a','auth')[1];cp=call('POST','/authorizations/'+a['authorization_id']+'/capture',{},'b','cap')[1];expect('batch-capture-immutable',batch([item(cp,0)],key='capbatch'),422,'linked_payment_immutable')
    rr=refund(cp['payment_id'],1,key='refundcap')[1];expect('batch-refund-immutable',batch([item(rr,0)],key='refbatch'),422,'linked_payment_immutable')
    # Full refund capacity and correction floor race share the lock.
    reset();p=payment('race',amount=100)[1]
    with cf.ThreadPoolExecutor(max_workers=2) as pool:
        f=pool.submit(refund,p['payment_id'],100);g=pool.submit(batch,[item(p,0)]);rs=[f.result(),g.result()]
    check('refund-correction-race',sum(r[0]==201 for r in rs)==1 and sum(r[0]==422 and r[1]['error']['code']=='refund_exceeds_payment' for r in rs)==1,[r[0] for r in rs]);check('race-total',sum(bal(u) for u in ['a','b','c','o'])==11000)
    # Half-open and knowledge-aware corrected statements preserve refunds as separate payments.
    reset();p=payment('p',amount=100)[1];rr=refund(p['payment_id'],20)[1];c=batch([item(p,50)])[1];s=statement()[1];check('refund-history-two-movements',len(s['entries'])==2 and sum(e['delta'] for e in s['entries'])==-30 and s['closing_balance']==9970,s)

if __name__=='__main__':
    for g in ['import_sweep','additional_semantics']:
        try:globals()[g]()
        except Exception as e:check(g+'-uncaught',False,str(e))
        print('DONE',g,flush=True)
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-stage4-import.json'),'w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
