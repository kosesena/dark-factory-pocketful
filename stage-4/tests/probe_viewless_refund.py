"""Stage 4: a snapshot without its view marker is a pre-refund page and cannot hold a refund entry.
usage: probes_viewless_refund.py http://127.0.0.1:PORT   (resets and replaces state of a disposable service)"""
import copy, json, sys, urllib.request, urllib.error, uuid

B = sys.argv[1].rstrip("/")


def call(m, p, body=None, tok=None):
    h = {"Content-Type": "application/json", "Idempotency-Key": uuid.uuid4().hex}
    if tok:
        h["Authorization"] = "Bearer " + tok
    r = urllib.request.Request(B + p, data=None if body is None else json.dumps(body).encode(), method=m, headers=h)
    try:
        x = urllib.request.urlopen(r)
        d = x.read()
        return x.status, json.loads(d) if d else None
    except urllib.error.HTTPError as e:
        d = e.read()
        return e.code, json.loads(d) if d else None


fails = 0


def check(name, ok):
    global fails
    fails += 0 if ok else 1
    print("PASS" if ok else "FAIL", name)


users = [{"id": "u_" + h, "email": h + "@x.io", "password": "correct horse", "display_name": h, "handle": h, "balance": 10000}
         for h in ("ada", "bob")]
check("reset", call("POST", "/_test/reset", {"currency": "EUR", "minor_units": 2, "users": users})[0] == 204)
tok = {h: call("POST", "/auth/login", {"email": h + "@x.io", "password": "correct horse"})[1]["token"] for h in ("ada", "bob")}
pid = call("POST", "/payments", {"to_handle": "bob", "amount": 500}, tok["ada"])[1]["payment_id"]
check("refund", call("POST", "/payments/%s/refunds" % pid, {"amount": 50}, tok["bob"])[0] == 201)
snap_tok = call("GET", "/statement", None, tok["ada"])[1]["snapshot"]
exp = call("GET", "/_test/export")[1]
check("round trip", call("POST", "/_test/import", exp)[0] == 204)
m = copy.deepcopy(exp)
for sn in m["state"]["snapshots"]:
    if sn["token"] == snap_tok:
        sn.pop("view")
check("view removed from a refund-holding snapshot is 422", call("POST", "/_test/import", m)[0] == 422)
m = copy.deepcopy(exp)
for sn in m["state"]["snapshots"]:
    if sn["token"] == snap_tok:
        sn.pop("view"); sn.pop("taken_ts"); sn.pop("taken_seq")
check("view and metadata removed is 422", call("POST", "/_test/import", m)[0] == 422)
page = call("GET", "/statement?snapshot=%s&limit=200" % snap_tok, None, tok["ada"])[1]
check("destination unchanged: refund_of still on the page", json.dumps(page).count('"refund_of": "') >= 1)
print(("%d failed" % fails) if fails else "all passed")
sys.exit(1 if fails else 0)
