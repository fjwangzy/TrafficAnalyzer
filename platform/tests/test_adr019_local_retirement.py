import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "validate_adr019_local_retirement.py"
SPEC = importlib.util.spec_from_file_location("validate_adr019_local_retirement", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_live_retirement_check_requires_explicit_guard(monkeypatch):
    monkeypatch.delenv("ALLOW_ADR019_LOCAL_RETIREMENT_CHECK", raising=False)
    with pytest.raises(RuntimeError, match="ALLOW_ADR019_LOCAL_RETIREMENT_CHECK=1"):
        module.validate()


def test_retirement_allowlists_are_fixed_to_approved_assets():
    assert module.OLD_VOLUMES == {
        "trafficanalyzer_postgres_data",
        "trafficanalyzer_timescaledb_local_data",
        "traffic_analyzer_mp4new_road9_target_data",
    }
    assert module.EXPECTED_CONTAINERS == {
        "traffic_analyzer-road9-1",
        "traffic_analyzer-kafka-1",
        "traffic_analyzer-platform-1",
        "traffic_analyzer-console2-1",
        "traffic_analyzer-nginx-1",
    }
    assert module.EXPECTED_HYPERTABLES == {
        "uav_conflict_events",
        "uav_system_metrics",
        "uav_telemetry_metrics",
        "uav_track_points",
        "uav_traffic_metrics",
    }


def test_canonical_topic_check_ignores_kafka_internal_topics():
    assert module._canonical_topics_only(["__consumer_offsets", "uav_statistics_local_probe"])
    assert not module._canonical_topics_only(["__consumer_offsets"])
    assert not module._canonical_topics_only(["__consumer_offsets", "statistics_1"])


def test_live_retirement_gate_tracks_current_schema_head():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'revision == "20260716_0011"' in source
    assert "business_rows == 0" not in source
