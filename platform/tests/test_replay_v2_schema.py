from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models import replay_v2  # noqa: F401
from app.core.database import Base


def test_replay_v2_uses_an_independent_migration_track_and_fact_tables():
    platform_dir = Path(__file__).resolve().parents[1]
    config = Config(str(platform_dir / "alembic_replay_v2.ini"))
    config.set_main_option("script_location", str(platform_dir / "alembic_replay_v2"))

    assert config.get_main_option("version_table") == "uav_replay_v2_alembic_version"
    assert ScriptDirectory.from_config(config).get_current_head() == "20260805_rv2_0003"
    assert {
        "uav_replay_v2_missions",
        "uav_replay_v2_message_inbox",
        "uav_replay_v2_message_dead_letters",
        "uav_replay_v2_track_events",
        "uav_replay_v2_track_points",
        "uav_replay_v2_episodes",
        "uav_replay_v2_maneuvers",
        "uav_replay_v2_conflict_events",
        "uav_replay_v2_telemetry_metrics",
        "uav_replay_v2_traffic_metric_samples",
        "uav_replay_v2_intersection_metrics_5min",
        "uav_replay_v2_link_metrics_5min",
        "uav_replay_v2_lane_metrics_5min",
        "uav_replay_v2_turn_metrics_5min",
        "uav_replay_v2_inter_evaluation_5min_mm",
    } <= set(Base.metadata.tables)


def test_replay_v2_metric_samples_have_versioned_timescale_policies():
    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic_replay_v2"
        / "versions"
        / "20260804_rv2_0002_metric_sample_timescale.py"
    ).read_text()

    assert "create_hypertable" in migration
    assert "add_compression_policy" in migration
    assert "add_retention_policy" in migration
    assert "INTERVAL '7 days'" in migration
    assert "INTERVAL '90 days'" in migration


def test_each_five_minute_road_grain_has_its_own_business_key_constraint():
    expected = {
        replay_v2.ReplayV2LinkMetric5Min: ("window_start", "inter_id", "source_profile_id", "mission_id", "calc_version", "link_id"),
        replay_v2.ReplayV2LaneMetric5Min: ("window_start", "inter_id", "source_profile_id", "mission_id", "calc_version", "lane_id"),
        replay_v2.ReplayV2TurnMetric5Min: ("window_start", "inter_id", "source_profile_id", "mission_id", "calc_version", "movement_key"),
    }
    for model, columns in expected.items():
        unique_sets = {
            tuple(column.name for column in constraint.columns)
            for constraint in model.__table__.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
        assert columns in unique_sets
