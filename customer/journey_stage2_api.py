import json, sys, time, copy, threading, urllib.request
sys.argv = [sys.argv[0]] + sys.argv[1:]
B = sys.argv[1]
fails = []; n = 0
def call(m, p, body=None, tok=None, key=None, raw=None, hdr=None):
    h = {"Content-Type": "application/json"}
    if tok: h["Authorization"] = "Bearer " + tok
    if key is not None: h["Idempotency-Key"] = key
    if hdr: h.update(hdr)
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(B + p, data=data, method=m, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=10) as x: s, t = x.status, x.read()
    except urllib.error.HTTPError as e: s, t = e.code, e.read()
    try: return s, json.loads(t) if t else None
    except Exception: return s, t
def chk(name, cond, info=""):
    global n; n += 1
    if not cond: fails.append(name); print("FAIL", name, info)
    else: print("ok  ", name)
def code(r): return r[1]["error"]["code"] if isinstance(r[1], dict) and "error" in r[1] else None
def iso(dt): return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(dt))
now = time.time()
fx = {"currency": "EUR", "minor_units": 2, "authorization_ttl_seconds": 3600, "settlement_operator_ids": ["u_op"],
 "users": [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada", "handle": "ada", "balance": 10000},
           {"id": "u_bob", "email": "bob@example.com", "password": "correct horse", "display_name": "Bob", "handle": "bob", "balance": 2500},
           {"id": "u_cy", "email": "cy@example.com", "password": "correct horse", "display_name": "Cy", "handle": "cy", "balance": 0},
           {"id": "u_op", "email": "op@example.com", "password": "correct horse", "display_name": "Op", "handle": "op", "balance": 500}],
 "authorizations": [{"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "deposit", "visibility": "public", "status": "open", "expires_at": iso(now + 7200)},
                    {"id": "a_old", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 9999, "note": "old", "visibility": "public", "status": "open", "expires_at": iso(now - 7200)}]}
chk("reset 204", call("POST", "/_test/reset", fx)[0] == 204)
login = lambda e: call("POST", "/auth/login", {"email": e + "@example.com", "password": "correct horse"})[1]["token"]
A, Bo, C, O = [login(e) for e in ("ada", "bob", "cy", "op")]
me = lambda t: call("GET", "/me", tok=t)[1]
m = me(A); chk("me fields", m["balance"] == m["total"] == 10000 and m["held"] == 2000 and m["available"] == 8000, m)
chk("expired seeded not held", [x["status"] for x in call("GET", "/authorizations?status=expired", tok=A)[1]["authorizations"]] == ["expired"])
chk("bob no held", me(Bo)["held"] == 0)
# overheld reset
f2 = copy.deepcopy(fx); f2["authorizations"].append({"id": "a_2", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 9000, "status": "open", "expires_at": iso(now + 7200), "note": "", "visibility": "public"})
chk("over-held reset 422", call("POST", "/_test/reset", f2)[0] == 422 and me(A)["held"] == 2000)
f3 = copy.deepcopy(fx); f3["authorization_ttl_seconds"] = 0; chk("ttl 0 422", call("POST", "/_test/reset", f3)[0] == 422)
f3["authorization_ttl_seconds"] = 1.5; chk("ttl 1.5 422", call("POST", "/_test/reset", f3)[0] == 422)
f4 = copy.deepcopy(fx); del f4["authorizations"]; del f4["authorization_ttl_seconds"]; chk("omit authorizations ok", call("POST", "/_test/reset", f4)[0] == 204)
call("POST", "/_test/reset", fx); A, Bo, C, O = [login(e) for e in ("ada", "bob", "cy", "op")]
# create
az = lambda b, k, t=None: call("POST", "/authorizations", b, tok=t or A, key=k)
r = az({"to_handle": "bob", "amount": 3000, "note": "dep", "visibility": "private"}, "z1"); chk("authorize 201", r[0] == 201 and r[1]["status"] == "open" and r[1]["captured_amount"] == 0 and r[1]["remaining_amount"] == 3000 and r[1]["payment_id"] is None and r[1]["visibility"] == "private" and r[1]["from_handle"] == "ada", r)
a1 = r[1]; chk("replay", az({"to_handle": "bob", "amount": 3000, "note": "dep", "visibility": "private"}, "z1")[1] == a1)
chk("held 5000 avail 5000 total 10000", (me(A)["held"], me(A)["available"], me(A)["total"]) == (5000, 5000, 10000))
chk("not in feed", not any(p.get("note") == "dep" for p in call("GET", "/activity", tok=A)[1]["payments"]))
chk("ttl applied", abs(__import__("datetime").datetime.fromisoformat(a1["expires_at"]).timestamp() - __import__("datetime").datetime.fromisoformat(a1["created_at"]).timestamp() - 3600) < 1)
for nm, b, s, c in [("insuff", {"to_handle": "bob", "amount": 5001}, 409, "insufficient_funds"), ("self", {"to_handle": "ada", "amount": 5}, 422, "self_payment"), ("unk", {"to_handle": "zz", "amount": 5}, 404, "not_found"),
                    ("amt0", {"to_handle": "bob", "amount": 0}, 422, "validation_failed"), ("vis", {"to_handle": "bob", "amount": 5, "visibility": "x"}, 422, "validation_failed"), ("note", {"to_handle": "bob", "amount": 5, "note": "x" * 201}, 422, "validation_failed"), ("frac", {"to_handle": "bob", "amount": 1.5}, 422, "validation_failed")]:
    r = az(b, "zv" + nm); chk("authorize " + nm, r[0] == s and code(r) == c, r)
chk("authorize no key", code(call("POST", "/authorizations", {"to_handle": "bob", "amount": 5}, tok=A)) == "missing_idempotency_key")
chk("exactly available ok", az({"to_handle": "bob", "amount": 5000}, "zall")[0] == 201 and me(A)["available"] == 0)
# held cannot fund payments
chk("payment blocked by hold", code(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, tok=A, key="hp")) == "insufficient_funds")
chk("hold can't fund settlement", code(call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}, tok=O, key="hs")) == "insufficient_funds")
# request pay uses available
rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 10}, tok=Bo, key="rqa")[1]["request_id"]
chk("pay request vs available", code(call("POST", f"/requests/{rq}/pay", {}, tok=A, key="pra")) == "insufficient_funds")
chk("split ignores balance", call("POST", "/splits", {"amount": 99999, "participant_handles": ["ada", "bob"]}, tok=A, key="spl")[0] == 201)
call("POST", "/authorizations/" + [x for x in call("GET", "/authorizations?limit=200", tok=A)[1]["authorizations"] if x["amount"] == 5000][0]["authorization_id"] + "/void", tok=A)
chk("void released", me(A)["available"] == 5000)
# capture
cap = lambda i, b, k, t=None: call("POST", f"/authorizations/{i}/capture", b, tok=t or Bo, key=k)
id1 = a1["authorization_id"]
chk("payer capture 403", cap(id1, {}, "c0", A)[0] == 403)
chk("third capture 403", cap(id1, {}, "c0", C)[0] == 403)
chk("third void 403", call("POST", f"/authorizations/{id1}/void", tok=C)[0] == 403)
chk("receiver void 403", call("POST", f"/authorizations/{id1}/void", tok=Bo)[0] == 403)
chk("unknown 404", cap("nope", {}, "c0")[0] == 404)
r = cap(id1, {"amount": 3001}, "cx"); chk("exceeds 422", r[0] == 422 and code(r) == "capture_exceeds_authorization", r)
chk("amount 0 422", code(cap(id1, {"amount": 0}, "c00")) == "validation_failed")
chk("final non-bool 400/422", cap(id1, {"amount": 1, "final": "no"}, "cf")[0] in (400, 422))
r = cap(id1, {"amount": 1000, "final": False}, "c1"); chk("partial capture", r[0] == 201 and r[1]["authorization_id"] == id1 and r[1]["request_id"] is None and r[1]["amount"] == 1000 and r[1]["visibility"] == "private" and r[1]["note"] == "dep", r)
p_1 = r[1]
chk("partial: stays open", (lambda a: a["status"] == "open" and a["captured_amount"] == 1000 and a["remaining_amount"] == 2000 and a["payment_id"] == p_1["payment_id"] and a["payment_ids"] == [p_1["payment_id"]])([x for x in call("GET", "/authorizations", tok=A)[1]["authorizations"] if x["authorization_id"] == id1][0]))
chk("balances after partial", (me(A)["total"], me(A)["held"], me(A)["available"], me(Bo)["total"]) == (9000, 4000, 5000, 3500), me(A))
chk("replay capture 200", cap(id1, {"amount": 1000, "final": False}, "c1")[0] == 200)
chk("replay diff body 409", code(cap(id1, {"amount": 1000}, "c1")) == "idempotency_key_reuse")
r = cap(id1, {"amount": 2001}, "c2x"); chk("exceeds remaining 422", code(r) == "capture_exceeds_authorization", r)
r = cap(id1, {"amount": 500}, "c2"); chk("final capture 500 releases 1500", r[0] == 201, r)
chk("closed", (lambda a: a["status"] == "captured" and a["captured_amount"] == 1500 and a["remaining_amount"] == 0 and len(a["payment_ids"]) == 2)([x for x in call("GET", "/authorizations", tok=A)[1]["authorizations"] if x["authorization_id"] == id1][0]))
chk("released", (me(A)["total"], me(A)["held"], me(A)["available"]) == (8500, 2000, 6500), me(A))
r = cap(id1, {}, "c3"); chk("capture closed 409", r[0] == 409 and code(r) == "authorization_not_open", r)
chk("void captured 409", code(call("POST", f"/authorizations/{id1}/void", tok=A)) == "authorization_not_open")
chk("capture payments in bob feed", p_1["payment_id"] in [p["payment_id"] for p in call("GET", "/activity", tok=Bo)[1]["payments"]])
chk("private capture hidden from cy", p_1["payment_id"] not in [p["payment_id"] for p in call("GET", "/activity", tok=C)[1]["payments"]])
chk("replay capture after close 200", cap(id1, {"amount": 1000, "final": False}, "c1")[0] == 200)
# default capture
r = az({"to_handle": "bob", "amount": 800}, "z8"); i8 = r[1]["authorization_id"]
r = cap(i8, {}, "d1"); chk("default capture full", r[0] == 201 and r[1]["amount"] == 800, r)
r = az({"to_handle": "bob", "amount": 800}, "z9"); i9 = r[1]["authorization_id"]
r = cap(i9, {"amount": 800, "final": False}, "d2"); chk("full remainder closes w/ final false", r[0] == 201 and call("GET", "/authorizations?status=captured", tok=A)[1]["authorizations"][0]["remaining_amount"] == 0, r)
r = az({"to_handle": "bob", "amount": 800}, "z10"); i10 = r[1]["authorization_id"]
cap(i10, {"amount": 300, "final": False}, "d3")
r = call("POST", f"/authorizations/{i10}/void", tok=A); chk("void partial releases remainder only", r[0] == 200 and r[1]["status"] == "voided" and r[1]["captured_amount"] == 300 and len(r[1]["payment_ids"]) == 1, r)
chk("void twice 200", call("POST", f"/authorizations/{i10}/void", tok=A)[0] == 200)
chk("capture voided 409", code(cap(i10, {}, "d4")) == "authorization_not_open")
# list
l = call("GET", "/authorizations?direction=incoming&limit=2", tok=Bo)[1]; chk("list incoming paged", len(l["authorizations"]) == 2 and l["has_more"] is True)
chk("list outgoing for bob empty", call("GET", "/authorizations?direction=outgoing", tok=Bo)[1]["authorizations"] == [])
chk("cy sees none", call("GET", "/authorizations", tok=C)[1]["authorizations"] == [])
for q in ("?direction=x", "?status=x", "?limit=0", "?offset=-1", "?limit=1e1"): chk("auth list bad " + q, call("GET", "/authorizations" + q, tok=A)[0] == 422)
cs = [x["created_at"] for x in call("GET", "/authorizations", tok=A)[1]["authorizations"]]; chk("newest first", cs == sorted(cs, reverse=True))
chk("HTML for browser", "text/html" in urllib.request.urlopen(urllib.request.Request(B + "/authorizations", headers={"Accept": "text/html"})).headers["Content-Type"])
chk("JSON w/o accept", call("GET", "/authorizations", tok=A)[0] == 200 and call("GET", "/authorizations")[0] == 401)
for p in ("/", "/requests", "/split", "/signup", "/login"):
    chk("html " + p, urllib.request.urlopen(urllib.request.Request(B + p, headers={"Accept": "text/html"})).status == 200)
chk("requests JSON w/o accept", call("GET", "/requests", tok=A)[0] == 200)
# expiry by clock: ttl 2s
f5 = copy.deepcopy(fx); f5["authorization_ttl_seconds"] = 2; f5["authorizations"] = []; call("POST", "/_test/reset", f5)
A, Bo = login("ada"), login("bob")
i = az({"to_handle": "bob", "amount": 1000}, "e1")[1]["authorization_id"]
cap(i, {"amount": 400, "final": False}, "e2")
chk("held before expiry", me(A)["held"] == 600)
time.sleep(3)
chk("expiry releases remainder", me(A)["held"] == 0 and me(A)["available"] == 9600 and me(A)["total"] == 9600, me(A))
x = call("GET", "/authorizations", tok=A)[1]["authorizations"][0]; chk("status expired, captures kept", x["status"] == "expired" and x["captured_amount"] == 400 and len(x["payment_ids"]) == 1 and x["remaining_amount"] == 0, x)
chk("open filter excludes", call("GET", "/authorizations?status=open", tok=A)[1]["authorizations"] == [])
r = cap(i, {}, "e3"); chk("capture expired -> not_open/expired 409", r[0] == 409 and code(r) in ("authorization_expired", "authorization_not_open"), r)
chk("void expired 409", code(call("POST", f"/authorizations/{i}/void", tok=A)) == "authorization_not_open")
i2 = az({"to_handle": "bob", "amount": 100}, "e4")[1]["authorization_id"]; time.sleep(2.5)
r = cap(i2, {}, "e5"); chk("capture past deadline authorization_expired", r[0] == 409 and code(r) == "authorization_expired", r)
# concurrency: capture race
f6 = copy.deepcopy(fx); f6["authorizations"] = []; call("POST", "/_test/reset", f6); A, Bo = login("ada"), login("bob")
i = az({"to_handle": "bob", "amount": 1000}, "r1")[1]["authorization_id"]
res = []
def go(k): res.append(cap(i, {"amount": 300, "final": False}, f"k{k}")[0])
th = [threading.Thread(target=go, args=(k,)) for k in range(20)]; [t.start() for t in th]; [t.join() for t in th]
chk("20 concurrent captures of 300/1000: 3 succeed", res.count(201) == 3 and not [s for s in res if s >= 500], sorted(res))
chk("sum conserved", sum(me(t)["total"] for t in (A, Bo, C, O)) == 13000 if (C := login("cy")) and (O := login("op")) else False)
res = []
def go2(k): res.append(call("POST", "/payments", {"to_handle": "cy", "amount": 600}, tok=A, key=f"q{k}")[0])
az({"to_handle": "bob", "amount": 5000}, "hold5")
th = [threading.Thread(target=go2, args=(k,)) for k in range(20)]; [t.start() for t in th]; [t.join() for t in th]
chk("concurrent payments vs hold never dip below available", me(A)["available"] >= 0 and me(A)["total"] - me(A)["held"] == me(A)["available"], me(A))
# JPY and BHD
for cur, mu in (("JPY", 0), ("BHD", 3)):
    f7 = copy.deepcopy(fx); f7["currency"] = cur; f7["minor_units"] = mu; call("POST", "/_test/reset", f7); t = login("ada")
    mm = me(t); chk("currency " + cur, mm["currency"] == cur and mm["minor_units"] == mu and mm["held"] == 2000 and mm["available"] == 8000, mm)
# stage1 export -> stage2 import: tolerate any; self roundtrip with holds
call("POST", "/_test/reset", fx); A, Bo = login("ada"), login("bob")
az({"to_handle": "bob", "amount": 100}, "x1"); s = call("GET", "/_test/export")[1]
call("POST", "/_test/reset", fx); chk("import w/ holds", call("POST", "/_test/import", s)[0] == 204 and me(A)["held"] == 2100 and az({"to_handle": "bob", "amount": 100}, "x1")[0] == 200)
print(f"\nSTAGE2 API {n} checks, {len(fails)} failed: {fails}")
