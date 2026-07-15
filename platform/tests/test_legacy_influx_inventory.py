import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "inventory_legacy_influx.py"
SPEC = importlib.util.spec_from_file_location("inventory_legacy_influx", SCRIPT)
assert SPEC and SPEC.loader
inventory_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory_module)


def test_inventory_parsers_keep_counts_and_boundaries_without_payloads():
    count_payload = {
        "results": [{"series": [{"columns": ["time", "count_a", "count_b"], "values": [[0, 2, 5]]}]}]
    }
    boundary_payload = {
        "results": [{"series": [{"columns": ["time", "payload"], "values": [[2_002_000_000, "ignored"]]}]}]
    }

    assert inventory_module._point_count_estimate(count_payload) == 5
    assert inventory_module._boundary_time(boundary_payload) == "1970-01-01T00:00:02.002000Z"
    assert inventory_module._time_semantics("1970-01-01T00:00:02Z", "1970-01-01T00:10:00Z") == {
        "status": "blocked_external",
        "classification": "relative_or_invalid_epoch",
        "detail": "Source time is relative or invalid as UTC; an approved reconstruction rule is required before backfill.",
    }


def test_inventory_refuses_unapproved_container_or_database_names():
    with pytest.raises(ValueError, match="restricted to the approved local"):
        inventory_module.inventory(influx_container="production-influx")
