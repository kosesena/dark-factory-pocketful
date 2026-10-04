#!/usr/bin/env python3
"""Reviewer's stage-3 model check: a reference model of the bitemporal ledger (opening balances,
payment revisions with effective/recorded times, corrections) written from the stage-3
specification. Random sequences of payments and corrections (valid, stale, unaffordable,
historically overdrawing) are applied to the service and the model; after every step current
balances are compared, and periodically random /me?as_of&known_at views and random statement
windows (with paging) are compared entry by entry. Holds are not modelled here (probes_s3 covers
them).

Usage: python3 model_check_s3.py http://localhost:8080 [--seeds 8] [--steps 60]
"""
import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = None


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
        return e.code, json.loads(t) if t else None


def code(b):
    try:
        return b["error"]["code"]
    except (TypeError, KeyError):
        return None


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


class Mismatch(Exception):
    pass


def expect(cond, msg, trace):
    if not cond:
        raise Mismatch(msg + "\n  trace (last 10): " + json.dumps(trace[-10:], default=str))


class Model:
    def __init__(self, users, opening):
        self.users = users              # handle -> {id, token}
        self.opening = dict(opening)    # uid -> opening balance
        self.pays = {}                  # pid -> {from, to, revs: [(rev, amount, eff dt, rec dt)]}

    def selected(self, p, K):
        revs = [r for r in p["revs"] if K is None or r[3] <= K]
        return revs[-1] if revs else None

    def balance(self, uid, t=None, K=None, pays=None):
        b = self.opening[uid]
        for p in (pays or self.pays).values():
            r = self.selected(p, K)
            if r is None or (t is not None and r[2] > t):
                continue
            if p["from"] == uid:
                b -= r[1]
            if p["to"] == uid:
                b += r[1]
        return b

    def boundaries(self, pays):
        return sorted({p["revs"][-1][2] for p in pays.values()})

    def statement(self, uid, frm, to, K):
        rows = []
        for pid, p in self.pays.items():
            if uid not in (p["from"], p["to"]):
                continue
            r = self.selected(p, K)
            if r is None:
                continue
            if (frm is None or r[2] >= frm) and r[2] < to:
                rows.append((r[2], pid, r, -r[1] if p["from"] == uid else r[1]))
        rows.sort(key=lambda x: (x[0], x[1]))
        opening = self.balance(uid, frm - timedelta(microseconds=1), K) if frm else self.opening[uid]
        out, bal = [], opening
        for eff, pid, r, d in rows:
            bal += d
            out.append((pid, r[0], r[1], d, bal))
        return opening, out, bal


def run(seed, steps):
    rng = random.Random(seed)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    n = rng.randint(3, 5)
    users = [{"id": "u%d" % i, "email": "u%d@x.io" % i, "password": "password", "display_name": "U%d" % i,
              "handle": "u%d" % i, "balance": 0} for i in range(n)]
    opening = {u["id"]: rng.choice([0, 500, 2000, 10000]) for u in users}
    cur = dict(opening)
    pays = []
    t = now - timedelta(days=20)
    for j in range(rng.randint(2, 8)):
        a, b = rng.sample(users, 2)
        amt = rng.randint(1, max(1, cur[a["id"]] // 2)) if cur[a["id"]] else 0
        if amt == 0:
            continue
        t += timedelta(hours=rng.choice([0, 1, 7]))  # some same-instant payments
        cur[a["id"]] -= amt
        cur[b["id"]] += amt
        pays.append({"id": "p_seed_%02d" % j, "from_user_id": a["id"], "to_user_id": b["id"], "amount": amt,
                     "note": "", "visibility": rng.choice(["public", "private"]), "created_at": iso(t)})
    for u in users:
        u["balance"] = cur[u["id"]]
    fx = {"currency": "EUR", "minor_units": 2, "users": users, "payments": pays, "requests": [], "authorizations": []}
    trace = [["seed", seed]]
    st, b = call("POST", "/_test/reset", fx)
    expect(st == 204, "reset %s %s" % (st, b), trace)
    U = {}
    for u in users:
        U[u["handle"]] = {"id": u["id"], "token": call("POST", "/auth/login", {"email": u["email"], "password": "password"})[1]["token"]}
    m = Model(U, opening)
    for p in pays:
        c = ts(p["created_at"])
        m.pays[p["id"]] = {"from": p["from_user_id"], "to": p["to_user_id"], "revs": [(1, p["amount"], c, c)], "created": c}
    by_id = {v["id"]: h for h, v in U.items()}
    total = sum(opening.values())
    recorded = []

    def check_current():
        s = 0
        for h, u in U.items():
            st, me = call("GET", "/me", token=u["token"])
            expect(st == 200 and me["balance"] == m.balance(u["id"]), "current balance %s: %s vs %s" % (h, me, m.balance(u["id"])), trace)
            s += me["balance"]
        expect(s == total, "sum %s != %s" % (s, total), trace)

    def check_views():
        times = [p["revs"][-1][2] for p in m.pays.values()] + [p["created"] for p in m.pays.values()]
        h = rng.choice(list(U))
        u = U[h]
        cand = [rng.choice(times) + timedelta(microseconds=rng.choice([-1, 0, 1])) for _ in range(2)] if times else []
        cand.append(datetime.now(timezone.utc) + timedelta(days=1))
        Ks = [None] + ([rng.choice(recorded)] if recorded else [])
        for K in Ks:
            for t in cand:
                qs = {"as_of": iso(t)}
                if K is not None:
                    qs["known_at"] = iso(K)
                st, me = call("GET", "/me?" + urllib.parse.urlencode(qs), token=u["token"])
                want = m.balance(u["id"], t, K)
                expect(st == 200 and me["balance"] == want and me.get("as_of") == qs["as_of"],
                       "as_of %s known_at %s for %s: got %s want %s" % (qs["as_of"], K, h, me, want), trace)
                tot = sum(m.balance(x["id"], t, K) for x in U.values())
                expect(tot == total, "model sum broken (reviewer bug)", trace)
            frm = rng.choice([None] + cand[:2])
            to = rng.choice(cand)
            if frm is not None and frm > to:
                frm, to = to, frm
            qs = {"to": iso(to), "limit": 200}
            if frm is not None:
                qs["from"] = iso(frm)
            if K is not None:
                qs["known_at"] = iso(K)
            st, s = call("GET", "/statement?" + urllib.parse.urlencode(qs), token=u["token"])
            op, rows, close = m.statement(u["id"], frm, to, K)
            expect(st == 200, "statement status %s %s" % (st, s), trace)
            got = [(e["payment"]["payment_id"], e["revision"], e["payment"]["amount"], e["delta"], e["balance_after"])
                   for e in s["entries"]]
            expect(s["opening_balance"] == op and s["closing_balance"] == close and got == rows,
                   "statement %s for %s:\n got  %s %s %s\n want %s %s %s" % (qs, h, s["opening_balance"], got,
                                                                          s["closing_balance"], op, rows, close), trace)
            if len(rows) > 1:
                k = rng.randint(1, len(rows) - 1)
                qs2 = dict(qs, limit=1, offset=k)
                st, s2 = call("GET", "/statement?" + urllib.parse.urlencode(qs2), token=u["token"])
                expect([(e["payment"]["payment_id"], e["balance_after"]) for e in s2["entries"]] == [(rows[k][0], rows[k][4])]
                       and s2["opening_balance"] == op and s2["closing_balance"] == close
                       and s2["has_more"] == (k < len(rows) - 1), "paged statement %s" % qs2, trace)

    check_current()
    for i in range(steps):
        op = rng.choices(["pay", "corr", "corr_stale", "corr_bad_party"], [3, 6, 1, 1])[0]
        if op == "pay":
            a, b = rng.sample(list(U), 2)
            amt = rng.randint(1, 3000)
            st, p = call("POST", "/payments", {"to_handle": b, "amount": amt}, token=U[a]["token"], key="k%d-%d" % (seed, i))
            want = 201 if m.balance(U[a]["id"]) >= amt else 409
            trace.append(["pay", a, b, amt, st])
            expect(st == want, "payment status %s want %s" % (st, want), trace)
            if st == 201:
                c = ts(p["created_at"])
                m.pays[p["payment_id"]] = {"from": U[a]["id"], "to": U[b]["id"], "revs": [(1, amt, c, c)], "created": c}
        elif m.pays:
            pid = rng.choice(list(m.pays))
            p = m.pays[pid]
            sender = by_id[p["from"]]
            last = p["revs"][-1]
            amt = rng.choice([0, last[1], rng.randint(0, 4000), last[1] + rng.randint(1, 500), max(0, last[1] - rng.randint(1, 500))])
            choices = [p["created"], last[2], datetime.now(timezone.utc) - timedelta(days=rng.randint(0, 25)),
                       min(mp["revs"][-1][2] for mp in m.pays.values())]
            eff = rng.choice(choices).replace(microsecond=0)
            body = {"expected_revision": last[0] - 1 if op == "corr_stale" and last[0] > 1 else last[0],
                    "amount": amt, "effective_at": iso(eff), "reason": "r%d" % i}
            caller = sender if op != "corr_bad_party" else by_id[p["to"]]
            st, r = call("POST", "/payments/%s/corrections" % pid, body, token=U[caller]["token"], key="c%d-%d" % (seed, i))
            trace.append([op, pid, body, st, code(r)])
            if op == "corr_bad_party":
                expect(st == 403, "non-sender correction %s" % st, trace)
                continue
            if body["expected_revision"] != last[0]:
                expect(st == 409 and code(r) == "stale_revision", "stale %s %s" % (st, r), trace)
                continue
            diff = amt - last[1]
            if diff > 0 and m.balance(p["from"]) < diff or diff < 0 and m.balance(p["to"]) < -diff:
                expect(st == 409 and code(r) == "insufficient_funds", "want insufficient, got %s %s" % (st, r), trace)
                continue
            trial = {k: dict(v, revs=list(v["revs"])) for k, v in m.pays.items()}
            trial[pid]["revs"].append((last[0] + 1, amt, eff, datetime.now(timezone.utc)))
            bounds = m.boundaries(trial)
            neg = any(m.balance(uid, t, None, trial) < 0 for uid in m.opening for t in bounds)
            if neg:
                expect(st == 409 and code(r) == "historical_overdraft", "want historical_overdraft, got %s %s" % (st, r), trace)
                continue
            expect(st == 201 and r["revision"] == last[0] + 1 and r["amount"] == amt and ts(r["effective_at"]) == eff,
                   "want 201 correction, got %s %s" % (st, r), trace)
            rec = ts(r["recorded_at"])
            expect(rec > last[3], "recorded_at not increasing", trace)
            p["revs"].append((r["revision"], amt, eff, rec))
            recorded.append(rec)
            if rng.random() < 0.3:
                recorded.append(rec - timedelta(microseconds=1))
            st, rep = call("POST", "/payments/%s/corrections" % pid, body, token=U[sender]["token"], key="c%d-%d" % (seed, i))
            expect(st == 200 and rep == r, "correction replay %s" % st, trace)
        check_current()
        if i % 6 == 5:
            check_views()
    check_views()
    # revisions endpoint agrees with the model
    for pid, p in m.pays.items():
        st, rv = call("GET", "/payments/%s/revisions" % pid, token=U[by_id[p["from"]]]["token"])
        expect(st == 200 and [(x["revision"], x["amount"]) for x in rv["revisions"]] == [(r[0], r[1]) for r in p["revs"]],
               "revisions of %s" % pid, trace)


def main():
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--steps", type=int, default=60)
    a = ap.parse_args()
    BASE = a.base.rstrip("/")
    fails = 0
    for seed in range(1, a.seeds + 1):
        try:
            run(seed, a.steps)
            print("seed %d: ok" % seed)
        except Mismatch as e:
            fails += 1
            print("seed %d: MISMATCH %s" % (seed, e))
    print("FAILURES: %d" % fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
