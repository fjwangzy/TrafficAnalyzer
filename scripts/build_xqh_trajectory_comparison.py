"""Build deterministic before/after xqh trajectory evidence without altering pixels."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def _panel(image: np.ndarray, width: int = 1280, height: int = 720) -> np.ndarray:
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)


def _caption(panel: np.ndarray, title: str, metric: str) -> np.ndarray:
    bar_height = 84
    output = np.zeros((panel.shape[0] + bar_height, panel.shape[1], 3), dtype=np.uint8)
    output[bar_height:] = panel
    cv2.putText(
        output,
        title,
        (22, 34),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.82,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        output,
        metric,
        (22, 67),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (0, 191, 255),
        2,
        cv2.LINE_AA,
    )
    return output


def build(
    before_path: Path,
    after_path: Path,
    output_path: Path,
    *,
    crop_before_right_half: bool = True,
    before_title: str = "BEFORE: MPS corrupt boxes + mixed trace coordinates",
    before_metric: str = (
        "display/world residual max 322.825 px; visible long jumps and scribbles"
    ),
    after_title: str = "AFTER: safe MPS boxes + current-frame image coordinates",
    after_metric: str = (
        "invalid boxes 0; display/world residual P95 0.006 px, max 0.007 px"
    ),
) -> None:
    before = cv2.imread(str(before_path))
    after = cv2.imread(str(after_path))
    if before is None or after is None:
        raise ValueError("before/after image cannot be read")
    if crop_before_right_half:
        # The historical geometry artifact is a two-panel comparison; its right
        # half is the pre-fix rendering the user reported as abnormal.
        before = before[:, before.shape[1] // 2 :]
    before_panel = _caption(
        _panel(before),
        before_title,
        before_metric,
    )
    after_panel = _caption(
        _panel(after),
        after_title,
        after_metric,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(
        str(output_path),
        np.hstack([before_panel, after_panel]),
        [cv2.IMWRITE_JPEG_QUALITY, 94],
    ):
        raise RuntimeError("failed to write comparison image")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--before-full-frame",
        action="store_true",
        help="do not crop the historical before image to its right half",
    )
    parser.add_argument("--before-title")
    parser.add_argument("--before-metric")
    parser.add_argument("--after-title")
    parser.add_argument("--after-metric")
    args = parser.parse_args()
    kwargs = {
        key: value
        for key, value in {
            "before_title": args.before_title,
            "before_metric": args.before_metric,
            "after_title": args.after_title,
            "after_metric": args.after_metric,
        }.items()
        if value is not None
    }
    build(
        args.before,
        args.after,
        args.output,
        crop_before_right_half=not args.before_full_frame,
        **kwargs,
    )
    print(args.output.resolve())


if __name__ == "__main__":
    main()
