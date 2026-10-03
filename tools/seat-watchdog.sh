#!/usr/bin/env bash
# Seat watchdog: keeps the band's runtimes alive during an unattended run.
#
# Every INTERVAL seconds it reads `band status` for each seat. A room session that is
# still bound but whose runtime has disconnected (the process died) is restarted with
# `band restart`; BAND redelivers the pending message, so the seat resumes its work.
# It never sends a message into the room and never touches the repository.
#
# Usage: tools/seat-watchdog.sh <owner> [interval-seconds] [log-file]
#   e.g. tools/seat-watchdog.sh kosesena 60 ~/band-watchdog.log
# Start it before the dispatch; stop it with Ctrl-C after the final report.

set -u
OWNER=${1:?usage: seat-watchdog.sh <owner> [interval] [log]}
INTERVAL=${2:-60}
LOG=${3:-./seat-watchdog.log}
BAND=${BAND:-band}
SEATS=(coordinator implementer reviewer spec-auditor customer cross-auditor)

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }

log "watchdog started: owner=$OWNER seats=${SEATS[*]} interval=${INTERVAL}s"
while true; do
  for seat in "${SEATS[@]}"; do
    status=$("$BAND" status --as "$OWNER/$seat" 2>&1) || { log "$seat: status failed: $status"; continue; }
    # Room sessions look like "default-<room-id> room=<room-id> ... presence=<p> binding=<b>".
    while read -r session rest; do
      case "$rest" in
        *binding=bound*presence=disconnected*|*presence=disconnected*binding=bound*)
          log "$seat: $session disconnected; restarting"
          if out=$("$BAND" restart --as "$OWNER/$seat" --host-session "$session" 2>&1); then
            log "$seat: $session restarted"
          else
            log "$seat: restart failed: $out"
          fi
          ;;
      esac
    done < <(printf '%s\n' "$status" | grep -E '^ +default-[^ ]+ room=')
  done
  sleep "$INTERVAL"
done
