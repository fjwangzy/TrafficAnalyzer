#!/usr/bin/env bash
# Idempotent native Apple Silicon detector environment bootstrap.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UV_BIN="${UV_BIN:-$HOME/.local/bin/uv}"
VENV_DIR="${MPS_VENV_DIR:-$PROJECT_ROOT/.venv-mps}"
PYTHON_VERSION="${MPS_PYTHON_VERSION:-3.11}"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "This bootstrap must run in a native arm64 macOS terminal." >&2
  exit 2
fi
if [[ ! -x "$UV_BIN" ]]; then
  echo "uv was not found at $UV_BIN; set UV_BIN to the native arm64 uv executable." >&2
  exit 2
fi
if ! file "$UV_BIN" | grep -q "arm64"; then
  echo "uv is not an arm64 executable: $UV_BIN" >&2
  exit 2
fi

"$UV_BIN" python install "$PYTHON_VERSION"
"$UV_BIN" venv --allow-existing --python "$PYTHON_VERSION" "$VENV_DIR"
"$UV_BIN" pip install \
  --python "$VENV_DIR/bin/python" \
  --constraint "$PROJECT_ROOT/platform/pipeline-constraints.txt" \
  --requirement "$PROJECT_ROOT/platform/pipeline-requirements.txt" \
  --editable "$PROJECT_ROOT/platform" \
  pytest \
  pytest-asyncio

"$VENV_DIR/bin/python" - <<'PY'
import json
import platform
import sys

import torch

result = {
    "executable": sys.executable,
    "machine": platform.machine(),
    "python": platform.python_version(),
    "torch": torch.__version__,
    "mps_built": torch.backends.mps.is_built(),
    "mps_available": torch.backends.mps.is_available(),
}
print(json.dumps(result, ensure_ascii=False, indent=2))
if result["machine"] != "arm64" or not result["mps_built"] or not result["mps_available"]:
    raise SystemExit("native arm64 PyTorch/MPS verification failed")
PY

echo "Native MPS environment is ready: $VENV_DIR/bin/python"
