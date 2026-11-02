"""Idempotent conversion of application tables after DBA enables TimescaleDB."""
from sqlalchemy import text

BASE_TABLES = (
    ("uav_traffic_metrics", "observed_at"), ("uav_system_metrics", "observed_at"),
    ("uav_telemetry_metrics", "observed_at"), ("uav_track_points", "observed_at"),
    ("uav_conflict_events", "occurred_at"),
)
REPLAY_TABLE = "uav_replay_v2_traffic_metric_samples"


def configure_timescale(connection, *, replay_v2=False):
    if not connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='timescaledb')")):
        return False
    tables = BASE_TABLES + (((REPLAY_TABLE, "sampled_at"),) if replay_v2 else ())
    for table, column in tables:
        converted = connection.scalar(text(
            "SELECT EXISTS (SELECT 1 FROM timescaledb_information.hypertables "
            "WHERE hypertable_schema=current_schema() AND hypertable_name=:table)"
        ), {"table": table})
        if not converted:
            if table == REPLAY_TABLE:
                connection.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_pkey"))
                connection.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT {table}_pkey PRIMARY KEY (id, sampled_at)"))
            connection.execute(text(
                f"SELECT create_hypertable('{table}', by_range('{column}'), "
                "if_not_exists => TRUE, migrate_data => TRUE)"
            ))
    if replay_v2:
        connection.execute(text(
            f"ALTER TABLE {REPLAY_TABLE} SET (timescaledb.compress, "
            "timescaledb.compress_segmentby = 'mission_id,inter_id,source_profile_id', "
            "timescaledb.compress_orderby = 'sampled_at DESC')"
        ))
        for policy, interval in (("compression", "7 days"), ("retention", "90 days")):
            connection.execute(text(
                f"SELECT add_{policy}_policy('{REPLAY_TABLE}', INTERVAL '{interval}', if_not_exists => TRUE)"
            ))
    return True
