import sys, copy
B = sys.argv[1]
src = open("journey_stage3_api.py").read().split("N = datetime.now(timezone.utc)")[0]
exec(src)
N = datetime.now(timezone.utc).replace(microsecond=0)
st = lambda t, **kw: call("GET", "/statement" + (q(**kw) if kw else ""), tok=t)
cr = lambda t, pid, body, key: call("POST", f"/payments/{pid}/corrections", body, tok=t, key=key)
fx = {"currency": "EUR", "minor_units": 2, "users": [user("u_ada", "ada", 10000), user("u_bob", "bob", 2500)],
      "payments": [{"id": "p_a", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "a", "visibility": "public", "created_at": iso(N - timedelta(hours=3))},
                   {"id": "p_b", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 1200, "note": "b", "visibility": "public", "created_at": iso(N - timedelta(hours=2))}]}
call("POST", "/_test/reset", fx); A = login("ada")
cr(A, "p_a", {"expected_revision": 1, "amount": 400, "effective_at": iso(N - timedelta(minutes=30)), "reason": "fix"}, "c1")
s = st(A)[1]; tok = s["snapshot"]
pages = lambda: [call("GET", "/statement" + q(snapshot=tok, limit=1, offset=o), tok=A) for o in range(4)]
before = pages()
exp = call("GET", "/_test/export")[1]
def snap0(e): return e["state"]["snapshots"][0]
print("snapshot keys:", sorted(snap0(exp).keys()))
def legacy(e):
    e = copy.deepcopy(e); sn = snap0(e)
    for k in ("taken_ts", "taken_seq", "view"): sn.pop(k, None)
    return e
# genuine legacy shape imports unchanged
call("POST", "/_test/reset", fx); r = call("POST", "/_test/import", legacy(exp))
chk("genuine legacy-shaped snapshot imports 204", r[0] == 204, r)
chk("legacy snapshot pages identical", pages() == before)
# mutations, each in full and legacy shape
def mut(e, mode):
    sn = snap0(e)
    if mode == "drop-last": sn["entries"].pop(); sn["closing_balance"] = sn["entries"][-1][3]
    elif mode == "empty": sn["entries"] = []; sn["closing_balance"] = sn["opening_balance"]
    elif mode == "shift":
        sn["opening_balance"] += 1; sn["closing_balance"] += 1
        for x in sn["entries"]: x[3] += 1
    elif mode == "closing+1": sn["closing_balance"] += 1
    elif mode == "swap": sn["entries"].reverse()
    elif mode == "dup": sn["entries"].append(copy.deepcopy(sn["entries"][-1]))
    return e
for leg in (False, True):
    for mode in ("drop-last", "empty", "shift", "closing+1", "swap", "dup"):
        call("POST", "/_test/reset", fx); call("POST", "/_test/import", exp)
        pre = call("GET", "/_test/export")[1]
        e = mut(legacy(exp) if leg else copy.deepcopy(exp), mode)
        r = call("POST", "/_test/import", e)
        chk(f"{'legacy' if leg else 'full'} {mode} -> 422", r[0] == 422, r)
        chk(f"{'legacy' if leg else 'full'} {mode} state intact", call("GET", "/_test/export")[1] == pre and pages() == before)
# genuine full-shape still fine, double import
call("POST", "/_test/reset", fx); chk("full export imports", call("POST", "/_test/import", exp)[0] == 204)
chk("full pages identical", pages() == before)
chk("re-export/import", call("POST", "/_test/import", call("GET", "/_test/export")[1])[0] == 204 and pages() == before)
print(f"LEGACY {n} checks, {len(fails)} failed: {fails}")
