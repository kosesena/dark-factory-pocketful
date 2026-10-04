import os,json,asyncio
os.environ.setdefault('AUDIT_BASE','http://127.0.0.1:18083')
os.environ.setdefault('AUDIT_REV','d78f1bd')
from probe_stage1 import *
from playwright.async_api import async_playwright
ROOT=os.path.join(os.path.dirname(__file__),REV)
os.makedirs(ROOT,exist_ok=True)

async def main():
    reset()
    for i in range(3):
        payment('layout-pay-'+str(i),amount=10,note='Shared lunch '+str(i))
        request('layout-request-'+str(i),amount=10,note='Shared taxi '+str(i))
        call('POST','/authorizations',{'to_handle':'b','amount':10,'note':'Reservation '+str(i)},'a','layout-auth-'+str(i))
    async with async_playwright() as pl:
        browser=await pl.chromium.launch()
        for width in [375,900,1280]:
            ctx=await browser.new_context(viewport={'width':width,'height':900})
            p=await ctx.new_page();p.set_default_timeout(5000)
            await p.goto(BASE+'/login')
            await p.get_by_test_id('login-email').fill('a@example.com')
            await p.get_by_test_id('login-password').fill('eight chars')
            await p.get_by_test_id('login-submit').click()
            await p.get_by_test_id('wallet-available').wait_for()
            pad=await p.get_by_test_id('wallet-refresh').evaluate('e=>{let s=getComputedStyle(e);return {left:s.paddingLeft,right:s.paddingRight,top:s.paddingTop,bottom:s.paddingBottom,width:e.getBoundingClientRect().width}}')
            check('refresh-symmetric-'+str(width),pad['left']==pad['right'] and pad['top']==pad['bottom'],pad)
            for path,listid in [('/','activity-list'),('/requests','incoming-list'),('/authorizations','authorization-list')]:
                await p.goto(BASE+path)
                lis=p.get_by_test_id(listid);await lis.wait_for()
                await p.locator('[data-testid="'+listid+'"] > *').nth(2).wait_for()
                boxes=await lis.evaluate('e=>({outer:e.getBoundingClientRect().toJSON(),items:[...e.children].map(c=>c.getBoundingClientRect().toJSON())})')
                a,b,c=boxes['items'][:3]
                if width>=900 and listid!='incoming-list':
                    check('two-column-'+listid+'-'+str(width),abs(a['top']-b['top'])<2 and b['left']>a['left'],boxes)
                    check('odd-card-spans-'+listid+'-'+str(width),abs(c['width']-boxes['outer']['width'])<2,boxes)
                else:check('single-column-'+listid+'-'+str(width),a['top']<b['top']<c['top'] and abs(c['width']-boxes['outer']['width'])<2,boxes)
                dims=await p.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})')
                check('layout-no-overflow-'+listid+'-'+str(width),dims['scroll']<=dims['width'],dims)
                await p.screenshot(path=ROOT+'/layout-'+listid+'-'+str(width)+'.png',full_page=True)
            await ctx.close()
        await browser.close()
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    with open(ROOT+'/evidence-'+REV+'-layout.json','w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
asyncio.run(main())
