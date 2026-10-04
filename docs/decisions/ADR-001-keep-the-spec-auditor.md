# ADR-001: Keep the spec-auditor, our most expensive seat

**Status:** Accepted; options measured on 3 October 2026; re-checked against the submitted run (4 October 2026, section below)
**Date:** 3 October 2026
**Author:** Sena Köse
**Decides:** which seats verify the work, and on which model

---

## Context

The factory has five seats. Three of them verify: the reviewer (independent clean run and a
reference model written from the specification), the customer (uses the product, never reads the
code) and the spec-auditor (requirements ledger, gap list, fault seeding). The auditor runs on
Opus.

Practice run 3 (stages 1 and 2, 2 October 2026) measured what each seat costs. Figures are
Anthropic API list prices applied to the seats' transcripts with `tools/factory_numbers.py`
and `tools/prices.json`; the seats run on a subscription, so this is the equivalent API cost.

| Seat | Model | Output tokens | Cache reads | Cost (USD, list) | Share |
|---|---|---|---|---|---|
| coordinator | Sonnet 5.5 | 26,614 | 5.1 M | 1.77 | 5 % |
| implementer | Sonnet 5.5 | 124,304 | 16.5 M | 5.71 | 16 % |
| reviewer | Opus 5.5 | 110,216 | 14.4 M | 8.65 | 24 % |
| **spec-auditor** | **Opus 5.5** | **218,846** | **42.0 M** | **17.22** | **48 %** |
| customer | Sonnet 5.5 | 45,492 | 4.4 M | 2.38 | 7 % |
| **Total** | | 525,472 | 82.6 M | **35.72** | |

The auditor costs about as much as the other four seats together. It was also the slowest step
of the run, and its runtime was the one that crashed. Here we decide whether it pays for itself.

## What the auditor caught that nothing else did

Practice run 3, stage 1:

| Evidence | Result |
|---|---|
| Shipped checks on the first revision | 147/147, stage 1 claimed |
| Reviewer and customer on the same revision | both ACCEPT |
| Auditor, same revision | REJECT: gap G-35. A note holding a lone UTF-16 surrogate moved money but returned no response, after which every user's activity feed returned 5xx. The specification says requests must never produce 5xx and a failed payment leaves no trace |
| Auditor's gap list before any code was written | 34 gaps (G-01..G-34), each citing a specification sentence, handed to the implementer as part of the build |
| Fault seeding, round 3: 37 requirements broken one at a time in throwaway copies | shipped checks caught **9/37**; the band's evidence caught **36/37** (33 by black-box probes, 3 by a static lock check); the last one is an equivalent mutant (1-second timestamp resolution) and cannot be caught |

Practice run 2 showed the same pattern: three reject rounds after 147/147, none of them visible to
the shipped checks, two of them found by the auditor after the reviewer had accepted.

What the rest of the band catches without the auditor was measured afterwards, by running the
reviewer's own scripts (model check, edge probes) against the same 37 broken copies
(`band-work/experiments/reviewer_vs_faults.py`, no model calls):

| Evidence against the 37 seeded faults | Caught |
|---|---|
| Shipped checks alone | 9 |
| Reviewer's own scripts, as they stood before any auditor finding | 29 |
| Everything except the auditor (implementer tests, customer journey, shipped checks, reviewer) | 30 |
| Plus the auditor's probes | 33 |
| Plus the auditor's static lock check | 36 |

The reviewer is stronger than the first table suggested. The auditor's own share is 7 of 37
faults (4 by probes, 3 by the lock check), plus G-35 in the live run and the gap list before
the build. That is narrower than "it catches everything", and it is still the part nobody
else looks at.

The shipped checks are a partial sample of the judges' full suite. A service that passes them
can still fail the hidden part. The auditor is the seat that looks at that hidden part.

## The options, measured

Same task for each arm: verify revision `1a0af59` against the stage-1 specification, fault
seeding off, run headless with the factory's own mandate text (`band-work/experiments/
verifier_arms.sh`). Costs at list price from each run's own usage.

| Arm | Finds G-35 | Other findings | Time | Cost |
|---|---|---|---|---|
| spec-auditor on Opus (today's seat) | yes | malformed chunked body gives 500; 5,000-digit amount gives 400, not 422 | 4 min | $1.39 |
| spec-auditor on Sonnet (option C) | yes | the over-long integer case | 2 min | $0.46 |
| reviewer and auditor as one Opus seat (option B) | **no** | malformed chunked body gives 500 | 9 min | $2.32 |
| spec-auditor on Codex (see ADR-002) | no | seven other breaks of stated requirements | 24.5 min | ChatGPT plan |

One run per arm, so these are signs, not rates.

The evidence itself was then measured: each model, given the same mandate, wrote one probe suite
from the specification for the accepted revision `ba26a06`, and each suite was run against the
same 37 seeded faults (`band-work/experiments/seeding_arms.sh`, `score_probes.py`):

| Probe suite written by | Faults caught (of 37) | Time | Cost |
|---|---|---|---|
| Opus, practice run 3, strengthened over several rounds | 33 | — | — |
| Opus, one pass | 30 | 12 min | $3.07 |
| Sonnet, one pass | 30 | 6.5 min | $1.10 |
| Codex (gpt-6-astra), one pass | 30 | 34 min | ChatGPT plan (1.66 M input, 1.49 M cached, 48 k output) |

All three one-pass suites catch 30 of 37; together they catch 32. Opus alone catches F26, the
lone-surrogate fix reverted, which is the defect that started this record; Sonnet alone catches
F24; Codex alone catches F06 (an import that merges the destination's sessions instead of
replacing them). The 37 faults were designed by the Opus auditor, which may favour Opus slightly.
The Codex arm was stopped from outside twice before a third attempt finished.

## Options

**A. Drop the auditor.** Reviewer and customer verify, and the shipped checks act as the
specification. Saves about 17 USD per two stages (48 %) and the slowest step. *Rejected:* in
both practice runs the revisions this would have accepted break a stated requirement. On
practice run 3 that revision would have failed a user-visible rule while passing every shipped
check.

**B. Fold the audit into the reviewer (one Opus seat does both).** This is the strongest
alternative. There would be one fewer handoff and the specification would be read once instead
of twice, so much of the duplicated cache reading would go away. *Rejected:* the reviewer
accepted the revision the auditor rejected, and the measured combined seat (above) missed G-35
while costing more than the separate auditor. A reviewer that also writes the ledger checks the
code against its own reading of the specification, so the independence the factory is built on
goes away. The context would also grow: the auditor alone read 42 M cached tokens, and adding
that to the reviewer's 14 M pushes one seat toward its context limit in the middle of a stage.

**C. Keep the auditor but run it on Sonnet.** At list prices this roughly halves its cost
(about 8.60 USD instead of 17.22). *Not chosen for the submitted run, and a sound choice where cost matters:*
the Sonnet arm found G-35 in half the time at a third of the cost, and its probe suite caught as
many seeded faults as Opus's (30 of 37) for $1.10 against $3.07. Opus stays for the submitted
run because its suite caught the one regression that matters most here (F26) and because a
model change the day before the final run would be unrehearsed.

**D. Keep the auditor on Opus, but bound its work. Chosen.**
- Fault seeding is capped at 12–15 of the riskiest requirements per stage. The full set runs
  once, and later rounds seed only the code that changed.
- Stages are pipelined. The implementer starts the next stage once the reviewer and customer
  accept, while the auditor finishes; a late finding is fixed in both stage folders.
- A blocking gap is reported the moment it is found, not at the end of the walk.

## Cost of this decision

- About half the model spend goes to one seat. Per caught problem: practice run 3's auditor cost
  17.22 USD for two stages. That bought one blocking defect nobody else saw, 34 gaps written
  before the build, and a fault-seeding measurement on 37 requirements.
- The auditor sets the pace at the end of each stage. Pipelining hides this for stages 1–3, but
  stage 4 still waits for it.
- It is a single point of failure for the closing verdict. In practice run 3 its runtime
  crashed and its report never reached the room. This is mitigated, not removed, by the seat
  watchdog and by the rule that the coordinator treats a committed report as a verdict.
- Its accepts are provisional until the walk closes. Under pipelining the implementer may build
  on a revision that is later rejected, and then has to fix it twice.

## Five axes

| Axis | Effect |
|---|---|
| Availability | One more runtime that can crash; the watchdog and committed-report rule cover it |
| Performance | The slowest verifier; pipelining keeps it off the critical path except for the last stage |
| Security / identity | Commits under its own Git identity, never edits the service; its throwaway copies stay out of the repository |
| Changeability | The mandate is generic; it works for any specification, not only this track |
| Cost | 48 % of spend for the evidence above; the cap on faults is the dial if spend must drop |

## What we do not know

- **One run, two stages.** The cost split and the catch rates come from a single practice run.
  The submitted run, with four stages, will replace them (`FACTORY.md` section 7).
- **Whether G-35 is in the hidden suite.** Catching it matters for the product. Whether it
  changes the score is not known.
- **Whether the tie holds.** Opus and Sonnet tie at 30 of 37 on one suite each. More runs,
  and faults designed by a different model, would show whether the tie is real.
- **One run per arm.** Each arm above ran once; a second run could differ.
- **List price, not invoice.** The numbers are the equivalent API cost of subscription usage.

## Result in the submitted run

Four stages, one dispatch, 4 October 2026 (`FACTORY.md` section 7).

| Seat | Cost (USD, list) | Share of Claude spend |
|---|---|---|
| implementer | 37.89 | 29 % |
| **spec-auditor** | **35.79** | **27 %** |
| reviewer | 32.90 | 25 % |
| coordinator | 12.89 | 10 % |
| customer | 11.82 | 9 % |

- **Its share fell from 48 % to 27 %.** The cap on seeded faults and fix-scoped reseeding held
  its cost close to the reviewer's over four stages.
- **Its fault seeding is the run's headline measurement:** 81 faults across the four stages; the
  shipped checks caught 8, the band's evidence 75, and the other 6 changed nothing observable.
  Without the auditor there would be no number to put against the shipped checks.
- **It again caught what the reviewer accepted.** The reviewer accepted stage-4 revision
  `0f56cc2`; the auditor rejected it with a tampered import that took 29.6 s against a 5 s limit,
  and the reviewer then reproduced the timeout and withdrew its accept. On `145b98e` (stage 1) it
  rejected together with the reviewer and the cross-auditor.
- **It was not the only seat to see what others missed.** On five revisions it accepted with the
  reviewer and the customer while the cross-auditor rejected (ADR-002). The auditor reads the same
  specification as the other Claude seats and shares their blind spots.

The condition for testing option C (share near half, no unique catches) was not met. The decision
stands.

## Revisit when

A run where the auditor's fault seeding finds nothing the shipped checks miss, or where its share
of spend rises back towards half without a catch the reviewer missed.
