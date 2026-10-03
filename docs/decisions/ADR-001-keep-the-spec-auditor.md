# ADR-001: Keep the spec-auditor, our most expensive seat

**Status:** Accepted for the submitted run; to be re-checked against its numbers
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

The shipped checks are a partial sample of the judges' full suite. A service that passes them
can still fail the hidden part. The auditor is the seat that looks at that hidden part.

## Options

**A. Drop the auditor.** Reviewer and customer verify, and the shipped checks act as the
specification. Saves about 17 USD per two stages (48 %) and the slowest step. *Rejected:* in
both practice runs the revisions this would have accepted break a stated requirement. On
practice run 3 that revision would have failed a user-visible rule while passing every shipped
check.

**B. Fold the audit into the reviewer (one Opus seat does both).** This is the strongest
alternative. There would be one fewer handoff and the specification would be read once instead
of twice, so much of the duplicated cache reading would go away. *Rejected:* the reviewer
accepted the revision the auditor rejected. A reviewer that also writes the ledger checks the
code against its own reading of the specification, so the independence the factory is built on
goes away. The context would also grow: the auditor alone read 42 M cached tokens, and adding
that to the reviewer's 14 M pushes one seat toward its context limit in the middle of a stage.

**C. Keep the auditor but run it on Sonnet.** At list prices this roughly halves its cost
(about 8.60 USD instead of 17.22). *Not chosen for the submitted run:* this is not measured. We
do not know whether a Sonnet auditor finds G-35 or reaches 36/37. Switching the model in the
final run without data would replace a measured result with a guess.

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
- **Whether Sonnet would do.** Option C is untested. It is the first experiment after the
  hackathon.
- **List price, not invoice.** The numbers are the equivalent API cost of subscription usage.

## Revisit when

The submitted run's numbers are in. If the auditor's share stays near half and its unique
catches drop to zero across four stages, option C is tested next. If it again catches what the
reviewer accepted, this decision stands.
