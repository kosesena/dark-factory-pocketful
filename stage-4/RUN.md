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

- `POST /payments/{id}/refunds` (receiver only): a new payment in the opposite direction with `refund_of`; cumulative
  refunds cannot exceed the payment's current corrected amount; refund payments and captures cannot be corrected or refunded.
- `POST /correction-batches` (settlement operator): up to 32 corrections applied atomically, settlement members only
  together with the whole settlement and one effective instant; all revisions share `recorded_at` and a `correction_batch_id`.
- Exports now carry statement snapshots; imports of stage-1..3 exports derive missing ledger fields.
- Reset and import share one invariant checker (instants at full precision, historical non-negativity, receipts).
