#!/usr/bin/env python3
"""Reviewer's stage-4 model check: extends the stage-3 bitemporal reference model with refunds
(new opposite-direction immutable payments, cumulative limit against the current corrected
amount, funded from available money) and operator correction batches (combined current
affordability, historical non-negativity under all proposed revisions, shared recorded_at).
Written from the stage-4 specification. No holds or settlements here (probes_s4 covers them).

Usage: python3 model_check_s4.py http://localhost:8080 [--seeds 8] [--steps 60]
"""
import argparse
import random
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

import model_check_s3 as M3
from model_check_s3 import Mismatch, Model, code, expect, iso, ts


def run(seed, steps):
    rng = random.Random(seed)
    call = M3.call
    now = datetime.now(timezone.utc).replace(microsecond=0)
    n = rng.randint(3, 5)
    users = [{"id": "u%d" % i, "email": "u%d@x.io" % i, "password": "password", "display_name": "U%d" % i,
              "handle": "u%d" % i, "balance": 0} for i in range(n)]
    users.append({"id": "op", "email": "op@x.io", "password": "password", "display_name": "Op", "handle": "op", "balance": 0})
    opening = {u["id"]: (rng.choice([0, 500, 2000, 10000]) if u["id"] != "op" else 0) for u in users}
    cur = dict(opening)
    pays = []
    t = now - timedelta(days=20)
    for j in range(rng.randint(2, 8)):
        a, b = rng.sample(users[:-1], 2)
        if cur[a["id"]] < 2:
            continue
        amt = rng.randint(1, cur[a["id"]] // 2)
        t += timedelta(hours=rng.choice([0, 1, 7]))
        cur[a["id"]] -= amt
        cur[b["id"]] += amt
        pays.append({"id": "p_seed_%02d" % j, "from_user_id": a["id"], "to_user_id": b["id"], "amount": amt,
                     "note": "", "visibility": "public", "created_at": iso(t)})
    for u in users:
        u["balance"] = cur[u["id"]]
    fx = {"currency": "EUR", "minor_units": 2, "users": users, "payments": pays, "requests": [], "authorizations": [],
          "settlement_operator_ids": ["op"]}
    trace = [["seed", seed]]
    st, b = call("POST", "/_test/reset", fx)
    expect(st == 204, "reset %s %s" % (st, b), trace)
    U = {u["handle"]: {"id": u["id"], "token": call("POST", "/auth/login", {"email": u["email"], "password": "password"})[1]["token"]}
         for u in users}
    m = Model(U, opening)
    refund_of = {}       # refund pid -> target pid
    for p in pays:
        c = ts(p["created_at"])
        m.pays[p["id"]] = {"from": p["from_user_id"], "to": p["to_user_id"], "revs": [(1, p["amount"], c, c)], "created": c}
    by_id = {v["id"]: h for h, v in U.items()}
    total = sum(opening.values())
    people = [h for h in U if h != "op"]

    def refunded(pid):
        return sum(m.pays[r]["revs"][-1][1] for r, tgt in refund_of.items() if tgt == pid)

    def hist_ok(trial):
        bounds = m.boundaries(trial)
        return not any(m.balance(uid, tt, None, trial) < 0 for uid in m.opening for tt in bounds)

    def check_current():
        s = 0
        for h, u in U.items():
            st, me = call("GET", "/me", token=u["token"])
            expect(st == 200 and me["balance"] == m.balance(u["id"]), "balance %s: %s vs %s" % (h, me, m.balance(u["id"])), trace)
            s += me["balance"]
        expect(s == total, "sum %s" % s, trace)

    def check_statement():
        h = rng.choice(people)
        st, s = call("GET", "/statement?limit=200", token=U[h]["token"])
        op, rows, close = m.statement(U[h]["id"], None, datetime.now(timezone.utc) + timedelta(seconds=5), None)
        got = [(e["payment"]["payment_id"], e["revision"], e["payment"]["amount"], e["delta"], e["balance_after"]) for e in s["entries"]]
        expect(st == 200 and got == rows and s["opening_balance"] == op and s["closing_balance"] == close,
               "statement %s\n got %s\n want %s" % (h, got, rows), trace)

    def new_eff(p):
        return rng.choice([p["created"], p["revs"][-1][2], datetime.now(timezone.utc) - timedelta(days=rng.randint(0, 25))]).replace(microsecond=0)

    def new_amount(pid):
        last = m.pays[pid]["revs"][-1][1]
        return rng.choice([0, last, rng.randint(0, 4000), last + rng.randint(1, 500), max(0, last - rng.randint(1, 500)), refunded(pid)])

    check_current()
    for i in range(steps):
        op = rng.choices(["pay", "corr", "refund", "batch"], [3, 3, 3, 3])[0]
        ordinary = [pid for pid in m.pays if pid not in refund_of]
        if op == "pay" or not ordinary:
            a, b = rng.sample(people, 2)
            amt = rng.randint(1, 3000)
            st, p = call("POST", "/payments", {"to_handle": b, "amount": amt}, token=U[a]["token"], key="k%d-%d" % (seed, i))
            expect(st == (201 if m.balance(U[a]["id"]) >= amt else 409), "payment %s" % st, trace)
            if st == 201:
                c = ts(p["created_at"])
                m.pays[p["payment_id"]] = {"from": U[a]["id"], "to": U[b]["id"], "revs": [(1, amt, c, c)], "created": c}
            trace.append(["pay", a, b, amt, st])
        elif op == "refund":
            pid = rng.choice(list(m.pays))
            p = m.pays[pid]
            receiver = by_id[p["to"]]
            amt = rng.choice([1, rng.randint(1, 2000), max(1, p["revs"][-1][1] - refunded(pid)), p["revs"][-1][1] - refunded(pid) + 1])
            st, r = call("POST", "/payments/%s/refunds" % pid, {"amount": amt}, token=U[receiver]["token"], key="r%d-%d" % (seed, i))
            trace.append(["refund", pid, amt, st, code(r)])
            if pid in refund_of:
                expect(st == 422 and code(r) == "invalid_refund_target", "refund of refund %s %s" % (st, r), trace)
                continue
            if amt < 1 or refunded(pid) + amt > p["revs"][-1][1]:
                expect(st == 422 and code(r) in ("refund_exceeds_payment", "validation_failed"), "refund exceeds %s %s" % (st, r), trace)
                continue
            if m.balance(p["to"]) < amt:
                expect(st == 409 and code(r) == "insufficient_funds", "refund funds %s %s" % (st, r), trace)
                continue
            expect(st == 201 and r["refund_of"] == pid and r["amount"] == amt and r["from_user_id"] == p["to"], "refund 201 %s %s" % (st, r), trace)
            c = ts(r["created_at"])
            m.pays[r["payment_id"]] = {"from": p["to"], "to": p["from"], "revs": [(1, amt, c, c)], "created": c}
            refund_of[r["payment_id"]] = pid
        elif op == "corr":
            pid = rng.choice(list(m.pays))
            p = m.pays[pid]
            last = p["revs"][-1]
            amt, eff = new_amount(pid), new_eff(p)
            body = {"expected_revision": last[0], "amount": amt, "effective_at": iso(eff), "reason": "r%d" % i}
            st, r = call("POST", "/payments/%s/corrections" % pid, body, token=U[by_id[p["from"]]]["token"], key="c%d-%d" % (seed, i))
            trace.append(["corr", pid, body, st, code(r)])
            if pid in refund_of:
                expect(st == 422 and code(r) == "linked_payment_immutable", "correct refund %s" % st, trace)
                continue
            if amt < refunded(pid):
                expect(st == 422 and code(r) == "refund_exceeds_payment", "correction below refunded %s %s" % (st, r), trace)
                continue
            diff = amt - last[1]
            if diff > 0 and m.balance(p["from"]) < diff or diff < 0 and m.balance(p["to"]) < -diff:
                expect(st == 409 and code(r) == "insufficient_funds", "corr funds %s %s" % (st, r), trace)
                continue
            trial = {k: dict(v, revs=list(v["revs"])) for k, v in m.pays.items()}
            trial[pid]["revs"].append((last[0] + 1, amt, eff, datetime.now(timezone.utc)))
            if not hist_ok(trial):
                expect(st == 409 and code(r) == "historical_overdraft", "corr hist %s %s" % (st, r), trace)
                continue
            expect(st == 201 and r["revision"] == last[0] + 1, "corr 201 %s %s" % (st, r), trace)
            p["revs"].append((r["revision"], amt, eff, ts(r["recorded_at"])))
        else:  # batch
            pool = [pid for pid in m.pays if pid not in refund_of]
            k = rng.randint(1, min(4, len(pool)))
            chosen = rng.sample(pool, k)
            items = []
            for pid in chosen:
                p = m.pays[pid]
                items.append({"payment_id": pid, "expected_revision": p["revs"][-1][0], "amount": new_amount(pid),
                              "effective_at": iso(new_eff(p)), "reason": "b%d" % i})
            st, r = call("POST", "/correction-batches", {"corrections": items}, token=U["op"]["token"], key="b%d-%d" % (seed, i))
            trace.append(["batch", items, st, code(r)])
            below = [it for it in items if it["amount"] < refunded(it["payment_id"])]
            if below:
                expect(st == 422 and code(r) == "refund_exceeds_payment", "batch below refunded %s %s" % (st, r), trace)
                continue
            net = {}
            for it in items:
                p = m.pays[it["payment_id"]]
                d = it["amount"] - p["revs"][-1][1]
                net[p["from"]] = net.get(p["from"], 0) - d
                net[p["to"]] = net.get(p["to"], 0) + d
            if any(m.balance(uid) + dv < 0 for uid, dv in net.items()):
                expect(st == 409 and code(r) == "insufficient_funds", "batch funds %s %s" % (st, r), trace)
                continue
            trial = {kk: dict(v, revs=list(v["revs"])) for kk, v in m.pays.items()}
            nowdt = datetime.now(timezone.utc)
            for it in items:
                trial[it["payment_id"]]["revs"].append((0, it["amount"], ts(it["effective_at"]), nowdt))
            if not hist_ok(trial):
                expect(st == 409 and code(r) == "historical_overdraft", "batch hist %s %s" % (st, r), trace)
                continue
            expect(st == 201 and [x["payment_id"] for x in r["revisions"]] == chosen and
                   len({x["recorded_at"] for x in r["revisions"]}) == 1, "batch 201 %s %s" % (st, r), trace)
            rec = ts(r["recorded_at"])
            for it, x in zip(items, r["revisions"]):
                p = m.pays[it["payment_id"]]
                expect(rec > p["revs"][-1][3] and x["revision"] == p["revs"][-1][0] + 1, "batch recorded/revision", trace)
                p["revs"].append((x["revision"], it["amount"], ts(it["effective_at"]), rec))
            st, rep = call("POST", "/correction-batches", {"corrections": items}, token=U["op"]["token"], key="b%d-%d" % (seed, i))
            expect(st == 200 and rep == r, "batch replay %s" % st, trace)
        check_current()
        if i % 5 == 4:
            check_statement()
    check_statement()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--steps", type=int, default=60)
    a = ap.parse_args()
    M3.BASE = a.base.rstrip("/")
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
