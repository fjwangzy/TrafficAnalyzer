from __future__ import annotations

import numpy as np
from shapely.geometry import Point, shape

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.coordinates import enu_to_gcj02
from utils_local.homography import (
    is_valid_homography,
    pixel_to_world,
    undistort_points,
)
from utils_local.utils import profile_time


class PostTrackingWorldProjectionNode:
    """Project image associations into the map and segment formal business IDs.

    The node runs strictly after ``GroundTrajectoryTrackerNode``.  Homography
    error may degrade or terminate a formal business segment, but it can never
    alter the already assigned image association ID.
    """

    tracking_method = "motion_compensated_image_v2"

    def __init__(self, config: dict) -> None:
        tracker_cfg = config["tracking_node"]
        self._tail_points = int(
            tracker_cfg.get("candidate_trajectory_tail_points", 30)
        )
        self._next_formal_track_id = 1
        self._formal_id_by_association: dict[int, int] = {}
        self._previous_formal_id_by_association: dict[int, int] = {}
        self._world_history: dict[int, dict[str, list]] = {}
        self._last_formal_eligible: bool | None = None
        self.last_flush_result: dict | None = None

    def _allocate_formal_track_id(self) -> int:
        track_id = self._next_formal_track_id
        self._next_formal_track_id += 1
        return track_id

    def _close_formal_segments(
        self, association_ids: set[int] | None = None
    ) -> tuple[list[int], list[int]]:
        targets = (
            set(self._formal_id_by_association)
            if association_ids is None
            else set(association_ids) & set(self._formal_id_by_association)
        )
        formal_ids = []
        for association_id in sorted(targets):
            formal_id = self._formal_id_by_association.pop(association_id)
            self._previous_formal_id_by_association[association_id] = formal_id
            formal_ids.append(formal_id)
        return sorted(formal_ids), sorted(targets)

    @staticmethod
    def _project_pixel_point(
        frame_element: FrameElement, pixel_point: list[float]
    ) -> np.ndarray | None:
        projection = getattr(frame_element, "pixel_to_map_enu", None)
        if not is_valid_homography(projection):
            return None
        point_px = np.asarray([pixel_point], dtype=np.float64)
        dist_coeffs = getattr(frame_element, "dist_coeffs", None)
        camera_intrinsics = getattr(frame_element, "camera_intrinsics", None)
        if dist_coeffs and camera_intrinsics and frame_element.frame is not None:
            point_px = undistort_points(
                point_px,
                camera_intrinsics,
                (frame_element.frame.shape[1], frame_element.frame.shape[0]),
                dist_coeffs,
            )
        return pixel_to_world(point_px, projection)[0]

    @classmethod
    def _inside_map_coverage(cls, frame_element: FrameElement, bbox) -> bool:
        quality = getattr(frame_element, "geo_reference_quality", None) or {}
        coverage = quality.get("map_coverage") or {}
        raw = coverage.get("geometry_enu_m")
        if not raw:
            return coverage.get("status") in {None, "verified"}
        try:
            ground = cls._project_pixel_point(
                frame_element,
                [(bbox[0] + bbox[2]) / 2.0, bbox[3]],
            )
            if ground is None:
                return False
            return bool(shape(raw).covers(Point(float(ground[0]), float(ground[1]))))
        except (TypeError, ValueError):
            return False

    def _append_world_fact(
        self,
        frame_element: FrameElement,
        association_id: int,
        pixel_point: list[float],
        is_formal: bool,
    ) -> dict[str, list]:
        history = self._world_history.setdefault(
            association_id,
            {
                "trajectory_enu_m": [],
                "trajectory_timestamps_sec": [],
                "trajectory_frame_nums": [],
                "point_quality_lineage": [],
            },
        )
        world_position = self._project_pixel_point(frame_element, pixel_point)
        if world_position is not None:
            world_fact = [
                float(world_position[0]),
                float(world_position[1]),
            ]
        else:
            world_fact = None
        geo_quality = getattr(frame_element, "geo_reference_quality", None) or {}
        history["trajectory_enu_m"].append(world_fact)
        history["trajectory_timestamps_sec"].append(float(frame_element.timestamp))
        history["trajectory_frame_nums"].append(int(frame_element.frame_num))
        history["point_quality_lineage"].append(
            {
                "timestamp_sec": float(frame_element.timestamp),
                "frame_num": int(frame_element.frame_num),
                "flight_phase": getattr(frame_element, "flight_phase", None),
                "flight_segment_id": getattr(frame_element, "flight_segment_id", None),
                "geo_reference_quality": geo_quality.get("status"),
                "tracking_quality": "verified" if is_formal else "degraded",
            }
        )
        tail = max(self._tail_points, 1)
        for key in history:
            history[key] = history[key][-tail:]
        return history

    def _enrich_trajectories(
        self,
        frame_element: FrameElement,
        formal_association_ids: set[int],
        covered_association_ids: set[int],
    ) -> None:
        raw_trajectories = getattr(frame_element, "association_trajectories", None) or []
        active_ids = {int(value) for value in (frame_element.id_list or [])}
        association_state_ids = set(
            (frame_element.tracking_diagnostics or {}).get("association_state_ids")
            or active_ids
        )
        for association_id in list(self._world_history):
            if association_id not in association_state_ids:
                self._world_history.pop(association_id, None)

        quality = getattr(frame_element, "geo_reference_quality", None) or {}
        quality_reasons = list(quality.get("reasons") or [])
        anchor = getattr(frame_element, "anchor_gcj02", None)
        enriched = []
        candidates = []
        for raw in raw_trajectories:
            association_id = int(raw.get("association_id", raw.get("track_id")))
            trajectory_px = raw.get("trajectory_px") or []
            if not trajectory_px:
                continue
            is_formal = association_id in formal_association_ids
            history = self._append_world_fact(
                frame_element,
                association_id,
                list(trajectory_px[-1]),
                is_formal,
            )
            reasons = [] if is_formal else quality_reasons.copy()
            if (
                not is_formal
                and bool(frame_element.formal_analytics_eligible)
                and association_id not in covered_association_ids
            ):
                reasons = ["target_outside_map_coverage"]
            elif not is_formal and not reasons:
                reasons = ["formal_analytics_disabled"]

            item = dict(raw)
            item.update(
                {
                    "tracking_quality": "verified" if is_formal else "degraded",
                    "quality_reasons": reasons,
                    "flight_phase": getattr(frame_element, "flight_phase", None),
                    "flight_segment_id": getattr(
                        frame_element, "flight_segment_id", None
                    ),
                    "trajectory_enu_m": [
                        point.copy() if point is not None else None
                        for point in history["trajectory_enu_m"]
                    ],
                    "point_quality_lineage": [
                        dict(point) for point in history["point_quality_lineage"]
                    ],
                }
            )
            if anchor:
                item["anchor_gcj02"] = [round(anchor[0], 6), round(anchor[1], 6)]
                trajectory_gcj02 = []
                for point in history["trajectory_enu_m"]:
                    if point is None:
                        trajectory_gcj02.append(None)
                        continue
                    lon, lat = enu_to_gcj02(point[0], point[1], anchor)
                    trajectory_gcj02.append([round(lon, 8), round(lat, 8)])
                item["trajectory_gcj02"] = trajectory_gcj02
            enriched.append(item)
            if not is_formal:
                candidates.append(item)
        frame_element.association_trajectories = enriched
        frame_element.candidate_trajectories = candidates

    def update(self, frame_element: FrameElement) -> FrameElement:
        return self.process(frame_element)

    def flush(self, reason: str) -> dict:
        formal_ids, association_ids = self._close_formal_segments()
        result = {
            "tracking_method": self.tracking_method,
            "terminated_track_ids": formal_ids,
            "terminated_association_ids": association_ids,
            "termination_reason": reason,
        }
        self._world_history.clear()
        self._last_formal_eligible = None
        self.last_flush_result = result
        return result

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            self.flush("natural_eof")
            return frame_element
        assert isinstance(frame_element, FrameElement), (
            f"PostTrackingWorldProjectionNode | 输入元素格式错误 {type(frame_element)}"
        )

        diagnostics = dict(frame_element.tracking_diagnostics or {})
        terminated_formal_ids: list[int] = []
        terminated_association_ids = list(
            diagnostics.get("terminated_association_ids") or []
        )
        termination_reason = diagnostics.get("termination_reason")

        if terminated_association_ids:
            closed_formal, _ = self._close_formal_segments(
                set(terminated_association_ids)
            )
            terminated_formal_ids.extend(closed_formal)

        current_formal = bool(frame_element.formal_analytics_eligible)
        if (
            self._last_formal_eligible is True
            and not current_formal
            and not termination_reason
        ):
            closed_formal, closed_associations = self._close_formal_segments()
            terminated_formal_ids.extend(closed_formal)
            terminated_association_ids.extend(closed_associations)
            quality_reasons = set(
                (getattr(frame_element, "geo_reference_quality", None) or {}).get(
                    "reasons"
                )
                or []
            )
            termination_reason = (
                "telemetry_gap"
                if {"telemetry_gap", "telemetry_unavailable"} & quality_reasons
                else "mode_transition_quality_break"
            )

        active_association_ids = {int(value) for value in (frame_element.id_list or [])}
        association_state_ids = set(
            diagnostics.get("association_state_ids") or active_association_ids
        )
        boxes_by_association = {
            int(association_id): bbox
            for association_id, bbox in zip(
                frame_element.id_list or [], frame_element.tracked_xyxy or []
            )
        }
        covered_association_ids = {
            association_id
            for association_id, bbox in boxes_by_association.items()
            if self._inside_map_coverage(frame_element, bbox)
        }
        associations_to_close = {
            association_id
            for association_id in self._formal_id_by_association
            if association_id not in association_state_ids
            or not current_formal
            or association_id not in covered_association_ids
        }
        if associations_to_close:
            closed_formal, closed_associations = self._close_formal_segments(
                associations_to_close
            )
            terminated_formal_ids.extend(closed_formal)
            terminated_association_ids.extend(closed_associations)
            termination_reason = termination_reason or (
                "target_left_map_coverage"
                if current_formal
                else "mode_transition_quality_break"
            )

        if current_formal:
            for association_id in sorted(covered_association_ids):
                if association_id not in self._formal_id_by_association:
                    self._formal_id_by_association[association_id] = (
                        self._allocate_formal_track_id()
                    )
            formal_association_ids = set(covered_association_ids)
        else:
            formal_association_ids = set()

        frame_element.formal_track_ids = sorted(formal_association_ids)
        frame_element.formal_track_id_by_association = {
            association_id: self._formal_id_by_association[association_id]
            for association_id in sorted(formal_association_ids)
        }
        frame_element.previous_formal_track_id_by_association = {
            association_id: self._previous_formal_id_by_association[association_id]
            for association_id in sorted(formal_association_ids)
            if association_id in self._previous_formal_id_by_association
        }
        self._enrich_trajectories(
            frame_element,
            formal_association_ids,
            covered_association_ids,
        )
        geo_quality = getattr(frame_element, "geo_reference_quality", None) or {}
        diagnostics.update(
            {
                "world_projection_stage": "post_bytetrack",
                "tracking_quality": (
                    "verified"
                    if current_formal and geo_quality.get("status") == "verified"
                    else "degraded"
                ),
                "formal_track_count": len(formal_association_ids),
                "candidate_track_count": len(
                    frame_element.candidate_trajectories or []
                ),
                "terminated_track_ids": sorted(set(terminated_formal_ids)),
                "terminated_association_ids": sorted(
                    set(terminated_association_ids)
                ),
                "termination_reason": termination_reason,
            }
        )
        frame_element.tracking_diagnostics = diagnostics
        self._last_formal_eligible = current_formal
        return frame_element
