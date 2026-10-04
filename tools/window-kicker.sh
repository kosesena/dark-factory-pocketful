#!/usr/bin/env bash
# Usage-window kicker: if the seats' plan limit stopped them mid-run, wake them once the window resets.
# At the given time it checks the result repository; if no Claude seat committed in the last QUIET
# minutes, it restarts each seat's bound room session (band restart), which redelivers any message
# the seat had not finished. Idle seats have nothing pending, so a restart does not change their work.
# Commits by the Codex seat (cross-auditor) are ignored: it runs on a separate plan and keeps going.
# It never writes to the room or the repository. Usage: tools/window-kicker.sh <owner> <HH:MM> <repo> [quiet-min] [log]
set -u
OWNER=$1; AT=$2; REPO=$3; QUIET=${4:-20}; LOG=${5:-./window-kicker.log}
BAND=${BAND:-band}; SEATS=(coordinator implementer reviewer spec-auditor customer cross-auditor)
log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }
log "kicker armed for $AT (quiet window ${QUIET} min)"
until [ "$(date +%H:%M)" = "$AT" ]; do sleep 20; done
sleep 60
last=$(git -C "$REPO" log -1 --format=%ct --perl-regexp --author="^(?!cross-auditor)" 2>/dev/null || echo 0)
age=$(( ($(date +%s) - last) / 60 ))
if [ "$age" -lt "$QUIET" ]; then log "last commit ${age} min ago: band is working, no kick"; exit 0; fi
log "no commit for ${age} min after the window reset: restarting bound room sessions"
for seat in "${SEATS[@]}"; do
  for hs in $("$BAND" sessions --as "$OWNER/$seat" 2>/dev/null | awk '$0 ~ /binding=bound/ {print $1}' | grep '^default-'); do
    "$BAND" restart --as "$OWNER/$seat" --host-session "$hs" >/dev/null 2>&1 && log "$seat: restarted $hs" || log "$seat: restart FAILED $hs"
  done
done
