# Pocketful stage 4 — run

Python 3.12 standard library only; the browser UI is static HTML/CSS/JS served by the same process
(no web fonts, no CDN, no network at run time).

```sh
docker build -t pocketful-stage4 .
docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage4
```

- Listens on `0.0.0.0:$PORT` (default 8080); `GET /health` answers immediately.
- UI routes: `/`, `/requests`, `/split`, `/signup`, `/login`, `/authorizations`. `/requests` and
  `/authorizations` are also JSON API paths: HTML is returned only for `Accept: text/html`.
- State is in memory. `POST /_test/reset`, `GET /_test/export` and `POST /_test/import` are enabled and
  unauthenticated; stage-1 exports import cleanly.
- Every handler runs under one lock, so balances, holds and idempotent writes are serialized.
  Authorization expiry is evaluated against the clock on every request (no timers).
- Passwords are salted scrypt hashes.

Own tests (from this folder): `python3 -m unittest tests.test_service`.
Browser check (Playwright, kickoff venv): `python tests/ui_check.py [screenshot-dir]`.

## Stage 3 additions

- Ledger: every payment has a revision history (revision 1 = original receipt). `POST /payments/{id}/corrections`
  appends an immutable revision; `GET /payments/{id}/revisions` reads them. `GET /me` and `GET /statement`
  accept `as_of`, `known_at` (effective vs recorded time); statements return a `snapshot` token for stable paging.
- Payment ids sort in creation order (`p_~` + counter) so same-second payments keep their order in statements.
- Exports of stage-1 and stage-2 services import: revision 1, opening balances and hold closing times are derived.

## Stage 4 additions

- `POST /payments/{id}/refunds` (original receiver only, idempotent): a new payment in the opposite direction with
  `refund_of`, funded from the receiver's available money. Direct payments, request payments, captures and
  settlement members can be refunded; a refund itself cannot (`invalid_refund_target`). Cumulative refunds cannot
  exceed the payment's current corrected amount (`refund_exceeds_payment`). Refunds never reopen a request or an
  authorization.
- Refund payments and captures cannot be corrected (`linked_payment_immutable`); a correction cannot go below the
  refunded amount. Settlement members are corrected only through a batch.
- `POST /correction-batches` (settlement operator, idempotent): 1..32 corrections applied atomically. Captures and
  refunds are immutable; a settlement member can be corrected only together with every member of its settlement and
  with one effective instant (`incomplete_settlement`). All revisions of a batch share `recorded_at` and a
  `correction_batch_id`. Error precedence: items in input order, settlement completeness, current available funds,
  then historical total/available at every boundary.
- Exports carry statement snapshots (frozen original form); imports of stage 1-3 exports derive missing ledger fields.
- Reset and import share one invariant checker: instants at full precision, historical non-negativity, snapshot
  rebuild from the ledger and idempotency receipts (including batch receipts) checked against the records.

### Importing exports from older stages (snapshots)

- A statement snapshot with no `taken_ts`/`taken_seq` (an export of an older stage) is accepted only if its whole
  page (opening, entries, closing, echoed query) equals the full rebuild at some recorded moment of the imported
  ledger. The search covers every moment back to the snapshot's own latest recorded instant, with no cap; a snapshot
  matching no moment is refused with 422 and the destination is unchanged.
- A recorded instant is only a reconstruction device, not proof that a read happened there. The check is that owner,
  window, known_at selection, balances and ledger cutoff all agree with a possible read at such a moment.
- This admits two classes of alternative valid earlier states (never equivalent to the original, non-empty page), which cannot be told from a genuine page: "the
  last-created fact dropped, closing adjusted" and "cleared entries equal to the empty-ledger statement". Every other
  change (shifted or reordered balances, duplicated entries, another user, malformed fields) is refused.
- A snapshot without `view` predates refunds and is refused if any entry is a refund.
- Current-format snapshots (with `taken_ts`, `taken_seq`, `view`) are checked against their explicit frozen metadata.
