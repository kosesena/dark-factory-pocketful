# ADR-002: Add a verifier on a second model family

**Status:** Accepted; confirmed by the submitted run (4 October 2026, section below)
**Date:** 3 October 2026
**Author:** Sena Köse
**Decides:** whether all verifiers run on one model family, and if not, where the second family sits

---

## Context

Until 3 October every seat ran on Claude: Opus for the reviewer and the spec-auditor, Sonnet for
the coordinator, implementer and customer. The factory's claim is independent verification, and
three verifiers on one family may share blind spots. Practice run 3 hinted at it: the reviewer and
the customer both accepted revision `1a0af59`, which hid a defect only the auditor found.

## The experiment

Same mandate (`mandates/spec-auditor.md`), same task, same revision (`1a0af59`, practice run 3,
stage 1), fault seeding switched off, run headless outside the room. Script:
`docs/experiments/verifier_arms.sh`, claims checked by `verify_codex_claims.py`.

| | Opus spec-auditor (practice run 3) | Codex (gpt-6-astra, effort high) |
|---|---|---|
| Verdict | REJECT | REJECT |
| Lone UTF-16 surrogate in a note (G-35): money moves, no response, every feed then fails | **found** | missed |
| Other specification breaks reported | none open | 9 claimed, **7 reproduced** independently |
| Time | part of a longer run | 24.5 min |
| Tokens | — | 1.59 M input (1.50 M cached), 35 k output |

The seven reproduced breaks, each on `1a0af59` **and** on `ba26a06`, the revision reviewer,
spec-auditor and customer all finally accepted:

| | Requirement | Expected | Observed |
|---|---|---|---|
| D2 | "Same body" is the same JSON value after parsing | `0.10` and `0.1` replay with 200 | 409 |
| D3 | Same key, different body gives 409 | `0.5` vs `{"$dec":"0.5"}` gives 409 | 200 |
| D4 | Invalid imported state gives 422 without changing the destination | 422 | 204; a later payment drives a balance negative |
| D5 | Requests must not produce 5xx | 422 / 200 on a 4,301-digit `limit` / `offset` | 500 |
| D6 | A body that does not parse gives 400 | 400 on `{` to decline | 200, state changed |
| D7 | A field of the wrong type gives 400, never 5xx | 400 | 500 on a list as a seeded user id |
| D8 | Every 4xx/5xx carries the JSON error body | JSON error | 501 with an HTML page for OPTIONS |

Two more claims (a transient negative balance inside a lock, a balance above 2^53) depend on a
reading of the specification and are not counted.

A second measurement points the same way: asked to write a probe suite from the specification,
Opus, Sonnet and Codex each caught 30 of the same 37 seeded faults, but not the same 30; Codex
alone caught one, Opus alone the lone-surrogate regression (ADR-001).

Neither family covered the other: Opus found what Codex missed, Codex found seven things three
Claude verifiers accepted.

## Options

**A. Stay on one family.** Simplest, already rehearsed. *Rejected:* the experiment shows seven
accepted breaks of stated requirements that a second family finds in under half an hour.

**B. Move the reviewer to Codex.** Keeps five seats; three verifiers on three models. *Not
chosen:* the evidence is for the auditor's mandate on Codex, not the reviewer's (reference
model, random sequences), which is untested there. Swapping would also drop the Opus reviewer,
whose own scripts catch 29 of 37 seeded faults.

**C. Add a sixth seat, the cross-auditor, on Codex. Chosen.** It runs a mandate derived from the
one tested in the experiment: its own walk of the specification, blind to the other verifiers'
files until its verdict, no fault seeding (the spec-auditor keeps that), never reading shipped
check sources. A stage closes only on four accepts of the same revision.

## Cost of this decision

- One more verifier on every revision. In practice run 6 (`toy`) the cross-auditor took about
  three to five minutes per revision and was never the last to report.
- Coordination: the coordinator waits for four verdicts instead of three, and a lost verdict now
  has four places to happen. Practice run 5 stalled on exactly that (the reviewer's, not the
  cross-auditor's); every verifier now commits its verdict as a file.
- Two subscriptions and two harnesses to keep signed in and up to date.
- Codex tokens are on a ChatGPT plan; `tools/factory_numbers.py` reports them as tokens, not
  dollars, because we have no list price to apply.

## Five axes

| Axis | Effect |
|---|---|
| Availability | Another runtime that can crash; the watchdog covers it like the others |
| Performance | Runs in parallel with the other verifiers; adds no step on the critical path unless it is last |
| Security / identity | Commits as `cross-auditor`; runs with approvals off and full disk access, as the Claude seats run in `auto` |
| Changeability | Its mandate is generic and names its harness and model on the first two lines |
| Cost | Tokens on a second plan; no extra Claude spend |

## What we do not know

- **One revision, one run per arm.** The overlap result comes from a single revision of one
  stage. A second family could agree with the first more often elsewhere.
- **Whether the seven breaks are in the hidden suite.** They break stated requirements, so
  fixing them is right regardless; whether they change the score is unknown.
- **The reviewer mandate on Codex** (option B) is untested.
- **How the cross-auditor behaves on a long stage** with a browser interface; practice run 6 was
  a one-file service.

## Result in the submitted run

Four stages, one dispatch, 4 October 2026 (`FACTORY.md` sections 6 and 7).

- **The cross-auditor alone rejected five revisions that all three Claude verifiers accepted:**
  `69289b3` and `0e8dea4` (stage 1), `7c35a2a` (stage 3), `8bbd03a` and `2bd67ec` (stage 4).
  Among them: fractional amounts rounded into valid payments, a paid request that a hand-edited
  import let be paid a second time, legacy statements that skipped validation on import, and a
  genuine stage-3 export that stage 4 refused.
- **It cast 13 of the run's 27 reject verdicts**, more than any other seat (reviewer 8,
  spec-auditor 4, customer 2).
- **The overlap is still partial in the other direction.** It accepted `94e856c`, which the
  customer had rejected for a button label crowding the edge of its pill, and the reviewer reached the
  stage-2 currency-label and hold-expiry defects on a revision it never judged. Neither family covered the other, as in the experiment.
- **Cost:** 1.30 M input, 233 k output and 46.7 M cached tokens on the ChatGPT plan, 22 points of
  that plan's weekly allowance. Its reject rounds lengthened stage 1 (three rounds) and stage 4
  (six) more than any other seat's.

The condition for bringing option A back, that it raises nothing the Claude verifiers did not,
was not met. The decision stands.

## Revisit when

The cross-auditor goes a whole multi-stage run without a reject that the Claude verifiers missed,
or a different second family (or option B, the reviewer on Codex) is measured against it on the
same revisions.
