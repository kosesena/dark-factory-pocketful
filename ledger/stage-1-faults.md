# Stage 1 seeded faults — spec-auditor

Revision 69289b3 (`git archive` copy in `audit/mutants/_src-69289b3`, git-ignored, never committed).
One fault per mutant; evidence = implementer tests (`stage-1/tests`), shipped checks (`harness run --base-url`),
customer journey (`customer/journey_stage1.py`, scored against its 2-check baseline failure), reviewer
model check (`verification/model_check.py --seeds 8`), auditor probes (`audit/probes/stage1_probes.py`).
Runner: `python3 audit/seed_faults.py`. F00 is the unmodified copy (control).

| id | requirement broken | file | change | caught by |
|---|---|---|---|---|
| F00 | baseline: unmodified copy (must be caught by nothing) | common.py | none | — |
| F01 | R55 key scoped by path | common.py | `ik = (user["id"], key, req.path)` → `ik = (user["id"], key, req.path.split("/")[1])` | impl, auditor |
| F02 | R56 replay returns 200 | common.py | `            return 200, rec[1]` → `            return 201, rec[1]` | impl, shipped, customer, reviewer, auditor |
| F03 | R59 body equality ignores key order | common.py | `json.dumps(_norm(body), sort_keys=True,` → `json.dumps(_norm(body), sort_keys=False,` | impl, auditor |
| F04 | R3/R74 paid request cannot be paid again | wallet.py | `if r["status"] != "pending":⏎            raise ApiError(409` → `if r["status"] in ("declined", "cancelled"):⏎            raise ApiError(409` | impl, customer, reviewer, auditor |
| F05 | R118/R119 settlement net affordability, all-or-nothing | settlements.py | `check_funds=False)` → `check_funds=True)` | impl, customer, auditor |
| F06 | R121 settlement payments in input order | settlements.py | `"payments": [pay_view(s, p) for p in payments]}` → `"payments": [pay_view(s, p) for p in reversed(payments)]}` | impl, customer, reviewer, auditor |
| F07 | R122 nonmembers expose settlement_id null | wallet.py | `"request_id": p["request_id"], "settlement_id": p["settlement_id"],` → `"request_id": p["request_id"], **({"settlement_id": p["settlement_id"]} if p["settlement_id"] else {}),` | impl, customer, auditor |
| F08 | R116 self-transfer in settlement is 422 self_payment | settlements.py | `    if frm is to:` → `    if False:` | impl, customer, auditor |
| F09 | R112 non-operator gets 403 | settlements.py | `if user["id"] not in s.operators:` → `if not s.operators:` | impl, customer, reviewer, auditor |
| F10 | R101 import preserves idempotency records | snapshot.py | `        s.idem[(u, k, p)] = (fp, resp)` → `        pass` | impl, customer, reviewer, auditor |
| F11 | R99 import preserves bearer tokens | snapshot.py | `        s.tokens[t] = uid` → `        pass` | impl, shipped, reviewer, auditor |
| F12 | R42 query integers are plain digits | common.py | `DIGITS_RE = re.compile(r"[0-9]+", re.ASCII)` → `DIGITS_RE = re.compile(r"[+]?[0-9]+", re.ASCII)` | impl, auditor |
| F13 | R17 booleans are not amounts | common.py | `if isinstance(v, bool) or not isinstance(v, (int, float)):` → `if not isinstance(v, (int, float)):` | impl, customer, reviewer, auditor |
| F14 | R78 decline of a cancelled request is 409 | wallet.py | `elif r["status"] != status:` → `elif r["status"] == "paid":` | impl, customer, reviewer, auditor |
| F15 | R40 malformed bearer scheme is 401 | common.py | `if len(parts) != 2 or parts[0].lower() != "bearer":` → `if len(parts) != 2:` | auditor |

Result: 15 seeded, 15 caught. F15 is caught only by the auditor probe (added in this walk) → suggested test for the implementer.
Shipped checks alone catch 2 of 15 (F02, F11).

## Revision 145b98e (fix walk)

Source: `git archive 145b98e stage-1`. F01–F15 rerun (F13 anchor updated to the Decimal code), F16–F24 seeded in the code the fix changed.
The auditor column is scored beyond its own 2 baseline failures (G1/G2), which fail on the unmodified copy.

| id | requirement broken | file | change | caught by |
|---|---|---|---|---|
| F00 | baseline: unmodified copy (must be caught by nothing) | common.py | none | — |
| F01 | R55 key scoped by path | common.py | `ik = (user["id"], key, req.path)` → `ik = (user["id"], key, req.path.split("/")[1])` | impl, auditor |
| F02 | R56 replay returns 200 | common.py | `            return 200, rec[1]` → `            return 201, rec[1]` | impl, shipped, customer, reviewer, auditor |
| F03 | R59 body equality ignores key order | common.py | `json.dumps(_norm(body), sort_keys=True,` → `json.dumps(_norm(body), sort_keys=False,` | impl, auditor |
| F04 | R3/R74 paid request cannot be paid again | wallet.py | `if r["status"] != "pending":⏎            raise ApiError(409` → `if r["status"] in ("declined", "cancelled"):⏎            raise ApiError(409` | impl, customer, reviewer, auditor |
| F05 | R118/R119 settlement net affordability, all-or-nothing | settlements.py | `check_funds=False)` → `check_funds=True)` | impl, customer, auditor |
| F06 | R121 settlement payments in input order | settlements.py | `"payments": [pay_view(s, p) for p in payments]}` → `"payments": [pay_view(s, p) for p in reversed(payments)]}` | impl, customer, reviewer, auditor |
| F07 | R122 nonmembers expose settlement_id null | wallet.py | `"request_id": p["request_id"], "settlement_id": p["settlement_id"],` → `"request_id": p["request_id"], **({"settlement_id": p["settlement_id"]} if p["settlement_id"] else {}),` | impl, customer, auditor |
| F08 | R116 self-transfer in settlement is 422 self_payment | settlements.py | `    if frm is to:` → `    if False:` | impl, customer, auditor |
| F09 | R112 non-operator gets 403 | settlements.py | `if user["id"] not in s.operators:` → `if not s.operators:` | impl, customer, reviewer, auditor |
| F10 | R101 import preserves idempotency records | snapshot.py | `        s.idem[(u, k, p)] = (fp, resp)` → `        pass` | impl, customer, reviewer, auditor |
| F11 | R99 import preserves bearer tokens | snapshot.py | `        s.tokens[t] = uid` → `        pass` | impl, shipped, reviewer, auditor |
| F12 | R42 query integers are plain digits | common.py | `DIGITS_RE = re.compile(r"[0-9]+", re.ASCII)` → `DIGITS_RE = re.compile(r"[+]?[0-9]+", re.ASCII)` | impl, auditor |
| F13 | R17 booleans are not amounts | common.py | `if isinstance(v, bool) or not isinstance(v, (int, Decimal)):` → `if not isinstance(v, (int, Decimal)):` | impl, customer, reviewer, auditor |
| F14 | R78 decline of a cancelled request is 409 | wallet.py | `elif r["status"] != status:` → `elif r["status"] == "paid":` | impl, customer, reviewer, auditor |
| F15 | R40 malformed bearer scheme is 401 | common.py | `if len(parts) != 2 or parts[0].lower() != "bearer":` → `if len(parts) != 2:` | impl, auditor |
| F16 | R16/R73 fractional amounts are 422, never rounded | common.py | `        if v != v.to_integral_value():⏎            raise validation` → `        if False:⏎            raise validation` | impl, shipped, customer, reviewer |
| F17 | R16 exact parse: 1.0000000000000001 is not an integer | common.py | `parse_float=Decimal if decimal else float,` → `parse_float=(lambda s: Decimal(float(s))) if decimal else float,` | impl, customer |
| F18 | R44/R73 huge integer amounts are 422, not 400/5xx | common.py | `return int(text) if len(text) <= 18 else Decimal(text)` → `return int(text)` | impl |
| F19 | R42 huge offset is valid (empty page), huge limit 422 | common.py | `n = int(v) if len(v) <= 18 else 10 ** 18` → `n = int(v) if len(v) <= 18 else 0` | customer |
| F20 | R105 import rejects an invalid timestamp | snapshot.py | `    _need(_str(v) and RFC3339.fullmatch(v))⏎    parse_ts(v)` → `    return` | impl, auditor |
| F21 | R105 import rejects dangling payment->request references | snapshot.py | `_need(p["request_id"] is None or p["request_id"] in s.requests_by_id)` → `pass` | impl |
| F22 | R105 import rejects a negative/fractional balance | snapshot.py | `_need(_id(rec["id"]) and 0 <= rec["balance"] <= 2 ** 53 and _int(rec["balance"]))` → `_need(_id(rec["id"]))` | impl, customer, auditor |
| F23 | R31 seeded users log in (per-record KDF cost honoured) | common.py | `user.get("n", 2 ** 12))` → `2 ** 12)` | impl, shipped, customer, reviewer, auditor |
| F24 | R59/A2 1000 and 1000.0 are the same body | common.py | `return int(v) if v == v.to_integral_value() and abs(v) < 10 ** 30 else str(v)` → `return str(v)` | impl, customer |

Result: 24 seeded, 24 caught. No surviving fault.

## Revision 0e8dea4 (final fix walk)

Source: `git archive 0e8dea4 stage-1`. F01–F24 rerun (F03, F13, F16, F17, F24 anchors moved to the rewritten code), F25–F30 seeded in the code the fix changed.
Customer and auditor columns are scored beyond what each already fails on the unmodified copy (customer: "reset operator unknown 422").

| id | requirement broken | file | change | caught by |
|---|---|---|---|---|
| F00 | baseline: unmodified copy (must be caught by nothing) | common.py | none | — |
| F01 | R55 key scoped by path | common.py | `ik = (user["id"], key, req.path)` → `ik = (user["id"], key, req.path.split("/")[1])` | impl, shipped, reviewer, customer, auditor |
| F02 | R56 replay returns 200 | common.py | `            return 200, rec[1]` → `            return 201, rec[1]` | impl, shipped, reviewer, customer, auditor |
| F03 | R59 body equality ignores key order | common.py | `for k, x in sorted(v.items())) + "}"` → `for k, x in v.items()) + "}"` | impl, customer, auditor |
| F04 | R3/R74 paid request cannot be paid again | wallet.py | `if r["status"] != "pending":⏎            raise ApiError(409` → `if r["status"] in ("declined", "cancelled"):⏎            raise ApiError(409` | impl, reviewer, customer, auditor |
| F05 | R118/R119 settlement net affordability, all-or-nothing | settlements.py | `check_funds=False)` → `check_funds=True)` | impl, customer, auditor |
| F06 | R121 settlement payments in input order | settlements.py | `"payments": [pay_view(s, p) for p in payments]}` → `"payments": [pay_view(s, p) for p in reversed(payments)]}` | impl, reviewer, customer, auditor |
| F07 | R122 nonmembers expose settlement_id null | wallet.py | `"request_id": p["request_id"], "settlement_id": p["settlement_id"],` → `"request_id": p["request_id"], **({"settlement_id": p["settlement_id"]} if p["settlement_id"] else {}),` | impl, customer, auditor |
| F08 | R116 self-transfer in settlement is 422 self_payment | settlements.py | `    if frm is to:` → `    if False:` | impl, customer, auditor |
| F09 | R112 non-operator gets 403 | settlements.py | `if user["id"] not in s.operators:` → `if not s.operators:` | impl, reviewer, customer, auditor |
| F10 | R101 import preserves idempotency records | snapshot.py | `        s.idem[(u, k, p)] = (fp, resp)` → `        pass` | impl, reviewer, customer, auditor |
| F11 | R99 import preserves bearer tokens | snapshot.py | `        s.tokens[t] = uid` → `        pass` | impl, shipped, reviewer, auditor |
| F12 | R42 query integers are plain digits | common.py | `DIGITS_RE = re.compile(r"[0-9]+", re.ASCII)` → `DIGITS_RE = re.compile(r"[+]?[0-9]+", re.ASCII)` | impl, auditor |
| F13 | R17 booleans are not amounts | common.py | `if isinstance(v, bool) or not isinstance(v, (int, Decimal)):` → `if not isinstance(v, (int, Decimal)):` | impl, reviewer, customer, auditor |
| F14 | R78 decline of a cancelled request is 409 | wallet.py | `elif r["status"] != status:` → `elif r["status"] == "paid":` | impl, reviewer, customer, auditor |
| F15 | R40 malformed bearer scheme is 401 | common.py | `if len(parts) != 2 or parts[0].lower() != "bearer":` → `if len(parts) != 2:` | impl, auditor |
| F16 | R16/R73 fractional amounts are 422, never rounded | common.py | `        if v is None:⏎            raise validation(field + " must be an integer")` → `        if v is None:⏎            v = 1` | impl, shipped, reviewer, customer, auditor |
| F17 | R16 exact parse: 1.0000000000000001 is not an integer | common.py | `parse_float=_parse_float if decimal else float,` → `parse_float=(lambda s: _parse_float(repr(float(s)))) if decimal else float,` | impl, customer, auditor |
| F18 | R44/R73 huge integer amounts are 422, not 400/5xx | common.py | `return int(text) if len(text) <= 18 else Decimal(text)` → `return int(text)` | impl, customer, auditor |
| F19 | R42 huge offset is valid (empty page), huge limit 422 | common.py | `n = int(v) if len(v) <= 18 else 10 ** 18` → `n = int(v) if len(v) <= 18 else 0` | impl, customer |
| F20 | R105 import rejects an invalid timestamp | snapshot.py | `    _need(_str(v) and RFC3339.fullmatch(v))⏎    parse_ts(v)` → `    return` | auditor * |
| F21 | R105 import rejects dangling payment->request references | snapshot.py | `_need(p["request_id"] is None or p["request_id"] in s.requests_by_id)` → `pass` | auditor * |
| F22 | R105 import rejects a negative/fractional balance | snapshot.py | `_need(_id(rec["id"]) and 0 <= rec["balance"] <= 2 ** 53 and _int(rec["balance"]))` → `_need(_id(rec["id"]))` | impl, customer, auditor |
| F23 | R31 seeded users log in (per-record KDF cost honoured) | common.py | `user.get("n", 2 ** 12))` → `2 ** 12)` | impl, shipped, reviewer, customer, auditor |
| F24 | R59/A2 1000 and 1000.0 are the same body | common.py | `    if isinstance(v, int):⏎        return _num(Decimal(v))` → `    if isinstance(v, int):⏎        return str(v)` | impl, customer, auditor |
| F25 | R16/R73 1.5 is not an integer amount (as_tuple integrality) | common.py | `if len(digits) <= k or any(digits[-k:]):` → `if len(digits) <= k:` | impl, shipped, reviewer, customer, auditor |
| F26 | R59 1.5 and 1.50 are the same JSON value | common.py | `    while digits[-1] == 0:⏎        digits.pop()⏎        exp += 1` → `    pass` | impl, customer, auditor |
| F27 | R59 a string never equals a literal ("true" vs true, "null" vs null) | common.py | `    if isinstance(v, str):⏎        return json.dumps(v)` → `    if isinstance(v, str):⏎        return v` | auditor * |
| F28 | R105/§10 reset rejects dangling references (export must re-import) | accounts.py | `raise validation("request refers to an unknown payment")` → `pass` | impl |
| F29 | R30/§10 reset rejects balance above 2^53 (export must re-import) | accounts.py | `bal = _int(u.get("balance", 0), 0, 2 ** 53)` → `bal = _int(u.get("balance", 0), 0)` | impl |
| F30 | R105 import rejects a receipt that disagrees with its record | snapshot.py | `and resp["amount"] == r["amount"] and resp["currency"] == s.currency` → `and resp["currency"] == s.currency` | impl |

\* F20, F21 and F27 survived every piece of band evidence on the first run. Probes added in this walk now catch them, so they are suggested tests for the implementer.
Result: 30 seeded, 30 caught (27 by the implementer, shipped, customer or reviewer evidence; 3 only by the auditor's probes).

## Revision 999fda2 (shared invariant checker)

Source: `git archive 999fda2 stage-1`. F01–F30 rerun, F31–F32 seeded in the new reset wiring. Baselines: none (customer and auditor pass the unmodified copy).

| id | requirement broken | file | change | caught by |
|---|---|---|---|---|
| F00 | baseline: unmodified copy (must be caught by nothing) | common.py | none | — |
| F01 | R55 key scoped by path | common.py | `ik = (user["id"], key, req.path)` → `ik = (user["id"], key, req.path.split("/")[1])` | impl, shipped, reviewer, customer, auditor |
| F02 | R56 replay returns 200 | common.py | `            return 200, rec[1]` → `            return 201, rec[1]` | impl, shipped, reviewer, customer, auditor |
| F03 | R59 body equality ignores key order | common.py | `for k, x in sorted(v.items())) + "}"` → `for k, x in v.items()) + "}"` | impl, customer, auditor |
| F04 | R3/R74 paid request cannot be paid again | wallet.py | `if r["status"] != "pending":⏎            raise ApiError(409` → `if r["status"] in ("declined", "cancelled"):⏎            raise ApiError(409` | impl, reviewer, customer, auditor |
| F05 | R118/R119 settlement net affordability, all-or-nothing | settlements.py | `check_funds=False)` → `check_funds=True)` | impl, customer, auditor |
| F06 | R121 settlement payments in input order | settlements.py | `"payments": [pay_view(s, p) for p in payments]}` → `"payments": [pay_view(s, p) for p in reversed(payments)]}` | impl, reviewer, customer, auditor |
| F07 | R122 nonmembers expose settlement_id null | wallet.py | `"request_id": p["request_id"], "settlement_id": p["settlement_id"],` → `"request_id": p["request_id"], **({"settlement_id": p["settlement_id"]} if p["settlement_id"] else {}),` | impl, customer, auditor |
| F08 | R116 self-transfer in settlement is 422 self_payment | settlements.py | `    if frm is to:` → `    if False:` | impl, customer, auditor |
| F09 | R112 non-operator gets 403 | settlements.py | `if user["id"] not in s.operators:` → `if not s.operators:` | impl, reviewer, customer, auditor |
| F10 | R101 import preserves idempotency records | snapshot.py | `        s.idem[(u, k, p)] = (fp, resp)` → `        pass` | impl, reviewer, customer, auditor |
| F11 | R99 import preserves bearer tokens | snapshot.py | `        s.tokens[t] = uid` → `        pass` | impl, shipped, reviewer, auditor |
| F12 | R42 query integers are plain digits | common.py | `DIGITS_RE = re.compile(r"[0-9]+", re.ASCII)` → `DIGITS_RE = re.compile(r"[+]?[0-9]+", re.ASCII)` | impl, auditor |
| F13 | R17 booleans are not amounts | common.py | `if isinstance(v, bool) or not isinstance(v, (int, Decimal)):` → `if not isinstance(v, (int, Decimal)):` | impl, reviewer, customer, auditor |
| F14 | R78 decline of a cancelled request is 409 | wallet.py | `elif r["status"] != status:` → `elif r["status"] == "paid":` | impl, reviewer, customer, auditor |
| F15 | R40 malformed bearer scheme is 401 | common.py | `if len(parts) != 2 or parts[0].lower() != "bearer":` → `if len(parts) != 2:` | impl, auditor |
| F16 | R16/R73 fractional amounts are 422, never rounded | common.py | `        if v is None:⏎            raise validation(field + " must be an integer")` → `        if v is None:⏎            v = 1` | impl, shipped, reviewer, customer, auditor |
| F17 | R16 exact parse: 1.0000000000000001 is not an integer | common.py | `parse_float=_parse_float if decimal else float,` → `parse_float=(lambda s: _parse_float(repr(float(s)))) if decimal else float,` | impl, customer, auditor |
| F18 | R44/R73 huge integer amounts are 422, not 400/5xx | common.py | `return int(text) if len(text) <= 18 else Decimal(text)` → `return int(text)` | impl, customer, auditor |
| F19 | R42 huge offset is valid (empty page), huge limit 422 | common.py | `n = int(v) if len(v) <= 18 else 10 ** 18` → `n = int(v) if len(v) <= 18 else 0` | impl, customer |
| F20 | R105 import rejects an invalid timestamp | snapshot.py | `    _need(_str(v) and RFC3339.fullmatch(v))⏎    parse_ts(v)` → `    return` | equivalent † |
| F21 | R105 import rejects dangling payment->request references | snapshot.py | `_need(p["request_id"] is None or p["request_id"] in s.requests_by_id)` → `pass` | equivalent † |
| F22 | R105 import rejects a negative/fractional balance | snapshot.py | `_need(_id(rec["id"]) and 0 <= rec["balance"] <= 2 ** 53 and _int(rec["balance"]))` → `_need(_id(rec["id"]))` | equivalent † |
| F23 | R31 seeded users log in (per-record KDF cost honoured) | common.py | `user.get("n", 2 ** 12))` → `2 ** 12)` | impl, shipped, reviewer, customer, auditor |
| F24 | R59/A2 1000 and 1000.0 are the same body | common.py | `    if isinstance(v, int):⏎        return _num(Decimal(v))` → `    if isinstance(v, int):⏎        return str(v)` | impl, customer, auditor |
| F25 | R16/R73 1.5 is not an integer amount (as_tuple integrality) | common.py | `if len(digits) <= k or any(digits[-k:]):` → `if len(digits) <= k:` | impl, shipped, reviewer, customer, auditor |
| F26 | R59 1.5 and 1.50 are the same JSON value | common.py | `    while digits[-1] == 0:⏎        digits.pop()⏎        exp += 1` → `    pass` | impl, customer, auditor |
| F27 | R59 a string never equals a literal ("true" vs true, "null" vs null) | common.py | `    if isinstance(v, str):⏎        return json.dumps(v)` → `    if isinstance(v, str):⏎        return v` | impl, customer, auditor |
| F28 | R105/§10 reset rejects dangling references (export must re-import) | accounts.py | `raise validation("request refers to an unknown payment")` → `pass` | equivalent † |
| F29 | R30/§10 reset rejects balance above 2^53 (export must re-import) | accounts.py | `bal = _int(u.get("balance", 0), 0, 2 ** 53)` → `bal = _int(u.get("balance", 0), 0)` | equivalent † |
| F30 | R105 import rejects a receipt that disagrees with its record | snapshot.py | `and resp["amount"] == r["amount"] and resp["currency"] == s.currency` → `and resp["currency"] == s.currency` | impl |
| F31 | §10 reset rejects states import would reject (invariants on reset) | accounts.py | `    try:⏎        check_state_invariants(s)⏎    except` → `    try:⏎        pass⏎    except` | impl |
| F32 | R31/R34 a seeded paid request linked by payment_id is a valid fixture | accounts.py | `        if p is not None and p["request_id"] is None:⏎            p["request_id"] = r["id"]` → `        if False:⏎            p["request_id"] = r["id"]` | impl |

† Equivalent mutant: removing this single guard leaves behaviour unchanged, because `invariants.py` repeats the check on the same reset/import path (all 39 auditor probes still pass). Removing the invariant call itself (F31) is caught.
Result: 32 seeded; 27 caught, 5 equivalent, 0 surviving.
