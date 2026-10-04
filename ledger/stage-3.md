# Stage 3 requirements ledger — spec-auditor

Source: `pocketful/spec/stage-3.md` (verbatim as sent by coordinator). Stage-1 (R1–R127) and stage-2 (S2-1–S2-88)
requirements still apply. Numbers below are S3-n.
Shipped checks read: `pocketful/test/stage_3/test_sample.py`, 6 checks:
- created_at has an offset
- `/me` without `as_of` has no `as_of` field
- a future `as_of` returns the current balance and is echoed
- statement arithmetic closes
- `balance_after` walks forward with signed deltas
- one correction gives revision 2 and a new balance

Legend: **C** covered · **P** partly covered · **U** uncovered.

## Payment timestamps and seeding

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S3-1 | Every endpoint returning a payment includes `created_at` with an offset (payments, pay, capture, settlement members, activity, statement entries, replays) | "Every endpoint returning a payment includes it." | P — POST /payments only |
| S3-2 | Seeded `created_at` honoured; omission = reset time, before later API payments | "omission uses reset time, before subsequent API-created payments" | U |
| S3-3 | Seeded `created_at` in the future → reset 422, no state change | "A seeded `created_at` in the future gives `422 validation_failed`" | U |
| S3-4 | Loading seeded payments does not change the fixture balance | "Loading those payments must not change that balance." | U |
| S3-5 | Opening balance = seeded ending balance − net of original seeded payments; corrections never change it; new accounts open at 0 | "Opening balances equal seeded ending balances minus the net effect of original seeded payments." | U |

## `GET /me?as_of`

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S3-6 | `as_of` must be RFC 3339 with offset; naive, bare date, empty → 422 | "a naive local time, a bare date, an empty value — is 422" | U |
| S3-7 | Without temporal params: existing fields, current corrected values, no `as_of` | "retains the existing money fields and reports current corrected values" | P |
| S3-8 | Balance after every payment at or before `as_of` (inclusive at exactly `as_of`) | "A payment made at exactly `as_of` counts as having happened." | U |
| S3-9 | `as_of` before the earliest payment → opening balance (incl. before a seeded payment) | "returns the opening balance — what the wallet held before anything moved" | U |
| S3-10 | `as_of` at/after the latest → current balance | §as_of | C |
| S3-11 | `as_of` echoed exactly as given (offset spelling, fraction kept) | "The response carries `as_of` back, exactly as given." | P — one spelling |

## `GET /statement`

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S3-12 | `from` defaults to wallet opening, `to` to now; half-open `[from, to)` | "half-open window `[from, to)`" | P — defaults only |
| S3-13 | Oldest first by created_at (then effective_at), ties by payment id ascending | "then payment `id` ascending for ties" | P — two payments at different times |
| S3-14 | `opening_balance` = balance just before `from`; `closing_balance` = just before `to` | statement req. 2 | P — default window only |
| S3-15 | opening + Σdelta(full window) = closing; sent negative, received positive | statement req. 3 | P — sent only |
| S3-16 | Pagination never changes `balance_after`, opening or closing; `limit`/`offset` as /requests (defaults, ranges, plain digits) | statement req. 4 | U |
| S3-17 | Only the caller's own payments, never public third-party payments | "including when other payments are public" | U |
| S3-18 | `from`/`to` invalid (naive, date, empty) → 422; `from > to` handling | "Invalid/empty instants are 422" | U |

## Corrections

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S3-19 | Revision 1 = original amount, effective_at = recorded_at = created_at (seeded: supplied created_at or reset time) | "Revision 1 has `amount` as originally paid" | U |
| S3-20 | Only the original sender; non-sender 403, unknown 404, no token 401, key required (400) | "requires an idempotency key and the original sender" | U |
| S3-21 | All fields required; revision positive int; amount int 0..1e9; reason str 1..200; effective_at RFC 3339 not later than now; invalid → 422 | §corrections | U |
| S3-22 | 201 with payment_id, revision, amount, effective_at, recorded_at, reason; parties and visibility unchanged | "returning 201 with `payment_id`, `revision`…" | P — revision only |
| S3-23 | recorded_at strictly increases per payment (even within one second) | "Recorded times for one payment strictly increase." | U |
| S3-24 | Stale expected revision → 409 stale_revision | §corrections | U |
| S3-25 | Replay → 200 original revision even after newer revisions; different body → 409 reuse | "Successful replay returns that original revision with 200 even after newer revisions." | U |
| S3-26 | Difference moves between the same wallets atomically: increase debits sender, decrease debits receiver; amount 0 reverses fully | "Increasing the amount debits the original sender; decreasing it debits the original receiver." | P — decrease only |
| S3-27 | Current unaffordable debit → 409 insufficient_funds (checked against available) and takes precedence over historical_overdraft | "A currently unaffordable debit gives 409 `insufficient_funds`." | U |
| S3-28 | Any user's corrected balance negative at any effective boundary → 409 historical_overdraft; boundary includes all movements at that instant | "Balances at a boundary include the combined effect of all movements at that instant." | U |
| S3-29 | Failure preserves balances, history, statements, idempotency state | "Either failure preserves balances, revision history, statements and idempotency state." | U |
| S3-30 | Sum of balances equals seeded total in every historical view (any as_of/known_at) | "The sum of balances must equal the seeded total in every historical view." | U |
| S3-31 | Original payment and original idempotent responses unchanged; activity shows the original; corrections are not feed items | "correction records are not new feed payments" | U |
| S3-32 | GET /payments/{id}/revisions: revision order, revision 1 reason ""; only the two parties; third party 404 even if public; no token 401 | §revisions | U |
| S3-33 | Concurrent corrections with the same expected revision: at most one succeeds | "Concurrent corrections using the same expected revision cannot both succeed." | U |

## `known_at` (bitemporal reads)

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S3-34 | For each payment, latest revision recorded at or before known_at; none → contributes nothing | "if none was yet recorded, that payment contributes nothing" | U |
| S3-35 | Then apply by effective time; as_of inclusive, statement half-open | §known_at | U |
| S3-36 | Both instants may be in the future; invalid/empty → 422; known_at echoed exactly | "Echo supplied `known_at` exactly." | U |
| S3-37 | Omission = everything known when the read begins | §known_at | P |
| S3-38 | Statement order by selected effective_at then id; entries add revision, effective_at, recorded_at; payment.amount = selected amount; zero-amount revisions appear with delta 0; never double counted | "No correction is counted alongside the revision it replaces." | U |
| S3-39 | A backdated correction moves a payment into/out of a window and changes opening/closing accordingly | "A correction may move a payment into or out of a statement window." | U |
| S3-40 | Without corrections and known_at, previous behaviour is unchanged | §known_at | P |

## Snapshots

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S3-41 | Every first statement response returns an opaque `snapshot` | "Every first `GET /statement` response additionally returns an opaque `snapshot` token." | U |
| S3-42 | Snapshot freezes revisions, window, balances, entries and the default `to`; pages identically after new payments, corrections, lifecycle events | "pages that exact result, even after payments or corrections" | U |
| S3-43 | Only limit/offset with snapshot; from/to/known_at with it → 422 | "supplying `from`, `to` or `known_at` with it gives 422" | U |
| S3-44 | Unknown token, another user's token, token from before reset → 404 | §snapshots | U |
| S3-45 | has_more correct on the final partial page and beyond the end | "the final partial page and offsets beyond the end must report `has_more` correctly" | U |
| S3-46 | Snapshots unchanged under concurrent payments/corrections | "Existing snapshots remain unchanged during concurrent payments or corrections." | U |
| S3-47 | Snapshots survive export/import (state includes them) — inferred from §10 "Preserve … all completed … original responses" plus "Tokens last until reset" | §10 + snapshots | U |

## Settlements, upgrades, holds

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S3-48 | Settlement member revision 1 uses committed_at for effective and recorded | "Each member's original revision uses its shared committed_at" | U |
| S3-49 | Correcting a settlement member → 422 linked_payment_immutable; correcting a capture → 422 linked_payment_immutable | §settlement history | U |
| S3-50 | Accept stage-1 and stage-2 exports; ledger accounts for authorizations and captures (historical views, revisions) | "A stage-3 service must accept exports produced by the same team's stage-1 or stage-2 service." | U |
| S3-51 | /me?as_of&known_at: all four money fields from one view; balance=total, available=total−held | "all four money fields describe that same view" | U |
| S3-52 | Hold timeline: starts at creation; nonfinal capture reduces at capture time; final capture/void/expiry releases at event time; expiry at expires_at; future queries expire open holds at the deadline | §historical holds | U |
| S3-53 | Event knowledge: non-expiry events known at their event time; creation known ⇒ deadline known | "Once creation is known, the expiry deadline is known too." | U |
| S3-54 | Authorizations expose `closed_at` (null while open; event time when closed, expires_at for expiry) | "Authorizations expose `closed_at`" | U |
| S3-55 | historical_overdraft also when **available** goes negative at a past boundary under latest revisions; insufficient_funds precedes | "if it makes either total or available negative at any past effective/event boundary" | U |
| S3-56 | Seeded open holds created at reset unless created_at supplied; seeded closed holds need no lifecycle | §historical holds | U |
| S3-57 | Statements contain money movements only; captures exactly once with links; holds/releases not entries | "authorization, release and expiry are not payments" | U |
| S3-58 | Old snapshots unchanged after any lifecycle action or correction | §historical holds last sentence | U |

## Ambiguities and the reading taken

- C1 `as_of` uses `created_at` (stage text), but after corrections the selected revision's `effective_at` governs (the known_at section says "apply selected revisions according to their effective times"). Reading: with no correction they coincide; with a correction, effective_at governs.
- C2 A seeded `created_at` with no offset: reading 422 (RFC 3339 requires one).
- C3 `from` after `to`: reading 422 validation_failed (an empty window is acceptable only if `from == to`).
- C4 The default `to` is "now" at the first read and frozen in the snapshot.
- C5 Exactly-equal instants: as_of inclusive, statement `to` exclusive, `from` inclusive.
- C6 Snapshot tokens are scoped per user; another user's token returns 404, not 403.
- C7 A correction's `effective_at` may move the payment before the wallet opening; opening balances stay fixed and historical_overdraft guards negativity.
- C8 The timestamps in captures and settlement members follow the same revision rules; corrections to them are refused.
