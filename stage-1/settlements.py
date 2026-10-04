"""POST /settlements: atomic net settlement of up to 32 transfers."""
from common import (ApiError, authenticate, idempotent, new_id, now_ts, parse_amount, parse_note,
                    parse_visibility, store, validation)
from wallet import lookup_handle, move_money, pay_view


def _entry(s, t):
    if not isinstance(t, dict):
        raise validation("each transfer must be an object")
    for f in ("from_handle", "to_handle"):
        if not isinstance(t.get(f), str):
            raise validation(f + " must be a string")
    amount = parse_amount(t)
    note = parse_note(t)
    vis = parse_visibility(t)
    frm = lookup_handle(s, t["from_handle"])
    to = lookup_handle(s, t["to_handle"])
    if frm is to:
        raise ApiError(422, "self_payment", "cannot transfer to the same wallet")
    return frm, to, amount, note, vis


def create_settlement(req):
    user = authenticate(req)
    s = store.state
    if user["id"] not in s.operators:
        raise ApiError(403, "forbidden", "settlement operator required")

    def run(body):
        transfers = body.get("transfers")
        if not isinstance(transfers, list) or not 1 <= len(transfers) <= 32:
            raise validation("transfers must be an array of 1 to 32 objects")
        entries = [_entry(s, t) for t in transfers]  # first failing entry wins
        net = {}
        for frm, to, amount, _, _ in entries:
            net[frm["id"]] = net.get(frm["id"], 0) - amount
            net[to["id"]] = net.get(to["id"], 0) + amount
        if any(s.users[uid]["balance"] + d < 0 for uid, d in net.items()):
            raise ApiError(409, "insufficient_funds", "settlement is not affordable")
        sid = new_id("st_")
        stamp = now_ts()
        # net affordability is verified; intermediate dips are never visible (lock held)
        payments = [move_money(s, frm, to, amount, note, vis, settlement_id=sid, stamp=stamp,
                               check_funds=False)
                    for frm, to, amount, note, vis in entries]
        resp = {"settlement_id": sid, "committed_at": stamp[1],
                "payments": [pay_view(s, p) for p in payments]}
        s.settlements[sid] = {"id": sid, "committed_at": stamp[1],
                              "payment_ids": [p["id"] for p in payments]}
        return resp
    return idempotent(req, user, run)


ROUTES = [("POST", r"/settlements", create_settlement)]
