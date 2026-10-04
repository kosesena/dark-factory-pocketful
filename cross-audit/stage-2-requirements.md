# Stage 2 atomic requirement ledger

First reviewed revision: `94e856c73f45dbcc44491d5a76d0ce6f2a29b92b`. Stage-1 R001–R101 remain applicable with the explicit total/available changes below. Status and evidence belong in the revision-named report. Quotes refer to the full supplied stage-2 specification; test-id tables are contractual, not optional selectors.

| ID | Atomic obligation | Specification quote |
|---|---|---|
| S001 | All five required screens reachable directly | “The following screens must be reachable by URL” — /, /requests, /split, /signup, /login |
| S002 | Requests content negotiation | “Return the UI for Accept: text/html; API requests without that header receive JSON.” |
| S003 | Coherent consumer-finance visual design | “coherent, presentation-ready consumer finance product” |
| S004 | Available funds visually primary | “Available funds must be the clearest monetary value once holds exist” |
| S005 | Status, direction, privacy and money understandable | “understandable without interpreting raw API data.” |
| S006 | Consistent typography/spacing/controls and identifiable primary actions | “Use a consistent visual system” |
| S007 | Distinguish available/held/pending/loading/success/refused/uncertain | “must be visually distinct” |
| S008 | Human-readable people, amounts and time | “Format people, amounts and timestamps for people first” |
| S009 | Usable 375px and desktop with no horizontal page scroll | “without horizontal page scrolling.” |
| S010 | Visible labels, focus and sufficient contrast | “Inputs need visible labels, keyboard focus must be apparent” |
| S011 | Designed empty/loading/error states and consistent navigation | “Provide considered empty, loading and error states” |
| S012 | Signup selectors and functional signup/error | signup-email, signup-password, signup-display-name, signup-submit; “auth-error ... Present only when there is one” |
| S013 | Login selectors and functional login/error | login-email, login-password, login-submit; auth-error |
| S014 | Identity and logout on signed-in screens | “current-user ... Visible on every screen when signed in” |
| S015 | Current handle exact | “exactly the caller's handle, with no @ and no surrounding words” |
| S016 | Balance text/data exact for all minor-unit currencies | “decimal with exactly minor_units decimal places, a single space, then the currency code” |
| S017 | Required pay form controls/select values/error | pay-handle, pay-amount, pay-note, pay-visibility, pay-submit, pay-error table |
| S018 | Successful pay preserves inputs and unchanged resubmit transfers once | “Submitting it again without changing a field must not send another payment” |
| S019 | Changed pay field creates new request | “Changing a field makes the next submission a new payment request.” |
| S020 | Decimal input converted exactly | “15.00 and 15 both submit 1500; 15.5 submits 1550.” |
| S021 | Invalid/excess-precision decimal rejected locally with error | “without sending a request” / “15.005 is rejected rather than rounded.” |
| S022 | Request form controls, error, successful creation | request-handle, request-amount, request-note, request-submit, request-error |
| S023 | Activity DOM order/visibility attributes | “Its children are newest first in the DOM”; data-visibility |
| S024 | Activity parties/amount/note exactly correct | “Text contains both handles”; “Text is exactly the formatted amount”; “exactly the note ... even when ... empty” |
| S025 | Empty activity instead of list | “Shown instead of the list when nothing is visible” |
| S026 | Request lists/status/formatted amount IDs | incoming-list, outgoing-list, request-item/id data-status, request-amount table |
| S027 | Request pay/decline/cancel buttons only when permitted | “Present only on a pending incoming request” / pending outgoing |
| S028 | Request action error and empty indicator | request-error; “empty-requests ... when both lists are empty” |
| S029 | Split input selectors and decimal validation | split-amount, split-handles, split-note, split-submit, split-error |
| S030 | Pre-submit split preview exact server shares/order | “before anything is posted”; “preview and submitted split must have identical shares.” |
| S031 | Own successful action refreshes state without manual reload | “balance, the feed and the request lists on the same page must show the new state” |
| S032 | Refresh/navigation waits for write success | “Navigation must wait for the write to succeed before it refreshes the data.” |
| S033 | Wallet refresh button preserves form | “refreshes the balance and feed without clearing the pay form.” |
| S034 | Latest refresh wins out of order | “a delayed earlier read must not overwrite a later refresh” |
| S035 | Stale-balance refusal shows pay-error, refreshes, preserves inputs | “A refused payment shows pay-error, refreshes the balance/feed, and preserves all pay inputs.” |
| S036 | Externally cancelled request refusal refreshes stale button away | “show request-error ... refresh the request list so the stale pay button disappears.” |
| S037 | Lost committed payment response shows uncertainty, not rejection | “show pay-uncertain (nonempty text), not pay-error.” |
| S038 | Unchanged retry same key/body, one movement, clears feedback | “same key and body”; “moves money exactly once.” |
| S039 | Refresh ordering also applies available/held | “same balance refresh rules apply to the available and held amounts” |
| S040 | Accept own stage-1 export | “A stage-2 service must accept an export produced by the same team's stage-1 service.” |
| S041 | Upgrade retains browser authentication and payable pending requests | “must remain signed in afterwards”; “Existing pending requests remain payable” |
| S042 | Lost pre-upgrade response retry preserves form/key across import | “No page reload or new screen is required. The form and pending retry identity must survive the upgrade.” |
| S043 | Total conserved, hold moves no money | “sum of all wallet total values always equals the total seeded”; “A hold moves no money” |
| S044 | Available=total-held nonnegative | “available = total − held must never be negative.” |
| S045 | Held money unavailable to payment/request-pay/settlement/new hold | “Held funds cannot fund new payments, authorizations or settlement net debits.” |
| S046 | Captures spend only their reservation, once | “Cumulative captures must not exceed the authorized amount.” |
| S047 | Closed holds cannot be captured | “A closed hold cannot be captured again.” |
| S048 | GET /me balance=total; no holds preserves old behavior | “balance equals total”; “With no open holds ... agree and held is zero” |
| S049 | Direct payments and request payment immediate; splits unchanged | “must not leave an intermediate hold or require a separate capture.” |
| S050 | Seven independent idempotent paths | “stage 1's five, authorizations and captures” |
| S051 | Default TTL600, supplied positive integer | “defaults to 600 when omitted”; “positive integer number of seconds.” |
| S052 | Seed balance total, available derived, omission compatible | “available is derived, never seeded”; “omission means an empty list.” |
| S053 | Overcommitted seeded open holds reject reset atomically | “422 validation_failed ... changing nothing” |
| S054 | Seed open/captured/voided/expired; only open holds | “Only open holds anything.” |
| S055 | Deadline at/before now expired, releases remainder without traffic | “Reads and writes must reflect expiry even if no request occurred at the deadline.” |
| S056 | Authorization response roles, fields, initial amounts and TTL | authorization response example; “expires_at is created_at plus authorization_ttl_seconds” |
| S057 | Authorization validation mirrors payments | Authorization error table (funds409, amount/note/visibility422, self422, unknown404) |
| S058 | Open authorization not feed item | “never appears in GET /activity.” |
| S059 | Capture receiver-only; other party/third-party403; unknown404 | Capture table; “including callers who are neither party.” |
| S060 | Capture default remaining and exact replay body distinction | “amount is optional and defaults to ... remaining”; “{} and {amount:2000} are different JSON values” |
| S061 | Capture receipt ordinary payment with auth link, null request, copied metadata | “note and visibility are copied from the authorisation” |
| S062 | Ordinary payments expose null authorization_id | “Payments created without an authorisation carry authorization_id: null” |
| S063 | Final default capture closes/release unused remainder atomically | “capturing 1500 of 2000 returns 500 ... in the same step.” |
| S064 | Nonfinal capture keeps remainder; full remaining closes even nonfinal | “Capturing the entire remainder closes it even with final:false.” |
| S065 | final boolean default true; wrong types malformed | “final is boolean, default true” and stage1 wrong-type rule |
| S066 | Capture errors: exceeds remaining422, below1/noninteger422 | capture error table |
| S067 | Captured total cumulative, last payment and ordered payment_ids | “payment_id is the latest capture; payment_ids lists every capture in order.” |
| S068 | Remaining amount held only while open, zero when closed | “remaining_amount: the amount still held, zero when closed.” |
| S069 | Partial void/expiry preserves captures and releases only remainder | “preserve all capture records.” |
| S070 | Capture expired409 vs other closed409 | “authorization_expired”; “authorization_not_open” table |
| S071 | Void payer-only, repeat200, captured/expired409 | “Only the payer may void”; “already-voided ... 200” |
| S072 | Authorization list parties only, direction/status/newest/pagination | GET /authorizations section |
| S073 | Expired list filtering reflects clock | “matches expired, never open.” |
| S074 | /authorizations HTML/JSON negotiation and navigation | “serve HTML for Accept: text/html and JSON otherwise” |
| S075 | Total/available/held exact formatted/data; held absent at zero | wallet-balance, wallet-available, wallet-held table |
| S076 | Authorize form selectors/decimal/privacy/errors | authorize-handle/amount/note/visibility/submit/error table |
| S077 | Authorization items/status/amount/captured display | authorization-list/item/amount/captured; “Present only when status is captured” |
| S078 | Authorization expiry text exact RFC3339 | “Text is the RFC 3339 expires_at” |
| S079 | Incoming open capture amount prefilled remainder and capture button | “Present only on an incoming open authorisation” |
| S080 | Outgoing open void button only | “Present only on an outgoing open authorisation” |
| S081 | Authorization error and empty states | authorization-error, empty-authorizations table |
| S082 | Seeded/new holds reflected immediately | “including immediately after reset with open holds.” |
| S083 | Concurrent operations serializable, correct every read | “same results as executing them one at a time in some order” |

No background polling or page-reload recovery is required. Capture expiry error takes precedence for an expired hold even though its current status is closed. Historical authorization/request receipts must retain their original mutable values on replay, not be regenerated from current state. Visual judgments will distinguish observed defects from stylistic preference.
