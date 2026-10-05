#!/usr/bin/env python3
"""Independent check of the Codex auditor's defect claims (D2-D8) against two revisions of
practice run 3 stage 1: 1a0af59 (the revision under test) and ba26a06 (the revision the
all-Claude factory finally accepted). No model involved."""
import http.client, json, os, subprocess, sys, uuid
P3 = "/Users/kosesena/Desktop/dark-factory/band-work/practice-3"
sys.path.insert(0, f"{P3}/audit/faults"); import seed_faults as sf  # noqa

FIX = {"currency":"EUR","minor_units":2,"settlement_operator_ids":["u_ada"],"users":[
 {"id":"u_ada","email":"ada@example.com","password":"correct horse","display_name":"Ada","handle":"ada","balance":10000},
 {"id":"u_bob","email":"bob@example.com","password":"correct horse","display_name":"Bob","handle":"bob","balance":1000},
 {"id":"u_cy","email":"cy@example.com","password":"correct horse","display_name":"Cy","handle":"cy","balance":0}]}

def req(port, method, path, body=None, tok=None, key=None, raw=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Content-Type": "application/json; charset=utf-8"}
    if tok: h["Authorization"] = "Bearer " + tok
    if key: h["Idempotency-Key"] = key
    data = raw if raw is not None else (json.dumps(body) if body is not None else None)
    c.request(method, path, body=data, headers=h); r = c.getresponse(); b = r.read().decode(errors="replace")
    try: b = json.loads(b)
    except ValueError: pass
    return r.status, r.getheader("Content-Type"), b

def login(p, who):
    return req(p, "POST", "/auth/login", {"email": f"{who}@example.com", "password": "correct horse"})[2]["token"]

def fresh(p, fix=FIX):
    assert req(p, "POST", "/_test/reset", fix)[0] == 204
    return login(p, "ada"), login(p, "bob")

def run(port):
    out = {}
    a, b = fresh(port)
    s1 = req(port, "POST", "/payments", raw='{"to_handle":"bob","amount":1,"unused":0.10}', tok=a, key="k2")[0]
    s2 = req(port, "POST", "/payments", raw='{"to_handle":"bob","amount":1,"unused":0.1}', tok=a, key="k2")[0]
    out["D2 0.10 vs 0.1 replay (want 200)"] = f"{s1}->{s2}"
    s1 = req(port, "POST", "/payments", raw='{"to_handle":"bob","amount":1,"unused":0.5}', tok=a, key="k3")[0]
    s2 = req(port, "POST", "/payments", raw='{"to_handle":"bob","amount":1,"unused":{"$dec":"0.5"}}', tok=a, key="k3")[0]
    out["D3 0.5 vs {$dec} (want 409)"] = f"{s1}->{s2}"
    a, b = fresh(port, {**FIX, "users": [dict(FIX["users"][0], balance=1), dict(FIX["users"][1], balance=0)]})
    rid = req(port, "POST", "/requests", {"payer_handle": "bob", "amount": 1}, tok=a, key="r1")[2]["request_id"]
    exp = req(port, "GET", "/_test/export")[2]; exp["state"]["requests"][0]["amount"] = -5
    out["D4 import negative request amount (want 422)"] = req(port, "POST", "/_test/import", exp)[0]
    a, b = fresh(port)
    out["D5 limit=9*4301 (want 422)"] = req(port, "GET", "/activity?limit=" + "9"*4301, tok=a)[0]
    out["D5 offset=9*4301 (want 200)"] = req(port, "GET", "/activity?offset=" + "9"*4301, tok=a)[0]
    rid = req(port, "POST", "/requests", {"payer_handle": "bob", "amount": 1}, tok=a, key="r2")[2]["request_id"]
    st, _, body = req(port, "POST", f"/requests/{rid}/decline", raw="{", tok=b)
    out["D6 decline with body '{' (want 400)"] = f"{st} {body.get('status') if isinstance(body, dict) else ''}"
    bad = {**FIX, "payments": [{"id":"p_seed","from_user_id":[],"to_user_id":"u_bob","amount":1,"note":"","visibility":"public"}]}
    out["D7 reset with list user ref (want 400)"] = req(port, "POST", "/_test/reset", bad)[0]
    st, ct, _ = req(port, "OPTIONS", "/health")
    out["D8 OPTIONS /health (want 4xx JSON)"] = f"{st} {ct}"
    return out

for rev in ("1a0af59", "ba26a06"):
    d = f"/tmp/verify-codex-{rev}"
    subprocess.run(f"rm -rf {d} && mkdir -p {d} && git -C {P3} archive {rev} stage-1 | tar -x -C {d}", shell=True, check=True)
    proc, port = sf.serve(f"{d}/stage-1")
    try:
        print(f"== {rev}")
        for k, v in run(port).items(): print(f"  {k}: {v}")
    finally:
        proc.kill()
