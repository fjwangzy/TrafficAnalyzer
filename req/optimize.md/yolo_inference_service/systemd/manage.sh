#!/usr/bin/env bash
# manage.sh — device-run-yolo-inference 单元安装 / 状态（渲染 @PROJECT_ROOT@）
set -euo pipefail
UNIT_SRC="$(cd "$(dirname "$0")" && pwd)/device-run-yolo-inference.service"
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
UNIT_DST=/etc/systemd/system/device-run-yolo-inference.service

case "${1:-status}" in
  install)
    sed "s|@PROJECT_ROOT@|${ROOT}|g" "${UNIT_SRC}" > "${UNIT_DST}"
    systemctl daemon-reload
    systemctl enable device-run-yolo-inference.service
    echo "installed (enabled, not started): ${UNIT_DST}"
    ;;
  status) systemctl status device-run-yolo-inference.service || true ;;
  *) echo "usage: $0 [install|status]" >&2; exit 2 ;;
esac
