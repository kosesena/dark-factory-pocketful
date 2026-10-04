"""POST /correction-batches: a settlement operator corrects several payments atomically."""
import time
from datetime import datetime, timezone

from common import ApiError, authenticate, available_of, held_of, idempotent, new_id, store, validation
from history import _rev_view, correction_fields
from ledger import history_ok, parse_instant
from refunds import refunded_total


def correction_batch(req):
    user = authenticate(req)
    s = store.state
    if user["id"] not in s.operators:
        raise ApiError(403, "forbidden", "settlement operator required")

    def run(body):
        items = body.get("corrections")
        if not isinstance(items, list) or not 1 <= len(items) <= 32 or not all(isinstance(i, dict) for i in items):
            raise validation("corrections must be an array of 1 to 32 objects")
        ids = [i.get("payment_id") for i in items]
        if not all(isinstance(x, str) for x in ids) or len(set(ids)) != len(ids):
            raise validation("each correction needs a distinct payment_id")
        now = time.time()
        plan = []  # (payment, new amount, effective ts, effective text, reason)
        for it in items:  # item errors, in input order
            p = s.payments_by_id.get(it["payment_id"])
            if p is None:
                raise ApiError(404, "not_found", "no such payment")
            expected, amount, eff_ts, reason = correction_fields(it, now)
            if p.get("authorization_id") is not None or p.get("refund_of") is not None:
                raise ApiError(422, "linked_payment_immutable", "captures and refunds cannot be corrected")
            if expected != p["revisions"][-1]["revision"]:
                raise ApiError(409, "stale_revision", "the payment has a newer revision")
            if amount < refunded_total(s, p["id"]):
                raise ApiError(422, "refund_exceeds_payment", "a payment cannot be corrected below what was refunded")
            plan.append((p, amount, eff_ts, it["effective_at"], reason))
        # settlement completeness, then identical effective instants within a settlement
        by_settlement = {}
        for p, _, eff_ts, _, _ in plan:
            if p["settlement_id"] is not None:
                by_settlement.setdefault(p["settlement_id"], []).append((p["id"], eff_ts))
        for sid, members in by_settlement.items():
            if set(s.settlements[sid]["payment_ids"]) != {m[0] for m in members}:
                raise ApiError(422, "incomplete_settlement", "every member of a settlement must be corrected together")
        for members in by_settlement.values():
            if len({m[1] for m in members}) != 1:
                raise validation("members of one settlement must share one effective instant")
        # current affordability of the combined effect, then history at every boundary
        net = {}
        for p, amount, _, _, _ in plan:
            diff = amount - p["revisions"][-1]["amount"]
            net[p["from_user_id"]] = net.get(p["from_user_id"], 0) - diff
            net[p["to_user_id"]] = net.get(p["to_user_id"], 0) + diff
        for uid, d in net.items():
            if d < 0 and available_of(s, s.users[uid]) + d < 0:
                raise ApiError(409, "insufficient_funds", "insufficient available funds for the corrections")
        last = max(p["revisions"][-1]["recorded_ts"] for p, *_ in plan)
        rec_ts = max(now, last + 1e-6)  # strictly later than every member's previous recorded time
        rec_at = datetime.fromtimestamp(rec_ts, timezone.utc).isoformat(timespec="microseconds")
        rec_parsed = parse_instant(rec_at)
        bid = new_id("cb_")
        override = {}
        for p, amount, eff_ts, eff_text, reason in plan:
            override[p["id"]] = {"revision": p["revisions"][-1]["revision"] + 1, "amount": amount,
                                 "effective_at": eff_text, "effective_ts": eff_ts, "recorded_at": rec_at,
                                 "recorded_ts": rec_parsed, "reason": reason, "correction_batch_id": bid}
        parties = {p["from_user_id"] for p, *_ in plan} | {p["to_user_id"] for p, *_ in plan}
        if not history_ok(s, sorted(parties), override, now):
            raise ApiError(409, "historical_overdraft", "the corrections would overdraw a past balance")
        for p, amount, *_ in plan:
            diff = amount - p["revisions"][-1]["amount"]
            s.users[p["from_user_id"]]["balance"] -= diff
            s.users[p["to_user_id"]]["balance"] += diff
            p["revisions"].append(override[p["id"]])
        return {"correction_batch_id": bid, "recorded_at": rec_at,
                "revisions": [_rev_view(p["id"], override[p["id"]]) for p, *_ in plan]}
    return idempotent(req, user, run)


ROUTES = [("POST", r"/correction-batches", correction_batch)]
