# Tablekeeper run — final report (coordinator)

Dispatch 2026-10-05T17:16:45Z. All four stages closed by 2026-10-05T19:40Z (about 2 h 25 min). Times are UTC, taken from coordinator logs; seat-reported verdict times may differ by minutes.

## Accepted revisions (all four verifiers accepted the exact revision)
| Stage | Revision | reviewer | customer | spec-auditor | cross-auditor |
|---|---|---|---|---|---|
| 1 | 54932f86073961db5d7c0a620e19c5652ecd1c97 | 85ca1ff 18:27Z | 18:29Z | fdee06e 19:16Z | 18:34Z |
| 2 | def4be84aa435f4d9445794fdd595e3a1d7c315b | da47aae 18:47Z | 18:49Z | 7c44a4a 19:16Z | 18:48Z |
| 3 | ad025f1ae5d491c6186b3feb8ff84b7fe4fc88b8 | 9eeff23 19:08Z | 19:07Z | 63f4a7c ~19:39Z | 19:14Z |
| 4 | 01698f16b6d46ed78e893597baed3527c1825ca8 | 57550c5 19:31Z | 19:28Z | 9f5ec2a ~19:40Z | 92877a7 19:37Z |

The result repository HEAD contains stage-1..4 folders byte-identical to these revisions (git diff empty), no .git inside stage folders.

## What @reviewer ran (each accepted revision)
Clean `git archive`, `docker build --no-cache`, run at 2 CPU/2 GiB, shipped check normal and `--mode isolated`, "claimed stage: N" printed, plus own spec probes (stage 1: 126 + 69 regression, model-based random runs; stage 2: 51 API + 123 Playwright at 375/1280 and long-label walks; stage 3: 167; stage 4: 134 + planner vs own brute force on 250 random worlds). All passed on the accepted revisions.

## Gap lists and fault seeding (spec-auditor)
| Stage | Ledger / gaps | Gaps open at close | Fault seeding on accepted code |
|---|---|---|---|
| 1 | 136 reqs / 51 gaps (24c392a) | 0 | 18/18 caught (+3/3 on the b0f6075 fix, +2/2 on the 54932f8 fix) |
| 2 | 98 reqs / 29 gaps (a1521a3) | 0 | 20/20 caught |
| 3 | 83 reqs / 26 gaps (110e667) | 0 | 18/18 caught |
| 4 | 53 reqs / 20 gaps (154ce62) | 0 | 18/18 caught (one mutant, Q03, first survived and was killed by a new probe V4b) |
The shipped checks alone caught only 0-3 of each batch of seeded faults. Shared evidence: the shipped checks are thin; the independent probes carried the verification.

## Rejects and fixes
| # | Stage / revision | Seat | Reason (requirement) | Fix |
|---|---|---|---|---|
| 1 | 1 / 6f92a0c | reviewer | 8 KB unparseable nested JSON segfaults the container (§5 400, no 5xx) | 1a94009 |
| 2 | 1 / 6f92a0c | cross-auditor | 65-char IDs gave 404 not 422 (§3.4/§5); null auth fields 422 not 400 (§5); undocumented 1900-2200 year range (§4); party_size query cap (§8) | 43e5995, 34f7794 |
| 3 | 1 / 1a94009 | reviewer | zero-padded party_size treated as 10^18 (§8); LMT offsets with seconds not RFC 3339 (§3.4) | 34f7794 |
| 4 | 1 / 34f7794 | cross-auditor | huge capacity vs capped party_size (§8); 9999-12-31 availability 422 (§4) | b0f6075 |
| 5 | 1 / 5321c2d | reviewer | concurrent first logins of a seeded user: one 401 (§6/§2) — introduced by my own request to speed up reset (reset of 2000 seeded users had measured 38 s > 10 s) | 8d2b8c5, 54932f8 |
| 6 | 2 / 0a172d5 | reviewer | inherits #5 | ce54585 |
| 7 | 2 / 4f9cd3d | cross-auditor | horizontal scroll at 375 px with long labels (stage 2 "no horizontal scrolling") — caused by my no-wrap request | 4e5cb72 |
| 8 | 2 / 4e5cb72 | customer | header "Log out" breaks mid-word with a long display name (visual direction) | def4be8 |
| 9 | 4 / 62ad5a3 | cross-auditor, reviewer | `reassigned` history entry used `table_id` for single moves; spec says `table_ids` change | 01698f1 |
Stage 3 closed on its first revision with no rejects. Rounds per item: no item reached three rounds; the UI wrapping item took two (#7, #8).

## Rulings I made (disclosed, spec silent or ambiguous)
- Stage 1 §11: ownership/same-restaurant (404/422) are batch preconditions; kept (cross-auditor's R89 recorded as non-blocking; implementer later changed to per-item input order and all verifiers accepted).
- Path-segment lookup of an over-length/unknown id stays 404; body/query ids >64 chars are 422.
- Stage 4: adoption increments restaurant revision once; ranks over the whole option list; unknown table 404 before the 422 interval check; `from`/`to` need an RFC 3339 offset; `reassigned` always uses `table_ids`.
- Seeded off-grid / out-of-hours reservations are accepted at reset; overlapping seeds are rejected (agreed by spec-auditor).
- Closed table reads "Taken" in the grid (customer observation, left as is).

## Not verified / limits (stated plainly)
- Latency under the harness's exact CPU throttling beyond 50-request bursts (max observed 0.15 s).
- Formal contrast ratios were judged from screenshots by reviewer/spec-auditor; the customer measured text contrast >= 4.5:1.
- Provenance rule ("no source/docs/schemas from existing products") cannot be established from HTTP evidence; only the implementer's attestation exists.
- Commit granularity: stages 1-3 bundled several items per commit (disclosed by implementer, recorded by reviewer); stage 4 followed one item per commit.
- Three `__pycache__` files remain tracked in the repository (not in any stage folder's image contents that matter).
- I did not run the check command myself; reviewer's independent runs are the counted passes.
- Customer screenshots (desktop and phone) are committed under evidence/customer-stage-2..4/.

## Measurement
Turns are as reported by each seat (self-reported, summed from its messages; the implementer's are per message).
| Seat | Reported turns |
|---|---|
| implementer | ~19 working turns, 31 commits |
| reviewer | 11 turns (cumulative at its last verdict), 13 commits |
| spec-auditor | 9 turns (cumulative), 12 commits |
| customer | 1 turn per verdict, 12 commits |
| cross-auditor | 1 turn per verdict, 16 commits |
| coordinator | one long session |

Stage timeline (UTC): stage 1 audit 17:17 -> first build 17:30 -> closed 19:16; stage 2 dispatched 17:47 -> closed 19:16; stage 3 dispatched 18:50 (spec-auditor audit sent 18:29) -> closed ~19:39; stage 4 dispatched 19:08 -> closed ~19:40. First reject 17:38, last accept ~19:40.
