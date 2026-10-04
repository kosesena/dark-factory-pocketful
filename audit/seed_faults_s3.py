"""spec-auditor fault seeding for stage 3 (and reusable for stage 4 with SEED_STAGE=4).

Each fault: copy stage-N/ from `git archive <REV>` into audit/mutants/sN/<id>/ (git-ignored, never committed),
apply one replacement, start it, and run the band's API evidence against it. A previous-stage service from the
same archive serves the upgrade checks. Copies of other seats' scripts run from audit/mutants/_ev so that
nothing is written into their folders.
A seat catches a fault when its evidence fails a check it passes on the unmodified copy (H00).
Usage: SEED_REV=65dd709 SEED_STAGE=3 python3 audit/seed_faults_s3.py [fault-id ...]
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REV = os.environ.get("SEED_REV", "65dd709")
STAGE = int(os.environ.get("SEED_STAGE", "3"))
SRCROOT = os.path.join(ROOT, "audit", "mutants", "_src-" + REV)
MUT = os.path.join(ROOT, "audit", "mutants", f"s{STAGE}")
EV = os.path.join(ROOT, "audit", "mutants", f"_ev{STAGE}")
HARNESS = "/Users/kosesena/Desktop/dark-factory/dark-factory-wearedevs"
VPY = os.path.join(HARNESS, ".venv", "bin", "python")
CHECKS = "/Users/kosesena/Desktop/dark-factory/band-work/checks"
PREV_PORT = 18090 + STAGE * 100

S3_FAULTS = [
    ("H00", "baseline: unmodified copy (must be caught by nothing)", "ledger.py", "def whole(ts):", "def whole(ts):"),
    ("H01", "S3-8 as_of is inclusive", "ledger.py", "if as_of is None or eff <= as_of:", "if as_of is None or eff < as_of:"),
    ("H02", "S3-34 known_at selects by recorded time", "ledger.py",
     'if r["recorded_ts"] <= known:', 'if r["effective_ts"] <= known:'),
    ("H03", "S3-13 ties ordered by payment id ascending", "history.py",
     "key=lambda e: (e[0], e[1]))", "key=lambda e: (e[0], [-ord(c) for c in e[1]]))"),
    ("H04", "S3-12 statement window is half-open (to exclusive)", "history.py",
     "if hi is not None and t >= hi:", "if hi is not None and t > hi:"),
    ("H05", "S3-42 snapshots page their frozen entries", "history.py",
     '        return 200, _page(s, snap, limit, offset)\n    frm',
     '        return 200, _page(s, dict(snap, entries=build_statement(s, snap["user_id"], None, None, None, time.time(), s.seq)[1]), limit, offset)\n    frm'),
    ("H06", "S3-16 paging never changes the opening balance", "history.py",
     'body = {"opening_balance": snap["opening_balance"],',
     'body = {"opening_balance": (chunk[0][3] - chunk[0][2]) if chunk else snap["opening_balance"],'),
    ("H07", "S3-26/27 a decrease debits the receiver (affordability of the receiver)", "history.py",
     "debtor = sender if diff > 0 else receiver", "debtor = sender"),
    ("H08", "S3-28 historical_overdraft guards past boundaries", "history.py",
     "if not history_ok(s, (sender[\"id\"], receiver[\"id\"]), {pid: rev}, now):", "if False:"),
    ("H09", "S3-23 recorded times strictly increase per payment", "history.py",
     'rec_ts = max(now, cur["recorded_ts"] + 1e-6)', 'rec_ts = float(int(now))'),
    ("H10", "S3-24/33 a stale expected revision is 409", "history.py",
     'if expected != cur["revision"]:', 'if expected > cur["revision"]:'),
    ("H11", "S3-49 settlement members are immutable to single corrections", "history.py",
     'if p["settlement_id"] is not None or p.get("authorization_id") is not None:', 'if p.get("authorization_id") is not None:'),
    ("H12", "S3-32 revisions are hidden from third parties even for public payments", "history.py",
     'if p is None or user["id"] not in (p["from_user_id"], p["to_user_id"]):',
     'if p is None or (p["visibility"] != "public" and user["id"] not in (p["from_user_id"], p["to_user_id"])):'),
    ("H13", "S3-43 known_at may not accompany a snapshot", "history.py",
     'if any(k in q for k in ("from", "to", "known_at")):', 'if any(k in q for k in ("from", "to")):'),
    ("H14", "S3-52 a nonfinal capture reduces the hold at capture time", "ledger.py",
     'done = early + sum(c["amount"] for c in caps if whole(c["ts"]) <= m)', 'done = early + sum(c["amount"] for c in caps)'),
    ("H15", "S3-21 a correction's effective time is not later than now", "history.py",
     "if eff_ts > now:", "if eff_ts > now + 86400:"),
    ("H16", "S3-3 a seeded created_at in the future is a reset error", "accounts.py",
     'if rec["ts"] > time.time():', 'if rec["ts"] > time.time() + 86400:'),
    ("H17", "S3-42 a frozen snapshot with a future known_at selects revisions known when it was taken", "snapshot.py",
     'k = min(known, sn["taken_ts"]) if "taken_ts" in sn else known', 'k = known'),
    ("H18", "S3-42/44 an imported snapshot must have been taken in the ledger's past", "snapshot.py",
     '_need(sn["taken_seq"] <= st["seq"] and sn["taken_ts"] <= time.time() + 86400)', '_need(True)'),
]

S4_FAULTS = [
    ("J00", "baseline: unmodified copy (must be caught by nothing)", "refunds.py", "def refunded_total(s, pid):", "def refunded_total(s, pid):"),
    ("J01", "S4-2 only the original receiver may refund", "refunds.py",
     'if p["to_user_id"] != user["id"]:', 'if user["id"] not in (p["to_user_id"], p["from_user_id"]):'),
    ("J02", "S4-3 refunds of refunds give invalid_refund_target", "refunds.py",
     'if p.get("refund_of") is not None:\n            raise ApiError(422, "invalid_refund_target"',
     'if False:\n            raise ApiError(422, "invalid_refund_target"'),
    ("J03", "S4-5 refunds are capped cumulatively", "refunds.py",
     'if refunded_total(s, pid) + v > p["revisions"][-1]["amount"]:', 'if v > p["revisions"][-1]["amount"]:'),
    ("J04", "S4-5 the cap is the current corrected amount", "refunds.py",
     '+ v > p["revisions"][-1]["amount"]:', '+ v > p["revisions"][0]["amount"]:'),
    ("J05", "S4-8 a refund is funded from available money, not held", "refunds.py",
     '        return pay_view(s, move_money(s, user, s.users[p["from_user_id"]], v, p["note"], p["visibility"],\n'
     '                                      refund_of=pid))',
     '        if user["balance"] < v:\n            raise ApiError(409, "insufficient_funds", "insufficient funds")\n'
     '        return pay_view(s, move_money(s, user, s.users[p["from_user_id"]], v, p["note"], p["visibility"],\n'
     '                                      refund_of=pid, check_funds=False))'),
    ("J06", "S4-15 a single correction cannot go below the refunded total", "history.py",
     'if amount < refunded_total(s, pid):', 'if amount < 0:'),
    ("J07", "S4-14 a refund payment cannot be corrected (single)", "history.py",
     'or p.get("refund_of") is not None):', '):'),
    ("J08", "S4-21 batches cannot correct refunds", "batches.py",
     'if p.get("authorization_id") is not None or p.get("refund_of") is not None:', 'if p.get("authorization_id") is not None:'),
    ("J09", "S4-22 correcting a settlement member needs every member", "batches.py",
     'if set(s.settlements[sid]["payment_ids"]) != {m[0] for m in members}:', 'if False:'),
    ("J10", "S4-23 settlement members share one effective instant", "batches.py",
     'if len({m[1] for m in members}) != 1:', 'if False:'),
    ("J11", "S4-16/25 batch debits are checked against available funds", "batches.py",
     'if d < 0 and available_of(s, s.users[uid]) + d < 0:', 'if d < 0 and s.users[uid]["balance"] + d < 0:'),
    ("J12", "S4-27 batch recorded_at strictly later than every member's previous", "batches.py",
     'rec_ts = max(now, last + 1e-6)', 'rec_ts = now'),
    ("J13", "S4-24 batches are checked for historical total/available", "batches.py",
     'if not history_ok(s, sorted(parties), override, now):', 'if False:'),
    ("J14", "S4-27 each batch revision exposes correction_batch_id", "batches.py",
     '"reason": reason, "correction_batch_id": bid}', '"reason": reason, "correction_batch_id": None}'),
    ("J15", "S4-37 pre-stage-4 snapshots page in their original form", "history.py",
     '    if legacy:  # a snapshot taken before stage 4', '    if False:  # a snapshot taken before stage 4'),
    ("L01", "§10/S4-37 a view-less (pre-stage-4) snapshot cannot hold a refund entry", "snapshot.py",
     '_need("view" in sn or all(', '_need(True or all('),
    ("N01", "S4-36 legacy screen: opening is the balance before from", "snapshot.py",
     'and base + tot.prefix(lo_i) == sn["opening_balance"]', 'and base + tot.prefix(hi_i) == sn["opening_balance"]'),
    ("N02", "S4-36/§10 legacy candidates are only real moments (prefix test)", "snapshot.py",
     'if i == 0 or seqs[i - 1] == best:', 'if True:'),
    ("N03", "S4-36 a legacy known_at snapshot selects revisions recorded by min(known_at, moment)", "snapshot.py",
     'kk = tm if known is None else min(known, tm)', 'kk = tm'),
    ("Q01", "run contract: the legacy search screens moments by window content (hash)", "snapshot.py",
     'if (window_hash == want_hash and cnt.prefix', 'if (cnt.prefix'),
    ("Q02", "S4-36 the content hash uses (payment, revision)", "snapshot.py",
     'want_hash = sum(hash((e[0], e[1]))', 'want_hash = sum(hash((e[0], 1))'),
    ("Q03", "run contract: the legacy search is bounded (content screen and content dedup)", "snapshot.py",
     '        if (window_hash == want_hash and cnt.prefix(hi_i) - cnt.prefix(lo_i) == len(entries)\n                and base + tot.prefix(lo_i) == sn["opening_balance"]\n                and base + tot.prefix(hi_i) == sn["closing_balance"]):\n            passing.append((tm, cut, window_hash))  # every passing moment has the stored content: one rebuild decides',
     '        if (cnt.prefix(hi_i) - cnt.prefix(lo_i) == len(entries)\n                and base + tot.prefix(lo_i) == sn["opening_balance"]\n                and base + tot.prefix(hi_i) == sn["closing_balance"]):\n            passing.append((tm, cut, (pi, ri)))  # every passing moment has the stored content: one rebuild decides'),
    ("M01", "S4-36/§10 legacy candidates are only real moments of the ledger", "snapshot.py",
     "        if all(ts <= tm for seq, ts in by_seq if seq <= best) and all(ts > tm for seq, ts in by_seq if seq > best):",
     "        if True:"),
    ("M02", "§10 a legacy snapshot's balances must equal the rebuild", "snapshot.py",
     'if ob == sn["opening_balance"] and cb == sn["closing_balance"] and rebuilt == entries:', 'if rebuilt == entries:'),
    ("M03", "§10 a legacy snapshot's entries must equal the rebuild", "snapshot.py",
     'and rebuilt == entries:', 'and len(rebuilt) == len(entries):'),
    ("M04", "S4-36 a legacy snapshot taken before later facts still imports (search is complete)", "snapshot.py",
     'for taken_ts, taken_seq in past[0]:', 'for taken_ts, taken_seq in past[0][:1]:'),
    ("M05", "§10 a legacy snapshot's entries must equal the rebuild (0f56cc2 search)", "snapshot.py",
     'if ob == sn["opening_balance"] and cb == sn["closing_balance"] and rebuilt == entries:\n            return tm, cut',
     'if ob == sn["opening_balance"] and cb == sn["closing_balance"]:\n            return tm, cut'),
    ("M06", "S4-36 the legacy search is complete (tries earlier moments, latest first)", "snapshot.py",
     'for tm, cut, sig in reversed(passing):', 'for tm, cut, sig in reversed(passing[-1:]):'),
]

K_FAULTS = [
    ("K01", "§10/S3-42 imported snapshots are always rebuilt (never skipped for legacy shape)", "snapshot.py",
     'if True:  # frozen facts', 'if sn["taken_seq"] != st["seq"]:  # frozen facts'),
    ("K02", "§10/S3-42 imported snapshot balances must equal the rebuild", "snapshot.py",
     '_need(ob == sn["opening_balance"] and cb == sn["closing_balance"] and rebuilt == entries)', '_need(rebuilt == entries)'),
    ("K03", "§10/S3-42 imported snapshot entries must equal the rebuild", "snapshot.py",
     'and rebuilt == entries)', 'and len(rebuilt) == len(entries))'),
    ("K04", "§10/S3-42 a legacy snapshot's time is derived from the whole ledger, not its own entries", "snapshot.py",
     'latest = max([ledger_latest[0]] + [parse_instant(e[5]) for e in entries])', 'latest = max([0.0] + [parse_instant(e[5]) for e in entries])'),
]

FAULTS = (S4_FAULTS if STAGE == 4 else S3_FAULTS) + K_FAULTS


def wait(port):
    for _ in range(200):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("no health on %d" % port)


def run(cmd, cwd, timeout=1200, env=None):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        return 99, "timeout"


def fails(out):
    names = set()
    for line in out.splitlines():
        m = re.match(r"^\s*(FAIL|FAILED|ERROR:?)\s+(.*)$", line)
        if m:
            names.add(re.split(r" -- | \(|: |\[", m.group(2))[0].strip()[:90])
    return names


def evidence(d, url, prev, tag):
    res = {}
    rc, out = run([sys.executable, "-m", "unittest", "tests.test_service"], d)
    res["impl"] = fails(out) | ({"exit"} if rc else set())
    v = os.path.join(ROOT, "verification")
    for f in (f"probes_s{STAGE}.py",):
        if os.path.exists(os.path.join(v, f)):
            rc, out = run([VPY, os.path.join(v, f), url], ROOT)
            res["reviewer:" + f] = fails(out) | ({"exit"} if rc and not fails(out) else set())
    if os.path.exists(os.path.join(v, f"model_check_s{STAGE}.py")):
        rc, out = run([VPY, os.path.join(v, f"model_check_s{STAGE}.py"), url, "--seeds", "4", "--steps", "40"], ROOT)
        res["reviewer:model"] = {"exit"} if rc else set()
    for f in sorted(glob.glob(os.path.join(EV, f"journey_stage{STAGE}_*.py"))):
        rc, out = run([VPY, f, url], EV)
        res["customer:" + os.path.basename(f)] = fails(out) | ({"exit"} if rc and not fails(out) else set())
    env = dict(os.environ, AUDIT_BASE=url, AUDIT_DEST=url, AUDIT_REV=tag)
    for f in sorted(glob.glob(os.path.join(EV, f"probe_stage{STAGE}*.py"))):
        before = set(glob.glob(os.path.join(EV, "evidence-*.json")))
        rc, out = run([VPY, f], EV, env=env)
        names = set()
        for ef in set(glob.glob(os.path.join(EV, f"evidence-{tag}-*.json"))):
            try:
                names |= {x.get("name") or x.get("id") or json.dumps(x)[:80] for x in json.load(open(ef)).get("failed", [])}
            except Exception:
                pass
            os.remove(ef)
        res["cross:" + os.path.basename(f)] = names | ({"exit"} if rc and not names else set())
    mine = os.path.join(ROOT, f"audit/probes/stage{STAGE}_probes.py")
    rc, out = run([VPY, mine, url, prev], ROOT)
    res["auditor"] = fails(out)
    for mode in sorted({STAGE, 3}):
        rc, out = run([VPY, os.path.join(ROOT, "audit/probes/legacy_snapshot_probes.py"), url, str(mode)], ROOT)
        res["auditor"] = sorted(set(res["auditor"]) | {f"legacy{mode}:" + x for x in fails(out)})
    rc, out = run(["/bin/sh", "-c", f". .venv/bin/activate && python -m harness run --track pocketful --base-url {url} "
                   f"--previous-base-url {prev} --stages {STAGE} --out {CHECKS}/spec-auditor-seed{STAGE}-{tag}-{int(time.time())}"], HARNESS)
    res["shipped"] = set() if f"stage {STAGE}: pass" in out else {f"stage {STAGE} not pass"}
    return {k: sorted(v) for k, v in res.items()}


def one(args):
    i, (fid, req, fname, old, new) = args
    port = 18000 + STAGE * 100 + i
    d = os.path.join(MUT, fid)
    shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(os.path.join(SRCROOT, f"stage-{STAGE}"), d, ignore=shutil.ignore_patterns("__pycache__"))
    path = os.path.join(d, fname)
    text = open(path).read()
    assert text.count(old) == 1, (fid, "anchor not unique/absent")
    open(path, "w").write(text.replace(old, new))
    proc = subprocess.Popen([sys.executable, "server.py"], cwd=d, env=dict(os.environ, PORT=str(port)),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait(port)
        ev = evidence(d, f"http://127.0.0.1:{port}", f"http://127.0.0.1:{PREV_PORT}", f"{REV}-{fid}")
    finally:
        proc.kill()
    return {"id": fid, "requirement": req, "file": fname, "old": old, "new": new, "fails": ev}


def main():
    only = sys.argv[1:]
    if not os.path.isdir(SRCROOT):
        os.makedirs(SRCROOT)
        subprocess.run(f"/Library/Developer/CommandLineTools/usr/bin/git -C {ROOT} archive {REV} | tar -x -C {SRCROOT}", shell=True, check=True)
    shutil.rmtree(EV, ignore_errors=True)
    os.makedirs(EV)
    for f in glob.glob(os.path.join(ROOT, "customer", "journey_stage*.py")):
        shutil.copy(f, EV)
    for f in glob.glob(os.path.join(ROOT, "cross-audit", "probe_stage*.py")):
        shutil.copy(f, EV)
    prev = subprocess.Popen([sys.executable, "server.py"], cwd=os.path.join(SRCROOT, f"stage-{STAGE - 1}"),
                            env=dict(os.environ, PORT=str(PREV_PORT)), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait(PREV_PORT)
    out_path = os.path.join(ROOT, "audit", f"seed-results-stage-{STAGE}-{REV}.json")
    results = {r["id"]: r for r in (json.load(open(out_path)) if os.path.exists(out_path) else [])}
    todo = [f for f in FAULTS if not only or f[0] in only]
    try:
        with ThreadPoolExecutor(int(os.environ.get("SEED_PAR", "3"))) as ex:
            for row in ex.map(one, enumerate(todo)):
                results[row["id"]] = row
                json.dump(sorted(results.values(), key=lambda r: r["id"]), open(out_path, "w"), indent=1)
                print(json.dumps({"id": row["id"], "done": True}), flush=True)
    finally:
        prev.kill()
    base = results.get(FAULTS[0][0])
    for r in sorted(results.values(), key=lambda r: r["id"]):
        bf = base["fails"] if base else {}
        new = {k: sorted(set(v) - set(bf.get(k, []))) for k, v in r["fails"].items() if set(v) - set(bf.get(k, []))}
        r["caught_by"] = sorted({k.split(":")[0] for k in new})
        r["new_fails"] = new
        print(r["id"], r["requirement"][:60], "->", r["caught_by"], flush=True)
    json.dump(sorted(results.values(), key=lambda r: r["id"]), open(out_path, "w"), indent=1)


if __name__ == "__main__":
    main()
