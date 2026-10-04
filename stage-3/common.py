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
        self.auths = []       # authorizations, insertion order
        self.auths_by_id = {}
        self.open_auths = {}  # id -> record, only status "open"
        self.auth_ttl = 600


store = types.SimpleNamespace(state=State())


def held_of(s, uid):
    return sum(a["amount"] - a["captured_amount"] for a in s.open_auths.values()
               if a["from_user_id"] == uid)


def available_of(s, user):
    return user["balance"] - held_of(s, user["id"])


def close_auth(s, a, status, closed_at=None, closed_ts=None):
    """Close a hold; closed_at is the event time (a whole-second RFC 3339 string)."""
    a["status"] = status
    a["closed_at"] = closed_at
    a["closed_ts"] = closed_ts
    s.open_auths.pop(a["id"], None)


def sweep(s, now):
    """Expire open authorizations whose deadline has passed (releases their remainder)."""
    for a in list(s.open_auths.values()):
        if a["expires_ts"] <= now:
            close_auth(s, a, "expired", a["expires_at"], float(int(a["expires_ts"])))


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


class _Huge(Decimal):
    """A JSON number whose exponent Decimal cannot represent: kept as a stand-in far outside any valid range."""


def _parse_float(text):
    try:
        return Decimal(text)
    except ArithmeticError:
        h = _Huge("-1E+999999999" if text.startswith("-") else "1E+999999999")
        h.text = text.lower()
        if "e-" in h.text:  # a vanishing magnitude: not integral, not an amount
            h = _Huge("-1E-999999999" if text.startswith("-") else "1E-999999999")
            h.text = text.lower()
        return h


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
                           parse_float=_parse_float if decimal else float,
                           parse_int=_big_int)
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


def decimal_int(d):
    """Exact integer value of a Decimal without arithmetic (no Overflow on huge exponents).
    Returns None when not integral; values beyond 10**25 collapse to +-10**30 (out of range anyway)."""
    sign, digits, exp = d.as_tuple()
    if not isinstance(exp, int):
        return None  # NaN / Infinity
    if not any(digits):
        return 0
    if exp >= 0:
        if exp + len(digits) > 25:
            return -(10 ** 30) if sign else 10 ** 30
        n = int("".join(map(str, digits))) * 10 ** exp
    else:
        k = -exp
        if len(digits) <= k or any(digits[-k:]):
            return None
        n = int("".join(map(str, digits[:-k])))
    return -n if sign else n


def parse_amount(body, field="amount"):
    if field not in body:
        raise validation(field + " is required")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, Decimal)):
        raise validation(field + " must be an integer")
    if isinstance(v, Decimal):  # exact decimal value: 1000.0 and 1e3 are fine, 1.0000000000000001 is not
        v = decimal_int(v)
        if v is None:
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

def _num(d):
    """Canonical text of a JSON number: equal values (1, 1.0, 1e0, 1.50 vs 1.5) give equal text."""
    if isinstance(d, _Huge):
        return "huge:" + d.text
    sign, digits, exp = d.as_tuple()
    digits = list(digits)
    if not any(digits):
        return "0"
    while digits[-1] == 0:
        digits.pop()
        exp += 1
    return ("-" if sign else "") + "".join(map(str, digits)) + "e" + str(exp)


def _canon(v):
    # numbers are bare tokens, strings are quoted: a number can never collide with a string
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, int):
        return _num(Decimal(v))
    if isinstance(v, Decimal):
        return _num(v)
    if isinstance(v, float):
        return _num(Decimal(repr(v)))
    if isinstance(v, dict):
        return "{" + ",".join(json.dumps(k) + ":" + _canon(x) for k, x in sorted(v.items())) + "}"
    return "[" + ",".join(_canon(x) for x in v) + "]"


def fingerprint(body):
    try:
        return "v2:" + _canon(body)
    except RecursionError:
        raise ApiError(400, "malformed_request", "body is nested too deeply")


def _legacy(v, floats):
    """Fingerprints written by earlier revisions (kept so imported exports still replay)."""
    if isinstance(v, Decimal):
        n = decimal_int(v)
        if n is not None and abs(n) < 10 ** 30:
            return n
        return float(v) if floats else str(v)
    if isinstance(v, dict):
        return {k: _legacy(x, floats) for k, x in v.items()}
    if isinstance(v, list):
        return [_legacy(x, floats) for x in v]
    return v


def same_body(stored, body):
    fp = fingerprint(body)
    if stored == fp:
        return True
    if stored.startswith("v2:"):
        return False
    for floats in (True, False):
        try:
            if stored == json.dumps(_legacy(body, floats), sort_keys=True, separators=(",", ":")):
                return True
        except (ValueError, OverflowError, RecursionError):
            pass
    return False


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
    rec = s.idem.get(ik)
    if rec is not None:
        if same_body(rec[0], body):
            return 200, rec[1]
        raise ApiError(409, "idempotency_key_reuse", "key already used with a different body")
    resp = handler(body)
    s.idem[ik] = (fingerprint(body), resp)
    return 201, resp
