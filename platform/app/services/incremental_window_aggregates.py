"""Bounded one-window aggregation from paged immutable full-sequence summaries."""

from collections import Counter
from datetime import datetime, timedelta

from utils_local.trajectory_sampling import validate_summary

from app.services.replay_v2_aggregates import (
    _at_offset,
    _empty_bucket,
    _fact_row,
    _record_episode,
    _window_start,
)


class WindowAccumulator:
    def __init__(self, mission, window, *, calc_version="replay-v2-aggregate/v2"):
        self.mission, self.window, self.calc_version = mission, window, calc_version
        self.buckets = {}

    def bucket(self, grain="intersection", dimension="intersection"):
        return self.buckets.setdefault((grain, dimension), _empty_bucket())

    def add(self, journey, *, root=None):
        root = root or journey
        key = str(root["track_id"])
        dimensions = {
            "link": root.get("matched_link_id"),
            "lane": root.get("matched_lane_key"),
            "turn": root.get("movement_key")
            or (f"turn_behavior:{root['turn_behavior']}" if root.get("turn_behavior") else None),
        }
        targets = [self.bucket()] + [
            self.bucket(grain, str(value)) for grain, value in dimensions.items() if value
        ]
        if (
            _window_start(_at_offset(self.mission["started_at"], root.get("started_offset_ms")))
            == self.window
        ):
            for bucket in targets:
                bucket["track_ids"].add(key)
        sampling = journey.get("sampling") or {}
        if sampling.get("algorithm_version") == "event-faithful/v2":
            summary = validate_summary(
                sampling,
                time_basis=self.mission["started_at"],
                source_count=journey["source_point_count"],
            )
            for window in summary["windows"]:
                if datetime.fromisoformat(window["window_start"]) == self.window:
                    for bucket in targets:
                        bucket["speed_histogram"].update(Counter(dict(window["histogram"])))
        else:
            for point in journey.get("points") or []:
                speed = (point.get("speed") or {}).get("ema_kmh")
                if (
                    speed is not None
                    and _window_start(_at_offset(self.mission["started_at"], point["offset_ms"]))
                    == self.window
                ):
                    for bucket in targets:
                        bucket["speeds"].append(float(speed))
        for behavior in journey.get("episodes") or []:
            if (
                _window_start(_at_offset(self.mission["started_at"], behavior["start_offset_ms"]))
                == self.window
            ):
                for bucket in targets:
                    _record_episode(bucket, key, behavior["kind"])
        for behavior in journey.get("maneuvers") or []:
            if (
                behavior["kind"] == "geometric_u_turn"
                and _window_start(
                    _at_offset(self.mission["started_at"], behavior["start_offset_ms"])
                )
                == self.window
            ):
                for bucket in targets:
                    bucket["u_turns"].add(key)

    def sample(self, coverage):
        if coverage is not None:
            self.bucket()["coverage"].append(float(coverage))

    def facts(self):
        rows = {grain: [] for grain in ("intersection", "link", "lane", "turn")}
        dimension_names = {"link": "link_id", "lane": "lane_id", "turn": "movement_key"}
        for (grain, dimension), bucket in sorted(self.buckets.items()):
            row = {
                "window_start": self.window,
                "window_end": self.window + timedelta(minutes=5),
                "inter_id": self.mission["inter_id"],
                "source_profile_id": self.mission["source_profile_id"],
                "mission_id": self.mission["id"],
                "calc_version": self.calc_version,
                **_fact_row(bucket),
            }
            if grain != "intersection":
                row[dimension_names[grain]] = dimension
            rows[grain].append(row)
        return rows
