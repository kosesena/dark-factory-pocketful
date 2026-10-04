import asyncio,os,json,copy,time
os.environ['AUDIT_BASE']='http://127.0.0.1:18083'
os.environ['AUDIT_REV']='94e856c'
from probe_stage1 import *
from playwright.async_api import async_playwright,expect as pwexpect

ROOT=os.path.dirname(__file__)
async def textid(page,id):return await page.get_by_test_id(id).text_content()
async def login(browser,user='a',width=1280):
    context=await browser.new_context(viewport={'width':width,'height':900})
    page=await context.new_page();page.set_default_timeout(5000)
    await page.goto(BASE+'/login')
    await page.get_by_test_id('login-email').fill(user+'@example.com')
    await page.get_by_test_id('login-password').fill('eight chars')
    await page.get_by_test_id('login-submit').click()
    await page.get_by_test_id('wallet-balance').wait_for()
    return context,page
async def wallet(page,amount):
    await pwexpect(page.get_by_test_id('wallet-balance')).to_have_attribute('data-amount',str(amount))
    check('ui-wallet-'+str(amount),True)
async def fillpay(page,amount='15.5',note='  é 🪷  '):
    await page.get_by_test_id('pay-handle').fill('b');await page.get_by_test_id('pay-amount').fill(amount);await page.get_by_test_id('pay-note').fill(note);await page.get_by_test_id('pay-visibility').select_option('private')
async def nav(page,path):
    await page.goto(BASE+path);await page.get_by_test_id('current-user').wait_for()

async def ordinary(browser):
    reset();ctx,p=await login(browser)
    check('identity',await textid(p,'current-user')=='A' and await textid(p,'current-handle')=='a')
    check('empty-feed',await p.get_by_test_id('empty-activity').count()==1 and await p.get_by_test_id('activity-list').count()==0)
    check('no-held-ui',await p.get_by_test_id('wallet-held').count()==0)
    posts=[]
    p.on('request',lambda r:posts.append(r) if r.method=='POST' and r.url.endswith('/payments') else None)
    await fillpay(p,'15.005');await p.get_by_test_id('pay-submit').click();await p.get_by_test_id('pay-error').wait_for()
    check('excess-decimals-no-post',not posts)
    await fillpay(p);await p.get_by_test_id('pay-submit').click();await wallet(p,8450)
    check('pay-preserves-values',await p.get_by_test_id('pay-handle').input_value()=='b' and await p.get_by_test_id('pay-amount').input_value()=='15.5' and await p.get_by_test_id('pay-note').input_value()=='  é 🪷  ')
    payments=feed('a');pid=payments[0]['payment_id'];item=p.get_by_test_id('activity-item-'+pid)
    check('activity-visibility',await item.get_attribute('data-visibility')=='private')
    check('activity-parties','a' in await textid(p,'activity-parties-'+pid) and 'b' in await textid(p,'activity-parties-'+pid))
    check('activity-amount',await textid(p,'activity-amount-'+pid)=='15.50 EUR')
    check('activity-note',await textid(p,'activity-note-'+pid)=='  é 🪷  ')
    await p.get_by_test_id('pay-submit').click();await asyncio.sleep(.2);await wallet(p,8450)
    check('repeat-pay-once',len(feed('a'))==1 and await p.get_by_test_id('pay-error').count()==0)
    await p.get_by_test_id('pay-note').fill('changed');await p.get_by_test_id('pay-submit').click();await wallet(p,6900)
    check('changed-field-new-payment',len(feed('a'))==2)
    await p.get_by_test_id('request-handle').fill('b');await p.get_by_test_id('request-amount').fill('3');await p.get_by_test_id('request-note').fill('request');await p.get_by_test_id('request-submit').click()
    await asyncio.sleep(.2);check('request-ui-created',any(r['amount']==300 for r in reqs('a')))
    await nav(p,'/requests');await p.get_by_test_id('outgoing-list').wait_for()
    r=next(r for r in reqs('a') if r['amount']==300);rid=r['request_id']
    check('outgoing-controls',await p.get_by_test_id('request-cancel-'+rid).count()==1 and await p.get_by_test_id('request-pay-'+rid).count()==0)
    check('request-amount',await textid(p,'request-amount-'+rid)=='3.00 EUR')
    await p.get_by_test_id('request-cancel-'+rid).click();await pwexpect(p.get_by_test_id('request-item-'+rid)).to_have_attribute('data-status','cancelled')
    for action in ['pay','decline']:
        r=request('ui-'+action,amount=100)[1];rid=r['request_id'];await nav(p,'/requests')
        await p.get_by_test_id('request-'+action+'-'+rid).click();await pwexpect(p.get_by_test_id('request-item-'+rid)).to_have_attribute('data-status','paid' if action=='pay' else 'declined')
        check('ui-request-'+action,await p.get_by_test_id('request-pay-'+rid).count()==0)
    await nav(p,'/split');await p.get_by_test_id('split-amount').fill('0.01');await p.get_by_test_id('split-handles').fill('a,b,c');await p.get_by_test_id('split-note').fill('split')
    await p.get_by_test_id('split-preview').wait_for();check('preview-exact',[await textid(p,'split-share-'+h) for h in ['a','b','c']]==['0.01 EUR','0.00 EUR','0.00 EUR'])
    before=len(reqs('a'));await p.get_by_test_id('split-submit').click();await asyncio.sleep(.2);check('split-created',len(reqs('a'))==before+2)
    for path in ['/','/requests','/split','/authorizations','/login','/signup']:
        await nav(p,path);check('identity-every-route-'+path,await textid(p,'current-handle')=='a' and 'A' in await textid(p,'current-user'))
    await p.get_by_test_id('logout-button').click();await p.get_by_test_id('login-submit').wait_for();check('logout',await p.get_by_test_id('current-user').count()==0)
    await p.get_by_test_id('login-email').fill('a@example.com');await p.get_by_test_id('login-password').fill('wrongpass');await p.get_by_test_id('login-submit').click();await p.get_by_test_id('auth-error').wait_for();check('login-error',bool(await textid(p,'auth-error')))
    await p.goto(BASE+'/signup');await p.get_by_test_id('signup-email').fill('Fresh.Person@example.com');await p.get_by_test_id('signup-password').fill('eight chars');await p.get_by_test_id('signup-display-name').fill('Fresh Person');await p.get_by_test_id('signup-submit').click();await wallet(p,0);check('signup-derived',await textid(p,'current-handle')=='fresh_person')
    await ctx.close()

async def currency_auth(browser):
    for curr,units,balance,formatted in [('JPY',0,1200,'1200 JPY'),('BHD',3,12345,'12.345 BHD')]:
        f=copy.deepcopy(FIX);f.update(currency=curr,minor_units=units);f['users'][0]['balance']=balance;reset(f);ctx,p=await login(browser)
        check('format-'+curr,await textid(p,'wallet-balance')==formatted)
        await fillpay(p,'1.1' if units==0 else '1.0001');await p.get_by_test_id('pay-submit').click();await p.get_by_test_id('pay-error').wait_for();check('precision-'+curr,len(feed('a'))==0)
        await ctx.close()
    reset();ctx,p=await login(browser)
    await p.get_by_test_id('authorize-handle').fill('b');await p.get_by_test_id('authorize-amount').fill('20');await p.get_by_test_id('authorize-note').fill('hold');await p.get_by_test_id('authorize-visibility').select_option('private');await p.get_by_test_id('authorize-submit').click()
    await pwexpect(p.get_by_test_id('wallet-held')).to_have_attribute('data-amount','2000')
    check('held-wallet-ui',await textid(p,'wallet-available')=='80.00 EUR' and await textid(p,'wallet-held')=='20.00 EUR' and await textid(p,'wallet-balance')=='100.00 EUR')
    a=call('GET','/authorizations',user='a')[1]['authorizations'][0];aid=a['authorization_id']
    await nav(p,'/authorizations');await p.get_by_test_id('authorization-item-'+aid).wait_for()
    check('outgoing-auth-controls',await p.get_by_test_id('authorization-void-'+aid).count()==1 and await p.get_by_test_id('authorization-capture-'+aid).count()==0)
    check('auth-time-exact',await textid(p,'authorization-expires-'+aid)==a['expires_at'])
    ctxb,pb=await login(browser,'b');await nav(pb,'/authorizations');await pb.get_by_test_id('authorization-capture-'+aid).wait_for()
    check('capture-input-default',await pb.get_by_test_id('authorization-capture-amount-'+aid).input_value()=='20.00')
    await pb.get_by_test_id('authorization-capture-amount-'+aid).fill('15');await pb.get_by_test_id('authorization-capture-'+aid).click()
    await pwexpect(pb.get_by_test_id('authorization-item-'+aid)).to_have_attribute('data-status','captured')
    check('captured-formatted',await textid(pb,'authorization-captured-'+aid)=='15.00 EUR')
    await nav(p,'/');check('released-held-ui',await p.get_by_test_id('wallet-held').count()==0);await wallet(p,8500)
    # Seeded holds visible immediately, then outgoing void and empty state.
    a2=call('POST','/authorizations',{'to_handle':'b','amount':100},'a','void-ui')[1];await nav(p,'/authorizations');await p.get_by_test_id('authorization-void-'+a2['authorization_id']).click();await pwexpect(p.get_by_test_id('authorization-item-'+a2['authorization_id'])).to_have_attribute('data-status','voided')
    check('void-ui',await p.get_by_test_id('authorization-void-'+a2['authorization_id']).count()==0)
    await ctx.close();await ctxb.close()

async def failures_and_refresh(browser):
    reset();ctx,p=await login(browser);await fillpay(p,'50','keep')
    payment('other-client',to_handle='c',amount=9000)
    await p.get_by_test_id('pay-submit').click();await p.get_by_test_id('pay-error').wait_for();await wallet(p,1000)
    check('refused-preserves',await p.get_by_test_id('pay-amount').input_value()=='50' and await p.get_by_test_id('pay-note').input_value()=='keep')
    r=request('stale',amount=1)[1];await nav(p,'/requests');rid=r['request_id'];await p.get_by_test_id('request-pay-'+rid).wait_for();call('POST','/requests/'+rid+'/cancel',{},'b')
    await p.get_by_test_id('request-pay-'+rid).click();await p.get_by_test_id('request-error').wait_for();await pwexpect(p.get_by_test_id('request-item-'+rid)).to_have_attribute('data-status','cancelled');check('stale-button-removed',await p.get_by_test_id('request-pay-'+rid).count()==0)
    await ctx.close()
    reset();ctx,p=await login(browser);await fillpay(p,'1','uncertain');posts=[]
    async def lost(route):
        posts.append((route.request.headers.get('idempotency-key'),route.request.post_data))
        await route.fetch();await route.abort('failed')
    await p.route('**/payments',lost);await p.get_by_test_id('pay-submit').click();await p.get_by_test_id('pay-uncertain').wait_for()
    check('lost-not-refused',await p.get_by_test_id('pay-error').count()==0 and bool(await textid(p,'pay-uncertain')))
    await p.screenshot(path=ROOT+'/s2-uncertain-desktop.png',full_page=True)
    await p.unroute('**/payments',lost)
    async def retry(route):posts.append((route.request.headers.get('idempotency-key'),route.request.post_data));await route.continue_()
    await p.route('**/payments',retry);await p.get_by_test_id('pay-submit').click();await wallet(p,9900)
    check('retry-same-identity',len(posts)==2 and posts[0]==posts[1]);await pwexpect(p.get_by_test_id('pay-uncertain')).to_have_count(0)
    await pwexpect(p.get_by_test_id('pay-error')).to_have_count(0)
    n=len(feed('a'));check('retry-once',n==1,{'payment_count':n})
    await p.unroute('**/payments',retry)
    # Hold one earlier read, serve a later refresh with changed total and holds.
    first=asyncio.Event();release=asyncio.Event();count=0
    async def reorder(route):
        nonlocal count
        count+=1;response=await route.fetch()
        if count==1:first.set();await release.wait()
        await route.fulfill(response=response)
    await p.route('**/me',reorder);await p.get_by_test_id('wallet-refresh').click();await asyncio.wait_for(first.wait(),5)
    payment('refresh-change',amount=100);call('POST','/authorizations',{'to_handle':'b','amount':500},'a','refresh-hold')
    await p.get_by_test_id('wallet-refresh').click();await wallet(p,9800);await pwexpect(p.get_by_test_id('wallet-held')).to_have_attribute('data-amount','500')
    release.set();await asyncio.sleep(.3);check('latest-refresh-wins',await p.get_by_test_id('wallet-balance').get_attribute('data-amount')=='9800' and await p.get_by_test_id('wallet-available').get_attribute('data-amount')=='9300')
    check('refresh-preserves-form',await p.get_by_test_id('pay-note').input_value()=='uncertain')
    await ctx.close()

async def visuals(browser):
    reset()
    payment('visible',note='Lunch together',visibility='public',amount=1234)
    request('incoming',note='Shared taxi',amount=2250)
    call('POST','/requests',{'payer_handle':'b','amount':700,'note':'Coffee'},'a','outgoing')
    call('POST','/authorizations',{'to_handle':'b','amount':2000,'note':'Weekend reservation','visibility':'private'},'a','open')
    call('POST','/authorizations',{'to_handle':'a','amount':500,'note':'Incoming reservation'},'b','incoming')
    for width in [375,1280]:
        ctx,p=await login(browser,width=width)
        for path,label in [('/','wallet'),('/requests','requests'),('/authorizations','holds'),('/split','split')]:
            await nav(p,path)
            if path=='/split':
                await p.get_by_test_id('split-amount').fill('10');await p.get_by_test_id('split-handles').fill('a,b,c');await p.get_by_test_id('split-preview').wait_for()
            await p.screenshot(path=ROOT+'/s2-'+label+'-'+str(width)+'.png',full_page=True)
            dims=await p.evaluate('({vw:innerWidth,sw:document.documentElement.scrollWidth})');check('no-overflow-'+label+'-'+str(width),dims['sw']<=dims['vw'],dims)
            unlabelled=await p.locator('input,select,textarea').evaluate_all('es=>es.filter(e=>!e.labels?.length&&!e.getAttribute("aria-label")&&!e.getAttribute("aria-labelledby")).map(e=>e.dataset.testid)')
            check('visible-labels-'+label+'-'+str(width),not unlabelled,unlabelled)
        await nav(p,'/');sizes=await p.locator('[data-testid^="wallet-"]').evaluate_all('es=>es.map(e=>({id:e.dataset.testid,size:parseFloat(getComputedStyle(e).fontSize)}))');d={x['id']:x['size'] for x in sizes};check('available-headline-'+str(width),d['wallet-available']>d['wallet-balance'] and d['wallet-available']>d['wallet-held'],d)
        await p.get_by_test_id('pay-handle').focus();focus=await p.get_by_test_id('pay-handle').evaluate('e=>({outline:getComputedStyle(e).outlineStyle,width:getComputedStyle(e).outlineWidth,shadow:getComputedStyle(e).boxShadow})');check('focus-visible-'+str(width),(focus['outline']!='none' and focus['width']!='0px') or focus['shadow']!='none',focus)
        await ctx.close()

async def upgrade(browser):
    old='http://127.0.0.1:18084';call('POST','/_test/reset',FIX,base=old)
    # Serve stage2's UI while its pre-upgrade API requests target the actual stage1 process.
    reset();ctx=await browser.new_context(viewport={'width':1280,'height':900});p=await ctx.new_page();p.set_default_timeout(5000);pre=True;lose=True;ident=[]
    async def bridge(route):
        nonlocal lose
        path=route.request.url.split(BASE,1)[1]
        if not pre:await route.continue_();return
        if path.split('?')[0] not in ['/auth/login','/me','/activity','/requests','/payments'] or (route.request.headers.get('accept','').find('text/html')>=0):await route.continue_();return
        response=await route.fetch(url=old+path)
        if path=='/payments' and route.request.method=='POST':
            ident.append((route.request.headers.get('idempotency-key'),route.request.post_data))
            if lose:lose=False;await route.abort('failed');return
        await route.fulfill(response=response)
    await p.route('**/*',bridge);await p.goto(BASE+'/login');await p.get_by_test_id('login-email').fill('a@example.com');await p.get_by_test_id('login-password').fill('eight chars');await p.get_by_test_id('login-submit').click();await p.get_by_test_id('wallet-balance').wait_for()
    blog=call('POST','/auth/login',{'email':'b@example.com','password':'eight chars'},base=old)[1]['token'];r=call('POST','/requests',{'payer_handle':'a','amount':25},blog,'old-request',base=old)[1]
    await fillpay(p,'1','upgrade retained');await p.get_by_test_id('pay-submit').click();await p.get_by_test_id('pay-uncertain').wait_for()
    snap=state(old);expect('stage1-upgrade-import',call('POST','/_test/import',snap),204);pre=False
    async def record(route):ident.append((route.request.headers.get('idempotency-key'),route.request.post_data));await route.continue_()
    await p.route('**/payments',record);await p.get_by_test_id('pay-submit').click();await wallet(p,9900)
    check('upgrade-same-key-body',len(ident)==2 and ident[0]==ident[1]);check('upgrade-form-survives',await p.get_by_test_id('pay-note').input_value()=='upgrade retained' and await textid(p,'current-handle')=='a');check('upgrade-uncertainty-cleared',await p.get_by_test_id('pay-uncertain').count()==0)
    await nav(p,'/requests');await p.get_by_test_id('request-pay-'+r['request_id']).click();await pwexpect(p.get_by_test_id('request-item-'+r['request_id'])).to_have_attribute('data-status','paid');check('upgrade-pending-request-payable',True)
    await ctx.close()

async def supplementary(browser):
    reset();ctx,p=await login(browser);posts=[]
    p.on('request',lambda r:posts.append(r) if r.method=='POST' else None)
    await fillpay(p,'abc');await p.get_by_test_id('pay-submit').click();await p.get_by_test_id('pay-error').wait_for();check('nonnumeric-local',not posts)
    for prefix in ['request','authorize']:
        await p.get_by_test_id(prefix+'-handle').fill('b');await p.get_by_test_id(prefix+'-amount').fill('1.001');await p.get_by_test_id(prefix+'-submit').click();await p.get_by_test_id(prefix+'-error').wait_for();check(prefix+'-precision-local',not posts)
    for value,note,expected in [('15.00','decimal1500a',1500),('15','decimal1500b',1500)]:
        await fillpay(p,value,note);await p.get_by_test_id('pay-submit').click();await asyncio.sleep(.2);check('decimal-conversion-'+value,feed('a')[0]['amount']==expected)
    await p.get_by_test_id('authorize-amount').fill('1000');await p.get_by_test_id('authorize-submit').click();await p.get_by_test_id('authorize-error').wait_for();check('authorize-refusal-visible',bool(await textid(p,'authorize-error')))
    await p.screenshot(path=ROOT+'/s2-refused-desktop.png',full_page=True)
    await ctx.close()
    reset();ctx,p=await login(browser)
    await nav(p,'/requests');await p.get_by_test_id('empty-requests').wait_for();check('empty-requests',True)
    await nav(p,'/authorizations');await p.get_by_test_id('empty-authorizations').wait_for();check('empty-authorizations',True)
    # Seeded total is unchanged while available reflects the open fixture hold.
    from datetime import datetime,timezone,timedelta
    f=copy.deepcopy(FIX);f['authorizations']=[{'id':'seed-ui','from_user_id':'u_a','to_user_id':'u_b','amount':2345,'note':'Seeded reservation','visibility':'private','status':'open','expires_at':(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()}]
    await ctx.close();reset(f);ctx,p=await login(browser,width=375)
    check('seeded-held-ui',await textid(p,'wallet-balance')=='100.00 EUR' and await textid(p,'wallet-available')=='76.55 EUR' and await textid(p,'wallet-held')=='23.45 EUR')
    await p.screenshot(path=ROOT+'/s2-seeded-hold-375.png',full_page=True)
    # Contrast of visible text against the nearest opaque background, based on rendered styles.
    contrasts=await p.evaluate('''() => {
      const rgb=s=>(s.match(/[\\d.]+/g)||[]).map(Number);
      const lum=a=>a.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
      return [...document.querySelectorAll('body *')].filter(e=>e.getClientRects().length&&[...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim())).map(e=>{
        const cs=getComputedStyle(e),fg=rgb(cs.color);let cur=e,bg;
        while(cur){let c=rgb(getComputedStyle(cur).backgroundColor);if(c.length===3||c[3]===1){bg=c;break;}cur=cur.parentElement;}
        bg=bg||[255,255,255];const l1=lum(fg),l2=lum(bg);return {tag:e.tagName,text:e.textContent.trim().slice(0,30),ratio:(Math.max(l1,l2)+.05)/(Math.min(l1,l2)+.05),size:parseFloat(cs.fontSize),weight:parseFloat(cs.fontWeight)||400};
      });
    }''')
    bad=[x for x in contrasts if x['ratio']<(3 if x['size']>=24 or x['size']>=18.66 and x['weight']>=700 else 4.5)-.01]
    check('rendered-text-contrast',not bad,bad)
    await ctx.close()
    # Delay an earlier activity response until after a later refresh has rendered.
    reset();ctx,p=await login(browser);first=asyncio.Event();release=asyncio.Event();n=0
    async def activity_reorder(route):
        nonlocal n
        n+=1;resp=await route.fetch()
        if n==1:first.set();await release.wait()
        await route.fulfill(response=resp)
    await p.route('**/activity**',activity_reorder);await p.get_by_test_id('wallet-refresh').click();await asyncio.wait_for(first.wait(),5)
    pp=payment('new-feed',note='')[1];await p.get_by_test_id('wallet-refresh').click();await p.get_by_test_id('activity-item-'+pp['payment_id']).wait_for();release.set();await asyncio.sleep(.3)
    check('latest-feed-refresh-wins',await p.get_by_test_id('activity-item-'+pp['payment_id']).count()==1)
    check('empty-note-present',await p.get_by_test_id('activity-note-'+pp['payment_id']).count()==1 and await textid(p,'activity-note-'+pp['payment_id'])=='')
    await p.unroute('**/activity**',activity_reorder)
    # Keep the write outstanding and ensure the form cannot refresh stale pre-write data.
    gate=asyncio.Event();entered=asyncio.Event();reads=[]
    async def hold_write(route):entered.set();await gate.wait();await route.continue_()
    p.on('request',lambda r:reads.append(r.url) if r.method=='GET' and any(x in r.url for x in ['/me','/activity']) else None)
    await p.route('**/payments',hold_write);await fillpay(p,'1','delayed write');await p.get_by_test_id('pay-submit').click();await asyncio.wait_for(entered.wait(),5);await asyncio.sleep(.15)
    check('refresh-waits-for-write',not reads and await p.get_by_test_id('wallet-balance').get_attribute('data-amount')=='9990')
    gate.set();await wallet(p,9890);await ctx.close()

async def presentation_states(browser):
    reset();ctx,p=await login(browser);await fillpay(p,'1','Confirmed payment');await p.get_by_test_id('pay-submit').click();await wallet(p,9900);await asyncio.sleep(.1)
    await p.screenshot(path=ROOT+'/s2-success-desktop.png',full_page=True)
    gate=asyncio.Event();entered=asyncio.Event()
    async def delayed(route):entered.set();await gate.wait();await route.continue_()
    await p.route('**/me',delayed);await p.goto(BASE+'/requests');await asyncio.wait_for(entered.wait(),5)
    await p.screenshot(path=ROOT+'/s2-loading-desktop.png',full_page=True)
    check('loading-state-visible','Loading' in await p.locator('body').inner_text())
    gate.set();await p.get_by_test_id('current-user').wait_for();await ctx.close()
    external=[];ctx=await browser.new_context()
    async def local_only(route):
        if route.request.url.startswith(BASE):await route.continue_()
        else:external.append(route.request.url);await route.abort('blockedbyclient')
    await ctx.route('**/*',local_only);p=await ctx.new_page();await p.goto(BASE+'/login')
    await p.get_by_test_id('login-email').fill('a@example.com');await p.get_by_test_id('login-password').fill('eight chars');await p.get_by_test_id('login-submit').click();await p.get_by_test_id('wallet-balance').wait_for()
    for path in ['/requests','/split','/authorizations']:await nav(p,path)
    check('all-browser-assets-local',not external,external);await ctx.close()

async def main():
    async with async_playwright() as pl:
        b=await pl.chromium.launch()
        selected=os.environ.get('UI_GROUPS','').split(',')
        for fn in [ordinary,currency_auth,failures_and_refresh,visuals,upgrade,supplementary,presentation_states]:
            if selected!=[''] and fn.__name__ not in selected:continue
            try:await fn(b)
            except Exception as e:check(fn.__name__+'-uncaught',False,str(e)[:800])
            print('DONE',fn.__name__,flush=True)
        await b.close()
    out={'probes':len(RESULTS),'passed':sum(r['passed'] for r in RESULTS),'failed':[r for r in RESULTS if not r['passed']],'results':RESULTS}
    suffix='-'+os.environ['UI_GROUPS'] if os.environ.get('UI_GROUPS') else ''
    with open(ROOT+'/evidence-94e856c-stage2-browser'+suffix+'.json','w') as f:json.dump(out,f,indent=2)
    print('TOTAL',out['probes'],'PASS',out['passed'],'FAIL',len(out['failed']))
asyncio.run(main())
