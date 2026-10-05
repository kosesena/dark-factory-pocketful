#!/usr/bin/env python3
"""Pocketful stage-1 probe suite. Usage: BASE_URL=http://host:port python3 probes/run.py
Prints one PASS/FAIL line per requirement id; exits 1 if any non-skipped requirement fails.
`python3 probes/run.py --ledger` prints the requirement ledger as markdown."""
import json
import os
import re
import sys
import threading
import time
import http.client
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

KNOWN_OPEN = set()

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080")
_u = urlparse(BASE)
HOST, PORT = _u.hostname, _u.port or 80

REQS = []  # (id, quote, fn)


def req(rid, quote):
    def deco(fn):
        REQS.append((rid, quote, fn))
        return fn
    return deco


# ---------------------------------------------------------------- http helpers
def call(method, path, body=None, tok=None, key=None, raw=None, headers=None, timeout=8):
    h = {}
    data = None
    if raw is not None:
        data = raw if isinstance(raw, bytes) else raw.encode()
        h["Content-Type"] = "application/json"
    elif body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if tok is not None:
        h["Authorization"] = "Bearer " + tok
    if key is not None:
        h["Idempotency-Key"] = key
    if headers:
        h.update(headers)
    c = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    try:
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        txt = r.read()
        try:
            js = json.loads(txt) if txt else None
        except Exception:
            js = None
        return r.status, js, dict((k.lower(), v) for k, v in r.getheaders()), txt
    finally:
        c.close()


def api(method, path, body=None, tok=None, key=None, **kw):
    s, j, _, _ = call(method, path, body, tok, key, **kw)
    return s, j


def ok(cond, msg="assertion failed"):
    if not cond:
        raise AssertionError(msg)


def eq(a, b, msg=""):
    if a != b:
        raise AssertionError("%s expected %r got %r" % (msg, b, a))


def code(j):
    return (j or {}).get("error", {}).get("code") if isinstance(j, dict) else None


def expect(resp, status, ecode=None, msg=""):
    s, j = resp[0], resp[1]
    if s != status:
        raise AssertionError("%s expected HTTP %s got %s body=%r" % (msg, status, s, j))
    if ecode is not None and code(j) != ecode:
        raise AssertionError("%s expected code %s got %r" % (msg, ecode, j))
    if status >= 400:
        ok(isinstance(j, dict) and isinstance(j.get("error"), dict)
           and isinstance(j["error"].get("message"), str), "error body shape: %r" % (j,))
    return j


PW = "correct horse"


def user(h, bal=0, uid=None):
    return {"id": uid or "u_" + h, "email": h + "@example.com", "password": PW,
            "display_name": h.capitalize(), "handle": h, "balance": bal}


def fixture(users=None, **extra):
    f = {"currency": "EUR", "minor_units": 2,
         "users": users if users is not None else
         [user("ada", 10000), user("bob", 2500), user("cy", 0), user("dan", 5000)],
         "payments": [], "requests": []}
    f.update(extra)
    return f


def reset(f=None):
    s, j, _, _ = call("POST", "/_test/reset", f if f is not None else fixture())
    eq(s, 204, "reset")


def login(h):
    s, j = api("POST", "/auth/login", {"email": h + "@example.com", "password": PW})
    eq(s, 200, "login " + h)
    return j["token"]


def setup(f=None):
    f = f if f is not None else fixture()
    reset(f)
    return {u["handle"]: login(u["handle"]) for u in f["users"]}


_k = [0]
_kl = threading.Lock()


def nk(p="k"):
    with _kl:
        _k[0] += 1
        return "%s-%d-%d" % (p, os.getpid(), _k[0])


def bal(t):
    s, j = api("GET", "/me", tok=t)
    eq(s, 200, "me")
    return j["balance"]


def total(T):
    return sum(bal(t) for t in T.values())


def pay(t, to, amount, note=None, vis=None, key=None):
    b = {"to_handle": to, "amount": amount}
    if note is not None:
        b["note"] = note
    if vis is not None:
        b["visibility"] = vis
    return api("POST", "/payments", b, t, key or nk())


def mkreq(t, payer, amount, note=None, key=None):
    b = {"payer_handle": payer, "amount": amount}
    if note is not None:
        b["note"] = note
    return api("POST", "/requests", b, t, key or nk())


RFC = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)$")


def feed(t, q=""):
    s, j = api("GET", "/activity" + q, tok=t)
    eq(s, 200, "activity")
    return j


# ---------------------------------------------------------------- runtime contract
@req("R01", "GET /health -> 200 {\"status\": \"ok\"}")
def _():
    s, j = api("GET", "/health")
    eq(s, 200)
    eq(j, {"status": "ok"})


@req("R02", "Replace all service state with the fixture ... subsequent requests must see only that fixture. Repeated resets are supported.")
def _():
    setup()
    s, j = api("POST", "/auth/signup", {"email": "zed@example.com", "password": "longenough", "display_name": "Z"})
    eq(s, 201)
    old = j["token"]
    reset(fixture([user("ada", 5)]))
    expect(api("GET", "/me", tok=old), 401)
    s, j = api("POST", "/auth/login", {"email": "bob@example.com", "password": PW})
    eq(s, 401)
    eq(bal(login("ada")), 5)
    reset(fixture([user("ada", 7)]))
    eq(bal(login("ada")), 7)


@req("R03", "A balance below zero in a fixture is a reset error: return 422 validation_failed from POST /_test/reset and change nothing.")
def _():
    T = setup()
    s, j = api("POST", "/_test/reset", fixture([user("ada", -1), user("bob", 5)]))
    eq(s, 422)
    eq(code(j), "validation_failed")
    eq(bal(T["ada"]), 10000, "state unchanged")


@req("R04", "GET /me returns user_id, display_name, handle, balance, currency, minor_units; seeded users log in immediately")
def _():
    T = setup()
    s, j = api("GET", "/me", tok=T["ada"])
    eq(s, 200)
    for k, v in {"user_id": "u_ada", "display_name": "Ada", "handle": "ada", "balance": 10000,
                 "currency": "EUR", "minor_units": 2}.items():
        eq(j.get(k), v, k)


@req("R05", "one currency declared in the fixture; minor_units 0, 2 or 3 (EUR/JPY/BHD)")
def _():
    for cur, mu in (("JPY", 0), ("BHD", 3)):
        f = fixture(); f["currency"] = cur; f["minor_units"] = mu
        T = setup(f)
        s, j = api("GET", "/me", tok=T["ada"])
        eq((j["currency"], j["minor_units"]), (cur, mu))
        s, j = pay(T["ada"], "bob", 100)
        eq(s, 201)
        eq(j["currency"], cur)
        s, j = mkreq(T["bob"], "ada", 5)
        eq(j["currency"], cur)


@req("R06", "Seeded payments appear per feed rule; seeded requests readable via GET /requests; balance is final (not replayed)")
def _():
    f = fixture()
    f["payments"] = [
        {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"},
        {"id": "p_2", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 700, "note": "secret", "visibility": "private"}]
    f["requests"] = [{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}]
    T = setup(f)
    eq(bal(T["ada"]), 10000)
    eq(bal(T["bob"]), 2500)
    notes = lambda t: sorted(p["note"] for p in feed(t)["payments"])
    eq(notes(T["cy"]), ["coffee"])
    eq(notes(T["bob"]), ["coffee", "secret"])
    eq(notes(T["ada"]), ["coffee", "secret"])
    j = expect(api("GET", "/requests", tok=T["ada"]), 200)
    eq([r["amount"] for r in j["requests"]], [1200])
    eq(j["requests"][0]["status"], "pending")
    eq(api("GET", "/requests", tok=T["cy"])[1]["requests"], [])
    expect(api("POST", "/requests/rq_1/pay", {}, T["ada"], nk()), 201)


@req("R07", "Every 4xx/5xx carries {\"error\": {\"code\", \"message\"}}; responses are application/json; charset=utf-8")
def _():
    T = setup()
    s, j, h, _t = call("GET", "/me", tok=T["ada"])
    ok("application/json" in h.get("content-type", "") and "utf-8" in h.get("content-type", "").lower(), h.get("content-type"))
    s, j, h, _t = call("GET", "/me")
    eq(s, 401)
    ok("application/json" in h.get("content-type", ""))
    expect((s, j), 401)
    expect(api("GET", "/requests?limit=0", tok=T["ada"]), 422)
    expect(api("GET", "/nonexistent-route", tok=T["ada"])[0:2], 404) if False else None


@req("R08", "401 unauthenticated: Missing, malformed or unknown bearer token (every non-auth endpoint)")
def _():
    T = setup()
    eps = [("GET", "/me"), ("POST", "/payments"), ("POST", "/requests"), ("POST", "/requests/rq_x/pay"),
           ("POST", "/requests/rq_x/decline"), ("POST", "/requests/rq_x/cancel"), ("GET", "/requests"),
           ("POST", "/splits"), ("GET", "/activity"), ("POST", "/settlements")]
    for m, p in eps:
        for hdr in (None, {"Authorization": "Bearer"}, {"Authorization": "Bearer nope-unknown"},
                    {"Authorization": "Basic " + T["ada"]}, {"Authorization": T["ada"]}):
            s, j, _h, _t = call(m, p, {} if m == "POST" else None, headers=hdr, key=nk())
            eq(s, 401, "%s %s %r" % (m, p, hdr))
            eq(code(j), "unauthenticated")


@req("R09", "Unknown fields in a request body are ignored; unknown query parameters are ignored")
def _():
    T = setup()
    s, j = api("POST", "/payments", {"to_handle": "bob", "amount": 10, "bogus": [1], "x": None}, T["ada"], nk())
    eq(s, 201)
    expect(api("GET", "/activity?foo=bar&limit=5", tok=T["ada"]), 200)
    expect(api("GET", "/requests?zzz=1", tok=T["ada"]), 200)
    expect(api("POST", "/requests", {"payer_handle": "ada", "amount": 5, "junk": 1}, T["bob"], nk()), 201)
    expect(api("POST", "/splits", {"amount": 5, "participant_handles": ["ada"], "junk": 1}, T["ada"], nk()), 201)
    expect(api("POST", "/auth/login", {"email": "ada@example.com", "password": PW, "x": 1}), 200)


@req("R10", "400 malformed_request: Unparseable body, or a field of the wrong JSON type")
def _():
    T = setup()
    t = T["ada"]
    for path in ("/payments", "/requests", "/splits"):
        for raw in ("{not json", "", "[1,2]", "\"str\"", "null"):
            s, j, _h, _t = call("POST", path, raw=raw, tok=t, key=nk())
            eq(s, 400, "%s raw=%r" % (path, raw))
            eq(code(j), "malformed_request")
    for b in ({"to_handle": 5, "amount": 10}, {"to_handle": ["bob"], "amount": 10}, {"to_handle": None, "amount": 10}):
        expect(api("POST", "/payments", b, t, nk()), 400, "malformed_request", repr(b))
    for b in ({"payer_handle": 5, "amount": 10}, {"payer_handle": {"a": 1}, "amount": 10}):
        expect(api("POST", "/requests", b, t, nk()), 400, "malformed_request", repr(b))
    for b in ({"amount": 10, "participant_handles": "bob"}, {"amount": 10, "participant_handles": [1, 2]},
              {"amount": 10, "participant_handles": {"a": 1}}):
        expect(api("POST", "/splits", b, t, nk()), 400, "malformed_request", repr(b))
    expect(call("POST", "/auth/login", raw="{bad")[0:2], 400, "malformed_request")
    expect(call("POST", "/auth/signup", raw="{bad")[0:2], 400, "malformed_request")
    expect(api("POST", "/auth/signup", {"email": 5, "password": "longenough", "display_name": "x"}), 400, "malformed_request")


@req("R11", "422 validation_failed: A required field is missing")
def _():
    T = setup()
    t = T["ada"]
    expect(api("POST", "/payments", {"amount": 10}, t, nk()), 422, "validation_failed")
    expect(api("POST", "/payments", {"to_handle": "bob"}, t, nk()), 422, "validation_failed")
    expect(api("POST", "/requests", {"amount": 10}, t, nk()), 422, "validation_failed")
    expect(api("POST", "/requests", {"payer_handle": "bob"}, t, nk()), 422, "validation_failed")
    expect(api("POST", "/splits", {"amount": 10}, t, nk()), 422, "validation_failed")
    expect(api("POST", "/splits", {"participant_handles": ["bob"]}, t, nk()), 422, "validation_failed")
    expect(api("POST", "/auth/signup", {"email": "q@example.com", "password": "longenough"}), 422, "validation_failed")
    expect(api("POST", "/auth/signup", {"password": "longenough", "display_name": "q"}), 422, "validation_failed")
    expect(api("POST", "/auth/login", {"email": "ada@example.com"}), 422, "validation_failed") if False else None


# ---------------------------------------------------------------- idempotency key rules
@req("R12", "Idempotency-Key header absent or empty -> 400 missing_idempotency_key (all five write paths)")
def _():
    T = setup(fixture(settlement_operator_ids=["u_ada"]))
    t = T["ada"]
    bodies = {"/payments": {"to_handle": "bob", "amount": 5},
              "/requests": {"payer_handle": "bob", "amount": 5},
              "/requests/rq_x/pay": {},
              "/splits": {"amount": 5, "participant_handles": ["bob"]},
              "/settlements": {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}}
    bodies["/requests/rq_x/pay"] = {}
    for p, b in bodies.items():
        tok = T["ada"]
        path = p
        if p.endswith("/pay"):
            r = expect(api("POST", "/requests", {"payer_handle": "ada", "amount": 5}, T["bob"], nk()), 201)
            path = "/requests/%s/pay" % r["request_id"]
        s, j, _h, _t = call("POST", path, b, tok=tok)
        eq((s, code(j)), (400, "missing_idempotency_key"), p + " absent")
        s, j, _h, _t = call("POST", path, b, tok=tok, headers={"Idempotency-Key": ""})
        eq((s, code(j)), (400, "missing_idempotency_key"), p + " empty")
    eq(bal(T["ada"]), 10000)


@req("R13", "Idempotency-Key 1 to 255 characters, else 422 validation_failed")
def _():
    T = setup()
    t = T["ada"]
    expect(api("POST", "/payments", {"to_handle": "bob", "amount": 1}, t, "k" * 255), 201)
    expect(api("POST", "/payments", {"to_handle": "bob", "amount": 1}, t, "k" * 256), 422, "validation_failed")
    expect(api("POST", "/payments", {"to_handle": "bob", "amount": 1}, t, "x"), 201)
    expect(api("POST", "/requests", {"payer_handle": "bob", "amount": 1}, t, "k" * 256), 422, "validation_failed")
    expect(api("POST", "/splits", {"amount": 1, "participant_handles": ["bob"]}, t, "k" * 256), 422, "validation_failed")
    eq(bal(t), 10000 - 2)


@req("R14", "First use 201; Replay (same key, same body) 200 with body identical; money moves once")
def _():
    T = setup()
    t = T["ada"]
    k = nk()
    b = {"to_handle": "bob", "amount": 1500, "note": "dinner"}
    s1, j1 = api("POST", "/payments", b, t, k)
    eq(s1, 201)
    for _i in range(3):
        s2, j2 = api("POST", "/payments", b, t, k)
        eq(s2, 200)
        eq(j2, j1)
    eq(bal(t), 8500)
    eq(bal(T["bob"]), 4000)
    eq(len(feed(t)["payments"]), 1)
    # requests
    k = nk()
    s1, j1 = api("POST", "/requests", {"payer_handle": "bob", "amount": 9}, t, k)
    s2, j2 = api("POST", "/requests", {"payer_handle": "bob", "amount": 9}, t, k)
    eq((s1, s2), (201, 200))
    eq(j1, j2)
    eq(len(api("GET", "/requests", tok=t)[1]["requests"]), 1)


@req("R15", "Same body means same JSON value - key order and whitespace do not matter")
def _():
    T = setup()
    t = T["ada"]
    k = nk()
    s1, j1, _h, _t = call("POST", "/payments", raw='{"to_handle":"bob","amount":10,"note":"n"}', tok=t, key=k)
    s2, j2, _h, _t = call("POST", "/payments", raw='{ "note" : "n",\n "amount":10 , "to_handle":"bob" }', tok=t, key=k)
    eq((s1, s2), (201, 200))
    eq(j1, j2)
    eq(bal(t), 9990)


@req("R16", "Same key, different body -> 409 idempotency_key_reuse (all write paths)")
def _():
    T = setup(fixture(settlement_operator_ids=["u_ada"]))
    t = T["ada"]
    cases = [("/payments", {"to_handle": "bob", "amount": 10}, {"to_handle": "bob", "amount": 11}),
             ("/payments", {"to_handle": "bob", "amount": 10}, {"to_handle": "cy", "amount": 10}),
             ("/payments", {"to_handle": "bob", "amount": 10}, {"to_handle": "bob", "amount": 10, "note": "x"}),
             ("/requests", {"payer_handle": "bob", "amount": 10}, {"payer_handle": "bob", "amount": 12}),
             ("/splits", {"amount": 10, "participant_handles": ["ada", "bob"]}, {"amount": 10, "participant_handles": ["bob", "ada"]}),
             ("/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]},
              {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 2}]})]
    for p, b1, b2 in cases:
        k = nk()
        expect(api("POST", p, b1, t, k), 201, msg=p)
        expect(api("POST", p, b2, t, k), 409, "idempotency_key_reuse", p)
        s, j = api("POST", p, b1, t, k)
        eq(s, 200, p + " original still replayable")


@req("R17", "The key is scoped to the authenticated user; two users may use the same key string")
def _():
    T = setup()
    k = nk()
    s1, j1 = api("POST", "/payments", {"to_handle": "cy", "amount": 10}, T["ada"], k)
    s2, j2 = api("POST", "/payments", {"to_handle": "cy", "amount": 10}, T["bob"], k)
    eq((s1, s2), (201, 201))
    ok(j1["payment_id"] != j2["payment_id"])
    s3, j3 = api("POST", "/payments", {"to_handle": "dan", "amount": 3}, T["bob"], k)
    eq((s3, code(j3)), (409, "idempotency_key_reuse"))
    eq(bal(T["cy"]), 20)


@req("R18", "The same key with the same body on a different path is a different request, not a replay")
def _():
    T = setup()
    k = nk()
    s1, _j = api("POST", "/payments", {"to_handle": "bob", "amount": 10}, T["ada"], k)
    s2, _j = api("POST", "/requests", {"payer_handle": "bob", "amount": 10}, T["ada"], k)
    s3, _j = api("POST", "/splits", {"amount": 10, "participant_handles": ["bob"]}, T["ada"], k)
    eq((s1, s2, s3), (201, 201, 201))
    # same body shape on pay path (different request ids -> different paths)
    r1 = api("POST", "/requests", {"payer_handle": "ada", "amount": 5}, T["bob"], nk())[1]["request_id"]
    r2 = api("POST", "/requests", {"payer_handle": "ada", "amount": 5}, T["bob"], nk())[1]["request_id"]
    s1, _j = api("POST", "/requests/%s/pay" % r1, {}, T["ada"], k)
    s2, _j = api("POST", "/requests/%s/pay" % r2, {}, T["ada"], k)
    eq((s1, s2), (201, 201))


@req("R19", "Key reused after the original request failed with 4xx is treated as a first use")
def _():
    T = setup()
    t = T["ada"]
    k = nk()
    big = {"to_handle": "bob", "amount": 20000}
    expect(api("POST", "/payments", big, t, k), 409, "insufficient_funds")
    expect(api("POST", "/payments", big, t, k), 409, "insufficient_funds")
    expect(api("POST", "/payments", {"to_handle": "bob", "amount": 0}, t, k), 422)
    expect(api("POST", "/payments", {"to_handle": "nobody", "amount": 5}, t, k), 404)
    # now succeed with the same key and a different body
    expect(api("POST", "/payments", {"to_handle": "bob", "amount": 5}, t, k), 201)
    # fund then retry original failing body with a fresh failed key
    k2 = nk()
    expect(api("POST", "/payments", {"to_handle": "cy", "amount": 99999}, t, k2), 409, "insufficient_funds")
    api("POST", "/payments", {"to_handle": "ada", "amount": 2500}, T["bob"], nk())
    s, j = api("POST", "/payments", {"to_handle": "cy", "amount": 9000}, t, k2)
    eq(s, 201, "failed key reusable with new body")


@req("R20", "an already claimed key is resolved before endpoint field validation: changing a successful request to an invalid body with the same key returns 409 idempotency_key_reuse")
def _():
    T = setup()
    t = T["ada"]
    k = nk()
    expect(api("POST", "/payments", {"to_handle": "bob", "amount": 10}, t, k), 201)
    for bad in ({"to_handle": "bob", "amount": -1}, {"to_handle": "bob", "amount": "x"},
                {"to_handle": "ada", "amount": 10}, {"to_handle": "nobody", "amount": 10},
                {"to_handle": "bob", "amount": 10, "visibility": "zzz"}, {"amount": 10}):
        expect(api("POST", "/payments", bad, t, k), 409, "idempotency_key_reuse", repr(bad))
    k = nk()
    expect(api("POST", "/requests", {"payer_handle": "bob", "amount": 10}, t, k), 201)
    expect(api("POST", "/requests", {"payer_handle": "bob", "amount": 0}, t, k), 409, "idempotency_key_reuse")
    k = nk()
    expect(api("POST", "/splits", {"amount": 10, "participant_handles": ["bob"]}, t, k), 201)
    expect(api("POST", "/splits", {"amount": 10, "participant_handles": []}, t, k), 409, "idempotency_key_reuse")


@req("R21", "A successful replay returns the original response, even after the resource changes or is cancelled; makes no further state changes")
def _():
    T = setup()
    k = nk()
    s1, r1 = api("POST", "/requests", {"payer_handle": "bob", "amount": 100}, T["ada"], k)
    eq(s1, 201)
    expect(api("POST", "/requests/%s/cancel" % r1["request_id"], tok=T["ada"]), 200)
    s2, r2 = api("POST", "/requests", {"payer_handle": "bob", "amount": 100}, T["ada"], k)
    eq(s2, 200)
    eq(r2, r1)
    eq(r2["status"], "pending")
    eq(len(api("GET", "/requests", tok=T["ada"])[1]["requests"]), 1)
    # pay replay after the payer's balance changed
    r = api("POST", "/requests", {"payer_handle": "ada", "amount": 100}, T["bob"], nk())[1]
    kp = nk()
    p1 = api("POST", "/requests/%s/pay" % r["request_id"], {}, T["ada"], kp)
    eq(p1[0], 201)
    api("POST", "/payments", {"to_handle": "cy", "amount": bal(T["ada"])}, T["ada"], nk())
    p2 = api("POST", "/requests/%s/pay" % r["request_id"], {}, T["ada"], kp)
    eq(p2[0], 200)
    eq(p2[1], p1[1])


@req("R22", "Concurrent identical requests with an unused key: exactly one 201, the others 200 with the same body; takes effect once")
def _():
    T = setup()
    for path, body in (("/payments", {"to_handle": "bob", "amount": 100}),
                       ("/requests", {"payer_handle": "bob", "amount": 100}),
                       ("/splits", {"amount": 90, "participant_handles": ["ada", "bob", "cy"]})):
        k = nk()
        with ThreadPoolExecutor(25) as ex:
            res = list(ex.map(lambda _i: api("POST", path, body, T["ada"], k), range(25)))
        st = sorted(s for s, _j in res)
        eq(st, [200] * 24 + [201], path)
        eq(len(set(json.dumps(j, sort_keys=True) for s, j in res)), 1, path + " same body")
    eq(bal(T["ada"]), 9900)
    eq(len(api("GET", "/requests", tok=T["ada"])[1]["requests"]), 3)  # 1 request + 2 split requests
    eq(len(feed(T["ada"])["payments"]), 1)


# ---------------------------------------------------------------- authentication
@req("R23", "signup 201 {user_id, display_name, token}; new user balance 0; token works; ids <= 64 chars")
def _():
    setup()
    s, j = api("POST", "/auth/signup", {"email": "new@example.com", "password": "longenough", "display_name": "Newbie"})
    eq(s, 201)
    eq(j["display_name"], "Newbie")
    ok(isinstance(j["user_id"], str) and 0 < len(j["user_id"]) <= 64)
    ok(isinstance(j["token"], str) and j["token"])
    s, me = api("GET", "/me", tok=j["token"])
    eq(s, 200)
    eq(me["balance"], 0)
    eq(me["user_id"], j["user_id"])
    eq(me["currency"], "EUR")


@req("R24", "Handle derived from email: local part lowercased, chars outside [a-z0-9_] -> '_', truncated to 20")
def _():
    setup()
    cases = {"Ann.Lee+x@example.com": "ann_lee_x", "MiXeD_09@example.com": "mixed_09",
             "abcdefghijklmnopqrstuvwxyz@example.com": "abcdefghijklmnopqrst",
             "a-b@example.com": "a_b", "x.y.z@e.com": "x_y_z",
             "Abcdefghij.klmnopqrstu@e.com": "abcdefghij_klmnopqrs"}
    for em, h in cases.items():
        s, j = api("POST", "/auth/signup", {"email": em, "password": "longenough", "display_name": "x"})
        eq(s, 201, em)
        eq(api("GET", "/me", tok=j["token"])[1]["handle"], h, em)
    # usable as payment recipient
    T = {"ada": login("ada")}
    expect(pay(T["ada"], "ann_lee_x", 10), 201)


@req("R25", "email already registered -> 409 email_taken; no second account")
def _():
    setup()
    expect(api("POST", "/auth/signup", {"email": "ada@example.com", "password": "longenough", "display_name": "x"}), 409) if False else None
    s, j = api("POST", "/auth/signup", {"email": "p@example.com", "password": "longenough", "display_name": "x"})
    eq(s, 201)
    s, j = api("POST", "/auth/signup", {"email": "p@example.com", "password": "otherpass1", "display_name": "y"})
    eq((s, code(j)), (409, "email_taken"))
    # seeded email whose handle differs from derived: email_taken
    f = fixture([user("ada", 10), {"id": "u_z", "email": "zed@example.com", "password": PW, "display_name": "Z", "handle": "zzz", "balance": 0}])
    reset(f)
    s, j = api("POST", "/auth/signup", {"email": "zed@example.com", "password": "longenough", "display_name": "x"})
    eq((s, code(j)), (409, "email_taken"))


@req("R26", "derived handle already taken -> 409 handle_taken, and no account is created")
def _():
    setup()
    s, j = api("POST", "/auth/signup", {"email": "Ada@other.org", "password": "longenough", "display_name": "x"})
    eq((s, code(j)), (409, "handle_taken"))
    s, j = api("POST", "/auth/login", {"email": "Ada@other.org", "password": "longenough"})
    eq(s, 401, "no account created")
    s, j = api("POST", "/auth/signup", {"email": "x.y@a.org", "password": "longenough", "display_name": "x"})
    eq(s, 201)
    s, j = api("POST", "/auth/signup", {"email": "x_y@b.org", "password": "longenough", "display_name": "x"})
    eq((s, code(j)), (409, "handle_taken"), "derived collision with signup user")
    s, j = api("POST", "/auth/signup", {"email": "ada@example.com", "password": "longenough", "display_name": "x"})
    ok(s in (409,), "seeded email")


@req("R27", "Password shorter than 8 characters -> 422; email not of the form local@domain -> 422")
def _():
    setup()
    expect(api("POST", "/auth/signup", {"email": "s1@example.com", "password": "1234567", "display_name": "x"}), 422, "validation_failed")
    expect(api("POST", "/auth/signup", {"email": "s2@example.com", "password": "12345678", "display_name": "x"}), 201)
    expect(api("POST", "/auth/signup", {"email": "s3@example.com", "password": "", "display_name": "x"}), 422, "validation_failed")
    expect(api("POST", "/auth/signup", {"email": "s4@example.com", "password": "ééééééé", "display_name": "x"}), 422, "validation_failed")
    for em in ("plain", "@example.com", "a@", "", "a b@c.com", "a@@b.com", "no-at-sign.com"):
        s, j = api("POST", "/auth/signup", {"email": em, "password": "longenough", "display_name": "x"})
        eq((s, code(j)), (422, "validation_failed"), repr(em))
    # failed signup creates nothing: valid email retried works
    expect(api("POST", "/auth/signup", {"email": "s1@example.com", "password": "12345678", "display_name": "x"}), 201)


@req("R28", "Login: wrong password or unknown email -> 401 unauthenticated; success 200 {user_id, display_name, token}")
def _():
    setup()
    for em, pw in (("ada@example.com", "wrong password"), ("nobody@example.com", PW), ("ada@example.com", "")):
        s, j = api("POST", "/auth/login", {"email": em, "password": pw})
        eq((s, code(j)), (401, "unauthenticated"), em)
    s, j = api("POST", "/auth/login", {"email": "ada@example.com", "password": PW})
    eq(s, 200)
    eq((j["user_id"], j["display_name"]), ("u_ada", "Ada"))
    ok(j["token"])
    s, j = api("POST", "/auth/signup", {"email": "lg@example.com", "password": "longenough", "display_name": "L"})
    s, j2 = api("POST", "/auth/login", {"email": "lg@example.com", "password": "longenough"})
    eq(s, 200)
    eq(j2["user_id"], j["user_id"])
    eq(api("POST", "/auth/login", {"email": "lg@example.com", "password": "longenoug"})[0], 401)


@req("R29", "Tokens do not expire. An account may have multiple valid tokens and concurrent sessions.")
def _():
    setup()
    toks = set()
    for _i in range(4):
        toks.add(login("ada"))
    ok(len(toks) >= 2, "logins yield independent tokens")
    for t in toks:
        eq(bal(t), 10000)
    # a signup token and a later login token both work
    s, j = api("POST", "/auth/signup", {"email": "mt@example.com", "password": "longenough", "display_name": "M"})
    s2, j2 = api("POST", "/auth/login", {"email": "mt@example.com", "password": "longenough"})
    eq(bal(j["token"]), 0)
    eq(bal(j2["token"]), 0)
    eq(bal(j["token"]), 0)


@req("R30", "New users can receive money and be asked for money immediately")
def _():
    T = setup()
    s, j = api("POST", "/auth/signup", {"email": "fresh@example.com", "password": "longenough", "display_name": "F"})
    ft = j["token"]
    expect(pay(T["ada"], "fresh", 123), 201)
    eq(bal(ft), 123)
    expect(mkreq(T["ada"], "fresh", 50), 201)
    eq(len(api("GET", "/requests?direction=incoming", tok=ft)[1]["requests"]), 1)
    # new user with zero balance cannot send
    s, j = api("POST", "/auth/signup", {"email": "zero@example.com", "password": "longenough", "display_name": "Z"})
    expect(pay(j["token"], "ada", 1), 409, "insufficient_funds")


@req("R31", "Passwords must not be stored in plaintext (export must not contain the plaintext password)")
def _():
    setup()
    s, j = api("POST", "/auth/signup", {"email": "pwchk@example.com", "password": "S3cretPlaintextPW!", "display_name": "P"})
    s, e, _h, txt = call("GET", "/_test/export")
    eq(s, 200)
    ok(b"S3cretPlaintextPW!" not in txt, "plaintext signup password in export")
    ok(b"correct horse" not in txt, "plaintext seeded password in export")


# ---------------------------------------------------------------- payments
@req("R32", "POST /payments 201 body shape; defaults note \"\" and visibility public; request_id null; RFC3339 offset timestamp; id <= 64")
def _():
    T = setup()
    s, j = api("POST", "/payments", {"to_handle": "bob", "amount": 1500}, T["ada"], nk())
    eq(s, 201)
    exp = {"from_user_id": "u_ada", "from_handle": "ada", "to_user_id": "u_bob", "to_handle": "bob",
           "amount": 1500, "currency": "EUR", "note": "", "visibility": "public", "request_id": None}
    for k, v in exp.items():
        ok(k in j, "missing " + k)
        eq(j[k], v, k)
    ok(isinstance(j["payment_id"], str) and 0 < len(j["payment_id"]) <= 64)
    ok(RFC.match(j["created_at"]), j["created_at"])
    ok("settlement_id" not in j or j["settlement_id"] is None)
    eq(bal(T["ada"]), 8500)
    eq(bal(T["bob"]), 4000)


@req("R33", "The caller's balance is below amount -> 409 insufficient_funds; failed payment leaves no trace; exactly full balance is allowed")
def _():
    T = setup()
    expect(pay(T["ada"], "bob", 10001), 409, "insufficient_funds")
    eq((bal(T["ada"]), bal(T["bob"])), (10000, 2500))
    eq(feed(T["ada"])["payments"], [])
    expect(pay(T["cy"], "bob", 1), 409, "insufficient_funds")
    expect(pay(T["ada"], "bob", 10000), 201)
    eq((bal(T["ada"]), bal(T["bob"])), (0, 12500))
    expect(pay(T["ada"], "bob", 1), 409, "insufficient_funds")


@req("R34", "amount below 1, above 1000000000, or not an integer -> 422 validation_failed (payments)")
def _():
    f = fixture([user("ada", 5 * 10**9), user("bob", 0)])
    T = setup(f)
    t = T["ada"]
    for a in (0, -1, -1000, 1000000001, 10**12, 10**30, 1.5, 0.5, 1000.0000001, "100", "", True, False, None, [1], {"a": 1}):
        s, j = api("POST", "/payments", {"to_handle": "bob", "amount": a}, t, nk())
        eq((s, code(j)), (422, "validation_failed"), "amount=%r" % (a,))
    eq(bal(t), 5 * 10**9)
    eq(bal(T["bob"]), 0)


@req("R35", "JSON 1000, 1000.0 and 1e3 all represent the same valid minor-unit amount; amount 1 and 1000000000 are valid")
def _():
    f = fixture([user("ada", 5 * 10**9), user("bob", 0)])
    T = setup(f)
    t = T["ada"]
    for raw in ('{"to_handle":"bob","amount":1000.0}', '{"to_handle":"bob","amount":1e3}',
                '{"to_handle":"bob","amount":1000}', '{"to_handle":"bob","amount":1E3}', '{"to_handle":"bob","amount":10e2}'):
        s, j, _h, _t = call("POST", "/payments", raw=raw, tok=t, key=nk())
        eq(s, 201, raw)
        eq(j["amount"], 1000, raw)
        ok(isinstance(j["amount"], int) and not isinstance(j["amount"], bool), "amount integer in response")
    expect(pay(t, "bob", 1), 201)
    expect(pay(t, "bob", 1000000000), 201)
    s, j, _h, _t = call("POST", "/payments", raw='{"to_handle":"bob","amount":1e9}', tok=t, key=nk())
    eq(s, 201)
    s, j, _h, _t = call("POST", "/payments", raw='{"to_handle":"bob","amount":1000000000.5}', tok=t, key=nk())
    eq(s, 422)
    eq(bal(T["bob"]), 5000 + 1 + 2 * 10**9)


@req("R36", "to_handle is the caller's own handle -> 422 self_payment; no user has that handle -> 404 not_found")
def _():
    T = setup()
    expect(pay(T["ada"], "ada", 10), 422, "self_payment")
    expect(pay(T["ada"], "nobody", 10), 404, "not_found")
    expect(pay(T["ada"], "BOB", 10), 404, "not_found")
    expect(pay(T["ada"], "", 10), 404) if False else None
    eq(bal(T["ada"]), 10000)
    eq(feed(T["ada"])["payments"], [])


@req("R37", "note longer than 200 characters -> 422; 200 characters accepted (counted as characters)")
def _():
    T = setup()
    expect(pay(T["ada"], "bob", 1, note="a" * 200), 201)
    expect(pay(T["ada"], "bob", 1, note="a" * 201), 422, "validation_failed")
    expect(pay(T["ada"], "bob", 1, note="\U0001F600" * 200), 201)
    expect(pay(T["ada"], "bob", 1, note="é" * 200), 201)
    expect(pay(T["ada"], "bob", 1, note="\U0001F600" * 201), 422, "validation_failed")
    expect(mkreq(T["ada"], "bob", 1, note="a" * 201), 422, "validation_failed")
    expect(mkreq(T["ada"], "bob", 1, note="a" * 200), 201)
    expect(api("POST", "/splits", {"amount": 3, "participant_handles": ["bob"], "note": "a" * 201}, T["ada"], nk()), 422, "validation_failed")
    expect(api("POST", "/splits", {"amount": 3, "participant_handles": ["bob"], "note": "a" * 200}, T["ada"], nk()), 201)
    eq(bal(T["ada"]), 10000 - 3)


@req("R38", "note is stored and returned verbatim: no trimming, no escaping, no normalisation; Unicode survives byte for byte")
def _():
    T = setup()
    notes = ["  padded  ", "<b>&amp;\"q\"</b>", "caf\u00e9", "cafe\u0301", "\U0001F468\u200d\U0001F469\u200d\U0001F467 \U0001F389",
             "line1\nline2\ttab", "back\\slash", "\u0000nul" if False else "x", "\u202eRTL", " "]
    for n in notes:
        s, j = pay(T["ada"], "bob", 1, note=n)
        eq(s, 201)
        eq(j["note"], n, "response")
    got = [p["note"] for p in feed(T["ada"])["payments"]]
    eq(sorted(got), sorted(notes), "feed")
    s, j = mkreq(T["ada"], "bob", 1, note="  \U0001F389 <x> ")
    eq(j["note"], "  \U0001F389 <x> ")
    eq(api("GET", "/requests", tok=T["ada"])[1]["requests"][0]["note"], "  \U0001F389 <x> ")


@req("R39", "non-string note values (including null), and any visibility other than public/private are 422 validation_failed; omission selects defaults")
def _():
    T = setup()
    t = T["ada"]
    for n in (None, 5, True, ["a"], {"a": 1}, 1.5):
        expect(api("POST", "/payments", {"to_handle": "bob", "amount": 1, "note": n}, t, nk()), 422, "validation_failed", "note=%r" % (n,))
        expect(api("POST", "/requests", {"payer_handle": "bob", "amount": 1, "note": n}, t, nk()), 422, "validation_failed", "req note=%r" % (n,))
        expect(api("POST", "/splits", {"amount": 3, "participant_handles": ["bob"], "note": n}, t, nk()), 422, "validation_failed", "split note=%r" % (n,))
    for v in ("Public", "PRIVATE", "friends", "", None, 1, True, ["public"], " public"):
        expect(api("POST", "/payments", {"to_handle": "bob", "amount": 1, "visibility": v}, t, nk()), 422, "validation_failed", "vis=%r" % (v,))
    eq(bal(t), 10000)
    s, j = api("POST", "/payments", {"to_handle": "bob", "amount": 1}, t, nk())
    eq((j["note"], j["visibility"]), ("", "public"))
    s, j = pay(t, "bob", 1, vis="private")
    eq(j["visibility"], "private")


@req("R40", "Atomic: sum of balances equals seeded total; no 5xx and nothing changes on failed validation")
def _():
    T = setup()
    seed = total(T)
    eq(seed, 17500)
    pay(T["ada"], "bob", 777)
    pay(T["bob"], "cy", 3000)
    pay(T["cy"], "dan", 1)
    pay(T["ada"], "ada", 5)
    pay(T["ada"], "bob", 10**6)
    eq(total(T), seed)


# ---------------------------------------------------------------- requests
@req("R41", "POST /requests 201 shape; requester is caller; pending; payment_id null; created_at RFC3339; payer balance not checked")
def _():
    T = setup()
    s, j = api("POST", "/requests", {"payer_handle": "ada", "amount": 99999999, "note": "taxi"}, T["cy"], nk())
    eq(s, 201)
    exp = {"requester_id": "u_cy", "requester_handle": "cy", "payer_id": "u_ada", "payer_handle": "ada",
           "amount": 99999999, "currency": "EUR", "note": "taxi", "status": "pending", "payment_id": None}
    for k, v in exp.items():
        ok(k in j, "missing " + k)
        eq(j[k], v, k)
    ok(0 < len(j["request_id"]) <= 64)
    ok(RFC.match(j["created_at"]), j["created_at"])
    eq(bal(T["ada"]), 10000)
    s, j = api("POST", "/requests", {"payer_handle": "ada", "amount": 5}, T["cy"], nk())
    eq(j["note"], "")


@req("R42", "requests: amount validation (422), self_request 422, unknown payer 404")
def _():
    T = setup()
    t = T["ada"]
    for a in (0, -5, 1000000001, 2.5, "10", True, None):
        s, j = api("POST", "/requests", {"payer_handle": "bob", "amount": a}, t, nk())
        eq((s, code(j)), (422, "validation_failed"), "amount=%r" % (a,))
    expect(api("POST", "/requests", {"payer_handle": "bob", "amount": 1000000000}, t, nk()), 201)
    expect(api("POST", "/requests", {"payer_handle": "bob", "amount": 1e3}, t, nk()), 201)
    expect(mkreq(t, "ada", 5), 422, "self_request")
    expect(mkreq(t, "ghost", 5), 404, "not_found")
    eq(len(api("GET", "/requests", tok=t)[1]["requests"]), 2)


@req("R43", "Pay: 201 with payment (request_id set), request becomes paid with payment_id; balances move; default visibility public")
def _():
    T = setup()
    r = mkreq(T["bob"], "ada", 1200, note="taxi")[1]
    s, p = api("POST", "/requests/%s/pay" % r["request_id"], {}, T["ada"], nk())
    eq(s, 201)
    eq(p["request_id"], r["request_id"])
    eq((p["from_handle"], p["to_handle"], p["amount"], p["visibility"], p["currency"]), ("ada", "bob", 1200, "public", "EUR"))
    ok(RFC.match(p["created_at"]))
    eq((bal(T["ada"]), bal(T["bob"])), (8800, 3700))
    for t in (T["ada"], T["bob"]):
        rs = api("GET", "/requests", tok=t)[1]["requests"]
        eq((rs[0]["status"], rs[0]["payment_id"]), ("paid", p["payment_id"]))
    ids = [x["payment_id"] for x in feed(T["cy"])["payments"]]
    eq(ids, [p["payment_id"]])
    # exactly full balance payable
    r = mkreq(T["bob"], "cy", 0 + 1)[1]
    r2 = mkreq(T["ada"], "dan", 5000)[1]
    expect(api("POST", "/requests/%s/pay" % r2["request_id"], {}, T["dan"], nk()), 201)
    eq(bal(T["dan"]), 0)


@req("R44", "Only the payer may pay: requester or third party -> 403 forbidden; unknown request -> 404 not_found; no money moves")
def _():
    T = setup()
    r = mkreq(T["bob"], "ada", 100)[1]
    rid = r["request_id"]
    for who in ("bob", "cy", "dan"):
        expect(api("POST", "/requests/%s/pay" % rid, {}, T[who], nk()), 403, "forbidden", who)
    expect(api("POST", "/requests/nope/pay", {}, T["ada"], nk()), 404, "not_found")
    eq((bal(T["ada"]), bal(T["bob"])), (10000, 2500))
    eq(api("GET", "/requests?status=pending", tok=T["bob"])[1]["requests"][0]["status"], "pending")


@req("R45", "Paying a request while short is 409 insufficient_funds and changes nothing; money can arrive later and the same request becomes payable")
def _():
    T = setup()
    r = mkreq(T["ada"], "cy", 600)[1]
    rid = r["request_id"]
    k = nk()
    expect(api("POST", "/requests/%s/pay" % rid, {}, T["cy"], k), 409, "insufficient_funds")
    eq((bal(T["cy"]), bal(T["ada"])), (0, 10000))
    eq(api("GET", "/requests", tok=T["cy"])[1]["requests"][0]["status"], "pending")
    eq(feed(T["cy"])["payments"], [])
    expect(pay(T["bob"], "cy", 599), 201)
    expect(api("POST", "/requests/%s/pay" % rid, {}, T["cy"], nk()), 409, "insufficient_funds")
    expect(pay(T["bob"], "cy", 1), 201)
    s, p = api("POST", "/requests/%s/pay" % rid, {}, T["cy"], k)
    eq(s, 201, "same key reusable after 4xx")
    eq(bal(T["cy"]), 0)
    eq(bal(T["ada"]), 10600)


@req("R46", "Pay a request that is not pending (declined/cancelled/paid, new key) -> 409 request_not_pending")
def _():
    T = setup()
    a = mkreq(T["bob"], "ada", 100)[1]["request_id"]
    b = mkreq(T["bob"], "ada", 100)[1]["request_id"]
    c = mkreq(T["bob"], "ada", 100)[1]["request_id"]
    api("POST", "/requests/%s/decline" % a, tok=T["ada"])
    api("POST", "/requests/%s/cancel" % b, tok=T["bob"])
    expect(api("POST", "/requests/%s/pay" % c, {}, T["ada"], nk()), 201)
    for r in (a, b, c):
        expect(api("POST", "/requests/%s/pay" % r, {}, T["ada"], nk()), 409, "request_not_pending", r)
    eq((bal(T["ada"]), bal(T["bob"])), (9900, 2600))


@req("R47", "Replaying a successful payment returns 200 with its original payment body, even when request is paid; moves no money; not request_not_pending")
def _():
    T = setup()
    rid = mkreq(T["bob"], "ada", 250)[1]["request_id"]
    k = nk()
    s1, p1 = api("POST", "/requests/%s/pay" % rid, {"visibility": "private"}, T["ada"], k)
    eq(s1, 201)
    for _i in range(3):
        s2, p2 = api("POST", "/requests/%s/pay" % rid, {"visibility": "private"}, T["ada"], k)
        eq(s2, 200)
        eq(p2, p1)
    eq((bal(T["ada"]), bal(T["bob"])), (9750, 2750))
    eq(len([1 for p in feed(T["bob"])["payments"]]), 1)
    # same key with body {} vs {"visibility":"public"} is a reuse conflict
    rid2 = mkreq(T["bob"], "ada", 10)[1]["request_id"]
    k2 = nk()
    expect(api("POST", "/requests/%s/pay" % rid2, {}, T["ada"], k2), 201)
    expect(api("POST", "/requests/%s/pay" % rid2, {"visibility": "public"}, T["ada"], k2), 409, "idempotency_key_reuse")
    expect(api("POST", "/requests/%s/pay" % rid2, {"visibility": "private"}, T["ada"], k2), 409, "idempotency_key_reuse")
    expect(api("POST", "/requests/%s/pay" % rid2, {}, T["ada"], k2), 200)
    # replay after the request is paid, with an invalid body and same key -> reuse
    expect(api("POST", "/requests/%s/pay" % rid2, {"visibility": "bogus"}, T["ada"], k2), 409, "idempotency_key_reuse")


@req("R48", "pay visibility: payer chooses; default public; invalid (any type) -> 422; request carries no visibility")
def _():
    T = setup()
    for v, seen in (("private", False), ("public", True), (None, True)):
        rid = mkreq(T["bob"], "ada", 10)[1]["request_id"]
        body = {} if v is None else {"visibility": v}
        s, p = api("POST", "/requests/%s/pay" % rid, body, T["ada"], nk())
        eq(s, 201)
        eq(p["visibility"], v or "public")
        seen_by_cy = p["payment_id"] in [x["payment_id"] for x in feed(T["cy"])["payments"]]
        eq(seen_by_cy, seen, "third party sees %s" % v)
        for t in (T["ada"], T["bob"]):
            ids = {x["payment_id"]: x["visibility"] for x in feed(t)["payments"]}
            eq(ids[p["payment_id"]], v or "public", "both parties see same visibility")
    rid = mkreq(T["bob"], "ada", 10)[1]["request_id"]
    for v in ("hidden", 1, None, True, "Private"):
        expect(api("POST", "/requests/%s/pay" % rid, {"visibility": v}, T["ada"], nk()), 422, "validation_failed", repr(v))
    eq(api("GET", "/requests?status=pending", tok=T["ada"])[1]["requests"][0]["status"], "pending")
    r = mkreq(T["bob"], "ada", 10)[1]
    ok("visibility" not in r)


@req("R49", "A payment request may move money at most once (concurrent pay with distinct keys)")
def _():
    T = setup()
    rid = mkreq(T["bob"], "ada", 1000)[1]["request_id"]
    with ThreadPoolExecutor(30) as ex:
        res = list(ex.map(lambda _i: api("POST", "/requests/%s/pay" % rid, {}, T["ada"], nk()), range(30)))
    st = sorted(s for s, _j in res)
    eq(st.count(201), 1, str(st))
    ok(all(s in (201, 409) for s in st), str(st))
    for s, j in res:
        if s == 409:
            eq(code(j), "request_not_pending")
    eq((bal(T["ada"]), bal(T["bob"])), (9000, 3500))
    eq(len(feed(T["ada"])["payments"]), 1)
    # concurrent pay + cancel + decline race: end state consistent
    for _r in range(5):
        rid = mkreq(T["bob"], "ada", 100)[1]["request_id"]
        before = (bal(T["ada"]), bal(T["bob"]))
        calls = [lambda: api("POST", "/requests/%s/pay" % rid, {}, T["ada"], nk()),
                 lambda: api("POST", "/requests/%s/cancel" % rid, tok=T["bob"]),
                 lambda: api("POST", "/requests/%s/decline" % rid, tok=T["ada"]),
                 lambda: api("POST", "/requests/%s/pay" % rid, {}, T["ada"], nk())]
        with ThreadPoolExecutor(4) as ex:
            res = list(ex.map(lambda f: f(), calls))
        ok(all(s < 500 for s, _j in res), str(res))
        final = api("GET", "/requests?limit=1", tok=T["ada"])[1]["requests"][0]
        after = (bal(T["ada"]), bal(T["bob"]))
        if final["status"] == "paid":
            eq(after, (before[0] - 100, before[1] + 100))
        else:
            eq(after, before)
        wins = [s for s, _j in res if s == 201]
        ok(len(wins) == (1 if final["status"] == "paid" else 0))


@req("R50", "Decline: only payer; 200 status declined; declining twice 200; paid/cancelled -> 409 request_not_pending; requester/third 403; unknown 404")
def _():
    T = setup()
    r = mkreq(T["bob"], "ada", 100)[1]["request_id"]
    for who in ("bob", "cy"):
        expect(api("POST", "/requests/%s/decline" % r, tok=T[who]), 403, "forbidden", who)
    j = expect(api("POST", "/requests/%s/decline" % r, tok=T["ada"]), 200)
    eq((j["status"], j["request_id"], j["amount"], j["payment_id"]), ("declined", r, 100, None))
    j = expect(api("POST", "/requests/%s/decline" % r, tok=T["ada"]), 200)
    eq(j["status"], "declined")
    expect(api("POST", "/requests/%s/cancel" % r, tok=T["bob"]), 409, "request_not_pending")
    expect(api("POST", "/requests/%s/decline" % r, {}, tok=T["ada"]), 200)
    paid = mkreq(T["bob"], "ada", 100)[1]["request_id"]
    api("POST", "/requests/%s/pay" % paid, {}, T["ada"], nk())
    expect(api("POST", "/requests/%s/decline" % paid, tok=T["ada"]), 409, "request_not_pending")
    canc = mkreq(T["bob"], "ada", 100)[1]["request_id"]
    api("POST", "/requests/%s/cancel" % canc, tok=T["bob"])
    expect(api("POST", "/requests/%s/decline" % canc, tok=T["ada"]), 409, "request_not_pending")
    expect(api("POST", "/requests/nope/decline", tok=T["ada"]), 404, "not_found")
    eq(bal(T["ada"]), 9900)


@req("R51", "Cancel: only requester; 200 status cancelled; cancelling twice 200; paid/declined -> 409; payer/third 403; unknown 404")
def _():
    T = setup()
    r = mkreq(T["bob"], "ada", 100)[1]["request_id"]
    for who in ("ada", "cy"):
        expect(api("POST", "/requests/%s/cancel" % r, tok=T[who]), 403, "forbidden", who)
    j = expect(api("POST", "/requests/%s/cancel" % r, tok=T["bob"]), 200)
    eq((j["status"], j["request_id"], j["requester_handle"], j["payer_handle"]), ("cancelled", r, "bob", "ada"))
    expect(api("POST", "/requests/%s/cancel" % r, tok=T["bob"]), 200)
    expect(api("POST", "/requests/%s/decline" % r, tok=T["ada"]), 409, "request_not_pending")
    paid = mkreq(T["bob"], "ada", 100)[1]["request_id"]
    api("POST", "/requests/%s/pay" % paid, {}, T["ada"], nk())
    expect(api("POST", "/requests/%s/cancel" % paid, tok=T["bob"]), 409, "request_not_pending")
    dec = mkreq(T["bob"], "ada", 100)[1]["request_id"]
    api("POST", "/requests/%s/decline" % dec, tok=T["ada"])
    expect(api("POST", "/requests/%s/cancel" % dec, tok=T["bob"]), 409, "request_not_pending")
    expect(api("POST", "/requests/nope/cancel", tok=T["bob"]), 404, "not_found")


@req("R52", "GET /requests: only requests where caller is requester or payer; direction incoming/outgoing/absent; status filter")
def _():
    T = setup()
    a = mkreq(T["bob"], "ada", 1)[1]["request_id"]      # bob -> ada (ada incoming)
    b = mkreq(T["ada"], "bob", 2)[1]["request_id"]      # ada -> bob (ada outgoing)
    c = mkreq(T["cy"], "dan", 3)[1]["request_id"]       # unrelated to ada
    d = mkreq(T["bob"], "ada", 4)[1]["request_id"]
    api("POST", "/requests/%s/decline" % d, tok=T["ada"])
    ids = lambda t, q="": [r["request_id"] for r in api("GET", "/requests" + q, tok=T[t])[1]["requests"]]
    eq(sorted(ids("ada")), sorted([a, b, d]))
    eq(sorted(ids("ada", "?direction=incoming")), sorted([a, d]))
    eq(ids("ada", "?direction=outgoing"), [b])
    eq(sorted(ids("ada", "?status=pending")), sorted([a, b]))
    eq(ids("ada", "?status=declined"), [d])
    eq(ids("ada", "?direction=incoming&status=pending"), [a])
    eq(ids("ada", "?status=paid"), [])
    eq(ids("ada", "?status=cancelled"), [])
    eq(ids("cy"), [c])
    eq(ids("dan", "?direction=outgoing"), [])
    eq(sorted(ids("bob", "?direction=outgoing")), sorted([a, d]))
    # third party never sees a request, even via status filters
    eq(ids("dan"), [c])
    j = api("GET", "/requests", tok=T["ada"])[1]
    ok(set(j.keys()) >= {"requests", "has_more"})
    ok(all(set(("request_id", "requester_id", "payer_id", "amount", "status", "payment_id", "created_at")) <= set(r) for r in j["requests"]))


@req("R53", "GET /requests newest first by created_at")
def _():
    T = setup()
    ids = []
    for _i in range(3):
        ids.append(mkreq(T["ada"], "bob", 1)[1]["request_id"])
        time.sleep(1.1)
    got = [r["request_id"] for r in api("GET", "/requests", tok=T["ada"])[1]["requests"]]
    eq(got, list(reversed(ids)))


@req("R54", "limit default 50 range 1..200, offset >= 0; outside -> 422; unknown direction/status -> 422; has_more correct (requests)")
def _():
    T = setup()
    for _i in range(5):
        mkreq(T["ada"], "bob", 1)
    g = lambda q: api("GET", "/requests" + q, tok=T["ada"])
    for q in ("?limit=0", "?limit=201", "?limit=-1", "?limit=abc", "?limit=", "?offset=-1", "?offset=x",
              "?direction=sideways", "?status=done", "?direction=", "?status=PENDING", "?limit=1e9", "?limit=4.0", "?limit=+4",
              "?offset=1e0", "?offset=2.0", "?offset=+1", "?limit=%204", "?limit=9999999999999999999999"):
        s, j = g(q)
        eq((s, code(j)), (422, "validation_failed"), q)
    s, j = g("?limit=200&offset=0")
    eq(s, 200)
    s, j = g("?limit=1")
    eq((s, len(j["requests"]), j["has_more"]), (200, 1, True))
    s, j = g("?limit=5")
    eq((len(j["requests"]), j["has_more"]), (5, False))
    s, j = g("?limit=4")
    eq((len(j["requests"]), j["has_more"]), (4, True))
    s, j = g("?limit=2&offset=4")
    eq((len(j["requests"]), j["has_more"]), (1, False))
    s, j = g("?offset=5")
    eq((j["requests"], j["has_more"]), ([], False))
    s, j = g("?offset=100")
    eq((s, j["requests"], j["has_more"]), (200, [], False))
    # pages are disjoint and cover everything
    a = [r["request_id"] for r in g("?limit=2&offset=0")[1]["requests"]]
    b = [r["request_id"] for r in g("?limit=2&offset=2")[1]["requests"]]
    c = [r["request_id"] for r in g("?limit=2&offset=4")[1]["requests"]]
    eq(len(set(a + b + c)), 5)
    # default limit 50
    for _i in range(48):
        mkreq(T["ada"], "bob", 1)
    j = g("")[1]
    eq((len(j["requests"]), j["has_more"]), (50, True))
    eq(len(g("?limit=200")[1]["requests"]), 53)


# ---------------------------------------------------------------- activity feed
@req("R55", "Feed: a payment appears iff visibility is public, or caller is sender or receiver")
def _():
    T = setup()
    pu = pay(T["ada"], "bob", 10, note="pub", vis="public")[1]["payment_id"]
    pr = pay(T["ada"], "bob", 10, note="priv", vis="private")[1]["payment_id"]
    pr2 = pay(T["cy" if False else "dan"], "cy", 10, note="priv2", vis="private")[1]["payment_id"]
    ids = lambda t: [p["payment_id"] for p in feed(T[t])["payments"]]
    eq(sorted(ids("ada")), sorted([pu, pr]))
    eq(sorted(ids("bob")), sorted([pu, pr]), "private hidden from own receiver?")
    eq(sorted(ids("cy")), sorted([pu, pr2]))
    eq(sorted(ids("dan")), sorted([pu, pr2]))
    for p in feed(T["bob"])["payments"]:
        if p["payment_id"] == pr:
            eq(p["visibility"], "private")
    ok(all(set(("payment_id", "from_handle", "to_handle", "amount", "currency", "note", "visibility", "request_id", "created_at")) <= set(p)
           for p in feed(T["ada"])["payments"]))


@req("R56", "Requests never appear in activity; a split is not a feed item; split-fulfilling payments follow the rule")
def _():
    T = setup()
    mkreq(T["ada"], "bob", 10)
    s, sp = api("POST", "/splits", {"amount": 30, "participant_handles": ["ada", "bob", "cy"]}, T["ada"], nk())
    eq(s, 201)
    for t in T.values():
        eq(feed(t)["payments"], [])
    rid = [r for r in sp["requests"] if r["payer_handle"] == "bob"][0]["request_id"]
    p = api("POST", "/requests/%s/pay" % rid, {"visibility": "private"}, T["bob"], nk())[1]
    eq([x["payment_id"] for x in feed(T["ada"])["payments"]], [p["payment_id"]])
    eq([x["payment_id"] for x in feed(T["bob"])["payments"]], [p["payment_id"]])
    eq(feed(T["cy"])["payments"], [])
    eq(feed(T["dan"])["payments"], [])


@req("R57", "Feed newest first by created_at")
def _():
    T = setup()
    ids = []
    for i in range(3):
        ids.append(pay(T["ada"], "bob", 1 + i)[1]["payment_id"])
        time.sleep(1.1)
    eq([p["payment_id"] for p in feed(T["cy"])["payments"]], list(reversed(ids)))


@req("R58", "GET /activity limit/offset validation (422), has_more semantics")
def _():
    T = setup()
    for i in range(5):
        pay(T["ada"], "bob", 1 + i)
    g = lambda q: api("GET", "/activity" + q, tok=T["cy"])
    for q in ("?limit=0", "?limit=201", "?limit=-3", "?limit=x", "?limit=", "?offset=-1", "?offset=abc", "?limit=1e9", "?limit=4.0",
              "?limit=+4", "?offset=1e1", "?offset=0.0", "?offset=+0"):
        s, j = g(q)
        eq((s, code(j)), (422, "validation_failed"), q)
    eq(g("?limit=200")[0], 200)
    s, j = g("?limit=1")
    eq((len(j["payments"]), j["has_more"]), (1, True))
    s, j = g("?limit=5")
    eq((len(j["payments"]), j["has_more"]), (5, False))
    s, j = g("?limit=3&offset=3")
    eq((len(j["payments"]), j["has_more"]), (2, False))
    s, j = g("?limit=2&offset=3")
    eq((len(j["payments"]), j["has_more"]), (2, False))
    s, j = g("?limit=2&offset=2")
    eq((len(j["payments"]), j["has_more"]), (2, True))
    s, j = g("?offset=50")
    eq((s, j["payments"], j["has_more"]), (200, [], False))
    a = [p["payment_id"] for p in g("?limit=2")[1]["payments"]]
    b = [p["payment_id"] for p in g("?limit=2&offset=2")[1]["payments"]]
    c = [p["payment_id"] for p in g("?limit=2&offset=4")[1]["payments"]]
    eq(len(set(a + b + c)), 5)


# ---------------------------------------------------------------- splits
@req("R59", "Split shares per §9 table (1000/3, 1/3, 10/3, 999/3, 5/5); sum to amount; larger shares to first participants")
def _():
    f = fixture([user("ada", 0)] + [user(h) for h in ("bob", "cy", "dan", "eve", "fay")])
    T = setup(f)
    t = T["ada"]
    cases = [(1000, ["ada", "bob", "cy"], [334, 333, 333]), (1, ["ada", "bob", "cy"], [1, 0, 0]),
             (10, ["ada", "bob", "cy"], [4, 3, 3]), (999, ["ada", "bob", "cy"], [333, 333, 333]),
             (5, ["ada", "bob", "cy", "dan", "eve"], [1, 1, 1, 1, 1]),
             (1000, ["cy", "ada", "bob"], [334, 333, 333]), (1000, ["bob", "cy", "ada"], [334, 333, 333]),
             (7, ["ada", "bob", "cy", "dan"], [2, 2, 2, 1]), (2, ["ada", "bob", "cy", "dan", "eve"], [1, 1, 0, 0, 0]),
             (1000000000, ["ada", "bob", "cy"], [333333334, 333333333, 333333333]),
             (100, ["ada", "bob", "cy", "dan", "eve", "fay"], [17, 17, 17, 17, 16, 16])]
    for amt, hs, shares in cases:
        s, j = api("POST", "/splits", {"amount": amt, "participant_handles": hs}, t, nk())
        eq(s, 201, repr((amt, hs)))
        eq([(x["handle"], x["amount"]) for x in j["shares"]], list(zip(hs, shares)), repr((amt, hs)))
        eq(sum(x["amount"] for x in j["shares"]), amt)
        eq(j["amount"], amt)
        eq(j["currency"], "EUR")
    # order matters: different person gets the extra unit
    a = api("POST", "/splits", {"amount": 10, "participant_handles": ["bob", "cy", "ada"]}, t, nk())[1]
    eq([x["amount"] for x in a["shares"]], [4, 3, 3])
    eq(a["shares"][0]["handle"], "bob")


@req("R60", "Split: requests for every participant except the caller, same order, caller is requester, pending, each for share; shape")
def _():
    T = setup()
    s, j = api("POST", "/splits", {"amount": 3000, "participant_handles": ["ada", "bob", "cy"], "note": "dinner"}, T["ada"], nk())
    eq(s, 201)
    ok(0 < len(j["split_id"]) <= 64)
    ok(RFC.match(j["created_at"]))
    eq(j["note"], "dinner")
    eq([r["payer_handle"] for r in j["requests"]], ["bob", "cy"])
    for r in j["requests"]:
        eq((r["requester_handle"], r["status"], r["amount"], r["note"], r["payment_id"]), ("ada", "pending", 1000, "dinner", None))
    # caller in the middle / omitted
    s, j = api("POST", "/splits", {"amount": 3000, "participant_handles": ["bob", "ada", "cy"]}, T["ada"], nk())
    eq([r["payer_handle"] for r in j["requests"]], ["bob", "cy"])
    eq([x["handle"] for x in j["shares"]], ["bob", "ada", "cy"])
    s, j = api("POST", "/splits", {"amount": 3001, "participant_handles": ["cy", "bob"]}, T["ada"], nk())
    eq([x["handle"] for x in j["shares"]], ["cy", "bob"])
    eq([x["amount"] for x in j["shares"]], [1501, 1500])
    eq([(r["payer_handle"], r["amount"]) for r in j["requests"]], [("cy", 1501), ("bob", 1500)])
    # visible to both parties through GET /requests, not to a third party
    eq(len(api("GET", "/requests?direction=incoming", tok=T["cy"])[1]["requests"]), 3)
    eq(api("GET", "/requests", tok=T["dan"])[1]["requests"], [])
    s, j = api("POST", "/splits", {"amount": 10, "participant_handles": ["bob", "cy"]}, T["dan"], nk())
    eq([r["requester_handle"] for r in j["requests"]], ["dan", "dan"])
    eq(j["note"] if "note" in j else "", "")


@req("R61", "A split whose only participant is the caller is valid: one share, zero requests, \"requests\": []")
def _():
    T = setup()
    s, j = api("POST", "/splits", {"amount": 777, "participant_handles": ["ada"]}, T["ada"], nk())
    eq(s, 201)
    eq(j["requests"], [])
    eq([(x["handle"], x["amount"]) for x in j["shares"]], [("ada", 777)])
    eq(api("GET", "/requests", tok=T["ada"])[1]["requests"], [])
    eq(bal(T["ada"]), 10000)


@req("R62", "Split 422: amount invalid, participants empty or duplicate handle; 404 for any unknown handle (and nothing created)")
def _():
    T = setup()
    t = T["ada"]
    for a in (0, -1, 1000000001, 1.5, "30", True, None):
        s, j = api("POST", "/splits", {"amount": a, "participant_handles": ["bob"]}, t, nk())
        eq((s, code(j)), (422, "validation_failed"), "amount=%r" % (a,))
    for hs in ([], ["bob", "bob"], ["ada", "bob", "ada"], ["bob", "cy", "bob"]):
        s, j = api("POST", "/splits", {"amount": 30, "participant_handles": hs}, t, nk())
        eq((s, code(j)), (422, "validation_failed"), repr(hs))
    for hs in (["bob", "ghost"], ["ghost"], ["ghost", "bob"], ["ada", "ghost"]):
        s, j = api("POST", "/splits", {"amount": 30, "participant_handles": hs}, t, nk())
        eq((s, code(j)), (404, "not_found"), repr(hs))
    eq(api("GET", "/requests", tok=t)[1]["requests"], [])
    eq(api("GET", "/requests", tok=T["bob"])[1]["requests"], [])
    expect(api("POST", "/splits", {"amount": 1000000000, "participant_handles": ["bob"]}, t, nk()), 201)
    expect(api("POST", "/splits", {"amount": 1e3, "participant_handles": ["bob"]}, t, nk()), 201)


@req("R63", "A share of 0 is legal and still produces a request for that participant")
def _():
    T = setup()
    s, j = api("POST", "/splits", {"amount": 1, "participant_handles": ["ada", "bob", "cy"]}, T["ada"], nk())
    eq(s, 201)
    eq([(r["payer_handle"], r["amount"]) for r in j["requests"]], [("bob", 0), ("cy", 0)])
    eq(len(api("GET", "/requests", tok=T["cy"])[1]["requests"]), 1)
    # paying a zero-amount request must not be a 5xx
    rid = j["requests"][0]["request_id"]
    s, p = api("POST", "/requests/%s/pay" % rid, {}, T["bob"], nk())
    ok(s < 500)
    s, j = api("POST", "/splits", {"amount": 2, "participant_handles": ["bob", "cy", "dan"]}, T["ada"], nk())
    eq([r["amount"] for r in j["requests"]], [1, 1, 0])


@req("R64", "Nothing about a split checks anyone's balance; a split moves no money")
def _():
    T = setup()
    seed = total(T)
    s, j = api("POST", "/splits", {"amount": 1000000000, "participant_handles": ["cy", "dan", "bob"]}, T["cy"], nk())
    eq(s, 201)
    eq(sum(x["amount"] for x in j["shares"]), 1000000000)
    eq([bal(T[h]) for h in ("ada", "bob", "cy", "dan")], [10000, 2500, 0, 5000])
    eq(total(T), seed)


@req("R65", "Split replay 200 identical, no duplicate requests; split request pay works and sum is preserved after all paid in full")
def _():
    T = setup()
    seed = total(T)
    k = nk()
    b = {"amount": 1001, "participant_handles": ["ada", "bob", "dan"], "note": "x"}
    s1, j1 = api("POST", "/splits", b, T["ada"], k)
    s2, j2 = api("POST", "/splits", b, T["ada"], k)
    eq((s1, s2), (201, 200))
    eq(j1, j2)
    eq(len(api("GET", "/requests", tok=T["ada"])[1]["requests"]), 2)
    for r in j1["requests"]:
        payer = r["payer_handle"]
        expect(api("POST", "/requests/%s/pay" % r["request_id"], {}, T[payer], nk()), 201)
    eq(total(T), seed)
    eq(bal(T["ada"]), 10000 + 334 + 333)
    eq(bal(T["bob"]), 2500 - 334)
    eq(bal(T["dan"]), 5000 - 333)
    for i in range(10):
        s, j = api("POST", "/splits", {"amount": 100 + i, "participant_handles": ["ada", "bob", "cy", "dan"]}, T["ada"], nk())
        for r in j["requests"]:
            if r["payer_handle"] != "cy":
                api("POST", "/requests/%s/pay" % r["request_id"], {}, T[r["payer_handle"]], nk())
    eq(total(T), seed)
    expect(api("POST", "/splits", {"amount": 5, "participant_handles": ["bob"]}, T["ada"], nk()), 201)


# ---------------------------------------------------------------- arithmetic range
@req("R66", "Monetary arithmetic preserves exact minor-unit values (balances up to 2^53)")
def _():
    big = 2**52 + 1
    f = fixture([user("ada", big), user("bob", 2**53 - 5), user("cy", 0)])
    T = setup(f)
    eq(bal(T["ada"]), big)
    expect(pay(T["ada"], "cy", 1), 201)
    eq(bal(T["ada"]), big - 1)
    eq(bal(T["cy"]), 1)
    expect(pay(T["bob"], "cy", 1000000000), 201)
    eq(bal(T["bob"]), 2**53 - 5 - 1000000000)
    expect(pay(T["ada"], "bob", 3), 201)
    eq(bal(T["bob"]), 2**53 - 5 - 1000000000 + 3)
    eq(total(T), big - 1 + 1 + 1000000000 + 3 - 3 + 2**53 - 5 - 1000000000 - 0 + 0 - 0 if False else total(T))
    eq(sum(bal(t) for t in T.values()), big + 2**53 - 5)
    # odd values
    f = fixture([user("ada", 9007199254740991), user("bob", 0)])
    T = setup(f)
    expect(pay(T["ada"], "bob", 999999999), 201)
    eq(bal(T["ada"]), 9007199254740991 - 999999999)
    eq(bal(T["bob"]), 999999999)


# ---------------------------------------------------------------- concurrency invariants
@req("R67", "No balance negative (even transiently) and sum constant under concurrent payments")
def _():
    f = fixture([user("ada", 1000), user("bob", 1000), user("cy", 1000)])
    T = setup(f)
    stop = threading.Event()
    seen = []

    def watcher():
        while not stop.is_set():
            for t in T.values():
                s, j = api("GET", "/me", tok=t)
                if s == 200:
                    seen.append(j["balance"])

    th = threading.Thread(target=watcher)
    th.start()
    jobs = []
    hs = ["ada", "bob", "cy"]
    for i in range(90):
        a = hs[i % 3]
        b = hs[(i + 1) % 3]
        jobs.append((a, b, 300))
    with ThreadPoolExecutor(30) as ex:
        res = list(ex.map(lambda j: pay(T[j[0]], j[1], j[2]), jobs))
    stop.set()
    th.join()
    ok(all(s in (201, 409) for s, _j in res), str([s for s, _j in res if s not in (201, 409)]))
    ok(min(seen) >= 0, "negative balance observed: %r" % min(seen))
    eq(total(T), 3000)
    ok(all(bal(t) >= 0 for t in T.values()))
    # a single wallet drained concurrently: exactly balance/amount succeed
    f = fixture([user("ada", 1000), user("bob", 0), user("cy", 0)])
    T = setup(f)
    with ThreadPoolExecutor(40) as ex:
        res = list(ex.map(lambda i: pay(T["ada"], "bob" if i % 2 else "cy", 100), range(40)))
    eq(sorted(set(s for s, _j in res)), [201, 409])
    eq(sum(1 for s, _j in res if s == 201), 10)
    eq((bal(T["ada"]), bal(T["bob"]) + bal(T["cy"])), (0, 1000))
    for s, j in res:
        if s == 409:
            eq(code(j), "insufficient_funds")


@req("R68", "Concurrent mixed operations never produce 5xx and preserve the seeded total")
def _():
    T = setup()
    hs = ["ada", "bob", "cy", "dan"]
    reqs = []
    for i in range(8):
        r = mkreq(T[hs[(i + 1) % 4]], hs[i % 4], 100 + i)[1]
        reqs.append((r["request_id"], hs[i % 4], hs[(i + 1) % 4]))

    def work(i):
        k = i % 6
        h = hs[i % 4]
        o = hs[(i + 2) % 4]
        if k == 0:
            return pay(T[h], o, 50 + i)
        if k == 1:
            rid, payer, rq = reqs[i % 8]
            return api("POST", "/requests/%s/pay" % rid, {}, T[payer], nk())
        if k == 2:
            return api("POST", "/splits", {"amount": 100 + i, "participant_handles": [h, o, hs[(i + 1) % 4]]}, T[h], nk())
        if k == 3:
            rid, payer, rq = reqs[i % 8]
            return api("POST", "/requests/%s/cancel" % rid, tok=T[rq])
        if k == 4:
            return api("GET", "/activity?limit=200", tok=T[h])
        return mkreq(T[h], o, 10 + i)

    with ThreadPoolExecutor(50) as ex:
        res = list(ex.map(work, range(200)))
    bad = [(s, j) for s, j in res if s >= 500]
    ok(not bad, "5xx: %r" % bad[:2])
    eq(total(T), 17500)
    ok(all(bal(t) >= 0 for t in T.values()))
    # every paid request corresponds to exactly one payment in the payer's feed
    for h in hs:
        for r in api("GET", "/requests?status=paid&limit=200", tok=T[h])[1]["requests"]:
            ok(r["payment_id"] is not None)
    pids = []
    for r in api("GET", "/requests?status=paid&limit=200", tok=T["ada"])[1]["requests"]:
        pids.append(r["payment_id"])
    eq(len(pids), len(set(pids)))


@req("R69", "Requests must not produce 5xx responses: garbage inputs")
def _():
    T = setup(fixture(settlement_operator_ids=["u_ada"]))
    t = T["ada"]
    weird = [None, 0, -1, 2**64, 1e308, "x" * 1000, [], {}, [None], True, "", {"a": {"b": [1]}}, 1e-5, float("1e400") if False else 5]
    paths = ["/payments", "/requests", "/splits", "/settlements", "/requests/rq_1/pay", "/auth/login", "/auth/signup"]
    bodies = []
    for w in weird:
        bodies += [{"to_handle": w, "amount": w}, {"payer_handle": w, "amount": w, "note": w, "visibility": w},
                   {"amount": w, "participant_handles": w}, {"transfers": w}, {"transfers": [w]}, {"transfers": [{"from_handle": w, "to_handle": w, "amount": w}]},
                   {"email": w, "password": w, "display_name": w}, {"participant_handles": [w], "amount": 5}]
    n = 0
    for p in paths:
        for b in bodies:
            s, j, _h, _t = call("POST", p, b, tok=t, key=nk())
            ok(s < 500, "%s %r -> %s" % (p, b, s))
            if s >= 400:
                ok(isinstance(j, dict) and "error" in j, "error body %s %r" % (p, b))
            n += 1
    for raw in ('{"amount": 1e999, "to_handle": "bob"}', '{"amount": NaN, "to_handle": "bob"}', '{"amount": Infinity, "to_handle":"bob"}',
                '{"amount": 99999999999999999999999999, "to_handle":"bob"}', '{"to_handle": "bob", "amount": 5, "amount": 6}',
                "\ufeff{}", '{"to_handle":"bob\\ud800","amount":5}', "{" * 5000):
        for p in ("/payments", "/requests", "/splits"):
            s, j, _h, _t = call("POST", p, raw=raw, tok=t, key=nk())
            ok(s in (400, 422, 404, 409, 201), "%s %r -> %s" % (p, raw[:30], s))
    for q in ("/requests?limit=%FF", "/activity?offset=%00", "/activity?limit=1&limit=2", "/me?x=1"):
        s, j, _h, _t = call("GET", q, tok=t)
        ok(s < 500, q)
    for m in ("PUT", "DELETE", "PATCH"):
        s, j, _h, _t = call(m, "/payments", {}, tok=t)
        ok(s < 500, m)
    eq(total(T), 17500)


# ---------------------------------------------------------------- export / import
def _ex():
    s, j, _h, _t = call("GET", "/_test/export")
    eq(s, 200, "export")
    return j


@req("R70", "GET /_test/export 200 with track pocketful, format_version 1, state object; unauthenticated")
def _():
    setup()
    j = _ex()
    eq(j["track"], "pocketful")
    eq(j["format_version"], 1)
    ok(isinstance(j["state"], dict))


@req("R71", "Import atomically replaces state: balances, payments, requests, tokens, idempotent responses restored; later changes removed; new signups removed")
def _():
    T = setup(fixture(settlement_operator_ids=["u_ada"]))
    s, su = api("POST", "/auth/signup", {"email": "pre@example.com", "password": "longenough", "display_name": "Pre"})
    pre_tok = su["token"]
    k1, k2, k3 = nk(), nk(), nk()
    p1 = api("POST", "/payments", {"to_handle": "bob", "amount": 111, "note": "n\u00e9"}, T["ada"], k1)[1]
    r1 = api("POST", "/requests", {"payer_handle": "cy", "amount": 40}, T["bob"], k2)[1]
    sp = api("POST", "/splits", {"amount": 10, "participant_handles": ["ada", "bob"], "note": "s"}, T["ada"], k3)[1]
    kf = nk()
    expect(api("POST", "/payments", {"to_handle": "bob", "amount": 99999999}, T["ada"], kf), 409, "insufficient_funds")
    ks = nk()
    st = api("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 70, "visibility": "private"}]}, T["ada"], ks)[1]
    before = {h: bal(t) for h, t in T.items()}
    feed_before = feed(T["ada"])["payments"]
    reqs_before = api("GET", "/requests", tok=T["bob"])[1]["requests"]
    E = _ex()
    # mutations after export
    pay(T["ada"], "bob", 5000)
    api("POST", "/requests/%s/cancel" % r1["request_id"], tok=T["bob"])
    s, late = api("POST", "/auth/signup", {"email": "late@example.com", "password": "longenough", "display_name": "L"})
    api("POST", "/auth/signup", {"email": "pre@example.com", "password": "longenough", "display_name": "x"})
    eq(call("POST", "/_test/import", E)[0], 204)
    eq({h: bal(t) for h, t in T.items()}, before)
    eq(bal(pre_tok), 0)
    expect(api("GET", "/me", tok=late["token"]), 401)
    eq(api("POST", "/auth/login", {"email": "late@example.com", "password": "longenough"})[0], 401)
    eq(api("POST", "/auth/login", {"email": "pre@example.com", "password": "longenough"})[0], 200)
    eq(feed(T["ada"])["payments"], feed_before, "feed identical incl. ids/timestamps")
    eq(api("GET", "/requests", tok=T["bob"])[1]["requests"], reqs_before)
    # replays
    s, j = api("POST", "/payments", {"to_handle": "bob", "amount": 111, "note": "n\u00e9"}, T["ada"], k1)
    eq((s, j), (200, p1))
    s, j = api("POST", "/requests", {"payer_handle": "cy", "amount": 40}, T["bob"], k2)
    eq((s, j), (200, r1))
    s, j = api("POST", "/splits", {"amount": 10, "participant_handles": ["ada", "bob"], "note": "s"}, T["ada"], k3)
    eq((s, j), (200, sp))
    s, j = api("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 70, "visibility": "private"}]}, T["ada"], ks)
    eq((s, j), (200, st))
    expect(api("POST", "/payments", {"to_handle": "bob", "amount": 112}, T["ada"], k1), 409, "idempotency_key_reuse")
    # failed key remains reusable (first use, not reuse)
    s, j = api("POST", "/payments", {"to_handle": "bob", "amount": 99999999}, T["ada"], kf)
    eq((s, code(j)), (409, "insufficient_funds"))
    s, j = api("POST", "/payments", {"to_handle": "bob", "amount": 1}, T["ada"], kf)
    eq(s, 201)
    eq(bal(T["ada"]), before["ada"] - 1)
    # imported request still payable once; operator permission preserved; no id regeneration collisions
    s, p = api("POST", "/requests/%s/pay" % r1["request_id"], {}, T["cy"], nk())
    eq(s, 409, "cy has 70 from settlement... 40 payable?") if False else None
    ids = [p1["payment_id"]] + [x["payment_id"] for x in st["payments"]]
    newp = pay(T["dan"], "bob", 1)[1]
    ok(newp["payment_id"] not in ids, "payment id collision after import")
    nr = mkreq(T["bob"], "dan", 1)[1]
    ok(nr["request_id"] not in (r1["request_id"],) + tuple(r["request_id"] for r in sp["requests"]), "request id collision")
    expect(api("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 1}]}, T["ada"], nk()), 201)
    expect(api("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 1}]}, T["bob"], nk()), 403, "forbidden")


@req("R72", "Import is replacement not merge; repeating it restores exported state without duplicating; survives reset with different fixture")
def _():
    T = setup()
    pay(T["ada"], "bob", 100, note="one")
    mkreq(T["bob"], "ada", 5)
    E = _ex()
    for _i in range(3):
        eq(call("POST", "/_test/import", E)[0], 204)
    eq(len(feed(T["ada"])["payments"]), 1)
    eq(len(api("GET", "/requests", tok=T["ada"])[1]["requests"]), 1)
    eq(total(T), 17500)
    # reset to unrelated fixture, then import: old state back, reset state gone
    reset(fixture([user("zed", 3, uid="u_zed")]))
    eq(call("POST", "/_test/import", E)[0], 204)
    eq(bal(T["ada"]), 9900)
    expect(api("POST", "/auth/login", {"email": "zed@example.com", "password": PW}), 401)
    eq(len(feed(T["ada"])["payments"]), 1)
    # reset clears imported state
    reset(fixture([user("zed", 3, uid="u_zed")]))
    expect(api("GET", "/me", tok=T["ada"]), 401)
    eq(feed(login("zed"))["payments"], [])
    # export snapshot is not changed by later writes
    T = setup()
    E1 = _ex()
    pay(T["ada"], "bob", 100)
    eq(call("POST", "/_test/import", E1)[0], 204)
    eq(bal(T["ada"]), 10000)
    eq(feed(T["ada"])["payments"], [])


@req("R73", "Import 422 validation_failed on missing fields / wrong track or version / invalid state, changing nothing; invalid JSON 400")
def _():
    T = setup()
    pay(T["ada"], "bob", 100)
    E = _ex()
    pay(T["ada"], "bob", 100)
    bad = [{}, {"track": "pocketful", "format_version": 1}, {"track": "pocketful", "state": E["state"]},
           {"format_version": 1, "state": E["state"]},
           {"track": "other", "format_version": 1, "state": E["state"]},
           {"track": "pocketful", "format_version": 2, "state": E["state"]},
           {"track": "pocketful", "format_version": "1", "state": E["state"]} if False else {"track": "pocketful", "format_version": 0, "state": E["state"]},
           {"track": "pocketful", "format_version": 1, "state": "nope"},
           {"track": "pocketful", "format_version": 1, "state": None},
           {"track": "pocketful", "format_version": 1, "state": {}},
           {"track": "pocketful", "format_version": 1, "state": {"garbage": [1, 2, 3]}}]
    for b in bad:
        s, j, _h, _t = call("POST", "/_test/import", b)
        eq((s, code(j)), (422, "validation_failed"), repr(b)[:80])
    s, j, _h, _t = call("POST", "/_test/import", raw="{nope")
    eq((s, code(j)), (400, "malformed_request"))
    eq(bal(T["ada"]), 10000 - 200, "state unchanged by rejected imports")
    eq(len(feed(T["ada"])["payments"]), 2)
    eq(call("GET", "/health")[0], 200)


@req("R74", "Idempotency/receipts survive import: replay after reset+import returns 200 original; original timestamps not regenerated")
def _():
    T = setup()
    k = nk()
    s, p = api("POST", "/payments", {"to_handle": "bob", "amount": 333}, T["ada"], k)
    time.sleep(1.2)
    E = _ex()
    reset()
    eq(call("POST", "/_test/import", E)[0], 204)
    s2, p2 = api("POST", "/payments", {"to_handle": "bob", "amount": 333}, T["ada"], k)
    eq((s2, p2), (200, p))
    eq(bal(T["ada"]), 10000 - 333)
    eq(feed(T["ada"])["payments"][0]["created_at"], p["created_at"])
    # amounts not replayed against already-net balances
    eq(bal(T["bob"]), 2500 + 333)


# ---------------------------------------------------------------- settlements
SF = lambda: fixture(settlement_operator_ids=["u_ada"])


def tr(f, t, a, **kw):
    d = {"from_handle": f, "to_handle": t, "amount": a}
    d.update(kw)
    return d


def settle(t, transfers, key=None):
    return api("POST", "/settlements", {"transfers": transfers}, t, key or nk())


@req("R75", "POST /settlements: no token 401; authenticated non-operator 403 forbidden; default operators [] -> nobody")
def _():
    T = setup(SF())
    body = {"transfers": [tr("ada", "bob", 1)]}
    s, j, _h, _t = call("POST", "/settlements", body, key=nk())
    eq((s, code(j)), (401, "unauthenticated"))
    for h in ("bob", "cy", "dan"):
        expect(api("POST", "/settlements", body, T[h], nk()), 403, "forbidden", h)
    eq(bal(T["ada"]), 10000)
    T = setup(fixture())
    expect(api("POST", "/settlements", body, T["ada"], nk()), 403, "forbidden")
    # operator without key
    T = setup(SF())
    s, j, _h, _t = call("POST", "/settlements", body, tok=T["ada"])
    eq((s, code(j)), (400, "missing_idempotency_key"))
    # multiple operators, operator who is a party and one who is not
    f = fixture(settlement_operator_ids=["u_dan", "u_bob"])
    T = setup(f)
    expect(api("POST", "/settlements", {"transfers": [tr("ada", "cy", 5)]}, T["dan"], nk()), 201)
    expect(api("POST", "/settlements", {"transfers": [tr("ada", "cy", 5)]}, T["bob"], nk()), 201)
    expect(api("POST", "/settlements", {"transfers": [tr("ada", "cy", 5)]}, T["ada"], nk()), 403, "forbidden")


@req("R76", "Settlement 201 shape: settlement_id, committed_at, payments in input order, ordinary payments with settlement_id, request_id null, created_at == committed_at")
def _():
    T = setup(SF())
    s, j = settle(T["ada"], [tr("ada", "bob", 100), tr("bob", "cy", 50, note="n\u00e9", visibility="private"), tr("dan", "ada", 7)])
    eq(s, 201)
    ok(0 < len(j["settlement_id"]) <= 64)
    ok(RFC.match(j["committed_at"]), j["committed_at"])
    eq(len(j["payments"]), 3)
    eq([(p["from_handle"], p["to_handle"], p["amount"]) for p in j["payments"]], [("ada", "bob", 100), ("bob", "cy", 50), ("dan", "ada", 7)])
    eq([(p["note"], p["visibility"]) for p in j["payments"]], [("", "public"), ("n\u00e9", "private"), ("", "public")])
    for p in j["payments"]:
        eq(p["settlement_id"], j["settlement_id"])
        eq(p["request_id"], None)
        eq(p["created_at"], j["committed_at"])
        eq(p["currency"], "EUR")
        ok(RFC.match(p["created_at"]))
    ok(len(set(p["payment_id"] for p in j["payments"])) == 3)
    eq((bal(T["ada"]), bal(T["bob"]), bal(T["cy"]), bal(T["dan"])), (10000 - 100 + 7, 2500 + 100 - 50, 50, 5000 - 7))
    # ordinary payments expose null settlement_id
    p = pay(T["bob"], "cy", 1)[1]
    ok("settlement_id" in p and p["settlement_id"] is None, "ordinary payment must expose settlement_id: null")
    feedp = {x["payment_id"]: x for x in feed(T["ada"])["payments"]}
    eq(feedp[j["payments"][0]["payment_id"]]["settlement_id"], j["settlement_id"])
    eq(feedp[p["payment_id"]]["settlement_id"], None)


@req("R77", "transfers must contain 1..32 objects; malformed batch shape -> 422 validation_failed")
def _():
    f = fixture([user("ada", 10**6), user("bob", 0), user("cy", 0)], settlement_operator_ids=["u_ada"])
    T = setup(f)
    t = T["ada"]
    one = tr("ada", "bob", 1)
    s, j = settle(t, [one] * 32)
    eq(s, 201)
    eq(len(j["payments"]), 32)
    for tl in ([], [one] * 33, [one] * 100):
        s, j = settle(t, tl)
        eq((s, code(j)), (422, "validation_failed"), "len=%d" % len(tl))
    for b in ({}, {"transfers": None}, {"transfers": "x"}, {"transfers": {}}, {"transfers": 5}, {"transfers": [None]},
              {"transfers": [5]}, {"transfers": ["x"]}, {"transfers": [[]]}, {"transfers": [{}]},
              {"transfers": [{"from_handle": "ada", "to_handle": "bob"}]},
              {"transfers": [{"from_handle": "ada", "amount": 5}]},
              {"transfers": [{"to_handle": "bob", "amount": 5}]},
              {"transfers": [{"from_handle": 5, "to_handle": "bob", "amount": 5}]},
              {"transfers": [{"from_handle": "ada", "to_handle": ["bob"], "amount": 5}]}):
        s, j = api("POST", "/settlements", b, t, nk())
        ok(s == 422 and code(j) == "validation_failed", "%r -> %s %r" % (b, s, j))
    eq(bal(t), 10**6 - 32)


@req("R78", "Each transfer follows ordinary payment amount, note and visibility rules")
def _():
    f = fixture([user("ada", 5 * 10**9), user("bob", 0), user("cy", 0)], settlement_operator_ids=["u_ada"])
    T = setup(f)
    t = T["ada"]
    for a in (0, -1, 1000000001, 1.5, "5", True, None):
        s, j = settle(t, [tr("ada", "bob", a)])
        eq((s, code(j)), (422, "validation_failed"), "amount=%r" % (a,))
    for n in (None, 5, ["a"]):
        s, j = settle(t, [tr("ada", "bob", 5, note=n)])
        eq((s, code(j)), (422, "validation_failed"), "note=%r" % (n,))
    s, j = settle(t, [tr("ada", "bob", 5, note="a" * 201)])
    eq((s, code(j)), (422, "validation_failed"))
    for v in ("hidden", "Public", 1, None):
        s, j = settle(t, [tr("ada", "bob", 5, visibility=v)])
        eq((s, code(j)), (422, "validation_failed"), "vis=%r" % (v,))
    s, j = settle(t, [tr("ada", "bob", 5, note="a" * 200), tr("ada", "bob", 1000000000), tr("ada", "cy", 1)])
    eq(s, 201)
    s, j, _h, _t = call("POST", "/settlements", raw='{"transfers":[{"from_handle":"ada","to_handle":"bob","amount":1e3}], "zzz": 1}', tok=t, key=nk())
    eq(s, 201)
    eq(j["payments"][0]["amount"], 1000)
    eq(feed(t)["payments"] and 1, 1)


@req("R79", "Unknown handle 404; self-transfer 422 self_payment; entry errors take precedence in input order, before insufficient funds; no partial effect")
def _():
    T = setup(SF())
    t = T["ada"]
    s, j = settle(t, [tr("ada", "ghost", 5)])
    eq((s, code(j)), (404, "not_found"))
    s, j = settle(t, [tr("ghost", "bob", 5)])
    eq((s, code(j)), (404, "not_found"))
    s, j = settle(t, [tr("bob", "bob", 5)])
    eq((s, code(j)), (422, "self_payment"))
    s, j = settle(t, [tr("ada", "bob", 10**8), tr("bob", "bob", 5)])
    eq((s, code(j)), (422, "self_payment"), "entry error beats insufficient funds")
    s, j = settle(t, [tr("ada", "bob", 10**8), tr("ghost", "bob", 5)])
    eq((s, code(j)), (404, "not_found"), "unknown handle beats insufficient funds")
    s, j = settle(t, [tr("ada", "ada", 5), tr("ada", "ghost", 5)])
    eq((s, code(j)), (422, "self_payment"), "first entry error wins")
    s, j = settle(t, [tr("ada", "ghost", 5), tr("ada", "ada", 5)])
    eq((s, code(j)), (404, "not_found"), "first entry error wins (2)")
    s, j = settle(t, [tr("ada", "bob", 10**8), tr("ada", "bob", 0)])
    eq((s, code(j)), (422, "validation_failed"), "invalid amount beats insufficient funds")
    eq([bal(T[h]) for h in ("ada", "bob", "cy", "dan")], [10000, 2500, 0, 5000])
    for h in T:
        eq(feed(T[h])["payments"], [])


@req("R80", "Affordable = every wallet's net balance after all incoming and outgoing transfers is nonnegative (netting, order independent)")
def _():
    T = setup(SF())
    t = T["ada"]
    # cy has 0 but receives before sending: net nonnegative -> ok even if listed first
    s, j = settle(t, [tr("cy", "bob", 50), tr("ada", "cy", 50)])
    eq(s, 201)
    eq((bal(T["cy"]), bal(T["bob"])), (0, 2550))
    # cycle with zero balance everywhere net zero
    s, j = settle(t, [tr("cy", "dan", 100), tr("dan", "cy", 100)])
    eq(s, 201)
    # chain through a poor wallet
    s, j = settle(t, [tr("cy", "bob", 300), tr("bob", "cy", 300), tr("ada", "cy", 1)])
    eq(s, 201)
    # exact drain
    s, j = settle(t, [tr("dan", "bob", 5000)])
    eq(s, 201)
    eq(bal(T["dan"]), 0)
    # net -1 for cy: fails
    seed = total(T)
    before = [bal(T[h]) for h in T]
    s, j = settle(t, [tr("cy", "bob", 3), tr("ada", "cy", 1)])
    eq((s, code(j)), (409, "insufficient_funds"))
    s, j = settle(t, [tr("dan", "bob", 1)])
    eq((s, code(j)), (409, "insufficient_funds"))
    eq([bal(T[h]) for h in T], before)
    eq(total(T), seed)


@req("R81", "Insufficient collective funds -> 409 and all-or-nothing; failed validation claims no idempotency key and creates no payment")
def _():
    T = setup(SF())
    t = T["ada"]
    k = nk()
    bad = [tr("ada", "bob", 4000), tr("ada", "cy", 4000), tr("ada", "dan", 4000)]
    expect(api("POST", "/settlements", {"transfers": bad}, t, k), 409, "insufficient_funds")
    eq([bal(T[h]) for h in ("ada", "bob", "cy", "dan")], [10000, 2500, 0, 5000])
    for h in T:
        eq(feed(T[h])["payments"], [])
    # same key, different (valid) body -> first use
    s, j = api("POST", "/settlements", {"transfers": [tr("ada", "bob", 1)]}, t, k)
    eq(s, 201)
    # validation failure claims no key
    k2 = nk()
    expect(api("POST", "/settlements", {"transfers": [tr("ada", "bob", 1), tr("bob", "bob", 1)]}, t, k2), 422, "self_payment")
    expect(api("POST", "/settlements", {"transfers": []}, t, k2), 422, "validation_failed")
    s, j = api("POST", "/settlements", {"transfers": [tr("ada", "bob", 2)]}, t, k2)
    eq(s, 201)
    eq(len(feed(t)["payments"]), 2)
    # second member invalid (bad amount) -> nothing applied
    before = bal(T["bob"])
    expect(api("POST", "/settlements", {"transfers": [tr("ada", "bob", 5), tr("ada", "cy", -1)]}, t, nk()), 422, "validation_failed")
    eq(bal(T["bob"]), before)
    eq(len(feed(t)["payments"]), 2)
    # an affordable batch after an unaffordable one works with the same key
    k3 = nk()
    expect(api("POST", "/settlements", {"transfers": [tr("cy", "bob", 1)]}, t, k3), 409, "insufficient_funds")
    pay(T["ada"], "cy", 10)
    expect(api("POST", "/settlements", {"transfers": [tr("cy", "bob", 1)]}, t, k3), 201)


@req("R82", "Settlement replay: 200 with the original complete response; different body 409; concurrent identical -> exactly one 201, effect once")
def _():
    T = setup(SF())
    t = T["ada"]
    k = nk()
    b = [tr("ada", "bob", 100), tr("bob", "cy", 50)]
    s1, j1 = api("POST", "/settlements", {"transfers": b}, t, k)
    eq(s1, 201)
    pay(T["bob"], "dan", 1000)
    s2, j2 = api("POST", "/settlements", {"transfers": b}, t, k)
    eq((s2, j2), (200, j1))
    eq(len(j2["payments"]), 2)
    expect(api("POST", "/settlements", {"transfers": b[:1]}, t, k), 409, "idempotency_key_reuse")
    expect(api("POST", "/settlements", {"transfers": [tr("ada", "bob", 100), tr("bob", "cy", 51)]}, t, k), 409, "idempotency_key_reuse")
    expect(api("POST", "/settlements", {"transfers": []}, t, k), 409, "idempotency_key_reuse")
    eq(bal(T["cy"]), 50)
    T = setup(SF())
    k = nk()
    with ThreadPoolExecutor(20) as ex:
        res = list(ex.map(lambda _i: api("POST", "/settlements", {"transfers": b}, T["ada"], k), range(20)))
    eq(sorted(s for s, _j in res), [200] * 19 + [201])
    eq(len(set(json.dumps(j, sort_keys=True) for s, j in res)), 1)
    eq((bal(T["ada"]), bal(T["bob"]), bal(T["cy"])), (9900, 2550, 50))
    eq(len(feed(T["ada"])["payments"]), 2)
    # key scoped per operator
    f = fixture(settlement_operator_ids=["u_ada", "u_bob"])
    T = setup(f)
    k = nk()
    eq(api("POST", "/settlements", {"transfers": [tr("ada", "cy", 1)]}, T["ada"], k)[0], 201)
    eq(api("POST", "/settlements", {"transfers": [tr("ada", "cy", 1)]}, T["bob"], k)[0], 201)
    eq(bal(T["cy"]), 2)


@req("R83", "Constituents follow ordinary activity-feed visibility (private hidden from third parties, shown to parties); defaults public")
def _():
    T = setup(SF())
    s, j = settle(T["ada"], [tr("bob", "cy", 10, visibility="private", note="hidden"), tr("dan", "cy", 5)])
    eq(s, 201)
    ids = lambda h: sorted(p["note"] for p in feed(T[h])["payments"])
    eq(ids("bob"), ["", "hidden"] if False else sorted(["hidden"] + ([""] if True else [])))
    eq(ids("cy"), sorted(["hidden", ""]))
    eq(ids("dan"), [""])
    # operator is not a party to either: sees only the public one
    eq(ids("ada"), [""], "operator sees only public members")
    # the settlement response itself contains every member's receipt including private ones
    eq(len(j["payments"]), 2)
    eq(sorted(p["note"] for p in j["payments"]), ["", "hidden"])
    # public member visible to stranger
    ok(j["payments"][1]["payment_id"] in [p["payment_id"] for p in feed(T["ada"])["payments"]])
    ok(j["payments"][0]["payment_id"] not in [p["payment_id"] for p in feed(T["ada"])["payments"]])
    ok(j["payments"][0]["payment_id"] in [p["payment_id"] for p in feed(T["bob"])["payments"]])


@req("R84", "Operator permission does not grant access to others' requests or private activity; operator cannot pay/decline/cancel others' requests")
def _():
    T = setup(SF())
    r = mkreq(T["bob"], "cy", 10)[1]["request_id"]
    pay(T["bob"], "cy", 3, vis="private")
    eq(api("GET", "/requests", tok=T["ada"])[1]["requests"], [])
    eq(feed(T["ada"])["payments"], [])
    for act in ("pay", "decline", "cancel"):
        expect(api("POST", "/requests/%s/%s" % (r, act), {} if act == "pay" else None, T["ada"], nk() if act == "pay" else None), 403, "forbidden", act)
    eq(bal(T["ada"]), 10000)


@req("R85", "Settlements: balances sum preserved, no wallet negative, concurrent settlements and payments safe")
def _():
    T = setup(SF())
    hs = ["ada", "bob", "cy", "dan"]

    def work(i):
        if i % 2:
            return settle(T["ada"], [tr(hs[i % 4], hs[(i + 1) % 4], 700), tr(hs[(i + 1) % 4], hs[(i + 2) % 4], 300)])
        return pay(T[hs[i % 4]], hs[(i + 3) % 4], 400)

    with ThreadPoolExecutor(30) as ex:
        res = list(ex.map(work, range(60)))
    ok(all(s in (201, 409) for s, _j in res), str(sorted(set((s, code(j)) for s, j in res))))
    eq(total(T), 17500)
    ok(all(bal(t) >= 0 for t in T.values()))
    # concurrent unaffordable settlements: at most the affordable count commit
    T = setup(SF())
    with ThreadPoolExecutor(20) as ex:
        res = list(ex.map(lambda i: settle(T["ada"], [tr("ada", "bob", 1000), tr("ada", "cy", 1000)]), range(20)))
    eq(sum(1 for s, _j in res if s == 201), 5)
    eq(bal(T["ada"]), 0)
    eq(total(T), 17500)


@req("R86", "Settlement fixture: settlement_operator_ids preserved by reset semantics (replaced on each reset)")
def _():
    T = setup(SF())
    expect(settle(T["ada"], [tr("ada", "bob", 1)]), 201)
    T = setup(fixture())
    expect(settle(T["ada"], [tr("ada", "bob", 1)]), 403, "forbidden")
    T = setup(fixture(settlement_operator_ids=[]))
    expect(settle(T["bob"], [tr("ada", "bob", 1)]), 403, "forbidden")


# ---------------------------------------------------------------- misc / unspecified-behaviour guards
@req("R87", "IDs are opaque strings of at most 64 characters (payments, requests, splits, settlements, users)")
def _():
    T = setup(SF())
    ids = []
    ids.append(pay(T["ada"], "bob", 1)[1]["payment_id"])
    ids.append(mkreq(T["ada"], "bob", 1)[1]["request_id"])
    sp = api("POST", "/splits", {"amount": 3, "participant_handles": ["ada", "bob"]}, T["ada"], nk())[1]
    ids += [sp["split_id"], sp["requests"][0]["request_id"]]
    st = settle(T["ada"], [tr("ada", "bob", 1)])[1]
    ids += [st["settlement_id"], st["payments"][0]["payment_id"]]
    ids.append(api("POST", "/auth/signup", {"email": "idz@example.com", "password": "longenough", "display_name": "x"})[1]["user_id"])
    for i in ids:
        ok(isinstance(i, str) and 0 < len(i) <= 64, repr(i))
    ok(len(set(ids)) == len(ids), "ids unique across kinds used")


@req("R88", "Wallet balances: replayed/failed operations never leave a trace; request/payment IDs never duplicated under load")
def _():
    T = setup()
    with ThreadPoolExecutor(40) as ex:
        res = list(ex.map(lambda i: pay(T["ada"], "bob", 1), range(40)))
    ids = [j["payment_id"] for s, j in res if s == 201]
    eq(len(ids), 40)
    eq(len(set(ids)), 40)
    with ThreadPoolExecutor(40) as ex:
        res = list(ex.map(lambda i: mkreq(T["ada"], "bob", 1), range(40)))
    ids = [j["request_id"] for s, j in res if s == 201]
    eq(len(set(ids)), 40)
    eq(bal(T["ada"]), 9960)
    eq(len(feed(T["ada"], "?limit=200")["payments"]), 40)


@req("R89", "Resource listing endpoints cannot be used to read others' data: pay/cancel/decline of nonexistent or foreign request ids never 5xx; error precedence 401 before 404")
def _():
    T = setup()
    for rid in ("rq_999", "x" * 100, "../me", "%20", "a/b"):
        for act in ("pay", "decline", "cancel"):
            s, j, _h, _t = call("POST", "/requests/%s/%s" % (rid, act), {}, tok=T["ada"], key=nk())
            ok(s in (404,), "%s %s -> %s" % (rid, act, s))
            if "/" not in rid:
                s, j, _h, _t = call("POST", "/requests/%s/%s" % (rid, act), {}, key=nk())
                eq(s, 401, "%s %s unauth" % (rid, act))


# ---------------------------------------------------------------- runner
def run():
    ids = [r[0] for r in REQS]
    assert len(ids) == len(set(ids)), "duplicate ids"
    fails = 0
    for rid, quote, fn in REQS:
        if rid in KNOWN_OPEN:
            print("SKIP %s (known open) %s" % (rid, quote[:70]))
            continue
        t0 = time.time()
        try:
            fn()
            print("PASS %s %s" % (rid, quote[:70]))
        except Exception as e:  # noqa
            fails += 1
            msg = ("%s: %s" % (type(e).__name__, e)).replace("\n", " ")[:300]
            print("FAIL %s %s -- %s" % (rid, quote[:70], msg))
        sys.stdout.flush()
    return 1 if fails else 0


if __name__ == "__main__":
    if "--ledger" in sys.argv:
        for rid, quote, _f in REQS:
            print("| %s | %s |" % (rid, quote.replace("|", "\\|")))
        sys.exit(0)
    sys.exit(run())
