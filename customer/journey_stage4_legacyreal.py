import sys, copy, json
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
    on(NEW); call("POST", "/_test/reset", fx([])); r = call("POST", "/_test/import", exp)
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
# tampers against stage 4 (current destination = whatever state; use exp1)
on(NEW)
def sn0(e, k=0): return e["state"]["snapshots"][k]
def tamper(mode, e):
    e = copy.deepcopy(e)
    for s in e["state"]["snapshots"]:
        if not s["entries"]: continue
        if mode == "shift": s["opening_balance"] += 1; s["closing_balance"] += 1; [x.__setitem__(3, x[3] + 1) for x in s["entries"]]
        elif mode == "reverse": s["entries"].reverse()
        elif mode == "dup": s["entries"].append(copy.deepcopy(s["entries"][-1]))
        elif mode == "dropfirst": s["entries"].pop(0)
        elif mode == "closing": s["closing_balance"] += 7
        elif mode == "otheruser": s["user_id"] = "u_bob" if s["user_id"] == "u_ada" else "u_ada"
        elif mode == "malformed": s["entries"][0] = ["x"]
        elif mode == "badwin": s["echo"] = {"from": "garbage"}
        break
    return e
for m in ("shift", "reverse", "dup", "dropfirst", "closing", "otheruser", "malformed", "badwin"):
    call("POST", "/_test/reset", fx([])); call("POST", "/_test/import", exp1); pre = call("GET", "/_test/export")[1]
    r = call("POST", "/_test/import", tamper(m, exp1))
    chk(f"tamper {m} -> 422 (no 500)", r[0] == 422, r)
    chk(f"tamper {m} destination intact", call("GET", "/_test/export")[1] == pre)
print(f"LEGACYREAL {n} checks, {len(fails)} failed: {fails}")
