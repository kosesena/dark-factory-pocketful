#!/usr/bin/env python3
"""Experiment for ADR-001: would the reviewer's own evidence have caught the auditor's 37 seeded faults?

Re-applies each fault from practice run 3 (audit/faults/seed_faults.py, revision ba26a06) and runs
the reviewer's scripts against the broken copy, in two versions:
  v1 = the reviewer's scripts as committed at its first verdict (7ef9527, before it saw any
       auditor finding)  -> the "no auditor" counterfactual (option A)
  v2 = the scripts at its stage-1 re-verification (297c513, after learning G-35 from the auditor)
No model is called; this costs no tokens. Writes experiments/reviewer_vs_faults.json.
"""
import json, os, subprocess, sys
P3 = "/Users/kosesena/Desktop/dark-factory/band-work/practice-3"
sys.path.insert(0, f"{P3}/audit/faults")
import seed_faults as sf  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reviewer_vs_faults.json")
VERS = {"v1": "7ef9527", "v2": "297c513"}
TOOLS = {}
for v, rev in VERS.items():
    d = f"/tmp/p3-review-{v}"
    subprocess.run(f"rm -rf {d} && mkdir -p {d} && git -C {P3} archive {rev} review | tar -x -C {d}", shell=True, check=True)
    TOOLS[v] = sorted(f for f in os.listdir(f"{d}/review") if f.endswith(".py") and "stage2" not in f and "ui_" not in f)
    TOOLS[v] = [(f, f"{d}/review/{f}") for f in TOOLS[v]]
print({v: [t for t, _ in ts] for v, ts in TOOLS.items()}, flush=True)

def check(port, path):
    args = "--steps 3000" if path.endswith("model_check.py") else ""
    rc, out, _ = sf.run(f"python3 {path} {args}", env={"BASE_URL": f"http://127.0.0.1:{port}"}, timeout=600)
    return "caught" if rc else "missed"

results = {}
for fid, gap, req, path, old, new in sf.FAULTS:
    d = sf.prepare(fid, path, old, new)
    proc, port = sf.serve(os.path.join(d, "stage-1"))
    r = {"gap": gap}
    try:
        for v, ts in TOOLS.items():
            for name, p in ts:
                # reset between scripts: every script seeds its own fixture via /_test/reset
                r[f"{v}:{name}"] = check(port, p)
            r[v] = "caught" if any(r[f"{v}:{n}"] == "caught" for n, _ in ts) else "missed"
    finally:
        proc.kill()
    results[fid] = r
    json.dump(results, open(OUT, "w"), indent=1)
    print(fid, gap, r["v1"], r["v2"], flush=True)
