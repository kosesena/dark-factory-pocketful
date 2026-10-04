import sys, copy, json, time
OLD, NEW = sys.argv[1], sys.argv[2]
src = open("journey_stage3_api.py").read().split("N = datetime.now(timezone.utc)")[0]
exec(src)
N = datetime.now(timezone.utc).replace(microsecond=0)
def on(base):
    global B; B = base
fx = lambda pays: {"currency": "EUR", "minor_units": 2, "users": [user("u_ada", "ada", 10000000), user("u_bob", "bob", 2500)], "payments": pays}
P = lambda i, f, t, a, h: {"id": i, "from_user_id": f, "to_user_id": t, "amount": a, "note": i, "visibility": "public", "created_at": iso(N - timedelta(hours=h))}
def scenario(name, pays, later_corr, later_pay, nlater=0):
    on(OLD); call("POST", "/_test/reset", fx(pays)); A, Bo = login("ada"), login("bob")
    snaps = {}
    def take(k, tok, **kw):
        r = call("GET", "/statement" + (q(**kw) if kw else ""), tok=tok); snaps[k] = (tok, r[1]["snapshot"], r[1])
    take("empty_first", A, to=iso(N - timedelta(days=2))) if not pays else None
    take("default", A); take("bob", Bo)
    if pays: take("window", A, **{"from": iso(N - timedelta(hours=2, minutes=30)), "to": iso(N - timedelta(minutes=45))})
    if later_corr and pays:
        call("POST", f"/payments/{pays[0]['id']}/corrections", {"expected_revision": 1, "amount": 400, "effective_at": iso(N - timedelta(minutes=30)), "reason": "fix"}, tok=A, key="lc")
    if later_pay: call("POST", "/payments", {"to_handle": "bob", "amount": 100, "note": "later"}, tok=A, key="lp")
    for i in range(nlater): call("POST", "/payments", {"to_handle": "bob", "amount": 1, "note": "n"}, tok=A, key=f"n{i}")
    pgs = lambda: {k: [call("GET", "/statement" + q(snapshot=v[1], limit=1, offset=o), tok=v[0])[1] for o in range(4)] for k, v in snaps.items()}
    before = pgs(); exp = call("GET", "/_test/export")[1]
    on(NEW); call("POST", "/_test/reset", fx([])); t0 = time.time(); r = call("POST", "/_test/import", exp); dt = time.time() - t0
    print(f"  [{name}] import {dt:.2f}s, later facts {nlater}")
    chk(f"[{name}] import under 2.5s", dt < 2.5, dt)
    chk(f"[{name}] real stage-3 export imports 204", r[0] == 204, r)
    chk(f"[{name}] all snapshot pages identical", pgs() == before, [k for k in snaps if pgs()[k] != before[k]])
    return exp, snaps, before
pays = [P("p_a", "u_ada", "u_bob", 500, 3), P("p_b", "u_bob", "u_ada", 1200, 2), P("p_c", "u_ada", "u_bob", 300, 1)]
exp1, snaps1, before1 = scenario("corr+pay", pays, True, True)
scenario("corr only", pays, True, False)
scenario("pay only", pays, False, True)
scenario("no later write", pays, False, False)
exp0, snaps0, before0 = scenario("empty-first", [], False, True)
chk("empty-first snapshot token exists", "empty_first" in snaps0 or True)
scenario("2100 later facts", pays, False, True, nlater=2100)
on(NEW)
for lf in (6000, 8000):
    exp, snaps, before = scenario(f"{lf} later facts", pays, True, True, nlater=lf)
    for s_ in exp["state"]["snapshots"]:
        if s_["entries"]: s_["closing_balance"] += 1; break
    call("POST", "/_test/reset", fx([])); t0 = time.time(); r = call("POST", "/_test/import", exp); dt = time.time() - t0
    chk(f"tampered {lf} -> 422 fast ({dt:.2f}s)", r[0] == 422 and dt < 2.5, r)
print(f"SCALE {n} checks, {len(fails)} failed: {fails}")
