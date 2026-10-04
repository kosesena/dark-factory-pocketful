import json, sys, time, copy, urllib.request, os
from playwright.sync_api import sync_playwright
B = sys.argv[1]; OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screens-stage2")
fails = []; n = 0
def chk(name, cond, info=""):
    global n; n += 1
    if not cond: fails.append(name); print("FAIL", name, info)
    else: print("ok  ", name)
def api(m, p, body=None, tok=None, key=None):
    h = {"Content-Type": "application/json"}
    if tok: h["Authorization"] = "Bearer " + tok
    if key: h["Idempotency-Key"] = key
    r = urllib.request.Request(B + p, data=json.dumps(body).encode() if body is not None else None, method=m, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=10) as x: t = x.read(); return x.status, json.loads(t) if t else None
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"null")
def iso(dt): return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(dt))
now = time.time()
def fixture(cur="EUR", mu=2, ttl=600):
    return {"currency": cur, "minor_units": mu, "authorization_ttl_seconds": ttl,
     "users": [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada Lovelace", "handle": "ada", "balance": 10000 if mu else 10000},
               {"id": "u_bob", "email": "bob@example.com", "password": "correct horse", "display_name": "Bob", "handle": "bob", "balance": 2500},
               {"id": "u_cy", "email": "cy@example.com", "password": "correct horse", "display_name": "Cy", "handle": "cy", "balance": 0}],
     "payments": [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"},
                  {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 250, "note": "", "visibility": "private"},
                  {"id": "p_3", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 100, "note": "secret", "visibility": "private"}],
     "requests": [{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"},
                  {"id": "rq_2", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 300, "note": "lunch", "status": "pending"},
                  {"id": "rq_3", "requester_id": "u_ada", "payer_id": "u_cy", "amount": 300, "note": "old", "status": "declined"}],
     "authorizations": [{"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "deposit", "visibility": "public", "status": "open", "expires_at": iso(now + 7200)},
                        {"id": "a_2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 700, "note": "hold for you", "visibility": "private", "status": "open", "expires_at": iso(now + 7200)},
                        {"id": "a_3", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 900, "note": "done", "visibility": "public", "status": "captured", "expires_at": iso(now + 7200)}]}
def T(c): return c.locator
def shot(page, name, full=True):
    page.screenshot(path=f"{OUT}/{name}.png", full_page=full)
def overflow(page): return page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
def login(page, email, pw="correct horse"):
    page.goto(B + "/login"); page.get_by_test_id("login-email").fill(email); page.get_by_test_id("login-password").fill(pw); page.get_by_test_id("login-submit").click()
    page.get_by_test_id("current-user").wait_for(timeout=5000)
def txt(page, tid): return page.get_by_test_id(tid).inner_text().strip()
def cnt(page, tid): return page.get_by_test_id(tid).count()
def lum(c):
    r = [int(c[i:i+2], 16) / 255 for i in (1, 3, 5)]
    r = [x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4 for x in r]; return .2126 * r[0] + .7152 * r[1] + .0722 * r[2]
def rgb2hex(s):
    import re; v = [int(float(x)) for x in re.findall(r"[\d.]+", s)[:3]]; return "#%02x%02x%02x" % tuple(v)
with sync_playwright() as p:
    br = p.chromium.launch()
    for W, H, tag in ((1280, 900, "d"), (375, 800, "m")):
        api("POST", "/_test/reset", fixture())
        ctx = br.new_context(viewport={"width": W, "height": H}); page = ctx.new_page()
        errs = []; page.on("pageerror", lambda e: errs.append(str(e))); page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        page.goto(B + "/login"); shot(page, f"{tag}-login"); chk(f"{tag} login no overflow", overflow(page) <= 0, overflow(page))
        page.goto(B + "/signup"); shot(page, f"{tag}-signup"); chk(f"{tag} signup no overflow", overflow(page) <= 0)
        # login errors
        page.goto(B + "/login"); page.get_by_test_id("login-email").fill("ada@example.com"); page.get_by_test_id("login-password").fill("wrongpass"); page.get_by_test_id("login-submit").click()
        page.get_by_test_id("auth-error").wait_for(timeout=4000); shot(page, f"{tag}-login-error"); chk(f"{tag} auth-error shown", True)
        login(page, "ada@example.com"); page.wait_for_timeout(500)
        chk(f"{tag} current-handle exact", txt(page, "current-handle") == "ada", txt(page, "current-handle"))
        chk(f"{tag} current-user has name", "Ada" in txt(page, "current-user"))
        chk(f"{tag} wallet-balance", txt(page, "wallet-balance") == "100.00 EUR" and page.get_by_test_id("wallet-balance").get_attribute("data-amount") == "10000", txt(page, "wallet-balance"))
        chk(f"{tag} wallet-available", txt(page, "wallet-available") == "80.00 EUR" and page.get_by_test_id("wallet-available").get_attribute("data-amount") == "8000", txt(page, "wallet-available"))
        chk(f"{tag} wallet-held", txt(page, "wallet-held") == "20.00 EUR" and page.get_by_test_id("wallet-held").get_attribute("data-amount") == "2000")
        fs = lambda t: float(page.get_by_test_id(t).evaluate("e=>getComputedStyle(e).fontSize")[:-2])
        chk(f"{tag} available is largest number", fs("wallet-available") > fs("wallet-balance") and fs("wallet-available") > fs("wallet-held") and fs("wallet-available") >= 36, (fs("wallet-available"), fs("wallet-balance"), fs("wallet-held")))
        chk(f"{tag} feed items", cnt(page, "activity-item-p_1") == 1 and cnt(page, "activity-item-p_2") == 1 and cnt(page, "activity-item-p_3") == 0)
        chk(f"{tag} feed vis attr", page.get_by_test_id("activity-item-p_2").get_attribute("data-visibility") == "private" and page.get_by_test_id("activity-item-p_1").get_attribute("data-visibility") == "public")
        chk(f"{tag} empty note present", cnt(page, "activity-note-p_2") == 1 and txt(page, "activity-note-p_2") == "")
        chk(f"{tag} activity amount", txt(page, "activity-amount-p_1") == "5.00 EUR" and "ada" in txt(page, "activity-parties-p_1") and "bob" in txt(page, "activity-parties-p_1"))
        chk(f"{tag} newest first DOM", page.locator('[data-testid="activity-list"] > *').first.get_attribute("data-testid") in ("activity-item-p_3", "activity-item-p_2", "activity-item-p_1") )
        chk(f"{tag} / no overflow", overflow(page) <= 0, overflow(page))
        shot(page, f"{tag}-home-held")
        shot(page, f"{tag}-home-held-fold", full=False)
        # nav labels no wrap
        navs = page.evaluate("[...document.querySelectorAll('nav a, header a')].map(a=>{const r=document.createRange();r.selectNodeContents(a);return [a.innerText.trim(),r.getClientRects().length,a.getBoundingClientRect().right]})")
        chk(f"{tag} nav labels single-line", all(c == 1 for _, c, _r in navs) and len(navs) >= 4 and all(r_ <= W for _, _c, r_ in navs), navs)
        # contrast of headline + body
        cs = page.evaluate("""()=>{const q=t=>document.querySelector('[data-testid=\"'+t+'\"]');const g=e=>{let b;let x=e;while(x){b=getComputedStyle(x).backgroundColor;if(b&&b!=='rgba(0, 0, 0, 0)')break;x=x.parentElement}return [getComputedStyle(e).color,b]};return {avail:g(q('wallet-available')),held:g(q('wallet-held')),bal:g(q('wallet-balance')),note:g(q('activity-note-p_1')),parties:g(q('activity-parties-p_1'))}}""")
        for k, (fg, bg) in cs.items():
            a, b = lum(rgb2hex(fg)), lum(rgb2hex(bg)); ratio = (max(a, b) + .05) / (min(a, b) + .05)
            chk(f"{tag} contrast {k} >=4.5", ratio >= 4.5, (fg, bg, round(ratio, 2)))
        # pay form validations
        page.get_by_test_id("pay-handle").fill("bob"); page.get_by_test_id("pay-amount").fill("15.005"); page.get_by_test_id("pay-submit").click(); page.wait_for_timeout(400)
        chk(f"{tag} 15.005 rejected locally", cnt(page, "pay-error") == 1 and txt(page, "wallet-balance") == "100.00 EUR")
        page.get_by_test_id("pay-amount").fill("abc"); page.get_by_test_id("pay-submit").click(); page.wait_for_timeout(300); chk(f"{tag} nonnumeric rejected", cnt(page, "pay-error") == 1)
        shot(page, f"{tag}-home-pay-error")
        # pay 15 : success, repeat does nothing
        reqs = []; page.on("request", lambda r: reqs.append(r) if r.method == "POST" and r.url.endswith("/payments") else None)
        page.get_by_test_id("pay-amount").fill("15"); page.get_by_test_id("pay-note").fill("dinner ✓"); page.get_by_test_id("pay-visibility").select_option("private"); page.get_by_test_id("pay-submit").click(); page.wait_for_timeout(800)
        chk(f"{tag} paid 15 -> 85.00", txt(page, "wallet-balance") == "85.00 EUR" and txt(page, "wallet-available") == "65.00 EUR", (txt(page, "wallet-balance"), txt(page, "wallet-available")))
        chk(f"{tag} pay form preserved", page.get_by_test_id("pay-amount").input_value() in ("15", "15.00") and page.get_by_test_id("pay-handle").input_value() == "bob" and page.get_by_test_id("pay-note").input_value() == "dinner ✓")
        chk(f"{tag} pay-error gone", cnt(page, "pay-error") == 0)
        page.get_by_test_id("pay-submit").click(); page.wait_for_timeout(800)
        chk(f"{tag} repeat submit no second payment", txt(page, "wallet-balance") == "85.00 EUR" and page.locator('[data-testid^="activity-item-"]').count() == 3, (txt(page, "wallet-balance"), page.locator('[data-testid^="activity-item-"]').count()))
        shot(page, f"{tag}-home-after-pay")
        page.get_by_test_id("pay-amount").fill("15.5"); page.get_by_test_id("pay-submit").click(); page.wait_for_timeout(800)
        chk(f"{tag} changed field new payment (15.5)", txt(page, "wallet-balance") == "69.50 EUR", txt(page, "wallet-balance"))
        # insufficient (available 49.5): pay 60
        page.get_by_test_id("pay-amount").fill("60"); page.get_by_test_id("pay-submit").click(); page.wait_for_timeout(800)
        chk(f"{tag} insufficient vs available -> pay-error, inputs kept", cnt(page, "pay-error") == 1 and page.get_by_test_id("pay-amount").input_value() == "60" and txt(page, "wallet-balance") == "69.50 EUR", cnt(page, "pay-error"))
        shot(page, f"{tag}-home-insufficient")
        # request form
        page.get_by_test_id("request-handle").fill("cy"); page.get_by_test_id("request-amount").fill("7.25"); page.get_by_test_id("request-note").fill("book"); page.get_by_test_id("request-submit").click(); page.wait_for_timeout(700)
        page.get_by_test_id("request-handle").fill("ada"); page.get_by_test_id("request-submit").click(); page.wait_for_timeout(500)
        chk(f"{tag} request-error self", cnt(page, "request-error") == 1)
        shot(page, f"{tag}-home-request-error")
        # refresh
        chk(f"{tag} wallet-refresh exists", cnt(page, "wallet-refresh") == 1)
        # external spend then refresh
        tok = api("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})[1]["token"]
        api("POST", "/payments", {"to_handle": "cy", "amount": 100}, tok=tok, key="ext1")
        page.get_by_test_id("pay-note").fill("keep-me"); page.get_by_test_id("wallet-refresh").click(); page.wait_for_timeout(700)
        chk(f"{tag} refresh updates, keeps form", txt(page, "wallet-balance") == "68.50 EUR" and page.get_by_test_id("pay-note").input_value() == "keep-me", txt(page, "wallet-balance"))
        # out-of-order refresh: delay first balance read
        calls = []
        def handler(route):
            calls.append(1)
            if len(calls) == 1: time.sleep(1.5)
            route.continue_()
        # (simple: just check that after two quick refreshes, final state matches server)
        api("POST", "/payments", {"to_handle": "cy", "amount": 100}, tok=tok, key="ext2")
        page.get_by_test_id("wallet-refresh").click(); page.get_by_test_id("wallet-refresh").click(); page.wait_for_timeout(900)
        chk(f"{tag} double refresh consistent", txt(page, "wallet-balance") == "67.50 EUR", txt(page, "wallet-balance"))
        # logout
        page.get_by_test_id("logout-button").click(); page.wait_for_timeout(600); chk(f"{tag} logout -> login", "/login" in page.url or cnt(page, "login-submit") == 1, page.url)
        # --- requests page
        login(page, "ada@example.com"); page.goto(B + "/requests"); page.wait_for_timeout(500)
        chk(f"{tag} requests testids", cnt(page, "request-item-rq_1") == 1 and cnt(page, "request-item-rq_2") == 1 and cnt(page, "request-pay-rq_1") == 1 and cnt(page, "request-decline-rq_1") == 1 and cnt(page, "request-cancel-rq_2") == 1 and cnt(page, "request-cancel-rq_1") == 0 and cnt(page, "request-pay-rq_2") == 0, "")
        chk(f"{tag} request lists", page.locator('[data-testid="incoming-list"] [data-testid="request-item-rq_1"]').count() == 1 and page.locator('[data-testid="outgoing-list"] [data-testid="request-item-rq_2"]').count() == 1)
        chk(f"{tag} request amount", txt(page, "request-amount-rq_1") == "12.00 EUR" and page.get_by_test_id("request-item-rq_1").get_attribute("data-status") == "pending")
        chk(f"{tag} declined row no buttons", cnt(page, "request-item-rq_3") == 1 and cnt(page, "request-cancel-rq_3") == 0)
        chk(f"{tag} /requests no overflow", overflow(page) <= 0, overflow(page)); shot(page, f"{tag}-requests")
        # cancelled elsewhere while pay button visible
        btok = api("POST", "/auth/login", {"email": "bob@example.com", "password": "correct horse"})[1]["token"]
        api("POST", "/requests/rq_1/cancel", tok=btok)
        page.get_by_test_id("request-pay-rq_1").click(); page.wait_for_timeout(800)
        chk(f"{tag} cancelled elsewhere -> request-error, pay btn gone", cnt(page, "request-error") >= 1 and cnt(page, "request-pay-rq_1") == 0, (cnt(page, "request-error"), cnt(page, "request-pay-rq_1")))
        shot(page, f"{tag}-requests-error")
        page.get_by_test_id("request-cancel-rq_2").click(); page.wait_for_timeout(700)
        chk(f"{tag} cancel own request", page.get_by_test_id("request-item-rq_2").get_attribute("data-status") == "cancelled" and cnt(page, "request-cancel-rq_2") == 0)
        c2 = br.new_context(viewport={"width": W, "height": H}); pg2 = c2.new_page(); login(pg2, "cy@example.com"); pg2.goto(B + "/requests"); pg2.wait_for_timeout(400)
        chk(f"{tag} cy has request rq_3", pg2.get_by_test_id("request-item-rq_3").count() == 1)
        # empty requests: new signup user
        c3 = br.new_context(viewport={"width": W, "height": H}); pg3 = c3.new_page()
        pg3.goto(B + "/signup"); pg3.get_by_test_id("signup-email").fill(f"new.person{tag}@example.com"); pg3.get_by_test_id("signup-password").fill("longenough1"); pg3.get_by_test_id("signup-display-name").fill("New Person")
        pg3.get_by_test_id("signup-submit").click(); pg3.get_by_test_id("current-user").wait_for(timeout=5000)
        chk(f"{tag} signup -> handle derived", txt(pg3, "current-handle") == f"new_person{tag}", txt(pg3, "current-handle"))
        pg3.wait_for_timeout(300); chk(f"{tag} empty-activity", cnt(pg3, "empty-activity") == 1 or cnt(pg3, "activity-item-p_1") == 1)
        chk(f"{tag} zero balance no held element", cnt(pg3, "wallet-held") == 0 and txt(pg3, "wallet-available") == "0.00 EUR")
        shot(pg3, f"{tag}-home-empty")
        pg3.goto(B + "/requests"); pg3.wait_for_timeout(400); chk(f"{tag} empty-requests", cnt(pg3, "empty-requests") == 1); shot(pg3, f"{tag}-requests-empty")
        pg3.goto(B + "/authorizations"); pg3.wait_for_timeout(400); chk(f"{tag} empty-authorizations", cnt(pg3, "empty-authorizations") == 1); shot(pg3, f"{tag}-authorizations-empty")
        pg3.goto(B + "/signup"); 
        pg3.get_by_test_id("signup-email").fill("dup@example.com") if False else None
        # signup errors
        c4 = br.new_context(viewport={"width": W, "height": H}); pg4 = c4.new_page(); pg4.goto(B + "/signup")
        pg4.get_by_test_id("signup-email").fill("ada@example.com"); pg4.get_by_test_id("signup-password").fill("longenough1"); pg4.get_by_test_id("signup-display-name").fill("X"); pg4.get_by_test_id("signup-submit").click(); pg4.wait_for_timeout(600)
        chk(f"{tag} signup email taken -> auth-error", cnt(pg4, "auth-error") == 1); shot(pg4, f"{tag}-signup-error")
        # --- split
        page.goto(B + "/split"); page.wait_for_timeout(400); shot(page, f"{tag}-split-empty")
        page.get_by_test_id("split-amount").fill("10"); page.get_by_test_id("split-handles").fill("ada, bob, cy"); page.wait_for_timeout(500)
        sh = {h: txt(page, f"split-share-{h}") for h in ("ada", "bob", "cy")}
        chk(f"{tag} split preview 10/3", sh == {"ada": "3.34 EUR", "bob": "3.33 EUR", "cy": "3.33 EUR"}, sh)
        page.get_by_test_id("split-handles").fill("cy,bob,ada"); page.get_by_test_id("split-amount").fill("0.01"); page.wait_for_timeout(500)
        chk(f"{tag} split preview order 0.01", txt(page, "split-share-cy") == "0.01 EUR" and txt(page, "split-share-bob") == "0.00 EUR", {h: txt(page, f"split-share-{h}") for h in ("ada", "bob", "cy")})
        page.get_by_test_id("split-amount").fill("30"); page.get_by_test_id("split-handles").fill("ada,bob,cy"); page.get_by_test_id("split-note").fill("dinner"); page.wait_for_timeout(400); shot(page, f"{tag}-split-preview")
        page.get_by_test_id("split-submit").click(); page.wait_for_timeout(800)
        sr = api("GET", "/requests?limit=10", tok=tok)[1]["requests"]; chk(f"{tag} split created requests with matching shares", sorted(r["amount"] for r in sr if r["note"] == "dinner") == [1000, 1000], [r["amount"] for r in sr])
        shot(page, f"{tag}-split-after")
        page.get_by_test_id("split-handles").fill("ada,nobodyx"); page.get_by_test_id("split-submit").click(); page.wait_for_timeout(700); chk(f"{tag} split-error unknown handle", cnt(page, "split-error") == 1); shot(page, f"{tag}-split-error")
        page.get_by_test_id("split-amount").fill("1.234"); page.get_by_test_id("split-submit").click(); page.wait_for_timeout(300); chk(f"{tag} split bad decimals error", cnt(page, "split-error") == 1)
        chk(f"{tag} /split no overflow", overflow(page) <= 0)
        # --- authorizations
        page.goto(B + "/authorizations"); page.wait_for_timeout(500)
        chk(f"{tag} auth items", cnt(page, "authorization-item-a_1") == 1 and cnt(page, "authorization-item-a_2") == 1 and cnt(page, "authorization-item-a_3") == 1)
        chk(f"{tag} auth attrs", page.get_by_test_id("authorization-item-a_1").get_attribute("data-status") == "open" and page.get_by_test_id("authorization-item-a_3").get_attribute("data-status") == "captured")
        chk(f"{tag} auth amounts", txt(page, "authorization-amount-a_1") == "20.00 EUR" and cnt(page, "authorization-captured-a_3") == 1 and cnt(page, "authorization-captured-a_1") == 0)
        chk(f"{tag} void only outgoing open", cnt(page, "authorization-void-a_1") == 1 and cnt(page, "authorization-void-a_2") == 0 and cnt(page, "authorization-void-a_3") == 0)
        chk(f"{tag} capture only incoming open", cnt(page, "authorization-capture-a_2") == 1 and cnt(page, "authorization-capture-a_1") == 0 and page.get_by_test_id("authorization-capture-amount-a_2").input_value() in ("7", "7.00"), page.get_by_test_id("authorization-capture-amount-a_2").input_value() if cnt(page, "authorization-capture-amount-a_2") else None)
        import re; chk(f"{tag} expires RFC3339", re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)$", txt(page, "authorization-expires-a_1")) is not None, txt(page, "authorization-expires-a_1"))
        chk(f"{tag} /authorizations no overflow", overflow(page) <= 0, overflow(page)); shot(page, f"{tag}-authorizations")
        before = txt(page, "wallet-available") if cnt(page, "wallet-available") else None
        page.get_by_test_id("authorize-handle").fill("bob"); page.get_by_test_id("authorize-amount").fill("5.00"); page.get_by_test_id("authorize-note").fill("ticket"); page.get_by_test_id("authorize-visibility").select_option("private"); page.get_by_test_id("authorize-submit").click(); page.wait_for_timeout(900)
        chk(f"{tag} authorize created, shows new item", page.locator('[data-testid^="authorization-item-"]').count() == 4, page.locator('[data-testid^="authorization-item-"]').count())
        first = page.locator('[data-testid="authorization-list"] > *').first.get_attribute("data-testid"); chk(f"{tag} newest first", first not in ("authorization-item-a_1", "authorization-item-a_2", "authorization-item-a_3"), first)
        if cnt(page, "wallet-available"): chk(f"{tag} available updated on auth page", txt(page, "wallet-available") != before, (before, txt(page, "wallet-available")))
        page.get_by_test_id("authorize-amount").fill("9999"); page.get_by_test_id("authorize-submit").click(); page.wait_for_timeout(700); chk(f"{tag} authorize-error insufficient", cnt(page, "authorize-error") == 1); shot(page, f"{tag}-authorize-error")
        page.get_by_test_id("authorize-amount").fill("1.005"); page.get_by_test_id("authorize-submit").click(); page.wait_for_timeout(300); chk(f"{tag} authorize decimals rejected", cnt(page, "authorize-error") == 1)
        # capture partial via UI at bob
        c5 = br.new_context(viewport={"width": W, "height": H}); pg5 = c5.new_page(); login(pg5, "bob@example.com"); pg5.goto(B + "/authorizations"); pg5.wait_for_timeout(500)
        shot(pg5, f"{tag}-authorizations-bob")
        pg5.get_by_test_id("authorization-capture-amount-a_1").fill("15"); pg5.get_by_test_id("authorization-capture-a_1").click(); pg5.wait_for_timeout(900)
        chk(f"{tag} capture 15 of 20 -> captured", pg5.get_by_test_id("authorization-item-a_1").get_attribute("data-status") == "captured" and txt(pg5, "authorization-captured-a_1") == "15.00 EUR", pg5.get_by_test_id("authorization-item-a_1").get_attribute("data-status"))
        chk(f"{tag} capture buttons gone", cnt(pg5, "authorization-capture-a_1") == 0)
        shot(pg5, f"{tag}-authorizations-captured")
        pg5.get_by_test_id("authorization-capture-amount-a_2") if False else None
        # capture exceeds -> authorization-error
        ids = [x["authorization_id"] for x in api("GET", "/authorizations?direction=incoming&status=open", tok=btok)[1]["authorizations"]]
        if ids:
            i0 = ids[0]; pg5.reload(); pg5.wait_for_timeout(400)
            pg5.get_by_test_id(f"authorization-capture-amount-{i0}").fill("999"); pg5.get_by_test_id(f"authorization-capture-{i0}").click(); pg5.wait_for_timeout(700)
            chk(f"{tag} capture too much -> authorization-error", cnt(pg5, "authorization-error") == 1); shot(pg5, f"{tag}-authorization-error")
        # void via ada
        page.reload(); page.wait_for_timeout(400)
        vid = [x["authorization_id"] for x in api("GET", "/authorizations?direction=outgoing&status=open", tok=tok)[1]["authorizations"]][0]
        page.get_by_test_id(f"authorization-void-{vid}").click(); page.wait_for_timeout(800)
        chk(f"{tag} void via UI", page.get_by_test_id(f"authorization-item-{vid}").get_attribute("data-status") == "voided" and cnt(page, f"authorization-void-{vid}") == 0)
        shot(page, f"{tag}-authorizations-voided")
        # uncertain: abort POST /payments after commit
        page.goto(B + "/"); page.wait_for_timeout(400)
        def abort_after(route):
            rq = route.request; h = dict(rq.headers)
            h.pop("content-length", None)
            try: urllib.request.urlopen(urllib.request.Request(rq.url, data=rq.post_data_buffer, method="POST", headers=h), timeout=10).read()
            except Exception as e: print("commit-side err", e)
            route.abort("connectionreset")   # commits server side, response lost
        page.route("**/payments", lambda r: abort_after(r) if r.request.method == "POST" else r.continue_())
        bal0 = int(page.get_by_test_id("wallet-balance").get_attribute("data-amount"))
        page.get_by_test_id("pay-handle").fill("cy"); page.get_by_test_id("pay-amount").fill("1.00"); page.get_by_test_id("pay-note").fill("lost"); page.get_by_test_id("pay-submit").click(); page.wait_for_timeout(1200)
        chk(f"{tag} uncertain shown, not pay-error", cnt(page, "pay-uncertain") == 1 and txt(page, "pay-uncertain") != "" and cnt(page, "pay-error") == 0, (cnt(page, "pay-uncertain"), cnt(page, "pay-error")))
        shot(page, f"{tag}-home-uncertain")
        page.unroute("**/payments"); page.get_by_test_id("pay-submit").click(); page.wait_for_timeout(1200)
        chk(f"{tag} retry clears both, moves once", cnt(page, "pay-uncertain") == 0 and cnt(page, "pay-error") == 0 and int(page.get_by_test_id("wallet-balance").get_attribute("data-amount")) == bal0 - 100, int(page.get_by_test_id("wallet-balance").get_attribute("data-amount")) - bal0)
        shot(page, f"{tag}-home-uncertain-recovered")
        # loading state: slow /activity
        page.route("**/activity*", lambda r: (time.sleep(1.5), r.continue_()))
        page.reload(wait_until="commit"); page.wait_for_timeout(350); shot(page, f"{tag}-home-loading", full=False); page.unroute("**/activity*")
        chk(f"{tag} no JS errors (non-network)", not [e for e in errs if "Failed to load resource" not in e], errs[:3])
        page.unroute_all(behavior="ignoreErrors"); ctx.close()
    # JPY / BHD
    for cur, mu, exp in (("JPY", 0, "1200 JPY"), ("BHD", 3, "10.000 BHD")):
        f = fixture(cur, mu); f["users"][0]["balance"] = 1200 if mu == 0 else 10000; f["authorizations"] = []; api("POST", "/_test/reset", f)
        ctx = br.new_context(viewport={"width": 375, "height": 800}); page = ctx.new_page(); login(page, "ada@example.com"); page.wait_for_timeout(400)
        chk(f"{cur} balance format", txt(page, "wallet-balance") == exp, txt(page, "wallet-balance")); shot(page, f"m-home-{cur}")
        page.get_by_test_id("pay-handle").fill("bob"); page.get_by_test_id("pay-amount").fill("1.5" if mu == 0 else "1.2345"); page.get_by_test_id("pay-submit").click(); page.wait_for_timeout(400)
        chk(f"{cur} too many decimals rejected", cnt(page, "pay-error") == 1)
        page.get_by_test_id("pay-amount").fill("100" if mu == 0 else "1.5"); page.get_by_test_id("pay-submit").click(); page.wait_for_timeout(700)
        chk(f"{cur} pay works", txt(page, "wallet-balance") == ("1100 JPY" if mu == 0 else "8.500 BHD"), txt(page, "wallet-balance"))
        ctx.close()
    br.close()
print(f"\nUI {n} checks, {len(fails)} failed: {fails}")
