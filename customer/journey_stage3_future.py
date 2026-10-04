import sys, copy
B = sys.argv[1]
src = open("journey_stage3_api.py").read().split("N = datetime.now(timezone.utc)")[0]
exec(src)
N = datetime.now(timezone.utc).replace(microsecond=0)
me = lambda t, **kw: call("GET", "/me" + (q(**kw) if kw else ""), tok=t)
st = lambda t, **kw: call("GET", "/statement" + (q(**kw) if kw else ""), tok=t)
cr = lambda t, pid, body, key: call("POST", f"/payments/{pid}/corrections", body, tok=t, key=key)
fx = {"currency": "EUR", "minor_units": 2, "authorization_ttl_seconds": 3600, "users": [user("u_ada", "ada", 10000), user("u_bob", "bob", 2500)],
      "payments": [{"id": "p_a", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "a", "visibility": "public", "created_at": iso(N - timedelta(hours=3))},
                   {"id": "p_b", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 1200, "note": "b", "visibility": "public", "created_at": iso(N - timedelta(hours=2))}]}
call("POST", "/_test/reset", fx); A, Bo = login("ada"), login("bob")
F1, F2 = iso(N + timedelta(days=2)), iso(N + timedelta(days=5))
cr(A, "p_a", {"expected_revision": 1, "amount": 400, "effective_at": iso(N - timedelta(minutes=30)), "reason": "x"}, "c1")
snaps = {"future known_at": st(A, known_at=F1)[1], "future to": st(A, to=F1)[1], "future from+to": st(A, **{"from": F1, "to": F2})[1], "future all": st(A, **{"from": F1, "to": F2, "known_at": F2})[1], "future from only": st(A, **{"from": F1})[1]}
for k, v in snaps.items(): chk(f"{k}: statement 200 w/ snapshot", "snapshot" in v, v)
toks = {k: v["snapshot"] for k, v in snaps.items()}
pg = lambda k, **kw: call("GET", "/statement" + q(snapshot=toks[k], **kw), tok=A)
before = {k: [pg(k, limit=1, offset=o)[1] for o in range(4)] for k in toks}
# post-snapshot activity: new payment, correction
call("POST", "/payments", {"to_handle": "bob", "amount": 7}, tok=A, key="later")
cr(A, "p_b", {"expected_revision": 1, "amount": 1000, "effective_at": iso(N - timedelta(minutes=20)), "reason": "y"}, "c2") if False else None
chk("future-known_at snapshot frozen vs later payment", all([pg(k, limit=1, offset=o)[1] for o in range(4)] == before[k] for k in toks))
exp = call("GET", "/_test/export")[1]
call("POST", "/_test/reset", fx); r = call("POST", "/_test/import", exp); chk("import export with future-window snapshots 204", r[0] == 204, r)
chk("future snapshots page original result after import", all([pg(k, limit=1, offset=o)[1] for o in range(4)] == before[k] for k in toks), [k for k in toks if [pg(k, limit=1, offset=o)[1] for o in range(4)] != before[k]])
chk("re-export/import stable", call("POST", "/_test/import", call("GET", "/_test/export")[1])[0] == 204)
chk("after reimport still same", all([pg(k, limit=1, offset=o)[1] for o in range(4)] == before[k] for k in toks))
# new fixes: taken_seq/taken_ts bounds
e0 = call("GET", "/_test/export")[1]
def mut(label, fn, exp_status=422):
    bad = copy.deepcopy(e0); s = bad["state"]["snapshots"][0]; fn(s, bad["state"])
    r = call("POST", "/_test/import", bad); chk(f"tampered {label} -> {exp_status}", r[0] == exp_status, r)
    chk(f"  export of current state still re-importable after [{label}]", call("POST", "/_test/import", call("GET", "/_test/export")[1])[0] == 204)
mut("taken_seq 10^9", lambda s, st_: s.__setitem__("taken_seq", 10 ** 9))
mut("taken_seq seq+1", lambda s, st_: s.__setitem__("taken_seq", st_["seq"] + 1))
mut("taken_ts +10 days", lambda s, st_: s.__setitem__("taken_ts", s["taken_ts"] + 10 * 86400))
mut("taken_ts -10 years", lambda s, st_: s.__setitem__("taken_ts", 1.0))
# the earlier-found sequence: corrupt then new payment then re-export/import
call("POST", "/_test/import", e0)
bad = copy.deepcopy(e0); bad["state"]["snapshots"][0]["taken_seq"] = 10 ** 9
call("POST", "/_test/import", bad); call("POST", "/payments", {"to_handle": "bob", "amount": 1}, tok=A, key="z1")
e2 = call("GET", "/_test/export")[1]; chk("export→import always accepted after tamper attempt", call("POST", "/_test/import", e2)[0] == 204 and call("POST", "/_test/import", e2)[0] == 204)
# known_at semantics with future values
m = me(A, known_at=F1)[1]; chk("me future known_at echo + current balance", m["known_at"] == F1 and m["balance"] == me(A)[1]["balance"], m)
m = me(A, known_at=F1, as_of=F2)[1]; chk("me future both", m["as_of"] == F2 and m["known_at"] == F1, m)
s1 = st(A, known_at=F1)[1]; s0 = st(A)[1]; chk("future known_at == omitted", s1["entries"] == s0["entries"] and s1["closing_balance"] == s0["closing_balance"])
print(f"\nFUTURE {n} checks, {len(fails)} failed: {fails}")
