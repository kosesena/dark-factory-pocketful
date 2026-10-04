"""spec-auditor fault seeding for stage 1.

For each fault: copy stage-1/ into audit/mutants/<id>/ (git-ignored, never committed), apply one
string replacement, start the copy as a local process, and run every piece of band evidence:
  impl     implementer's tests (stage-1/tests, run against the mutant copy)
  shipped  shipped checks via `harness run --base-url`
  customer customer/journey_stage1.py
  reviewer verification/model_check.py (if present)
  auditor  audit/probes/stage1_probes.py
Usage: python3 audit/seed_faults.py [fault-id ...]
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REV = os.environ.get("SEED_REV", "69289b3")
SRC = os.path.join(ROOT, "audit", "mutants", "_src-" + REV, "stage-1")  # git archive of REV
MUT = os.path.join(ROOT, "audit", "mutants")
HARNESS = "/Users/kosesena/Desktop/dark-factory/dark-factory-wearedevs"
VENV_PY = os.path.join(HARNESS, ".venv", "bin", "python")
CHECKS = "/Users/kosesena/Desktop/dark-factory/band-work/checks"

# id, requirement, file, old, new
FAULTS = [
    ("F00", "baseline: unmodified copy (must be caught by nothing)", "common.py",
     "LOCK = threading.RLock()", "LOCK = threading.RLock()"),
    ("F01", "R55 key scoped by path", "common.py",
     'ik = (user["id"], key, req.path)', 'ik = (user["id"], key, req.path.split("/")[1])'),
    ("F02", "R56 replay returns 200", "common.py",
     "            return 200, rec[1]", "            return 201, rec[1]"),
    ("F03", "R59 body equality ignores key order", "common.py",
     "json.dumps(_norm(body), sort_keys=True,", "json.dumps(_norm(body), sort_keys=False,"),
    ("F04", "R3/R74 paid request cannot be paid again", "wallet.py",
     'if r["status"] != "pending":\n            raise ApiError(409',
     'if r["status"] in ("declined", "cancelled"):\n            raise ApiError(409'),
    ("F05", "R118/R119 settlement net affordability, all-or-nothing", "settlements.py",
     "check_funds=False)", "check_funds=True)"),
    ("F06", "R121 settlement payments in input order", "settlements.py",
     '"payments": [pay_view(s, p) for p in payments]}', '"payments": [pay_view(s, p) for p in reversed(payments)]}'),
    ("F07", "R122 nonmembers expose settlement_id null", "wallet.py",
     '"request_id": p["request_id"], "settlement_id": p["settlement_id"],',
     '"request_id": p["request_id"], **({"settlement_id": p["settlement_id"]} if p["settlement_id"] else {}),'),
    ("F08", "R116 self-transfer in settlement is 422 self_payment", "settlements.py",
     "    if frm is to:", "    if False:"),
    ("F09", "R112 non-operator gets 403", "settlements.py",
     'if user["id"] not in s.operators:', 'if not s.operators:'),
    ("F10", "R101 import preserves idempotency records", "snapshot.py",
     "        s.idem[(u, k, p)] = (fp, resp)", "        pass"),
    ("F11", "R99 import preserves bearer tokens", "snapshot.py",
     "        s.tokens[t] = uid", "        pass"),
    ("F12", "R42 query integers are plain digits", "common.py",
     'DIGITS_RE = re.compile(r"[0-9]+", re.ASCII)', 'DIGITS_RE = re.compile(r"[+]?[0-9]+", re.ASCII)'),
    ("F13", "R17 booleans are not amounts", "common.py",
     "if isinstance(v, bool) or not isinstance(v, (int, float)):", "if not isinstance(v, (int, float)):"),
    ("F14", "R78 decline of a cancelled request is 409", "wallet.py",
     'elif r["status"] != status:', 'elif r["status"] == "paid":'),
    ("F15", "R40 malformed bearer scheme is 401", "common.py",
     'if len(parts) != 2 or parts[0].lower() != "bearer":', "if len(parts) != 2:"),
]

# faults in code changed by the fix revision 145b98e (exact numbers, huge digits, strict import, seeded hashing)
FAULTS += [
    ("F16", "R16/R73 fractional amounts are 422, never rounded", "common.py",
     "        if v != v.to_integral_value():\n            raise validation", "        if False:\n            raise validation"),
    ("F17", "R16 exact parse: 1.0000000000000001 is not an integer", "common.py",
     "parse_float=Decimal if decimal else float,", "parse_float=(lambda s: Decimal(float(s))) if decimal else float,"),
    ("F18", "R44/R73 huge integer amounts are 422, not 400/5xx", "common.py",
     "return int(text) if len(text) <= 18 else Decimal(text)", "return int(text)"),
    ("F19", "R42 huge offset is valid (empty page), huge limit 422", "common.py",
     "n = int(v) if len(v) <= 18 else 10 ** 18", "n = int(v) if len(v) <= 18 else 0"),
    ("F20", "R105 import rejects an invalid timestamp", "snapshot.py",
     "    _need(_str(v) and RFC3339.fullmatch(v))\n    parse_ts(v)", "    return"),
    ("F21", "R105 import rejects dangling payment->request references", "snapshot.py",
     '_need(p["request_id"] is None or p["request_id"] in s.requests_by_id)', 'pass'),
    ("F22", "R105 import rejects a negative/fractional balance", "snapshot.py",
     '_need(_id(rec["id"]) and 0 <= rec["balance"] <= 2 ** 53 and _int(rec["balance"]))', '_need(_id(rec["id"]))'),
    ("F23", "R31 seeded users log in (per-record KDF cost honoured)", "common.py",
     'user.get("n", 2 ** 12))', '2 ** 12)'),
    ("F24", "R59/A2 1000 and 1000.0 are the same body", "common.py",
     "return int(v) if v == v.to_integral_value() and abs(v) < 10 ** 30 else str(v)", "return str(v)"),
]

ALT = {"F13": ("if isinstance(v, bool) or not isinstance(v, (int, Decimal)):", "if not isinstance(v, (int, Decimal)):")}


def make(fid, fname, old, new):
    d = os.path.join(MUT, fid)
    shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(SRC, d, ignore=shutil.ignore_patterns("__pycache__"))
    path = os.path.join(d, fname)
    text = open(path).read()
    if text.count(old) != 1 and fid in ALT:  # anchor rewritten by a later revision
        old, new = ALT[fid]
    assert text.count(old) == 1, (fid, "anchor not unique/absent")
    open(path, "w").write(text.replace(old, new))
    return d


def wait(port):
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("no health")


def run(cmd, cwd, timeout=900):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)
    except subprocess.TimeoutExpired:
        return 99, "timeout"


def evidence(d, port, fid):
    url = f"http://127.0.0.1:{port}"
    res = {}
    rc, out = run([sys.executable, "-m", "unittest", "tests.test_service"], d)
    res["impl"] = rc != 0
    rc, out = run([sys.executable, os.path.join(ROOT, "audit/probes/stage1_probes.py"), url], ROOT)
    res["auditor"] = rc != 0
    res["auditor_fails"] = [l[5:60] for l in out.splitlines() if l.startswith("FAIL")]
    rc, out = run([sys.executable, os.path.join(ROOT, "customer/journey_stage1.py"), url], ROOT)
    # the customer journey fails 2 checks on the unmodified service (script bugs, see report);
    # count it as catching a fault only when it fails a check beyond that baseline
    baseline = {"key scoped per user", "op sees no others' requests"}
    cf = {l.split(" ", 1)[1].split(" (")[0].strip() for l in out.splitlines() if l.startswith("FAIL ")}
    res["customer"] = bool({c for c in cf if not any(c.startswith(b) for b in baseline)})
    res["customer_fails"] = sorted(cf)
    mc = os.path.join(ROOT, "verification/model_check.py")
    if os.path.exists(mc):
        rc, out = run([sys.executable, mc, url, "--seeds", "8"], ROOT)
        res["reviewer"] = rc != 0
    rc, out = run(["/bin/sh", "-c", f". .venv/bin/activate && python -m harness run --track pocketful "
                   f"--base-url {url} --stages 1 --out {CHECKS}/spec-auditor-seed-{fid}-{int(time.time())}"],
                  HARNESS)
    res["shipped"] = "stage 1: pass" not in out
    return res


def main():
    if not os.path.isdir(SRC):
        os.makedirs(os.path.dirname(SRC), exist_ok=True)
        subprocess.run(f"git -C {ROOT} archive {REV} stage-1 | tar -x -C {os.path.dirname(SRC)}", shell=True, check=True)
    only = sys.argv[1:]
    results = []
    port = 9400
    for fid, req, fname, old, new in FAULTS:
        if only and fid not in only:
            continue
        port += 1
        if fid in ALT and open(os.path.join(SRC, fname)).read().count(old) != 1:
            old, new = ALT[fid]
        d = make(fid, fname, old, new)
        proc = subprocess.Popen([sys.executable, "server.py"], cwd=d, env=dict(os.environ, PORT=str(port)),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            wait(port)
            res = evidence(d, port, fid)
        finally:
            proc.kill()
        caught = [k for k in ("impl", "shipped", "customer", "reviewer", "auditor") if res.get(k)]
        row = {"id": fid, "requirement": req, "file": fname, "old": old, "new": new,
               "caught_by": caught, "auditor_fails": res.get("auditor_fails"),
               "customer_fails": res.get("customer_fails")}
        print(json.dumps(row), flush=True)
        results.append(row)
    out = os.path.join(ROOT, "audit", "seed-results-stage-1.json")
    json.dump(results, open(out, "w"), indent=1)


if __name__ == "__main__":
    main()
