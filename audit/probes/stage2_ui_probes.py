"""spec-auditor stage 2 browser probes (Playwright, sync). One probe per UI gap in ledger/stage-2.md.

Usage (kickoff venv): python stage2_ui_probes.py http://127.0.0.1:PORT [STAGE1_URL] [name-filter ...]
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
S1 = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2].startswith("http") else None
FILTER = [a for a in sys.argv[2:] if not a.startswith("http")]
sys.argv = [sys.argv[0], URL]
import stage1_probes as P  # noqa: E402
from stage2_probes import A, iso  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

call, k, ok, err, fx, user, reset, tok = P.call, P.k, P.ok, P.err, P.fx, P.user, P.reset, P.tok
T = lambda name: f"[data-testid='{name}']"
PROBES = []


def probe(name):
    def deco(fn):
        PROBES.append((name, fn))
        return fn
    return deco


def login(page, email="ada@example.com"):
    page.goto(URL + "/login")
    page.fill(T("login-email"), email)
    page.fill(T("login-password"), "correct horse")
    page.click(T("login-submit"))
    page.wait_for_selector(T("current-user"))


def amount_of(page, tid="wallet-balance"):
    return page.get_attribute(T(tid), "data-amount")


def wait_amount(page, tid, value, timeout=5000):
    page.wait_for_selector(f"{T(tid)}[data-amount='{value}']", timeout=timeout)


def posts(page):
    seen = []
    page.on("request", lambda r: seen.append((r.method, r.url, r.headers.get("idempotency-key"), r.post_data))
            if r.method == "POST" else None)
    return seen


def pay_form(page, handle="bob", amount="15.00", note="", vis=None):
    page.fill(T("pay-handle"), handle)
    page.fill(T("pay-amount"), amount)
    page.fill(T("pay-note"), note)
    if vis:
        page.select_option(T("pay-visibility"), vis)


def present(page, tid):
    return page.query_selector(T(tid)) is not None


# ---- 10. lost response -----------------------------------------------------------------------

@probe("S2-40 lost response after commit -> pay-uncertain; retry same key+body moves money once")
def _(page):
    reset(fx())
    login(page)
    page.goto(URL + "/")
    page.wait_for_selector(T("pay-submit"))
    seen = posts(page)
    state = {"drop": True}

    def handler(route):
        if state["drop"]:
            route.fetch()          # the server commits
            state["drop"] = False
            route.abort("connectionreset")  # but the browser never sees the response
        else:
            route.continue_()
    page.route("**/payments", handler)
    pay_form(page, amount="15.00", note="lost")
    page.click(T("pay-submit"))
    page.wait_for_selector(T("pay-uncertain"))
    assert page.text_content(T("pay-uncertain")).strip(), "pay-uncertain must have text"
    assert not present(page, "pay-error"), "unknown outcome shown as a refusal"
    assert tok and call("GET", "/me", token=tok("ada"))[1]["balance"] == 8500, "server should have committed"
    page.click(T("pay-submit"))
    wait_amount(page, "wallet-balance", 8500)
    page.wait_for_timeout(300)
    assert not present(page, "pay-uncertain") and not present(page, "pay-error")
    p = [s for s in seen if s[1].endswith("/payments")]
    assert len(p) == 2 and p[0][2] == p[1][2] and json.loads(p[0][3]) == json.loads(p[1][3]), p
    feed = call("GET", "/activity", token=tok("ada"))[1]["payments"]
    assert len([x for x in feed if x["note"] == "lost"]) == 1


# ---- 11. latest refresh wins ------------------------------------------------------------------

@probe("S2-37 latest refresh wins when an earlier read arrives last")
def _(page):
    reset(fx())
    login(page)
    page.goto(URL + "/")
    wait_amount(page, "wallet-balance", 10000)
    held, phase = [], {"hold": True}

    def handler(route):
        if phase["hold"] and route.request.method == "GET":
            held.append((route, route.fetch()))   # read now (stale), deliver later
        else:
            route.continue_()
    page.route("**/me", handler)
    page.route("**/activity*", handler)
    page.click(T("wallet-refresh"))
    page.wait_for_timeout(500)
    ok(call("POST", "/payments", {"to_handle": "bob", "amount": 300}, token=tok("ada"), key=k()), 201)
    phase["hold"] = False
    page.click(T("wallet-refresh"))
    wait_amount(page, "wallet-balance", 9700)
    for route, resp in held:
        route.fulfill(response=resp)
    page.wait_for_timeout(800)
    assert amount_of(page, "wallet-balance") == "9700", "a delayed earlier read overwrote the later refresh"
    assert amount_of(page, "wallet-available") == "9700"


# ---- 12. refusal refresh ---------------------------------------------------------------------------

@probe("S2-38 refused payment: pay-error, balance refreshed, inputs preserved")
def _(page):
    reset(fx())
    login(page)
    page.goto(URL + "/")
    wait_amount(page, "wallet-balance", 10000)
    ok(call("POST", "/payments", {"to_handle": "cy", "amount": 9000}, token=tok("ada"), key=k()), 201)
    pay_form(page, handle="bob", amount="50.00", note="keep me", vis="private")
    page.click(T("pay-submit"))
    page.wait_for_selector(T("pay-error"))
    wait_amount(page, "wallet-balance", 1000)
    vals = [page.input_value(T(x)) for x in ("pay-handle", "pay-amount", "pay-note")] + \
        [page.eval_on_selector(T("pay-visibility"), "e => e.value")]
    assert vals == ["bob", "50.00", "keep me", "private"], vals


@probe("S2-39 request cancelled elsewhere: request-error and the stale pay button disappears")
def _(page):
    reset(fx())
    rid = ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 100}, token=tok("bob"), key=k()), 201)["request_id"]
    login(page)
    page.goto(URL + "/requests")
    page.wait_for_selector(T(f"request-pay-{rid}"))
    ok(call("POST", f"/requests/{rid}/cancel", token=tok("bob")), 200)
    page.click(T(f"request-pay-{rid}"))
    page.wait_for_selector(T("request-error"))
    page.wait_for_selector(f"{T('request-item-' + rid)}[data-status='cancelled']")
    assert not present(page, f"request-pay-{rid}")
    assert call("GET", "/me", token=tok("ada"))[1]["balance"] == 10000


# ---- 15. decimal input on every form ------------------------------------------------------------------

@probe("S2-17/34/84 bad decimal input shows the form error and sends nothing")
def _(page):
    reset(fx())
    login(page)
    forms = [("/", "pay", "pay-error"), ("/", "request", "request-error"), ("/", "authorize", "authorize-error"),
             ("/split", "split", "split-error")]
    for route, prefix, etid in forms:
        for bad in ("abc", "-5", "1e3", "15,00", "", "10.005", " ", "1.2.3", "0", "0.00"):
            page.goto(URL + route)
            page.wait_for_selector(T(prefix + "-submit"))
            seen = posts(page)
            if prefix == "split":
                page.fill(T("split-handles"), "ada,bob")
            else:
                page.fill(T(prefix + "-handle"), "bob" if prefix != "request" else "bob")
            page.fill(T(prefix + "-amount"), bad)
            page.click(T(prefix + "-submit"))
            page.wait_for_selector(T(etid), timeout=3000)
            page.wait_for_timeout(150)
            assert not [s for s in seen if "/_test" not in s[1]], (prefix, bad, seen)
    reset(fx(currency="JPY", minor_units=0))
    login(page)
    page.goto(URL + "/")
    page.wait_for_selector(T("pay-submit"))
    seen = posts(page)
    pay_form(page, amount="15.5")
    page.click(T("pay-submit"))
    page.wait_for_selector(T("pay-error"))
    assert not seen, "JPY 15.5 must be refused in the form"
    reset(fx(currency="BHD", minor_units=3))
    login(page)
    page.goto(URL + "/")
    wait_amount(page, "wallet-balance", 10000)
    pay_form(page, amount="1.234")
    page.click(T("pay-submit"))
    wait_amount(page, "wallet-balance", 10000 - 1234)
    pay_form(page, amount="2")
    page.click(T("pay-submit"))
    wait_amount(page, "wallet-balance", 10000 - 1234 - 2000)


# ---- 16. authorization UI ------------------------------------------------------------------------------

@probe("S2-83/85-88 authorization screens and wallet numbers")
def _(page):
    reset(fx(authorizations=[A("a_open", 2000), A("a_in", 300, frm="u_bob", to="u_ada"),
                             A("a_cap", 500, status="captured"), A("a_exp", 100, status="expired", exp=-7200)]))
    login(page)
    page.goto(URL + "/")
    wait_amount(page, "wallet-available", 8000)
    assert page.text_content(T("wallet-available")).strip() == "80.00 EUR"
    assert amount_of(page, "wallet-balance") == "10000" and page.text_content(T("wallet-balance")).strip() == "100.00 EUR"
    assert amount_of(page, "wallet-held") == "2000" and page.text_content(T("wallet-held")).strip() == "20.00 EUR"
    fs = lambda t: float(page.eval_on_selector(T(t), "e => getComputedStyle(e).fontSize").rstrip("px"))
    assert fs("wallet-available") > fs("wallet-balance") and fs("wallet-available") > fs("wallet-held"), \
        "available must be the headline number"
    page.goto(URL + "/authorizations")
    page.wait_for_selector(T("authorization-list"))
    kids = page.eval_on_selector_all(f"{T('authorization-list')} > *", "els => els.map(e => e.getAttribute('data-testid'))")
    items = [x for x in kids if x and x.startswith("authorization-item-")]
    assert set(items) == {f"authorization-item-{i}" for i in ("a_open", "a_in", "a_cap", "a_exp")}, items
    st = {i: page.get_attribute(T(f"authorization-item-{i}"), "data-status") for i in ("a_open", "a_in", "a_cap", "a_exp")}
    assert st == {"a_open": "open", "a_in": "open", "a_cap": "captured", "a_exp": "expired"}, st
    assert page.text_content(T("authorization-amount-a_open")).strip() == "20.00 EUR"
    assert present(page, "authorization-captured-a_cap") and not present(page, "authorization-captured-a_open") \
        and not present(page, "authorization-captured-a_exp")
    exp = call("GET", "/authorizations", token=tok("ada"))[1]["authorizations"]
    for a in exp:
        assert page.text_content(T(f"authorization-expires-{a['authorization_id']}")).strip() == a["expires_at"]
    assert present(page, "authorization-void-a_open") and not present(page, "authorization-capture-a_open")
    assert present(page, "authorization-capture-a_in") and not present(page, "authorization-void-a_in")
    assert page.input_value(T("authorization-capture-amount-a_in")) == "3.00"
    for i in ("a_cap", "a_exp"):
        assert not present(page, f"authorization-capture-{i}") and not present(page, f"authorization-void-{i}")
    # stale capture: bob voids elsewhere, then the UI capture is refused
    ok(call("POST", "/authorizations/a_in/void", token=tok("bob")), 200)
    page.click(T("authorization-capture-a_in"))
    page.wait_for_selector(T("authorization-error"))
    # partial capture through the UI keeps nothing extra held
    a = ok(call("POST", "/authorizations", {"to_handle": "ada", "amount": 1000}, token=tok("bob"), key=k()), 201)
    page.goto(URL + "/authorizations")
    page.wait_for_selector(T(f"authorization-capture-{a['authorization_id']}"))
    page.fill(T(f"authorization-capture-amount-{a['authorization_id']}"), "4.00")
    page.click(T(f"authorization-capture-{a['authorization_id']}"))
    page.wait_for_selector(f"{T('authorization-item-' + a['authorization_id'])}[data-status='captured']")
    assert page.text_content(T(f"authorization-captured-{a['authorization_id']}")).strip() == "4.00 EUR"
    m = call("GET", "/me", token=tok("bob"))[1]
    assert m["held"] == 0 and m["total"] == 2500 - 400, m
    # void through the UI
    page.click(T("authorization-void-a_open"))
    page.wait_for_selector(f"{T('authorization-item-a_open')}[data-status='voided']")
    page.goto(URL + "/")
    wait_amount(page, "wallet-available", 10400)
    assert not present(page, "wallet-held"), "wallet-held must be absent when held is zero"
    # authorise form and insufficient available
    page.fill(T("authorize-handle"), "bob")
    page.fill(T("authorize-amount"), "1000.00")
    page.click(T("authorize-submit"))
    page.wait_for_selector(T("authorize-error"))
    page.fill(T("authorize-amount"), "30.00")
    page.click(T("authorize-submit"))
    wait_amount(page, "wallet-held", 3000)
    wait_amount(page, "wallet-available", 7400)
    reset(fx())
    login(page, "cy@example.com")
    page.goto(URL + "/authorizations")
    page.wait_for_selector(T("empty-authorizations"))


# ---- 17. formatting ------------------------------------------------------------------------------------

@probe("S2-15 amount formatting: leading zero, 3 places, 0 places, large values")
def _(page):
    for cur, mu, bal, want in (("EUR", 2, 5, "0.05 EUR"), ("BHD", 3, 5, "0.005 BHD"), ("JPY", 0, 1200, "1200 JPY"),
                               ("EUR", 2, 9007199254740991, "90071992547409.91 EUR"), ("EUR", 2, 0, "0.00 EUR")):
        reset(fx(currency=cur, minor_units=mu, users=[user("ada", bal), user("bob", 0)]))
        login(page)
        page.goto(URL + "/")
        wait_amount(page, "wallet-balance", bal)
        got = page.text_content(T("wallet-balance")).strip()
        assert got == want, (cur, bal, got)
        assert page.text_content(T("wallet-available")).strip() == want


# ---- 18. request UI --------------------------------------------------------------------------------------

@probe("S2-28/29/31/21 request buttons, errors, double click pays once, request form errors")
def _(page):
    reset(fx())
    bob = tok("bob")
    rids = [ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 100 + i}, token=bob, key=k()), 201)["request_id"] for i in range(3)]
    out = ok(call("POST", "/requests", {"payer_handle": "bob", "amount": 5}, token=tok("ada"), key=k()), 201)["request_id"]
    ok(call("POST", f"/requests/{rids[1]}/cancel", token=bob), 200)
    login(page)
    page.goto(URL + "/requests")
    page.wait_for_selector(T(f"request-item-{rids[0]}"))
    assert not present(page, f"request-decline-{rids[1]}") and not present(page, f"request-pay-{rids[1]}")
    assert present(page, f"request-cancel-{out}") and not present(page, f"request-decline-{out}")
    page.dblclick(T(f"request-pay-{rids[0]}"))
    page.wait_for_selector(f"{T('request-item-' + rids[0])}[data-status='paid']")
    page.wait_for_timeout(500)
    assert call("GET", "/me", token=tok("ada"))[1]["balance"] == 10000 - 100, "double click paid twice"
    assert not present(page, f"request-cancel-{rids[0]}") and not present(page, f"request-decline-{rids[0]}")
    ok(call("POST", f"/requests/{rids[2]}/cancel", token=bob), 200)
    page.click(T(f"request-decline-{rids[2]}"))
    page.wait_for_selector(T("request-error"))
    page.goto(URL + "/")
    page.wait_for_selector(T("request-submit"))
    for handle, amt in (("ada", "1.00"), ("nobody", "1.00")):
        page.fill(T("request-handle"), handle)
        page.fill(T("request-amount"), amt)
        page.click(T("request-submit"))
        page.wait_for_selector(T("request-error"))


# ---- 19. auth UI ---------------------------------------------------------------------------------------------

@probe("S2-10/11/14 current-user on every route, auth-error only on errors, signup errors")
def _(page):
    reset(fx())
    page.goto(URL + "/login")
    page.wait_for_selector(T("login-submit"))
    assert not present(page, "auth-error")
    login(page)
    for route in ("/", "/requests", "/split", "/authorizations"):
        page.goto(URL + route)
        page.wait_for_selector(T("current-user"))
        assert "Ada" in page.text_content(T("current-user")) and page.text_content(T("current-handle")).strip() == "ada"
        assert not present(page, "auth-error")
    page.click(T("logout-button"))
    page.wait_for_selector(T("current-user"), state="detached")
    for email, pw in (("ada@example.com", "correct horse"), ("ada@other.example", "correct horse"),
                      ("new@example.com", "short"), ("not-an-email", "correct horse")):
        page.goto(URL + "/signup")
        page.fill(T("signup-email"), email)
        page.fill(T("signup-password"), pw)
        page.fill(T("signup-display-name"), "X")
        page.click(T("signup-submit"))
        page.wait_for_selector(T("auth-error"), timeout=4000)


# ---- 20. product quality ---------------------------------------------------------------------------------------

@probe("S2-3/4 no horizontal scroll at 375 px and 1280 px; labels; visible focus")
def _(page):
    long_h = "h" * 20
    reset(fx(users=[user("ada", 10 ** 12), user("bob", 0), user(long_h, 0)],
             authorizations=[A("a_1", 2000, note="n" * 200)]))
    ada = tok("ada")
    ok(call("POST", "/payments", {"to_handle": long_h, "amount": 999999999, "note": "W" * 200}, token=ada, key=k()), 201)
    ok(call("POST", "/requests", {"payer_handle": long_h, "amount": 999999999, "note": "x" * 200}, token=ada, key=k()), 201)
    login(page)
    bad = []
    for w in (375, 1280):
        page.set_viewport_size({"width": w, "height": 900})
        for route in ("/", "/requests", "/split", "/authorizations", "/login", "/signup"):
            page.goto(URL + route)
            page.wait_for_timeout(600)
            sw = page.evaluate("() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]")
            if sw[0] > sw[1]:
                bad.append((w, route, sw))
            unl = page.evaluate("""() => [...document.querySelectorAll('input,select,textarea')]
                .filter(e => e.type !== 'hidden' && !(e.labels && e.labels.length) && !e.getAttribute('aria-label'))
                .map(e => e.getAttribute('data-testid') || e.name || e.id)""")
            if unl:
                bad.append((w, route, "unlabelled", unl))
            if route == "/":
                page.focus(T("pay-amount"))
                ring = page.eval_on_selector(T("pay-amount"), """e => { const s = getComputedStyle(e);
                    return (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== 'none'; }""")
                if not ring:
                    bad.append((w, route, "no visible focus on pay-amount"))
    assert not bad, bad


# ---- 13. upgrade in the browser ---------------------------------------------------------------------------------

@probe("S2-43/44/45 browser stays signed in across import; lost payment before export replays after import")
def _(page):
    reset(fx())
    login(page)
    page.goto(URL + "/")
    page.wait_for_selector(T("pay-submit"))
    rid = ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 70}, token=tok("bob"), key=k()), 201)["request_id"]
    state = {"drop": True}

    def handler(route):
        if state["drop"]:
            route.fetch()
            state["drop"] = False
            route.abort("connectionreset")
        else:
            route.continue_()
    page.route("**/payments", handler)
    seen = posts(page)
    pay_form(page, amount="12.00", note="upgrade")
    page.click(T("pay-submit"))
    page.wait_for_selector(T("pay-uncertain"))
    ex = call("GET", "/_test/export")[1]
    reset(fx())                       # destination wiped, then upgraded state imported
    s, b, _ = call("POST", "/_test/import", ex)
    assert s == 204, (s, b)
    page.click(T("pay-submit"))       # same key and body, no reload
    wait_amount(page, "wallet-balance", 10000 - 1200)
    page.wait_for_timeout(300)
    assert not present(page, "pay-uncertain") and not present(page, "pay-error")
    p = [x for x in seen if x[1].endswith("/payments")]
    assert len(p) == 2 and p[0][2] == p[1][2], p
    assert page.query_selector(T("current-user")) is not None, "browser signed out by the upgrade"
    page.goto(URL + "/requests")
    page.click(T(f"request-pay-{rid}"))
    page.wait_for_selector(f"{T('request-item-' + rid)}[data-status='paid']")
    if S1:  # a token minted by the stage-1 service keeps the browser signed in after the upgrade import
        from urllib.parse import urlsplit
        base = P.BASE
        P.BASE = urlsplit(S1)
        try:
            P.reset(fx())
            t1 = tok("ada")
            ok(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=t1, key=k()), 201)
            ex1 = call("GET", "/_test/export")[1]
        finally:
            P.BASE = base
        reset(fx())
        page.goto(URL + "/login")   # a public page: no 401 redirect can clear the injected token
        page.wait_for_selector(T("login-submit"))
        page.evaluate("t => localStorage.setItem('pf_token', t)", t1)
        assert call("POST", "/_test/import", ex1)[0] == 204
        page.goto(URL + "/")
        wait_amount(page, "wallet-balance", 9999)
        page.wait_for_selector(T("current-user"))


def main():
    fails = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name, fn in PROBES:
            if FILTER and not any(f in name for f in FILTER):
                continue
            ctx = browser.new_context(base_url=URL, viewport={"width": 1280, "height": 900})
            page = ctx.new_page()
            page.set_default_timeout(6000)
            try:
                fn(page)
                print("PASS", name, flush=True)
            except Exception as e:  # noqa: BLE001
                fails += 1
                print("FAIL", name, "--", repr(e)[:700], flush=True)
            finally:
                ctx.close()
        browser.close()
    print(f"{len(PROBES)} ui probes, {fails} failed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
