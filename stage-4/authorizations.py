"""Authorizations (holds) and captures."""
from common import (ApiError, authenticate, available_of, close_auth, get_str, idempotent,
                    new_id, next_seq, now_ts, paginate, parse_amount, parse_note, parse_visibility,
                    store, fmt_ts, validation)
from wallet import lookup_handle, move_money, pay_view

AUTH_STATUSES = ("open", "captured", "voided", "expired")


def auth_view(s, a):
    fu, tu = s.users[a["from_user_id"]], s.users[a["to_user_id"]]
    pids = a["payment_ids"]
    return {"authorization_id": a["id"], "from_user_id": fu["id"], "from_handle": fu["handle"],
            "to_user_id": tu["id"], "to_handle": tu["handle"], "amount": a["amount"],
            "captured_amount": a["captured_amount"],
            "remaining_amount": a["amount"] - a["captured_amount"] if a["status"] == "open" else 0,
            "currency": s.currency, "note": a["note"], "visibility": a["visibility"],
            "status": a["status"], "expires_at": a["expires_at"],
            "payment_id": pids[-1] if pids else None, "payment_ids": list(pids),
            "created_at": a["created_at"], "closed_at": a.get("closed_at")}


def create_authorization(req):
    user = authenticate(req)
    s = store.state

    def run(body):
        amount = parse_amount(body)
        note = parse_note(body)
        vis = parse_visibility(body)
        to = lookup_handle(s, get_str(body, "to_handle"))
        if to is user:
            raise ApiError(422, "self_payment", "cannot authorize a payment to yourself")
        if available_of(s, user) < amount:
            raise ApiError(409, "insufficient_funds", "insufficient available funds")
        ts, created = now_ts()
        ets = int(ts) + s.auth_ttl  # the deadline is exactly the displayed expires_at
        a = {"id": new_id("a_"), "from_user_id": user["id"], "to_user_id": to["id"],
             "amount": amount, "captured_amount": 0, "note": note, "visibility": vis,
             "status": "open", "expires_at": fmt_ts(int(ts) + s.auth_ttl), "expires_ts": ets, "payment_ids": [],
             "closed_at": None, "closed_ts": None,
             "created_at": created, "ts": ts, "seq": next_seq(s)}
        s.auths.append(a)
        s.auths_by_id[a["id"]] = a
        s.open_auths[a["id"]] = a
        return auth_view(s, a)
    return idempotent(req, user, run)


def find_auth(s, aid):
    a = s.auths_by_id.get(aid)
    if a is None:
        raise ApiError(404, "not_found", "no such authorization")
    return a


def capture(req):
    user = authenticate(req)
    s = store.state
    aid = req.params[0]

    def run(body):
        a = find_auth(s, aid)
        if a["to_user_id"] != user["id"]:
            raise ApiError(403, "forbidden", "only the receiver may capture")
        remaining = a["amount"] - a["captured_amount"]
        amount = parse_amount(body) if "amount" in body else remaining
        final = body.get("final", True)
        if not isinstance(final, bool):
            raise ApiError(400, "malformed_request", "final must be a boolean")
        if a["status"] == "expired":
            raise ApiError(409, "authorization_expired", "authorization has expired")
        if a["status"] != "open":
            raise ApiError(409, "authorization_not_open", "authorization is not open")
        if amount > remaining:
            raise ApiError(422, "capture_exceeds_authorization", "amount exceeds the remainder")
        payer = s.users[a["from_user_id"]]
        # the money was reserved for this capture, so it may use held funds
        p = move_money(s, payer, user, amount, a["note"], a["visibility"],
                       check_funds=False, authorization_id=a["id"])
        a["captured_amount"] += amount
        a["payment_ids"].append(p["id"])
        if final or a["captured_amount"] == a["amount"]:
            close_auth(s, a, "captured", p["created_at"], float(int(p["ts"])))
        return pay_view(s, p)
    return idempotent_capture(req, user, run)


def idempotent_capture(req, user, run):
    if not req.raw.strip():
        req.raw = b"{}"
    return idempotent(req, user, run)


def void(req):
    user = authenticate(req)
    s = store.state
    a = find_auth(s, req.params[0])
    if a["from_user_id"] != user["id"]:
        raise ApiError(403, "forbidden", "only the payer may void")
    if a["status"] == "open":
        vts, vat = now_ts()
        close_auth(s, a, "voided", vat, float(int(vts)))
    elif a["status"] != "voided":
        raise ApiError(409, "authorization_not_open", "authorization is not open")
    return 200, auth_view(s, a)


def list_authorizations(req):
    user = authenticate(req)
    s = store.state
    q = req.query
    direction, status = q.get("direction"), q.get("status")
    if direction is not None and direction not in ("incoming", "outgoing"):
        raise validation("direction must be incoming or outgoing")
    if status is not None and status not in AUTH_STATUSES:
        raise validation("unknown status")
    uid = user["id"]
    rows = []
    for a in s.auths:
        out, inc = a["from_user_id"] == uid, a["to_user_id"] == uid
        if direction == "outgoing" and not out:
            continue
        if direction == "incoming" and not inc:
            continue
        if not (out or inc) or (status and a["status"] != status):
            continue
        rows.append(a)
    paginate(rows, q)
    rows.sort(key=lambda a: (a["ts"], a["seq"]), reverse=True)
    page, more = paginate(rows, q)
    return 200, {"authorizations": [auth_view(s, a) for a in page], "has_more": more}


ROUTES = [
    ("POST", r"/authorizations", create_authorization),
    ("GET", r"/authorizations", list_authorizations),
    ("POST", r"/authorizations/([^/]+)/capture", capture),
    ("POST", r"/authorizations/([^/]+)/void", void),
]
