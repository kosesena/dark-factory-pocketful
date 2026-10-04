# Stage 4 requirements ledger — spec-auditor

Source: `pocketful/spec/stage-4.md` (verbatim as sent by coordinator). Stages 1–3 still apply (R1–R127, S2-1–S2-88,
S3-1–S3-58). Numbers below are S4-n.
Shipped checks read: `pocketful/test/stage_4/test_sample.py`, 5 checks:
- `refund_of: null` on a direct payment
- a refund is a reverse payment with `refund_of`, and total falls
- refund replay returns 200 with the original body
- an operator corrects one payment in a batch (201, one revision, balance)
- a non-operator gets 403 on batches

Legend: **C** covered · **P** partly covered · **U** uncovered.

## Refunds

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S4-1 | `POST /payments/{id}/refunds` requires an idempotency key (400), a token (401) | "requires an idempotency key" | U |
| S4-2 | Only the original receiver refunds; sender and third party → 403; unknown → 404 | "Only the original receiver may refund, else 403 `forbidden`" | U |
| S4-3 | Targets: direct, request payment, capture, settlement member; a refund is never a target → 422 invalid_refund_target | "Refunds of refunds give 422 `invalid_refund_target`." | U |
| S4-4 | Invalid amount (0, negative, >1e9, fractional, bool, string, missing) → 422 | "Invalid amount is 422 `validation_failed`." | U |
| S4-5 | Cumulative refunds ≤ current corrected amount → else 422 refund_exceeds_payment (after a correction lowers the amount, the cap follows) | "Refunds cumulatively may not exceed the payment's current corrected amount" | U |
| S4-6 | Refund = new payment receiver→sender with refund_of, request_id null, authorization_id null, settlement_id null, original note and visibility; 201 | "A refund is a new payment in the opposite direction" | P — direction/amount only |
| S4-7 | Replay 200 original body; different body → 409 reuse; concurrent same key → one 201 | "replay returns 200 with the original body" | P — sequential replay only |
| S4-8 | Moves money from the receiver's **available** funds (held money excluded) → else 409 insufficient_funds, atomically | "It moves existing money from the receiver's **available** funds" | U |
| S4-9 | Refunds never reopen a request or authorization or restore a released hold | "Refunds never reopen a request or authorization or restore a released hold." | U |
| S4-10 | Every other payment has `refund_of: null` (request pay, capture, settlement member, seeded, imported, statement entries, activity) | "Other payments have `refund_of: null`." | P — direct only |
| S4-11 | A refund is an ordinary payment: in activity by visibility, in both statements, revision history (revision 1) | inferred: "a new payment" | U |
| S4-12 | Concurrent refunds of one payment can't exceed the corrected amount in total | §1 invariants + S4-5 | U |

## Corrections after stage 4

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S4-13 | Single corrections still work for ordinary direct and request payments | "Stage-3 corrections remain available for ordinary direct/request payments." | U |
| S4-14 | Correcting a capture or a refund payment → 422 linked_payment_immutable | "Captures and refund payments cannot themselves be corrected" | U |
| S4-15 | A correction can't reduce a payment below its refunded total → 422 refund_exceeds_payment | "A correction cannot reduce a payment below its already-refunded amount" | U |
| S4-16 | Correction debits are checked against available (held funds excluded) | "Correction debits are checked against available funds." | U |

## Batch corrections

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S4-17 | Operator only; 401 no token; 403 non-operator; key required | "requires a settlement operator and an idempotency key" | P — 403 only |
| S4-18 | 1..32 items with distinct payment_ids; 0, 33, duplicates, non-array, non-object → 422 | "corrections contains 1..32 objects with distinct payment_ids" | U |
| S4-19 | Each item validated like a correction (fields, ranges, effective_at ≤ now) | "Every item has the ordinary correction fields and validation." | U |
| S4-20 | Unknown payment 404; stale expected revision 409 stale_revision | §batches | U |
| S4-21 | Operator may correct ordinary, request and settlement payments (any sender, not only their own); captures and refunds → 422 linked_payment_immutable | "The operator may correct ordinary, request and settlement payments" | P — own payment only |
| S4-22 | Any settlement member requires every member → 422 incomplete_settlement | "requires including every member of that settlement" | U |
| S4-23 | Members of one settlement must share an identical effective instant (offset spelling may differ) → else 422 validation_failed | "Members of one settlement must have identical effective instants (offset spellings may differ)" | U |
| S4-24 | Precedence: item errors in input order → completeness → current available → historical total/available at every boundary | "Error precedence is: item errors in input order, settlement completeness, …" | U |
| S4-25 | Affordability on the combined effect of all items (an individually unaffordable item may pass when combined) | "Affordability is determined by the combined effect of all proposed revisions." | U |
| S4-26 | A rejected batch leaves history, balances and idempotency records unchanged (key reusable) | "A rejected batch leaves history, balances and idempotency records unchanged." | U |
| S4-27 | 201 with correction_batch_id, recorded_at, revisions in input order; all share recorded_at, strictly later than every member's previous recorded_at; each revision exposes correction_batch_id | "All new revisions share recorded_at, strictly later than the previous recorded_at of every member" | P — fields present |
| S4-28 | Effective times not later than now | "Effective times cannot be later than now." | U |
| S4-29 | Original payments, receipts, payment and settlement retries unchanged (replay returns the original bodies) | "Original payment and settlement retries return their original bodies." | U |
| S4-30 | New statements reflect new revisions; earlier snapshots page their frozen entries | "earlier snapshot tokens continue to page their frozen entries" | U |
| S4-31 | Batch replay → 200 original response; different body → 409 | "Replays return the original batch response with 200." | U |
| S4-32 | Unknown fields ignored | "Unknown fields are ignored." | U |
| S4-33 | Concurrent corrections (single or batch) sharing any expected payment revision: at most one succeeds | "Concurrent corrections sharing any expected payment revision cannot both succeed." | U |
| S4-34 | Single-payment corrections still reject settlement members (stage 3) but batches accept them | "Ordinary single-payment corrections remain available for nonmembers." | U |

## Settlements, upgrades

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S4-35 | A settlement member may be refunded; membership unchanged (the refund isn't a member; the settlement receipt unchanged) | "refunds never change settlement membership" | U |
| S4-36 | Accept stage 1–3 exports, keeping settlement membership, corrections and snapshots | "A stage-4 service must accept exports produced by the same team's stages 1–3" | U |
| S4-37 | Saved statements/snapshots keep their original form (pre-stage-4 snapshots page without new fields) | "Existing receipts and saved statements must remain available in their original form." | U |
| S4-38 | Ten idempotent write paths; replay rules apply to each | "There are ten idempotent write paths" | P |
| S4-39 | Historical views (as_of/known_at, statements) account for refunds as payments and batch revisions with their recorded_at | §stage 3 rules | U |

## Ambiguities and the reading taken

- D1 Refunding a payment that was corrected to 0 → 422 refund_exceeds_payment for any positive amount.
- D2 A capture's refund doesn't restore the hold; the authorization stays captured.
- D3 A batch item for the operator's own payment and for others' payments are treated the same.
- D4 A batch with one settlement member's effective_at in a different offset spelling of the same instant is valid.
- D5 Precedence inside "item errors": per item, the stage-3 order of checks (404, then 422 field validation, then linked_payment_immutable, then stale_revision, then refund_exceeds_payment); items are walked in input order and the first failing item decides.
- D6 A refund's effective/recorded time is its created_at (revision 1), like any payment.
- D7 Stage-3 snapshots imported into stage 4 page without `refund_of` in their entries (original form); new stage-4 snapshots include it.
