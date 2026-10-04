# spec-auditor verdict — stage 4, revision 000d7acadb64fdb8c37a3c48ce55d37af28b823a

**ACCEPT 000d7ac.** No open blocking gap. One limitation was accepted by the coordinator (L1 below).

## Method
- Judged from a clean `git archive 000d7ac`. Stage 3 is unchanged (397a149, closed).
- Shipped checks pass stage 4 in standard and isolated modes (`checks/spec-auditor-000d7ac-host`, `-isolated`).
  They ran alone, on a quiet machine.
- All timings below come from a 000d7ac container limited to 2 CPU / 2 GiB. The source is a real 495d5d6 stage-3
  service from `git archive 495d5d6`.
- `stage4_probes.py`: 13/13.
- `legacy_snapshot_probes.py`:
  - Stage-4 mode: 169 checks pass, 3 imported as earlier moments.
  - Refund-free mode: 165 checks pass, 6 imported as earlier moments.
  - M01 (unreal moment) and M03 (swap) get 422.
- `legacy_migration_probes.py`: every genuine case imports and pages its original result. At 4000, 6000 and 10000
  later payments it takes 0.26 s, 0.39 s and 0.58 s.
- `legacy_worstcase_probe.py`: N=10000, K=10 per user, two users (20 snapshots), each window type:

  | window | genuine | swap tamper | shift tamper |
  |---|---|---|---|
  | to | 204 in 1.03 s | 422 in 0.33 s | 422 in 0.31 s |
  | from | 204 in 0.90 s | 422 in 0.36 s | 422 in 0.30 s |
  | known_at | 204 in 0.68 s | 422 in 0.34 s | 422 in 0.30 s |
  | none | 204 in 0.72 s | 422 in 0.31 s | 422 in 0.26 s |

- `legacy_correction_scale_probe.py` (1000 payments, 20 snapshots, 5000 same-amount corrections):

  | later out-of-window payments | genuine | swap tamper | shift tamper |
  |---|---|---|---|
  | 0 | 204 in 0.59 s | 422 in 0.14 s | 422 in 0.14 s |
  | 6000 (combination) | 204 in 0.89 s | 422 in 0.34 s | 422 in 0.30 s |

- The fix is sound. Every moment that passes the screen has the same in-window (payment, revision) multiset, opening
  and closing as the snapshot. The entries are then fully determined (order, deltas, balances), so one rebuild decides.
  A hash collision would only cost an extra rebuild, never a wrong accept. Python's hash is salted per process.

## Accepted limitation (coordinator decision, recorded as unfixed)
**L1: cost grows with snapshot count times later facts.**
- Each legacy snapshot still walks every moment once.
- Genuine imports at N=10000, closed windows, two users:

  | snapshots | genuine import |
  |---|---|
  | 20 | 1.03 s |
  | 100 | 2.09 s |
  | 200 | 4.05 s |
  | 300 | **5.83 s** (over the 5 s limit) |

- 300 snapshots at N=2000 take 0.88 s. Tampered imports stay at about 0.3 s.
- Suggested fix: walk only in-window events per snapshot, or one shared sweep per user.
- Reproduction: `SRC=… DEST=… N=10000 K=150 WINDOW=to USERS=2 legacy_worstcase_probe.py`.

## Gap walk (ledger/stage-4.md)
All 39 requirements are met. S4-36 has the scale caveat L1.

## Fault seeding (`ledger/stage-4-faults.md`)
- Q02, Q03, N01, N02 and M05 are caught.
- Q01 and M06 are equivalent under the hash dedup.
- Earlier rounds stand for the unchanged code.

## Not verified
- The reviewer's ui_check_s2, receipt_tamper, import34 and model_check_legacy_migration were not run separately.
  probes_s4 and model_check_s4 run inside my fault-seeding evidence, where the control copy passed.
- The cross-auditor's own probes. Their two patterns were reproduced with my own probes instead.
- Snapshot counts above 300, and other adversarial schedules beyond those listed.
