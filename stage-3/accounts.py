"""Health, reset, signup, login and /me."""
import re
from concurrent.futures import ThreadPoolExecutor
import time

from invariants import check_state_invariants
from common import (MAX_AMOUNT, ApiError, State, available_of, held_of, store, sweep, STATUSES, HANDLE_RE, EMAIL_RE, authenticate,
                    check_password, get_str, hash_password, new_id, next_seq, now_ts,
                    parse_json, parse_ts, validation)


SEED_KDF_N = 2 ** 10  # seeded fixture passwords: cheaper scrypt keeps a 1000+ user reset well under 10 s


def health(req):
    return 200, {"status": "ok"}


def _int(v, lo=0, hi=None):
    if isinstance(v, bool):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, int) and v >= lo and (hi is None or v <= hi):
        return v
    return None


def build_state(fx):
    s = State()
    cur = fx.get("currency", "EUR")
    mu = fx.get("minor_units", 2)
    if not isinstance(cur, str) or not cur:
        raise validation("currency must be a non-empty string")
    if isinstance(mu, bool) or mu not in (0, 2, 3):
        raise validation("minor_units must be 0, 2 or 3")
    s.currency, s.minor_units = cur, mu

    def lst(name):
        v = fx.get(name, [])
        if not isinstance(v, list) or not all(isinstance(x, dict) for x in v):
            raise validation(name + " must be an array of objects")
        return v

    pending = []  # (user record, password) hashed together after validation
    for u in lst("users"):
        uid, handle = u.get("id"), u.get("handle")
        email, pw = u.get("email"), u.get("password")
        if not isinstance(uid, str) or not uid or len(uid) > 64 or uid in s.users:
            raise validation("bad or duplicate user id")
        if not isinstance(handle, str) or not HANDLE_RE.fullmatch(handle) or handle in s.by_handle:
            raise validation("bad or duplicate handle")
        if not isinstance(email, str) or email.lower() in s.by_email:
            raise validation("bad or duplicate email")
        if not isinstance(pw, str):
            raise validation("password must be a string")
        name = u.get("display_name", handle)
        if not isinstance(name, str):
            raise validation("display_name must be a string")
        bal = _int(u.get("balance", 0), 0, 2 ** 53)
        if bal is None:
            raise validation("balance must be a non-negative integer")
        rec = {"id": uid, "email": email, "display_name": name, "handle": handle,
               "balance": bal, "salt": "", "hash": "", "n": SEED_KDF_N}
        pending.append((rec, pw))
        s.users[uid] = rec
        s.by_handle[handle] = rec
        s.by_email[email.lower()] = rec

    def hash_one(item):
        rec, pw = item
        rec["salt"], rec["hash"] = hash_password(pw, SEED_KDF_N)
    with ThreadPoolExecutor(2) as pool:  # scrypt releases the GIL: two cores hash seeded users
        list(pool.map(hash_one, pending))

    def stamp(item, rec):
        if "created_at" in item and item["created_at"] is not None:
            try:
                rec["ts"], rec["created_at"] = parse_ts(item["created_at"])
            except (ValueError, OverflowError, OSError):
                raise validation("bad created_at")
        else:
            rec["ts"], rec["created_at"] = now_ts()
        rec["seq"] = next_seq(s)

    for p in lst("payments"):
        pid = p.get("id") if p.get("id") is not None else new_id("p_")
        amt = _int(p.get("amount"), 0, MAX_AMOUNT)
        note = p.get("note", "")
        vis = p.get("visibility", "public")
        if (not isinstance(pid, str) or not pid or len(pid) > 64 or pid in s.payments_by_id
                or p.get("from_user_id") not in s.users or p.get("to_user_id") not in s.users
                or amt is None or not isinstance(note, str) or len(note) > 200 or vis not in ("public", "private")
                or p.get("from_user_id") == p.get("to_user_id")
                or not isinstance(vis, str)):
            raise validation("bad payment")
        rec = {"id": pid, "from_user_id": p["from_user_id"], "to_user_id": p["to_user_id"],
               "amount": amt, "note": note, "visibility": vis,
               "request_id": p.get("request_id"), "settlement_id": None,
               "authorization_id": None}
        stamp(p, rec)
        s.payments.append(rec)
        s.payments_by_id[pid] = rec

    for r in lst("requests"):
        rid = r.get("id") if r.get("id") is not None else new_id("rq_")
        amt = _int(r.get("amount"), 0, MAX_AMOUNT)
        note = r.get("note", "")
        status = r.get("status", "pending")
        if (not isinstance(rid, str) or not rid or len(rid) > 64 or rid in s.requests_by_id
                or r.get("requester_id") not in s.users or r.get("payer_id") not in s.users
                or amt is None or not isinstance(note, str) or len(note) > 200 or status not in STATUSES
                or r.get("requester_id") == r.get("payer_id")
                or not isinstance(status, str)):
            raise validation("bad request")
        rec = {"id": rid, "requester_id": r["requester_id"], "payer_id": r["payer_id"],
               "amount": amt, "note": note, "status": status,
               "payment_id": r.get("payment_id")}
        stamp(r, rec)
        s.requests.append(rec)
        s.requests_by_id[rid] = rec

    for r in s.requests:  # a seeded paid request's payment points back at it
        p = s.payments_by_id.get(r["payment_id"]) if r["payment_id"] is not None else None
        if p is not None and p["request_id"] is None:
            p["request_id"] = r["id"]
    for p in s.payments:
        if p["request_id"] is not None and p["request_id"] not in s.requests_by_id:
            raise validation("payment refers to an unknown request")
    for r in s.requests:
        if r["payment_id"] is not None and r["payment_id"] not in s.payments_by_id:
            raise validation("request refers to an unknown payment")

    ttl = fx.get("authorization_ttl_seconds", 600)
    if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl < 1:
        raise validation("authorization_ttl_seconds must be a positive integer")
    s.auth_ttl = ttl
    now = time.time()
    for a in lst("authorizations"):
        aid = a.get("id") if a.get("id") is not None else new_id("a_")
        amt = _int(a.get("amount"), 1, MAX_AMOUNT)
        cap = _int(a.get("captured_amount", 0 if a.get("status", "open") != "captured" else a.get("amount")))
        note = a.get("note", "")
        vis = a.get("visibility", "public")
        status = a.get("status", "open")
        pids = a.get("payment_ids", [])
        if (not isinstance(aid, str) or not aid or len(aid) > 64 or aid in s.auths_by_id
                or a.get("from_user_id") not in s.users or a.get("to_user_id") not in s.users
                or amt is None or cap is None or cap > amt or not isinstance(note, str) or len(note) > 200
                or a.get("from_user_id") == a.get("to_user_id")
                or vis not in ("public", "private") or not isinstance(vis, str)
                or status not in ("open", "captured", "voided", "expired")
                or not isinstance(status, str)
                or not isinstance(pids, list) or not all(isinstance(x, str) for x in pids)):
            raise validation("bad authorization")
        try:
            ets, eat = parse_ts(a.get("expires_at"))
        except (ValueError, OverflowError, OSError):
            raise validation("bad expires_at")
        rec = {"id": aid, "from_user_id": a["from_user_id"], "to_user_id": a["to_user_id"],
               "amount": amt, "captured_amount": cap, "note": note, "visibility": vis,
               "status": status, "expires_at": eat, "expires_ts": ets, "payment_ids": list(pids)}
        stamp(a, rec)
        s.auths.append(rec)
        s.auths_by_id[aid] = rec
        if status == "open":
            s.open_auths[aid] = rec
    for au in s.auths:
        if any(pid not in s.payments_by_id for pid in au["payment_ids"]):
            raise validation("authorization refers to an unknown payment")
    for au in s.auths:  # seeded captures point back at their authorization
        for pid in au["payment_ids"]:
            if s.payments_by_id[pid].get("authorization_id") is None:
                s.payments_by_id[pid]["authorization_id"] = au["id"]
    sweep(s, now)
    for uid, u in s.users.items():
        if held_of(s, uid) > u["balance"]:
            raise validation("seeded holds exceed the balance")

    ops = fx.get("settlement_operator_ids", [])
    if not isinstance(ops, list) or not all(isinstance(x, str) for x in ops):
        raise validation("settlement_operator_ids must be an array of strings")
    s.operators = set(ops)
    try:
        check_state_invariants(s)
    except (ValueError, KeyError, TypeError):
        raise validation("fixture is inconsistent")
    return s


def reset(req):
    fx = parse_json(req.raw, decimal=False)
    store.state = build_state(fx)
    return 204, None


def _user_auth_body(user, token):
    return {"user_id": user["id"], "display_name": user["display_name"], "token": token}


def _issue_token(s, user):
    import secrets
    token = secrets.token_urlsafe(32)
    s.tokens[token] = user["id"]
    return token


def signup(req):
    body = parse_json(req.raw)
    email = get_str(body, "email")
    password = get_str(body, "password")
    name = get_str(body, "display_name")
    if not EMAIL_RE.fullmatch(email) or email.count("@") != 1:
        raise validation("email must look like local@domain")
    if len(password) < 8:
        raise validation("password must be at least 8 characters")
    s = store.state
    if email.lower() in s.by_email:
        raise ApiError(409, "email_taken", "email already registered")
    local = email.split("@", 1)[0]
    handle = re.sub(r"[^a-z0-9_]", "_", local.lower())[:20]
    if handle in s.by_handle:
        raise ApiError(409, "handle_taken", "derived handle already taken")
    salt, h = hash_password(password)
    user = {"id": new_id("u_"), "email": email, "display_name": name, "handle": handle,
            "balance": 0, "salt": salt, "hash": h, "n": 2 ** 12}
    s.users[user["id"]] = user
    s.by_handle[handle] = user
    s.by_email[email.lower()] = user
    return 201, _user_auth_body(user, _issue_token(s, user))


def login(req):
    body = parse_json(req.raw)
    email = get_str(body, "email")
    password = get_str(body, "password")
    s = store.state
    user = s.by_email.get(email.lower())
    if user is None or not check_password(user, password):
        raise ApiError(401, "unauthenticated", "wrong email or password")
    return 200, _user_auth_body(user, _issue_token(s, user))


def me(req):
    user = authenticate(req)
    s = store.state
    return 200, {"user_id": user["id"], "display_name": user["display_name"],
                 "handle": user["handle"], "balance": user["balance"],
                 "total": user["balance"], "available": available_of(s, user),
                 "held": held_of(s, user["id"]),
                 "currency": s.currency, "minor_units": s.minor_units}


ROUTES = [
    ("GET", r"/health", health),
    ("POST", r"/_test/reset", reset),
    ("POST", r"/auth/signup", signup),
    ("POST", r"/auth/login", login),
    ("GET", r"/me", me),
]
