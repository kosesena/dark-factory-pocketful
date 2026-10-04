import sys, copy, subprocess
B = sys.argv[1]
src = open("journey_stage4_api.py").read().split("# ---------- refunds")[0]
exec(src)
D = "/usr/local/bin/docker"
def start(img, port):
    subprocess.run([D, "rm", "-f", f"y{port}"], capture_output=True); subprocess.run([D, "run", "-d", "--name", f"y{port}", "-e", f"PORT={port}", "-p", f"{port}:{port}", img], capture_output=True); time.sleep(3)
def stop(port): subprocess.run([D, "rm", "-f", f"y{port}"], capture_output=True)
def oc(OB, m, p, body=None, tok=None, key=None):
    h = {"Content-Type": "application/json"}
    if tok: h["Authorization"] = "Bearer " + tok
    if key: h["Idempotency-Key"] = key
    r = urllib.request.Request(OB + p, data=json.dumps(body).encode() if body is not None else None, method=m, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=10) as x: t = x.read(); return x.status, json.loads(t) if t else None
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"null")
def strip(es): return [dict(e, payment={k: v for k, v in e["payment"].items() if k != "refund_of"}) for e in es]
for img, port, nm in (("cust-s1d", 8061, "stage1"), ("cust-s2c", 8062, "stage2"), ("cust-s3b", 8063, "stage3")):
    start(img, port); OB = f"http://localhost:{port}"
    f = copy.deepcopy(base); f["payments"] = [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"}]
    f["requests"] = [{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}]
    if nm == "stage1": f.pop("authorization_ttl_seconds")
    oc(OB, "POST", "/_test/reset", f)
    tk = lambda e: oc(OB, "POST", "/auth/login", {"email": e + "@example.com", "password": "correct horse"})[1]["token"]
    a, b, o = tk("ada"), tk("bob"), tk("op")
    p1 = oc(OB, "POST", "/payments", {"to_handle": "bob", "amount": 100, "note": "x"}, tok=a, key="old1")[1]
    S = oc(OB, "POST", "/settlements", T1 := {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 30}, {"from_handle": "bob", "to_handle": "cy", "amount": 10}]}, tok=o, key="olds")[1]
    snap = corr = None
    if nm == "stage3":
        corr = oc(OB, "POST", f"/payments/{p1['payment_id']}/corrections", {"expected_revision": 1, "amount": 80, "effective_at": iso(datetime.now(timezone.utc) - timedelta(seconds=1)), "reason": "old"}, tok=a, key="oldc")[1]
        sn = oc(OB, "GET", "/statement", tok=a)[1]; snap = sn
    exp = oc(OB, "GET", "/_test/export")[1]
    call("POST", "/_test/reset", base)
    r = call("POST", "/_test/import", exp); chk(f"import {nm} export into stage 4", r[0] == 204, r)
    if r[0] != 204: stop(port); continue
    chk(f"{nm}: token valid", call("GET", "/me", tok=a)[0] == 200)
    chk(f"{nm}: payment & settlement replays 200", call("POST", "/payments", {"to_handle": "bob", "amount": 100, "note": "x"}, tok=a, key="old1") == (200, p1) and call("POST", "/settlements", T1, tok=o, key="olds") == (200, S))
    chk(f"{nm}: pending request payable", call("POST", "/requests/rq_1/pay", {}, tok=a, key="oldrq")[0] == 201)
    mids = [x["payment_id"] for x in S["payments"]]
    r = call("POST", "/correction-batches", {"corrections": [item(mids[0])]}, tok=o, key="ob1"); chk(f"{nm}: imported settlement partial batch -> incomplete_settlement (membership retained)", r[0] == 422 and code(r) == "incomplete_settlement", r)
    r = call("POST", "/correction-batches", {"corrections": [item(mids[0], amount=20), item(mids[1], amount=5)]}, tok=o, key="ob2"); chk(f"{nm}: whole imported settlement batch ok", r[0] == 201, r)
    r = call("POST", f"/payments/{mids[0]}/refunds", {"amount": 1}, tok=login("bob"), key="obr"); chk(f"{nm}: refund imported settlement member", r[0] == 201, r)
    r = call("POST", f"/payments/{p1['payment_id']}/refunds", {"amount": 10}, tok=login("bob"), key="obr2"); chk(f"{nm}: refund imported payment", r[0] == 201 or code(r) == "insufficient_funds", r)
    if nm == "stage3":
        chk("stage3: correction retained, replay 200", call("POST", f"/payments/{p1['payment_id']}/corrections", {"expected_revision": 1, "amount": 80, "effective_at": corr["effective_at"], "reason": "old"}, tok=a, key="oldc") == (200, corr))
        pg = call("GET", "/statement" + q(snapshot=snap["snapshot"]), tok=a); chk("stage3: snapshot token pages same entries after import", pg[0] == 200 and strip(pg[1]["entries"]) == strip(snap["entries"]) and pg[1]["closing_balance"] == snap["closing_balance"], pg[0])
        chk("stage3: revisions retained", len(call("GET", f"/payments/{p1['payment_id']}/revisions", tok=a)[1]["revisions"]) == 2)
    chk(f"{nm}: sum conserved", sum(me(login(e))[1]["balance"] for e in ("ada", "bob", "cy", "op")) == 17000)
    stop(port)
# stage-4 self roundtrip with refunds and batches
A, Bo, C, O = reset()
P = pay(A, "bob", 1000, "p")[1]; RF = refund(Bo, P["payment_id"], 200, "rf")[1]
S = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 30}, {"from_handle": "bob", "to_handle": "cy", "amount": 10}]}, tok=O, key="s")[1]; m = [x["payment_id"] for x in S["payments"]]
Bt = batch(O, [item(m[0], amount=20), item(m[1], amount=5)], "bt")[1]
snap = st(A)[1]; tok = snap["snapshot"]
exp = call("GET", "/_test/export")[1]; call("POST", "/_test/reset", base)
chk("self import 204", call("POST", "/_test/import", exp)[0] == 204)
chk("refund replay after import", refund(Bo, P["payment_id"], 200, "rf") == (200, RF))
chk("batch replay after import", batch(O, [item(m[0], amount=20), item(m[1], amount=5)], "bt") == (200, Bt))
chk("refund cumulative retained", code(refund(Bo, P["payment_id"], 801, "rf2")) == "refund_exceeds_payment" and refund(Bo, P["payment_id"], 800, "rf3")[0] == 201)
chk("refund payment still immutable after import", code(cr(Bo, RF["payment_id"], {"expected_revision": 1, "amount": 1, "effective_at": iso(N - timedelta(minutes=1)), "reason": "r"}, "ci")) == "linked_payment_immutable")
chk("batch revision ids retained", all(x.get("correction_batch_id") == Bt["correction_batch_id"] for x in revs(A, m[0])[1]["revisions"][1:]))
chk("snapshot after self import", call("GET", "/statement" + q(snapshot=tok), tok=A)[1]["entries"] == snap["entries"])
chk("re-export equal", call("GET", "/_test/export")[1]["state"].keys() == exp["state"].keys())
# fuzz
for nm_, raw in [("not object", b"[1]"), ("bad json", b"{x"), ("items not objects", b'{"corrections":[1,"a",null]}'), ("huge amount", b'{"corrections":[{"payment_id":"p","expected_revision":1,"amount":1e999999999,"effective_at":"2026-01-01T00:00:00Z","reason":"r"}]}'), ("payment_id wrong type", b'{"corrections":[{"payment_id":5,"expected_revision":1,"amount":1,"effective_at":"2026-01-01T00:00:00Z","reason":"r"}]}'), ("deep", b'{"corrections":' + b"[" * 3000 + b"]" * 3000 + b"}")]:
    r = call("POST", "/correction-batches", raw=raw, tok=O, key="fz" + nm_); chk(f"batch fuzz {nm_}: 4xx", 400 <= r[0] < 500, r)
for nm_, raw in [("bad json", b"{x"), ("array", b"[1]"), ("huge", b'{"amount":1e999999999}'), ("str amount", b'{"amount":"5"}')]:
    r = call("POST", f"/payments/{P['payment_id']}/refunds", raw=raw, tok=Bo, key="fr" + nm_); chk(f"refund fuzz {nm_}: 4xx", 400 <= r[0] < 500, r)
print(f"\nSTAGE4 IMPORT {n} checks, {len(fails)} failed: {fails}")
