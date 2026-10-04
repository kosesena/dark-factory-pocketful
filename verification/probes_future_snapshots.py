#!/usr/bin/env python3
"""Reviewer's future-instant snapshot probes (stage 3+): statements taken with future known_at,
future from/to windows (and a past known_at) must stay frozen across later payments, corrections
and holds, survive export -> import unchanged, and page their original result. Imported
snapshots claiming to be taken after the ledger (huge taken_seq, far-future taken_ts) give 422.

Usage: python3 probes_future_snapshots.py http://localhost:8080
"""
import copy
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

B = sys.argv[1].rstrip("/")
RESULTS = []


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
T1 = NOW - timedelta(days=3)
U = [{"id": "u_a", "email": "a@x.io", "password": "password", "display_name": "A", "handle": "a", "balance": 5000},
     {"id": "u_b", "email": "b@x.io", "password": "password", "display_name": "B", "handle": "b", "balance": 1000}]
call("POST", "/_test/reset", {"currency": "EUR", "minor_units": 2, "users": U, "requests": [],
                              "payments": [{"id": "p_s", "from_user_id": "u_b", "to_user_id": "u_a", "amount": 300, "note": "",
                                            "visibility": "public", "created_at": T1.isoformat()}]})
ta, tb = [call("POST", "/auth/login", {"email": u["email"], "password": "password"})[1]["token"] for u in U]
st, p1 = call("POST", "/payments", {"to_handle": "b", "amount": 100}, ta, "p1")
future = "2090-01-01T00:00:00+00:00"
queries = {"future known_at": {"known_at": future},
           "future from": {"from": (NOW + timedelta(days=30)).isoformat()},
           "future to": {"to": (NOW + timedelta(days=365)).isoformat()},
           "window + future known_at": {"from": (T1 - timedelta(days=1)).isoformat(), "to": future, "known_at": future},
           "past known_at": {"known_at": (T1 + timedelta(hours=1)).isoformat()},
           "default": {}}
snaps = {}
for name, q in queries.items():
    st, s = call("GET", "/statement?" + urllib.parse.urlencode(dict(q, limit=1)), None, ta)
    check("%s: statement 200 with snapshot" % name, st == 200 and s.get("snapshot"), (st, s))
    snaps[name] = (s["snapshot"], call("GET", "/statement?limit=200&snapshot=" + s["snapshot"], None, ta)[1])
# later activity: payment, correction, hold, capture
time.sleep(1.1)
call("POST", "/payments", {"to_handle": "b", "amount": 7}, ta, "p2")
call("POST", "/payments/%s/corrections" % p1["payment_id"], {"expected_revision": 1, "amount": 80,
     "effective_at": p1["created_at"], "reason": "x"}, ta, "c1")
st, au = call("POST", "/authorizations", {"to_handle": "b", "amount": 50}, ta, "au")
call("POST", "/authorizations/%s/capture" % au["authorization_id"], {"amount": 20, "final": False}, tb, "cp")
for name, (tok, page) in snaps.items():
    check("%s: frozen after later activity" % name, call("GET", "/statement?limit=200&snapshot=" + tok, None, ta)[1] == page, "")
st, ex = call("GET", "/_test/export")
st, _ = call("POST", "/_test/import", ex)
check("export with future-instant snapshots imports", st == 204, (st, _))
for name, (tok, page) in snaps.items():
    check("%s: identical after export/import" % name, call("GET", "/statement?limit=200&snapshot=" + tok, None, ta)[1] == page, "")
st, ex2 = call("GET", "/_test/export")
check("re-export imports again", call("POST", "/_test/import", ex2)[0] == 204, "")
base = call("GET", "/_test/export")[1]
for name, fn in (("taken_seq 10^9", lambda s: s.__setitem__("taken_seq", 10 ** 9)),
                 ("taken_ts far future", lambda s: s.__setitem__("taken_ts", s["taken_ts"] + 10 * 365 * 86400))):
    bad = copy.deepcopy(ex)
    sn = bad["state"].get("snapshots")
    if not isinstance(sn, list) or not sn:
        check("applicable: " + name, False, "no snapshots in export")
        continue
    fn(sn[0])
    st, b = call("POST", "/_test/import", bad)
    check("%s -> 422" % name, st == 422, (st, b))
    check("%s leaves destination unchanged" % name, call("GET", "/_test/export")[1] == base, "")

fails = [r for r in RESULTS if not r[1]]
for n, ok, d in RESULTS:
    print("%s  %s%s" % ("PASS" if ok else "FAIL", n, "" if ok else "  -> %s" % (d,)))
print("%d probes, %d failed" % (len(RESULTS), len(fails)))
sys.exit(1 if fails else 0)
