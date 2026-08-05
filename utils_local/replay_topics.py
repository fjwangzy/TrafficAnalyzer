"""Stable Kafka Topic identities for live traffic and sealed replay facts."""

from __future__ import annotations

import re
from dataclasses import astuple, dataclass


CANONICAL_CONSUMER_PATTERN = (
    r"(?:uav_(?:statistics|track_complete|conflicts|telemetry)_[A-Za-z0-9._-]+"
    r"|uav_system_metrics)"
)
REPLAY_V2_CONSUMER_PATTERN = (
    r"uav_replay_v2_(?:statistics|track_complete|conflicts|telemetry|mission)_"
    r"[A-Za-z0-9._-]+"
)
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
    prefix = "uav_replay_v2"
    return ReplayV2Topics(
        statistics=f"{prefix}_statistics_{value}",
        track_complete=f"{prefix}_track_complete_{value}",
        conflicts=f"{prefix}_conflicts_{value}",
        telemetry=f"{prefix}_telemetry_{value}",
        mission=f"{prefix}_mission_{value}",
    )
