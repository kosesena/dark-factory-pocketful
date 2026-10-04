import sys, copy
B = sys.argv[1]
src = open("journey_stage4_api.py").read().split("# ---------- refunds")[0]
exec(src)
A, Bo, C, O = reset()
P = pay(A, "bob", 1000, "p")[1]; RF = refund(Bo, P["payment_id"], 200, "rf")[1]
S = call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 30}, {"from_handle": "bob", "to_handle": "cy", "amount": 10}]}, tok=O, key="s")[1]; m = [x["payment_id"] for x in S["payments"]]
P2 = pay(A, "cy", 100, "p2")[1]
Bt = batch(O, [item(m[1], amount=5), item(m[0], amount=20), item(P2["payment_id"], amount=50, eff=N - timedelta(minutes=2))], "bt")
chk("batch created", Bt[0] == 201, Bt); Bt = Bt[1]
e0 = call("GET", "/_test/export")[1]
chk("genuine export imports", call("POST", "/_test/import", e0)[0] == 204)
chk("batch replay after import", batch(O, [item(m[1], amount=5), item(m[0], amount=20), item(P2["payment_id"], amount=50, eff=N - timedelta(minutes=2))], "bt") == (200, Bt))
st0 = e0["state"]; idem = st0["idempotency"]
def find_batch(state):
    for e in state["idempotency"]:
        if "/correction-batches" in str(e[2]): return e
def resp(e): return e[4]
before = me(A)[1]
def mut(label, fn):
    bad = copy.deepcopy(e0); e = find_batch(bad["state"])
    try: fn(e, bad["state"])
    except Exception as ex: print("   skip", label, repr(ex)); return
    r = call("POST", "/_test/import", bad); chk(f"corrupt batch receipt [{label}] -> 422", r[0] == 422 and code(r) == "validation_failed", r)
    chk(f"  unchanged after [{label}]", me(A)[1] == before and batch(O, [item(m[1], amount=5), item(m[0], amount=20), item(P2["payment_id"], amount=50, eff=N - timedelta(minutes=2))], "bt")[0] == 200)
mut("drop a revision", lambda e, s: resp(e)["revisions"].pop())
mut("reorder", lambda e, s: resp(e)["revisions"].reverse())
mut("duplicate revision", lambda e, s: resp(e)["revisions"].append(copy.deepcopy(resp(e)["revisions"][0])))
mut("wrong amount", lambda e, s: resp(e)["revisions"][0].__setitem__("amount", 999))
mut("wrong batch id on revision", lambda e, s: resp(e)["revisions"][0].__setitem__("correction_batch_id", "cb_x"))
mut("wrong recorded_at", lambda e, s: resp(e)["revisions"][0].__setitem__("recorded_at", "2001-01-01T00:00:00+00:00"))
mut("wrong reason", lambda e, s: resp(e)["revisions"][0].__setitem__("reason", "tampered"))
mut("wrong effective_at", lambda e, s: resp(e)["revisions"][0].__setitem__("effective_at", "2001-01-01T00:00:00+00:00"))
mut("wrong revision number", lambda e, s: resp(e)["revisions"][0].__setitem__("revision", 9))
mut("unknown payment", lambda e, s: resp(e)["revisions"][0].__setitem__("payment_id", "p_ghost"))
mut("top-level batch id", lambda e, s: resp(e).__setitem__("correction_batch_id", "cb_other"))
mut("top-level recorded_at", lambda e, s: resp(e).__setitem__("recorded_at", "2001-01-01T00:00:00+00:00"))
def owner(e, s): e[0] = "u_ada"
mut("non-operator owner", owner)
def drop_ledger_rev(e, s):
    for p in s["payments"]:
        if p["id"] == m[0]: p["revisions"].pop()
mut("ledger revision removed", drop_ledger_rev)
# stage 3 snapshot case and combos still fine; genuine again
chk("state still working", call("POST", "/_test/import", e0)[0] == 204 and me(O)[0] == 200)
print(f"\nRECEIPTS {n} checks, {len(fails)} failed: {fails}")
