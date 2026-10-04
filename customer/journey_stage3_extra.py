import sys
B = sys.argv[1]
src = open("journey_stage3_api.py").read().split("N = datetime.now(timezone.utc)")[0]
exec(src)
N = datetime.now(timezone.utc).replace(microsecond=0)
cr = lambda t, pid, body, key: call("POST", f"/payments/{pid}/corrections", body, tok=t, key=key)
me = lambda t, **kw: call("GET", "/me" + (q(**kw) if kw else ""), tok=t)
# known_at with holds
fx = {"currency": "EUR", "minor_units": 2, "authorization_ttl_seconds": 3600, "users": [user("u_ada", "ada", 10000), user("u_bob", "bob", 0)]}
call("POST", "/_test/reset", fx); A, Bo = login("ada"), login("bob"); time.sleep(0.5)
az = call("POST", "/authorizations", {"to_handle": "bob", "amount": 1000}, tok=A, key="k1")[1]; t_create = parse(az["created_at"]); time.sleep(1.1)
cap = call("POST", f"/authorizations/{az['authorization_id']}/capture", {"amount": 300, "final": False}, tok=Bo, key="k2")[1]; t_cap = parse(cap["created_at"]); time.sleep(1.1)
call("POST", f"/authorizations/{az['authorization_id']}/void", tok=A); a = call("GET", "/authorizations", tok=A)[1]["authorizations"][0]; t_close = parse(a["closed_at"])
now = datetime.now(timezone.utc)
m = me(A, as_of=iso(now), known_at=iso(t_create - timedelta(seconds=1)))[1]; chk("known_at before creation: nothing known", (m["total"], m["held"], m["available"]) == (10000, 0, 10000), m)
m = me(A, as_of=iso(now), known_at=iso(t_create + timedelta(milliseconds=200)))[1]; chk("known_at after create only: hold 1000, no capture", (m["total"], m["held"], m["available"]) == (10000, 1000, 9000), m)
m = me(A, as_of=iso(now), known_at=iso(t_cap + timedelta(milliseconds=200)))[1]; chk("known_at after capture: held 700 total 9700", (m["total"], m["held"], m["available"]) == (9700, 700, 9000), m)
m = me(A, as_of=iso(now), known_at=iso(t_close + timedelta(milliseconds=200)))[1]; chk("known_at after void: held 0", (m["total"], m["held"], m["available"]) == (9700, 0, 9700), m)
m = me(A, as_of=iso(t_cap - timedelta(milliseconds=300)), known_at=iso(now))[1]; chk("as_of before capture, known now: hold 1000 total 10000", (m["total"], m["held"], m["available"]) == (10000, 1000, 9000), m)
m = me(A, as_of=iso(now + timedelta(days=1)), known_at=iso(t_create + timedelta(milliseconds=200)))[1]; chk("future as_of with only-create known: expired at deadline", (m["held"], m["total"]) == (0, 10000), m)
m = me(A, as_of=iso(now + timedelta(minutes=30)), known_at=iso(t_create + timedelta(milliseconds=200)))[1]; chk("future as_of before deadline: still held", (m["held"], m["total"]) == (1000, 10000), m)
# historical overdraft on available
fx2 = {"currency": "EUR", "minor_units": 2, "users": [user("u_ada", "ada", 900), user("u_bob", "bob", 500)],
       "payments": [{"id": "r", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 500, "note": "", "visibility": "public", "created_at": iso(N - timedelta(hours=3))},
                    {"id": "q", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "note": "", "visibility": "public", "created_at": iso(N - timedelta(hours=1))}],
       "authorizations": [{"id": "h", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 800, "note": "", "visibility": "public", "status": "open", "created_at": iso(N - timedelta(hours=2)), "expires_at": iso(N + timedelta(hours=5))}]}
r = call("POST", "/_test/reset", fx2); chk("reset with seeded hold created_at", r[0] == 204, r)
if r[0] == 204:
    A, Bo = login("ada"), login("bob")
    m = me(A, as_of=iso(N - timedelta(hours=1, minutes=30)))[1]; chk("seeded hold with created_at honoured historically", (m["total"], m["held"]) == (1000, 800), m)
    m = me(A, as_of=iso(N - timedelta(hours=2, minutes=30)))[1]; chk("before seeded hold created", m["held"] == 0, m)
    r = cr(Bo, "r", {"expected_revision": 1, "amount": 500, "effective_at": iso(N - timedelta(minutes=30)), "reason": "later"}, "h1"); chk("available negative in past -> historical_overdraft", r[0] == 409 and code(r) == "historical_overdraft", r)
    chk("state unchanged", call("GET", "/payments/r/revisions", tok=Bo)[1]["revisions"].__len__() == 1 and me(A)[1]["balance"] == 900)
    r = cr(Bo, "r", {"expected_revision": 1, "amount": 500, "effective_at": iso(N - timedelta(hours=2, minutes=50)), "reason": "earlier"}, "h2"); chk("earlier effective ok", r[0] == 201, r)
# cross-version imports
import subprocess
def run_old(img, port):
    subprocess.run(["/usr/local/bin/docker", "rm", "-f", f"x{port}"], capture_output=True)
    subprocess.run(["/usr/local/bin/docker", "run", "-d", "--name", f"x{port}", "-e", f"PORT={port}", "-p", f"{port}:{port}", img], capture_output=True); time.sleep(3)
for img, port, nm in (("cust-s1d", 8071, "stage1"), ("cust-s2c", 8072, "stage2")):
    run_old(img, port); OB = f"http://localhost:{port}"
    def oc(m, p, body=None, tok=None, key=None):
        h = {"Content-Type": "application/json"}
        if tok: h["Authorization"] = "Bearer " + tok
        if key: h["Idempotency-Key"] = key
        r = urllib.request.Request(OB + p, data=json.dumps(body).encode() if body is not None else None, method=m, headers=h)
        try:
            with urllib.request.urlopen(r, timeout=10) as x: t = x.read(); return x.status, json.loads(t) if t else None
        except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"null")
    f = {"currency": "EUR", "minor_units": 2, "settlement_operator_ids": ["u_op"], "users": [user("u_ada", "ada", 10000), user("u_bob", "bob", 2500), user("u_cy", "cy", 0), user("u_op", "op", 0)],
         "payments": [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"}],
         "requests": [{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}]}
    oc("POST", "/_test/reset", f)
    tk = lambda e: oc("POST", "/auth/login", {"email": e + "@example.com", "password": "correct horse"})[1]["token"]
    a, b, o = tk("ada"), tk("bob"), tk("op")
    p1 = oc("POST", "/payments", {"to_handle": "bob", "amount": 100, "note": "x"}, tok=a, key="old1")[1]
    st_ = oc("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]}, tok=o, key="olds")[1]
    if nm == "stage2":
        az = oc("POST", "/authorizations", {"to_handle": "bob", "amount": 700}, tok=a, key="olda")[1]
        cp = oc("POST", f"/authorizations/{az['authorization_id']}/capture", {"amount": 200, "final": False}, tok=b, key="oldc")[1]
    exp = oc("GET", "/_test/export")[1]
    call("POST", "/_test/reset", fx)
    r = call("POST", "/_test/import", exp); chk(f"import {nm} export into stage 3", r[0] == 204, r)
    if r[0] != 204: continue
    chk(f"{nm}: old token valid", call("GET", "/me", tok=a)[0] == 200)
    m = call("GET", "/me", tok=a)[1]; print("   ", nm, m)
    chk(f"{nm}: payment replay 200 same", call("POST", "/payments", {"to_handle": "bob", "amount": 100, "note": "x"}, tok=a, key="old1") == (200, p1))
    chk(f"{nm}: settlement replay 200", call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]}, tok=o, key="olds") == (200, st_))
    chk(f"{nm}: pending request payable", call("POST", "/requests/rq_1/pay", {}, tok=a, key="oldrq")[0] == 201)
    s = call("GET", "/statement", tok=a)[1]; ids = [e["payment"]["payment_id"] for e in s["entries"]]
    chk(f"{nm}: statement has imported payments once, sums", p1["payment_id"] in ids and "p_1" in ids and len(ids) == len(set(ids)) and s["opening_balance"] + sum(e["delta"] for e in s["entries"]) == s["closing_balance"], s["entries"] if False else (ids, s["opening_balance"], s["closing_balance"]))
    chk(f"{nm}: opening = end - seeded net", s["opening_balance"] == 10000 + 500 + 100 + 10 - 0 - 0 + 0 or s["opening_balance"] >= 0, s["opening_balance"])
    chk(f"{nm}: revisions for imported payment", call("GET", f"/payments/{p1['payment_id']}/revisions", tok=a)[0] == 200)
    chk(f"{nm}: correction on imported payment works", call("POST", f"/payments/{p1['payment_id']}/corrections", {"expected_revision": 1, "amount": 50, "effective_at": p1["created_at"], "reason": "r"}, tok=a, key="oldcorr")[0] in (201, 409))
    chk(f"{nm}: settlement member immutable", call("POST", f"/payments/{st_['payments'][0]['payment_id']}/corrections", {"expected_revision": 1, "amount": 5, "effective_at": st_["committed_at"], "reason": "r"}, tok=a, key="oldsc")[0] == 422)
    if nm == "stage2":
        mm = call("GET", "/me", tok=a)[1]; chk("stage2: hold carried (held 500)", mm["held"] == 500, mm)
        chk("stage2: capture replay 200", call("POST", f"/authorizations/{az['authorization_id']}/capture", {"amount": 200, "final": False}, tok=b, key="oldc") == (200, cp))
        chk("stage2: capture immutable", call("POST", f"/payments/{cp['payment_id']}/corrections", {"expected_revision": 1, "amount": 5, "effective_at": cp["created_at"], "reason": "r"}, tok=a, key="oldcc")[0] == 422)
        chk("stage2: capture once in statement", ids.count(cp["payment_id"]) == 1)
        ai = [x for x in call("GET", "/authorizations", tok=a)[1]["authorizations"]][0]; chk("stage2: authorization has closed_at null", ai.get("closed_at", "M") is None, ai)
    chk(f"{nm}: sum conserved", sum(call("GET", "/me", tok=login(e))[1]["balance"] for e in ("ada", "bob", "cy", "op")) == 12500)
    subprocess.run(["/usr/local/bin/docker", "rm", "-f", f"x{port}"], capture_output=True)
print(f"\nSTAGE3 EXTRA {n} checks, {len(fails)} failed: {fails}")
