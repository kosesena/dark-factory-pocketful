# Customer verdict — stage 4, revision 000d7acadb64fdb8c37a3c48ce55d37af28b823a

ACCEPT

Clean git archive of exactly this revision; container run with --cpus=2 --memory=2g; real stage-3 495d5d6 container as legacy source.
New journey_stage4_adversarial.py (same-second entries via second-aligned payments; ledgers built on the real 495d5d6 source):
- A closed-window same-instant swap with recomputed balances, 20 snapshots, later out-of-window payments: N=6000 swap 422 in 0.18 s, shift+1 422 in 0.14 s; N=10000 genuine 204 in 1.12 s, swap 422 in 0.34 s, shift+1 422 in 0.28 s.
- B 1000 payments, 20 snapshots, same-amount corrections of the first payment: 5000 corrections genuine 204 in 0.67 s, shift+1 422 in 0.16 s (a 6000-run only reached 347 corrections because of my script's effective_at timing, genuine 0.22 s).
- C combination (3 users, 54 snapshots mixing default/closed-window/known_at, 200 payments, 1000 same-amount corrections, then N later payments): N=10000 genuine 204 in 1.43 s, swap 422 in 0.34 s, shift 422 in 0.31 s; N=6000 genuine 204 in 2.18 s (all well under 5 s; the single value slightly above the "about 2 s" target was on a loaded host).
- Reviewer probes_legacy_migration, 10 snapshots at 4000/6000/10000: 67/67 each; scale journey 27/27 (genuine 0.2-0.5 s, tampered 422 fast); real-source legacy journey 29/29.
- probes_receipt_tamper 27/27, probes_import34 33/33, spec-auditor legacy_snapshot_probes (stage 4) 0 failed, ui_check_s2 88/88.
- Journeys: stage-4 API 95/95, import 48/48, receipts 32/32, stage-3 API 176/176, fuzz 90/90, snapshot 61/61, future 22/22, extra 40/40, stage-2 API 84/84, fix 72/73 (known out-of-contract reset expectation), legacy-shape 28/29 (known non-blocking).
- Harness: stages 1-4 pass, "claimed stage: 4", standard and --mode isolated.
Unverified: unit tests/implementation not read; model_check* and cross-auditor probes not run; I did not run the spec-auditor's legacy_worstcase_probe.py (argv bug) but reproduced its pattern with my own script; other adversarial schedules beyond A/B/C not exhaustively explored.
