# Stage 4 independent atomic requirements

Inherited R001–R101/S001–S083/T001–T085 continue. Each quote is from the supplied stage4 specification; final revision report records disposition/evidence.

| ID | Atomic obligation and quote |
|---|---|
| U001 | Inherited behavior retained: “All requirements from stages 1–3 continue to apply.” |
| U002 | Refund idempotency: “POST /payments/{payment_id}/refunds ... requires an idempotency key.” |
| U003 | Refund permission: “Only the original receiver may refund, else 403 forbidden”. |
| U004 | Unknown target: “unknown payment is 404.” |
| U005 | Eligible target types: “The target may be a direct payment, request payment or capture”. |
| U006 | Refund amount validation: “Invalid amount is 422 validation_failed.” Inherited payment integer1..1e9 range. |
| U007 | Refund capacity: “Refunds cumulatively may not exceed the payment's current corrected amount: 422 refund_exceeds_payment.” |
| U008 | Refund of refund forbidden: “Refunds of refunds give 422 invalid_refund_target.” |
| U009 | Reverse payment: “A refund is a new payment in the opposite direction, with refund_of naming the target”. |
| U010 | Links null: “request_id: null, authorization_id: null”. |
| U011 | Copied metadata: “and the original note/visibility.” |
| U012 | Original refund receipt replay: “Return 201 with that payment; replay returns 200 with the original body.” |
| U013 | Available funds atomicity: “It moves existing money from the receiver's available funds, or fails 409 insufficient_funds, atomically.” |
| U014 | Terminal request/hold remains terminal: “Refunds never reopen a request or authorization or restore a released hold.” |
| U015 | Nonrefund field: “Other payments have refund_of: null.” |
| U016 | Ordinary/request corrections remain: “Stage-3 corrections remain available for ordinary direct/request payments.” |
| U017 | Immutable linked corrections: “Captures and refund payments cannot themselves be corrected: 422 linked_payment_immutable.” |
| U018 | Correction refund floor: “A correction cannot reduce a payment below its already-refunded amount: 422 refund_exceeds_payment.” |
| U019 | Correction available check: “Correction debits are checked against available funds.” |
| U020 | Batch operator/auth: “POST /correction-batches requires a settlement operator ... same 401/403 rules as settlements.” |
| U021 | Batch key: “and an idempotency key”. |
| U022 | Batch shape/count/distinct ids: “corrections contains 1..32 objects with distinct payment_ids, else 422 validation_failed.” |
| U023 | Batch fields: “Every item has the ordinary correction fields and validation.” |
| U024 | Batch unknown/stale: “Unknown payment is 404; a stale expected revision is 409 stale_revision.” |
| U025 | Operator target eligibility: “The operator may correct ordinary, request and settlement payments, but captures and refunds remain immutable.” |
| U026 | Settlement complete: “Correcting any settlement member requires including every member ... else 422 incomplete_settlement.” |
| U027 | Settlement effective instant: “Members of one settlement must have identical effective instants (offset spellings may differ), else 422 validation_failed.” |
| U028 | Nonmember single correction: “Ordinary single-payment corrections remain available for nonmembers.” |
| U029 | Unknown fields ignored: “Unknown fields are ignored.” |
| U030 | Item error order: “Error precedence is: item errors in input order”. |
| U031 | Completeness before funds: “settlement completeness, resulting current available funds, then historical total and available funds”. |
| U032 | Combined affordability: “Affordability is determined by the combined effect of all proposed revisions.” |
| U033 | Historical every boundary: “at every effective/event boundary.” |
| U034 | Rejected batch atomicity: “A rejected batch leaves history, balances and idempotency records unchanged.” |
| U035 | Batch receipt/order: “Return 201 with correction_batch_id, recorded_at and revisions in input order.” |
| U036 | Shared/increasing recording time: “All new revisions share recorded_at, strictly later than the previous recorded_at of every member”. |
| U037 | Revision batch link: “each revision also exposes correction_batch_id.” |
| U038 | No future effective times: “Effective times cannot be later than now.” |
| U039 | Immutable originals: “Original payments and receipts never change.” |
| U040 | Original retries: “Original payment and settlement retries return their original bodies.” |
| U041 | Statement corrected/frozen views: “New statements reflect the new revisions; earlier snapshot tokens continue to page their frozen entries.” |
| U042 | Batch replay: “Replays return the original batch response with 200.” |
| U043 | Settlement refunds: “A settlement payment may be refunded ... refunds never change settlement membership.” |
| U044 | Overlapping revision concurrency: “Concurrent corrections sharing any expected payment revision cannot both succeed.” |
| U045 | All older exports: “A stage-4 service must accept exports produced by the same team's stages 1–3”. |
| U046 | Migration records: “retaining settlement membership, corrections and snapshots.” |

Interpretation: refund amount uses inherited ordinary payment amount validation, positive exact integer1..1e9. Capture is explicitly a legal refund target even though RUN.md says otherwise; specification controls. Old snapshots must be validated against their frozen revisions, not current latest revisions.
