"""spec-auditor: genuine legacy-snapshot migration probes. A real older stage-3 service (e.g. 495d5d6, whose exports
carry snapshots without taken_ts/taken_seq) is the source; the stage-4 service under test is the destination.

Usage: python3 legacy_migration_probes.py SRC_URL DEST_URL [big-N ...]
Every genuine snapshot must import (204) and page exactly its original result (stage-4 S4-36/S4-37).
"""
import copy
import os
import sys
import time
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
SRC, DEST = sys.argv[1], sys.argv[2]
BIG = [int(a) for a in sys.argv[3:]] or [2500]
sys.argv = [sys.argv[0], DEST]
import stage3_probes as S3  # noqa: E402

P = S3.P
call, k, ok, fx, reset, tok, user = P.call, P.k, P.ok, P.fx, P.reset, P.tok, P.user
fails = []


def at(url):
    P.BASE = urlsplit(url)


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else " -- " + str(detail)[:400]), flush=True)
    if not cond:
        fails.append(name)


def strip_rf(page):
    page = copy.deepcopy(page)
    page.pop("snapshot", None)
    for e in page.get("entries", []):
        e["payment"].pop("refund_of", None)
    return page


def pages_of(tokens):
    return {t: strip_rf(call("GET", f"/statement?snapshot={t}&limit=200", token=tok(h))[1]) for t, h in tokens}


def migrate(name, tokens, timed=False):
    exp = ok(call("GET", "/_test/export"), 200)
    before = pages_of(tokens)
    at(DEST)
    t0 = time.time()
    r = call("POST", "/_test/import", exp)
    dt = time.time() - t0
    check(f"{name}: genuine legacy export imports (204)" + (f" in {dt:.2f}s" if timed else ""), r[0] == 204, r[:2])
    if timed:
        check(f"{name}: import within the 5 s request limit", dt < 5, dt)
    if r[0] == 204:
        after = pages_of(tokens)
        for t, _ in tokens:
            check(f"{name}: snapshot pages its original result", after[t] == before[t], (after[t], before[t]))
    at(SRC)


_conn = {}


def pay(t, to, n):
    """One persistent connection per server, so thousands of payments do not exhaust local ports."""
    import http.client
    import json as _j
    key = (P.BASE.hostname, P.BASE.port)
    for attempt in (0, 1):
        c = _conn.get(key) or http.client.HTTPConnection(*key, timeout=30)
        _conn[key] = c
        try:
            c.request("POST", "/payments", body=_j.dumps({"to_handle": to, "amount": n}),
                      headers={"Authorization": "Bearer " + t, "Idempotency-Key": k(),
                               "Content-Type": "application/json"})
            r = c.getresponse()
            body = _j.loads(r.read())
            assert r.status == 201, (r.status, body)
            return body["payment_id"]
        except (http.client.HTTPException, OSError):
            c.close()
            _conn.pop(key, None)
            if attempt:
                raise


def snap(t, **kw):
    return ok(S3.st(t, limit=1, **kw), 200)["snapshot"]


def main():
    at(SRC)
    # G1 empty first statement, then a payment
    reset(fx())
    ada = tok("ada")
    s1 = snap(ada)
    pay(ada, "bob", 100)
    migrate("G1 empty-first", [(s1, "ada")])
    # G2 statement, then a later correction and a later payment
    reset(fx())
    ada, bob = tok("ada"), tok("bob")
    p = pay(ada, "bob", 500)
    pay(bob, "ada", 70)
    s2 = snap(ada)
    s2b = snap(bob)
    ok(S3.correct(ada, p, 1, 400, S3.ago(1)), 201)
    pay(ada, "bob", 30)
    migrate("G2 later correction and payment", [(s2, "ada"), (s2b, "bob")])
    # G3 windowed and known_at snapshots in the middle of history
    reset(fx())
    ada, bob = tok("ada"), tok("bob")
    p = pay(ada, "bob", 500)
    time.sleep(1.1)
    mid = S3.now_precise()
    time.sleep(1.1)
    ok(S3.correct(ada, p, 1, 450, S3.ago(1)), 201)
    pay(ada, "bob", 10)
    s3a = snap(ada, known_at=mid)
    s3b = snap(ada, to=mid)
    s3c = snap(ada, **{"from": mid})
    pay(ada, "bob", 20)
    ok(S3.correct(ada, p, 2, 440, S3.ago(1)), 201)
    migrate("G3 known_at/from/to snapshots", [(s3a, "ada"), (s3b, "ada"), (s3c, "ada")])
    # G4 same second: payment A, statement, payment B within one second (created_at is whole-second)
    for attempt in range(3):
        reset(fx())
        ada = tok("ada")
        while time.time() % 1 > 0.3:
            time.sleep(0.05)
        pay(ada, "bob", 11)
        s4 = snap(ada)
        pay(ada, "bob", 12)
        if time.time() % 1 > 0.3:
            break
    migrate("G4 statement between two same-second payments", [(s4, "ada")])
    # G5 many later facts
    for n in BIG:
        reset(fx(users=[user("ada", 10 ** 8), user("bob", 0), user("cy", 0)]))
        ada = tok("ada")
        pay(ada, "bob", 1)
        s5 = snap(ada)
        st = ok(call("GET", "/_test/export"), 200)
        # add n later payments directly via the API in bulk (sequential keys)
        for i in range(n):
            pay(ada, "bob", 1)
        migrate(f"G5 {n} later payments", [(s5, "ada")], timed=True)
    print(f"{len(fails)} failed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
