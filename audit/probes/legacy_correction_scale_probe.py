"""spec-auditor: legacy-snapshot import under many same-amount corrections and many saved statements.

A real older stage-3 service (no taken_ts/taken_seq in its snapshots) is the source; the stage-4 service is the
destination. Same-amount corrections leave every count and sum unchanged, so a screen on counts and sums cannot
separate the moments; only content can.

Usage: SRC=http://old-stage3 DEST=http://stage4 PAYMENTS=1000 SNAPSHOTS=20 CORRECTIONS=5000 LATER=0 \
       python3 legacy_correction_scale_probe.py
Checks: the genuine export imports (204) within the limit and every snapshot pages its original result; a tampered
copy (same-instant swap or shift +1 in each snapshot) gives 422 within the limit.
"""
import copy
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
SRC, DEST = os.environ.get("SRC", "http://127.0.0.1:18762"), os.environ.get("DEST", "http://127.0.0.1:18761")
NPAY = int(os.environ.get("PAYMENTS", "1000"))
NSNAP = int(os.environ.get("SNAPSHOTS", "20"))
NCOR = int(os.environ.get("CORRECTIONS", "5000"))
LATER = int(os.environ.get("LATER", "0"))  # later out-of-window payments after the corrections (combination case)
LIMIT = float(os.environ.get("LIMIT", "5"))
sys.argv = [sys.argv[0], SRC, DEST]
import legacy_migration_probes as M  # noqa: E402
import legacy_snapshot_probes as L  # noqa: E402

P = M.P
fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else " -- " + str(detail)[:300]), flush=True)
    if not cond:
        fails.append(name)


def correct_many(t, pid, n, eff):
    import http.client
    import json
    c = http.client.HTTPConnection(P.BASE.hostname, P.BASE.port, timeout=30)
    for rev in range(1, n + 1):
        c.request("POST", f"/payments/{pid}/corrections",
                  body=json.dumps({"expected_revision": rev, "amount": 1, "effective_at": eff, "reason": "same"}),
                  headers={"Authorization": "Bearer " + t, "Idempotency-Key": M.k(), "Content-Type": "application/json"})
        r = c.getresponse()
        r.read()
        assert r.status == 201, (rev, r.status)
    c.close()


def timed_import(exp):
    t0 = time.time()
    try:
        r = P.call("POST", "/_test/import", exp)[0]
    except Exception as x:  # noqa: BLE001
        r = repr(x)[:80]
    return r, time.time() - t0


def main():
    M.at(SRC)
    P.reset(P.fx(users=[P.user("ada", 10 ** 8), P.user("bob", 10 ** 8), P.user("cy", 0)]))
    ada, bob = P.tok("ada"), P.tok("bob")
    while time.time() % 1 > 0.2:
        time.sleep(0.02)
    first = M.pay(ada, "bob", 1)
    M.pay(ada, "bob", 1)  # same second as `first`: a swappable pair
    for _ in range(NPAY - 2):
        M.pay(ada, "bob", 1)
    eff = P.call("GET", "/activity", token=ada)[1]["payments"][-1]["created_at"]
    toks = []
    for i in range(NSNAP):
        who, h = (ada, "ada") if i % 2 == 0 else (bob, "bob")
        toks.append((M.snap(who), h))
    time.sleep(1.1)
    correct_many(ada, first, NCOR, eff)
    for i in range(LATER):
        M.pay(ada if i % 2 == 0 else bob, "cy", 1)
    exp = P.ok(P.call("GET", "/_test/export"), 200)
    before = M.pages_of(toks)
    M.at(DEST)
    tag = f"payments={NPAY} snapshots={NSNAP} corrections={NCOR} later={LATER}"
    r, dt = timed_import(exp)
    check(f"{tag}: genuine imports (204) in {dt:.2f}s", r == 204 and dt < LIMIT, (r, dt))
    if r == 204:
        after = M.pages_of(toks)
        check(f"{tag}: every snapshot pages its original result", after == before)
    for name, mut in (("swap same-instant", L.swap_same_instant), ("shift +1", L.shift)):
        e = copy.deepcopy(exp)
        hit = 0
        for sn in e["state"]["snapshots"]:
            try:
                mut(sn)
                hit += 1
            except ValueError:
                pass
        r, dt = timed_import(e)
        check(f"{tag}: tampered ({name}, {hit} snapshots) gives 422 in {dt:.2f}s", hit and r == 422 and dt < LIMIT,
              (hit, r, dt))
    print(f"{len(fails)} failed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
