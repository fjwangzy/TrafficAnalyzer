import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "validate_i6_local_performance.py"
SPEC = importlib.util.spec_from_file_location("validate_i6_local_performance", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_local_performance_guard_precedes_auth(monkeypatch):
    monkeypatch.delenv("ALLOW_LOCAL_PERF_SMOKE", raising=False)
    with pytest.raises(RuntimeError, match="ALLOW_LOCAL_PERF_SMOKE=1"):
        module.run_smoke("http://127.0.0.1:18004", 4, 1)


def test_local_performance_rejects_non_local_target():
    with pytest.raises(ValueError, match="restricted to an explicit local"):
        module._validate_local_url("https://platform.example.com")


def test_percentile_uses_nearest_rank():
    assert module._percentile([1, 2, 3, 4, 100], 0.95) == 100
    assert module._percentile([], 0.95) == 0.0
