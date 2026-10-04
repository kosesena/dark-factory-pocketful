# spec-auditor verdict — stage 1, revision 0e8dea4bc027a12ae5baef72654d4b609f7268ec

**ACCEPT 0e8dea4.** No open gap cites a spec sentence. G1 and G2 from 145b98e are closed.

## Method
- Judged from `git archive 0e8dea4 stage-1` (`audit/mutants/_src-0e8dea4`). Shipped checks on that build pass stage 1
  in host mode and in isolated mode (`checks/spec-auditor-0e8dea4-host`, `checks/spec-auditor-0e8dea4-iso`).
- Docker container (2 CPU, 2 GiB): **39/39 auditor probes pass**. That is every stage-1 gap, plus exact and huge numbers, huge
  limit/offset, number identity, strict import and corrupted seeded records. The reviewer's
  `verification/probes_edges.py` also passes: 52/52.
- Code read: `decimal_int` and `_num` work from `as_tuple()` with no exponent expansion; `_canon` quotes strings, so they
  cannot collide with numbers or literals; `check_receipts` cross-checks only immutable facts; reset now validates ranges
  and references the same way import does.

## Closed gaps
- G1 (§5 "no 5xx"): `amount: 1E+999999999` → 422. `"x":1e1000000` in an unknown field → 201, and its replay → 200.
- G2 (§7 same body): `1.5` and `1.50` → 200 replay. `1.5` and `"1.5"`, `1e40` and `"1E+40"`, `"true"` and `true`, `"null"` and `null` → 409.
  `1000` and `1000.0` → 200.

## Other checks
- Rich state round-trips through export/import, and a second export after import is identical. The state covered
  every write path, paid, cancelled and declined requests, zero-share splits, settlements, huge-number bodies and a
  non-ASCII signup. After import into a fresh reset, every original key replays with 200, and a different body gets 409.
  Tokens survive.
- Reset accepts a balance of exactly 2⁵³, a seeded amount of 1e9, a seeded amount of 0, float balances, and huge numbers in unknown fields.
  Each of those states exports and re-imports. Reset rejects a balance of 2⁵³+1 and dangling references with 422 (closes 145b98e's non-blocking (b)).

## Fault seeding (`ledger/stage-1-faults.md`, `audit/seed-results-stage-1-0e8dea4.json`)
30 seeded (F01–F24 rerun, F25–F30 in the changed code), **30 caught**. The control copy is caught by nothing beyond baselines.
The customer journey now fails "reset operator unknown 422" on the unmodified service.

## Suggested tests (non-blocking; the code is correct, but only the auditor's probes catch a regression)
- F20/F21: import of an export whose **seeded** payment (no idempotency receipt) has an invalid `created_at`
  ("yesterday", "2026-02-30T…") or a dangling `request_id`/`settlement_id` → 422. The receipt cross-check hides this
  for API-created payments, so current tests pass even with the timestamp/reference guards removed.
- F27: same key, `{"x":"true"}` then `{"x":true}` (also `"null"`/`null`) → 409.
- F28–F30 are caught only by the implementer's tests; nothing else in the band exercises reset-reference/2⁵³ validation or receipt cross-checks.

## Ambiguity (non-blocking)
- `settlement_operator_ids` containing an id that matches no user: the service accepts it with 204, and it grants
  nothing. The customer journey expects 422. The spec lists only a negative balance as a reset error, so I read 204 as
  acceptable. The state still round-trips through export/import.
