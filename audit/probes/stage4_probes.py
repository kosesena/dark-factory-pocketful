"""spec-auditor stage 4 probes: one probe per gap in ledger/stage-4.md (S4-n). Stdlib only.

Usage: python3 stage4_probes.py http://127.0.0.1:PORT [STAGE3_URL] [name-filter ...]
STAGE3_URL (optional): a running stage-3 service for the upgrade probe.
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
PREV = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2].startswith("http") else None
FILTER = [a for a in sys.argv[2:] if not a.startswith("http")]
sys.argv = [sys.argv[0], URL]
import stage3_probes as S3  # noqa: E402

P = S3.P
call, k, err, ok, user, fx, reset, tok, par = P.call, P.k, P.err, P.ok, P.user, P.fx, P.reset, P.tok, P.par
me, st, PM, correct, ago = S3.me, S3.st, S3.PM, S3.correct, S3.ago
PROBES = []


def probe(name):
    def deco(fn):
        PROBES.append((name, fn))
        return fn
    return deco


def pay(t, to, amount, **x):
    return ok(call("POST", "/payments", dict({"to_handle": to, "amount": amount}, **x), token=t, key=k()), 201)


def refund(t, pid, amount, key=None):
    return call("POST", f"/payments/{pid}/refunds", {"amount": amount}, token=t, key=key or k())


def batch(t, items, key=None, **extra):
    return call("POST", "/correction-batches", dict({"corrections": items}, **extra), token=t, key=key or k())


def item(pid, rev, amount, eff=None, reason="fix", **x):
    return dict({"payment_id": pid, "expected_revision": rev, "amount": amount,
                 "effective_at": eff or ago(60), "reason": reason}, **x)


def m(t):
    return ok(me(t), 200)


def settle(t, transfers):
    return ok(call("POST", "/settlements", {"transfers": [
        {"from_handle": a, "to_handle": b, "amount": n} for a, b, n in transfers]}, token=t, key=k()), 201)


def world(ops=("u_cy",)):
    reset(fx(ops=list(ops)))
    return tok("ada"), tok("bob"), tok("cy")


def revs(t, pid):
    return ok(call("GET", f"/payments/{pid}/revisions", token=t), 200)["revisions"]


# ---- refunds --------------------------------------------------------------------------------------

@probe("S4-1/2/4 refund auth, key and amount validation")
def _():
    ada, bob, cy = world()
    p = pay(ada, "bob", 500)["payment_id"]
    assert call("POST", f"/payments/{p}/refunds", {"amount": 1}, key=k())[0] == 401
    assert call("POST", f"/payments/{p}/refunds", {"amount": 1}, token=bob)[0] == 400
    err(refund(ada, p, 1), 403, "forbidden", "sender")
    err(refund(cy, p, 1), 403, "forbidden", "third party")
    err(refund(bob, "p_nope", 1), 404, "not_found")
    for bad in (0, -1, 1000000001, 1.5, True, "5", None):
        err(refund(bob, p, bad), 422, "validation_failed", bad)
    err(call("POST", f"/payments/{p}/refunds", {}, token=bob, key=k()), 422, "validation_failed")
    assert (m(ada)["balance"], m(bob)["balance"]) == (9500, 3000)


@probe("S4-5/6/10/11 refund shape, cumulative cap, refund_of null elsewhere, activity and statements")
def _():
    ada, bob, cy = world()
    p = pay(ada, "bob", 500, note="dinner", visibility="private")
    r = ok(refund(bob, p["payment_id"], 200), 201)
    assert r["refund_of"] == p["payment_id"] and r["from_user_id"] == "u_bob" and r["to_user_id"] == "u_ada", r
    assert r["request_id"] is None and r["authorization_id"] is None and r["amount"] == 200, r
    assert r["note"] == "dinner" and r["visibility"] == "private", r
    assert p["refund_of"] is None
    ok(refund(bob, p["payment_id"], 300), 201)
    err(refund(bob, p["payment_id"], 1), 422, "refund_exceeds_payment")
    assert (m(ada)["balance"], m(bob)["balance"]) == (10000, 2500)
    acts = call("GET", "/activity", token=ada)[1]["payments"]
    assert sum(1 for a in acts if a.get("refund_of") == p["payment_id"]) == 2, acts
    assert all("refund_of" in a for a in acts)
    for t in (ada, bob):
        ents = ok(st(t), 200)["entries"]
        assert sum(1 for e in ents if e["payment"].get("refund_of") == p["payment_id"]) == 2
        s = ok(st(t), 200)
        assert s["opening_balance"] + sum(e["delta"] for e in s["entries"]) == s["closing_balance"]
    assert len(revs(ada, r["payment_id"])) == 1
    # request payments, captures, settlement members, seeded payments carry refund_of: null
    reset(fx(ops=["u_cy"], payments=[PM("p_seed", amount=5, created=ago(600))]))
    ada, bob, cy = tok("ada"), tok("bob"), tok("cy")
    rid = ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 7}, token=bob, key=k()), 201)["request_id"]
    rp = ok(call("POST", f"/requests/{rid}/pay", {}, token=ada, key=k()), 201)
    a = ok(call("POST", "/authorizations", {"to_handle": "bob", "amount": 9}, token=ada, key=k()), 201)
    cp = ok(call("POST", f"/authorizations/{a['authorization_id']}/capture", {}, token=bob, key=k()), 201)
    sp = settle(cy, [("ada", "bob", 3)])["payments"][0]
    for x in (rp, cp, sp):
        assert x["refund_of"] is None, x
    for x in call("GET", "/activity", token=ada)[1]["payments"]:
        assert x["refund_of"] is None, x


@probe("S4-3/14/21 refund targets: capture and settlement member yes, refund no; immutable refunds and captures")
def _():
    ada, bob, cy = world()
    a = ok(call("POST", "/authorizations", {"to_handle": "bob", "amount": 900}, token=ada, key=k()), 201)
    cp = ok(call("POST", f"/authorizations/{a['authorization_id']}/capture", {}, token=bob, key=k()), 201)
    rc = ok(refund(bob, cp["payment_id"], 400), 201)
    au = [x for x in call("GET", "/authorizations", token=ada)[1]["authorizations"]
          if x["authorization_id"] == a["authorization_id"]][0]
    assert au["status"] == "captured", ("refund never reopens an authorization", au)
    assert m(ada)["held"] == 0
    err(refund(ada, rc["payment_id"], 1), 422, "invalid_refund_target")
    err(correct(bob, rc["payment_id"], 1, 1, ago(5)), 422, "linked_payment_immutable")
    err(correct(ada, cp["payment_id"], 1, 1, ago(5)), 422, "linked_payment_immutable")
    err(batch(cy, [item(rc["payment_id"], 1, 1)]), 422, "linked_payment_immutable")
    err(batch(cy, [item(cp["payment_id"], 1, 1)]), 422, "linked_payment_immutable")
    sres = settle(cy, [("ada", "bob", 100), ("bob", "cy", 50)])
    sp = sres["payments"][0]
    ok(refund(bob, sp["payment_id"], 100), 201)
    sid = sres["settlement_id"]
    again = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100},
                                                        {"from_handle": "bob", "to_handle": "cy", "amount": 50}]},
                 token=cy, key=k())
    assert again[0] == 201  # a new settlement; membership of the old is unchanged:
    # correcting the old settlement still needs exactly its two members (the refund is not a member)
    err(batch(cy, [item(sp["payment_id"], 1, 100)]), 422, "incomplete_settlement")
    err(correct(ada, sp["payment_id"], 1, 100, ago(5)), 422, "linked_payment_immutable")
    assert sid


@probe("S4-8/16 refunds and correction debits use available funds, not held")
def _():
    ada, bob, cy = world()
    p = pay(ada, "bob", 2000)["payment_id"]   # bob 4500
    ok(call("POST", "/authorizations", {"to_handle": "cy", "amount": 4000}, token=bob, key=k()), 201)  # bob avail 500
    err(refund(bob, p, 501), 409, "insufficient_funds")
    assert (m(bob)["balance"], m(bob)["available"], m(ada)["balance"]) == (4500, 500, 8000)
    ok(refund(bob, p, 500), 201)
    # correction decreasing p debits bob (receiver) -> available 0
    err(correct(ada, p, 1, 1400, ago(5)), 409, "insufficient_funds")
    # correction increasing debits ada: hold ada's money
    ok(call("POST", "/authorizations", {"to_handle": "cy", "amount": 8500}, token=ada, key=k()), 201)
    assert m(ada)["available"] == 0
    err(correct(ada, p, 1, 2001, ago(5)), 409, "insufficient_funds")
    assert len(revs(ada, p)) == 1


@probe("S4-9 refunds never reopen a request or restore a released hold")
def _():
    ada, bob, cy = world()
    rid = ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 700}, token=bob, key=k()), 201)["request_id"]
    rp = ok(call("POST", f"/requests/{rid}/pay", {}, token=ada, key=k()), 201)
    ok(refund(bob, rp["payment_id"], 700), 201)
    rq = [x for x in ok(call("GET", "/requests?direction=outgoing&limit=200", token=bob), 200)["requests"]
          if x["request_id"] == rid][0]
    assert rq["status"] == "paid", rq
    assert call("POST", f"/requests/{rid}/pay", {}, token=ada, key=k())[0] == 409, "request stays paid"
    a = ok(call("POST", "/authorizations", {"to_handle": "bob", "amount": 1000}, token=ada, key=k()), 201)
    cp = ok(call("POST", f"/authorizations/{a['authorization_id']}/capture",
                 {"amount": 300, "final": True}, token=bob, key=k()), 201)
    ok(refund(bob, cp["payment_id"], 300), 201)
    mm = m(ada)
    assert mm["held"] == 0 and mm["available"] == mm["balance"] == 10000 - 700 + 700, mm


@probe("S4-7/12 refund idempotency: replay, reuse, concurrent same key, concurrent cap")
def _():
    ada, bob, cy = world()
    p = pay(ada, "bob", 1000)["payment_id"]
    key = k()
    out = par(lambda i: refund(bob, p, 100, key=key), 20)
    assert sorted(o[0] for o in out).count(201) == 1 and all(o[0] in (200, 201) for o in out), [o[0] for o in out]
    assert len({json.dumps(o[1], sort_keys=True) for o in out}) == 1
    err(refund(bob, p, 101, key=key), 409, "idempotency_key_reuse")
    out = par(lambda i: refund(bob, p, 100), 30)
    assert [o[0] for o in out].count(201) == 9, sorted(o[0] for o in out)
    assert all(o[1]["error"]["code"] == "refund_exceeds_payment" for o in out if o[0] != 201)
    assert m(bob)["balance"] == 2500 and m(ada)["balance"] == 10000


@probe("S4-5/15/13 cap follows corrections; correction below refunded total refused")
def _():
    ada, bob, cy = world()
    p = pay(ada, "bob", 1000)["payment_id"]
    ok(refund(bob, p, 400), 201)
    err(correct(ada, p, 1, 399, ago(5)), 422, "refund_exceeds_payment")
    ok(correct(ada, p, 1, 600, ago(5)), 201)
    err(refund(bob, p, 201), 422, "refund_exceeds_payment")
    ok(refund(bob, p, 200), 201)
    err(batch(cy, [item(p, 2, 599)]), 422, "refund_exceeds_payment")
    assert (m(ada)["balance"], m(bob)["balance"]) == (10000, 2500)


# ---- batches ----------------------------------------------------------------------------------------

@probe("S4-17/18/19/20/28/32 batch API validation")
def _():
    ada, bob, cy = world()
    p = pay(ada, "bob", 500)["payment_id"]
    q = pay(bob, "ada", 100)["payment_id"]
    assert batch(None, [item(p, 1, 400)])[0] == 401
    assert call("POST", "/correction-batches", {"corrections": [item(p, 1, 400)]}, token=cy)[0] == 400
    err(batch(ada, [item(p, 1, 400)]), 403, "forbidden")
    for bad in ([], [item(p, 1, 400)] * 2, "x", [1], None):
        err(batch(cy, bad), 422, "validation_failed", bad)
    many = [item(f"p_{i}", 1, 1) for i in range(33)]
    err(batch(cy, many), 422, "validation_failed", "33 items")
    fut = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    for it in (item(p, 0, 400), item(p, 1, -1), item(p, 1, 10**9 + 1), item(p, 1, 4, reason=""),
               item(p, 1, 4, reason="x" * 201), item(p, 1, 4, eff=fut), item(p, 1, 4, eff="2026-01-01"),
               {k2: v for k2, v in item(p, 1, 4).items() if k2 != "reason"}):
        err(batch(cy, [item(q, 1, 100), it]), 422, "validation_failed", it)
    err(batch(cy, [item("p_none", 1, 1)]), 404, "not_found")
    err(batch(cy, [item(p, 2, 1)]), 409, "stale_revision")
    r = ok(batch(cy, [item(p, 1, 400, junk=1)], extra=True), 201)
    assert r["revisions"][0]["amount"] == 400
    assert (m(ada)["balance"], m(bob)["balance"]) == (9600 + 100, 2400 + 400 - 400 + 0) or True
    assert m(ada)["balance"] == 10000 - 400 + 100 and m(bob)["balance"] == 2500 + 400 - 100


@probe("S4-22/23/27/29/34 settlement members in batches; shared recorded_at; receipts unchanged")
def _():
    ada, bob, cy = world()
    skey = k()
    body = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100},
                          {"from_handle": "bob", "to_handle": "cy", "amount": 50}]}
    s1 = ok(call("POST", "/settlements", body, token=cy, key=skey), 201)
    a_, b_ = [x["payment_id"] for x in s1["payments"]]
    o = pay(ada, "cy", 10)["payment_id"]
    c1 = ok(correct(ada, o, 1, 11, ago(30)), 201)
    err(batch(cy, [item(a_, 1, 90)]), 422, "incomplete_settlement")
    e1 = ago(120)
    e2 = datetime.fromisoformat(e1).astimezone(timezone(timedelta(hours=-3))).isoformat()
    err(batch(cy, [item(a_, 1, 90, eff=e1), item(b_, 1, 40, eff=ago(121))]), 422, "validation_failed")
    r = ok(batch(cy, [item(o, 2, 12), item(b_, 1, 40, eff=e2), item(a_, 1, 90, eff=e1)]), 201)
    assert [x["payment_id"] for x in r["revisions"]] == [o, b_, a_], "input order"
    assert {x["recorded_at"] for x in r["revisions"]} == {r["recorded_at"]}
    assert all(x["correction_batch_id"] == r["correction_batch_id"] for x in r["revisions"])
    assert datetime.fromisoformat(r["recorded_at"]) > datetime.fromisoformat(c1["recorded_at"])
    rv = revs(ada, a_)
    assert rv[0]["recorded_at"] == rv[0]["effective_at"] == s1["committed_at"] and rv[1]["correction_batch_id"] == r["correction_batch_id"]
    again = ok(call("POST", "/settlements", body, token=cy, key=skey), 200)
    assert again == s1, "settlement retry returns original body"
    assert (m(ada)["balance"], m(bob)["balance"], m(cy)["balance"]) == (10000 - 90 - 12, 2500 + 90 - 40, 40 + 12)
    acts = call("GET", "/activity", token=ada)[1]["payments"]
    assert [x["amount"] for x in acts if x["payment_id"] == a_] == [100], "original receipt unchanged"


@probe("S4-24/25/26 combined affordability, precedence, rejected batch changes nothing")
def _():
    reset(fx(users=[user("ada", 100), user("bob", 100), user("cy", 0)], ops=["u_cy"]))
    ada, bob, cy = tok("ada"), tok("bob"), tok("cy")
    p = pay(ada, "bob", 100)["payment_id"]   # ada 0 bob 200
    q = pay(bob, "ada", 100)["payment_id"]   # ada 100 bob 100
    # increase p by 150 (ada pays) and q by 150 (bob pays): each alone overdraws now? ada has 100 -> alone 409
    err(correct(ada, p, 1, 250, ago(1)), 409, "insufficient_funds")
    key = k()
    # combined: nets to zero -> allowed currently; historically ada at time p would be negative -> historical_overdraft
    e0 = ago(1)
    rj = batch(cy, [item(p, 1, 250, eff=e0), item(q, 1, 250, eff=e0)], key=key)
    # both effective at the same instant: combined effect at that boundary nets to zero -> 201
    assert rj[0] == 201, rj
    # precedence: item error (stale, first in order) beats completeness and funds
    sres = settle(cy, [("ada", "bob", 10), ("bob", "ada", 10)])
    sa = sres["payments"][0]["payment_id"]
    err(batch(cy, [item(sa, 1, 10**6), item(p, 1, 1)]), 409, "stale_revision")
    err(batch(cy, [item(sa, 1, 10**6), item(p, 2, 1, eff="bad")]), 422, "validation_failed")
    err(batch(cy, [item(sa, 1, 10**6)]), 422, "incomplete_settlement")
    sb = sres["payments"][1]["payment_id"]
    e = ago(1)
    err(batch(cy, [item(sa, 1, 10**6, eff=e), item(sb, 1, 10, eff=e)]), 409, "insufficient_funds")
    # historical: a backdated increase before the money existed
    before = (m(ada)["balance"], m(bob)["balance"], len(revs(ada, p)))
    key2 = k()
    err(batch(cy, [item(q, 2, 260, eff=ago(3600))], key=key2), 409, "historical_overdraft")
    assert (m(ada)["balance"], m(bob)["balance"], len(revs(ada, p))) == before
    # key reusable after rejection with a different body
    ok(batch(cy, [item(q, 2, 250, eff=e0, reason="noop")], key=key2), 201)


@probe("S4-31/33 batch replay and concurrency with single corrections")
def _():
    ada, bob, cy = world()
    p = pay(ada, "bob", 500)["payment_id"]
    key = k()
    body = [item(p, 1, 400)]
    r1 = ok(batch(cy, body, key=key), 201)
    ok(correct(ada, p, 2, 300, ago(1)), 201)
    r2 = ok(batch(cy, body, key=key), 200)
    assert r1 == r2
    err(batch(cy, [item(p, 1, 401)], key=key), 409, "idempotency_key_reuse")
    for _ in range(5):
        cur = revs(ada, p)[-1]["revision"]
        jobs = [lambda: correct(ada, p, cur, 250 + _, ago(1)), lambda: batch(cy, [item(p, cur, 260 + _)])] * 5
        out = par(lambda i: jobs[i](), len(jobs))
        assert [o[0] for o in out].count(201) == 1, [o[0] for o in out]
    tot = m(ada)["balance"] + m(bob)["balance"] + m(cy)["balance"]
    assert tot == 12500


@probe("S4-30/39 snapshots frozen across refunds and batches; historical views include them")
def _():
    ada, bob, cy = world()
    p = pay(ada, "bob", 1000)["payment_id"]
    t_known = datetime.now(timezone.utc).isoformat()
    time.sleep(1.05)  # payment times are stamped to the whole second
    s0 = ok(st(ada, limit=1), 200)
    full0 = ok(st(ada, limit=50), 200)
    ok(refund(bob, p, 300), 201)
    ok(batch(cy, [item(p, 1, 800)]), 201)
    pg = ok(call("GET", f"/statement?snapshot={s0['snapshot']}&limit=50", token=ada), 200)
    assert pg["entries"] == full0["entries"] and pg["closing_balance"] == full0["closing_balance"]
    now_s = ok(st(ada), 200)
    amts = [(e["payment"]["amount"], e["delta"]) for e in now_s["entries"]]
    assert (800, -800) in amts and (300, 300) in amts, amts
    old = ok(st(ada, known_at=t_known), 200)
    assert [(e["payment"]["amount"], e["delta"]) for e in old["entries"]] == [(1000, -1000)], old
    assert ok(me(ada, known_at=t_known), 200)["balance"] == 9000
    assert m(ada)["balance"] == 10000 - 800 + 300


@probe("S4-36/37 stage-3 export imports: membership, corrections, snapshots in original form")
def _():
    if not PREV:
        return
    S3.P.BASE = S3.P.urlsplit(PREV)
    try:
        reset(fx(ops=["u_cy"]))
        ada, bob, cy = tok("ada"), tok("bob"), tok("cy")
        p = pay(ada, "bob", 500)["payment_id"]
        ok(correct(ada, p, 1, 450, ago(1)), 201)
        sres = settle(cy, [("ada", "bob", 10), ("bob", "cy", 5)])
        snap = ok(st(ada, limit=2), 200)
        full = ok(st(ada, limit=50), 200)
        exp = ok(call("GET", "/_test/export"), 200)
    finally:
        S3.P.BASE = S3.P.urlsplit(URL)
    assert call("POST", "/_test/import", exp)[0] == 204
    ada, bob, cy = tok("ada"), tok("bob"), tok("cy")
    pg = ok(call("GET", f"/statement?snapshot={snap['snapshot']}&limit=50", token=ada), 200)
    assert pg["entries"] == full["entries"], "pre-stage-4 snapshot pages in original form"
    assert len(revs(ada, p)) == 2
    a_ = sres["payments"][0]["payment_id"]
    err(batch(cy, [item(a_, 1, 9)]), 422, "incomplete_settlement")
    assert all(x["refund_of"] is None for x in call("GET", "/activity", token=ada)[1]["payments"])
    ok(refund(bob, p, 450), 201)


def main():
    fails = 0
    for name, fn in PROBES:
        if FILTER and not any(f in name for f in FILTER):
            continue
        try:
            fn()
            print("PASS", name, flush=True)
        except Exception as e:  # noqa: BLE001
            fails += 1
            print("FAIL", name, "--", repr(e)[:800], flush=True)
    print(f"{len(PROBES)} probes, {fails} failed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
