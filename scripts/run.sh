#!/usr/bin/env bash
# Cross-platform NEXUS runner — works on macOS, Linux, WSL
# Usage: bash scripts/run.sh [api|gui|terminal|all]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GUI_DIR="$ROOT/gui"
LOGS_DIR="$ROOT/logs"
VENV_PYTHON="$ROOT/.venv/bin/python"
[ ! -f "$VENV_PYTHON" ] && VENV_PYTHON="python3"
[ ! -f "$VENV_PYTHON" ] && VENV_PYTHON="python"

mkdir -p "$LOGS_DIR"
RUN_STAMP=$(date +"%Y%m%d-%H%M%S")

stop_port() {
  local port=$1
  lsof -ti:$port 2>/dev/null | xargs kill -9 2>/dev/null || true
}

wait_ok() {
  local url=$1
  local sec=${2:-30}
  for i in $(seq 1 $sec); do
    if curl --silent --output /dev/null --max-time 5 --write-out "%{http_code}" "$url" 2>/dev/null | grep -qE "^(200|429)$"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

MODE="${1:-all}"

case "$MODE" in
  api)
    echo "Starting NEXUS API on http://127.0.0.1:8000 ..."
    stop_port 8000
    "$VENV_PYTHON" -m uvicorn gui.api:app --host 127.0.0.1 --port 8000 > "$LOGS_DIR/api-$RUN_STAMP.log" 2>&1 &
    echo "API PID: $!"
    if wait_ok "http://127.0.0.1:8000/api/health" 20; then
      echo "API ready."
    else
      echo "API failed to start" >&2
      tail -20 "$LOGS_DIR/api-$RUN_STAMP.log" >&2
      exit 1
    fi
    ;;
  gui)
    echo "Starting NEXUS GUI on http://127.0.0.1:5173 ..."
    stop_port 5173
    (cd "$GUI_DIR" && npm run dev -- --host 127.0.0.1 --port 5173 > "$LOGS_DIR/gui-$RUN_STAMP.log" 2>&1) &
    echo "GUI PID: $!"
    if wait_ok "http://127.0.0.1:5173" 60; then
      echo "GUI ready."
    else
      echo "GUI failed to start" >&2
      exit 1
    fi
    ;;
  all|"")
    echo "Starting NEXUS (API + GUI)..."
    stop_port 8000
    stop_port 5173
    "$VENV_PYTHON" -m uvicorn gui.api:app --host 127.0.0.1 --port 8000 > "$LOGS_DIR/api-$RUN_STAMP.log" 2>&1 &
    API_PID=$!
    echo "API PID: $API_PID"
    if wait_ok "http://127.0.0.1:8000/api/health" 20; then
      echo "API ready."
    else
      echo "API failed to start" >&2
      tail -20 "$LOGS_DIR/api-$RUN_STAMP.log" >&2
      exit 1
    fi
    (cd "$GUI_DIR" && npm run dev -- --host 127.0.0.1 --port 5173 > "$LOGS_DIR/gui-$RUN_STAMP.log" 2>&1) &
    GUI_PID=$!
    echo "GUI PID: $GUI_PID"
    if wait_ok "http://127.0.0.1:5173" 60; then
      echo "GUI ready at http://127.0.0.1:5173"
      echo "API  at http://127.0.0.1:8000"
    else
      echo "GUI failed to start" >&2
      exit 1
    fi
    # wait for either process to exit
    wait $API_PID $GUI_PID 2>/dev/null
    ;;
  terminal)
    echo "Starting NEXUS Terminal..."
    "$VENV_PYTHON" -c "from shell import NexusShell; NexusShell().start()"
    ;;
  network)
    echo "Starting NEXUS in NETWORK mode (accessible from any device)..."
    stop_port 8000
    stop_port 5173
    "$VENV_PYTHON" -m uvicorn gui.api:app --host 0.0.0.0 --port 8000 > "$LOGS_DIR/api-$RUN_STAMP.log" 2>&1 &
    API_PID=$!
    export NEXUS_DASHBOARD_LOCAL_ONLY=false
    if wait_ok "http://127.0.0.1:8000/api/health" 20; then
      echo "API ready."
    else
      echo "API failed to start" >&2
      exit 1
    fi
    (cd "$GUI_DIR" && npm run dev -- --host 0.0.0.0 --port 5173 > "$LOGS_DIR/gui-$RUN_STAMP.log" 2>&1) &
    GUI_PID=$!
    if wait_ok "http://127.0.0.1:5173" 60; then
      IP=$(ip route get 1 2>/dev/null | awk '{print $NF; exit}' || ifconfig 2>/dev/null | grep 'inet ' | grep -v 127.0.0.1 | awk '{print $2}' | head -1 || hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
      echo "NEXUS GUI ready on your network: http://$IP:5173"
      echo "Web Terminal: http://$IP:8000/terminal"
    else
      echo "GUI failed to start" >&2
      exit 1
    fi
    wait $API_PID $GUI_PID 2>/dev/null
    ;;
  help|--help|-h)
    echo "Usage: bash scripts/run.sh [command]"
    echo ""
    echo "Commands:"
    echo "  all          Start API + GUI (default)"
    echo "  api          Start API only"
    echo "  gui          Start GUI only"
    echo "  terminal     Start terminal shell"
    echo "  network      Start in network mode (all devices)"
    echo "  help         This help"
    ;;
  *)
    echo "Unknown: $MODE" >&2
    echo "Usage: bash scripts/run.sh [api|gui|terminal|all|network]" >&2
    exit 1
    ;;
esac
