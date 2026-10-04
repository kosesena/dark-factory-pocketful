#!/usr/bin/env python3
"""Reviewer's model-based check for Pocketful stage 1.

Written from the stage-1 specification only. A small reference model of the stated rules is
driven with random operation sequences (valid, invalid, repeated, replayed) against a running
service; every response is compared with the model and every §1 invariant is checked after
each step. A concurrent phase fires bursts of up to 50 in-flight requests and checks the
invariants plus exactly-once idempotency.

Usage: python3 model_check.py http://localhost:8080 [--seeds 20] [--steps 150]
Exit 0 when no mismatch was found. Stdlib only.
"""
import argparse
import copy
import json
import random
import re
import sys
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = None
FAIL = []
STATS = {}


def call(method, path, body=None, token=None, key=None, raw=None, headers=None):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    if key is not None:
        h["Idempotency-Key"] = key
    h.update(headers or {})
    k = (method, re.sub(r"/requests/[^/]+/", "/requests/{id}/", path.split("?")[0]))
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            txt = r.read()
            STATS[k + (r.status,)] = STATS.get(k + (r.status,), 0) + 1
            return r.status, (json.loads(txt) if txt else None)
    except urllib.error.HTTPError as e:
        txt = e.read()
        STATS[k + (e.code,)] = STATS.get(k + (e.code,), 0) + 1
        try:
            return e.code, json.loads(txt) if txt else None
        except ValueError:
            return e.code, {"_raw": txt.decode("utf-8", "replace")}


def code_of(body):
    try:
        return body["error"]["code"]
    except (TypeError, KeyError):
        return None


class Mismatch(Exception):
    pass


def expect(cond, msg, trace):
    if not cond:
        raise Mismatch(msg + "\n  trace (last 12): " + json.dumps(trace[-12:], ensure_ascii=False))


# --------------------------------------------------------------------------- model

class Model:
    def __init__(self, fixture):
        self.users = {}            # handle -> dict(id, balance, token)
        self.by_id = {}
        for u in fixture["users"]:
            m = {"id": u["id"], "handle": u["handle"], "balance": u["balance"],
                 "email": u["email"], "password": u["password"]}
            self.users[u["handle"]] = m
            self.by_id[u["id"]] = m
        self.total = sum(u["balance"] for u in fixture["users"])
        self.payments = {}         # id -> dict(from, to, amount, vis, request_id)
        for p in fixture.get("payments", []):
            self.payments[p["id"]] = {"from": p["from_user_id"], "to": p["to_user_id"],
                                      "amount": p["amount"], "vis": p.get("visibility", "public"),
                                      "request_id": None, "settlement_id": None}
        self.requests = {}         # id -> dict(requester, payer, amount, status, payment_id)
        for r in fixture.get("requests", []):
            self.requests[r["id"]] = {"requester": r["requester_id"], "payer": r["payer_id"],
                                      "amount": r["amount"], "status": r.get("status", "pending"),
                                      "paid_count": 0}
        self.operators = set(fixture.get("settlement_operator_ids", []))
        self.idem = {}             # (uid, key, path) -> (canonical body, status-201 body)


def canon(b):
    def n(v):
        if isinstance(v, float) and v.is_integer():
            return int(v)
        if isinstance(v, dict):
            return {k: n(x) for k, x in v.items()}
        if isinstance(v, list):
            return [n(x) for x in v]
        return v
    return json.dumps(n(b), sort_keys=True)


def valid_amount(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    if isinstance(v, float) and not v.is_integer():
        return False
    return 1 <= v <= 1_000_000_000


def make_fixture(rng):
    n = rng.randint(3, 6)
    users = []
    for i in range(n):
        users.append({"id": "u_%d_%d" % (i, rng.randint(0, 999)), "email": "user%d@example.com" % i,
                      "password": "password%d!" % i, "display_name": "User %d" % i,
                      "handle": "user%d" % i, "balance": rng.choice([0, 0, 100, 2500, 10000, 999999])})
    pays = []
    for j in range(rng.randint(0, 3)):
        a, b = rng.sample(users, 2)
        pays.append({"id": "p_seed_%d" % j, "from_user_id": a["id"], "to_user_id": b["id"],
                     "amount": rng.randint(1, 500), "note": "seed", "visibility": rng.choice(["public", "private"])})
    reqs = []
    for j in range(rng.randint(0, 3)):
        a, b = rng.sample(users, 2)
        reqs.append({"id": "rq_seed_%d" % j, "requester_id": a["id"], "payer_id": b["id"],
                     "amount": rng.randint(1, 3000), "note": "seedreq", "status": "pending"})
    ops = [users[0]["id"]] if rng.random() < 0.8 else []
    return {"currency": rng.choice(["EUR", "JPY", "BHD"]), "minor_units": 2, "users": users,
            "payments": pays, "requests": reqs, "settlement_operator_ids": ops}


# --------------------------------------------------------------------------- checks

def check_invariants(m, trace):
    total = 0
    for h, u in m.users.items():
        st, me = call("GET", "/me", token=u["token"])
        expect(st == 200, "GET /me %s -> %s %s" % (h, st, me), trace)
        expect(me["balance"] >= 0, "negative balance for %s: %s" % (h, me["balance"]), trace)
        expect(me["balance"] == u["balance"],
               "balance mismatch %s: service %s model %s" % (h, me["balance"], u["balance"]), trace)
        total += me["balance"]
    expect(total == m.total, "sum %s != seeded %s" % (total, m.total), trace)


def list_all(path, field, token):
    out, off = [], 0
    while True:
        st, b = call("GET", "%s?limit=200&offset=%d" % (path, off), token=token)
        if st != 200:
            return st, b
        out += b[field]
        if not b["has_more"]:
            return 200, out
        off += 200


def check_views(m, trace):
    for h, u in m.users.items():
        st, feed = list_all("/activity", "payments", u["token"])
        expect(st == 200, "activity %s -> %s" % (h, st), trace)
        got = {p["payment_id"] for p in feed}
        want = {pid for pid, p in m.payments.items()
                if p["vis"] == "public" or u["id"] in (p["from"], p["to"])}
        expect(got == want, "feed mismatch for %s: extra %s missing %s" % (h, got - want, want - got), trace)
        for p in feed:
            mp = m.payments[p["payment_id"]]
            expect(p["visibility"] == mp["vis"] and p["amount"] == mp["amount"],
                   "feed item differs %s" % p, trace)
        ts = [p["created_at"] for p in feed]
        st, reqs = list_all("/requests", "requests", u["token"])
        expect(st == 200, "requests %s -> %s" % (h, st), trace)
        got = {r["request_id"]: r["status"] for r in reqs}
        want = {rid: r["status"] for rid, r in m.requests.items()
                if u["id"] in (r["requester"], r["payer"])}
        expect(got == want, "requests mismatch for %s: got %s want %s" % (h, got, want), trace)


# --------------------------------------------------------------------------- random ops

AMOUNTS_BAD = [0, -1, 1_000_000_001, "100", True, 1.5, None]


def rnd_amount(rng, hi=3000):
    r = rng.random()
    if r < 0.12:
        return rng.choice(AMOUNTS_BAD), False
    v = rng.randint(1, hi)
    if r < 0.2:
        return float(v), True
    return v, True


def step(m, rng, trace, keys):
    handles = list(m.users)
    actor_h = rng.choice(handles)
    actor = m.users[actor_h]
    op = rng.choices(["pay", "req", "payreq", "decline", "cancel", "split", "settle", "replay",
                      "reuse"], [6, 4, 5, 2, 2, 2, 2, 3, 1])[0]

    def new_key():
        k = "k%d" % rng.randint(0, 10 ** 9)
        return k

    def run_idem(path, body, expected_status, expected_code, on_ok):
        key = new_key()
        st, b = call("POST", path, body, token=actor["token"], key=key)
        trace.append([actor_h, "POST", path, body, st, code_of(b)])
        expect(st == expected_status and (expected_code is None or code_of(b) == expected_code),
               "%s %s: service %s %s, model %s %s" % (path, body, st, code_of(b) or "", expected_status,
                                                    expected_code), trace)
        if st == 201:
            on_ok(b)
            m.idem[(actor["id"], key, path)] = (canon(body), b)
            keys.append((actor_h, key, path, body))
        else:
            keys.append((actor_h, key, path, None))  # failed key: reusable

    if op == "pay":
        amt, ok = rnd_amount(rng, max(1, actor["balance"] + 200))
        to_h = rng.choice(handles + ["nobody_x"])
        body = {"to_handle": to_h, "amount": amt}
        vis = rng.choice([None, "public", "private", "PUBLIC"])
        if vis is not None:
            body["visibility"] = vis
        if rng.random() < 0.3:
            body["note"] = rng.choice(["", "dinner 🍕", "x" * 200, "x" * 201, None])
        if rng.random() < 0.1:
            body["extra_field"] = 1
        note_ok = "note" not in body or (isinstance(body["note"], str) and len(body["note"]) <= 200)
        vis_ok = vis in (None, "public", "private")
        if not ok or not note_ok or not vis_ok:
            # only one class of fault at a time, else precedence is unspecified
            if to_h == "nobody_x" or to_h == actor_h:
                return
            exp = (422, "validation_failed")
        elif to_h == "nobody_x":
            exp = (404, "not_found")
        elif to_h == actor_h:
            exp = (422, "self_payment")
        elif actor["balance"] < amt:
            exp = (409, "insufficient_funds")
        else:
            exp = (201, None)

        def ok_fn(b):
            to = m.users[to_h]
            actor["balance"] -= int(amt)
            to["balance"] += int(amt)
            expect(b["amount"] == int(amt) and b["to_handle"] == to_h and b["from_handle"] == actor_h
                   and b["visibility"] == (vis or "public") and b["request_id"] is None
                   and b.get("settlement_id") is None
                   and b["note"] == body.get("note", ""), "payment body wrong %s" % b, trace)
            m.payments[b["payment_id"]] = {"from": actor["id"], "to": to["id"], "amount": int(amt),
                                           "vis": vis or "public", "request_id": None,
                                           "settlement_id": None}
        run_idem("/payments", body, exp[0], exp[1], ok_fn)

    elif op == "req":
        amt, ok = rnd_amount(rng, 20000)
        p_h = rng.choice(handles + ["nobody_x"])
        body = {"payer_handle": p_h, "amount": amt, "note": "r"}
        if not ok:
            if p_h in ("nobody_x", actor_h):
                return
            exp = (422, "validation_failed")
        elif p_h == "nobody_x":
            exp = (404, "not_found")
        elif p_h == actor_h:
            exp = (422, "self_request")
        else:
            exp = (201, None)

        def ok_fn(b):
            expect(b["status"] == "pending" and b["amount"] == int(amt) and b["payment_id"] is None
                   and b["payer_handle"] == p_h and b["requester_handle"] == actor_h,
                   "request body wrong %s" % b, trace)
            m.requests[b["request_id"]] = {"requester": actor["id"], "payer": m.users[p_h]["id"],
                                           "amount": int(amt), "status": "pending", "paid_count": 0}
        run_idem("/requests", body, exp[0], exp[1], ok_fn)

    elif op == "payreq":
        mine = [rid for rid, r in m.requests.items() if r["payer"] == actor["id"]]
        pool = mine * 3 + list(m.requests) + ["rq_does_not_exist"]
        rid = rng.choice(pool)
        body = rng.choice([{}, {"visibility": "public"}, {"visibility": "private"}, {"visibility": "x"}])
        r = m.requests.get(rid)
        if r is None:
            exp = (404, "not_found")
        elif r["payer"] != actor["id"]:
            exp = (403, "forbidden")
        elif body.get("visibility", "public") not in ("public", "private"):
            if r["status"] != "pending" or actor["balance"] < r["amount"]:
                return  # precedence between validation and state unspecified
            exp = (422, "validation_failed")
        elif r["status"] != "pending":
            exp = (409, "request_not_pending")
        elif actor["balance"] < r["amount"]:
            exp = (409, "insufficient_funds")
        else:
            exp = (201, None)

        def ok_fn(b):
            to = m.by_id[r["requester"]]
            actor["balance"] -= r["amount"]
            to["balance"] += r["amount"]
            r["status"] = "paid"
            r["paid_count"] += 1
            expect(b["request_id"] == rid and b["amount"] == r["amount"]
                   and b["visibility"] == body.get("visibility", "public"), "pay body wrong %s" % b, trace)
            m.payments[b["payment_id"]] = {"from": actor["id"], "to": to["id"], "amount": r["amount"],
                                           "vis": body.get("visibility", "public"), "request_id": rid,
                                           "settlement_id": None}
        run_idem("/requests/%s/pay" % rid, body, exp[0], exp[1], ok_fn)

    elif op in ("decline", "cancel"):
        rid = rng.choice(list(m.requests) + ["rq_does_not_exist"])
        r = m.requests.get(rid)
        target = "declined" if op == "decline" else "cancelled"
        who = "payer" if op == "decline" else "requester"
        if r is None:
            exp = 404
        elif r[who] != actor["id"]:
            exp = 403
        elif r["status"] in ("pending", target):
            exp = 200
        else:
            exp = 409
        st, b = call("POST", "/requests/%s/%s" % (rid, op), {}, token=actor["token"])
        trace.append([actor_h, op, rid, st, code_of(b)])
        expect(st == exp, "%s %s: service %s model %s" % (op, rid, st, exp), trace)
        if st == 200:
            r["status"] = target
            expect(b["status"] == target, "%s body status %s" % (op, b), trace)

    elif op == "split":
        k = rng.randint(1, len(handles))
        parts = rng.sample(handles, k)
        if rng.random() < 0.1:
            parts.append(parts[0])
        if rng.random() < 0.05:
            parts.append("nobody_x")
        amt, ok = rnd_amount(rng, 5000)
        body = {"amount": amt, "participant_handles": parts}
        dup = len(set(parts)) != len(parts)
        if not ok or dup:
            if "nobody_x" in parts:
                return
            exp = (422, "validation_failed")
        elif "nobody_x" in parts:
            exp = (404, "not_found")
        else:
            exp = (201, None)

        def ok_fn(b):
            n = len(parts)
            a = int(amt)
            base, extra = divmod(a, n)
            want = [base + (1 if i < extra else 0) for i in range(n)]
            expect([s["amount"] for s in b["shares"]] == want and
                   [s["handle"] for s in b["shares"]] == parts, "shares wrong %s" % b["shares"], trace)
            others = [(h, w) for h, w in zip(parts, want) if h != actor_h]
            expect([(q["payer_handle"], q["amount"]) for q in b["requests"]] == others,
                   "split requests wrong %s" % b["requests"], trace)
            for q in b["requests"]:
                m.requests[q["request_id"]] = {"requester": actor["id"],
                                               "payer": m.users[q["payer_handle"]]["id"],
                                               "amount": q["amount"], "status": "pending", "paid_count": 0}
        run_idem("/splits", body, exp[0], exp[1], ok_fn)

    elif op == "settle":
        n = rng.randint(1, 5)
        transfers = []
        for _ in range(n):
            a, b_ = rng.sample(handles, 2)
            transfers.append({"from_handle": a, "to_handle": b_, "amount": rng.randint(1, 3000),
                              "visibility": rng.choice(["public", "private"])})
        body = {"transfers": transfers}
        net = {}
        for t in transfers:
            net[t["from_handle"]] = net.get(t["from_handle"], 0) - t["amount"]
            net[t["to_handle"]] = net.get(t["to_handle"], 0) + t["amount"]
        if actor["id"] not in m.operators:
            exp = (403, "forbidden")
        elif any(m.users[h]["balance"] + d < 0 for h, d in net.items()):
            exp = (409, "insufficient_funds")
        else:
            exp = (201, None)

        def ok_fn(b):
            for h, d in net.items():
                m.users[h]["balance"] += d
            expect(len(b["payments"]) == n, "settlement payments count", trace)
            ca = {p["created_at"] for p in b["payments"]}
            expect(ca == {b["committed_at"]}, "member created_at != committed_at %s" % b, trace)
            for t, p in zip(transfers, b["payments"]):
                expect(p["from_handle"] == t["from_handle"] and p["to_handle"] == t["to_handle"]
                       and p["amount"] == t["amount"] and p["settlement_id"] == b["settlement_id"]
                       and p["request_id"] is None, "settlement member wrong %s" % p, trace)
                m.payments[p["payment_id"]] = {"from": m.users[t["from_handle"]]["id"],
                                               "to": m.users[t["to_handle"]]["id"],
                                               "amount": t["amount"], "vis": t["visibility"],
                                               "request_id": None, "settlement_id": b["settlement_id"]}
        run_idem("/settlements", body, exp[0], exp[1], ok_fn)

    elif op == "replay" and keys:
        h, key, path, body = rng.choice(keys)
        if body is None:
            return
        u = m.users[h]
        orig = m.idem[(u["id"], key, path)][1]
        st, b = call("POST", path, body, token=u["token"], key=key)
        trace.append([h, "REPLAY", path, body, st])
        expect(st == 200 and b == orig, "replay %s: %s body equal=%s" % (path, st, b == orig), trace)
        # different body with the same key -> 409 (also with an invalid body)
        bad = dict(body)
        bad["amount" if "amount" in bad else "visibility"] = rng.choice([-5, "zzz"])
        if path.endswith("/pay"):
            bad = {"visibility": "public"} if body == {} else {}
        if path == "/settlements":
            bad = {"transfers": []}
        st, b = call("POST", path, bad, token=u["token"], key=key)
        trace.append([h, "REUSE", path, bad, st, code_of(b)])
        expect(st == 409 and code_of(b) == "idempotency_key_reuse",
               "key reuse %s %s -> %s %s" % (path, bad, st, code_of(b)), trace)

    elif op == "reuse" and keys:
        # a key whose request failed with 4xx is treated as a first use
        failed = [k for k in keys if k[3] is None and k[0] == actor_h]
        if not failed:
            return
        _, key, path, _ = rng.choice(failed)
        if path != "/payments":
            return
        others = [h for h in handles if h != actor_h]
        body = {"to_handle": rng.choice(others), "amount": 1}
        exp = 201 if actor["balance"] >= 1 else 409
        st, b = call("POST", path, body, token=actor["token"], key=key)
        trace.append([actor_h, "FAILED-KEY-REUSE", path, body, st])
        expect(st == exp, "failed key reuse -> %s want %s" % (st, exp), trace)
        if st == 201:
            to = m.users[body["to_handle"]]
            actor["balance"] -= 1
            to["balance"] += 1
            m.payments[b["payment_id"]] = {"from": actor["id"], "to": to["id"], "amount": 1,
                                           "vis": "public", "request_id": None, "settlement_id": None}
            m.idem[(actor["id"], key, path)] = (canon(body), b)
            keys.remove((actor_h, key, path, None))
            keys.append((actor_h, key, path, body))


def login_all(m, trace):
    for h, u in m.users.items():
        st, b = call("POST", "/auth/login", {"email": u["email"], "password": u["password"]})
        expect(st == 200 and b["user_id"] == u["id"], "login %s -> %s" % (h, st), trace)
        u["token"] = b["token"]


def run_sequence(seed, steps):
    rng = random.Random(seed)
    fx = make_fixture(rng)
    st, _ = call("POST", "/_test/reset", fx)
    trace = [["reset", seed]]
    expect(st == 204, "reset -> %s" % st, trace)
    m = Model(fx)
    login_all(m, trace)
    keys = []
    snap = None
    for i in range(steps):
        step(m, rng, trace, keys)
        check_invariants(m, trace)
        if i % 25 == 24:
            check_views(m, trace)
        if i == steps // 3:
            st, exp_ = call("GET", "/_test/export")
            expect(st == 200 and exp_["track"] == "pocketful" and exp_["format_version"] == 1,
                   "export", trace)
            snap = (exp_, copy.deepcopy(m.__dict__), list(keys))
        if i == 2 * steps // 3 and snap:
            st, _ = call("POST", "/_test/import", snap[0])
            trace.append(["import-snapshot", st])
            expect(st == 204, "import -> %s" % st, trace)
            m.__dict__ = copy.deepcopy(snap[1])
            keys[:] = snap[2]
            check_invariants(m, trace)   # old tokens still valid, balances restored
            check_views(m, trace)
    check_views(m, trace)


# --------------------------------------------------------------------------- concurrency

def concurrent_phase(seed):
    rng = random.Random(seed)
    users = [{"id": "c%d" % i, "email": "c%d@example.com" % i, "password": "password!",
              "display_name": "C", "handle": "c%d" % i, "balance": rng.choice([0, 50, 300, 1000])}
             for i in range(6)]
    fx = {"currency": "EUR", "minor_units": 2, "users": users, "payments": [], "requests": [],
          "settlement_operator_ids": ["c0"]}
    trace = [["concurrent", seed]]
    expect(call("POST", "/_test/reset", fx)[0] == 204, "reset", trace)
    m = Model(fx)
    login_all(m, trace)
    hs = list(m.users)
    # a few requests to race on
    rids = []
    for i in range(4):
        a, b = rng.sample(hs, 2)
        st, r = call("POST", "/requests", {"payer_handle": b, "amount": rng.randint(1, 400)},
                     token=m.users[a]["token"], key="mk%d" % i)
        rids.append((r["request_id"], b, a))
    shared_key_body = {"to_handle": hs[1], "amount": 7}

    def job(j):
        r = random.Random(seed * 1000 + j)
        kind = r.choice(["pay", "pay", "payreq", "cancel", "decline", "settle", "samekey"])
        u = r.choice(hs)
        tok = m.users[u]["token"]
        if kind == "pay":
            to = r.choice([h for h in hs if h != u])
            return kind, call("POST", "/payments", {"to_handle": to, "amount": r.randint(1, 400)},
                              token=tok, key="cp%d-%d" % (seed, j))
        if kind == "payreq":
            rid, payer, _ = r.choice(rids)
            return kind, call("POST", "/requests/%s/pay" % rid, {}, token=m.users[payer]["token"],
                              key="cr%d-%d" % (seed, j))
        if kind == "cancel":
            rid, _, req_ = r.choice(rids)
            return kind, call("POST", "/requests/%s/cancel" % rid, {}, token=m.users[req_]["token"])
        if kind == "decline":
            rid, payer, _ = r.choice(rids)
            return kind, call("POST", "/requests/%s/decline" % rid, {}, token=m.users[payer]["token"])
        if kind == "settle":
            ts = []
            for _ in range(r.randint(1, 4)):
                a, b = r.sample(hs, 2)
                ts.append({"from_handle": a, "to_handle": b, "amount": r.randint(1, 600)})
            return kind, call("POST", "/settlements", {"transfers": ts}, token=m.users["c0"]["token"],
                              key="cs%d-%d" % (seed, j))
        return kind, call("POST", "/payments", shared_key_body, token=m.users[hs[0]]["token"],
                          key="SAME-%d" % seed)

    stop = threading.Event()
    seen_bad = []

    def watcher():
        while not stop.is_set():
            tot = 0
            for h in hs:
                st, me = call("GET", "/me", token=m.users[h]["token"])
                if st != 200 or me["balance"] < 0:
                    seen_bad.append((h, st, me))
                tot += me["balance"] if st == 200 else 0
    wt = threading.Thread(target=watcher)
    wt.start()
    with ThreadPoolExecutor(max_workers=50) as ex:
        results = list(ex.map(job, range(150)))
    stop.set()
    wt.join()
    expect(not seen_bad, "negative/failed balance observed during burst: %s" % seen_bad[:3], trace)
    for kind, (st, b) in results:
        expect(st < 500, "5xx under load: %s %s %s" % (kind, st, b), trace)
    same = [(st, b) for kind, (st, b) in results if kind == "samekey"]
    if same:
        expect(sum(1 for st, _ in same if st == 201) == 1 or
               (sum(1 for st, _ in same if st == 201) == 0 and all(st == 409 for st, _ in same)),
               "same-key burst statuses %s" % [st for st, _ in same], trace)
        okb = [b for st, b in same if st in (200, 201)]
        expect(all(b == okb[0] for b in okb), "same-key bodies differ", trace)
    tot = 0
    for h in hs:
        st, me = call("GET", "/me", token=m.users[h]["token"])
        expect(me["balance"] >= 0, "negative after burst", trace)
        tot += me["balance"]
    expect(tot == m.total, "sum after burst %s != %s" % (tot, m.total), trace)
    # each request moved money at most once
    st, feed = list_all("/activity", "payments", m.users[hs[0]]["token"])
    by_req = {}
    for p in feed:
        if p["request_id"]:
            by_req[p["request_id"]] = by_req.get(p["request_id"], 0) + 1
    for rid, _, req_ in rids:
        st, lst = list_all("/requests", "requests", m.users[req_]["token"])
        r = [x for x in lst if x["request_id"] == rid][0]
        expect(by_req.get(rid, 0) <= 1, "request %s paid %d times" % (rid, by_req.get(rid, 0)), trace)
        expect((r["status"] == "paid") == (by_req.get(rid, 0) == 1),
               "request %s status %s vs %d payments" % (rid, r["status"], by_req.get(rid, 0)), trace)
    samekey_pays = [p for p in feed if p["from_handle"] == hs[0] and p["to_handle"] == hs[1]
                    and p["amount"] == 7]
    if same and any(st == 201 for st, _ in same):
        expect(len(samekey_pays) >= 1, "same-key payment missing", trace)


def main():
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--steps", type=int, default=150)
    ap.add_argument("--bursts", type=int, default=5)
    a = ap.parse_args()
    BASE = a.base.rstrip("/")
    failures = 0
    for seed in range(1, a.seeds + 1):
        try:
            run_sequence(seed, a.steps)
            print("seed %d: ok" % seed)
        except Mismatch as e:
            failures += 1
            print("seed %d: MISMATCH %s" % (seed, e))
    for seed in range(1, a.bursts + 1):
        try:
            concurrent_phase(seed)
            print("burst %d: ok" % seed)
        except Mismatch as e:
            failures += 1
            print("burst %d: MISMATCH %s" % (seed, e))
    for k in sorted(STATS, key=str):
        if k[1] != "/me":
            print("  %-6s %-24s %s x%d" % (k[0], k[1], k[2], STATS[k]))
    print("FAILURES: %d" % failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
