"""GET /_test/export and POST /_test/import."""
import json

from common import (HANDLE_RE, STATUSES, State, parse_json, store, validation)


def export(req):
    s = store.state
    state = {
        "currency": s.currency, "minor_units": s.minor_units,
        "users": list(s.users.values()),
        "tokens": s.tokens,
        "payments": s.payments, "requests": s.requests,
        "splits": s.splits, "settlements": s.settlements,
        "idempotency": [[u, k, p, fp, resp] for (u, k, p), (fp, resp) in s.idem.items()],
        "operators": sorted(s.operators), "seq": s.seq,
    }
    # serialised under the lock: an atomic, read-only snapshot
    data = json.dumps({"track": "pocketful", "format_version": 1, "state": state})
    return 200, data.encode("utf-8")


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _need(cond):
    if not cond:
        raise ValueError("invalid state")


def _str(v):
    return isinstance(v, str)


def load_state(st):
    _need(isinstance(st, dict))
    s = State()
    s.currency, s.minor_units = st["currency"], st["minor_units"]
    _need(_str(s.currency) and s.currency and _int(s.minor_units) and s.minor_units in (0, 2, 3))
    for u in st["users"]:
        _need(isinstance(u, dict))
        rec = {k: u[k] for k in ("id", "email", "display_name", "handle", "balance", "salt", "hash")}
        _need(all(_str(rec[k]) for k in ("id", "email", "display_name", "handle", "salt", "hash")))
        _need(_int(rec["balance"]) and rec["balance"] >= 0)
        _need(HANDLE_RE.fullmatch(rec["handle"]))
        bytes.fromhex(rec["salt"]), bytes.fromhex(rec["hash"])
        _need(rec["id"] not in s.users and rec["handle"] not in s.by_handle
              and rec["email"].lower() not in s.by_email)
        s.users[rec["id"]] = rec
        s.by_handle[rec["handle"]] = rec
        s.by_email[rec["email"].lower()] = rec
    _need(isinstance(st["tokens"], dict))
    for t, uid in st["tokens"].items():
        _need(uid in s.users)
        s.tokens[t] = uid
    for p in st["payments"]:
        rec = {k: p[k] for k in ("id", "from_user_id", "to_user_id", "amount", "note", "visibility",
                                 "request_id", "settlement_id", "created_at", "ts", "seq")}
        _need(_str(rec["id"]) and rec["id"] not in s.payments_by_id)
        _need(rec["from_user_id"] in s.users and rec["to_user_id"] in s.users)
        _need(_int(rec["amount"]) and rec["amount"] >= 0 and _str(rec["note"]))
        _need(rec["visibility"] in ("public", "private") and _str(rec["created_at"]))
        _need(isinstance(rec["ts"], (int, float)) and _int(rec["seq"]))
        s.payments.append(rec)
        s.payments_by_id[rec["id"]] = rec
    for r in st["requests"]:
        rec = {k: r[k] for k in ("id", "requester_id", "payer_id", "amount", "note", "status",
                                 "payment_id", "created_at", "ts", "seq")}
        _need(_str(rec["id"]) and rec["id"] not in s.requests_by_id)
        _need(rec["requester_id"] in s.users and rec["payer_id"] in s.users)
        _need(_int(rec["amount"]) and rec["amount"] >= 0 and _str(rec["note"]))
        _need(rec["status"] in STATUSES and _str(rec["created_at"]))
        _need(isinstance(rec["ts"], (int, float)) and _int(rec["seq"]))
        s.requests.append(rec)
        s.requests_by_id[rec["id"]] = rec
    _need(isinstance(st["splits"], dict) and all(isinstance(v, dict) for v in st["splits"].values()))
    s.splits = dict(st["splits"])
    _need(isinstance(st["settlements"], dict))
    for k, v in st["settlements"].items():
        _need(isinstance(v, dict) and isinstance(v["payment_ids"], list)
              and all(pid in s.payments_by_id for pid in v["payment_ids"]))
        s.settlements[k] = {"id": v["id"], "committed_at": v["committed_at"],
                            "payment_ids": list(v["payment_ids"])}
    for item in st["idempotency"]:
        _need(isinstance(item, list) and len(item) == 5)
        u, k, p, fp, resp = item
        _need(_str(u) and _str(k) and _str(p) and _str(fp) and isinstance(resp, dict))
        s.idem[(u, k, p)] = (fp, resp)
    _need(isinstance(st["operators"], list) and all(_str(x) for x in st["operators"]))
    s.operators = set(st["operators"])
    _need(_int(st["seq"]))
    s.seq = max(st["seq"], max([p["seq"] for p in s.payments] + [r["seq"] for r in s.requests] + [0]))
    return s


def import_state(req):
    body = parse_json(req.raw, decimal=False)
    if body.get("track") != "pocketful":
        raise validation("track must be pocketful")
    fv = body.get("format_version")
    if isinstance(fv, bool) or fv != 1:
        raise validation("format_version must be 1")
    if "state" not in body:
        raise validation("state is required")
    try:
        new = load_state(body["state"])
    except (KeyError, TypeError, ValueError, AttributeError):
        raise validation("state is not a valid pocketful state")
    store.state = new
    return 204, None


ROUTES = [
    ("GET", r"/_test/export", export),
    ("POST", r"/_test/import", import_state),
]
