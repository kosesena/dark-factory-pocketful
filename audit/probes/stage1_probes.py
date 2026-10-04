"""spec-auditor stage 1 probes: one probe per gap in ledger/stage-1.md.

Usage: python3 stage1_probes.py http://127.0.0.1:PORT   (stdlib only)
Exit status 1 when any probe fails. Each probe names the ledger requirement it exercises.
"""
import http.client
import json
import re
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

BASE = urlsplit(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080")
RFC3339 = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)$")


def call(method, path, body=None, token=None, key=None, raw=None, headers=None):
    c = http.client.HTTPConnection(BASE.hostname, BASE.port, timeout=15)
    h = dict(headers or {})
    if token:
        h["Authorization"] = "Bearer " + token
    if key is not None:
        h["Idempotency-Key"] = key
    data = raw if raw is not None else (None if body is None else json.dumps(body))
    if data is not None:
        h.setdefault("Content-Type", "application/json")
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    txt = r.read()
    ctype = r.getheader("Content-Type") or ""
    c.close()
    try:
        js = json.loads(txt) if txt else None
    except ValueError:
        js = {"_raw": txt[:200]}
    return r.status, js, ctype


def k():
    return uuid.uuid4().hex


def user(handle, bal, uid=None):
    return {"id": uid or "u_" + handle, "email": handle + "@example.com",
            "password": "correct horse", "display_name": handle.title(),
            "handle": handle, "balance": bal}


def fx(users=None, ops=None, **kw):
    f = {"currency": "EUR", "minor_units": 2,
         "users": users or [user("ada", 10000), user("bob", 2500), user("cy", 0)],
         "payments": [], "requests": []}
    if ops is not None:
        f["settlement_operator_ids"] = ops
    f.update(kw)
    return f


def reset(f):
    s, b, _ = call("POST", "/_test/reset", f)
    assert s == 204, ("reset", s, b)


def tok(handle, pw="correct horse"):
    s, b, _ = call("POST", "/auth/login", {"email": handle + "@example.com", "password": pw})
    assert s == 200, ("login", handle, s, b)
    return b["token"]


def bal(t):
    return call("GET", "/me", token=t)[1]["balance"]


def err(resp, status, code, what=""):
    s, b, _ = resp
    assert s == status and isinstance(b, dict) and b.get("error", {}).get("code") == code, \
        (what, "want", status, code, "got", s, b)


def ok(resp, status, what=""):
    assert resp[0] == status, (what, "want", status, "got", resp[0], resp[1])
    return resp[1]


def world(ops=None):
    reset(fx(ops=ops))
    return tok("ada"), tok("bob"), tok("cy")


def par(fn, n, workers=50):
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(fn, range(n)))


PROBES = []


def probe(rid):
    def deco(fn):
        PROBES.append((rid, fn))
        return fn
    return deco


# ---- 1. concurrent identical idempotent requests ---------------------------

@probe("R60 concurrent same key /payments")
def _():
    ada, bob, _ = world()
    key = k()
    out = par(lambda i: call("POST", "/payments", {"to_handle": "bob", "amount": 100},
                             token=ada, key=key), 30)
    st = sorted(o[0] for o in out)
    assert st.count(201) == 1 and st.count(200) == 29, st
    assert len({json.dumps(o[1], sort_keys=True) for o in out}) == 1
    assert bal(ada) == 9900


@probe("R60 concurrent same key /requests/{id}/pay, /splits, /settlements")
def _():
    ada, bob, _ = world(ops=["u_ada"])
    rid = ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 300}, token=bob, key=k()), 201)["request_id"]
    key = k()
    out = par(lambda i: call("POST", f"/requests/{rid}/pay", {}, token=ada, key=key), 20)
    assert sorted(o[0] for o in out).count(201) == 1 and all(o[0] in (200, 201) for o in out), [o[0] for o in out]
    key = k()
    out = par(lambda i: call("POST", "/splits", {"amount": 90, "participant_handles": ["ada", "bob", "cy"]},
                             token=ada, key=key), 20)
    assert [o[0] for o in out].count(201) == 1 and all(o[0] in (200, 201) for o in out)
    out_reqs = call("GET", "/requests?direction=outgoing&limit=200", token=ada)[1]["requests"]
    assert len(out_reqs) == 2, len(out_reqs)
    key = k()
    out = par(lambda i: call("POST", "/settlements", {"transfers": [
        {"from_handle": "bob", "to_handle": "cy", "amount": 10}]}, token=ada, key=key), 20)
    assert [o[0] for o in out].count(201) == 1 and all(o[0] in (200, 201) for o in out)
    assert bal(tok("cy")) == 10


# ---- 2. money races ----------------------------------------------------------

@probe("R2 drain in parts under 50 in flight")
def _():
    reset(fx(users=[user("ada", 1000), user("bob", 0)]))
    toks = [tok("ada") for _ in range(10)]
    out = par(lambda i: call("POST", "/payments", {"to_handle": "bob", "amount": 30},
                             token=toks[i % 10], key=k()), 50)
    st = [o[0] for o in out]
    assert st.count(201) == 33 and st.count(409) == 17, sorted(st)
    assert bal(toks[0]) == 10


@probe("R1/R2 ring of three wallets conserves total")
def _():
    reset(fx(users=[user("ada", 100), user("bob", 100), user("cy", 100)]))
    t = {h: tok(h) for h in ("ada", "bob", "cy")}
    nxt = {"ada": "bob", "bob": "cy", "cy": "ada"}
    hs = list(t)
    out = par(lambda i: call("POST", "/payments", {"to_handle": nxt[hs[i % 3]], "amount": 7},
                             token=t[hs[i % 3]], key=k()), 150)
    assert all(o[0] in (201, 409) for o in out), {o[0] for o in out}
    bs = [bal(t[h]) for h in hs]
    assert sum(bs) == 300 and min(bs) >= 0, bs


@probe("R3 same request paid concurrently with different keys")
def _():
    ada, bob, _ = world()
    rid = ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 100}, token=bob, key=k()), 201)["request_id"]
    out = par(lambda i: call("POST", f"/requests/{rid}/pay", {}, token=ada, key=k()), 20)
    st = [o[0] for o in out]
    assert st.count(201) == 1 and st.count(409) == 19, st
    assert all(o[1]["error"]["code"] == "request_not_pending" for o in out if o[0] == 409)
    assert bal(ada) == 9900


@probe("R3 pay races cancel")
def _():
    ada, bob, _ = world()
    rids = [ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 10}, token=bob, key=k()), 201)["request_id"]
            for _ in range(10)]

    def go(i):
        rid = rids[i // 2]
        if i % 2:
            return call("POST", f"/requests/{rid}/cancel", token=bob)
        return call("POST", f"/requests/{rid}/pay", {}, token=ada, key=k())
    out = par(go, 20)
    paid = sum(1 for i, o in enumerate(out) if i % 2 == 0 and o[0] == 201)
    canc = sum(1 for i, o in enumerate(out) if i % 2 == 1 and o[0] == 200)
    assert paid + canc == 10, (paid, canc, [o[0] for o in out])
    assert bal(ada) == 10000 - 10 * paid


# ---- 3. claimed key before validation ----------------------------------------

@probe("R62 used key + invalid body -> 409 reuse (payments, pay, requests, splits)")
def _():
    ada, bob, _ = world()
    key = k()
    ok(call("POST", "/payments", {"to_handle": "bob", "amount": 10}, token=ada, key=key), 201)
    err(call("POST", "/payments", {"to_handle": "bob", "amount": -5}, token=ada, key=key), 409, "idempotency_key_reuse")
    err(call("POST", "/payments", {"to_handle": "nobody", "amount": 10}, token=ada, key=key), 409, "idempotency_key_reuse")
    key = k()
    ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 10}, token=bob, key=key), 201)
    err(call("POST", "/requests", {"payer_handle": "bob", "amount": 10}, token=bob, key=key), 409, "idempotency_key_reuse")
    key = k()
    ok(call("POST", "/splits", {"amount": 10, "participant_handles": ["bob"]}, token=ada, key=key), 201)
    err(call("POST", "/splits", {"amount": 10, "participant_handles": []}, token=ada, key=key), 409, "idempotency_key_reuse")
    rid = ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 10}, token=bob, key=k()), 201)["request_id"]
    key = k()
    ok(call("POST", f"/requests/{rid}/pay", {}, token=ada, key=key), 201)
    err(call("POST", f"/requests/{rid}/pay", {"visibility": "nope"}, token=ada, key=key), 409, "idempotency_key_reuse")


@probe("R63 malformed body / no token on a claimed key")
def _():
    ada, _, _ = world()
    key = k()
    ok(call("POST", "/payments", {"to_handle": "bob", "amount": 10}, token=ada, key=key), 201)
    err(call("POST", "/payments", raw="{nope", token=ada, key=key), 400, "malformed_request")
    err(call("POST", "/payments", {"to_handle": "bob", "amount": 10}, key=key), 401, "unauthenticated")


# ---- 4-6. settlements ----------------------------------------------------------

@probe("R118 net affordability independent of entry order")
def _():
    ada, bob, cy = world(ops=["u_ada"])
    reset(fx(users=[user("ada", 1000), user("bob", 0), user("cy", 0)], ops=["u_ada"]))
    ada = tok("ada")
    b = ok(call("POST", "/settlements", {"transfers": [
        {"from_handle": "bob", "to_handle": "cy", "amount": 100},
        {"from_handle": "ada", "to_handle": "bob", "amount": 100}]}, token=ada, key=k()), 201)
    assert [p["from_handle"] for p in b["payments"]] == ["bob", "ada"]
    assert bal(tok("bob")) == 0 and bal(tok("cy")) == 100 and bal(ada) == 900


@probe("R119 unaffordable settlement is all-or-nothing")
def _():
    reset(fx(users=[user("ada", 1000), user("bob", 0), user("cy", 5)], ops=["u_ada"]))
    ada = tok("ada")
    err(call("POST", "/settlements", {"transfers": [
        {"from_handle": "ada", "to_handle": "bob", "amount": 100},
        {"from_handle": "cy", "to_handle": "ada", "amount": 6}]}, token=ada, key=k()), 409, "insufficient_funds")
    assert bal(ada) == 1000 and bal(tok("bob")) == 0 and bal(tok("cy")) == 5
    assert call("GET", "/activity", token=ada)[1]["payments"] == []


@probe("R122/R123/R65 settlement_id, request_id, created_at == committed_at")
def _():
    ada, bob, cy = world(ops=["u_ada"])
    p = ok(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=ada, key=k()), 201)
    assert "settlement_id" in p and p["settlement_id"] is None, p
    b = ok(call("POST", "/settlements", {"transfers": [
        {"from_handle": "ada", "to_handle": "bob", "amount": 10},
        {"from_handle": "bob", "to_handle": "cy", "amount": 5, "note": "n", "visibility": "private"},
        {"from_handle": "ada", "to_handle": "cy", "amount": 1}]}, token=ada, key=k()), 201)
    assert b["settlement_id"] and RFC3339.match(b["committed_at"]), b
    assert len(b["payments"]) == 3
    for m in b["payments"]:
        assert m["settlement_id"] == b["settlement_id"] and m["request_id"] is None
        assert m["created_at"] == b["committed_at"]
    assert b["payments"][0]["note"] == "" and b["payments"][0]["visibility"] == "public"
    assert b["payments"][1]["visibility"] == "private"
    feed = call("GET", "/activity", token=cy)[1]["payments"]
    assert all("settlement_id" in x for x in feed)


@probe("R112/R113 settlement auth: 401, 403, missing key 400")
def _():
    ada, bob, _ = world(ops=["u_ada"])
    body = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}
    err(call("POST", "/settlements", body, key=k()), 401, "unauthenticated")
    err(call("POST", "/settlements", body, token=bob, key=k()), 403, "forbidden")
    err(call("POST", "/settlements", body, token=ada), 400, "missing_idempotency_key")


@probe("R114-R117/R120 settlement validation and precedence")
def _():
    ada, _, _ = world(ops=["u_ada"])
    T = lambda f, t, a, **x: dict(from_handle=f, to_handle=t, amount=a, **x)
    err(call("POST", "/settlements", {"transfers": []}, token=ada, key=k()), 422, "validation_failed")
    err(call("POST", "/settlements", {"transfers": [T("ada", "bob", 1)] * 33}, token=ada, key=k()), 422, "validation_failed")
    ok(call("POST", "/settlements", {"transfers": [T("ada", "bob", 1)] * 32}, token=ada, key=k()), 201)
    err(call("POST", "/settlements", {}, token=ada, key=k()), 422, "validation_failed")
    err(call("POST", "/settlements", {"transfers": [T("ada", "nobody", 1), T("bob", "bob", 1)]}, token=ada, key=k()), 404, "not_found")
    err(call("POST", "/settlements", {"transfers": [T("bob", "bob", 1), T("ada", "nobody", 1)]}, token=ada, key=k()), 422, "self_payment")
    err(call("POST", "/settlements", {"transfers": [T("cy", "ada", 999999), T("bob", "bob", 1)]}, token=ada, key=k()), 422, "self_payment")
    err(call("POST", "/settlements", {"transfers": [T("ada", "bob", 0)]}, token=ada, key=k()), 422, "validation_failed")
    err(call("POST", "/settlements", {"transfers": [T("ada", "bob", True)]}, token=ada, key=k()), 422, "validation_failed")
    err(call("POST", "/settlements", {"transfers": [T("ada", "bob", 1, note="x" * 201)]}, token=ada, key=k()), 422, "validation_failed")
    err(call("POST", "/settlements", {"transfers": [T("ada", "bob", 1, visibility="Public")]}, token=ada, key=k()), 422, "validation_failed")
    key = k()
    err(call("POST", "/settlements", {"transfers": [T("ada", "bob", 0)]}, token=ada, key=key), 422, "validation_failed")
    ok(call("POST", "/settlements", {"transfers": [T("ada", "bob", 1)]}, token=ada, key=key), 201)
    assert len(call("GET", "/activity?limit=200", token=ada)[1]["payments"]) == 33


@probe("R125 settlement replay 200 identical; R124 operator sees no private member")
def _():
    reset(fx(ops=["u_cy"]))
    cy = tok("cy")
    body = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10, "visibility": "private"}]}
    key = k()
    a = ok(call("POST", "/settlements", body, token=cy, key=key), 201)
    b = ok(call("POST", "/settlements", body, token=cy, key=key), 200)
    assert a == b
    assert bal(tok("ada")) == 9990
    assert call("GET", "/activity", token=cy)[1]["payments"] == []
    ok(call("POST", "/requests", {"payer_handle": "bob", "amount": 1}, token=tok("ada"), key=k()), 201)
    assert call("GET", "/requests", token=cy)[1]["requests"] == []


# ---- 7. 401 everywhere --------------------------------------------------------

@probe("R40/R51 401 on every authenticated endpoint")
def _():
    world()
    eps = [("GET", "/me"), ("GET", "/activity"), ("GET", "/requests"), ("POST", "/payments"),
           ("POST", "/requests"), ("POST", "/requests/rq_x/pay"), ("POST", "/requests/rq_x/decline"),
           ("POST", "/requests/rq_x/cancel"), ("POST", "/splits"), ("POST", "/settlements")]
    for hdr in ({}, {"Authorization": "Bearer garbage"}, {"Authorization": "Basic abc"},
                {"Authorization": "Bearer"}):
        for m, p in eps:
            err(call(m, p, {} if m == "POST" else None, key=k(), headers=hdr), 401, "unauthenticated", (m, p, hdr))
    ada = tok("ada")  # a valid token under a non-Bearer scheme is still a malformed bearer header
    for hdr in ({"Authorization": "Basic " + ada}, {"Authorization": "Token " + ada}, {"Authorization": ada}):
        err(call("GET", "/me", headers=hdr), 401, "unauthenticated", hdr["Authorization"][:6])


# ---- 8. export / import -----------------------------------------------------------

@probe("R97-R109 export/import preserves tokens, replays, failed keys; replaces; invalid 422")
def _():
    ada, bob, cy = world(ops=["u_ada"])
    pk = k()
    first = ok(call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=ada, key=pk), 201)
    fk = k()
    err(call("POST", "/payments", {"to_handle": "bob", "amount": 10 ** 9}, token=ada, key=fk), 409, "insufficient_funds")
    rid = ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 50}, token=bob, key=k()), 201)["request_id"]
    sk = k()
    sbody = {"transfers": [{"from_handle": "bob", "to_handle": "cy", "amount": 5}]}
    sres = ok(call("POST", "/settlements", sbody, token=ada, key=sk), 201)
    s, ex, _ = call("GET", "/_test/export")
    assert s == 200 and ex["track"] == "pocketful" and ex["format_version"] == 1 and isinstance(ex["state"], dict)
    assert "correct horse" not in json.dumps(ex), "R53 plaintext password in export"
    # writes after export must not alter the snapshot or survive import
    ok(call("POST", "/payments", {"to_handle": "cy", "amount": 7}, token=ada, key=k()), 201)
    ns = ok(call("POST", "/auth/signup", {"email": "zed@example.com", "password": "correct horse", "display_name": "Z"}), 201)
    s2, ex2, _ = call("GET", "/_test/export")
    reset(fx())
    s, _, _ = call("POST", "/_test/import", ex)
    assert s == 204, s
    s, _, _ = call("POST", "/_test/import", ex)  # repeat: no duplication
    assert s == 204
    assert bal(ada) == 9900 - 0 and bal(bob) == 2500 + 100 - 5 and bal(cy) == 5, (bal(ada), bal(bob), bal(cy))
    err(call("GET", "/me", token=ns["token"]), 401, "unauthenticated", "post-export signup token")
    err(call("POST", "/auth/login", {"email": "zed@example.com", "password": "correct horse"}), 401, "unauthenticated")
    again = ok(call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=ada, key=pk), 200)
    assert again == first
    err(call("POST", "/payments", {"to_handle": "bob", "amount": 101}, token=ada, key=pk), 409, "idempotency_key_reuse")
    ok(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=ada, key=fk), 201)
    assert ok(call("POST", "/settlements", sbody, token=ada, key=sk), 200) == sres
    feed = call("GET", "/activity?limit=200", token=ada)[1]["payments"]
    ids = [p["payment_id"] for p in feed]
    assert len(ids) == len(set(ids)) == 3, ids
    assert first in feed
    reqs = call("GET", "/requests", token=bob)[1]["requests"]
    assert [r["request_id"] for r in reqs] == [rid]
    ok(call("POST", f"/requests/{rid}/pay", {}, token=ada, key=k()), 201)
    assert ex2["state"] != ex["state"]
    # invalid imports change nothing
    before = bal(ada)
    for bad in ({"track": "tablekeeper", "format_version": 1, "state": ex["state"]},
                {"track": "pocketful", "format_version": 2, "state": ex["state"]},
                {"track": "pocketful", "format_version": 1},
                {"track": "pocketful", "format_version": 1, "state": 5},
                {"track": "pocketful", "format_version": 1, "state": {}}):
        err(call("POST", "/_test/import", bad), 422, "validation_failed", bad.get("track"))
    err(call("POST", "/_test/import", raw="{nope"), 400, "malformed_request")
    assert bal(ada) == before
    reset(fx())
    err(call("GET", "/me", token=ada), 401, "unauthenticated", "reset must clear imported tokens")


# ---- 9-10. path and body equality ----------------------------------------------------

@probe("R55 same key+body on another request's pay path is a first use")
def _():
    ada, bob, _ = world()
    r1 = ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 10}, token=bob, key=k()), 201)["request_id"]
    r2 = ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 20}, token=bob, key=k()), 201)["request_id"]
    key = k()
    a = ok(call("POST", f"/requests/{r1}/pay", {}, token=ada, key=key), 201)
    b = ok(call("POST", f"/requests/{r2}/pay", {}, token=ada, key=key), 201)
    assert a["request_id"] == r1 and b["request_id"] == r2
    assert bal(ada) == 9970


@probe("R59 key order and whitespace do not matter")
def _():
    ada, _, _ = world()
    key = k()
    ok(call("POST", "/payments", raw='{"to_handle":"bob","amount":10}', token=ada, key=key), 201)
    ok(call("POST", "/payments", raw='{ "amount" : 10 ,\n "to_handle" : "bob" }', token=ada, key=key), 200)
    assert bal(ada) == 9990


# ---- 11-12. numbers and types ------------------------------------------------------------

@probe("R16/R17 1000.0 and 1e3 valid; booleans 422 on every amount")
def _():
    ada, bob, _ = world()
    for raw in ('{"to_handle":"bob","amount":1000.0}', '{"to_handle":"bob","amount":1e3}'):
        b = ok(call("POST", "/payments", raw=raw, token=ada, key=k()), 201)
        assert b["amount"] == 1000 and isinstance(b["amount"], int), b
    b = ok(call("POST", "/requests", raw='{"payer_handle":"ada","amount":1e3}', token=bob, key=k()), 201)
    assert b["amount"] == 1000
    b = ok(call("POST", "/splits", raw='{"participant_handles":["bob"],"amount":1.0e3}', token=ada, key=k()), 201)
    assert b["amount"] == 1000
    for path, body, t in (("/payments", {"to_handle": "bob"}, ada), ("/requests", {"payer_handle": "ada"}, bob),
                          ("/splits", {"participant_handles": ["bob"]}, ada)):
        for v in (True, False, None, [1], {"a": 1}):
            err(call("POST", path, dict(body, amount=v), token=t, key=k()), 422, "validation_failed", (path, v))


@probe("R37 wrong-type non-amount fields -> 400; non-object body -> 400")
def _():
    ada, bob, _ = world()
    cases = [("/payments", {"to_handle": 5, "amount": 1}, ada),
             ("/requests", {"payer_handle": ["ada"], "amount": 1}, bob),
             ("/splits", {"participant_handles": "ada", "amount": 1}, ada),
             ("/splits", {"participant_handles": [1], "amount": 1}, ada)]
    for path, body, t in cases:
        err(call("POST", path, body, token=t, key=k()), 400, "malformed_request", (path, body))
    for raw in ("[]", "null", '"x"', "5"):
        err(call("POST", "/payments", raw=raw, token=ada, key=k()), 400, "malformed_request", raw)
    err(call("POST", "/auth/signup", {"email": 5, "password": "correct horse", "display_name": "x"}), 400, "malformed_request")
    err(call("POST", "/auth/login", {"email": "ada@example.com", "password": 12345678}), 400, "malformed_request")
    err(call("POST", "/payments", {"to_handle": "bob", "amount": 1, "note": None}, token=ada, key=k()), 422, "validation_failed")
    err(call("POST", "/payments", {"to_handle": "bob", "amount": 1, "visibility": 5}, token=ada, key=k()), 422, "validation_failed")


# ---- 13. signup / login ---------------------------------------------------------------

@probe("R47-R50/R52 signup and login table")
def _():
    world()
    err(call("POST", "/auth/signup", {"email": "ada@example.com", "password": "correct horse", "display_name": "A"}), 409, "email_taken")
    err(call("POST", "/auth/signup", {"email": "new@example.com", "password": "1234567", "display_name": "N"}), 422, "validation_failed")
    for e in ("noat", "@x.com", "a@", "a@b@c", ""):
        err(call("POST", "/auth/signup", {"email": e, "password": "correct horse", "display_name": "N"}), 422, "validation_failed", e)
    b = ok(call("POST", "/auth/signup", {"email": "new@example.com", "password": "12345678", "display_name": "N"}), 201)
    assert set(b) >= {"user_id", "display_name", "token"} and b["display_name"] == "N"
    l = ok(call("POST", "/auth/login", {"email": "new@example.com", "password": "12345678"}), 200)
    assert l["user_id"] == b["user_id"]
    ok(call("GET", "/me", token=b["token"]), 200)
    ok(call("GET", "/me", token=l["token"]), 200)
    err(call("POST", "/auth/login", {"email": "new@example.com", "password": "12345679"}), 401, "unauthenticated")
    err(call("POST", "/auth/signup", {"password": "correct horse", "display_name": "N"}), 422, "validation_failed")


# ---- 14. reset clears ----------------------------------------------------------------------

@probe("R8 reset clears tokens, signups and keys")
def _():
    ada, _, _ = world()
    key = k()
    ok(call("POST", "/payments", {"to_handle": "bob", "amount": 10}, token=ada, key=key), 201)
    ok(call("POST", "/auth/signup", {"email": "dee@example.com", "password": "correct horse", "display_name": "D"}), 201)
    reset(fx())
    err(call("GET", "/me", token=ada), 401, "unauthenticated")
    err(call("POST", "/auth/login", {"email": "dee@example.com", "password": "correct horse"}), 401, "unauthenticated")
    ada = tok("ada")
    ok(call("POST", "/payments", {"to_handle": "bob", "amount": 10}, token=ada, key=key), 201)
    assert call("GET", "/activity", token=ada)[1]["payments"].__len__() == 1


# ---- 15. query integers --------------------------------------------------------------------

@probe("R42/R83 query integer forms and default limit 50")
def _():
    ada, bob, _ = world()
    for path in ("/requests", "/activity"):
        for q in ("limit=4.0", "limit=%2B4", "offset=1e1", "limit=", "limit=1e2", "offset=-0", "limit=%204"):
            err(call("GET", f"{path}?{q}", token=ada), 422, "validation_failed", (path, q))
        ok(call("GET", f"{path}?limit=200&offset=0&bogus=1", token=ada), 200)
    for i in range(55):
        ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 1 + i}, token=bob, key=k()), 201)
    b = call("GET", "/requests", token=ada)[1]
    assert len(b["requests"]) == 50 and b["has_more"] is True
    amts = [r["amount"] for r in b["requests"]]
    assert amts == sorted(amts, reverse=True), "R81 newest first"


# ---- 16. splits ---------------------------------------------------------------------------

@probe("R86/R88/R91/R95 splits: caller omitted, payable, replay, nothing on 404, conservation")
def _():
    ada, bob, cy = world()
    b = ok(call("POST", "/splits", {"amount": 1001, "participant_handles": ["bob", "cy"]}, token=ada, key=k()), 201)
    assert b["shares"] == [{"handle": "bob", "amount": 501}, {"handle": "cy", "amount": 500}], b["shares"]
    assert [r["payer_handle"] for r in b["requests"]] == ["bob", "cy"] and b["note"] == ""
    assert b["currency"] == "EUR" and RFC3339.match(b["created_at"])
    assert [r["amount"] for r in b["requests"]] == [501, 500]
    assert call("GET", "/activity", token=ada)[1]["payments"] == [], "R28 split is not a feed item"
    rid = b["requests"][0]["request_id"]
    inc = call("GET", "/requests?direction=incoming", token=bob)[1]["requests"]
    assert [r["request_id"] for r in inc] == [rid]
    ok(call("POST", f"/requests/{rid}/pay", {}, token=bob, key=k()), 201)
    ok(call("POST", "/payments", {"to_handle": "cy", "amount": 500}, token=ada, key=k()), 201)
    ok(call("POST", f"/requests/{b['requests'][1]['request_id']}/pay", {}, token=cy, key=k()), 201)
    assert bal(ada) + bal(bob) + bal(cy) == 12500
    key = k()
    body = {"amount": 1, "participant_handles": ["ada", "bob", "cy"], "note": "z"}
    s1 = ok(call("POST", "/splits", body, token=ada, key=key), 201)
    s2 = ok(call("POST", "/splits", body, token=ada, key=key), 200)
    assert s1 == s2
    zero = s1["requests"][0]
    assert zero["amount"] == 0
    n_before = len(call("GET", "/requests?limit=200", token=ada)[1]["requests"])
    err(call("POST", "/splits", {"amount": 10, "participant_handles": ["bob", "nobody"]}, token=ada, key=k()), 404, "not_found")
    err(call("POST", "/splits", {"amount": 10, "participant_handles": ["bob"], "note": "x" * 201}, token=ada, key=k()), 422, "validation_failed")
    assert len(call("GET", "/requests?limit=200", token=ada)[1]["requests"]) == n_before
    pz = call("POST", f"/requests/{zero['request_id']}/pay", {}, token=bob, key=k())
    assert pz[0] == 201, ("A1 zero-share request should be payable", pz)


# ---- 17. state machine ------------------------------------------------------------------

@probe("R74/R75/R78/R79/R80 request state machine")
def _():
    ada, bob, _ = world()
    new = lambda: ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 10}, token=bob, key=k()), 201)["request_id"]
    r = new(); ok(call("POST", f"/requests/{r}/cancel", token=bob), 200)
    err(call("POST", f"/requests/{r}/pay", {}, token=ada, key=k()), 409, "request_not_pending")
    err(call("POST", f"/requests/{r}/decline", token=ada), 409, "request_not_pending")
    r = new(); ok(call("POST", f"/requests/{r}/pay", {}, token=ada, key=k()), 201)
    err(call("POST", f"/requests/{r}/pay", {}, token=ada, key=k()), 409, "request_not_pending")
    err(call("POST", f"/requests/{r}/decline", token=ada), 409, "request_not_pending")
    r = new(); d = ok(call("POST", f"/requests/{r}/decline", token=ada), 200)
    assert d["status"] == "declined" and d["request_id"] == r
    err(call("POST", f"/requests/{r}/cancel", token=bob), 409, "request_not_pending")
    r = new()
    err(call("POST", f"/requests/{r}/pay", {}, token=bob, key=k()), 403, "forbidden")
    err(call("POST", f"/requests/{r}/decline", token=bob), 403, "forbidden")
    err(call("POST", f"/requests/{r}/pay", {"visibility": "secret"}, token=ada, key=k()), 422, "validation_failed")
    err(call("POST", "/requests/rq_nope/decline", token=ada), 404, "not_found")
    err(call("POST", "/requests/rq_nope/cancel", token=ada), 404, "not_found")


# ---- 18. replay after change -------------------------------------------------------------

@probe("R61 replay returns the original after the resource changed")
def _():
    ada, bob, cy = world()
    key = k()
    body = {"payer_handle": "ada", "amount": 10}
    orig = ok(call("POST", "/requests", body, token=bob, key=key), 201)
    ok(call("POST", f"/requests/{orig['request_id']}/cancel", token=bob), 200)
    again = ok(call("POST", "/requests", body, token=bob, key=key), 200)
    assert again == orig and again["status"] == "pending"
    reset(fx(users=[user("ada", 100), user("bob", 0)]))
    ada = tok("ada")
    key = k()
    p = ok(call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=ada, key=key), 201)
    assert ok(call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=ada, key=key), 200) == p
    assert bal(ada) == 0


# ---- 19-21. listing, formats, key bounds ---------------------------------------------------------

@probe("R82 combined filters")
def _():
    ada, bob, _ = world()
    a = ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 1}, token=bob, key=k()), 201)["request_id"]
    ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 2}, token=bob, key=k()), 201)
    ok(call("POST", "/requests", {"payer_handle": "bob", "amount": 3}, token=ada, key=k()), 201)
    ok(call("POST", f"/requests/{a}/decline", token=ada), 200)
    r = call("GET", "/requests?direction=incoming&status=pending", token=ada)[1]["requests"]
    assert [x["amount"] for x in r] == [2], r
    r = call("GET", "/requests?direction=outgoing&status=declined", token=ada)[1]["requests"]
    assert r == []


@probe("R10/R11/R14 content type, timestamps, id length")
def _():
    ada, bob, _ = world()
    p = call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=ada, key=k())
    assert p[2].startswith("application/json") and "utf-8" in p[2].lower(), p[2]
    e = call("POST", "/payments", {"to_handle": "bob", "amount": 0}, token=ada, key=k())
    assert e[2].startswith("application/json"), e[2]
    assert RFC3339.match(p[1]["created_at"]), p[1]["created_at"]
    r = ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 1}, token=bob, key=k()), 201)
    assert RFC3339.match(r["created_at"])
    for v in (p[1]["payment_id"], p[1]["from_user_id"], r["request_id"]):
        assert isinstance(v, str) and 0 < len(v) <= 64
    s = ok(call("POST", "/auth/signup", {"email": "q@example.com", "password": "correct horse", "display_name": "Q"}), 201)
    assert isinstance(s["user_id"], str) and len(s["user_id"]) <= 64


@probe("R39/R41 key bounds: empty 400, 255 ok, 256 422")
def _():
    ada, _, _ = world()
    err(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=ada, key=""), 400, "missing_idempotency_key")
    ok(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=ada, key="k" * 255), 201)
    err(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=ada, key="k" * 256), 422, "validation_failed")


# ---- 22. feed edges -------------------------------------------------------------------------------

@probe("R26/R67 private request-payment hidden from third party; failed payment absent")
def _():
    ada, bob, cy = world()
    rid = ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 10}, token=bob, key=k()), 201)["request_id"]
    ok(call("POST", f"/requests/{rid}/pay", {"visibility": "private"}, token=ada, key=k()), 201)
    assert call("GET", "/activity", token=cy)[1]["payments"] == []
    assert len(call("GET", "/activity", token=bob)[1]["payments"]) == 1
    err(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=cy, key=k()), 409, "insufficient_funds")
    assert call("GET", "/activity", token=cy)[1]["payments"] == []


# ---- 23-26. misc -------------------------------------------------------------------------------------

@probe("R30 large balances exact")
def _():
    big = 2 ** 53 - 10 ** 9
    reset(fx(users=[user("ada", big), user("bob", 0)]))
    ada, bob = tok("ada"), tok("bob")
    ok(call("POST", "/payments", {"to_handle": "bob", "amount": 10 ** 9}, token=ada, key=k()), 201)
    ok(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=ada, key=k()), 201)
    assert bal(ada) == big - 10 ** 9 - 1 and bal(bob) == 10 ** 9 + 1


@probe("R19/R21 non-ASCII handle derivation; new user can be asked")
def _():
    ada, _, _ = world()
    s = ok(call("POST", "/auth/signup", {"email": "Zoë.Q@example.com", "password": "correct horse", "display_name": "Z"}), 201)
    h = call("GET", "/me", token=s["token"])[1]["handle"]
    assert h == "zo__q", h
    ok(call("POST", "/requests", {"payer_handle": "zo__q", "amount": 5}, token=ada, key=k()), 201)
    assert len(call("GET", "/requests", token=s["token"])[1]["requests"]) == 1


@probe("R12/R43 unknown fields ignored, missing required fields 422")
def _():
    ada, bob, _ = world(ops=["u_ada"])
    ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 1, "x": 1}, token=bob, key=k()), 201)
    ok(call("POST", "/splits", {"participant_handles": ["bob"], "amount": 1, "x": [1]}, token=ada, key=k()), 201)
    ok(call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1, "y": 2}], "x": 1},
            token=ada, key=k()), 201)
    for path, body, t in (("/payments", {"to_handle": "bob"}, ada), ("/requests", {"amount": 1}, bob),
                          ("/requests", {"payer_handle": "ada"}, bob), ("/splits", {"amount": 1}, ada),
                          ("/splits", {"participant_handles": ["bob"]}, ada)):
        err(call("POST", path, body, token=t, key=k()), 422, "validation_failed", (path, body))
    err(call("POST", "/auth/login", {"email": "ada@example.com"}), 422, "validation_failed")


@probe("R34 seeded payment shape")
def _():
    reset(fx(payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500,
                        "note": "coffee", "visibility": "public"}]))
    p = call("GET", "/activity", token=tok("cy"))[1]["payments"]
    assert len(p) == 1 and p[0]["payment_id"] == "p_1" and p[0]["request_id"] is None
    assert p[0]["settlement_id"] is None and p[0]["from_handle"] == "ada" and RFC3339.match(p[0]["created_at"])


# ---- fix-revision probes (145b98e): exact numbers, huge digits, body identity, import -----

@probe("R16/R44 exact and huge numbers never 5xx, never rounded")
def _():
    ada, _, _ = world(ops=["u_ada"])
    for raw in ("1.0000000000000001", "1e-400", "1e400", "1E+999999999", "1e-999999999",
                "1" + "0" * 5000, "-0", "99999999999999999999e-11", "1000000000.5"):
        body = '{"to_handle":"bob","amount":%s}' % raw
        err(call("POST", "/payments", raw=body, token=ada, key=k()), 422, "validation_failed", raw[:20])
        err(call("POST", "/requests", raw='{"payer_handle":"bob","amount":%s}' % raw, token=ada, key=k()),
            422, "validation_failed", raw[:20])
    for raw in ("1000.000", "0.1e4", "1e3", "1000000000.0"):
        ok(call("POST", "/requests", raw='{"payer_handle":"bob","amount":%s}' % raw, token=ada, key=k()), 201, raw)
    s = call("POST", "/payments", raw='{"to_handle":"bob","amount":1,"x":1e1000000}', token=ada, key=k())[0]
    assert s == 201, ("unknown huge-exponent field", s)


@probe("R42 huge digit strings in limit/offset")
def _():
    ada, _, _ = world()
    err(call("GET", "/activity?limit=" + "9" * 5000, token=ada), 422, "validation_failed")
    b = ok(call("GET", "/activity?offset=" + "9" * 5000, token=ada), 200)
    assert b["payments"] == [] and b["has_more"] is False
    assert ok(call("GET", "/requests?limit=000200&offset=00", token=ada), 200)["requests"] == []


@probe("R59 number identity: numeric value, never equal to a string")
def _():
    ada, _, _ = world()
    for a, b, want in (('1.5', '"1.5"', 409), ('1e40', '"1E+40"', 409), ('1.50', '1.5', 200),
                       ('1000', '1000.0', 200), ('1', 'true', 409), ('"true"', 'true', 409),
                       ('"null"', 'null', 409), ('"false"', 'false', 409)):
        key = k()
        ok(call("POST", "/payments", raw='{"to_handle":"bob","amount":1,"x":%s}' % a, token=ada, key=key), 201)
        r = call("POST", "/payments", raw='{"to_handle":"bob","amount":1,"x":%s}' % b, token=ada, key=key)
        assert r[0] == want, (a, b, "want", want, "got", r[0])


@probe("R105 strict import: corrupted export pieces rejected, destination unchanged")
def _():
    ada, bob, _ = world()
    ok(call("POST", "/payments", {"to_handle": "bob", "amount": 10}, token=ada, key=k()), 201)
    ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 1}, token=bob, key=k()), 201)
    ok(call("POST", "/splits", {"amount": 1, "participant_handles": ["ada", "bob", "cy"]}, token=ada, key=k()), 201)
    ex = call("GET", "/_test/export")[1]
    s, _, _ = call("POST", "/_test/import", ex)
    assert s == 204, "zero-share requests must still import"
    st = ex["state"]
    import copy
    bads = []
    for path, val in ((("users", 0, "balance"), -1), (("users", 0, "balance"), 1.5), (("payments", 0, "amount"), "10"),
                      (("payments", 0, "created_at"), "yesterday"), (("payments", 0, "from_user_id"), "u_nobody"),
                      (("requests", 0, "status"), "open"), (("tokens",), []), (("idempotency",), "x")):
        b = copy.deepcopy(ex)
        node = b["state"]
        for part in path[:-1]:
            node = node[part]
        node[path[-1]] = val
        bads.append((path, b))
    reset(fx())
    a2 = tok("ada")
    for path, b in bads:
        err(call("POST", "/_test/import", b), 422, "validation_failed", path)
    assert bal(a2) == 10000, "a rejected import changed the destination"


@probe("R105 import rejects corrupted seeded records (no receipt to cross-check)")
def _():
    import copy
    reset(fx(payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 5,
                        "note": "", "visibility": "public"}]))
    ex = call("GET", "/_test/export")[1]
    for field, val in (("created_at", "yesterday"), ("created_at", "2026-02-30T10:00:00+00:00"),
                       ("request_id", "rq_gone"), ("settlement_id", "st_gone")):
        b = copy.deepcopy(ex)
        b["state"]["payments"][0][field] = val
        err(call("POST", "/_test/import", b), 422, "validation_failed", (field, val))


def main():
    only = sys.argv[2:]
    fails = 0
    for rid, fn in PROBES:
        if only and not any(o in rid for o in only):
            continue
        try:
            fn()
            print("PASS", rid)
        except Exception as e:  # noqa: BLE001
            fails += 1
            print("FAIL", rid, "--", repr(e)[:600])
    print(f"{len(PROBES) if not only else ''} probes, {fails} failed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
