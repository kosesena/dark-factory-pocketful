#!/usr/bin/env bash
# Experiment for ADR-001 option C: how strong is each model's evidence?
# Each arm gets the spec-auditor mandate and the same task on practice run 3's accepted stage 1
# (ba26a06): write one runnable probe suite from the specification. The suites are then run
# against the 37 faults the original auditor seeded (score_probes.py), which is what fault
# seeding measures. Arms: opus, sonnet (Claude Code), codex (Codex CLI).
# Usage: experiments/seeding_arms.sh [arm ...]   results in experiments/seeding/<arm>/
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
BW=$(dirname "$HERE")
P3="$BW/practice-3"
MAND="$BW/result/mandates/spec-auditor.md"
CLAUDE=${CLAUDE:-$HOME/node/bin/claude}
CODEX=${CODEX:-/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex}
REV=ba26a06
ARMS=(${@:-opus sonnet codex})

task() {
  cat <<EOF
You are building the evidence for one revision of a service. Nobody will answer questions; work
alone to the end.

Repository: $1 (git; commit under your own identity:
git -c user.name="spec-auditor" -c user.email="spec-auditor@band.local" commit ...).
Revision: the current HEAD, stage-1/. Start it with: cd stage-1 && PORT=<port> python3 -m app.main
Specification (read in full; the only source of truth):
/Users/kosesena/Desktop/dark-factory/dark-factory-wearedevs/pocketful/spec/stage-1.md
Never read the source of any shipped checks.

Do Phase 1 and Phase 2 of your instructions for this revision, and skip Phase 3. Your
deliverable is one runnable probe suite, committed at probes/run.py:
- it reads the service address from the environment variable BASE_URL;
- it resets state itself with POST /_test/reset before each scenario that needs it;
- it exercises every requirement in your ledger that can be observed over HTTP, including
  boundaries, malformed and wrongly typed input, replays, concurrency and what must never happen;
- it prints one line per requirement, PASS or FAIL, and exits 1 if any requirement fails;
- it uses the Python standard library only and finishes in under 3 minutes.
Run it against the revision. If a requirement fails because the revision really breaks it,
list that requirement id in a constant KNOWN_OPEN at the top of run.py and skip it, so the
suite exits 0 on this revision. Commit the suite and your ledger. Do not leave background
jobs running when you finish.
EOF
}

for arm in "${ARMS[@]}"; do
  out="$HERE/seeding/$arm"; ws="/tmp/exp-seed-$arm"
  rm -rf "$ws" "$out"; mkdir -p "$ws" "$out"
  git -C "$P3" archive "$REV" stage-1 | tar -x -C "$ws"
  git -C "$ws" init -q && git -C "$ws" -c user.name=setup -c user.email=setup@band.local add -A \
    && git -C "$ws" -c user.name=setup -c user.email=setup@band.local commit -qm "revision under test ($REV)"
  start=$(date +%s)
  case $arm in
    opus|sonnet)
      model=claude-$arm-5-5
      ( cd "$ws" && "$CLAUDE" -p "$(task "$ws")" --model "$model" --append-system-prompt "$(cat "$MAND")" \
          --output-format json --dangerously-skip-permissions > "$out/result.json" 2> "$out/stderr.log" ) ;;
    codex)
      "$CODEX" exec -C "$ws" -m gpt-6-astra -c model_reasoning_effort=high --json \
        --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check \
        "$(printf 'Your standing instructions:\n\n%s\n\n---\n\n%s' "$(cat "$MAND")" "$(task "$ws")")" \
        > "$out/events.jsonl" 2> "$out/stderr.log" ;;
  esac
  echo "$(( $(date +%s) - start ))" > "$out/seconds"
  cp -R "$ws" "$out/workspace"
  echo "$arm done in $(cat "$out/seconds")s; suite: $(test -f "$ws/probes/run.py" && echo yes || echo MISSING)"
done
