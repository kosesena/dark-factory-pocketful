#!/usr/bin/env python3
"""Reviewer's legacy-snapshot sweep for stage 3+ (§10 "missing fields ... or an invalid state give 422
validation_failed without changing the destination"; stage 3 "pages that exact result"; stage 4
"a stage-4 service must accept exports produced by the same team's stages 1-3, retaining ... snapshots").

A saved statement whose metadata (taken_ts/taken_seq, and view on stage 4) is removed must still be
judged as strictly as a complete one: every corruption is 422 with the destination unchanged. On
stage 4 the ledger also holds a refund, and a statement that pages the refund is stripped of its
metadata: the import must either refuse it or page the refund exactly as the genuine statement did
(refund_of naming its target); a refund cannot appear in a statement taken before stage 4.

Usage: python3 probes_legacy_snapshots.py http://localhost:8080
"""
import copy
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

B = sys.argv[1].rstrip("/")
RESULTS = []
META = ("taken_ts", "taken_seq", "view")


def call(m, p, body=None, tok=None, key=None):
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
T1 = NOW - timedelta(days=4)
U = [{"id": "u_a", "email": "a@x.io", "password": "password", "display_name": "A", "handle": "a", "balance": 5000},
     {"id": "u_b", "email": "b@x.io", "password": "password", "display_name": "B", "handle": "b", "balance": 1000}]
fx = {"currency": "EUR", "minor_units": 2, "users": U, "requests": [],
      "payments": [{"id": "p_s1", "from_user_id": "u_b", "to_user_id": "u_a", "amount": 300, "note": "n1",
                    "visibility": "public", "created_at": T1.isoformat()},
                   {"id": "p_s2", "from_user_id": "u_a", "to_user_id": "u_b", "amount": 50, "note": "", "visibility": "public",
                    "created_at": (T1 + timedelta(hours=5)).isoformat()}]}
st, _ = call("POST", "/_test/reset", fx)
check("reset", st == 204, st)
ta = call("POST", "/auth/login", {"email": "a@x.io", "password": "password"})[1]["token"]
call("POST", "/payments", {"to_handle": "b", "amount": 100}, ta, "k1")
time.sleep(1.1)
call("POST", "/payments/p_s1/corrections", {"expected_revision": 1, "amount": 250, "effective_at": T1.isoformat(),
                                             "reason": "x"}, ta, "c1")
st, rf = call("POST", "/payments/p_s1/refunds", {"amount": 70}, ta, "r1")
STAGE4 = st == 201
check("stage-4 refund set-up (or stage 3: route absent)", st in (201, 404), (st, rf))
time.sleep(1.1)
st, s_full = call("GET", "/statement?limit=1", None, ta)
st, s_win = call("GET", "/statement?limit=1&from=" + (T1 - timedelta(hours=1)).isoformat().replace("+", "%2B"), None, ta)
pages = {s["snapshot"]: call("GET", "/statement?limit=200&snapshot=" + s["snapshot"], None, ta)[1] for s in (s_full, s_win)}
if STAGE4:
    refund_entries = [e for e in pages[s_full["snapshot"]]["entries"] if e["payment"].get("refund_of")]
    check("genuine statement pages the refund with refund_of", len(refund_entries) == 1, pages[s_full["snapshot"]])
ex = call("GET", "/_test/export")[1]
base = ex
check("export has saved statements", len(ex["state"].get("snapshots", [])) >= 2, "")


def stripped(keys=META):
    bad = copy.deepcopy(ex)
    for s in bad["state"]["snapshots"]:
        for k in keys:
            s.pop(k, None)
    return bad


def target(state):
    return max(state["snapshots"], key=lambda s: len(s["entries"]))


def tamper(name, fn, keys=META):
    bad = stripped(keys)
    fn(target(bad["state"]))
    st, b = call("POST", "/_test/import", bad)
    check("legacy tamper %s -> 422" % name, st == 422 and (b or {}).get("error", {}).get("code") == "validation_failed", (st, b))
    check("legacy tamper %s leaves destination unchanged" % name, call("GET", "/_test/export")[1] == base, "")


def drop_last(s):
    e = s["entries"].pop()
    s["closing_balance"] -= e[2]


def clear(s):
    s["entries"] = []
    s["closing_balance"] = s["opening_balance"]


def shift(s):
    s["opening_balance"] += 1
    s["closing_balance"] += 1
    for e in s["entries"]:
        e[3] += 1


def drop_first(s):
    e = s["entries"].pop(0)
    s["opening_balance"] += e[2]


tamper("drop last entry, closing adjusted", drop_last)
tamper("clear entries, closing = opening", clear)
tamper("shift all balances +1", shift)
tamper("drop first entry, opening adjusted", drop_first)
tamper("owner swapped", lambda s: s.__setitem__("user_id", "u_b"))
tamper("entries reversed", lambda s: s["entries"].reverse())
tamper("drop last entry, closing adjusted (only taken_* removed)", drop_last, keys=("taken_ts", "taken_seq"))

if STAGE4:
    rid = refund_entries[0]["payment"]["payment_id"]
    for keys, label in ((("view",), "view removed"), (META, "all metadata removed")):
        bad = stripped(keys)
        st, b = call("POST", "/_test/import", bad)
        if st == 422:
            check("refund-bearing statement, %s -> refused 422 unchanged" % label,
                  call("GET", "/_test/export")[1] == base, "")
            continue
        page = call("GET", "/statement?limit=200&snapshot=" + s_full["snapshot"], None, ta)[1]
        got = [e["payment"].get("refund_of", "<absent>") for e in page["entries"] if e["payment"]["payment_id"] == rid]
        check("refund-bearing statement, %s: imported (%s) pages the refund with refund_of=p_s1" % (label, st),
              got == ["p_s1"], "refund entry refund_of = %r" % (got,))
        call("POST", "/_test/import", ex)

fails = [r for r in RESULTS if not r[1]]
for n, ok, d in RESULTS:
    print("%s  %s%s" % ("PASS" if ok else "FAIL", n, "" if ok else "  -> %s" % (d,)))
print("%d probes, %d failed" % (len(RESULTS), len(fails)))
sys.exit(1 if fails else 0)
