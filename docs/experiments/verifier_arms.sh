#!/usr/bin/env bash
# Experiment for ADR-001, options B and C. Same task, same revision, three arms:
#   opus-auditor     control: the spec-auditor mandate on Opus (what the factory does today)
#   sonnet-auditor   option C: the same mandate on Sonnet
#   opus-combined    option B: one Opus seat carrying both the reviewer and the auditor mandate
#   codex-auditor    cross-vendor: the same auditor mandate on Codex (codex exec, gpt-6-astra,
#                    reasoning effort high); Codex has no system-prompt flag, so the mandate is
#                    placed before the task in the prompt
# Target: practice run 3, stage 1, revision 1a0af59 — accepted by reviewer and customer, rejected
# by the auditor for G-35 (a note with a lone UTF-16 surrogate moves money, returns nothing, and
# then breaks every user's activity feed). Each arm gets a fresh copy holding only stage-1/.
# Measured per arm: verdict, whether the lone-surrogate defect is reported, gaps cited,
# cost/tokens/turns/time (from claude --output-format json).
#
# Usage: experiments/verifier_arms.sh [arm ...]     results in experiments/arms/<arm>/
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
BW=$(dirname "$HERE")
P3="$BW/practice-3"
MAND="$BW/result/mandates"
CLAUDE=${CLAUDE:-$HOME/node/bin/claude}
CODEX=${CODEX:-/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex}
REV=1a0af59
ARMS=("${@:-opus-auditor sonnet-auditor opus-combined}")
ARMS=(${ARMS[@]})

task() {
  cat <<EOF
You are verifying one revision of a service. Nobody will answer questions; work alone to the end.

Repository: $1 (git; commit your files here under your own identity:
git -c user.name="$2" -c user.email="$2@band.local" commit ...). Revision under test: the current HEAD, stage-1/.
Specification (read in full; it is the only source of truth):
/Users/kosesena/Desktop/dark-factory/dark-factory-wearedevs/pocketful/spec/stage-1.md
Shipped checks (partial, read-only; never read their source; run them only with):
cd /Users/kosesena/Desktop/dark-factory/dark-factory-wearedevs && . .venv/bin/activate && python -m harness run --track pocketful --repo $1 --stage 1 --out /Users/kosesena/Desktop/dark-factory/band-work/checks/exp-$2-<new-unique-name>
Docker is at /usr/local/bin/docker.

Do the work your instructions describe for a verification of this revision, with one exception:
skip fault seeding. End with a verdict file VERDICT.md at the repository root: first line
ACCEPT or REJECT, then every open gap or defect with the specification sentence it violates and
a reproduction. Commit it. Do not leave background jobs running when you finish.
EOF
}

for arm in "${ARMS[@]}"; do
  case $arm in
    opus-auditor)   model=claude-opus-5-5;   seat=spec-auditor; files=("$MAND/spec-auditor.md") ;;
    sonnet-auditor) model=claude-sonnet-5-5; seat=spec-auditor; files=("$MAND/spec-auditor.md") ;;
    opus-combined)  model=claude-opus-5-5;   seat=verifier;     files=("$MAND/reviewer.md" "$MAND/spec-auditor.md") ;;
    codex-auditor)  model=gpt-6-astra;       seat=spec-auditor; files=("$MAND/spec-auditor.md") ;;
    *) echo "unknown arm $arm"; exit 2 ;;
  esac
  out="$HERE/arms/$arm"; ws="/tmp/exp-arm-$arm"
  rm -rf "$ws" "$out"; mkdir -p "$ws" "$out"
  git -C "$P3" archive "$REV" stage-1 | tar -x -C "$ws"
  git -C "$ws" init -q && git -C "$ws" -c user.name=setup -c user.email=setup@band.local add -A \
    && git -C "$ws" -c user.name=setup -c user.email=setup@band.local commit -qm "revision under test ($REV)"
  sys="$out/system.md"; : > "$sys"
  for f in "${files[@]}"; do cat "$f" >> "$sys"; printf '\n\n' >> "$sys"; done
  [ "$arm" = opus-combined ] && printf 'You hold both seats above: do the reviewer'"'"'s and the spec-auditor'"'"'s verification yourself, in one session.\n' >> "$sys"
  start=$(date +%s)
  if [ "$arm" = codex-auditor ]; then
    "$CODEX" exec -C "$ws" -m "$model" -c model_reasoning_effort=high --json \
      --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check \
      "$(printf 'Your standing instructions:\n\n%s\n\n---\n\n%s' "$(cat "$sys")" "$(task "$ws" "$seat")")" \
      > "$out/events.jsonl" 2> "$out/stderr.log"
    python3 - "$out" <<'PY'
import json, pathlib, sys
out = pathlib.Path(sys.argv[1]); u = {}; turns = 0
for line in (out / "events.jsonl").read_text().splitlines():
    try: e = json.loads(line)
    except ValueError: continue
    if e.get("type") == "turn.completed":
        turns += 1
        for k, v in (e.get("usage") or {}).items(): u[k] = u.get(k, 0) + v
(out / "result.json").write_text(json.dumps({"total_cost_usd": None, "num_turns": turns, "usage": u}))
PY
  else
  ( cd "$ws" && "$CLAUDE" -p "$(task "$ws" "$seat")" --model "$model" \
      --append-system-prompt "$(cat "$sys")" --output-format json \
      --dangerously-skip-permissions > "$out/result.json" 2> "$out/stderr.log" )
  fi
  echo "$(( $(date +%s) - start ))" > "$out/seconds"
  cp -R "$ws" "$out/workspace"
  python3 - "$out" <<'PY'
import json, pathlib, re, sys
out = pathlib.Path(sys.argv[1]); ws = out / "workspace"
r = json.loads((out / "result.json").read_text() or "{}")
verdict = (ws / "VERDICT.md").read_text() if (ws / "VERDICT.md").exists() else ""
text = verdict + "\n" + "\n".join(p.read_text(errors="ignore") for p in ws.rglob("*.md") if "stage-1" not in p.parts)
summary = {
    "verdict": verdict.splitlines()[0].strip() if verdict else "none",
    "lone_surrogate_found": bool(re.search(r"surrogate|\\\\ud8|\\\\udc|ensure_ascii", text, re.I)),
    "gaps_cited": len(re.findall(r"^\s*(?:[-*]|\d+\.|\|)\s*\**(?:G-?\d+|gap|defect)", verdict, re.I | re.M)),
    "cost_usd": r.get("total_cost_usd"), "turns": r.get("num_turns"),
    "seconds": int((out / "seconds").read_text()), "usage": r.get("usage"),
}
(out / "summary.json").write_text(json.dumps(summary, indent=1))
print(out.name, json.dumps({k: v for k, v in summary.items() if k != "usage"}))
PY
done
