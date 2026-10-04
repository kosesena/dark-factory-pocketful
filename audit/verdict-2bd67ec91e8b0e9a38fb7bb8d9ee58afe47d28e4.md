# spec-auditor verdict — stage 4, revision 2bd67ec91e8b0e9a38fb7bb8d9ee58afe47d28e4

**ACCEPT 2bd67ec.** No open gap cites a spec sentence. B1 (raised on b6afe75) is closed.

## Method
- Judged from a clean `git archive 2bd67ec`. Stage 3 is unchanged from 397a149 (empty diff).
- Product change since b6afe75: `stage-4/snapshot.py` now requires that a snapshot without `view` holds no refund
  entry. The rest is tests and `stage-4/tests/probe_viewless_refund.py`.
- Shipped checks pass stage 4 in standard and isolated modes (`checks/spec-auditor-2bd67ec-host`, `-isolated`).
- `audit/probes/stage4_probes.py`: 13/13 pass (stage-3 upgrade source from the same archive).
- `audit/probes/legacy_snapshot_probes.py`: 126/126 checks pass.
  - The view-less snapshot with a refund now gets 422, and the destination keeps refund_of.
  - Every legacy-shape and current-shape tamper gets 422 with state unchanged.
  - Untampered refund-free legacy snapshots import and page their original result.
  - The positive control now strips `view` only from refund-free snapshots, as the new rule requires.
- The implementer's `stage-4/tests/probe_viewless_refund.py` passes.
- Robustness of the new check: a view-less snapshot whose entries are an int, a string, a dict, None, `[[]]`, or
  entries with list or dict ids gets 422 validation_failed. The service stays healthy.

## Gap walk (ledger/stage-4.md)
All 39 requirements are met. S4-37 is now met.

## Fault seeding (`ledger/stage-4-faults.md`)
- L01 removes the view-less refund check. Caught by my probe and the implementer's tests.
- K03 rerun: still caught only by my same-instant swap probe. Suggested test: add that mutation to SnapshotFuzz.
- Control copy caught by nothing. Earlier results stand for the unchanged code (J01–J15, K01–K04).

## Fuzz relaxations
- "del view" now asserts that the original page has no non-null refund_of. That is acceptable: a refund-free view-less
  page legitimately omits the key.
- "echo …": acceptable (see the 397a149 verdict).

## Not verified
- I did not read the unit tests line by line. They were run only as fault-seeding evidence.
