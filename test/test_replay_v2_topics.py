import re

from utils_local.replay_topics import (
    CANONICAL_CONSUMER_PATTERN,
    REPLAY_V2_CONSUMER_GROUP,
    REPLAY_V2_CONSUMER_PATTERN,
    build_replay_v2_topics,
)
from nodes.KafkaProducerNode import KafkaProducerNode


def test_replay_v2_topics_are_fixed_and_share_business_families():
    topics = build_replay_v2_topics("SRC-MP4729-JS-0729-3MS")

    assert topics.statistics == "uav_statistics"
    assert topics.track_complete == "uav_track_complete"
    assert topics.conflicts == "uav_conflicts"
    assert topics.telemetry == "uav_telemetry"
    assert topics.mission == "uav_missions"
    assert REPLAY_V2_CONSUMER_GROUP == "uav-platform-replay-v2"

    for topic in topics:
        assert re.fullmatch(REPLAY_V2_CONSUMER_PATTERN, topic)
        assert re.fullmatch(CANONICAL_CONSUMER_PATTERN, topic)


def test_pipeline_selects_v2_topics_by_stable_source_profile_without_changing_live_defaults():
    assert KafkaProducerNode._topics_for_profile("live", "SRC-1", 7) == (
        "uav_statistics",
        "uav_track_complete",
        "uav_conflicts",
        "uav_telemetry",
        None,
    )
    assert KafkaProducerNode._topics_for_profile("replay_v2", "SRC-1", 7) == (
        "uav_statistics",
        "uav_track_complete",
        "uav_conflicts",
        "uav_telemetry",
        "uav_missions",
    )
