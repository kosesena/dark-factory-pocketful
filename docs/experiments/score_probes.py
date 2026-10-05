#!/usr/bin/env python3
"""Score each arm's probe suite against the 37 faults seeded in practice run 3 (ba26a06).

For every fault: apply it to a fresh copy (seed_faults.prepare), serve it, run the suite with
BASE_URL; a non-zero exit is a catch. F00 (no change) must pass, or the suite is unusable.
Usage: score_probes.py <suite.py> [<suite.py> ...]   -> one JSON line per suite
"""
import json, os, sys
P3 = "/Users/kosesena/Desktop/dark-factory/band-work/practice-3"
sys.path.insert(0, f"{P3}/audit/faults"); import seed_faults as sf  # noqa: E402

def score(suite):
    res = {}
    for fid, gap, req, path, old, new in sf.FAULTS:
        d = sf.prepare(fid, path, old, new)
        proc, port = sf.serve(os.path.join(d, "stage-1"))
        try:
            rc, out, secs = sf.run(f"python3 {suite}", env={"BASE_URL": f"http://127.0.0.1:{port}"}, timeout=400)
        except Exception as e:  # noqa: BLE001  timeout counts as caught (the suite noticed a hang)
            rc, secs = 124, 400
        finally:
            proc.kill()
        res[fid] = "caught" if rc else "missed"
        print(fid, res[fid], flush=True, file=sys.stderr)
    caught = sorted(f for f, v in res.items() if f != "F00" and v == "caught")
    return {"suite": suite, "control_passes": res["F00"] == "missed", "caught": len(caught),
            "of": len(res) - 1, "caught_ids": caught}

for s in sys.argv[1:]:
    print(json.dumps(score(s)), flush=True)
