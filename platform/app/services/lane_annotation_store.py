"""File-backed lane annotation tasks and saved lane parameters."""
from __future__ import annotations

import base64
import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class LaneAnnotationStore:
    """Tracks hover-created annotation tasks and reusable lane parameters."""

    def __init__(
        self,
        db_path: str,
        hover_seconds: float = 30.0,
        hover_radius_m: float = 1.5,
    ) -> None:
        self.db_path = Path(db_path)
        self.hover_seconds = hover_seconds
        self.hover_radius_m = hover_radius_m
        self.export_dir = self.db_path.parent / "lane_annotations"
        self.image_dir = self.db_path.parent / "lane_task_images"
        self._hover_state: dict[str, dict[str, Any]] = {}

    def list_tasks(self) -> list[dict[str, Any]]:
        db = self._load()
        return sorted(
            db.get("tasks", []),
            key=lambda item: item.get("created_at", 0),
            reverse=True,
        )

    def list_annotations(self) -> list[dict[str, Any]]:
        db = self._load()
        return sorted(
            db.get("annotations", {}).values(),
            key=lambda item: item.get("updated_at", 0),
            reverse=True,
        )

    def get_annotation(self, intersection_id: str) -> dict[str, Any] | None:
        return self._load().get("annotations", {}).get(intersection_id)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        for task in self._load().get("tasks", []):
            if task.get("task_id") == task_id:
                return task
        return None

    def get_task_image_path(self, task_id: str) -> Path | None:
        task = self.get_task(task_id)
        if not task:
            return None
        image_path = task.get("image_path")
        if not image_path:
            return None
        path = Path(image_path)
        return path if path.exists() else None

    def ensure_task_from_snapshot(
        self,
        intersection_id: str,
        image_bytes: bytes,
        image_width: int,
        image_height: int,
        source_frame_id: str,
        roads: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create an idempotent task from a persisted real keyframe; hover tasks remain the live trigger."""
        db = self._load()
        existing = next(
            (task for task in db.get("tasks", []) if task.get("source_frame_id") == source_frame_id),
            None,
        )
        if existing:
            return existing
        now = time.time()
        safe_frame = "".join(char if char.isalnum() or char in "-_" else "_" for char in source_frame_id)
        task_id = f"lane-{intersection_id}-{safe_frame}"[:120]
        self.image_dir.mkdir(parents=True, exist_ok=True)
        image_path = self.image_dir / f"{task_id}.jpg"
        with image_path.open("wb") as fh:
            fh.write(image_bytes)
        task = {
            "task_id": task_id,
            "intersection_id": intersection_id,
            "status": "pending",
            "created_at": now,
            "hover_started_at": None,
            "is_hovering": False,
            "trigger": "persisted_survey_keyframe",
            "source_frame_id": source_frame_id,
            "roads": roads or {},
            "lane_count": 0,
            "image_path": str(image_path),
            "image_url": f"/api/v1/calibration/lane-tasks/{task_id}/image",
            "image_width": image_width,
            "image_height": image_height,
        }
        db.setdefault("tasks", []).append(task)
        self._write(db)
        return task

    def observe_stats(self, intersection_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        if not data.get("is_hovering"):
            self._hover_state.pop(intersection_id, None)
            return None

        position = data.get("drone_position") or {}
        point = self._position_point(position)
        if point is None:
            return None

        now = time.time()
        state = self._hover_state.get(intersection_id)
        if not state or self._distance_m(state["point"], point) > self.hover_radius_m:
            self._hover_state[intersection_id] = {"point": point, "started_at": now}
            return None

        if now - state["started_at"] < self.hover_seconds:
            return None

        if self.get_annotation(intersection_id):
            return None

        return self._ensure_task(intersection_id, data, state["started_at"], now)

    def save_annotation(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        db = self._load()
        task = next((t for t in db.get("tasks", []) if t.get("task_id") == task_id), None)
        if task is None:
            raise KeyError(task_id)

        lanes = payload.get("lanes")
        if not isinstance(lanes, list) or not lanes:
            raise ValueError("lanes must be a non-empty list")

        normalized_lanes = [self._normalize_lane(idx, lane) for idx, lane in enumerate(lanes, start=1)]
        intersection_id = task["intersection_id"]
        now = time.time()
        annotation = {
            "intersection_id": intersection_id,
            "task_id": task_id,
            "status": "active",
            "lanes": normalized_lanes,
            "roads": payload.get("roads") or task.get("roads") or {},
            "source": "manual",
            "created_at": db.get("annotations", {}).get(intersection_id, {}).get("created_at", now),
            "updated_at": now,
            "export_path": str(self._export_path(intersection_id)),
        }

        db.setdefault("annotations", {})[intersection_id] = annotation
        task["status"] = "completed"
        task["completed_at"] = now
        task["lane_count"] = len(normalized_lanes)
        self._write(db)
        self._export_annotation(annotation)
        return annotation

    def _ensure_task(
        self,
        intersection_id: str,
        data: dict[str, Any],
        hover_started_at: float,
        now: float,
    ) -> dict[str, Any]:
        db = self._load()
        for task in db.get("tasks", []):
            if task.get("intersection_id") == intersection_id and task.get("status") == "pending":
                if not task.get("image_path"):
                    self._attach_snapshot(task, data)
                    self._write(db)
                return task

        task_id = f"lane-{intersection_id}-{int(now)}"
        task = {
            "task_id": task_id,
            "intersection_id": intersection_id,
            "status": "pending",
            "created_at": now,
            "hover_started_at": hover_started_at,
            "drone_position": data.get("drone_position"),
            "is_hovering": True,
            "roads": self._roads_from_stats(data),
            "lane_count": 0,
        }
        self._attach_snapshot(task, data)
        db.setdefault("tasks", []).append(task)
        self._write(db)
        logger.info("Created lane annotation task %s", task["task_id"])
        return task

    def _attach_snapshot(self, task: dict[str, Any], data: dict[str, Any]) -> None:
        encoded = data.get("annotation_snapshot_jpeg")
        if not encoded:
            return

        try:
            image_bytes = base64.b64decode(encoded)
        except Exception as exc:
            logger.warning("Failed to decode annotation snapshot: %s", exc)
            return

        self.image_dir.mkdir(parents=True, exist_ok=True)
        image_path = self.image_dir / f"{task['task_id']}.jpg"
        with image_path.open("wb") as fh:
            fh.write(image_bytes)

        task["image_path"] = str(image_path)
        task["image_url"] = f"/api/v1/calibration/lane-tasks/{task['task_id']}/image"
        task["image_width"] = data.get("annotation_snapshot_width")
        task["image_height"] = data.get("annotation_snapshot_height")

    def _load(self) -> dict[str, Any]:
        try:
            if self.db_path.exists():
                with self.db_path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    if isinstance(data, dict):
                        data.setdefault("tasks", [])
                        data.setdefault("annotations", {})
                        return data
        except Exception as exc:
            logger.error("Failed to load lane annotation DB: %s", exc)
        return {"tasks": [], "annotations": {}}

    def _write(self, data: dict[str, Any]) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.db_path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.db_path)

    def _export_annotation(self, annotation: dict[str, Any]) -> None:
        payload = {
            "roads": annotation.get("roads", {}),
            "lanes": {
                lane["lane_id"]: {
                    "name": lane["name"],
                    "direction": lane["direction"],
                    "polygon": lane["polygon"],
                }
                for lane in annotation["lanes"]
            },
            "calibration": {"source": "manual_lane_annotation"},
        }
        path = self._export_path(annotation["intersection_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)

    def _export_path(self, intersection_id: str) -> Path:
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in intersection_id)
        return self.export_dir / f"{safe_id}.json"

    @staticmethod
    def _normalize_lane(idx: int, lane: dict[str, Any]) -> dict[str, Any]:
        polygon = lane.get("polygon")
        if not isinstance(polygon, list) or len(polygon) < 6 or len(polygon) % 2 != 0:
            raise ValueError("each lane polygon must contain at least 3 x/y points")
        return {
            "lane_id": str(lane.get("lane_id") or f"L{idx}"),
            "name": str(lane.get("name") or f"车道 {idx}"),
            "direction": str(lane.get("direction") or "unknown"),
            "polygon": [float(v) for v in polygon],
        }

    @staticmethod
    def _position_point(position: dict[str, Any]) -> tuple[float, float] | None:
        try:
            return float(position["easting_m"]), float(position["northing_m"])
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    @staticmethod
    def _roads_from_stats(data: dict[str, Any]) -> dict[str, Any]:
        roads = data.get("road_polygons")
        if isinstance(roads, dict):
            return roads
        roads = data.get("roads")
        return roads if isinstance(roads, dict) else {}
