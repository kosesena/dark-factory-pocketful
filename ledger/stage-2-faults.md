# Stage 2 seeded faults — spec-auditor

Revision d78f1bd (`git archive d78f1bd stage-1 stage-2` into `audit/mutants/_src-d78f1bd`, git-ignored, never committed).
One fault per mutant. An unmodified stage-1 service from the same archive serves the upgrade checks. Evidence:
- impl: `stage-2/tests/test_service.py` and `tests/ui_check.py`
- shipped: `harness --base-url … --previous-base-url … --stages 2`
- reviewer: `verification/probes_s2.py`, `ui_check_s2.py`
- customer: `customer/journey_stage2_api.py`, `journey_stage2_ui.py` (copies)
- auditor: `audit/probes/stage2_probes.py`, `stage2_ui_probes.py`
A seat catches a fault when its evidence fails a check it passes on the unmodified copy G00, which fails nothing anywhere.
Runner: `SEED_REV=d78f1bd python3 audit/seed_faults_s2.py`.

| id | requirement broken | file | change | caught by |
|---|---|---|---|---|
| G00 | baseline: unmodified copy (must be caught by nothing) | common.py | none | — |
| G01 | S2-49 payments are checked against available, not total | wallet.py | `if check_funds and available_of(s, frm) < amount:` → `if check_funds and frm["balance"] < amount:` | auditor, customer, impl, reviewer |
| G02 | S2-49 settlement net debits cannot use held funds | settlements.py | `< held_of(s, uid) for uid, d in net.items()` → `< 0 for uid, d in net.items()` | auditor, customer, impl |
| G03 | S2-50 captures may spend the money reserved for them | authorizations.py | `check_funds=False, authorization_id=a["id"])` → `check_funds=True, authorization_id=a["id"])` | auditor, impl |
| G04 | S2-61 expiry is reflected by reads with no request at the deadline | server.py | `                    sweep(store.state, time.time())` → `                    if req.method != 'GET': sweep(store.state, time.time())` | auditor, customer, impl, reviewer |
| G05 | S2-68 a default (final) capture releases the remainder | authorizations.py | `if final or a["captured_amount"] == a["amount"]:` → `if a["captured_amount"] == a["amount"]:` | auditor, customer, impl, reviewer |
| G06 | S2-71 capturing the whole remainder closes it even with final:false | authorizations.py | `if final or a["captured_amount"] == a["amount"]:` → `if final:` | auditor, impl, reviewer |
| G07 | S2-72 capture_exceeds compares with the remaining amount | authorizations.py | `if amount > remaining:` → `if amount > a["amount"]:` | auditor, customer, impl, reviewer |
| G08 | S2-75 remaining_amount is zero when closed | authorizations.py | `"remaining_amount": a["amount"] - a["captured_amount"] if a["status"] == "open" else 0,` → `"remaining_amount": a["amount"] - a["captured_amount"],` | auditor, customer, impl, reviewer |
| G09 | S2-74 capture after expiry is authorization_expired | authorizations.py | `raise ApiError(409, "authorization_expired", "authorization has expired")` → `raise ApiError(409, "authorization_not_open", "authorization has expired")` | auditor, customer, impl, reviewer |
| G10 | S2-76 only the payer may void | authorizations.py | `if a["from_user_id"] != user["id"]:⏎        raise ApiError(403, "forbidden", "only the payer may void")` → `if a["from_user_id"] != user["id"] and a["to_user_id"] != user["id"]:⏎        raise ApiError(403, "forbidden", "only the payer may void")` | auditor, customer, impl, reviewer |
| G11 | S2-2 API clients without Accept: text/html get JSON on /requests | ui.py | `"text/html" not in req.headers.get("Accept", "")` → `"json" in req.headers.get("Accept", "")` | auditor, customer, impl, reviewer, shipped |
| G12 | S2-37 latest refresh wins | static/app.js | `if (my !== seq) return;` → `/* no ordering guard */` | auditor |
| G13 | S2-40 a lost response is uncertain, not a refusal | static/app.js | `return { status: 0, ok: false, network: true, uncertain: true };` → `return { status: 0, ok: false, network: true, uncertain: false };` | auditor, customer, impl, reviewer |
| G14 | S2-17 too many decimal places is refused, not rounded | static/app.js | `if (frac.length > CFG.mu) {` → `if (frac.length > CFG.mu + 1) {` | auditor, customer, impl, reviewer |
| G15 | S2-83 wallet-held is absent when held is zero | static/app.js | `me.held > 0 && h('div', { class: 'held' }` → `me.held >= 0 && h('div', { class: 'held' }` | auditor, customer, impl, reviewer |
| G16 | S2-56 expires_at is created_at + ttl | authorizations.py | `"expires_at": fmt_ts(int(ts) + s.auth_ttl)` → `"expires_at": fmt_ts(int(ts) + s.auth_ttl + 60)` | auditor, customer, impl, reviewer |

Result: 16 seeded, 16 caught. G12 (latest refresh wins) is caught only by the auditor's browser probe: suggested test.
The shipped stage-2 checks alone catch 1 of 16 (G11).
