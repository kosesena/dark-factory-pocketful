# Pocketful stage 1 — run

Python 3.12 standard library only; no third-party dependencies, no network at run time.

```sh
docker build -t pocketful-stage1 .
docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage1
```

- Listens on `0.0.0.0:$PORT` (default 8080); `GET /health` answers immediately.
- State is in memory. `POST /_test/reset`, `GET /_test/export` and `POST /_test/import` are
  enabled and unauthenticated.
- Money-moving handlers run under one process-wide lock, so balances never go negative and
  idempotent writes take effect exactly once under concurrency.
- Passwords are stored as salted scrypt hashes.

Own tests (run from this folder, no container needed): `python3 -m unittest tests.test_service`
