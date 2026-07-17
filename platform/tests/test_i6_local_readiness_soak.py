import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "validate_i6_local_readiness_soak.py"
SPEC = importlib.util.spec_from_file_location("validate_i6_local_readiness_soak", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_readiness_soak_requires_explicit_guard(monkeypatch):
    monkeypatch.delenv("ALLOW_LOCAL_READINESS_SOAK", raising=False)
    with pytest.raises(RuntimeError, match="ALLOW_LOCAL_READINESS_SOAK=1"):
        module.validate(duration_sec=10, interval_sec=1)


def test_readiness_soak_rejects_duration_longer_than_local_cutover_probe(monkeypatch):
    monkeypatch.setenv("ALLOW_LOCAL_READINESS_SOAK", "1")
    with pytest.raises(ValueError, match="between 10 and 1800"):
        module.validate(duration_sec=1801, interval_sec=1)


def test_summarize_requires_every_probe_to_remain_healthy():
    healthy = {
        "checks": {"platform_ready": True, "console_login": True, "dashboard": True, "system_health": True},
        "latency_ms": 12.0,
    }
    degraded = {
        "checks": {"platform_ready": False, "console_login": True, "dashboard": True, "system_health": True},
        "latency_ms": 25.0,
    }
    summary = module._summarize([healthy, healthy, degraded])

    assert summary["sample_count"] == 3
    assert summary["all_samples_healthy"] is False
    assert summary["ready_ratio"] == pytest.approx(2 / 3)
    assert summary["max_latency_ms"] == 25.0


def test_readiness_soak_stops_on_first_failed_sample(monkeypatch):
    monkeypatch.setenv("ALLOW_LOCAL_READINESS_SOAK", "1")
    healthy = {
        "checks": {"platform_ready": True, "console_login": True, "dashboard": True, "system_health": True},
        "latency_ms": 12.0,
    }
    degraded = {
        "checks": {"platform_ready": False, "console_login": True, "dashboard": True, "system_health": True},
        "latency_ms": 25.0,
    }
    probes = iter([healthy, degraded])
    ticks = iter([0.0, 1.0, 2.0])

    result = module.validate(
        duration_sec=10,
        interval_sec=1,
        probe=lambda: next(probes),
        clock=lambda: next(ticks),
        sleeper=lambda _seconds: None,
    )

    assert result["passed"] is False
    assert result["execution_complete"] is False
    assert result["stopped_early"] is True
    assert result["summary"]["sample_count"] == 2
