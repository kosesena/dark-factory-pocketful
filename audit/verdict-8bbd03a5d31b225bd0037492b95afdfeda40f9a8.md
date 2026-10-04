# spec-auditor verdict — stage 4, revision 8bbd03a5d31b225bd0037492b95afdfeda40f9a8

**ACCEPT 8bbd03a.** No open gap cites a spec sentence.

## Method
- Judged from a clean `git archive 8bbd03a` (not the working tree, which holds uncommitted edits in stage-3/ and stage-4/).
- Shipped checks pass stage 4 in standard and isolated modes (`checks/spec-auditor-8bbd03a-host`, `-isolated`).
- `audit/probes/stage4_probes.py`: 13/13 probes pass, twice, against the archived stage-4 service. A stage-3 service
  from the same archive served the upgrade probe. The probes cover every gap in `ledger/stage-4.md`, S4-1 to S4-39.
- Regression against the stage-4 service:
  - Stage-1 probes: 39/39 pass.
  - Stage-2 probes: 14/14 applicable probes pass (the upgrade probe needs a stage-1 URL).
  - Stage-3 probes: 12/12 applicable probes pass. The one difference is that revisions now carry
    `correction_batch_id: null`. Stage 4 requires this field, so it is additive.
- Ambiguity readings D1–D7 checked directly:
  - D1: a payment corrected to 0 refuses any refund with refund_exceeds_payment.
  - D2: a refunded capture leaves its authorization captured, and the hold is not restored.
  - D5: item errors come first, in input order.
  - D7: stage-3 snapshots page without refund_of.
- Also checked: a batch that lowers a settlement member below its refunded amount gets 422 refund_exceeds_payment.
- RUN.md matches the observed behaviour. One wording nit: the batch paragraph puts "one effective instant" next to
  `(incomplete_settlement)`, but mismatched instants return `validation_failed`, as the spec requires.

## Gap walk (ledger/stage-4.md)
All 39 requirements are **met**.

## Fault seeding (`ledger/stage-4-faults.md`)
- 15 faults seeded: 14 caught, 1 equivalent (J12), 0 surviving. The unmodified control copy is caught by nothing.
- J12 replaces `max(now, last + 1e-6)` with `now` for the batch recorded time. It is unreachable: import refuses
  revisions recorded in the future, and a batch always comes later than any earlier revision. A test with an injected
  clock is suggested, not blocking.
- J11 (batch debits checked against balance instead of available) is caught only by the implementer's tests and the
  cross-auditor. J15 (pre-stage-4 snapshot form) is caught by the implementer, the customer and my probes.

## Non-blocking
- Payment created_at is stamped to the whole second, as in stage 3 (see the stage-3 verdict for 7c35a2a).
