"""spec-auditor stage 3 probes: one probe per gap in ledger/stage-3.md (S3-n). Stdlib only.

Usage: python3 stage3_probes.py http://127.0.0.1:PORT [STAGE2_URL] [name-filter ...]
STAGE2_URL (optional): a running stage-2 service for the upgrade probe.
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
PREV = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2].startswith("http") else None
FILTER = [a for a in sys.argv[2:] if not a.startswith("http")]
sys.argv = [sys.argv[0], URL]
import stage1_probes as P  # noqa: E402
from stage2_probes import A  # noqa: E402

call, k, err, ok, user, fx, reset, tok, par = P.call, P.k, P.err, P.ok, P.user, P.fx, P.reset, P.tok, P.par
PROBES = []


def probe(name):
    def deco(fn):
        PROBES.append((name, fn))
        return fn
    return deco


def ago(sec):
    return (datetime.now(timezone.utc) - timedelta(seconds=sec)).replace(microsecond=0).isoformat()


def now_precise():
    return datetime.now(timezone.utc).isoformat()


def q(**kw):
    return "&".join(f"{a}={quote(str(b), safe='')}" for a, b in kw.items())


def me(t, **kw):
    return call("GET", "/me" + ("?" + q(**kw) if kw else ""), token=t)


def st(t, **kw):
    return call("GET", "/statement" + ("?" + q(**kw) if kw else ""), token=t)


def PM(i, frm="u_ada", to="u_bob", amount=100, created=None, **x):
    d = {"id": i, "from_user_id": frm, "to_user_id": to, "amount": amount, "note": i, "visibility": "public"}
    if created:
        d["created_at"] = created
    d.update(x)
    return d


def correct(t, pid, rev, amount, eff, reason="fix", key=None):
    return call("POST", f"/payments/{pid}/corrections",
                {"expected_revision": rev, "amount": amount, "effective_at": eff, "reason": reason},
                token=t, key=key or k())


def seeded_world():
    """ada 10000 now; history: p_old ada->bob 1000 at -3h, p_mid bob->ada 300 at -2h."""
    reset(fx(payments=[PM("p_old", amount=1000, created=ago(3 * 3600)),
                       PM("p_mid", frm="u_bob", to="u_ada", amount=300, created=ago(2 * 3600))]))
    return tok("ada"), tok("bob"), tok("cy")


# ---- seeding and as_of ----------------------------------------------------------------------

@probe("S3-2/3/4/5/9/12 seeded history: opening balances, as_of inclusive, before first payment")
def _():
    ada, bob, cy = seeded_world()
    m = ok(me(ada), 200)
    assert m["balance"] == 10000 and ok(me(bob), 200)["balance"] == 2500, "loading payments changed balances"
    t_old, t_mid = ago(3 * 3600), ago(2 * 3600)
    acts = call("GET", "/activity", token=ada)[1]["payments"]
    created = {p["payment_id"]: p["created_at"] for p in acts}
    assert created["p_old"] != created["p_mid"]
    first = created["p_old"]
    b = ok(me(ada, as_of=first), 200)
    assert b["balance"] == 10000 - 300 and b["as_of"] == first, ("payment at exactly as_of counts", b)
    before = (datetime.fromisoformat(first) - timedelta(seconds=1)).isoformat()
    assert ok(me(ada, as_of=before), 200)["balance"] == 10000 + 1000 - 300, "opening = ending - net"
    assert ok(me(bob, as_of=before), 200)["balance"] == 2500 - 1000 + 300
    weird = datetime.fromisoformat(first).astimezone(timezone(timedelta(hours=5, minutes=30))).isoformat()
    b = ok(me(ada, as_of=weird), 200)
    assert b["as_of"] == weird and b["balance"] == 9700, b
    frac = first.replace("+00:00", ".000+00:00")
    assert ok(me(ada, as_of=frac), 200)["as_of"] == frac
    # future seeded created_at is a reset error that changes nothing
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    err(call("POST", "/_test/reset", fx(payments=[PM("p_f", created=future)])), 422, "validation_failed")
    assert ok(me(ada), 200)["balance"] == 10000
    # omitted created_at = reset time, before later API payments
    reset(fx(payments=[PM("p_s", amount=7)]))
    ada = tok("ada")
    time.sleep(1.1)
    ok(call("POST", "/payments", {"to_handle": "bob", "amount": 5}, token=ada, key=k()), 201)
    ents = ok(st(ada), 200)["entries"]
    assert [e["payment"]["payment_id"] for e in ents][0] == "p_s", ents
    s0 = ok(st(ada), 200)
    assert s0["opening_balance"] == 10000 + 7, "new-account/seeded opening"
    s = ok(call("POST", "/auth/signup", {"email": "nn@example.com", "password": "correct horse", "display_name": "N"}), 201)
    assert ok(st(s["token"]), 200)["opening_balance"] == 0


@probe("S3-6/18/36 instant validation on /me and /statement")
def _():
    ada, _, _ = seeded_world()
    for bad in ("2026-09-24T13:20:00", "2026-09-24", "", "yesterday", "2026-09-24 13:20:00+00:00",
                "2026-13-01T00:00:00+00:00", "2026-09-24T13:20:00+0000"):
        err(me(ada, as_of=bad), 422, "validation_failed", ("as_of", bad))
        err(me(ada, known_at=bad), 422, "validation_failed", ("known_at", bad))
        for f in ("from", "to", "known_at"):
            err(st(ada, **{f: bad}), 422, "validation_failed", (f, bad))
    fut = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    ok(me(ada, as_of=fut, known_at=fut), 200)
    ok(st(ada, to=fut, known_at=fut), 200)


# ---- statements ---------------------------------------------------------------------------------

@probe("S3-13/14/15/16/17 statement window, order, signs, paging, third parties")
def _():
    ada, bob, cy = seeded_world()
    ok(call("POST", "/payments", {"to_handle": "cy", "amount": 50}, token=bob, key=k()), 201)  # public, not ada's
    for i in range(5):
        ok(call("POST", "/payments", {"to_handle": "bob", "amount": 10 + i}, token=ada, key=k()), 201)
    full = ok(st(ada, limit=200), 200)
    ids = [e["payment"]["payment_id"] for e in full["entries"]]
    assert len(ids) == 7 and ids[:2] == ["p_old", "p_mid"], ids
    keys = [(e["effective_at"], e["payment"]["payment_id"]) for e in full["entries"]]
    assert keys == sorted(keys, key=lambda x: (datetime.fromisoformat(x[0]), x[1])), "order by effective then id"
    assert [e["delta"] for e in full["entries"]][:2] == [-1000, 300], "sent negative, received positive"
    assert full["opening_balance"] + sum(e["delta"] for e in full["entries"]) == full["closing_balance"] == 10000 - 60
    run = full["opening_balance"]
    for e in full["entries"]:
        run += e["delta"]
        assert e["balance_after"] == run
        assert {"revision", "effective_at", "recorded_at", "payment", "delta", "balance_after"} <= set(e)
    p2 = ok(st(ada, limit=3, offset=3), 200)
    assert (p2["opening_balance"], p2["closing_balance"]) == (full["opening_balance"], full["closing_balance"])
    assert [e["balance_after"] for e in p2["entries"]] == [e["balance_after"] for e in full["entries"][3:6]]
    assert p2["has_more"] is True and ok(st(ada, limit=3, offset=6), 200)["has_more"] is False
    assert ok(st(ada, limit=3, offset=50), 200)["entries"] == []
    # half-open window: from inclusive, to exclusive
    t_mid = full["entries"][1]["effective_at"]
    w = ok(st(ada, **{"from": t_mid, "to": full["entries"][2]["effective_at"]}), 200)
    assert [e["payment"]["payment_id"] for e in w["entries"]] == ["p_mid"], w["entries"]
    assert w["opening_balance"] == 10000 + 1000 - 300 - 1000 and w["closing_balance"] == w["opening_balance"] + 300
    w = ok(st(ada, to=t_mid), 200)
    assert [e["payment"]["payment_id"] for e in w["entries"]] == ["p_old"]
    for bad in ({"limit": "0"}, {"limit": "201"}, {"offset": "-1"}, {"limit": "4.0"}):
        err(st(ada, **bad), 422, "validation_failed", bad)


@probe("S3-41/43/44/45/42 snapshots: token, exclusivity, scoping, frozen after writes and reset")
def _():
    ada, bob, cy = seeded_world()
    first = ok(st(ada, limit=1), 200)
    tokn = first["snapshot"]
    assert isinstance(tokn, str) and tokn
    full_before = ok(call("GET", f"/statement?snapshot={quote(tokn)}&limit=200", token=ada), 200)
    pid = ok(call("POST", "/payments", {"to_handle": "bob", "amount": 77}, token=ada, key=k()), 201)["payment_id"]
    ok(correct(ada, "p_old", 1, 900, ago(3 * 3600)), 201)
    ok(call("POST", "/authorizations", {"to_handle": "bob", "amount": 5}, token=ada, key=k()), 201)
    after = ok(call("GET", f"/statement?snapshot={quote(tokn)}&limit=200", token=ada), 200)
    for f in ("opening_balance", "closing_balance", "entries", "has_more"):
        assert after[f] == full_before[f], (f, "snapshot changed after writes")
    p = ok(call("GET", f"/statement?snapshot={quote(tokn)}&limit=1&offset=1", token=ada), 200)
    assert p["entries"] == full_before["entries"][1:2] and p["has_more"] is False
    for extra in ("from", "to", "known_at"):
        err(call("GET", f"/statement?snapshot={quote(tokn)}&{extra}={quote(ago(10))}", token=ada), 422, "validation_failed", extra)
    ok(call("GET", f"/statement?snapshot={quote(tokn)}&bogus=1", token=ada), 200)
    err(call("GET", f"/statement?snapshot={quote(tokn)}", token=bob), 404, "not_found")
    err(call("GET", "/statement?snapshot=nope", token=ada), 404, "not_found")
    fresh = ok(st(ada, limit=200), 200)
    assert pid in [e["payment"]["payment_id"] for e in fresh["entries"]]
    reset(fx())
    err(call("GET", f"/statement?snapshot={quote(tokn)}", token=tok("ada")), 404, "not_found")


# ---- corrections ------------------------------------------------------------------------------------

@probe("S3-19/22/26/31/32 corrections move the difference; revisions endpoint; feed unchanged")
def _():
    ada, bob, cy = seeded_world()
    pay = ok(call("POST", "/payments", {"to_handle": "bob", "amount": 500, "visibility": "private"}, token=ada, key=k()), 201)
    pid = pay["payment_id"]
    revs = ok(call("GET", f"/payments/{pid}/revisions", token=bob), 200)["revisions"]
    assert revs == [{"payment_id": pid, "revision": 1, "amount": 500, "effective_at": pay["created_at"],
                     "recorded_at": pay["created_at"], "reason": ""}], revs
    up = ok(correct(ada, pid, 1, 800, pay["created_at"], "more"), 201)
    assert set(up) >= {"payment_id", "revision", "amount", "effective_at", "recorded_at", "reason"}
    assert (up["revision"], up["amount"], up["effective_at"], up["reason"]) == (2, 800, pay["created_at"], "more")
    assert ok(me(ada), 200)["balance"] == 10000 - 800 and ok(me(bob), 200)["balance"] == 2500 + 800
    ok(correct(ada, pid, 2, 0, pay["created_at"], "reverse"), 201)
    assert ok(me(ada), 200)["balance"] == 10000 and ok(me(bob), 200)["balance"] == 2500
    feed = call("GET", "/activity", token=ada)[1]["payments"]
    assert [p for p in feed if p["payment_id"] == pid] == [pay], "activity must show the original payment"
    assert len(feed) == 3
    ent = [e for e in ok(st(ada), 200)["entries"] if e["payment"]["payment_id"] == pid][0]
    assert (ent["delta"], ent["revision"], ent["payment"]["amount"]) == (0, 3, 0), ent
    assert ent["payment"]["visibility"] == "private" and ent["payment"]["to_handle"] == "bob"
    revs = ok(call("GET", f"/payments/{pid}/revisions", token=ada), 200)["revisions"]
    assert [r["revision"] for r in revs] == [1, 2, 3]
    err(call("GET", f"/payments/{pid}/revisions", token=cy), 404, "not_found")
    err(call("GET", "/payments/p_old/revisions", token=cy), 404, "not_found")  # public, still 404
    err(call("GET", f"/payments/{pid}/revisions"), 401, "unauthenticated")


@probe("S3-20/21/24/25/23 correction validation, staleness, idempotency, strictly increasing recorded_at")
def _():
    ada, bob, cy = seeded_world()
    pay = ok(call("POST", "/payments", {"to_handle": "bob", "amount": 500}, token=ada, key=k()), 201)
    pid, ca = pay["payment_id"], pay["created_at"]
    fut = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    base = {"expected_revision": 1, "amount": 400, "effective_at": ca, "reason": "r"}
    for bad in ({"expected_revision": 0}, {"expected_revision": 1.5}, {"expected_revision": True}, {"amount": -1},
                {"amount": 10 ** 9 + 1}, {"amount": "400"}, {"reason": ""}, {"reason": "x" * 201}, {"reason": None},
                {"effective_at": fut}, {"effective_at": "2026-09-20T12:00:00"}, {"effective_at": "2026-09-20"}):
        err(call("POST", f"/payments/{pid}/corrections", dict(base, **bad), token=ada, key=k()), 422, "validation_failed", bad)
    for miss in base:
        b = dict(base)
        b.pop(miss)
        err(call("POST", f"/payments/{pid}/corrections", b, token=ada, key=k()), 422, "validation_failed", miss)
    err(call("POST", f"/payments/{pid}/corrections", base, token=bob, key=k()), 403, "forbidden")
    err(call("POST", f"/payments/{pid}/corrections", base, token=cy, key=k()), 403, "forbidden")
    err(call("POST", "/payments/p_nope/corrections", base, token=ada, key=k()), 404, "not_found")
    err(call("POST", f"/payments/{pid}/corrections", base, key=k()), 401, "unauthenticated")
    err(call("POST", f"/payments/{pid}/corrections", base, token=ada), 400, "missing_idempotency_key")
    key = k()
    r2 = ok(call("POST", f"/payments/{pid}/corrections", base, token=ada, key=key), 201)
    r3 = ok(correct(ada, pid, 2, 300, ca), 201)
    r4 = ok(correct(ada, pid, 3, 200, ca), 201)
    assert ok(call("POST", f"/payments/{pid}/corrections", base, token=ada, key=key), 200) == r2
    err(call("POST", f"/payments/{pid}/corrections", dict(base, amount=401), token=ada, key=key), 409, "idempotency_key_reuse")
    err(correct(ada, pid, 2, 100, ca), 409, "stale_revision")
    rec = [datetime.fromisoformat(r["recorded_at"]) for r in (r2, r3, r4)]
    assert rec[0] < rec[1] < rec[2], rec
    assert ok(me(ada), 200)["balance"] == 10000 - 200


@probe("S3-33 concurrent corrections with the same expected revision: exactly one wins")
def _():
    ada, bob, _ = seeded_world()
    pay = ok(call("POST", "/payments", {"to_handle": "bob", "amount": 500}, token=ada, key=k()), 201)
    out = par(lambda i: correct(ada, pay["payment_id"], 1, 100 + i, pay["created_at"]), 20)
    st_ = [o[0] for o in out]
    assert st_.count(201) == 1 and st_.count(409) == 19, sorted(st_)
    m = ok(me(ada), 200)["balance"] + ok(me(bob), 200)["balance"] + ok(me(tok("cy")), 200)["balance"]
    assert m == 12500


@probe("S3-27/28/29/55 insufficient_funds first, historical_overdraft, failures change nothing")
def _():
    reset(fx(users=[user("ada", 100), user("bob", 0), user("cy", 0)],
             payments=[PM("p_old", frm="u_ada", to="u_bob", amount=50, created=ago(3 * 3600)),
                       PM("p_in", frm="u_cy", to="u_ada", amount=0, created=ago(2 * 3600))]))
    ada, bob = tok("ada"), tok("bob")
    # ada opened at 150, paid 50 at -3h. Increasing p_old to 160 debits ada 110 now: unaffordable (has 100)
    err(correct(ada, "p_old", 1, 160, ago(3 * 3600)), 409, "insufficient_funds")
    # ada receives 1000 now, so a correction to 160 is affordable now, but at -3h ada only had 150
    reset(fx(users=[user("ada", 100), user("bob", 0), user("cy", 1000)],
             payments=[PM("p_old", frm="u_ada", to="u_bob", amount=50, created=ago(3 * 3600))]))
    ada, bob, cy = tok("ada"), tok("bob"), tok("cy")
    ok(call("POST", "/payments", {"to_handle": "ada", "amount": 1000}, token=cy, key=k()), 201)
    snap = ok(st(ada), 200)
    key = k()
    err(correct(ada, "p_old", 1, 160, ago(3 * 3600), key=key), 409, "historical_overdraft")
    assert ok(me(ada), 200)["balance"] == 1100 and len(ok(call("GET", "/payments/p_old/revisions", token=ada), 200)["revisions"]) == 1
    s2 = ok(st(ada), 200)
    assert s2["entries"] == snap["entries"] and s2["closing_balance"] == snap["closing_balance"]
    ok(correct(ada, "p_old", 1, 150, ago(3 * 3600), key=key), 201)  # key not claimed by the failure; 150 is exactly affordable
    # available counts: a hold now makes an otherwise-affordable debit fail
    reset(fx(users=[user("ada", 1000), user("bob", 0), user("cy", 0)]))
    ada = tok("ada")
    p = ok(call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=ada, key=k()), 201)
    ok(call("POST", "/authorizations", {"to_handle": "cy", "amount": 850}, token=ada, key=k()), 201)
    err(correct(ada, p["payment_id"], 1, 200, p["created_at"]), 409, "insufficient_funds")


@probe("S3-34/35/38/39/37 known_at selection, zero revisions, backdated moves across windows")
def _():
    ada, bob, _ = seeded_world()
    t0 = now_precise()
    time.sleep(1.1)
    ok(correct(ada, "p_old", 1, 400, ago(30 * 60), "moved to -30min"), 201)
    t1 = now_precise()
    time.sleep(1.1)
    ok(correct(ada, "p_old", 2, 0, ago(30 * 60), "reversed"), 201)
    before_seed = ago(5 * 3600)
    # known before the seeded payment was recorded: it contributes nothing
    e = ok(st(ada, known_at=before_seed), 200)
    assert e["entries"] == [] and e["known_at"] == before_seed, e
    # known at t0: original revision 1 at -3h
    e = ok(st(ada, known_at=t0), 200)["entries"]
    old = [x for x in e if x["payment"]["payment_id"] == "p_old"][0]
    assert (old["revision"], old["delta"], old["payment"]["amount"]) == (1, -1000, 1000), old
    # known at t1: revision 2, moved to -30min, amount 400
    e = ok(st(ada, known_at=t1), 200)["entries"]
    ids = [x["payment"]["payment_id"] for x in e]
    assert ids == ["p_mid", "p_old"], ("moved after p_mid by its effective time", ids)
    old = e[1]
    assert (old["revision"], old["delta"]) == (2, -400), old
    # now: revision 3, zero amount, still an entry; counted once
    e = ok(st(ada), 200)["entries"]
    olds = [x for x in e if x["payment"]["payment_id"] == "p_old"]
    assert len(olds) == 1 and olds[0]["delta"] == 0 and olds[0]["revision"] == 3
    # window [-4h,-1h): known at t0 contains p_old; known now it moved out (effective -30min)
    w0 = ok(st(ada, **{"from": ago(4 * 3600), "to": ago(3600), "known_at": t0}), 200)
    w1 = ok(st(ada, **{"from": ago(4 * 3600), "to": ago(3600)}), 200)
    assert "p_old" in [x["payment"]["payment_id"] for x in w0["entries"]]
    assert "p_old" not in [x["payment"]["payment_id"] for x in w1["entries"]]
    assert w1["opening_balance"] == 10000 + 1000 - 300 and w1["closing_balance"] == w1["opening_balance"] + 300, w1
    # /me under the same views; opening balances never change
    assert ok(me(ada, as_of=ago(2.5 * 3600), known_at=t0), 200)["balance"] == 10700 - 1000
    assert ok(me(ada, as_of=ago(2.5 * 3600)), 200)["balance"] == 10700
    k1 = ok(me(ada, known_at=t1), 200)
    assert k1["balance"] == 10700 - 400 + 300, k1
    assert k1["known_at"] == t1


@probe("S3-30 conservation in every historical view")
def _():
    ada, bob, cy = seeded_world()
    ok(call("POST", "/payments", {"to_handle": "cy", "amount": 70}, token=bob, key=k()), 201)
    ok(correct(ada, "p_old", 1, 600, ago(150 * 60)), 201)
    toks = [ada, bob, cy]
    for as_of in (ago(5 * 3600), ago(3 * 3600), ago(150 * 60), ago(2 * 3600), ago(0)):
        for known in (None, ago(4 * 3600), ago(0)):
            kw = {"as_of": as_of}
            if known:
                kw["known_at"] = known
            assert sum(ok(me(t, **kw), 200)["balance"] for t in toks) == 12500, (as_of, known)


# ---- linked payments, holds, upgrade ---------------------------------------------------------------------

@probe("S3-48/49 settlement members and captures are immutable; member revision 1 at committed_at")
def _():
    reset(fx(ops=["u_ada"]))
    ada, bob = tok("ada"), tok("bob")
    s = ok(call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 5}]},
                token=ada, key=k()), 201)
    m = s["payments"][0]
    r = ok(call("GET", f"/payments/{m['payment_id']}/revisions", token=ada), 200)["revisions"][0]
    assert r["effective_at"] == r["recorded_at"] == s["committed_at"], (r, s["committed_at"])
    err(correct(ada, m["payment_id"], 1, 1, m["created_at"]), 422, "linked_payment_immutable")
    a = ok(call("POST", "/authorizations", {"to_handle": "bob", "amount": 50}, token=ada, key=k()), 201)
    c = ok(call("POST", f"/authorizations/{a['authorization_id']}/capture", {}, token=bob, key=k()), 201)
    err(correct(ada, c["payment_id"], 1, 1, c["created_at"]), 422, "linked_payment_immutable")
    ents = ok(st(ada), 200)["entries"]
    assert [e["payment"]["payment_id"] for e in ents].count(c["payment_id"]) == 1
    assert [e for e in ents if e["payment"]["payment_id"] == c["payment_id"]][0]["payment"]["authorization_id"] == a["authorization_id"]
    assert len(ents) == 2, "holds and releases are not statement entries"


@probe("S3-51/52/53/54/56 historical holds and closed_at")
def _():
    reset(fx(authorization_ttl_seconds=6, authorizations=[A("a_seed", 1000)]))
    ada, bob = tok("ada"), tok("bob")
    t_reset = ago(0)
    m = ok(me(ada, as_of=t_reset), 200)
    assert (m["total"], m["held"], m["available"], m["balance"]) == (10000, 1000, 9000, 10000), m
    a = ok(call("POST", "/authorizations", {"to_handle": "bob", "amount": 2000}, token=ada, key=k()), 201)
    assert a["closed_at"] is None
    t_auth = a["created_at"]
    time.sleep(1.1)
    c = ok(call("POST", f"/authorizations/{a['authorization_id']}/capture", {"amount": 500, "final": False},
                token=bob, key=k()), 201)
    time.sleep(1.1)
    t_cap = ago(0)
    time.sleep(1.1)
    v = ok(call("POST", f"/authorizations/{a['authorization_id']}/void", token=ada), 200)
    assert v["closed_at"] and v["status"] == "voided"
    m = ok(me(ada, as_of=t_auth), 200)
    assert (m["held"], m["total"]) == (3000, 10000), m
    m = ok(me(ada, as_of=t_cap), 200)
    assert (m["held"], m["total"], m["available"]) == (2500, 9500, 7000), m
    m = ok(me(ada, as_of=t_cap, known_at=t_cap), 200)
    assert m["held"] == 2500, ("void not yet known at t_cap", m)
    m = ok(me(ada), 200)
    assert m["held"] == 1000 and m["total"] == 9500
    # a future query expires the open seeded hold at its deadline (seeded expires in 2h)
    fut = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    assert ok(me(ada, as_of=fut), 200)["held"] == 0
    # clock expiry closes with closed_at = expires_at
    b = ok(call("POST", "/authorizations", {"to_handle": "bob", "amount": 10}, token=ada, key=k()), 201)
    time.sleep(6.5)
    lst = {x["authorization_id"]: x for x in call("GET", "/authorizations", token=ada)[1]["authorizations"]}
    assert lst[b["authorization_id"]]["status"] == "expired"
    assert datetime.fromisoformat(lst[b["authorization_id"]]["closed_at"]) == datetime.fromisoformat(b["expires_at"])
    ents = ok(st(ada), 200)["entries"]
    assert [e["payment"]["payment_id"] for e in ents] == [c["payment_id"]], "statement holds money movements only"


@probe("S3-50/47 stage-2 export imports; stage-3 snapshots survive export/import")
def _():
    ada, bob, _ = seeded_world()
    ok(correct(ada, "p_old", 1, 900, ago(3 * 3600)), 201)
    s1 = ok(st(ada, limit=1), 200)
    full = ok(call("GET", f"/statement?snapshot={quote(s1['snapshot'])}&limit=200", token=ada), 200)
    ex = call("GET", "/_test/export")[1]
    reset(fx())
    assert call("POST", "/_test/import", ex)[0] == 204
    again = ok(call("GET", f"/statement?snapshot={quote(s1['snapshot'])}&limit=200", token=ada), 200)
    assert again == full, "snapshot changed across export/import"
    assert len(ok(call("GET", "/payments/p_old/revisions", token=ada), 200)["revisions"]) == 2
    if not PREV:
        raise AssertionError("SKIP: no stage-2 URL for the upgrade half")
    base = P.BASE
    P.BASE = urlsplit(PREV)
    try:
        P.reset(fx(ops=["u_ada"], payments=[PM("p_x", created=ago(3600))]))
        a2 = tok("ada")
        ok(call("POST", "/payments", {"to_handle": "bob", "amount": 11}, token=a2, key=k()), 201)
        au = ok(call("POST", "/authorizations", {"to_handle": "bob", "amount": 100}, token=a2, key=k()), 201)
        ok(call("POST", f"/authorizations/{au['authorization_id']}/capture", {"amount": 40, "final": False}, token=tok("bob"), key=k()), 201)
        ok(call("POST", "/settlements", {"transfers": [{"from_handle": "bob", "to_handle": "cy", "amount": 3}]}, token=a2, key=k()), 201)
        ex2 = call("GET", "/_test/export")[1]
        m2 = ok(me(a2), 200)
    finally:
        P.BASE = base
    reset(fx())
    s, b, _ = call("POST", "/_test/import", ex2)
    assert s == 204, (s, b)
    m3 = ok(me(a2), 200)
    for f in ("balance", "total", "available", "held"):
        assert m3[f] == m2[f], (f, m2, m3)
    ents = ok(st(a2), 200)
    assert ents["opening_balance"] + sum(e["delta"] for e in ents["entries"]) == ents["closing_balance"] == m3["total"]
    assert sum(ok(me(t, as_of=ago(7200)), 200)["balance"] for t in (a2, tok("bob"), tok("cy"))) == 12500


@probe("S3-1 created_at on every payment-returning endpoint")
def _():
    reset(fx(ops=["u_ada"]))
    ada, bob = tok("ada"), tok("bob")
    bodies = [ok(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=ada, key=k()), 201)]
    rid = ok(call("POST", "/requests", {"payer_handle": "ada", "amount": 1}, token=bob, key=k()), 201)["request_id"]
    bodies.append(ok(call("POST", f"/requests/{rid}/pay", {}, token=ada, key=k()), 201))
    bodies += ok(call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}, token=ada, key=k()), 201)["payments"]
    a = ok(call("POST", "/authorizations", {"to_handle": "bob", "amount": 1}, token=ada, key=k()), 201)
    bodies.append(ok(call("POST", f"/authorizations/{a['authorization_id']}/capture", {}, token=bob, key=k()), 201))
    bodies += call("GET", "/activity", token=ada)[1]["payments"]
    bodies += [e["payment"] for e in ok(st(ada), 200)["entries"]]
    for b in bodies:
        assert P.RFC3339.match(b["created_at"]), b


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
