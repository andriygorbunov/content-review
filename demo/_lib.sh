#!/usr/bin/env bash
# Shared helpers for the demo scripts.
#
#   run  <cmd...>   echo the command, wait for a keypress, execute it
#   run! <cmd...>   same, but a non-zero exit is expected (gates that should fail)
#   say  <text>     narration line, no command
#   hdr  <text>     section banner
#
# Set NOPAUSE=1 to run straight through with no keypresses.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

if [ -t 1 ]; then
  B=$'\033[1m'; DIM=$'\033[2m'; CY=$'\033[36m'; YL=$'\033[33m'; RS=$'\033[0m'
else
  B=""; DIM=""; CY=""; YL=""; RS=""
fi

pause() {
  [ "${NOPAUSE:-0}" = "1" ] && return 0
  printf '%s' "${DIM}   ⏎ ${RS}"
  read -r _ </dev/tty || true
}

hdr() {
  echo
  echo "${B}══════════════════════════════════════════════════════════════════${RS}"
  echo "${B}  $*${RS}"
  echo "${B}══════════════════════════════════════════════════════════════════${RS}"
}

say() { echo; echo "${YL}  ▸ $*${RS}"; }

run() {
  echo
  echo "${CY}  \$ $*${RS}"
  pause
  "$@"
  local ec=$?
  if [ $ec -ne 0 ]; then
    echo
    echo "  ✗ command exited $ec — stopping." >&2
    exit $ec
  fi
}

# For steps where a non-zero exit IS the point (a gate that should fail).
run!() {
  echo
  echo "${CY}  \$ $*${RS}"
  pause
  "$@"
  echo "${DIM}  (exit $? — expected)${RS}"
}

fresh_db() {
  export CR_DB="/tmp/cr_$1.db"
  rm -f "$CR_DB"
  say "database: $CR_DB  (each demo gets its own — see README)"
}

done_msg() {
  echo
  echo "${B}  ── done ──${RS}"
  echo
}
