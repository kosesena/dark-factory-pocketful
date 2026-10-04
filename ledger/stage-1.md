# Stage 1 requirements ledger — spec-auditor

Source: `pocketful/spec/stage-1.md` (verbatim spec as sent by coordinator).
Shipped checks read: `pocketful/test/stage_1/` — `test_sample.py`, `test_seeded_state.py`,
`test_me_payments.py`, `test_requests_splits_feed.py`, `test_retries_splits_input.py`.

Legend: **C** covered (a shipped check fails if violated) · **P** partly covered (touched, but
not the edge that matters) · **U** uncovered.

## §1 Invariants

| # | Requirement | Quote | Cov |
|---|---|---|---|
| 1 | Sum of balances equals seeded total, across all operations, concurrency and retries | "The sum of wallet balances always equals the total seeded by the last `POST /_test/reset`." | P — sequential `conservation`; one 10-client single-wallet burst |
| 2 | No balance negative, even transiently, under concurrency | "No wallet balance may be negative, including transiently." | P — only one wallet, full-balance sends; no partial drain, no cycle, no request-pay/settlement races |
| 3 | A request moves money at most once (concurrent pays with different keys, pay vs cancel/decline race) | "A payment request may move money at most once." | P — sequential replay only |
| 4 | Money only moves between existing wallets | "Money moves only between existing wallets." | C |

## §2–3 Delivery and runtime

| # | Requirement | Quote | Cov |
|---|---|---|---|
| 5 | Dockerfile + RUN.md, single container, no outbound network at run time | "Deliver an HTTP service, a `Dockerfile` and a `RUN.md`…" | C (harness) |
| 6 | Listen on 0.0.0.0:$PORT, default 8080 | "Listen on `0.0.0.0` using the `PORT` environment variable, default `8080`." | P — default 8080 never exercised |
| 7 | /health 200 `{"status":"ok"}` within 60 s | "GET /health -> 200 {"status": "ok"}" | C (harness) |
| 8 | Reset replaces all state; afterwards only the fixture is visible (old users, tokens, payments, requests, idempotency keys gone) | "When reset returns 204, subsequent requests must see only that fixture." | P — old tokens / old keys / old signups after reset never probed |
| 9 | Repeated resets supported; reset unauthenticated; 204 | "Repeated resets are supported." | C |
| 10 | Responses `application/json; charset=utf-8` | "Requests and responses are `application/json; charset=utf-8`." | U |
| 11 | Response timestamps RFC 3339 with explicit offset | "Timestamps in responses are RFC 3339 with an explicit offset" | U — only truthiness/sort checked |
| 12 | Unknown body fields ignored on every endpoint | "Unknown fields in a request body are ignored, never an error." | P — `/payments` only |
| 13 | Unknown query params ignored | "Unknown query parameters are ignored." | P — `/activity` only |
| 14 | IDs are strings ≤ 64 chars | "IDs are opaque strings of at most 64 characters." | U |

## §4 Model

| # | Requirement | Quote | Cov |
|---|---|---|---|
| 15 | One currency from fixture, echoed in me/payments/requests/splits | "The service has **one currency**, declared in the fixture." | P — splits currency unchecked |
| 16 | `1000.0` and `1e3` are valid amounts on every amount field | "JSON `1000`, `1000.0` and `1e3` all represent the same valid minor-unit amount." | P — only `1e9` on `/payments` |
| 17 | Booleans are not numbers: `amount: true` → 422 | "Booleans and strings are not numbers here." | U — strings covered, booleans never |
| 18 | Handle unique, `^[a-z0-9_]{1,20}$`, immutable | "unique across the service, matching `^[a-z0-9_]{1,20}$`" | P |
| 19 | Derived handle: local part, lowercase, non-`[a-z0-9_]` → `_` per character, truncate 20 | "take the local part, lowercase it, replace every character outside `[a-z0-9_]` with `_`, and truncate to 20 characters" | P — ASCII only; non-ASCII (one `_` per character, not per byte) unchecked |
| 20 | Derived handle taken → 409 handle_taken, no account | "If that handle is already taken the signup fails" | C |
| 21 | New users start at 0, can receive and be asked immediately | "They can receive money and be asked for money immediately." | P — "be asked" unchecked |
| 22 | Request lifecycle: pending → exactly one terminal state | "A request is `pending`, and then exactly one of `paid`, `declined` or `cancelled`." | P |
| 23 | Only payer pays/declines; only requester cancels | "Only the payer may pay or decline it; only the requester may cancel it." | P — requester paying/declining own request unchecked |
| 24 | Request may exceed balance; pay while short 409, nothing changes, later payable | "an attempt to pay it while short is `409 insufficient_funds` and changes nothing" | C |
| 25 | Visibility chosen by payer at pay time | "Visibility belongs to the payment, not the request." | C |
| 26 | Feed: payment visible iff public or caller is sender/receiver | "A payment appears for a caller **if and only if**…" | P — private request-payment and private settlement members to a third party unchecked |
| 27 | Requests never in any feed; GET /requests only own | "Requests never appear in the activity feed" | C |
| 28 | A split is not a feed item | "A split is not a feed item." | U |
| 29 | Visibility identical for all viewers | "Visibility is **one value on the payment**" | P |
| 30 | amount ≤ 1e9; balances up to ±2⁵³ exact | "no operation produces a balance outside ±2⁵³. Monetary arithmetic must preserve exact minor-unit values" | U — large balances never seeded |
| 31 | Seeded users can log in; balances are post-payment, not replayed | "you do not replay seeded payments against balances" | C |
| 32 | Negative seeded balance → 422 validation_failed, nothing changes | "A `balance` below zero in a fixture is a reset error" | C |
| 33 | minor_units 0/2/3 | "`minor_units` is `0`, `2` or `3`." | C |
| 34 | Seeded payments appear as ordinary payments (id, note, visibility, request_id null, settlement_id null, created_at) | fixture format | P |

## §5 Errors

| # | Requirement | Quote | Cov |
|---|---|---|---|
| 35 | Every 4xx/5xx has `{"error":{"code","message"}}` | "Every 4xx and 5xx response carries this body" | P |
| 36 | Unparseable body → 400 malformed_request on every body endpoint | "Unparseable body, or a field of the wrong JSON type" | P — `/payments` only |
| 37 | Wrong JSON type on non-amount/note/visibility field → 400 (e.g. `to_handle: 5`, `participant_handles: "ada"`, `[1]`, `email: 5`) | "Other wrong JSON types follow the rule below… Reserve 400 `malformed_request` for… a field of the wrong type." | U |
| 38 | `note: null` / non-string note → 422 | "non-string `note` values (including `null`)… are 422" | P — `/payments` only |
| 39 | Missing/empty Idempotency-Key → 400 | "Header absent or empty" | P — absent on 4 paths; empty string and `/settlements` unchecked |
| 40 | Missing/malformed/unknown bearer → 401 unauthenticated | "Missing, malformed or unknown bearer token" | U |
| 41 | Key 1..255 chars; 256 → 422 | "`Idempotency-Key` \| 1 to 255 characters" | P — 10 000 only; 255/256 boundary unchecked |
| 42 | Integer query params plain digits: `1e9`, `4.0`, `+4` → 422 | "`1e9`, `4.0` and `+4` are 422 `validation_failed` whatever their numeric value" | U |
| 43 | Missing required field → 422 | "A required field or query parameter is missing" | P — only `to_handle` on `/payments` |
| 44 | No 5xx, including under load | "Requests must not produce 5xx responses, including under concurrent load." | P |

## §6 Authentication

| # | Requirement | Quote | Cov |
|---|---|---|---|
| 45 | Signup 201 `{user_id, display_name, token}` | signup example | P |
| 46 | Login 200 same shape | login example | P |
| 47 | Email already registered → 409 email_taken | table | U |
| 48 | Password < 8 chars → 422 (8 accepted) | table | U |
| 49 | Email not `local@domain` → 422 | table | U |
| 50 | Wrong password / unknown email → 401 | table | P — wrong password unchecked |
| 51 | Every other endpoint needs bearer | "Every other endpoint requires a bearer token" | U |
| 52 | Tokens never expire; several valid tokens per account at once | "An account may have multiple valid tokens and concurrent sessions." | P — signup token + later login token both valid unchecked |
| 53 | Passwords hashed, not plaintext | "Plaintext password storage is not permitted." | U — export is the only HTTP window |

## §7 Idempotency (applies to payments, requests, pay, splits, settlements)

| # | Requirement | Quote | Cov |
|---|---|---|---|
| 54 | Keys scoped per user | "The key is scoped to **the authenticated user**." | C |
| 55 | Replay = same user, method, path, body; same key+body on a different path is a fresh request — incl. `/requests/A/pay` vs `/requests/B/pay` | "The same key with the same body on a different path is a different request" | P — `/payments` vs `/requests` only |
| 56 | First use 201; replay 200 with identical body on all 5 paths | table | P — payments and pay only |
| 57 | Same key, different body → 409 | table | P — payments and pay only |
| 58 | Key after a 4xx is a first use (any 4xx: 404, 422, 403, 409) | "Key reused after the original request failed with 4xx" | P — 409 insufficient only |
| 59 | Body equality is JSON-value equality: key order, whitespace irrelevant | "\"Same body\" means the same JSON value after parsing" | U |
| 60 | Concurrent identical requests on unused key: exactly one 201, rest 200 same body, effect once | "For concurrent identical requests with an unused key, exactly one returns 201." | U |
| 61 | Replay returns original even after resource changed/cancelled; no state change | "A successful replay returns the original response, even after the resource changes or is cancelled." | P — pay-after-paid only |
| 62 | Claimed key resolved before field validation / resource checks: invalid body on a used key → 409 reuse | "changing a successful request to an invalid body with the same key still returns `409 idempotency_key_reuse`." | U |
| 63 | Order: body must parse and caller authenticate before key resolution (malformed body on used key → 400; no token → 401) | "After the body has parsed as a JSON object and the caller is authenticated" | U |

## §8 API

| # | Requirement | Quote | Cov |
|---|---|---|---|
| 64 | GET /me shape | example | C |
| 65 | Payment shape incl. `request_id: null`, `settlement_id: null` | example + §11 "nonmembers expose null for that field" | P — `settlement_id` never checked |
| 66 | Payment errors (409 funds, 422 amount, 422 self_payment, 422 note, 422 visibility, 404 handle) | table | C |
| 67 | Failed payment leaves no trace (incl. not in activity) | "a failed payment leaves no trace in either" | P — balance only |
| 68 | Note verbatim on payments, requests, splits | "`note` is stored and returned verbatim" | P — payments only |
| 69 | POST /requests shape; note default `""` | example | P — default unchecked |
| 70 | Requests: amount range, self_request, note >200, 404 | table | P — note >200 on requests unchecked |
| 71 | Payer balance not checked at request creation | "**The payer's balance is not checked here.**" | C |
| 72 | Pay body: visibility only, default public; invalid → 422 | "The body carries `visibility` only, optional, default `\"public\"`." | P — invalid visibility on pay unchecked |
| 73 | Pay returns payment with request_id; request → paid with payment_id | "The request becomes `paid` and carries the new `payment_id`." | C |
| 74 | Pay non-pending → 409 (declined, cancelled, paid with a new key) | table | P — declined only |
| 75 | Pay by non-payer (incl. the requester) → 403 | table | P — third party only, 403/404 accepted |
| 76 | Pay unknown → 404 | table | C |
| 77 | Pay replay 200 even when paid, no 409 | "must not return `409 request_not_pending`" | C |
| 78 | Decline: 200 with request; twice 200; paid/cancelled → 409; non-payer 403 | §8 decline | P — 409 cases unchecked |
| 79 | Cancel: 200; twice 200; paid/declined → 409; non-requester 403 | §8 cancel | P — cancel-declined unchecked |
| 80 | Decline/cancel unknown id → 404 | §5 not_found | U |
| 81 | GET /requests newest first by created_at | "Newest first by `created_at`." | U |
| 82 | direction / status filters, combinable | §8 list | P — combined unchecked |
| 83 | limit default 50, 1..200; offset ≥0 | "`limit` defaults to 50" | P — default 50 unchecked |
| 84 | has_more | "`has_more` is true when items exist beyond the last one returned." | C |
| 85 | Split shares by §9, order kept | §8/§9 | C |
| 86 | Caller omitted from participants: no share for caller, request for every listed participant | "The caller may be included in `participant_handles` or omitted." | U |
| 87 | Split response: split_id, amount, currency, note (default ""), shares, requests, created_at | example | P |
| 88 | Split requests are ordinary pending requests: listed for payer and requester, payable/declinable | "creating one `pending` request each" | P — shape only |
| 89 | Split validation: amount, empty/duplicate, note >200 → 422; unknown handle 404; nothing created on failure | table | P — note >200 and "nothing created" unchecked |
| 90 | Self-only split valid; no balance check | "A split whose only participant is the caller is **valid**" | C |
| 91 | Split replay 200 identical, no new requests | §7 | U |
| 92 | Activity newest first, paging | §8 activity | C |

## §9 Money and rounding

| # | Requirement | Quote | Cov |
|---|---|---|---|
| 93 | Shares whole, sum exact, differ ≤1, larger first | "the larger shares go to the first participants" | C |
| 94 | Zero share produces a request | "A share of `0` is legal and still produces a request" | C |
| 95 | Balances still sum after splits paid in full | "After any number of splits have been paid in full…" | U |
| 96 | Large amounts split exactly (e.g. 1e9 over 7) | §4 arithmetic | U |

## §10 Export / import

| # | Requirement | Quote | Cov |
|---|---|---|---|
| 97 | Export 200 `{track:"pocketful", format_version:1, state:{…}}` | "containing `track: \"pocketful\"`, `format_version: 1` and `state`" | P — status only |
| 98 | Import of unchanged export → 204 | "It must accept an unchanged export" | C |
| 99 | Import preserves bearer tokens | "Existing receipts, tokens and retries must remain valid after import" | U |
| 100 | Import preserves balances, requests (status, payment_id), currency | "Preserve accounts…currency, balances, payments, requests" | P — one payment only |
| 101 | Import preserves completed idempotency records: replay after import → 200 original, no money moves; different body → 409 | "all completed idempotent request bodies and original responses" | U |
| 102 | Failed keys stay reusable after import | "Failed request keys remain reusable." | U |
| 103 | Import is replacement, not merge; repeating it duplicates nothing | "Import is replacement, not merge" | U |
| 104 | Import removes destination's previous data and credentials (old tokens 401) | "Import removes all previous destination data and credentials." | U |
| 105 | Invalid JSON → 400; missing fields / wrong track / wrong version / invalid state → 422, destination unchanged | §10 | U |
| 106 | Export is an atomic snapshot unchanged by later writes | "subsequent source writes do not change it" | U |
| 107 | Reset clears imported state | "Reset clears all state, including imported state." | U |
| 108 | IDs and timestamps not regenerated | "Identities, timestamps and monetary records must not be regenerated" | P |
| 109 | Import preserves operator permissions, settlement membership, settlement replays | §10/§11 | U |
| 110 | Import has no dependency on source process (works in a fresh container) | "No dependency on the source process…" | P (isolated mode) |

## §11 Settlements

| # | Requirement | Quote | Cov |
|---|---|---|---|
| 111 | `settlement_operator_ids` in fixture, default [] | §11 | C |
| 112 | No token → 401; non-operator → 403 forbidden | "No token gives 401; authenticated non-operator gives 403 `forbidden`." | U |
| 113 | Idempotency-Key required (400 when absent) | "requires an operator and an idempotency key" | U |
| 114 | transfers 1..32; 0, 33, non-array, non-object entry → 422 | "transfers contains 1..32 objects… malformed batch shape is 422" | U |
| 115 | Per-entry amount/note/visibility rules; defaults note "" and public | "Each uses ordinary payment amount, note and visibility rules" | U |
| 116 | Unknown handle 404; self-transfer 422 self_payment | §11 | U |
| 117 | Entry errors in input order, before funds | "Entry errors take precedence in input order, before insufficient funds." | U |
| 118 | Affordability is net: final balances ≥ 0 regardless of entry order | "every wallet's balance after all incoming and outgoing transfers is nonnegative" | U |
| 119 | Unaffordable → 409 insufficient_funds; all-or-nothing | "Either all movements commit together or none do" | U |
| 120 | Failed validation claims no key, creates no payment | "failed validation claims no idempotency key and creates no payment" | U |
| 121 | 201 with settlement_id, committed_at, payments in input order | §11 | P — count only |
| 122 | Members carry settlement_id; ordinary payments carry `settlement_id: null` | "nonmembers expose null for that field" | U |
| 123 | Members: request_id null, created_at identical and equal to committed_at | §11 | U |
| 124 | Members follow feed visibility; operator is not a party → no private view | "This permission does not grant access to another user's requests or private activity items." | U |
| 125 | Settlement replay → 200 complete original | §11 | U |
| 126 | Settlement concurrent with payments keeps §1 invariants | §1 | U |
| 127 | Reset/import preserves operator permissions, payments, membership, replays | §11 last sentence | U |

## Ambiguities and the reading taken

- A1 Zero-share request (§9) being paid: amount 0. Reading: pay succeeds 201 with an
  `amount: 0` payment (the 1..1e9 rule is on input amounts; the spec says the request is legal).
- A2 `1000` vs `1000.0` as "same JSON value" (§7): reading — numerically equal, so a replay.
- A3 Third party acting on someone else's request: 403 (table) or 404 ("not visible"). Reading: 403 for pay/decline/cancel per the endpoint tables; both observable as "not actionable".
- A4 Signup with an already-registered email also derives a taken handle: reading — 409 `email_taken` wins (the email table row is first and more specific).
- A5 Request body that parses but is not an object (`[]`, `null`, `"x"`) → 400 malformed_request.
- A6 Settlement entry with wrong-typed handle fields: §11 "malformed batch shape is 422" vs §5 wrong type 400. Reading: shape of `transfers` (missing, not array, length, entry not object) → 422; `amount`/`note`/`visibility` per payment rules → 422; wrong-typed handle in an entry → 422 under the settlement-specific rule.
- A7 Email form: exactly one `@`, non-empty local and domain.
- A8 Seeded request with status `paid` has no payment to point to: `payment_id: null` acceptable.
