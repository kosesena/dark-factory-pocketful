# Stage 1 independent requirement ledger

Revision: `69289b356ae974565c86c9c3202b706afaf38483`.
Source: complete specification in the coordinator's assignment, including run contract.
Each numbered obligation is judged separately; quotes identify its source. Evidence and final statuses are in the revision-named report. Initially all are unverifiable until exercised.

| ID | Atomic obligation | Specification quote |
|---|---|---|
| R001 | Preserve total balance through operations, concurrent requests and retries | “The sum of wallet balances always equals the total seeded by the last `POST /_test/reset`.” |
| R002 | Never expose or transiently create negative balances | “No wallet balance may be negative, including transiently.” |
| R003 | Pay a request at most once | “A payment request may move money at most once.” |
| R004 | Use exact integer arithmetic and existing wallets | “All amounts are exact integer counts of minor units.” / “Money moves only between existing wallets.” |
| R005 | Deliver Dockerfile and runnable RUN.md | “Deliver an HTTP service, a `Dockerfile` and a `RUN.md` with a command that builds and starts the service without manual setup.” |
| R006 | Run single container without outbound services or dependencies | “All runtime dependencies, initialization and seed data must work within that single container.” |
| R007 | Serve under 2 CPU/2 GiB, 50 concurrent, 5-second requests and 10-second controls | Resource-limit table; “Test control calls have a 10-second timeout.” |
| R008 | Listen on all interfaces, honor PORT, default 8080 | “Listen on `0.0.0.0` using the `PORT` environment variable, default `8080`.” |
| R009 | Health JSON and status, ready within 60 seconds | “Return 200 once the service and its data store can serve requests, within 60 seconds of container start.” |
| R010 | Reset unauthenticated, enabled, 204, repeated replacement of all state | “When reset returns 204, subsequent requests must see only that fixture.” |
| R011 | JSON UTF-8 response media type | “Requests and responses are `application/json; charset=utf-8`.” |
| R012 | Explicit-offset RFC3339 timestamps | “Timestamps in responses are RFC 3339 with an explicit offset” |
| R013 | Ignore unknown body fields | “Unknown fields in a request body are ignored, never an error.” |
| R014 | Ignore unknown query parameters | “Unknown query parameters are ignored.” |
| R015 | Opaque string IDs no longer than 64 | “IDs are opaque strings of at most 64 characters.” |
| R016 | Accept integral numeric JSON spellings; reject strings/bools as amounts | “JSON `1000`, `1000.0` and `1e3` all represent the same valid minor-unit amount.” / “Booleans and strings are not numbers here.” |
| R017 | Handles unique, immutable, valid character/length rule | “unique across the service, matching `^[a-z0-9_]{1,20}$`, and never changing once set.” |
| R018 | Signup derives lowercase, replacement, truncated email local part | “take the local part, lowercase it, replace every character outside `[a-z0-9_]` with `_`, and truncate to 20 characters.” |
| R019 | New accounts start at zero and immediately receive payments/requests | “New users start with a balance of `0`. They can receive money and be asked for money immediately.” |
| R020 | Request roles and terminal states | “A request is `pending`, and then exactly one of `paid`, `declined` or `cancelled`.” |
| R021 | Over-balance requests remain pending; failed pay unchanged; later money makes payable | “an attempt to pay it while short is `409 insufficient_funds` and changes nothing.” |
| R022 | Payer alone chooses payment visibility | “The payer chooses it when the money moves.” |
| R023 | Feed contains public payments and caller's own private payments exactly | “if and only if its `visibility` is `public`, **or** the caller is its sender or its receiver.” |
| R024 | No requests or splits in payment feed | “Requests never appear in the activity feed” / “A split is not a feed item.” |
| R025 | Requests visible only to their two parties; operator no exception | “returns only requests where the caller is the requester or the payer.” |
| R026 | Single amount maximum 1e9 and exact large balances through ±2^53 | “`amount` is at most `1000000000` on any single request, and no operation produces a balance outside ±2⁵³.” |
| R027 | Seeded users immediately login; seed payments not replayed | “Seeded users must be able to log in with the given password immediately.” / “you do not replay seeded payments against balances.” |
| R028 | Negative fixture rejected atomically | “return `422 validation_failed` from `POST /_test/reset` and change nothing.” |
| R029 | Support EUR/2, JPY/0, BHD/3 | “`minor_units` is `0`, `2` or `3`. Fixtures use `EUR` (2), `JPY` (0) and `BHD` (3).” |
| R030 | All errors have specified status, code and human-readable message | “Every 4xx and 5xx response carries this body” |
| R031 | Malformed JSON and ordinary wrong body types return 400 | “Unparseable body, or a field of the wrong JSON type” |
| R032 | Missing required fields/invalid formats and ranges return 422 | “A required field or query parameter is missing, or a stated rule is violated with no more specific code” |
| R033 | Invalid amount, note (including null), visibility always 422 | “Endpoint-specific field rules take precedence” |
| R034 | Query integers plain decimal only | “`1e9`, `4.0` and `+4` are 422 `validation_failed` whatever their numeric value.” |
| R035 | No request produces 5xx, even concurrent | “Requests must not produce 5xx responses, including under concurrent load.” |
| R036 | Signup 201 and login 200 return identity/display name/token | Signup/login HTTP examples in §6 |
| R037 | Duplicate email 409 email_taken | “Email already registered” |
| R038 | Short password, malformed email rejected at signup | “Password shorter than 8 characters” / “`email` not of the form `local@domain`” |
| R039 | Bad password and unknown email give 401 | “Wrong password or unknown email on login” |
| R040 | Derived-handle collision fails atomically 409 handle_taken | “The handle derived from the email (§4) is already taken” / “and no account is created” |
| R041 | Protected endpoints require well-formed known bearer token | “Missing, malformed or unknown bearer token” |
| R042 | Multiple tokens/sessions valid; tokens do not expire | “Tokens do not expire. An account may have multiple valid tokens and concurrent sessions.” |
| R043 | Password-hashing storage, never plaintext | “Passwords must be stored using a password-hashing function such as bcrypt, scrypt or Argon2, or an equivalent.” |
| R044 | All five write paths require idempotency keys | “Five write paths require an idempotency key” |
| R045 | Key absent/empty 400; length >255 422; 1/255 accepted | “Header absent or empty” / “1 to 255 characters” |
| R046 | Keys independently scoped by caller and method/path | “Two different users may use the same key string with no interaction between them.” / “on a different path is a different request” |
| R047 | First success 201, identical replay 200 exact original JSON body | “Replay: same key, same body” |
| R048 | Different body yields 409 reuse; JSON key order/whitespace irrelevant | “Same body” means the same JSON value after parsing — key order and whitespace do not matter. |
| R049 | Failed request does not consume key | “Key reused after the original request failed with 4xx” / “Treated as a first use” |
| R050 | Concurrent identical unused key commits once: one 201, others 200 | “For concurrent identical requests with an unused key, exactly one returns 201.” |
| R051 | Successful replay unchanged after resource transition | “A successful replay returns the original response, even after the resource changes or is cancelled.” |
| R052 | Claimed key resolution precedes field/current-resource validation | “changing a successful request to an invalid body with the same key still returns `409 idempotency_key_reuse`.” |
| R053 | GET /me returns required identity, wallet and currency fields | §8 `GET /me` response example |
| R054 | Payments debit/credit atomically and failed payments leave no trace | “The debit and the credit are one atomic step.” / “a failed payment leaves no trace in either.” |
| R055 | Payment receipt includes fields, amount, linkage, timestamp | §8 `POST /payments` response example |
| R056 | Payment note/visibility omission defaults | “`note` is optional and defaults to `""`. `visibility` is optional and defaults to `"public"`.” |
| R057 | Payment insufficient funds 409 | “The caller's balance is below `amount`” |
| R058 | Payment amount 1..1e9, integral | “`amount` below 1, above 1000000000, or not an integer” |
| R059 | Self-payment 422 self_payment; unknown recipient 404 | “`to_handle` is the caller's own handle” / “No user has that handle” |
| R060 | Note ≤200 characters; preserve Unicode verbatim | “`note` longer than 200 characters” / “Unicode and emoji survive a round trip byte for byte.” |
| R061 | Request creation returns correct roles, pending state, null payment | §8 `POST /requests` response example |
| R062 | Request validation: amount/note/self/unknown and no balance check | “The payer's balance is not checked here.” and request error table |
| R063 | Only payer may pay, unknown 404, nonpending 409 | Pay endpoint error table |
| R064 | Pay creates ordinary receipt, request links it; visibility defaults public | “The request becomes `paid` and carries the new `payment_id`.” |
| R065 | Pay replay returns original payment, no repeat transfer | “It moves no additional money and must not return `409 request_not_pending`.” |
| R066 | Empty/default visibility bodies distinct for idempotency | “`{}` and `{"visibility": "public"}` are different JSON values” |
| R067 | Decline only payer, repeat decline 200, conflicting terminal states 409 | “Declining an already-declined request is `200` with the current state” |
| R068 | Cancel only requester, repeat cancel 200, conflicting states 409 | “Cancelling an already-cancelled request is `200`.” |
| R069 | Request list newest first | “Newest first by `created_at`.” |
| R070 | Request direction/status filters, invalid filters 422 | “An unknown `direction` or `status` value is also 422.” |
| R071 | Request pagination defaults/ranges/has_more | “`limit` defaults to 50, range 1 to 200. `offset` defaults to 0” / “`has_more` is true when items exist beyond the last one returned.” |
| R072 | Splits create pending requests for all noncaller participants | “A request is created for every participant except the caller” |
| R073 | Split shares/request order matches participant order | “in the same order” |
| R074 | Caller included or omitted accepted | “The caller may be included in `participant_handles` or omitted.” |
| R075 | Split validation amount/empty/duplicates/note/unknown | Split error table in §8 |
| R076 | Caller-only split valid with zero requests | “A split whose only participant is the caller is **valid**” |
| R077 | Splits never check balance | “Nothing about a split checks anyone's balance.” |
| R078 | Whole shares sum amount, differ by ≤1, extras first | “When the amount does not divide evenly, the larger shares go to the first participants” |
| R079 | Zero share creates legal payable request | “A share of `0` is legal and still produces a request for that participant.” |
| R080 | Split rounding independent across repeated/reordered splits | “Each split's shares are independent of previous splits.” |
| R081 | Activity newest-first pagination, defaults/ranges/has_more | “`limit` and `offset` behave exactly as in `GET /requests`.” |
| R082 | Unauthenticated export 200 with correct envelope | “Return 200 from export with a JSON object containing `track: "pocketful"`, `format_version: 1` and `state`” |
| R083 | Unauthenticated import unchanged export across processes, 204 | “No dependency on the source process, files, volume, port or network address is allowed.” |
| R084 | Import atomically replaces and repeats without duplication | “Import is replacement, not merge; repeating it restores the exported state without duplicating anything.” |
| R085 | Invalid import 422 leaves destination unchanged; invalid JSON follows §5 | “missing fields, wrong track/version or an invalid state give 422 `validation_failed` without changing the destination.” |
| R086 | Export atomic read-only independent snapshot | “Export is an atomic, read-only snapshot; subsequent source writes do not change it.” |
| R087 | Import preserves credentials, tokens, currency, exact balances and IDs/timestamps | “Identities, timestamps and monetary records must not be regenerated or replayed against an already-net balance.” |
| R088 | Import preserves completed original idempotency responses and bodies; failed keys reusable | “Preserve ... all completed idempotent request bodies and original responses.” / “Failed request keys remain reusable.” |
| R089 | Import removes destination credentials/data; reset clears imported state | “Import removes all previous destination data and credentials. Reset clears all state, including imported state.” |
| R090 | Operator permission seeded, default none, no-token401/nonoperator403 | “The reset fixture may include `settlement_operator_ids`, an array of user ids, default [].” |
| R091 | Operator permission does not expand private feed/request access | “This permission does not grant access to another user's requests or private activity items.” |
| R092 | Settlement 1..32 objects, malformed batch 422 | “transfers contains 1..32 objects.” / “malformed batch shape is 422 `validation_failed`.” |
| R093 | Entry payment validation/defaults; unknown404/self422 | “Each uses ordinary payment amount, note and visibility rules” |
| R094 | Entry errors input order before funds | “Entry errors take precedence in input order, before insufficient funds.” |
| R095 | Net affordability allows cycles/net-funded transfers | “A settlement is affordable when every wallet's balance after all incoming and outgoing transfers is nonnegative.” |
| R096 | Insufficient net funds 409, atomic no movements/payments/key/revision | “Either all movements commit together or none do” / “creates no payment or revision.” |
| R097 | Settlement receipt ID/timestamp and member order | “Return 201 with `settlement_id`, `committed_at` and `payments` in input order.” |
| R098 | Member linkage, null request, shared time; nonmember null settlement | “Members have null request_id and the same server-assigned created_at, equal to committed_at.” |
| R099 | Members follow ordinary feed visibility; operator sees all in receipt | “The settlement response contains every member's receipt.” |
| R100 | Settlement replay complete, import preserves operators/membership/retries | “A reset/import must preserve settlement operator permissions, original payments, requests, settlement membership and retry responses.” |
| R101 | Build independently from supplied requirements | “Source code, API documentation and schemas from existing products in this domain must not be used.” |

Interpretations to retain: splitting with caller omitted divides among the listed handles (the permission to omit conflicts with the later phrase “including the caller”; no unlisted share is invented). Reset necessarily clears prior runtime records and takes the replacement fixture, so the final settlement sentence means preserving the supplied fixture's records, not retaining old state. Requests generated for a zero share may be paid at zero, despite direct creation requiring at least one. No maximum count of fixture users is stated. No transient-state guarantee or development provenance can be proven solely with black-box observations; mark the proof boundary explicitly.
