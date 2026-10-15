#!/usr/bin/env python3
"""Run the maintained node/entrypoint contracts formerly duplicated in this script.

World speed, statistics, image lifecycle, TCC, rendering and EOF are tested by
pytest fixtures that carry the current quality and coordinate contracts.
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TESTS = [
    "test/test_speed_estimation_coordinate_contract.py",
    "test/test_calc_statistics_capability.py",
    "test/test_kafka_active_trajectories.py",
    "test/test_ground_trajectory_tracker.py",
    "test/test_tcc_diagnostics.py",
    "test/test_tcc_evidence_publisher.py",
    "test/test_show_node_class_colors.py",
    "test/test_video_saver_conflict_evidence.py",
    "test/test_xqh_acceptance_rendering.py",
    "test/test_main_optimized_eof.py",
]

if __name__ == "__main__":
    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", *TESTS, "-q"], cwd=ROOT))
