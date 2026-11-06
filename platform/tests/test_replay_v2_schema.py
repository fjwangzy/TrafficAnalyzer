import importlib.util
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app.core.database import Base
from app.models import replay_v2  # noqa: F401
from app.models.mission import MessageInbox


def test_canonical_baseline_keeps_replay_tables_on_their_own_migration_track(monkeypatch):
    migration = Path(__file__).resolve().parents[1] / "alembic/versions/20260714_0001_road9_survey_baseline.py"
    spec = importlib.util.spec_from_file_location("canonical_baseline", migration)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            monkeypatch.setattr(module.op, "get_bind", lambda: connection)
            module.upgrade()
            tables = set(inspect(connection).get_table_names())
            assert {"uav_users", "uav_missions", "uav_survey_tasks"} <= tables
            assert not any(name.startswith("uav_replay_v2_") for name in tables)
    finally:
        engine.dispose()


def test_replay_v2_uses_an_independent_migration_track_and_fact_tables():
    platform_dir = Path(__file__).resolve().parents[1]
    config = Config(str(platform_dir / "alembic_replay_v2.ini"))
    config.set_main_option("script_location", str(platform_dir / "alembic_replay_v2"))

    assert (platform_dir / "alembic_replay_v2" / "env.py").is_file()
    assert config.get_main_option("version_table") == "uav_replay_v2_alembic_version"
    assert ScriptDirectory.from_config(config).get_current_head() == "20261104_rv2_0007"
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


@pytest.mark.parametrize("path,model,index_name,identity", [
    ("alembic_replay_v2/versions/20261019_rv2_0005_inbox_transport_index.py", replay_v2.ReplayV2MessageInbox, "ix_uav_replay_v2_inbox_offset", ("message_id",)),
    ("alembic/versions/20261019_0021_inbox_transport_index.py", MessageInbox, "ix_uav_inbox_topic_partition_offset", ("source_system", "message_id")),
])
def test_transport_index_migration_also_accepts_fresh_model_bootstrap(monkeypatch, path, model, index_name, identity):
    migration = Path(__file__).resolve().parents[1] / path
    spec = importlib.util.spec_from_file_location("replay_transport_index", migration)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            table = model.__table__
            table.create(connection)
            monkeypatch.setattr(module.op, "get_bind", lambda: connection)
            module.upgrade()
            module.upgrade()
            inspector = inspect(connection)
            assert any(index["name"] == index_name and not index["unique"] for index in inspector.get_indexes(table.name))
            assert {tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name)} == {identity}
    finally:
        engine.dispose()


def test_replay_v2_metric_samples_have_versioned_timescale_policies():
    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic_replay_v2"
        / "versions"
        / "20260804_rv2_0002_metric_sample_timescale.py"
    ).read_text()

    assert "configure_timescale" in migration
    migration = (Path(__file__).resolve().parents[1] / "app/core/timeseries.py").read_text()
    assert "create_hypertable" in migration
    assert '("compression", "7 days")' in migration
    assert '("retention", "90 days")' in migration
    assert "if_not_exists => TRUE" in migration
    assert "migrate_data => TRUE" in migration


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
