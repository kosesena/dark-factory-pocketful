#!/usr/bin/env python3
"""Spec-auditor probe suite for Pocketful stage 1.

Every probe is derived from spec/stage-1.md only; requirement ids match
ledger/stage-1.md. Usage: BASE_URL=http://127.0.0.1:8080 python3 probes/run.py
Prints one PASS/FAIL/SKIP line per requirement, exits 1 if any requirement fails.
Standard library only.
"""
import http.client
import json
import os
import re
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

# Requirements the revision under test really breaks (skipped so the suite exits 0).
KNOWN_OPEN = set()

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080").rstrip("/")
_U = urlsplit(BASE)
HOST, PORT = _U.hostname, _U.port or 80
PW = "correct horse"
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")

FIVE_XX = []        # (method, path, status) of every 5xx seen
BAD_ERR_BODY = []   # (method, path, status, body) of 4xx/5xx without the error envelope
BAD_CTYPE = []      # (method, path, content-type) of JSON responses with a wrong type
TIMESTAMPS = []     # every created_at / committed_at seen in a response
_lock = threading.Lock()


class Fail(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Fail(msg)


class R:
    def __init__(self, status, j, headers, raw):
        self.status, self.j, self.headers, self.raw = status, j, headers, raw

    @property
    def code(self):
        try:
            return self.j["error"]["code"]
        except Exception:
            return None

    def __repr__(self):
        return "<%s %s>" % (self.status, self.raw[:300])


def _collect_ts(v):
    if isinstance(v, dict):
        for k, x in v.items():
            if k in ("created_at", "committed_at") and x is not None:
                with _lock:
                    TIMESTAMPS.append(x)
            else:
                _collect_ts(x)
    elif isinstance(v, list):
        for x in v:
            _collect_ts(x)


def H(method, path, body=None, tok=None, key=None, raw=None, extra=None, timeout=20):
    hdrs = {}
    if raw is None and body is not None:
        raw = json.dumps(body).encode("utf-8")
    if raw is not None:
        hdrs["Content-Type"] = "application/json"
    if tok is not None:
        hdrs["Authorization"] = "Bearer " + tok
    if key is not None:
        hdrs["Idempotency-Key"] = key
    hdrs.update(extra or {})
    conn = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    try:
        conn.request(method, path, body=raw, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()
        rh = {k.lower(): v for k, v in resp.getheaders()}
    finally:
        conn.close()
    j = None
    if data:
        try:
            j = json.loads(data.decode("utf-8"))
        except Exception:
            j = None
    r = R(resp.status, j, rh, data)
    with _lock:
        if r.status >= 500:
            FIVE_XX.append((method, path, r.status))
        if r.status >= 400:
            ok = (isinstance(j, dict) and isinstance(j.get("error"), dict)
                  and isinstance(j["error"].get("code"), str)
                  and isinstance(j["error"].get("message"), str))
            if not ok:
                BAD_ERR_BODY.append((method, path, r.status, data[:200]))
        if data and r.status != 204:
            ct = rh.get("content-type", "").replace(" ", "").lower()
            if ct != "application/json;charset=utf-8":
                BAD_CTYPE.append((method, path, rh.get("content-type")))
    _collect_ts(j)
    return r


def K():
    return uuid.uuid4().hex


def expect(r, status, code=None, what=""):
    check(r.status == status and (code is None or r.code == code),
          "%s: expected %s %s, got %r" % (what, status, code or "", r))


# ---------------------------------------------------------------- fixtures

def user(uid, handle, bal, pw=PW):
    return {"id": uid, "email": handle + "@example.com", "password": pw,
            "display_name": handle.capitalize(), "handle": handle, "balance": bal}


def base_fixture(**over):
    fx = {
        "currency": "EUR", "minor_units": 2,
        "users": [user("u_ada", "ada", 10000), user("u_bob", "bob", 2500),
                  user("u_cy", "cy", 0), user("u_dee", "dee", 5000),
                  user("u_eve", "eve", 1000), user("u_op", "op", 0)],
        "payments": [
            {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500,
             "note": "coffee", "visibility": "public"},
            {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 300,
             "note": "secret", "visibility": "private"}],
        "requests": [
            {"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200,
             "note": "taxi", "status": "pending"}],
        "settlement_operator_ids": ["u_op"],
    }
    fx.update(over)
    return fx


class W:
    """A freshly reset world."""

    def __init__(self, fx=None):
        self.fx = fx or base_fixture()
        r = H("POST", "/_test/reset", self.fx, timeout=30)
        check(r.status == 204, "reset failed: %r" % r)
        self.toks = {}
        self.emails = {u["handle"]: (u["email"], u["password"]) for u in self.fx["users"]}
        self.seed_total = sum(u.get("balance", 0) for u in self.fx["users"])

    def t(self, h):
        if h not in self.toks:
            e, p = self.emails[h]
            r = H("POST", "/auth/login", {"email": e, "password": p})
            check(r.status == 200, "login %s failed: %r" % (h, r))
            self.toks[h] = r.j["token"]
        return self.toks[h]

    def signup(self, email, pw="password123", dn="New"):
        r = H("POST", "/auth/signup", {"email": email, "password": pw, "display_name": dn})
        check(r.status == 201, "signup %s failed: %r" % (email, r))
        me = H("GET", "/me", tok=r.j["token"]).j
        self.toks[me["handle"]] = r.j["token"]
        self.emails[me["handle"]] = (email, pw)
        return me["handle"]

    def me(self, h):
        r = H("GET", "/me", tok=self.t(h))
        check(r.status == 200, "/me %s: %r" % (h, r))
        return r.j

    def bal(self, h):
        return self.me(h)["balance"]

    def bals(self):
        return {h: self.bal(h) for h in self.emails}

    def total(self):
        return sum(self.bals().values())

    def pay(self, frm, to, amount, key=None, **kw):
        b = {"to_handle": to, "amount": amount}
        b.update(kw)
        return H("POST", "/payments", b, tok=self.t(frm), key=key or K())

    def req(self, requester, payer, amount, key=None, **kw):
        b = {"payer_handle": payer, "amount": amount}
        b.update(kw)
        return H("POST", "/requests", b, tok=self.t(requester), key=key or K())

    def payreq(self, h, rid, body=None, key=None):
        return H("POST", "/requests/%s/pay" % rid, {} if body is None else body,
                 tok=self.t(h), key=key or K())

    def split(self, h, amount, handles, key=None, **kw):
        b = {"amount": amount, "participant_handles": handles}
        b.update(kw)
        return H("POST", "/splits", b, tok=self.t(h), key=key or K())

    def settle(self, transfers, key=None, h="op"):
        return H("POST", "/settlements", {"transfers": transfers}, tok=self.t(h), key=key or K())

    def feed(self, h, q=""):
        r = H("GET", "/activity" + q, tok=self.t(h))
        check(r.status == 200, "activity: %r" % r)
        return r.j

    def reqs(self, h, q=""):
        r = H("GET", "/requests" + q, tok=self.t(h))
        check(r.status == 200, "requests list: %r" % r)
        return r.j

    def feed_ids(self, h):
        return [p["payment_id"] for p in self.feed(h, "?limit=200")["payments"]]


def tr(f, t, a, **kw):
    d = {"from_handle": f, "to_handle": t, "amount": a}
    d.update(kw)
    return d


def par(fns, workers=50):
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(lambda f: f(), fns))


# ---------------------------------------------------------------- registry

REQS = []


def req(rid, title):
    def deco(fn):
        REQS.append((rid, title, fn))
        return fn
    return deco


# ================================================================= §1 invariants

@req("R01", "sum of balances equals seeded total after mixed and concurrent operations")
def r01():
    w = W()
    for h in ("ada", "bob", "cy", "dee", "eve", "op"):
        w.t(h)
    rq = w.req("bob", "cy", 700).j["request_id"]
    ops = []
    for i in range(30):
        ops.append(lambda i=i: w.pay(["ada", "dee", "bob"][i % 3], ["bob", "cy", "eve"][i % 3], 137 + i))
    ops.append(lambda: w.settle([tr("ada", "cy", 999), tr("cy", "eve", 999)]))
    ops.append(lambda: w.settle([tr("eve", "ada", 50000)]))
    ops.append(lambda: w.split("ada", 1001, ["ada", "bob", "cy"]))
    ops.append(lambda: w.payreq("cy", rq))
    par(ops)
    check(w.total() == w.seed_total, "total %s != seeded %s" % (w.total(), w.seed_total))


@req("R02", "no wallet balance is ever negative under concurrent spending")
def r02():
    w = W()
    ada = w.t("ada")
    seen = []
    stop = threading.Event()

    def poll():
        while not stop.is_set():
            r = H("GET", "/me", tok=ada)
            if r.status == 200:
                seen.append(r.j["balance"])

    th = threading.Thread(target=poll)
    th.start()
    try:
        res = par([lambda: w.pay("ada", "bob", 1000) for _ in range(40)])
    finally:
        stop.set()
        th.join()
    ok = [r for r in res if r.status == 201]
    check(len(ok) == 10, "expected 10 successes of 40, got %d" % len(ok))
    check(all(r.status in (201, 409) for r in res), "unexpected statuses %s" % {r.status for r in res})
    check(all(r.code == "insufficient_funds" for r in res if r.status == 409), "409 code")
    check(min(seen + [0]) >= 0, "negative balance observed %s" % min(seen))
    check(w.bal("ada") == 0, "final balance %s" % w.bal("ada"))
    check(w.total() == w.seed_total, "sum changed")


@req("R03", "a payment request moves money at most once under concurrent pays with distinct keys")
def r03():
    w = W()
    ada = w.t("ada")
    res = par([lambda: H("POST", "/requests/rq_1/pay", {}, tok=ada, key=K()) for _ in range(20)])
    st = sorted(r.status for r in res)
    check(st.count(201) == 1, "201 count %s" % st)
    check(all(r.code == "request_not_pending" for r in res if r.status != 201), "others %s" % st)
    check(w.bal("ada") == 10000 - 1200 and w.bal("bob") == 2500 + 1200, "money moved more than once")
    pays = [p for p in w.feed("ada", "?limit=200")["payments"] if p["request_id"] == "rq_1"]
    check(len(pays) == 1, "payments for rq_1: %d" % len(pays))


@req("R04", "amounts and balances near 2^53 are exact")
def r04():
    big = 2 ** 53 - 1000000001
    fx = base_fixture(users=[user("u_ada", "ada", big), user("u_bob", "bob", 0)],
                      payments=[], requests=[], settlement_operator_ids=[])
    w = W(fx)
    expect(w.pay("ada", "bob", 1000000000), 201, what="pay 1e9")
    expect(w.pay("ada", "bob", 1), 201, what="pay 1")
    check(w.bal("ada") == big - 1000000001, "ada %s" % w.bal("ada"))
    check(w.bal("bob") == 1000000001, "bob %s" % w.bal("bob"))
    w2 = W(base_fixture(users=[user("u_ada", "ada", 2 ** 53 - 1), user("u_bob", "bob", 0)],
                        payments=[], requests=[], settlement_operator_ids=[]))
    expect(w2.pay("ada", "bob", 7), 201)
    check(w2.bal("ada") == 2 ** 53 - 8, "ada %s" % w2.bal("ada"))


@req("R05", "malformed, hostile and concurrent input never produces a 5xx")
def r05():
    w = W()
    ada = w.t("ada")
    bodies = [b"", b"{", b"null", b"[]", b"\"x\"", b"1e999999", b'{"amount": NaN}',
              b'{"to_handle":"bob","amount":1e400}', b'{"to_handle":"bob","amount":-1e-400}',
              b"\xff\xfe", b"[" * 5000 + b"]" * 5000, b'{"to_handle":"bob","amount":{"a":1}}',
              b'{"to_handle":"bob","amount":100,"note":"\\ud800"}',
              b'{"to_handle":["bob"],"amount":1}', b'{"to_handle":"' + b"x" * 100000 + b'","amount":1}']
    paths = ["/payments", "/requests", "/splits", "/settlements", "/requests/rq_1/pay",
             "/auth/signup", "/auth/login", "/_test/import"]
    for p in paths:
        for b in bodies:
            H("POST", p, raw=b, tok=ada if not p.startswith("/auth") else None, key=K())
    for q in ["?limit=99999999999999999999999", "?offset=99999999999999999999999", "?limit=%00",
              "?limit=%ff", "?direction=%ff&status=%C3%A9"]:
        H("GET", "/activity" + q, tok=ada)
        H("GET", "/requests" + q, tok=ada)
    for p in ["/requests/" + "x" * 500 + "/pay", "/requests/%2e%2e/decline", "/requests//cancel"]:
        H("POST", p, {}, tok=ada, key=K())
    H("GET", "/me", extra={"Authorization": "Bearer éé".encode("utf-8").decode("latin-1")})
    check(not FIVE_XX, "5xx responses seen: %s" % FIVE_XX[:5])


# ================================================================= §2/§3 runtime

@req("R06", "GET /health returns 200 {\"status\":\"ok\"}")
def r06():
    r = H("GET", "/health")
    check(r.status == 200 and r.j == {"status": "ok"}, repr(r))


@req("R07", "JSON responses carry Content-Type application/json; charset=utf-8")
def r07():
    w = W()
    H("GET", "/me", tok=w.t("ada"))
    w.pay("ada", "bob", 1)
    H("GET", "/me")
    check(not BAD_CTYPE, "wrong content-type: %s" % BAD_CTYPE[:3])


@req("R08", "timestamps in responses are RFC 3339 with an explicit offset")
def r08():
    w = W()
    w.pay("ada", "bob", 1)
    w.req("ada", "bob", 1)
    w.split("ada", 3, ["ada", "bob"])
    w.settle([tr("ada", "bob", 1)])
    w.feed("ada")
    w.reqs("ada")
    bad = [t for t in TIMESTAMPS if not isinstance(t, str) or not TS_RE.match(t)]
    check(TIMESTAMPS and not bad, "bad timestamps: %s" % bad[:5])


@req("R09", "unknown request-body fields are ignored and cannot redirect money")
def r09():
    w = W()
    r = w.pay("ada", "cy", 100, from_handle="bob", from_user_id="u_bob", currency="JPY",
              request_id="rq_1", settlement_id="x", created_at="1999-01-01T00:00:00+00:00")
    expect(r, 201, what="payment with extra fields")
    check(r.j["from_user_id"] == "u_ada" and r.j["currency"] == "EUR" and r.j["request_id"] is None,
          "extra fields leaked: %r" % r.j)
    check(w.bal("ada") == 9900 and w.bal("bob") == 2500 and w.bal("cy") == 100, "balances")
    expect(w.req("ada", "bob", 5, requester_handle="cy", status="paid"), 201, what="request extra")
    expect(H("POST", "/auth/signup", {"email": "x1@x.io", "password": "password1",
                                      "display_name": "X", "handle": "zzz", "balance": 99}), 201)
    me = H("POST", "/auth/login", {"email": "x1@x.io", "password": "password1", "foo": 1})
    expect(me, 200, what="login extra")
    m = H("GET", "/me", tok=me.j["token"]).j
    check(m["handle"] == "x1" and m["balance"] == 0, "signup honoured extra fields %r" % m)


@req("R10", "unknown query parameters are ignored")
def r10():
    w = W()
    for p in ("/activity?foo=1&bar", "/requests?zzz=9", "/me?x=y"):
        expect(H("GET", p, tok=w.t("ada")), 200, what=p)


@req("R11", "ids are strings of at most 64 characters")
def r11():
    w = W()
    ids = [w.pay("ada", "bob", 1).j["payment_id"], w.req("ada", "bob", 1).j["request_id"],
           w.split("ada", 2, ["ada", "bob"]).j["split_id"], w.settle([tr("ada", "bob", 1)]).j["settlement_id"],
           H("POST", "/auth/signup", {"email": "idz@x.io", "password": "password1",
                                      "display_name": "I"}).j["user_id"]]
    check(all(isinstance(i, str) and 1 <= len(i) <= 64 for i in ids), "ids %r" % ids)


# ================================================================= §3.3/§4 reset & fixture

@req("R12", "reset replaces all state: old tokens, users, payments disappear")
def r12():
    w = W()
    old = w.t("ada")
    hz = w.signup("ghost@x.io")
    w.pay("ada", "bob", 77, note="before-reset")
    fx = base_fixture(users=[user("u_ada", "ada", 50), user("u_zed", "zed", 5)], payments=[],
                      requests=[], settlement_operator_ids=[])
    w2 = W(fx)
    expect(H("GET", "/me", tok=old), 401, "unauthenticated", "old token after reset")
    expect(H("POST", "/auth/login", {"email": "ghost@x.io", "password": "password123"}), 401,
           "unauthenticated", "signed-up user after reset")
    check(w2.bal("ada") == 50, "ada balance %s" % w2.bal("ada"))
    check(w2.feed("ada")["payments"] == [], "feed not empty after reset")
    check(w2.reqs("ada")["requests"] == [], "requests not empty after reset")
    expect(H("POST", "/auth/login", {"email": "bob@example.com", "password": PW}), 401, what="bob gone")
    expect(w2.pay("ada", hz, 1), 404, "not_found", "pay to vanished handle")


@req("R13", "seeded users can log in immediately with the fixture password")
def r13():
    fx = base_fixture()
    fx["users"][0]["password"] = "Sp3cial pässwörd ✓"
    w = W(fx)
    r = H("POST", "/auth/login", {"email": "ada@example.com", "password": "Sp3cial pässwörd ✓"})
    expect(r, 200, what="seeded login")
    check(r.j["user_id"] == "u_ada" and r.j["display_name"] == "Ada" and r.j["token"], repr(r.j))
    m = H("GET", "/me", tok=r.j["token"]).j
    check(m == {"user_id": "u_ada", "display_name": "Ada", "handle": "ada", "balance": 10000,
                "currency": "EUR", "minor_units": 2}, "/me %r" % m)


@req("R14", "seeded balances are already net: seeded payments are not replayed")
def r14():
    w = W()
    check(w.bal("ada") == 10000 and w.bal("bob") == 2500, "balances %s" % w.bals())
    ids = w.feed_ids("ada")
    check("p_1" in ids and "p_2" in ids, "seeded payments missing from feed %s" % ids)
    rq = [r for r in w.reqs("ada")["requests"] if r["request_id"] == "rq_1"]
    check(rq and rq[0]["status"] == "pending" and rq[0]["amount"] == 1200, "seeded request %r" % rq)
    p1 = [p for p in w.feed("cy")["payments"] if p["payment_id"] == "p_1"][0]
    check(p1["from_handle"] == "ada" and p1["to_handle"] == "bob" and p1["amount"] == 500
          and p1["note"] == "coffee" and p1["visibility"] == "public", "p_1 %r" % p1)


@req("R15", "negative fixture balance -> 422 validation_failed and state unchanged")
def r15():
    w = W()
    ada = w.t("ada")
    w.pay("ada", "bob", 10)
    fx = base_fixture()
    fx["users"][2]["balance"] = -1
    expect(H("POST", "/_test/reset", fx), 422, "validation_failed", "negative balance reset")
    r = H("GET", "/me", tok=ada)
    expect(r, 200, what="old token after rejected reset")
    check(r.j["balance"] == 9990, "balance changed %s" % r.j["balance"])


@req("R16", "currency and minor_units come from the fixture (EUR 2, JPY 0, BHD 3)")
def r16():
    for cur, mu in (("JPY", 0), ("BHD", 3), ("EUR", 2)):
        w = W(base_fixture(currency=cur, minor_units=mu))
        m = w.me("ada")
        check(m["currency"] == cur and m["minor_units"] == mu, "/me %r" % m)
        r = w.pay("ada", "bob", 1000)
        check(r.status == 201 and r.j["currency"] == cur and r.j["amount"] == 1000, repr(r))
        check(w.req("ada", "bob", 5).j["currency"] == cur, "request currency")
    for mu in (1, 4, -1, "2"):
        expect(H("POST", "/_test/reset", base_fixture(minor_units=mu)), 422, "validation_failed",
               "minor_units %r" % (mu,))


@req("R17", "repeated resets are supported and the last one wins")
def r17():
    for b in (1, 2, 3):
        fx = base_fixture()
        fx["users"][0]["balance"] = b
        expect(H("POST", "/_test/reset", fx), 204, what="reset")
    w = W.__new__(W)
    w.toks, w.emails = {}, {"ada": ("ada@example.com", PW)}
    check(w.bal("ada") == 3, "balance %s" % w.bal("ada"))


@req("R18", "reset of a 500-user fixture completes within the 10 s reset timeout")
def r18():
    users = [user("u_%d" % i, "h%d" % i, i) for i in range(500)]
    fx = base_fixture(users=users, payments=[], requests=[], settlement_operator_ids=[])
    t0 = time.time()
    r = H("POST", "/_test/reset", fx, timeout=60)
    dt = time.time() - t0
    expect(r, 204, what="large reset")
    check(dt < 10, "reset took %.1fs" % dt)
    lg = H("POST", "/auth/login", {"email": "h499@example.com", "password": PW})
    expect(lg, 200, what="login last user")


# ================================================================= §4/§5 amounts and fields

@req("R19", "integral amounts written 1000, 1000.0 and 1e3 are the same valid amount")
def r19():
    w = W()
    ada = w.t("ada")
    for raw in (b"1000.0", b"1e3", b"1E3", b"10000e-1"):
        r = H("POST", "/payments", raw=b'{"to_handle":"bob","amount":' + raw + b"}", tok=ada, key=K())
        expect(r, 201, what="payment amount %s" % raw)
        check(r.j["amount"] == 1000 and type(r.j["amount"]) is int, "amount echoed %r" % r.j["amount"])
        r = H("POST", "/requests", raw=b'{"payer_handle":"bob","amount":' + raw + b"}", tok=ada, key=K())
        expect(r, 201, what="request amount %s" % raw)
        check(type(r.j["amount"]) is int and r.j["amount"] == 1000, "request amount echoed")
    r = H("POST", "/splits", raw=b'{"participant_handles":["ada","bob"],"amount":1e3}', tok=ada, key=K())
    expect(r, 201, what="split 1e3")
    check([s["amount"] for s in r.j["shares"]] == [500, 500], "shares %r" % r.j["shares"])
    r = H("POST", "/settlements", raw=b'{"transfers":[{"from_handle":"ada","to_handle":"bob","amount":1.0e2}]}',
          tok=w.t("op"), key=K())
    expect(r, 201, what="settlement 1.0e2")
    check(w.bal("ada") == 10000 - 4000 - 100, "ada balance %s" % w.bal("ada"))


def _bad_amounts():
    return [True, False, "1000", None, [1], {"v": 1}, 0, -1, -0.0, 1000000001, 1.5, 0.5, 1e10, "1e3"]


@req("R20", "amount booleans, strings, null and non-integers are 422 on every money path")
def r20():
    w = W()
    rq = w.req("bob", "ada", 5).j["request_id"]
    for a in _bad_amounts():
        expect(w.pay("ada", "bob", a), 422, "validation_failed", "payment amount %r" % (a,))
        expect(w.req("ada", "bob", a), 422, "validation_failed", "request amount %r" % (a,))
        expect(w.split("ada", a, ["ada", "bob"]), 422, "validation_failed", "split amount %r" % (a,))
        expect(w.settle([tr("ada", "bob", a)]), 422, "validation_failed", "settlement amount %r" % (a,))
    check(w.bal("ada") == 10000, "money moved")
    check(len(w.reqs("ada")["requests"]) == 2, "requests created")


@req("R21", "amount boundaries: 1 and 1000000000 valid; 0, -1, 1000000001 invalid (422)")
def r21():
    fx = base_fixture()
    fx["users"][0]["balance"] = 3000000000
    w = W(fx)
    for a in (0, -1, 1000000001, -1000000000):
        expect(w.pay("ada", "bob", a), 422, "validation_failed", "payment %d" % a)
        expect(w.req("ada", "bob", a), 422, "validation_failed", "request %d" % a)
        expect(w.split("ada", a, ["ada", "bob"]), 422, "validation_failed", "split %d" % a)
        expect(w.settle([tr("ada", "bob", a)]), 422, "validation_failed", "settle %d" % a)
    for a in (1, 1000000000):
        expect(w.pay("ada", "bob", a), 201, what="payment %d" % a)
        expect(w.req("ada", "bob", a), 201, what="request %d" % a)
        expect(w.split("ada", a, ["ada", "bob"]), 201, what="split %d" % a)
        expect(w.settle([tr("ada", "bob", a)]), 201, what="settle %d" % a)


@req("R22", "note: non-string (incl. null) or >200 chars is 422; exactly 200 is accepted")
def r22():
    w = W()
    rq = w.req("bob", "ada", 5).j["request_id"]
    for n in (None, 5, True, ["x"], {"a": 1}, "x" * 201, "é" * 201):
        expect(w.pay("ada", "bob", 1, note=n), 422, "validation_failed", "payment note %r" % (n,))
        expect(w.req("ada", "bob", 1, note=n), 422, "validation_failed", "request note %r" % (n,))
        expect(w.split("ada", 2, ["ada", "bob"], note=n), 422, "validation_failed", "split note")
        expect(w.settle([tr("ada", "bob", 1, note=n)]), 422, "validation_failed", "settle note")
    for n in ("x" * 200, "é" * 200, "😀" * 200):
        r = w.pay("ada", "bob", 1, note=n)
        expect(r, 201, what="payment note len 200 (%s)" % n[0])
        check(r.j["note"] == n, "note altered")
        expect(w.req("ada", "bob", 1, note=n), 201, what="request note 200")
        expect(w.split("ada", 2, ["ada", "bob"], note=n), 201, what="split note 200")
    check(w.bal("ada") == 10000 - 3, "balance %s" % w.bal("ada"))


@req("R23", "visibility other than public/private is 422 on payment, pay and settlement")
def r23():
    w = W()
    for v in (None, "PUBLIC", "Private", "", "friends", 1, True, ["public"]):
        expect(w.pay("ada", "bob", 1, visibility=v), 422, "validation_failed", "payment vis %r" % (v,))
        expect(w.payreq("ada", "rq_1", {"visibility": v}), 422, "validation_failed", "pay vis %r" % (v,))
        expect(w.settle([tr("ada", "bob", 1, visibility=v)]), 422, "validation_failed", "settle vis")
    check(w.bal("ada") == 10000, "money moved")
    rq = [r for r in w.reqs("ada")["requests"] if r["request_id"] == "rq_1"][0]
    check(rq["status"] == "pending", "rq_1 changed")


@req("R24", "omitted note defaults to \"\" and omitted visibility to public")
def r24():
    w = W()
    r = w.pay("ada", "bob", 1)
    check(r.j["note"] == "" and r.j["visibility"] == "public", "payment defaults %r" % r.j)
    r = w.req("ada", "bob", 1)
    check(r.j["note"] == "", "request note default %r" % r.j)
    r = w.payreq("ada", "rq_1", {})
    check(r.j["visibility"] == "public", "pay default visibility %r" % r.j)
    r = w.split("ada", 4, ["ada", "bob"])
    check(r.j["note"] == "" and r.j["requests"][0]["note"] == "", "split note default")
    r = w.settle([tr("ada", "bob", 1)])
    check(r.j["payments"][0]["note"] == "" and r.j["payments"][0]["visibility"] == "public", "settle defaults")


@req("R25", "note is stored and returned verbatim (unicode, emoji, whitespace, markup)")
def r25():
    w = W()
    n = "  héllo 👋🏽 مرحبا\n\t<b>&amp;</b> \"q\" \\ 'x'  ​  Ω≈ç "
    r = w.pay("ada", "bob", 1, note=n)
    check(r.j["note"] == n, "payment response note %r" % r.j["note"])
    got = [p for p in w.feed("bob")["payments"] if p["payment_id"] == r.j["payment_id"]][0]["note"]
    check(got == n, "feed note %r" % got)
    r = w.req("ada", "bob", 1, note=n)
    got = [x for x in w.reqs("bob")["requests"] if x["request_id"] == r.j["request_id"]][0]["note"]
    check(got == n, "request note %r" % got)
    pr = w.payreq("bob", r.j["request_id"])
    check(pr.j["note"] == n, "request payment note %r" % pr.j["note"])
    r = w.split("ada", 4, ["ada", "bob"], note=n)
    check(r.j["note"] == n and r.j["requests"][0]["note"] == n, "split note")
    raw = H("GET", "/activity?limit=1", tok=w.t("ada")).raw.decode("utf-8")
    check(json.loads(raw)["payments"][0]["note"] == n, "raw decode")


# ================================================================= §5 errors

@req("R26", "every 4xx/5xx response carries {\"error\":{\"code\",\"message\"}}")
def r26():
    W()
    H("GET", "/me")
    H("GET", "/nope")
    H("POST", "/payments", raw=b"{", tok="x", key="k")
    check(not BAD_ERR_BODY, "responses without error envelope: %s" % BAD_ERR_BODY[:3])


@req("R27", "unparseable or non-object body is 400 malformed_request")
def r27():
    w = W()
    ada = w.t("ada")
    for raw in (b"{", b"not json", b"[]", b"\"str\"", b"42", b"null", b"\xff\xfe\x00"):
        for p in ("/payments", "/requests", "/splits"):
            expect(H("POST", p, raw=raw, tok=ada, key=K()), 400, "malformed_request", "%s %r" % (p, raw))
        expect(H("POST", "/settlements", raw=raw, tok=w.t("op"), key=K()), 400, "malformed_request",
               "settle %r" % raw)
        expect(H("POST", "/auth/signup", raw=raw), 400, "malformed_request", "signup %r" % raw)
        expect(H("POST", "/auth/login", raw=raw), 400, "malformed_request", "login %r" % raw)
        expect(H("POST", "/_test/reset", raw=raw), 400, "malformed_request", "reset %r" % raw)
        expect(H("POST", "/_test/import", raw=raw), 400, "malformed_request", "import %r" % raw)
    check(w.bal("ada") == 10000, "state changed")


@req("R28", "a non-amount/note/visibility field of the wrong JSON type is 400 malformed_request")
def r28():
    w = W()
    expect(w.pay("ada", 5, 1), 400, "malformed_request", "to_handle number")
    expect(w.pay("ada", None, 1), 400, "malformed_request", "to_handle null")
    expect(w.pay("ada", ["bob"], 1), 400, "malformed_request", "to_handle list")
    expect(w.req("ada", {"h": "bob"}, 1), 400, "malformed_request", "payer_handle object")
    expect(w.split("ada", 2, "ada,bob"), 400, "malformed_request", "participant_handles string")
    expect(w.split("ada", 2, ["ada", 7]), 400, "malformed_request", "participant_handles element")
    expect(H("POST", "/auth/signup", {"email": 5, "password": "password1", "display_name": "x"}),
           400, "malformed_request", "signup email number")
    expect(H("POST", "/auth/signup", {"email": "q@q.io", "password": 12345678, "display_name": "x"}),
           400, "malformed_request", "signup password number")
    expect(H("POST", "/auth/login", {"email": "ada@example.com", "password": None}),
           400, "malformed_request", "login password null")


@req("R29", "a missing required field is 422 validation_failed")
def r29():
    w = W()
    ada = w.t("ada")
    expect(H("POST", "/payments", {"amount": 1}, tok=ada, key=K()), 422, "validation_failed", "no to_handle")
    expect(H("POST", "/payments", {"to_handle": "bob"}, tok=ada, key=K()), 422, "validation_failed", "no amount")
    expect(H("POST", "/requests", {"amount": 1}, tok=ada, key=K()), 422, "validation_failed", "no payer_handle")
    expect(H("POST", "/requests", {"payer_handle": "bob"}, tok=ada, key=K()), 422, "validation_failed", "no amount")
    expect(H("POST", "/splits", {"amount": 1}, tok=ada, key=K()), 422, "validation_failed", "no handles")
    expect(H("POST", "/splits", {"participant_handles": ["bob"]}, tok=ada, key=K()), 422,
           "validation_failed", "split no amount")
    expect(H("POST", "/auth/signup", {"email": "m@m.io", "display_name": "M"}), 422,
           "validation_failed", "signup no password")
    expect(H("POST", "/auth/signup", {"password": "password1", "display_name": "M"}), 422,
           "validation_failed", "signup no email")
    expect(H("POST", "/auth/login", {"email": "ada@example.com"}), 422, "validation_failed", "login no password")
    expect(w.settle([{"from_handle": "ada", "to_handle": "bob"}]), 422, "validation_failed", "settle no amount")
    expect(H("POST", "/settlements", {}, tok=w.t("op"), key=K()), 422, "validation_failed", "no transfers")


@req("R30", "unknown handle is 404 not_found and leaves no trace")
def r30():
    w = W()
    n0 = len(w.feed_ids("ada"))
    for h in ("nobody", "ADA", "ada ", "", "a" * 21):
        r = w.pay("ada", h, 1)
        check(r.status in (404, 422) if h in ("",) else r.status == 404 and r.code == "not_found",
              "payment to %r: %r" % (h, r))
        r = w.req("ada", h, 1)
        check(r.status in (404, 422) if h in ("",) else r.status == 404 and r.code == "not_found",
              "request to %r: %r" % (h, r))
    expect(w.split("ada", 2, ["ada", "nobody"]), 404, "not_found", "split unknown")
    check(w.bal("ada") == 10000 and len(w.feed_ids("ada")) == n0, "trace left")
    check(len(w.reqs("ada")["requests"]) == 1, "request created")


# ================================================================= §6 auth

@req("R31", "signup returns 201 {user_id, display_name, token}; token works")
def r31():
    W()
    r = H("POST", "/auth/signup", {"email": "neo@matrix.io", "password": "password1", "display_name": "Neo"})
    expect(r, 201, what="signup")
    check(set(r.j) >= {"user_id", "display_name", "token"} and r.j["display_name"] == "Neo", repr(r.j))
    m = H("GET", "/me", tok=r.j["token"]).j
    check(m["user_id"] == r.j["user_id"] and m["handle"] == "neo" and m["balance"] == 0
          and m["display_name"] == "Neo" and m["currency"] == "EUR" and m["minor_units"] == 2, "/me %r" % m)


@req("R32", "login returns 200 with a new token; several tokens stay valid at once")
def r32():
    w = W()
    toks = []
    for _ in range(3):
        r = H("POST", "/auth/login", {"email": "ada@example.com", "password": PW})
        expect(r, 200, what="login")
        check(r.j["user_id"] == "u_ada" and r.j["display_name"] == "Ada", repr(r.j))
        toks.append(r.j["token"])
    s = H("POST", "/auth/signup", {"email": "multi@x.io", "password": "password1", "display_name": "M"}).j["token"]
    l2 = H("POST", "/auth/login", {"email": "multi@x.io", "password": "password1"}).j["token"]
    for t in toks + [s, l2]:
        expect(H("GET", "/me", tok=t), 200, what="token valid")
    res = par([lambda t=t: H("GET", "/me", tok=t) for t in toks * 5])
    check(all(r.status == 200 for r in res), "concurrent sessions")


@req("R33", "signup with an already registered email is 409 email_taken")
def r33():
    W()
    expect(H("POST", "/auth/signup", {"email": "ada@example.com", "password": "otherpass1",
                                      "display_name": "A2"}), 409, "email_taken", "seeded email")
    H("POST", "/auth/signup", {"email": "twice@x.io", "password": "password1", "display_name": "T"})
    expect(H("POST", "/auth/signup", {"email": "twice@x.io", "password": "password1", "display_name": "T"}),
           409, "email_taken", "repeat signup")
    expect(H("POST", "/auth/login", {"email": "ada@example.com", "password": "otherpass1"}), 401,
           "unauthenticated", "password not overwritten")


@req("R34", "password shorter than 8 characters is 422; exactly 8 is accepted")
def r34():
    W()
    for pw in ("", "1234567", "short"):
        expect(H("POST", "/auth/signup", {"email": "p%d@x.io" % len(pw), "password": pw, "display_name": "P"}),
               422, "validation_failed", "password %r" % pw)
    expect(H("POST", "/auth/signup", {"email": "p8@x.io", "password": "12345678", "display_name": "P"}),
           201, what="password of 8")
    expect(H("POST", "/auth/login", {"email": "p7@x.io", "password": "1234567"}), 401, what="no account")


@req("R35", "email not of the form local@domain is 422 validation_failed")
def r35():
    W()
    for e in ("plainaddress", "@domain.com", "local@", "", "@"):
        expect(H("POST", "/auth/signup", {"email": e, "password": "password1", "display_name": "E"}),
               422, "validation_failed", "email %r" % e)


@req("R36", "wrong password or unknown email on login is 401 unauthenticated")
def r36():
    W()
    expect(H("POST", "/auth/login", {"email": "ada@example.com", "password": "wrong horse"}), 401,
           "unauthenticated", "wrong pw")
    expect(H("POST", "/auth/login", {"email": "nobody@example.com", "password": PW}), 401,
           "unauthenticated", "unknown email")
    expect(H("POST", "/auth/login", {"email": "ada@example.com", "password": "correct hors"}), 401,
           "unauthenticated", "prefix pw")


@req("R37", "derived handle: local part lowercased, non [a-z0-9_] -> _, truncated to 20")
def r37():
    w = W()
    cases = {"Mary.Jane-Watson+Spider@x.com": "mary_jane_watson_spi",
             "UPPER_case9@x.io": "upper_case9",
             "a.b@x.io": "a_b",
             "abcdefghijklmnopqrstuvwxyz@x.io": "abcdefghijklmnopqrst",
             "Zoë.Ünïcode@x.io": "zo___n_code"}
    for email, want in cases.items():
        r = H("POST", "/auth/signup", {"email": email, "password": "password1", "display_name": "D"})
        expect(r, 201, what="signup %s" % email)
        m = H("GET", "/me", tok=r.j["token"]).j
        check(m["handle"] == want, "%s -> %r, want %r" % (email, m["handle"], want))
    expect(w.pay("ada", "mary_jane_watson_spi", 5), 201, what="pay derived handle")


@req("R38", "derived handle already taken is 409 handle_taken and no account is created")
def r38():
    W()
    expect(H("POST", "/auth/signup", {"email": "ADA@elsewhere.org", "password": "password1",
                                      "display_name": "A"}), 409, "handle_taken", "handle collision")
    expect(H("POST", "/auth/login", {"email": "ADA@elsewhere.org", "password": "password1"}), 401,
           "unauthenticated", "account created anyway")
    H("POST", "/auth/signup", {"email": "x.y@a.io", "password": "password1", "display_name": "A"})
    expect(H("POST", "/auth/signup", {"email": "x-y@b.io", "password": "password1", "display_name": "B"}),
           409, "handle_taken", "x-y collides with x.y")
    expect(H("POST", "/auth/login", {"email": "x-y@b.io", "password": "password1"}), 401, what="no account")


@req("R39", "new users start at 0 and can receive and be asked for money immediately")
def r39():
    w = W()
    h = w.signup("fresh@x.io")
    check(w.bal(h) == 0, "start balance")
    expect(w.req("ada", h, 500), 201, what="request to new user")
    expect(w.pay("ada", h, 300), 201, what="pay new user")
    check(w.bal(h) == 300, "balance %s" % w.bal(h))
    expect(w.pay(h, "ada", 301), 409, "insufficient_funds", "overspend")


@req("R40", "missing, malformed or unknown bearer token is 401 on every protected endpoint")
def r40():
    W()
    eps = [("GET", "/me", None), ("POST", "/payments", {"to_handle": "bob", "amount": 1}),
           ("POST", "/requests", {"payer_handle": "bob", "amount": 1}),
           ("POST", "/requests/rq_1/pay", {}), ("POST", "/requests/rq_1/decline", {}),
           ("POST", "/requests/rq_1/cancel", {}), ("GET", "/requests", None),
           ("POST", "/splits", {"amount": 2, "participant_handles": ["ada"]}), ("GET", "/activity", None),
           ("POST", "/settlements", {"transfers": [tr("ada", "bob", 1)]})]
    for auth in (None, "Bearer", "Bearer ", "Bearer nope", "Basic YWRhOnB3", "nope"):
        for m, p, b in eps:
            extra = {"Authorization": auth} if auth is not None else {}
            r = H(m, p, b, key=K(), extra=extra)
            expect(r, 401, "unauthenticated", "%s %s auth=%r" % (m, p, auth))


@req("R41", "passwords are not stored in plaintext (export state holds no plaintext password)")
def r41():
    fx = base_fixture()
    fx["users"][0]["password"] = "Sentinel-Fixture-Pw-7731"
    W(fx)
    H("POST", "/auth/signup", {"email": "sent@x.io", "password": "Sentinel-Signup-Pw-9124", "display_name": "S"})
    r = H("GET", "/_test/export")
    expect(r, 200, what="export")
    txt = r.raw.decode("utf-8")
    check("Sentinel-Fixture-Pw-7731" not in txt and "Sentinel-Signup-Pw-9124" not in txt,
          "plaintext password present in exported state")


# ================================================================= §7 idempotency

def five_paths(w):
    """(name, path, token, body) for each idempotent write path, ready for a first use."""
    rid = w.req("bob", "ada", 10).j["request_id"]
    return [("payments", "/payments", w.t("ada"), {"to_handle": "bob", "amount": 11}),
            ("requests", "/requests", w.t("ada"), {"payer_handle": "bob", "amount": 12}),
            ("pay", "/requests/%s/pay" % rid, w.t("ada"), {"visibility": "private"}),
            ("splits", "/splits", w.t("ada"), {"amount": 13, "participant_handles": ["ada", "bob"]}),
            ("settlements", "/settlements", w.t("op"), {"transfers": [tr("ada", "bob", 14)]})]


@req("R42", "absent or empty Idempotency-Key is 400 missing_idempotency_key on all five paths")
def r42():
    w = W()
    for name, p, tok, b in five_paths(w):
        expect(H("POST", p, b, tok=tok), 400, "missing_idempotency_key", name + " absent")
        expect(H("POST", p, b, tok=tok, key=""), 400, "missing_idempotency_key", name + " empty")
    check(w.bal("ada") == 10000, "money moved without key")


@req("R43", "Idempotency-Key of 1 and 255 characters accepted; 256 is 422")
def r43():
    w = W()
    for name, p, tok, b in five_paths(w):
        expect(H("POST", p, b, tok=tok, key="k" * 256), 422, "validation_failed", name + " 256")
    w = W()
    for (name, p, tok, b), key in zip(five_paths(w), ["a", "z" * 255, "b", "y" * 255, "c"]):
        expect(H("POST", p, b, tok=tok, key=key), 201, what="%s key len %d" % (name, len(key)))
        expect(H("POST", p, b, tok=tok, key=key), 200, what="%s replay len %d" % (name, len(key)))


@req("R44", "first use 201; replay 200 with an identical body and no further state change")
def r44():
    w = W()
    for name, p, tok, b in five_paths(w):
        k = K()
        r1 = H("POST", p, b, tok=tok, key=k)
        expect(r1, 201, what=name + " first")
        bals, nreq, nfeed = w.bals(), len(w.reqs("bob")["requests"]), len(w.feed_ids("ada"))
        for _ in range(2):
            r2 = H("POST", p, b, tok=tok, key=k)
            expect(r2, 200, what=name + " replay")
            check(r2.j == r1.j, "%s replay body differs" % name)
        check(w.bals() == bals, "%s replay moved money" % name)
        check(len(w.reqs("bob")["requests"]) == nreq and len(w.feed_ids("ada")) == nfeed,
              "%s replay created records" % name)


@req("R45", "same key with a different body is 409 idempotency_key_reuse")
def r45():
    w = W()
    for name, p, tok, b in five_paths(w):
        k = K()
        expect(H("POST", p, b, tok=tok, key=k), 201, what=name)
        b2 = dict(b)
        b2["note"] = "different"
        expect(H("POST", p, b2, tok=tok, key=k), 409, "idempotency_key_reuse", name + " changed body")


@req("R46", "same body means same JSON value: key order and whitespace do not matter")
def r46():
    w = W()
    ada = w.t("ada")
    k = K()
    r1 = H("POST", "/payments", raw=b'{"to_handle":"bob","amount":5,"note":"n"}', tok=ada, key=k)
    expect(r1, 201)
    r2 = H("POST", "/payments", raw=b'{ "note" : "n",\n  "amount": 5, "to_handle":"bob" }', tok=ada, key=k)
    expect(r2, 200, what="reordered replay")
    check(r1.j == r2.j, "replay body")
    check(w.bal("ada") == 9995, "balance %s" % w.bal("ada"))


@req("R47", "keys are scoped per user: two users may use the same key independently")
def r47():
    w = W()
    k = "shared-key"
    r1 = w.pay("ada", "cy", 5, key=k)
    r2 = w.pay("bob", "cy", 5, key=k)
    r3 = w.pay("dee", "cy", 6, key=k)
    expect(r1, 201)
    expect(r2, 201, what="other user same key same body")
    expect(r3, 201, what="other user same key other body")
    check(r1.j["payment_id"] != r2.j["payment_id"], "shared result")
    check(w.bal("cy") == 16, "cy %s" % w.bal("cy"))


@req("R48", "same key and body on a different path is a new request, not a replay")
def r48():
    w = W()
    a = w.req("bob", "ada", 10).j["request_id"]
    b = w.req("bob", "ada", 20).j["request_id"]
    k = K()
    expect(w.payreq("ada", a, {}, key=k), 201)
    r = w.payreq("ada", b, {}, key=k)
    expect(r, 201, what="other path same key")
    check(r.j["request_id"] == b and r.j["amount"] == 20, repr(r.j))
    expect(w.req("ada", "bob", 7, key=k), 201, what="POST /requests with key used on pay")
    check(w.bal("ada") == 10000 - 30, "balance")


@req("R49", "a key whose original request failed with 4xx is treated as a first use")
def r49():
    w = W()
    k = K()
    expect(w.pay("cy", "ada", 100, key=k), 409, "insufficient_funds")
    w.pay("ada", "cy", 100)
    expect(w.pay("cy", "ada", 100, key=k), 201, what="same body after funding")
    k2 = K()
    expect(w.pay("ada", "nobody", 5, key=k2), 404)
    expect(w.pay("ada", "bob", 5, key=k2), 201, what="different body after 404")
    k3 = K()
    expect(w.payreq("cy", "rq_1", {}, key=k3), 403)
    expect(w.req("ada", "bob", 1, key=k3), 201)
    k4 = K()
    expect(w.settle([tr("cy", "ada", 1)], key=k4), 409, "insufficient_funds")
    expect(w.settle([tr("ada", "cy", 1)], key=k4), 201, what="settlement key after 409")
    k5 = K()
    expect(w.split("ada", 0, ["bob"], key=k5), 422)
    expect(w.split("ada", 4, ["bob"], key=k5), 201, what="split key after 422")


@req("R50", "concurrent identical requests with an unused key: one 201, the rest 200, effect once")
def r50():
    w = W()
    ada = w.t("ada")
    k = K()
    res = par([lambda: H("POST", "/payments", {"to_handle": "bob", "amount": 100}, tok=ada, key=k)
               for _ in range(25)])
    st = sorted(r.status for r in res)
    check(st.count(201) == 1 and st.count(200) == 24, "statuses %s" % st)
    check(all(r.j == res[0].j for r in res), "bodies differ")
    check(w.bal("ada") == 9900, "balance %s" % w.bal("ada"))
    k = K()
    res = par([lambda: H("POST", "/requests/rq_1/pay", {}, tok=ada, key=k) for _ in range(25)])
    st = sorted(r.status for r in res)
    check(st.count(201) == 1 and st.count(200) == 24, "pay statuses %s" % st)
    check(w.bal("ada") == 9900 - 1200, "balance after pay %s" % w.bal("ada"))
    k = K()
    op = w.t("op")
    res = par([lambda: H("POST", "/settlements", {"transfers": [tr("dee", "cy", 7)]}, tok=op, key=k)
               for _ in range(25)])
    st = sorted(r.status for r in res)
    check(st.count(201) == 1 and st.count(200) == 24, "settle statuses %s" % st)
    check(w.bal("cy") == 7, "cy %s" % w.bal("cy"))
    k = K()
    res = par([lambda: H("POST", "/splits", {"amount": 9, "participant_handles": ["bob", "cy"]}, tok=ada, key=k)
               for _ in range(25)])
    st = sorted(r.status for r in res)
    check(st.count(201) == 1 and st.count(200) == 24, "split statuses %s" % st)
    check(len(w.reqs("cy", "?direction=incoming")["requests"]) == 1, "split requests duplicated")


@req("R51", "a replay returns the original response even after the resource changed")
def r51():
    w = W()
    k = K()
    r1 = w.req("ada", "bob", 50, key=k)
    rid = r1.j["request_id"]
    expect(H("POST", "/requests/%s/cancel" % rid, {}, tok=w.t("ada")), 200)
    r2 = w.req("ada", "bob", 50, key=k)
    expect(r2, 200, what="replay after cancel")
    check(r2.j == r1.j and r2.j["status"] == "pending", "replay body %r" % r2.j)
    k = K()
    s1 = w.split("ada", 30, ["ada", "bob"], key=k)
    w.payreq("bob", s1.j["requests"][0]["request_id"])
    s2 = w.split("ada", 30, ["ada", "bob"], key=k)
    expect(s2, 200)
    check(s2.j == s1.j, "split replay changed")


@req("R52", "a claimed key is resolved before validation: an invalid body with it is 409")
def r52():
    w = W()
    k = K()
    expect(w.pay("ada", "bob", 5, key=k), 201)
    for bad in ({"to_handle": "bob", "amount": -5}, {"to_handle": "nobody", "amount": 5},
                {"to_handle": "ada", "amount": 5}, {"to_handle": "bob", "amount": 10 ** 12},
                {"amount": 5}, {"to_handle": 9, "amount": 5}):
        expect(H("POST", "/payments", bad, tok=w.t("ada"), key=k), 409, "idempotency_key_reuse", "%r" % bad)
    k = K()
    expect(w.payreq("ada", "rq_1", {}, key=k), 201)
    expect(w.payreq("ada", "rq_1", {"visibility": "secret"}, key=k), 409, "idempotency_key_reuse", "pay")
    k = K()
    expect(w.settle([tr("ada", "bob", 1)], key=k), 201)
    expect(w.settle([tr("ada", "nobody", 1)], key=k), 409, "idempotency_key_reuse", "settle")
    expect(w.settle([], key=k), 409, "idempotency_key_reuse", "settle empty")


# ================================================================= §8 payments

@req("R53", "POST /payments 201 returns the payment and moves money atomically")
def r53():
    w = W()
    r = w.pay("ada", "bob", 1500, note="dinner", visibility="public")
    expect(r, 201)
    j = r.j
    want = {"from_user_id": "u_ada", "from_handle": "ada", "to_user_id": "u_bob", "to_handle": "bob",
            "amount": 1500, "currency": "EUR", "note": "dinner", "visibility": "public", "request_id": None}
    check(all(j.get(k) == v for k, v in want.items()) and "payment_id" in j and "created_at" in j,
          "body %r" % j)
    check(w.bal("ada") == 8500 and w.bal("bob") == 4000, "balances")
    for h in ("ada", "bob", "cy"):
        f = [p for p in w.feed(h)["payments"] if p["payment_id"] == j["payment_id"]]
        check(f and f[0] == j or (f and {k: f[0][k] for k in j} == j), "%s feed item differs %r" % (h, f))


@req("R54", "insufficient funds is 409 and the failed payment leaves no trace")
def r54():
    w = W()
    n0 = w.feed_ids("ada")
    expect(w.pay("ada", "bob", 10001), 409, "insufficient_funds")
    expect(w.pay("cy", "bob", 1), 409, "insufficient_funds")
    check(w.bal("ada") == 10000 and w.bal("bob") == 2500 and w.bal("cy") == 0, "balances changed")
    check(w.feed_ids("ada") == n0 and w.feed_ids("bob") == n0, "feed changed")


@req("R55", "paying your own handle is 422 self_payment")
def r55():
    w = W()
    expect(w.pay("ada", "ada", 1), 422, "self_payment")
    expect(w.pay("cy", "cy", 1), 422, "self_payment", "self pay with zero balance")
    check(w.bal("ada") == 10000, "balance")


@req("R56", "a payment of exactly the whole balance is allowed (balance reaches 0)")
def r56():
    w = W()
    expect(w.pay("eve", "ada", 1000), 201)
    check(w.bal("eve") == 0, "eve %s" % w.bal("eve"))


# ================================================================= §8 requests

@req("R57", "POST /requests 201 returns a pending request with payment_id null")
def r57():
    w = W()
    r = w.req("bob", "ada", 1200, note="taxi")
    expect(r, 201)
    want = {"requester_id": "u_bob", "requester_handle": "bob", "payer_id": "u_ada", "payer_handle": "ada",
            "amount": 1200, "currency": "EUR", "note": "taxi", "status": "pending", "payment_id": None}
    check(all(r.j.get(k) == v for k, v in want.items()) and r.j.get("request_id") and r.j.get("created_at"),
          repr(r.j))
    check(w.bal("ada") == 10000 and w.bal("bob") == 2500, "request moved money")


@req("R58", "a request may exceed the payer's balance and is created normally")
def r58():
    w = W()
    r = w.req("ada", "cy", 1000000000)
    expect(r, 201)
    check(r.j["status"] == "pending", repr(r.j))


@req("R59", "requesting from your own handle is 422 self_request")
def r59():
    w = W()
    expect(w.req("ada", "ada", 1), 422, "self_request")


@req("R60", "paying a request: 201 payment with request_id; request becomes paid with payment_id")
def r60():
    w = W()
    r = w.payreq("ada", "rq_1", {"visibility": "private"})
    expect(r, 201)
    j = r.j
    want = {"from_user_id": "u_ada", "from_handle": "ada", "to_user_id": "u_bob", "to_handle": "bob",
            "amount": 1200, "currency": "EUR", "note": "taxi", "visibility": "private", "request_id": "rq_1"}
    check(all(j.get(k) == v for k, v in want.items()) and j.get("payment_id"), repr(j))
    check(w.bal("ada") == 8800 and w.bal("bob") == 3700, "balances")
    for h in ("ada", "bob"):
        rq = [x for x in w.reqs(h)["requests"] if x["request_id"] == "rq_1"][0]
        check(rq["status"] == "paid" and rq["payment_id"] == j["payment_id"], "%s sees %r" % (h, rq))


@req("R61", "paying while short is 409 and changes nothing; it becomes payable when money arrives")
def r61():
    w = W()
    rid = w.req("ada", "cy", 500).j["request_id"]
    expect(w.payreq("cy", rid), 409, "insufficient_funds")
    rq = [x for x in w.reqs("cy")["requests"] if x["request_id"] == rid][0]
    check(rq["status"] == "pending" and rq["payment_id"] is None, "request changed %r" % rq)
    check(w.bal("ada") == 10000 and w.bal("cy") == 0, "money moved")
    w.pay("dee", "cy", 500)
    expect(w.payreq("cy", rid), 201, what="pay after funding")
    check(w.bal("cy") == 0 and w.bal("ada") == 10500, "balances")


@req("R62", "only the payer may pay: requester or third party is 403 forbidden")
def r62():
    w = W()
    expect(w.payreq("bob", "rq_1"), 403, "forbidden", "requester pays")
    expect(w.payreq("dee", "rq_1"), 403, "forbidden", "third party pays")
    expect(w.payreq("op", "rq_1"), 403, "forbidden", "operator pays")
    check(w.bal("ada") == 10000 and w.bal("dee") == 5000, "money moved")


@req("R63", "paying, declining or cancelling an unknown request is 404 not_found")
def r63():
    w = W()
    expect(w.payreq("ada", "rq_nope"), 404, "not_found", "pay")
    expect(H("POST", "/requests/rq_nope/decline", {}, tok=w.t("ada")), 404, "not_found", "decline")
    expect(H("POST", "/requests/rq_nope/cancel", {}, tok=w.t("ada")), 404, "not_found", "cancel")


@req("R64", "paying a non-pending request (paid/declined/cancelled) is 409 request_not_pending")
def r64():
    w = W()
    expect(w.payreq("ada", "rq_1"), 201)
    expect(w.payreq("ada", "rq_1"), 409, "request_not_pending", "paid, new key")
    d = w.req("bob", "ada", 5).j["request_id"]
    H("POST", "/requests/%s/decline" % d, {}, tok=w.t("ada"))
    expect(w.payreq("ada", d), 409, "request_not_pending", "declined")
    c = w.req("bob", "ada", 5).j["request_id"]
    H("POST", "/requests/%s/cancel" % c, {}, tok=w.t("bob"))
    expect(w.payreq("ada", c), 409, "request_not_pending", "cancelled")
    check(w.bal("ada") == 8800, "balance %s" % w.bal("ada"))
    fx = base_fixture(requests=[{"id": "rq_9", "requester_id": "u_bob", "payer_id": "u_ada",
                                 "amount": 5, "note": "", "status": "paid"}])
    w2 = W(fx)
    expect(w2.payreq("ada", "rq_9"), 409, "request_not_pending", "seeded paid")


@req("R65", "replaying a successful pay returns 200 with the original payment, never 409")
def r65():
    w = W()
    k = K()
    r1 = w.payreq("ada", "rq_1", {"visibility": "private"}, key=k)
    expect(r1, 201)
    for _ in range(3):
        r2 = w.payreq("ada", "rq_1", {"visibility": "private"}, key=k)
        expect(r2, 200, what="replay of paid")
        check(r2.j == r1.j, "body differs")
    check(w.bal("ada") == 8800 and w.bal("bob") == 3700, "extra money moved")


@req("R66", "pay replay must send the identical body: {} vs {\"visibility\":\"public\"} is 409")
def r66():
    w = W()
    k = K()
    expect(w.payreq("ada", "rq_1", {}, key=k), 201)
    expect(w.payreq("ada", "rq_1", {"visibility": "public"}, key=k), 409, "idempotency_key_reuse")
    rid = w.req("bob", "ada", 3).j["request_id"]
    k = K()
    expect(w.payreq("ada", rid, {"visibility": "public"}, key=k), 201)
    expect(w.payreq("ada", rid, {}, key=k), 409, "idempotency_key_reuse", "reverse")


@req("R67", "visibility of a request payment is the payer's choice and follows the feed rule")
def r67():
    w = W()
    r = w.payreq("ada", "rq_1", {"visibility": "private"})
    pid = r.j["payment_id"]
    for h, vis in (("ada", True), ("bob", True), ("cy", False), ("op", False)):
        check((pid in w.feed_ids(h)) == vis, "%s visibility of private request payment" % h)
    bobs = [p for p in w.feed("bob")["payments"] if p["payment_id"] == pid][0]
    check(bobs["visibility"] == "private", "requester sees %r" % bobs["visibility"])


@req("R68", "decline: payer only, 200 declined, twice is 200, paid/cancelled is 409")
def r68():
    w = W()
    expect(H("POST", "/requests/rq_1/decline", {}, tok=w.t("bob")), 403, "forbidden", "requester declines")
    expect(H("POST", "/requests/rq_1/decline", {}, tok=w.t("cy")), 403, "forbidden", "third party")
    r = H("POST", "/requests/rq_1/decline", {}, tok=w.t("ada"))
    expect(r, 200)
    check(r.j["status"] == "declined" and r.j["request_id"] == "rq_1" and r.j["amount"] == 1200, repr(r.j))
    r2 = H("POST", "/requests/rq_1/decline", {}, tok=w.t("ada"))
    expect(r2, 200, what="decline twice")
    check(r2.j["status"] == "declined", repr(r2.j))
    expect(H("POST", "/requests/rq_1/cancel", {}, tok=w.t("bob")), 409, "request_not_pending", "cancel declined")
    p = w.req("bob", "ada", 5).j["request_id"]
    w.payreq("ada", p)
    expect(H("POST", "/requests/%s/decline" % p, {}, tok=w.t("ada")), 409, "request_not_pending", "paid")
    c = w.req("bob", "ada", 5).j["request_id"]
    H("POST", "/requests/%s/cancel" % c, {}, tok=w.t("bob"))
    expect(H("POST", "/requests/%s/decline" % c, {}, tok=w.t("ada")), 409, "request_not_pending", "cancelled")
    expect(H("POST", "/requests/rq_1/decline", tok=w.t("ada")), 200, what="decline with no body")
    st = {x["request_id"]: x["status"] for x in w.reqs("ada")["requests"]}
    check(st["rq_1"] == "declined" and st[p] == "paid" and st[c] == "cancelled", "statuses %r" % st)


@req("R69", "cancel: requester only, 200 cancelled, twice is 200, paid/declined is 409")
def r69():
    w = W()
    expect(H("POST", "/requests/rq_1/cancel", {}, tok=w.t("ada")), 403, "forbidden", "payer cancels")
    expect(H("POST", "/requests/rq_1/cancel", {}, tok=w.t("cy")), 403, "forbidden", "third party")
    r = H("POST", "/requests/rq_1/cancel", {}, tok=w.t("bob"))
    expect(r, 200)
    check(r.j["status"] == "cancelled", repr(r.j))
    expect(H("POST", "/requests/rq_1/cancel", {}, tok=w.t("bob")), 200, what="cancel twice")
    expect(H("POST", "/requests/rq_1/decline", {}, tok=w.t("ada")), 409, "request_not_pending", "decline cancelled")
    p = w.req("bob", "ada", 5).j["request_id"]
    w.payreq("ada", p)
    expect(H("POST", "/requests/%s/cancel" % p, {}, tok=w.t("bob")), 409, "request_not_pending", "paid")
    d = w.req("bob", "ada", 5).j["request_id"]
    H("POST", "/requests/%s/decline" % d, {}, tok=w.t("ada"))
    expect(H("POST", "/requests/%s/cancel" % d, {}, tok=w.t("bob")), 409, "request_not_pending", "declined")
    check(w.bal("bob") == 2505, "bob %s" % w.bal("bob"))


@req("R70", "a request has no visibility and never appears in any activity feed")
def r70():
    w = W()
    before = {h: w.feed_ids(h) for h in ("ada", "bob", "cy")}
    r = w.req("bob", "ada", 77, visibility="public")
    expect(r, 201)
    check("visibility" not in r.j, "request carries visibility %r" % r.j)
    w.split("ada", 30, ["ada", "bob", "cy"])
    for h in ("ada", "bob", "cy"):
        check(w.feed_ids(h) == before[h], "%s feed changed by request/split" % h)
        for p in w.feed(h)["payments"]:
            check("payment_id" in p and "status" not in p, "non-payment item %r" % p)


# ================================================================= GET /requests

@req("R71", "GET /requests returns only requests where the caller is requester or payer")
def r71():
    w = W()
    w.req("ada", "bob", 1)
    w.req("dee", "eve", 1)
    for h in ("ada", "bob", "cy", "dee", "eve", "op"):
        for x in w.reqs(h, "?limit=200")["requests"]:
            check(h in (x["requester_handle"], x["payer_handle"]), "%s sees %r" % (h, x))
    check(w.reqs("cy")["requests"] == [], "cy sees requests")
    check(len(w.reqs("ada")["requests"]) == 2, "ada count")


@req("R72", "direction and status filters")
def r72():
    w = W()
    a = w.req("ada", "bob", 1).j["request_id"]      # ada outgoing
    b = w.req("cy", "ada", 2).j["request_id"]       # ada incoming
    H("POST", "/requests/%s/decline" % b, {}, tok=w.t("ada"))
    ids = lambda q: sorted(x["request_id"] for x in w.reqs("ada", q)["requests"])
    check(ids("?direction=incoming") == sorted(["rq_1", b]), "incoming %s" % ids("?direction=incoming"))
    check(ids("?direction=outgoing") == [a], "outgoing")
    check(ids("") == sorted(["rq_1", a, b]), "both")
    check(ids("?status=declined") == [b], "declined")
    check(ids("?status=pending") == sorted(["rq_1", a]), "pending")
    check(ids("?status=paid") == [] and ids("?status=cancelled") == [], "paid/cancelled")
    check(ids("?direction=incoming&status=pending") == ["rq_1"], "combined")


@req("R73", "GET /requests and GET /activity are newest first by created_at")
def r73():
    w = W()
    a = w.req("ada", "bob", 1).j["request_id"]
    p1 = w.pay("ada", "bob", 1).j["payment_id"]
    time.sleep(1.1)
    b = w.req("ada", "bob", 2).j["request_id"]
    p2 = w.pay("ada", "bob", 2).j["payment_id"]
    rs = [x["request_id"] for x in w.reqs("ada")["requests"]]
    check(rs.index(b) < rs.index(a), "requests order %s" % rs)
    ps = w.feed_ids("ada")
    check(ps.index(p2) < ps.index(p1), "activity order %s" % ps)
    for lst in (w.reqs("ada")["requests"], w.feed("ada")["payments"]):
        ts = [x["created_at"] for x in lst]
        from datetime import datetime
        d = [datetime.fromisoformat(t.replace("Z", "+00:00")) for t in ts]
        check(all(d[i] >= d[i + 1] for i in range(len(d) - 1)), "not newest first %s" % ts)


def _many_fixture():
    reqs = [{"id": "rq_m%d" % i, "requester_id": "u_bob", "payer_id": "u_ada", "amount": i + 1,
             "note": "", "status": "pending"} for i in range(60)]
    pays = [{"id": "p_m%d" % i, "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 1,
             "note": "", "visibility": "public"} for i in range(60)]
    return base_fixture(requests=reqs, payments=pays)


@req("R74", "limit default 50 (1..200), offset default 0, has_more on both list endpoints")
def r74():
    w = W(_many_fixture())
    for ep, key, n in (("/requests", "requests", 60), ("/activity", "payments", 60)):
        g = lambda q: H("GET", ep + q, tok=w.t("ada")).j
        d = g("")
        check(len(d[key]) == 50 and d["has_more"] is True, "%s default page %d %s" % (ep, len(d[key]), d["has_more"]))
        d = g("?limit=200")
        check(len(d[key]) == n and d["has_more"] is False, "%s limit 200" % ep)
        d = g("?limit=1")
        check(len(d[key]) == 1 and d["has_more"] is True, "%s limit 1" % ep)
        d = g("?limit=10&offset=50")
        check(len(d[key]) == 10 and d["has_more"] is False, "%s exact end has_more=%s" % (ep, d["has_more"]))
        d = g("?limit=10&offset=49")
        check(len(d[key]) == 10 and d["has_more"] is True, "%s before end" % ep)
        d = g("?offset=1000")
        check(d[key] == [] and d["has_more"] is False, "%s past end" % ep)
        full = [x[key[:-1] + "_id"] for x in g("?limit=200")[key]]
        paged = []
        for off in range(0, n, 7):
            paged += [x[key[:-1] + "_id"] for x in g("?limit=7&offset=%d" % off)[key]]
        check(paged == full, "%s paging does not tile the list" % ep)


@req("R75", "limit/offset out of range or not plain digits, unknown direction/status: 422")
def r75():
    w = W()
    ada = w.t("ada")
    bad = ["limit=0", "limit=201", "limit=-1", "limit=1e9", "limit=4.0", "limit=%2B4", "limit=",
           "limit=abc", "offset=-1", "offset=1e1", "offset=%2B0", "offset=0.0", "offset=", "limit=%204", "limit=4%20"]
    for ep in ("/requests", "/activity"):
        for q in bad:
            expect(H("GET", ep + "?" + q, tok=ada), 422, "validation_failed", ep + "?" + q)
        for q in ("limit=200", "limit=1", "offset=0", "limit=007"):
            expect(H("GET", ep + "?" + q, tok=ada), 200, what=ep + "?" + q)
    for q in ("direction=sideways", "direction=INCOMING", "status=open", "status=PAID"):
        expect(H("GET", "/requests?" + q, tok=ada), 422, "validation_failed", q)


# ================================================================= §8/§9 splits

@req("R76", "POST /splits 201: shares in given order summing to amount, requests to the others")
def r76():
    w = W()
    r = w.split("ada", 3000, ["ada", "bob", "cy"], note="dinner")
    expect(r, 201)
    j = r.j
    check(j["amount"] == 3000 and j["currency"] == "EUR" and j["note"] == "dinner" and j.get("split_id")
          and j.get("created_at"), repr(j))
    check(j["shares"] == [{"handle": "ada", "amount": 1000}, {"handle": "bob", "amount": 1000},
                          {"handle": "cy", "amount": 1000}], "shares %r" % j["shares"])
    check([x["payer_handle"] for x in j["requests"]] == ["bob", "cy"], "requests %r" % j["requests"])
    for x in j["requests"]:
        check(x["requester_handle"] == "ada" and x["requester_id"] == "u_ada" and x["status"] == "pending"
              and x["amount"] == 1000 and x["note"] == "dinner" and x["payment_id"] is None, repr(x))
    inc = {x["request_id"] for x in w.reqs("cy", "?direction=incoming")["requests"]}
    check(j["requests"][1]["request_id"] in inc, "cy cannot see split request")


@req("R77", "equal-split rule: whole units, differ by <=1, larger shares first (spec table)")
def r77():
    w = W()
    others = ["bob", "cy", "dee", "eve"]
    for amount, n, want in ((1000, 3, [334, 333, 333]), (1, 3, [1, 0, 0]), (10, 3, [4, 3, 3]),
                            (999, 3, [333, 333, 333]), (5, 5, [1, 1, 1, 1, 1]), (7, 4, [2, 2, 2, 1]),
                            (1000000000, 3, [333333334, 333333333, 333333333])):
        hs = (["ada"] + others)[:n]
        got = [s["amount"] for s in w.split("ada", amount, hs).j["shares"]]
        check(got == want, "%d/%d -> %s want %s" % (amount, n, got, want))
        hs = (others + ["ada"])[:n]
        got = [s["amount"] for s in w.split("ada", amount, hs).j["shares"]]
        check(got == want, "%d/%d (caller absent) -> %s" % (amount, n, got))


@req("R78", "a different participant order gives the extra unit to a different person")
def r78():
    w = W()
    a = w.split("ada", 1000, ["bob", "cy", "ada"]).j["shares"]
    b = w.split("ada", 1000, ["cy", "bob", "ada"]).j["shares"]
    check(a[0] == {"handle": "bob", "amount": 334} and b[0] == {"handle": "cy", "amount": 334}, "%r %r" % (a, b))
    s1 = w.split("ada", 1000, ["bob", "cy", "ada"]).j["shares"]
    check(s1 == a, "shares depend on previous splits")


@req("R79", "a share of 0 is legal and still produces a request for that participant")
def r79():
    w = W()
    r = w.split("ada", 1, ["ada", "bob", "cy"])
    expect(r, 201)
    check([(x["payer_handle"], x["amount"]) for x in r.j["requests"]] == [("bob", 0), ("cy", 0)],
          "requests %r" % r.j["requests"])
    r = w.split("ada", 1, ["bob", "cy", "ada"])
    check([(x["payer_handle"], x["amount"]) for x in r.j["requests"]] == [("bob", 1), ("cy", 0)], repr(r.j))


@req("R80", "caller may be anywhere or omitted; requests skip the caller and keep order")
def r80():
    w = W()
    r = w.split("ada", 900, ["bob", "ada", "cy"])
    check([x["payer_handle"] for x in r.j["requests"]] == ["bob", "cy"], "middle caller")
    check([s["handle"] for s in r.j["shares"]] == ["bob", "ada", "cy"], "shares order")
    r = w.split("ada", 900, ["cy", "bob"])
    check([x["payer_handle"] for x in r.j["requests"]] == ["cy", "bob"] and
          [s["amount"] for s in r.j["shares"]] == [450, 450], "caller omitted %r" % r.j)


@req("R81", "a split whose only participant is the caller is valid with requests []")
def r81():
    w = W()
    r = w.split("ada", 500, ["ada"])
    expect(r, 201)
    check(r.j["requests"] == [] and r.j["shares"] == [{"handle": "ada", "amount": 500}], repr(r.j))
    check(len(w.reqs("ada")["requests"]) == 1, "requests created")


@req("R82", "participant_handles empty or with a duplicate is 422; unknown handle 404, nothing created")
def r82():
    w = W()
    expect(w.split("ada", 10, []), 422, "validation_failed", "empty")
    expect(w.split("ada", 10, ["bob", "bob"]), 422, "validation_failed", "duplicate")
    expect(w.split("ada", 10, ["ada", "bob", "ada"]), 422, "validation_failed", "duplicate caller")
    expect(w.split("ada", 10, ["bob", "cy", "ghost"]), 404, "not_found", "unknown last")
    check(w.reqs("bob")["requests"] == [x for x in w.reqs("bob")["requests"] if x["request_id"] == "rq_1"],
          "partial split requests created")


@req("R83", "splits never check balances and create no payments")
def r83():
    w = W()
    n0 = w.feed_ids("cy")
    r = w.split("cy", 1000000000, ["cy", "op", "bob"])
    expect(r, 201, what="split by zero-balance caller")
    r = w.split("ada", 1000000000, ["cy", "op"])
    expect(r, 201, what="split to zero-balance payers")
    check(w.feed_ids("cy") == n0, "split created payments")
    check(w.bal("cy") == 0 and w.bal("ada") == 10000, "split moved money")


@req("R84", "after split requests are paid in full, balances still sum to the seeded total")
def r84():
    w = W()
    r = w.split("ada", 1001, ["bob", "dee", "eve", "ada"])
    for x in r.j["requests"]:
        expect(w.payreq(x["payer_handle"], x["request_id"]), 201, what="pay share")
    check(w.bal("ada") == 10000 + 251 + 250 + 250, "ada %s" % w.bal("ada"))
    check(w.total() == w.seed_total, "sum drifted")


# ================================================================= §4 feed

@req("R85", "feed: public payments visible to all, private only to sender and receiver, same value")
def r85():
    w = W()
    pub = w.pay("dee", "eve", 5, visibility="public").j["payment_id"]
    prv = w.pay("dee", "eve", 6, visibility="private").j["payment_id"]
    for h in ("ada", "bob", "cy", "dee", "eve", "op"):
        ids = w.feed_ids(h)
        check(pub in ids and "p_1" in ids, "%s misses public" % h)
        check((prv in ids) == (h in ("dee", "eve")), "%s private visibility wrong" % h)
        check(("p_2" in ids) == (h in ("ada", "bob")), "%s seeded private visibility wrong" % h)
    for h in ("dee", "eve"):
        it = [p for p in w.feed(h)["payments"] if p["payment_id"] == prv][0]
        check(it["visibility"] == "private" and it["amount"] == 6, "%s sees %r" % (h, it))


# ================================================================= §10 export/import

@req("R86", "export returns 200 {track: pocketful, format_version: 1, state: object}")
def r86():
    W()
    r = H("GET", "/_test/export")
    expect(r, 200)
    check(r.j.get("track") == "pocketful" and r.j.get("format_version") == 1 and isinstance(r.j.get("state"), dict),
          "export envelope %r" % {k: r.j.get(k) for k in ("track", "format_version")})


@req("R87", "import of an unchanged export restores balances, payments, requests, tokens, logins")
def r87():
    w = W()
    ada, bob = w.t("ada"), w.t("bob")
    k = K()
    p = w.pay("ada", "bob", 123, key=k, note="before")
    rq = w.req("bob", "cy", 40).j
    h = w.signup("imp@x.io", pw="imp-password")
    imp_tok = w.toks[h]
    w.pay("ada", h, 7)
    snap = (w.bals(), w.feed_ids("ada"), w.reqs("bob")["requests"], w.feed("bob")["payments"])
    exp = H("GET", "/_test/export").j
    W(base_fixture(users=[user("u_zz", "zz", 1)], payments=[], requests=[], settlement_operator_ids=[]))
    expect(H("POST", "/_test/import", exp), 204, what="import")
    for t in (ada, bob, imp_tok):
        expect(H("GET", "/me", tok=t), 200, what="token after import")
    expect(H("POST", "/auth/login", {"email": "imp@x.io", "password": "imp-password"}), 200, what="login")
    expect(H("POST", "/auth/login", {"email": "ada@example.com", "password": PW}), 200, what="seeded login")
    w2 = W.__new__(W)
    w2.toks, w2.emails = dict(w.toks), dict(w.emails)
    check((w2.bals(), w2.feed_ids("ada"), w2.reqs("bob")["requests"], w2.feed("bob")["payments"]) == snap,
          "state differs after import")
    r = w2.pay("ada", "bob", 123, key=k, note="before")
    expect(r, 200, what="replay after import")
    check(r.j == p.j, "replay body differs after import")
    check(w2.bal("ada") == snap[0]["ada"], "replay moved money")
    expect(H("POST", "/auth/login", {"email": "zz@example.com", "password": PW}), 401, what="old dest user")


@req("R88", "after import, failed keys stay reusable and new ids do not collide")
def r88():
    w = W()
    k = K()
    expect(w.pay("cy", "ada", 50, key=k), 409)
    ids = set(w.feed_ids("ada")) | {x["request_id"] for x in w.reqs("ada")["requests"]}
    w.pay("ada", "bob", 1)
    w.req("ada", "bob", 1)
    exp = H("GET", "/_test/export").j
    ids = set(w.feed_ids("ada")) | {x["request_id"] for x in w.reqs("ada")["requests"]}
    expect(H("POST", "/_test/import", exp), 204)
    expect(w.pay("cy", "ada", 50, key=k), 409, "insufficient_funds", "failed key after import")
    w.pay("ada", "cy", 50)
    expect(w.pay("cy", "ada", 50, key=k), 201, what="failed key reusable")
    new = {w.pay("ada", "bob", 2).j["payment_id"], w.req("ada", "bob", 2).j["request_id"]}
    check(not (new & ids), "id collision %s" % (new & ids))
    s = w.signup("after@x.io")
    check(s == "after", "signup after import")


@req("R89", "import replaces (not merges); repeating it duplicates nothing; export is a snapshot")
def r89():
    w = W()
    w.pay("ada", "bob", 5)
    snap = (w.bals(), w.feed_ids("ada"))
    exp = H("GET", "/_test/export").j
    post_pid = w.pay("ada", "bob", 6).j["payment_id"]
    tok = w.t("ada")
    w.signup("later@x.io")
    for _ in range(2):
        expect(H("POST", "/_test/import", exp), 204)
    later = w.toks.pop("later")
    w.emails.pop("later")
    check((w.bals(), w.feed_ids("ada")) == snap, "state after repeated import differs")
    check(post_pid not in w.feed_ids("ada"), "write after export leaked into snapshot")
    expect(H("POST", "/auth/login", {"email": "later@x.io", "password": "password123"}), 401, what="post-export user")
    expect(H("GET", "/me", tok=later), 401, what="post-export token")
    expect(H("GET", "/me", tok=tok), 200, what="pre-export token")


@req("R90", "invalid import (track, version, missing state, bad state) is 422 and changes nothing")
def r90():
    w = W()
    w.pay("ada", "bob", 9)
    good = H("GET", "/_test/export").j
    W(base_fixture())
    w = W.__new__(W)
    w.toks, w.emails = {}, {u["handle"]: (u["email"], PW) for u in base_fixture()["users"]}
    before = (w.bals(), w.feed_ids("ada"))
    bads = [{"track": "other", "format_version": 1, "state": good["state"]},
            {"track": "pocketful", "format_version": 2, "state": good["state"]},
            {"track": "pocketful", "format_version": "1", "state": good["state"]},
            {"format_version": 1, "state": good["state"]},
            {"track": "pocketful", "state": good["state"]},
            {"track": "pocketful", "format_version": 1},
            {"track": "pocketful", "format_version": 1, "state": "garbage"},
            {"track": "pocketful", "format_version": 1, "state": {}},
            {"track": "pocketful", "format_version": 1, "state": None},
            {"track": "pocketful", "format_version": 1, "state": [good["state"]]}]
    for b in bads:
        expect(H("POST", "/_test/import", b), 422, "validation_failed", "import %s" % str(b)[:60])
    expect(H("POST", "/_test/import", raw=b"{not json"), 400, "malformed_request", "invalid JSON")
    check((w.bals(), w.feed_ids("ada")) == before, "state changed by rejected import")


@req("R91", "reset clears imported state, including imported tokens")
def r91():
    w = W()
    exp = H("GET", "/_test/export").j
    tok = w.t("ada")
    expect(H("POST", "/_test/import", exp), 204)
    W()
    expect(H("GET", "/me", tok=tok), 401, "unauthenticated", "imported token after reset")


# ================================================================= §11 settlements

@req("R92", "settlements: no token 401, authenticated non-operator 403 forbidden")
def r92():
    w = W()
    b = {"transfers": [tr("ada", "bob", 1)]}
    expect(H("POST", "/settlements", b, key=K()), 401, "unauthenticated")
    for h in ("ada", "bob", "cy"):
        expect(H("POST", "/settlements", b, tok=w.t(h), key=K()), 403, "forbidden", h)
    check(w.bal("ada") == 10000, "money moved")
    w = W({k: v for k, v in base_fixture().items() if k != "settlement_operator_ids"})
    expect(w.settle([tr("ada", "bob", 1)]), 403, "forbidden", "operator ids default []")


@req("R93", "settlement 201: settlement_id, committed_at, payments in input order, linked")
def r93():
    w = W()
    r = w.settle([tr("ada", "bob", 100, note="a"), tr("bob", "cy", 50, visibility="private"),
                  tr("dee", "ada", 7)])
    expect(r, 201)
    j = r.j
    check(j.get("settlement_id") and j.get("committed_at"), repr(j))
    ps = j["payments"]
    check([(p["from_handle"], p["to_handle"], p["amount"]) for p in ps] ==
          [("ada", "bob", 100), ("bob", "cy", 50), ("dee", "ada", 7)], "order %r" % ps)
    for p in ps:
        check(p["settlement_id"] == j["settlement_id"] and p["request_id"] is None
              and p["created_at"] == j["committed_at"] and p["currency"] == "EUR" and p.get("payment_id"),
              "member %r" % p)
    check(ps[0]["note"] == "a" and ps[1]["visibility"] == "private" and ps[2]["note"] == "", "fields")
    check(len({p["payment_id"] for p in ps}) == 3, "duplicate payment ids")
    check(w.bals() == {"ada": 9907, "bob": 2550, "cy": 50, "dee": 4993, "eve": 1000, "op": 0}, "balances %s" % w.bals())
    f = [p for p in w.feed("ada")["payments"] if p["payment_id"] == ps[0]["payment_id"]][0]
    check(f.get("settlement_id") == j["settlement_id"], "feed member lacks settlement_id")


@req("R94", "non-settlement payments expose settlement_id null")
def r94():
    w = W()
    r = w.pay("ada", "bob", 1)
    check("settlement_id" in r.j and r.j["settlement_id"] is None, "payment %r" % r.j)
    r = w.payreq("ada", "rq_1")
    check("settlement_id" in r.j and r.j["settlement_id"] is None, "request payment %r" % r.j)
    for p in w.feed("ada")["payments"]:
        check("settlement_id" in p and p["settlement_id"] is None, "feed item %r" % p)


@req("R95", "affordability is net: individually unaffordable legs commit if every final balance >= 0")
def r95():
    w = W()
    r = w.settle([tr("cy", "eve", 300), tr("dee", "cy", 300)])
    expect(r, 201, what="cy pays before being paid")
    check(w.bal("cy") == 0 and w.bal("eve") == 1300 and w.bal("dee") == 4700, "balances")
    r = w.settle([tr("op", "cy", 5000), tr("cy", "ada", 5000), tr("ada", "op", 5000)])
    expect(r, 201, what="zero-balance cycle")
    check(w.bal("op") == 0 and w.bal("cy") == 0, "cycle balances")


@req("R96", "collectively insufficient settlement is 409 and nothing moves or is recorded")
def r96():
    w = W()
    before, feed = w.bals(), w.feed_ids("op")
    expect(w.settle([tr("ada", "bob", 100), tr("cy", "ada", 1)]), 409, "insufficient_funds")
    expect(w.settle([tr("eve", "ada", 600), tr("eve", "bob", 401)]), 409, "insufficient_funds", "two legs")
    check(w.bals() == before and w.feed_ids("op") == feed, "partial settlement")


@req("R97", "transfers must hold 1..32 objects (0, 33, non-list, non-object are 422); 32 is fine")
def r97():
    w = W()
    for ts in ([], [tr("dee", "ada", 1)] * 33, "x", None, {"a": 1}, [1], [None], [[]]):
        expect(w.settle(ts), 422, "validation_failed", "transfers %s" % str(ts)[:30])
    r = w.settle([tr("dee", "ada", 1)] * 32)
    expect(r, 201, what="32 transfers")
    check(len(r.j["payments"]) == 32 and w.bal("dee") == 4968, "32 legs")


@req("R98", "entry errors in input order take precedence over insufficient funds")
def r98():
    w = W()
    expect(w.settle([tr("ada", "ghost", 1), tr("bob", "bob", 1)]), 404, "not_found", "404 first")
    expect(w.settle([tr("bob", "bob", 1), tr("ada", "ghost", 1)]), 422, "self_payment", "self first")
    expect(w.settle([tr("cy", "ada", 999999), tr("ghost", "ada", 1)]), 404, "not_found", "404 over funds")
    expect(w.settle([tr("cy", "ada", 999999), tr("ada", "ada", 1)]), 422, "self_payment", "self over funds")
    expect(w.settle([tr("cy", "ada", 999999), tr("ada", "bob", 0)]), 422, "validation_failed", "amount over funds")
    expect(w.settle([tr("ada", "bob", 1), tr("bob", "ghost", 1), tr("cy", "cy", 1)]), 404, "not_found", "mid")
    check(w.bal("ada") == 10000, "money moved")


@req("R99", "settlement entries use payment rules and ignore unknown fields")
def r99():
    w = W()
    expect(w.settle([tr("ada", "bob", 1, note="x" * 201)]), 422, "validation_failed", "note")
    expect(w.settle([tr("ada", "bob", 1, visibility="x")]), 422, "validation_failed", "vis")
    expect(w.settle([tr("ada", "bob", 1.5)]), 422, "validation_failed", "amount")
    r = w.settle([tr("ada", "bob", 1, junk=1, from_user_id="u_cy")])
    expect(r, 201, what="unknown entry fields")
    check(r.j["payments"][0]["from_handle"] == "ada", "unknown field honoured")


@req("R100", "failed settlement claims no key and creates nothing")
def r100():
    w = W()
    k = K()
    n = w.feed_ids("op")
    expect(w.settle([tr("ada", "ghost", 1)], key=k), 404)
    expect(w.settle([tr("cy", "ada", 1)], key=k), 409)
    r = w.settle([tr("ada", "cy", 1)], key=k)
    expect(r, 201, what="key free after failures")
    check(len(w.feed_ids("op")) == len(n) + 1, "extra payments")


@req("R101", "settlement replay returns 200 with the original complete response and moves nothing")
def r101():
    w = W()
    k = K()
    b = [tr("ada", "bob", 10), tr("bob", "cy", 20)]
    r1 = w.settle(b, key=k)
    bals = w.bals()
    r2 = w.settle(b, key=k)
    expect(r2, 200)
    check(r2.j == r1.j and w.bals() == bals, "replay differs or moved money")
    expect(w.settle([tr("ada", "bob", 10)], key=k), 409, "idempotency_key_reuse")


@req("R102", "operators gain no access to other users' requests or private activity")
def r102():
    w = W()
    check(w.reqs("op")["requests"] == [], "operator sees requests")
    check("p_2" not in w.feed_ids("op"), "operator sees private payment")
    expect(w.payreq("op", "rq_1"), 403, "forbidden", "operator pays others' request")
    expect(H("POST", "/requests/rq_1/decline", {}, tok=w.t("op")), 403, "forbidden", "decline")
    expect(H("POST", "/requests/rq_1/cancel", {}, tok=w.t("op")), 403, "forbidden", "cancel")


@req("R103", "settlement members follow ordinary feed visibility")
def r103():
    w = W()
    r = w.settle([tr("dee", "eve", 3, visibility="private"), tr("dee", "eve", 4)])
    a, b = [p["payment_id"] for p in r.j["payments"]]
    for h in ("ada", "op", "cy"):
        ids = w.feed_ids(h)
        check(a not in ids and b in ids, "%s visibility wrong" % h)
    for h in ("dee", "eve"):
        ids = w.feed_ids(h)
        check(a in ids and b in ids, "%s misses member" % h)


@req("R104", "import preserves operator permission, settlement membership and settlement replay")
def r104():
    w = W()
    k = K()
    b = [tr("ada", "bob", 10)]
    r1 = w.settle(b, key=k)
    exp = H("GET", "/_test/export").j
    W(base_fixture(settlement_operator_ids=[]))
    expect(H("POST", "/_test/import", exp), 204)
    r2 = w.settle(b, key=k)
    expect(r2, 200, what="settlement replay after import")
    check(r2.j == r1.j, "body differs")
    m = [p for p in w.feed("ada")["payments"] if p["payment_id"] == r1.j["payments"][0]["payment_id"]][0]
    check(m["settlement_id"] == r1.j["settlement_id"], "membership lost")
    expect(w.settle([tr("ada", "bob", 1)]), 201, what="operator still operator")
    expect(w.settle([tr("ada", "bob", 1)], h="ada"), 403, "forbidden", "non-operator after import")


@req("R105", "concurrent settlements and payments never overdraw a wallet")
def r105():
    w = W()
    op, dee = w.t("op"), w.t("dee")
    fns = [lambda: H("POST", "/settlements", {"transfers": [tr("dee", "ada", 1000)]}, tok=op, key=K())
           for _ in range(8)]
    fns += [lambda: H("POST", "/payments", {"to_handle": "bob", "amount": 1000}, tok=dee, key=K())
            for _ in range(8)]
    res = par(fns)
    check(sum(r.status == 201 for r in res) == 5, "successes %s" % sorted(r.status for r in res))
    check(w.bal("dee") == 0 and w.total() == w.seed_total, "balances %s" % w.bals())


# ================================================================= added: races and edges

@req("R106", "concurrent signups with one email (or one derived handle) create exactly one account")
def r106():
    W()
    res = par([lambda i=i: H("POST", "/auth/signup", {"email": "race@x.io", "password": "password%d" % i,
                                                     "display_name": "R"}) for i in range(10)])
    st = sorted(r.status for r in res)
    check(st.count(201) == 1 and all(r.code == "email_taken" for r in res if r.status != 201), "email %s" % st)
    res = par([lambda i=i: H("POST", "/auth/signup", {"email": "same.h@d%d.io" % i, "password": "password1",
                                                     "display_name": "R"}) for i in range(10)])
    st = sorted(r.status for r in res)
    check(st.count(201) == 1 and all(r.code == "handle_taken" for r in res if r.status != 201), "handle %s" % st)
    ok = sum(H("POST", "/auth/login", {"email": "same.h@d%d.io" % i, "password": "password1"}).status == 200
             for i in range(10))
    check(ok == 1, "%d accounts exist for one handle" % ok)


@req("R107", "pay racing cancel/decline: exactly one wins and money moves only if paid")
def r107():
    for loser in ("cancel", "decline"):
        w = W()
        ada, bob = w.t("ada"), w.t("bob")
        rids = [w.req("bob", "ada", 100).j["request_id"] for _ in range(10)]
        fns = []
        for rid in rids:
            fns.append(lambda rid=rid: ("pay", rid, H("POST", "/requests/%s/pay" % rid, {}, tok=ada, key=K())))
            if loser == "cancel":
                fns.append(lambda rid=rid: ("x", rid, H("POST", "/requests/%s/cancel" % rid, {}, tok=bob)))
            else:
                fns.append(lambda rid=rid: ("x", rid, H("POST", "/requests/%s/decline" % rid, {}, tok=ada)))
        res = par(fns)
        status = {x["request_id"]: x for x in w.reqs("ada", "?limit=200")["requests"]}
        paid = 0
        for rid in rids:
            p = [r for k, i, r in res if i == rid and k == "pay"][0]
            x = [r for k, i, r in res if i == rid and k == "x"][0]
            check((p.status == 201) != (x.status == 200), "%s: pay %s and %s %s" % (rid, p.status, loser, x.status))
            want = "paid" if p.status == 201 else ("cancelled" if loser == "cancel" else "declined")
            check(status[rid]["status"] == want, "%s status %s want %s" % (rid, status[rid]["status"], want))
            paid += p.status == 201
        check(w.bal("ada") == 10000 - 100 * paid and w.total() == w.seed_total, "money %s" % w.bals())


@req("R108", "export taken during concurrent writes is a consistent snapshot")
def r108():
    w = W()
    for h in w.emails:
        w.t(h)
    fns = [lambda i=i: w.pay(["ada", "dee", "bob"][i % 3], ["bob", "cy", "eve"][i % 3], 50 + i) for i in range(40)]
    fns += [lambda: H("GET", "/_test/export") for _ in range(6)]
    exps = [r.j for r in par(fns) if isinstance(r.j, dict) and r.j.get("track") == "pocketful"]
    check(len(exps) == 6, "exports failed")
    for e in exps:
        expect(H("POST", "/_test/import", e), 204, what="import concurrent export")
        b = w.bals()
        check(sum(b.values()) == w.seed_total and min(b.values()) >= 0, "inconsistent snapshot %s" % b)
        n = len(w.feed_ids("ada"))
        check(10000 - sum(p["amount"] for p in w.feed("ada", "?limit=200")["payments"]
                          if p["from_handle"] == "ada" and p["payment_id"] not in ("p_1",))
              + sum(p["amount"] for p in w.feed("ada", "?limit=200")["payments"]
                    if p["to_handle"] == "ada" and p["payment_id"] != "p_2") == b["ada"], "ledger vs balance")


@req("R109", "unknown fields in a reset fixture are ignored")
def r109():
    fx = base_fixture(extra_top="x")
    fx["users"][0]["nickname"] = "A"
    fx["payments"][0]["memo"] = 1
    fx["requests"][0]["foo"] = {"b": 2}
    w = W(fx)
    check(w.bal("ada") == 10000, "fixture with unknown fields")


@req("R110", "numerically equal amount spellings (5, 5.0, 5e0) are the same body for replay")
def r110():
    w = W()
    ada = w.t("ada")
    k = K()
    expect(H("POST", "/payments", raw=b'{"to_handle":"bob","amount":5}', tok=ada, key=k), 201)
    for raw in (b'{"to_handle":"bob","amount":5.0}', b'{"to_handle":"bob","amount":5e0}'):
        expect(H("POST", "/payments", raw=raw, tok=ada, key=k), 200, what=raw.decode())
    check(w.bal("ada") == 9995, "balance %s" % w.bal("ada"))


@req("R111", "the key belongs to the user, not the token: replay through a second token is a replay")
def r111():
    w = W()
    k = K()
    t2 = H("POST", "/auth/login", {"email": "ada@example.com", "password": PW}).j["token"]
    r1 = w.pay("ada", "bob", 9, key=k)
    r2 = H("POST", "/payments", {"to_handle": "bob", "amount": 9}, tok=t2, key=k)
    expect(r2, 200, what="replay via second token")
    check(r2.j == r1.j and w.bal("ada") == 9991, "second token replay moved money")
    expect(H("POST", "/payments", {"to_handle": "bob", "amount": 8}, tok=t2, key=k), 409,
           "idempotency_key_reuse", "second token different body")


# ================================================================= runner

def main():
    only = set(sys.argv[1:])
    t0 = time.time()
    r = None
    for _ in range(60):
        try:
            r = H("GET", "/health", timeout=2)
            if r.status == 200:
                break
        except Exception:
            pass
        time.sleep(1)
    failed = []
    # global sweeps run last so they see every response the other probes produced
    sweeps = ("R05", "R07", "R08", "R26")
    order = [x for x in REQS if x[0] not in sweeps] + [x for x in REQS if x[0] in sweeps]
    for rid, title, fn in order:
        if only and rid not in only:
            continue
        if rid in KNOWN_OPEN:
            print("SKIP %-5s %s (KNOWN_OPEN)" % (rid, title))
            continue
        try:
            fn()
            print("PASS %-5s %s" % (rid, title))
        except Fail as e:
            failed.append(rid)
            print("FAIL %-5s %s -- %s" % (rid, title, e))
        except Exception as e:
            failed.append(rid)
            print("FAIL %-5s %s -- error: %s" % (rid, title, "".join(
                traceback.format_exception_only(type(e), e)).strip()))
        sys.stdout.flush()
    print("%d requirements, %d failed, %d known open, %.1fs" % (
        len(REQS) if not only else len(only), len(failed), len(KNOWN_OPEN), time.time() - t0))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
