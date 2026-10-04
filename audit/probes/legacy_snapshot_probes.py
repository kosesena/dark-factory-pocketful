"""spec-auditor: legacy-shape snapshot import probes (stage 3 and 4). Stdlib only.

Usage: python3 legacy_snapshot_probes.py http://127.0.0.1:PORT STAGE
A snapshot whose metadata (taken_ts, taken_seq and, on stage 4, view) is removed must still be checked against the
ledger. Tampered content gives 422 validation_failed and leaves the destination unchanged (stage-1 §10). An untampered
snapshot taken after the last write still imports and pages its original result.
"""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
STAGE = int(sys.argv[2]) if len(sys.argv) > 2 else 3
sys.argv = [sys.argv[0], URL]
import stage3_probes as S3  # noqa: E402

P = S3.P
call, k, ok, fx, reset, tok = P.call, P.k, P.ok, P.fx, P.reset, P.tok
fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else " -- " + str(detail)[:300]), flush=True)
    if not cond:
        fails.append(name)


def build():
    reset(fx(ops=["u_cy"]))
    ada, bob = tok("ada"), tok("bob")
    p1 = ok(call("POST", "/payments", {"to_handle": "bob", "amount": 500}, token=ada, key=k()), 201)["payment_id"]
    ok(call("POST", "/payments", {"to_handle": "ada", "amount": 120}, token=bob, key=k()), 201)
    ok(S3.correct(ada, p1, 1, 450, S3.ago(1)), 201)
    if STAGE >= 4:
        ok(call("POST", f"/payments/{p1}/refunds", {"amount": 50}, token=bob, key=k()), 201)
    ok(call("POST", "/payments", {"to_handle": "bob", "amount": 30}, token=ada, key=k()), 201)
    snaps = {"empty": ok(S3.st(ada, limit=1, to="2001-01-01T00:00:00+00:00"), 200)["snapshot"],
             "default": ok(S3.st(ada, limit=1), 200)["snapshot"],
             "known": ok(S3.st(ada, limit=1, known_at=S3.now_precise()), 200)["snapshot"],
             "bob": ok(S3.st(bob, limit=1), 200)["snapshot"]}
    exp = ok(call("GET", "/_test/export"), 200)
    return exp, snaps


def strip(sn):
    for f in ("taken_ts", "taken_seq", "view"):
        sn.pop(f, None)


def shift(sn):
    sn["opening_balance"] += 1
    sn["closing_balance"] += 1
    for e in sn["entries"]:
        if isinstance(e, list):
            e[3] += 1  # entry = [payment_id, revision, delta, balance_after, effective_at, recorded_at, amount]


def main():
    exp, snaps = build()
    ss = exp["state"]["snapshots"]
    print("snapshot record shape:", json.dumps(ss[0])[:400])
    ada = tok("ada")
    pages = {n: ok(call("GET", f"/statement?snapshot={t}&limit=50", token=tok("bob" if n == "bob" else "ada")), 200)
             for n, t in snaps.items()}
    # positive control: metadata stripped, content untouched
    e2 = copy.deepcopy(exp)
    refunds = {q["id"] for q in exp["state"]["payments"] if q.get("refund_of")}
    for sn in e2["state"]["snapshots"]:
        if not any(e[0] in refunds for e in sn["entries"]):  # a view-less snapshot cannot hold a refund (stage 4)
            strip(sn)
    r = call("POST", "/_test/import", e2)
    check("legacy shape, untampered, imports (snapshots taken after the last write)", r[0] == 204, r)
    if r[0] == 204:
        for n, t in snaps.items():
            pg = call("GET", f"/statement?snapshot={t}&limit=50", token=tok("bob" if n == "bob" else "ada"))[1]
            same = pg == pages[n] or (STAGE >= 4 and _no_refund_of(pages[n]) == pg)
            check(f"legacy {n} pages its original entries", same, (pg, pages[n]))
    # tampering after the metadata is stripped
    muts = {
        "drop last entry + closing": lambda sn: (sn["entries"].pop(), sn.__setitem__(
            "closing_balance", sn["entries"][-1][3] if sn["entries"] else sn["opening_balance"])),
        "clear entries, closing=opening": lambda sn: (sn["entries"].clear(),
                                                      sn.__setitem__("closing_balance", sn["opening_balance"])),
        "shift balances +1": shift,
        "drop first entry": lambda sn: sn["entries"].pop(0),
        "duplicate first entry": lambda sn: sn["entries"].insert(0, copy.deepcopy(sn["entries"][0])),
        "reverse entries": lambda sn: sn["entries"].reverse(),
        "move to other user": lambda sn: sn.__setitem__("user_id", "u_cy"),
        "opening and closing +1": lambda sn: (sn.__setitem__("opening_balance", sn["opening_balance"] + 1),
                                              sn.__setitem__("closing_balance", sn["closing_balance"] + 1),
                                              [e.__setitem__(3, e[3] + 1) for e in sn["entries"]]),
        "swap same-instant entries, balances recomputed": swap_same_instant,
    }
    for idx, keep in [(i, kp) for i in range(len(ss)) for kp in (False, True)]:
        for name, fn in muts.items():
            e3 = copy.deepcopy(exp)
            sn = e3["state"]["snapshots"][idx]
            if not keep:
                strip(sn)
            try:
                fn(sn)
            except Exception:  # noqa: BLE001
                continue
            if json.dumps(sn, sort_keys=True) == json.dumps({k2: v for k2, v in exp["state"]["snapshots"][idx].items()
                                                             if keep or k2 not in ("taken_ts", "taken_seq", "view")},
                                                            sort_keys=True):
                continue
            ada = tok("ada")
            before = call("GET", "/me", token=ada)[1]
            r = call("POST", "/_test/import", e3)
            ok_ = r[0] == 422 and (r[1] or {}).get("error", {}).get("code") == "validation_failed"
            check(f"snapshot {idx} {'current' if keep else 'legacy'} + {name} -> 422", ok_, (r[0], r[1]))
            if not ok_:
                reset_state(exp)
            ada = tok("ada")
            check(f"snapshot {idx} legacy + {name} leaves state", call("GET", "/me", token=ada)[1] == before)
    if STAGE >= 4:
        # a snapshot without view claims to predate stage 4: it cannot contain a refund
        e4 = copy.deepcopy(exp)
        hit = False
        for sn in e4["state"]["snapshots"]:
            if "refund" in json.dumps(sn) or len(sn["entries"]) >= 3:
                sn.pop("view", None)
                hit = True
        r = call("POST", "/_test/import", e4)
        check("del view on a snapshot that holds a refund entry -> 422", hit and r[0] == 422, (hit, r[0], r[1]))
    print(f"{len(fails)} failed")
    sys.exit(1 if fails else 0)


def swap_same_instant(sn):
    es = sn["entries"]
    for i in range(len(es) - 1):
        if es[i][4] == es[i + 1][4] and es[i][0] != es[i + 1][0]:
            es[i], es[i + 1] = es[i + 1], es[i]
            run = sn["opening_balance"]
            for e in es:
                run += e[2]
                e[3] = run
            return
    raise ValueError("no same-instant pair")


def _no_refund_of(page):
    page = copy.deepcopy(page)
    for e in page.get("entries", []):
        e["payment"].pop("refund_of", None)
    return page


def reset_state(exp):
    assert call("POST", "/_test/import", exp)[0] == 204


if __name__ == "__main__":
    main()
