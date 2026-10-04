# Stage 3 independent atomic requirements

Inherited R001–R101 and S001–S083 continue except where explicitly extended. Each item below is a separate testable obligation; status/evidence will be recorded in the revision verdict. Quotes are from the supplied stage-3 specification.

| ID | Atomic obligation and specification quote |
|---|---|
| T001 | All payment endpoints expose original movement timestamp: “Every endpoint returning a payment includes it.” |
| T002 | Activity order unchanged: “GET /activity retains its existing ordering by this field.” |
| T003 | Seed supplied timestamp honored: “Seeded payments may supply created_at”. |
| T004 | Omitted timestamp is reset time preceding API writes: “omission uses reset time, before subsequent API-created payments.” |
| T005 | Future seed rejected atomically: “A seeded created_at in the future gives 422 validation_failed ... with no state change.” |
| T006 | No seed replay: “Loading those payments must not change that balance.” |
| T007 | as_of accepts offset RFC3339 only: “Anything else — a naive local time, a bare date, an empty value — is 422 validation_failed.” |
| T008 | Current default corrected values: “Without temporal query parameters ... reports current corrected values.” |
| T009 | as_of inclusive: “A payment made at exactly as_of counts as having happened.” |
| T010 | After latest/current and before earliest/opening: “An as_of at or after the latest payment returns the current balance.” / “An as_of before the earliest payment returns the opening balance”. |
| T011 | Exact echo: “The response carries as_of back, exactly as given.” |
| T012 | Statement defaults: “from defaults to the opening of the wallet and to to now.” |
| T013 | Statement pagination ranges: “limit and offset behave exactly as in GET /requests.” |
| T014 | Half-open selection: “in the half-open window [from, to)”. |
| T015 | Entry tie ordering: “created_at ascending, then payment id ascending for ties.” |
| T016 | Window endpoint balances: “opening_balance is the balance immediately before from. closing_balance is ... immediately before to.” |
| T017 | Conservation and signs: “opening_balance plus all delta values in the full window must equal closing_balance” / “sent ... negative ... received ... positive”. |
| T018 | Pagination independent balances: “Pagination must not change an entry's balance_after or the window's opening and closing balances.” |
| T019 | Statement party-only: “Only payments sent or received by the caller appear ... including when other payments are public.” |
| T020 | Original revision: “Revision 1 has amount as originally paid and effective_at = recorded_at = created_at.” |
| T021 | Seed original revision times: “A seeded payment's supplied created_at is also its original recorded/effective time”. |
| T022 | Fixed opening balances: “Opening balances equal seeded ending balances minus the net effect of original seeded payments. Corrections must not change those opening balances.” |
| T023 | New account opening: “New accounts open at zero.” |
| T024 | Correction key required: “POST /payments/{payment_id}/corrections requires an idempotency key”. |
| T025 | Correction sender/unknown authorization: “An authenticated non-sender gets 403 forbidden; unknown payment gets 404.” |
| T026 | All correction fields required: “All fields are required.” |
| T027 | Revision numeric rule: “Revision is a positive integer”. |
| T028 | Correction amount rule: “amount is an integer 0..1000000000 (zero reverses the entire payment)”. |
| T029 | Reason validation: “reason is a string of 1..200 characters”. |
| T030 | Effective date validation: “effective time is an RFC 3339 instant not later than now. Invalid input is 422 validation_failed.” |
| T031 | Parties/privacy immutable: “Correction changes neither parties nor visibility.” |
| T032 | Correction receipt: “returning 201 with payment_id, revision, amount, effective_at, server-assigned recorded_at, and reason.” |
| T033 | Increasing recorded timestamps: “Recorded times for one payment strictly increase.” |
| T034 | Optimistic conflict: “A stale expected revision gives 409 stale_revision.” |
| T035 | Original correction replay: “Successful replay returns that original revision with 200 even after newer revisions.” |
| T036 | Different body conflicts: “Different body with the same key is 409 idempotency_key_reuse.” |
| T037 | Difference transferred atomically: “The difference from the previous amount moves between the same two wallets in the same atomic step.” |
| T038 | Direction of correction: “Increasing ... debits the original sender; decreasing ... debits the original receiver.” |
| T039 | Current unaffordability precedence: “A currently unaffordable debit gives 409 insufficient_funds. Otherwise ... historical_overdraft.” |
| T040 | Historical nonnegative invariant: “if any user's corrected balance is negative at any effective-time boundary, return 409 historical_overdraft.” |
| T041 | Simultaneous movements aggregate: “Balances at a boundary include the combined effect of all movements at that instant.” |
| T042 | Failed correction atomicity/key reuse: “Either failure preserves balances, revision history, statements and idempotency state.” |
| T043 | Historical conservation: “The sum of balances must equal the seeded total in every historical view.” |
| T044 | Original receipts immutable: “The original payment and every original idempotent response remain unchanged.” |
| T045 | No correction feed item: “GET /activity continues to display the original payment; correction records are not new feed payments.” |
| T046 | Revisions ordered, original reason empty: “returns ... in revision order, including revision 1 (reason: \"\").” |
| T047 | Revision privacy and auth: “Only the two parties can read it; a third party gets 404 even for a public payment. No token is 401.” |
| T048 | recorded-time selection inclusive: “select its latest revision recorded at or before known_at; if none was yet recorded, that payment contributes nothing.” |
| T049 | Read-start knowledge default: “Omission means everything known when the read begins.” |
| T050 | Selected effective time: “Then apply selected revisions according to their effective times.” |
| T051 | Future temporal reads legal: “Both query instants may be in the future.” |
| T052 | Invalid known_at rejected/exact echo: “Invalid/empty instants are 422. Echo supplied known_at exactly.” |
| T053 | Statement effective order: “Statement ordering is now by selected effective_at, then payment id.” |
| T054 | Statement revision metadata and amount: “adds the selected revision, effective_at and recorded_at. payment.amount is the selected amount for this statement.” |
| T055 | Zero correction entry retained: “Zero-amount revisions still appear as entries with zero delta.” |
| T056 | Replacement not accumulation: “No correction is counted alongside the revision it replaces.” |
| T057 | No-correction compatibility: “With no corrections and no known_at, previous behavior is unchanged.” |
| T058 | First statement snapshot: “Every first GET /statement response additionally returns an opaque snapshot token.” |
| T059 | Frozen result/window/default-to: “It freezes the caller's selected revisions, window, balances, entries and default to at that read.” |
| T060 | Frozen pages after writes: “pages that exact result, even after payments or corrections.” |
| T061 | Snapshot query exclusion: “supplying from, to or known_at with it gives 422 validation_failed.” |
| T062 | Snapshot ownership/reset: “Unknown token, another user's token, or a token from before reset gives 404 not_found.” |
| T063 | Token lifetime: “Tokens last until reset.” |
| T064 | Snapshot last/beyond pages: “the final partial page and offsets beyond the end must report has_more correctly.” |
| T065 | Unknown query ignored: “Unrecognized query parameters remain ignored”. |
| T066 | Window migration: “A correction may move a payment into or out of a statement window.” |
| T067 | Concurrent frozen view: “Existing snapshots remain unchanged during concurrent payments or corrections.” |
| T068 | Concurrent expected revision: “Concurrent corrections using the same expected revision cannot both succeed.” |
| T069 | Settlement original history/privacy: “Each member's original revision uses its shared committed_at as both effective_at and recorded_at.” |
| T070 | Settlement correction forbidden: “Single-payment corrections reject settlement members with 422 linked_payment_immutable.” |
| T071 | Both older exports accepted: “A stage-3 service must accept exports produced by the same team's stage-1 or stage-2 service.” |
| T072 | Captures and holds migrate: “The ledger must import and account for authorizations and captures.” |
| T073 | Capture correction forbidden: “a correction of a capture gives 422 linked_payment_immutable.” |
| T074 | Historical money fields consistent: “all four money fields describe that same view: balance = total, available = total - held.” |
| T075 | Hold creation and partial reduction: “A hold starts at authorization creation; nonfinal capture reduces it at capture time”. |
| T076 | Final/void/expiry release: “final capture, void or expiry releases the remainder at that event's time. Expiry takes effect at expires_at.” |
| T077 | Hold knowledge timing: “Events other than clock expiry are known at their server-assigned event time.” |
| T078 | Future expiry known: “Once creation is known, the expiry deadline is known too. For queries beyond now, an open hold expires at its deadline.” |
| T079 | No-as_of uses read start: “Without as_of, use the instant the request began.” |
| T080 | Authorization close time: “Authorizations expose closed_at (null while open; event time when closed).” |
| T081 | Historical held-funds protection: “rejected with 409 historical_overdraft if it makes either total or available negative at any past effective/event boundary, under the latest known revisions.” |
| T082 | Current funds precedence with holds: “Current unaffordable debits still take precedence as insufficient_funds.” |
| T083 | Seed creation semantics: “Seeded open holds are assumed created at reset unless created_at is supplied; seeded closed holds need not reconstruct a prior lifecycle.” |
| T084 | Statement movements only: “authorization, release and expiry are not payments. Captures appear exactly once with their links.” |
| T085 | Lifecycle cannot mutate snapshot: “Old snapshots remain unchanged after any lifecycle action or correction.” |

Interpretation: amount/revision integral numeric encodings follow inherited exact-number conventions. Statement reversed windows are invalid under general stated-rule validation. Seeded closed holds may omit reconstructed lifecycle; no invented history is required. Universal infinite token lifetime and inaccessible transient states remain finite-test proof boundaries.
