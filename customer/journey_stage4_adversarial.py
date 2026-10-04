import sys, copy, json, time
OLD, NEW = sys.argv[1], sys.argv[2]
NL = int(sys.argv[3]) if len(sys.argv) > 3 else 6000
NS = int(sys.argv[4]) if len(sys.argv) > 4 else 20
NC = int(sys.argv[5]) if len(sys.argv) > 5 else 5000
src = open("journey_stage3_api.py").read().split("N = datetime.now(timezone.utc)")[0]
exec(src)
def on(b):
    global B; B = b
def now_s(): return datetime.now(timezone.utc).replace(microsecond=0)
def fx(): return {"currency": "EUR", "minor_units": 2, "users": [user("u_ada", "ada", 10**8), user("u_bob", "bob", 1000), user("u_cy", "cy", 1000)], "payments": []}
def pay(t, h, a, k): return call("POST", "/payments", {"to_handle": h, "amount": a, "note": "n"}, tok=t, key=k)
def imp(exp, label, want, limit=2.5):
    on(NEW); call("POST", "/_test/reset", fx()); t0 = time.time(); r = call("POST", "/_test/import", exp); dt = time.time() - t0
    print(f"  {label}: {r[0]} in {dt:.2f}s"); chk(f"{label} -> {want} within {limit}s", r[0] == want and dt < limit, (r[0], dt)); return r
def swap(exp):
    e = copy.deepcopy(exp)
    for s in e["state"]["snapshots"]:
        en = s["entries"]
        if len(en) >= 2 and en[0][4] == en[1][4]:
            en[0], en[1] = en[1], en[0]; b = s["opening_balance"]
            for x in en: b += x[2]; x[3] = b
            s["closing_balance"] = b
    return e
def shift(exp):
    e = copy.deepcopy(exp)
    for s in e["state"]["snapshots"]:
        if s["entries"]: s["closing_balance"] += 1; break
    return e
# --- A: closed-window same-instant swap, NL later out-of-window payments, NS snapshots
on(OLD); call("POST", "/_test/reset", fx()); A, Bo, C = login("ada"), login("bob"), login("cy")
while time.time() % 1 > 0.2: time.sleep(0.02)
pay(A, "bob", 1, "w1"); pay(A, "bob", 2, "w2")
cut = datetime.now(timezone.utc)
cutq = cut.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+00:00"
toks = [call("GET", "/statement" + q(limit=1, to=cutq), tok=A)[1]["snapshot"] for _ in range(NS)]
time.sleep(1.2)
for i in range(NL): pay(A, "bob", 1, f"a{i}")
exp = call("GET", "/_test/export")[1]
print("A: snapshots", len(exp["state"]["snapshots"]), "entries0", len(exp["state"]["snapshots"][0]["entries"]))
imp(exp, f"A genuine closed-window N={NL} K={NS}", 204)
imp(swap(exp), f"A same-instant swap N={NL} K={NS}", 422)
imp(shift(exp), f"A shift+1 N={NL} K={NS}", 422)
# --- B: same-amount corrections of the first payment, many snapshots
on(OLD); call("POST", "/_test/reset", fx()); A, Bo, C = login("ada"), login("bob"), login("cy")
ids = []
for i in range(1000): ids.append(pay(A, "bob", 5, f"b{i}")[1]["payment_id"])
for j in range(NS): call("GET", "/statement" + q(limit=1), tok=A)
rev = 1
for i in range(NC):
    r = call("POST", f"/payments/{ids[0]}/corrections", {"expected_revision": rev, "amount": 5, "effective_at": iso(now_s()), "reason": "same"}, tok=A, key=f"c{i}")
    if r[0] != 201: print("corr fail", r); break
    rev += 1
exp = call("GET", "/_test/export")[1]
imp(exp, f"B genuine 1000 payments, {rev-1} same-amount corrections, K={NS}", 204, 4.5)
imp(shift(exp), "B shift+1", 422, 4.5)
# --- C: combination: several users, windows/known_at snapshots, corrections + out-of-window later payments
on(OLD); call("POST", "/_test/reset", fx()); A, Bo, C = login("ada"), login("bob"), login("cy")
while time.time() % 1 > 0.2: time.sleep(0.02)
pay(A, "bob", 1, "x1"); pay(A, "bob", 2, "x2"); pay(Bo, "cy", 1, "x3")
mid = datetime.now(timezone.utc); midq = mid.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+00:00"
ids = [pay(A, "cy", 3, f"y{i}")[1]["payment_id"] for i in range(200)]
for tk in (A, Bo, C):
    for j in range(max(1, NS // 3)):
        call("GET", "/statement" + q(limit=1, to=midq), tok=tk); call("GET", "/statement" + q(limit=1, known_at=midq), tok=tk); call("GET", "/statement" + q(limit=1), tok=tk)
rev = 1
for i in range(1000):
    r = call("POST", f"/payments/{ids[0]}/corrections", {"expected_revision": rev, "amount": 3, "effective_at": iso(now_s()), "reason": "same"}, tok=A, key=f"z{i}")
    if r[0] == 201: rev += 1
time.sleep(1.2)
for i in range(NL): pay(A, "bob", 1, f"c{i}")
exp = call("GET", "/_test/export")[1]
print("C: snapshots", len(exp["state"]["snapshots"]))
imp(exp, f"C combo genuine N={NL}", 204, 4.5)
imp(swap(exp), "C swap", 422, 4.5)
imp(shift(exp), "C shift+1", 422, 4.5)
print(f"ADVERSARIAL {n} checks, {len(fails)} failed: {fails}")
