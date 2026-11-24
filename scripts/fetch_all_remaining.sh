#!/usr/bin/env bash
# Fetch all remaining data in parallel lanes, one lane per website. Each site keeps its own rate limit,
# so lanes don't slow each other down; steps inside a lane run one after another (same site).
#
#   nse       NSE API (www.nseindia.com, 2s gap): quarterly results -> announcements -> corporate actions
#   yfinance  Yahoo Finance: fundamentals
#   screener  Screener.in (5s gap): fundamentals
#
# Usage (from anywhere):
#   scripts/fetch_all_remaining.sh                 all lanes in parallel, logs in logs/backfill-<lane>.log
#   scripts/fetch_all_remaining.sh nse screener    only these lanes, in parallel
#   scripts/fetch_all_remaining.sh --fg nse        one lane in this terminal, asking before each batch
#
# Overall progress: printed here every minute, or in another terminal:
#   backend/.venv/bin/python scripts/backfill_progress.py --watch 30
# Item-by-item:    tail -f logs/backfill-*.log      (or the Jobs page)
# Ctrl+C stops every lane cleanly (runs marked cancelled; everything fetched so far is kept).
set -u
cd "$(dirname "$0")/.."
PY=backend/.venv/bin/python
export PYTHONUNBUFFERED=1
ALL_LANES=(nse yfinance screener)

lane_steps() {
  case "$1" in
    nse)      echo "quarters_backfill announcements_backfill actions_backfill" ;;
    yfinance) echo "yf_fundamentals_backfill" ;;
    screener) echo "screener_backfill" ;;
    *) return 1 ;;
  esac
}

run_lane() {  # run_lane LANE [extra args for each script]
  local lane=$1; shift
  local steps; steps=$(lane_steps "$lane") || { echo "unknown lane: $lane"; return 2; }
  for s in $steps; do
    echo; echo "################ [$lane] $s  ($(date +%H:%M:%S)) ################"
    "$PY" "scripts/$s.py" "$@"; local rc=$?
    echo "-> [$lane] $s exit $rc"
    if [ "$rc" -eq 130 ]; then echo "[$lane] interrupted; skipping the rest of this lane."; return 130; fi
  done
  echo "[$lane] lane finished $(date +%H:%M:%S)"
}

if [ "${1:-}" = "--fg" ]; then
  [ -n "${2:-}" ] || { echo "usage: $0 --fg <lane> [--yes]"; exit 2; }
  lane=$2; shift 2
  run_lane "$lane" "$@"
  exit $?
fi

lanes=("$@"); [ ${#lanes[@]} -eq 0 ] && lanes=("${ALL_LANES[@]}")
for l in "${lanes[@]}"; do lane_steps "$l" >/dev/null || { echo "unknown lane: $l (use: ${ALL_LANES[*]})"; exit 2; }; done

mkdir -p logs
set -m  # each lane in its own process group, so Python sees SIGINT (not ignored) and we can signal it
declare -A PID
for l in "${lanes[@]}"; do
  run_lane "$l" --yes >"logs/backfill-$l.log" 2>&1 &
  PID[$l]=$!
  echo "started lane $l (pid ${PID[$l]}) -> logs/backfill-$l.log"
done

stop_all() {
  echo; echo "Stopping all lanes cleanly..."
  for l in "${!PID[@]}"; do kill -INT -- "-${PID[$l]}" 2>/dev/null; done
}
trap stop_all INT TERM

echo; echo "Progress: tail -f logs/backfill-*.log   (Ctrl+C here stops all lanes)"
any_alive() { for l in "${!PID[@]}"; do kill -0 "${PID[$l]}" 2>/dev/null && return 0; done; return 1; }
while any_alive; do  # short status every minute until every lane exits
  echo; echo "======================================================================"
  "$PY" scripts/backfill_progress.py "${lanes[@]}" 2>/dev/null || echo "  (progress unavailable right now)"
  echo; echo "  Current item per lane:"
  for l in "${lanes[@]}"; do
    last=$(grep -E '^\s+\[ *[0-9]+/[0-9]+\]|^#{4}' "logs/backfill-$l.log" 2>/dev/null | tail -1 | sed 's/^ *//' | cut -c1-100)
    printf '    %-9s %s\n' "$l" "${last:-starting...}"
  done
  for _ in $(seq 12); do any_alive || break; sleep 5 & wait $!; done
done

echo; echo "All lanes done:"
for l in "${lanes[@]}"; do
  wait "${PID[$l]}" 2>/dev/null; rc=$?
  printf '  %-9s exit %s   (log: logs/backfill-%s.log)\n' "$l" "$rc" "$l"
done
echo; "$PY" scripts/data_status.py | sed -n '1,20p'
