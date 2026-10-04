#!/usr/bin/env python3
"""Reviewer's targeted probes for Pocketful stage 1, one per specification line that the
random model check does not reach. Written from the specification only.

Usage: python3 probes.py http://localhost:8080   (exit 0 when every probe passes)
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8080"
RESULTS = []


def call(method, path, body=None, token=None, key=None, raw=None, headers=None):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    if key is not None:
        h["Idempotency-Key"] = key
    h.update(headers or {})
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            txt = r.read()
            return r.status, (json.loads(txt) if txt else None), r.headers
    except urllib.error.HTTPError as e:
        txt = e.read()
        try:
            return e.code, (json.loads(txt) if txt else None), e.headers
        except ValueError:
            return e.code, {"_raw": txt[:200]}, e.headers


def code(b):
    try:
        return b["error"]["code"]
    except (TypeError, KeyError):
        return None


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))


def err(name, resp, status, ecode):
    st, b, _ = resp
    check(name, st == status and code(b) == ecode and isinstance(b["error"].get("message"), str),
          "got %s %s" % (st, b))


FX = {
    "currency": "EUR", "minor_units": 2,
    "users": [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 10000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 2500},
        {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
         "display_name": "Cy", "handle": "cy", "balance": 0},
        {"id": "u_op", "email": "op@example.com", "password": "correct horse",
         "display_name": "Op", "handle": "op", "balance": 0},
    ],
    "payments": [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500,
                  "note": "coffee", "visibility": "private"}],
    "requests": [{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200,
                  "note": "taxi", "status": "pending"}],
    "settlement_operator_ids": ["u_op"],
}


def reset(fx=FX):
    st, _, _ = call("POST", "/_test/reset", fx)
    assert st == 204, st
    return {u["handle"]: call("POST", "/auth/login", {"email": u["email"], "password": u["password"]})[1]["token"]
            for u in fx["users"]}


def bal(tok):
    return call("GET", "/me", token=tok)[1]["balance"]


RFC3339 = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?([+-]\d\d:\d\d|Z)$")


def main():
    T = reset()
    a, b, c, op = T["ada"], T["bob"], T["cy"], T["op"]

    # §3 conventions
    st, body, hd = call("GET", "/me", token=a)
    want_me = {"user_id": "u_ada", "display_name": "Ada", "handle": "ada",
               "balance": 10000, "currency": "EUR", "minor_units": 2}
    check("me shape", all(body.get(k) == v for k, v in want_me.items()), body)  # later stages add fields
    check("content-type json utf-8", "application/json" in hd.get("Content-Type", "")
          and "utf-8" in hd.get("Content-Type", "").lower(), hd.get("Content-Type"))
    st, p, _ = call("POST", "/payments", {"to_handle": "bob", "amount": 1500, "note": "dinner",
                                          "visibility": "public", "zzz": [1]}, token=a, key="k1")
    check("payment 201 + unknown field ignored", st == 201, (st, p))
    check("payment shape", set(p) >= {"payment_id", "from_user_id", "from_handle", "to_user_id",
                                       "to_handle", "amount", "currency", "note", "visibility",
                                       "request_id", "created_at"} and p["currency"] == "EUR", p)
    check("rfc3339 created_at", RFC3339.match(p["created_at"] or ""), p["created_at"])
    check("id <= 64", isinstance(p["payment_id"], str) and len(p["payment_id"]) <= 64, p["payment_id"])
    check("ordinary payment settlement_id null", p.get("settlement_id", "MISSING") is None, p)
    st, feed, _ = call("GET", "/activity?foo=bar", token=a)
    check("unknown query ignored", st == 200, st)

    # §4 amounts
    for i, amt in enumerate((1000.0, 1e3)):
        st, x, _ = call("POST", "/payments", {"to_handle": "bob", "amount": amt}, token=a, key="am%d" % i)
        check("amount %r (#%d) accepted as 1000" % (amt, i), st == 201 and x["amount"] == 1000 and
              isinstance(x["amount"], int), (st, x))
    for amt in (True, "1000", 10.5, 0, -1, 1000000001, None):
        err("amount %r -> 422" % (amt,), call("POST", "/payments", {"to_handle": "bob", "amount": amt},
                                              token=a, key="bad%r" % (amt,)), 422, "validation_failed")
    err("amount missing -> 422", call("POST", "/payments", {"to_handle": "bob"}, token=a, key="m1"),
        422, "validation_failed")
    err("to_handle missing -> 422", call("POST", "/payments", {"amount": 1}, token=a, key="m2"),
        422, "validation_failed")
    err("note null -> 422", call("POST", "/payments", {"to_handle": "bob", "amount": 1, "note": None},
                                 token=a, key="n1"), 422, "validation_failed")
    err("note 201 chars -> 422", call("POST", "/payments", {"to_handle": "bob", "amount": 1, "note": "x" * 201},
                                      token=a, key="n2"), 422, "validation_failed")
    st, x, _ = call("POST", "/payments", {"to_handle": "bob", "amount": 1, "note": "é" * 200}, token=a, key="n3")
    check("note 200 unicode chars ok", st == 201, st)
    emoji = "  🍕 dinner\u200d\n<b>&amp; "
    st, x, _ = call("POST", "/payments", {"to_handle": "bob", "amount": 1, "note": emoji}, token=a, key="n4")
    check("note verbatim", st == 201 and x["note"] == emoji, x)
    err("visibility bad", call("POST", "/payments", {"to_handle": "bob", "amount": 1, "visibility": "Public"},
                               token=a, key="v1"), 422, "validation_failed")
    err("to_handle wrong type -> 400", call("POST", "/payments", {"to_handle": 5, "amount": 1}, token=a, key="t1"),
        400, "malformed_request")
    err("self payment", call("POST", "/payments", {"to_handle": "ada", "amount": 1}, token=a, key="s1"),
        422, "self_payment")
    err("unknown handle", call("POST", "/payments", {"to_handle": "nobody", "amount": 1}, token=a, key="u1"),
        404, "not_found")
    err("insufficient", call("POST", "/payments", {"to_handle": "ada", "amount": 1}, token=c, key="i1"),
        409, "insufficient_funds")

    # §5 errors / auth
    err("malformed json", call("POST", "/payments", raw=b"{nope", token=a, key="mj"), 400, "malformed_request")
    err("non-object body", call("POST", "/payments", raw=b"[1]", token=a, key="mj2"), 400, "malformed_request")
    err("no key", call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=a), 400,
        "missing_idempotency_key")
    err("empty key", call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=a, key=""), 400,
        "missing_idempotency_key")
    st, _, _ = call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=a, key="K" * 255)
    check("key 255 ok", st == 201, st)
    err("key 256 -> 422", call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=a, key="K" * 256),
        422, "validation_failed")
    for path, meth in [("/me", "GET"), ("/activity", "GET"), ("/requests", "GET"), ("/payments", "POST"),
                       ("/requests", "POST"), ("/splits", "POST"), ("/settlements", "POST"),
                       ("/requests/rq_1/pay", "POST"), ("/requests/rq_1/decline", "POST"),
                       ("/requests/rq_1/cancel", "POST")]:
        err("401 no token %s %s" % (meth, path), call(meth, path, {} if meth == "POST" else None, key="x"),
            401, "unauthenticated")
    err("401 bad token", call("GET", "/me", token="garbage"), 401, "unauthenticated")
    err("401 malformed auth", call("GET", "/me", headers={"Authorization": "Basic abc"}), 401, "unauthenticated")
    for q in ("limit=1e9", "limit=4.0", "limit=+4", "limit=0", "limit=201", "offset=-1", "offset=1.0",
              "limit=", "limit=abc"):
        for path in ("/activity", "/requests"):
            err("query %s %s" % (path, q), call("GET", "%s?%s" % (path, q), token=a), 422, "validation_failed")
    st, x, _ = call("GET", "/activity?limit=200&offset=0", token=a)
    check("limit 200 ok", st == 200, st)
    err("direction bad", call("GET", "/requests?direction=both", token=a), 422, "validation_failed")
    err("status bad", call("GET", "/requests?status=open", token=a), 422, "validation_failed")

    # §6 signup/login
    st, s1, _ = call("POST", "/auth/signup", {"email": "Dee.O'Neil+x@Example.com", "password": "12345678",
                                              "display_name": "Dee"})
    check("signup 201", st == 201 and set(s1) >= {"user_id", "display_name", "token"}, (st, s1))
    st, me, _ = call("GET", "/me", token=s1["token"])
    check("derived handle", me["handle"] == "dee_o_neil_x" and me["balance"] == 0, me)
    st, s2, _ = call("POST", "/auth/signup", {"email": "ÄBCDEFGHIJKLMNOPQRSTUVWXYZ@x.io", "password": "12345678",
                                              "display_name": "U"})
    st2, me2, _ = call("GET", "/me", token=s2["token"]) if st == 201 else (0, {}, 0)
    check("derived handle non-ascii per char + truncate 20", me2.get("handle") == "_bcdefghijklmnopqrst", me2)
    err("email taken", call("POST", "/auth/signup", {"email": "ada@example.com", "password": "12345678",
                                                     "display_name": "x"}), 409, "email_taken")
    err("handle taken", call("POST", "/auth/signup", {"email": "ada@other.org", "password": "12345678",
                                                      "display_name": "x"}), 409, "handle_taken")
    err("handle taken creates nothing", call("POST", "/auth/login", {"email": "ada@other.org",
                                                                     "password": "12345678"}), 401, "unauthenticated")
    err("short password", call("POST", "/auth/signup", {"email": "zz@x.io", "password": "1234567",
                                                        "display_name": "x"}), 422, "validation_failed")
    for e in ("noat", "@x.io", "a@", "a@@b"):
        err("bad email %s" % e, call("POST", "/auth/signup", {"email": e, "password": "12345678",
                                                              "display_name": "x"}), 422, "validation_failed")
    err("wrong password", call("POST", "/auth/login", {"email": "ada@example.com", "password": "nope nope"}),
        401, "unauthenticated")
    err("unknown email", call("POST", "/auth/login", {"email": "q@q.q", "password": "nope nope"}),
        401, "unauthenticated")
    st, l2, _ = call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})
    check("two tokens both valid", call("GET", "/me", token=l2["token"])[0] == 200 and
          call("GET", "/me", token=a)[0] == 200, "")
    st, x, _ = call("POST", "/payments", {"to_handle": "dee_o_neil_x", "amount": 5}, token=a, key="newuser")
    check("new user receives immediately", st == 201 and bal(s1["token"]) == 5, st)
    st, x, _ = call("POST", "/requests", {"payer_handle": "dee_o_neil_x", "amount": 5}, token=a, key="askn")
    check("new user can be asked", st == 201, st)

    # §7 idempotency details
    T = reset()
    a, b, c, op = T["ada"], T["bob"], T["cy"], T["op"]
    body = {"to_handle": "bob", "amount": 100, "note": "x"}
    st1, r1, _ = call("POST", "/payments", body, token=a, key="same")
    st2, r2, _ = call("POST", "/payments", raw=b'{ "note":"x",  "amount":100.0,"to_handle":"bob"}', token=a, key="same")
    check("replay json-value equal -> 200 same body", st1 == 201 and st2 == 200 and r1 == r2, (st2, r2))
    check("replay moves no money", bal(a) == 9900, bal(a))
    err("reuse invalid body -> 409", call("POST", "/payments", {"to_handle": "bob", "amount": -1}, token=a,
                                          key="same"), 409, "idempotency_key_reuse")
    err("reuse self-payment body -> 409", call("POST", "/payments", {"to_handle": "ada", "amount": 1}, token=a,
                                               key="same"), 409, "idempotency_key_reuse")
    err("malformed body on used key -> 400", call("POST", "/payments", raw=b"{", token=a, key="same"), 400,
        "malformed_request")
    err("used key no token -> 401", call("POST", "/payments", body, key="same"), 401, "unauthenticated")
    st, x, _ = call("POST", "/payments", {"to_handle": "ada", "amount": 100, "note": "x"}, token=b, key="same")
    check("key scoped per user", st == 201, st)
    st, x, _ = call("POST", "/requests", {"payer_handle": "bob", "amount": 100, "note": "x"}, token=a, key="same")
    check("same key different path -> fresh", st == 201, st)
    # pay paths per request
    _, q1, _ = call("POST", "/requests", {"payer_handle": "bob", "amount": 10}, token=a, key="q1")
    _, q2, _ = call("POST", "/requests", {"payer_handle": "bob", "amount": 10}, token=a, key="q2")
    s_a, pa, _ = call("POST", "/requests/%s/pay" % q1["request_id"], {}, token=b, key="pk")
    s_b, pb, _ = call("POST", "/requests/%s/pay" % q2["request_id"], {}, token=b, key="pk")
    check("same key on /requests/A/pay and B/pay both 201", s_a == 201 and s_b == 201, (s_a, s_b))
    err("pay {} vs {visibility:public} -> 409",
        call("POST", "/requests/%s/pay" % q1["request_id"], {"visibility": "public"}, token=b, key="pk"),
        409, "idempotency_key_reuse")
    st, x, _ = call("POST", "/requests/%s/pay" % q1["request_id"], {}, token=b, key="pk")
    check("pay replay after paid -> 200", st == 200 and x == pa, st)
    err("pay with new key after paid -> 409", call("POST", "/requests/%s/pay" % q1["request_id"], {},
                                                   token=b, key="pk2"), 409, "request_not_pending")
    st, rq, _ = call("GET", "/requests?status=paid", token=a)
    got = [r for r in rq["requests"] if r["request_id"] == q1["request_id"]]
    check("request paid carries payment_id", got and got[0]["payment_id"] == pa["payment_id"], got)
    # failed key reusable (404, 422, 409)
    for i, bad in enumerate([{"to_handle": "nobody", "amount": 1}, {"to_handle": "bob", "amount": 0},
                             {"to_handle": "bob", "amount": 10 ** 9}]):
        call("POST", "/payments", bad, token=a, key="fk%d" % i)
        st, _, _ = call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=a, key="fk%d" % i)
        check("failed key %d reusable" % i, st == 201, st)
    # replay after cancel
    st, rr, _ = call("POST", "/requests", {"payer_handle": "cy", "amount": 5}, token=a, key="rc")
    call("POST", "/requests/%s/cancel" % rr["request_id"], {}, token=a)
    st, rr2, _ = call("POST", "/requests", {"payer_handle": "cy", "amount": 5}, token=a, key="rc")
    check("replay after cancel -> original pending body", st == 200 and rr2 == rr and rr2["status"] == "pending", rr2)

    # concurrency: 50 identical with fresh key
    def same(_):
        return call("POST", "/payments", {"to_handle": "cy", "amount": 3}, token=a, key="burst")[:2]
    before = bal(a)
    with ThreadPoolExecutor(50) as ex:
        res = list(ex.map(same, range(50)))
    sts = [s for s, _ in res]
    check("50 same-key: one 201 rest 200 same body", sts.count(201) == 1 and sts.count(200) == 49 and
          all(x == res[0][1] for _, x in res), sorted(set(sts)))
    check("50 same-key: moved once", bal(a) == before - 3, bal(a))
    # 50 concurrent pays of one request with different keys
    _, big, _ = call("POST", "/requests", {"payer_handle": "ada", "amount": 7}, token=b, key="race")
    with ThreadPoolExecutor(50) as ex:
        res = list(ex.map(lambda i: call("POST", "/requests/%s/pay" % big["request_id"], {}, token=a,
                                         key="race%d" % i)[0], range(50)))
    check("request pay race: exactly one 201, rest 409", res.count(201) == 1 and res.count(409) == 49,
          sorted(set(res)))

    # requests: decline/cancel rules
    T = reset()
    a, b, c, op = T["ada"], T["bob"], T["cy"], T["op"]
    err("requester cannot pay own", call("POST", "/requests/rq_1/pay", {}, token=b, key="x"), 403, "forbidden")
    err("requester cannot decline", call("POST", "/requests/rq_1/decline", {}, token=b), 403, "forbidden")
    err("payer cannot cancel", call("POST", "/requests/rq_1/cancel", {}, token=a), 403, "forbidden")
    err("decline unknown", call("POST", "/requests/nope/decline", {}, token=a), 404, "not_found")
    err("cancel unknown", call("POST", "/requests/nope/cancel", {}, token=a), 404, "not_found")
    err("pay unknown", call("POST", "/requests/nope/pay", {}, token=a, key="pu"), 404, "not_found")
    st, d1, _ = call("POST", "/requests/rq_1/decline", {}, token=a)
    st2, d2, _ = call("POST", "/requests/rq_1/decline", {}, token=a)
    check("decline twice 200", st == 200 and st2 == 200 and d2["status"] == "declined", (st, st2))
    err("cancel declined -> 409", call("POST", "/requests/rq_1/cancel", {}, token=b), 409, "request_not_pending")
    err("pay declined -> 409", call("POST", "/requests/rq_1/pay", {}, token=a, key="pd"), 409, "request_not_pending")
    _, r2, _ = call("POST", "/requests", {"payer_handle": "cy", "amount": 50}, token=a, key="r2")
    err("pay short -> 409", call("POST", "/requests/%s/pay" % r2["request_id"], {"visibility": "private"},
                                 token=c, key="short"), 409, "insufficient_funds")
    call("POST", "/payments", {"to_handle": "cy", "amount": 50}, token=b, key="fund")
    st, pp, _ = call("POST", "/requests/%s/pay" % r2["request_id"], {"visibility": "private"}, token=c, key="short")
    check("later payable with same key after 409", st == 201 and pp["visibility"] == "private"
          and pp["request_id"] == r2["request_id"], (st, pp))
    err("cancel paid -> 409", call("POST", "/requests/%s/cancel" % r2["request_id"], {}, token=a), 409,
        "request_not_pending")
    err("decline paid -> 409", call("POST", "/requests/%s/decline" % r2["request_id"], {}, token=c), 409,
        "request_not_pending")
    st, fb, _ = call("GET", "/activity", token=b)
    check("third party does not see private request payment",
          all(x["payment_id"] != pp["payment_id"] for x in fb["payments"]), "")
    check("third party does not see seeded private p_1? (bob is receiver -> sees)",
          any(x["payment_id"] == "p_1" for x in fb["payments"]), "")
    st, fc, _ = call("GET", "/activity", token=op)
    check("operator does not see private items", all(x["visibility"] == "public" for x in fc["payments"]), fc)
    st, rqop, _ = call("GET", "/requests", token=op)
    check("operator sees no others' requests", rqop["requests"] == [], rqop)
    check("seeded payment in feed with null settlement/request",
          [x for x in call("GET", "/activity", token=a)[1]["payments"] if x["payment_id"] == "p_1"][0]
          ["request_id"] is None, "")
    # ordering newest first and filters
    for i in range(3):
        call("POST", "/requests", {"payer_handle": "bob", "amount": i + 1}, token=c, key="ord%d" % i)
        time.sleep(1.05)
    st, lo, _ = call("GET", "/requests?direction=outgoing&status=pending", token=c)
    check("requests newest first", [r["amount"] for r in lo["requests"]] == [3, 2, 1], lo)
    st, li, _ = call("GET", "/requests?direction=incoming&limit=2&offset=0", token=b)
    check("incoming paging has_more", st == 200 and len(li["requests"]) == 2 and li["has_more"] is True, li)
    st, fa, _ = call("GET", "/activity", token=a)
    ts = [x["created_at"] for x in fa["payments"]]

    # splits
    err("split note > 200", call("POST", "/splits", {"amount": 10, "participant_handles": ["bob"], "note": "x" * 201},
                                 token=a, key="sn"), 422, "validation_failed")
    err("split empty", call("POST", "/splits", {"amount": 10, "participant_handles": []}, token=a, key="se"),
        422, "validation_failed")
    err("split handles wrong type", call("POST", "/splits", {"amount": 10, "participant_handles": "bob"},
                                         token=a, key="sw"), 400, "malformed_request")
    st, sp, _ = call("POST", "/splits", {"amount": 1, "participant_handles": ["bob", "ada", "cy"]}, token=a, key="sz")
    check("split 1/3 shares and zero-share request", st == 201 and [s["amount"] for s in sp["shares"]] == [1, 0, 0]
          and [r["amount"] for r in sp["requests"]] == [1, 0] and sp["note"] == "" and sp["currency"] == "EUR",
          sp)
    zero = sp["requests"][1]
    st, zp, _ = call("POST", "/requests/%s/pay" % zero["request_id"], {}, token=c, key="z0")
    check("zero-share request payable (amount 0)", st == 201 and zp["amount"] == 0, (st, zp))
    st, so, _ = call("POST", "/splits", {"amount": 5, "participant_handles": ["ada"]}, token=a, key="solo")
    check("self-only split", st == 201 and so["requests"] == [] and so["shares"] == [{"handle": "ada", "amount": 5}], so)
    st, sb, _ = call("POST", "/splits", {"amount": 1000000000, "participant_handles": ["bob", "cy", "op"] * 1},
                     token=a, key="big")
    check("caller omitted: requests for all, shares sum", st == 201 and len(sb["requests"]) == 3 and
          sum(s["amount"] for s in sb["shares"]) == 10 ** 9, sb)
    st, sr, _ = call("POST", "/splits", {"amount": 1000000000, "participant_handles": ["bob", "cy", "op"]},
                     token=a, key="big")
    check("split replay identical", st == 200 and sr == sb, st)
    st, fa2, _ = call("GET", "/activity?limit=200", token=a)
    check("split not a feed item", len(fa2["payments"]) == len(call("GET", "/activity?limit=200", token=a)[1]["payments"]), "")
    n_before = len(call("GET", "/requests?limit=200", token=a)[1]["requests"])
    call("POST", "/splits", {"amount": 9, "participant_handles": ["bob", "nobody"]}, token=a, key="s404")
    check("failed split creates nothing", len(call("GET", "/requests?limit=200", token=a)[1]["requests"]) == n_before, "")

    # §11 settlements
    T = reset()
    a, b, c, op = T["ada"], T["bob"], T["cy"], T["op"]
    tr = {"transfers": [{"from_handle": "cy", "to_handle": "bob", "amount": 100},
                        {"from_handle": "ada", "to_handle": "cy", "amount": 100, "visibility": "private",
                         "note": "n", "zz": 1}]}
    err("settle non-operator 403", call("POST", "/settlements", tr, token=a, key="s"), 403, "forbidden")
    err("settle no key 400", call("POST", "/settlements", tr, token=op), 400, "missing_idempotency_key")
    for bad in ({}, {"transfers": []}, {"transfers": "x"}, {"transfers": [1]},
                {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}] * 33}):
        err("settle shape %s" % str(bad)[:40], call("POST", "/settlements", bad, token=op, key="shape"),
            422, "validation_failed")
    err("settle entry order: 404 before later 422",
        call("POST", "/settlements", {"transfers": [{"from_handle": "zz", "to_handle": "bob", "amount": 1},
                                                    {"from_handle": "ada", "to_handle": "ada", "amount": 1}]},
             token=op, key="ord"), 404, "not_found")
    err("settle entry order: self before later 404",
        call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "ada", "amount": 1},
                                                    {"from_handle": "zz", "to_handle": "bob", "amount": 1}]},
             token=op, key="ord"), 422, "self_payment")
    err("settle entry error before funds",
        call("POST", "/settlements", {"transfers": [{"from_handle": "cy", "to_handle": "bob", "amount": 99999},
                                                    {"from_handle": "ada", "to_handle": "bob", "amount": 0}]},
             token=op, key="ord"), 422, "validation_failed")
    err("settle unaffordable", call("POST", "/settlements", {"transfers": [
        {"from_handle": "cy", "to_handle": "bob", "amount": 1}]}, token=op, key="ord"), 409, "insufficient_funds")
    check("failed settlements moved nothing", (bal(a), bal(b), bal(c)) == (10000, 2500, 0), "")
    st, sres, _ = call("POST", "/settlements", tr, token=op, key="ord")
    check("net settlement (cy pays before receiving) 201 with key reused after failures", st == 201, (st, sres))
    if st == 201:
        check("settlement shape", set(sres) >= {"settlement_id", "committed_at", "payments"} and
              [x["amount"] for x in sres["payments"]] == [100, 100] and
              all(x["settlement_id"] == sres["settlement_id"] and x["request_id"] is None and
                  x["created_at"] == sres["committed_at"] for x in sres["payments"]) and
              sres["payments"][1]["note"] == "n" and sres["payments"][0]["note"] == "" and
              sres["payments"][0]["visibility"] == "public", sres)
        check("settlement balances", (bal(a), bal(b), bal(c)) == (9900, 2600, 0), (bal(a), bal(b), bal(c)))
        st, rep, _ = call("POST", "/settlements", tr, token=op, key="ord")
        check("settlement replay 200 identical", st == 200 and rep == sres, st)
        st, fb, _ = call("GET", "/activity", token=b)
        check("private settlement member hidden from third party",
              all(x["payment_id"] != sres["payments"][1]["payment_id"] for x in fb["payments"]), "")
        st, fop, _ = call("GET", "/activity", token=op)
        check("operator does not see private member",
              all(x["payment_id"] != sres["payments"][1]["payment_id"] for x in fop["payments"]), "")
        st, fc, _ = call("GET", "/activity", token=c)
        check("member visible to receiver with settlement_id",
              [x for x in fc["payments"] if x["payment_id"] == sres["payments"][1]["payment_id"]][0]
              ["settlement_id"] == sres["settlement_id"], "")

    # §10 export / import
    st, ex1, _ = call("GET", "/_test/export")
    check("export shape", st == 200 and ex1["track"] == "pocketful" and ex1["format_version"] == 1
          and isinstance(ex1["state"], dict), "")
    check("no plaintext password in export", "correct horse" not in json.dumps(ex1), "")
    call("POST", "/payments", {"to_handle": "cy", "amount": 1}, token=a, key="after-export")
    st, ex2, _ = call("GET", "/_test/export")
    check("export is a snapshot", ex1 != ex2, "")
    st, sg, _ = call("POST", "/auth/signup", {"email": "late@x.io", "password": "12345678", "display_name": "L"})
    for bad in ({"track": "other", "format_version": 1, "state": ex1["state"]},
                {"track": "pocketful", "format_version": 2, "state": ex1["state"]},
                {"track": "pocketful", "format_version": 1},
                {"track": "pocketful", "format_version": 1, "state": {"users": "x"}},
                {"track": "pocketful", "format_version": 1, "state": []}):
        err("import invalid -> 422", call("POST", "/_test/import", bad), 422, "validation_failed")
    err("import bad json", call("POST", "/_test/import", raw=b"{"), 400, "malformed_request")
    check("destination unchanged after bad import", call("GET", "/me", token=sg["token"])[0] == 200, "")
    st, _, _ = call("POST", "/_test/import", ex1)
    st2, _, _ = call("POST", "/_test/import", ex1)
    check("import 204 twice", st == 204 and st2 == 204, (st, st2))
    err("import removes destination credentials", call("GET", "/me", token=sg["token"]), 401, "unauthenticated")
    check("tokens and balances preserved", (bal(a), bal(b), bal(c)) == (9900, 2600, 0), "")
    st, rep, _ = call("POST", "/settlements", tr, token=op, key="ord")
    check("settlement replay after import", st == 200 and rep == sres, st)
    err("settlement reuse after import", call("POST", "/settlements", {"transfers": tr["transfers"][:1]},
                                              token=op, key="ord"), 409, "idempotency_key_reuse")
    st, x, _ = call("POST", "/payments", {"to_handle": "cy", "amount": 1}, token=a, key="after-export")
    check("key from after export is fresh after import", st == 201, st)
    st, fa, _ = call("GET", "/activity?limit=200", token=a)
    ids = [x["payment_id"] for x in fa["payments"]]
    check("no duplicate payments after repeated import", len(ids) == len(set(ids)), "")
    check("operator preserved after import", call("POST", "/settlements", {"transfers": [
        {"from_handle": "ada", "to_handle": "bob", "amount": 1}]}, token=op, key="post-imp")[0] == 201, "")
    st, l3, _ = call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})
    check("hashed login after import", st == 200, st)
    T2 = reset()
    err("reset clears imported tokens", call("GET", "/me", token=a), 401, "unauthenticated")

    # §4 reset validation
    bad = json.loads(json.dumps(FX))
    bad["users"][0]["balance"] = -1
    err("reset negative balance 422", call("POST", "/_test/reset", bad), 422, "validation_failed")
    check("reset 422 changed nothing", call("GET", "/me", token=T2["ada"])[0] == 200, "")
    for cur, mu in (("JPY", 0), ("BHD", 3)):
        fx = json.loads(json.dumps(FX))
        fx["currency"], fx["minor_units"] = cur, mu
        T3 = reset(fx)
        st, me, _ = call("GET", "/me", token=T3["ada"])
        check("currency %s" % cur, me["currency"] == cur and me["minor_units"] == mu, me)
    # big balances
    fx = json.loads(json.dumps(FX))
    fx["users"][0]["balance"] = 2 ** 53 - 10 ** 9
    T4 = reset(fx)
    st, x, _ = call("POST", "/payments", {"to_handle": "bob", "amount": 10 ** 9}, token=T4["ada"], key="huge")
    check("exact large balances", st == 201 and bal(T4["bob"]) == 2500 + 10 ** 9 and
          bal(T4["ada"]) == 2 ** 53 - 2 * 10 ** 9, "")

    # reset speed with a large fixture, and concurrent logins latency
    fx = {"currency": "EUR", "minor_units": 2, "users": [
        {"id": "u%d" % i, "email": "u%d@x.io" % i, "password": "password", "display_name": "U",
         "handle": "u%d" % i, "balance": 100} for i in range(300)], "payments": [], "requests": []}
    t0 = time.time()
    st, _, _ = call("POST", "/_test/reset", fx)
    dt = time.time() - t0
    check("reset 300 users < 10 s (%.2fs)" % dt, st == 204 and dt < 10, dt)
    t0 = time.time()
    with ThreadPoolExecutor(50) as ex:
        res = list(ex.map(lambda i: call("POST", "/auth/login", {"email": "u%d@x.io" % i, "password": "password"})[0],
                          range(50)))
    dt = time.time() - t0
    check("50 concurrent logins all 200 in < 5 s (%.2fs)" % dt, res.count(200) == 50 and dt < 5, dt)
    # oversized note / body
    st, _, _ = call("POST", "/auth/login", raw=b'{"email":"' + b"a" * 2_000_000 + b'","password":"x"}')
    check("oversized body no 5xx", st < 500, st)
    st, _, _ = call("GET", "/nope")
    check("unknown route 404", st == 404, st)

    fails = [r for r in RESULTS if not r[1]]
    for name, ok, det in RESULTS:
        print("%s  %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else "  -> %s" % (det,)))
    print("%d probes, %d failed" % (len(RESULTS), len(fails)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
