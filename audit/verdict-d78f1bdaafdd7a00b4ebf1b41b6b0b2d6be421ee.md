# spec-auditor verdict — stage 2, revision d78f1bdaafdd7a00b4ebf1b41b6b0b2d6be421ee

**ACCEPT d78f1bd.** No open gap cites a spec sentence (stage 2, and stage 1 run against stage 2).

## Method
- Judged from `git archive d78f1bd stage-1 stage-2` (`audit/mutants/_src-d78f1bd`). Its stage-1 equals 999fda2 (ACCEPTed).
- Shipped checks on that build, with stage-1 as the previous build, pass stages 1 and 2 in host and isolated modes
  (`checks/spec-auditor-d78f1bd-host`, `-isolated`).
- Docker containers (2 CPU, 2 GiB), with a stage-1 container from the same archive for the upgrade checks:
  - stage-1 probes against stage 2: **39/39**
  - stage-2 API probes (`audit/probes/stage2_probes.py`): **15/15**
  - stage-2 browser probes (`audit/probes/stage2_ui_probes.py`, Playwright/Chromium): **11/11**
- Read `authorizations.py`, the expiry sweep, content negotiation and the client's retry and refresh logic.

## Gap walk (ledger/stage-2.md; every gap met)
| Gap | Evidence |
|---|---|
| 1 S2-49/50 available-based funds | Hold 8000 of 10000. Payment, request pay, authorisation and settlement of 2001 each → 409; payment of 2000 → 201. Receiver then captures all 8000 with available 0 → 201. |
| 2 S2-61/62/74 clock expiry | ttl 2 s, sleep 3 s, no other request. /me releases the hold; status=open is empty, status=expired lists it; capture → 409 authorization_expired; void → 409 not_open. A capture just after the deadline moves nothing. |
| 3 S2-80 linearizability | 20 concurrent final:false captures of 100 on a 1000 hold → exactly 10 succeed, held 0. Capture racing void → exactly one wins. 50 parallel authorisations of 30 on 1000 → 33 succeed, held 990, available 10. |
| 4 S2-71/75/77 extended capture | 700 final:false → open/700/1300, payment_ids [p1]. Capturing the remaining 1300 closes it. Partial capture then void releases only the remainder and keeps the capture record. "final":"false" → 400. |
| 5 S2-68/69/72/73 final capture | 1500 of 2000 → available +500 in the same step. Second capture → 409 not_open. 2001 → 422 capture_exceeds. 0, 1.5, -1, true, "100", null → 422. |
| 6 S2-70/54/79 idempotency | `{}` then `{"amount":2000}` with one key → 409 reuse. A replay after later captures returns the original body. 20 concurrent same-key authorisations → 1×201, 19×200 with an identical body, one hold. |
| 7 S2-65/76 permissions | Payer capturing, receiver voiding, third party doing either → 403. Unknown id → 404. No token → 401. |
| 8 S2-66/67/26 payment shape | authorization_id null on direct, request-pay, settlement and seeded payments. A capture carries authorization_id, request_id null, copied note and visibility. A private capture is hidden from third parties. Open holds never appear in the feed. |
| 9 S2-55/57/58/59 seeding | Seeded open/captured/voided/expired holds give available 8000. Holds over the balance (one or summed) → 422 with state unchanged; expired or captured seeded holds don't count. ttl 0, -1, 1.5, "600", true → 422. ttl 37 and the 600 default are exact. |
| 10 S2-40 lost response | Response aborted after commit → pay-uncertain (non-empty text), no pay-error. Retry uses the same key and body (checked on the wire); money moves once and both elements clear. |
| 11 S2-37 latest refresh wins | The first refresh's /me and /activity are held and delivered after a later refresh. The display keeps the later balance (total and available). |
| 12 S2-38/39 refusal refresh | Wallet drained elsewhere → pay-error, balance refreshed, all four inputs kept. Request cancelled elsewhere → request-error, status cancelled, pay button gone, no money moved. |
| 13 S2-42–46 upgrade | Stage-1 export → stage-2 import: tokens, replays, settlements and pending requests work; /me total=available=balance, held 0; authorization_id null; new holds get ttl 600. In the browser, no reload: a payment lost before the export, retried after the import, replays (same key) and refreshes; the session survives; a stage-1 token keeps the browser signed in. |
| 14 S2-2 negotiation | /requests and /authorizations: no Accept, `*/*` or application/json → JSON; a browser Accept → HTML. Other routes serve HTML. |
| 15 S2-17/34/84 decimal input | pay, request, authorize and split forms: `abc`, `-5`, `1e3`, `15,00`, empty, spaces, `1.2.3`, `0`, `0.00`, `10.005` → form error with no POST on the wire. JPY `15.5` → error. BHD `1.234` → 1234 and `2` → 2000. |
| 16 S2-83/85-88 authorisation UI | wallet-available is the headline (larger font than total and held) and shows right after reset with seeded holds; wallet-held carries data-amount and is absent at 0. List shows every hold with data-status; captured element only on captured; expires text equals the API value; capture input pre-filled `3.00`; buttons only where allowed; stale capture → authorization-error; UI capture and void work; empty-authorizations shown. |
| 17 S2-15 formatting | `0.05 EUR`, `0.005 BHD`, `1200 JPY`, `90071992547409.91 EUR`, `0.00 EUR`. |
| 18 S2-28/29/31/21 request UI | Buttons absent on non-pending items. A double click pays once. Refused decline → request-error. Request form shows request-error for self and unknown handles. |
| 19 S2-10/11/14 auth UI | current-user and exact current-handle on every route. auth-error only after an error. email_taken, handle_taken, short password and bad email each show auth-error. Logout works. |
| 20 S2-3/4 quality | No horizontal scroll at 375 and 1280 px on all six routes, including 20-character handles, 200-character notes and 13-digit amounts. Every input has a label. pay-amount shows a focus ring. Visual and state distinctness is left to the customer seat. |
| 21 S2-81 export/import | Holds, ttl 900, capture records and replays on both new paths survive a repeated import. |
| 22 S2-56 expires_at | created_at + ttl exactly, for 2, 37, 600 and 900 s. |

Readings confirmed: B1 (expired → authorization_expired; void → not_open); B2 (seeded captured shows captured_amount = amount);
B3 (partial capture then expiry → expired, capture kept, remainder released); B4 (`final` of wrong type → 400); B7 (ttl 600 after a stage-1 import).

## Fault seeding (`ledger/stage-2-faults.md`, `audit/seed-results-stage-2-d78f1bd.json`)
16 seeded (G01–G16), **16 caught**. The unmodified copy G00 fails nothing in any evidence.

## Suggested test (non-blocking)
- G12: removing the "latest refresh wins" guard (`if (my !== seq) return;`) is caught only by the auditor's browser probe.
  Add a UI test that holds the first refresh's /me and /activity responses and delivers them after a second refresh.
- The shipped stage-2 checks alone catch 1 of 16 faults. Everything else rests on the band's own evidence.
