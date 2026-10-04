import sys, copy
B = sys.argv[1]
src = open("journey_stage3_api.py").read().split("N = datetime.now(timezone.utc)")[0]
exec(src)
N = datetime.now(timezone.utc).replace(microsecond=0)
me = lambda t, **kw: call("GET", "/me" + (q(**kw) if kw else ""), tok=t)
st = lambda t, **kw: call("GET", "/statement" + (q(**kw) if kw else ""), tok=t)
cr = lambda t, pid, body, key: call("POST", f"/payments/{pid}/corrections", body, tok=t, key=key)
fx = {"currency": "EUR", "minor_units": 2, "users": [user("u_ada", "ada", 10000), user("u_bob", "bob", 2500), user("u_cy", "cy", 300)],
      "payments": [{"id": "p_a", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "a", "visibility": "public", "created_at": iso(N - timedelta(hours=3))},
                   {"id": "p_b", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 1200, "note": "b", "visibility": "public", "created_at": iso(N - timedelta(hours=2))},
                   {"id": "p_c", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 300, "note": "c", "visibility": "private", "created_at": iso(N - timedelta(hours=1))}]}
call("POST", "/_test/reset", fx); A, Bo, C = login("ada"), login("bob"), login("cy")
cr(A, "p_a", {"expected_revision": 1, "amount": 400, "effective_at": iso(N - timedelta(minutes=30)), "reason": "fix"}, "c1")
ka = iso(datetime.now(timezone.utc))
cr(A, "p_a", {"expected_revision": 2, "amount": 350, "effective_at": iso(N - timedelta(minutes=20)), "reason": "fix2"}, "c2")
# several snapshots: default, windowed, known_at
snaps = {}
snaps["default"] = st(A)[1]
snaps["window"] = st(A, **{"from": iso(N - timedelta(hours=2, minutes=30)), "to": iso(N - timedelta(minutes=45))})[1]
snaps["known_at"] = st(A, known_at=ka)[1]
snaps["empty"] = st(A, to=iso(N - timedelta(days=1)))[1]
snaps["bob"] = st(Bo)[1]; snaps["cy"] = st(C)[1]
toks = {k: v["snapshot"] for k, v in snaps.items()}
owner = {"default": A, "window": A, "known_at": A, "empty": A, "bob": Bo, "cy": C}
pg = lambda k, tok_=None, **kw: call("GET", "/statement" + q(snapshot=toks[k], **kw), tok=tok_ or owner[k])
before = {k: [pg(k, limit=1, offset=o) for o in range(0, 6)] for k in toks}
exp = call("GET", "/_test/export")[1]
chk("export carries 6 snapshots", len(exp["state"]["snapshots"]) >= 6, len(exp["state"].get("snapshots", [])))
call("POST", "/_test/reset", fx)
r = call("POST", "/_test/import", exp); chk("genuine export with 6 old snapshots imports unchanged", r[0] == 204, r)
after = {k: [pg(k, limit=1, offset=o) for o in range(0, 6)] for k in toks}
chk("all snapshot pages identical after import", after == before, [k for k in toks if after[k] != before[k]])
chk("other-user snapshot 404 after import", pg("default", Bo)[0] == 404 and pg("bob", A)[0] == 404)
chk("snapshot + from/to/known_at still 422 after import", call("GET", "/statement" + q(snapshot=toks["default"], known_at=ka), tok=A)[0] == 422)
chk("known_at snapshot echo retained", pg("known_at")[1]["entries"] == snaps["known_at"]["entries"] if "entries" in pg("known_at")[1] else False)
# corruptions
e0 = exp
def snapshots(state): return state["snapshots"]
def find(state, key):
    for s in state["snapshots"]:
        if s["token"] == toks[key]: return s
def mut(label, fn, keys=("default",)):
    for key in keys:
        bad = copy.deepcopy(e0); s = find(bad["state"], key)
        try: fn(s, bad["state"])
        except Exception as ex: print("   skip", label, key, ex); continue
        r = call("POST", "/_test/import", bad)
        chk(f"corrupt snapshot [{label}/{key}] -> 422", r[0] == 422 and code(r) == "validation_failed", r)
        # state unchanged: previous (post-first-import) state still serves snapshot
        chk(f"  state unchanged after [{label}/{key}]", pg(key, limit=1, offset=0) == before[key][0])
def entry_field(i, v): 
    def f(s, st_): s["entries"][0][i] = v
    return f
print("   snapshot keys:", sorted(find(e0["state"], "default").keys()), "entry:", find(e0["state"], "default")["entries"][0])
mut("revision 99", entry_field(1, 99), ("default", "window"))
mut("wrong delta", entry_field(2, 12345), ("default",))
mut("wrong balance_after", entry_field(3, 1), ("default",))
mut("wrong effective_at", entry_field(4, "2020-01-01T00:00:00+00:00"), ("default", "known_at"))
mut("wrong recorded_at", entry_field(5, "2020-01-01T00:00:00+00:00"), ("default",))
mut("wrong amount", entry_field(6, 999), ("default", "known_at"))
mut("owner other user", lambda s, st_: s.__setitem__("user_id", "u_bob"), ("default",))
mut("owner unknown", lambda s, st_: s.__setitem__("user_id", "ghost"), ("default",))
mut("closing balance wrong", lambda s, st_: s.__setitem__("closing_balance", s["closing_balance"] + 1), ("default",))
mut("opening balance wrong", lambda s, st_: s.__setitem__("opening_balance", s["opening_balance"] + 1), ("default",))
mut("entry dropped", lambda s, st_: s["entries"].pop(), ("default",))
mut("entry duplicated", lambda s, st_: s["entries"].append(copy.deepcopy(s["entries"][0])), ("default",))
mut("entries reordered", lambda s, st_: s["entries"].reverse(), ("default",))
mut("entry unknown payment", lambda s, st_: s["entries"][0].__setitem__(0, "p_ghost"), ("default",))
def echo_kn(s, st_):
    s["echo"] = dict(s.get("echo", {}), known_at="2000-01-01T00:00:00+00:00")
mut("known_at echo early", echo_kn, ("known_at", "default"))
def echo_bad(s, st_): s["echo"] = dict(s.get("echo", {}), known_at="not-a-date")
mut("known_at echo bad", echo_bad, ("known_at",))
def win(s, st_): s["echo"] = dict(s.get("echo", {}), to="2000-01-01T00:00:00+00:00", **{"from": "1999-01-01T00:00:00+00:00"})
mut("window excludes entries", win, ("default", "window"))
mut("token duplicated", lambda s, st_: st_["snapshots"].append(copy.deepcopy(s)), ("default",))
mut("missing token", lambda s, st_: s.pop("token"), ("default",))
for k in ("taken_seq", "taken_ts"):
    if k in find(e0["state"], "default"):
        mut(f"{k} corrupt", lambda s, st_, k=k: s.__setitem__(k, 10 ** 9 if k == "taken_seq" else 1.0), ("default",))
# snapshots remain frozen after import + new writes
call("POST", "/payments", {"to_handle": "bob", "amount": 1}, tok=A, key="afterimp")
cr(A, "p_b", {"expected_revision": 1, "amount": 1100, "effective_at": iso(N - timedelta(minutes=10)), "reason": "x"}, "afterimp-c") if False else None
chk("snapshots still frozen after new writes post-import", [pg("default", limit=1, offset=o) for o in range(0, 6)] == before["default"])
# re-export/import twice idempotent
e1 = call("GET", "/_test/export")[1]; chk("re-import twice 204", call("POST", "/_test/import", e1)[0] == 204 and call("POST", "/_test/import", e1)[0] == 204)
chk("snapshot after double import", pg("window", limit=1, offset=0) == before["window"][0])
print(f"\nSNAP {n} checks, {len(fails)} failed: {fails}")
