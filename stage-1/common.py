"""Shared state, errors, validation helpers and the idempotency wrapper."""
import hashlib
import hmac
import json
import os
import re
import threading
import time
import types
import uuid
from decimal import Decimal
from datetime import datetime, timezone

LOCK = threading.RLock()  # every handler runs under this lock: money moves serially
MAX_AMOUNT = 1_000_000_000
HANDLE_RE = re.compile(r"[a-z0-9_]{1,20}")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+")
DIGITS_RE = re.compile(r"[0-9]+", re.ASCII)
STATUSES = ("pending", "paid", "declined", "cancelled")


class ApiError(Exception):
    def __init__(self, status, code, message=""):
        super().__init__(message or code)
        self.status = status
        self.code = code
        self.message = message or code


class State:
    def __init__(self):
        self.currency = "EUR"
        self.minor_units = 2
        self.users = {}       # id -> record
        self.by_handle = {}   # handle -> record
        self.by_email = {}    # lowercased email -> record
        self.tokens = {}      # token -> user id
        self.payments = []    # insertion order
        self.payments_by_id = {}
        self.requests = []
        self.requests_by_id = {}
        self.splits = {}      # id -> original response
        self.settlements = {}  # id -> {id, committed_at, payment_ids}
        self.idem = {}        # (user id, key, path) -> (fingerprint, response)
        self.operators = set()
        self.seq = 0


store = types.SimpleNamespace(state=State())


def next_seq(s):
    s.seq += 1
    return s.seq


def new_id(prefix):
    return prefix + uuid.uuid4().hex[:16]


def fmt_ts(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def parse_ts(value):
    """Parse a fixture/import timestamp into (epoch seconds, normalised string)."""
    if not isinstance(value, str):
        raise ValueError("timestamp")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ts = dt.timestamp()
    return ts, fmt_ts(ts)


def now_ts():
    ts = time.time()
    return ts, fmt_ts(ts)


# --- passwords -------------------------------------------------------------

def _scrypt(password, salt, n=2 ** 12):
    return hashlib.scrypt(password.encode("utf-8", "surrogatepass"), salt=salt,
                          n=n, r=8, p=1, dklen=32)


def hash_password(password, n=2 ** 12):
    salt = os.urandom(16)
    return salt.hex(), _scrypt(password, salt, n).hex()


def check_password(user, password):
    got = _scrypt(password, bytes.fromhex(user["salt"]), user.get("n", 2 ** 12))
    return hmac.compare_digest(got, bytes.fromhex(user["hash"]))


# --- request parsing -------------------------------------------------------

def _no_const(name):
    raise ValueError(name)


def _big_int(text):
    # huge integers stay exact Decimals (range-checked later) instead of tripping int()'s digit limit
    return int(text) if len(text) <= 18 else Decimal(text)


def parse_json(raw, allow_empty=False, decimal=True):
    """decimal=True parses JSON fractions exactly (API bodies); test endpoints keep floats."""
    if not raw.strip():
        if allow_empty:
            return {}
        raise ApiError(400, "malformed_request", "request body is required")
    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=_no_const,
                           parse_float=Decimal if decimal else float,
                           parse_int=_big_int if decimal else int)
    except (ValueError, RecursionError):
        raise ApiError(400, "malformed_request", "body is not valid JSON")
    if not isinstance(value, dict):
        raise ApiError(400, "malformed_request", "body must be a JSON object")
    return value


def validation(msg):
    return ApiError(422, "validation_failed", msg)


def get_str(body, field, required=True):
    if field not in body:
        if required:
            raise validation(field + " is required")
        return None
    v = body[field]
    if not isinstance(v, str):
        raise ApiError(400, "malformed_request", field + " must be a string")
    return v


def parse_amount(body, field="amount"):
    if field not in body:
        raise validation(field + " is required")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, Decimal)):
        raise validation(field + " must be an integer")
    if isinstance(v, Decimal):  # exact decimal value: 1000.0 and 1e3 are fine, 1.0000000000000001 is not
        if v != v.to_integral_value():
            raise validation(field + " must be an integer")
    if v < 1 or v > MAX_AMOUNT:
        raise validation(field + " out of range")
    return int(v)


def parse_note(body):
    if "note" not in body:
        return ""
    v = body["note"]
    if not isinstance(v, str):
        raise validation("note must be a string")
    if len(v) > 200:
        raise validation("note too long")
    return v


def parse_visibility(body):
    if "visibility" not in body:
        return "public"
    v = body["visibility"]
    if v not in ("public", "private") or not isinstance(v, str):
        raise validation("visibility must be public or private")
    return v


def parse_page(query):
    def num(name, default, lo, hi):
        if name not in query:
            return default
        v = query[name]
        if not DIGITS_RE.fullmatch(v):
            raise validation(name + " must be plain decimal digits")
        v = v.lstrip("0") or "0"
        n = int(v) if len(v) <= 18 else 10 ** 18  # avoids Python's int() digit limit; still out of range
        if n < lo or (hi is not None and n > hi):
            raise validation(name + " out of range")
        return n
    return num("limit", 50, 1, 200), num("offset", 0, 0, None)


def paginate(items, query):
    limit, offset = parse_page(query)
    return items[offset:offset + limit], len(items) > offset + limit


# --- auth ------------------------------------------------------------------

def authenticate(req):
    s = store.state
    parts = req.headers.get("Authorization", "").split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise ApiError(401, "unauthenticated", "missing or malformed bearer token")
    user = s.users.get(s.tokens.get(parts[1].strip()))
    if user is None:
        raise ApiError(401, "unauthenticated", "unknown token")
    return user


# --- idempotency -----------------------------------------------------------

def _norm(v):
    if isinstance(v, Decimal):
        if v == v.to_integral_value() and abs(v) < 10 ** 30:
            return int(v)
        return format(v.normalize(), "f")  # 1.5 and 1.50 are the same JSON value
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_norm(x) for x in v]
    return v


def fingerprint(body):
    return json.dumps(_norm(body), sort_keys=True, separators=(",", ":"))


def idempotent(req, user, handler):
    """Run handler(body) -> response dict at most once per (user, key, path)."""
    key = req.headers.get("Idempotency-Key")
    if key is None or key.strip() == "":
        raise ApiError(400, "missing_idempotency_key", "Idempotency-Key header is required")
    body = parse_json(req.raw)
    if len(key) > 255:
        raise validation("Idempotency-Key must be 1 to 255 characters")
    s = store.state
    ik = (user["id"], key, req.path)
    fp = fingerprint(body)
    rec = s.idem.get(ik)
    if rec is not None:
        if rec[0] == fp:
            return 200, rec[1]
        raise ApiError(409, "idempotency_key_reuse", "key already used with a different body")
    resp = handler(body)
    s.idem[ik] = (fp, resp)
    return 201, resp
