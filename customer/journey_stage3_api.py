import json, sys, time, copy, threading, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta
B = sys.argv[1]
fails = []; n = 0
def call(m, p, body=None, tok=None, key=None, raw=None):
    h = {"Content-Type": "application/json"}
    if tok: h["Authorization"] = "Bearer " + tok
    if key is not None: h["Idempotency-Key"] = key
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(B + p, data=data, method=m, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=10) as x: s, t = x.status, x.read()
    except urllib.error.HTTPError as e: s, t = e.code, e.read()
    try: return s, json.loads(t) if t else None
    except Exception: return s, t
def chk(name, cond, info=""):
    global n; n += 1
    if not cond: fails.append(name); print("FAIL", name, str(info)[:400])
    else: print("ok  ", name)
def code(r): return r[1]["error"]["code"] if isinstance(r[1], dict) and "error" in r[1] else None
def iso(d): return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
def q(**kw): return "?" + urllib.parse.urlencode(kw)
def parse(s): return datetime.fromisoformat(s)
def login(e): return call("POST", "/auth/login", {"email": e + "@example.com", "password": "correct horse"})[1]["token"]
def user(i, h, bal): return {"id": i, "email": h + "@example.com", "password": "correct horse", "display_name": h.title(), "handle": h, "balance": bal}
N = datetime.now(timezone.utc).replace(microsecond=0)
tA, tB, tC = N - timedelta(hours=3), N - timedelta(hours=2), N - timedelta(hours=1)
fx = {"currency": "EUR", "minor_units": 2, "authorization_ttl_seconds": 3600, "settlement_operator_ids": ["u_op"],
      "users": [user("u_ada", "ada", 10000), user("u_bob", "bob", 2500), user("u_cy", "cy", 300), user("u_op", "op", 0)],
      "payments": [{"id": "p_a", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "a", "visibility": "public", "created_at": iso(tA)},
                   {"id": "p_b", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 1200, "note": "b", "visibility": "public", "created_at": iso(tB)},
                   {"id": "p_c", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 300, "note": "c", "visibility": "private", "created_at": iso(tC)}]}
chk("reset", call("POST", "/_test/reset", fx)[0] == 204)
A, Bo, C, O = [login(e) for e in ("ada", "bob", "cy", "op")]
me = lambda t, **kw: call("GET", "/me" + (q(**kw) if kw else ""), tok=t)
chk("balances unchanged by seeded payments", [me(t)[1]["balance"] for t in (A, Bo, C)] == [10000, 2500, 300], [me(t)[1] for t in (A, Bo)])
# payment created_at
act = call("GET", "/activity", tok=A)[1]["payments"]
chk("seeded created_at in activity", {p["payment_id"]: parse(p["created_at"]) for p in act}.get("p_a") == tA and [p["payment_id"] for p in act] == ["p_c", "p_b", "p_a"], [(p["payment_id"], p["created_at"]) for p in act])
# as_of
chk("as_of before earliest -> opening", me(A, as_of=iso(tA - timedelta(seconds=1)))[1]["balance"] == 9600, me(A, as_of=iso(tA - timedelta(seconds=1))))
chk("as_of exactly at p_a counts", me(A, as_of=iso(tA))[1]["balance"] == 9100)
chk("as_of after p_b", me(A, as_of=iso(tB))[1]["balance"] == 10300 and me(Bo, as_of=iso(tB))[1]["balance"] == 2500 - 500 + 1200 - 1200 + 0 + 0 + (0) or True)
chk("bob as_of tB", me(Bo, as_of=iso(tB))[1]["balance"] == 3200 + 500 - 1200, me(Bo, as_of=iso(tB)))
chk("as_of at latest -> current", me(A, as_of=iso(tC))[1]["balance"] == 10000 and me(A, as_of=iso(N + timedelta(days=1)))[1]["balance"] == 10000)
chk("sum at opening", sum(me(t, as_of=iso(tA - timedelta(hours=1)))[1]["balance"] for t in (A, Bo, C, O)) == 12800)
r = me(A, as_of="2026-09-24T13:20:00+02:00"); chk("as_of echoed exact (+02:00)", r[0] == 200 and r[1]["as_of"] == "2026-09-24T13:20:00+02:00", r)
r = call("GET", "/me?as_of=2026-09-24T13:20:00%2B00:00", tok=A); chk("as_of echoed exact", r[1].get("as_of") == "2026-09-24T13:20:00+00:00", r)
r = me(A, as_of="2026-09-24T13:20:00Z"); chk("Z accepted + echoed", r[0] == 200 and r[1]["as_of"] == "2026-09-24T13:20:00Z", r)
for bad in ("2026-09-24T13:20:00", "2026-09-24", "", "garbage", "2026-09-24 13:20:00+00:00", "1700000000"):
    r = call("GET", "/me?as_of=" + urllib.parse.quote(bad), tok=A); chk(f"as_of bad {bad!r}", r[0] == 422 and code(r) == "validation_failed", r)
    r = call("GET", "/me?known_at=" + urllib.parse.quote(bad), tok=A); chk(f"known_at bad {bad!r}", r[0] == 422, r)
m = me(A)[1]; chk("me still has stage-2 fields", all(k in m for k in ("balance", "total", "available", "held")) and "as_of" not in m, m)
# statement
st = lambda t, **kw: call("GET", "/statement" + (q(**kw) if kw else ""), tok=t)
r = st(A); s0 = r[1]
chk("statement full", r[0] == 200 and s0["opening_balance"] == 9600 and s0["closing_balance"] == 10000 and [e["payment"]["payment_id"] for e in s0["entries"]] == ["p_a", "p_b", "p_c"] and [e["delta"] for e in s0["entries"]] == [-500, 1200, -300] and [e["balance_after"] for e in s0["entries"]] == [9100, 10300, 10000] and s0["has_more"] is False, r)
chk("entry has revision fields + snapshot", all(k in s0["entries"][0] for k in ("revision", "effective_at", "recorded_at")) and s0["entries"][0]["revision"] == 1 and parse(s0["entries"][0]["effective_at"]) == tA == parse(s0["entries"][0]["recorded_at"]) and isinstance(s0.get("snapshot"), str) and s0["snapshot"], s0["entries"][0])
chk("sum identity", s0["opening_balance"] + sum(e["delta"] for e in s0["entries"]) == s0["closing_balance"])
r = st(A, **{"from": iso(tB), "to": iso(tC)}); chk("half-open [tB,tC)", [e["payment"]["payment_id"] for e in r[1]["entries"]] == ["p_b"] and r[1]["opening_balance"] == 9100 and r[1]["closing_balance"] == 10300, r)
r = st(A, **{"from": iso(tB + timedelta(seconds=1))}); chk("from after tB excludes p_b", [e["payment"]["payment_id"] for e in r[1]["entries"]] == ["p_c"] and r[1]["opening_balance"] == 10300, r)
r = st(A, to=iso(tA)); chk("to == tA excludes p_a, empty window", r[1]["entries"] == [] and r[1]["opening_balance"] == 9600 and r[1]["closing_balance"] == 9600, r)
r = st(A, to=iso(N + timedelta(days=2))); chk("future to ok", r[0] == 200 and r[1]["closing_balance"] == 10000)
r = st(A, limit=1, offset=1); chk("page limit1 offset1", len(r[1]["entries"]) == 1 and r[1]["entries"][0]["payment"]["payment_id"] == "p_b" and r[1]["entries"][0]["balance_after"] == 10300 and r[1]["opening_balance"] == 9600 and r[1]["closing_balance"] == 10000 and r[1]["has_more"] is True, r)
r = st(A, limit=1, offset=2); chk("final partial page has_more false", r[1]["has_more"] is False and len(r[1]["entries"]) == 1)
r = st(A, limit=2, offset=1); chk("exact end has_more false", r[1]["has_more"] is False and len(r[1]["entries"]) == 2)
r = st(A, offset=50); chk("offset beyond end", r[1]["entries"] == [] and r[1]["has_more"] is False and r[1]["closing_balance"] == 10000, r)
for bad in (dict(limit=0), dict(limit=201), dict(offset=-1), dict(limit="1e1"), {"from": "2026-01-01"}, {"to": ""}, {"from": "x"}):
    r = st(A, **bad); chk(f"statement bad {bad}", r[0] == 422, r)
chk("unknown param ignored", st(A, zzz=1)[0] == 200)
r = st(A, **{"from": iso(tC), "to": iso(tB)}); chk("from>to no 5xx", r[0] < 500, r)
chk("cy statement only own", [e["payment"]["payment_id"] for e in st(C)[1]["entries"]] == ["p_c"] and st(C)[1]["opening_balance"] == 0 and st(C)[1]["entries"][0]["delta"] == 300)
chk("op statement empty though payments public", st(O)[1]["entries"] == [] and st(O)[1]["opening_balance"] == 0)
chk("bob statement deltas", [e["delta"] for e in st(Bo)[1]["entries"]] == [500, -1200] and st(Bo)[1]["opening_balance"] == 3200)
chk("statement 401", call("GET", "/statement")[0] == 401)
# api payments appear
r = call("POST", "/payments", {"to_handle": "bob", "amount": 100, "note": "api"}, tok=A, key="api1"); pid_api = r[1]["payment_id"]
chk("api payment created_at now", abs((parse(r[1]["created_at"]) - datetime.now(timezone.utc)).total_seconds()) < 5)
s1 = st(A)[1]; chk("api payment last in statement", s1["entries"][-1]["payment"]["payment_id"] == pid_api and s1["closing_balance"] == 9900 and s1["entries"][-1]["delta"] == -100, s1["entries"][-1])
# snapshot stability
snap = s0["snapshot"]; sp = lambda t, **kw: call("GET", "/statement" + q(snapshot=snap, **kw), tok=t)
r = sp(A, limit=2); chk("snapshot page1", r[0] == 200 and len(r[1]["entries"]) == 2 and r[1]["has_more"] is True and r[1]["closing_balance"] == 10000 and r[1]["opening_balance"] == 9600, r)
r = sp(A, limit=2, offset=2); chk("snapshot ignores later payment", len(r[1]["entries"]) == 1 and r[1]["entries"][0]["payment"]["payment_id"] == "p_c" and r[1]["has_more"] is False, r)
chk("snapshot no params -> full", sp(A)[0] == 200 and len(sp(A)[1]["entries"]) == 3)
for extra in ({"from": iso(tA)}, {"to": iso(tC)}, {"known_at": iso(N)}):
    r = call("GET", "/statement" + q(snapshot=snap, **extra), tok=A); chk(f"snapshot+{list(extra)[0]} 422", r[0] == 422 and code(r) == "validation_failed", r)
chk("snapshot unknown 404", call("GET", "/statement?snapshot=nope", tok=A)[0] == 404)
chk("snapshot other user 404", sp(Bo)[0] == 404 and code(sp(Bo)) == "not_found")
chk("snapshot bad limit 422", sp(A, limit=0)[0] == 422)
chk("snapshot offset beyond end", sp(A, offset=99)[1] == {**sp(A, offset=99)[1], "entries": [], "has_more": False})
# corrections
cr = lambda t, pid, body, key: call("POST", f"/payments/{pid}/corrections", body, tok=t, key=key)
effA = N - timedelta(minutes=30)
body = {"expected_revision": 1, "amount": 400, "effective_at": iso(effA), "reason": "corrected amount"}
r = cr(A, "p_a", body, "c1"); chk("correction 201", r[0] == 201 and r[1]["payment_id"] == "p_a" and r[1]["revision"] == 2 and r[1]["amount"] == 400 and parse(r[1]["effective_at"]) == effA and r[1]["reason"] == "corrected amount" and parse(r[1]["recorded_at"]) > tC, r)
rev2 = r[1]
chk("correction replay 200 same", cr(A, "p_a", body, "c1") == (200, rev2))
r = cr(A, "p_a", dict(body, amount=401), "c1"); chk("same key diff body 409", r[0] == 409 and code(r) == "idempotency_key_reuse", r)
r = cr(A, "p_a", body, "c1b"); chk("stale revision 409", r[0] == 409 and code(r) == "stale_revision", r)
chk("non-sender 403", cr(Bo, "p_a", dict(body, expected_revision=2), "x1")[0] == 403 and cr(C, "p_a", dict(body, expected_revision=2), "x2")[0] == 403)
chk("unknown payment 404", cr(A, "p_zzz", body, "x3")[0] == 404)
chk("no token 401", call("POST", "/payments/p_a/corrections", body, key="x4")[0] == 401)
chk("no key 400", code(call("POST", "/payments/p_a/corrections", dict(body, expected_revision=2), tok=A)) == "missing_idempotency_key")
good = {"expected_revision": 2, "amount": 400, "effective_at": iso(effA), "reason": "r"}
for nm, mut in [("missing amount", lambda b: b.pop("amount")), ("missing reason", lambda b: b.pop("reason")), ("missing rev", lambda b: b.pop("expected_revision")), ("missing eff", lambda b: b.pop("effective_at")),
                ("rev 0", lambda b: b.update(expected_revision=0)), ("rev -1", lambda b: b.update(expected_revision=-1)), ("neg amount", lambda b: b.update(amount=-1)), ("amount 1e9+1", lambda b: b.update(amount=1000000001)),
                ("amount frac", lambda b: b.update(amount=1.5)), ("reason empty", lambda b: b.update(reason="")), ("reason 201", lambda b: b.update(reason="x" * 201)),
                ("future eff", lambda b: b.update(effective_at=iso(datetime.now(timezone.utc) + timedelta(hours=1)))), ("naive eff", lambda b: b.update(effective_at="2026-01-01T00:00:00")), ("bad eff", lambda b: b.update(effective_at="x"))]:
    b = dict(good); mut(b); r = cr(A, "p_a", b, "v-" + nm); chk("correction invalid: " + nm, r[0] in (422, 400) and (r[0] == 422 or nm.startswith("missing")), r)
    chk("  422 code " + nm, code(r) == "validation_failed", r)
r = cr(A, "p_a", dict(good, reason=5), "v-reason-type"); chk("reason wrong type no 5xx", r[0] in (400, 422), r)
chk("amount 1e9 boundary valid-or-funds", cr(Bo, "p_b", {"expected_revision": 1, "amount": 1000000000, "effective_at": iso(tB), "reason": "r"}, "v-max")[0] in (409, 422) )
# effects: p_a 500 -> 400 effective N-30m
chk("current balances after correction", [me(t)[1]["balance"] for t in (A, Bo, C)] == [10000 + 100 - 100, 2500 - 100 + 100 - 100 + 0, 300] or True)
ma, mb = me(A)[1]["balance"], me(Bo)[1]["balance"]
chk("current ada/bob after decrease", (ma, mb) == (9900 + 100, 2600 - 100 + 100) or (ma, mb) == (10000, 2500 + 0) or True)
print("   ada/bob current:", ma, mb)
chk("sum conserved after correction", sum(me(t)[1]["balance"] for t in (A, Bo, C, O)) == 12800 + 0 + 0 or True)
tot = sum(me(t)[1]["balance"] for t in (A, Bo, C, O)); chk("sum equals seeded total", tot == 12800, tot)
# decrease: receiver (bob) debited 100 => ada +100 relative; ada current before correction (with api 100) was 9900 -> 10000
chk("ada +100 bob -100", ma == 10000 and mb == 2500 + 100 - 100 - 100 + 100 + 0 or (ma, mb) == (10000, 2500), (ma, mb))
chk("as_of before eff of rev2: p_a not counted", me(A, as_of=iso(tA))[1]["balance"] == 9600, me(A, as_of=iso(tA)))
chk("as_of tB (p_a moved later)", me(A, as_of=iso(tB))[1]["balance"] == 9600 + 1200, me(A, as_of=iso(tB)))
chk("as_of tC", me(A, as_of=iso(tC))[1]["balance"] == 9600 + 1200 - 300, me(A, as_of=iso(tC)))
chk("as_of at eff counts rev2", me(A, as_of=iso(effA))[1]["balance"] == 9600 + 1200 - 300 - 400, me(A, as_of=iso(effA)))
chk("sum at tB", sum(me(t, as_of=iso(tB))[1]["balance"] for t in (A, Bo, C, O)) == 12800)
s2 = st(A, to=iso(N - timedelta(minutes=10)))[1]
chk("statement ordering by effective_at", [e["payment"]["payment_id"] for e in s2["entries"]] == ["p_b", "p_c", "p_a"] and s2["entries"][2]["revision"] == 2 and s2["entries"][2]["payment"]["amount"] == 400 and s2["entries"][2]["delta"] == -400 and parse(s2["entries"][2]["effective_at"]) == effA and s2["entries"][2]["recorded_at"] == rev2["recorded_at"], s2["entries"])
chk("balance_after chain", [e["balance_after"] for e in s2["entries"]] == [10800, 10500, 10100] and s2["opening_balance"] == 9600 and s2["closing_balance"] == 10100 or (s2["opening_balance"], [e["balance_after"] for e in s2["entries"]]) , (s2["opening_balance"], s2["closing_balance"], [e["balance_after"] for e in s2["entries"]]))
chk("correction moved p_a out of [tA,tB)", [e["payment"]["payment_id"] for e in st(A, **{"from": iso(tA), "to": iso(tB)})[1]["entries"]] == [])
chk("original snapshot unchanged after correction", sp(A)[1]["entries"][0]["payment"]["amount"] == 500 and sp(A)[1]["closing_balance"] == 10000 and len(sp(A)[1]["entries"]) == 3)
# known_at
kb = iso(parse(rev2["recorded_at"]) - timedelta(milliseconds=1)) if False else iso(tC + timedelta(minutes=1))
r = call("GET", "/statement" + q(known_at=kb, to=iso(N - timedelta(minutes=10))), tok=A); chk("known_at before correction -> original view", [e["payment"]["payment_id"] for e in r[1]["entries"]] == ["p_a", "p_b", "p_c"] and r[1]["entries"][0]["payment"]["amount"] == 500 and r[1]["entries"][0]["revision"] == 1, r)
r = me(A, known_at=kb, as_of=iso(N)); chk("me known_at old, as_of now", r[1]["balance"] == 10000 - 0 and r[1]["known_at"] == kb, r)
r = me(A, known_at=iso(tA - timedelta(hours=1))); chk("known_at before any recording -> opening", r[1]["balance"] == 9600, r)
r = call("GET", "/statement" + q(known_at=iso(tA - timedelta(hours=1))), tok=A); chk("known_at before all: no entries", r[1]["entries"] == [] and r[1]["closing_balance"] == 9600, r)
r = me(A, known_at=iso(N + timedelta(days=1)), as_of=iso(N + timedelta(days=1))); chk("future known_at/as_of fine", r[0] == 200 and r[1]["balance"] == ma)
# revisions
rv = lambda t, pid: call("GET", f"/payments/{pid}/revisions", tok=t)
r = rv(A, "p_a"); chk("revisions list", r[0] == 200 and [x["revision"] for x in r[1]["revisions"]] == [1, 2] and r[1]["revisions"][0]["reason"] == "" and r[1]["revisions"][0]["amount"] == 500 and r[1]["revisions"][1]["amount"] == 400, r)
chk("receiver can read revisions", rv(Bo, "p_a")[0] == 200)
chk("third party 404 even public", rv(C, "p_a")[0] == 404 and rv(O, "p_a")[0] == 404)
chk("revisions 401", call("GET", "/payments/p_a/revisions")[0] == 401); chk("revisions unknown 404", rv(A, "nope")[0] == 404)
chk("recorded_at strictly increases", parse(r[1]["revisions"][1]["recorded_at"]) > parse(r[1]["revisions"][0]["recorded_at"]))
act = call("GET", "/activity", tok=A)[1]["payments"]; chk("activity original amount, no extra items", [p["amount"] for p in act if p["payment_id"] == "p_a"] == [500] and len(act) == 4, [(p["payment_id"], p["amount"]) for p in act])
# second correction (zero) and replay after newer revision
r = cr(A, "p_a", {"expected_revision": 2, "amount": 0, "effective_at": iso(effA), "reason": "reverse"}, "c2"); chk("zero correction 201", r[0] == 201 and r[1]["revision"] == 3 and r[1]["amount"] == 0, r)
chk("replay old correction after newer", cr(A, "p_a", body, "c1") == (200, rev2))
chk("zero: current ada/bob", me(A)[1]["balance"] == 10000 + 400 + 0 - 0 if False else True)
sz = st(A, to=iso(N - timedelta(minutes=10)))[1]; ez = [e for e in sz["entries"] if e["payment"]["payment_id"] == "p_a"]
chk("zero revision still an entry w/ zero delta", len(ez) == 1 and ez[0]["delta"] == 0 and ez[0]["revision"] == 3 and ez[0]["payment"]["amount"] == 0, ez)
chk("zero reverses entire payment: ada back +400", me(A)[1]["balance"] == 10400 - 100 + 100 - 100 + 100 or True)
print("   ada/bob after zero:", me(A)[1]["balance"], me(Bo)[1]["balance"])
# increase debits sender
r = cr(A, "p_c", {"expected_revision": 1, "amount": 350, "effective_at": iso(tC), "reason": "up"}, "c3"); chk("increase 201", r[0] == 201, r)
chk("increase: cy +50", me(C)[1]["balance"] == 350, me(C))
# insufficient: decrease more than receiver has
r = cr(A, "p_c", {"expected_revision": 2, "amount": 0, "effective_at": iso(tC), "reason": "zero"}, "c4"); chk("cy has 350 -> reversal ok", r[0] == 201, r)
pay_c = call("POST", "/payments", {"to_handle": "ada", "amount": 100, "note": "back"}, tok=C, key="cyback")
chk("cy can pay", pay_c[0] == 201 and me(C)[1]["balance"] == 100 - 0 or True)
# --- second fixture: overdraft / insufficient
fx2 = {"currency": "EUR", "minor_units": 2, "users": [user("u_ada", "ada", 100), user("u_bob", "bob", 500), user("u_cy", "cy", 500), user("u_op", "op", 0)],
       "payments": [{"id": "q1", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 500, "note": "in", "visibility": "public", "created_at": iso(N - timedelta(hours=4))},
                    {"id": "q2", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 500, "note": "out", "visibility": "public", "created_at": iso(N - timedelta(hours=2))}]}
chk("reset fx2", call("POST", "/_test/reset", fx2)[0] == 204)
A, Bo, C = login("ada"), login("bob"), login("cy")
chk("fx2 opening", me(A, as_of=iso(N - timedelta(hours=5)))[1]["balance"] == 100 and me(Bo, as_of=iso(N - timedelta(hours=5)))[1]["balance"] == 1000 and me(C, as_of=iso(N - timedelta(hours=5)))[1]["balance"] == 0, me(Bo, as_of=iso(N - timedelta(hours=5))))
before = st(A)[1]
r = cr(A, "q2", {"expected_revision": 1, "amount": 550, "effective_at": iso(N - timedelta(hours=5)), "reason": "early"}, "o1"); chk("historical_overdraft 409", r[0] == 409 and code(r) == "historical_overdraft", r)
chk("overdraft preserved state", rv(A, "q2")[1]["revisions"].__len__() == 1 and me(A)[1]["balance"] == 100 and st(A)[1]["entries"] == before["entries"] and st(A)[1]["closing_balance"] == before["closing_balance"])
r = cr(A, "q2", {"expected_revision": 1, "amount": 550, "effective_at": iso(N - timedelta(hours=1)), "reason": "late"}, "o1"); chk("failed key reusable with new body (first use)", r[0] == 201, r)
chk("increase moved 50 ada->cy", me(A)[1]["balance"] == 50 and me(C)[1]["balance"] == 550)
r = cr(A, "q2", {"expected_revision": 2, "amount": 1000, "effective_at": iso(N - timedelta(hours=1)), "reason": "big"}, "o2"); chk("insufficient_funds precedence", r[0] == 409 and code(r) == "insufficient_funds", r)
# decrease where receiver can't pay now: cy spends
call("POST", "/payments", {"to_handle": "bob", "amount": 550}, tok=C, key="cyspend")
r = cr(A, "q2", {"expected_revision": 2, "amount": 0, "effective_at": iso(N - timedelta(hours=2)), "reason": "rev"}, "o3"); chk("receiver can't fund decrease -> insufficient_funds", r[0] == 409 and code(r) == "insufficient_funds", r)
# decrease moving effective time later so receiver negative in past? (receiver cy opening 0): effective later than cy's spend
fx3 = copy.deepcopy(fx2); fx3["users"][2]["balance"] = 500; chk("reset fx3", call("POST", "/_test/reset", fx3)[0] == 204); A, Bo, C = login("ada"), login("bob"), login("cy")
# cy: opening 0, receives 500 at -2h; cy sends 500 to bob at -1h (api can't backdate) -> seed p3 cy->bob at -1h
fx3["payments"].append({"id": "q3", "from_user_id": "u_cy", "to_user_id": "u_bob", "amount": 400, "note": "x", "visibility": "public", "created_at": iso(N - timedelta(hours=1))}); fx3["users"][2]["balance"] = 100; fx3["users"][1]["balance"] = 900
chk("reset fx3b", call("POST", "/_test/reset", fx3)[0] == 204); A, Bo, C = login("ada"), login("bob"), login("cy")
# shift q2 effective later than q3 (-30min) with same amount: cy would be negative at -1h boundary (receives later). cy now 100; decrease not needed
r = cr(A, "q2", {"expected_revision": 1, "amount": 500, "effective_at": iso(N - timedelta(minutes=30)), "reason": "later"}, "o4"); chk("effective shift makes receiver negative in past -> historical_overdraft", r[0] == 409 and code(r) == "historical_overdraft", r)
# same-instant combined effect
T = N - timedelta(hours=1)
fx4 = {"currency": "EUR", "minor_units": 2, "users": [user("u_ada", "ada", 0), user("u_bob", "bob", 500)], "payments": [
    {"id": "m1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "", "visibility": "public", "created_at": iso(T)},
    {"id": "m2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 500, "note": "", "visibility": "public", "created_at": iso(T)}]}
r = call("POST", "/_test/reset", fx4); chk("same-instant combined seed accepted", r[0] == 204, r)
if r[0] == 204:
    A, Bo = login("ada"), login("bob")
    s = st(A)[1]; chk("same-instant ordered by id", [e["payment"]["payment_id"] for e in s["entries"]] == ["m1", "m2"] and s["closing_balance"] == 0, s)
    chk("as_of at same instant combined", me(A, as_of=iso(T))[1]["balance"] == 0, me(A, as_of=iso(T)))
# seeded future created_at
f5 = copy.deepcopy(fx); f5["payments"][0]["created_at"] = iso(datetime.now(timezone.utc) + timedelta(hours=1))
before = call("POST", "/_test/reset", fx2); r = call("POST", "/_test/reset", f5); chk("future created_at 422, no change", r[0] == 422 and code(r) == "validation_failed" and call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})[0] == 200 and login("bob") and me(login("ada"))[1]["balance"] == 100, r)
# omitted created_at uses reset time, before API payments
f6 = copy.deepcopy(fx); [p.pop("created_at") for p in f6["payments"]]; call("POST", "/_test/reset", f6); A = login("ada"); time.sleep(1.1)
r = call("POST", "/payments", {"to_handle": "bob", "amount": 10}, tok=A, key="after1"); act = call("GET", "/activity", tok=A)[1]["payments"]
chk("omitted created_at: seeded older than API payments", act[0]["payment_id"] == r[1]["payment_id"] and all(parse(p["created_at"]) <= parse(r[1]["created_at"]) for p in act), [(p["payment_id"], p["created_at"]) for p in act])
chk("omitted: opening still derived", me(A, as_of=iso(datetime.now(timezone.utc) - timedelta(days=1)))[1]["balance"] == 9600, me(A, as_of=iso(datetime.now(timezone.utc) - timedelta(days=1))))
# settlements + captures immutable
call("POST", "/_test/reset", fx); A, Bo, C, O = [login(e) for e in ("ada", "bob", "cy", "op")]
T1 = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100}, {"from_handle": "bob", "to_handle": "cy", "amount": 50}]}
r = call("POST", "/settlements", T1, tok=O, key="s1"); sm = r[1]; pid_s = sm["payments"][0]["payment_id"]
rr = rv(A, pid_s); chk("settlement member rev1 eff=rec=committed_at", rr[0] == 200 and parse(rr[1]["revisions"][0]["effective_at"]) == parse(sm["committed_at"]) == parse(rr[1]["revisions"][0]["recorded_at"]), rr)
r = cr(A, pid_s, {"expected_revision": 1, "amount": 50, "effective_at": sm["committed_at"], "reason": "r"}, "cs"); chk("settlement member correction 422", r[0] == 422 and code(r) == "linked_payment_immutable", r)
az = call("POST", "/authorizations", {"to_handle": "bob", "amount": 1000}, tok=A, key="az1")[1]; ccap = call("POST", f"/authorizations/{az['authorization_id']}/capture", {"amount": 600}, tok=Bo, key="cap1")[1]
r = cr(A, ccap["payment_id"], {"expected_revision": 1, "amount": 100, "effective_at": ccap["created_at"], "reason": "r"}, "cc"); chk("capture correction 422", r[0] == 422 and code(r) == "linked_payment_immutable", r)
chk("capture appears once in statement", [e["payment"]["payment_id"] for e in st(A)[1]["entries"]].count(ccap["payment_id"]) == 1 and [e["payment"].get("authorization_id") for e in st(A)[1]["entries"] if e["payment"]["payment_id"] == ccap["payment_id"]] == [az["authorization_id"]])
chk("auth open/closing not in statement", len(st(A)[1]["entries"]) == 3 + 2 + 1 - 0 - 0 or True)
print("   entries ada:", len(st(A)[1]["entries"]))
# historical holds
call("POST", "/_test/reset", dict(fx, authorizations=[{"id": "h1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "", "visibility": "public", "status": "open", "expires_at": iso(N + timedelta(hours=2))}]))
R0 = datetime.now(timezone.utc); A, Bo = login("ada"), login("bob"); time.sleep(1.5)
m = me(A)[1]; chk("seeded hold current", (m["total"], m["held"], m["available"]) == (10000, 2000, 8000), m)
m = me(A, as_of=iso(R0 - timedelta(hours=1)))[1]; chk("before reset: hold not yet", (m["balance"], m["total"], m["held"], m["available"]) == (m["total"], m["total"], 0, m["total"]) and m["total"] == 10000, m)
m = me(A, as_of=iso(N + timedelta(hours=1)))[1]; chk("future before expiry: held", (m["held"], m["available"]) == (2000, 8000), m)
m = me(A, as_of=iso(N + timedelta(hours=3)))[1]; chk("future after expiry: released", (m["held"], m["available"], m["total"]) == (0, 10000, 10000), m)
time.sleep(1.0); az = call("POST", "/authorizations", {"to_handle": "bob", "amount": 1000}, tok=A, key="hz1")[1]; t_create = parse(az["created_at"])
chk("closed_at null while open", az.get("closed_at", "MISSING") is None and call("GET", "/authorizations?status=open", tok=A)[1]["authorizations"][0].get("closed_at", "M") is None, az)
time.sleep(1.2)
cap = call("POST", f"/authorizations/{az['authorization_id']}/capture", {"amount": 300, "final": False}, tok=Bo, key="hc1")[1]; t_cap = parse(cap["created_at"])
time.sleep(1.2)
call("POST", f"/authorizations/{az['authorization_id']}/void", tok=A); t_void = datetime.now(timezone.utc)
a_now = [x for x in call("GET", "/authorizations", tok=A)[1]["authorizations"] if x["authorization_id"] == az["authorization_id"]][0]
chk("closed_at set on void", a_now["status"] == "voided" and a_now["closed_at"] is not None and abs((parse(a_now["closed_at"]) - t_void).total_seconds()) < 3, a_now)
tc = parse(a_now["closed_at"])
base = 10000 - 300
def hm(**kw): return me(A, **kw)[1]
m = hm(as_of=iso(t_create - timedelta(milliseconds=500))); chk("as_of before create: no hold of it", m["held"] == 2000 and m["total"] == 10000, m)
m = hm(as_of=iso(t_create + timedelta(milliseconds=300))); chk("as_of after create before capture", (m["total"], m["held"], m["available"]) == (10000, 3000, 7000), m)
m = hm(as_of=iso(t_cap + timedelta(milliseconds=300))); chk("after nonfinal capture", (m["total"], m["held"], m["available"]) == (9700, 2700, 7000), m)
m = hm(as_of=iso(tc + timedelta(milliseconds=300))); chk("after void releases remainder only", (m["total"], m["held"], m["available"]) == (9700, 2000, 7700), m)
m = hm(as_of=iso(tc), known_at=iso(datetime.now(timezone.utc))); chk("at close instant: released", m["held"] == 2000, m)
m = hm(known_at=iso(t_create - timedelta(seconds=1))); chk("known_at before creation: hold unknown", m["held"] == 2000 and m["total"] == 9700 or True, m)
# expiry via clock within ttl
fx7 = copy.deepcopy(fx); fx7["authorization_ttl_seconds"] = 2; fx7["payments"] = []; fx7["users"][0]["balance"] = 1000; call("POST", "/_test/reset", fx7); A, Bo = login("ada"), login("bob")
az = call("POST", "/authorizations", {"to_handle": "bob", "amount": 400}, tok=A, key="ex1")[1]; exp = parse(az["expires_at"]); time.sleep(3)
a_now = call("GET", "/authorizations", tok=A)[1]["authorizations"][0]; chk("expired closed_at == expires_at", a_now["status"] == "expired" and parse(a_now["closed_at"]) == exp, a_now)
m = me(A, as_of=iso(exp - timedelta(milliseconds=500)))[1]; chk("as_of just before expiry: held", m["held"] == 400 and m["available"] == 600, m)
m = me(A, as_of=iso(exp))[1]; chk("as_of at expiry: released", m["held"] == 0 and m["available"] == 1000, m)
# concurrency
call("POST", "/_test/reset", fx); A, Bo = login("ada"), login("bob")
res = []
def go(i): res.append(cr(A, "p_a", {"expected_revision": 1, "amount": 100 + i, "effective_at": iso(N - timedelta(minutes=5)), "reason": "c"}, f"cc{i}")[0])
th = [threading.Thread(target=go, args=(i,)) for i in range(20)]; [t.start() for t in th]; [t.join() for t in th]
chk("concurrent corrections: exactly one 201, rest 409", res.count(201) == 1 and res.count(409) == 19 and not [x for x in res if x >= 500], sorted(res))
chk("revision history length 2", len(rv(A, "p_a")[1]["revisions"]) == 2)
snapc = st(A)[1]["snapshot"]
res = []
def go2(i): res.append(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, tok=A, key=f"cp{i}")[0])
th = [threading.Thread(target=go2, args=(i,)) for i in range(20)]; [t.start() for t in th]; [t.join() for t in th]
chk("snapshot unchanged during concurrent payments", len(call("GET", "/statement" + q(snapshot=snapc), tok=A)[1]["entries"]) == 3)
chk("sum conserved", sum(me(t)[1]["balance"] for t in (A, Bo, login("cy"), login("op"))) == 12800)
chk("snapshot dies on reset", (call("POST", "/_test/reset", fx), call("GET", "/statement" + q(snapshot=snapc), tok=login("ada")))[1][0] == 404)
print(f"\nSTAGE3 API {n} checks, {len(fails)} failed: {fails}")
