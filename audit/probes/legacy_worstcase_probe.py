"""spec-auditor worst cases for the legacy-snapshot search (stage 4).

A real older stage-3 service (snapshots without taken_ts/taken_seq) is the source; the stage-4 service is the
destination. Two same-second payments, then K saved statements per user, then N later payments outside the
statements' windows; export; then each snapshot is tampered with a same-instant swap (balances recomputed), which
passes every cheap check, or with a shift of every balance by +1.

Usage: SRC=http://old-stage3 DEST=http://stage4 N=6000 K=1 WINDOW=to USERS=1 LIMIT=5 python3 legacy_worstcase_probe.py
WINDOW: to (closed window, explicit `to`), from (explicit `from` before the pair), known_at (known_at just after the
pair), none (default window). USERS: 1 (ada) or 2 (ada and bob both keep statements).
"""
import copy
import os
import sys
import time

SRC, DEST = os.environ.get("SRC", "http://127.0.0.1:18762"), os.environ.get("DEST", "http://127.0.0.1:18761")
N, K = int(os.environ.get("N", "6000")), int(os.environ.get("K", "1"))
WINDOW, USERS = os.environ.get("WINDOW", "to"), int(os.environ.get("USERS", "1"))
LIMIT = float(os.environ.get("LIMIT", "5"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.argv = [sys.argv[0], SRC, DEST]
import legacy_migration_probes as M  # noqa: E402  (imports reset sys.argv; SRC/DEST are captured above)
import legacy_snapshot_probes as L  # noqa: E402

P = M.P
fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else " -- " + str(detail)[:300]), flush=True)
    if not cond:
        fails.append(name)


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
    before_pair = M.S3.now_precise()
    time.sleep(1.1)
    while time.time() % 1 > 0.2:
        time.sleep(0.02)
    M.pay(ada, "bob", 1)
    M.pay(ada, "bob", 2)
    time.sleep(0.05)
    cut = M.S3.now_precise()
    q = {"to": {"to": cut}, "from": {"from": before_pair}, "known_at": {"known_at": cut}, "none": {}}[WINDOW]
    toks = []
    for who, h in [(ada, "ada"), (bob, "bob")][:USERS]:
        toks += [(P.ok(M.S3.st(who, limit=1, **q), 200)["snapshot"], h) for _ in range(K)]
    time.sleep(1.2)
    for i in range(N):
        M.pay(ada if i % 2 == 0 else bob, "cy", 1)
    exp = P.ok(P.call("GET", "/_test/export"), 200)
    pages = M.pages_of(toks)
    M.at(DEST)
    tag = f"N={N} K={K} WINDOW={WINDOW} USERS={USERS}"
    r, dt = timed_import(exp)
    check(f"{tag} genuine: 204 in {dt:.2f}s", r == 204 and dt < LIMIT, (r, dt))
    if r == 204:
        check(f"{tag} genuine pages unchanged", M.pages_of(toks) == pages)
    for name, mut in (("swap same-instant", L.swap_same_instant), ("shift +1", L.shift)):
        e = copy.deepcopy(exp)
        hit = 0
        for sn in e["state"]["snapshots"]:
            if any(sn["token"] == t for t, _ in toks):
                try:
                    mut(sn)
                    hit += 1
                except ValueError:
                    pass
        r, dt = timed_import(e)
        check(f"{tag} {name} ({hit} snapshots): 422 in {dt:.2f}s", hit and r == 422 and dt < LIMIT, (hit, r, dt))
    print(f"{len(fails)} failed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
