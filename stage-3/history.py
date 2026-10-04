"""Statements (with stable snapshots), payment corrections and revision history."""
import secrets
import time
from datetime import datetime, timezone
from decimal import Decimal

from common import (ApiError, MAX_AMOUNT, authenticate, available_of, decimal_int, idempotent, parse_page,
                    store, validation)
from ledger import effects, history_ok, instant_param, parse_instant
from wallet import pay_view


def _entry_view(s, e):
    pid, rev_no, delta, after, eff_at, rec_at, amount = e
    pv = pay_view(s, s.payments_by_id[pid])
    pv["amount"] = amount  # the amount of the selected revision, for this statement
    return {"payment": pv, "delta": delta, "balance_after": after, "revision": rev_no,
            "effective_at": eff_at, "recorded_at": rec_at}


def _page(s, snap, limit, offset):
    chunk = snap["entries"][offset:offset + limit]
    body = {"opening_balance": snap["opening_balance"], "entries": [_entry_view(s, e) for e in chunk],
            "closing_balance": snap["closing_balance"], "has_more": len(snap["entries"]) > offset + limit,
            "snapshot": snap["token"]}
    body.update(snap["echo"])
    return body


def build_statement(s, uid, lo, hi, known, taken_ts, taken_seq):
    """(opening balance, entries, closing balance) for the window [lo, hi) as the ledger stood when the
    statement was taken: only payments up to taken_seq, only revisions recorded by min(known_at, taken_ts)."""
    k = taken_ts if known is None else min(known, taken_ts)
    eff = sorted(effects(s, uid, k, max_seq=taken_seq), key=lambda e: (e[0], e[1]))
    running = s.users[uid]["opening"]
    entries = []
    opening = running if lo is None else None
    for t, pid, rev, delta in eff:
        if lo is not None and t < lo:
            running += delta
            continue
        if opening is None:
            opening = running
        if hi is not None and t >= hi:
            break
        running += delta
        entries.append((pid, rev["revision"], delta, running, rev["effective_at"], rev["recorded_at"], rev["amount"]))
    if opening is None:  # nothing at or after `from`
        opening = running
    return opening, entries, running


def statement(req):
    user = authenticate(req)
    s = store.state
    q = req.query
    limit, offset = parse_page(q)
    if "snapshot" in q:
        if any(k in q for k in ("from", "to", "known_at")):
            raise validation("only limit and offset may accompany a snapshot")
        snap = s.snapshots.get(q["snapshot"])
        if snap is None or snap["user_id"] != user["id"]:
            raise ApiError(404, "not_found", "unknown snapshot")
        return 200, _page(s, snap, limit, offset)
    frm, to, known = instant_param(q, "from"), instant_param(q, "to"), instant_param(q, "known_at")
    lo = frm[0] if frm else None
    hi = to[0] if to else None
    if lo is not None and hi is not None and hi < lo:
        hi = lo  # an inverted window is empty: opening == closing
    uid = user["id"]
    taken_ts, taken_seq = time.time(), s.seq
    opening, entries, running = build_statement(s, uid, lo, hi, known[0] if known else None, taken_ts, taken_seq)
    echo = {}
    for name, v in (("from", frm), ("to", to), ("known_at", known)):
        if v:
            echo[name] = v[1]
    snap = {"token": secrets.token_urlsafe(24), "user_id": uid, "opening_balance": opening,
            "entries": entries, "closing_balance": running, "echo": echo,
            "taken_ts": taken_ts, "taken_seq": taken_seq}
    s.snapshots[snap["token"]] = snap
    return 200, _page(s, snap, limit, offset)


def _int_field(body, name, lo, hi):
    if name not in body:
        raise validation(name + " is required")
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, Decimal)):
        raise validation(name + " must be an integer")
    if isinstance(v, Decimal):
        v = decimal_int(v)
        if v is None:
            raise validation(name + " must be an integer")
    if v < lo or (hi is not None and v > hi):
        raise validation(name + " out of range")
    return int(v)


def _rev_view(pid, r):
    return {"payment_id": pid, "revision": r["revision"], "amount": r["amount"],
            "effective_at": r["effective_at"], "recorded_at": r["recorded_at"], "reason": r["reason"]}


def correct(req):
    user = authenticate(req)
    s = store.state
    pid = req.params[0]

    def run(body):
        p = s.payments_by_id.get(pid)
        if p is None:
            raise ApiError(404, "not_found", "no such payment")
        if p["from_user_id"] != user["id"]:
            raise ApiError(403, "forbidden", "only the sender may correct a payment")
        expected = _int_field(body, "expected_revision", 1, None)
        amount = _int_field(body, "amount", 0, MAX_AMOUNT)
        if "effective_at" not in body or "reason" not in body:
            raise validation("effective_at and reason are required")
        try:
            eff_ts = parse_instant(body["effective_at"])
        except ValueError:
            raise validation("effective_at must be an RFC 3339 instant with an offset")
        now = time.time()
        if eff_ts > now:
            raise validation("effective_at cannot be in the future")
        reason = body["reason"]
        if not isinstance(reason, str) or not 1 <= len(reason) <= 200:
            raise validation("reason must be 1 to 200 characters")
        if p["settlement_id"] is not None or p.get("authorization_id") is not None:
            raise ApiError(422, "linked_payment_immutable", "settlement members and captures cannot be corrected")
        cur = p["revisions"][-1]
        if expected != cur["revision"]:
            raise ApiError(409, "stale_revision", "the payment has a newer revision")
        diff = amount - cur["amount"]
        sender, receiver = s.users[p["from_user_id"]], s.users[p["to_user_id"]]
        debtor = sender if diff > 0 else receiver  # increasing debits the sender, decreasing the receiver
        if diff != 0 and available_of(s, debtor) < abs(diff):
            raise ApiError(409, "insufficient_funds", "insufficient available funds for the correction")
        rec_ts = max(now, cur["recorded_ts"] + 1e-6)  # recorded times strictly increase per payment
        rec_at = datetime.fromtimestamp(rec_ts, timezone.utc).isoformat(timespec="microseconds")
        rev = {"revision": cur["revision"] + 1, "amount": amount, "effective_at": body["effective_at"],
               "effective_ts": eff_ts, "recorded_at": rec_at, "recorded_ts": parse_instant(rec_at),
               "reason": reason}
        if not history_ok(s, (sender["id"], receiver["id"]), {pid: rev}, now):
            raise ApiError(409, "historical_overdraft", "the correction would overdraw a past balance")
        sender["balance"] -= diff
        receiver["balance"] += diff
        p["revisions"].append(rev)
        return _rev_view(pid, rev)
    return idempotent(req, user, run)


def revisions(req):
    user = authenticate(req)
    s = store.state
    p = s.payments_by_id.get(req.params[0])
    if p is None or user["id"] not in (p["from_user_id"], p["to_user_id"]):
        raise ApiError(404, "not_found", "no such payment")
    return 200, {"revisions": [_rev_view(p["id"], r) for r in p["revisions"]]}


ROUTES = [
    ("GET", r"/statement", statement),
    ("POST", r"/payments/([^/]+)/corrections", correct),
    ("GET", r"/payments/([^/]+)/revisions", revisions),
]
