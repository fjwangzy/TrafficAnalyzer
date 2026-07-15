import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "validate_i6_database_outage.py"
SPEC = importlib.util.spec_from_file_location("validate_i6_database_outage", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_database_outage_drill_requires_explicit_guard(monkeypatch):
    monkeypatch.delenv("ALLOW_LOCAL_DB_OUTAGE_DRILL", raising=False)
    with pytest.raises(RuntimeError, match="ALLOW_LOCAL_DB_OUTAGE_DRILL=1"):
        module.run_drill()


def test_database_outage_drill_uses_fixed_isolated_names():
    assert module.PROJECT == "traffic_analyzer_i6_fault"
    assert module.DB_PORT == "6545"
    assert module.PLATFORM_PORT == 18006
