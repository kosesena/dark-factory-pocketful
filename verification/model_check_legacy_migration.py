#!/usr/bin/env python3
"""Reviewer's randomized migration check for stage 4 (stage 4: "A stage-4 service must accept exports produced by
the same team's stages 1-3, retaining ... corrections and snapshots"; stage 3: a snapshot "pages that exact result";
§10: an invalid state gives 422 with the destination unchanged).

Model, from the specification alone: a statement saved by the source is a fixed fact. Whatever happens on the source
afterwards, the export of the source must import into stage 4 and every saved token must page exactly what the source
returned when the statement was taken (stage 4 adds refund_of, which a pre-stage-4 page does not carry).

Each seed drives a real older stage-3 service (495d5d6, metadata-free snapshots) with a random sequence: payments
between three users, corrections by the sender with back-dated effective times (some rejected by the source, which is
fine), (half of them keeping the amount), and statements taken by random users with random from/to/known_at (past, present and future instants).
Afterwards: export -> import into stage 4 -> 204, every token pages its original page, the import is inside 5 s.
Then one random snapshot is corrupted in a way the ruling says must be refused (balances shifted, owner swapped,
entry duplicated, entries reversed when distinct) -> 422 with the destination unchanged.

Usage: python3 model_check_legacy_migration.py http://localhost:DST http://localhost:SRC [--seeds 20] [--steps 40]
"""
import argparse
import copy
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ap = argparse.ArgumentParser()
ap.add_argument("dst")
ap.add_argument("src")
ap.add_argument("--seeds", type=int, default=20)
ap.add_argument("--steps", type=int, default=40)
a = ap.parse_args()
DST, SRC = a.dst.rstrip("/"), a.src.rstrip("/")
FAIL = []


def call(base, m, p, body=None, tok=None, key=None):
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if tok:
        h["Authorization"] = "Bearer " + tok
    if key:
        h["Idempotency-Key"] = key
    r = urllib.request.Request(base + p, data=None if body is None else json.dumps(body).encode(), method=m, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=60) as x:
            t = x.read()
            return x.status, (json.loads(t) if t else None)
    except urllib.error.HTTPError as e:
        t = e.read()
        try:
            return e.code, (json.loads(t) if t else None)
        except ValueError:
            return e.code, t[:200]


def norm(p):
    p = copy.deepcopy(p)
    for e in p.get("entries", []):
        e["payment"].pop("refund_of", None)
    return p


def fail(seed, what, detail):
    FAIL.append((seed, what))
    print("FAIL seed %d: %s -> %s" % (seed, what, json.dumps(detail, default=str)[:700]))


for seed in range(a.seeds):
    rnd = random.Random(seed)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    t0 = now - timedelta(days=6)
    users = [{"id": "u_" + h, "email": h + "@x.io", "password": "password", "display_name": h.upper(), "handle": h,
              "balance": rnd.choice([5000, 20000, 100000])} for h in "abc"]
    pays = []
    for i in range(rnd.randint(0, 3)):
        f, t = rnd.sample("abc", 2)
        pays.append({"id": "p_seed%d" % i, "from_user_id": "u_" + f, "to_user_id": "u_" + t, "amount": rnd.randint(1, 500),
                     "note": "", "visibility": rnd.choice(["public", "private"]),
                     "created_at": (t0 + timedelta(hours=rnd.randint(0, 100))).isoformat()})
    st, b = call(SRC, "POST", "/_test/reset", {"currency": "EUR", "minor_units": 2, "users": users, "requests": [],
                                               "payments": pays})
    if st != 204:
        print("skip seed %d: reset %s %s" % (seed, st, b))
        continue
    tok = {h: call(SRC, "POST", "/auth/login", {"email": h + "@x.io", "password": "password"})[1]["token"] for h in "abc"}
    payments = [(p["id"], p["from_user_id"][2:]) for p in pays]
    revs = {p["id"]: 1 for p in pays}
    amt = {p["id"]: p["amount"] for p in pays}
    saved = {}
    ncorr = 0
    instants = lambda: rnd.choice([t0 - timedelta(days=1), t0 + timedelta(hours=rnd.randint(0, 140)),
                                   datetime.now(timezone.utc) + timedelta(seconds=rnd.randint(-5, 5)),
                                   now + timedelta(days=rnd.randint(1, 30))])
    for step in range(a.steps):
        op = rnd.random()
        if op < 0.4:
            f, t = rnd.sample("abc", 2)
            st, b = call(SRC, "POST", "/payments", {"to_handle": t, "amount": rnd.randint(1, 800)}, tok[f], "s%dp%d" % (seed, step))
            if st == 201:
                payments.append((b["payment_id"], f))
                revs[b["payment_id"]] = 1
                amt[b["payment_id"]] = b["amount"]
        elif op < 0.6 and payments:
            pid, sender = rnd.choice(payments)
            eff = t0 + timedelta(hours=rnd.randint(0, 140))
            eff = min(eff, datetime.now(timezone.utc) - timedelta(seconds=1))
            # half the corrections keep the amount (same balances at many moments defeat a balance-based screen)
            new_amt = amt[pid] if rnd.random() < 0.5 else rnd.randint(0, 900)
            st, b = call(SRC, "POST", "/payments/%s/corrections" % pid,
                         {"expected_revision": revs[pid], "amount": new_amt, "effective_at": eff.isoformat(),
                          "reason": "r"}, tok[sender], "s%dc%d" % (seed, step))
            if st == 201:
                revs[pid] = b["revision"]
                amt[pid] = new_amt
                ncorr += 1
        else:
            h = rnd.choice("abc")
            q = {}
            if rnd.random() < 0.4:
                q["from"] = instants().isoformat()
            if rnd.random() < 0.4:
                q["to"] = instants().isoformat()
            if rnd.random() < 0.4:
                q["known_at"] = instants().isoformat()
            st, b = call(SRC, "GET", "/statement?limit=1&" + urllib.parse.urlencode(q), None, tok[h])
            if st == 200:
                full = call(SRC, "GET", "/statement?limit=100&snapshot=" + b["snapshot"], None, tok[h])[1]
                saved[b["snapshot"]] = (h, full)
    ex = call(SRC, "GET", "/_test/export")[1]
    t = time.time()
    st, b = call(DST, "POST", "/_test/import", ex)
    dt = time.time() - t
    if st != 204:
        fail(seed, "genuine 495d5d6 export refused (%d payments, %d snapshots)" % (len(payments), len(saved)), (st, b))
        continue
    if dt >= 5:
        fail(seed, "import took %.2fs" % dt, "")
    dtok = {h: call(DST, "POST", "/auth/login", {"email": h + "@x.io", "password": "password"})[1]["token"] for h in "abc"}
    bad_pages = 0
    for snap, (h, full) in saved.items():
        got = call(DST, "GET", "/statement?limit=100&snapshot=" + snap, None, dtok[h])[1]
        if norm(got) != norm(full):
            bad_pages += 1
            fail(seed, "token %s pages differently after migration" % snap[:8], {"got": got, "orig": full})
    # corruption that the ruling says must be refused
    legacy = [s for s in ex["state"]["snapshots"] if "taken_ts" not in s]
    if legacy:
        base = call(DST, "GET", "/_test/export")[1]
        bad = copy.deepcopy(ex)
        sn = rnd.choice([s for s in bad["state"]["snapshots"] if "taken_ts" not in s])
        kinds = ["shift", "owner"]
        if sn["entries"]:
            kinds.append("dup")
        if len({tuple(e) for e in sn["entries"]}) >= 2 and sn["entries"] != sn["entries"][::-1]:
            kinds.append("reverse")
        kind = rnd.choice(kinds)
        if kind == "shift":
            sn["opening_balance"] += 1
            sn["closing_balance"] += 1
            for e in sn["entries"]:
                e[3] += 1
        elif kind == "owner":
            sn["user_id"] = rnd.choice([u for u in ("u_a", "u_b", "u_c") if u != sn["user_id"]])
        elif kind == "dup":
            e = list(sn["entries"][-1])
            sn["entries"].append(e)
            e[3] = sn["entries"][-2][3] + e[2]
            sn["closing_balance"] = e[3]
        else:
            sn["entries"].reverse()
            run = sn["opening_balance"]
            for e in sn["entries"]:
                run += e[2]
                e[3] = run
        st2, b2 = call(DST, "POST", "/_test/import", bad)
        if st2 != 422:
            fail(seed, "corruption '%s' not refused" % kind, (st2, b2))
        elif call(DST, "GET", "/_test/export")[1] != base:
            fail(seed, "corruption '%s' changed the destination" % kind, "")
        tag = kind
    else:
        tag = "-"
    print("seed %2d: %3d payments, %2d corrections, %2d snapshots, import %.2fs, pages ok %d/%d, corruption %s" %
          (seed, len(payments), ncorr, len(saved), dt, len(saved) - bad_pages, len(saved), tag))

print("FAILURES: %d" % len(FAIL))
sys.exit(1 if FAIL else 0)
