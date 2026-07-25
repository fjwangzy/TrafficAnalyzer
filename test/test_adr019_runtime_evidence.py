from scripts.validate_adr019_local_retirement import (
    build_local_validation_environment,
    build_runtime_report,
    evaluate_runtime_snapshot,
)
from scripts.audit_adr019_retirement import runtime_evidence_passed


def _native_runtime_snapshot() -> dict:
    return {
        "containers": {
            "running": ["traffic_analyzer-kafka-1", "traffic_analyzer-road9-1"],
            "all": [
                "traffic_analyzer-kafka-1",
                "traffic_analyzer-road9-1",
                "traffic_analyzer-platform-1",
                "traffic_analyzer-console2-1",
                "traffic_analyzer-nginx-1",
            ],
            "states": {
                "traffic_analyzer-kafka-1": {"status": "running", "health": "healthy"},
                "traffic_analyzer-road9-1": {"status": "running", "health": "healthy"},
            },
        },
        "native_platform": {
            "status": "ready",
            "services": {
                "database": "healthy",
                "kafka": "healthy",
                "timescaledb": "healthy",
                "pipeline_manager": "healthy",
            },
            "pipelines_active": 0,
            "single_instance": True,
            "mps_available": True,
        },
        "database": {
            "name": "road9",
            "alembic_revision": "20260723_0019",
            "hypertables": 5,
            "hypertable_names": [
                "uav_conflict_events",
                "uav_system_metrics",
                "uav_telemetry_metrics",
                "uav_track_points",
                "uav_traffic_metrics",
            ],
            "admin_rows": 1,
            "user_rows": 3,
            "legacy_database_count": 0,
            "migration_isolation_tables": [],
        },
        "kafka": {"topics": ["__consumer_offsets", "uav_statistics_10"]},
        "storage": {
            "stable_volume_mounted": True,
            "old_storage_retained": True,
            "old_storage_unmounted": True,
        },
        "retention": {"at_least_seven_days": True},
        "resilience": {
            "database_outage_recovered": True,
            "thirty_minute_soak": True,
        },
    }


def test_native_macos_runtime_is_the_local_adr019_evidence_topology():
    result = evaluate_runtime_snapshot(
        _native_runtime_snapshot(), expected_schema_head="20260723_0019"
    )

    assert result["passed"] is True
    assert result["checks"]["native_platform_ready"] is True
    assert result["checks"]["docker_application_containers_stopped"] is True


def test_duplicate_docker_platform_blocks_native_runtime_evidence():
    snapshot = _native_runtime_snapshot()
    snapshot["containers"]["running"].append("traffic_analyzer-platform-1")
    snapshot["containers"]["states"]["traffic_analyzer-platform-1"] = {
        "status": "running",
        "health": "healthy",
    }

    result = evaluate_runtime_snapshot(
        snapshot, expected_schema_head="20260723_0019"
    )

    assert result["passed"] is False
    assert result["checks"]["docker_application_containers_stopped"] is False


def test_runtime_report_records_native_topology_and_current_schema_head():
    snapshot = _native_runtime_snapshot()

    report = build_runtime_report(
        snapshot,
        expected_schema_head="20260723_0019",
        generated_at="2026-07-25T00:00:00Z",
    )

    assert report["schema_version"] == "uav.adr019-local-retirement/v2"
    assert report["runtime_topology"] == "native_macos_platform_with_docker_infra"
    assert report["database"]["alembic_revision"] == "20260723_0019"
    assert report["passed"] is True


def test_local_validation_environment_fills_empty_secrets_without_overwriting_values():
    environment = build_local_validation_environment(
        {
            "ROAD9_PASSWORD": "",
            "JWT_SECRET_KEY": "operator-provided-secret",
        }
    )

    assert environment["ROAD9_PASSWORD"] == "traffic123"
    assert environment["JWT_SECRET_KEY"] == "operator-provided-secret"
    assert environment["CORS_ORIGINS"] == '["http://127.0.0.1:8080"]'
    assert environment["AMAP_JS_API_KEY"] == "local-retirement-validation-only"
    assert environment["YCX_DB_USER"] == "local-retirement-validation-only"


def test_strict_audit_combines_historical_clean_rebuild_with_current_runtime():
    rebuild = {
        "schema_version": "uav.gcj02-local-rebuild/v1",
        "passed": True,
        "database": {
            "alembic_revision": "20260721_0017",
            "hypertables": 5,
            "business_tables_empty": True,
        },
        "raw_materials": {"missing_files": []},
        "kafka": {
            "nonzero_end_offsets": {},
            "managed_consumer_groups_remaining": [],
        },
    }
    runtime = {
        "schema_version": "uav.adr019-local-retirement/v2",
        "runtime_topology": "native_macos_platform_with_docker_infra",
        "passed": True,
        "database": {
            "alembic_revision": "20260723_0019",
            "hypertables": 5,
        },
    }

    assert runtime_evidence_passed(
        rebuild,
        runtime,
        current_schema_head="20260723_0019",
        known_revisions={"20260721_0017", "20260723_0019"},
    ) is True
