# Pocketful stage 2 — run

Python 3.12 standard library only; the browser UI is static HTML/CSS/JS served by the same process
(no web fonts, no CDN, no network at run time).

```sh
docker build -t pocketful-stage2 .
docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage2
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
