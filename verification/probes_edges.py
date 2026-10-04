#!/usr/bin/env python3
"""Reviewer's exact-number, huge-input and import-validation probes (stage 1 rules; also valid
for later stages). Written from the specification only.

Usage: python3 probes_edges.py http://localhost:8080
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1].rstrip("/")
RESULTS = []


def call(method, path, raw=None, token=None, key=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    if key is not None:
        h["Idempotency-Key"] = key
    req = urllib.request.Request(BASE + path, data=raw, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            t = r.read()
            return r.status, json.loads(t) if t else None
    except urllib.error.HTTPError as e:
        t = e.read()
        try:
            return e.code, json.loads(t) if t else None
        except ValueError:
            return e.code, {"_raw": t[:100]}


def j(v):
    return json.dumps(v).encode()


def code(b):
    try:
        return b["error"]["code"]
    except (TypeError, KeyError):
        return None


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))


def expect(name, resp, status, ecode=None):
    st, b = resp
    check(name, st == status and (ecode is None or code(b) == ecode), "got %s %s" % (st, str(b)[:160]))


FX = {"currency": "EUR", "minor_units": 2, "users": [
    {"id": "u_a", "email": "a@x.io", "password": "password", "display_name": "A", "handle": "a", "balance": 5000},
    {"id": "u_b", "email": "b@x.io", "password": "password", "display_name": "B", "handle": "b", "balance": 0},
    {"id": "u_op", "email": "op@x.io", "password": "password", "display_name": "Op", "handle": "op", "balance": 0}],
    "payments": [], "requests": [], "settlement_operator_ids": ["u_op"]}


def reset(fx=FX):
    st, b = call("POST", "/_test/reset", j(fx))
    assert st == 204, (st, b)
    return {u["handle"]: call("POST", "/auth/login", j({"email": u["email"], "password": u["password"]}))[1]["token"]
            for u in fx["users"]}


def bal(tok):
    return call("GET", "/me", token=tok)[1]["balance"]


def main():
    T = reset()
    a, b, op = T["a"], T["b"], T["op"]
    # fractional values are never rounded into a valid amount
    cases = [("/payments", b'{"to_handle":"b","amount":1.0000000000000001}'),
             ("/payments", b'{"to_handle":"b","amount":1000000000.00000001}'),
             ("/payments", b'{"to_handle":"b","amount":0.99999999999999999999}'),
             ("/requests", b'{"payer_handle":"b","amount":1.0000000000000001}'),
             ("/splits", b'{"participant_handles":["b"],"amount":2.0000000000000001}'),
             ("/payments", b'{"to_handle":"b","amount":1e-400}'),
             ("/payments", b'{"to_handle":"b","amount":1e400}'),
             ("/payments", b'{"to_handle":"b","amount":' + b"9" * 5000 + b'}')]
    for i, (path, raw) in enumerate(cases):
        expect("fraction/huge %d %s -> 422" % (i, path), call("POST", path, raw, token=a, key="f%d" % i),
               422, "validation_failed")
    expect("settlement fractional entry -> 422", call("POST", "/settlements",
           b'{"transfers":[{"from_handle":"a","to_handle":"b","amount":1.0000000000000001}]}', token=op, key="sf"),
           422, "validation_failed")
    check("no money moved by refused fractions", bal(a) == 5000 and bal(b) == 0, (bal(a), bal(b)))
    for i, raw in enumerate((b'{"to_handle":"b","amount":1000.0}', b'{"to_handle":"b","amount":1e3}',
                             b'{"to_handle":"b","amount":1E3}', b'{"to_handle":"b","amount":100000e-2}')):
        st, x = call("POST", "/payments", raw, token=a, key="ok%d" % i)
        check("integral forms accepted %d" % i, st == 201 and x["amount"] == 1000, (st, x))
    # JSON-value body identity
    T = reset()
    a = T["a"]
    pairs = [(b'{"to_handle":"b","amount":1,"x":1.0000000000000001}', b'{"to_handle":"b","amount":1,"x":1}', 409),
             (b'{"to_handle":"b","amount":1,"x":1.5}', b'{"to_handle":"b","amount":1,"x":1.50}', 200),
             (b'{"to_handle":"b","amount":1,"x":15e-1}', b'{"to_handle":"b","amount":1,"x":1.5}', 200),
             (b'{"to_handle":"b","amount":1,"x":100}', b'{"to_handle":"b","amount":1,"x":1e2}', 200),
             (b'{"to_handle":"b","amount":1,"x":1e30}', b'{"to_handle":"b","amount":1,"x":1000000000000000000000000000000}', 200),
             (b'{"to_handle":"b","amount":1,"x":0.1}', b'{"to_handle":"b","amount":1,"x":0.10000000000000001}', 409),
             (b'{"to_handle":"b","amount":1000,"note":"n"}', b'{"note":"n","amount":1e3,"to_handle":"b"}', 200)]
    for i, (first, second, want) in enumerate(pairs):
        st1, _ = call("POST", "/payments", first, token=a, key="id%d" % i)
        st2, b2 = call("POST", "/payments", second, token=a, key="id%d" % i)
        check("body identity %d: %s vs %s -> %d" % (i, first[-30:].decode(), second[-36:].decode(), want),
              st1 == 201 and st2 == want, (st1, st2, code(b2)))
    # huge query integers
    for path in ("/activity", "/requests"):
        expect("limit 5000 digits %s -> 422" % path, call("GET", path + "?limit=" + "9" * 5000, token=a), 422, "validation_failed")
        expect("limit 0-padded 5000 digits then 5 %s -> 200" % path, call("GET", path + "?limit=" + "0" * 5000 + "5", token=a), 200)
        st, x = call("GET", path + "?offset=" + "9" * 5000, token=a)
        check("offset 5000 digits %s -> 200 empty" % path, st == 200 and x[path.strip("/") if path != "/activity" else "payments"] == []
              and x["has_more"] is False, (st, str(x)[:100]))
        expect("limit 201 still 422 %s" % path, call("GET", path + "?limit=201", token=a), 422, "validation_failed")
    # import validation, destination unchanged
    T = reset()
    a, b = T["a"], T["b"]
    call("POST", "/payments", j({"to_handle": "b", "amount": 100}), token=a, key="imp")
    st, sp = call("POST", "/splits", j({"amount": 1, "participant_handles": ["b", "a", "op"]}), token=a, key="zero")
    st, ex = call("GET", "/_test/export")
    # mutate the destination so "unchanged" is observable
    call("POST", "/payments", j({"to_handle": "b", "amount": 7}), token=a, key="dest")
    snap = (bal(a), bal(b))
    mutations = {
        "bad created_at": lambda s: s["payments"][0].__setitem__("created_at", "not-a-timestamp"),
        "amount > max": lambda s: s["payments"][0].__setitem__("amount", 1000000001),
        "negative amount": lambda s: s["payments"][0].__setitem__("amount", -1),
        "negative balance": lambda s: s["users"][0].__setitem__("balance", -5),
        "unknown user in payment": lambda s: s["payments"][0].__setitem__("from_user_id", "ghost"),
        "bad visibility": lambda s: s["payments"][0].__setitem__("visibility", "secret"),
        "bad request status": lambda s: s["requests"][0].__setitem__("status", "done"),
        "state not object": None,
    }
    for name, mut in mutations.items():
        bad = json.loads(json.dumps(ex))
        if mut is None:
            bad["state"] = "nope"
        else:
            try:
                mut(bad["state"])
            except (KeyError, IndexError, TypeError):
                check("import mutation applicable: " + name, False, "export layout differs")
                continue
        expect("import %s -> 422" % name, call("POST", "/_test/import", j(bad)), 422, "validation_failed")
    check("destination unchanged after bad imports", (bal(a), bal(b)) == snap, ((bal(a), bal(b)), snap))
    st, _ = call("POST", "/_test/import", j(ex))
    check("unchanged export (with zero-share request) imports", st == 204, st)
    check("import restored balances", (bal(a), bal(b)) == (4900, 100), (bal(a), bal(b)))
    st, x = call("POST", "/splits", j({"amount": 1, "participant_handles": ["b", "a", "op"]}), token=a, key="zero")
    check("zero-share split replay after import", st == 200 and x == sp, st)
    # large reset and login timing
    big = {"currency": "EUR", "minor_units": 2, "users": [
        {"id": "u%d" % i, "email": "u%d@x.io" % i, "password": "password%d" % i, "display_name": "U",
         "handle": "u%d" % i, "balance": 1} for i in range(1200)], "payments": [], "requests": []}
    t0 = time.time()
    st, _ = call("POST", "/_test/reset", j(big))
    dt = time.time() - t0
    check("reset 1200 users 204 within 10 s (%.2fs)" % dt, st == 204 and dt < 10, dt)
    st, x = call("POST", "/auth/login", j({"email": "u1199@x.io", "password": "password1199"}))
    check("seeded login after big reset", st == 200, st)
    st, x = call("POST", "/auth/login", j({"email": "u7@x.io", "password": "wrong"}))
    check("seeded wrong password 401", st == 401, st)
    st, ex = call("GET", "/_test/export")
    check("no plaintext passwords in export", st == 200 and "password1199" not in json.dumps(ex), "")

    fails = [r for r in RESULTS if not r[1]]
    for name, ok, det in RESULTS:
        print("%s  %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else "  -> %s" % (det,)))
    print("%d probes, %d failed" % (len(RESULTS), len(fails)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
