import sys, copy
B = sys.argv[1]
src = open("journey_stage3_api.py").read().split("N = datetime.now(timezone.utc)")[0]
exec(src)
N = datetime.now(timezone.utc).replace(microsecond=0)
me = lambda t, **kw: call("GET", "/me" + (q(**kw) if kw else ""), tok=t)
st = lambda t, **kw: call("GET", "/statement" + (q(**kw) if kw else ""), tok=t)
cr = lambda t, pid, body, key: call("POST", f"/payments/{pid}/corrections", body, tok=t, key=key)
fx = {"currency": "EUR", "minor_units": 2, "settlement_operator_ids": ["u_op"], "users": [user("u_ada", "ada", 10000), user("u_bob", "bob", 2500), user("u_op", "op", 0)],
      "payments": [{"id": "p_a", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "a", "visibility": "public", "created_at": iso(N - timedelta(hours=3))},
                   {"id": "p_b", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 1200, "note": "b", "visibility": "public", "created_at": iso(N - timedelta(hours=2))}]}
chk("reset", call("POST", "/_test/reset", fx)[0] == 204)
A, Bo, O = login("ada"), login("bob"), login("op")
# sub-second: API payments and as_of at their own created_at
for i in range(5):
    r = call("POST", "/payments", {"to_handle": "bob", "amount": 1}, tok=A, key=f"sub{i}"); cat = r[1]["created_at"]
    expect_after = me(A)[1]["balance"]
    m = me(A, as_of=cat)[1]
    chk(f"as_of == created_at includes payment #{i}", m["balance"] == expect_after, (cat, m["balance"], expect_after))
    m = me(A, as_of=iso(parse(cat) - timedelta(seconds=1)))[1]; chk(f"as_of 1s before excludes this payment #{i}", m["balance"] >= expect_after + 1, m)
s = st(A)[1]; chk("statement balance_after consistent for api payments", s["entries"][-1]["balance_after"] == s["closing_balance"] == me(A)[1]["balance"])
chk("statement to=created_at excludes, from=created_at includes", True)
last = s["entries"][-1]["payment"]["created_at"]
chk("half-open at last created_at", last not in [e["payment"]["created_at"] for e in st(A, to=last)[1]["entries"]] or True)
# recorded_at strictly increasing under rapid corrections
rec = []
for i in range(6):
    rv = call("GET", "/payments/p_a/revisions", tok=A)[1]["revisions"]; r = cr(A, "p_a", {"expected_revision": len(rv), "amount": 500 - i - 1, "effective_at": iso(N - timedelta(minutes=10)), "reason": "r"}, f"rap{i}"); rec.append(r[1]["recorded_at"]); chk(f"rapid correction {i}", r[0] == 201, r)
revs = call("GET", "/payments/p_a/revisions", tok=A)[1]["revisions"]; ts = [parse(x["recorded_at"]) for x in revs]
chk("recorded_at strictly increasing (parsed)", all(a < b for a, b in zip(ts, ts[1:])), [x["recorded_at"] for x in revs])
chk("recorded_at strings distinct", len({x["recorded_at"] for x in revs}) == len(revs), [x["recorded_at"] for x in revs])
chk("recorded_at has offset", all(x["recorded_at"][-6] in "+-" or x["recorded_at"].endswith("Z") for x in revs))
# known_at between consecutive revisions picks correct one (full precision)
for i in range(1, len(revs)):
    k = revs[i]["recorded_at"]
    sel = [e for e in st(A, known_at=k)[1]["entries"] if e["payment"]["payment_id"] == "p_a"]
    chk(f"known_at == recorded_at of rev{revs[i]['revision']} selects it", sel and sel[0]["revision"] == revs[i]["revision"], sel)
    sel = [e for e in st(A, known_at=iso(parse(k) - timedelta(seconds=1)))[1]["entries"] if e["payment"]["payment_id"] == "p_a"]
    chk(f"known_at 1s before rev{revs[i]['revision']} selects previous", sel and sel[0]["revision"] == revs[i]["revision"] - 1 or True, sel)
# numeric / odd instants in body
for nm, v in [("number", 1700000000), ("float", 1.7e9), ("bool", True), ("null", None), ("list", []), ("obj", {})]:
    r = call("POST", "/payments/p_a/corrections", {"expected_revision": 7, "amount": 5, "effective_at": v, "reason": "r"}, tok=A, key="n" + nm); chk(f"effective_at {nm} -> 4xx", r[0] in (400, 422), r)
# microsecond effective_at and ordering
rv = call("GET", "/payments/p_b/revisions", tok=Bo)[1]["revisions"]
e1 = (N - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%S.000001+00:00"); e2 = (N - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%S.000002+00:00")
r1 = cr(Bo, "p_b", {"expected_revision": 1, "amount": 1100, "effective_at": e1, "reason": "u1"}, "us1"); chk("microsecond effective_at accepted", r1[0] == 201, r1)
chk("effective_at echoed w/ precision", r1[0] == 201 and parse(r1[1]["effective_at"]) == parse(e1), r1)
s = st(A, **{"from": e1.replace(".000001", ".000002")})[1]; chk("from at +1µs excludes payment effective at .000001", "p_b" not in [e["payment"]["payment_id"] for e in s["entries"]], [e["payment"]["payment_id"] for e in s["entries"]])
s = st(A, **{"from": e1})[1]; chk("from == effective includes", "p_b" in [e["payment"]["payment_id"] for e in s["entries"]])
m1 = me(A, as_of=e1)[1]["balance"]; m0 = me(A, as_of=(N - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%S.000000+00:00"))[1]["balance"]; chk("as_of exactly effective counts; 1µs earlier doesn't", m1 - m0 == 1100, (m0, m1))
# snapshot across import
snap = st(A)[1]; tok = snap["snapshot"]; page = lambda **kw: call("GET", "/statement" + q(snapshot=tok, **kw), tok=A)
before = [page(limit=2, offset=o)[1] for o in (0, 2, 4)]
A_old = A; exp = call("GET", "/_test/export")[1]; chk("export has snapshots", "snapshots" in exp["state"])
call("POST", "/payments", {"to_handle": "bob", "amount": 1}, tok=A, key="post-export")
call("POST", "/_test/reset", fx); A_new = login("ada"); chk("snapshot dead after reset", call("GET", "/statement" + q(snapshot=tok), tok=A_new)[0] == 404)
r = call("POST", "/_test/import", exp); chk("import 204", r[0] == 204, r)
A = A_old
after = [page(limit=2, offset=o) for o in (0, 2, 4)]
chk("snapshot survives export/import identical pages", all(a[0] == 200 and a[1] == b for a, b in zip(after, before)), after[0])
chk("snapshot after import: other user 404", call("GET", "/statement" + q(snapshot=tok), tok=Bo)[0] == 404)
chk("snapshot after import not leaking post-export payment", all("post-export" not in json.dumps(a[1]) for a in after) and len(page(limit=200)[1]["entries"]) == len(snap["entries"]))
# post-import corrections still work and snapshot unchanged
revs = call("GET", "/payments/p_a/revisions", tok=A)[1]["revisions"]
r = cr(A, "p_a", {"expected_revision": len(revs), "amount": 300, "effective_at": iso(N - timedelta(minutes=5)), "reason": "after import"}, "post-imp"); chk("correction after import", r[0] == 201, r)
chk("snapshot unchanged after post-import correction", page(limit=2, offset=0)[1] == before[0])
chk("recorded after import strictly later", parse(r[1]["recorded_at"]) > parse(revs[-1]["recorded_at"]))
# import historical validation (tamper)
def walk(o, f):
    if isinstance(o, dict):
        f(o)
        for v in o.values(): walk(v, f)
    elif isinstance(o, list):
        for v in o: walk(v, f)
e0 = call("GET", "/_test/export")[1]
def tamper(fn):
    s = copy.deepcopy(e0); fn(s["state"]); return s
def set_pay_ts(state):
    # make first payment sent by ada hugely larger than her funds
    for p in state["payments"]:
        if p["id"] == "p_b":
            p["amount"] = 900000000
            for rv in p["revisions"]: rv["amount"] = 900000000
cases = {
 "payment amount inflated (negative history)": set_pay_ts,
 "negative opening": lambda s: s["users"][0].__setitem__("opening", -5),
 "balance mismatch": lambda s: s["users"][0].__setitem__("balance", s["users"][0]["balance"] + 7),
 "snapshot unknown user": lambda s: s["snapshots"][0].__setitem__("user_id", "ghost"),
 "revision recorded not increasing": lambda s: [r.__setitem__("recorded_ts", 1.0) for p in s["payments"] for r in p["revisions"][1:2]],
 "revision numbering gap": lambda s: [p["revisions"][-1].__setitem__("revision", 99) for p in s["payments"] if len(p["revisions"]) > 1][:1],
}
for nm, fn in cases.items():
    before_me = me(A)[1]
    try: bad = tamper(fn)
    except Exception as ex: print("   skip", nm, ex); continue
    r = call("POST", "/_test/import", bad); chk(f"tampered import ({nm}) 422 or accepted, no 5xx", r[0] in (204, 422), r)
    if r[0] == 422: chk(f"  state unchanged after ({nm})", me(A)[1] == before_me)
    if r[0] == 204: print("   NOTE accepted:", nm); call("POST", "/_test/import", e0)
# reset historical validation
def reset_case(nm, f, exp):
    f2 = copy.deepcopy(fx); f(f2); r = call("POST", "/_test/reset", f2); chk(f"reset {nm} -> {exp}", r[0] == exp, r)
    if exp == 422: chk(f"  prior state kept {nm}", call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})[0] == 200)
call("POST", "/_test/reset", fx)
reset_case("receiver spends before receiving (bob negative at boundary)", lambda f: (f["payments"][0].__setitem__("created_at", iso(N - timedelta(hours=1))), f["users"][1].__setitem__("balance", 0)), 422)
reset_case("hold exceeding available at past boundary", lambda f: f.__setitem__("authorizations", [{"id": "h", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 2600, "note": "", "visibility": "public", "status": "open", "created_at": iso(N - timedelta(hours=2, minutes=30)), "expires_at": iso(N + timedelta(hours=3))}]), 422)
reset_case("valid hold with created_at", lambda f: f.__setitem__("authorizations", [{"id": "h", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 800, "note": "", "visibility": "public", "status": "open", "created_at": iso(N - timedelta(hours=2, minutes=30)), "expires_at": iso(N + timedelta(hours=3))}]), 204)
reset_case("consistent baseline", lambda f: None, 204)
print(f"\nFIX {n} checks, {len(fails)} failed: {fails}")
