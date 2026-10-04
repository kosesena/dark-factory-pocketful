#!/usr/bin/env python3
"""Reviewer's stage-2 API probes: holds, captures, voids, expiry, available-based funds,
HTML/JSON routing, stage-1 export upgrade, plus exact-number edge classes. Written from the
specification only.

Usage: python3 probes_s2.py http://localhost:8080 [stage1-base-url-for-upgrade-test]
"""
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

BASE = sys.argv[1].rstrip("/")
S1 = sys.argv[2].rstrip("/") if len(sys.argv) > 2 else None
RESULTS = []


def call(method, path, body=None, token=None, key=None, raw=None, headers=None, base=None):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    if key is not None:
        h["Idempotency-Key"] = key
    h.update(headers or {})
    req = urllib.request.Request((base or BASE) + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            txt = r.read()
            ct = r.headers.get("Content-Type", "")
            return r.status, (json.loads(txt) if txt and "json" in ct else txt), r.headers
    except urllib.error.HTTPError as e:
        txt = e.read()
        try:
            return e.code, (json.loads(txt) if txt else None), e.headers
        except ValueError:
            return e.code, {"_raw": txt[:200]}, e.headers


def code(b):
    try:
        return b["error"]["code"]
    except (TypeError, KeyError):
        return None


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))


def err(name, resp, status, ecode):
    st, b, _ = resp
    check(name, st == status and code(b) == ecode, "got %s %s" % (st, b))


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


NOW = datetime.now(timezone.utc)


def fixture(**kw):
    fx = {
        "currency": "EUR", "minor_units": 2,
        "users": [
            {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
             "display_name": "Ada", "handle": "ada", "balance": 10000},
            {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
             "display_name": "Bob", "handle": "bob", "balance": 2500},
            {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
             "display_name": "Cy", "handle": "cy", "balance": 0},
            {"id": "u_op", "email": "op@example.com", "password": "correct horse",
             "display_name": "Op", "handle": "op", "balance": 0},
        ],
        "payments": [], "requests": [], "settlement_operator_ids": ["u_op"],
        "authorizations": [
            {"id": "a_open", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000,
             "note": "deposit", "visibility": "public", "status": "open",
             "expires_at": iso(NOW + timedelta(hours=2))},
            {"id": "a_past", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 3000,
             "note": "old", "visibility": "private", "status": "open",
             "expires_at": iso(NOW - timedelta(hours=2))},
            {"id": "a_void", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 100,
             "note": "", "visibility": "public", "status": "voided",
             "expires_at": iso(NOW + timedelta(hours=2))},
        ],
    }
    fx.update(kw)
    return fx


def reset(fx, base=None):
    st, b, _ = call("POST", "/_test/reset", fx, base=base)
    assert st == 204, (st, b)
    return {u["handle"]: call("POST", "/auth/login", {"email": u["email"], "password": u["password"]},
                              base=base)[1]["token"] for u in fx["users"]}


def me(tok, base=None):
    return call("GET", "/me", token=tok, base=base)[1]


def auths(tok, q=""):
    return call("GET", "/authorizations?limit=200" + q, token=tok)[1]["authorizations"]


def by_id(lst, i):
    return next((a for a in lst if a["authorization_id"] == i), None)


def main():
    T = reset(fixture())
    a, b, c, op = T["ada"], T["bob"], T["cy"], T["op"]

    # seeded holds and /me
    m = me(a)
    check("me seeded open hold", (m["balance"], m["total"], m["available"], m["held"]) == (10000, 10000, 8000, 2000), m)
    m = me(b)
    check("me no hold: all agree", (m["balance"], m["total"], m["available"], m["held"]) == (2500, 2500, 2500, 0), m)
    la = auths(a)
    check("seeded past expiry is expired", by_id(la, "a_past")["status"] == "expired", by_id(la, "a_past"))
    check("seeded voided kept", by_id(la, "a_void")["status"] == "voided", "")
    check("expired filter", {x["authorization_id"] for x in auths(a, "&status=expired")} == {"a_past"}, "")
    check("open filter excludes expired", {x["authorization_id"] for x in auths(a, "&status=open")} == {"a_open"}, "")
    check("direction outgoing", {x["authorization_id"] for x in auths(a, "&direction=outgoing")} == {"a_open", "a_past"}, "")
    check("direction incoming", {x["authorization_id"] for x in auths(a, "&direction=incoming")} == {"a_void"}, "")
    check("only involving caller", auths(c) == [] and auths(op) == [], "")
    for q in ("direction=x", "status=closed", "limit=0", "limit=201", "offset=-1", "limit=1e2", "limit=+5"):
        err("auth list bad %s" % q, call("GET", "/authorizations?" + q, token=a), 422, "validation_failed")
    err("auth list 401", call("GET", "/authorizations"), 401, "unauthenticated")

    # held funds cannot fund payments / request pay / settlements / new holds
    err("pay over available", call("POST", "/payments", {"to_handle": "cy", "amount": 8001}, token=a, key="p1"),
        409, "insufficient_funds")
    st, _, _ = call("POST", "/payments", {"to_handle": "cy", "amount": 1000}, token=a, key="p2")
    check("pay within available", st == 201, st)
    _, rq, _ = call("POST", "/requests", {"payer_handle": "ada", "amount": 7001}, token=c, key="r1")
    err("request pay over available", call("POST", "/requests/%s/pay" % rq["request_id"], {}, token=a, key="rp"),
        409, "insufficient_funds")
    err("settlement net debit over available", call("POST", "/settlements", {"transfers": [
        {"from_handle": "ada", "to_handle": "cy", "amount": 7001}]}, token=op, key="s1"), 409, "insufficient_funds")
    err("auth over available", call("POST", "/authorizations", {"to_handle": "cy", "amount": 7001}, token=a, key="a1"),
        409, "insufficient_funds")
    check("totals unchanged by refusals", me(a)["total"] == 9000 and me(a)["available"] == 7000, me(a))

    # create authorization
    st, au, _ = call("POST", "/authorizations", {"to_handle": "cy", "amount": 3000, "note": "bike 🚲",
                                                 "visibility": "private", "zz": 1}, token=a, key="a2")
    check("auth 201 shape", st == 201 and au["status"] == "open" and au["captured_amount"] == 0 and
          au["remaining_amount"] == 3000 and au["payment_id"] is None and au.get("payment_ids") == [] and
          au["from_handle"] == "ada" and au["to_handle"] == "cy" and au["currency"] == "EUR" and
          au["note"] == "bike 🚲" and au["visibility"] == "private", au)
    ca = datetime.fromisoformat(au["created_at"])
    ea = datetime.fromisoformat(au["expires_at"])
    check("expires_at = created_at + 600", ea - ca == timedelta(seconds=600) and ea.utcoffset() is not None, au)
    m = me(a)
    check("hold moves no money", m["total"] == 9000 and m["held"] == 5000 and m["available"] == 4000, m)
    check("receiver unaffected by hold", me(c)["total"] == 1000 and me(c)["available"] == 1000, me(c))
    st, feed, _ = call("GET", "/activity?limit=200", token=a)
    check("open auth not in feed", all(p.get("authorization_id") is None for p in feed["payments"]), "")
    check("ordinary payments carry authorization_id null", all("authorization_id" in p for p in feed["payments"]), "")
    st, rep, _ = call("POST", "/authorizations", {"to_handle": "cy", "amount": 3000, "note": "bike 🚲",
                                                  "visibility": "private", "zz": 1}, token=a, key="a2")
    check("auth replay 200 identical, no new hold", st == 200 and rep == au and me(a)["held"] == 5000, st)
    err("auth key reuse", call("POST", "/authorizations", {"to_handle": "cy", "amount": 1}, token=a, key="a2"),
        409, "idempotency_key_reuse")
    err("auth missing key", call("POST", "/authorizations", {"to_handle": "cy", "amount": 1}, token=a), 400,
        "missing_idempotency_key")
    err("auth self", call("POST", "/authorizations", {"to_handle": "ada", "amount": 1}, token=a, key="a3"), 422, "self_payment")
    err("auth unknown", call("POST", "/authorizations", {"to_handle": "zz", "amount": 1}, token=a, key="a4"), 404, "not_found")
    for bad in (0, -1, 1000000001, "5", True, 1.5):
        err("auth amount %r" % (bad,), call("POST", "/authorizations", {"to_handle": "cy", "amount": bad}, token=a,
                                           key="a5%r" % (bad,)), 422, "validation_failed")
    err("auth note long", call("POST", "/authorizations", {"to_handle": "cy", "amount": 1, "note": "x" * 201},
                               token=a, key="a6"), 422, "validation_failed")
    err("auth visibility bad", call("POST", "/authorizations", {"to_handle": "cy", "amount": 1, "visibility": "x"},
                                    token=a, key="a7"), 422, "validation_failed")
    err("auth 401", call("POST", "/authorizations", {"to_handle": "cy", "amount": 1}, key="a8"), 401, "unauthenticated")

    aid = au["authorization_id"]
    # capture permission/validation
    err("payer cannot capture", call("POST", "/authorizations/%s/capture" % aid, {}, token=a, key="c0"), 403, "forbidden")
    err("third party cannot capture", call("POST", "/authorizations/%s/capture" % aid, {}, token=b, key="c0"), 403, "forbidden")
    err("capture unknown", call("POST", "/authorizations/nope/capture", {}, token=c, key="c0"), 404, "not_found")
    err("capture exceeds", call("POST", "/authorizations/%s/capture" % aid, {"amount": 3001}, token=c, key="c1"),
        422, "capture_exceeds_authorization")
    for bad in (0, -5, 1.5, "10", True):
        err("capture amount %r" % (bad,), call("POST", "/authorizations/%s/capture" % aid, {"amount": bad}, token=c,
                                              key="c2%r" % (bad,)), 422, "validation_failed")
    err("capture missing key", call("POST", "/authorizations/%s/capture" % aid, {}, token=c), 400, "missing_idempotency_key")
    err("receiver cannot void", call("POST", "/authorizations/%s/void" % aid, {}, token=c), 403, "forbidden")
    err("third party cannot void", call("POST", "/authorizations/%s/void" % aid, {}, token=b), 403, "forbidden")
    err("void unknown", call("POST", "/authorizations/nope/void", {}, token=a), 404, "not_found")

    # extended (non-final) captures
    st, p1, _ = call("POST", "/authorizations/%s/capture" % aid, {"amount": 700, "final": False}, token=c, key="c3")
    check("nonfinal capture 201 payment shape", st == 201 and p1["amount"] == 700 and p1["authorization_id"] == aid
          and p1["request_id"] is None and p1["note"] == "bike 🚲" and p1["visibility"] == "private"
          and p1["from_handle"] == "ada" and p1["to_handle"] == "cy", p1)
    x = by_id(auths(a), aid)
    check("still open after nonfinal", x["status"] == "open" and x["captured_amount"] == 700 and
          x["remaining_amount"] == 2300 and x["payment_id"] == p1["payment_id"] and x["payment_ids"] == [p1["payment_id"]], x)
    m = me(a)
    check("capture spends held money", m["total"] == 8300 and m["held"] == 4300 and m["available"] == 4000, m)
    check("receiver credited", me(c)["total"] == 1700, me(c))
    st, r2, _ = call("POST", "/authorizations/%s/capture" % aid, {"amount": 700, "final": False}, token=c, key="c3")
    check("capture replay 200 identical, money once", st == 200 and r2 == p1 and me(c)["total"] == 1700, st)
    err("capture key different body", call("POST", "/authorizations/%s/capture" % aid, {"amount": 700}, token=c, key="c3"),
        409, "idempotency_key_reuse")
    err("capture exceeds remaining", call("POST", "/authorizations/%s/capture" % aid, {"amount": 2301, "final": False},
                                          token=c, key="c4"), 422, "capture_exceeds_authorization")
    st, p2, _ = call("POST", "/authorizations/%s/capture" % aid, {"amount": 300, "final": False}, token=c, key="c5")
    st3, p3, _ = call("POST", "/authorizations/%s/capture" % aid, {"final": False}, token=c, key="c6")
    check("omitted amount = remainder; closes even with final false", st3 == 201 and p3["amount"] == 2000, p3)
    x = by_id(auths(a), aid)
    check("captured cumulative + ids", x["status"] == "captured" and x["captured_amount"] == 3000 and
          x["remaining_amount"] == 0 and x["payment_ids"] == [p1["payment_id"], p2["payment_id"], p3["payment_id"]], x)
    err("capture after closed", call("POST", "/authorizations/%s/capture" % aid, {"amount": 1}, token=c, key="c7"),
        409, "authorization_not_open")
    err("void captured", call("POST", "/authorizations/%s/void" % aid, {}, token=a), 409, "authorization_not_open")
    st, fc, _ = call("GET", "/activity?limit=200", token=c)
    caps = [p for p in fc["payments"] if p.get("authorization_id") == aid]
    check("captures in receiver feed", len(caps) == 3, len(caps))
    st, fb, _ = call("GET", "/activity?limit=200", token=b)
    check("private captures hidden from third party", not [p for p in fb["payments"] if p.get("authorization_id") == aid], "")

    # default final capture releases remainder
    st, au2, _ = call("POST", "/authorizations", {"to_handle": "cy", "amount": 2000}, token=a, key="a9")
    before = me(a)
    st, pc, _ = call("POST", "/authorizations/%s/capture" % au2["authorization_id"], {"amount": 1500}, token=c, key="c8")
    after = me(a)
    check("final capture releases remainder in same step", st == 201 and after["total"] == before["total"] - 1500 and
          after["held"] == before["held"] - 2000 and after["available"] == before["available"] + 500, (before, after))
    x = by_id(auths(a), au2["authorization_id"])
    check("captured status, remaining 0", x["status"] == "captured" and x["captured_amount"] == 1500 and x["remaining_amount"] == 0, x)
    err("second capture after final", call("POST", "/authorizations/%s/capture" % au2["authorization_id"], {"amount": 1},
                                           token=c, key="c9"), 409, "authorization_not_open")
    st, rr, _ = call("POST", "/authorizations/%s/capture" % au2["authorization_id"], {"amount": 1500}, token=c, key="c8")
    check("final capture replay 200 after close", st == 200 and rr == pc, st)
    # {} vs explicit amount differ
    st, au3, _ = call("POST", "/authorizations", {"to_handle": "cy", "amount": 400}, token=a, key="a10")
    st, _, _ = call("POST", "/authorizations/%s/capture" % au3["authorization_id"], {}, token=c, key="c10")
    err("capture {} then {amount} same key -> 409", call("POST", "/authorizations/%s/capture" % au3["authorization_id"],
                                                          {"amount": 400}, token=c, key="c10"), 409, "idempotency_key_reuse")

    # void partially captured
    st, au4, _ = call("POST", "/authorizations", {"to_handle": "cy", "amount": 1000}, token=a, key="a11")
    i4 = au4["authorization_id"]
    call("POST", "/authorizations/%s/capture" % i4, {"amount": 250, "final": False}, token=c, key="c11")
    h0 = me(a)["held"]
    st, v, _ = call("POST", "/authorizations/%s/void" % i4, {}, token=a)
    check("void partial: 200 voided, records kept", st == 200 and v["status"] == "voided" and v["captured_amount"] == 250
          and len(v["payment_ids"]) == 1 and v["remaining_amount"] == 0, v)
    check("void releases only remainder", me(a)["held"] == h0 - 750, me(a))
    st, v2, _ = call("POST", "/authorizations/%s/void" % i4, {}, token=a)
    check("void twice 200", st == 200 and v2["status"] == "voided", st)
    err("capture voided", call("POST", "/authorizations/%s/capture" % i4, {}, token=c, key="c12"), 409, "authorization_not_open")
    err("void seeded expired", call("POST", "/authorizations/a_past/void", {}, token=a), 409, "authorization_not_open")
    err("capture seeded expired", call("POST", "/authorizations/a_past/capture", {}, token=b, key="c13"), 409,
        "authorization_expired")

    # sum of totals is conserved
    tot = sum(me(t)["total"] for t in (a, b, c, op))
    check("sum of totals == seeded", tot == 12500, tot)

    # reset validation
    snap_me = me(a)
    fx = fixture()
    fx["authorizations"].append({"id": "a_big", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 2501,
                                 "note": "", "visibility": "public", "status": "open",
                                 "expires_at": iso(NOW + timedelta(hours=3))})
    err("seeded holds > balance -> 422", call("POST", "/_test/reset", fx), 422, "validation_failed")
    check("422 reset changed nothing", me(a) == snap_me, me(a))
    fx = fixture()
    fx["authorizations"].append({"id": "a_big", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 2501,
                                 "note": "", "visibility": "public", "status": "open",
                                 "expires_at": iso(NOW - timedelta(hours=3))})
    check("expired seeded hold over balance is fine", call("POST", "/_test/reset", fx)[0] == 204, "")
    for ttl in (0, -1, "600", 1.5, True):
        err("ttl %r -> 422" % (ttl,), call("POST", "/_test/reset", fixture(authorization_ttl_seconds=ttl)), 422,
            "validation_failed")
    fx = fixture()
    del fx["authorizations"]
    check("fixture without authorizations ok", call("POST", "/_test/reset", fx)[0] == 204, "")

    # expiry at the displayed deadline (ttl 1 and 2 s)
    for ttl in (1, 2):
        T = reset(fixture(authorization_ttl_seconds=ttl))
        a, b = T["ada"], T["bob"]
        st, ax, _ = call("POST", "/authorizations", {"to_handle": "bob", "amount": 100}, token=a, key="e%d" % ttl)
        exp = datetime.fromisoformat(ax["expires_at"]).timestamp()
        check("ttl %d: expires_at = created_at + ttl" % ttl,
              exp - datetime.fromisoformat(ax["created_at"]).timestamp() == ttl, ax)
        while time.time() < exp + 0.02:
            time.sleep(0.005)
        x = by_id(auths(a), ax["authorization_id"])
        m = me(a)
        check("ttl %d: at expires_at the hold is expired (status)" % ttl, x["status"] == "expired", x)
        # the fixture's own a_open (2000) stays held; only the new 100 must be released
        check("ttl %d: at expires_at the remainder is released (available)" % ttl, m["held"] == 2000 and m["available"] == 8000, m)
        err("ttl %d: capture at expires_at -> authorization_expired" % ttl,
            call("POST", "/authorizations/%s/capture" % ax["authorization_id"], {}, token=b, key="ex%d" % ttl),
            409, "authorization_expired")

    # concurrency: 40 non-final captures of 1 on a 25 hold; payer spending concurrently
    T = reset(fixture())
    a, b, c = T["ada"], T["bob"], T["cy"]
    st, ah, _ = call("POST", "/authorizations", {"to_handle": "cy", "amount": 25}, token=a, key="cc")

    def job(i):
        if i % 2:
            return "cap", call("POST", "/authorizations/%s/capture" % ah["authorization_id"], {"amount": 1, "final": False},
                               token=c, key="k%d" % i)[0]
        return "pay", call("POST", "/payments", {"to_handle": "bob", "amount": 400}, token=a, key="pp%d" % i)[0]
    with ThreadPoolExecutor(50) as ex:
        res = list(ex.map(job, range(80)))
    caps = [s for k, s in res if k == "cap"]
    pays = [s for k, s in res if k == "pay"]
    m = me(a)
    check("concurrent captures: exactly 25 succeed", caps.count(201) == 25 and all(s in (201, 409, 422) for s in caps), sorted(set(caps)))
    # seeded a_open keeps 2000 held; the 25 hold is fully captured; available started at 7975
    check("concurrent pays never touch held money", m["available"] >= 0 and m["held"] == 2000 and
          m["total"] == 10000 - 25 - 400 * pays.count(201) and pays.count(201) == 7975 // 400, (m, pays.count(201)))
    check("no 5xx under load", all(s < 500 for _, s in res), "")

    # HTML vs JSON on shared paths, UI routes, no external assets
    for p in ("/", "/requests", "/split", "/signup", "/login", "/authorizations"):
        st, body, hd = call("GET", p, headers={"Accept": "text/html,application/xhtml+xml"})
        check("html %s" % p, st == 200 and "text/html" in hd.get("Content-Type", ""), (st, hd.get("Content-Type")))
        if isinstance(body, bytes):
            check("no external assets %s" % p, b"http://" not in body and b"https://" not in body, "")
    err("/requests JSON without html accept", call("GET", "/requests"), 401, "unauthenticated")
    st, j, hd = call("GET", "/requests", token=a, headers={"Accept": "application/json"})
    check("/requests JSON with token", st == 200 and "requests" in j, st)
    st, j, hd = call("GET", "/authorizations", token=a)
    check("/authorizations JSON default", st == 200 and "authorizations" in j, st)
    for asset in ("/static/app.js", "/static/app.css"):
        st, body, _ = call("GET", asset)
        check("asset %s has no external URLs" % asset, st == 200 and b"https://" not in body and b"http://" not in body
              and b"@import" not in body, "")

    # exact-number edge classes (stage-1 rules, still apply)
    T = reset(fixture())
    a, b, c = T["ada"], T["bob"], T["cy"]
    for path, body in (("/payments", '{"to_handle":"bob","amount":1.0000000000000001}'),
                       ("/requests", '{"payer_handle":"bob","amount":1.0000000000000001}'),
                       ("/splits", '{"participant_handles":["bob"],"amount":1.0000000000000001}'),
                       ("/authorizations", '{"to_handle":"bob","amount":1.0000000000000001}'),
                       ("/payments", '{"to_handle":"bob","amount":1000000000.00000001}')):
        err("fractional %s -> 422" % path, call("POST", path, raw=body.encode(), token=a, key="fr" + path + body[-8:]),
            422, "validation_failed")
    call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1,"x":1.0000000000000001}', token=a, key="ex1")
    err("extra 1.0000000000000001 vs 1 is a different body",
        call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1,"x":1}', token=a, key="ex1"), 409, "idempotency_key_reuse")
    call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1,"x":1.5}', token=a, key="ex2")
    st, _, _ = call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1,"x":1.50}', token=a, key="ex2")
    check("extra 1.5 vs 1.50 is the same JSON value -> 200", st == 200, st)
    for path in ("/activity", "/requests", "/authorizations"):
        err("huge limit %s -> 422" % path, call("GET", path + "?limit=" + "9" * 5000, token=a), 422, "validation_failed")
        st, j, _ = call("GET", path + "?offset=" + "9" * 5000, token=a)
        check("huge offset %s -> 200 empty" % path, st == 200, (st, j))
    st, ex, _ = call("GET", "/_test/export")
    pays = ex["state"].get("payments")
    if isinstance(pays, list) and pays:
        bad = json.loads(json.dumps(ex))
        bad["state"]["payments"][0]["created_at"] = "not-a-timestamp"
        err("import invalid timestamp -> 422", call("POST", "/_test/import", bad), 422, "validation_failed")
        bad = json.loads(json.dumps(ex))
        bad["state"]["payments"][0]["amount"] = 1000000001
        err("import amount above max -> 422", call("POST", "/_test/import", bad), 422, "validation_failed")
    # stage-2 export/import round trip keeps holds
    T = reset(fixture())
    a, b = T["ada"], T["bob"]
    st, ah, _ = call("POST", "/authorizations", {"to_handle": "bob", "amount": 500}, token=a, key="ri")
    st, ex, _ = call("GET", "/_test/export")
    call("POST", "/_test/reset", fixture())
    st, _, _ = call("POST", "/_test/import", ex)
    m = me(a)
    check("import keeps holds and tokens", st == 204 and m["held"] == 2500 and m["available"] == 7500, m)
    st, rep, _ = call("POST", "/authorizations", {"to_handle": "bob", "amount": 500}, token=a, key="ri")
    check("auth replay after import", st == 200 and rep == ah, st)

    # upgrade: stage-1 export -> stage-2 import
    if S1:
        fx1 = fixture()
        del fx1["authorizations"]
        T1 = reset(fx1, base=S1)
        st, pay1, _ = call("POST", "/payments", {"to_handle": "bob", "amount": 123}, token=T1["ada"], key="lost", base=S1)
        st, rq1, _ = call("POST", "/requests", {"payer_handle": "ada", "amount": 77}, token=T1["bob"], key="rq", base=S1)
        st, ex1, _ = call("GET", "/_test/export", base=S1)
        st, _, _ = call("POST", "/_test/import", ex1)
        check("stage-1 export imports into stage-2", st == 204, st)
        m = me(T1["ada"])
        check("stage-1 token valid after upgrade; held 0", m and m.get("total") == 10000 - 123 and m.get("held") == 0
              and m.get("available") == m.get("total"), m)
        st, r, _ = call("POST", "/payments", {"to_handle": "bob", "amount": 123}, token=T1["ada"], key="lost")
        check("stage-1 lost payment retry after upgrade -> 200 original", st == 200 and r == pay1, (st, r))
        st, p, _ = call("POST", "/requests/%s/pay" % rq1["request_id"], {}, token=T1["ada"], key="pay-after")
        check("stage-1 pending request payable after upgrade", st == 201, (st, p))
        check("upgrade total conserved", me(T1["ada"])["total"] + me(T1["bob"])["total"] == 12500, "")

    fails = [r for r in RESULTS if not r[1]]
    for name, ok, det in RESULTS:
        print("%s  %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else "  -> %s" % (det,)))
    print("%d probes, %d failed" % (len(RESULTS), len(fails)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
