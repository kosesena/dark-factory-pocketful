# Stage 3 seeded faults — spec-auditor

Each fault breaks one requirement in a throwaway copy (`audit/mutants/`, never committed) of the archived revision.
Evidence run against each copy: implementer unit tests, reviewer probes and model check, customer journeys, cross-auditor probes, spec-auditor probes, shipped checks.
Caught = fails a check that passes on the unmodified copy (H00).

| Rev | # | Requirement broken | Change | Caught by |
|---|---|---|---|---|
| 65dd709 | H00 | baseline: unmodified copy (must be caught by nothing) | ledger.py: `def whole(ts):` → `def whole(ts):` | — (control) |
| 65dd709 | H01 | S3-8 as_of is inclusive | ledger.py: `if as_of is None or eff <= as_of:` → `if as_of is None or eff < as_of:` | auditor, cross, customer, impl, reviewer |
| 65dd709 | H02 | S3-34 known_at selects by recorded time | ledger.py: `if r["recorded_ts"] <= known:` → `if r["effective_ts"] <= known:` | auditor, cross, customer, impl, reviewer |
| 65dd709 | H03 | S3-13 ties ordered by payment id ascending | history.py: `key=lambda e: (e[0], e[1]))` → `key=lambda e: (e[0], [-ord(c) for c in e[1]]))` | auditor, cross, customer, impl, reviewer, shipped |
| 65dd709 | H04 | S3-12 statement window is half-open (to exclusive) | history.py: `if hi is not None and t >= hi:` → `if hi is not None and t > hi:` | auditor, cross, customer, impl, reviewer |
| 65dd709 | H05 | S3-42 snapshots page their frozen entries | history.py: `        return 200, _page(s, snap, limit, offset)` → `        return 200, _page(s, dict(snap, entries=build_statem` | auditor, cross, customer, impl, reviewer |
| 65dd709 | H06 | S3-16 paging never changes the opening balance | history.py: `body = {"opening_balance": snap["opening_balance"],` → `body = {"opening_balance": (chunk[0][3] - chunk[0][2]) if ch` | auditor, cross, customer, impl, reviewer |
| 65dd709 | H07 | S3-26/27 a decrease debits the receiver (affordability of the receiver) | history.py: `debtor = sender if diff > 0 else receiver` → `debtor = sender` | cross, customer, impl, reviewer |
| 65dd709 | H08 | S3-28 historical_overdraft guards past boundaries | history.py: `if not history_ok(s, (sender["id"], receiver["id"]), {pid: r` → `if False:` | auditor, cross, customer, impl, reviewer |
| 65dd709 | H09 | S3-23 recorded times strictly increase per payment | history.py: `rec_ts = max(now, cur["recorded_ts"] + 1e-6)` → `rec_ts = float(int(now))` | auditor, cross, customer, impl, reviewer |
| 65dd709 | H10 | S3-24/33 a stale expected revision is 409 | history.py: `if expected != cur["revision"]:` → `if expected > cur["revision"]:` | auditor, cross, customer, impl, reviewer |
| 65dd709 | H11 | S3-49 settlement members are immutable to single corrections | history.py: `if p["settlement_id"] is not None or p.get("authorization_id` → `if p.get("authorization_id") is not None:` | auditor, cross, customer, impl, reviewer |
| 65dd709 | H12 | S3-32 revisions are hidden from third parties even for public payments | history.py: `if p is None or user["id"] not in (p["from_user_id"], p["to_` → `if p is None or (p["visibility"] != "public" and user["id"] ` | auditor, cross, customer, impl, reviewer |
| 65dd709 | H13 | S3-43 known_at may not accompany a snapshot | history.py: `if any(k in q for k in ("from", "to", "known_at")):` → `if any(k in q for k in ("from", "to")):` | auditor, cross, customer, impl, reviewer |
| 65dd709 | H14 | S3-52 a nonfinal capture reduces the hold at capture time | ledger.py: `done = early + sum(c["amount"] for c in caps if whole(c["ts"` → `done = early + sum(c["amount"] for c in caps)` | auditor, cross, customer |
| 65dd709 | H15 | S3-21 a correction's effective time is not later than now | history.py: `if eff_ts > now:` → `if eff_ts > now + 86400:` | auditor, customer, reviewer |
| 65dd709 | H16 | S3-3 a seeded created_at in the future is a reset error | accounts.py: `if rec["ts"] > time.time():` → `if rec["ts"] > time.time() + 86400:` | auditor, customer, reviewer |
| 7c35a2a | H00 | baseline: unmodified copy (must be caught by nothing) | ledger.py: `def whole(ts):` → `def whole(ts):` | — (control) |
| 7c35a2a | H17 | S3-42 a frozen snapshot with a future known_at selects revisions known when it was taken | snapshot.py: `k = min(known, sn["taken_ts"]) if "taken_ts" in sn else know` → `k = known` | cross, impl |
| 7c35a2a | H18 | S3-42/44 an imported snapshot must have been taken in the ledger's past | snapshot.py: `_need(sn["taken_seq"] <= st["seq"] and sn["taken_ts"] <= tim` → `_need(True)` | customer, impl |

Full seeding ran on 65dd709 (H01–H16). 7c35a2a changes only `stage-3/snapshot.py`, so on 7c35a2a only that code was seeded (H17, H18).
The 65dd709 results still hold for the unchanged code. No fault has survived.

## Revision 397a149: fix-revision seeding (changed code: snapshot import)

Only `snapshot.py` changed since the previous revision, so only it was seeded. The earlier results stand for the unchanged code.
Evidence now also includes `audit/probes/legacy_snapshot_probes.py`.

| # | Requirement broken | Change | Caught by |
|---|---|---|---|
| H00 | baseline: unmodified copy (must be caught by nothing) | ledger.py: `def whole(ts):` → `def whole(ts):` | — (control) |
| K01 | §10/S3-42 imported snapshots are always rebuilt (never skipped for legacy shape) | snapshot.py: `if True:  # frozen facts` → `if sn["taken_seq"] != st["seq"]:  # frozen facts` | auditor, cross, customer, impl |
| K02 | §10/S3-42 imported snapshot balances must equal the rebuild | snapshot.py: `_need(ob == sn["opening_balance"] and cb == sn["closing_balance"] and ` → `_need(rebuilt == entries)` | auditor, customer, impl |
| K03 | §10/S3-42 imported snapshot entries must equal the rebuild | snapshot.py: `and rebuilt == entries)` → `and len(rebuilt) == len(entries))` | auditor |
| K04 | §10/S3-42 a legacy snapshot's time is derived from the whole ledger, not its own entries | snapshot.py: `latest = max([ledger_latest[0]] + [parse_instant(e[5]) for e in entrie` → `latest = max([0.0] + [parse_instant(e[5]) for e in entries])` | auditor, cross, customer, impl |

K03 is caught only by the spec-auditor's probe: reorder two same-instant entries and recompute balance_after, so
opening, closing and every per-entry check still hold. Suggested test for the implementer: the snapshot fuzzer should
include this mutation. K02 was first caught only by the implementer; the empty-window balance shift probe now catches it too.
