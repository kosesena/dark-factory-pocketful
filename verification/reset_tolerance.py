import json,sys,urllib.request
from datetime import datetime,timedelta,timezone
B=sys.argv[1]
def call(m,p,raw=None,h={}):
    r=urllib.request.Request(B+p,data=raw,method=m,headers={"Content-Type":"application/json",**h})
    try:
        with urllib.request.urlopen(r) as x: return x.status
    except urllib.error.HTTPError as e: return e.code
U=[{"id":"u_a","email":"a@x.io","password":"password","display_name":"A","handle":"a","balance":5000},{"id":"u_b","email":"b@x.io","password":"password","display_name":"B","handle":"b","balance":100}]
def fx(**k): d={"currency":"EUR","minor_units":2,"users":U,"payments":[],"requests":[]}; d.update(k); return json.dumps(d).encode()
P=lambda **k: dict({"id":"p1","from_user_id":"u_a","to_user_id":"u_b","amount":5,"note":"","visibility":"public"},**k)
R=lambda **k: dict({"id":"r1","requester_id":"u_b","payer_id":"u_a","amount":5,"note":"","status":"pending"},**k)
past=(datetime.now(timezone.utc)-timedelta(days=3)).isoformat(timespec="seconds")
cases={
 "spec example": fx(payments=[P(id="p_1",amount=500,note="coffee")],requests=[R(id="rq_1",amount=1200,note="taxi")]),
 "paid req, no payment_id": fx(requests=[R(status="paid")]),
 "paid req -> payment_id": fx(payments=[P()],requests=[R(status="paid",payment_id="p1")]),
 "payment request_id + req payment_id": fx(payments=[P(request_id="r1")],requests=[R(status="paid",payment_id="p1")]),
 "payment request_id only (req paid)": fx(payments=[P(request_id="r1")],requests=[R(status="paid")]),
 "declined/cancelled reqs": fx(requests=[R(status="declined"),R(id="r2",status="cancelled")]),
 "payment created_at Z past": fx(payments=[P(created_at="2026-09-24T11:04:03Z")]),
 "payment created_at +02:00": fx(payments=[P(created_at="2026-09-24T13:04:03+02:00")]),
 "payment created_at fractional": fx(payments=[P(created_at="2026-09-24T11:04:03.250+00:00")]),
 "request created_at past": fx(requests=[R(created_at=past)]),
 "same-second seeded payments": fx(payments=[P(created_at=past),P(id="p2",created_at=past)]),
 "private payment, empty note": fx(payments=[P(visibility="private")]),
 "200-char note": fx(payments=[P(note="x"*200)]),
 "operators": fx(settlement_operator_ids=["u_a"]),
 "zero-amount payment": fx(payments=[P(amount=0)]),
 "zero-amount request": fx(requests=[R(amount=0)]),
}
for n,b in cases.items(): print(call("POST","/_test/reset",b), n)
