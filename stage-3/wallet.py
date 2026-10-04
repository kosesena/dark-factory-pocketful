"""Payments, requests, splits and the activity feed."""
from ledger import ensure_revisions
from common import (ApiError, available_of, STATUSES, authenticate, get_str, idempotent, new_id, next_seq,
                    now_ts, paginate, parse_amount, parse_json, parse_note, parse_visibility,
                    store, validation)


def pay_view(s, p):
    fu, tu = s.users[p["from_user_id"]], s.users[p["to_user_id"]]
    return {"payment_id": p["id"], "from_user_id": fu["id"], "from_handle": fu["handle"],
            "to_user_id": tu["id"], "to_handle": tu["handle"], "amount": p["amount"],
            "currency": s.currency, "note": p["note"], "visibility": p["visibility"],
            "request_id": p["request_id"], "settlement_id": p["settlement_id"],
            "authorization_id": p.get("authorization_id"),
            "created_at": p["created_at"]}


def req_view(s, r):
    a, b = s.users[r["requester_id"]], s.users[r["payer_id"]]
    return {"request_id": r["id"], "requester_id": a["id"], "requester_handle": a["handle"],
            "payer_id": b["id"], "payer_handle": b["handle"], "amount": r["amount"],
            "currency": s.currency, "note": r["note"], "status": r["status"],
            "payment_id": r["payment_id"], "created_at": r["created_at"]}


def move_money(s, frm, to, amount, note, visibility, request_id=None, settlement_id=None,
               stamp=None, check_funds=True, authorization_id=None):
    """Caller holds the lock. Held funds cannot fund a transfer (checked against available)."""
    if check_funds and available_of(s, frm) < amount:
        raise ApiError(409, "insufficient_funds", "insufficient funds")
    frm["balance"] -= amount
    to["balance"] += amount
    ts, created = stamp or now_ts()
    p = {"id": new_id("p_"), "from_user_id": frm["id"], "to_user_id": to["id"],
         "amount": amount, "note": note, "visibility": visibility,
         "request_id": request_id, "settlement_id": settlement_id,
         "authorization_id": authorization_id,
         "created_at": created, "ts": ts, "seq": next_seq(s)}
    ensure_revisions(p)
    s.payments.append(p)
    s.payments_by_id[p["id"]] = p
    return p


def lookup_handle(s, handle):
    user = s.by_handle.get(handle)
    if user is None:
        raise ApiError(404, "not_found", "no user with that handle")
    return user


def create_payment(req):
    user = authenticate(req)
    s = store.state

    def run(body):
        amount = parse_amount(body)
        note = parse_note(body)
        vis = parse_visibility(body)
        to = lookup_handle(s, get_str(body, "to_handle"))
        if to is user:
            raise ApiError(422, "self_payment", "cannot pay yourself")
        return pay_view(s, move_money(s, user, to, amount, note, vis))
    return idempotent(req, user, run)


def create_request(req):
    user = authenticate(req)
    s = store.state

    def run(body):
        amount = parse_amount(body)
        note = parse_note(body)
        payer = lookup_handle(s, get_str(body, "payer_handle"))
        if payer is user:
            raise ApiError(422, "self_request", "cannot request money from yourself")
        return req_view(s, new_request(s, user, payer, amount, note))
    return idempotent(req, user, run)


def new_request(s, requester, payer, amount, note):
    ts, created = now_ts()
    r = {"id": new_id("rq_"), "requester_id": requester["id"], "payer_id": payer["id"],
         "amount": amount, "note": note, "status": "pending", "payment_id": None,
         "created_at": created, "ts": ts, "seq": next_seq(s)}
    s.requests.append(r)
    s.requests_by_id[r["id"]] = r
    return r


def find_request(s, rid):
    r = s.requests_by_id.get(rid)
    if r is None:
        raise ApiError(404, "not_found", "no such request")
    return r


def pay_request(req):
    user = authenticate(req)
    s = store.state
    rid = req.params[0]

    def run(body):
        r = find_request(s, rid)
        if r["payer_id"] != user["id"]:
            raise ApiError(403, "forbidden", "only the payer may pay a request")
        vis = parse_visibility(body)
        if r["status"] != "pending":
            raise ApiError(409, "request_not_pending", "request is not pending")
        to = s.users[r["requester_id"]]
        p = move_money(s, user, to, r["amount"], r["note"], vis, request_id=r["id"])
        r["status"] = "paid"
        r["payment_id"] = p["id"]
        return pay_view(s, p)
    return idempotent_pay(req, user, run)


def idempotent_pay(req, user, run):
    # the pay body is optional: an empty body means {}
    if not req.raw.strip():
        req.raw = b"{}"
    return idempotent(req, user, run)


def decline_request(req):
    user = authenticate(req)
    s = store.state
    r = find_request(s, req.params[0])
    if r["payer_id"] != user["id"]:
        raise ApiError(403, "forbidden", "only the payer may decline a request")
    return close_request(s, r, "declined")


def cancel_request(req):
    user = authenticate(req)
    s = store.state
    r = find_request(s, req.params[0])
    if r["requester_id"] != user["id"]:
        raise ApiError(403, "forbidden", "only the requester may cancel a request")
    return close_request(s, r, "cancelled")


def close_request(s, r, status):
    if r["status"] == "pending":
        r["status"] = status
    elif r["status"] != status:
        raise ApiError(409, "request_not_pending", "request is not pending")
    return 200, req_view(s, r)


def list_requests(req):
    user = authenticate(req)
    s = store.state
    q = req.query
    direction = q.get("direction")
    status = q.get("status")
    if direction is not None and direction not in ("incoming", "outgoing"):
        raise validation("direction must be incoming or outgoing")
    if status is not None and status not in STATUSES:
        raise validation("unknown status")
    uid = user["id"]
    rows = []
    for r in s.requests:
        incoming, outgoing = r["payer_id"] == uid, r["requester_id"] == uid
        if direction == "incoming" and not incoming:
            continue
        if direction == "outgoing" and not outgoing:
            continue
        if not (incoming or outgoing) or (status and r["status"] != status):
            continue
        rows.append(r)
    paginate(rows, q)  # validate limit/offset before sorting
    rows.sort(key=lambda r: (r["ts"], r["seq"]), reverse=True)
    limit_rows, more = paginate(rows, q)
    return 200, {"requests": [req_view(s, r) for r in limit_rows], "has_more": more}


def shares(amount, n):
    base, extra = divmod(amount, n)
    return [base + (1 if i < extra else 0) for i in range(n)]


def create_split(req):
    user = authenticate(req)
    s = store.state

    def run(body):
        amount = parse_amount(body)
        note = parse_note(body)
        if "participant_handles" not in body:
            raise validation("participant_handles is required")
        handles = body["participant_handles"]
        if not isinstance(handles, list) or not all(isinstance(h, str) for h in handles):
            raise ApiError(400, "malformed_request", "participant_handles must be an array of strings")
        if not handles or len(set(handles)) != len(handles):
            raise validation("participant_handles must be non-empty and unique")
        people = [lookup_handle(s, h) for h in handles]
        parts = shares(amount, len(people))
        ts, created = now_ts()
        reqs = [req_view(s, new_request(s, user, p, share, note))
                for p, share in zip(people, parts) if p is not user]
        resp = {"split_id": new_id("sp_"), "amount": amount, "currency": s.currency,
                "note": note,
                "shares": [{"handle": p["handle"], "amount": a} for p, a in zip(people, parts)],
                "requests": reqs, "created_at": created}
        s.splits[resp["split_id"]] = resp
        return resp
    return idempotent(req, user, run)


def activity(req):
    user = authenticate(req)
    s = store.state
    uid = user["id"]
    rows = [p for p in s.payments
            if p["visibility"] == "public" or p["from_user_id"] == uid or p["to_user_id"] == uid]
    paginate(rows, req.query)
    rows.sort(key=lambda p: (p["ts"], p["seq"]), reverse=True)
    page, more = paginate(rows, req.query)
    return 200, {"payments": [pay_view(s, p) for p in page], "has_more": more}


ROUTES = [
    ("POST", r"/payments", create_payment),
    ("POST", r"/requests", create_request),
    ("GET", r"/requests", list_requests),
    ("POST", r"/requests/([^/]+)/pay", pay_request),
    ("POST", r"/requests/([^/]+)/decline", decline_request),
    ("POST", r"/requests/([^/]+)/cancel", cancel_request),
    ("POST", r"/splits", create_split),
    ("GET", r"/activity", activity),
]
