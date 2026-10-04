#!/usr/bin/env python3
"""Reviewer's snapshot tamper sweep for stage 3+ (§10 "an invalid state gives 422 without changing
the destination"; stage 3 "pages that exact result"). Builds a ledger with corrections and saved
statements, exports it, applies one corruption at a time to the saved statements and expects
422 with the destination unchanged; the genuine export must import and page identically.

The mutations target this implementation's export layout (state.snapshots[*]: entries as
[payment_id, revision, delta, balance_after, effective_at, recorded_at, amount], echo, taken_*);
a mutation that cannot be applied is reported as not applicable.

Usage: python3 probes_snapshot_tamper.py http://localhost:8080
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
T1 = NOW - timedelta(days=4)
U = [{"id": "u_a", "email": "a@x.io", "password": "password", "display_name": "A", "handle": "a", "balance": 5000},
     {"id": "u_b", "email": "b@x.io", "password": "password", "display_name": "B", "handle": "b", "balance": 1000}]
fx = {"currency": "EUR", "minor_units": 2, "users": U, "requests": [],
      "payments": [{"id": "p_s1", "from_user_id": "u_b", "to_user_id": "u_a", "amount": 300, "note": "", "visibility": "public",
                    "created_at": T1.isoformat()},
                   {"id": "p_s2", "from_user_id": "u_a", "to_user_id": "u_b", "amount": 50, "note": "", "visibility": "public",
                    "created_at": (T1 + timedelta(hours=5)).isoformat()}]}
st, _ = call("POST", "/_test/reset", fx)
ta = call("POST", "/auth/login", {"email": "a@x.io", "password": "password"})[1]["token"]
call("POST", "/payments", {"to_handle": "b", "amount": 100}, ta, "k1")
time.sleep(1.1)
call("POST", "/payments/p_s1/corrections", {"expected_revision": 1, "amount": 250, "effective_at": T1.isoformat(), "reason": "x"}, ta, "c1")
known = datetime.now(timezone.utc).isoformat()
time.sleep(1.1)
call("POST", "/payments/p_s2/corrections", {"expected_revision": 1, "amount": 40, "effective_at": (T1 + timedelta(hours=5)).isoformat(),
                                             "reason": "y"}, ta, "c2")
st, s_full = call("GET", "/statement?limit=1", None, ta)
st, s_win = call("GET", "/statement?" + urllib.parse.urlencode({"from": (T1 - timedelta(hours=1)).isoformat(),
                                                                "to": (T1 + timedelta(days=1)).isoformat(), "known_at": known, "limit": 1}), None, ta)
pages = {}
for s in (s_full, s_win):
    pages[s["snapshot"]] = call("GET", "/statement?limit=200&snapshot=" + s["snapshot"], None, ta)[1]
st, ex = call("GET", "/_test/export")
snaps = ex["state"].get("snapshots")
check("export has saved statements", isinstance(snaps, list) and len(snaps) >= 2, type(snaps).__name__)
st, _ = call("POST", "/_test/import", ex)
check("genuine export imports", st == 204, st)
check("genuine snapshots page identically", all(call("GET", "/statement?limit=200&snapshot=" + k, None, ta)[1] == v for k, v in pages.items()), "")
base = call("GET", "/_test/export")[1]


def idx(state, with_echo):
    for i, s in enumerate(state["snapshots"]):
        if bool(s.get("echo")) == with_echo and len(s.get("entries", [])) >= 2:
            return i
    for i, s in enumerate(state["snapshots"]):
        if bool(s.get("echo")) == with_echo:
            return i
    raise KeyError("no snapshot")


def mut(name, fn, with_echo=False):
    bad = copy.deepcopy(ex)
    try:
        s = bad["state"]["snapshots"][idx(bad["state"], with_echo)]
        fn(s)
    except (KeyError, IndexError, TypeError) as e:
        check("applicable: " + name, False, repr(e))
        return
    st, b = call("POST", "/_test/import", bad)
    check("tamper %s -> 422" % name, st == 422 and b["error"]["code"] == "validation_failed", (st, b))
    check("tamper %s leaves destination unchanged" % name, call("GET", "/_test/export")[1] == base, "")


def setent(i, j, v):
    def f(s):
        s["entries"][i][j] = v(s["entries"][i][j]) if callable(v) else v
    return f


mut("revision 99", setent(0, 1, 99))
mut("wrong delta", setent(0, 2, lambda x: x + 1))
mut("wrong balance_after", setent(0, 3, lambda x: x + 1))
mut("wrong effective_at", setent(0, 4, (T1 - timedelta(days=1)).isoformat()))
mut("wrong recorded_at", setent(0, 5, (T1 - timedelta(days=1)).isoformat()))
mut("wrong amount", setent(0, 6, lambda x: x + 7))
mut("opening changed", lambda s: s.__setitem__("opening_balance", s["opening_balance"] + 1))
mut("closing changed", lambda s: s.__setitem__("closing_balance", s["closing_balance"] + 1))
mut("entry dropped", lambda s: s["entries"].pop())
mut("entries reversed", lambda s: s["entries"].reverse())
mut("entry duplicated", lambda s: s["entries"].append(list(s["entries"][0])))
mut("owner changed", lambda s: s.__setitem__("user_id", "u_b"))
mut("taken_seq changed", lambda s: s.__setitem__("taken_seq", 0))
mut("taken_seq removed", lambda s: s.pop("taken_seq"))
mut("taken_ts removed", lambda s: s.pop("taken_ts"))
mut("known_at bad-time", lambda s: s["echo"].__setitem__("known_at", "bad-time"), with_echo=True)
mut("known_at earlier", lambda s: s["echo"].__setitem__("known_at", (T1 - timedelta(days=2)).isoformat()), with_echo=True)
mut("window excludes entries", lambda s: s["echo"].__setitem__("to", (T1 - timedelta(hours=2)).isoformat()), with_echo=True)
mut("snapshots not a list", lambda s: s.clear() or s.update({"bogus": 1}))

fails = [r for r in RESULTS if not r[1]]
for n, ok, d in RESULTS:
    print("%s  %s%s" % ("PASS" if ok else "FAIL", n, "" if ok else "  -> %s" % (d,)))
print("%d probes, %d failed" % (len(RESULTS), len(fails)))
sys.exit(1 if fails else 0)
