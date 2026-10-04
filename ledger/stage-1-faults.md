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
