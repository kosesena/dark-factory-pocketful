#!/usr/bin/env python3
"""Reviewer's import probes for stages 3-4: upgrade imports from earlier-stage exports (settlement
membership, corrections, snapshots, holds), snapshot survival across export/import, and tamper
cases (exact instants, historical validity) that must give 422 with the destination unchanged.

Usage: python3 probes_import34.py <target-base> <stage1-base> <stage2-base> [<stage3-base>]
"""
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

TGT, S1, S2 = sys.argv[1], sys.argv[2], sys.argv[3]
S3 = sys.argv[4] if len(sys.argv) > 4 else None
RESULTS = []


def call(B, m, p, body=None, tok=None, key=None):
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if tok:
        h["Authorization"] = "Bearer " + tok
    if key:
        h["Idempotency-Key"] = key
    r = urllib.request.Request(B + p, data=None if body is None else json.dumps(body).encode(), method=m, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=20) as x:
            t = x.read()
            return x.status, (json.loads(t) if t else None)
    except urllib.error.HTTPError as e:
        t = e.read()
        return e.code, (json.loads(t) if t else None)


def check(n, c, d=""):
    RESULTS.append((n, bool(c), d))


NOW = datetime.now(timezone.utc).replace(microsecond=0)
U = [{"id": "u_a", "email": "a@x.io", "password": "password", "display_name": "A", "handle": "a", "balance": 5000},
     {"id": "u_b", "email": "b@x.io", "password": "password", "display_name": "B", "handle": "b", "balance": 1000},
     {"id": "u_op", "email": "o@x.io", "password": "password", "display_name": "O", "handle": "op", "balance": 0}]


def fx():
    return {"currency": "EUR", "minor_units": 2, "users": U, "requests": [], "settlement_operator_ids": ["u_op"],
            "payments": [{"id": "p_s", "from_user_id": "u_b", "to_user_id": "u_a", "amount": 300, "note": "", "visibility": "public",
                          "created_at": (NOW - timedelta(days=3)).isoformat()}]}


def login(B):
    return [call(B, "POST", "/auth/login", {"email": u["email"], "password": "password"})[1]["token"] for u in U]


def snapshot_state(B, toks):
    return [call(B, "GET", "/me", None, t)[1] for t in toks]


for B, name in ((S1, "stage-1"), (S2, "stage-2")) + (((S3, "stage-3"),) if S3 else ()):
    call(B, "POST", "/_test/reset", fx())
    ta, tb, to = login(B)
    st, p = call(B, "POST", "/payments", {"to_handle": "b", "amount": 100}, ta, "k1")
    st, se = call(B, "POST", "/settlements", {"transfers": [{"from_handle": "a", "to_handle": "b", "amount": 10},
                                                            {"from_handle": "b", "to_handle": "a", "amount": 4}]}, to, "s1")
    cap = corr = snap = page = None
    if name != "stage-1":
        st, au = call(B, "POST", "/authorizations", {"to_handle": "b", "amount": 500}, ta, "au")
        st, cap = call(B, "POST", "/authorizations/%s/capture" % au["authorization_id"], {"amount": 200, "final": False}, tb, "cp")
    if name == "stage-3":
        time.sleep(1.1)
        st, corr = call(B, "POST", "/payments/%s/corrections" % p["payment_id"],
                        {"expected_revision": 1, "amount": 60, "effective_at": p["created_at"], "reason": "x"}, ta, "c1")
        st, s0 = call(B, "GET", "/statement?limit=1", None, ta)
        snap = s0["snapshot"]
        page = call(B, "GET", "/statement?limit=200&snapshot=" + snap, None, ta)[1]
    before = snapshot_state(B, (ta, tb, to))
    st, ex = call(B, "GET", "/_test/export")
    st, _ = call(TGT, "POST", "/_test/import", ex)
    check("%s export imports" % name, st == 204, st)
    check("%s balances/tokens kept" % name, [(m["balance"]) for m in snapshot_state(TGT, (ta, tb, to))] == [m["balance"] for m in before], "")
    check("%s payment replay" % name, call(TGT, "POST", "/payments", {"to_handle": "b", "amount": 100}, ta, "k1") == (200, p), "")
    check("%s settlement replay" % name, call(TGT, "POST", "/settlements", {"transfers": [{"from_handle": "a", "to_handle": "b", "amount": 10},
          {"from_handle": "b", "to_handle": "a", "amount": 4}]}, to, "s1") == (200, se), "")
    m1 = se["payments"][0]["payment_id"]
    st, x = call(TGT, "POST", "/correction-batches", {"corrections": [{"payment_id": m1, "expected_revision": 1, "amount": 0,
                 "effective_at": se["committed_at"], "reason": "r"}]}, to, "inc")
    if st != 404:  # stage-3 targets have no batches; stage-4 must keep membership
        check("%s settlement membership kept (incomplete)" % name, st == 422 and x["error"]["code"] == "incomplete_settlement", (st, x))
    if cap:
        st, x = call(TGT, "POST", "/payments/%s/corrections" % cap["payment_id"], {"expected_revision": 1, "amount": 5,
                     "effective_at": cap["created_at"], "reason": "x"}, ta, "cc")
        check("%s capture immutable after import" % name, st == 422 and x["error"]["code"] == "linked_payment_immutable", (st, x))
        check("%s holds kept" % name, call(TGT, "GET", "/me", None, ta)[1]["held"] == 300, "")
    if corr:
        st, rv = call(TGT, "GET", "/payments/%s/revisions" % p["payment_id"], None, ta)
        check("%s corrections kept" % name, st == 200 and [r["amount"] for r in rv["revisions"]] == [100, 60], rv)
        check("%s correction replay" % name, call(TGT, "POST", "/payments/%s/corrections" % p["payment_id"], {"expected_revision": 1,
              "amount": 60, "effective_at": p["created_at"], "reason": "x"}, ta, "c1") == (200, corr), "")
        st, pg = call(TGT, "GET", "/statement?limit=200&snapshot=" + snap, None, ta)
        check("%s snapshot kept" % name, st == 200 and pg == page, (st, str(pg)[:200]))
    st, ex2 = call(TGT, "GET", "/_test/export")
    check("%s re-export re-imports" % name, call(TGT, "POST", "/_test/import", ex2)[0] == 204, "")

# tamper cases on the target's own export
call(TGT, "POST", "/_test/reset", fx())
ta, tb, to = login(TGT)
st, p = call(TGT, "POST", "/payments", {"to_handle": "b", "amount": 100}, ta, "t1")
time.sleep(1.1)
call(TGT, "POST", "/payments/%s/corrections" % p["payment_id"], {"expected_revision": 1, "amount": 90,
     "effective_at": p["created_at"], "reason": "x"}, ta, "t2")
call(TGT, "GET", "/statement", None, ta)
st, ex = call(TGT, "GET", "/_test/export")
blob = json.dumps(ex)
st, _ = call(TGT, "POST", "/_test/import", json.loads(blob))
check("own export imports", st == 204, st)
before = snapshot_state(TGT, (ta, tb, to))


def tamper(name, fn):
    st0, cur = call(TGT, "GET", "/_test/export")
    bad = json.loads(blob)
    try:
        ok = fn(bad["state"])
    except Exception as e:
        check("tamper applicable: " + name, False, repr(e))
        return
    if ok is False:
        check("tamper applicable: " + name, False, "field not found")
        return
    st, b = call(TGT, "POST", "/_test/import", bad)
    check("tamper %s -> 422" % name, st == 422, (st, b))
    st1, after = call(TGT, "GET", "/_test/export")
    check("tamper %s leaves destination unchanged" % name, after == cur, "")


def walk(o, pred, act):
    found = False
    if isinstance(o, dict):
        for k in list(o):
            if pred(k, o[k]):
                act(o, k)
                found = True
            else:
                found = walk(o[k], pred, act) or found
    elif isinstance(o, list):
        for x in o:
            found = walk(x, pred, act) or found
    return found


tamper("naive recorded_at", lambda s: walk(s, lambda k, v: k == "recorded_at" and isinstance(v, str),
                                           lambda o, k: o.__setitem__(k, o[k][:19])))
tamper("non-string effective_at", lambda s: walk(s, lambda k, v: k == "effective_at" and isinstance(v, str),
                                                 lambda o, k: o.__setitem__(k, 12345)))
tamper("negative opening balance", lambda s: walk(s, lambda k, v: k in ("opening", "opening_balance") and isinstance(v, int),
                                                  lambda o, k: o.__setitem__(k, -10_000_000)))
check("destination still matches after tampers", snapshot_state(TGT, (ta, tb, to)) == before, "")

fails = [r for r in RESULTS if not r[1]]
for n, ok, d in RESULTS:
    print("%s  %s%s" % ("PASS" if ok else "FAIL", n, "" if ok else "  -> %s" % (d,)))
print("%d probes, %d failed" % (len(RESULTS), len(fails)))
sys.exit(1 if fails else 0)
