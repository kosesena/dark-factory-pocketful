#!/usr/bin/env python3
"""Reviewer's stage-2 browser checks (Playwright/Chromium), written from the specification.

Usage (kickoff venv): python ui_check_s2.py http://localhost:8080 [screenshot-dir]
Prints PASS/FAIL per check; exit 1 on any failure.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip("/")
SHOTS = sys.argv[2] if len(sys.argv) > 2 else None
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name, "" if cond else "  -> %s" % (detail,)), flush=True)


def api(method, path, body=None, token=None, key=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    if key:
        h["Idempotency-Key"] = key
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            t = r.read()
            return r.status, json.loads(t) if t else None
    except urllib.error.HTTPError as e:
        t = e.read()
        return e.code, json.loads(t) if t else None


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def fixture(currency="EUR", mu=2, ada=10000, holds=True):
    now = datetime.now(timezone.utc)
    return {
        "currency": currency, "minor_units": mu,
        "users": [
            {"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada Lovelace",
             "handle": "ada", "balance": ada},
            {"id": "u_bob", "email": "bob@example.com", "password": "correct horse", "display_name": "Bob",
             "handle": "bob", "balance": 2500},
            {"id": "u_cy", "email": "cy@example.com", "password": "correct horse", "display_name": "Cy",
             "handle": "cy", "balance": 0},
        ],
        "payments": [{"id": "p_seed", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 500, "note": "",
                      "visibility": "public", "created_at": iso(now - timedelta(hours=1))}],
        "requests": [{"id": "rq_seed", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200,
                      "note": "taxi", "status": "pending"}],
        "authorizations": ([{"id": "a_seed", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000,
                             "note": "deposit", "visibility": "public", "status": "open",
                             "expires_at": iso(now + timedelta(hours=2))}] if holds else []),
    }


def reset(fx):
    st, _ = api("POST", "/_test/reset", fx)
    assert st == 204
    return {u["handle"]: api("POST", "/auth/login", {"email": u["email"], "password": u["password"]})[1]["token"]
            for u in fx["users"]}


def tid(page, t):
    return page.locator('[data-testid="%s"]' % t)


def text(page, t):
    return tid(page, t).first.inner_text().strip()


def wait_text(page, t, want, timeout=5000):
    try:
        page.wait_for_function(
            "([t, w]) => { const e = document.querySelector('[data-testid=\"' + t + '\"]'); return e && e.textContent.trim() === w; }",
            arg=[t, want], timeout=timeout)
        return True
    except Exception:
        return False


def login(page, email="ada@example.com", pw="correct horse"):
    page.goto(BASE + "/login")
    tid(page, "login-email").fill(email)
    tid(page, "login-password").fill(pw)
    tid(page, "login-submit").click()
    page.wait_for_url(BASE + "/")
    tid(page, "wallet-available").wait_for()


def as_user(page, token):
    # the app may itself redirect to /login after a reset invalidates its token; tolerate that race
    for _ in range(5):
        try:
            page.goto(BASE + "/login", wait_until="load")
            page.wait_for_timeout(300)
            page.evaluate("t => localStorage.setItem('pf_token', t)", token)
            return
        except Exception:
            page.wait_for_timeout(300)
    raise RuntimeError("could not sign in the page")


def no_hscroll(page):
    return page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=True)


def main():
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        ctx = br.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        posts = []
        page.on("request", lambda r: posts.append((r.method, r.url, r.post_data, r.headers.get("idempotency-key")))
                if r.method == "POST" else None)

        # --- auth pages
        T = reset(fixture())
        page.goto(BASE + "/login")
        tid(page, "login-email").fill("ada@example.com")
        tid(page, "login-password").fill("wrong password")
        tid(page, "login-submit").click()
        tid(page, "auth-error").wait_for()
        check("auth-error on wrong password", tid(page, "auth-error").count() == 1)
        page.goto(BASE + "/login")
        check("auth-error absent initially", tid(page, "auth-error").count() == 0)
        page.goto(BASE + "/signup")
        tid(page, "signup-email").fill("New.Person@example.com")
        tid(page, "signup-password").fill("short")
        tid(page, "signup-display-name").fill("Newbie")
        tid(page, "signup-submit").click()
        tid(page, "auth-error").wait_for()
        check("signup short password -> auth-error", True)
        tid(page, "signup-password").fill("long enough pw")
        tid(page, "signup-submit").click()
        page.wait_for_url(BASE + "/")
        tid(page, "current-handle").wait_for()
        check("signup lands signed in", text(page, "current-handle") == "new_person" and "Newbie" in text(page, "current-user"),
              text(page, "current-handle"))
        tid(page, "logout-button").click()
        page.wait_for_url(re.compile(".*/login"))
        check("logout", "/login" in page.url)

        # --- wallet numbers with seeded hold
        login(page)
        check("wallet-balance formatted total", text(page, "wallet-balance") == "100.00 EUR" and
              tid(page, "wallet-balance").get_attribute("data-amount") == "10000", text(page, "wallet-balance"))
        check("wallet-available formatted", text(page, "wallet-available") == "80.00 EUR" and
              tid(page, "wallet-available").get_attribute("data-amount") == "8000", text(page, "wallet-available"))
        check("wallet-held formatted", text(page, "wallet-held") == "20.00 EUR" and
              tid(page, "wallet-held").get_attribute("data-amount") == "2000", "")
        fs = page.evaluate("""() => ['wallet-available','wallet-balance','wallet-held'].map(t =>
            parseFloat(getComputedStyle(document.querySelector('[data-testid="'+t+'"]')).fontSize))""")
        check("available is the headline number", fs[0] > fs[1] and fs[0] > fs[2], fs)
        biggest = page.evaluate("""() => { let m = 0; for (const e of document.querySelectorAll('body *')) {
            if (e.children.length === 0 && /\\d/.test(e.textContent)) m = Math.max(m, parseFloat(getComputedStyle(e).fontSize)); }
            return m; }""")
        check("available is the largest number on the page", fs[0] >= biggest, (fs[0], biggest))
        for route in ("/", "/requests", "/split", "/authorizations"):
            page.goto(BASE + route)
            tid(page, "current-user").wait_for()
            check("current-user/handle on %s" % route, "Ada Lovelace" in text(page, "current-user") and
                  text(page, "current-handle") == "ada")
        page.goto(BASE + "/")
        tid(page, "activity-list").wait_for()

        # --- pay form: decimals, rejection without request, keep values, unchanged resubmit
        def pay_posts():
            return [p for p in posts if p[1].endswith("/payments")]
        for bad in ("15.005", "abc", "1,5", "-3", ""):
            n = len(pay_posts())
            tid(page, "pay-handle").fill("bob")
            tid(page, "pay-amount").fill(bad)
            tid(page, "pay-submit").click()
            tid(page, "pay-error").wait_for(timeout=3000)
            page.wait_for_timeout(200)
            check("pay %r rejected without request" % bad, len(pay_posts()) == n and tid(page, "pay-error").count() == 1)
        tid(page, "pay-amount").fill("15.5")
        tid(page, "pay-note").fill("lunch 🍜")
        tid(page, "pay-visibility").select_option("private")
        tid(page, "pay-submit").click()
        ok = wait_text(page, "wallet-available", "64.50 EUR")
        sent = json.loads(pay_posts()[-1][2])
        check("15.5 submits 1550 and balance falls", ok and sent["amount"] == 1550 and sent["visibility"] == "private",
              (text(page, "wallet-available"), sent))
        check("pay-error absent after success", tid(page, "pay-error").count() == 0)
        check("pay form keeps values", tid(page, "pay-handle").input_value() == "bob" and
              tid(page, "pay-amount").input_value() == "15.5" and tid(page, "pay-note").input_value() == "lunch 🍜")
        key1 = pay_posts()[-1][3]
        tid(page, "pay-submit").click()
        page.wait_for_timeout(800)
        st, me = api("GET", "/me", token=T["ada"])
        st, act = api("GET", "/activity?limit=200", token=T["ada"])
        mine = [p for p in act["payments"] if p["from_handle"] == "ada" and p["amount"] == 1550]
        check("unchanged resubmit: same key, one payment, no error", pay_posts()[-1][3] == key1 and len(mine) == 1 and
              me["total"] == 10000 - 1550 and tid(page, "pay-error").count() == 0, (len(mine), me["total"]))
        tid(page, "pay-amount").fill("15")
        tid(page, "pay-submit").click()
        ok = wait_text(page, "wallet-available", "49.50 EUR")
        check("changed field -> new payment, 15 submits 1500", ok and pay_posts()[-1][3] != key1 and
              json.loads(pay_posts()[-1][2])["amount"] == 1500, text(page, "wallet-available"))

        # --- feed
        items = page.locator('[data-testid="activity-list"] > *')
        ids = [items.nth(i).get_attribute("data-testid") for i in range(items.count())]
        st, act = api("GET", "/activity?limit=200", token=T["ada"])
        check("feed newest first and complete", ids == ["activity-item-" + p["payment_id"] for p in act["payments"]], ids)
        p0 = act["payments"][-1]  # the seeded payment with an empty note between others
        check("feed note present when empty", tid(page, "activity-note-" + p0["payment_id"]).count() == 1 and
              text(page, "activity-note-" + p0["payment_id"]) == "")
        check("feed parties contain both handles", all(h in text(page, "activity-parties-" + p0["payment_id"]) for h in ("bob", "cy")))
        check("feed amount formatted", text(page, "activity-amount-" + p0["payment_id"]) == "5.00 EUR")
        priv = [p for p in act["payments"] if p["visibility"] == "private"][0]
        check("feed visibility attribute", tid(page, "activity-item-" + priv["payment_id"]).get_attribute("data-visibility") == "private")
        check("feed note verbatim", text(page, "activity-note-" + priv["payment_id"]) == "lunch 🍜")

        # --- refused payment: competing client spends first
        api("POST", "/payments", {"to_handle": "cy", "amount": 4900}, token=T["ada"], key="elsewhere")
        tid(page, "pay-amount").fill("1")
        tid(page, "pay-submit").click()
        tid(page, "pay-error").wait_for(timeout=4000)
        ok = wait_text(page, "wallet-available", "0.50 EUR")
        check("refused: pay-error, balance refreshed, inputs kept", ok and tid(page, "pay-amount").input_value() == "1"
              and tid(page, "pay-handle").input_value() == "bob", text(page, "wallet-available"))
        check("held funds refused, no uncertain", tid(page, "pay-uncertain").count() == 0)

        # --- lost response after commit, retry same key+body, money once
        T = reset(fixture(holds=False))
        page.goto(BASE + "/")
        as_user(page, T["ada"])
        page.goto(BASE + "/")
        tid(page, "wallet-available").wait_for()
        state = {"drop": True}

        def lose(route):
            if state["drop"] and route.request.method == "POST":
                route.fetch()           # the server commits
                state["drop"] = False
                route.abort("failed")   # but the browser never sees the response
            else:
                route.continue_()
        page.route("**/payments", lose)
        tid(page, "pay-handle").fill("bob")
        tid(page, "pay-amount").fill("10")
        tid(page, "pay-submit").click()
        tid(page, "pay-uncertain").wait_for(timeout=5000)
        check("lost response -> pay-uncertain, not pay-error", tid(page, "pay-uncertain").count() == 1 and
              len(text(page, "pay-uncertain")) > 0 and tid(page, "pay-error").count() == 0)
        k_lost = pay_posts()[-1][3]
        b_lost = pay_posts()[-1][2]
        n_before = len(pay_posts())
        tid(page, "pay-submit").click()
        page.wait_for_function("n => true", arg=0)
        tid(page, "pay-uncertain").wait_for(state="detached", timeout=6000)
        ok = wait_text(page, "wallet-available", "90.00 EUR") and len(pay_posts()) == n_before + 1
        st, act = api("GET", "/activity?limit=200", token=T["ada"])
        check("retry: same key and body, money once, alerts cleared", ok and pay_posts()[-1][3] == k_lost and
              pay_posts()[-1][2] == b_lost and len([p for p in act["payments"] if p["from_handle"] == "ada"]) == 1 and
              tid(page, "pay-uncertain").count() == 0 and tid(page, "pay-error").count() == 0,
              dict(ok=ok, key=pay_posts()[-1][3] == k_lost, body=pay_posts()[-1][2] == b_lost,
                   n=len([p for p in act["payments"] if p["from_handle"] == "ada"]),
                   unc=tid(page, "pay-uncertain").count(), err=tid(page, "pay-error").count(),
                   msgs=page.locator(".alert").all_inner_texts()))
        page.unroute("**/payments")

        # --- latest refresh wins with out-of-order responses
        armed = {"n": 0}

        def slow_first(route):
            if route.request.method == "GET" and armed["n"] == 0:
                armed["n"] = 1
                resp = route.fetch()  # old state
                time.sleep(2.0)
                route.fulfill(response=resp)
            else:
                route.continue_()
        page.route("**/me", slow_first)
        tid(page, "wallet-refresh").click()
        page.wait_for_timeout(150)
        api("POST", "/payments", {"to_handle": "ada", "amount": 1000}, token=T["bob"], key="incoming")
        tid(page, "pay-amount").fill("7.77")
        tid(page, "wallet-refresh").click()
        page.wait_for_timeout(3000)
        check("latest refresh wins", text(page, "wallet-available") == "100.00 EUR", text(page, "wallet-available"))
        check("refresh keeps pay form", tid(page, "pay-amount").input_value() == "7.77")
        page.unroute("**/me")

        # --- upgrade: lost response before export, import, retry recovers original
        state["drop"] = True
        page.route("**/payments", lose)
        tid(page, "pay-amount").fill("3")
        tid(page, "pay-submit").click()
        tid(page, "pay-uncertain").wait_for(timeout=5000)
        page.unroute("**/payments")
        st, ex = api("GET", "/_test/export")
        api("POST", "/_test/reset", fixture(holds=False, ada=1))
        st, _ = api("POST", "/_test/import", ex)
        tid(page, "pay-submit").click()
        tid(page, "pay-uncertain").wait_for(state="detached", timeout=6000)
        ok = wait_text(page, "wallet-available", "97.00 EUR")
        st, act = api("GET", "/activity?limit=200", token=T["ada"])
        check("upgrade: signed-in browser retries lost payment after import, once", st == 200 and ok and
              len([p for p in act["payments"] if p["from_handle"] == "ada" and p["amount"] == 300]) == 1 and
              tid(page, "pay-uncertain").count() == 0, dict(bal=text(page, "wallet-available"),
              n=len([p for p in act["payments"] if p["from_handle"] == "ada" and p["amount"] == 300]),
              unc=tid(page, "pay-uncertain").count(), msgs=page.locator(".alert").all_inner_texts()))

        # --- requests page
        T = reset(fixture())
        as_user(page, T["ada"])
        api("POST", "/requests", {"payer_handle": "bob", "amount": 300, "note": "pizza"}, token=T["ada"], key="o1")
        st, cancel_me = api("POST", "/requests", {"payer_handle": "ada", "amount": 50}, token=T["cy"], key="o2")
        page.goto(BASE + "/requests", wait_until="domcontentloaded")
        tid(page, "incoming-list").wait_for()
        check("incoming has pay+decline", tid(page, "request-pay-rq_seed").count() == 1 and
              tid(page, "request-decline-rq_seed").count() == 1 and tid(page, "request-cancel-rq_seed").count() == 0)
        check("request amount formatted", text(page, "request-amount-rq_seed") == "12.00 EUR")
        st, rl = api("GET", "/requests?direction=outgoing", token=T["ada"])
        out_id = rl["requests"][0]["request_id"]
        check("outgoing has cancel only", tid(page, "request-cancel-" + out_id).count() == 1 and
              tid(page, "request-pay-" + out_id).count() == 0)
        check("status attribute", tid(page, "request-item-rq_seed").get_attribute("data-status") == "pending")
        api("POST", "/requests/%s/cancel" % cancel_me["request_id"], {}, token=T["cy"])
        tid(page, "request-pay-" + cancel_me["request_id"]).click()
        tid(page, "request-error").wait_for(timeout=4000)
        page.wait_for_timeout(500)
        check("cancelled elsewhere: request-error and stale pay button gone",
              tid(page, "request-pay-" + cancel_me["request_id"]).count() == 0 and
              tid(page, "request-item-" + cancel_me["request_id"]).get_attribute("data-status") == "cancelled")
        tid(page, "request-pay-rq_seed").click()
        page.wait_for_function("() => document.querySelector('[data-testid=\"request-item-rq_seed\"]').dataset.status === 'paid'", timeout=4000)
        check("pay via UI -> paid, balance refreshed", tid(page, "request-pay-rq_seed").count() == 0 and
              text(page, "wallet-available") == "68.00 EUR", text(page, "wallet-available"))
        tid(page, "request-cancel-" + out_id).click()
        page.wait_for_function("id => document.querySelector('[data-testid=\"request-item-' + id + '\"]').dataset.status === 'cancelled'",
                               arg=out_id, timeout=4000)
        check("cancel via UI", True)
        shot(page, "requests-1280")

        # --- split preview
        page.goto(BASE + "/split")
        tid(page, "split-amount").fill("10")
        tid(page, "split-handles").fill("bob, ada, cy")
        page.wait_for_timeout(200)
        check("split preview before posting", [text(page, "split-share-" + h) for h in ("bob", "ada", "cy")] ==
              ["3.34 EUR", "3.33 EUR", "3.33 EUR"] and not [p for p in posts if p[1].endswith("/splits")])
        tid(page, "split-amount").fill("0.01")
        page.wait_for_timeout(100)
        check("split preview zero shares", [text(page, "split-share-" + h) for h in ("bob", "ada", "cy")] ==
              ["0.01 EUR", "0.00 EUR", "0.00 EUR"])
        tid(page, "split-amount").fill("10")
        tid(page, "split-submit").click()
        page.wait_for_timeout(800)
        sp = [p for p in posts if p[1].endswith("/splits")][-1]
        st, rl = api("GET", "/requests?direction=outgoing&status=pending", token=T["ada"])
        got = sorted((r["payer_handle"], r["amount"]) for r in rl["requests"])
        check("submitted split matches preview", json.loads(sp[2])["amount"] == 1000 and got == [("bob", 334), ("cy", 333)], got)
        tid(page, "split-handles").fill("bob, nobody_here")
        tid(page, "split-submit").click()
        tid(page, "split-error").wait_for(timeout=3000)
        check("split error shown", True)
        tid(page, "split-amount").fill("1.234")
        page.wait_for_timeout(100)
        n = len([p for p in posts if p[1].endswith("/splits")])
        tid(page, "split-submit").click()
        page.wait_for_timeout(300)
        check("split 1.234 rejected without request", len([p for p in posts if p[1].endswith("/splits")]) == n
              and tid(page, "split-error").count() == 1)

        # --- authorizations
        T = reset(fixture())
        as_user(page, T["ada"])
        page.goto(BASE + "/authorizations")
        tid(page, "authorization-list").wait_for()
        check("seeded hold listed open with void", tid(page, "authorization-item-a_seed").get_attribute("data-status") == "open"
              and tid(page, "authorization-void-a_seed").count() == 1 and tid(page, "authorization-capture-a_seed").count() == 0)
        check("authorization amount + expires rfc3339", text(page, "authorization-amount-a_seed") == "20.00 EUR" and
              re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d([+-]\d\d:\d\d|Z)$", text(page, "authorization-expires-a_seed")),
              text(page, "authorization-expires-a_seed"))
        check("captured element absent when open", tid(page, "authorization-captured-a_seed").count() == 0)
        tid(page, "authorize-handle").fill("cy")
        tid(page, "authorize-amount").fill("90")
        tid(page, "authorize-submit").click()
        tid(page, "authorize-error").wait_for(timeout=4000)
        check("authorize over available -> authorize-error", True)
        tid(page, "authorize-handle").fill("cy")
        tid(page, "authorize-amount").fill("12.5")
        tid(page, "authorize-submit").click()
        ok = wait_text(page, "wallet-available", "67.50 EUR")
        check("authorize via UI: available falls, held shown", ok and text(page, "wallet-held") == "32.50 EUR",
              text(page, "wallet-available"))
        st, al = api("GET", "/authorizations?direction=outgoing&status=open", token=T["ada"])
        new_id = [x for x in al["authorizations"] if x["to_handle"] == "cy"][0]["authorization_id"]
        items = page.locator('[data-testid="authorization-list"] > *')
        check("authorization list newest first", items.nth(0).get_attribute("data-testid") == "authorization-item-" + new_id)
        # receiver captures part
        as_user(page, T["cy"])
        page.goto(BASE + "/authorizations")
        tid(page, "authorization-capture-amount-" + new_id).wait_for()
        check("capture amount prefilled with remaining", tid(page, "authorization-capture-amount-" + new_id).input_value() in ("12.50",),
              tid(page, "authorization-capture-amount-" + new_id).input_value())
        check("receiver has no void", tid(page, "authorization-void-" + new_id).count() == 0)
        tid(page, "authorization-capture-amount-" + new_id).fill("13")
        tid(page, "authorization-capture-" + new_id).click()
        tid(page, "authorization-error").wait_for(timeout=4000)
        check("capture over remaining -> authorization-error", True)
        tid(page, "authorization-capture-amount-" + new_id).fill("10")
        tid(page, "authorization-capture-" + new_id).click()
        page.wait_for_function("id => { const e = document.querySelector('[data-testid=\"authorization-item-' + id + '\"]'); return e && e.dataset.status === 'captured'; }",
                               arg=new_id, timeout=4000)
        check("capture via UI -> captured with captured amount", text(page, "authorization-captured-" + new_id) == "10.00 EUR"
              and text(page, "wallet-available") == "10.00 EUR", text(page, "wallet-available"))
        st, me = api("GET", "/me", token=T["ada"])
        check("final capture released remainder", me["held"] == 2000 and me["total"] == 9000, me)
        # void by payer
        as_user(page, T["ada"])
        page.goto(BASE + "/authorizations")
        tid(page, "authorization-void-a_seed").wait_for()
        api("POST", "/authorizations/a_seed/capture", {}, token=T["bob"], key="race-cap")
        tid(page, "authorization-void-a_seed").click()
        tid(page, "authorization-error").wait_for(timeout=4000)
        page.wait_for_timeout(300)
        check("void refused after capture elsewhere: error + refreshed", tid(page, "authorization-void-a_seed").count() == 0
              and tid(page, "authorization-item-a_seed").get_attribute("data-status") == "captured")
        T = reset(fixture(holds=False))
        as_user(page, T["cy"])
        page.goto(BASE + "/authorizations")
        tid(page, "empty-authorizations").wait_for(timeout=4000)
        check("empty-authorizations", tid(page, "authorization-list").count() == 0)
        page.goto(BASE + "/requests")
        tid(page, "empty-requests").wait_for(timeout=4000)
        check("empty-requests", True)
        T = reset({"currency": "JPY", "minor_units": 0, "users": [
            {"id": "u1", "email": "solo@example.com", "password": "correct horse", "display_name": "Solo",
             "handle": "solo", "balance": 1200}]})
        as_user(page, T["solo"])
        page.goto(BASE + "/")
        tid(page, "empty-activity").wait_for(timeout=4000)
        check("empty-activity", tid(page, "activity-list").count() == 0)
        check("JPY formatting", text(page, "wallet-balance") == "1200 JPY" and text(page, "wallet-available") == "1200 JPY"
              and tid(page, "wallet-held").count() == 0, text(page, "wallet-balance"))
        labels = page.locator("label").all_inner_texts()
        check("JPY: no form label names another currency", not [l for l in labels if "EUR" in l], labels)
        shot(page, "home-jpy-1280")

        # --- layout at 375 px and desktop, screenshots
        T = reset(fixture())
        api("POST", "/payments", {"to_handle": "bob", "amount": 1234, "note": "a fairly long note about dinner at the corner place",
                                  "visibility": "private"}, token=T["ada"], key="x1")
        api("POST", "/requests", {"payer_handle": "bob", "amount": 300, "note": "pizza"}, token=T["ada"], key="x2")
        api("POST", "/authorizations", {"to_handle": "cy", "amount": 1500, "note": "bike"}, token=T["ada"], key="x3")
        for w, hgt in ((375, 800), (1280, 900)):
            p2 = br.new_context(viewport={"width": w, "height": hgt}).new_page()
            p2.goto(BASE + "/login")
            p2.evaluate("t => localStorage.setItem('pf_token', t)", T["ada"])
            for route in ("/", "/requests", "/split", "/authorizations", "/login", "/signup"):
                p2.goto(BASE + route)
                p2.wait_for_timeout(700)
                check("no horizontal scroll %s @%d" % (route, w), no_hscroll(p2))
                if route not in ("/login", "/signup"):
                    nav_ok = p2.evaluate("""() => [...document.querySelectorAll('nav a')].every(a => {
                        const r = a.getBoundingClientRect(); const lh = parseFloat(getComputedStyle(a).lineHeight) || 24;
                        return r.height < lh * 1.9; })""")
                    check("nav labels do not wrap %s @%d" % (route, w), nav_ok)
                shot(p2, "%s-%d" % ((route.strip("/") or "home"), w))
            p2.context.close()
        # keyboard focus visible
        p3 = br.new_context(viewport={"width": 1280, "height": 900}).new_page()
        p3.goto(BASE + "/login")
        p3.keyboard.press("Tab")
        p3.keyboard.press("Tab")
        fo = p3.evaluate("""() => { const e = document.activeElement; const s = getComputedStyle(e);
            return {tag: e.tagName, outline: s.outlineStyle + ' ' + s.outlineWidth, shadow: s.boxShadow}; }""")
        check("keyboard focus is visible", fo["outline"].split()[0] != "none" or fo["shadow"] != "none", fo)
        inputs_labelled = p3.evaluate("""() => [...document.querySelectorAll('input,select')].every(i =>
            i.labels && i.labels.length && i.labels[0].innerText.trim())""")
        check("login inputs have visible labels", inputs_labelled)
        br.close()

    fails = [r for r in RESULTS if not r[1]]
    print("%d UI checks, %d failed" % (len(RESULTS), len(fails)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
