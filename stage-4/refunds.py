"""Refunds: the original receiver sends part or all of a payment back."""
from decimal import Decimal

from common import (ApiError, MAX_AMOUNT, authenticate, decimal_int, idempotent, store, validation)
from wallet import move_money, pay_view


def refunded_total(s, pid):
    return sum(q["amount"] for q in s.payments if q.get("refund_of") == pid)


def refund(req):
    user = authenticate(req)
    s = store.state
    pid = req.params[0]

    def run(body):
        p = s.payments_by_id.get(pid)
        if p is None:
            raise ApiError(404, "not_found", "no such payment")
        if p["to_user_id"] != user["id"]:
            raise ApiError(403, "forbidden", "only the receiver may refund a payment")
        if "amount" not in body:
            raise validation("amount is required")
        v = body["amount"]
        if isinstance(v, bool) or not isinstance(v, (int, Decimal)):
            raise validation("amount must be an integer")
        if isinstance(v, Decimal):
            v = decimal_int(v)
            if v is None:
                raise validation("amount must be an integer")
        if v < 1 or v > MAX_AMOUNT:
            raise validation("amount out of range")
        if p.get("refund_of") is not None:
            raise ApiError(422, "invalid_refund_target", "a refund cannot be refunded")
        if refunded_total(s, pid) + v > p["revisions"][-1]["amount"]:
            raise ApiError(422, "refund_exceeds_payment", "refunds would exceed the payment's current amount")
        # existing money, from the receiver's available funds; nothing else is reopened or restored
        return pay_view(s, move_money(s, user, s.users[p["from_user_id"]], v, p["note"], p["visibility"],
                                      refund_of=pid))
    return idempotent(req, user, run)


ROUTES = [("POST", r"/payments/([^/]+)/refunds", refund)]
