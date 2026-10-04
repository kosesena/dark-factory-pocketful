# Stage 2 requirements ledger — spec-auditor

Source: `pocketful/spec/stage-2.md` (verbatim as sent by coordinator). Every stage-1 requirement
(`ledger/stage-1.md`, R1–R127) still applies; numbers below are S2-n.
Shipped checks read: `pocketful/test/stage_2/test_sample.py`, `test_ui.py` (UI by `data-testid`,
one hold check, one stage-1→stage-2 import check). The stage-1 suite also runs against stage 2.

Legend: **C** covered · **P** partly covered · **U** uncovered.

## Routes, negotiation, product quality

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S2-1 | `/`, `/requests`, `/split`, `/signup`, `/login`, `/authorizations` reachable by URL | "The following screens must be reachable by URL." | P — `/authorizations` unchecked |
| S2-2 | `/requests` and `/authorizations`: HTML for `Accept: text/html`, JSON otherwise (API clients, no Accept, `Accept: */*`, `application/json`) | "Return the UI for `Accept: text/html`; API requests without that header receive JSON." | P — stage-1 API suite sends no text/html; real browser Accept string and `/authorizations` unchecked |
| S2-3 | No horizontal page scroll at 375 px and desktop | "without horizontal page scrolling" | U |
| S2-4 | Visible labels, visible keyboard focus, sufficient contrast | "Inputs need visible labels, keyboard focus must be apparent" | U |
| S2-5 | Designed empty, loading, error states; consistent navigation on all routes | "Provide considered empty, loading and error states, and keep navigation consistent" | P — empty testids only |
| S2-6 | Available is the clearest money value once holds exist; total and held secondary | "Available funds must be the clearest monetary value once holds exist" | U |
| S2-7 | Available, held, pending, loading, success, refused, uncertain visually distinct | "must be visually distinct" | U |
| S2-8 | People-first formatting of people, amounts, timestamps; IDs only where useful | "Format people, amounts and timestamps for people first" | U |

## Signup / login UI

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S2-9 | Signup and login testids work; signup signs in | table | C |
| S2-10 | `auth-error` present only when there is an error (absent on a clean page and after success) | "Present only when there is one" | P — presence only |
| S2-11 | `current-user` visible on **every** screen when signed in | "Visible on every screen when signed in." | P — after login only |
| S2-12 | `current-handle` text is exactly the handle | table | C |
| S2-13 | Logout removes the session | `logout-button` | C |
| S2-14 | Signup error (email_taken, handle_taken, short password) shown in `auth-error` | `auth-error` | U |

## Wallet and pay form `/`

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S2-15 | `wallet-balance` exact format `100.00 EUR`, `1200 JPY`; `data-amount` minor units | "Formatted amount" | P — EUR and JPY; BHD (3 places, e.g. `0.005 BHD`) and amounts below one unit (`0.05 EUR`) unchecked |
| S2-16 | Decimal input: `15`, `15.00` → 1500, `15.5` → 1550 | "`15.00` and `15` both submit `1500`; `15.5` submits `1550`" | P — `15.5`, `15.00` only |
| S2-17 | Nonnumeric or too many places → form error, **no request sent** | "must show the form's error element without sending a request" | P — `15.005` balance check only; nonnumeric (`abc`, `1e3`, `-5`, `15,00`, ``) and "no request sent" unchecked; same rule on request, split and authorize forms unchecked |
| S2-18 | `pay-visibility` option values exactly `public`, `private` | table | P |
| S2-19 | Pay form keeps values after success; resubmit unchanged = replay (same key, same body), money once, no `pay-error` | "Submitting it again without changing a field must not send another payment" | C |
| S2-20 | Changing any field → new key | "Changing a field makes the next submission a new payment request." | P — amount only; note/visibility/handle change unchecked |
| S2-21 | Request form works and shows `request-error` on refusal (self_request, unknown handle, bad amount) | table | U |
| S2-22 | After any success, balance, feed and request lists on that page refresh without reload; refresh waits for the write | "Navigation must wait for the write to succeed before it refreshes the data." | P — pay only |

## Feed `/`

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S2-23 | Feed item testids, visibility attribute, parties, amount, note (present when empty) | table | C |
| S2-24 | Newest first in DOM | "Its children are newest first in the DOM" | C |
| S2-25 | `empty-activity` shown **instead of** the list | "Shown instead of the list when nothing is visible" | P |
| S2-26 | Captures appear in the feed by the ordinary rule; open authorisations never | "An open authorisation is **not** a feed item" | U |

## Requests `/requests`

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S2-27 | Item testids, `data-status`, exact amount | table | C |
| S2-28 | Pay/decline only on pending incoming; cancel only on pending outgoing; absent otherwise | "Present only on a `pending` incoming request" | P — pay absence after pay and on outgoing; decline/cancel absence on non-pending unchecked |
| S2-29 | `request-error` on refused pay/decline/cancel | table | P — insufficient only |
| S2-30 | `empty-requests` when both lists empty | table | C |
| S2-31 | Request pay from the UI is idempotent (a double click pays once) | §7 "Retries follow §7" | U |

## Split `/split`

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S2-32 | Preview equals server rule before posting; one share per participant | "`split-preview` must show the shares the server would compute" | C (EUR, 3 people) |
| S2-33 | Preview and submitted split identical; preview with caller omitted, whitespace around commas, JPY/BHD | "The preview and submitted split must have identical shares." | P |
| S2-34 | `split-amount` same decimal rule as `pay-amount` (refuses `10.005`, nonnumeric, no POST) | "Decimal input, same rule as `pay-amount`" | U |
| S2-35 | `split-error` on unknown handle, duplicate, empty | table | P — unknown only |

## Competing clients and uncertain outcomes

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S2-36 | `wallet-refresh` refreshes balance+feed, keeps pay form | "refreshes the balance and feed without clearing the pay form" | P — form kept unchecked |
| S2-37 | Latest refresh wins under out-of-order responses | "a delayed earlier read must not overwrite a later refresh" | U |
| S2-38 | Refused payment → `pay-error`, balance/feed refreshed, all inputs preserved | "A refused payment shows `pay-error`, refreshes the balance/feed, and preserves all pay inputs." | P — error only |
| S2-39 | Request cancelled elsewhere → `request-error` on pay, list refreshed, stale pay button gone | "refresh the request list so the stale pay button disappears" | U |
| S2-40 | Lost response (incl. after commit) → `pay-uncertain` nonempty, not `pay-error`; retry with same key+body; success clears both, refreshes, money once | "show `pay-uncertain` (nonempty text), not `pay-error`" | U |
| S2-41 | Same refresh rules for available and held | "The same balance refresh rules apply to the available and held amounts" | U |

## Upgrade

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S2-42 | Stage-2 imports the team's stage-1 export | "A stage-2 service must accept an export produced by the same team's stage-1 service." | P — balance only |
| S2-43 | Stage-1 tokens still valid; browser stays signed in without reload | "A browser signed in before that export/import upgrade must remain signed in afterwards." | P — API token; browser session unchecked |
| S2-44 | Imported pending requests payable through the request screen | "Existing pending requests remain payable through the request screen." | U |
| S2-45 | Lost-response payment before export retryable after import with same key/body; UI recovers original and refreshes imported balance; form and retry identity survive | "the UI must recover the original payment and refresh the imported balance" | U |
| S2-46 | Imported stage-1 state: `/me` adds total=balance, available=balance, held=0; payments get `authorization_id: null`; idempotency records, settlements, operators preserved | §API changes + §10 | U |

## Authorisations — model and invariants

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S2-47 | Sum of `total` equals seeded total; holds move nothing | "A hold moves no money" | P |
| S2-48 | available = total − held ≥ 0 at every read, also under concurrency | "`available = total − held` must never be negative." | P — one hold, sequential |
| S2-49 | Held funds cannot fund payments, request pays, authorisations, settlement net debits (409 against available) | "Every `409 insufficient_funds` in stage 1 … is now evaluated against `available`." | U |
| S2-50 | Captures may spend the reserved money (capture succeeds even when available is 0) | "Captures may spend the money reserved for them." | U |
| S2-51 | Cumulative captures ≤ authorised; each capture moves money once; closed hold not capturable | invariant 3 | U |
| S2-52 | `/me`: balance == total; held = sum of open holds; available = total − held | §GET /me | P |
| S2-53 | POST /payments leaves no hold | "It must not leave an intermediate hold" | U |
| S2-54 | Seven idempotent paths; replay rules per path (incl. concurrent same key) on authorisations and captures | "There are now seven idempotent write paths" | U |
| S2-55 | `authorization_ttl_seconds` default 600; positive integer else reset 422 | "If supplied, it must be a positive integer number of seconds." | U |
| S2-56 | `expires_at` = `created_at` + ttl | "`expires_at` is `created_at` plus `authorization_ttl_seconds`." | U |
| S2-57 | Seeded authorisations: own `expires_at`, statuses open/captured/voided/expired; only open (unexpired) holds | "Only `open` holds anything." | U |
| S2-58 | available derived from seeded open holds | "**`available` is derived, never seeded**" | U |
| S2-59 | Seeded unexpired open holds > balance → reset 422, nothing changes; expired-by-clock seeded holds do not count | "A sum of seeded unexpired open holds larger than that user's `balance` is a reset error" | U |
| S2-60 | `authorizations` omitted = empty | "omission means an empty list" | P (every stage-1 fixture) |
| S2-61 | Clock expiry with no request at the deadline: lists show `expired`, `/me` releases remainder, writes see it | "Reads and writes must reflect expiry even if no request occurred at the deadline." | U |
| S2-62 | Expired-by-clock matches `status=expired`, never `open` | "matches `expired`, never `open`" | U |

## Authorisations — API

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S2-63 | POST /authorizations 201 shape (authorization_id, from/to ids+handles, amount, captured_amount 0, currency, note, visibility, status open, expires_at, payment_id null, created_at, remaining_amount) | example + "Every authorization response adds `remaining_amount`" | P — status only |
| S2-64 | Authorise errors: 409 available, 422 amount, 422 self_payment, 422 note/visibility, 404, 400 key | table | U |
| S2-65 | Capture: only receiver; 403 for payer and third party; 404 unknown | "Only the receiver (the `to` party) may capture." | U |
| S2-66 | Capture returns payment shape + `authorization_id`, `request_id: null`, `settlement_id: null`; note/visibility copied | "in exactly the shape `POST /payments` returns" | U |
| S2-67 | Ordinary payments carry `authorization_id: null` | "Payments created without an authorisation carry `authorization_id: null`" | U |
| S2-68 | Default capture is final: status captured, captured_amount, payment_id, remainder released in the same step | "**releases the uncaptured remainder immediately**" | U |
| S2-69 | Second capture after final → 409 authorization_not_open | table | U |
| S2-70 | `{}` and `{"amount": N}` are different bodies for replay | "reusing a key across the two is 409 `idempotency_key_reuse`" | U |
| S2-71 | `final: false` keeps remainder held, status open; further captures up to remainder; capturing whole remainder closes; `final` must be boolean (wrong type → 400) | "Extended capture mode" | U |
| S2-72 | `capture_exceeds_authorization` compares with remaining (422) | "compares with the **remaining** amount" | U |
| S2-73 | Capture amount <1 / non-integer → 422 validation_failed | table | U |
| S2-74 | Capture after expiry → 409 authorization_expired | table | U |
| S2-75 | `captured_amount` cumulative; `payment_id` latest; `payment_ids` all in order; `remaining_amount` 0 when closed | §Extended | U |
| S2-76 | Void: only payer (403 receiver/third); 200 voided; releases hold; void twice 200; captured/expired → 409 not_open | §void | U |
| S2-77 | Void / expiry of a partially captured authorisation releases only the remainder and keeps capture records | "release only the remainder, and preserve all capture records" | U |
| S2-78 | GET /authorizations: only own, newest first, direction/status filters, 422 on bad values, paging as /requests | §GET /authorizations | U |
| S2-79 | New fields do not change idempotency body equality (replay after later captures returns original body) | "New fields do not change idempotency body equality." | U |
| S2-80 | Concurrent operations linearizable (e.g. concurrent captures of one hold, capture vs void, pay vs authorise on one wallet) | "Concurrent requests must produce the same results as executing them one at a time in some order" | U |
| S2-81 | Export/import preserves authorisations, holds, ttl, capture records, auth idempotency | stage-1 §10 | U |
| S2-82 | Reset/import with authorisations: invalid seeded authorisation → 422 | §Model | U |

## Authorisations UI

| # | Requirement | Quote | Cov |
|---|---|---|---|
| S2-83 | `wallet-available` headline with data-amount; `wallet-held` with data-amount, absent at zero; `wallet-balance` shows total | UI table | U |
| S2-84 | Authorise form testids, same input rules, `authorize-error` (incl. insufficient available) | table | U |
| S2-85 | `authorization-list` newest first; item `data-status`; amount; captured only when captured; expires is RFC 3339 text | table | U |
| S2-86 | Capture amount input pre-filled with remaining; capture button only on incoming open; void only on outgoing open | table | U |
| S2-87 | `authorization-error` on refused capture/void; `empty-authorizations` | table | U |
| S2-88 | UI reflects seeded holds right after reset (available headline) | "including immediately after reset with open holds" | U |

## Ambiguities and the reading taken

- B1 Capture on an authorisation whose `expires_at` has passed: it is both "not open" (expired)
  and "expired". Reading: `409 authorization_expired` (the specific row); a seeded `voided`/`captured`
  is `authorization_not_open`. For a seeded `status: "expired"` I would also return `authorization_expired`.
- B2 Seeded `captured` authorisation without `captured_amount`: reading — captured_amount = amount, remaining 0.
- B3 Expired after a partial capture: status `expired`, `captured_amount` kept; `authorization-captured-{id}` absent (only for `captured`).
- B4 `final` of wrong JSON type → 400 malformed_request (§5 wrong type); `amount: null` on capture → 422.
- B5 Precedence on capture: auth (401) → key/parse → claimed key → 404 → 403 → body validation → not_open/expired → exceeds → funds n/a.
- B6 `Accept` with text/html anywhere in the list (browser default) → HTML; `*/*` or none → JSON.
- B7 Stage-1 export imported into stage 2: `authorization_ttl_seconds` defaults to 600.
