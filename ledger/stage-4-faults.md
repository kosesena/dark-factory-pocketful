# Stage 4 seeded faults — spec-auditor (revision 8bbd03a)

Each fault breaks one requirement in a throwaway copy (`audit/mutants/`, never committed) of `git archive 8bbd03a`.
The faults run one or two at a time; an earlier parallel run exhausted local ports and was discarded.
Evidence run against each copy: implementer unit tests, reviewer probes_s4 and model_check_s4, customer journeys (stage 4),
cross-auditor stage-4 probes, spec-auditor `audit/probes/stage4_probes.py`, and the shipped stage-4 checks (previous stage served from the same archive).
Caught = fails a check that passes on the unmodified copy (J00).

| # | Requirement broken | Change | Caught by |
|---|---|---|---|
| J00 | baseline: unmodified copy (must be caught by nothing) | refunds.py: `def refunded_total(s, pid):` → `def refunded_total(s, pid):` | — (control) |
| J01 | S4-2 only the original receiver may refund | refunds.py: `if p["to_user_id"] != user["id"]:` → `if user["id"] not in (p["to_user_id"], p["from_user_id"]):` | auditor, cross, customer, impl, reviewer |
| J02 | S4-3 refunds of refunds give invalid_refund_target | refunds.py: `if p.get("refund_of") is not None:` → `if False:` | auditor, cross, customer, impl, reviewer |
| J03 | S4-5 refunds are capped cumulatively | refunds.py: `if refunded_total(s, pid) + v > p["revisions"][-1]["amount"]:` → `if v > p["revisions"][-1]["amount"]:` | auditor, cross, customer, impl, reviewer |
| J04 | S4-5 the cap is the current corrected amount | refunds.py: `+ v > p["revisions"][-1]["amount"]:` → `+ v > p["revisions"][0]["amount"]:` | auditor, cross, customer, impl, reviewer |
| J05 | S4-8 a refund is funded from available money, not held | refunds.py: `return pay_view(s, move_money(s, user, s.users[p["from_user_id"]], v, ` → `if user["balance"] < v:` | auditor, cross, customer, impl, reviewer |
| J06 | S4-15 a single correction cannot go below the refunded total | history.py: `if amount < refunded_total(s, pid):` → `if amount < 0:` | auditor, cross, customer, impl, reviewer |
| J07 | S4-14 a refund payment cannot be corrected (single) | history.py: `or p.get("refund_of") is not None):` → `):` | auditor, cross, customer, impl, reviewer |
| J08 | S4-21 batches cannot correct refunds | batches.py: `if p.get("authorization_id") is not None or p.get("refund_of") is not ` → `if p.get("authorization_id") is not None:` | auditor, cross, customer, impl, reviewer |
| J09 | S4-22 correcting a settlement member needs every member | batches.py: `if set(s.settlements[sid]["payment_ids"]) != {m[0] for m in members}:` → `if False:` | auditor, cross, customer, impl, reviewer |
| J10 | S4-23 settlement members share one effective instant | batches.py: `if len({m[1] for m in members}) != 1:` → `if False:` | auditor, cross, customer, impl, reviewer |
| J11 | S4-16/25 batch debits are checked against available funds | batches.py: `if d < 0 and available_of(s, s.users[uid]) + d < 0:` → `if d < 0 and s.users[uid]["balance"] + d < 0:` | cross, impl |
| J12 | S4-27 batch recorded_at strictly later than every member's previous | batches.py: `rec_ts = max(now, last + 1e-6)` → `rec_ts = now` | none — equivalent in reachable states (see below) |
| J13 | S4-24 batches are checked for historical total/available | batches.py: `if not history_ok(s, sorted(parties), override, now):` → `if False:` | auditor, cross, customer, impl, reviewer |
| J14 | S4-27 each batch revision exposes correction_batch_id | batches.py: `"reason": reason, "correction_batch_id": bid}` → `"reason": reason, "correction_batch_id": None}` | auditor, cross, customer, impl, reviewer |
| J15 | S4-37 pre-stage-4 snapshots page in their original form | history.py: `if legacy:  # a snapshot taken before stage 4` → `if False:  # a snapshot taken before stage 4` | auditor, customer, impl |

15 faults seeded: 14 caught, 1 equivalent (J12), 0 surviving.

J12 replaces the batch recorded time `max(now, last + 1e-6)` with `now`. The two differ only if a member's previous
recorded time is at or after the current clock reading. Reachable states rule that out:
- Import refuses revisions recorded in the future (422).
- Revision 1 is stamped to the whole second, at or before now.
- A later write under the global lock comes well after a microsecond.
Only a backwards clock step could expose it. A test with an injected clock would pin it down (suggestion, not blocking).

## Revision b6afe75: fix-revision seeding (changed code: snapshot import)

Only `snapshot.py` changed since the previous revision, so only it was seeded. The earlier results stand for the unchanged code.
Evidence now also includes `audit/probes/legacy_snapshot_probes.py`.

| # | Requirement broken | Change | Caught by |
|---|---|---|---|
| J00 | baseline: unmodified copy (must be caught by nothing) | refunds.py: `def refunded_total(s, pid):` → `def refunded_total(s, pid):` | — (control) |
| K01 | §10/S3-42 imported snapshots are always rebuilt (never skipped for legacy shape) | snapshot.py: `if True:  # frozen facts` → `if sn["taken_seq"] != st["seq"]:  # frozen facts` | auditor, impl |
| K02 | §10/S3-42 imported snapshot balances must equal the rebuild | snapshot.py: `_need(ob == sn["opening_balance"] and cb == sn["closing_balance"] and ` → `_need(rebuilt == entries)` | auditor, impl |
| K03 | §10/S3-42 imported snapshot entries must equal the rebuild | snapshot.py: `and rebuilt == entries)` → `and len(rebuilt) == len(entries))` | auditor |
| K04 | §10/S3-42 a legacy snapshot's time is derived from the whole ledger, not its own entries | snapshot.py: `latest = max([ledger_latest[0]] + [parse_instant(e[5]) for e in entrie` → `latest = max([0.0] + [parse_instant(e[5]) for e in entries])` | auditor, impl |

K03 is caught only by the spec-auditor's probe: reorder two same-instant entries and recompute balance_after, so
opening, closing and every per-entry check still hold. Suggested test for the implementer: the snapshot fuzzer should
include this mutation. K02 was first caught only by the implementer; the empty-window balance shift probe now catches it too.
