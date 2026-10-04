"""spec-auditor worst case for the legacy-snapshot search: a closed-window legacy snapshot (explicit `to`), N later
payments outside the window, then a same-instant swap with recomputed balances. The swap passes every cheap check and
the count/sum screen at every later moment, so only full rebuilds can refuse it.
Usage: SRC=http://old-stage3 DEST=http://stage4 N=6000 K=1 python3 legacy_worstcase_probe.py
"""
import sys,copy,time,json,os
sys.argv=["x",os.environ.get("SRC","http://127.0.0.1:18762"),os.environ.get("DEST","http://127.0.0.1:18761")]
sys.path.insert(0,".")
import legacy_migration_probes as M
import legacy_snapshot_probes as L
P=M.P
N=int(sys.argv_n) if hasattr(sys,"argv_n") else 6000
import os; N=int(os.environ.get("N","6000")); K=int(os.environ.get("K","10"))
M.at(sys.argv[1])
P.reset(P.fx(users=[P.user("ada",10**8),P.user("bob",0),P.user("cy",0)]))
ada=P.tok("ada")
while time.time()%1>0.2: time.sleep(0.02)
M.pay(ada,"bob",1); M.pay(ada,"bob",2)
cut=M.S3.now_precise()
toks=[P.ok(M.S3.st(ada,limit=1,to=cut),200)["snapshot"] for _ in range(K)]
time.sleep(1.2)
for i in range(N): M.pay(ada,"bob",1)
exp=P.ok(P.call("GET","/_test/export"),200)
M.at(sys.argv[2])
DEST=os.environ.get("DEST")
if DEST: M.at(DEST)
def run(name, mut):
    e=copy.deepcopy(exp)
    for sn in e["state"]["snapshots"]:
        if sn["token"] in toks: mut(sn)
    t0=time.time()
    try: r=P.call("POST","/_test/import",e)[0]
    except Exception as x: r=repr(x)[:60]
    print(f"N={N} K={K} {name}: {r} in {time.time()-t0:.2f}s", flush=True)
run("genuine", lambda sn: None)
run("swap same-instant (closed window)", L.swap_same_instant)
run("shift +1", L.shift)
