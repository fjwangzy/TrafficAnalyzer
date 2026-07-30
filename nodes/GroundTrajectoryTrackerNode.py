from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from byte_tracker.byte_tracker_model import BYTETracker
from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.utils import profile_time


class GroundTrajectoryTrackerNode:
    """Assign stable image identities after background-motion compensation.

    This boundary deliberately accepts no homography, ENU point, map coverage or
    geographic quality input.  Its output is an image-space association fact;
    :class:`PostTrackingWorldProjectionNode` enriches that fact only after
    ByteTrack has finished assigning IDs.
    """

    tracking_method = "motion_compensated_image_v2"

    def __init__(self, config: dict) -> None:
        tracker_cfg = config["tracking_node"]
        self.tracker_cfg = tracker_cfg
        self.max_frame_gap_sec = float(tracker_cfg.get("max_frame_gap_sec", 0.5))
        self.max_lost_sec = float(tracker_cfg.get("max_lost_sec", 2.0))
        self._candidate_tail_points = int(
            tracker_cfg.get("candidate_trajectory_tail_points", 30)
        )
        self._last_timestamp: float | None = None
        self._next_track_id = 1
        self._next_shadow_track_id = 1
        vehicle_cfg = config.get("vehicle_classification", {})
        self._non_motor_class_ids = {
            int(value)
            for value in vehicle_cfg.get(
                "non_motor_class_ids", [0, 1, 2, 6, 7, 9]
            )
        }
        shadow_cfg = config.get("tracking_shadow", {})
        self._shadow_enabled = bool(shadow_cfg.get("enabled", False))
        self._shadow_offline_only = bool(shadow_cfg.get("offline_only", True))
        self._shadow_report_path = Path(
            shadow_cfg.get("report_path", "output/tracking-shadow.jsonl")
        )
        self._shadow_tracker: BYTETracker | None = None
        self._shadow_report = None
        self._shadow_report_error: str | None = None
        self.last_flush_result: dict | None = None
        self._reset_tracker()

    def _allocate_track_id(self) -> int:
        track_id = self._next_track_id
        self._next_track_id += 1
        return track_id

    def _allocate_shadow_track_id(self) -> int:
        track_id = self._next_shadow_track_id
        self._next_shadow_track_id += 1
        return track_id

    def _business_class_group(self, class_id: int) -> str:
        return "non_motor" if int(class_id) in self._non_motor_class_ids else "motor"

    def _reset_tracker(self) -> None:
        cfg = self.tracker_cfg
        self.tracker = BYTETracker(
            fps=30,
            first_track_thresh=cfg["first_track_thresh"],
            second_track_thresh=cfg["second_track_thresh"],
            match_thresh=cfg["match_thresh"],
            track_buffer=cfg["track_buffer"],
            resize_width_height=1,
            max_lost_sec=self.max_lost_sec,
            track_id_allocator=self._allocate_track_id,
            class_group_resolver=self._business_class_group,
            class_switch_confirm_frames=int(
                cfg.get("class_switch_confirm_frames", 3)
            ),
            large_object_area_px2=(
                float(cfg["large_object_area_px2"])
                if cfg.get("large_object_area_px2") is not None
                else None
            ),
            large_object_init_thresh=(
                float(cfg["large_object_init_thresh"])
                if cfg.get("large_object_init_thresh") is not None
                else None
            ),
        )
        self._image_history: dict[int, dict[str, list]] = {}

    def _get_shadow_tracker(self) -> BYTETracker:
        if self._shadow_tracker is None:
            cfg = self.tracker_cfg
            self._shadow_tracker = BYTETracker(
                fps=30,
                first_track_thresh=cfg["first_track_thresh"],
                second_track_thresh=cfg["second_track_thresh"],
                match_thresh=cfg["match_thresh"],
                track_buffer=cfg["track_buffer"],
                resize_width_height=1,
                max_lost_sec=None,
                track_id_allocator=self._allocate_shadow_track_id,
            )
        return self._shadow_tracker

    def _shadow_enabled_for_source(self, source) -> bool:
        if not self._shadow_enabled:
            return False
        if not self._shadow_offline_only:
            return True
        if isinstance(source, int):
            return False
        value = str(source).strip().lower()
        return not (
            value.isdigit()
            or value.startswith(("rtsp://", "rtsps://", "http://", "https://"))
        )

    @staticmethod
    def _bbox_iou(left, right) -> float:
        x1 = max(float(left[0]), float(right[0]))
        y1 = max(float(left[1]), float(right[1]))
        x2 = min(float(left[2]), float(right[2]))
        y2 = min(float(left[3]), float(right[3]))
        intersection = max(x2 - x1, 0.0) * max(y2 - y1, 0.0)
        left_area = max(float(left[2]) - float(left[0]), 0.0) * max(
            float(left[3]) - float(left[1]), 0.0
        )
        right_area = max(float(right[2]) - float(right[0]), 0.0) * max(
            float(right[3]) - float(right[1]), 0.0
        )
        union = left_area + right_area - intersection
        return intersection / union if union > 0 else 0.0

    def _compare_shadow_tracks(self, tracks, legacy_tracks) -> dict:
        pairs = sorted(
            (
                (self._bbox_iou(track.tlbr, legacy.tlbr), track, legacy)
                for track in tracks
                for legacy in legacy_tracks
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        matched_primary: set[int] = set()
        matched_legacy: set[int] = set()
        matched = []
        for iou, track, legacy in pairs:
            primary_id = int(track.track_id)
            legacy_id = int(legacy.track_id)
            if iou < 0.5 or primary_id in matched_primary or legacy_id in matched_legacy:
                continue
            matched_primary.add(primary_id)
            matched_legacy.add(legacy_id)
            matched.append(
                {
                    "image_v2_track_id": primary_id,
                    "legacy_track_id": legacy_id,
                    "iou": round(iou, 6),
                }
            )
        primary_ids = {int(track.track_id) for track in tracks}
        legacy_ids = {int(track.track_id) for track in legacy_tracks}
        return {
            "image_v2_track_count": len(tracks),
            "legacy_track_count": len(legacy_tracks),
            "matched_by_iou": matched,
            "unmatched_image_v2": sorted(primary_ids - matched_primary),
            "unmatched_legacy": sorted(legacy_ids - matched_legacy),
        }

    def _append_shadow_report(self, frame_element: FrameElement, comparison: dict) -> None:
        if self._shadow_report_error is not None:
            return
        try:
            if self._shadow_report is None:
                self._shadow_report_path.parent.mkdir(parents=True, exist_ok=True)
                self._shadow_report = self._shadow_report_path.open(
                    "a", encoding="utf-8"
                )
            record = {
                "schema_version": "uav.tracking-shadow/v2",
                "frame_num": int(frame_element.frame_num),
                "timestamp": float(frame_element.timestamp),
                "stage": "pre_georeference_image_association",
                "comparison": comparison,
            }
            self._shadow_report.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._shadow_report.flush()
        except OSError as exc:
            self._shadow_report_error = f"{type(exc).__name__}: {exc}"

    def _close_shadow_report(self) -> None:
        if self._shadow_report is not None:
            self._shadow_report.close()
            self._shadow_report = None

    @staticmethod
    def _warp_display_points(points, warp) -> list[list[float]] | None:
        if not points or warp is None:
            return None
        matrix = np.asarray(warp, dtype=np.float64)
        if matrix.shape == (2, 3):
            matrix = np.vstack([matrix, [0.0, 0.0, 1.0]])
        if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
            return None
        coordinates = np.asarray(points, dtype=np.float64)
        if coordinates.ndim != 2 or coordinates.shape[1] != 2:
            return None
        homogeneous = np.column_stack([coordinates, np.ones(len(coordinates))])
        projected = homogeneous @ matrix.T
        denominators = projected[:, 2]
        if np.any(~np.isfinite(projected)) or np.any(np.abs(denominators) < 1e-9):
            return None
        projected = projected[:, :2] / denominators[:, None]
        return [
            [round(float(point[0]), 2), round(float(point[1]), 2)]
            for point in projected
        ]

    def _build_image_trajectories(self, frame_element: FrameElement, tracks) -> list[dict]:
        # Keep history while ByteTrack holds an ID in ``lost_stracks``.  Removing
        # it merely because the ID is not emitted in one frame would make the
        # image history restart while post-ID world history correctly survives.
        active_ids = set(self._active_track_ids())
        for track_id in list(self._image_history):
            if track_id not in active_ids:
                self._image_history.pop(track_id, None)

        trajectories = []
        for track in tracks:
            track_id = int(track.track_id)
            bbox = track.tlbr
            ground_contact_point = [
                round(float((bbox[0] + bbox[2]) / 2.0), 2),
                round(float(bbox[3]), 2),
            ]
            display_point = [
                round(float((bbox[0] + bbox[2]) / 2.0), 2),
                round(float((bbox[1] + bbox[3]) / 2.0), 2),
            ]
            history = self._image_history.setdefault(
                track_id,
                {
                    "trajectory_px": [],
                    "trajectory_display_px": [],
                    "trajectory_timestamps_sec": [],
                    "trajectory_frame_nums": [],
                },
            )
            history["trajectory_px"].append(ground_contact_point)
            display = history["trajectory_display_px"]
            warped = self._warp_display_points(
                display, getattr(frame_element, "camera_motion_warp", None)
            )
            if warped is not None:
                display[:] = warped
            elif display:
                display.clear()
            display.append(display_point)
            history["trajectory_timestamps_sec"].append(float(frame_element.timestamp))
            history["trajectory_frame_nums"].append(int(frame_element.frame_num))
            tail = max(self._candidate_tail_points, 1)
            for key in history:
                history[key] = history[key][-tail:]
            trajectories.append(
                {
                    "track_id": track_id,
                    "association_id": track_id,
                    "tracking_method": self.tracking_method,
                    "trajectory_px": [point.copy() for point in history["trajectory_px"]],
                    "trajectory_display_px": [
                        point.copy() for point in history["trajectory_display_px"]
                    ],
                    "trajectory_timestamps_sec": list(
                        history["trajectory_timestamps_sec"]
                    ),
                    "trajectory_frame_nums": list(history["trajectory_frame_nums"]),
                }
            )
        return trajectories

    def _active_track_ids(self) -> list[int]:
        tracks = self.tracker.tracked_stracks + self.tracker.lost_stracks
        return sorted({int(track.track_id) for track in tracks})

    def update(self, tracking_frame: FrameElement) -> FrameElement:
        return self.process(tracking_frame)

    def flush(self, reason: str) -> dict:
        terminated_association_ids = self._active_track_ids()
        result = {
            "tracking_method": self.tracking_method,
            "terminated_track_ids": [],
            "terminated_association_ids": terminated_association_ids,
            "termination_reason": reason,
        }
        self._reset_tracker()
        self._last_timestamp = None
        self._close_shadow_report()
        self.last_flush_result = result
        return result

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            self.flush("natural_eof")
            return frame_element
        assert isinstance(frame_element, FrameElement), (
            f"GroundTrajectoryTrackerNode | 输入元素格式错误 {type(frame_element)}"
        )

        timestamp = float(frame_element.timestamp)
        termination_reason = None
        terminated_association_ids: list[int] = []
        if self._last_timestamp is not None:
            delta = timestamp - self._last_timestamp
            if delta <= 0 or delta > self.max_frame_gap_sec:
                terminated_association_ids = self._active_track_ids()
                termination_reason = (
                    "source_time_reversal" if delta <= 0 else "source_time_gap"
                )
                self._reset_tracker()

        boxes = frame_element.detected_xyxy or []
        confidences = frame_element.detected_conf or []
        class_ids = getattr(frame_element, "detected_cls_ids", None) or []
        rows = [
            [*box, confidences[index], class_ids[index]]
            for index, box in enumerate(boxes)
            if index < len(confidences) and index < len(class_ids)
        ]
        detections = np.asarray(rows, dtype=np.float32).reshape((-1, 6))
        warp = getattr(frame_element, "camera_motion_warp", None)
        tracks = self.tracker.update(
            detections,
            xyxy=True,
            camera_warp=warp,
            timestamp=timestamp,
        )
        shadow_comparison = None
        if self._shadow_enabled_for_source(frame_element.source):
            legacy_tracks = self._get_shadow_tracker().update(
                detections,
                xyxy=True,
                camera_warp=None,
                timestamp=None,
            )
            shadow_comparison = self._compare_shadow_tracks(tracks, legacy_tracks)
            self._append_shadow_report(frame_element, shadow_comparison)

        class_names_by_id = {
            int(class_id): frame_element.detected_cls[index]
            for index, class_id in enumerate(class_ids)
            if frame_element.detected_cls and index < len(frame_element.detected_cls)
        }
        frame_element.id_list = [int(track.track_id) for track in tracks]
        frame_element.association_id_list = list(frame_element.id_list)
        frame_element.tracked_xyxy = [list(track.tlbr.astype(int)) for track in tracks]
        frame_element.tracked_cls_ids = [int(track.class_name) for track in tracks]
        frame_element.tracked_cls = [
            class_names_by_id.get(int(track.class_name), str(int(track.class_name)))
            for track in tracks
        ]
        frame_element.tracked_conf = [float(track.score) for track in tracks]
        frame_element.association_trajectories = self._build_image_trajectories(
            frame_element, tracks
        )
        frame_element.tracking_diagnostics = {
            "tracking_method": self.tracking_method,
            "association_stage": "pre_georeference_image_only",
            "camera_motion_compensated": warp is not None,
            "association_count": len(tracks),
            "mahalanobis_gate": dict(
                self.tracker.last_association_diagnostics
            ),
            "association_state_ids": self._active_track_ids(),
            "terminated_track_ids": [],
            "terminated_association_ids": sorted(set(terminated_association_ids)),
            "termination_reason": termination_reason,
        }
        if shadow_comparison is not None:
            frame_element.tracking_diagnostics["shadow_comparison"] = shadow_comparison
        if self._shadow_report_error is not None:
            frame_element.tracking_diagnostics["shadow_report_error"] = (
                self._shadow_report_error
            )
        self._last_timestamp = timestamp
        return frame_element
