"""One shared invariant checker for service state, used by reset (fixture-derived state) and import.

Every stored record type is checked against the API's field rules and the model's cross-record
rules. Raises ValueError on the first violation. Identical in stage 1 and stage 2 (stage 1 has no
authorizations: those parts see empty collections)."""
import math
import time

from ledger import history_ok, instants_agree
from common import HANDLE_RE, MAX_AMOUNT, STATUSES, parse_ts

try:
    from common import held_of
except ImportError:  # stage 1 has no holds
    def held_of(s, uid):
        return 0


def _need(cond):
    if not cond:
        raise ValueError("inconsistent state")


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _amount(v, lo=0):
    return _int(v) and lo <= v <= MAX_AMOUNT


def _ts_ok(text, ts):
    """text is RFC 3339 with an offset and ts is (to the second) the instant it names."""
    _need(isinstance(text, str) and isinstance(ts, (int, float)) and not isinstance(ts, bool) and math.isfinite(ts))
    _need(text.endswith("Z") or text[-6:-5] in "+-")
    _need(math.floor(parse_ts(text)[0]) == math.floor(ts))


def check_state_invariants(s):
    _need(isinstance(s.currency, str) and s.currency and s.minor_units in (0, 2, 3))
    for uid, u in s.users.items():
        _need(u["id"] == uid and 1 <= len(uid) <= 64 and HANDLE_RE.fullmatch(u["handle"]))
        _need(isinstance(u["email"], str) and isinstance(u["display_name"], str))
        _need(_int(u["balance"]) and 0 <= u["balance"] <= 2 ** 53)
        _need(s.by_handle.get(u["handle"]) is u)
    for uid, u in s.users.items():  # the ledger: balance = opening + the net effect of every latest revision
        net = 0
        for p in s.payments:
            if uid in (p["from_user_id"], p["to_user_id"]):
                amt = p["revisions"][-1]["amount"]
                net += -amt if p["from_user_id"] == uid else amt
        _need(_int(u["opening"]) and u["balance"] == u["opening"] + net)
    for tok, uid in s.tokens.items():
        _need(isinstance(tok, str) and tok and uid in s.users)

    refunded = {}
    auths = getattr(s, "auths", [])
    auths_by_id = getattr(s, "auths_by_id", {})
    seqs = []
    for p in s.payments:
        _need(p["from_user_id"] in s.users and p["to_user_id"] in s.users and p["from_user_id"] != p["to_user_id"])
        _need(_amount(p["amount"]) and isinstance(p["note"], str) and len(p["note"]) <= 200)
        _need(p["visibility"] in ("public", "private"))
        _ts_ok(p["created_at"], p["ts"])
        revs = p["revisions"]
        _need(isinstance(revs, list) and revs and revs[0]["revision"] == 1 and revs[0]["amount"] == p["amount"]
              and revs[0]["effective_at"] == p["created_at"] == revs[0]["recorded_at"])
        for i, r in enumerate(revs, 1):
            _need(r["revision"] == i and _amount(r["amount"]) and isinstance(r["reason"], str) and len(r["reason"]) <= 200)
            _need(i == 1 or (r["reason"] and r["recorded_ts"] > revs[i - 2]["recorded_ts"]
                             and p["settlement_id"] is None and p.get("authorization_id") is None))
            _ts_ok(r["effective_at"], r["effective_ts"])
            _ts_ok(r["recorded_at"], r["recorded_ts"])
            _need(instants_agree(r["effective_at"], r["effective_ts"]) and instants_agree(r["recorded_at"], r["recorded_ts"]))
        seqs.append(p["seq"])
        rid = p["request_id"]
        rof = p.get("refund_of")
        if rof is not None:  # a refund: the target's receiver paying back, an ordinary immutable payment
            t = s.payments_by_id.get(rof)
            _need(t is not None and t.get("refund_of") is None and p["from_user_id"] == t["to_user_id"]
                  and p["to_user_id"] == t["from_user_id"] and p["note"] == t["note"]
                  and p["visibility"] == t["visibility"] and rid is None and p["settlement_id"] is None
                  and p.get("authorization_id") is None and len(revs) == 1)
        refunded[rof] = refunded.get(rof, 0) + p["amount"] if rof is not None else 0
        if rid is not None:  # a payment for a request: that request is paid by exactly this payment
            r = s.requests_by_id.get(rid)
            _need(r is not None and r["status"] == "paid" and r["payment_id"] == p["id"])
            _need(p["amount"] == r["amount"] and p["from_user_id"] == r["payer_id"]
                  and p["to_user_id"] == r["requester_id"])
        sid = p["settlement_id"]
        if sid is not None:
            st = s.settlements.get(sid)
            _need(st is not None and p["id"] in st["payment_ids"] and rid is None
                  and p["created_at"] == st["committed_at"])
        aid = p.get("authorization_id")
        if aid is not None:
            a = auths_by_id.get(aid)
            _need(a is not None and p["id"] in a["payment_ids"] and rid is None and sid is None)
            _need(p["from_user_id"] == a["from_user_id"] and p["to_user_id"] == a["to_user_id"]
                  and p["visibility"] == a["visibility"] and p["note"] == a["note"])
    for tid, total in refunded.items():  # refunds never exceed the payment's current corrected amount
        if tid is not None:
            _need(total <= s.payments_by_id[tid]["revisions"][-1]["amount"])
    for r in s.requests:
        _need(r["requester_id"] in s.users and r["payer_id"] in s.users and r["requester_id"] != r["payer_id"])
        _need(_amount(r["amount"]) and isinstance(r["note"], str) and len(r["note"]) <= 200)
        _need(r["status"] in STATUSES)
        _ts_ok(r["created_at"], r["ts"])
        seqs.append(r["seq"])
        pid = r["payment_id"]
        if pid is not None:  # linked only when paid, and the payment points back with the same facts
            p = s.payments_by_id.get(pid)
            _need(r["status"] == "paid" and p is not None and p["request_id"] == r["id"]
                  and p["amount"] == r["amount"] and p["from_user_id"] == r["payer_id"]
                  and p["to_user_id"] == r["requester_id"])
    for sid, st in s.settlements.items():
        ids = st["payment_ids"]
        members = [p for p in s.payments if p["settlement_id"] == sid]
        _need(1 <= len(ids) <= 32 and ids == [p["id"] for p in sorted(members, key=lambda p: p["seq"])])
        _need(all(p["created_at"] == st["committed_at"] and p["request_id"] is None for p in members))
    for a in auths:
        _need(a["from_user_id"] in s.users and a["to_user_id"] in s.users and a["from_user_id"] != a["to_user_id"])
        _need(_amount(a["amount"], 1) and _int(a["captured_amount"]) and 0 <= a["captured_amount"] <= a["amount"])
        _need(isinstance(a["note"], str) and len(a["note"]) <= 200 and a["visibility"] in ("public", "private"))
        _need(a["status"] in ("open", "captured", "voided", "expired"))
        _need((a["status"] == "open") == (a["closed_at"] is None) == (a["closed_ts"] is None))
        if a["closed_at"] is not None:
            _ts_ok(a["closed_at"], a["closed_ts"])
            _need(instants_agree(a["closed_at"], a["closed_ts"]))
        _ts_ok(a["created_at"], a["ts"])
        _ts_ok(a["expires_at"], a["expires_ts"])
        _need(instants_agree(a["expires_at"], a["expires_ts"]))
        seqs.append(a["seq"])
        caps = [s.payments_by_id.get(pid) for pid in a["payment_ids"]]
        _need(all(c is not None and c.get("authorization_id") == a["id"] for c in caps))
        if caps:  # captures are the only source of captured_amount
            _need(sum(c["amount"] for c in caps) == a["captured_amount"])
        if a["status"] == "open":
            _need(a["captured_amount"] < a["amount"] and a["id"] in s.open_auths)
        else:
            _need(a["id"] not in s.open_auths)
    for uid in s.users:
        _need(held_of(s, uid) <= s.users[uid]["balance"])
    now = time.time()  # corrected history must stay nonnegative (total and available) at every past boundary,
    for uid in s.users:  # unless the seeded/original history was already inconsistent for that user
        if history_ok(s, [uid], None, now, originals=True):
            _need(history_ok(s, [uid], None, now))
    _need(len(set(seqs)) == len(seqs))

    for sid, sp in s.splits.items():
        _need(isinstance(sp, dict) and sp.get("split_id") == sid and isinstance(sp.get("note"), str)
              and len(sp["note"]) <= 200 and _amount(sp.get("amount"), 1))
        shares = sp["shares"]
        _need(shares and sum(x["amount"] for x in shares) == sp["amount"])
        by_handle = {x["handle"]: x["amount"] for x in shares}
        _need(len(by_handle) == len(shares) and all(h in s.by_handle for h in by_handle))
        for rq in sp["requests"]:
            r = s.requests_by_id.get(rq.get("request_id"))
            _need(r is not None and r["note"] == sp["note"] and r["amount"] == rq["amount"]
                  and by_handle.get(rq["payer_handle"]) == r["amount"]
                  and s.users[r["payer_id"]]["handle"] == rq["payer_handle"])
