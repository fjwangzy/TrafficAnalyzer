import sys

import pytest

import scripts.run_replay_v2_acceptance as acceptance
from scripts.run_replay_v2_acceptance import (
    aggregate_gate,
    _message_size_summary,
    build_v2_run_identity,
    parse_args,
    topic_end_offsets,
    ensure_topics,
)


def test_v2_acceptance_identity_uses_stable_topics_and_unique_runtime_lineage():
    first = build_v2_run_identity("SRC-MP4NEW-HY-0625-AM", nonce="a1")
    second = build_v2_run_identity("SRC-MP4NEW-HY-0625-AM", nonce="b2")

    assert first["topics"] == second["topics"]
    assert first["mission_id"] != second["mission_id"]
    assert first["pipeline_id"] != second["pipeline_id"]
    assert first["topics"][-1] == "uav_replay_v2_mission_SRC-MP4NEW-HY-0625-AM"


def test_v2_acceptance_defaults_to_external_private_tmp_artifacts(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_replay_v2_acceptance.py"])

    args = parse_args()

    assert str(args.output_dir).startswith("/private/tmp/traffic-analyzer-replay-v2-")
    assert args.base_url == "http://127.0.0.1:8200"
    assert args.frame_stride == 10


def test_v2_acceptance_records_serialized_message_size_distribution():
    summary = _message_size_summary([{"value": "a"}, {"value": "abcdefgh"}])

    assert summary["count"] == 2
    assert summary["total_bytes"] > 0
    assert summary["max_bytes"] > summary["median_bytes"]


def test_canonical_topic_guard_does_not_request_missing_topics(monkeypatch):
    requested = []

    class FakeAdmin:
        def __init__(self, **_kwargs):
            pass

        def list_topics(self):
            return ["uav_conflicts_18101"]

        def close(self):
            pass

    class FakeConsumer:
        def __init__(self, **_kwargs):
            pass

        def partitions_for_topic(self, topic):
            requested.append(topic)
            return {0}

        def end_offsets(self, partitions):
            return {partition: 3 for partition in partitions}

        def close(self):
            pass

    monkeypatch.setattr(acceptance, "KafkaAdminClient", FakeAdmin)
    monkeypatch.setattr(acceptance, "KafkaConsumer", FakeConsumer)

    result = topic_end_offsets(
        "unused:9092",
        ["uav_conflicts_18101", "uav_conflicts_18103"],
    )

    assert result == {"uav_conflicts_18101": {0: 3}}
    assert requested == ["uav_conflicts_18101"]


def test_acceptance_topics_use_the_bounded_local_retention_contract(monkeypatch):
    created = []
    altered = []

    class FakeAdmin:
        def __init__(self, **_kwargs):
            pass

        def list_topics(self):
            return []

        def create_topics(self, topics, validate_only):
            assert validate_only is False
            created.extend(topics)

        def alter_configs(self, resources):
            altered.extend(resources)

        def close(self):
            pass

    monkeypatch.setattr(acceptance, "KafkaAdminClient", FakeAdmin)

    assert ensure_topics("unused:9092", ["uav_replay_v2_statistics_SRC-1"]) == [
        "uav_replay_v2_statistics_SRC-1"
    ]
    assert created[0].topic_configs == {
        "retention.ms": "21600000",
        "retention.bytes": "268435456",
        "cleanup.policy": "delete",
    }
    assert altered[0].name == "uav_replay_v2_statistics_SRC-1"
    assert altered[0].configs == created[0].topic_configs


def test_acceptance_requires_actual_and_typical_dws_and_road_grains_when_verified():
    base = {
        "intersection_5min": 2,
        "typical_5min_mm": 2,
        "link_5min": 1,
        "lane_5min": 1,
        "turn_5min": 1,
    }

    assert aggregate_gate(base, require_road_grains=True)["passed"] is True
    assert aggregate_gate({**base, "turn_5min": 0}, require_road_grains=True)["passed"] is False
    assert aggregate_gate({**base, "link_5min": 0, "lane_5min": 0, "turn_5min": 0}, require_road_grains=False)["passed"] is True


@pytest.mark.asyncio
async def test_reconciliation_waits_for_aggregate_convergence_after_base_facts(monkeypatch):
    reads = iter([
        {
            "stats": 1, "tracks": 1, "conflicts": 0, "telemetry": 1, "missions": 1,
            "mission_status": "sealed", "intersection_5min": 0, "typical_5min_mm": 0,
            "link_5min": 0, "lane_5min": 0, "turn_5min": 0,
        },
        {
            "stats": 1, "tracks": 1, "conflicts": 0, "telemetry": 1, "missions": 1,
            "mission_status": "sealed", "intersection_5min": 1, "typical_5min_mm": 1,
            "link_5min": 1, "lane_5min": 1, "turn_5min": 1,
        },
    ])
    async def fake_counts(_mission_id):
        return next(reads)

    monkeypatch.setattr(acceptance, "replay_v2_counts", fake_counts)
    monkeypatch.setattr(acceptance.asyncio, "sleep", _no_sleep)

    result = await acceptance.wait_for_reconciliation(
        "MSN-1",
        {"stats": 1, "tracks": 1, "conflicts": 0, "telemetry": 1, "missions": 1},
        require_road_grains=True,
    )

    assert result["road9"]["turn_5min"] == 1
async def _no_sleep(_seconds):
    return None
