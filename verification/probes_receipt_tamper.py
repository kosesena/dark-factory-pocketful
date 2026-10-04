#!/usr/bin/env python3
"""Reviewer's receipt tamper sweep for stage 4 (§10 invalid state -> 422 without changing the
destination; receipts must stay valid and original). Builds refunds, a single correction and a
correction batch (with a whole settlement), exports, corrupts one stored idempotent receipt at a
time and expects 422 with the destination unchanged; the genuine export must import and every
retry must replay its original body.

Targets this implementation's export layout: state.idempotency = [[user_id, key, path, fp, response], ...].

Usage: python3 probes_receipt_tamper.py http://localhost:8080
"""
import copy
import json
import sys
import time
import urllib.error
import urllib.request

B = sys.argv[1].rstrip("/")
RESULTS = []


def call(m, p, body=None, tok=None, key=None):
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if tok:
        h["Authorization"] = "Bearer " + tok
    if key:
        h["Idempotency-Key"] = key
    r = urllib.request.Request(B + p, data=None if body is None else json.dumps(body).encode(), method=m, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=20) as x:
            t = x.read()
            return x.status, (json.loads(t) if t else None)
    except urllib.error.HTTPError as e:
        t = e.read()
        return e.code, (json.loads(t) if t else None)


def check(n, c, d=""):
    RESULTS.append((n, bool(c), d))


U = [{"id": "u_a", "email": "a@x.io", "password": "password", "display_name": "A", "handle": "a", "balance": 5000},
     {"id": "u_b", "email": "b@x.io", "password": "password", "display_name": "B", "handle": "b", "balance": 1000},
     {"id": "u_op", "email": "o@x.io", "password": "password", "display_name": "O", "handle": "op", "balance": 0}]
call("POST", "/_test/reset", {"currency": "EUR", "minor_units": 2, "users": U, "payments": [], "requests": [],
                              "settlement_operator_ids": ["u_op"]})
ta, tb, to = [call("POST", "/auth/login", {"email": u["email"], "password": "password"})[1]["token"] for u in U]
calls = []


def rec(m, p, body, tok, key):
    st, r = call(m, p, body, tok, key)
    calls.append((m, p, body, tok, key, r))
    return st, r


st, p1 = rec("POST", "/payments", {"to_handle": "b", "amount": 300}, ta, "p1")
st, p2 = rec("POST", "/payments", {"to_handle": "b", "amount": 200}, ta, "p2")
st, se = rec("POST", "/settlements", {"transfers": [{"from_handle": "a", "to_handle": "b", "amount": 40},
                                                    {"from_handle": "b", "to_handle": "a", "amount": 10}]}, to, "se")
st, rf = rec("POST", "/payments/%s/refunds" % p1["payment_id"], {"amount": 50}, tb, "rf")
time.sleep(1.1)
st, co = rec("POST", "/payments/%s/corrections" % p2["payment_id"], {"expected_revision": 1, "amount": 150,
             "effective_at": p2["created_at"], "reason": "c"}, ta, "co")
time.sleep(1.1)
items = [{"payment_id": p1["payment_id"], "expected_revision": 1, "amount": 250, "effective_at": p1["created_at"], "reason": "b"},
         {"payment_id": se["payments"][0]["payment_id"], "expected_revision": 1, "amount": 30, "effective_at": se["committed_at"], "reason": "b"},
         {"payment_id": se["payments"][1]["payment_id"], "expected_revision": 1, "amount": 5, "effective_at": se["committed_at"], "reason": "b"}]
st, bt = rec("POST", "/correction-batches", {"corrections": items}, to, "bt")
check("setup: all writes succeeded", all(c[5] and "error" not in c[5] for c in calls), [c[5] for c in calls if c[5] and "error" in c[5]])
st, ex = call("GET", "/_test/export")
st, _ = call("POST", "/_test/import", ex)
check("genuine export imports", st == 204, st)
check("every receipt replays its original body", all(call(m, p, b, t, k) == (200, r) for m, p, b, t, k, r in calls), "")
base = call("GET", "/_test/export")[1]


def find(state, path_pred):
    for i, it in enumerate(state["idempotency"]):
        if path_pred(it[2]):
            return i
    raise KeyError("receipt not found")


def mut(name, path_pred, fn):
    bad = copy.deepcopy(ex)
    try:
        i = find(bad["state"], path_pred)
        fn(bad["state"]["idempotency"][i])
    except (KeyError, IndexError, TypeError) as e:
        check("applicable: " + name, False, repr(e))
        return
    st, b = call("POST", "/_test/import", bad)
    check("tamper %s -> 422" % name, st == 422 and b and b["error"]["code"] == "validation_failed", (st, b))
    check("tamper %s leaves destination unchanged" % name, call("GET", "/_test/export")[1] == base, "")


is_batch = lambda p: p == "/correction-batches"
is_refund = lambda p: p.endswith("/refunds")
is_corr = lambda p: p.endswith("/corrections")
mut("batch: member dropped", is_batch, lambda it: it[4]["revisions"].pop())
mut("batch: order reversed", is_batch, lambda it: it[4]["revisions"].reverse())
mut("batch: member duplicated", is_batch, lambda it: it[4]["revisions"].append(dict(it[4]["revisions"][0])))
mut("batch: recorded_at changed", is_batch, lambda it: it[4].__setitem__("recorded_at", "2020-01-01T00:00:00+00:00"))
mut("batch: one revision's recorded_at changed", is_batch,
    lambda it: it[4]["revisions"][1].__setitem__("recorded_at", "2020-01-01T00:00:00+00:00"))
mut("batch: amount changed", is_batch, lambda it: it[4]["revisions"][0].__setitem__("amount", it[4]["revisions"][0]["amount"] + 1))
mut("batch: batch id changed", is_batch, lambda it: it[4].__setitem__("correction_batch_id", "cb_forged"))
mut("batch: owned by non-operator", is_batch, lambda it: it.__setitem__(0, "u_a"))
mut("refund: amount changed", is_refund, lambda it: it[4].__setitem__("amount", it[4]["amount"] + 1))
mut("refund: refund_of changed", is_refund, lambda it: it[4].__setitem__("refund_of", "p_forged"))
mut("correction: revision changed", is_corr, lambda it: it[4].__setitem__("revision", 7))
mut("correction: reason changed", is_corr, lambda it: it[4].__setitem__("reason", "forged"))

fails = [r for r in RESULTS if not r[1]]
for n, ok, d in RESULTS:
    print("%s  %s%s" % ("PASS" if ok else "FAIL", n, "" if ok else "  -> %s" % (d,)))
print("%d probes, %d failed" % (len(RESULTS), len(fails)))
sys.exit(1 if fails else 0)
