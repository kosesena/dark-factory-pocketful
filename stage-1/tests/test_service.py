import http.client
import json
import os
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server  # noqa: E402

SRV = server.make_server(0, "127.0.0.1")
PORT = SRV.server_address[1]
threading.Thread(target=SRV.serve_forever, daemon=True).start()


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
    return r.status, (json.loads(txt) if txt else None), ctype


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

        if False:
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


if __name__ == "__main__":
    unittest.main()
