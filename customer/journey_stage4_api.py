import sys, copy, subprocess
B = sys.argv[1]
src = open("journey_stage3_api.py").read().split("N = datetime.now(timezone.utc)")[0]
exec(src)
N = datetime.now(timezone.utc).replace(microsecond=0)
me = lambda t, **kw: call("GET", "/me" + (q(**kw) if kw else ""), tok=t)
st = lambda t, **kw: call("GET", "/statement" + (q(**kw) if kw else ""), tok=t)
pay = lambda t, to, amt, key, **kw: call("POST", "/payments", dict(to_handle=to, amount=amt, **kw), tok=t, key=key)
refund = lambda t, pid, amt, key: call("POST", f"/payments/{pid}/refunds", {"amount": amt}, tok=t, key=key)
cr = lambda t, pid, body, key: call("POST", f"/payments/{pid}/corrections", body, tok=t, key=key)
batch = lambda t, items, key, **kw: call("POST", "/correction-batches", dict(corrections=items, **kw), tok=t, key=key)
def item(pid, rev=1, amount=0, eff=None, reason="reversal"): return {"payment_id": pid, "expected_revision": rev, "amount": amount, "effective_at": iso(eff or (N - timedelta(minutes=1))), "reason": reason}
revs = lambda t, pid: call("GET", f"/payments/{pid}/revisions", tok=t)
base = {"currency": "EUR", "minor_units": 2, "settlement_operator_ids": ["u_op"], "authorization_ttl_seconds": 3600,
        "users": [user("u_ada", "ada", 10000), user("u_bob", "bob", 5000), user("u_cy", "cy", 1000), user("u_op", "op", 1000)]}
def reset(extra=None, **kw):
    f = copy.deepcopy(base); f.update(kw)
    if extra: extra(f)
    assert call("POST", "/_test/reset", f)[0] == 204
    return tuple(login(e) for e in ("ada", "bob", "cy", "op"))
total = lambda: sum(me(login(e))[1]["balance"] for e in ("ada", "bob", "cy", "op"))
# ---------- refunds
A, Bo, C, O = reset()
r = pay(A, "bob", 1000, "p1", note="dinner ✓", visibility="private"); P = r[1]
r = refund(Bo, P["payment_id"], 200, "rf1"); R1 = r[1]
chk("refund 201 shape", r[0] == 201 and R1["refund_of"] == P["payment_id"] and R1["request_id"] is None and R1["authorization_id"] is None and R1["note"] == "dinner ✓" and R1["visibility"] == "private" and R1["from_handle"] == "bob" and R1["to_handle"] == "ada" and R1["amount"] == 200 and R1["currency"] == "EUR" and R1["payment_id"] != P["payment_id"], r)
chk("balances after refund", (me(A)[1]["balance"], me(Bo)[1]["balance"]) == (10000 - 1000 + 200, 5000 + 1000 - 200))
chk("refund replay 200 same", refund(Bo, P["payment_id"], 200, "rf1") == (200, R1))
chk("refund key reuse diff body 409", code(refund(Bo, P["payment_id"], 201, "rf1")) == "idempotency_key_reuse")
chk("original payment has refund_of null", P.get("refund_of", "MISSING") is None, P)
chk("sender can't refund 403", refund(A, P["payment_id"], 10, "x1")[0] == 403 and refund(C, P["payment_id"], 10, "x2")[0] == 403)
chk("unknown 404", refund(Bo, "nope", 10, "x3")[0] == 404)
chk("refund 401/400", call("POST", f"/payments/{P['payment_id']}/refunds", {"amount": 5}, key="k")[0] == 401 and code(call("POST", f"/payments/{P['payment_id']}/refunds", {"amount": 5}, tok=Bo)) == "missing_idempotency_key")
for nm, b in [("zero", {"amount": 0}), ("neg", {"amount": -1}), ("frac", {"amount": 1.5}), ("str", {"amount": "5"}), ("null", {"amount": None}), ("missing", {}), ("huge", {"amount": 1000000001}), ("bool", {"amount": True})]:
    r = call("POST", f"/payments/{P['payment_id']}/refunds", b, tok=Bo, key="v" + nm); chk("refund invalid " + nm, r[0] == 422 and code(r) == "validation_failed", r)
r = refund(Bo, P["payment_id"], 801, "ex1"); chk("cumulative exceed 422", r[0] == 422 and code(r) == "refund_exceeds_payment", r)
r = refund(Bo, P["payment_id"], 800, "ex2"); chk("cumulative exact ok", r[0] == 201, r)
r = refund(Bo, P["payment_id"], 1, "ex3"); chk("fully refunded further 422", code(r) == "refund_exceeds_payment", r)
r = refund(A, R1["payment_id"], 50, "rr1"); chk("refund of refund 422 invalid_refund_target", r[0] == 422 and code(r) == "invalid_refund_target", r)
r = cr(Bo, R1["payment_id"], {"expected_revision": 1, "amount": 100, "effective_at": iso(N - timedelta(minutes=1)), "reason": "r"}, "cc1"); chk("correct refund payment 422 linked_payment_immutable", r[0] == 422 and code(r) == "linked_payment_immutable", r)
act = call("GET", "/activity", tok=A)[1]["payments"]; chk("activity: refund is payment w/ refund_of, others null", [p for p in act if p["payment_id"] == R1["payment_id"]][0]["refund_of"] == P["payment_id"] and all(p.get("refund_of") is None for p in act if p["payment_id"] == P["payment_id"]))
chk("private refund hidden from third party", R1["payment_id"] not in [p["payment_id"] for p in call("GET", "/activity", tok=C)[1]["payments"]])
chk("sum conserved", total() == 17000)
s = st(A)[1]; ids = [e["payment"]["payment_id"] for e in s["entries"]]; chk("refunds in statement", R1["payment_id"] in ids and s["opening_balance"] + sum(e["delta"] for e in s["entries"]) == s["closing_balance"])
# corrections vs refunds
A, Bo, C, O = reset()
P = pay(A, "bob", 1000, "p1")[1]; refund(Bo, P["payment_id"], 300, "r1")
e = iso(N - timedelta(minutes=1))
r = cr(A, P["payment_id"], {"expected_revision": 1, "amount": 299, "effective_at": e, "reason": "r"}, "c1"); chk("correct below refunded 422 refund_exceeds_payment", r[0] == 422 and code(r) == "refund_exceeds_payment", r)
r = cr(A, P["payment_id"], {"expected_revision": 1, "amount": 300, "effective_at": e, "reason": "r"}, "c2"); chk("correct to exactly refunded ok", r[0] == 201, r)
r = refund(Bo, P["payment_id"], 1, "r2"); chk("refund limited by corrected amount", code(r) == "refund_exceeds_payment", r)
P2 = pay(A, "bob", 1000, "p2")[1]
r = cr(A, P2["payment_id"], {"expected_revision": 1, "amount": 1200, "effective_at": e, "reason": "up"}, "c3"); chk("increase ok", r[0] == 201)
r = refund(Bo, P2["payment_id"], 1200, "r3"); chk("refund up to corrected amount ok", r[0] == 201, r)
# insufficient / available
A, Bo, C, O = reset(users=None) if False else reset()
P = pay(A, "cy", 1000, "p1")[1]; pay(C, "ada", 1900, "drain")  # cy has 1000+1000-1900=100
r = refund(C, P["payment_id"], 200, "ins"); chk("refund > available 409 insufficient_funds, nothing changes", r[0] == 409 and code(r) == "insufficient_funds" and me(C)[1]["balance"] == 100, r)
r = refund(C, P["payment_id"], 100, "ok100"); chk("refund exactly available ok", r[0] == 201)
A, Bo, C, O = reset()
P = pay(A, "bob", 1000, "p1")[1]
call("POST", "/authorizations", {"to_handle": "cy", "amount": 5500}, tok=Bo, key="hold")   # bob 6000, available 500
m = me(Bo)[1]; chk("bob available 500", m["available"] == 500, m)
r = refund(Bo, P["payment_id"], 600, "held"); chk("refund can't use held funds", r[0] == 409 and code(r) == "insufficient_funds", r)
r = cr(A, P["payment_id"], {"expected_revision": 1, "amount": 200, "effective_at": iso(N - timedelta(minutes=1)), "reason": "r"}, "ch"); chk("correction debit checked against available", r[0] == 409 and code(r) == "insufficient_funds", r)
chk("refund 500 ok", refund(Bo, P["payment_id"], 500, "held2")[0] == 201)
# refund of request payment, capture; no reopen
A, Bo, C, O = reset()
rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 700}, tok=Bo, key="rq")[1]
pp = call("POST", f"/requests/{rq['request_id']}/pay", {}, tok=A, key="pq")[1]
r = refund(Bo, pp["payment_id"], 100, "rrq"); chk("refund request payment ok, request_id null", r[0] == 201 and r[1]["request_id"] is None and r[1]["refund_of"] == pp["payment_id"], r)
chk("request stays paid", [x for x in call("GET", "/requests", tok=A)[1]["requests"] if x["request_id"] == rq["request_id"]][0]["status"] == "paid")
az = call("POST", "/authorizations", {"to_handle": "bob", "amount": 1000}, tok=A, key="az")[1]; cp = call("POST", f"/authorizations/{az['authorization_id']}/capture", {"amount": 400}, tok=Bo, key="cp")[1]
av0 = me(A)[1]["available"]
r = refund(Bo, cp["payment_id"], 100, "rcap"); chk("refund capture ok, authorization_id null", r[0] == 201 and r[1]["authorization_id"] is None and r[1]["refund_of"] == cp["payment_id"], r)
a2 = call("GET", "/authorizations", tok=A)[1]["authorizations"][0]; chk("authorization stays captured; hold not restored", a2["status"] == "captured" and me(A)[1]["held"] == 0 and me(A)[1]["available"] == av0 + 100, (a2, me(A)[1]))
# settlements: refund member
A, Bo, C, O = reset()
T = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 300}, {"from_handle": "bob", "to_handle": "cy", "amount": 100}]}
S = call("POST", "/settlements", T, tok=O, key="s1")[1]
r = refund(Bo, S["payments"][0]["payment_id"], 100, "rs"); chk("refund settlement member ok", r[0] == 201 and r[1].get("settlement_id") is None, r)
chk("settlement replay unchanged", call("POST", "/settlements", T, tok=O, key="s1") == (200, S))
# ---------- batches
A, Bo, C, O = reset()
pa, pb = pay(A, "bob", 500, "a")[1], pay(Bo, "ada", 300, "b")[1]
chk("batch non-operator 403", batch(A, [item(pa["payment_id"])], "b0")[0] == 403 and code(batch(A, [item(pa["payment_id"])], "b0")) == "forbidden")
chk("batch 401", call("POST", "/correction-batches", {"corrections": []}, key="x")[0] == 401)
chk("batch no key 400", code(call("POST", "/correction-batches", {"corrections": [item(pa["payment_id"])]}, tok=O)) == "missing_idempotency_key")
for nm, items in [("empty", []), ("33", [item(pa["payment_id"])] * 33), ("dup ids", [item(pa["payment_id"]), item(pa["payment_id"])]), ("not list", "x")]:
    r = call("POST", "/correction-batches", {"corrections": items}, tok=O, key="v" + nm); chk("batch invalid " + nm, r[0] in (422, 400) and (r[0] == 422 or nm == "not list"), r)
r = call("POST", "/correction-batches", {}, tok=O, key="vmissing"); chk("batch missing corrections 422", r[0] == 422, r)
r = batch(O, [item(pa["payment_id"], amount=-1)], "vi1"); chk("item invalid amount 422", code(r) == "validation_failed", r)
r = batch(O, [item("nope")], "vi2"); chk("unknown payment 404", r[0] == 404, r)
r = batch(O, [item(pa["payment_id"], rev=5)], "vi3"); chk("stale 409", r[0] == 409 and code(r) == "stale_revision", r)
r = batch(O, [item("nope"), item(pa["payment_id"], amount=-1)], "pr1"); chk("precedence: first failing item (404) wins", r[0] == 404, r)
r = batch(O, [item(pa["payment_id"], amount=-1), item("nope")], "pr2"); chk("precedence: first failing item (422) wins", r[0] == 422, r)
r = batch(O, [item(pa["payment_id"], eff=N + timedelta(hours=1))], "fut"); chk("future effective 422", r[0] == 422, r)
chk("rejected batches left no revisions", len(revs(A, pa["payment_id"])[1]["revisions"]) == 1 and total() == 17000)
r = batch(O, [item(pa["payment_id"], amount=400, reason="fix"), item(pb["payment_id"], amount=250, reason="fix2")], "ok1", extra="ignored"); B1 = r[1]
chk("batch 201 shape", r[0] == 201 and B1["correction_batch_id"] and B1["recorded_at"] and [x["payment_id"] for x in B1["revisions"]] == [pa["payment_id"], pb["payment_id"]] and all(x["correction_batch_id"] == B1["correction_batch_id"] and x["recorded_at"] == B1["recorded_at"] and x["revision"] == 2 for x in B1["revisions"]) and [x["amount"] for x in B1["revisions"]] == [400, 250] and [x["reason"] for x in B1["revisions"]] == ["fix", "fix2"], r)
chk("recorded_at later than previous for each member", all(parse(B1["recorded_at"]) > parse(revs(A, x["payment_id"])[1]["revisions"][0]["recorded_at"]) for x in B1["revisions"]))
chk("batch replay 200 same", batch(O, [item(pa["payment_id"], amount=400, reason="fix"), item(pb["payment_id"], amount=250, reason="fix2")], "ok1", extra="ignored") == (200, B1))
chk("batch key reuse diff body 409", code(batch(O, [item(pa["payment_id"], amount=399)], "ok1")) == "idempotency_key_reuse")
chk("balances moved (a: -100 for ada refund, b: -50)", me(A)[1]["balance"] == 10000 - 400 + 250 and me(Bo)[1]["balance"] == 5000 + 400 - 250, (me(A)[1], me(Bo)[1]))
rr = revs(A, pa["payment_id"])[1]["revisions"]; chk("revisions expose correction_batch_id", rr[1]["correction_batch_id"] == B1["correction_batch_id"] and rr[0].get("correction_batch_id") is None and rr[0]["reason"] == "", rr)
chk("activity original amounts", [p["amount"] for p in call("GET", "/activity", tok=A)[1]["payments"] if p["payment_id"] == pa["payment_id"]] == [500])
sx = st(A, **{"to": iso(N + timedelta(minutes=5))})[1]; ea = [e for e in sx["entries"] if e["payment"]["payment_id"] == pa["payment_id"]][0]; chk("statement reflects batch revision", ea["revision"] == 2 and ea["payment"]["amount"] == 400 and ea["delta"] == -400)
chk("stale after batch for single correction", cr(A, pa["payment_id"], {"expected_revision": 1, "amount": 1, "effective_at": iso(N - timedelta(minutes=1)), "reason": "r"}, "st")[0] == 409)
chk("batch idempotency independent of other paths (same key)", pay(A, "bob", 1, "ok1")[0] == 201)
# snapshot frozen across batch
A, Bo, C, O = reset()
pa = pay(A, "bob", 500, "a")[1]; snap = st(A)[1]; tok = snap["snapshot"]
batch(O, [item(pa["payment_id"], amount=100)], "bs")
fr = call("GET", "/statement" + q(snapshot=tok), tok=A)[1]; chk("snapshot frozen across batch", fr["entries"][-1]["payment"]["amount"] == 500 and fr["entries"] == snap["entries"])
# combined affordability
def comb(f):
    f["users"][1]["balance"] = 0; f["users"][0]["balance"] = 10000
    f["payments"] = [{"id": "P1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "", "visibility": "public", "created_at": iso(N - timedelta(hours=3))},
                     {"id": "P2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 500, "note": "", "visibility": "public", "created_at": iso(N - timedelta(hours=2))}]
A, Bo, C, O = reset(comb)
E = N - timedelta(hours=1)
r = cr(A, "P1", {"expected_revision": 1, "amount": 0, "effective_at": iso(E), "reason": "r"}, "alone"); chk("alone unaffordable", r[0] == 409 and code(r) == "insufficient_funds", r)
r = batch(O, [item("P1", eff=E), item("P2", eff=E)], "comb"); chk("combined effect affordable -> 201", r[0] == 201, r)
chk("combined: balances unchanged", me(Bo)[1]["balance"] == 0 and me(A)[1]["balance"] == 10000)
# insufficient vs historical precedence, historical overdraft
def hist(f):
    f["users"][0]["balance"] = 100; f["users"][1]["balance"] = 500
    f["payments"] = [{"id": "r", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 500, "note": "", "visibility": "public", "created_at": iso(N - timedelta(hours=4))},
                     {"id": "q", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 500, "note": "", "visibility": "public", "created_at": iso(N - timedelta(hours=2))}]
    f["users"][2]["balance"] = 1500
A, Bo, C, O = reset(hist)
r = batch(O, [item("q", amount=550, eff=N - timedelta(hours=5))], "ho"); chk("batch historical_overdraft 409", r[0] == 409 and code(r) == "historical_overdraft", r)
chk("state preserved + key reusable", len(revs(A, "q")[1]["revisions"]) == 1 and me(A)[1]["balance"] == 100)
r = batch(O, [item("q", amount=550, eff=N - timedelta(hours=1))], "ho"); chk("same key retried w/ valid body is first use", r[0] == 201, r)
r = batch(O, [item("q", rev=2, amount=1000, eff=N - timedelta(hours=5))], "ho2"); chk("insufficient_funds precedes historical", r[0] == 409 and code(r) == "insufficient_funds", r)
# immutable & refund exceeds in batch
A, Bo, C, O = reset()
P = pay(A, "bob", 1000, "p")[1]; RF = refund(Bo, P["payment_id"], 400, "rf")[1]
az = call("POST", "/authorizations", {"to_handle": "bob", "amount": 300}, tok=A, key="az")[1]; CP = call("POST", f"/authorizations/{az['authorization_id']}/capture", {}, tok=Bo, key="cp")[1]
r = batch(O, [item(RF["payment_id"])], "i1"); chk("batch refund immutable", r[0] == 422 and code(r) == "linked_payment_immutable", r)
r = batch(O, [item(CP["payment_id"])], "i2"); chk("batch capture immutable", r[0] == 422 and code(r) == "linked_payment_immutable", r)
r = batch(O, [item(P["payment_id"], amount=399)], "i3"); chk("batch below refunded 422", r[0] == 422 and code(r) == "refund_exceeds_payment", r)
r = batch(O, [item(P["payment_id"], amount=400)], "i4"); chk("batch to exactly refunded ok", r[0] == 201, r)
# settlements
A, Bo, C, O = reset()
T = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 300}, {"from_handle": "bob", "to_handle": "cy", "amount": 100}, {"from_handle": "cy", "to_handle": "ada", "amount": 50}]}
S = call("POST", "/settlements", T, tok=O, key="s1")[1]; m = [x["payment_id"] for x in S["payments"]]
solo = pay(A, "cy", 10, "solo")[1]
r = batch(O, [item(m[0])], "inc1"); chk("incomplete_settlement 422", r[0] == 422 and code(r) == "incomplete_settlement", r)
r = batch(O, [item(m[0]), item(m[1])], "inc2"); chk("partial members incomplete", code(r) == "incomplete_settlement", r)
r = batch(O, [item(m[0], amount=-1)], "inc3"); chk("item error precedes completeness", code(r) == "validation_failed", r)
r = batch(O, [item(m[0]), item(m[1], eff=N - timedelta(minutes=2)), item(m[2])], "diff"); chk("members different effective -> validation_failed", r[0] == 422 and code(r) == "validation_failed", r)
r = cr(A, m[0], {"expected_revision": 1, "amount": 5, "effective_at": iso(N - timedelta(minutes=1)), "reason": "r"}, "single"); chk("single correction of member still 422 linked", code(r) == "linked_payment_immutable", r)
e1 = (N - timedelta(minutes=1)); e1b = e1.astimezone(timezone(timedelta(hours=2))).strftime("%Y-%m-%dT%H:%M:%S+02:00")
items = [item(m[0], amount=200), dict(item(m[1], amount=50), effective_at=e1b), item(m[2], amount=0), item(solo["payment_id"], amount=5)]
items = [dict(x, effective_at=iso(e1)) if i != 1 else x for i, x in enumerate(items)]; items[3]["effective_at"] = iso(N - timedelta(minutes=30))
r = batch(O, [items[2], items[0], items[1]], "setl"); chk("whole settlement w/ differing offset spelling -> 201", r[0] == 201 and [x["payment_id"] for x in r[1]["revisions"]] == [m[2], m[0], m[1]], r)
Sb = r[1]
chk("settlement replay original body", call("POST", "/settlements", T, tok=O, key="s1") == (200, S))
chk("membership unchanged: payments keep settlement_id", all(p.get("settlement_id") == S["settlement_id"] for p in call("GET", "/activity", tok=A)[1]["payments"] if p["payment_id"] in m))
chk("settlement members original revision effective==recorded==committed", parse(revs(A, m[0])[1]["revisions"][0]["effective_at"]) == parse(S["committed_at"]))
chk("sum conserved after batch", total() == 17000 + 0 or total() == 17000, total())
# batch with solo + settlement together
A, Bo, C, O = reset(); S = call("POST", "/settlements", T, tok=O, key="s1")[1]; m = [x["payment_id"] for x in S["payments"]]; solo = pay(A, "cy", 10, "solo")[1]
r = batch(O, [item(m[0]), item(m[1]), item(m[2]), item(solo["payment_id"], amount=3, eff=N - timedelta(minutes=2))], "mix"); chk("settlement + ordinary together", r[0] == 201 and len({x["recorded_at"] for x in r[1]["revisions"]}) == 1, r)
# concurrency
A, Bo, C, O = reset()
pa, pb = pay(A, "bob", 500, "a")[1], pay(A, "bob", 400, "b")[1]
res = []
def go(i):
    items = [item(pa["payment_id"], amount=10 + i)] + ([item(pb["payment_id"], amount=20 + i)] if i % 2 else [])
    res.append(batch(O, items, f"cb{i}")[0])
th = [threading.Thread(target=go, args=(i,)) for i in range(16)]; [t.start() for t in th]; [t.join() for t in th]
chk("concurrent overlapping batches: exactly one 201", res.count(201) == 1 and res.count(409) == 15 and not [x for x in res if x >= 500], sorted(res))
res = []
def go2(i):
    if i % 2: res.append(batch(O, [item(pb["payment_id"], amount=5)], f"mb{i}")[0])
    else: res.append(cr(A, pb["payment_id"], {"expected_revision": 1, "amount": 6 + i, "effective_at": iso(N - timedelta(minutes=1)), "reason": "r"}, f"mc{i}")[0])
th = [threading.Thread(target=go2, args=(i,)) for i in range(12)]; [t.start() for t in th]; [t.join() for t in th]
chk("batch vs single concurrent: exactly one 201", res.count(201) == 1 and not [x for x in res if x >= 500], sorted(res))
chk("sum conserved after concurrency", total() == 17000)
res = []
P = pay(A, "bob", 1000, "cr")[1]
def go3(i): res.append(refund(Bo, P["payment_id"], 100, f"rcc{i}")[0])
th = [threading.Thread(target=go3, args=(i,)) for i in range(25)]; [t.start() for t in th]; [t.join() for t in th]
chk("25 concurrent refunds of 100/1000: exactly 10 succeed", res.count(201) == 10 and res.count(422) == 15, sorted(res))
res = []
def go4(i): res.append(refund(Bo, P["payment_id"] if False else pay(A, "bob", 1, f"z{i}")[1]["payment_id"], 1, "samekey")[0])
th = [threading.Thread(target=lambda: res.append(refund(Bo, pa["payment_id"], 1, "samek")[0])) for i in range(20)]; [t.start() for t in th]; [t.join() for t in th]
chk("same-key concurrent refunds: one 201, rest 200", res.count(201) == 1 and res.count(200) == 19, sorted(res))
print(f"\nSTAGE4 API {n} checks, {len(fails)} failed: {fails}")
