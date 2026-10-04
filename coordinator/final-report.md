# Coordinator final report — pocketful, stages 1–4

Written from the room messages I handled and from `git log` of this repository. Times are commit times (local, 2026-10-04) of the seat's verdict commit; my own dispatch and accept times were not logged separately, so no dispatch-to-accept durations are claimed beyond what the commit times show.

## Closed revisions (all four verifiers accepted the exact revision)

| Stage | Revision | reviewer | spec-auditor | customer | cross-auditor |
|---|---|---|---|---|---|
| 1 | 999fda2 | 9e15771 (12:10) | 4cccd40 (12:17) | d8f95ee (12:08) | 472b276 (12:10) |
| 2 | d78f1bd | ac0c9ca (12:18) | d878773 (13:14) | d83c750 (12:19) | a5bf128 (12:32) |
| 3 | 397a14947d89806e107e8a8f09268fecfcd78300 | 3ffa1f6 (14:52) | 1afecf3 (15:01) | 84d1a17 (14:48) | e67cf57 (15:04) |
| 4 | 000d7acadb64fdb8c37a3c48ce55d37af28b823a | bdca469 (15:59; re-recorded as 28d24f0) | 6d92c3a (15:57) | 9eed164 (15:52) | 95b99b8 (15:50) |

Stages 1 and 2 were closed before this part of the session; I took their accepts from the commit log (I did not re-read those verdict files). Stage 3 closed at 15:04, stage 4 at 15:59 (reviewer's final accept bdca469, restated in 28d24f0).

## What the reviewer ran (stage 3 and 4)
Clean detached worktrees; shipped harness `--stage N` standard and `--mode isolated` (stages 1..N pass, "claimed stage: N"); unit tests (stage 3: 89, stage 4: 117 in container); probes, edges, s2/s3/s4; model_check, model_check_s3, model_check_s4 (0 mismatches); reset_tolerance; snapshot_tamper 41; receipt_tamper 27; future_snapshots 24; import34 33/33; ui_check_s2 88/88; the cross- and spec-auditor probes; legacy-migration and adversarial probes on a 2 CPU / 2 GiB container.

## Rejects and the commits that fixed them (stages 3 and 4, this session)

| Reject | Reason (requirement) | Fixed by |
|---|---|---|
| cross-auditor on 7c35a2a / 8bbd03a | Removing taken_ts/taken_seq (and view) skipped snapshot rebuild; drop-last/clear/shift-+1 imported 204 (§10) | 397a149 (s3), b6afe75 (s4) |
| spec-auditor + reviewer on b6afe75 | view-less snapshot holding a refund imported 204 and lost refund_of (§10; stage-4 original form) | d9736e7 |
| reviewer on d9736e7 | commit added a file outside stage-4/ (mandate §4) | 2bd67ec (net-diff ruling by coordinator) |
| cross-auditor on 2bd67ec | real 495d5d6 export with later writes imported 422 (stage-4 migration requirement) | 6487f2a |
| spec-auditor, cross-auditor, reviewer on 6487f2a | legacy import O(N^2), over 5 s / 10 s limits | 0f56cc2 |
| spec-auditor, cross-auditor (reviewer's accept withdrawn) on 0f56cc2 | closed-window swap tamper 29.6 s at N=10000; same-amount corrections x 20 snapshots 10 s timeout, 55-58 s completion | 000d7ac |

The legacy-import performance item went through three rounds (6487f2a, 0f56cc2, 000d7ac). On the third round I changed approach: one remaining cost was accepted as a limitation instead of a fourth revision.

## Rulings I made (coordinator), for the human to review
1. Fuzz-oracle relaxations: mutations named "echo ..." ignore only the page's echoed query keys (from, to, known_at); "del view" ignores only refund_of and asserts the original page holds no non-null refund_of.
2. Net-diff ruling: the stage-4 implementer's add (d9736e7) and removal (2bd67ec) of a file under verification/ cancel out; the revision was judged on its net diff.
3. Legacy snapshots (no taken_ts/taken_seq) import iff the page equals the full rebuild at some recorded moment of the imported ledger. Admitted as "alternative valid earlier states", not equivalents: drop-last-created-fact with closing adjusted; cleared entries equal to the empty-ledger statement; a later correction reverted inside a stripped snapshot. Everything else must be 422. This is a judgement call about what the specification means; the specification does not state it.
4. Not tightened on import: payment/request amount >= 1 and email format, because reset accepts those values.

## Open limitation (not fixed, not a pass)
Legacy import cost is linear in (legacy snapshots x later facts). At 10000 later facts on 2 CPU / 2 GiB, genuine imports: 20 snapshots about 0.8-1.0 s; 100 about 2.1-2.4 s; 200 about 4.1-4.3 s; 250 about 5.4 s; 300 5.2-6.7 s (limit 5 s per request); 500 about 10.5 s. Tampered imports fail early (about 0.3 s) except for the reviewer's tampered 300-case (6.15 s). Supported bound: roughly 200 legacy statements per export at 10000 later facts. Fix direction (spec-auditor): walk only in-window events per snapshot, or one shared pass per user.

## Unverified
- §2 provenance (reported unverified by the reviewer on every revision).
- Customer: did not read the unit tests or implementation; ran no cross-/spec-auditor probe scripts; adversarial schedules beyond their three were not exhaustively explored.
- Spec-auditor: did not run reviewer scripts or cross-auditor probe files separately; snapshot counts above 300 and other adversarial schedules not explored.
- Cross-auditor: did not remeasure the 300-snapshot case; finite tests do not prove indefinite token lifetime.
- Reviewer: spec-auditor's legacy_worstcase_probe not run by them (argv bug, since fixed by the spec-auditor).
- A genuine metadata-free snapshot cannot be told from a tampered "earlier moment" page; that is a limit of the retained fields, documented in stage-4/RUN.md.
- The spec-auditor's observation that created_at is stamped to the whole second was accepted as an interpretation, not tested further.
- Stage-4 customer verdict records one refund-free legacy page that omits refund_of (accepted as the original form).
- 2 nonblocking orphan-operator advisories from the cross-auditor remain open.

## Measurement table
Turns per seat for the stage-3/4 final verdicts as reported to me: reviewer 27 (stage 3/4 first rounds), 9, 25, 22, 27+2 (last two rounds); spec-auditor 1 per verdict; customer 1 per verdict; cross-auditor 1-2 per verdict; implementer about 10-14 per fix item (3, 4, 2, 10, 12, 10 on the later items). My own turns were not counted. Reject counts per item: snapshot-bypass 1, view-less refund 1, commit scope 1, legacy migration 1, legacy import performance 3 (one accepted as limitation).
