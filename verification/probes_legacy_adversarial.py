#!/usr/bin/env python3
"""Reviewer's adversarial timing probe for the stage-4 legacy-snapshot import (run contract: 5 s per request, 10 s
control calls; §10: an invalid state gives 422 with the destination unchanged, not a timeout; stage 4: exports of
stages 1-3 import, retaining snapshots).

Two ledger shapes defeat a balance-based screen of candidate moments, because many moments give the same balances:
  E1  same-amount back-dated corrections: K statements, then N corrections of one payment that keep its amount.
  E2  closed-window same-instant swap: two payments at one instant inside a closed past window, a statement of that
      window, then N later payments outside it; the tamper swaps the two same-instant entries (balances recomputed).
For each shape the genuine export must import (204, original pages) and the tampered export must be refused (422,
destination unchanged), each inside 5 s. SRC is a real older stage-3 service (495d5d6), DST is stage 4.

Usage: python3 probes_legacy_adversarial.py http://DST http://SRC [N=5000] [K=20]
"""
import copy
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

DST, SRC = sys.argv[1].rstrip("/"), sys.argv[2].rstrip("/")
N = int(sys.argv[3]) if len(sys.argv) > 3 else 5000
K = int(sys.argv[4]) if len(sys.argv) > 4 else 20
RESULTS = []


def call(base, m, p, body=None, tok=None, key=None, timeout=120):
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if tok:
        h["Authorization"] = "Bearer " + tok
    if key:
        h["Idempotency-Key"] = key
    r = urllib.request.Request(base + p, data=None if body is None else json.dumps(body).encode(), method=m, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as x:
            t = x.read()
            return x.status, (json.loads(t) if t else None)
    except urllib.error.HTTPError as e:
        t = e.read()
        try:
            return e.code, (json.loads(t) if t else None)
        except ValueError:
            return e.code, t[:200]


def check(n, c, d=""):
    RESULTS.append((n, bool(c), d))


def login(base, who):
    return call(base, "POST", "/auth/login", {"email": who + "@x.io", "password": "password"})[1]["token"]


def page(base, tok, snap):
    st, b = call(base, "GET", "/statement?limit=100&snapshot=" + snap, None, tok)
    if st != 200 or "entries" not in b:
        return ("NOT A PAGE", st, b)
    for e in b["entries"]:
        e["payment"].pop("refund_of", None)
    return b


def timed_import(body):
    t = time.time()
    st, b = call(DST, "POST", "/_test/import", body)
    return st, b, time.time() - t


def judge(name, ex, pages, owner, tamper):
    st, b, dt = timed_import(ex)
    check("%s: genuine imports (204)" % name, st == 204, (st, b))
    check("%s: genuine import within 5 s" % name, dt < 5, "%.2fs" % dt)
    print("%s: genuine %s in %.2fs" % (name, st, dt))
    if st == 204:
        tok = login(DST, owner)
        same = all(page(DST, tok, s) == p for s, p in pages.items())
        check("%s: every original page retained" % name, same, "")
    base = call(DST, "GET", "/_test/export")[1]
    bad = copy.deepcopy(ex)
    tamper(bad)
    st, b, dt = timed_import(bad)
    check("%s: tampered refused (422)" % name, st == 422, (st, b))
    check("%s: tampered refused within 5 s" % name, dt < 5, "%.2fs" % dt)
    check("%s: tampered leaves destination unchanged" % name, call(DST, "GET", "/_test/export")[1] == base, "")
    print("%s: tampered %s in %.2fs" % (name, st, dt))


NOW = datetime.now(timezone.utc).replace(microsecond=0)
T1 = NOW - timedelta(days=4)
USERS = [{"id": "u_a", "email": "a@x.io", "password": "password", "display_name": "A", "handle": "a", "balance": 10 ** 7},
         {"id": "u_b", "email": "b@x.io", "password": "password", "display_name": "B", "handle": "b", "balance": 10 ** 7}]

# ---- E1 same-amount back-dated corrections -----------------------------------------------------------
fx = {"currency": "EUR", "minor_units": 2, "users": USERS, "requests": [],
      "payments": [{"id": "p_x", "from_user_id": "u_a", "to_user_id": "u_b", "amount": 300, "note": "", "visibility": "public",
                    "created_at": T1.isoformat()},
                   {"id": "p_y", "from_user_id": "u_b", "to_user_id": "u_a", "amount": 70, "note": "", "visibility": "public",
                    "created_at": (T1 + timedelta(hours=2)).isoformat()}]}
check("E1 source reset", call(SRC, "POST", "/_test/reset", fx)[0] == 204, "")
ta = login(SRC, "a")
pages = {}
qs = ["", "&from=" + urllib.parse.quote((T1 - timedelta(hours=1)).isoformat()),
      "&known_at=" + urllib.parse.quote((NOW + timedelta(days=1)).isoformat()),
      "&from=" + urllib.parse.quote((T1 - timedelta(hours=1)).isoformat()) + "&to=" + urllib.parse.quote((T1 + timedelta(hours=1)).isoformat())]
for i in range(K):
    s = call(SRC, "GET", "/statement?limit=1" + qs[i % len(qs)], None, ta)[1]
    pages[s["snapshot"]] = page(SRC, ta, s["snapshot"])
t = time.time()
ok = 0
for i in range(N):
    st, b = call(SRC, "POST", "/payments/p_x/corrections", {"expected_revision": i + 1, "amount": 300,
                 "effective_at": (T1 - timedelta(minutes=1)).isoformat() if i % 2 else T1.isoformat(), "reason": "same"},
                 ta, "e1c%d" % i)
    ok += st == 201
check("E1 %d same-amount corrections on the source" % N, ok == N, "%d ok, %.1fs" % (ok, time.time() - t))


def e1_tamper(bad):
    sn = [s for s in bad["state"]["snapshots"] if s["entries"]][-1]
    sn["opening_balance"] += 1
    sn["closing_balance"] += 1
    for e in sn["entries"]:
        e[3] += 1


judge("E1 %d same-amount corrections x %d snapshots" % (N, K), call(SRC, "GET", "/_test/export")[1], pages, "a", e1_tamper)

# ---- E2 closed-window same-instant swap ---------------------------------------------------------------
fx = {"currency": "EUR", "minor_units": 2, "users": USERS, "requests": [],
      "payments": [{"id": "p_1", "from_user_id": "u_a", "to_user_id": "u_b", "amount": 300, "note": "", "visibility": "public",
                    "created_at": T1.isoformat()},
                   {"id": "p_2", "from_user_id": "u_b", "to_user_id": "u_a", "amount": 120, "note": "", "visibility": "public",
                    "created_at": T1.isoformat()}]}
check("E2 source reset", call(SRC, "POST", "/_test/reset", fx)[0] == 204, "")
ta = login(SRC, "a")
win = "&from=" + urllib.parse.quote((T1 - timedelta(hours=1)).isoformat()) + "&to=" + urllib.parse.quote((T1 + timedelta(hours=1)).isoformat())
pages = {}
for i in range(max(1, K // 4)):
    s = call(SRC, "GET", "/statement?limit=1" + win, None, ta)[1]
    pages[s["snapshot"]] = page(SRC, ta, s["snapshot"])
check("E2 window holds the two same-instant entries", len(list(pages.values())[0]["entries"]) == 2, list(pages.values())[0])
t = time.time()
for i in range(N):
    call(SRC, "POST", "/payments", {"to_handle": "b", "amount": 1}, ta, "e2p%d" % i)
check("E2 %d later out-of-window payments on the source" % N, True, "%.1fs" % (time.time() - t))


def e2_tamper(bad):
    for sn in bad["state"]["snapshots"]:
        if len(sn["entries"]) == 2:
            sn["entries"].reverse()
            run = sn["opening_balance"]
            for e in sn["entries"]:
                run += e[2]
                e[3] = run


judge("E2 closed-window swap, %d later facts, %d snapshots" % (N, len(pages)), call(SRC, "GET", "/_test/export")[1], pages, "a", e2_tamper)

fails = [r for r in RESULTS if not r[1]]
for n, ok, d in RESULTS:
    print("%s  %s%s" % ("PASS" if ok else "FAIL", n, "" if ok else "  -> %s" % (json.dumps(d, default=str)[:600],)))
print("%d probes, %d failed" % (len(RESULTS), len(fails)))
sys.exit(1 if fails else 0)
