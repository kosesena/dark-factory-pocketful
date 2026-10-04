#!/usr/bin/env python3
"""Reviewer's legacy-migration sweep for stage 4 (stage 4: "A stage-4 service must accept exports produced
by the same team's stages 1-3, retaining ... snapshots"; §10 invalid state -> 422, destination unchanged;
run contract: 5 s per request).

SRC is a real older stage-3 service whose exports carry metadata-free snapshots (495d5d6); DST is stage 4.
  A. genuine migrations: empty-first statement, later correction, later payment -> 204 and the original page
  B. ruling challenge: a stripped snapshot whose corrected entry is put back to its earlier revision
  C. malformed legacy snapshots -> 422 (never 500), destination unchanged
  D. scale: many later facts and several legacy snapshots -> import within the 5 s request limit

Usage: python3 probes_legacy_migration.py http://localhost:DST http://localhost:SRC [later_facts=2100] [snapshots=5]
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
N_LATER = int(sys.argv[3]) if len(sys.argv) > 3 else 2100
N_SNAPS = int(sys.argv[4]) if len(sys.argv) > 4 else 5
RESULTS = []


def call(base, m, p, body=None, tok=None, key=None, timeout=60):
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


NOW = datetime.now(timezone.utc).replace(microsecond=0)
T1 = NOW - timedelta(days=4)


def fixture(seeded=True):
    users = [{"id": "u_a", "email": "a@x.io", "password": "password", "display_name": "A", "handle": "a", "balance": 500000},
             {"id": "u_b", "email": "b@x.io", "password": "password", "display_name": "B", "handle": "b", "balance": 100000}]
    pays = [{"id": "p_s1", "from_user_id": "u_b", "to_user_id": "u_a", "amount": 300, "note": "", "visibility": "public",
             "created_at": T1.isoformat()}] if seeded else []
    return {"currency": "EUR", "minor_units": 2, "users": users, "requests": [], "payments": pays}


def login(base, who):
    return call(base, "POST", "/auth/login", {"email": who + "@x.io", "password": "password"})[1]["token"]


def page(base, tok, snap):
    st, b = call(base, "GET", "/statement?limit=100&snapshot=" + snap, None, tok)
    return b if st == 200 else {"status": st, "body": b}


def strip_refund(p):
    p = copy.deepcopy(p)
    if "entries" not in p:
        return ("NOT A PAGE", p)
    for e in p["entries"]:
        e["payment"].pop("refund_of", None)
    return p


def migrate(name, ex, pages, tok_user):
    t = time.time()
    st, b = call(DST, "POST", "/_test/import", ex)
    dt = time.time() - t
    check("A %s: real 495d5d6 export imports (204)" % name, st == 204, (st, b))
    check("A %s: import within 5 s" % name, dt < 5, "%.2fs" % dt)
    if st == 204:
        tok = login(DST, tok_user)
        for snap, orig in pages.items():
            got = page(DST, tok, snap)
            check("A %s: original page retained" % name, strip_refund(got) == strip_refund(orig), {"got": got, "orig": orig})
    return dt


# ---- A. genuine migrations ----------------------------------------------------------------------------
call(SRC, "POST", "/_test/reset", fixture(seeded=False))
ta = login(SRC, "a")
s0 = call(SRC, "GET", "/statement?limit=50", None, ta)[1]
check("A empty-first: source statement is empty", s0["entries"] == [], s0)
call(SRC, "POST", "/payments", {"to_handle": "b", "amount": 10}, ta, "e1")
ex = call(SRC, "GET", "/_test/export")[1]
check("A empty-first: source snapshots are metadata-free", all("taken_ts" not in s for s in ex["state"]["snapshots"]), "")
migrate("empty-first", ex, {s0["snapshot"]: page(SRC, ta, s0["snapshot"])}, "a")

for later in ("correction", "payment", "both"):
    call(SRC, "POST", "/_test/reset", fixture())
    ta, tb = login(SRC, "a"), login(SRC, "b")
    call(SRC, "POST", "/payments", {"to_handle": "b", "amount": 40}, ta, "k1")
    time.sleep(1.1)
    sA = call(SRC, "GET", "/statement?limit=1", None, ta)[1]
    sW = call(SRC, "GET", "/statement?limit=1&from=" + urllib.parse.quote((T1 - timedelta(hours=1)).isoformat()), None, ta)[1]
    pages = {s["snapshot"]: page(SRC, ta, s["snapshot"]) for s in (sA, sW)}
    time.sleep(1.1)
    if later in ("correction", "both"):
        check("A %s: source correction" % later, call(SRC, "POST", "/payments/p_s1/corrections",
              {"expected_revision": 1, "amount": 250, "effective_at": T1.isoformat(), "reason": "x"}, tb, "c1")[0] == 201, "")
    if later in ("payment", "both"):
        check("A %s: source payment" % later, call(SRC, "POST", "/payments", {"to_handle": "b", "amount": 5}, ta, "k2")[0] == 201, "")
    migrate("later " + later, call(SRC, "GET", "/_test/export")[1], pages, "a")

# ---- B. ruling challenge: revert a correction inside a stripped snapshot ------------------------------
call(SRC, "POST", "/_test/reset", fixture())
ta, tb = login(SRC, "a"), login(SRC, "b")
call(SRC, "POST", "/payments", {"to_handle": "b", "amount": 40}, ta, "k1")
time.sleep(1.1)
check("B source correction", call(SRC, "POST", "/payments/p_s1/corrections",
      {"expected_revision": 1, "amount": 250, "effective_at": T1.isoformat(), "reason": "x"}, tb, "c1")[0] == 201, "")
time.sleep(1.1)
sB = call(SRC, "GET", "/statement?limit=50", None, ta)[1]
genuine = page(SRC, ta, sB["snapshot"])
exB = call(SRC, "GET", "/_test/export")[1]
st, _ = call(DST, "POST", "/_test/import", exB)
check("B genuine corrected-statement export imports", st == 204, st)
baseB = call(DST, "GET", "/_test/export")[1]
bad = copy.deepcopy(exB)
sn = [s for s in bad["state"]["snapshots"] if s["token"] == sB["snapshot"]][0]
p1 = [p for p in bad["state"]["payments"] if p["id"] == "p_s1"][0]
rev1 = p1["revisions"][0] if "revisions" in p1 else None
reverted = False
running = sn["opening_balance"]
for e in sn["entries"]:
    if e[0] == "p_s1" and rev1 is not None:
        e[1], e[6], e[5], e[4] = 1, rev1["amount"], rev1["recorded_at"], rev1["effective_at"]
        e[2] = rev1["amount"]
        reverted = True
    running += e[2]
    e[3] = running
sn["closing_balance"] = running
check("B tamper applicable (corrected entry put back to revision 1)", reverted, "")
st, b = call(DST, "POST", "/_test/import", bad)
# The reverted snapshot is byte-identical to a genuine metadata-free snapshot taken before the correction
# (section A "later correction" migrates exactly that state), so stage 4 cannot refuse it without refusing a
# genuine export. Recorded as information for the coordinator's ruling, not as a pass/fail check.
print("INFO  B revert-correction tamper (admitted: coordinator ruling de5f3df5, any earlier recorded moment) -> %s" % st)
if st == 204:
    got = page(DST, login(DST, "a"), sB["snapshot"])
    print("INFO  B genuine entry: %s" % json.dumps([e for e in genuine["entries"] if e["payment"]["payment_id"] == "p_s1"])[:400])
    print("INFO  B imported entry: %s" % json.dumps([e for e in got["entries"] if e["payment"]["payment_id"] == "p_s1"])[:400])
call(DST, "POST", "/_test/import", exB)

# ---- C. malformed legacy snapshots -> 422, never 500 --------------------------------------------------
MAL = {
    "entry not a list": lambda s: s["entries"].__setitem__(0, {"x": 1}),
    "entry too short": lambda s: s["entries"].__setitem__(0, s["entries"][0][:3]),
    "unknown payment": lambda s: s["entries"][0].__setitem__(0, "p_nope"),
    "payment id int": lambda s: s["entries"][0].__setitem__(0, 7),
    "revision string": lambda s: s["entries"][0].__setitem__(1, "1"),
    "recorded_at garbage": lambda s: s["entries"][0].__setitem__(5, "garbage"),
    "recorded_at naive": lambda s: s["entries"][0].__setitem__(5, "2026-01-01T00:00:00"),
    "huge balance": lambda s: s.__setitem__("opening_balance", 10 ** 40),
    "opening float": lambda s: s.__setitem__("opening_balance", 1.5),
    "echo int": lambda s: s.__setitem__("echo", {"from": 5}),
    "user unknown": lambda s: s.__setitem__("user_id", "u_zz"),
    "entries null": lambda s: s.__setitem__("entries", None),
    "token empty": lambda s: s.__setitem__("token", ""),
}
for name, fn in MAL.items():
    badC = copy.deepcopy(exB)
    snC = [s for s in badC["state"]["snapshots"] if s["token"] == sB["snapshot"]][0]
    fn(snC)
    st, b = call(DST, "POST", "/_test/import", badC)
    check("C malformed legacy (%s) -> 422" % name, st == 422, (st, b))
    check("C malformed legacy (%s) leaves destination unchanged" % name, call(DST, "GET", "/_test/export")[1] == baseB, "")
    if st != 422:
        call(DST, "POST", "/_test/import", exB)
# a far-future known_at echo is a valid relabel (the rebuild is identical, query instants may be in the future):
# either outcome is acceptable, but never a 5xx
badC = copy.deepcopy(exB)
[s for s in badC["state"]["snapshots"] if s["token"] == sB["snapshot"]][0]["echo"] = {"known_at": "9999-12-31T23:59:59+00:00"}
st, b = call(DST, "POST", "/_test/import", badC)
check("C far-future known_at relabel -> 204 or 422, never 5xx", st in (204, 422), (st, b))
call(DST, "POST", "/_test/import", exB)

# ---- D. scale -----------------------------------------------------------------------------------------
call(SRC, "POST", "/_test/reset", fixture())
ta = login(SRC, "a")
early = {}
QS = ["", "&from=" + urllib.parse.quote((T1 - timedelta(hours=1)).isoformat()),
      "&to=" + urllib.parse.quote((NOW + timedelta(days=1)).isoformat()),
      "&known_at=" + urllib.parse.quote((NOW + timedelta(days=1)).isoformat())]
for i in range(N_SNAPS):
    s = call(SRC, "GET", "/statement?limit=1" + QS[i % len(QS)], None, ta)[1]
    early[s["snapshot"]] = page(SRC, ta, s["snapshot"])
t = time.time()
for i in range(N_LATER):
    call(SRC, "POST", "/payments", {"to_handle": "b", "amount": 1}, ta, "bulk%d" % i)
check("D created %d later payments on the source" % N_LATER, True, "%.1fs" % (time.time() - t))
dt = migrate("%d later facts, %d legacy snapshots" % (N_LATER, len(early)), call(SRC, "GET", "/_test/export")[1], early, "a")
print("D import took %.2fs" % dt)
# tampered at the same scale (one snapshot's balances shifted +1): refused within the same bound, unchanged
exD = call(SRC, "GET", "/_test/export")[1]
baseD = call(DST, "GET", "/_test/export")[1]
badD = copy.deepcopy(exD)
snD = badD["state"]["snapshots"][-1]
snD["opening_balance"] += 1
snD["closing_balance"] += 1
for e in snD["entries"]:
    e[3] += 1
t = time.time()
st, b = call(DST, "POST", "/_test/import", badD)
dt = time.time() - t
check("D tampered (%d facts, %d snapshots, one shifted +1) -> 422" % (N_LATER, N_SNAPS), st == 422, (st, b))
check("D tampered refused within 5 s", dt < 5, "%.2fs" % dt)
check("D tampered leaves destination unchanged", call(DST, "GET", "/_test/export")[1] == baseD, "")
print("D tampered import took %.2fs" % dt)

fails = [r for r in RESULTS if not r[1]]
for n, ok, d in RESULTS:
    print("%s  %s%s" % ("PASS" if ok else "FAIL", n, "" if ok else "  -> %s" % (json.dumps(d, default=str)[:900],)))
print("%d probes, %d failed" % (len(RESULTS), len(fails)))
sys.exit(1 if fails else 0)
