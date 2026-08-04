#!/usr/bin/env python3
"""Build a read-only detector/tracker engineering-coverage report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils_local.detection_tracking_evaluation import (  # noqa: E402
    evaluate_detection_tracking,
)


def _segment(value: str) -> dict[str, str | float]:
    try:
        name, start, end = value.split(":", 2)
        result = {
            "name": name,
            "start_sec": float(start),
            "end_sec": float(end),
        }
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            "segment must use NAME:START_SEC:END_SEC"
        ) from exc
    if not name or result["start_sec"] >= result["end_sec"]:
        raise argparse.ArgumentTypeError(
            "segment requires a name and START_SEC < END_SEC"
        )
    return result


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--tracks", type=Path, required=True)
    parser.add_argument("--lifecycle-audit", type=Path)
    parser.add_argument(
        "--segment",
        action="append",
        type=_segment,
        default=[],
        metavar="NAME:START_SEC:END_SEC",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    lifecycle_audit = (
        _read_json(args.lifecycle_audit) if args.lifecycle_audit else None
    )
    report = evaluate_detection_tracking(
        _read_json(args.stats),
        _read_json(args.tracks),
        lifecycle_audit=lifecycle_audit,
        segments=args.segment,
    )
    report["input_artifacts"] = {
        "stats": str(args.stats.resolve()),
        "tracks": str(args.tracks.resolve()),
        "lifecycle_audit": (
            str(args.lifecycle_audit.resolve()) if args.lifecycle_audit else None
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
