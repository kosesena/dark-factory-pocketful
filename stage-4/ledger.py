"""Temporal ledger: instants, payment revisions, balances and holds as of a time / known at a time.

Two clocks. A payment revision is *effective* at effective_ts (when the money took effect) and was
*recorded* at recorded_ts (when the service learned it). A view is asked for as of T (effective) and
known at K (recorded). Original payments are revision 1 with effective = recorded = created_at.
All instants of stored records are whole seconds except correction recorded times (microseconds,
strictly increasing per payment)."""
import math
import re
from datetime import datetime

from common import validation

INSTANT_RE = re.compile(r"\d{4}-\d\d-\d\d[Tt]\d\d:\d\d:\d\d(\.\d+)?([Zz]|[+-]\d\d:\d\d)")
INF = float("inf")


def parse_instant(text):
    """RFC 3339 instant with an explicit offset -> epoch seconds; ValueError for anything else."""
    if not isinstance(text, str) or not INSTANT_RE.fullmatch(text):
        raise ValueError("not an RFC 3339 instant")
    try:
        dt = datetime.fromisoformat(text[:-1] + "+00:00" if text[-1] in "Zz" else text)
        if dt.tzinfo is None:
            raise ValueError("no offset")
        return dt.timestamp()
    except (OverflowError, OSError):
        raise ValueError("instant out of range")


def instant_param(query, name):
    """None when absent; (epoch seconds, text exactly as given) when valid; 422 otherwise."""
    if name not in query:
        return None
    raw = query[name]
    try:
        return parse_instant(raw), raw
    except ValueError:
        raise validation(name + " must be an RFC 3339 instant with an offset")


def whole(ts):
    return float(math.floor(ts))


def first_revision(p):
    t = whole(p["ts"])
    return {"revision": 1, "amount": p["amount"], "effective_at": p["created_at"], "effective_ts": t,
            "recorded_at": p["created_at"], "recorded_ts": t, "reason": "", "correction_batch_id": None}


def ensure_revisions(p):
    if "revisions" not in p:
        p["revisions"] = [first_revision(p)]


def selected_revision(p, known):
    """Latest revision recorded at or before `known` (None = everything known); None if none yet."""
    if known is None:
        return p["revisions"][-1]
    best = None
    for r in p["revisions"]:
        if r["recorded_ts"] <= known:
            best = r
    return best


def delta_of(p, uid, amount):
    if p["from_user_id"] == uid:
        return -amount
    if p["to_user_id"] == uid:
        return amount
    return 0


def instants_agree(text, ts):
    """The string form must be the exact rendering of the stored numeric instant (microsecond precision)."""
    try:
        return abs(parse_instant(text) - ts) < 1e-6
    except ValueError:
        return False


def effects(s, uid, known, override=None, originals=False):
    """[(effective_ts, payment id, revision, delta)] for payments of uid under the selection."""
    out = []
    for p in s.payments:
        if p["from_user_id"] != uid and p["to_user_id"] != uid:
            continue
        r = p["revisions"][0] if originals else (
            override[p["id"]] if override and p["id"] in override else selected_revision(p, known))
        if r is None:
            continue
        out.append((r["effective_ts"], p["id"], r, delta_of(p, uid, r["amount"])))
    return out


def compute_opening(s, uid):
    """Seeded/imported opening balance: current balance minus the net effect of every payment."""
    net = 0
    for p in s.payments:
        net += delta_of(p, uid, p["revisions"][-1]["amount"])
    return s.users[uid]["balance"] - net


def balance_at(s, uid, as_of, known):
    total = s.users[uid]["opening"]
    for eff, _, _, d in effects(s, uid, known):
        if as_of is None or eff <= as_of:
            total += d
    return total


def _created(a):
    return whole(a["ts"])


def held_at(s, uid, as_of, known, now):
    """Held funds of uid in the view (as_of, known). A hold starts at creation; captures reduce it
    when they happen; a final capture, void or expiry releases the rest at that event's time; clock
    expiry is known as soon as the creation is."""
    t = now if as_of is None else as_of
    k = INF if known is None else known
    m = min(t, k)
    total = 0
    for a in s.auths:
        if a["from_user_id"] != uid or _created(a) > m:
            continue
        closed = a.get("closed_ts")
        release = closed if (closed is not None and closed <= k) else whole(a["expires_ts"])
        if release <= t:
            continue
        caps = [s.payments_by_id[pid] for pid in a["payment_ids"]]
        linked = sum(c["amount"] for c in caps)
        early = a["captured_amount"] - linked  # seeded captures with no linked payment: at creation
        done = early + sum(c["amount"] for c in caps if whole(c["ts"]) <= m)
        total += a["amount"] - done
    return total


def view_balances(s, user, as_of, known, now):
    uid = user["id"]
    total = balance_at(s, uid, as_of, known)
    held = held_at(s, uid, as_of, known, now)
    return {"balance": total, "total": total, "available": total - held, "held": held}


def history_ok(s, uids, override, now, originals=False):
    """No total or available is negative at any past effective/event boundary, under the latest
    known revisions with `override` applied. Movements at one instant are combined."""
    for uid in uids:
        ev = sorted((e[0], e[3]) for e in effects(s, uid, None, override, originals))
        mine = [a for a in s.auths if a["from_user_id"] == uid]
        times = {t for t, _ in ev if t <= now}
        for a in mine:
            times.add(_created(a))
            for pid in a["payment_ids"]:
                times.add(whole(s.payments_by_id[pid]["ts"]))
            if a.get("closed_ts") is not None:
                times.add(a["closed_ts"])
            times.add(whole(a["expires_ts"]))
        times = sorted(t for t in times if t <= now)
        total = s.users[uid]["opening"]
        i = 0
        for t in times:
            while i < len(ev) and ev[i][0] <= t:
                total += ev[i][1]
                i += 1
            if total < 0:
                return False
            if mine and total - held_at_override(s, uid, t, now) < 0:
                return False
        total += sum(d for t, d in ev[i:] if t <= now)
        if total < 0:
            return False
    return True


def held_at_override(s, uid, t, now):
    return held_at(s, uid, t, None, now)
