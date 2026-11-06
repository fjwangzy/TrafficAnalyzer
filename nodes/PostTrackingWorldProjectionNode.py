from __future__ import annotations

import os

import numpy as np

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.coordinates import enu_to_gcj02
from utils_local.homography import (
    is_valid_homography,
    pixel_to_world,
    undistort_points,
)
from utils_local.utils import profile_time

# Sentinel used to keep the two projection paths sharing one result assembler
# without ever writing a null ``trajectory_gcj02`` when no anchor was present.
_GCJ_NOT_REQUESTED = object()
_INCREMENTAL_DISABLED_VALUES = frozenset({"0", "false", "no", "off", "disabled"})


def _incremental_enabled_from_env() -> bool:
    raw_value = os.environ.get("WORLD_PROJECTION_INCREMENTAL")
    if raw_value is None:
        return True
    return str(raw_value).strip().lower() not in _INCREMENTAL_DISABLED_VALUES


class PostTrackingWorldProjectionNode:
    """Enrich stable image associations with optional world-coordinate facts.

    The node runs strictly after ``GroundTrajectoryTrackerNode``. Geographic
    or road quality may make one enrichment point null, but neither can change
    the output track identity or terminate its image-trajectory lifecycle.

    ``WORLD_PROJECTION_INCREMENTAL`` (default on) keeps the GCJ-02 tail of each
    association cached so only the points appended by the current frame are
    converted.  The cached tail is invalidated whenever ``anchor_gcj02``
    changes, and ``false`` falls back to converting and copying the whole
    bounded tail on every frame.
    """

    tracking_method = "motion_compensated_image_v2"

    def __init__(self, config: dict) -> None:
        tracker_cfg = config["tracking_node"]
        self._tail_points = int(
            tracker_cfg.get("candidate_trajectory_tail_points", 30)
        )
        self._incremental = _incremental_enabled_from_env()
        self._next_track_id = 1
        self._track_id_by_association: dict[int, int] = {}
        self._previous_track_id_by_association: dict[int, int] = {}
        self._world_history: dict[int, dict[str, list]] = {}
        # Number of world facts appended per association: the conversion cache
        # below stores how many of them are already expressed in GCJ-02.
        self._append_counts: dict[int, int] = {}
        self._gcj_tail_cache: dict[int, dict] = {}
        self.last_flush_result: dict | None = None

    def _allocate_track_id(self) -> int:
        track_id = self._next_track_id
        self._next_track_id += 1
        return track_id

    def _drop_association_state(self, association_id: int) -> None:
        self._world_history.pop(association_id, None)
        self._append_counts.pop(association_id, None)
        self._gcj_tail_cache.pop(association_id, None)

    def _close_tracks(
        self, association_ids: set[int] | None = None
    ) -> tuple[list[int], list[int]]:
        targets = (
            set(self._track_id_by_association)
            if association_ids is None
            else set(association_ids) & set(self._track_id_by_association)
        )
        track_ids = []
        for association_id in sorted(targets):
            track_id = self._track_id_by_association.pop(association_id)
            self._previous_track_id_by_association[association_id] = track_id
            track_ids.append(track_id)
        return sorted(track_ids), sorted(targets)

    @staticmethod
    def _project_pixel_point(
        frame_element: FrameElement, pixel_point: list[float]
    ) -> np.ndarray | None:
        projection = getattr(frame_element, "pixel_to_world_enu", None)
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
        world_position = (
            self._project_pixel_point(frame_element, pixel_point)
            if is_formal
            else None
        )
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
                "geo_reference_quality": geo_quality.get(
                    "geo_status", geo_quality.get("status")
                ),
                "tracking_quality": "verified" if is_formal else "degraded",
            }
        )
        self._append_counts[association_id] = (
            self._append_counts.get(association_id, 0) + 1
        )
        tail = max(self._tail_points, 1)
        for key in history:
            history[key] = history[key][-tail:]
        return history

    def _legacy_trajectory_fields(
        self, history: dict[str, list], anchor
    ) -> tuple[list, list, object]:
        """Whole-tail copy + conversion; the pre-optimization behaviour."""
        trajectory_enu_m = [
            point.copy() if point is not None else None
            for point in history["trajectory_enu_m"]
        ]
        point_quality_lineage = [
            dict(point) for point in history["point_quality_lineage"]
        ]
        if not anchor:
            return trajectory_enu_m, point_quality_lineage, _GCJ_NOT_REQUESTED
        trajectory_gcj02 = []
        for point in history["trajectory_enu_m"]:
            if point is None:
                trajectory_gcj02.append(None)
                continue
            lon, lat = enu_to_gcj02(point[0], point[1], anchor)
            trajectory_gcj02.append([round(lon, 8), round(lat, 8)])
        return trajectory_enu_m, point_quality_lineage, trajectory_gcj02

    def _incremental_gcj_tail(
        self, association_id: int, history_enu: list, anchor
    ) -> list:
        """Convert only the slices appended since the cached conversion."""
        anchor_key = (anchor[0], anchor[1])
        converted_count = self._append_counts.get(association_id, 0)
        length = len(history_enu)
        cached = self._gcj_tail_cache.get(association_id)
        if (
            cached is not None
            and cached["anchor_key"] == anchor_key
            and cached["converted_count"] <= converted_count
        ):
            cached_points = cached["gcj_tail"]
            new_points = converted_count - cached["converted_count"]
            # ``cached_points`` covers the tail as of the last conversion; drop
            # the entries a bounded-tail trim has pushed out of that overlap.
            keep = min(length, new_points + len(cached_points)) - new_points
            if keep < 0:
                keep = 0
            gcj_tail = (
                cached_points[len(cached_points) - keep:] if keep else []
            )
            first_new = length - min(new_points, length)
        else:
            gcj_tail = []
            first_new = 0

        def convert(points):
            converted = []
            for point in points:
                if point is None:
                    converted.append(None)
                    continue
                lon, lat = enu_to_gcj02(point[0], point[1], anchor)
                converted.append([round(lon, 8), round(lat, 8)])
            return converted

        if len(gcj_tail) + (length - first_new) != length:
            # The cached prefix no longer lines up with the bounded history (for
            # example a reset); convert the whole tail instead of emitting a
            # GCJ list shorter than the ENU list.
            gcj_tail, first_new = [], 0
        gcj_tail.extend(convert(history_enu[first_new:]))
        self._gcj_tail_cache[association_id] = {
            "anchor_key": anchor_key,
            "converted_count": converted_count,
            "gcj_tail": gcj_tail,
        }
        return list(gcj_tail)

    def _incremental_trajectory_fields(
        self, association_id: int, history: dict[str, list], anchor
    ) -> tuple[list, list, object]:
        # Copy at the emission boundary only: the emitted outer lists must not
        # be aliased by the bounded history that the next frame rewrites, while
        # the point lists / lineage dicts are never mutated after insertion.
        trajectory_enu_m = list(history["trajectory_enu_m"])
        point_quality_lineage = list(history["point_quality_lineage"])
        if not anchor:
            # Drop the cache so a None -> value transition always rebuilds the
            # whole tail instead of reusing values from before the outage.
            self._gcj_tail_cache.pop(association_id, None)
            return trajectory_enu_m, point_quality_lineage, _GCJ_NOT_REQUESTED
        return (
            trajectory_enu_m,
            point_quality_lineage,
            self._incremental_gcj_tail(association_id, history["trajectory_enu_m"], anchor),
        )

    def _assemble_trajectory_item(
        self,
        raw: dict,
        frame_element: FrameElement,
        association_id: int,
        track_id: int,
        is_active: bool,
        geo_eligible: bool,
        road_eligible: bool,
        reasons: list,
        quality: dict,
        anchor,
        trajectory_enu_m: list,
        point_quality_lineage: list,
        trajectory_gcj02: object,
    ) -> dict:
        """Shared emission contract for both the legacy and incremental paths."""
        item = dict(raw)
        item.update(
            {
                "track_id": track_id,
                "association_id": association_id,
                "trajectory_output_eligible": is_active,
                "geo_analytics_eligible": geo_eligible,
                "road_analytics_eligible": road_eligible,
                "tcc_analytics_eligible": bool(
                    frame_element.tcc_analytics_eligible
                ),
                "tracking_quality": (
                    (frame_element.tracking_diagnostics or {}).get(
                        "association_quality", "verified"
                    )
                ),
                "geo_reference_quality": quality.get(
                    "geo_status", quality.get("status", "degraded")
                ),
                "road_match_quality": (
                    "verified"
                    if road_eligible
                    else "missing"
                    if "lane_verified_map_required"
                    in (quality.get("reasons") or [])
                    else "degraded"
                ),
                "quality_reasons": reasons,
                "flight_phase": getattr(frame_element, "flight_phase", None),
                "flight_segment_id": getattr(
                    frame_element, "flight_segment_id", None
                ),
                "trajectory_enu_m": trajectory_enu_m,
                "point_quality_lineage": point_quality_lineage,
            }
        )
        if trajectory_gcj02 is not _GCJ_NOT_REQUESTED:
            item["anchor_gcj02"] = [round(anchor[0], 6), round(anchor[1], 6)]
            item["trajectory_gcj02"] = trajectory_gcj02
        return item

    def _enrich_trajectories(
        self,
        frame_element: FrameElement,
        active_association_ids: set[int],
        road_association_ids: set[int],
    ) -> None:
        raw_trajectories = getattr(frame_element, "association_trajectories", None) or []
        active_ids = {int(value) for value in (frame_element.id_list or [])}
        association_state_ids = set(
            (frame_element.tracking_diagnostics or {}).get("association_state_ids")
            or active_ids
        )
        for association_id in list(self._world_history):
            if association_id not in association_state_ids:
                self._drop_association_state(association_id)

        quality = getattr(frame_element, "geo_reference_quality", None) or {}
        quality_reasons = list(quality.get("reasons") or [])
        anchor = getattr(frame_element, "anchor_gcj02", None)
        geo_eligible = bool(frame_element.geo_analytics_eligible)
        road_analytics_eligible = bool(frame_element.road_analytics_eligible)
        enriched = []
        candidates = []
        for raw in raw_trajectories:
            association_id = int(raw.get("association_id", raw.get("track_id")))
            trajectory_px = raw.get("trajectory_px") or []
            if not trajectory_px:
                continue
            is_active = association_id in active_association_ids
            road_eligible = (
                road_analytics_eligible
                and association_id in road_association_ids
            )
            history = self._append_world_fact(
                frame_element,
                association_id,
                list(trajectory_px[-1]),
                geo_eligible,
            )
            reasons = [] if geo_eligible else quality_reasons.copy()
            if not road_eligible:
                reasons.extend(quality.get("road_reasons") or [])
            reasons = list(dict.fromkeys(reasons))
            track_id = self._track_id_by_association.get(association_id, association_id)
            if self._incremental:
                (
                    trajectory_enu_m,
                    point_quality_lineage,
                    trajectory_gcj02,
                ) = self._incremental_trajectory_fields(
                    association_id, history, anchor
                )
            else:
                (
                    trajectory_enu_m,
                    point_quality_lineage,
                    trajectory_gcj02,
                ) = self._legacy_trajectory_fields(history, anchor)
            item = self._assemble_trajectory_item(
                raw,
                frame_element,
                association_id,
                track_id,
                is_active,
                geo_eligible,
                road_eligible,
                reasons,
                quality,
                anchor,
                trajectory_enu_m,
                point_quality_lineage,
                trajectory_gcj02,
            )
            enriched.append(item)
            if not is_active:
                candidates.append(item)
        frame_element.association_trajectories = enriched
        frame_element.candidate_trajectories = candidates

    def update(self, frame_element: FrameElement) -> FrameElement:
        return self.process(frame_element)

    def flush(self, reason: str) -> dict:
        track_ids, association_ids = self._close_tracks()
        result = {
            "tracking_method": self.tracking_method,
            "terminated_track_ids": track_ids,
            "terminated_association_ids": association_ids,
            "termination_reason": reason,
        }
        self._world_history.clear()
        self._append_counts.clear()
        self._gcj_tail_cache.clear()
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
            closed_tracks, _ = self._close_tracks(
                set(terminated_association_ids)
            )
            terminated_formal_ids.extend(closed_tracks)

        active_association_ids = {int(value) for value in (frame_element.id_list or [])}
        association_state_ids = set(
            diagnostics.get("association_state_ids") or active_association_ids
        )
        associations_to_close = {
            association_id
            for association_id in self._track_id_by_association
            if association_id not in association_state_ids
        }
        if associations_to_close:
            closed_tracks, closed_associations = self._close_tracks(
                associations_to_close
            )
            terminated_formal_ids.extend(closed_tracks)
            terminated_association_ids.extend(closed_associations)
            termination_reason = termination_reason or "association_ended"

        for association_id in sorted(active_association_ids):
            if association_id not in self._track_id_by_association:
                self._track_id_by_association[association_id] = self._allocate_track_id()

        road_association_ids = (
            set(active_association_ids)
            if bool(frame_element.road_analytics_eligible)
            else set()
        )

        frame_element.trajectory_output_eligible = bool(active_association_ids)
        frame_element.trajectory_association_ids = sorted(active_association_ids)
        frame_element.track_id_by_association = {
            association_id: self._track_id_by_association[association_id]
            for association_id in sorted(active_association_ids)
        }
        frame_element.formal_track_ids = sorted(road_association_ids)
        frame_element.formal_track_id_by_association = {
            association_id: self._track_id_by_association[association_id]
            for association_id in sorted(road_association_ids)
        }
        frame_element.previous_formal_track_id_by_association = {
            association_id: self._previous_track_id_by_association[association_id]
            for association_id in sorted(active_association_ids)
            if association_id in self._previous_track_id_by_association
        }
        self._enrich_trajectories(
            frame_element,
            active_association_ids,
            road_association_ids,
        )
        diagnostics.update(
            {
                "world_projection_stage": "post_bytetrack",
                "tracking_quality": (
                    "verified" if active_association_ids else "degraded"
                ),
                "trajectory_track_count": len(active_association_ids),
                "formal_track_count": len(road_association_ids),
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
        return frame_element
