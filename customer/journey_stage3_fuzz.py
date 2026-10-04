import sys
B = sys.argv[1]
src = open("journey_stage3_api.py").read().split("N = datetime.now(timezone.utc)")[0]
exec(src)
N = datetime.now(timezone.utc).replace(microsecond=0)
fx = {"currency": "EUR", "minor_units": 2, "users": [user("u_ada", "ada", 1000), user("u_bob", "bob", 0)],
      "payments": [{"id": "p1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100, "note": "", "visibility": "public", "created_at": iso(N - timedelta(hours=1))}]}
call("POST", "/_test/reset", fx); A, Bo = login("ada"), login("bob")
weird = ["0001-01-01T00:00:00+00:00", "9999-12-31T23:59:59+00:00", "2026-09-24T23:59:60Z", "2026-09-24T13:20:00+25:00", "2026-09-24T13:20:00.123456789+00:00", "2026-09-24t13:20:00z", "2026-13-01T00:00:00Z", "2026-02-30T00:00:00Z", "2026-09-24T13:20:00+00:00 ", "٢٠٢٦-09-24T13:20:00Z", "2026-09-24T13:20:00-00:00", "0000-00-00T00:00:00Z", "+2026-09-24T13:20:00Z"]
for w in weird:
    for ep in ("/me?as_of=", "/me?known_at=", "/statement?from=", "/statement?to=", "/statement?known_at="):
        r = call("GET", ep + urllib.parse.quote(w), tok=A); chk(f"no 5xx {ep}{w!r}", r[0] < 500 and r[0] in (200, 422), (r[0], r[1] if r[0] != 200 else ""))
for w in weird:
    r = call("POST", "/payments/p1/corrections", {"expected_revision": 1, "amount": 50, "effective_at": w, "reason": "r"}, tok=A, key="f" + str(abs(hash(w)))); chk(f"correction eff {w!r} no 5xx", r[0] in (201, 409, 422), r)
for nm, b in [("huge exp amount", b'{"expected_revision":1,"amount":1e999999999,"effective_at":"%s","reason":"r"}'), ("huge rev", b'{"expected_revision":%s,"amount":5,"effective_at":"%s","reason":"r"}'), ("rev float", b'{"expected_revision":1.0,"amount":5,"effective_at":"%s","reason":"r"}'), ("rev bool", b'{"expected_revision":true,"amount":5,"effective_at":"%s","reason":"r"}'), ("amount str", b'{"expected_revision":1,"amount":"5","effective_at":"%s","reason":"r"}'), ("amount null", b'{"expected_revision":1,"amount":null,"effective_at":"%s","reason":"r"}'), ("reason null", b'{"expected_revision":1,"amount":5,"effective_at":"%s","reason":null}')]:
    t = iso(N - timedelta(minutes=5)).encode()
    raw = (b % (t,)) if b.count(b"%s") == 1 else (b % (b"9" * 400, t))
    r = call("POST", "/payments/p1/corrections", raw=raw, tok=A, key="fz" + nm); chk(f"correction {nm} 4xx not 5xx", 400 <= r[0] < 500, r)
r = call("POST", "/payments/p1/corrections", raw=b"[1]", tok=A, key="arr"); chk("array body", r[0] in (400, 422), r)
r = call("POST", "/payments/p1/corrections", raw=b"{bad", tok=A, key="bad"); chk("bad json 400", r[0] == 400, r)
# rev 1.0 equals 1?
r = call("POST", "/payments/p1/corrections", raw=b'{"expected_revision":1.0,"amount":90,"effective_at":"%s","reason":"r"}' % iso(N - timedelta(minutes=5)).encode(), tok=A, key="rev10"); print("   rev 1.0 ->", r[0], r[1] if r[0] != 201 else "")
r = call("GET", "/statement?snapshot=" + "x" * 5000, tok=A); chk("long snapshot no 5xx", r[0] == 404, r)
r = call("GET", "/payments/%00/revisions", tok=A); chk("odd id no 5xx", r[0] < 500, r)
r = call("GET", "/statement?limit=1&offset=" + "9" * 400, tok=A); chk("huge offset", r[0] == 200 and r[1]["entries"] == [] and r[1]["has_more"] is False, r)
print(f"\nFUZZ {n} checks, {len(fails)} failed: {fails}")
