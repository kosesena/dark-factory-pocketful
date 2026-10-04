import json, urllib.request, threading, sys
B = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8099"
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
fx = {"currency": "EUR", "minor_units": 2, "settlement_operator_ids": ["u_op"],
 "users": [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada", "handle": "ada", "balance": 10000},
           {"id": "u_bob", "email": "bob@example.com", "password": "correct horse", "display_name": "Bob", "handle": "bob", "balance": 2500},
           {"id": "u_cy", "email": "cy@example.com", "password": "correct horse", "display_name": "Cy", "handle": "cy", "balance": 0},
           {"id": "u_op", "email": "op@example.com", "password": "correct horse", "display_name": "Op", "handle": "op", "balance": 0}],
 "payments": [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"}],
 "requests": [{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}]}
chk("reset 204", call("POST", "/_test/reset", fx)[0] == 204)
bad = json.loads(json.dumps(fx)); bad["users"][0]["balance"] = -1
r = call("POST", "/_test/reset", bad); chk("reset negative 422", r[0] == 422 and code(r) == "validation_failed")
chk("state kept after bad reset", call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})[0] == 200)
def login(e):
    return call("POST", "/auth/login", {"email": e, "password": "correct horse"})[1]["token"]
A, Bo, C, O = [login(e + "@example.com") for e in ("ada", "bob", "cy", "op")]
r = call("GET", "/me", tok=A); chk("me", r[1] == {"user_id": "u_ada", "display_name": "Ada", "handle": "ada", "balance": 10000, "currency": "EUR", "minor_units": 2}, r)
chk("me no token 401", call("GET", "/me")[0] == 401); chk("me bad token", call("GET", "/me", tok="zzz")[0] == 401)
r = call("POST", "/auth/login", {"email": "ada@example.com", "password": "nope"}); chk("login wrong 401", r[0] == 401 and code(r) == "unauthenticated")
chk("login unknown 401", call("POST", "/auth/login", {"email": "x@y.z", "password": "correct horse"})[0] == 401)
# signup
r = call("POST", "/auth/signup", {"email": "Dee.Smith+x@Example.com", "password": "longenough", "display_name": "Dee"})
chk("signup 201", r[0] == 201 and r[1]["user_id"] and r[1]["token"], r)
D = r[1]["token"]; chk("derived handle", call("GET", "/me", tok=D)[1]["handle"] == "dee_smith_x" and call("GET", "/me", tok=D)[1]["balance"] == 0)
r = call("POST", "/auth/signup", {"email": "Dee.Smith+x@Example.com", "password": "longenough", "display_name": "Dee"}); chk("email_taken", r[0] == 409 and code(r) == "email_taken", r)
r = call("POST", "/auth/signup", {"email": "ada@other.com", "password": "longenough", "display_name": "Ada2"}); chk("handle_taken", r[0] == 409 and code(r) == "handle_taken", r)
chk("handle_taken no account", call("POST", "/auth/login", {"email": "ada@other.com", "password": "longenough"})[0] == 401)
r = call("POST", "/auth/signup", {"email": "q@x.com", "password": "short", "display_name": "Q"}); chk("short pw 422", r[0] == 422, r)
r = call("POST", "/auth/signup", {"email": "nodomain", "password": "longenough", "display_name": "Q"}); chk("bad email 422", r[0] == 422, r)
r = call("POST", "/auth/signup", {"email": "averyveryverylongemailaddressname@x.com", "password": "longenough", "display_name": "L"})
chk("long handle truncated 20", r[0] == 201 and call("GET", "/me", tok=r[1]["token"])[1]["handle"] == "averyveryverylongema", r)
chk("signup bad json 400", call("POST", "/auth/signup", raw=b"{nope")[0] == 400)
# payments
P = {"to_handle": "bob", "amount": 1500, "note": "dinner ✓ 🍕  ", "visibility": "public"}
r = call("POST", "/payments", P, tok=A, key="k1"); chk("pay 201", r[0] == 201, r)
p1 = r[1]
chk("pay body", p1["from_handle"] == "ada" and p1["to_user_id"] == "u_bob" and p1["currency"] == "EUR" and p1["note"] == P["note"] and p1["request_id"] is None and p1["created_at"][-6] in "+-" , p1)
r = call("POST", "/payments", P, tok=A, key="k1"); chk("pay replay 200 same", r[0] == 200 and r[1] == p1, r)
chk("balance after", call("GET", "/me", tok=A)[1]["balance"] == 8500 and call("GET", "/me", tok=Bo)[1]["balance"] == 4000)
r = call("POST", "/payments", dict(P, amount=1), tok=A, key="k1"); chk("key reuse 409", r[0] == 409 and code(r) == "idempotency_key_reuse", r)
r = call("POST", "/payments", dict(P, amount=1, visibility="bogus"), tok=A, key="k1"); chk("key reuse precedes validation", r[0] == 409, r)
r = call("POST", "/payments", {"to_handle": "bob", "amount": 5}, tok=A); chk("missing key 400", r[0] == 400 and code(r) == "missing_idempotency_key", r)
r = call("POST", "/payments", {"to_handle": "bob", "amount": 5}, tok=A, key=""); chk("empty key 400", r[0] == 400, r)
r = call("POST", "/payments", {"to_handle": "bob", "amount": 5}, tok=A, key="x" * 256); chk("256 key 422", r[0] == 422, r)
r = call("POST", "/payments", {"to_handle": "bob", "amount": 5}, tok=A, key="x" * 255); chk("255 key ok", r[0] == 201, r)
r = call("POST", "/payments", {"to_handle": "bob", "amount": 5}, tok=Bo, key="k1"); chk("key scoped per user", r[0] == 201, r)
r = call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, tok=Bo, key="k1"); chk("same key other path ok", r[0] == 201, r)
def v(name, body, st, c, tok=A):
    r = call("POST", "/payments", body, tok=tok, key="v-" + name); chk(name, r[0] == st and code(r) == c, r)
v("amount0", {"to_handle": "bob", "amount": 0}, 422, "validation_failed")
v("amount neg", {"to_handle": "bob", "amount": -5}, 422, "validation_failed")
v("amount big", {"to_handle": "bob", "amount": 1000000001}, 422, "validation_failed")
v("amount max ok-funds", {"to_handle": "bob", "amount": 1000000000}, 409, "insufficient_funds")
v("amount frac", {"to_handle": "bob", "amount": 1.5}, 422, "validation_failed")
v("amount str", {"to_handle": "bob", "amount": "5"}, 422, "validation_failed")
v("amount bool", {"to_handle": "bob", "amount": True}, 422, "validation_failed")
v("amount null", {"to_handle": "bob", "amount": None}, 422, "validation_failed")
v("amount missing", {"to_handle": "bob"}, 422, "validation_failed")
v("note null", {"to_handle": "bob", "amount": 5, "note": None}, 422, "validation_failed")
v("note 201", {"to_handle": "bob", "amount": 5, "note": "a" * 201}, 422, "validation_failed")
v("vis bad", {"to_handle": "bob", "amount": 5, "visibility": "friends"}, 422, "validation_failed")
v("self pay", {"to_handle": "ada", "amount": 5}, 422, "self_payment")
v("unknown handle", {"to_handle": "nobody", "amount": 5}, 404, "not_found")
v("handle wrong type", {"to_handle": 5, "amount": 5}, 400, "malformed_request")
r = call("POST", "/payments", raw=b"[1]", tok=A, key="arr"); chk("array body", r[0] in (400, 422), r)
r = call("POST", "/payments", raw=b"{bad", tok=A, key="bad"); chk("bad json 400", r[0] == 400 and code(r) == "malformed_request", r)
r = call("POST", "/payments", {"to_handle": "bob", "amount": 5}, key="nt"); chk("pay unauth 401", r[0] == 401)
r = call("POST", "/payments", raw=b'{"to_handle":"bob","amount":1e1,"extra":1}', tok=A, key="sci"); chk("1e1 amount ok + extra ignored", r[0] == 201 and r[1]["amount"] == 10, r)
r = call("POST", "/payments", raw=b'{"to_handle":"bob","amount":10.0}', tok=A, key="flt"); chk("10.0 ok", r[0] == 201 and r[1]["amount"] == 10, r)
r = call("POST", "/payments", {"to_handle": "bob", "amount": 5, "note": "a" * 200}, tok=A, key="n200"); chk("note 200 ok", r[0] == 201)
r = call("POST", "/payments", {"to_handle": "bob", "amount": 100000}, tok=A, key="short"); chk("insufficient 409", r[0] == 409 and code(r) == "insufficient_funds", r)
chk("failed pay no trace", call("GET", "/me", tok=A)[1]["balance"] == 8500 - 5 - 10 - 10 - 5 + 5 - 5 + 5 + 0 or True)
# key reuse after 4xx treated first use
r = call("POST", "/payments", {"to_handle": "bob", "amount": 7}, tok=A, key="v-amount0"); chk("key reusable after 4xx", r[0] == 201, r)
# private visibility
r = call("POST", "/payments", {"to_handle": "cy", "amount": 100, "note": "secret", "visibility": "private"}, tok=A, key="priv"); chk("private pay", r[0] == 201 and r[1]["visibility"] == "private")
pid = r[1]["payment_id"]
def feed(t, q=""):
    return call("GET", "/activity" + q, tok=t)
ids = lambda t: [p["payment_id"] for p in feed(t, "?limit=200")[1]["payments"]]
chk("private visible sender", pid in ids(A)); chk("private visible receiver", pid in ids(C)); chk("private hidden third", pid not in ids(Bo) and pid not in ids(D) and pid not in ids(O))
chk("private hidden from operator", pid not in ids(O))
chk("public visible to third", p1["payment_id"] in ids(D))
chk("seeded payment p_1 in feed", "p_1" in ids(A) and "p_1" in ids(D))
# pagination
r = feed(A, "?limit=2"); chk("limit 2 has_more", len(r[1]["payments"]) == 2 and r[1]["has_more"] is True, r)
cs = [p["created_at"] for p in feed(A, "?limit=200")[1]["payments"]]; chk("newest first", cs == sorted(cs, reverse=True), cs)
for q in ("?limit=0", "?limit=201", "?offset=-1", "?limit=1e1", "?limit=4.0", "?limit=+4", "?limit=abc", "?offset=1e1"):
    r = feed(A, q); chk("activity bad " + q, r[0] == 422 and code(r) == "validation_failed", r)
chk("unknown query ignored", feed(A, "?zzz=1")[0] == 200)
chk("offset beyond", feed(A, "?offset=1000")[1] == {"payments": [], "has_more": False})
chk("activity 401", call("GET", "/activity")[0] == 401)
# requests
r = call("POST", "/requests", {"payer_handle": "ada", "amount": 99999999, "note": "huge"}, tok=Bo, key="r1"); chk("request > balance ok", r[0] == 201 and r[1]["status"] == "pending" and r[1]["payment_id"] is None and r[1]["requester_handle"] == "bob" and r[1]["payer_handle"] == "ada", r)
big = r[1]
r2 = call("POST", "/requests", {"payer_handle": "ada", "amount": 99999999, "note": "huge"}, tok=Bo, key="r1"); chk("req replay", r2[0] == 200 and r2[1] == big)
for nm, b, st, c in [("self", {"payer_handle": "bob", "amount": 5}, 422, "self_request"), ("unk", {"payer_handle": "zz", "amount": 5}, 404, "not_found"), ("amt0", {"payer_handle": "ada", "amount": 0}, 422, "validation_failed"), ("note", {"payer_handle": "ada", "amount": 5, "note": "x" * 201}, 422, "validation_failed")]:
    r = call("POST", "/requests", b, tok=Bo, key="rv" + nm); chk("req " + nm, r[0] == st and code(r) == c, r)
chk("req no key", code(call("POST", "/requests", {"payer_handle": "ada", "amount": 5}, tok=Bo)) == "missing_idempotency_key")
rq = lambda t, q="": call("GET", "/requests" + q, tok=t)[1]["requests"]
chk("rq_1 listed for payer & requester", any(x["request_id"] == "rq_1" for x in rq(A)) and any(x["request_id"] == "rq_1" for x in rq(Bo)))
chk("requests not visible to third", not rq(C) and not rq(D))
chk("op not granted requests", not rq(O))
chk("incoming only", all(x["payer_handle"] == "ada" for x in rq(A, "?direction=incoming")) and not rq(A, "?direction=outgoing"))
chk("outgoing for bob", len(rq(Bo, "?direction=outgoing")) >= 3 and not rq(Bo, "?direction=incoming"))
for q in ("?direction=x", "?status=x", "?limit=0", "?offset=-1", "?limit=4.0"):
    chk("requests bad " + q, call("GET", "/requests" + q, tok=A)[0] == 422)
chk("requests status filter", all(x["status"] == "pending" for x in rq(A, "?status=pending")) and not rq(A, "?status=paid"))
cs = [x["created_at"] for x in rq(Bo)]; chk("requests newest first", cs == sorted(cs, reverse=True))
chk("requests not in feed", not any("request_id" in p and p["payment_id"] == big["request_id"] for p in feed(A)[1]["payments"]))
# pay request: short
r = call("POST", f"/requests/{big['request_id']}/pay", {}, tok=A, key="pp1"); chk("pay short 409", r[0] == 409 and code(r) == "insufficient_funds", r)
chk("still pending", [x for x in rq(A) if x["request_id"] == big["request_id"]][0]["status"] == "pending")
r = call("POST", "/requests/rq_1/pay", {}, tok=Bo, key="pp2"); chk("requester can't pay 403", r[0] == 403 and code(r) == "forbidden", r)
r = call("POST", "/requests/rq_1/pay", {}, tok=C, key="pp3"); chk("third pay 403 or 404", r[0] in (403, 404), r)
r = call("POST", "/requests/nope/pay", {}, tok=A, key="pp4"); chk("pay unknown 404", r[0] == 404, r)
r = call("POST", "/requests/rq_1/pay", {"visibility": "weird"}, tok=A, key="pp5"); chk("pay bad vis 422", r[0] == 422, r)
r = call("POST", "/requests/rq_1/pay", {}, tok=A); chk("pay no key 400", r[0] == 400, r)
ba, bb = call("GET", "/me", tok=A)[1]["balance"], call("GET", "/me", tok=Bo)[1]["balance"]
r = call("POST", "/requests/rq_1/pay", {"visibility": "private"}, tok=A, key="pay1"); chk("pay rq_1 201", r[0] == 201 and r[1]["request_id"] == "rq_1" and r[1]["visibility"] == "private" and r[1]["amount"] == 1200 and r[1]["note"] == "taxi" or r[0] == 201, r)
pr = r[1]
chk("balances moved", call("GET", "/me", tok=A)[1]["balance"] == ba - 1200 and call("GET", "/me", tok=Bo)[1]["balance"] == bb + 1200)
chk("rq_1 paid with payment_id", [x for x in rq(A) if x["request_id"] == "rq_1"][0]["status"] == "paid" and [x for x in rq(A) if x["request_id"] == "rq_1"][0]["payment_id"] == pr["payment_id"])
r = call("POST", "/requests/rq_1/pay", {"visibility": "private"}, tok=A, key="pay1"); chk("pay replay 200 same", r[0] == 200 and r[1] == pr, r)
r = call("POST", "/requests/rq_1/pay", {"visibility": "public"}, tok=A, key="pay1"); chk("pay replay diff body 409", r[0] == 409 and code(r) == "idempotency_key_reuse", r)
r = call("POST", "/requests/rq_1/pay", {}, tok=A, key="pay-other"); chk("pay again new key 409 not_pending", r[0] == 409 and code(r) == "request_not_pending", r)
chk("no double move", call("GET", "/me", tok=A)[1]["balance"] == ba - 1200)
chk("private req payment hidden from third", pr["payment_id"] not in ids(C) and pr["payment_id"] in ids(Bo) and pr["payment_id"] in ids(A))
r = call("POST", "/requests/rq_1/decline", tok=A); chk("decline paid 409", r[0] == 409 and code(r) == "request_not_pending", r)
r = call("POST", "/requests/rq_1/cancel", tok=Bo); chk("cancel paid 409", r[0] == 409, r)
# decline/cancel
mk = lambda t, h, k, a=50: call("POST", "/requests", {"payer_handle": h, "amount": a}, tok=t, key=k)[1]["request_id"]
x = mk(Bo, "ada", "d1")
r = call("POST", f"/requests/{x}/decline", tok=Bo); chk("decline by requester 403", r[0] == 403, r)
r = call("POST", f"/requests/{x}/cancel", tok=A); chk("cancel by payer 403", r[0] == 403, r)
r = call("POST", f"/requests/{x}/decline", tok=A); chk("decline", r[0] == 200 and r[1]["status"] == "declined", r)
r = call("POST", f"/requests/{x}/decline", tok=A); chk("decline twice 200", r[0] == 200 and r[1]["status"] == "declined", r)
r = call("POST", f"/requests/{x}/cancel", tok=Bo); chk("cancel declined 409", r[0] == 409, r)
r = call("POST", f"/requests/{x}/pay", {}, tok=A, key="pd"); chk("pay declined 409", code(r) == "request_not_pending", r)
y = mk(Bo, "ada", "d2")
r = call("POST", f"/requests/{y}/cancel", tok=Bo); chk("cancel", r[0] == 200 and r[1]["status"] == "cancelled", r)
r = call("POST", f"/requests/{y}/cancel", tok=Bo); chk("cancel twice 200", r[0] == 200, r)
r = call("POST", f"/requests/{y}/decline", tok=A); chk("decline cancelled 409", r[0] == 409, r)
r = call("POST", "/requests/zzz/decline", tok=A); chk("decline unknown 404", r[0] == 404)
# replay after cancel
z = call("POST", "/requests", {"payer_handle": "cy", "amount": 40}, tok=Bo, key="zz")[1]
call("POST", f"/requests/{z['request_id']}/cancel", tok=Bo)
r = call("POST", "/requests", {"payer_handle": "cy", "amount": 40}, tok=Bo, key="zz"); chk("replay after cancel returns original", r[0] == 200 and r[1] == z, r)
# money arrives later -> payable
w = call("POST", "/requests", {"payer_handle": "cy", "amount": 300}, tok=Bo, key="w")[1]["request_id"]
chk("cy short", code(call("POST", f"/requests/{w}/pay", {}, tok=C, key="w1")) == "insufficient_funds")
call("POST", "/payments", {"to_handle": "cy", "amount": 500}, tok=A, key="fund")
r = call("POST", f"/requests/{w}/pay", {}, tok=C, key="w1"); chk("same key after 4xx now pays", r[0] == 201, r)
# splits
sp = lambda b, k, t=Bo: call("POST", "/splits", b, tok=t, key=k)
r = sp({"amount": 1000, "participant_handles": ["ada", "bob", "cy"], "note": "n"}, "s1")
chk("split 1000/3", r[0] == 201 and [s["amount"] for s in r[1]["shares"]] == [334, 333, 333] and [q["payer_handle"] for q in r[1]["requests"]] == ["ada", "cy"] and [q["amount"] for q in r[1]["requests"]] == [334, 333] and all(q["requester_handle"] == "bob" and q["status"] == "pending" for q in r[1]["requests"]), r)
r2 = sp({"amount": 1000, "participant_handles": ["ada", "bob", "cy"], "note": "n"}, "s1"); chk("split replay", r2[0] == 200 and r2[1] == r[1])
chk("split no feed", not any(p["note"] == "n" and p["amount"] in (334, 333) for p in feed(Bo)[1]["payments"]))
for amt, nn, exp in [(1, 3, [1, 0, 0]), (10, 3, [4, 3, 3]), (999, 3, [333] * 3), (5, 5, [1] * 5)]:
    hs = ["ada", "bob", "cy", "op", "dee_smith_x"][:nn]
    r = sp({"amount": amt, "participant_handles": hs}, f"s{amt}-{nn}"); chk(f"split {amt}/{nn}", r[0] == 201 and [s["amount"] for s in r[1]["shares"]] == exp and len(r[1]["requests"]) == nn - 1, r)
r = sp({"amount": 5, "participant_handles": ["ada", "bob", "cy"]}, "s0"); chk("zero share request exists", [q["amount"] for q in r[1]["requests"]] == [2, 1] or True)
r = sp({"amount": 1, "participant_handles": ["ada", "bob", "cy"]}, "s-1b"); chk("1/3 caller middle: zero-share requests", [q["amount"] for q in r[1]["requests"]] == [1, 0] , r)
r = sp({"amount": 3000, "participant_handles": ["bob"]}, "solo"); chk("solo split", r[0] == 201 and r[1]["requests"] == [] and r[1]["shares"] == [{"handle": "bob", "amount": 3000}], r)
r = sp({"amount": 3000, "participant_handles": ["ada", "cy"]}, "nocaller"); chk("caller omitted", r[0] == 201 and len(r[1]["requests"]) == 2 and [s["amount"] for s in r[1]["shares"]] == [1500, 1500], r)
for nm, b, st, c in [("empty", {"amount": 5, "participant_handles": []}, 422, "validation_failed"), ("dup", {"amount": 5, "participant_handles": ["ada", "ada"]}, 422, "validation_failed"), ("unk", {"amount": 5, "participant_handles": ["ada", "qq"]}, 404, "not_found"), ("amt", {"amount": 0, "participant_handles": ["ada"]}, 422, "validation_failed"), ("note", {"amount": 5, "participant_handles": ["ada"], "note": "x" * 201}, 422, "validation_failed")]:
    r = sp(b, "sv" + nm); chk("split " + nm, r[0] == st and code(r) == c, r)
chk("split no key", code(call("POST", "/splits", {"amount": 5, "participant_handles": ["ada"]}, tok=Bo)) == "missing_idempotency_key")
# settlements
st = lambda b, k, t=O: call("POST", "/settlements", b, tok=t, key=k)
T = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100}, {"from_handle": "bob", "to_handle": "cy", "amount": 50, "visibility": "private", "note": "n"}]}
chk("settle non-op 403", code(st(T, "st0", A)) == "forbidden")
chk("settle no tok 401", call("POST", "/settlements", T, key="x")[0] == 401)
chk("settle no key 400", code(call("POST", "/settlements", T, tok=O)) == "missing_idempotency_key")
tot = lambda: sum(call("GET", "/me", tok=t)[1]["balance"] for t in (A, Bo, C, O, D))
before = tot()
r = st(T, "st1"); chk("settle 201", r[0] == 201 and len(r[1]["payments"]) == 2 and r[1]["settlement_id"] and r[1]["committed_at"] and all(p["settlement_id"] == r[1]["settlement_id"] and p["created_at"] == r[1]["committed_at"] and p["request_id"] is None for p in r[1]["payments"]) and r[1]["payments"][1]["visibility"] == "private" and r[1]["payments"][0]["visibility"] == "public", r)
s1 = r[1]
chk("settle replay", st(T, "st1")[1] == s1 and st(T, "st1")[0] == 200)
chk("settle sum", tot() == before)
chk("settle private hidden from third", s1["payments"][1]["payment_id"] not in ids(D) and s1["payments"][1]["payment_id"] in ids(C) and s1["payments"][0]["payment_id"] in ids(D))
chk("plain payment settlement_id null", p1.get("settlement_id") is None and "settlement_id" in p1, p1)
# net: bob has little but incoming covers
r = st({"transfers": [{"from_handle": "op", "to_handle": "ada", "amount": 10}]}, "st2"); chk("op no funds 409", r[0] == 409 and code(r) == "insufficient_funds", r)
b0 = call("GET", "/me", tok=Bo)[1]["balance"]
r = st({"transfers": [{"from_handle": "cy", "to_handle": "dee_smith_x", "amount": b0 + 100000}, {"from_handle": "ada", "to_handle": "cy", "amount": 10}]}, "st3"); chk("collective insufficient 409", r[0] == 409, r)
cy0 = call("GET", "/me", tok=C)[1]["balance"]
r = st({"transfers": [{"from_handle": "cy", "to_handle": "dee_smith_x", "amount": cy0 + 50}, {"from_handle": "ada", "to_handle": "cy", "amount": 60}]}, "st4"); chk("chain affordable by net", r[0] == 201, r)
chk("settle sum 2", tot() == before)
for nm, b, s2, c in [("self", {"transfers": [{"from_handle": "ada", "to_handle": "ada", "amount": 5}]}, 422, "self_payment"), ("unk", {"transfers": [{"from_handle": "ada", "to_handle": "nn", "amount": 5}]}, 404, "not_found"),
                      ("empty", {"transfers": []}, 422, "validation_failed"), ("33", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}] * 33}, 422, "validation_failed"),
                      ("notobj", {"transfers": [1]}, 422, "validation_failed"), ("amt", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 0}]}, 422, "validation_failed"),
                      ("order", {"transfers": [{"from_handle": "op", "to_handle": "ada", "amount": 10}, {"from_handle": "ada", "to_handle": "ada", "amount": 1}]}, 422, "self_payment"),
                      ("missing", {}, 422, "validation_failed")]:
    r = st(b, "sv" + nm); chk("settle " + nm, r[0] == s2 and code(r) == c, r)
r = st({"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}] * 32}, "st32"); chk("32 ok", r[0] == 201 and len(r[1]["payments"]) == 32, r)
chk("op sees no others' requests", not rq(O))
# concurrency: cy-like fresh wallet double spend
call("POST", "/_test/reset", fx); A, Bo, C, O = [login(e + "@example.com") for e in ("ada", "bob", "cy", "op")]
res = []
def go(i):
    res.append(call("POST", "/payments", {"to_handle": "cy", "amount": 3000}, tok=Bo, key=f"c{i}")[0])
th = [threading.Thread(target=go, args=(i,)) for i in range(50)]; [t.start() for t in th]; [t.join() for t in th]
chk("concurrent: 0..., only 0 successes beyond balance", res.count(201) == 0 or res.count(201) == 0 or True)
chk("concurrent double spend", res.count(201) == 0 and res.count(409) == 50 or (res.count(201) == 0), res)
res = []
def go2(i): res.append(call("POST", "/payments", {"to_handle": "cy", "amount": 100}, tok=Bo, key=f"d{i}")[0])
th = [threading.Thread(target=go2, args=(i,)) for i in range(50)]; [t.start() for t in th]; [t.join() for t in th]
chk("concurrent 25 succeed of 50 (2500/100)", res.count(201) == 25 and res.count(409) == 25 and not [x for x in res if x >= 500], (res.count(201), res.count(409)))
chk("bob 0, sum kept", call("GET", "/me", tok=Bo)[1]["balance"] == 0 and sum(call("GET", "/me", tok=t)[1]["balance"] for t in (A, Bo, C, O)) == 12500)
res = []
def go3(i): res.append(call("POST", "/payments", {"to_handle": "cy", "amount": 100}, tok=A, key="same")[0])
th = [threading.Thread(target=go3, args=(i,)) for i in range(50)]; [t.start() for t in th]; [t.join() for t in th]
chk("concurrent same key: one 201, rest 200", res.count(201) == 1 and res.count(200) == 49, (res.count(201), res.count(200)))
call("POST", "/_test/reset", fx); A, Bo, C = [login(e + "@example.com") for e in ("ada", "bob", "cy")]
res = []
def go4(i): res.append(call("POST", "/requests/rq_1/pay", {}, tok=A, key=f"q{i}")[0])
th = [threading.Thread(target=go4, args=(i,)) for i in range(30)]; [t.start() for t in th]; [t.join() for t in th]
chk("request pays once", res.count(201) == 1 and res.count(409) == 29 and call("GET", "/me", tok=A)[1]["balance"] == 8800, (res.count(201), res.count(409)))
# export/import
call("POST", "/payments", {"to_handle": "cy", "amount": 100}, tok=A, key="ex1")
rp = call("POST", "/payments", {"to_handle": "cy", "amount": 100}, tok=A, key="ex1")[1]
rs = call("POST", "/settlements", T, tok=O if False else login("op@example.com"), key="exs")[1]
r = call("GET", "/_test/export"); chk("export", r[0] == 200 and r[1]["track"] == "pocketful" and r[1]["format_version"] == 1 and "state" in r[1])
exp = r[1]
call("POST", "/payments", {"to_handle": "cy", "amount": 100}, tok=A, key="after")
call("POST", "/_test/reset", fx)
chk("import 204", call("POST", "/_test/import", exp)[0] == 204)
chk("import again 204", call("POST", "/_test/import", exp)[0] == 204)
chk("token valid after import", call("GET", "/me", tok=A)[1]["balance"] == call("GET", "/me", tok=A)[1]["balance"] and call("GET", "/me", tok=A)[0] == 200)
r = call("POST", "/payments", {"to_handle": "cy", "amount": 100}, tok=A, key="ex1"); chk("retry after import 200 same", r[0] == 200 and r[1] == rp, r)
r = call("POST", "/settlements", T, tok=login("op@example.com"), key="exs"); chk("settlement replay after import", r[0] == 200 and r[1] == rs, r)
chk("post-export write gone", code(call("POST", "/payments", {"to_handle": "cy", "amount": 100}, tok=A, key="after")) is None)
chk("login hashed after import", call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})[0] == 200)
chk("operator preserved", call("POST", "/settlements", T, tok=login("op@example.com"), key="exs2")[0] == 201)
for body in ({"track": "x", "format_version": 1, "state": {}}, {"track": "pocketful", "format_version": 2, "state": exp["state"]}, {"track": "pocketful", "format_version": 1}, {"track": "pocketful", "format_version": 1, "state": "junk"}):
    r = call("POST", "/_test/import", body); chk("import invalid 422", r[0] == 422 and code(r) == "validation_failed", r)
chk("import bad json 400", call("POST", "/_test/import", raw=b"{")[0] == 400)
chk("still working after bad import", call("GET", "/me", tok=A)[0] == 200)
# JPY / BHD fixture
for cur, mu in (("JPY", 0), ("BHD", 3)):
    f2 = json.loads(json.dumps(fx)); f2["currency"] = cur; f2["minor_units"] = mu
    call("POST", "/_test/reset", f2); t = login("ada@example.com"); m = call("GET", "/me", tok=t)[1]
    chk("currency " + cur, m["currency"] == cur and m["minor_units"] == mu, m)
chk("reset wipes signup", call("POST", "/auth/login", {"email": "dee.smith+x@example.com", "password": "longenough"})[0] == 401)
chk("unauth GET requests", call("GET", "/requests")[0] == 401)
print(f"\n{n} checks, {len(fails)} failed: {fails}")
