"""spec-auditor fault seeding for stage 2.

Each fault: copy stage-2/ from `git archive <REV>` into audit/mutants/<id>/ (git-ignored, never committed),
apply one replacement, start it, and run every piece of band evidence against it. An unmodified stage-1
service from the same archive serves the upgrade checks.
  impl      stage-2/tests/test_service.py (unittest) and stage-2/tests/ui_check.py (Playwright)
  shipped   harness run --base-url ... --previous-base-url ... --stages 2
  reviewer  verification/probes_s2.py and verification/ui_check_s2.py
  customer  customer/journey_stage2_api.py and customer/journey_stage2_ui.py (copies, so screenshots stay here)
  auditor   audit/probes/stage2_probes.py and audit/probes/stage2_ui_probes.py
A fault counts as caught by a seat when that seat's evidence fails a check it passes on the unmodified copy (G00).
Usage: SEED_REV=d78f1bd python3 audit/seed_faults_s2.py [fault-id ...]
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REV = os.environ.get("SEED_REV", "d78f1bd")
SRCROOT = os.path.join(ROOT, "audit", "mutants", "_src-" + REV)
MUT = os.path.join(ROOT, "audit", "mutants", "s2")
EV = os.path.join(ROOT, "audit", "mutants", "_ev")
HARNESS = "/Users/kosesena/Desktop/dark-factory/dark-factory-wearedevs"
VPY = os.path.join(HARNESS, ".venv", "bin", "python")
CHECKS = "/Users/kosesena/Desktop/dark-factory/band-work/checks"
S1PORT = 9499

FAULTS = [
    ("G00", "baseline: unmodified copy (must be caught by nothing)", "common.py", "def sweep(s, now):", "def sweep(s, now):"),
    ("G01", "S2-49 payments are checked against available, not total", "wallet.py",
     "if check_funds and available_of(s, frm) < amount:", 'if check_funds and frm["balance"] < amount:'),
    ("G02", "S2-49 settlement net debits cannot use held funds", "settlements.py",
     '< held_of(s, uid) for uid, d in net.items()', '< 0 for uid, d in net.items()'),
    ("G03", "S2-50 captures may spend the money reserved for them", "authorizations.py",
     "check_funds=False, authorization_id=a[\"id\"])", "check_funds=True, authorization_id=a[\"id\"])"),
    ("G04", "S2-61 expiry is reflected by reads with no request at the deadline", "server.py",
     "                    sweep(store.state, time.time())",
     "                    if req.method != 'GET': sweep(store.state, time.time())"),
    ("G05", "S2-68 a default (final) capture releases the remainder", "authorizations.py",
     'if final or a["captured_amount"] == a["amount"]:', 'if a["captured_amount"] == a["amount"]:'),
    ("G06", "S2-71 capturing the whole remainder closes it even with final:false", "authorizations.py",
     'if final or a["captured_amount"] == a["amount"]:', 'if final:'),
    ("G07", "S2-72 capture_exceeds compares with the remaining amount", "authorizations.py",
     'if amount > remaining:', 'if amount > a["amount"]:'),
    ("G08", "S2-75 remaining_amount is zero when closed", "authorizations.py",
     '"remaining_amount": a["amount"] - a["captured_amount"] if a["status"] == "open" else 0,',
     '"remaining_amount": a["amount"] - a["captured_amount"],'),
    ("G09", "S2-74 capture after expiry is authorization_expired", "authorizations.py",
     'raise ApiError(409, "authorization_expired", "authorization has expired")',
     'raise ApiError(409, "authorization_not_open", "authorization has expired")'),
    ("G10", "S2-76 only the payer may void", "authorizations.py",
     'if a["from_user_id"] != user["id"]:\n        raise ApiError(403, "forbidden", "only the payer may void")',
     'if a["from_user_id"] != user["id"] and a["to_user_id"] != user["id"]:\n        raise ApiError(403, "forbidden", "only the payer may void")'),
    ("G11", "S2-2 API clients without Accept: text/html get JSON on /requests", "ui.py",
     '"text/html" not in req.headers.get("Accept", "")', '"json" in req.headers.get("Accept", "")'),
    ("G12", "S2-37 latest refresh wins", "static/app.js",
     "if (my !== seq) return;", "/* no ordering guard */"),
    ("G13", "S2-40 a lost response is uncertain, not a refusal", "static/app.js",
     "return { status: 0, ok: false, network: true, uncertain: true };",
     "return { status: 0, ok: false, network: true, uncertain: false };"),
    ("G14", "S2-17 too many decimal places is refused, not rounded", "static/app.js",
     "if (frac.length > CFG.mu) {", "if (frac.length > CFG.mu + 1) {"),
    ("G15", "S2-83 wallet-held is absent when held is zero", "static/app.js",
     "me.held > 0 && h('div', { class: 'held' }", "me.held >= 0 && h('div', { class: 'held' }"),
    ("G16", "S2-56 expires_at is created_at + ttl", "authorizations.py",
     '"expires_at": fmt_ts(int(ts) + s.auth_ttl)', '"expires_at": fmt_ts(int(ts) + s.auth_ttl + 60)'),
]


def wait(port):
    for _ in range(150):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("no health on %d" % port)


def run(cmd, cwd, timeout=900):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout + p.stderr
    except subprocess.TimeoutExpired as e:
        return 99, (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else "timeout"


def fails(out):
    """Names of failed checks, normalised so the same check compares equal across runs."""
    names = set()
    for line in out.splitlines():
        m = re.match(r"^\s*(FAIL|FAILED|ERROR:?)\s+(.*)$", line)
        if m:
            names.add(re.split(r" -- | \(|: |\[", m.group(2))[0].strip()[:90])
    return names


def evidence(d, url, s1):
    res = {}
    rc, out = run([sys.executable, "-m", "unittest", "tests.test_service"], d)
    res["impl-api"] = (rc, fails(out) | ({"exit"} if rc else set()))
    rc, out = run([VPY, "tests/ui_check.py"], d)
    res["impl-ui"] = (rc, fails(out) | ({"exit"} if rc else set()))
    rc, out = run([VPY, os.path.join(ROOT, "verification/probes_s2.py"), url, s1], ROOT)
    res["reviewer-api"] = (rc, fails(out))
    rc, out = run([VPY, os.path.join(ROOT, "verification/ui_check_s2.py"), url], ROOT)
    res["reviewer-ui"] = (rc, fails(out) | ({"exit"} if rc and not fails(out) else set()))
    rc, out = run([VPY, os.path.join(EV, "journey_stage2_api.py"), url], EV)
    res["customer-api"] = (rc, fails(out))
    rc, out = run([VPY, os.path.join(EV, "journey_stage2_ui.py"), url], EV)
    res["customer-ui"] = (rc, fails(out) | ({"exit"} if rc and not fails(out) else set()))
    rc, out = run([VPY, os.path.join(ROOT, "audit/probes/stage2_probes.py"), url, s1], ROOT)
    res["auditor-api"] = (rc, fails(out))
    rc, out = run([VPY, os.path.join(ROOT, "audit/probes/stage2_ui_probes.py"), url, s1], ROOT)
    res["auditor-ui"] = (rc, fails(out))
    rc, out = run(["/bin/sh", "-c", f". .venv/bin/activate && python -m harness run --track pocketful --base-url {url} "
                   f"--previous-base-url {s1} --stages 2 --out {CHECKS}/spec-auditor-seed2-{int(time.time()*1000)}"], HARNESS)
    res["shipped"] = (0 if "stage 2: pass" in out else 1, set() if "stage 2: pass" in out else {"stage 2 not pass"})
    return res


def main():
    only = sys.argv[1:]
    if not os.path.isdir(SRCROOT):
        os.makedirs(SRCROOT)
        subprocess.run(f"git -C {ROOT} archive {REV} stage-1 stage-2 | tar -x -C {SRCROOT}", shell=True, check=True)
    os.makedirs(EV, exist_ok=True)
    for f in ("journey_stage2_api.py", "journey_stage2_ui.py"):
        shutil.copy(os.path.join(ROOT, "customer", f), os.path.join(EV, f))
    s1 = subprocess.Popen([sys.executable, "server.py"], cwd=os.path.join(SRCROOT, "stage-1"),
                          env=dict(os.environ, PORT=str(S1PORT)), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait(S1PORT)
    s1url = f"http://127.0.0.1:{S1PORT}"
    out_path = os.path.join(ROOT, "audit", f"seed-results-stage-2-{REV}.json")
    results = json.load(open(out_path)) if os.path.exists(out_path) and only else []
    base = next((r for r in results if r["id"] == "G00"), None)
    port = 9500
    try:
        for fid, req, fname, old, new in FAULTS:
            if only and fid not in only:
                continue
            port += 1
            d = os.path.join(MUT, fid)
            shutil.rmtree(d, ignore_errors=True)
            shutil.copytree(os.path.join(SRCROOT, "stage-2"), d, ignore=shutil.ignore_patterns("__pycache__"))
            path = os.path.join(d, fname)
            text = open(path).read()
            assert text.count(old) == 1, (fid, "anchor not unique/absent")
            open(path, "w").write(text.replace(old, new))
            proc = subprocess.Popen([sys.executable, "server.py"], cwd=d, env=dict(os.environ, PORT=str(port)),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                wait(port)
                ev = evidence(d, f"http://127.0.0.1:{port}", s1url)
            finally:
                proc.kill()
            row = {"id": fid, "requirement": req, "file": fname, "old": old, "new": new,
                   "fails": {k: sorted(v[1]) for k, v in ev.items()}}
            if fid == "G00":
                base = row
            bf = base["fails"] if base else {}
            row["caught_by"] = sorted({k.split("-")[0] for k, v in row["fails"].items()
                                       if set(v) - set(bf.get(k, []))})
            print(json.dumps({"id": fid, "requirement": req, "caught_by": row["caught_by"],
                              "new_fails": {k: sorted(set(v) - set(bf.get(k, []))) for k, v in row["fails"].items()
                                            if set(v) - set(bf.get(k, []))}}), flush=True)
            results = [r for r in results if r["id"] != fid] + [row]
            json.dump(sorted(results, key=lambda r: r["id"]), open(out_path, "w"), indent=1)
    finally:
        s1.kill()


if __name__ == "__main__":
    main()
