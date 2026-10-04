#!/usr/bin/env python3
"""Reviewer's stage-4 probes (refunds, correction batches), written from the stage-4
specification only.

Usage: python3 probes_s4.py http://localhost:8080
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

BASE = sys.argv[1].rstrip("/")
RESULTS = []


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
        try:
            return e.code, json.loads(t) if t else None
        except ValueError:
            return e.code, {"_raw": t[:100]}


def code(b):
    try:
        return b["error"]["code"]
    except (TypeError, KeyError):
        return None


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))


def expect(name, resp, status, ecode=None):
    st, b = resp
    check(name, st == status and (ecode is None or code(b) == ecode), "got %s %s" % (st, str(b)[:220]))


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


NOW = datetime.now(timezone.utc).replace(microsecond=0)
T1 = NOW - timedelta(days=5)


def fixture(**kw):
    fx = {"currency": "EUR", "minor_units": 2, "users": [
        {"id": "u_a", "email": "a@x.io", "password": "password", "display_name": "A", "handle": "a", "balance": 9500},
        {"id": "u_b", "email": "b@x.io", "password": "password", "display_name": "B", "handle": "b", "balance": 500},
        {"id": "u_c", "email": "c@x.io", "password": "password", "display_name": "C", "handle": "c", "balance": 1000},
        {"id": "u_op", "email": "op@x.io", "password": "password", "display_name": "Op", "handle": "op", "balance": 0}],
        "payments": [{"id": "p_seed", "from_user_id": "u_a", "to_user_id": "u_b", "amount": 500, "note": "seed note",
                      "visibility": "private", "created_at": iso(T1)}],
        "requests": [], "authorizations": [], "settlement_operator_ids": ["u_op"]}
    fx.update(kw)
    return fx


def reset(fx=None):
    fx = fx or fixture()
    st, b = call("POST", "/_test/reset", fx)
    assert st == 204, (st, b)
    return {u["handle"]: call("POST", "/auth/login", {"email": u["email"], "password": "password"})[1]["token"]
            for u in fx["users"]}


def me(t):
    return call("GET", "/me", token=t)[1]


def corr(pid, rev, amount, eff, reason="r"):
    return {"payment_id": pid, "expected_revision": rev, "amount": amount, "effective_at": eff, "reason": reason}


def main():
    T = reset()
    a, b, c, op = T["a"], T["b"], T["c"], T["op"]

    # ---------------- refunds
    path = "/payments/p_seed/refunds"
    expect("refund no token -> 401", call("POST", path, {"amount": 1}, key="r"), 401, "unauthenticated")
    expect("refund no key -> 400", call("POST", path, {"amount": 1}, token=b), 400, "missing_idempotency_key")
    expect("sender cannot refund -> 403", call("POST", path, {"amount": 1}, token=a, key="r"), 403, "forbidden")
    expect("third party cannot refund -> 403", call("POST", path, {"amount": 1}, token=c, key="r"), 403, "forbidden")
    expect("refund unknown -> 404", call("POST", "/payments/nope/refunds", {"amount": 1}, token=b, key="r"), 404, "not_found")
    for i, bad in enumerate([0, -1, 1.5, "10", True, 1000000001, None]):
        expect("refund amount %r -> 422" % (bad,), call("POST", path, {"amount": bad}, token=b, key="ra%d" % i),
               422, "validation_failed")
    expect("refund missing amount -> 422", call("POST", path, {}, token=b, key="ram"), 422, "validation_failed")
    expect("refund over amount -> 422", call("POST", path, {"amount": 501}, token=b, key="r1"), 422, "refund_exceeds_payment")
    st, rf = call("POST", path, {"amount": 200, "zz": 1}, token=b, key="r2")
    check("refund 201 shape", st == 201 and rf["refund_of"] == "p_seed" and rf["from_handle"] == "b" and rf["to_handle"] == "a"
          and rf["amount"] == 200 and rf["request_id"] is None and rf["authorization_id"] is None
          and rf["note"] == "seed note" and rf["visibility"] == "private" and rf["payment_id"] != "p_seed", (st, rf))
    check("refund moves money", me(a)["balance"] == 9700 and me(b)["balance"] == 300, (me(a), me(b)))
    st, rep = call("POST", path, {"amount": 200, "zz": 1}, token=b, key="r2")
    check("refund replay 200 identical", st == 200 and rep == rf, st)
    expect("refund key reuse -> 409", call("POST", path, {"amount": 100}, token=b, key="r2"), 409, "idempotency_key_reuse")
    expect("cumulative refunds over amount -> 422", call("POST", path, {"amount": 301}, token=b, key="r3"), 422, "refund_exceeds_payment")
    expect("refund of a refund -> 422", call("POST", "/payments/%s/refunds" % rf["payment_id"], {"amount": 1}, token=a, key="rr"),
           422, "invalid_refund_target")
    st, act = call("GET", "/activity?limit=200", token=a)
    others = [p for p in act["payments"] if p["payment_id"] != rf["payment_id"]]
    check("other payments carry refund_of null", others and all(p.get("refund_of", "MISSING") is None for p in others), others[:1])
    check("refund appears in feed for parties", any(p["payment_id"] == rf["payment_id"] for p in act["payments"]), "")
    st, act_c = call("GET", "/activity?limit=200", token=c)
    check("private refund hidden from third party", all(p["payment_id"] != rf["payment_id"] for p in act_c["payments"]), "")
    st, s = call("GET", "/statement", token=b)
    check("refund is a statement entry", any(e["payment"]["payment_id"] == rf["payment_id"] and e["delta"] == -200
                                             for e in s["entries"]), s)
    expect("refund payment cannot be corrected", call("POST", "/payments/%s/corrections" % rf["payment_id"],
           {"expected_revision": 1, "amount": 1, "effective_at": rf["created_at"], "reason": "x"}, token=b, key="rc"),
           422, "linked_payment_immutable")
    expect("correction below refunded -> 422", call("POST", "/payments/p_seed/corrections",
           {"expected_revision": 1, "amount": 199, "effective_at": iso(T1), "reason": "x"}, token=a, key="cb"),
           422, "refund_exceeds_payment")
    st, x = call("POST", "/payments/p_seed/corrections", {"expected_revision": 1, "amount": 250, "effective_at": iso(T1),
                                                           "reason": "x"}, token=a, key="cok")
    check("correction down to refunded+50 ok", st == 201, (st, x))
    expect("refund over corrected amount -> 422", call("POST", path, {"amount": 51}, token=b, key="r4"), 422, "refund_exceeds_payment")
    st, _ = call("POST", path, {"amount": 50}, token=b, key="r5")
    check("refund exactly remaining corrected amount", st == 201, st)
    tot = sum(me(t)["balance"] for t in (a, b, c, op))
    check("total conserved", tot == 11000, tot)

    # refunds from available funds; request payments and captures
    T = reset()
    a, b, c, op = T["a"], T["b"], T["c"], T["op"]
    call("POST", "/authorizations", {"to_handle": "c", "amount": 400}, token=b, key="hold")  # b available 100
    expect("refund beyond available -> insufficient_funds", call("POST", "/payments/p_seed/refunds", {"amount": 101},
           token=b, key="ri"), 409, "insufficient_funds")
    check("refused refund changes nothing", me(b)["balance"] == 500 and me(b)["held"] == 400, me(b))
    expect("correction decrease beyond receiver available -> insufficient_funds",
           call("POST", "/payments/p_seed/corrections", {"expected_revision": 1, "amount": 300, "effective_at": iso(T1),
                                                          "reason": "x"}, token=a, key="cav"), 409, "insufficient_funds")
    st, rq = call("POST", "/requests", {"payer_handle": "a", "amount": 300}, token=c, key="rq")
    st, rp = call("POST", "/requests/%s/pay" % rq["request_id"], {}, token=a, key="rqp")
    st, rr = call("POST", "/payments/%s/refunds" % rp["payment_id"], {"amount": 300}, token=c, key="rqr")
    check("refund of request payment", st == 201 and rr["refund_of"] == rp["payment_id"] and rr["request_id"] is None, (st, rr))
    st, lst = call("GET", "/requests", token=c)
    check("refund does not reopen request", [r for r in lst["requests"] if r["request_id"] == rq["request_id"]][0]["status"] == "paid", "")
    st, au = call("POST", "/authorizations", {"to_handle": "c", "amount": 1000}, token=a, key="au2")
    st, cp = call("POST", "/authorizations/%s/capture" % au["authorization_id"], {"amount": 600}, token=c, key="cp")
    held_before = me(a)["held"]
    st, cr = call("POST", "/payments/%s/refunds" % cp["payment_id"], {"amount": 600}, token=c, key="cpr")
    check("refund of capture", st == 201 and cr["refund_of"] == cp["payment_id"] and cr["authorization_id"] is None, (st, cr))
    st, al = call("GET", "/authorizations", token=a)
    x = [z for z in al["authorizations"] if z["authorization_id"] == au["authorization_id"]][0]
    check("refund does not reopen authorization or restore hold", x["status"] == "captured" and me(a)["held"] == held_before, x)

    # ---------------- correction batches
    T = reset()
    a, b, c, op = T["a"], T["b"], T["c"], T["op"]
    st, se = call("POST", "/settlements", {"transfers": [{"from_handle": "a", "to_handle": "b", "amount": 100},
                                                         {"from_handle": "a", "to_handle": "c", "amount": 50}]}, token=op, key="se")
    m1, m2 = [p["payment_id"] for p in se["payments"]]
    st, p2 = call("POST", "/payments", {"to_handle": "c", "amount": 300}, token=a, key="p2")
    st, au = call("POST", "/authorizations", {"to_handle": "b", "amount": 100}, token=a, key="au")
    st, cp = call("POST", "/authorizations/%s/capture" % au["authorization_id"], {}, token=b, key="cp")
    st, rf = call("POST", "/payments/p_seed/refunds", {"amount": 10}, token=b, key="rf")
    eff = se["committed_at"]
    good = {"corrections": [corr(m1, 1, 0, eff, "reversal"), corr(m2, 1, 0, eff, "reversal")]}
    expect("batch no token -> 401", call("POST", "/correction-batches", good, key="k"), 401, "unauthenticated")
    expect("batch non-operator -> 403", call("POST", "/correction-batches", good, token=a, key="k"), 403, "forbidden")
    expect("batch no key -> 400", call("POST", "/correction-batches", good, token=op), 400, "missing_idempotency_key")
    for i, bad in enumerate([{}, {"corrections": []}, {"corrections": "x"}, {"corrections": [1]},
                             {"corrections": [corr(p2["payment_id"], 1, 1, p2["created_at"])] * 2},
                             {"corrections": [corr("p_seed", 1, 1, iso(T1), "")]},
                             {"corrections": [corr("p_seed", 0, 1, iso(T1))]},
                             {"corrections": [corr("p_seed", 1, -1, iso(T1))]},
                             {"corrections": [corr("p_seed", 1, 1, iso(NOW + timedelta(hours=1)))]},
                             {"corrections": [corr("p_seed", 1, 1, "2026-09-20T12:00:00")]}]):
        expect("batch invalid %d -> 422" % i, call("POST", "/correction-batches", bad, token=op, key="bad%d" % i), 422, "validation_failed")
    expect("batch 33 items -> 422", call("POST", "/correction-batches",
           {"corrections": [corr("x%d" % i, 1, 1, iso(T1)) for i in range(33)]}, token=op, key="b33"), 422, "validation_failed")
    expect("batch unknown payment -> 404", call("POST", "/correction-batches", {"corrections": [corr("nope", 1, 1, iso(T1))]},
           token=op, key="b404"), 404, "not_found")
    expect("batch stale -> 409", call("POST", "/correction-batches", {"corrections": [corr("p_seed", 2, 1, iso(T1))]},
           token=op, key="bst"), 409, "stale_revision")
    expect("batch capture -> 422", call("POST", "/correction-batches", {"corrections": [corr(cp["payment_id"], 1, 1, cp["created_at"])]},
           token=op, key="bcp"), 422, "linked_payment_immutable")
    expect("batch refund -> 422", call("POST", "/correction-batches", {"corrections": [corr(rf["payment_id"], 1, 1, rf["created_at"])]},
           token=op, key="brf"), 422, "linked_payment_immutable")
    expect("batch below refunded -> 422", call("POST", "/correction-batches", {"corrections": [corr("p_seed", 1, 5, iso(T1))]},
           token=op, key="bre"), 422, "refund_exceeds_payment")
    expect("incomplete settlement -> 422", call("POST", "/correction-batches", {"corrections": [corr(m1, 1, 0, eff)]},
           token=op, key="binc"), 422, "incomplete_settlement")
    t_eff = datetime.fromisoformat(eff)
    expect("members with different effective instants -> 422", call("POST", "/correction-batches",
           {"corrections": [corr(m1, 1, 0, eff), corr(m2, 1, 0, iso(t_eff - timedelta(seconds=1)))]}, token=op, key="bdiff"),
           422, "validation_failed")
    expect("item error precedes completeness", call("POST", "/correction-batches",
           {"corrections": [corr(m1, 1, 0, eff), corr("nope", 1, 1, iso(T1))]}, token=op, key="bprec"), 404, "not_found")
    expect("single correction of settlement member still immutable", call("POST", "/payments/%s/corrections" % m1,
           {"expected_revision": 1, "amount": 0, "effective_at": eff, "reason": "x"}, token=a, key="single-member"),
           422, "linked_payment_immutable")
    before = {h: me(T[h])["balance"] for h in T}
    check("rejected batches changed nothing", before == {"a": 9500 - 150 - 300 - 100 + 10, "b": 500 + 100 + 100 - 10,
                                                          "c": 1000 + 50 + 300, "op": 0}, before)
    other_offset = t_eff.astimezone(timezone(timedelta(hours=3))).isoformat()
    body = {"corrections": [corr(m1, 1, 0, eff, "reversal"), dict(corr(m2, 1, 0, other_offset, "reversal"), zz=1)]}
    time.sleep(1.1)
    st, bt = call("POST", "/correction-batches", body, token=op, key="b1")
    revs = bt.get("revisions", []) if isinstance(bt, dict) else []
    check("batch 201 shape", st == 201 and bt.get("correction_batch_id") and bt.get("recorded_at") and
          [r["payment_id"] for r in revs] == [m1, m2] and all(r["recorded_at"] == bt["recorded_at"] and
          r["correction_batch_id"] == bt["correction_batch_id"] and r["revision"] == 2 and r["amount"] == 0 for r in revs), (st, bt))
    check("batch moved money", me(a)["balance"] == before["a"] + 150 and me(b)["balance"] == before["b"] - 100
          and me(c)["balance"] == before["c"] - 50, "")
    st, rep = call("POST", "/correction-batches", body, token=op, key="b1")
    check("batch replay 200 identical", st == 200 and rep == bt, st)
    expect("batch key reuse -> 409", call("POST", "/correction-batches", good, token=op, key="b1"), 409, "idempotency_key_reuse")
    st, sr = call("POST", "/settlements", {"transfers": [{"from_handle": "a", "to_handle": "b", "amount": 100},
                                                         {"from_handle": "a", "to_handle": "c", "amount": 50}]}, token=op, key="se")
    check("original settlement retry returns original body", st == 200 and sr == se, st)
    st, rv = call("GET", "/payments/%s/revisions" % m1, token=b)
    check("member revisions expose batch id", st == 200 and rv["revisions"][-1].get("correction_batch_id") == bt["correction_batch_id"], rv)
    st, act = call("GET", "/activity?limit=200", token=a)
    check("activity keeps original member", [p["amount"] for p in act["payments"] if p["payment_id"] == m1] == [100], "")
    expect("refund of settlement member allowed", call("POST", "/payments/%s/refunds" % m1, {"amount": 1}, token=b, key="rm"),
           422, "refund_exceeds_payment")  # corrected to 0, so nothing to refund

    # combined affordability: item 2 alone would overdraw b, item 1 credits b first
    T = reset(fixture(payments=[
        {"id": "p_cb", "from_user_id": "u_c", "to_user_id": "u_b", "amount": 100, "note": "", "visibility": "public", "created_at": iso(T1)},
        {"id": "p_ba", "from_user_id": "u_b", "to_user_id": "u_a", "amount": 100, "note": "", "visibility": "public",
         "created_at": iso(T1 + timedelta(hours=1))}],
        users=[{"id": "u_a", "email": "a@x.io", "password": "password", "display_name": "A", "handle": "a", "balance": 100},
               {"id": "u_b", "email": "b@x.io", "password": "password", "display_name": "B", "handle": "b", "balance": 0},
               {"id": "u_c", "email": "c@x.io", "password": "password", "display_name": "C", "handle": "c", "balance": 900},
               {"id": "u_op", "email": "op@x.io", "password": "password", "display_name": "Op", "handle": "op", "balance": 0}]))
    a, b, c, op = T["a"], T["b"], T["c"], T["op"]
    expect("alone: increase b->a by 300 -> insufficient", call("POST", "/correction-batches",
           {"corrections": [corr("p_ba", 1, 400, iso(T1 + timedelta(hours=1)))]}, token=op, key="alone"), 409, "insufficient_funds")
    st, x = call("POST", "/correction-batches", {"corrections": [corr("p_ba", 1, 400, iso(T1 + timedelta(hours=1))),
                                                                  corr("p_cb", 1, 400, iso(T1))]}, token=op, key="combined")
    check("combined effect affordable -> 201", st == 201, (st, x))
    st, x = call("POST", "/correction-batches", {"corrections": [corr("p_ba", 2, 400, iso(T1 - timedelta(days=1)))]},
                 token=op, key="hist")
    check("moving b's debit before its credit -> historical_overdraft", st == 409 and code(x) == "historical_overdraft", (st, x))
    tot = sum(me(t)["balance"] for t in (a, b, c, op))
    check("total conserved after batches", tot == 1000, tot)

    # snapshots frozen; concurrency between a batch and a single correction on the same revision
    st, s0 = call("GET", "/statement?limit=1", token=b)
    st, f0 = call("GET", "/statement?" + urllib.parse.urlencode({"snapshot": s0["snapshot"], "limit": 200}), token=b)
    T2 = reset(fixture())
    expect("snapshot from before reset -> 404", call("GET", "/statement?snapshot=" + s0["snapshot"], token=T2["b"]), 404, "not_found")
    a, b, op = T2["a"], T2["b"], T2["op"]
    st, s0 = call("GET", "/statement?limit=1", token=a)
    st, f0 = call("GET", "/statement?" + urllib.parse.urlencode({"snapshot": s0["snapshot"], "limit": 200}), token=a)
    time.sleep(1.1)

    def race(i):
        if i % 2:
            return call("POST", "/correction-batches", {"corrections": [corr("p_seed", 1, 400 + i, iso(T1))]}, token=op, key="rb%d" % i)[0]
        return call("POST", "/payments/p_seed/corrections", {"expected_revision": 1, "amount": 400 + i, "effective_at": iso(T1),
                                                              "reason": "x"}, token=a, key="rs%d" % i)[0]
    with ThreadPoolExecutor(20) as ex:
        res = list(ex.map(race, range(20)))
    check("batch vs single corrections on one revision: exactly one wins", res.count(201) == 1 and res.count(409) == 19, sorted(set(res)))
    st, f1 = call("GET", "/statement?" + urllib.parse.urlencode({"snapshot": s0["snapshot"], "limit": 200}), token=a)
    check("snapshot unchanged after batch/corrections", f0 == f1, "")

    # export/import keeps batches and refunds
    st, ex = call("GET", "/_test/export")
    reset(fixture())
    st, _ = call("POST", "/_test/import", ex)
    check("stage-4 export re-imports", st == 204, st)
    st, f2 = call("GET", "/statement?" + urllib.parse.urlencode({"snapshot": s0["snapshot"], "limit": 200}), token=a)
    check("snapshot survives export/import", st == 200 and f2 == f0, st)

    fails = [r for r in RESULTS if not r[1]]
    for name, ok, det in RESULTS:
        print("%s  %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else "  -> %s" % (det,)))
    print("%d probes, %d failed" % (len(RESULTS), len(fails)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
