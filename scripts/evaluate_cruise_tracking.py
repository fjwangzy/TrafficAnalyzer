#!/usr/bin/env python3
"""Evaluate an annotated hover/cruise dataset against production gates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils_local.cruise_evaluation import evaluate_cruise_dataset  # noqa: E402
from utils_local.cruise_acceptance_package import (  # noqa: E402
    audit_cruise_acceptance_package,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path, help="uav.cruise-eval/v1 JSON dataset")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--match-radius-m", type=float, default=3.0)
    parser.add_argument(
        "--asset-root",
        type=Path,
        help="root for content-addressed video/telemetry paths; defaults to dataset directory",
    )
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="audit capture assets/provenance before frame annotations are ready",
    )
    parser.add_argument("--allow-gate-failure", action="store_true")
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    asset_root = args.asset_root or args.dataset.parent
    if args.audit_only:
        report = audit_cruise_acceptance_package(dataset, asset_root=asset_root)
        passed = report["status"] == "production_evidence_ready"
    else:
        report = evaluate_cruise_dataset(
            dataset,
            match_radius_m=args.match_radius_m,
            asset_root=asset_root,
        )
        passed = report["gate"]["status"] == "production_signoff_passed"
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)
    if not passed and not args.allow_gate_failure:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
