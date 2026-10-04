"""Browser checks (Playwright): run with the kickoff .venv python.  python tests/ui_check.py [shots-dir]"""
import json
import os
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright, expect

PORT = 18199
BASE = "http://127.0.0.1:%d" % PORT
SHOTS = sys.argv[1] if len(sys.argv) > 1 else None
HERE = os.path.dirname(os.path.abspath(__file__))


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req).status


def fixture(**kw):
    users = [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada",
              "handle": "ada", "balance": 10000},
             {"id": "u_bob", "email": "bob@example.com", "password": "correct horse", "display_name": "Bob",
              "handle": "bob", "balance": 2500},
             {"id": "u_cy", "email": "cy@example.com", "password": "correct horse", "display_name": "Cy",
              "handle": "cy", "balance": 0}]
    fx = {"currency": "EUR", "minor_units": 2, "users": users,
          "payments": [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500,
                        "note": "coffee", "visibility": "public"},
                       {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 100,
                        "note": "", "visibility": "private"}],
          "requests": [{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200,
                        "note": "taxi", "status": "pending"}],
          "authorizations": [{"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000,
                              "note": "deposit", "visibility": "public", "status": "open",
                              "expires_at": "2099-01-01T00:00:00+00:00"},
                             {"id": "a_2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 700,
                              "note": "", "visibility": "private", "status": "open",
                              "expires_at": "2099-01-01T00:00:00+00:00"}]}
    fx.update(kw)
    return fx


def login(page, who):
    page.goto(BASE + "/login")
    page.get_by_test_id("login-email").fill(who + "@example.com")
    page.get_by_test_id("login-password").fill("correct horse")
    page.get_by_test_id("login-submit").click()
    page.wait_for_url(BASE + "/")
    expect(page.get_by_test_id("wallet-available")).to_be_visible()


def no_hscroll(page, label):
    w = page.evaluate("[document.documentElement.scrollWidth, innerWidth]")
    assert w[0] <= w[1], "horizontal scroll on %s: %s" % (label, w)


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=True)


def main():
    srv = subprocess.Popen([sys.executable, os.path.join(HERE, "..", "server.py")], env={**os.environ, "PORT": str(PORT)})
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(BASE + "/health"); break
            except Exception:
                time.sleep(0.1)
        post("/_test/reset", fixture())
        with sync_playwright() as p:
            br = p.chromium.launch()
            ctx = br.new_context(viewport={"width": 375, "height": 800})
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)

            # auth
            page.goto(BASE + "/login")
            shot(page, "login-375")
            page.get_by_test_id("login-email").fill("ada@example.com")
            page.get_by_test_id("login-password").fill("nope nope nope")
            page.get_by_test_id("login-submit").click()
            expect(page.get_by_test_id("auth-error")).to_be_visible()
            page.get_by_test_id("login-password").fill("correct horse")
            page.get_by_test_id("login-submit").click()
            page.wait_for_url(BASE + "/")
            expect(page.get_by_test_id("auth-error")).to_have_count(0)
            expect(page.get_by_test_id("current-user")).to_have_text("Ada")
            expect(page.get_by_test_id("current-handle")).to_have_text("ada")
            expect(page.get_by_test_id("wallet-balance")).to_have_text("100.00 EUR")
            expect(page.get_by_test_id("wallet-available")).to_have_text("80.00 EUR")
            expect(page.get_by_test_id("wallet-held")).to_have_text("20.00 EUR")
            assert page.get_by_test_id("wallet-balance").get_attribute("data-amount") == "10000"
            shot(page, "home-375"); no_hscroll(page, "home")

            # pay: validation without a request
            sent = []
            page.on("request", lambda r: sent.append(r.url) if r.method == "POST" and r.url.endswith("/payments") else None)
            page.get_by_test_id("pay-handle").fill("bob")
            page.get_by_test_id("pay-amount").fill("15.005")
            page.get_by_test_id("pay-submit").click()
            expect(page.get_by_test_id("pay-error")).to_be_visible()
            page.get_by_test_id("pay-amount").fill("abc")
            page.get_by_test_id("pay-submit").click()
            expect(page.get_by_test_id("pay-error")).to_be_visible()
            assert not sent
            # pay once; submit again unchanged: still one payment
            page.get_by_test_id("pay-amount").fill("15")
            page.get_by_test_id("pay-note").fill("dinner 🍕")
            page.get_by_test_id("pay-visibility").select_option("private")
            page.get_by_test_id("pay-submit").click()
            expect(page.get_by_test_id("wallet-balance")).to_have_text("85.00 EUR")
            page.get_by_test_id("pay-submit").click()
            page.wait_for_timeout(500)
            expect(page.get_by_test_id("wallet-balance")).to_have_text("85.00 EUR")
            expect(page.get_by_test_id("pay-error")).to_have_count(0)
            expect(page.get_by_test_id("pay-amount")).to_have_value("15")
            items = page.locator("[data-testid^=activity-item-]")
            assert items.count() == 2, items.count()
            first = page.get_by_test_id("activity-list").locator(":scope > *").first
            assert first.get_attribute("data-visibility") == "private"
            pid = first.get_attribute("data-testid")[len("activity-item-"):]
            expect(page.get_by_test_id("activity-amount-" + pid)).to_have_text("15.00 EUR")
            expect(page.get_by_test_id("activity-note-" + pid)).to_have_text("dinner 🍕")
            shot(page, "home-after-pay-375")

            # refused: insufficient available funds (63.00 available after the hold + payment)
            page.get_by_test_id("pay-amount").fill("500.00")
            page.get_by_test_id("pay-submit").click()
            expect(page.get_by_test_id("pay-error")).to_be_visible()
            expect(page.get_by_test_id("pay-handle")).to_have_value("bob")
            shot(page, "home-refused-375")

            # lost response -> uncertain, retry same key/body moves money once
            page.get_by_test_id("pay-amount").fill("1.00")
            keys = []
            state = {"drop": True}

            def handler(route):
                req = route.request
                if req.method == "POST" and state["drop"]:
                    keys.append((req.headers.get("idempotency-key"), req.post_data))
                    route.fetch()
                    state["drop"] = False
                    route.abort("failed")
                else:
                    keys.append((req.headers.get("idempotency-key"), req.post_data))
                    route.continue_()
            page.route("**/payments", handler)
            page.get_by_test_id("pay-submit").click()
            expect(page.get_by_test_id("pay-uncertain")).to_be_visible()
            expect(page.get_by_test_id("pay-error")).to_have_count(0)
            shot(page, "home-uncertain-375")
            page.get_by_test_id("pay-submit").click()
            expect(page.get_by_test_id("pay-uncertain")).to_have_count(0)
            assert len(keys) == 2 and keys[0] == keys[1], keys
            expect(page.get_by_test_id("wallet-balance")).to_have_text("84.00 EUR")
            page.unroute("**/payments")

            # refresh: latest wins when responses arrive out of order
            slow = {"n": 0}

            def me_handler(route):
                slow["n"] += 1
                if slow["n"] == 1:
                    resp = route.fetch()
                    time.sleep(1.2)
                    route.fulfill(response=resp)
                else:
                    route.continue_()
            page.route("**/me", me_handler)
            page.get_by_test_id("wallet-refresh").click()
            post_ok = post("/_test/import", json.loads(urllib.request.urlopen(BASE + "/_test/export").read()))
            page.get_by_test_id("wallet-refresh").click()
            page.wait_for_timeout(2000)
            page.unroute("**/me")

            # requests page
            page.goto(BASE + "/requests")
            expect(page.get_by_test_id("request-item-rq_1")).to_have_attribute("data-status", "pending")
            expect(page.get_by_test_id("request-amount-rq_1")).to_have_text("12.00 EUR")
            shot(page, "requests-375"); no_hscroll(page, "requests")
            post("/_test/reset", fixture()) if False else None
            page.get_by_test_id("request-pay-rq_1").click()
            expect(page.get_by_test_id("request-item-rq_1")).to_have_attribute("data-status", "paid")
            expect(page.get_by_test_id("request-pay-rq_1")).to_have_count(0)

            # stale pay button: request cancelled elsewhere -> request-error and the list refreshes
            tok = json.loads(urllib.request.urlopen(urllib.request.Request(BASE + "/auth/login", data=json.dumps({"email": "bob@example.com", "password": "correct horse"}).encode(), method="POST")).read())["token"]
            def bob(path, body=None, key=None):
                h = {"Authorization": "Bearer " + tok, "Content-Type": "application/json"}
                if key: h["Idempotency-Key"] = key
                return json.loads(urllib.request.urlopen(urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else (b"" if "cancel" in path else None), method="POST", headers=h)).read())
            rq = bob("/requests", {"payer_handle": "ada", "amount": 100}, "ui-k1")["request_id"]
            page.goto(BASE + "/requests")
            expect(page.get_by_test_id("request-pay-" + rq)).to_be_visible()
            bob("/requests/%s/cancel" % rq)
            page.get_by_test_id("request-pay-" + rq).click()
            expect(page.get_by_test_id("request-error")).to_be_visible()
            expect(page.get_by_test_id("request-pay-" + rq)).to_have_count(0)
            expect(page.get_by_test_id("request-item-" + rq)).to_have_attribute("data-status", "cancelled")

            # split
            page.goto(BASE + "/split")
            page.get_by_test_id("split-amount").fill("10.00")
            page.get_by_test_id("split-handles").fill("bob, cy, ada")
            expect(page.get_by_test_id("split-share-bob")).to_have_text("3.34 EUR")
            expect(page.get_by_test_id("split-share-cy")).to_have_text("3.33 EUR")
            shot(page, "split-375"); no_hscroll(page, "split")
            page.get_by_test_id("split-submit").click()
            expect(page.get_by_test_id("split-error")).to_have_count(0)
            expect(page.get_by_test_id("split-share-bob")).to_have_text("3.34 EUR")

            # authorizations
            page.goto(BASE + "/authorizations")
            expect(page.get_by_test_id("authorization-item-a_1")).to_have_attribute("data-status", "open")
            expect(page.get_by_test_id("authorization-void-a_1")).to_be_visible()
            expect(page.get_by_test_id("authorization-capture-amount-a_2")).to_have_value("7.00")
            expect(page.get_by_test_id("authorization-expires-a_1")).to_have_text("2099-01-01T00:00:00+00:00")
            shot(page, "holds-375"); no_hscroll(page, "holds")
            page.get_by_test_id("authorization-capture-a_2").click()
            expect(page.get_by_test_id("authorization-item-a_2")).to_have_attribute("data-status", "captured")
            expect(page.get_by_test_id("authorization-captured-a_2")).to_have_text("7.00 EUR")
            page.get_by_test_id("authorization-void-a_1").click()
            expect(page.get_by_test_id("authorization-item-a_1")).to_have_attribute("data-status", "voided")
            expect(page.get_by_test_id("wallet-held")).to_have_count(0)
            page.get_by_test_id("authorize-handle").fill("cy")
            page.get_by_test_id("authorize-amount").fill("5")
            page.get_by_test_id("authorize-submit").click()
            expect(page.locator("[data-testid^=authorization-item-]")).to_have_count(3)
            expect(page.get_by_test_id("wallet-held")).to_have_text("5.00 EUR")

            # desktop
            d = br.new_context(viewport={"width": 1280, "height": 900}).new_page()
            login(d, "ada")
            shot(d, "home-1280"); no_hscroll(d, "home-desktop")
            d.goto(BASE + "/requests"); shot(d, "requests-1280")
            d.goto(BASE + "/authorizations"); shot(d, "holds-1280")
            d.goto(BASE + "/split"); shot(d, "split-1280")
            d.goto(BASE + "/signup"); shot(d, "signup-1280")
            d.goto(BASE + "/"); d.get_by_test_id("logout-button").click()
            d.wait_for_url(BASE + "/login")
            assert not errors, errors
            br.close()
        print("UI CHECK OK")
    finally:
        srv.terminate()

def extra_checks():
    """Gap-list UI checks: invalid decimals send nothing, JPY/BHD formatting, long text, refresh ordering."""
    srv = subprocess.Popen([sys.executable, os.path.join(HERE, "..", "server.py")], env={**os.environ, "PORT": str(PORT + 1)})
    base = "http://127.0.0.1:%d" % (PORT + 1)
    def api(path, body, token=None, key=None):
        h = {"Content-Type": "application/json"}
        if token: h["Authorization"] = "Bearer " + token
        if key: h["Idempotency-Key"] = key
        r = urllib.request.urlopen(urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST", headers=h))
        return r.status, (json.loads(r.read() or b"null"))
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(base + "/health"); break
            except Exception:
                time.sleep(0.1)
        def users(mu_cur):
            fx = fixture(currency=mu_cur[0], minor_units=mu_cur[1], authorizations=[], requests=[], payments=[])
            for u in fx["users"]:
                u["balance"] = 5000000
            return fx
        def ui_login(page, who):
            page.goto(base + "/login")
            page.get_by_test_id("login-email").fill(who + "@example.com")
            page.get_by_test_id("login-password").fill("correct horse")
            page.get_by_test_id("login-submit").click()
            page.wait_for_url(base + "/")
            expect(page.get_by_test_id("wallet-available")).to_be_visible()
        with sync_playwright() as p:
            br = p.chromium.launch()
            page = br.new_context(viewport={"width": 375, "height": 800}).new_page()
            # JPY / BHD
            api("/_test/reset", users(("JPY", 0)))
            ui_login(page, "ada")
            expect(page.get_by_test_id("wallet-balance")).to_have_text("5000000 JPY")
            bodies = []
            page.on("request", lambda r: bodies.append(r.post_data) if r.method == "POST" else None)
            page.get_by_test_id("pay-handle").fill("bob"); page.get_by_test_id("pay-amount").fill("15.5")
            page.get_by_test_id("pay-submit").click()
            expect(page.get_by_test_id("pay-error")).to_be_visible()
            assert not bodies
            page.get_by_test_id("pay-amount").fill("15"); page.get_by_test_id("pay-submit").click()
            expect(page.get_by_test_id("wallet-balance")).to_have_text("4999985 JPY")
            api("/_test/reset", users(("BHD", 3)))
            page.goto(base + "/login") if False else None
            ui_login(page, "ada")
            bodies.clear()
            page.get_by_test_id("pay-handle").fill("bob"); page.get_by_test_id("pay-amount").fill("1.234")
            page.get_by_test_id("pay-submit").click()
            expect(page.get_by_test_id("wallet-balance")).to_have_text("4998.766 BHD")
            assert json.loads(bodies[-1])["amount"] == 1234
            # invalid decimals on every form send nothing
            api("/_test/reset", users(("EUR", 2)))
            ui_login(page, "ada")
            bodies.clear()
            for bad in ["abc", "-5", "1e3", "15,00", "", "10.005", " "]:
                for pre, handle_val in (("pay", "bob"), ("request", "bob"), ("authorize", "bob")):
                    page.get_by_test_id(pre + "-handle").fill(handle_val)
                    page.get_by_test_id(pre + "-amount").fill(bad)
                    page.get_by_test_id(pre + "-submit").click()
                    expect(page.get_by_test_id(pre + "-error")).to_be_visible()
            page.goto(base + "/split")
            for bad in ["abc", "-5", "1e3", "15,00", "", "10.005"]:
                page.get_by_test_id("split-amount").fill(bad); page.get_by_test_id("split-handles").fill("bob")
                page.get_by_test_id("split-submit").click()
                expect(page.get_by_test_id("split-error")).to_be_visible()
            assert not bodies, bodies
            # long unbroken text never scrolls the page sideways
            tok = api("/auth/login", {"email": "ada@example.com", "password": "correct horse"})[1]["token"]
            long = "x" * 190
            api("/payments", {"to_handle": "bob", "amount": 5, "note": long}, tok, "ln1")
            api("/requests", {"payer_handle": "bob", "amount": 5, "note": long}, tok, "ln2")
            api("/authorizations", {"to_handle": "bob", "amount": 5, "note": long}, tok, "ln3")
            for route in ("/", "/requests", "/authorizations"):
                page.goto(base + route)
                page.wait_for_timeout(400)
                no_hscroll(page, "long text " + route)
            # latest refresh wins
            page.goto(base + "/")
            expect(page.get_by_test_id("wallet-available")).to_be_visible()
            first = {"n": 0}
            def slow(route):
                first["n"] += 1
                if first["n"] == 1:
                    resp = route.fetch(); time.sleep(2); route.fulfill(response=resp)
                else:
                    route.continue_()
            page.route("**/me", slow)
            before = page.get_by_test_id("wallet-balance").inner_text()
            page.get_by_test_id("wallet-refresh").click()
            page.wait_for_timeout(300)
            bobtok = api("/auth/login", {"email": "bob@example.com", "password": "correct horse"})[1]["token"]
            api("/payments", {"to_handle": "ada", "amount": 1000}, bobtok, "ooo")
            page.get_by_test_id("wallet-refresh").click()
            expect(page.get_by_test_id("wallet-balance")).not_to_have_text(before)
            later = page.get_by_test_id("wallet-balance").inner_text()
            page.wait_for_timeout(2500)
            expect(page.get_by_test_id("wallet-balance")).to_have_text(later)
            br.close()
        print("EXTRA UI CHECK OK")
    finally:
        srv.terminate()


main()
extra_checks()
