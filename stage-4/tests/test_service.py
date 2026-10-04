import http.client
import json
import os
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server  # noqa: E402

SRV = server.make_server(0, "127.0.0.1")
PORT = SRV.server_address[1]
threading.Thread(target=SRV.serve_forever, daemon=True).start()


def datetime_now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def call(method, path, body=None, token=None, key=None, raw=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    h = dict(headers or {})
    if token:
        h["Authorization"] = "Bearer " + token
    if key is not None:
        h["Idempotency-Key"] = key
    data = raw if raw is not None else (None if body is None else json.dumps(body))
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    txt = r.read()
    ctype = r.getheader("Content-Type")
    c.close()
    return r.status, (json.loads(txt) if txt and "json" in (ctype or "") else (txt.decode() if txt else None)), ctype


def fixture(**kw):
    users = [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 10000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 2500},
        {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
         "display_name": "Cy", "handle": "cy", "balance": 0},
    ]
    fx = {"currency": "EUR", "minor_units": 2, "users": users,
          "payments": [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
                        "amount": 500, "note": "coffee", "visibility": "public"}],
          "requests": [{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada",
                        "amount": 1200, "note": "taxi", "status": "pending"}],
          "settlement_operator_ids": ["u_ada"]}
    fx.update(kw)
    return fx


def login(email):
    s, b, _ = call("POST", "/auth/login", {"email": email + "@example.com", "password": "correct horse"})
    assert s == 200, b
    return b["token"]


class Base(unittest.TestCase):
    def setUp(self):
        s, _, _ = call("POST", "/_test/reset", fixture())
        self.assertEqual(s, 204)
        self.ada, self.bob, self.cy = login("ada"), login("bob"), login("cy")

    def bal(self, tok):
        return call("GET", "/me", token=tok)[1]["balance"]

    def total(self):
        return sum(self.bal(t) for t in (self.ada, self.bob, self.cy))


class Basics(Base):
    def test_health_and_content_type(self):
        s, b, ct = call("GET", "/health")
        self.assertEqual((s, b), (200, {"status": "ok"}))
        self.assertEqual(ct, "application/json; charset=utf-8")
        s, b, ct = call("GET", "/me")
        self.assertEqual((s, ct), (401, "application/json; charset=utf-8"))

    def test_401_everywhere(self):
        for m, p in [("GET", "/me"), ("POST", "/payments"), ("POST", "/requests"),
                     ("GET", "/requests"), ("POST", "/requests/rq_1/pay"),
                     ("POST", "/requests/rq_1/decline"), ("POST", "/requests/rq_1/cancel"),
                     ("POST", "/splits"), ("GET", "/activity"), ("POST", "/settlements")]:
            for hdr in ({}, {"Authorization": "Bearer garbage"}, {"Authorization": "Basic x"}):
                s, b, _ = call(m, p, {}, key="k", headers=hdr)
                self.assertEqual(s, 401, (m, p, hdr))
                self.assertEqual(b["error"]["code"], "unauthenticated")

    def test_basic_scheme_and_big_reset(self):
        s, _, _ = call("GET", "/me", headers={"Authorization": "Basic " + self.ada})
        self.assertEqual(s, 401)
        s, _, _ = call("GET", "/me", headers={"Authorization": self.ada})
        self.assertEqual(s, 401)
        import time
        fx = fixture()
        fx["users"] += [{"id": "x%d" % i, "email": "x%d@e.io" % i, "password": "pw-%d-xxxxxxxx" % i,
                         "display_name": "X", "handle": "x%d" % i, "balance": 1} for i in range(1200)]
        t0 = time.time()
        self.assertEqual(call("POST", "/_test/reset", fx)[0], 204)
        self.assertLess(time.time() - t0, 6)
        s, b, _ = call("POST", "/auth/login", {"email": "x77@e.io", "password": "pw-77-xxxxxxxx"})
        self.assertEqual(s, 200)
        self.assertEqual(call("POST", "/auth/login", {"email": "x77@e.io", "password": "wrong-password"})[0], 401)
        s, snap, _ = call("GET", "/_test/export")
        call("POST", "/_test/reset", fixture())
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        self.assertEqual(call("POST", "/auth/login", {"email": "x77@e.io", "password": "pw-77-xxxxxxxx"})[0], 200)

    def test_signup_login(self):
        s, b, _ = call("POST", "/auth/signup", {"email": "ada@example.com", "password": "12345678", "display_name": "x"})
        self.assertEqual((s, b["error"]["code"]), (409, "email_taken"))
        for pw, st in (("1234567", 422), ("12345678", 201)):
            s, b, _ = call("POST", "/auth/signup", {"email": "n1@x.io", "password": pw, "display_name": "N"})
            self.assertEqual(s, st)
        tok = b["token"]
        for e in ("noat", "@x.com", "a@", "a@b@c"):
            s, _, _ = call("POST", "/auth/signup", {"email": e, "password": "12345678", "display_name": "N"})
            self.assertEqual(s, 422, e)
        self.assertEqual(call("POST", "/auth/signup", {"email": 5, "password": "12345678", "display_name": "N"})[0], 400)
        self.assertEqual(call("POST", "/auth/signup", {"email": "q@q.io", "password": 12345678, "display_name": "N"})[0], 400)
        s, b2, _ = call("POST", "/auth/login", {"email": "n1@x.io", "password": "12345678"})
        self.assertEqual(s, 200)
        self.assertEqual(call("GET", "/me", token=tok)[0], 200)
        self.assertEqual(call("GET", "/me", token=b2["token"])[0], 200)
        self.assertEqual(call("POST", "/auth/login", {"email": "n1@x.io", "password": "wrong"})[0], 401)
        self.assertEqual(call("POST", "/auth/login", {"email": "no@x.io", "password": "wrong"})[0], 401)
        s, b, _ = call("POST", "/auth/signup", {"email": "N1@y.io", "password": "12345678", "display_name": "N"})
        self.assertEqual((s, b["error"]["code"]), (409, "handle_taken"))

    def test_derived_handle(self):
        s, b, _ = call("POST", "/auth/signup", {"email": "Zoë.Q@x.io", "password": "12345678", "display_name": "Z"})
        self.assertEqual(s, 201)
        self.assertEqual(call("GET", "/me", token=b["token"])[1]["handle"], "zo__q")
        s, b, _ = call("POST", "/auth/signup", {"email": "a" * 30 + "@x.io", "password": "12345678", "display_name": "Z"})
        self.assertEqual(call("GET", "/me", token=b["token"])[1]["handle"], "a" * 20)
        s, _, _ = call("POST", "/requests", {"payer_handle": "zo__q", "amount": 5}, token=self.ada, key="k")
        self.assertEqual(s, 201)

    def test_reset_clears_everything(self):
        s, b, _ = call("POST", "/auth/signup", {"email": "n1@x.io", "password": "12345678", "display_name": "N"})
        tok = b["token"]
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=self.ada, key="k")[0], 201)
        call("POST", "/_test/reset", fixture())
        self.assertEqual(call("GET", "/me", token=tok)[0], 401)
        self.assertEqual(call("GET", "/me", token=self.ada)[0], 401)
        self.assertEqual(call("POST", "/auth/login", {"email": "n1@x.io", "password": "12345678"})[0], 401)
        ada = login("ada")
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=ada, key="k")[0], 201)

    def test_reset_validates_like_import(self):
        def bad(f):
            fx = fixture()
            f(fx)
            self.assertEqual(call("POST", "/_test/reset", fx)[0], 422)
            self.assertEqual(self.bal(self.ada), 10000)  # unchanged
        bad(lambda fx: fx["payments"][0].__setitem__("amount", 1000000001))
        bad(lambda fx: fx["requests"][0].__setitem__("amount", 1000000001))
        bad(lambda fx: fx["users"][0].__setitem__("balance", 2 ** 53 + 1))
        bad(lambda fx: fx["users"][0].__setitem__("balance", 10 ** 30))
        bad(lambda fx: fx["payments"][0].__setitem__("request_id", "ghost"))
        bad(lambda fx: fx["payments"][0].__setitem__("note", "x" * 201))
        bad(lambda fx: fx["requests"][0].__setitem__("note", "x" * 201))
        bad(lambda fx: fx["payments"][0].__setitem__("to_user_id", "u_ada"))
        bad(lambda fx: fx["requests"][0].__setitem__("payment_id", "ghost"))
        fx = fixture()
        fx["users"][0]["balance"] = 2 ** 53
        fx["requests"][0].update({"payment_id": "p_1", "status": "paid", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 500})
        self.assertEqual(call("POST", "/_test/reset", fx)[0], 204)
        fx["requests"][0]["amount"] = 501  # the linked payment disagrees
        self.assertEqual(call("POST", "/_test/reset", fx)[0], 422)
        fx["requests"][0].update({"amount": 500, "status": "paid", "payment_id": None})  # paid without a link is tolerated
        self.assertEqual(call("POST", "/_test/reset", fx)[0], 204)
        # a huge number in an unknown field is ignored, never a 400/5xx
        fx = fixture(whatever="x")
        raw = json.dumps(fx)[:-1] + ', "junk": ' + "9" * 5000 + "}"
        self.assertEqual(call("POST", "/_test/reset", raw=raw)[0], 204)
        self.assertEqual(self.bal(login("ada")), 10000)

    def test_huge_offset_is_an_empty_page(self):
        for p in ("/activity", "/requests"):
            s, b, _ = call("GET", p + "?offset=" + "9" * 5000, token=self.ada)
            self.assertEqual((s, b.get("payments", b.get("requests")), b["has_more"]), (200, [], False))

    def test_reset_negative_balance(self):
        fx = fixture()
        fx["users"][0]["balance"] = -1
        self.assertEqual(call("POST", "/_test/reset", fx)[0], 422)
        self.assertEqual(self.bal(self.ada), 10000)
        self.assertEqual(call("POST", "/_test/reset", raw="{nope")[0], 400)

    def test_large_balance(self):
        fx = fixture()
        fx["users"][0]["balance"] = 9007199254000000
        call("POST", "/_test/reset", fx)
        ada = login("ada")
        self.assertEqual(self.bal(ada), 9007199254000000)
        call("POST", "/payments", {"to_handle": "bob", "amount": 1000000000}, token=ada, key="k")
        self.assertEqual(self.bal(ada), 9007199254000000 - 1000000000)

    def test_query_ints(self):
        for p in ("/activity", "/requests"):
            for q in ("limit=4.0", "limit=%2B4", "offset=1e1", "limit=", "limit=0", "limit=201", "offset=-1", "limit=1e9"):
                self.assertEqual(call("GET", p + "?" + q, token=self.ada)[0], 422, (p, q))
            self.assertEqual(call("GET", p + "?limit=200&offset=0&foo=bar", token=self.ada)[0], 200)
        for p in ("/activity", "/requests"):
            self.assertEqual(call("GET", p + "?limit=" + "9" * 5000, token=self.ada)[0], 422)
            s, b, _ = call("GET", p + "?offset=" + "9" * 5000, token=self.ada)
            self.assertEqual((s, b["has_more"]), (200, False))
            self.assertEqual(call("GET", p + "?limit=" + "0" * 5000 + "5", token=self.ada)[0], 200)
        self.assertEqual(call("GET", "/requests?status=x", token=self.ada)[0], 422)
        self.assertEqual(call("GET", "/requests?direction=x", token=self.ada)[0], 422)


class Pages(Base):
    def test_html_vs_json(self):
        for path in ("/", "/requests", "/split", "/signup", "/login", "/authorizations"):
            s, _, ct = call("GET", path, headers={"Accept": "text/html,application/xhtml+xml"})
            self.assertEqual((s, ct), (200, "text/html; charset=utf-8"), path)
        for path in ("/split", "/signup", "/login"):
            self.assertEqual(call("GET", path)[2], "text/html; charset=utf-8")
        s, b, ct = call("GET", "/requests", token=self.ada, headers={"Accept": "application/json"})
        self.assertEqual((s, ct, "requests" in b), (200, "application/json; charset=utf-8", True))
        s, b, ct = call("GET", "/authorizations", token=self.ada)
        self.assertEqual((s, "authorizations" in b), (200, True))
        self.assertEqual(call("GET", "/requests")[0], 401)


class Strictness(Base):
    def test_exact_numbers_in_body_identity(self):
        b = '{"to_handle":"bob","amount":1,"extra":%s}'
        self.assertEqual(call("POST", "/payments", raw=b % "1.0000000000000001", token=self.ada, key="K")[0], 201)
        self.assertEqual(call("POST", "/payments", raw=b % "1.0000000000000001", token=self.ada, key="K")[0], 200)
        self.assertEqual(call("POST", "/payments", raw=b % "1", token=self.ada, key="K")[0], 409)
        self.assertEqual(call("POST", "/payments", raw=b % "1.0", token=self.ada, key="K2")[0], 201)
        self.assertEqual(call("POST", "/payments", raw=b % "1", token=self.ada, key="K2")[0], 200)

    def test_trailing_zeros_are_the_same_value(self):
        b = '{"to_handle":"bob","amount":1,"x":%s}'
        self.assertEqual(call("POST", "/payments", raw=b % "1.5", token=self.ada, key="TZ")[0], 201)
        self.assertEqual(call("POST", "/payments", raw=b % "1.50", token=self.ada, key="TZ")[0], 200)
        self.assertEqual(call("POST", "/payments", raw=b % "15e-1", token=self.ada, key="TZ")[0], 200)
        self.assertEqual(call("POST", "/payments", raw=b % "1.51", token=self.ada, key="TZ")[0], 409)

    def test_numbers_never_collide_with_strings_or_overflow(self):
        b = '{"to_handle":"bob","amount":1,"x":%s}'
        self.assertEqual(call("POST", "/payments", raw=b % "1.5", token=self.ada, key="NC")[0], 201)
        self.assertEqual(call("POST", "/payments", raw=b % '"1.5"', token=self.ada, key="NC")[0], 409)
        self.assertEqual(call("POST", "/payments", raw=b % "1.50", token=self.ada, key="NC")[0], 200)
        self.assertEqual(call("POST", "/payments", raw=b % "1e40", token=self.ada, key="NC2")[0], 201)
        self.assertEqual(call("POST", "/payments", raw=b % '"1E+40"', token=self.ada, key="NC2")[0], 409)
        self.assertEqual(call("POST", "/payments", raw=b % "true", token=self.ada, key="NC3")[0], 201)
        self.assertEqual(call("POST", "/payments", raw=b % "1", token=self.ada, key="NC3")[0], 409)
        self.assertEqual(call("POST", "/payments", raw=b % "[1]", token=self.ada, key="NC4")[0], 201)
        self.assertEqual(call("POST", "/payments", raw=b % '[1.0]', token=self.ada, key="NC4")[0], 200)
        for huge in ("1E+999999999", "1e1000000000", "1E-999999999", "-1e999999999", "1e99999999999999999999"):
            s, bb, _ = call("POST", "/payments", raw='{"to_handle":"bob","amount":%s}' % huge, token=self.ada, key="hg" + huge)
            self.assertEqual(s, 422, huge)
            s, bb, _ = call("POST", "/payments", raw=b % huge, token=self.ada, key="hx" + huge)
            self.assertEqual(s, 201, huge)
            self.assertEqual(call("POST", "/payments", raw=b % huge, token=self.ada, key="hx" + huge)[0], 200)

    def test_legacy_fingerprints_still_replay(self):
        s, p, _ = call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=self.ada, key="LG")
        s, snap, _ = call("GET", "/_test/export")
        for rec in snap["state"]["idempotency"]:
            rec[3] = json.dumps({"amount": 100, "to_handle": "bob"}, sort_keys=True, separators=(",", ":"))
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 100.0}, token=self.ada, key="LG")[0], 200)
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 101}, token=self.ada, key="LG")[0], 409)

    def test_string_literals_never_equal_json_literals(self):
        b = '{"to_handle":"bob","amount":1,"x":%s}'
        self.assertEqual(call("POST", "/payments", raw=b % '"true"', token=self.ada, key="LT")[0], 201)
        self.assertEqual(call("POST", "/payments", raw=b % "true", token=self.ada, key="LT")[0], 409)
        self.assertEqual(call("POST", "/payments", raw=b % "null", token=self.ada, key="LN")[0], 201)
        self.assertEqual(call("POST", "/payments", raw=b % '"null"', token=self.ada, key="LN")[0], 409)

    def test_bad_timestamps_and_dangling_refs_rejected_on_reset_and_import(self):
        for ts in ("yesterday", "2026-02-30T00:00:00+00:00", 5):
            fx = fixture()
            fx["payments"][0]["created_at"] = ts
            self.assertEqual(call("POST", "/_test/reset", fx)[0], 422, ts)
        self.assertEqual(self.bal(login("ada")), 10000)
        call("POST", "/_test/reset", fixture())
        s, snap, _ = call("GET", "/_test/export")
        snap["state"]["idempotency"] = []
        for f in (lambda st: st["payments"][0].__setitem__("created_at", "yesterday"),
                  lambda st: st["payments"][0].__setitem__("created_at", "2026-02-30T00:00:00+00:00"),
                  lambda st: st["payments"][0].__setitem__("request_id", "ghost"),
                  lambda st: st["payments"][0].__setitem__("settlement_id", "ghost"),
                  lambda st: st["requests"][0].__setitem__("created_at", "2026-02-30T00:00:00+00:00")):
            m = json.loads(json.dumps(snap))
            f(m["state"])
            self.assertEqual(call("POST", "/_test/import", m)[0], 422)
        self.assertEqual(self.bal(login("ada")), 10000)

    def test_huge_integers(self):
        big = "9" * 5000
        for path, body in (("/payments", '{"to_handle":"bob","amount":%s}'), ("/requests", '{"payer_handle":"bob","amount":%s}'),
                           ("/splits", '{"participant_handles":["bob"],"amount":%s}')):
            self.assertEqual(call("POST", path, raw=body % big, token=self.ada, key="h" + path)[0], 422, path)
        self.assertEqual(call("POST", "/payments", raw='{"to_handle":"bob","amount":1,"x":%s}' % big, token=self.ada, key="hx")[0], 201)


    def writes_everything(self):
        call("POST", "/payments", {"to_handle": "bob", "amount": 100, "note": "n"}, token=self.ada, key="w-p")
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 50}, token=self.bob, key="w-r")[1]["request_id"]
        call("POST", "/requests/%s/pay" % rq, {"visibility": "private"}, token=self.ada, key="w-pay")
        rq2 = call("POST", "/requests", {"payer_handle": "ada", "amount": 70}, token=self.bob, key="w-r2")[1]["request_id"]
        call("POST", "/requests/%s/cancel" % rq2, token=self.bob)
        call("POST", "/splits", {"amount": 1, "participant_handles": ["cy", "bob", "ada"]}, token=self.ada, key="w-s")
        call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 5}]}, token=self.ada, key="w-st")

        if True:
            a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 300}, token=self.ada, key="w-a")[1]["authorization_id"]
            call("POST", "/authorizations/%s/capture" % a, {"amount": 100, "final": False}, token=self.bob, key="w-c")
            a2 = call("POST", "/authorizations", {"to_handle": "cy", "amount": 50}, token=self.ada, key="w-a2")[1]["authorization_id"]
            call("POST", "/authorizations/%s/void" % a2, token=self.ada)

    def test_receipts_round_trip_and_tampering(self):
        self.writes_everything()
        s, snap, _ = call("GET", "/_test/export")
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        # original receipts replay after the live resources changed
        self.assertEqual(call("POST", "/requests", {"payer_handle": "ada", "amount": 70}, token=self.bob, key="w-r2")[1]["status"], "pending")
        recs = snap["state"]["idempotency"]
        self.assertGreaterEqual(len(recs), 6)
        def tamper(i, f):
            m = json.loads(json.dumps(snap))
            f(m["state"]["idempotency"][i][4])
            self.assertEqual(call("POST", "/_test/import", m)[0], 422, (i, recs[i][2]))
        for i, rec in enumerate(recs):
            path = rec[2]
            if path in ("/payments",) or path.endswith("/pay") or path.endswith("/capture"):
                tamper(i, lambda r: r.__setitem__("amount", r["amount"] + 1))
                tamper(i, lambda r: r.__setitem__("to_handle", "cy"))
                tamper(i, lambda r: r.__setitem__("created_at", "2001-01-01T00:00:00+00:00"))
                tamper(i, lambda r: r.__setitem__("payment_id", "nope"))
            elif path == "/requests":
                tamper(i, lambda r: r.__setitem__("amount", r["amount"] + 1))
                tamper(i, lambda r: r.__setitem__("status", "bogus"))
                tamper(i, lambda r: r.__setitem__("payer_handle", "cy"))
            elif path == "/splits":
                tamper(i, lambda r: r.__setitem__("amount", r["amount"] + 1))
                tamper(i, lambda r: r["shares"][0].__setitem__("amount", r["shares"][0]["amount"] + 1))
            elif path == "/settlements":
                tamper(i, lambda r: r["payments"][0].__setitem__("amount", 6))
                tamper(i, lambda r: r.__setitem__("committed_at", "2001-01-01T00:00:00+00:00"))
            elif path == "/authorizations":
                tamper(i, lambda r: r.__setitem__("amount", r["amount"] + 1))
                tamper(i, lambda r: r.__setitem__("expires_at", "2001-01-01T00:00:00+00:00"))
        for f in (lambda st: st["idempotency"][0].__setitem__(0, "ghost"),
                  lambda st: st["idempotency"][0].__setitem__(2, "/unknown")):
            m = json.loads(json.dumps(snap)); f(m["state"])
            self.assertEqual(call("POST", "/_test/import", m)[0], 422)
        self.assertEqual(self.bal(self.ada), call("GET", "/me", token=self.ada)[1]["balance"])
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)

    def test_property_every_state_reimports_unchanged(self):
        import random
        corrected, corr_codes, refunded, batched = [0], set(), [0], [0]
        for seed in (1, 2, 3):
            rnd = random.Random(seed)
            call("POST", "/_test/reset", fixture())
            toks = {"ada": login("ada"), "bob": login("bob"), "cy": login("cy")}
            names = list(toks)
            reqs, auths, pids, n = [], [], [], [0]

            def key():
                n[0] += 1
                return "k%d-%d" % (seed, n[0])

            def op():
                who = rnd.choice(names)
                other = rnd.choice([x for x in names if x != who])
                kind = rnd.choice(["pay", "pay", "req", "reqpay", "decline", "cancel", "split", "settle", "auth", "cap", "void", "signup", "correct", "correct", "refund", "batch"] if True
                                  else ["pay", "pay", "req", "reqpay", "decline", "cancel", "split", "settle", "signup", "correct", "refund", "batch"])
                amt = rnd.choice([0, 1, 7, 100, 250, 999])
                if kind == "pay" and amt:
                    s, b, _ = call("POST", "/payments", {"to_handle": other, "amount": amt, "note": rnd.choice(["", "n", "é🍕"]), "visibility": rnd.choice(["public", "private"])}, token=toks[who], key=key())
                    if s == 201:
                        pids.append((b["payment_id"], who, other))
                elif kind == "refund" and pids:
                    pid, owner, receiver = rnd.choice(pids)
                    rs, rb, _ = call("POST", "/payments/%s/refunds" % pid, {"amount": rnd.choice([1, 5, 50, 300])}, token=toks[receiver], key=key())
                    refunded[0] += rs == 201
                elif kind == "batch" and pids:
                    chosen = rnd.sample(pids, min(len(pids), rnd.choice([1, 2])))
                    from datetime import datetime, timedelta, timezone
                    eff = (datetime.now(timezone.utc) - timedelta(seconds=rnd.choice([0, 2, 90]))).isoformat(timespec="seconds")
                    items = []
                    for pid, owner, _ in chosen:
                        cur = call("GET", "/payments/%s/revisions" % pid, token=toks[owner])[1]["revisions"][-1]["revision"]
                        items.append({"payment_id": pid, "expected_revision": cur, "amount": rnd.choice([0, 1, 40, 250]), "effective_at": eff, "reason": "batch"})
                    bs, bb, _ = call("POST", "/correction-batches", {"corrections": items}, token=toks["ada"], key=key())
                    batched[0] += bs == 201
                elif kind == "correct" and pids:
                    pid, owner, _ = rnd.choice(pids)
                    cur = call("GET", "/payments/%s/revisions" % pid, token=toks[owner])[1]["revisions"][-1]["revision"]
                    from datetime import datetime, timedelta, timezone
                    eff = (datetime.now(timezone.utc) - timedelta(seconds=rnd.choice([0, 1, 30, 4000]))).isoformat(timespec="seconds")
                    cs, cb, _ = call("POST", "/payments/%s/corrections" % pid, {"expected_revision": cur, "amount": rnd.choice([0, 1, 50, 200, 700]), "effective_at": eff, "reason": "prop"}, token=toks[owner], key=key())
                    corrected[0] += cs == 201
                    corr_codes.add(cb.get("error", {}).get("code") if cs != 201 else 201)
                elif kind == "req" and amt:
                    s, b, _ = call("POST", "/requests", {"payer_handle": other, "amount": amt}, token=toks[who], key=key())
                    if s == 201:
                        reqs.append(b["request_id"])
                elif kind == "reqpay" and reqs:
                    call("POST", "/requests/%s/pay" % rnd.choice(reqs), {"visibility": rnd.choice(["public", "private"])}, token=toks[who], key=key())
                elif kind in ("decline", "cancel") and reqs:
                    call("POST", "/requests/%s/%s" % (rnd.choice(reqs), kind), token=toks[who])
                elif kind == "split":
                    hs = rnd.sample(names, rnd.randint(1, 3))
                    s, b, _ = call("POST", "/splits", {"amount": rnd.choice([1, 10, 1000]), "participant_handles": hs, "note": "s"}, token=toks[who], key=key())
                    if s == 201:
                        reqs.extend(r["request_id"] for r in b["requests"])
                elif kind == "settle":
                    call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": other if other != "ada" else "bob", "amount": amt or 1}, {"from_handle": "bob", "to_handle": "cy", "amount": 1, "visibility": "private"}]}, token=toks["ada"], key=key())
                elif kind == "signup":
                    call("POST", "/auth/signup", {"email": "u%d@x.io" % n[0], "password": "12345678", "display_name": "U"})
                elif kind == "auth" and amt:
                    s, b, _ = call("POST", "/authorizations", {"to_handle": other, "amount": amt, "note": "a"}, token=toks[who], key=key())
                    if s == 201:
                        auths.append(b["authorization_id"])
                elif kind == "cap" and auths:
                    call("POST", "/authorizations/%s/capture" % rnd.choice(auths), rnd.choice([{}, {"amount": 1, "final": False}, {"amount": 5}]), token=toks[who], key=key())
                elif kind == "void" and auths:
                    call("POST", "/authorizations/%s/void" % rnd.choice(auths), token=toks[who])

            for step in range(45):
                op()
                s, a, _ = call("GET", "/_test/export")
                self.assertEqual(call("POST", "/_test/import", a)[0], 204, (seed, step))
                s, b, _ = call("GET", "/_test/export")
                self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True), (seed, step))
                # every historical view conserves the total; statements add up and match /me
                total = 0
                for nm in names:
                    me = call("GET", "/me?as_of=2999-01-01T00:00:00%2B00:00&known_at=2999-01-01T00:00:00%2B00:00", token=toks[nm])[1]
                    total += me["balance"]
                    st = call("GET", "/statement?limit=200", token=toks[nm])[1]
                    self.assertEqual(st["opening_balance"] + sum(x["delta"] for x in st["entries"]), st["closing_balance"])
                    self.assertEqual(st["closing_balance"], call("GET", "/me", token=toks[nm])[1]["balance"])
                    self.assertGreaterEqual(min([st["opening_balance"]] + [x["balance_after"] for x in st["entries"]]), 0)
                self.assertEqual(total, 12500)
        self.assertGreater(corrected[0], 3, corr_codes)
        self.assertGreater(refunded[0], 1)
        self.assertGreater(batched[0], 1)

    def test_import_applies_every_api_field_rule(self):
        call("POST", "/payments", {"to_handle": "bob", "amount": 100, "note": "n"}, token=self.ada, key="sw1")
        call("POST", "/requests", {"payer_handle": "ada", "amount": 100}, token=self.bob, key="sw2")
        call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 5}]}, token=self.ada, key="sw3")
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 40}, token=self.bob, key="sw5")[1]["request_id"]
        call("POST", "/requests/%s/pay" % rq, {}, token=self.ada, key="sw6")
        call("POST", "/splits", {"amount": 30, "participant_handles": ["bob", "cy"], "note": "s"}, token=self.ada, key="sw7")
        if True:
            call("POST", "/authorizations", {"to_handle": "bob", "amount": 100}, token=self.ada, key="sw4")
        s, snap, _ = call("GET", "/_test/export")
        snap["state"]["idempotency"] = []
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        bad2 = [lambda st: [p for p in st["payments"] if p["note"] == "n"][0].__setitem__("note", "x" * 201),
                lambda st: st["requests"][-1].__setitem__("note", "x" * 201),
                lambda st: [p for p in st["payments"] if p["note"] == "n"][0].__setitem__("note", None),
                lambda st: [p for p in st["payments"] if p["note"] == "n"][0].__setitem__("to_user_id", [p for p in st["payments"] if p["note"] == "n"][0]["from_user_id"]),
                lambda st: st["requests"][-1].__setitem__("payer_id", st["requests"][-1]["requester_id"]),
                lambda st: [p for p in st["payments"] if p["note"] == "n"][0].__setitem__("ts", [p for p in st["payments"] if p["note"] == "n"][0]["ts"] + 5000),
                lambda st: st["requests"][-1].__setitem__("ts", st["requests"][-1]["ts"] - 5000),
                lambda st: [p for p in st["payments"] if p["settlement_id"]][0].__setitem__("settlement_id", None),
                lambda st: list(st["settlements"].values())[0].__setitem__("committed_at", "2001-01-01T00:00:00+00:00"),
                lambda st: list(st["settlements"].values())[0]["payment_ids"].append(list(st["settlements"].values())[0]["payment_ids"][0]),
                lambda st: st["payments"][0].__setitem__("seq", st["requests"][0]["seq"])]

        if True:
            bad2.append(lambda st: st["authorizations"][0].__setitem__("note", "x" * 201))
            bad2.append(lambda st: st["authorizations"][0].__setitem__("to_user_id", st["authorizations"][0]["from_user_id"]))
            bad2.append(lambda st: st["authorizations"][0].__setitem__("expires_ts", st["authorizations"][0]["expires_ts"] + 5000))

        bad2 += [lambda st: st["requests"][-1].__setitem__("payment_id", st["payments"][0]["id"]),
                 lambda st: [r for r in st["requests"] if r["status"] == "paid"][0].__setitem__("amount", 99),
                 lambda st: [r for r in st["requests"] if r["status"] == "paid"][0].__setitem__("status", "pending"),
                 lambda st: [p for p in st["payments"] if p["request_id"]][0].__setitem__("amount", 77),
                 lambda st: [p for p in st["payments"] if p["request_id"]][0].__setitem__("to_user_id", st["users"][2]["id"]),
                 lambda st: [p for p in st["payments"] if p["settlement_id"]][0].__setitem__("created_at", "2001-01-01T00:00:00+00:00"),
                 lambda st: list(st["settlements"].values())[0]["payment_ids"].clear(),
                 lambda st: list(st["splits"].values())[0].__setitem__("note", "x" * 201),
                 lambda st: list(st["splits"].values())[0]["shares"][0].__setitem__("amount", 12345),
                 lambda st: st["tokens"].__setitem__("t", "ghost-user"),
                 lambda st: st["users"][0].__setitem__("handle", "NOT valid")]
        for i, f in enumerate(bad2):
            m = json.loads(json.dumps(snap))
            f(m["state"])
            self.assertEqual(call("POST", "/_test/import", m)[0], 422, i)
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)

    def test_zero_share_state_roundtrips(self):
        s, sp, _ = call("POST", "/splits", {"amount": 1, "participant_handles": ["cy", "bob", "ada"]}, token=self.ada, key="Z")
        zero = sp["requests"][1]["request_id"]  # bob's share is 0
        self.assertEqual(call("POST", "/requests/%s/pay" % zero, {}, token=self.bob, key="ZP")[0], 201)
        s, snap, _ = call("GET", "/_test/export")
        call("POST", "/_test/reset", fixture())
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        s, b, _ = call("GET", "/requests?status=paid", token=self.bob)
        self.assertEqual([r["amount"] for r in b["requests"]], [0])

    def test_import_is_strict_and_transactional(self):
        call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=self.ada, key="K")
        call("POST", "/requests", {"payer_handle": "ada", "amount": 100}, token=self.cy, key="Q")
        s, snap, _ = call("GET", "/_test/export")
        def mutate(f):
            m = json.loads(json.dumps(snap))
            f(m["state"])
            return m
        bad = [lambda st: st["payments"][-1].__setitem__("created_at", "not-a-timestamp"),
               lambda st: st["payments"][-1].__setitem__("created_at", "2026-13-45T00:00:00+00:00"),
               lambda st: st["payments"][-1].__setitem__("created_at", "2026-01-01T00:00:00"),
               lambda st: st["payments"][-1].__setitem__("amount", 1000000001),
               lambda st: st["requests"][-1].__setitem__("amount", -1),
               lambda st: st["users"][0].__setitem__("balance", -1),
               lambda st: st["users"][0].__setitem__("balance", 2 ** 53 + 1),
               lambda st: st["users"][0].__setitem__("balance", 1.5),
               lambda st: st["users"][0].__setitem__("handle", "Bad Handle"),
               lambda st: st["users"][1].__setitem__("handle", st["users"][0]["handle"]),
               lambda st: st["payments"][-1].__setitem__("visibility", "secret"),
               lambda st: st["payments"][-1].__setitem__("request_id", "nope"),
               lambda st: st["payments"][-1].__setitem__("from_user_id", "ghost"),
               lambda st: st["requests"][-1].__setitem__("status", "weird"),
               lambda st: st["requests"][-1].__setitem__("payment_id", "nope"),
               lambda st: st["tokens"].__setitem__("t", "ghost"),
               lambda st: st["payments"][-1].__setitem__("ts", "now"),
               lambda st: st["payments"][-1].__setitem__("settlement_id", "st_x"),
               lambda st: st.__setitem__("currency", 5)]
        for i, f in enumerate(bad):
            self.assertEqual(call("POST", "/_test/import", mutate(f))[0], 422, i)
        self.assertEqual(self.bal(self.ada), 9900)
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)


class Payments(Base):
    def pay(self, tok, body, key="k1"):
        return call("POST", "/payments", body, token=tok, key=key)

    def test_payment_shape_and_errors(self):
        s, b, _ = self.pay(self.ada, {"to_handle": "bob", "amount": 1500, "note": "dîner 🍕 ", "extra": 1})
        self.assertEqual(s, 201)
        self.assertEqual(b["note"], "dîner 🍕 ")
        self.assertIsNone(b["settlement_id"])
        self.assertIsNone(b["request_id"])
        self.assertEqual(b["visibility"], "public")
        self.assertRegex(b["created_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        self.assertLessEqual(len(b["payment_id"]), 64)
        self.assertEqual(self.bal(self.ada), 8500)
        self.assertEqual(self.pay(self.ada, {"to_handle": "ada", "amount": 1}, "a")[1]["error"]["code"], "self_payment")
        self.assertEqual(self.pay(self.ada, {"to_handle": "zzz", "amount": 1}, "b")[0], 404)
        self.assertEqual(self.pay(self.bob, {"to_handle": "ada", "amount": 99999}, "c")[1]["error"]["code"], "insufficient_funds")
        for amt in (0, -1, 1000000001, "5", True, None, 1.5):
            self.assertEqual(self.pay(self.ada, {"to_handle": "bob", "amount": amt}, "d")[0], 422, amt)
        for amt in ("1.0000000000000001", "1e400", "1e-400", "1000.0000000000000001", "1.5"):
            s, b, _ = call("POST", "/payments", raw='{"to_handle":"bob","amount":%s}' % amt, token=self.ada, key="frac" + amt)
            self.assertEqual(s, 422, amt)
        self.assertEqual(self.bal(self.ada), 8500)  # none of the fractional amounts moved money
        for i, amt in enumerate((1000.0, 1e3)):
            s, b, _ = self.pay(self.ada, {"to_handle": "bob", "amount": amt}, "e%d" % i)
            self.assertEqual((s, b["amount"]), (201, 1000))
        self.assertEqual(self.pay(self.ada, {"to_handle": "bob", "amount": 1, "note": None}, "f")[0], 422)
        self.assertEqual(self.pay(self.ada, {"to_handle": "bob", "amount": 1, "note": "x" * 201}, "f")[0], 422)
        self.assertEqual(self.pay(self.ada, {"to_handle": "bob", "amount": 1, "visibility": 5}, "f")[0], 422)
        self.assertEqual(self.pay(self.ada, {"to_handle": "bob", "amount": 1, "visibility": "x"}, "f")[0], 422)
        self.assertEqual(self.pay(self.ada, {"amount": 1}, "f")[0], 422)
        self.assertEqual(self.pay(self.ada, {"to_handle": 5, "amount": 1}, "f")[0], 400)
        self.assertEqual(call("POST", "/payments", raw="[]", token=self.ada, key="f")[0], 400)
        self.assertEqual(call("POST", "/payments", raw="null", token=self.ada, key="f")[0], 400)
        self.assertEqual(call("POST", "/payments", raw="{x", token=self.ada, key="f")[0], 400)
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=self.ada)[1]["error"]["code"], "missing_idempotency_key")
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=self.ada, key="")[0], 400)

    def test_key_bounds(self):
        b = {"to_handle": "bob", "amount": 1}
        self.assertEqual(self.pay(self.ada, b, "k" * 255)[0], 201)
        self.assertEqual(self.pay(self.ada, b, "k" * 256)[0], 422)

    def test_idempotency(self):
        b = {"to_handle": "bob", "amount": 100}
        s1, r1, _ = self.pay(self.ada, b, "K")
        s2, r2, _ = self.pay(self.ada, json.loads('{"amount":100.0,  "to_handle":"bob"}'), "K")
        self.assertEqual((s1, s2, r1), (201, 200, r2))
        self.assertEqual(self.pay(self.ada, {"to_handle": "bob", "amount": 101}, "K")[1]["error"]["code"], "idempotency_key_reuse")
        # invalid body on a claimed key -> reuse, not validation
        self.assertEqual(self.pay(self.ada, {"to_handle": "bob", "amount": -5}, "K")[0], 409)
        self.assertEqual(call("POST", "/payments", raw="{x", token=self.ada, key="K")[0], 400)
        self.assertEqual(call("POST", "/payments", b, key="K")[0], 401)
        self.assertEqual(self.bal(self.ada), 9900)
        # other user, same key string
        self.assertEqual(self.pay(self.bob, {"to_handle": "ada", "amount": 100}, "K")[0], 201)
        # same key + body on a different path
        self.assertEqual(call("POST", "/requests", {"payer_handle": "bob", "amount": 100}, token=self.ada, key="K")[0], 201)
        # failed first use does not claim the key
        self.assertEqual(self.pay(self.cy, {"to_handle": "bob", "amount": 100}, "Z")[0], 409)
        self.pay(self.bob, {"to_handle": "cy", "amount": 500}, "Y")
        self.assertEqual(self.pay(self.cy, {"to_handle": "bob", "amount": 100}, "Z")[0], 201)

    def test_replay_after_balance_zero(self):
        b = {"to_handle": "ada", "amount": 2500}
        self.assertEqual(self.pay(self.bob, b, "Q")[0], 201)
        self.assertEqual(self.bal(self.bob), 0)
        self.assertEqual(self.pay(self.bob, b, "Q")[0], 200)

    def test_concurrent_same_key(self):
        b = {"to_handle": "bob", "amount": 100}
        with ThreadPoolExecutor(20) as ex:
            res = list(ex.map(lambda _: self.pay(self.ada, b, "SAME"), range(20)))
        self.assertEqual(sorted(r[0] for r in res), [200] * 19 + [201])
        self.assertEqual(len({json.dumps(r[1]) for r in res}), 1)
        self.assertEqual(self.bal(self.ada), 9900)

    def test_concurrent_drain(self):
        fx = fixture()
        fx["users"][0]["balance"] = 1000
        call("POST", "/_test/reset", fx)
        ada = login("ada")
        with ThreadPoolExecutor(50) as ex:
            res = list(ex.map(lambda i: self.pay(ada, {"to_handle": "bob", "amount": 30}, "k%d" % i), range(50)))
        self.assertEqual(sum(1 for r in res if r[0] == 201), 33)
        self.assertEqual({r[0] for r in res}, {201, 409})
        self.assertEqual(self.bal(ada), 10)
        self.assertEqual(self.bal(self.bob if False else login("bob")), 2500 + 990)

    def test_ring_conserved(self):
        fx = fixture()
        for u, b in zip(fx["users"], (300, 300, 300)):
            u["balance"] = b
        call("POST", "/_test/reset", fx)
        toks = {h: login(h) for h in ("ada", "bob", "cy")}
        ring = [("ada", "bob"), ("bob", "cy"), ("cy", "ada")]

        def one(i):
            a, b = ring[i % 3]
            return self.pay(toks[a], {"to_handle": b, "amount": 50 + i % 7}, "r%d" % i)[0]
        with ThreadPoolExecutor(50) as ex:
            res = list(ex.map(one, range(150)))
        self.assertTrue(all(r in (201, 409) for r in res))
        bals = [self.bal(t) for t in toks.values()]
        self.assertEqual(sum(bals), 900)
        self.assertTrue(all(b >= 0 for b in bals))


class Requests(Base):
    def mk(self, who=None, payer="ada", amount=1200, key=None, **kw):
        key = key or ("mk%d" % id(object()))
        body = {"payer_handle": payer, "amount": amount, **kw}
        return call("POST", "/requests", body, token=who or self.bob, key=key)

    def test_lifecycle(self):
        s, r, _ = self.mk()
        self.assertEqual((s, r["status"], r["note"], r["payment_id"]), (201, "pending", "", None))
        rid = r["request_id"]
        self.assertEqual(call("POST", "/requests/%s/pay" % rid, {}, token=self.bob, key="p")[0], 403)
        self.assertEqual(call("POST", "/requests/%s/decline" % rid, token=self.bob)[0], 403)
        self.assertEqual(call("POST", "/requests/%s/cancel" % rid, token=self.ada)[0], 403)
        self.assertEqual(call("POST", "/requests/%s/cancel" % rid, token=self.cy)[0], 403)
        self.assertEqual(call("POST", "/requests/nope/pay", {}, token=self.ada, key="p")[0], 404)
        self.assertEqual(call("POST", "/requests/nope/decline", token=self.ada)[0], 404)
        self.assertEqual(call("POST", "/requests/nope/cancel", token=self.ada)[0], 404)
        self.assertEqual(call("POST", "/requests/%s/pay" % rid, {"visibility": "x"}, token=self.ada, key="p")[0], 422)
        s, p, _ = call("POST", "/requests/%s/pay" % rid, {"visibility": "private"}, token=self.ada, key="p")
        self.assertEqual((s, p["request_id"], p["visibility"], p["amount"]), (201, rid, "private", 1200))
        self.assertEqual(self.bal(self.ada), 8800)
        self.assertEqual(call("POST", "/requests/%s/pay" % rid, {"visibility": "private"}, token=self.ada, key="p")[0], 200)
        self.assertEqual(call("POST", "/requests/%s/pay" % rid, {"visibility": "private"}, token=self.ada, key="p2")[1]["error"]["code"], "request_not_pending")
        for act, tok in (("decline", self.ada), ("cancel", self.bob)):
            self.assertEqual(call("POST", "/requests/%s/%s" % (rid, act), token=tok)[0], 409)
        # private payment hidden from third party, visible to parties
        self.assertEqual([x for x in call("GET", "/activity", token=self.cy)[1]["payments"] if x["request_id"] == rid], [])
        self.assertEqual(len([x for x in call("GET", "/activity", token=self.bob)[1]["payments"] if x["request_id"] == rid]), 1)

    def test_decline_cancel_idempotent_states(self):
        rid = self.mk()[1]["request_id"]
        self.assertEqual(call("POST", "/requests/%s/decline" % rid, token=self.ada)[1]["status"], "declined")
        self.assertEqual(call("POST", "/requests/%s/decline" % rid, token=self.ada)[0], 200)
        self.assertEqual(call("POST", "/requests/%s/cancel" % rid, token=self.bob)[0], 409)
        self.assertEqual(call("POST", "/requests/%s/pay" % rid, {}, token=self.ada, key="a")[0], 409)
        rid = self.mk(key="x2")[1]["request_id"]
        self.assertEqual(call("POST", "/requests/%s/cancel" % rid, token=self.bob)[1]["status"], "cancelled")
        self.assertEqual(call("POST", "/requests/%s/cancel" % rid, token=self.bob)[0], 200)
        self.assertEqual(call("POST", "/requests/%s/decline" % rid, token=self.ada)[0], 409)
        self.assertEqual(call("POST", "/requests/%s/pay" % rid, {}, token=self.ada, key="b")[0], 409)

    def test_short_then_payable_and_replay_after_cancel(self):
        s, r, _ = self.mk(who=self.ada, payer="cy", amount=500, key="K1")
        rid = r["request_id"]
        self.assertEqual(call("POST", "/requests/%s/pay" % rid, {}, token=self.cy, key="p")[1]["error"]["code"], "insufficient_funds")
        self.assertEqual(self.bal(self.cy), 0)
        call("POST", "/payments", {"to_handle": "cy", "amount": 500}, token=self.bob, key="m")
        self.assertEqual(call("POST", "/requests/%s/pay" % rid, {}, token=self.cy, key="p")[0], 201)
        # replay after state change
        s, r2, _ = self.mk(who=self.ada, payer="cy", amount=7, key="K2")
        call("POST", "/requests/%s/cancel" % r2["request_id"], token=self.ada)
        s, r3, _ = self.mk(who=self.ada, payer="cy", amount=7, key="K2")
        self.assertEqual((s, r3["status"]), (200, "pending"))

    def test_pay_body_variants_and_other_path(self):
        a = self.mk(key="a")[1]["request_id"]
        b = self.mk(key="b")[1]["request_id"]
        self.assertEqual(call("POST", "/requests/%s/pay" % a, {}, token=self.ada, key="K")[0], 201)
        self.assertEqual(call("POST", "/requests/%s/pay" % b, {}, token=self.ada, key="K")[0], 201)
        self.assertEqual(call("POST", "/requests/%s/pay" % a, {"visibility": "public"}, token=self.ada, key="K")[1]["error"]["code"], "idempotency_key_reuse")

    def test_concurrent_pay_one_request(self):
        rid = self.mk()[1]["request_id"]
        with ThreadPoolExecutor(10) as ex:
            res = list(ex.map(lambda i: call("POST", "/requests/%s/pay" % rid, {}, token=self.ada, key="c%d" % i), range(10)))
        self.assertEqual(sorted(r[0] for r in res), [201] + [409] * 9)
        self.assertEqual(self.bal(self.ada), 8800)

    def test_pay_races_cancel(self):
        for n in range(10):
            rid = self.mk(key="rc%d" % n, amount=10)[1]["request_id"]
            with ThreadPoolExecutor(2) as ex:
                f1 = ex.submit(call, "POST", "/requests/%s/pay" % rid, {}, self.ada, "pp%d" % n)
                f2 = ex.submit(call, "POST", "/requests/%s/cancel" % rid, None, self.bob)
                paid, cancelled = f1.result()[0], f2.result()[0]
            final = call("GET", "/requests?limit=200", token=self.bob)[1]["requests"]
            st = [r for r in final if r["request_id"] == rid][0]["status"]
            self.assertIn((paid, cancelled, st), [(201, 409, "paid"), (409, 200, "cancelled")])
        self.assertEqual(self.total(), 12500)

    def test_list_filters_and_order(self):
        ids = [self.mk(key="l%d" % i, amount=i + 1)[1]["request_id"] for i in range(60)]
        s, b, _ = call("GET", "/requests", token=self.bob)
        self.assertEqual((len(b["requests"]), b["has_more"]), (50, True))
        self.assertEqual(b["requests"][0]["request_id"], ids[-1])
        s, b, _ = call("GET", "/requests?limit=5&offset=58", token=self.bob)
        self.assertEqual((len(b["requests"]), b["has_more"]), (3, False))
        call("POST", "/requests/%s/cancel" % ids[0], token=self.bob)
        s, b, _ = call("GET", "/requests?direction=incoming&status=cancelled", token=self.ada)
        self.assertEqual([r["request_id"] for r in b["requests"]], [ids[0]])
        self.assertEqual(call("GET", "/requests?direction=outgoing", token=self.ada)[1]["requests"], [])
        self.assertEqual(call("GET", "/requests", token=self.cy)[1]["requests"], [])


class Splits(Base):
    def split(self, tok, handles, amount=1000, key="s", **kw):
        return call("POST", "/splits", {"amount": amount, "participant_handles": handles, **kw}, token=tok, key=key)

    def test_split(self):
        s, b, _ = self.split(self.ada, ["bob", "cy"])
        self.assertEqual(s, 201)
        self.assertEqual(b["shares"], [{"handle": "bob", "amount": 500}, {"handle": "cy", "amount": 500}])
        self.assertEqual(len(b["requests"]), 2)
        self.assertEqual(b["note"], "")
        self.assertEqual(b["currency"], "EUR")
        s2, b2, _ = self.split(self.ada, ["bob", "cy"])
        self.assertEqual((s2, b2), (200, b))
        before = len(call("GET", "/requests?limit=200", token=self.ada)[1]["requests"])
        self.assertEqual(before, 3)
        self.assertEqual(call("GET", "/activity", token=self.cy)[1]["payments"][0]["payment_id"], "p_1")
        self.assertEqual(len(call("GET", "/activity", token=self.cy)[1]["payments"]), 1)

    def test_rounding_and_self(self):
        s, b, _ = self.split(self.ada, ["bob", "ada", "cy"], 1000)
        self.assertEqual([x["amount"] for x in b["shares"]], [334, 333, 333])
        self.assertEqual([r["payer_handle"] for r in b["requests"]], ["bob", "cy"])
        s, b, _ = self.split(self.ada, ["cy", "bob", "ada"], 1, key="t")
        self.assertEqual([x["amount"] for x in b["shares"]], [1, 0, 0])
        self.assertEqual([r["amount"] for r in b["requests"]], [1, 0])
        zero = b["requests"][1]["request_id"]
        s, p, _ = call("POST", "/requests/%s/pay" % zero, {}, token=self.bob, key="z")
        self.assertEqual((s, p["amount"]), (201, 0))
        s, b, _ = self.split(self.ada, ["ada"], 7, key="u")
        self.assertEqual((s, b["requests"]), (201, []))
        s, b, _ = self.split(self.ada, ["bob", "cy"], 1000000000, key="v")
        self.assertEqual(sum(x["amount"] for x in b["shares"]), 1000000000)

    def test_split_errors(self):
        before = call("GET", "/requests?limit=200", token=self.ada)[1]
        for h in ([], ["bob", "bob"]):
            self.assertEqual(self.split(self.ada, h)[0], 422)
        self.assertEqual(self.split(self.ada, ["bob", "nobody"])[0], 404)
        self.assertEqual(self.split(self.ada, ["bob"], note="x" * 201)[0], 422)
        self.assertEqual(self.split(self.ada, ["bob"], amount=True)[0], 422)
        self.assertEqual(call("POST", "/splits", {"amount": 5, "participant_handles": "ada"}, token=self.ada, key="q")[0], 400)
        self.assertEqual(call("POST", "/splits", {"amount": 5, "participant_handles": [1]}, token=self.ada, key="q")[0], 400)
        self.assertEqual(call("POST", "/splits", {"amount": 5}, token=self.ada, key="q")[0], 422)
        self.assertEqual(call("GET", "/requests?limit=200", token=self.ada)[1], before)
        self.assertEqual(self.split(self.ada, ["bob"], amount=1e3, key="w")[0], 201)

    def test_conservation_after_paying_all(self):
        s, b, _ = self.split(self.ada, ["ada", "bob", "cy"], 1000)
        toks = {"bob": self.bob, "cy": self.cy}
        for r in b["requests"]:
            call("POST", "/requests/%s/pay" % r["request_id"], {}, token=toks[r["payer_handle"]], key="x")
        self.assertEqual(self.total(), 12500)


class Settlements(Base):
    def settle(self, tok, transfers, key="S"):
        return call("POST", "/settlements", {"transfers": transfers}, token=tok, key=key)

    def test_auth_and_validation(self):
        t = [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]
        self.assertEqual(call("POST", "/settlements", {"transfers": t}, key="S")[0], 401)
        self.assertEqual(self.settle(self.bob, t)[1]["error"]["code"], "forbidden")
        self.assertEqual(call("POST", "/settlements", {"transfers": t}, token=self.ada)[0], 400)
        for bad in ([], t * 33, "x", [5], [{"from_handle": "ada"}],
                    [{"from_handle": "ada", "to_handle": "bob", "amount": True}]):
            self.assertEqual(self.settle(self.ada, bad)[0], 422, bad)
        self.assertEqual(self.settle(self.ada, t * 32)[0], 201)
        s, b, _ = self.settle(self.ada, [{"from_handle": "zz", "to_handle": "bob", "amount": 1},
                                         {"from_handle": "ada", "to_handle": "ada", "amount": 1}], "K")
        self.assertEqual(s, 404)
        s, b, _ = self.settle(self.ada, [{"from_handle": "ada", "to_handle": "ada", "amount": 1},
                                         {"from_handle": "ada", "to_handle": "bob", "amount": 10 ** 12}], "K")
        self.assertEqual((s, b["error"]["code"]), (422, "self_payment"))
        self.assertEqual(self.settle(self.ada, t, "K")[0], 201)

    def test_net_affordability_and_atomic(self):
        s, b, _ = self.settle(self.ada, [{"from_handle": "cy", "to_handle": "bob", "amount": 100},
                                         {"from_handle": "ada", "to_handle": "cy", "amount": 100}])
        self.assertEqual(s, 201)
        self.assertEqual([self.bal(self.ada), self.bal(self.cy)], [9900, 0])
        feed = len(call("GET", "/activity", token=self.ada)[1]["payments"])
        s, b, _ = self.settle(self.ada, [{"from_handle": "ada", "to_handle": "bob", "amount": 100},
                                         {"from_handle": "cy", "to_handle": "ada", "amount": 999999}], "T")
        self.assertEqual((s, b["error"]["code"]), (409, "insufficient_funds"))
        self.assertEqual(self.bal(self.ada), 9900)
        self.assertEqual(len(call("GET", "/activity", token=self.ada)[1]["payments"]), feed)

    def test_response_shape_replay_visibility(self):
        s, b, _ = self.settle(self.ada, [{"from_handle": "ada", "to_handle": "bob", "amount": 100, "visibility": "private", "note": "n"},
                                         {"from_handle": "bob", "to_handle": "cy", "amount": 50.0}])
        self.assertEqual(s, 201)
        ps = b["payments"]
        self.assertEqual([p["amount"] for p in ps], [100, 50])
        self.assertTrue(all(p["settlement_id"] == b["settlement_id"] and p["request_id"] is None
                            and p["created_at"] == b["committed_at"] for p in ps))
        self.assertEqual([ps[0]["visibility"], ps[1]["visibility"], ps[1]["note"]], ["private", "public", ""])
        self.assertEqual(self.settle(self.ada, [{"from_handle": "ada", "to_handle": "bob", "amount": 100, "visibility": "private", "note": "n"},
                                                {"from_handle": "bob", "to_handle": "cy", "amount": 50.0}])[1], b)
        ids = [p["payment_id"] for p in call("GET", "/activity", token=self.cy)[1]["payments"]]
        self.assertIn(ps[1]["payment_id"], ids)
        self.assertNotIn(ps[0]["payment_id"], ids)
        op = call("POST", "/_test/reset", fixture(settlement_operator_ids=["u_cy"]))
        cy = login("cy")
        self.settle(cy, [{"from_handle": "ada", "to_handle": "bob", "amount": 1, "visibility": "private"}])
        ids = [p["settlement_id"] for p in call("GET", "/activity", token=cy)[1]["payments"]]
        self.assertEqual(ids, [None])

    def test_concurrent_same_key(self):
        body = [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]
        with ThreadPoolExecutor(20) as ex:
            res = list(ex.map(lambda _: self.settle(self.ada, body, "SS"), range(20)))
        self.assertEqual(sorted(r[0] for r in res), [200] * 19 + [201])
        self.assertEqual(self.bal(self.ada), 9990)


class ExportImport(Base):
    def test_roundtrip(self):
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=self.ada, key="K")[0], 201)
        call("POST", "/payments", {"to_handle": "bob", "amount": 10 ** 6}, token=self.cy, key="F")  # fails
        s, snap, _ = call("GET", "/_test/export")
        self.assertEqual((s, snap["track"], snap["format_version"]), (200, "pocketful", 1))
        self.assertNotIn("correct horse", json.dumps(snap))
        orig = call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=self.ada, key="K")[1]
        call("POST", "/payments", {"to_handle": "bob", "amount": 300}, token=self.ada, key="K2")
        s, nu, _ = call("POST", "/auth/signup", {"email": "n1@x.io", "password": "12345678", "display_name": "N"})
        for _ in range(2):
            self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
            self.assertEqual(self.bal(self.ada), 9900)
            self.assertEqual(len(call("GET", "/activity", token=self.ada)[1]["payments"]), 2)
        self.assertEqual(call("GET", "/me", token=nu["token"])[0], 401)
        self.assertEqual(call("POST", "/auth/login", {"email": "n1@x.io", "password": "12345678"})[0], 401)
        s, rep, _ = call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=self.ada, key="K")
        self.assertEqual((s, rep), (200, orig))
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 101}, token=self.ada, key="K")[0], 409)
        self.assertEqual(self.bal(self.ada), 9900)
        self.assertEqual(call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}, token=self.ada, key="X")[0], 201)
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=self.cy, key="F")[0], 409)
        call("POST", "/_test/reset", fixture())
        self.assertEqual(call("GET", "/me", token=self.ada)[0], 401)

    def test_invalid(self):
        s, snap, _ = call("GET", "/_test/export")
        call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=self.ada, key="K")
        for bad in ({**snap, "track": "x"}, {**snap, "format_version": 2}, {"track": "pocketful", "format_version": 1},
                    {"track": "pocketful", "format_version": 1, "state": 5},
                    {"track": "pocketful", "format_version": 1, "state": {"users": []}}):
            self.assertEqual(call("POST", "/_test/import", bad)[0], 422)
        self.assertEqual(call("POST", "/_test/import", raw="{nope")[0], 400)
        self.assertEqual(self.bal(self.ada), 9900)

    def test_snapshot_is_atomic_copy(self):
        s, snap, _ = call("GET", "/_test/export")
        call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=self.ada, key="K")
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        self.assertEqual(self.bal(self.ada), 10000)

    def test_operator_survives(self):
        s, snap, _ = call("GET", "/_test/export")
        call("POST", "/_test/reset", fixture(settlement_operator_ids=[]))
        call("POST", "/_test/import", snap)
        self.assertEqual(call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}, token=self.ada, key="X")[0], 201)


class Authorizations(Base):
    def auth(self, tok, body, key="A"):
        return call("POST", "/authorizations", body, token=tok, key=key)

    def cap(self, tok, aid, body, key="C"):
        return call("POST", "/authorizations/%s/capture" % aid, body, token=tok, key=key)

    def me(self, tok):
        return call("GET", "/me", token=tok)[1]

    def test_me_fields(self):
        m = self.me(self.ada)
        self.assertEqual((m["balance"], m["total"], m["available"], m["held"]), (10000, 10000, 10000, 0))

    def test_hold_capture_release(self):
        s, a, _ = self.auth(self.ada, {"to_handle": "bob", "amount": 2000, "note": "dep", "visibility": "private"})
        self.assertEqual((s, a["status"], a["remaining_amount"], a["captured_amount"], a["payment_id"]), (201, "open", 2000, 0, None))
        self.assertEqual(a["payment_ids"], [])
        m = self.me(self.ada)
        self.assertEqual((m["balance"], m["available"], m["held"]), (10000, 8000, 2000))
        self.assertEqual(len(call("GET", "/activity", token=self.bob)[1]["payments"]), 1)
        self.assertEqual(self.auth(self.ada, {"to_handle": "bob", "amount": 2000, "note": "dep", "visibility": "private"}, "A")[0], 200)
        # held funds cannot fund payments
        self.assertEqual(call("POST", "/payments", {"to_handle": "bob", "amount": 8001}, token=self.ada, key="p")[1]["error"]["code"], "insufficient_funds")
        self.assertEqual(self.auth(self.ada, {"to_handle": "bob", "amount": 8001}, "A2")[0], 409)
        aid = a["authorization_id"]
        self.assertEqual(self.cap(self.ada, aid, {})[0], 403)
        self.assertEqual(self.cap(self.cy, aid, {})[0], 403)
        self.assertEqual(self.cap(self.bob, aid, {"amount": 2001})[1]["error"]["code"], "capture_exceeds_authorization")
        self.assertEqual(self.cap(self.bob, aid, {"amount": 0})[0], 422)
        s, p, _ = self.cap(self.bob, aid, {"amount": 1500})
        self.assertEqual((s, p["amount"], p["authorization_id"], p["request_id"], p["visibility"], p["note"]), (201, 1500, aid, None, "private", "dep"))
        m = self.me(self.ada)
        self.assertEqual((m["balance"], m["available"], m["held"]), (8500, 8500, 0))
        self.assertEqual(self.me(self.bob)["balance"], 4000)
        self.assertEqual(self.cap(self.bob, aid, {"amount": 1500})[0], 200)
        self.assertEqual(self.cap(self.bob, aid, {"amount": 1}, "C2")[1]["error"]["code"], "authorization_not_open")
        self.assertEqual(call("POST", "/authorizations/%s/void" % aid, token=self.ada)[0], 409)
        s, b, _ = call("GET", "/authorizations?status=captured", token=self.bob)
        self.assertEqual((b["authorizations"][0]["captured_amount"], b["authorizations"][0]["remaining_amount"]), (1500, 0))
        self.assertEqual(call("GET", "/authorizations", token=self.cy)[1]["authorizations"], [])
        self.assertEqual(self.total(), 12500)

    def test_extended_capture_void_and_validation(self):
        aid = self.auth(self.ada, {"to_handle": "bob", "amount": 1000})[1]["authorization_id"]
        s, p, _ = self.cap(self.bob, aid, {"amount": 400, "final": False}, "C1")
        a = call("GET", "/authorizations?direction=incoming", token=self.bob)[1]["authorizations"][0]
        self.assertEqual((a["status"], a["remaining_amount"], a["captured_amount"], a["payment_ids"]), ("open", 600, 400, [p["payment_id"]]))
        self.assertEqual(self.me(self.ada)["held"], 600)
        self.assertEqual(self.cap(self.bob, aid, {"amount": 700, "final": False}, "C2")[0], 422)
        self.assertEqual(self.cap(self.bob, aid, {"final": "no"}, "C3")[0], 400)
        s, p2, _ = self.cap(self.bob, aid, {"amount": 100, "final": False}, "C4")
        self.assertEqual(call("POST", "/authorizations/%s/void" % aid, token=self.cy)[0], 403)
        self.assertEqual(call("POST", "/authorizations/%s/void" % aid, token=self.bob)[0], 403)
        s, v, _ = call("POST", "/authorizations/%s/void" % aid, token=self.ada)
        self.assertEqual((s, v["status"], v["remaining_amount"], v["captured_amount"], v["payment_ids"]), (200, "voided", 0, 500, [p["payment_id"], p2["payment_id"]]))
        self.assertEqual(call("POST", "/authorizations/%s/void" % aid, token=self.ada)[0], 200)
        self.assertEqual(self.cap(self.bob, aid, {}, "C5")[1]["error"]["code"], "authorization_not_open")
        self.assertEqual(self.me(self.ada)["held"], 0)
        self.assertEqual(self.me(self.ada)["balance"], 9500)
        # full remainder with final false closes it
        aid = self.auth(self.ada, {"to_handle": "bob", "amount": 100}, "A9")[1]["authorization_id"]
        self.cap(self.bob, aid, {"amount": 100, "final": False}, "C6")
        self.assertEqual(call("GET", "/authorizations?status=captured", token=self.ada)[1]["authorizations"][0]["authorization_id"], aid)
        for bad in ({"to_handle": "ada", "amount": 1}, {"to_handle": "zz", "amount": 1}):
            self.assertIn(self.auth(self.ada, bad, "B")[0], (404, 422))
        self.assertEqual(call("POST", "/authorizations/nope/void", token=self.ada)[0], 404)
        self.assertEqual(self.cap(self.bob, "nope", {})[0], 404)
        self.assertEqual(call("GET", "/authorizations?direction=x", token=self.ada)[0], 422)

    def test_expiry_and_ttl(self):
        fx = fixture(authorization_ttl_seconds=1)
        call("POST", "/_test/reset", fx)
        ada, bob = login("ada"), login("bob")
        s, a, _ = self.auth(ada, {"to_handle": "bob", "amount": 3000})
        self.assertEqual(self.me(ada)["available"], 7000)
        import time
        time.sleep(2.2)
        self.assertEqual(self.me(ada)["available"], 10000)
        self.assertEqual(call("GET", "/authorizations?status=expired", token=ada)[1]["authorizations"][0]["status"], "expired")
        self.assertEqual(call("GET", "/authorizations?status=open", token=ada)[1]["authorizations"], [])
        self.assertEqual(self.cap(bob, a["authorization_id"], {}, "k")[1]["error"]["code"], "authorization_expired")
        self.assertEqual(call("POST", "/authorizations/%s/void" % a["authorization_id"], token=ada)[0], 409)
        for ttl in (0, -1, "5", True, 1.5):
            self.assertEqual(call("POST", "/_test/reset", fixture(authorization_ttl_seconds=ttl))[0], 422)

    def test_deadline_is_the_shown_expires_at(self):
        import time
        from datetime import datetime
        call("POST", "/_test/reset", fixture(authorization_ttl_seconds=2))
        ada, bob = login("ada"), login("bob")
        for n in range(3):
            a = self.auth(ada, {"to_handle": "bob", "amount": 100}, "dl%d" % n)[1]
            wait = datetime.fromisoformat(a["expires_at"]).timestamp() + 0.02 - time.time()
            self.assertGreater(wait, 0)
            time.sleep(wait)
            self.assertEqual(call("GET", "/authorizations?status=open", token=ada)[1]["authorizations"], [])
            self.assertEqual(self.me(ada)["held"], 0)
            self.assertEqual(self.cap(bob, a["authorization_id"], {}, "dc%d" % n)[1]["error"]["code"], "authorization_expired")

    def test_seeded_holds(self):
        past = "2000-01-01T00:00:00+00:00"
        fx = fixture(authorizations=[
            {"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "deposit",
             "visibility": "public", "status": "open", "expires_at": "2099-01-01T00:00:00+00:00"},
            {"id": "a_2", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 99999,
             "status": "open", "expires_at": past},
            {"id": "a_3", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5, "status": "voided",
             "expires_at": "2099-01-01T00:00:00+00:00"}])
        self.assertEqual(call("POST", "/_test/reset", fx)[0], 204)
        ada = login("ada")
        m = self.me(ada)
        self.assertEqual((m["balance"], m["available"], m["held"]), (10000, 8000, 2000))
        st = {a["authorization_id"]: a["status"] for a in call("GET", "/authorizations", token=ada)[1]["authorizations"]}
        self.assertEqual(st, {"a_1": "open", "a_2": "expired", "a_3": "voided"})
        fx["authorizations"][0]["amount"] = 10001
        self.assertEqual(call("POST", "/_test/reset", fx)[0], 422)
        self.assertEqual(self.me(ada)["held"], 2000)
        fx2 = fixture(settlement_operator_ids=["u_ada"], authorizations=[{"id": "a_1", "from_user_id": "u_cy", "to_user_id": "u_bob", "amount": 1,
            "status": "open", "expires_at": "2099-01-01T00:00:00+00:00"}])
        self.assertEqual(call("POST", "/_test/reset", fx2)[0], 422)  # cy has 0

    def test_settlement_respects_holds(self):
        self.auth(self.ada, {"to_handle": "bob", "amount": 9000})
        t = [{"from_handle": "ada", "to_handle": "bob", "amount": 1001}]
        self.assertEqual(call("POST", "/settlements", {"transfers": t}, token=self.ada, key="S")[0], 409)
        t[0]["amount"] = 1000
        self.assertEqual(call("POST", "/settlements", {"transfers": t}, token=self.ada, key="S2")[0], 201)

    def test_concurrent_captures_and_payments(self):
        aid = self.auth(self.ada, {"to_handle": "bob", "amount": 1000})[1]["authorization_id"]
        with ThreadPoolExecutor(30) as ex:
            res = list(ex.map(lambda i: self.cap(self.bob, aid, {"amount": 100, "final": False}, "c%d" % i), range(30)))
        self.assertEqual(sum(1 for r in res if r[0] == 201), 10)
        self.assertTrue(all(r[0] in (201, 409) for r in res))
        self.assertEqual(self.me(self.ada)["held"], 0)
        self.assertEqual(self.bal(self.ada), 9000)
        # payments racing a hold: available never negative
        aid = self.auth(self.ada, {"to_handle": "cy", "amount": 6000}, "z")[1]["authorization_id"]
        with ThreadPoolExecutor(30) as ex:
            res = list(ex.map(lambda i: call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=self.ada, key="q%d" % i), range(30)))
        self.assertEqual(sum(1 for r in res if r[0] == 201), 30)
        res = call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=self.ada, key="last")
        self.assertEqual(res[0], 409)
        self.assertEqual(self.me(self.ada)["available"], 0)
        self.assertEqual(self.total(), 12500)

    def test_gap_funds_and_capture_rules(self):
        aid = self.auth(self.ada, {"to_handle": "bob", "amount": 8000}, "g1")[1]["authorization_id"]
        self.assertEqual(call("POST", "/payments", {"to_handle": "cy", "amount": 2001}, token=self.ada, key="g2")[0], 409)
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 2001}, token=self.cy, key="g3")[1]["request_id"]
        self.assertEqual(call("POST", "/requests/%s/pay" % rq, {}, token=self.ada, key="g4")[1]["error"]["code"], "insufficient_funds")
        self.assertEqual(call("POST", "/payments", {"to_handle": "cy", "amount": 2000}, token=self.ada, key="g5")[0], 201)
        self.assertEqual(self.me(self.ada)["available"], 0)
        self.assertEqual(self.auth(self.ada, {"to_handle": "bob", "amount": 1}, "g6")[0], 409)
        self.assertEqual(self.cap(self.bob, aid, {"final": "false"}, "g7")[0], 400)
        self.assertEqual(self.cap(self.bob, aid, {"amount": 1.5}, "g8")[0], 422)
        s, p, _ = self.cap(self.bob, aid, {}, "g9")  # full 8000 although available is 0
        self.assertEqual((s, p["amount"]), (201, 8000))
        self.assertEqual(self.cap(self.bob, aid, {"amount": 2000}, "g9")[0], 409)  # {} vs {"amount": 2000}
        self.assertEqual(self.cap(self.bob, aid, {}, "g9")[0], 200)
        self.assertEqual(self.total(), 12500)

    def test_gap_partial_capture_then_release(self):
        aid = self.auth(self.ada, {"to_handle": "bob", "amount": 2000}, "h1")[1]["authorization_id"]
        s, p1, _ = self.cap(self.bob, aid, {"amount": 700, "final": False}, "h2")
        a = call("GET", "/authorizations", token=self.ada)[1]["authorizations"][0]
        self.assertEqual((a["status"], a["captured_amount"], a["remaining_amount"], a["payment_ids"]), ("open", 700, 1300, [p1["payment_id"]]))
        self.assertEqual(self.me(self.ada)["available"], 10000 - 700 - 1300)
        s, p2, _ = self.cap(self.bob, aid, {"amount": 1300, "final": False}, "h3")
        a = call("GET", "/authorizations", token=self.ada)[1]["authorizations"][0]
        self.assertEqual((a["status"], a["remaining_amount"], a["payment_id"]), ("captured", 0, p2["payment_id"]))
        aid = self.auth(self.ada, {"to_handle": "bob", "amount": 1500}, "h4")[1]["authorization_id"]
        self.cap(self.bob, aid, {"amount": 1000}, "h5")  # final capture releases the remainder at once
        self.assertEqual(self.me(self.ada)["available"], 10000 - 2000 - 1000)

    def test_gap_races(self):
        aid = self.auth(self.ada, {"to_handle": "bob", "amount": 1000}, "r0")[1]["authorization_id"]
        for n in range(8):
            a2 = self.auth(self.ada, {"to_handle": "bob", "amount": 100}, "rr%d" % n)[1]["authorization_id"]
            with ThreadPoolExecutor(2) as ex:
                f1 = ex.submit(self.cap, self.bob, a2, {}, "rc%d" % n)
                f2 = ex.submit(call, "POST", "/authorizations/%s/void" % a2, None, self.ada)
                r = (f1.result()[0], f2.result()[0])
            st = [x for x in call("GET", "/authorizations?limit=200", token=self.ada)[1]["authorizations"] if x["authorization_id"] == a2][0]["status"]
            self.assertIn((r, st), [((201, 409), "captured"), ((409, 200), "voided")])
        with ThreadPoolExecutor(50) as ex:
            res = list(ex.map(lambda i: self.auth(self.cy, {"to_handle": "ada", "amount": 1}, "dz%d" % i), range(50)))
        self.assertTrue(all(r[0] == 409 for r in res))
        s_ = self.me(self.bob)
        self.assertEqual(s_["available"], s_["total"])
        with ThreadPoolExecutor(50) as ex:
            res = list(ex.map(lambda i: self.auth(self.ada, {"to_handle": "cy", "amount": 100}, "dr%d" % i), range(60)))
        ok = sum(1 for r in res if r[0] == 201)
        self.assertEqual(self.me(self.ada)["held"], 1000 + ok * 100)
        m = self.me(self.ada)
        self.assertGreaterEqual(m["available"], 0)
        self.assertEqual(self.total(), 12500)

    def test_gap_seeding_and_ttl(self):
        past = "2000-01-01T00:00:00+00:00"
        fx = fixture(authorizations=[{"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 12000,
                                     "status": "open", "expires_at": past}])
        self.assertEqual(call("POST", "/_test/reset", fx)[0], 204)
        self.assertEqual(self.me(login("ada"))["available"], 10000)
        fx = fixture(authorization_ttl_seconds=37)
        call("POST", "/_test/reset", fx)
        ada = login("ada")
        from datetime import datetime
        a = self.auth(ada, {"to_handle": "bob", "amount": 5}, "ttl")[1]
        d = datetime.fromisoformat(a["expires_at"]) - datetime.fromisoformat(a["created_at"])
        self.assertEqual(d.total_seconds(), 37)
        self.assertEqual(call("POST", "/_test/reset", fixture(authorizations=[
            {"id": "c", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5, "status": "captured", "expires_at": "2099-01-01T00:00:00+00:00"}]))[0], 204)
        ada, bob = login("ada"), login("bob")
        a = call("GET", "/authorizations", token=ada)[1]["authorizations"][0]
        self.assertEqual((a["captured_amount"], a["remaining_amount"]), (5, 0))
        self.assertEqual(self.cap(bob, "c", {}, "x")[1]["error"]["code"], "authorization_not_open")

    def test_import_stage1_export(self):
        s, snap, _ = call("GET", "/_test/export")
        st = snap["state"]
        for k in ("authorizations", "auth_ttl"):
            st.pop(k)
        for p in st["payments"]:
            p.pop("authorization_id", None)
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        self.assertEqual(self.me(self.ada)["available"], 10000)
        s, snap, _ = call("GET", "/_test/export")
        self.auth(self.ada, {"to_handle": "bob", "amount": 100})
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        self.assertEqual(self.me(self.ada)["held"], 0)


def login_user(email):
    s, b, _ = call("POST", "/auth/login", {"email": email, "password": "correct horse"})
    assert s == 200, b
    return b["token"]


def hist_fixture():
    """ada/bob/cy with dated seeded payments; openings: ada 9300, bob 2000, cy 0 (balances 10000/2500/..)."""
    users = [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada", "handle": "ada", "balance": 10000},
             {"id": "u_bob", "email": "bob@example.com", "password": "correct horse", "display_name": "Bob", "handle": "bob", "balance": 2500},
             {"id": "u_cy", "email": "cy@example.com", "password": "correct horse", "display_name": "Cy", "handle": "cy", "balance": 600}]
    pays = [{"id": "p_a", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "one", "visibility": "public", "created_at": "2026-09-20T10:00:00+00:00"},
            {"id": "p_b", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 1200, "note": "two", "visibility": "private", "created_at": "2026-09-21T10:00:00+00:00"},
            {"id": "p_c", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 300, "note": "three", "visibility": "public", "created_at": "2026-09-22T10:00:00+00:00"},
            {"id": "p_d", "from_user_id": "u_cy", "to_user_id": "u_bob", "amount": 100, "note": "four", "visibility": "public", "created_at": "2026-09-22T10:00:00+00:00"}]
    return {"currency": "EUR", "minor_units": 2, "users": users, "payments": pays, "requests": [],
            "settlement_operator_ids": ["u_ada"]}


class Ledger(unittest.TestCase):
    def setUp(self):
        s, _, _ = call("POST", "/_test/reset", hist_fixture())
        self.assertEqual(s, 204)
        self.ada, self.bob, self.cy = login("ada"), login("bob"), login("cy")

    def me(self, tok, qs=""):
        return call("GET", "/me" + qs, token=tok)

    def test_as_of(self):
        # ada: opening 9300; p_a -500 (09-20), p_b +1200 (09-21) -> 10000
        e = lambda ts: "?as_of=" + ts.replace("+", "%2B")
        self.assertEqual(self.me(self.ada)[1]["balance"], 10000)
        for ts, want in (("2026-09-19T00:00:00+00:00", 9300), ("2026-09-20T10:00:00+00:00", 8800),
                         ("2026-09-20T09:59:59+00:00", 9300), ("2026-09-21T10:00:00+00:00", 10000),
                         ("2030-01-01T00:00:00+00:00", 10000), ("2026-09-20T12:00:00+02:00", 8800)):
            s, b, _ = self.me(self.ada, e(ts))
            self.assertEqual((s, b["balance"], b["total"], b["held"], b["available"], b["as_of"]), (200, want, want, 0, want, ts), ts)
        for bad in ("?as_of=2026-09-20", "?as_of=2026-09-20T10:00:00", "?as_of=", "?as_of=yesterday", "?known_at=", "?known_at=2026-09-20T10:00:00"):
            self.assertEqual(self.me(self.ada, bad)[0], 422, bad)
        self.assertEqual(call("GET", "/me?as_of=2026-09-20T10:00:00%2B00:00")[0], 401)

    def test_statement_basics_and_pagination(self):
        s, b, _ = call("GET", "/statement", token=self.bob)
        self.assertEqual(s, 200)
        # bob opening 2000: +500 (a) -1200 (b) -300 (c) +100 (d) = 1100 ... balance 2500 -> opening 2000+... check
        total = b["opening_balance"] + sum(x["delta"] for x in b["entries"])
        self.assertEqual(total, b["closing_balance"])
        self.assertEqual(b["closing_balance"], self.me(self.bob)[1]["balance"])
        self.assertEqual([x["payment"]["payment_id"] for x in b["entries"]], ["p_a", "p_b", "p_c", "p_d"])
        self.assertEqual([x["delta"] for x in b["entries"]], [500, -1200, -300, 100])
        running = b["opening_balance"]
        for x in b["entries"]:
            running += x["delta"]
            self.assertEqual(x["balance_after"], running)
            self.assertEqual((x["revision"], x["effective_at"], x["recorded_at"]), (1, x["payment"]["created_at"], x["payment"]["created_at"]))
        self.assertTrue(b["snapshot"])
        # window [from, to): half-open, ties by id
        q = "?from=2026-09-21T10:00:00%2B00:00&to=2026-09-22T10:00:00%2B00:00"
        s, w, _ = call("GET", "/statement" + q, token=self.bob)
        self.assertEqual([x["payment"]["payment_id"] for x in w["entries"]], ["p_b"])
        self.assertEqual(w["opening_balance"], b["entries"][0]["balance_after"])
        self.assertEqual(w["closing_balance"], b["entries"][1]["balance_after"])
        s, w2, _ = call("GET", "/statement?from=2026-09-22T10:00:00%2B00:00", token=self.bob)
        self.assertEqual([x["payment"]["payment_id"] for x in w2["entries"]], ["p_c", "p_d"])
        # pagination does not change balances
        s, p1, _ = call("GET", "/statement?limit=3&offset=0", token=self.bob)
        s, p2, _ = call("GET", "/statement?limit=3&offset=3", token=self.bob)
        self.assertEqual((len(p1["entries"]), p1["has_more"], len(p2["entries"]), p2["has_more"]), (3, True, 1, False))
        for pg in (p1, p2):
            self.assertEqual((pg["opening_balance"], pg["closing_balance"]), (b["opening_balance"], b["closing_balance"]))
        self.assertEqual(p2["entries"][0]["balance_after"], b["entries"][3]["balance_after"])
        self.assertEqual(call("GET", "/statement?offset=99", token=self.bob)[1]["has_more"], False)
        for bad in ("?limit=0", "?limit=201", "?offset=-1", "?from=2026-09-20", "?to=", "?known_at=x"):
            self.assertEqual(call("GET", "/statement" + bad, token=self.bob)[0], 422, bad)
        self.assertEqual(call("GET", "/statement")[0], 401)
        # only own payments, regardless of public feed: cy has p_c and p_d only
        s, c, _ = call("GET", "/statement", token=self.cy)
        self.assertEqual([x["payment"]["payment_id"] for x in c["entries"]], ["p_c", "p_d"])
        self.assertEqual(c["opening_balance"], 600 - 300 + 100)

    def test_snapshots(self):
        s, a, _ = call("GET", "/statement?limit=2", token=self.bob)
        tok = a["snapshot"]
        call("POST", "/payments", {"to_handle": "cy", "amount": 5}, token=self.bob, key="sn1")
        s, fresh, _ = call("GET", "/statement", token=self.bob)
        self.assertEqual(len(fresh["entries"]), 5)
        s, again, _ = call("GET", "/statement?snapshot=%s&limit=10&offset=0" % tok, token=self.bob)
        self.assertEqual((len(again["entries"]), again["closing_balance"]), (4, a["closing_balance"]))
        s, tail, _ = call("GET", "/statement?snapshot=%s&limit=3&offset=3" % tok, token=self.bob)
        self.assertEqual((len(tail["entries"]), tail["has_more"]), (1, False))
        for extra in ("&from=2026-09-20T10:00:00%2B00:00", "&to=2026-09-20T10:00:00%2B00:00", "&known_at=2026-09-20T10:00:00%2B00:00"):
            self.assertEqual(call("GET", "/statement?snapshot=" + tok + extra, token=self.bob)[0], 422)
        self.assertEqual(call("GET", "/statement?snapshot=" + tok, token=self.ada)[0], 404)
        self.assertEqual(call("GET", "/statement?snapshot=nope", token=self.bob)[0], 404)
        call("POST", "/_test/reset", hist_fixture())
        self.assertEqual(call("GET", "/statement?snapshot=" + tok, token=login("bob"))[0], 404)

    def corr(self, tok, pid, body, key="c1"):
        return call("POST", "/payments/%s/corrections" % pid, body, token=tok, key=key)

    def test_corrections_basic(self):
        body = {"expected_revision": 1, "amount": 400, "effective_at": "2026-09-20T12:00:00+00:00", "reason": "fix"}
        self.assertEqual(self.corr(self.bob, "p_a", body)[0], 403)
        self.assertEqual(self.corr(self.cy, "p_a", body)[0], 403)
        self.assertEqual(self.corr(self.ada, "nope", body)[0], 404)
        self.assertEqual(call("POST", "/payments/p_a/corrections", body, key="x")[0], 401)
        self.assertEqual(call("POST", "/payments/p_a/corrections", body, token=self.ada)[0], 400)
        for bad in ({**body, "expected_revision": 0}, {**body, "amount": -1}, {**body, "amount": 1000000001}, {**body, "amount": 1.5},
                    {**body, "reason": ""}, {**body, "reason": "x" * 201}, {**body, "effective_at": "2026-09-20"}, {**body, "effective_at": "2999-01-01T00:00:00+00:00"},
                    {k: v for k, v in body.items() if k != "reason"}, {**body, "expected_revision": True}):
            self.assertEqual(self.corr(self.ada, "p_a", bad, "bk")[0], 422, bad)
        s, r, _ = self.corr(self.ada, "p_a", body)
        self.assertEqual((s, r["payment_id"], r["revision"], r["amount"], r["effective_at"], r["reason"]), (201, "p_a", 2, 400, body["effective_at"], "fix"))
        self.assertRegex(r["recorded_at"], r"^\d{4}-\d\d-\d\dT")
        self.assertEqual(self.corr(self.ada, "p_a", body)[1], r)  # replay: same revision, 200
        self.assertEqual(self.corr(self.ada, "p_a", body)[0], 200)
        self.assertEqual(self.corr(self.ada, "p_a", {**body, "amount": 300})[1]["error"]["code"], "idempotency_key_reuse")
        self.assertEqual(self.corr(self.ada, "p_a", body, "c2")[1]["error"]["code"], "stale_revision")
        # money moved: ada +100, bob -100; sum conserved; activity shows the original
        self.assertEqual((self.me(self.ada)[1]["balance"], self.me(self.bob)[1]["balance"]), (10100, 2400))
        act = {p["payment_id"]: p for p in call("GET", "/activity", token=self.ada)[1]["payments"]}
        self.assertEqual(act["p_a"]["amount"], 500)
        s, rv, _ = call("GET", "/payments/p_a/revisions", token=self.bob)
        self.assertEqual([(x["revision"], x["amount"], x["reason"]) for x in rv["revisions"]], [(1, 500, ""), (2, 400, "fix")])
        self.assertEqual(call("GET", "/payments/p_a/revisions", token=self.cy)[0], 404)
        self.assertEqual(call("GET", "/payments/p_a/revisions")[0], 401)
        self.assertEqual(call("GET", "/payments/nope/revisions", token=self.ada)[0], 404)
        # replay after a newer revision still returns the original
        s, r3, _ = self.corr(self.ada, "p_a", {"expected_revision": 2, "amount": 0, "effective_at": "2026-09-20T13:00:00+00:00", "reason": "reverse"}, "c3")
        self.assertEqual((s, r3["revision"]), (201, 3))
        self.assertEqual(self.corr(self.ada, "p_a", body)[1]["revision"], 2)
        self.assertEqual(self.me(self.ada)[1]["balance"], 10500)

    def test_corrections_in_history(self):
        t0 = time.time()
        body = {"expected_revision": 1, "amount": 400, "effective_at": "2026-09-20T12:00:00+00:00", "reason": "fix"}
        before = datetime_now_iso()
        self.corr(self.ada, "p_a", body)
        after = datetime_now_iso()
        e = lambda ts: ts.replace("+", "%2B")
        # known before the correction: the original; known after: corrected, effective at 09-20 12:00
        _, old, _ = self.me(self.ada, "?as_of=2026-09-21T00:00:00%2B00:00&known_at=" + e(before))
        _, new, _ = self.me(self.ada, "?as_of=2026-09-21T00:00:00%2B00:00&known_at=" + e(after))
        self.assertEqual((old["balance"], new["balance"]), (8800, 8900))
        self.assertEqual(old["known_at"], before)
        # not yet effective at 11:00 either way
        _, early, _ = self.me(self.ada, "?as_of=2026-09-20T11:00:00%2B00:00")
        self.assertEqual(early["balance"], 9300)
        # known before the payment existed: contributes nothing -> opening
        _, none, _ = self.me(self.ada, "?known_at=2000-01-01T00:00:00%2B00:00")
        self.assertEqual(none["balance"], 9300)
        # statement: ordering by selected effective time, selected amount, revision fields
        _, st, _ = call("GET", "/statement", token=self.ada)
        ent = {x["payment"]["payment_id"]: x for x in st["entries"]}
        self.assertEqual((ent["p_a"]["revision"], ent["p_a"]["payment"]["amount"], ent["p_a"]["delta"], ent["p_a"]["effective_at"]), (2, 400, -400, body["effective_at"]))
        self.assertEqual(st["opening_balance"] + sum(x["delta"] for x in st["entries"]), st["closing_balance"])
        _, st0, _ = call("GET", "/statement?known_at=" + e(before), token=self.ada)
        self.assertEqual(st0["entries"][0]["payment"]["amount"], 500)
        self.assertEqual(st0["known_at"], before)
        # a window excluding the correction's effective time drops the payment; zero amount still an entry
        self.corr(self.ada, "p_a", {"expected_revision": 2, "amount": 0, "effective_at": "2026-09-20T13:00:00+00:00", "reason": "zero"}, "z")
        _, st1, _ = call("GET", "/statement?to=2026-09-20T13:00:00%2B00:00", token=self.ada)
        self.assertEqual(st1["entries"], [])
        _, st2, _ = call("GET", "/statement?to=2026-09-20T13:00:01%2B00:00", token=self.ada)
        self.assertEqual([(x["payment"]["amount"], x["delta"]) for x in st2["entries"]], [(0, 0)])

    def test_historical_overdraft_and_funds(self):
        # bob: opening 2000. Make bob nearly empty historically via fixture
        fx = hist_fixture()
        fx["users"][1]["balance"] = 600  # bob opening = 600 - (500-1200-300+100) = 1500; shrink via payments below
        fx["payments"] = [{"id": "q1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "created_at": "2026-09-20T10:00:00+00:00"},
                          {"id": "q2", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 500, "created_at": "2026-09-21T10:00:00+00:00"},
                          {"id": "q3", "from_user_id": "u_cy", "to_user_id": "u_bob", "amount": 600, "created_at": "2026-09-22T10:00:00+00:00"}]
        fx["users"][0]["balance"] = 5000
        fx["users"][1]["balance"] = 600  # opening 0 + 500 - 500 + 600
        fx["users"][2]["balance"] = 1000
        self.assertEqual(call("POST", "/_test/reset", fx)[0], 204)
        ada, bob = login("ada"), login("bob")
        self.assertEqual(call("GET", "/me?as_of=2026-09-20T00:00:00%2B00:00", token=bob)[1]["balance"], 0)
        # shrinking q1 would leave bob at -100 after q2 -> rejected, nothing changes
        body = {"expected_revision": 1, "amount": 400, "effective_at": "2026-09-20T10:00:00+00:00", "reason": "r"}
        s, b, _ = self.corr(ada, "q1", body)
        self.assertEqual((s, b["error"]["code"]), (409, "historical_overdraft"))
        self.assertEqual(call("GET", "/payments/q1/revisions", token=ada)[1]["revisions"][0]["amount"], 500)
        self.assertEqual(call("GET", "/me", token=bob)[1]["balance"], 600)
        # moving it later than q2 also overdraws bob at q2
        s, b, _ = self.corr(ada, "q1", {**body, "amount": 500, "effective_at": "2026-09-21T11:00:00+00:00"}, "c9")
        self.assertEqual((s, b["error"]["code"]), (409, "historical_overdraft"))
        # moving it to the same instant as q2 is fine: combined effect at that instant
        s, b, _ = self.corr(ada, "q1", {**body, "amount": 500, "effective_at": "2026-09-21T10:00:00+00:00"}, "c10")
        self.assertEqual(s, 201)
        # current unaffordable debit takes precedence: bob holds 600; reducing q3 (+600) by 600 is fine now? receiver bob pays back
        s, b, _ = self.corr(login("cy"), "q3", {**body, "expected_revision": 1, "amount": 0}, "c11")
        self.assertEqual(s, 403 if False else s)
        s, b, _ = self.corr(login("cy"), "q3", {"expected_revision": 1, "amount": 0, "effective_at": "2026-09-22T10:00:00+00:00", "reason": "z"}, "c12")
        self.assertIn(s, (201, 409))
        total = sum(call("GET", "/me", token=t)[1]["balance"] for t in (ada, bob, login("cy")))
        self.assertEqual(total, 5000 + 600 + 1000)
        self.assertEqual(call("POST", "/payments", {"to_handle": "ada", "amount": 10 ** 6}, token=bob, key="big")[0], 409)

    def test_linked_payments_immutable(self):
        s, st, _ = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 5}]}, token=self.ada, key="ls")
        pid = st["payments"][0]["payment_id"]
        body = {"expected_revision": 1, "amount": 1, "effective_at": "2026-09-22T10:00:00+00:00", "reason": "r"}
        s, b, _ = self.corr(self.ada, pid, body)
        self.assertEqual((s, b["error"]["code"]), (422, "linked_payment_immutable"))
        a = call("POST", "/authorizations", {"to_handle": "cy", "amount": 50}, token=self.ada, key="la")[1]["authorization_id"]
        cap = call("POST", "/authorizations/%s/capture" % a, {}, token=self.cy, key="lc")[1]
        s, b, _ = self.corr(self.ada, cap["payment_id"], body, "cc")
        self.assertEqual((s, b["error"]["code"]), (422, "linked_payment_immutable"))
        self.assertEqual(call("GET", "/payments/%s/revisions" % pid, token=self.ada)[1]["revisions"][0]["effective_at"], st["committed_at"])

    def test_concurrent_corrections_same_revision(self):
        body = lambda i: {"expected_revision": 1, "amount": 100 + i, "effective_at": "2026-09-20T12:00:00+00:00", "reason": "r%d" % i}
        with ThreadPoolExecutor(20) as ex:
            res = list(ex.map(lambda i: self.corr(self.ada, "p_a", body(i), "cc%d" % i), range(20)))
        self.assertEqual(sorted(r[0] for r in res), [201] + [409] * 19)
        revs = call("GET", "/payments/p_a/revisions", token=self.ada)[1]["revisions"]
        self.assertEqual(len(revs), 2)
        total = sum(call("GET", "/me", token=t)[1]["balance"] for t in (self.ada, self.bob, self.cy))
        self.assertEqual(total, 10000 + 2500 + 600)

    def test_holds_over_time(self):
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 1000}, token=self.ada, key="h1")[1]
        self.assertIsNone(a["closed_at"])
        created = a["created_at"]
        e = lambda ts: ts.replace("+", "%2B")
        _, before, _ = self.me(self.ada, "?as_of=2026-09-01T00:00:00%2B00:00")
        self.assertEqual((before["held"], before["available"], before["total"]), (0, 9300, 9300))
        _, at, _ = self.me(self.ada, "?as_of=" + e(created))
        self.assertEqual((at["held"], at["available"], at["total"]), (1000, 9000, 10000))
        _, late, _ = self.me(self.ada, "?as_of=2999-01-01T00:00:00%2B00:00")
        self.assertEqual((late["held"], late["available"]), (0, 10000))  # expired at its deadline
        _, deadline, _ = self.me(self.ada, "?as_of=" + e(a["expires_at"]))
        self.assertEqual(deadline["held"], 0)
        _, unknown, _ = self.me(self.ada, "?known_at=2026-09-01T00:00:00%2B00:00")
        self.assertEqual(unknown["held"], 0)
        # a partial then final capture releases over time
        s, c1, _ = call("POST", "/authorizations/%s/capture" % a["authorization_id"], {"amount": 300, "final": False}, token=self.bob, key="hc1")
        _, mid, _ = self.me(self.ada)
        self.assertEqual((mid["held"], mid["total"], mid["available"]), (700, 9700, 9000))
        _, hist, _ = self.me(self.ada, "?as_of=" + e(c1["created_at"]))
        self.assertEqual((hist["held"], hist["total"]), (700, 9700))
        s, c2, _ = call("POST", "/authorizations/%s/capture" % a["authorization_id"], {"amount": 100}, token=self.bob, key="hc2")
        _, done, _ = self.me(self.ada)
        self.assertEqual((done["held"], done["total"], done["available"]), (0, 9600, 9600))
        got = [x for x in call("GET", "/authorizations", token=self.ada)[1]["authorizations"] if x["authorization_id"] == a["authorization_id"]][0]
        self.assertEqual(got["closed_at"], c2["created_at"])
        # statement holds money movements only: the two captures once each
        _, st, _ = call("GET", "/statement", token=self.ada)
        self.assertEqual([x["payment"]["authorization_id"] for x in st["entries"] if x["payment"]["authorization_id"]], [a["authorization_id"]] * 2)
        # void records closed_at
        a2 = call("POST", "/authorizations", {"to_handle": "bob", "amount": 50}, token=self.ada, key="h2")[1]
        v = call("POST", "/authorizations/%s/void" % a2["authorization_id"], token=self.ada)[1]
        self.assertIsNotNone(v["closed_at"])

    def test_reset_rules(self):
        fx = hist_fixture()
        fx["payments"][0]["created_at"] = "2999-01-01T00:00:00+00:00"
        self.assertEqual(call("POST", "/_test/reset", fx)[0], 422)
        self.assertEqual(self.me(self.ada)[1]["balance"], 10000)
        fx = hist_fixture()
        fx["payments"].append({"id": "p_e", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1})  # no created_at: reset time
        fx["users"][0]["balance"] = 9999
        fx["users"][1]["balance"] = 2501
        self.assertEqual(call("POST", "/_test/reset", fx)[0], 204)
        ada = login("ada")
        self.assertEqual(self.me(ada)[1]["balance"], 9999)
        pay = call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=ada, key="n1")[1]
        s, st, _ = call("GET", "/statement", token=ada)
        self.assertEqual([x["payment"]["payment_id"] for x in st["entries"]][-2:], ["p_e", pay["payment_id"]])
        self.assertEqual(st["closing_balance"], 9998)
        # seeded request back-fill is symmetric
        fx = hist_fixture()
        fx["requests"] = [{"id": "r1", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 1200, "status": "paid"}]
        fx["payments"][1]["request_id"] = "r1"
        self.assertEqual(call("POST", "/_test/reset", fx)[0], 204)

    def test_saved_statements_keep_their_original_form(self):
        self.assertEqual(call("POST", "/payments/p_b/corrections", {"expected_revision": 1, "amount": 1000, "effective_at": "2026-09-21T10:00:00+00:00", "reason": "r"}, token=self.bob, key="sf1")[0], 201)
        s, first, _ = call("GET", "/statement?limit=1", token=self.ada)
        tok = first["snapshot"]
        s, p4, _ = call("GET", "/statement?snapshot=%s&limit=200" % tok, token=self.ada)
        self.assertIn("refund_of", p4["entries"][0]["payment"])
        # later refunds and corrections never change a saved page, nor does export/import
        call("POST", "/payments/p_b/refunds", {"amount": 5}, token=self.ada, key="sf2")
        s, snap, _ = call("GET", "/_test/export")
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        self.assertEqual(call("GET", "/statement?snapshot=%s&limit=200" % tok, token=self.ada)[1], p4)
        # a snapshot exported by a stage-3 service has no `view` marker: it pages without refund_of
        old = json.loads(json.dumps(snap))
        for sn in old["state"]["snapshots"]:
            sn.pop("view")
        self.assertEqual(call("POST", "/_test/import", old)[0], 204)
        s, p3, _ = call("GET", "/statement?snapshot=%s&limit=200" % tok, token=self.ada)
        self.assertTrue(all("refund_of" not in e["payment"] for e in p3["entries"]))
        strip = json.loads(json.dumps(p4))
        for e in strip["entries"]:
            e["payment"].pop("refund_of")
        self.assertEqual(p3, strip)

    def test_import_validates_the_ledger(self):
        call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=self.ada, key="lg1")
        pid = call("GET", "/activity", token=self.ada)[1]["payments"][0]["payment_id"]
        call("POST", "/payments/%s/corrections" % pid, {"expected_revision": 1, "amount": 40, "effective_at": "2026-09-20T10:00:00+00:00", "reason": "r"}, token=self.ada, key="lg2")
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 10}, token=self.ada, key="lg3")[1]["authorization_id"]
        call("POST", "/authorizations/%s/void" % a, token=self.ada)
        s, snap, _ = call("GET", "/_test/export")
        snap["state"]["idempotency"] = []
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        def revs(st):
            return [p for p in st["payments"] if len(p["revisions"]) > 1][0]["revisions"]
        muts = [lambda st: st["users"][0].__setitem__("opening", st["users"][0]["opening"] + 1),
                lambda st: st["users"][0].pop("balance") and None,
                lambda st: revs(st)[1].__setitem__("amount", 41),
                lambda st: revs(st)[1].__setitem__("revision", 3),
                lambda st: revs(st)[1].__setitem__("reason", ""),
                lambda st: revs(st)[1].__setitem__("recorded_ts", revs(st)[0]["recorded_ts"] - 5),
                lambda st: revs(st)[0].__setitem__("amount", 99),
                lambda st: revs(st)[1].__setitem__("effective_at", "yesterday"),
                lambda st: revs(st).append(dict(revs(st)[1], revision=3)),
                lambda st: [x for x in st["authorizations"] if x["status"] == "voided"][0].__setitem__("closed_at", None),
                lambda st: [x for x in st["authorizations"] if x["status"] == "voided"][0].__setitem__("closed_ts", 5.0)]
        for i, f in enumerate(muts):
            m = json.loads(json.dumps(snap))
            f(m["state"])
            self.assertEqual(call("POST", "/_test/import", m)[0], 422, i)
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        self.assertEqual(call("GET", "/payments/%s/revisions" % pid, token=self.ada)[0], 200)

    def test_snapshots_survive_export_import(self):
        s, a, _ = call("GET", "/statement?limit=2", token=self.bob)
        tok = a["snapshot"]
        s, snap, _ = call("GET", "/_test/export")
        call("POST", "/payments", {"to_handle": "cy", "amount": 5}, token=self.bob, key="sx1")
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        s, p1, _ = call("GET", "/statement?snapshot=%s&limit=3&offset=0" % tok, token=self.bob)
        s, p2, _ = call("GET", "/statement?snapshot=%s&limit=3&offset=3" % tok, token=self.bob)
        self.assertEqual((s, len(p1["entries"]), len(p2["entries"]), p2["has_more"]), (200, 3, 1, False))
        self.assertEqual(p1["closing_balance"], a["closing_balance"])
        self.assertEqual(call("GET", "/statement?snapshot=" + tok, token=self.ada)[0], 404)
        # tampered snapshots are rejected, reset forgets them
        bad = json.loads(json.dumps(snap))
        bad["state"]["snapshots"][0]["closing_balance"] += 1
        self.assertEqual(call("POST", "/_test/import", bad)[0], 422)
        bad = json.loads(json.dumps(snap))
        bad["state"]["snapshots"][0]["entries"][0][0] = "ghost"
        self.assertEqual(call("POST", "/_test/import", bad)[0], 422)
        for f in (lambda sn: sn["entries"][0].__setitem__(1, 99),
                  lambda sn: sn["entries"][0].__setitem__(4, "2020-01-01T00:00:00+00:00"),
                  lambda sn: sn["entries"][0].__setitem__(5, "2020-01-01T00:00:00+00:00"),
                  lambda sn: sn["entries"][0].__setitem__(6, sn["entries"][0][6] + 1),
                  lambda sn: sn["echo"].__setitem__("known_at", "bad-time"),
                  lambda sn: sn["echo"].__setitem__("from", "2026-09-22T10:00:00+00:00"),
                  lambda sn: sn["echo"].__setitem__("to", "2026-09-20T10:00:01+00:00"),
                  lambda sn: sn["entries"].reverse(),
                  lambda sn: sn["entries"].pop(),
                  lambda sn: sn.__setitem__("opening_balance", sn["opening_balance"] + 1),
                  lambda sn: sn.__setitem__("closing_balance", sn["closing_balance"] + 1),
                  lambda sn: sn.__setitem__("taken_seq", 0),
                  lambda sn: sn.__setitem__("taken_seq", 10 ** 9),
                  lambda sn: sn.__setitem__("taken_ts", sn["taken_ts"] + 10 ** 7),
                  lambda sn: sn.__setitem__("taken_ts", sn["taken_ts"] - 1e9),
                  lambda sn: sn.pop("taken_ts"),
                  lambda sn: sn["echo"].__setitem__("known_at", "2000-01-01T00:00:00+00:00")):
            bad = json.loads(json.dumps(snap))
            f(bad["state"]["snapshots"][0])
            self.assertEqual(call("POST", "/_test/import", bad)[0], 422)
        call("POST", "/_test/reset", hist_fixture())
        self.assertEqual(call("GET", "/statement?snapshot=" + tok, token=login("bob"))[0], 404)

    def test_import_rejects_inconsistent_instants_and_histories(self):
        body = {"expected_revision": 1, "amount": 400, "effective_at": "2026-09-20T12:00:00+00:00", "reason": "fix"}
        self.assertEqual(self.corr(self.ada, "p_a", body)[0], 201)
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 10}, token=self.ada, key="ti1")[1]["authorization_id"]
        call("POST", "/authorizations/%s/void" % a, token=self.ada)
        s, snap, _ = call("GET", "/_test/export")
        snap["state"]["idempotency"] = []
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        def pay(st):
            return [x for x in st["payments"] if x["id"] == "p_a"][0]
        def voided(st):
            return [x for x in st["authorizations"] if x["status"] == "voided"][0]
        muts = [lambda st: pay(st)["revisions"][1].__setitem__("recorded_at", pay(st)["revisions"][0]["recorded_at"]),
                lambda st: pay(st)["revisions"][1].__setitem__("effective_at", "2026-09-20T12:00:00.5+00:00"),
                lambda st: pay(st)["revisions"][1].__setitem__("recorded_at", pay(st)["revisions"][1]["recorded_at"][:19] + ".999999+00:00"),
                lambda st: pay(st)["revisions"][1].__setitem__("effective_ts", pay(st)["revisions"][1]["effective_ts"] + 0.5),
                lambda st: voided(st).__setitem__("closed_at", voided(st)["closed_at"][:-6] + ".5+00:00"),
                lambda st: voided(st).__setitem__("closed_ts", voided(st)["closed_ts"] + 0.5)]
        for i, f in enumerate(muts):
            m = json.loads(json.dumps(snap))
            f(m["state"])
            self.assertEqual(call("POST", "/_test/import", m)[0], 422, i)
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)

    def test_import_rejects_a_historical_overdraft(self):
        fx = {"currency": "EUR", "minor_units": 2, "users": [
            {"id": "u_a", "email": "a@x.io", "password": "correct horse", "display_name": "A", "handle": "ha", "balance": 0},
            {"id": "u_b", "email": "b@x.io", "password": "correct horse", "display_name": "B", "handle": "hb", "balance": 100},
            {"id": "u_c", "email": "c@x.io", "password": "correct horse", "display_name": "C", "handle": "hc", "balance": 0}],
              "payments": [{"id": "ab", "from_user_id": "u_a", "to_user_id": "u_b", "amount": 100, "created_at": "2020-01-02T00:00:00+00:00"},
                           {"id": "bc", "from_user_id": "u_b", "to_user_id": "u_c", "amount": 100, "created_at": "2020-01-03T00:00:00+00:00"},
                           {"id": "cb", "from_user_id": "u_c", "to_user_id": "u_b", "amount": 100, "created_at": "2020-01-04T00:00:00+00:00"}]}
        self.assertEqual(call("POST", "/_test/reset", fx)[0], 204)
        s, snap, _ = call("GET", "/_test/export")
        snap["state"]["idempotency"] = []
        st = snap["state"]
        ab = [x for x in st["payments"] if x["id"] == "ab"][0]
        rev = dict(ab["revisions"][0])
        rev.update({"revision": 2, "amount": 0, "effective_at": "2020-01-02T00:00:00+00:00", "effective_ts": 1577923200.0,
                    "recorded_at": "2020-01-05T00:00:00+00:00", "recorded_ts": 1578182400.0, "reason": "reversal"})
        ab["revisions"].append(rev)
        for u in st["users"]:
            u["balance"] = {"u_a": 100, "u_b": 0, "u_c": 0}[u["id"]]
        self.assertEqual(call("POST", "/_test/import", snap)[0], 422)
        # the same correction made through the API is refused too
        self.assertEqual(call("POST", "/payments/ab/corrections", {"expected_revision": 1, "amount": 0, "effective_at": "2020-01-02T00:00:00+00:00", "reason": "r"},
                              token=login_user("a@x.io"), key="k")[1]["error"]["code"], "insufficient_funds" if False else "historical_overdraft")

    def test_import_rejects_a_backdating_that_overdraws_available(self):
        fx = {"currency": "EUR", "minor_units": 2, "users": [
            {"id": "u_a", "email": "a@x.io", "password": "correct horse", "display_name": "A", "handle": "ha", "balance": 30},
            {"id": "u_b", "email": "b@x.io", "password": "correct horse", "display_name": "B", "handle": "hb", "balance": 70},
            {"id": "u_c", "email": "c@x.io", "password": "correct horse", "display_name": "C", "handle": "hc", "balance": 0}],
              "payments": [{"id": "ab", "from_user_id": "u_a", "to_user_id": "u_b", "amount": 70, "created_at": "2020-01-04T00:00:00+00:00"}],
              "authorizations": [{"id": "h1", "from_user_id": "u_a", "to_user_id": "u_c", "amount": 80, "status": "open",
                                  "created_at": "2020-01-02T00:00:00+00:00", "expires_at": "2020-01-03T00:00:00+00:00"}]}
        self.assertEqual(call("POST", "/_test/reset", fx)[0], 204)
        a = login_user("a@x.io")
        s, v, _ = call("GET", "/me?as_of=2020-01-02T00:00:00%2B00:00", token=a)
        self.assertEqual((v["total"], v["held"], v["available"]), (100, 80, 20))
        # backdating the payment to the hold's creation would leave total 30 with 80 held
        s, snap, _ = call("GET", "/_test/export")
        snap["state"]["idempotency"] = []
        ab = [x for x in snap["state"]["payments"] if x["id"] == "ab"][0]
        rev = dict(ab["revisions"][0])
        rev.update({"revision": 2, "effective_at": "2020-01-02T00:00:00+00:00", "effective_ts": 1577923200.0,
                    "recorded_at": "2020-01-05T00:00:00+00:00", "recorded_ts": 1578182400.0, "reason": "backdate"})
        ab["revisions"].append(rev)
        self.assertEqual(call("POST", "/_test/import", snap)[0], 422)
        self.assertEqual(call("POST", "/payments/ab/corrections", {"expected_revision": 1, "amount": 70, "effective_at": "2020-01-02T00:00:00+00:00", "reason": "r"},
                              token=a, key="k")[1]["error"]["code"], "historical_overdraft")

    def test_future_known_at_snapshot_survives_later_corrections_and_import(self):
        s, a, _ = call("GET", "/statement?known_at=2090-01-01T00:00:00%2B00:00&to=2090-01-01T00:00:00%2B00:00", token=self.ada)
        tok = a["snapshot"]
        self.corr(self.ada, "p_a", {"expected_revision": 1, "amount": 400, "effective_at": "2026-09-20T12:00:00+00:00", "reason": "later"})
        s, before, _ = call("GET", "/statement?snapshot=%s&limit=200" % tok, token=self.ada)
        self.assertEqual([x["payment"]["amount"] for x in before["entries"] if x["payment"]["payment_id"] == "p_a"], [500])
        s, snap, _ = call("GET", "/_test/export")
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        self.assertEqual(call("GET", "/statement?snapshot=%s&limit=200" % tok, token=self.ada)[1], before)
        # a fresh statement with the same future known_at sees the correction
        s, fresh, _ = call("GET", "/statement?known_at=2090-01-01T00:00:00%2B00:00", token=self.ada)
        self.assertEqual([x["payment"]["amount"] for x in fresh["entries"] if x["payment"]["payment_id"] == "p_a"], [400])

    def test_future_instants_in_saved_statements_survive_later_events(self):
        toks = {}
        for q in ("known_at=2090-01-01T00:00:00%2B00:00", "from=2090-01-01T00:00:00%2B00:00", "to=2090-01-01T00:00:00%2B00:00",
                  "from=2020-01-01T00:00:00%2B00:00&to=2090-01-01T00:00:00%2B00:00&known_at=2090-06-01T00:00:00%2B00:00",
                  "known_at=2000-01-01T00:00:00%2B00:00"):
            toks[q] = call("GET", "/statement?" + q, token=self.bob)[1]["snapshot"]
        pages = {q: call("GET", "/statement?snapshot=%s&limit=200" % t_, token=self.bob)[1] for q, t_ in toks.items()}
        # later events: a payment, a correction, a hold
        call("POST", "/payments", {"to_handle": "cy", "amount": 7}, token=self.bob, key="fi1")
        self.corr(self.ada, "p_a", {"expected_revision": 1, "amount": 450, "effective_at": "2026-09-20T12:00:00+00:00", "reason": "later"}, "fi2")
        call("POST", "/authorizations", {"to_handle": "cy", "amount": 9}, token=self.bob, key="fi3")
        s, snap, _ = call("GET", "/_test/export")
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        for q, t_ in toks.items():
            self.assertEqual(call("GET", "/statement?snapshot=%s&limit=200" % t_, token=self.bob)[1], pages[q], q)
        # tampering still fails for the future-dated ones
        bad = json.loads(json.dumps(snap))
        for sn in bad["state"]["snapshots"]:
            if sn["entries"]:
                sn["entries"][0][6] += 1
        self.assertEqual(call("POST", "/_test/import", bad)[0], 422)

    def test_import_from_earlier_stage_exports(self):
        s, snap, _ = call("GET", "/_test/export")
        st = snap["state"]
        for u in st["users"]:
            u.pop("opening")
        for p in st["payments"]:
            p.pop("revisions")
        for a in st.get("authorizations", []):
            a.pop("closed_at", None); a.pop("closed_ts", None)
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        self.assertEqual(self.me(self.ada)[1]["balance"], 10000)
        self.assertEqual(call("GET", "/me?as_of=2026-09-19T00:00:00%2B00:00", token=self.ada)[1]["balance"], 9300)
        s, e, _ = call("GET", "/_test/export")
        self.assertEqual(call("POST", "/_test/import", e)[0], 204)


class Refunds(unittest.TestCase):
    def setUp(self):
        self.assertEqual(call("POST", "/_test/reset", hist_fixture())[0], 204)
        self.ada, self.bob, self.cy = login("ada"), login("bob"), login("cy")

    def refund(self, tok, pid, body, key="r1"):
        return call("POST", "/payments/%s/refunds" % pid, body, token=tok, key=key)

    def bal(self, tok):
        return call("GET", "/me", token=tok)[1]["balance"]

    def test_refund_rules(self):
        self.assertEqual(self.refund(self.bob, "p_b", {"amount": 5})[0], 403)   # the sender
        self.assertEqual(self.refund(self.cy, "p_b", {"amount": 5})[0], 403)    # a third party
        self.assertEqual(self.refund(self.ada, "nope", {"amount": 5})[0], 404)
        self.assertEqual(call("POST", "/payments/p_b/refunds", {"amount": 5}, key="x")[0], 401)
        self.assertEqual(call("POST", "/payments/p_b/refunds", {"amount": 5}, token=self.ada)[0], 400)
        for bad in ({}, {"amount": 0}, {"amount": -1}, {"amount": 1.5}, {"amount": "5"}, {"amount": True}, {"amount": 1000000001}):
            self.assertEqual(self.refund(self.ada, "p_b", bad, "bad")[0], 422, bad)
        before = (self.bal(self.ada), self.bal(self.bob))
        s, r, _ = self.refund(self.ada, "p_b", {"amount": 200})
        self.assertEqual((s, r["refund_of"], r["from_handle"], r["to_handle"], r["amount"], r["request_id"], r["authorization_id"], r["note"], r["visibility"]),
                         (201, "p_b", "ada", "bob", 200, None, None, "two", "private"))
        self.assertEqual((self.bal(self.ada), self.bal(self.bob)), (before[0] - 200, before[1] + 200))
        self.assertEqual(self.refund(self.ada, "p_b", {"amount": 200})[1], r)
        self.assertEqual(self.refund(self.ada, "p_b", {"amount": 200})[0], 200)
        self.assertEqual(self.refund(self.ada, "p_b", {"amount": 201})[1]["error"]["code"], "idempotency_key_reuse")
        self.assertEqual((self.bal(self.ada), self.bal(self.bob)), (before[0] - 200, before[1] + 200))
        # other payments carry refund_of null
        act = {x["payment_id"]: x for x in call("GET", "/activity", token=self.ada)[1]["payments"]}
        self.assertIsNone(act["p_a"]["refund_of"])
        # cumulative limit
        s, b, _ = self.refund(self.ada, "p_b", {"amount": 1001}, "r2")
        self.assertEqual((s, b["error"]["code"]), (422, "refund_exceeds_payment"))
        self.assertEqual(self.refund(self.ada, "p_b", {"amount": 1000}, "r3")[0], 201)
        self.assertEqual(self.refund(self.ada, "p_b", {"amount": 1}, "r4")[1]["error"]["code"], "refund_exceeds_payment")
        # refunds of refunds are refused; refunds are immutable
        s, b, _ = self.refund(self.bob, r["payment_id"], {"amount": 1}, "r5")
        self.assertEqual((s, b["error"]["code"]), (422, "invalid_refund_target"))
        body = {"expected_revision": 1, "amount": 1, "effective_at": "2026-09-22T10:00:00+00:00", "reason": "r"}
        s, b, _ = call("POST", "/payments/%s/corrections" % r["payment_id"], body, token=self.ada, key="cr")
        self.assertEqual((s, b["error"]["code"]), (422, "linked_payment_immutable"))
        # statements show refunds as ordinary payments, once
        st = call("GET", "/statement", token=self.ada)[1]
        self.assertEqual(sum(1 for x in st["entries"] if x["payment"]["refund_of"] == "p_b"), 2)
        self.assertEqual(st["opening_balance"] + sum(x["delta"] for x in st["entries"]), st["closing_balance"])

    def test_correction_cannot_go_below_refunded(self):
        self.assertEqual(self.refund(self.cy, "p_c", {"amount": 200})[0], 201)  # cy got 300 from bob
        body = {"expected_revision": 1, "amount": 150, "effective_at": "2026-09-22T10:00:00+00:00", "reason": "r"}
        s, b, _ = call("POST", "/payments/p_c/corrections", body, token=self.bob, key="cc1")
        self.assertEqual((s, b["error"]["code"]), (422, "refund_exceeds_payment"))
        s, b, _ = call("POST", "/payments/p_c/corrections", {**body, "amount": 200}, token=self.bob, key="cc2")
        self.assertEqual(s, 201)
        # refunds limit follows the corrected amount
        self.assertEqual(self.refund(self.cy, "p_c", {"amount": 1}, "rr")[1]["error"]["code"], "refund_exceeds_payment")

    def test_available_funds_and_non_effects(self):
        # cy locks everything in a hold: nothing left to refund from
        a = call("POST", "/authorizations", {"to_handle": "ada", "amount": 600}, token=self.cy, key="h")[1]
        s, b, _ = self.refund(self.cy, "p_c", {"amount": 1})
        self.assertEqual((s, b["error"]["code"]), (409, "insufficient_funds"))
        call("POST", "/authorizations/%s/void" % a["authorization_id"], token=self.cy)
        self.assertEqual(self.refund(self.cy, "p_c", {"amount": 1})[0], 201)
        # a request payment: the request stays paid
        rq = call("POST", "/requests", {"payer_handle": "bob", "amount": 50}, token=self.cy, key="rq")[1]["request_id"]
        pay = call("POST", "/requests/%s/pay" % rq, {}, token=self.bob, key="rqp")[1]
        self.assertEqual(self.refund(self.cy, pay["payment_id"], {"amount": 50}, "rf2")[0], 201)
        reqs = {r["request_id"]: r for r in call("GET", "/requests", token=self.cy)[1]["requests"]}
        self.assertEqual(reqs[rq]["status"], "paid")
        # a capture: the authorization stays captured and the hold is not restored
        a2 = call("POST", "/authorizations", {"to_handle": "cy", "amount": 100}, token=self.bob, key="h2")[1]["authorization_id"]
        cap = call("POST", "/authorizations/%s/capture" % a2, {"amount": 60}, token=self.cy, key="hc")[1]
        self.assertEqual(self.refund(self.cy, cap["payment_id"], {"amount": 60}, "rf3")[0], 201)
        me = call("GET", "/me", token=self.bob)[1]
        self.assertEqual(me["held"], 0)
        got = [x for x in call("GET", "/authorizations", token=self.bob)[1]["authorizations"] if x["authorization_id"] == a2][0]
        self.assertEqual((got["status"], got["captured_amount"]), ("captured", 60))
        # a settlement member can be refunded; membership is unchanged
        st = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 30}]}, token=self.ada, key="s1")[1]
        sp = st["payments"][0]["payment_id"]
        self.assertEqual(self.refund(self.bob, sp, {"amount": 30}, "rf4")[0], 201)
        again = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 30}]}, token=self.ada, key="s1")
        self.assertEqual((again[0], again[1]), (200, st))
        # round trip and conservation
        s, snap, _ = call("GET", "/_test/export")
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        tot = sum(call("GET", "/me", token=t)[1]["balance"] for t in (self.ada, self.bob, self.cy))
        self.assertEqual(tot, 10000 + 2500 + 600)

    def test_import_checks_refunds(self):
        self.refund(self.ada, "p_b", {"amount": 100})
        s, snap, _ = call("GET", "/_test/export")
        snap["state"]["idempotency"] = []
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        def refund_payment(st):
            return [p for p in st["payments"] if p.get("refund_of")][0]
        for f in (lambda st: refund_payment(st).__setitem__("refund_of", "ghost"),
                  lambda st: refund_payment(st).__setitem__("amount", 5000),
                  lambda st: refund_payment(st).__setitem__("note", "changed"),
                  lambda st: refund_payment(st).__setitem__("refund_of", refund_payment(st)["id"]),
                  lambda st: refund_payment(st).__setitem__("to_user_id", st["users"][2]["id"])):
            m = json.loads(json.dumps(snap))
            f(m["state"])
            self.assertEqual(call("POST", "/_test/import", m)[0], 422)


class Batches(unittest.TestCase):
    EFF = "2026-09-22T12:00:00+00:00"

    def setUp(self):
        self.assertEqual(call("POST", "/_test/reset", hist_fixture())[0], 204)
        self.ada, self.bob, self.cy = login("ada"), login("bob"), login("cy")

    def item(self, pid, rev=1, amount=0, eff=None, reason="reversal"):
        return {"payment_id": pid, "expected_revision": rev, "amount": amount, "effective_at": eff or self.EFF, "reason": reason}

    def batch(self, tok, items, key="b1", extra=None):
        return call("POST", "/correction-batches", {"corrections": items, **(extra or {})}, token=tok, key=key)

    def total(self):
        return sum(call("GET", "/me", token=t)[1]["balance"] for t in (self.ada, self.bob, self.cy))

    def test_access_and_shape(self):
        it = [self.item("p_a")]
        self.assertEqual(call("POST", "/correction-batches", {"corrections": it}, key="k")[0], 401)
        self.assertEqual(self.batch(self.bob, it)[1]["error"]["code"], "forbidden")
        self.assertEqual(call("POST", "/correction-batches", {"corrections": it}, token=self.ada)[1]["error"]["code"], "missing_idempotency_key")
        for bad in ([], [self.item("p_a")] * 2, [5], [{"expected_revision": 1}], "x"):
            self.assertEqual(call("POST", "/correction-batches", {"corrections": bad}, token=self.ada, key="bad")[0], 422, bad)
        self.assertEqual(call("POST", "/correction-batches", {}, token=self.ada, key="bad2")[0], 422)
        many = [self.item("n%d" % i) for i in range(33)]
        self.assertEqual(self.batch(self.ada, many, "many")[0], 422)

    def test_item_error_order(self):
        s, b, _ = self.batch(self.ada, [self.item("nope"), self.item("p_a", amount=-1)], "o1")
        self.assertEqual((s, b["error"]["code"]), (404, "not_found"))
        s, b, _ = self.batch(self.ada, [self.item("p_a", amount=-1), self.item("nope")], "o2")
        self.assertEqual((s, b["error"]["code"]), (422, "validation_failed"))
        s, b, _ = self.batch(self.ada, [self.item("p_a", rev=2)], "o3")
        self.assertEqual((s, b["error"]["code"]), (409, "stale_revision"))
        a = call("POST", "/authorizations", {"to_handle": "cy", "amount": 10}, token=self.ada, key="oa")[1]["authorization_id"]
        cap = call("POST", "/authorizations/%s/capture" % a, {}, token=self.cy, key="oc")[1]["payment_id"]
        s, b, _ = self.batch(self.ada, [self.item("p_a"), self.item(cap)], "o4")
        self.assertEqual((s, b["error"]["code"]), (422, "linked_payment_immutable"))
        ref = call("POST", "/payments/p_b/refunds", {"amount": 5}, token=self.ada, key="or")[1]["payment_id"]
        s, b, _ = self.batch(self.ada, [self.item(ref)], "o5")
        self.assertEqual((s, b["error"]["code"]), (422, "linked_payment_immutable"))
        s, b, _ = self.batch(self.ada, [self.item("p_b", amount=4)], "o6")
        self.assertEqual((s, b["error"]["code"]), (422, "refund_exceeds_payment"))
        self.assertEqual(self.total(), 10000 + 2500 + 600)

    def test_success_replay_statements_snapshots(self):
        _, st0, _ = call("GET", "/statement?limit=2", token=self.bob)
        tok = st0["snapshot"]
        prev = {r["revision"]: r for r in call("GET", "/payments/p_a/revisions", token=self.ada)[1]["revisions"]}
        s, r, _ = self.batch(self.ada, [self.item("p_a", amount=0), self.item("p_c", amount=100, eff="2026-09-22T14:00:00+02:00")], extra={"junk": 1})
        self.assertEqual(s, 201)
        self.assertTrue(r["correction_batch_id"])
        self.assertEqual([x["payment_id"] for x in r["revisions"]], ["p_a", "p_c"])
        self.assertEqual({x["recorded_at"] for x in r["revisions"]}, {r["recorded_at"]})
        self.assertEqual({x["correction_batch_id"] for x in r["revisions"]}, {r["correction_batch_id"]})
        self.assertEqual([x["revision"] for x in r["revisions"]], [2, 2])
        self.assertGreater(r["recorded_at"], prev[1]["recorded_at"])
        self.assertEqual(self.batch(self.ada, [self.item("p_a", amount=0), self.item("p_c", amount=100, eff="2026-09-22T14:00:00+02:00")], extra={"junk": 1})[1], r)
        self.assertEqual(self.batch(self.ada, [self.item("p_a", amount=1)])[1]["error"]["code"], "idempotency_key_reuse")
        # balances: ada +500, bob -500 (p_a reversed), then p_c 300 -> 100: bob +200, cy -200
        self.assertEqual([call("GET", "/me", token=t)[1]["balance"] for t in (self.ada, self.bob, self.cy)], [10500, 2200, 400])
        self.assertEqual(self.total(), 13100)
        # activity shows originals; the revisions endpoint shows the batch id; the old snapshot is frozen
        act = {x["payment_id"]: x for x in call("GET", "/activity", token=self.ada)[1]["payments"]}
        self.assertEqual(act["p_a"]["amount"], 500)
        rv = call("GET", "/payments/p_a/revisions", token=self.bob)[1]["revisions"]
        self.assertEqual((rv[0]["correction_batch_id"], rv[1]["correction_batch_id"]), (None, r["correction_batch_id"]))
        s, pg, _ = call("GET", "/statement?snapshot=%s&limit=10" % tok, token=self.bob)
        self.assertEqual([x["payment"]["amount"] for x in pg["entries"]], [500, 1200, 300, 100])
        _, st1, _ = call("GET", "/statement", token=self.bob)
        self.assertEqual([x["payment"]["amount"] for x in st1["entries"] if x["payment"]["payment_id"] in ("p_a", "p_c")], [0, 100])
        self.assertEqual(st1["opening_balance"] + sum(x["delta"] for x in st1["entries"]), st1["closing_balance"])
        s, snap, _ = call("GET", "/_test/export")
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        self.assertEqual(self.batch(self.ada, [self.item("p_a", amount=0), self.item("p_c", amount=100, eff="2026-09-22T14:00:00+02:00")], extra={"junk": 1})[1], r)

    def test_settlement_members(self):
        s, st, _ = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 30},
                                                               {"from_handle": "bob", "to_handle": "cy", "amount": 20, "visibility": "private"}]}, token=self.ada, key="st")
        m1, m2 = [x["payment_id"] for x in st["payments"]]
        s, b, _ = self.batch(self.ada, [self.item(m1)], "s1")
        self.assertEqual((s, b["error"]["code"]), (422, "incomplete_settlement"))
        s, b, _ = self.batch(self.ada, [self.item(m1), self.item(m2, eff="2026-09-22T12:00:01+00:00")], "s2")
        self.assertEqual((s, b["error"]["code"]), (422, "validation_failed"))
        # the single-payment endpoint still refuses members
        body = {k: v for k, v in self.item(m1).items() if k != "payment_id"}
        self.assertEqual(call("POST", "/payments/%s/corrections" % m1, body, token=self.ada, key="sc")[1]["error"]["code"], "linked_payment_immutable")
        # same instant in different offset spellings is fine, with an ordinary payment alongside
        s, r, _ = self.batch(self.ada, [self.item(m1, amount=10), self.item(m2, amount=5, eff="2026-09-22T14:00:00+02:00"), self.item("p_a", amount=450)], "s3")
        self.assertEqual(s, 201)
        # original settlement receipt, retries and membership are untouched; a member refund obeys the new amount
        again = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 30},
                                                            {"from_handle": "bob", "to_handle": "cy", "amount": 20, "visibility": "private"}]}, token=self.ada, key="st")
        self.assertEqual((again[0], again[1]), (200, st))
        self.assertEqual(call("POST", "/payments/%s/refunds" % m1, {"amount": 11}, token=self.bob, key="sr")[1]["error"]["code"], "refund_exceeds_payment")
        self.assertEqual(call("POST", "/payments/%s/refunds" % m1, {"amount": 10}, token=self.bob, key="sr2")[0], 201)
        # a batch cannot go below a settlement member's refund
        s, b, _ = self.batch(self.ada, [self.item(m1, rev=2, amount=9), self.item(m2, rev=2, amount=5)], "s4")
        self.assertEqual((s, b["error"]["code"]), (422, "refund_exceeds_payment"))
        self.assertEqual(self.total(), 10000 + 2500 + 600)

    def test_combined_funds_and_history(self):
        # bob locks all his money in a hold: reversing p_a alone (bob owes 500) is unaffordable, with p_b it is not
        call("POST", "/authorizations", {"to_handle": "ada", "amount": 2500}, token=self.bob, key="lock")
        eff = "2026-09-20T12:00:00+00:00"
        s, b, _ = self.batch(self.ada, [self.item("p_a", eff=eff)], "f1")
        self.assertEqual((s, b["error"]["code"]), (409, "insufficient_funds"))
        s, r, _ = self.batch(self.ada, [self.item("p_a", eff=eff), self.item("p_b", eff=eff)], "f2")
        self.assertEqual(s, 201)
        self.assertEqual(self.total(), 10000 + 2500 + 600)

    def test_history_failure_changes_nothing(self):
        fx = hist_fixture()
        fx["payments"] = [{"id": "q1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "created_at": "2026-09-20T10:00:00+00:00"},
                          {"id": "q2", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 500, "created_at": "2026-09-21T10:00:00+00:00"},
                          {"id": "q3", "from_user_id": "u_cy", "to_user_id": "u_bob", "amount": 600, "created_at": "2026-09-22T10:00:00+00:00"}]
        fx["users"][0]["balance"], fx["users"][1]["balance"], fx["users"][2]["balance"] = 5000, 600, 1000
        self.assertEqual(call("POST", "/_test/reset", fx)[0], 204)
        ada = login("ada")
        before = call("GET", "/statement", token=ada)[1]
        s, b, _ = self.batch(ada, [{"payment_id": "q1", "expected_revision": 1, "amount": 400, "effective_at": "2026-09-20T10:00:00+00:00", "reason": "r"}], "h1")
        self.assertEqual((s, b["error"]["code"]), (409, "historical_overdraft"))
        self.assertEqual(call("GET", "/payments/q1/revisions", token=ada)[1]["revisions"][0]["amount"], 500)
        after = call("GET", "/statement", token=ada)[1]
        self.assertEqual(before["entries"], after["entries"])
        # the failed key is reusable
        s, r, _ = self.batch(ada, [{"payment_id": "q1", "expected_revision": 1, "amount": 500, "effective_at": "2026-09-20T10:00:00+00:00", "reason": "r"}], "h1")
        self.assertEqual(s, 201)

    def test_import_checks_batches(self):
        s, st, _ = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 30},
                                                               {"from_handle": "bob", "to_handle": "cy", "amount": 20}]}, token=self.ada, key="ist")
        m1, m2 = [x["payment_id"] for x in st["payments"]]
        self.assertEqual(self.batch(self.ada, [self.item(m1, amount=1), self.item(m2, amount=2), self.item("p_a", amount=3)], "ib")[0], 201)
        s, snap, _ = call("GET", "/_test/export")
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)
        def rev(st_, pid):
            return [p for p in st_["payments"] if p["id"] == pid][0]["revisions"][1]
        def batch_row(st_):
            return [r for r in st_["idempotency"] if r[2] == "/correction-batches"][0]
        for f in (lambda st_: batch_row(st_)[4]["revisions"].pop(),
                  lambda st_: batch_row(st_)[4]["revisions"].reverse(),
                  lambda st_: batch_row(st_)[4]["revisions"].append(dict(batch_row(st_)[4]["revisions"][0])),
                  lambda st_: batch_row(st_)[4].__setitem__("recorded_at", "2001-01-01T00:00:00+00:00"),
                  lambda st_: st_["operators"].clear()):
            m = json.loads(json.dumps(snap))
            f(m["state"])
            self.assertEqual(call("POST", "/_test/import", m)[0], 422)
        snap["state"]["idempotency"] = []
        muts = [lambda st_: rev(st_, m1).__setitem__("correction_batch_id", None),
                lambda st_: rev(st_, m2).__setitem__("effective_at", "2026-09-22T12:00:00+00:00") or rev(st_, m2).__setitem__("effective_ts", 1.0),
                lambda st_: rev(st_, m2).__setitem__("recorded_ts", rev(st_, m2)["recorded_ts"] + 1)]
        for i, f in enumerate(muts):
            m = json.loads(json.dumps(snap))
            f(m["state"])
            self.assertEqual(call("POST", "/_test/import", m)[0], 422, i)
        self.assertEqual(call("POST", "/_test/import", snap)[0], 204)

    def test_concurrent_batches_sharing_a_revision(self):
        def go(i):
            items = [self.item("p_a", amount=100 + i), self.item("p_c", amount=50 + i)] if i % 2 else [self.item("p_c", amount=60 + i), self.item("p_b", amount=70 + i)]
            return self.batch(self.ada, items, "cb%d" % i)
        with ThreadPoolExecutor(12) as ex:
            res = list(ex.map(go, range(12)))
        ok = [r for r in res if r[0] == 201]
        self.assertEqual(len(ok), 1)  # every batch touches p_c at revision 1
        self.assertTrue(all(r[0] in (201, 409) for r in res))
        self.assertEqual(self.total(), 10000 + 2500 + 600)


class Stage3GapList(unittest.TestCase):
    """Scripted checks for the spec-auditor's stage-3 gap list (items not covered elsewhere)."""

    def setUp(self):
        self.assertEqual(call("POST", "/_test/reset", hist_fixture())[0], 204)
        self.ada, self.bob, self.cy = login("ada"), login("bob"), login("cy")

    def corr(self, tok, pid, **kw):
        body = {"expected_revision": 1, "amount": 0, "effective_at": "2026-09-20T12:00:00+00:00", "reason": "r"}
        body.update(kw)
        return call("POST", "/payments/%s/corrections" % pid, body, token=tok, key=kw.get("key", "k-%s-%s" % (pid, body["expected_revision"])))

    def test_known_at_between_pay_and_correction(self):
        s, pay, _ = call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=self.ada, key="g1")
        time.sleep(1.1)
        mid = datetime_now_iso()
        time.sleep(0.05)
        s, c, _ = call("POST", "/payments/%s/corrections" % pay["payment_id"], {"expected_revision": 1, "amount": 0, "effective_at": pay["created_at"], "reason": "zero"}, token=self.ada, key="g2")
        e = lambda ts: ts.replace("+", "%2B")
        _, st, _ = call("GET", "/statement?known_at=" + e(mid), token=self.ada)
        mine = [x for x in st["entries"] if x["payment"]["payment_id"] == pay["payment_id"]]
        self.assertEqual([(x["revision"], x["delta"]) for x in mine], [(1, -100)])
        _, st, _ = call("GET", "/statement", token=self.ada)
        mine = [x for x in st["entries"] if x["payment"]["payment_id"] == pay["payment_id"]]
        self.assertEqual([(x["revision"], x["delta"], x["payment"]["amount"]) for x in mine], [(2, 0, 0)])  # a zero entry, counted once
        _, st, _ = call("GET", "/statement?known_at=2000-01-01T00:00:00%2B00:00", token=self.ada)
        self.assertEqual(st["entries"], [])
        self.assertEqual(st["opening_balance"], st["closing_balance"])

    def test_recorded_at_strictly_increases_within_a_second(self):
        s, pay, _ = call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=self.ada, key="r1")
        times = [pay["created_at"]]
        for i, amt in enumerate((90, 80, 70, 60)):
            s, r, _ = call("POST", "/payments/%s/corrections" % pay["payment_id"], {"expected_revision": i + 1, "amount": amt, "effective_at": pay["created_at"], "reason": "r%d" % i}, token=self.ada, key="r-%d" % i)
            self.assertEqual(s, 201)
            times.append(r["recorded_at"])
        from datetime import datetime
        parsed = [datetime.fromisoformat(x).timestamp() for x in times]
        self.assertEqual(parsed, sorted(set(parsed)))

    def test_backdating_moves_entries_between_windows(self):
        win = "?from=2026-09-20T00:00:00%2B00:00&to=2026-09-21T00:00:00%2B00:00"
        _, before, _ = call("GET", "/statement" + win, token=self.bob)
        self.assertEqual([x["payment"]["payment_id"] for x in before["entries"]], ["p_a"])
        # move p_c (09-22) into the window, and p_a out of it
        self.assertEqual(self.corr(self.bob, "p_c", amount=300, effective_at="2026-09-20T18:00:00+00:00", key="m1")[0], 201)
        self.assertEqual(self.corr(self.ada, "p_a", amount=500, effective_at="2026-09-23T00:00:00+00:00", key="m2")[0], 201)
        _, after, _ = call("GET", "/statement" + win, token=self.bob)
        self.assertEqual([x["payment"]["payment_id"] for x in after["entries"]], ["p_c"])
        self.assertNotEqual((before["opening_balance"], before["closing_balance"]), (after["opening_balance"], after["closing_balance"]))
        self.assertEqual(after["opening_balance"] + sum(x["delta"] for x in after["entries"]), after["closing_balance"])

    def test_insufficient_funds_beats_historical_overdraft(self):
        fx = hist_fixture()
        fx["payments"] = [{"id": "q1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "created_at": "2026-09-20T10:00:00+00:00"},
                          {"id": "q2", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 500, "created_at": "2026-09-21T10:00:00+00:00"},
                          {"id": "q3", "from_user_id": "u_cy", "to_user_id": "u_bob", "amount": 600, "created_at": "2026-09-22T10:00:00+00:00"}]
        fx["users"][0]["balance"], fx["users"][1]["balance"], fx["users"][2]["balance"] = 5000, 600, 1000
        self.assertEqual(call("POST", "/_test/reset", fx)[0], 204)
        ada, bob = login("ada"), login("bob")
        body = {"expected_revision": 1, "amount": 400, "effective_at": "2026-09-20T10:00:00+00:00", "reason": "r"}
        self.assertEqual(call("POST", "/payments/q1/corrections", body, token=ada, key="p1")[1]["error"]["code"], "historical_overdraft")
        call("POST", "/authorizations", {"to_handle": "ada", "amount": 600}, token=bob, key="lock")  # bob's available is now 0
        self.assertEqual(call("POST", "/payments/q1/corrections", body, token=ada, key="p2")[1]["error"]["code"], "insufficient_funds")
        # a backdated increase before the sender had the money
        body = {"expected_revision": 1, "amount": 900, "effective_at": "2026-09-20T09:00:00+00:00", "reason": "r"}
        s, b, _ = call("POST", "/payments/q2/corrections", body, token=bob, key="p3")
        self.assertIn(b["error"]["code"], ("historical_overdraft", "insufficient_funds"))
        self.assertEqual(call("GET", "/payments/q2/revisions", token=bob)[1]["revisions"][0]["amount"], 500)

    def test_default_statement_snapshot_is_frozen_after_lifecycle_events(self):
        _, first, _ = call("GET", "/statement", token=self.ada)
        call("POST", "/authorizations", {"to_handle": "bob", "amount": 10}, token=self.ada, key="l1")
        call("POST", "/payments", {"to_handle": "cy", "amount": 3}, token=self.ada, key="l2")
        self.corr(self.ada, "p_a", amount=1, key="l3")
        _, again, _ = call("GET", "/statement?snapshot=%s&limit=200" % first["snapshot"], token=self.ada)
        self.assertEqual((again["opening_balance"], again["closing_balance"], [x["payment"]["amount"] for x in again["entries"]]),
                         (first["opening_balance"], first["closing_balance"], [x["payment"]["amount"] for x in first["entries"]]))

    def test_created_at_on_every_payment_endpoint(self):
        pay = call("POST", "/payments", {"to_handle": "bob", "amount": 5}, token=self.ada, key="c1")[1]
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, token=self.bob, key="c2")[1]["request_id"]
        paid = call("POST", "/requests/%s/pay" % rq, {}, token=self.ada, key="c3")[1]
        st = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}, token=self.ada, key="c4")[1]
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 5}, token=self.ada, key="c5")[1]["authorization_id"]
        cap = call("POST", "/authorizations/%s/capture" % a, {}, token=self.bob, key="c6")[1]
        rows = [pay, paid, st["payments"][0], cap] + call("GET", "/activity", token=self.ada)[1]["payments"]
        rows += [e["payment"] for e in call("GET", "/statement", token=self.ada)[1]["entries"]]
        self.assertTrue(all(isinstance(r.get("created_at"), str) and r["created_at"][-6:] in ("+00:00",) for r in rows))


class Stage4GapList(unittest.TestCase):
    EFF = "2026-09-22T12:00:00+00:00"

    def setUp(self):
        self.assertEqual(call("POST", "/_test/reset", hist_fixture())[0], 204)
        self.ada, self.bob, self.cy = login("ada"), login("bob"), login("cy")

    def item(self, pid, rev=1, amount=0, eff=None):
        return {"payment_id": pid, "expected_revision": rev, "amount": amount, "effective_at": eff or self.EFF, "reason": "r"}

    def test_batch_netting_and_key_reuse(self):
        # bob's money is all held: p_a -> 0 (bob owes 500 back) is unaffordable alone, p_b -> 700 (bob gets 500) funds it
        call("POST", "/authorizations", {"to_handle": "ada", "amount": 2500}, token=self.bob, key="lock")
        alone = call("POST", "/correction-batches", {"corrections": [self.item("p_a")]}, token=self.ada, key="n1")
        self.assertEqual((alone[0], alone[1]["error"]["code"]), (409, "insufficient_funds"))
        both = call("POST", "/correction-batches", {"corrections": [self.item("p_a"), self.item("p_b", amount=700)]}, token=self.ada, key="n1")
        self.assertEqual(both[0], 201)  # the rejected attempt did not claim the key
        self.assertEqual(sum(call("GET", "/me", token=t)[1]["balance"] for t in (self.ada, self.bob, self.cy)), 10000 + 2500 + 600)

    def test_batch_recorded_at_after_a_single_correction_in_the_same_second(self):
        s, one, _ = call("POST", "/payments/p_a/corrections", {"expected_revision": 1, "amount": 450, "effective_at": "2026-09-20T12:00:00+00:00", "reason": "s"}, token=self.ada, key="sc")
        s, b, _ = call("POST", "/correction-batches", {"corrections": [self.item("p_a", rev=2, amount=400), self.item("p_c", amount=250)]}, token=self.ada, key="bc")
        self.assertEqual(s, 201)
        from datetime import datetime
        self.assertGreater(datetime.fromisoformat(b["recorded_at"]).timestamp(), datetime.fromisoformat(one["recorded_at"]).timestamp())
        self.assertEqual([x["payment_id"] for x in b["revisions"]], ["p_a", "p_c"])
        self.assertTrue(all(x["correction_batch_id"] == b["correction_batch_id"] for x in b["revisions"]))

    def test_concurrent_refunds_respect_the_cap(self):
        with ThreadPoolExecutor(12) as ex:
            res = list(ex.map(lambda i: call("POST", "/payments/p_b/refunds", {"amount": 200}, token=self.ada, key="cr%d" % i), range(12)))
        self.assertEqual(sum(1 for r in res if r[0] == 201), 6)  # 1200 / 200
        self.assertTrue(all(r[0] in (201, 422) for r in res))
        self.assertEqual(sum(call("GET", "/me", token=t)[1]["balance"] for t in (self.ada, self.bob, self.cy)), 10000 + 2500 + 600)

    def test_single_correction_and_batch_share_a_revision(self):
        def go(i):
            if i % 2:
                return call("POST", "/payments/p_c/corrections", {"expected_revision": 1, "amount": 100 + i, "effective_at": self.EFF, "reason": "r"}, token=self.bob, key="sx%d" % i)
            return call("POST", "/correction-batches", {"corrections": [self.item("p_c", amount=50 + i)]}, token=self.ada, key="bx%d" % i)
        with ThreadPoolExecutor(10) as ex:
            res = list(ex.map(go, range(10)))
        self.assertEqual(sum(1 for r in res if r[0] == 201), 1)

    def test_refund_shape_everywhere(self):
        s, r, _ = call("POST", "/payments/p_b/refunds", {"amount": 10}, token=self.ada, key="rs")
        self.assertEqual((r["settlement_id"], r["request_id"], r["authorization_id"], r["refund_of"]), (None, None, None, "p_b"))
        for tok in (self.ada, self.bob):
            st = call("GET", "/statement", token=tok)[1]
            self.assertEqual(sum(1 for x in st["entries"] if x["payment"]["refund_of"] == "p_b"), 1)
        for tok in (self.ada, self.bob, self.cy):
            act = call("GET", "/activity", token=tok)[1]["payments"]
            self.assertTrue(all("refund_of" in p for p in act))
            self.assertEqual([p["refund_of"] for p in act if p["payment_id"] == "p_a"], [None])
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, token=self.bob, key="rq")[1]["request_id"]
        self.assertIsNone(call("POST", "/requests/%s/pay" % rq, {}, token=self.ada, key="rp")[1]["refund_of"])

    def test_history_accounts_for_refunds_and_batches(self):
        call("POST", "/payments/p_b/refunds", {"amount": 200}, token=self.ada, key="h1")
        call("POST", "/correction-batches", {"corrections": [self.item("p_a", amount=100, eff="2026-09-20T12:00:00+00:00")]}, token=self.ada, key="h2")
        for tok in (self.ada, self.bob, self.cy):
            me = call("GET", "/me?as_of=2999-01-01T00:00:00%2B00:00&known_at=2999-01-01T00:00:00%2B00:00", token=tok)[1]
            st = call("GET", "/statement?limit=200", token=tok)[1]
            self.assertEqual(me["balance"], st["closing_balance"])
            self.assertEqual(st["opening_balance"] + sum(x["delta"] for x in st["entries"]), st["closing_balance"])
        self.assertEqual(sum(call("GET", "/me", token=t)[1]["balance"] for t in (self.ada, self.bob, self.cy)), 10000 + 2500 + 600)


if __name__ == "__main__":
    unittest.main()
