"""GET /_test/export and POST /_test/import."""
import json
import math
import re

from common import (MAX_AMOUNT, parse_ts, HANDLE_RE, held_of, STATUSES, State, parse_json, store, validation)


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
        "authorizations": s.auths, "auth_ttl": s.auth_ttl,
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


RFC3339 = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|z|[+-]\d\d:\d\d)")


def _ts_str(v):
    _need(_str(v) and RFC3339.fullmatch(v))
    parse_ts(v)  # raises ValueError for impossible dates


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _amount(v, lo=0):
    return _int(v) and lo <= v <= MAX_AMOUNT


def _id(v):
    return _str(v) and 1 <= len(v) <= 64


def _seq(v):
    return _int(v) and v >= 0


def load_state(st):
    _need(isinstance(st, dict))
    s = State()
    s.currency, s.minor_units = st["currency"], st["minor_units"]
    _need(_str(s.currency) and s.currency and _int(s.minor_units) and s.minor_units in (0, 2, 3))
    for u in st["users"]:
        _need(isinstance(u, dict))
        rec = {k: u[k] for k in ("id", "email", "display_name", "handle", "balance", "salt", "hash")}
        _need(all(_str(rec[k]) for k in ("id", "email", "display_name", "handle", "salt", "hash")))
        _need(_id(rec["id"]) and 0 <= rec["balance"] <= 2 ** 53 and _int(rec["balance"]))
        _need(HANDLE_RE.fullmatch(rec["handle"]))
        bytes.fromhex(rec["salt"]), bytes.fromhex(rec["hash"])
        rec["n"] = u.get("n", 2 ** 12)  # stage-1 exports carry no cost parameter
        _need(rec["n"] in (2 ** 10, 2 ** 11, 2 ** 12, 2 ** 14))
        _need(rec["id"] not in s.users and rec["handle"] not in s.by_handle
              and rec["email"].lower() not in s.by_email)
        s.users[rec["id"]] = rec
        s.by_handle[rec["handle"]] = rec
        s.by_email[rec["email"].lower()] = rec
    _need(isinstance(st["tokens"], dict))
    for t, uid in st["tokens"].items():
        _need(_str(t) and t and uid in s.users)
        s.tokens[t] = uid
    for p in st["payments"]:
        rec = {k: p[k] for k in ("id", "from_user_id", "to_user_id", "amount", "note", "visibility",
                                 "request_id", "settlement_id", "created_at", "ts", "seq")}
        rec["authorization_id"] = p.get("authorization_id")  # absent in stage-1 exports
        _need(_id(rec["id"]) and rec["id"] not in s.payments_by_id)
        _need(rec["from_user_id"] in s.users and rec["to_user_id"] in s.users)
        _need(_amount(rec["amount"]) and _str(rec["note"]))
        _need(rec["visibility"] in ("public", "private") and _str(rec["visibility"]))
        _ts_str(rec["created_at"])
        _need(_num(rec["ts"]) and _seq(rec["seq"]))
        s.payments.append(rec)
        s.payments_by_id[rec["id"]] = rec
    for r in st["requests"]:
        rec = {k: r[k] for k in ("id", "requester_id", "payer_id", "amount", "note", "status",
                                 "payment_id", "created_at", "ts", "seq")}
        _need(_id(rec["id"]) and rec["id"] not in s.requests_by_id)
        _need(rec["requester_id"] in s.users and rec["payer_id"] in s.users)
        _need(_amount(rec["amount"]) and _str(rec["note"]))
        _need(rec["status"] in STATUSES and _str(rec["status"]))
        _ts_str(rec["created_at"])
        _need(_num(rec["ts"]) and _seq(rec["seq"]))
        s.requests.append(rec)
        s.requests_by_id[rec["id"]] = rec
    _need(isinstance(st["splits"], dict) and all(isinstance(v, dict) for v in st["splits"].values()))
    s.splits = dict(st["splits"])
    _need(isinstance(st["settlements"], dict))
    for k, v in st["settlements"].items():
        _need(isinstance(v, dict) and _str(k) and v["id"] == k and isinstance(v["payment_ids"], list)
              and all(pid in s.payments_by_id for pid in v["payment_ids"]))
        _ts_str(v["committed_at"])
        s.settlements[k] = {"id": v["id"], "committed_at": v["committed_at"],
                            "payment_ids": list(v["payment_ids"])}
    for item in st["idempotency"]:
        _need(isinstance(item, list) and len(item) == 5)
        u, k, p, fp, resp = item
        _need(_str(u) and _str(k) and 1 <= len(k) <= 255 and _str(p) and _str(fp) and isinstance(resp, dict))
        s.idem[(u, k, p)] = (fp, resp)
    _need(isinstance(st["operators"], list) and all(_str(x) for x in st["operators"]))
    s.operators = set(st["operators"])
    ttl = st.get("auth_ttl", 600)  # stage-1 exports carry no authorizations
    _need(_int(ttl) and ttl >= 1)
    s.auth_ttl = ttl
    for a in st.get("authorizations", []):
        rec = {k: a[k] for k in ("id", "from_user_id", "to_user_id", "amount", "captured_amount",
                                 "note", "visibility", "status", "expires_at", "expires_ts",
                                 "payment_ids", "created_at", "ts", "seq")}
        _need(_id(rec["id"]) and rec["id"] not in s.auths_by_id)
        _need(rec["from_user_id"] in s.users and rec["to_user_id"] in s.users)
        _need(_amount(rec["amount"], 1) and _int(rec["captured_amount"])
              and 0 <= rec["captured_amount"] <= rec["amount"] and _str(rec["note"]))
        _need(rec["visibility"] in ("public", "private")
              and rec["status"] in ("open", "captured", "voided", "expired"))
        _ts_str(rec["expires_at"])
        _need(_num(rec["expires_ts"]))
        _need(isinstance(rec["payment_ids"], list) and all(_str(x) for x in rec["payment_ids"]))
        _ts_str(rec["created_at"])
        _need(_num(rec["ts"]) and _seq(rec["seq"]))
        s.auths.append(rec)
        s.auths_by_id[rec["id"]] = rec
        if rec["status"] == "open":
            s.open_auths[rec["id"]] = rec
    for uid, u in s.users.items():
        _need(held_of(s, uid) <= u["balance"])
    for a in s.auths:
        _need(all(pid in s.payments_by_id for pid in a["payment_ids"]))
    for p in s.payments:
        _need(p["authorization_id"] is None or p["authorization_id"] in s.auths_by_id)
    for p in s.payments:
        _need(p["request_id"] is None or p["request_id"] in s.requests_by_id)
        _need(p["settlement_id"] is None or p["settlement_id"] in s.settlements)
    for r in s.requests:
        _need(r["payment_id"] is None or r["payment_id"] in s.payments_by_id)
    _need(_int(st["seq"]))
    s.seq = max(st["seq"], max([p["seq"] for p in s.payments] + [r["seq"] for r in s.requests]
                         + [a["seq"] for a in s.auths] + [0]))
    check_receipts(s)
    return s


# --- idempotency receipts must agree with the imported records (immutable facts only) ---------

PATH_PAYMENTS = re.compile(r"/payments")
PATH_REQUESTS = re.compile(r"/requests")
PATH_PAY = re.compile(r"/requests/([^/]+)/pay")
PATH_SPLITS = re.compile(r"/splits")
PATH_SETTLEMENTS = re.compile(r"/settlements")
PATH_AUTHS = re.compile(r"/authorizations")
PATH_CAPTURE = re.compile(r"/authorizations/([^/]+)/capture")

REQUEST_KEYS = {"request_id", "requester_id", "requester_handle", "payer_id", "payer_handle", "amount",
                "currency", "note", "status", "payment_id", "created_at"}


def _payment_receipt(s, resp):
    from wallet import pay_view
    _need(isinstance(resp, dict) and resp.get("payment_id") in s.payments_by_id)
    expected = pay_view(s, s.payments_by_id[resp["payment_id"]])
    if "authorization_id" not in resp:  # receipts written before stage 2 have no such field
        expected.pop("authorization_id", None)
    _need(resp == expected)
    return s.payments_by_id[resp["payment_id"]]


def _request_receipt(s, resp):
    _need(isinstance(resp, dict) and set(resp) == REQUEST_KEYS and resp["request_id"] in s.requests_by_id)
    r = s.requests_by_id[resp["request_id"]]
    a, b = s.users[r["requester_id"]], s.users[r["payer_id"]]
    # status and payment_id are mutable: the receipt keeps the state at creation time
    _need(resp["requester_id"] == a["id"] and resp["requester_handle"] == a["handle"]
          and resp["payer_id"] == b["id"] and resp["payer_handle"] == b["handle"]
          and resp["amount"] == r["amount"] and resp["currency"] == s.currency
          and resp["note"] == r["note"] and resp["created_at"] == r["created_at"])
    _need(resp["status"] in STATUSES)
    _need(resp["payment_id"] is None or resp["payment_id"] in s.payments_by_id)
    return r


def _split_receipt(s, resp):
    _need(isinstance(resp, dict) and set(resp) == {"split_id", "amount", "currency", "note", "shares",
                                                    "requests", "created_at"})
    _need(_amount(resp["amount"], 1) and resp["currency"] == s.currency and _str(resp["note"]))
    _ts_str(resp["created_at"])
    shares = resp["shares"]
    _need(isinstance(shares, list) and shares)
    for sh in shares:
        _need(isinstance(sh, dict) and set(sh) == {"handle", "amount"} and sh["handle"] in s.by_handle
              and _amount(sh["amount"]))
    _need(sum(sh["amount"] for sh in shares) == resp["amount"])
    amounts = [sh["amount"] for sh in shares]
    _need(max(amounts) - min(amounts) <= 1 and amounts == sorted(amounts, reverse=True))
    _need(isinstance(resp["requests"], list))
    for rq in resp["requests"]:
        r = _request_receipt(s, rq)
        _need(rq["amount"] in amounts and s.users[r["payer_id"]]["handle"] in [sh["handle"] for sh in shares])


def _settlement_receipt(s, resp):
    _need(isinstance(resp, dict) and set(resp) == {"settlement_id", "committed_at", "payments"})
    st = s.settlements.get(resp["settlement_id"])
    _need(st is not None and resp["committed_at"] == st["committed_at"] and isinstance(resp["payments"], list)
          and [p.get("payment_id") if isinstance(p, dict) else None for p in resp["payments"]] == st["payment_ids"])
    for p in resp["payments"]:
        _need(_payment_receipt(s, p)["settlement_id"] == st["id"])


def _auth_receipt(s, resp):
    _need(isinstance(resp, dict) and resp.get("authorization_id") in s.auths_by_id)
    a = s.auths_by_id[resp["authorization_id"]]
    fu, tu = s.users[a["from_user_id"]], s.users[a["to_user_id"]]
    # captured_amount / remaining_amount / status / payment ids move with later captures: shape only
    _need(set(resp) == {"authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount",
                        "captured_amount", "remaining_amount", "currency", "note", "visibility", "status",
                        "expires_at", "payment_id", "payment_ids", "created_at"})
    _need(resp["from_user_id"] == fu["id"] and resp["from_handle"] == fu["handle"]
          and resp["to_user_id"] == tu["id"] and resp["to_handle"] == tu["handle"]
          and resp["amount"] == a["amount"] and resp["currency"] == s.currency and resp["note"] == a["note"]
          and resp["visibility"] == a["visibility"] and resp["expires_at"] == a["expires_at"]
          and resp["created_at"] == a["created_at"])
    _need(resp["status"] in ("open", "captured", "voided", "expired")
          and _int(resp["captured_amount"]) and 0 <= resp["captured_amount"] <= a["amount"]
          and _int(resp["remaining_amount"]) and 0 <= resp["remaining_amount"] <= a["amount"])
    _need(isinstance(resp["payment_ids"], list) and all(x in s.payments_by_id for x in resp["payment_ids"])
          and resp["payment_id"] == (resp["payment_ids"][-1] if resp["payment_ids"] else None))


def check_receipts(s):
    for (uid, key, path), (fp, resp) in s.idem.items():
        _need(uid in s.users and (fp.startswith("v2:") or isinstance(json.loads(fp), dict)))
        m = PATH_PAY.fullmatch(path)
        if PATH_PAYMENTS.fullmatch(path):
            p = _payment_receipt(s, resp)
            _need(p["from_user_id"] == uid and p["request_id"] is None and p["settlement_id"] is None
                  and p.get("authorization_id") is None)
        elif m:
            p = _payment_receipt(s, resp)
            _need(p["from_user_id"] == uid and p["request_id"] == m.group(1)
                  and s.requests_by_id[m.group(1)]["payer_id"] == uid)
        elif PATH_REQUESTS.fullmatch(path):
            _need(_request_receipt(s, resp)["requester_id"] == uid)
        elif PATH_SPLITS.fullmatch(path):
            _split_receipt(s, resp)
            _need(resp["split_id"] in s.splits)
        elif PATH_SETTLEMENTS.fullmatch(path):
            _settlement_receipt(s, resp)
        elif PATH_AUTHS.fullmatch(path):
            _auth_receipt(s, resp)
            _need(s.auths_by_id[resp["authorization_id"]]["from_user_id"] == uid)
        elif PATH_CAPTURE.fullmatch(path):
            c = PATH_CAPTURE.fullmatch(path).group(1)
            p = _payment_receipt(s, resp)
            _need(p.get("authorization_id") == c and c in s.auths_by_id
                  and s.auths_by_id[c]["to_user_id"] == uid)
        else:
            _need(False)
    for sid, sp in s.splits.items():
        _split_receipt(s, sp)
        _need(sp["split_id"] == sid)


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
