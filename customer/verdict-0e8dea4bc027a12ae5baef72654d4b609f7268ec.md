# Customer verdict — stage 1, revision 0e8dea4bc027a12ae5baef72654d4b609f7268ec

ACCEPT

Verified from a `git archive` of exactly this revision (image built, run on PORT 8097). `journey_stage1.py`, log `run-0e8dea4.log`:
260 checks, 259 pass, 0 product-blocking failures, no tracebacks in the container log.
New this round: canonical number identity (15e1 == 150 == 1.50e2 on replay, "150" string -> 409, key-order/5.0 replay 200);
1e999999999 / 1e-999999999 / -0.0 / 5000-digit int / NaN / Infinity / 5000-deep nesting / duplicate keys on payments, settlements,
splits and requests -> 4xx, never 5xx; real export (payment, paid request, split, settlement, over-limit failed key) re-imported:
receipts replay 200, settlement receipt valid, re-export identical; tampered imports (negative amount/balance, bogus status/visibility,
non-object state) -> 422 or accepted, never 5xx, state unchanged on 422; reset validation (dup handle/email, bad handle, minor_units 5,
unknown payment user, bad request status) -> 422 with prior state kept.
Single non-blocking observation: reset with `settlement_operator_ids` naming an unknown user returns 204 (spec does not say it is an error).
Harness check on the archived revision: stage 1 pass, "claimed stage: 1", also with --mode isolated.
