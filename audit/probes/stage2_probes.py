"""spec-auditor stage 2 API probes: one probe per gap in ledger/stage-2.md (S2-n).

Usage: python3 stage2_probes.py http://127.0.0.1:PORT [STAGE1_URL] [name-filter ...]
STAGE1_URL (optional) is a running stage-1 service for the upgrade probe. Stdlib only.
"""
import copy
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
S1 = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2].startswith("http") else None
sys.argv = [sys.argv[0], URL]
import stage1_probes as P  # noqa: E402

call, k, err, ok, user, fx, reset, tok, par = P.call, P.k, P.err, P.ok, P.user, P.fx, P.reset, P.tok, P.par
RFC3339 = P.RFC3339
PROBES = []


def probe(name):
    def deco(fn):
        PROBES.append((name, fn))
        return fn
    return deco


def iso(delta_s):
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_s)).isoformat(timespec="seconds")


def A(aid, amount, status="open", frm="u_ada", to="u_bob", exp=7200, **x):
    d = {"id": aid, "from_user_id": frm, "to_user_id": to, "amount": amount, "note": "deposit",
         "visibility": "public", "status": status, "expires_at": iso(exp)}
    d.update(x)
    return d


def me(t):
    return call("GET", "/me", token=t)[1]


def authz(t, to="bob", amount=2000, key=None, **x):
    return call("POST", "/authorizations", dict({"to_handle": to, "amount": amount}, **x), token=t, key=key or k())


def cap(t, aid, body=None, key=None):
    return call("POST", f"/authorizations/{aid}/capture", {} if body is None else body, token=t, key=key or k())


def world2(ops=None, **kw):
    reset(fx(ops=ops, **kw))
    return tok("ada"), tok("bob"), tok("cy")


# ---- 1. funds checks use available -------------------------------------------------

@probe("S2-49/50 funds checks against available; captures spend held money")
def _():
    ada, bob, cy = world2(ops=["u_cy"])
    a = ok(authz(ada, amount=8000), 201)
    m = me(ada)
    assert (m["balance"], m["total"], m["available"], m["held"]) == (10000, 10000, 2000, 8000), m
    err(call("POST", "/payments", {"to_handle": "cy", "amount": 2001}, token=ada, key=k()), 409, "insufficient_funds")
    rid = ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 2001}, token=bob, key=k()), 201)["request_id"]
    err(call("POST", f"/requests/{rid}/pay", {}, token=ada, key=k()), 409, "insufficient_funds")
    err(authz(ada, to="cy", amount=2001), 409, "insufficient_funds")
    err(call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 2001}]},
             token=cy, key=k()), 409, "insufficient_funds")
    ok(call("POST", "/payments", {"to_handle": "cy", "amount": 2000}, token=ada, key=k()), 201)
    assert me(ada)["available"] == 0
    p = ok(cap(bob, a["authorization_id"]), 201)
    assert p["amount"] == 8000
    m = me(ada)
    assert (m["total"], m["available"], m["held"]) == (0, 0, 0), m
    assert me(bob)["total"] == 2500 + 8000


# ---- 2. clock expiry -------------------------------------------------------------------

@probe("S2-61/62/74 clock expiry without a triggering request")
def _():
    ada, bob, _ = world2(authorization_ttl_seconds=2)
    a = ok(authz(ada, amount=500), 201)
    aid = a["authorization_id"]
    t0 = datetime.fromisoformat(a["created_at"])
    assert datetime.fromisoformat(a["expires_at"]) - t0 == timedelta(seconds=2), a
    time.sleep(3.2)
    m = me(ada)
    assert (m["available"], m["held"]) == (10000, 0), m
    assert call("GET", "/authorizations?status=open", token=ada)[1]["authorizations"] == []
    ex = call("GET", "/authorizations?status=expired", token=bob)[1]["authorizations"]
    assert [x["authorization_id"] for x in ex] == [aid] and ex[0]["status"] == "expired"
    assert ex[0]["remaining_amount"] == 0
    err(cap(bob, aid), 409, "authorization_expired")
    err(call("POST", f"/authorizations/{aid}/void", token=ada), 409, "authorization_not_open")


@probe("S2-80 a capture racing the deadline never moves money after expiry")
def _():
    ada, bob, _ = world2(authorization_ttl_seconds=1)
    a = ok(authz(ada, amount=500), 201)
    time.sleep(1.2)
    err(cap(bob, a["authorization_id"]), 409, "authorization_expired")
    assert me(bob)["total"] == 2500


# ---- 3. linearizability --------------------------------------------------------------------

@probe("S2-80/48/51 concurrent captures, capture vs void, parallel authorisations")
def _():
    ada, bob, _ = world2()
    aid = ok(authz(ada, amount=1000), 201)["authorization_id"]
    out = par(lambda i: cap(bob, aid, {"amount": 100, "final": False}), 20)
    assert all(o[0] in (201, 409) for o in out), sorted({o[0] for o in out})
    assert [o[0] for o in out].count(201) == 10, [o[0] for o in out]
    m = me(ada)
    assert m["total"] == 9000 and m["held"] == 0 and m["available"] == 9000, m
    # capture vs void
    for _ in range(5):
        aid = ok(authz(ada, amount=50), 201)["authorization_id"]
        out = par(lambda i: cap(bob, aid) if i % 2 == 0 else call("POST", f"/authorizations/{aid}/void", token=ada), 2)
        assert (out[0][0] == 201) != (out[1][0] == 200), (out[0][0], out[1][0])
    # parallel authorisations drain available exactly
    reset(fx(users=[user("ada", 1000), user("bob", 0)]))
    toks = [tok("ada") for _ in range(5)]
    out = par(lambda i: authz(toks[i % 5], amount=30), 50)
    st = [o[0] for o in out]
    assert st.count(201) == 33 and st.count(409) == 17, sorted(st)
    m = me(toks[0])
    assert (m["held"], m["available"], m["total"]) == (990, 10, 1000), m


# ---- 4-5. capture modes ------------------------------------------------------------------------

@probe("S2-71/75/77 extended capture, partial then void, final type")
def _():
    ada, bob, _ = world2()
    aid = ok(authz(ada, amount=2000), 201)["authorization_id"]
    p1 = ok(cap(bob, aid, {"amount": 700, "final": False}), 201)
    lst = call("GET", "/authorizations", token=ada)[1]["authorizations"][0]
    assert (lst["status"], lst["captured_amount"], lst["remaining_amount"], lst["payment_ids"]) == \
        ("open", 700, 1300, [p1["payment_id"]]), lst
    assert lst["payment_id"] == p1["payment_id"]
    assert me(ada)["held"] == 1300
    err(cap(bob, aid, {"amount": 1301, "final": False}), 422, "capture_exceeds_authorization")
    err(cap(bob, aid, {"amount": 5, "final": "false"}), 400, "malformed_request")
    p2 = ok(cap(bob, aid, {"amount": 1300, "final": False}), 201)
    lst = call("GET", "/authorizations", token=ada)[1]["authorizations"][0]
    assert (lst["status"], lst["captured_amount"], lst["remaining_amount"], lst["payment_ids"]) == \
        ("captured", 2000, 0, [p1["payment_id"], p2["payment_id"]]), lst
    # partial capture then void
    aid = ok(authz(ada, amount=1000), 201)["authorization_id"]
    ok(cap(bob, aid, {"amount": 300, "final": False}), 201)
    v = ok(call("POST", f"/authorizations/{aid}/void", token=ada), 200)
    assert (v["status"], v["captured_amount"], v["remaining_amount"], len(v["payment_ids"])) == ("voided", 300, 0, 1), v
    m = me(ada)
    assert m["held"] == 0 and m["total"] == 10000 - 2000 - 300, m
    ok(call("POST", f"/authorizations/{aid}/void", token=ada), 200)
    err(cap(bob, aid), 409, "authorization_not_open")


@probe("S2-68/69/72/73 default final capture releases the remainder")
def _():
    ada, bob, _ = world2()
    aid = ok(authz(ada, amount=2000), 201)["authorization_id"]
    err(cap(bob, aid, {"amount": 2001}), 422, "capture_exceeds_authorization")
    for bad in (0, 1.5, -1, True, "100", None):
        err(cap(bob, aid, {"amount": bad}), 422, "validation_failed", bad)
    assert me(ada)["available"] == 8000
    p = ok(cap(bob, aid, {"amount": 1500}), 201)
    assert p["amount"] == 1500
    m = me(ada)
    assert (m["total"], m["held"], m["available"]) == (8500, 0, 8500), m
    err(cap(bob, aid, {"amount": 1}), 409, "authorization_not_open")
    err(call("POST", f"/authorizations/{aid}/void", token=ada), 409, "authorization_not_open")


# ---- 6. idempotency on the new paths -----------------------------------------------------------

@probe("S2-70/54/79 idempotency on authorisations and captures")
def _():
    ada, bob, _ = world2()
    aid = ok(authz(ada, amount=2000), 201)["authorization_id"]
    key = k()
    first = ok(cap(bob, aid, {}, key=key), 201)
    err(cap(bob, aid, {"amount": 2000}, key=key), 409, "idempotency_key_reuse")
    assert ok(cap(bob, aid, {}, key=key), 200) == first
    aid2 = ok(authz(ada, amount=1000), 201)["authorization_id"]
    key = k()
    c1 = ok(cap(bob, aid2, {"amount": 100, "final": False}, key=key), 201)
    ok(cap(bob, aid2, {"amount": 100, "final": False}), 201)
    assert ok(cap(bob, aid2, {"amount": 100, "final": False}, key=key), 200) == c1, "replay after later captures"
    assert me(ada)["held"] == 800
    key = k()
    out = par(lambda i: authz(ada, amount=10, key=key), 20)
    assert sorted(o[0] for o in out).count(201) == 1 and all(o[0] in (200, 201) for o in out)
    assert len({json.dumps(o[1], sort_keys=True) for o in out}) == 1
    assert me(ada)["held"] == 810
    err(call("POST", "/authorizations", {"to_handle": "bob", "amount": 5}, token=ada), 400, "missing_idempotency_key")
    err(call("POST", f"/authorizations/{aid2}/capture", {}, token=bob), 400, "missing_idempotency_key")
    key = k()
    ok(authz(ada, amount=5, key=key), 201)
    err(authz(ada, amount=-5, key=key), 409, "idempotency_key_reuse")


# ---- 7. permissions --------------------------------------------------------------------------------

@probe("S2-65/76 permissions: 403 for wrong party and third party, 404 unknown, 401")
def _():
    ada, bob, cy = world2(ops=["u_cy"])
    aid = ok(authz(ada, amount=100), 201)["authorization_id"]
    err(cap(ada, aid), 403, "forbidden")
    err(cap(cy, aid), 403, "forbidden")
    err(call("POST", f"/authorizations/{aid}/void", token=bob), 403, "forbidden")
    err(call("POST", f"/authorizations/{aid}/void", token=cy), 403, "forbidden")
    err(cap(bob, "a_nope"), 404, "not_found")
    err(call("POST", "/authorizations/a_nope/void", token=ada), 404, "not_found")
    assert call("GET", "/authorizations", token=cy)[1]["authorizations"] == []
    for m, p in (("GET", "/authorizations"), ("POST", "/authorizations"), ("POST", f"/authorizations/{aid}/capture"),
                 ("POST", f"/authorizations/{aid}/void")):
        err(call(m, p, {} if m == "POST" else None, key=k()), 401, "unauthenticated", p)


# ---- 8. payment shape ---------------------------------------------------------------------------------

@probe("S2-66/67/26 authorization_id on every payment; captures follow visibility; open holds not in feed")
def _():
    reset(fx(ops=["u_ada"], payments=[{"id": "p_s", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1,
                                        "note": "", "visibility": "public"}]))
    ada, bob, cy = tok("ada"), tok("bob"), tok("cy")
    p = ok(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=ada, key=k()), 201)
    assert "authorization_id" in p and p["authorization_id"] is None and p["settlement_id"] is None
    rid = ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 1}, token=bob, key=k()), 201)["request_id"]
    assert ok(call("POST", f"/requests/{rid}/pay", {}, token=ada, key=k()), 201)["authorization_id"] is None
    st = ok(call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 1}]},
                 token=ada, key=k()), 201)
    assert st["payments"][0]["authorization_id"] is None
    a = ok(authz(ada, amount=50, note="hold n", visibility="private"), 201)
    feed = call("GET", "/activity?limit=200", token=ada)[1]["payments"]
    assert all("authorization_id" in x and x["authorization_id"] is None for x in feed)
    assert len(feed) == 4, "open authorisation must not be a feed item"
    c = ok(cap(bob, a["authorization_id"]), 201)
    assert (c["authorization_id"], c["request_id"], c["settlement_id"], c["note"], c["visibility"]) == \
        (a["authorization_id"], None, None, "hold n", "private"), c
    assert set(c) >= set(p), set(p) - set(c)
    assert c["payment_id"] not in [x["payment_id"] for x in call("GET", "/activity", token=cy)[1]["payments"]]
    assert c["payment_id"] in [x["payment_id"] for x in call("GET", "/activity", token=bob)[1]["payments"]]


# ---- 9. seeding ----------------------------------------------------------------------------------------

@probe("S2-55/57/58/59 seeded authorisations, ttl validation, reset errors change nothing")
def _():
    reset(fx(authorizations=[A("a_1", 2000), A("a_2", 300, status="captured"), A("a_3", 400, status="voided"),
                             A("a_4", 500, status="expired", exp=-7200), A("a_5", 100, exp=-7200)]))
    ada = tok("ada")
    m = me(ada)
    assert (m["total"], m["held"], m["available"]) == (10000, 2000, 8000), m
    st = {x["authorization_id"]: x["status"] for x in call("GET", "/authorizations", token=ada)[1]["authorizations"]}
    assert st == {"a_1": "open", "a_2": "captured", "a_3": "voided", "a_4": "expired", "a_5": "expired"}, st
    for bad in (fx(authorizations=[A("a_x", 12000)]),
                fx(authorizations=[A("a_x", 6000), A("a_y", 6000)]),
                fx(authorization_ttl_seconds=0), fx(authorization_ttl_seconds=-1),
                fx(authorization_ttl_seconds=1.5), fx(authorization_ttl_seconds="600"),
                fx(authorization_ttl_seconds=True)):
        err(call("POST", "/_test/reset", bad), 422, "validation_failed", str(bad.get("authorization_ttl_seconds")))
    assert me(ada)["held"] == 2000, "a rejected reset changed state"
    s, _, _ = call("POST", "/_test/reset", fx(authorizations=[A("a_x", 12000, exp=-7200)]))
    assert s == 204, "an expired seeded hold does not count"
    s, _, _ = call("POST", "/_test/reset", fx(authorizations=[A("a_x", 12000, status="captured")]))
    assert s == 204, "only open holds count"
    reset(fx(authorization_ttl_seconds=37))
    a = ok(authz(tok("ada"), amount=1), 201)
    assert datetime.fromisoformat(a["expires_at"]) - datetime.fromisoformat(a["created_at"]) == timedelta(seconds=37)
    reset(fx())
    a = ok(authz(tok("ada"), amount=1), 201)
    assert datetime.fromisoformat(a["expires_at"]) - datetime.fromisoformat(a["created_at"]) == timedelta(seconds=600)


@probe("S2-63/64 POST /authorizations shape and errors")
def _():
    ada, bob, _ = world2()
    a = ok(authz(ada, amount=2000, note="deposit", visibility="private"), 201)
    want = {"authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount", "captured_amount",
            "currency", "note", "visibility", "status", "expires_at", "payment_id", "created_at", "remaining_amount"}
    assert want <= set(a), want - set(a)
    assert (a["from_handle"], a["to_handle"], a["amount"], a["captured_amount"], a["remaining_amount"], a["currency"],
            a["status"], a["payment_id"]) == ("ada", "bob", 2000, 0, 2000, "EUR", "open", None), a
    assert RFC3339.match(a["expires_at"]) and RFC3339.match(a["created_at"])
    d = ok(authz(ada, amount=1), 201)
    assert d["note"] == "" and d["visibility"] == "public"
    err(authz(ada, to="ada"), 422, "self_payment")
    err(authz(ada, to="nobody"), 404, "not_found")
    for bad in ({"amount": 0}, {"amount": 10 ** 9 + 1}, {"amount": 1.5}, {"amount": True}, {"note": "x" * 201},
                {"visibility": "Public"}, {"note": None}):
        err(call("POST", "/authorizations", dict({"to_handle": "bob", "amount": 1}, **bad), token=ada, key=k()),
            422, "validation_failed", bad)
    err(authz(ada, amount=10 ** 9), 409, "insufficient_funds")


@probe("S2-78 GET /authorizations scoping, order, filters, paging")
def _():
    ada, bob, cy = world2()
    ids = [ok(authz(ada, amount=1 + i), 201)["authorization_id"] for i in range(3)]
    ok(authz(bob, to="ada", amount=1), 201)
    lst = call("GET", "/authorizations", token=ada)[1]["authorizations"]
    assert [x["amount"] for x in lst][1:] == [3, 2, 1] or [x["amount"] for x in lst] == [1, 3, 2, 1], lst
    assert [x["authorization_id"] for x in call("GET", "/authorizations?direction=outgoing", token=ada)[1]["authorizations"]] == ids[::-1]
    assert len(call("GET", "/authorizations?direction=incoming", token=ada)[1]["authorizations"]) == 1
    b = call("GET", "/authorizations?limit=2&offset=0", token=ada)[1]
    assert len(b["authorizations"]) == 2 and b["has_more"] is True
    for q in ("direction=both", "status=pending", "limit=0", "limit=201", "offset=-1", "limit=4.0", "limit=%2B4"):
        err(call("GET", "/authorizations?" + q, token=ada), 422, "validation_failed", q)
    assert call("GET", "/authorizations", token=cy)[1]["authorizations"] == []


# ---- 13. upgrade from stage 1 (API part) -------------------------------------------------------------------

@probe("S2-42/43/46 a stage-1 export imports into stage 2 with tokens, replays and requests")
def _():
    if not S1:
        raise AssertionError("SKIP: no stage-1 URL given")
    c1 = lambda m, p, b=None, **kw: P.call.__wrapped__(m, p, b, **kw) if hasattr(P.call, "__wrapped__") else None
    from urllib.parse import urlsplit
    s2base = P.BASE
    P.BASE = urlsplit(S1)
    try:
        P.reset(fx(ops=["u_ada"]))
        ada, bob = tok("ada"), tok("bob")
        key = k()
        pay = ok(call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=ada, key=key), 201)
        rid = ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 7}, token=bob, key=k()), 201)["request_id"]
        st = ok(call("POST", "/settlements", {"transfers": [{"from_handle": "bob", "to_handle": "cy", "amount": 3}]},
                     token=ada, key=k()), 201)
        ex = call("GET", "/_test/export")[1]
    finally:
        P.BASE = s2base
    reset(fx())
    s, b, _ = call("POST", "/_test/import", ex)
    assert s == 204, (s, b)
    m = me(ada)
    assert (m["balance"], m["total"], m["available"], m["held"]) == (9900, 9900, 9900, 0), m
    assert ok(call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=ada, key=key), 200) == pay
    ok(call("POST", f"/requests/{rid}/pay", {}, token=ada, key=k()), 201)
    feed = call("GET", "/activity?limit=200", token=ada)[1]["payments"]
    assert all(x.get("authorization_id", "missing") is None for x in feed), feed
    a = ok(authz(ada, amount=1), 201)
    assert datetime.fromisoformat(a["expires_at"]) - datetime.fromisoformat(a["created_at"]) == timedelta(seconds=600)
    assert st["settlement_id"] in [x["settlement_id"] for x in feed]


# ---- 14. content negotiation -------------------------------------------------------------------------------

@probe("S2-2 /requests and /authorizations: HTML only for text/html")
def _():
    ada, _, _ = world2()
    browser = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    for path in ("/requests", "/authorizations"):
        for acc in (None, "*/*", "application/json"):
            h = {"Accept": acc} if acc else {}
            s, b, ct = call("GET", path, token=ada, headers=h)
            assert s == 200 and ct.startswith("application/json") and isinstance(b, dict), (path, acc, s, ct)
        s, b, ct = call("GET", path, headers={"Accept": browser})
        assert s == 200 and ct.startswith("text/html"), (path, s, ct)
    for path in ("/", "/split", "/signup", "/login"):
        s, b, ct = call("GET", path, headers={"Accept": browser})
        assert s == 200 and ct.startswith("text/html"), (path, s, ct)


# ---- 21. export/import of stage-2 state -------------------------------------------------------------------

@probe("S2-81 export/import carries holds, ttl, capture records and new-path receipts")
def _():
    ada, bob, _ = world2(authorization_ttl_seconds=900)
    akey, ckey = k(), k()
    a = ok(authz(ada, amount=1000, key=akey), 201)
    c = ok(cap(bob, a["authorization_id"], {"amount": 300, "final": False}, key=ckey), 201)
    ex = call("GET", "/_test/export")[1]
    reset(fx())
    s, b, _ = call("POST", "/_test/import", ex)
    assert s == 204, (s, b)
    s, b, _ = call("POST", "/_test/import", ex)
    assert s == 204
    m = me(ada)
    assert (m["total"], m["held"], m["available"]) == (9700, 700, 9000), m
    assert ok(authz(ada, amount=1000, key=akey), 200) == a
    assert ok(cap(bob, a["authorization_id"], {"amount": 300, "final": False}, key=ckey), 200) == c
    lst = call("GET", "/authorizations", token=ada)[1]["authorizations"]
    assert len(lst) == 1 and lst[0]["payment_ids"] == [c["payment_id"]] and lst[0]["remaining_amount"] == 700
    n = ok(authz(ada, amount=1), 201)
    assert datetime.fromisoformat(n["expires_at"]) - datetime.fromisoformat(n["created_at"]) == timedelta(seconds=900)
    ok(cap(bob, a["authorization_id"]), 201)
    assert me(ada)["held"] == 1


def main():
    only = [a for a in sys.argv[2:]]
    fails = 0
    for name, fn in PROBES:
        if only and not any(o in name for o in only):
            continue
        try:
            fn()
            print("PASS", name)
        except Exception as e:  # noqa: BLE001
            fails += 1
            print("FAIL", name, "--", repr(e)[:700])
    print(f"{len(PROBES)} probes, {fails} failed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
