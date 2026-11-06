"""Stable Kafka Topic identities for live traffic and sealed replay facts."""

from __future__ import annotations

import re
from dataclasses import astuple, dataclass


FIXED_TOPICS = {
    "uav_stats": "uav_statistics", "uav_track_complete": "uav_track_complete",
    "uav_conflict": "uav_conflicts", "uav_telemetry": "uav_telemetry",
    "uav_replay_mission": "uav_missions", "uav_track_relation": "uav_track_relations",
    "uav_enforcement_clue": "uav_enforcement_clues", "uav_system_metrics": "uav_system_metrics",
    "uav_ingest_receipt": "uav_ingest_receipts",
}
CANONICAL_CONSUMER_PATTERN = r"^(?:uav_statistics|uav_track_complete|uav_conflicts|uav_telemetry|uav_missions|uav_track_relations|uav_enforcement_clues|uav_system_metrics)$"
REPLAY_V2_CONSUMER_PATTERN = r"^(?:uav_statistics|uav_track_complete|uav_conflicts|uav_telemetry|uav_missions|uav_track_relations|uav_enforcement_clues|uav_system_metrics)$"
REPLAY_V2_CONSUMER_GROUP = "uav-platform-replay-v2"


@dataclass(frozen=True, slots=True)
class ReplayV2Topics:
    statistics: str
    track_complete: str
    conflicts: str
    telemetry: str
    mission: str

    def __iter__(self):
        return iter(astuple(self))


def build_replay_v2_topics(source_key: str) -> ReplayV2Topics:
    """Return the fixed Topic family for one stable SourceProfile/Camera key."""
    value = str(source_key)
    if not value or len(value) > 128 or re.fullmatch(r"[A-Za-z0-9._-]+", value) is None:
        raise ValueError("source_key contains unsupported Kafka Topic characters")
    prefix = "uav"
    return ReplayV2Topics(
        statistics=f"{prefix}_statistics",
        track_complete=f"{prefix}_track_complete",
        conflicts=f"{prefix}_conflicts",
        telemetry=f"{prefix}_telemetry",
        mission="uav_missions",
    )
