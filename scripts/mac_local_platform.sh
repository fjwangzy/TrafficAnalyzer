#!/usr/bin/env bash
# Run the Platform directly on Apple Silicon so detector children can use MPS.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MPS_PYTHON="${MPS_VENV_DIR:-$PROJECT_ROOT/.venv-mps}/bin/python"
PLATFORM_PORT="${PLATFORM_PORT:-8000}"
RUNTIME_DIR="${TMPDIR:-/tmp}/traffic-analyzer-local-platform-${UID}"
LOG_FILE="$RUNTIME_DIR/platform.log"
LAUNCHD_LABEL="com.traffic-analyzer.local-platform-${UID}"
LOCAL_SURVEY_STORAGE_DIR="${SURVEY_STORAGE_DIR:-$PROJECT_ROOT/.runtime/survey}"

require_native_mps() {
  if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
    echo "mac_local_platform.sh requires native arm64 macOS." >&2
    exit 2
  fi
  if [[ ! -x "$MPS_PYTHON" ]]; then
    echo "Missing $MPS_PYTHON; run scripts/bootstrap_native_mps.sh first." >&2
    exit 2
  fi
  "$MPS_PYTHON" -c "import torch; assert torch.backends.mps.is_built() and torch.backends.mps.is_available()"
}

platform_is_running() {
  launchctl print "gui/${UID}/${LAUNCHD_LABEL}" >/dev/null 2>&1 \
    && curl -fsS "http://127.0.0.1:${PLATFORM_PORT}/health" >/dev/null 2>&1
}

platform_is_ready() {
  local readiness
  readiness="$(curl -fsS "http://127.0.0.1:${PLATFORM_PORT}/ready" 2>/dev/null)" || return 1
  "$MPS_PYTHON" -c \
    "import json, sys; raise SystemExit(json.loads(sys.argv[1]).get('status') != 'ready')" \
    "$readiness"
}

port_is_busy() {
  "$MPS_PYTHON" -c "import socket; s=socket.socket(); raise SystemExit(s.connect_ex(('127.0.0.1', ${PLATFORM_PORT})) != 0)"
}

platform_instance_pids() {
  pgrep -f "^${MPS_PYTHON} -m uvicorn app.main:app --host 0.0.0.0 --port ${PLATFORM_PORT}( --reload)?$" || true
}

launchd_platform_pid() {
  launchctl print "gui/${UID}/${LAUNCHD_LABEL}" 2>/dev/null \
    | awk '/^[[:space:]]*pid = / { print $3; exit }'
}

assert_single_platform() {
  local owned_pid platform_pids
  owned_pid="$(launchd_platform_pid)"
  platform_pids="$(platform_instance_pids)"
  if [[ -z "$owned_pid" || "$platform_pids" != "$owned_pid" ]]; then
    echo "Platform single-instance check failed: launchd_pid=${owned_pid:-none}, uvicorn_pids=${platform_pids//$'\n'/,}" >&2
    return 1
  fi
}

start_platform() {
  require_native_mps
  mkdir -p "$RUNTIME_DIR"
  mkdir -p "$LOCAL_SURVEY_STORAGE_DIR"
  chmod 700 "$RUNTIME_DIR"
  chmod 700 "$LOCAL_SURVEY_STORAGE_DIR"
  if platform_is_running; then
    assert_single_platform
    return
  fi
  if port_is_busy; then
    echo "Port ${PLATFORM_PORT} is already in use; stop the Docker Platform or choose PLATFORM_PORT." >&2
    exit 1
  fi
  umask 077
  rm -f "$LOG_FILE"
  launchctl remove "$LAUNCHD_LABEL" >/dev/null 2>&1 || true
  launchctl submit \
    -l "$LAUNCHD_LABEL" \
    -o "$LOG_FILE" \
    -e "$LOG_FILE" \
    -- /usr/bin/env \
    DEBUG="${DEBUG:-false}" \
    DEPLOYMENT_MODE=local \
    SERVICE_PORT="$PLATFORM_PORT" \
    DB_HOST="${DB_HOST:-127.0.0.1}" \
    DB_PORT="${DB_PORT:-5432}" \
    DB_USER="${DB_USER:-traffic}" \
    DB_PASSWORD="${DB_PASSWORD:-traffic123}" \
    DB_NAME="${DB_NAME:-road9}" \
    YCX_DB_HOST="${YCX_DB_HOST:-}" \
    YCX_DB_PORT="${YCX_DB_PORT:-5432}" \
    YCX_DB_USER="${YCX_DB_USER:-}" \
    YCX_DB_PASSWORD="${YCX_DB_PASSWORD:-}" \
    YCX_DB_NAME="${YCX_DB_NAME:-ycx}" \
    YCX_DB_SCHEMA="${YCX_DB_SCHEMA:-road9}" \
    KAFKA_BOOTSTRAP="${KAFKA_BOOTSTRAP:-127.0.0.1:9092}" \
    KAFKA_CONSUMER_GROUP="${KAFKA_CONSUMER_GROUP:-uav-platform-local}" \
    SURVEY_STORAGE_DIR="$LOCAL_SURVEY_STORAGE_DIR" \
    PIPELINE_PROJECT_ROOT="$PROJECT_ROOT" \
    PIPELINE_PYTHON="$MPS_PYTHON" \
    PIPELINE_DEVICE=mps \
    PIPELINE_IMGSZ="${PIPELINE_IMGSZ:-960}" \
    PIPELINE_FRAME_STRIDE="${PIPELINE_FRAME_STRIDE:-3}" \
    PYTORCH_ENABLE_MPS_FALLBACK=1 \
    "$MPS_PYTHON" "$PROJECT_ROOT/run_platform.py"

  for _ in {1..80}; do
    if platform_is_ready; then
      assert_single_platform
      return
    fi
    sleep 0.25
  done
  echo "Local Platform did not become ready; see $LOG_FILE" >&2
  exit 1
}

stop_platform() {
  launchctl remove "$LAUNCHD_LABEL" >/dev/null 2>&1 || true
  for _ in {1..50}; do
    if ! port_is_busy && [[ -z "$(platform_instance_pids)" ]]; then
      return
    fi
    sleep 0.1
  done
  echo "Local Platform stopped but port ${PLATFORM_PORT} is still busy." >&2
  return 1
}

show_status() {
  if platform_is_running; then
    assert_single_platform
    curl -fsS "http://127.0.0.1:${PLATFORM_PORT}/ready"
    echo
  else
    echo '{"status":"stopped"}'
  fi
}

show_logs() {
  [[ -f "$LOG_FILE" ]] && tail -n "${LOG_LINES:-120}" "$LOG_FILE"
}

case "${1:-up}" in
  up|start) start_platform ;;
  stop) stop_platform ;;
  restart) stop_platform; start_platform ;;
  status) show_status ;;
  logs) show_logs ;;
  *)
    echo "Usage: $0 [up|start|stop|restart|status|logs]" >&2
    exit 2
    ;;
esac
