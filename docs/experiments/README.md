# Experiments behind ADR-001 and ADR-002

Scripts and results from 3 Oct 2026, run outside any room, on revisions of practice run 3.
Paths inside the scripts are the operator's machine; the working copies of the service that the
arms produced are not included.

| File | What it is |
|---|---|
| `reviewer_vs_faults.py`, `.json`, `.log` | the 37 seeded faults of practice run 3 run against the reviewer's own scripts, no model calls |
| `verifier_arms.sh`, `arms/*-summary.json`, `arms-*.log` | the same revision audited by four arms: Opus auditor, Sonnet auditor, one combined Opus seat, Codex auditor |
| `verify_codex_claims.py` | reproduces the gaps the Codex arm reported |
| `seeding_arms.sh`, `score_probes.py`, `seeding/` | each model writes probes from the specification; the probes are scored against the 37 seeded faults |
