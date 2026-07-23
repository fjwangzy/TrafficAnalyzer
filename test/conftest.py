"""Shared pytest setup for repository-level tests."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# These files are executable verification programs rather than pytest modules.
collect_ignore = [
    "test_e2e_inter_xqh.py",
    "test_e2e_mps_streaming.py",
    "test_live_api.py",
    "test_pipeline_inter_xqh.py",
    "test_pipeline_no_yolo.py",
    "test_refactor_unit.py",
]
