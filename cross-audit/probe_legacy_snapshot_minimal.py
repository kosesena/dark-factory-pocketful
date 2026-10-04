from probe_stage3 import *

def run():
    old=os.getenv('OLD_LEGACY','http://cross-s3legacy-495d5d6:8080')
    for change in ['none','correction','payment']:
        reset(histfixture(),base=old)
        tok=call('POST','/auth/login',{'email':'a@example.com','password':'eight chars'},base=old)[1]['token']
        page=call('GET','/statement',user=tok,base=old)[1]
        if change=='correction':
            expect('source-write-'+change,call('POST','/payments/p_b/corrections',{'expected_revision':1,'amount':150,'effective_at':D0,'reason':'later'},user=tok,key='later',base=old),201)
        if change=='payment':
            expect('source-write-'+change,call('POST','/payments',{'to_handle':'b','amount':10},user=tok,key='later',base=old),201)
        exported=state(old)
        check('metadata-free-source-'+change,all('taken_ts' not in s and 'taken_seq' not in s for s in exported['state']['snapshots']))
        expect('source-unchanged-import-'+change,call('POST','/_test/import',exported,base=old),204)
        got=call('GET','/statement?'+urlencode({'snapshot':page['snapshot']}),user=tok,base=old)[1]
        check('source-original-page-'+change,got==page)
        response=call('POST','/_test/import',exported)
        expect('destination-unchanged-import-'+change,response,204)
        if response[0]==204:check('destination-original-page-'+change,call('GET','/statement?'+urlencode({'snapshot':page['snapshot']}),user=tok)[1]==page)

if __name__=='__main__':
    try:run()
    except Exception as e:check('uncaught',False,str(e))
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(os.path.join(os.path.dirname(__file__),'evidence-'+REV+'-legacy-minimal.json'),'w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
