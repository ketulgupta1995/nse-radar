#!/usr/bin/env bash
# Launcher: ./start.sh [--dev | --background | --stop | --status]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
HOST="${STOCK_HOST:-0.0.0.0}"
PORT="${STOCK_PORT:-8600}"
URL="http://127.0.0.1:$PORT"
DATA="${STOCK_DATA_DIR:-$ROOT/data}"
PIDFILE="$DATA/app.pid"
LOGFILE="$DATA/logs/app.log"
VENV="$ROOT/backend/.venv"
UVICORN="$VENV/bin/uvicorn"

running() { curl -fs "$URL/api/health" >/dev/null 2>&1; }

# The pid listening on $PORT, if any (fallback when the pid file is missing or stale).
port_pid() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null | head -1
  elif command -v ss >/dev/null 2>&1; then
    ss -ltnpH "sport = :$PORT" 2>/dev/null | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | head -1
  fi
}

ensure_backend() {
  if [ ! -x "$UVICORN" ]; then
    echo "Setting up the Python environment (first run only)..."
    local py=python3
    command -v python3.13 >/dev/null 2>&1 && py=python3.13
    [ -x "$HOME/miniconda3/envs/py313/bin/python3.13" ] && py="$HOME/miniconda3/envs/py313/bin/python3.13"
    [ -d "$VENV" ] || "$py" -m venv "$VENV"
    "$VENV/bin/pip" install -e "backend[dev]"
  fi
}

ensure_frontend() {
  [ -d frontend ] || return 0
  if [ ! -d frontend/node_modules ]; then
    echo "Installing frontend packages (first run only)..."
    (cd frontend && npm ci)
  fi
}

build_frontend() {
  # The phone bundle ships only frontend/dist (no src, no npm), so there is nothing to build.
  [ -d frontend/src ] || return 0
  ensure_frontend
  if [ ! -d frontend/dist ] || [ -n "$(find frontend/src frontend/index.html frontend/package.json -newer frontend/dist -print -quit 2>/dev/null)" ]; then
    echo "Building the frontend..."
    (cd frontend && npm run build)
  fi
}

stop_app() {
  local pid=""
  if [ -f "$PIDFILE" ]; then
    pid="$(cat "$PIDFILE")"
    rm -f "$PIDFILE"
  fi
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    pid="$(port_pid || true)"
  fi
  if [ -n "$pid" ] && kill "$pid" 2>/dev/null; then
    echo "Stopped (pid $pid)."
  else
    echo "Not running."
  fi
}

case "${1:-}" in
  --stop)
    stop_app
    ;;
  --status)
    if running; then echo "running at $URL"; else echo "not running"; exit 1; fi
    ;;
  --background)
    if running; then
      echo "Already running at $URL"; exit 0
    fi
    ensure_backend
    build_frontend
    mkdir -p "$DATA/logs"
    cd backend
    nohup "$UVICORN" app.main:app --host "$HOST" --port "$PORT" >> "$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    cd "$ROOT"
    echo "Started in the background. Log: $LOGFILE"
    echo "Open $URL"
    ;;
  --dev)
    ensure_backend
    ensure_frontend
    mkdir -p "$DATA"
    (cd backend && exec "$UVICORN" app.main:app --host "$HOST" --port "$PORT" --reload) &
    BACK=$!
    FRONT=""
    cleanup() { kill "$BACK" $FRONT 2>/dev/null || true; }
    trap cleanup EXIT INT TERM
    if [ -d frontend ]; then
      (cd frontend && exec npm run dev) &
      FRONT=$!
      echo "API: $URL   (the page itself is on the vite address printed below)"
    fi
    wait
    ;;
  "")
    ensure_backend
    build_frontend
    echo "Open $URL"
    cd backend && exec "$UVICORN" app.main:app --host "$HOST" --port "$PORT"
    ;;
  *) echo "Usage: ./start.sh [--dev|--background|--stop|--status]"; exit 1 ;;
esac
