#!/usr/bin/env python3
"""Reviewer's stage-3 probes (statements, as_of/known_at, corrections, snapshots, historical
holds), written from the stage-3 specification only.

Usage: python3 probes_s3.py http://localhost:8080
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

BASE = sys.argv[1].rstrip("/")
RESULTS = []


def call(method, path, body=None, token=None, key=None):
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    if key is not None:
        h["Idempotency-Key"] = key
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            t = r.read()
            return r.status, json.loads(t) if t else None
    except urllib.error.HTTPError as e:
        t = e.read()
        try:
            return e.code, json.loads(t) if t else None
        except ValueError:
            return e.code, {"_raw": t[:100]}


def q(**kw):
    return "?" + urllib.parse.urlencode(kw)


def code(b):
    try:
        return b["error"]["code"]
    except (TypeError, KeyError):
        return None


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))


def expect(name, resp, status, ecode=None):
    st, b = resp
    check(name, st == status and (ecode is None or code(b) == ecode), "got %s %s" % (st, str(b)[:200]))


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


NOW = datetime.now(timezone.utc).replace(microsecond=0)
T1 = NOW - timedelta(days=10)
T2 = NOW - timedelta(days=9)
T3 = NOW - timedelta(days=8)  # a public payment between bob and cy
S = timedelta(seconds=1)


def fixture(**kw):
    fx = {
        "currency": "EUR", "minor_units": 2,
        "users": [
            {"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada",
             "handle": "ada", "balance": 10000},
            {"id": "u_bob", "email": "bob@example.com", "password": "correct horse", "display_name": "Bob",
             "handle": "bob", "balance": 2400},
            {"id": "u_cy", "email": "cy@example.com", "password": "correct horse", "display_name": "Cy",
             "handle": "cy", "balance": 100},
            {"id": "u_op", "email": "op@example.com", "password": "correct horse", "display_name": "Op",
             "handle": "op", "balance": 0},
        ],
        # ada opening 9300, bob opening 3200 + (−100 to cy) => bob 2400 final; cy opening 0
        "payments": [
            {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "a",
             "visibility": "public", "created_at": iso(T1)},
            {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 1200, "note": "b",
             "visibility": "private", "created_at": iso(T2)},
            {"id": "p_3", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 100, "note": "c",
             "visibility": "public", "created_at": iso(T3)},
        ],
        "requests": [], "authorizations": [], "settlement_operator_ids": ["u_op"],
    }
    fx.update(kw)
    return fx


def reset(fx=None):
    fx = fx or fixture()
    st, b = call("POST", "/_test/reset", fx)
    assert st == 204, (st, b)
    return {u["handle"]: call("POST", "/auth/login", {"email": u["email"], "password": u["password"]})[1]["token"]
            for u in fx["users"]}


def me(tok, **kw):
    return call("GET", "/me" + (q(**kw) if kw else ""), token=tok)


def stmt(tok, **kw):
    return call("GET", "/statement" + (q(**kw) if kw else ""), token=tok)


def full_stmt(tok, **kw):
    st, first = stmt(tok, limit=200, **kw)
    return st, first


def main():
    # --- reset rules
    fx = fixture()
    fx["payments"][0]["created_at"] = iso(NOW + timedelta(hours=1))
    expect("seeded future created_at -> 422", call("POST", "/_test/reset", fx), 422, "validation_failed")
    T = reset()
    a, b, c, op = T["ada"], T["bob"], T["cy"], T["op"]
    check("loading seeded payments keeps balances", me(a)[1]["balance"] == 10000 and me(b)[1]["balance"] == 2400, "")

    # --- /me as_of
    for bad in ("2026-09-24T13:20:00", "2026-09-24", "", "yesterday", "2026-13-01T00:00:00+00:00"):
        expect("as_of %r -> 422" % bad, me(a, as_of=bad), 422, "validation_failed")
        expect("known_at %r -> 422" % bad, me(a, known_at=bad), 422, "validation_failed")
    weird = (T1 + timedelta(hours=2)).astimezone(timezone(timedelta(hours=2))).isoformat(timespec="seconds")
    st, m = me(a, as_of=weird)
    check("as_of echoed exactly", st == 200 and m.get("as_of") == weird, m)
    check("as_of before earliest -> opening", me(a, as_of=iso(T1 - S))[1]["balance"] == 9300, me(a, as_of=iso(T1 - S))[1])
    check("as_of exactly at payment counts it", me(a, as_of=iso(T1))[1]["balance"] == 8800, "")
    check("as_of between", me(a, as_of=iso(T2 - S))[1]["balance"] == 8800, "")
    check("as_of after latest -> current", me(a, as_of=iso(T3))[1]["balance"] == 10000, "")
    check("as_of future -> current", me(a, as_of=iso(NOW + timedelta(days=400)))[1]["balance"] == 10000, "")
    for t in (T1 - S, T1, T2, T3 - S, T3, NOW):
        tot = sum(me(x, as_of=iso(t))[1]["balance"] for x in (a, b, c, op))
        check("historical sum at %s == 12500" % iso(t), tot == 12500, tot)
    st, m = me(a)
    check("/me without temporal params keeps fields", st == 200 and m["balance"] == m["total"] == 10000, m)

    # --- statements
    st, s = stmt(a)
    ids = [e["payment"]["payment_id"] for e in s["entries"]]
    check("statement own payments only, oldest first", st == 200 and ids == ["p_1", "p_2"], ids)
    check("statement opening/closing/deltas", s["opening_balance"] == 9300 and s["closing_balance"] == 10000 and
          [e["delta"] for e in s["entries"]] == [-500, 1200] and [e["balance_after"] for e in s["entries"]] == [8800, 10000], s)
    check("statement entries carry revision fields", all(k in e for e in s["entries"]
                                                        for k in ("revision", "effective_at", "recorded_at")), s["entries"][:1])
    check("statement snapshot token", isinstance(s.get("snapshot"), str) and s["snapshot"], s.get("snapshot"))
    st, s = stmt(a, **{"from": iso(T1), "to": iso(T2)})
    check("half-open window [T1,T2)", [e["payment"]["payment_id"] for e in s["entries"]] == ["p_1"] and
          s["opening_balance"] == 9300 and s["closing_balance"] == 8800, s)
    st, s = stmt(a, **{"from": iso(T1 + S), "to": iso(T2 + S)})
    check("window [T1+1,T2+1)", [e["payment"]["payment_id"] for e in s["entries"]] == ["p_2"] and
          s["opening_balance"] == 8800 and s["closing_balance"] == 10000, s)
    st, s = stmt(a, limit=1, offset=1)
    check("pagination keeps balances", s["entries"][0]["balance_after"] == 10000 and s["opening_balance"] == 9300
          and s["closing_balance"] == 10000 and s["has_more"] is False, s)
    st, s = stmt(a, limit=1)
    check("first page has_more", s["has_more"] is True and len(s["entries"]) == 1, s)
    st, s = stmt(a, offset=5)
    check("offset beyond end", st == 200 and s["entries"] == [] and s["has_more"] is False, s)
    st, s = stmt(c)
    check("statement excludes public payments of others", [e["payment"]["payment_id"] for e in s["entries"]] == ["p_3"], s)
    for kw in ({"from": "2026-09-24"}, {"to": ""}, {"limit": "0"}, {"offset": "-1"}, {"known_at": "x"}):
        expect("statement bad %s -> 422" % kw, stmt(a, **kw), 422, "validation_failed")
    expect("statement 401", call("GET", "/statement"), 401, "unauthenticated")

    # --- snapshot paging
    st, s0 = stmt(a, limit=1)
    snap = s0["snapshot"]
    call("POST", "/payments", {"to_handle": "cy", "amount": 7}, token=a, key="after-snap")
    st, s1 = stmt(a, snapshot=snap, limit=1, offset=1)
    check("snapshot pages frozen result", st == 200 and [e["payment"]["payment_id"] for e in s1["entries"]] == ["p_2"]
          and s1["closing_balance"] == 10000 and s1["has_more"] is False, s1)
    st, s2 = stmt(a, snapshot=snap, limit=1, offset=2)
    check("snapshot beyond end", st == 200 and s2["entries"] == [] and s2["has_more"] is False, s2)
    for kw in ({"from": iso(T1)}, {"to": iso(T2)}, {"known_at": iso(NOW)}):
        expect("snapshot + %s -> 422" % list(kw)[0], stmt(a, snapshot=snap, **kw), 422, "validation_failed")
    expect("snapshot of another user -> 404", stmt(b, snapshot=snap), 404, "not_found")
    expect("unknown snapshot -> 404", stmt(a, snapshot="nope"), 404, "not_found")
    st, s3 = stmt(a, snapshot=snap, zzz="1")
    check("unknown param ignored with snapshot", st == 200, st)

    # --- corrections
    T = reset()
    a, b, c, op = T["ada"], T["bob"], T["cy"], T["op"]
    body = {"expected_revision": 1, "amount": 400, "effective_at": iso(T1), "reason": "corrected amount"}
    expect("correction no key -> 400", call("POST", "/payments/p_1/corrections", body, token=a), 400, "missing_idempotency_key")
    expect("correction no token -> 401", call("POST", "/payments/p_1/corrections", body, key="k"), 401, "unauthenticated")
    expect("receiver cannot correct -> 403", call("POST", "/payments/p_1/corrections", body, token=b, key="k"), 403, "forbidden")
    expect("third party cannot correct -> 403", call("POST", "/payments/p_1/corrections", body, token=c, key="k"), 403, "forbidden")
    expect("unknown payment -> 404", call("POST", "/payments/nope/corrections", body, token=a, key="k"), 404, "not_found")
    bads = [dict(body, amount=-1), dict(body, amount=1000000001), dict(body, amount="400"), dict(body, amount=1.5),
            dict(body, reason=""), dict(body, reason="x" * 201), dict(body, expected_revision=0),
            dict(body, expected_revision="1"), dict(body, effective_at=iso(NOW + timedelta(hours=1))),
            dict(body, effective_at="2026-09-20T12:00:00"), {k: v for k, v in body.items() if k != "reason"},
            {k: v for k, v in body.items() if k != "effective_at"}, {k: v for k, v in body.items() if k != "amount"},
            {k: v for k, v in body.items() if k != "expected_revision"}]
    for i, bb in enumerate(bads):
        st, x = call("POST", "/payments/p_1/corrections", bb, token=a, key="bad%d" % i)
        check("invalid correction %d -> 422 (or 400 for wrong type)" % i,
              (st == 422 and code(x) == "validation_failed") or (st == 400 and code(x) == "malformed_request"
                                                                  and isinstance(bb.get("expected_revision"), str)), (bb, st, x))
    before_known = iso(datetime.now(timezone.utc))
    time.sleep(1.1)
    st, r2 = call("POST", "/payments/p_1/corrections", body, token=a, key="c1")
    check("correction 201 shape", st == 201 and r2["payment_id"] == "p_1" and r2["revision"] == 2 and r2["amount"] == 400
          and r2["effective_at"] and r2["recorded_at"] and r2["reason"] == "corrected amount", (st, r2))
    check("decrease debits receiver, credits sender", me(a)[1]["balance"] == 10100 and me(b)[1]["balance"] == 2300, "")
    st, rep = call("POST", "/payments/p_1/corrections", body, token=a, key="c1")
    check("correction replay 200 identical", st == 200 and rep == r2, st)
    expect("correction key reuse -> 409", call("POST", "/payments/p_1/corrections", dict(body, reason="other"), token=a, key="c1"),
           409, "idempotency_key_reuse")
    expect("stale revision -> 409", call("POST", "/payments/p_1/corrections", body, token=a, key="c2"), 409, "stale_revision")
    st, rv = call("GET", "/payments/p_1/revisions", token=b)
    revs = rv.get("revisions", []) if isinstance(rv, dict) else []
    check("revisions for receiver", st == 200 and [x["revision"] for x in revs] == [1, 2] and revs[0]["reason"] == ""
          and revs[0]["amount"] == 500 and revs[1]["amount"] == 400, rv)
    expect("revisions third party (public payment) -> 404", call("GET", "/payments/p_1/revisions", token=c), 404, "not_found")
    expect("revisions no token -> 401", call("GET", "/payments/p_1/revisions"), 401, "unauthenticated")
    st, act = call("GET", "/activity?limit=200", token=a)
    p1 = [p for p in act["payments"] if p["payment_id"] == "p_1"]
    check("activity shows original payment once", len(p1) == 1 and p1[0]["amount"] == 500 and len(act["payments"]) == 3, p1)
    st, s = stmt(a)
    e1 = [e for e in s["entries"] if e["payment"]["payment_id"] == "p_1"]
    check("statement uses corrected revision once", len(e1) == 1 and e1[0]["payment"]["amount"] == 400 and e1[0]["delta"] == -400
          and e1[0]["revision"] == 2 and s["opening_balance"] == 9300 and s["closing_balance"] == 10100, s)
    st, s = stmt(a, known_at=before_known)
    e1 = [e for e in s["entries"] if e["payment"]["payment_id"] == "p_1"]
    check("known_at before correction -> revision 1", e1 and e1[0]["revision"] == 1 and e1[0]["delta"] == -500 and
          s["closing_balance"] == 10000 and s.get("known_at") == before_known, s)
    check("me known_at before correction", me(a, known_at=before_known)[1]["balance"] == 10000, "")
    check("me known_at before seeded/reset? future known_at ok", me(a, known_at=iso(NOW + timedelta(days=1)))[0] == 200, "")
    check("opening unchanged by correction", me(a, as_of=iso(T1 - S))[1]["balance"] == 9300, "")
    for t in (T1 - S, T1, T2, NOW):
        tot = sum(me(x, as_of=iso(t))[1]["balance"] for x in (a, b, c, op))
        check("historical sum after correction at %s" % iso(t), tot == 12500, tot)

    # move effective time: p_1 corrected to effective after T2
    st, r3 = call("POST", "/payments/p_1/corrections", {"expected_revision": 2, "amount": 400, "effective_at": iso(T2 + S),
                                                         "reason": "later"}, token=a, key="c3")
    check("correction moving effective time 201", st == 201 and r3["revision"] == 3, (st, r3))
    st, s = stmt(a, **{"from": iso(T1), "to": iso(T2 + S)})
    check("correction moves payment out of window", [e["payment"]["payment_id"] for e in s["entries"]] == ["p_2"], s)
    st, s = stmt(a)
    check("ordering by effective_at", [e["payment"]["payment_id"] for e in s["entries"]] == ["p_2", "p_1"], s)

    # insufficient / historical overdraft / zero
    big = {"expected_revision": 1, "amount": 1200 + 2400 + 1, "effective_at": iso(T2), "reason": "bigger"}
    bal_b = me(b)[1]["balance"]
    expect("increase beyond current balance -> insufficient_funds",
           call("POST", "/payments/p_2/corrections", big, token=b, key="i1"), 409, "insufficient_funds")
    # bob opening 3200; move p_2 (1200) before T1 and raise to 3300 -> negative before p_1 credit
    st, rv = call("GET", "/payments/p_2/revisions", token=b)
    od = {"expected_revision": 1, "amount": 3300, "effective_at": iso(T1 - timedelta(days=1)), "reason": "earlier"}
    st, x = call("POST", "/payments/p_2/corrections", od, token=b, key="h1")
    check("historical overdraft -> 409", st == 409 and code(x) == "historical_overdraft", (st, x))
    check("failure changes nothing", me(b)[1]["balance"] == bal_b and
          len(call("GET", "/payments/p_2/revisions", token=b)[1]["revisions"]) == 1, "")
    st, z = call("POST", "/payments/p_2/corrections", {"expected_revision": 1, "amount": 0, "effective_at": iso(T2),
                                                        "reason": "reversal"}, token=b, key="z1")
    check("zero-amount reversal 201", st == 201 and z["amount"] == 0, (st, z))
    st, s = stmt(a)
    e2 = [e for e in s["entries"] if e["payment"]["payment_id"] == "p_2"]
    check("zero revision appears with zero delta", e2 and e2[0]["delta"] == 0, s)
    tot = sum(me(x)[1]["balance"] for x in (a, b, c, op))
    check("current sum preserved", tot == 12500, tot)

    # concurrent corrections with the same expected revision
    st, pz = call("POST", "/payments", {"to_handle": "cy", "amount": 50}, token=a, key="pz")
    time.sleep(1.1)
    def corr(i):
        return call("POST", "/payments/%s/corrections" % pz["payment_id"],
                    {"expected_revision": 1, "amount": 40 - i % 3, "effective_at": pz["created_at"], "reason": "r%d" % i},
                    token=a, key="cc%d" % i)[0]
    with ThreadPoolExecutor(20) as ex:
        res = list(ex.map(corr, range(20)))
    check("concurrent same expected_revision: exactly one 201", res.count(201) == 1 and res.count(409) == 19, sorted(set(res)))

    # snapshot frozen across corrections
    st, s0 = stmt(a, limit=1)
    snap = s0["snapshot"]
    st, full0 = stmt(a, snapshot=snap, limit=200)
    time.sleep(1.1)
    st, rv = call("GET", "/payments/%s/revisions" % pz["payment_id"], token=a)
    last = rv["revisions"][-1]["revision"]
    call("POST", "/payments/%s/corrections" % pz["payment_id"], {"expected_revision": last, "amount": 1,
         "effective_at": pz["created_at"], "reason": "again"}, token=a, key="after-snap-corr")
    st, full1 = stmt(a, snapshot=snap, limit=200)
    check("snapshot unchanged after correction", full0 == full1, "")
    T = reset()
    expect("snapshot from before reset -> 404", stmt(T["ada"], snapshot=snap), 404, "not_found")

    # settlement members and captures are immutable
    a, b, c, op = T["ada"], T["bob"], T["cy"], T["op"]
    st, se = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]},
                  token=op, key="s")
    pid = se["payments"][0]["payment_id"]
    expect("settlement member correction -> 422 linked_payment_immutable",
           call("POST", "/payments/%s/corrections" % pid, {"expected_revision": 1, "amount": 5, "effective_at": se["committed_at"],
                                                           "reason": "x"}, token=a, key="sc"), 422, "linked_payment_immutable")
    st, rv = call("GET", "/payments/%s/revisions" % pid, token=a)
    check("settlement member revision 1 uses committed_at", st == 200 and rv["revisions"][0]["effective_at"] == se["committed_at"]
          and rv["revisions"][0]["recorded_at"] == se["committed_at"], rv)
    st, au = call("POST", "/authorizations", {"to_handle": "bob", "amount": 300}, token=a, key="au")
    st, cp = call("POST", "/authorizations/%s/capture" % au["authorization_id"], {}, token=b, key="cp")
    expect("capture correction -> 422 linked_payment_immutable",
           call("POST", "/payments/%s/corrections" % cp["payment_id"], {"expected_revision": 1, "amount": 5,
                "effective_at": cp["created_at"], "reason": "x"}, token=a, key="cpc"), 422, "linked_payment_immutable")
    st, s = stmt(b)
    check("capture appears once in statement", [e["payment"]["payment_id"] for e in s["entries"]].count(cp["payment_id"]) == 1, s)
    st, al = call("GET", "/authorizations", token=a)
    x = [z for z in al["authorizations"] if z["authorization_id"] == au["authorization_id"]][0]
    check("closed authorization exposes closed_at", x.get("closed_at") is not None and x["status"] == "captured", x)

    # historical holds
    hold_created = NOW - timedelta(days=2)
    fx = fixture(authorizations=[{"id": "a_h", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "",
                                  "visibility": "public", "status": "open", "created_at": iso(hold_created),
                                  "expires_at": iso(NOW + timedelta(hours=2))}])
    T = reset(fx)
    a = T["ada"]
    m0 = me(a, as_of=iso(hold_created - S))[1]
    m1 = me(a, as_of=iso(hold_created + S))[1]
    m2 = me(a, as_of=iso(NOW + timedelta(days=1)))[1]
    check("hold absent before creation", m0["held"] == 0 and m0["available"] == m0["total"] == m0["balance"], m0)
    check("hold present after creation", m1["held"] == 2000 and m1["available"] == m1["total"] - 2000, m1)
    check("hold expired in the future view", m2["held"] == 0 and m2["available"] == m2["total"], m2)
    st, al = call("GET", "/authorizations", token=a)
    check("open authorization closed_at null", al["authorizations"][0].get("closed_at", "MISSING") is None, al)
    st, s = stmt(a)
    check("holds are not statement entries", all(e["payment"]["payment_id"] in ("p_1", "p_2") for e in s["entries"]), s)

    fails = [r for r in RESULTS if not r[1]]
    for name, ok, det in RESULTS:
        print("%s  %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else "  -> %s" % (det,)))
    print("%d probes, %d failed" % (len(RESULTS), len(fails)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
