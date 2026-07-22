from datetime import UTC, datetime
from types import SimpleNamespace

from app.services.dashboard_read_model import DashboardReadModel


def test_local_acceptance_coordinate_is_map_eligible_without_becoming_authoritative():
    snapshot = SimpleNamespace(
        inter_id="INT-TEST",
        road_data_version="ROAD-TEST",
        checksum="c" * 64,
        quality_status="unverified",
        coordinate_reference={
            "status": "test",
            "display": "GCJ02",
            "usage": "local_acceptance_only",
            "source": "SRC-TEST telemetry_median",
        },
        payload={"intersection": {"name": "验收测试路口", "center_gcj02": [117.0, 36.7]}},
    )
    facts = {
        "as_of": datetime.now(UTC),
        "snapshots": {snapshot.inter_id: snapshot},
        "metrics": {},
        "conflicts": [],
        "ai_events": [],
        "missions": [],
        "pipelines": [],
    }

    row = DashboardReadModel(None)._intersection_rows(facts)[0]

    assert row["map_eligible"] is True
    assert row["map_coordinate_status"] == "test"
    assert row["road_context_quality"] == "unverified"
    assert row["coordinate_reference"]["status"] == "test"
    assert row["center_gcj02"] == {"longitude": 117.0, "latitude": 36.7}
    assert row["coordinate_system"] == "GCJ02"


def test_unscoped_unverified_coordinate_remains_isolated():
    snapshot = SimpleNamespace(
        inter_id="INT-ISOLATED",
        road_data_version="ROAD-ISOLATED",
        checksum="d" * 64,
        quality_status="unverified",
        coordinate_reference={"status": "unverified", "display": "GCJ02"},
        payload={"intersection": {"name": "未验证路口", "center_gcj02": [117.0, 36.7]}},
    )
    facts = {
        "as_of": datetime.now(UTC),
        "snapshots": {snapshot.inter_id: snapshot},
        "metrics": {},
        "conflicts": [],
        "ai_events": [],
        "missions": [],
        "pipelines": [],
    }

    row = DashboardReadModel(None)._intersection_rows(facts)[0]

    assert row["map_eligible"] is False
    assert row["map_coordinate_status"] == "unavailable"
    assert row["center_gcj02"] is None
