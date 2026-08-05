import re

from utils_local.replay_topics import (
    CANONICAL_CONSUMER_PATTERN,
    REPLAY_V2_CONSUMER_GROUP,
    REPLAY_V2_CONSUMER_PATTERN,
    build_replay_v2_topics,
)
from nodes.KafkaProducerNode import KafkaProducerNode


def test_replay_v2_topics_are_stable_and_invisible_to_the_live_consumer():
    topics = build_replay_v2_topics("SRC-MP4729-JS-0729-3MS")

    assert topics.statistics == "uav_replay_v2_statistics_SRC-MP4729-JS-0729-3MS"
    assert topics.track_complete == "uav_replay_v2_track_complete_SRC-MP4729-JS-0729-3MS"
    assert topics.conflicts == "uav_replay_v2_conflicts_SRC-MP4729-JS-0729-3MS"
    assert topics.telemetry == "uav_replay_v2_telemetry_SRC-MP4729-JS-0729-3MS"
    assert topics.mission == "uav_replay_v2_mission_SRC-MP4729-JS-0729-3MS"
    assert REPLAY_V2_CONSUMER_GROUP == "uav-platform-replay-v2"

    for topic in topics:
        assert re.fullmatch(REPLAY_V2_CONSUMER_PATTERN, topic)
        assert re.fullmatch(CANONICAL_CONSUMER_PATTERN, topic) is None


def test_pipeline_selects_v2_topics_by_stable_source_profile_without_changing_live_defaults():
    assert KafkaProducerNode._topics_for_profile("live", "SRC-1", 7) == (
        "uav_statistics_7",
        "uav_track_complete_7",
        "uav_conflicts_7",
        "uav_telemetry_7",
        None,
    )
    assert KafkaProducerNode._topics_for_profile("replay_v2", "SRC-1", 7) == (
        "uav_replay_v2_statistics_SRC-1",
        "uav_replay_v2_track_complete_SRC-1",
        "uav_replay_v2_conflicts_SRC-1",
        "uav_replay_v2_telemetry_SRC-1",
        "uav_replay_v2_mission_SRC-1",
    )
