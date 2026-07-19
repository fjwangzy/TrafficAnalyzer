import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "validate_i6_target_stack.py"
SPEC = importlib.util.spec_from_file_location("validate_i6_target_stack", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_target_stack_check_requires_explicit_guard(monkeypatch):
    monkeypatch.delenv("ALLOW_LOCAL_TARGET_STACK_CHECK", raising=False)
    with pytest.raises(RuntimeError, match="ALLOW_LOCAL_TARGET_STACK_CHECK=1"):
        module.validate()


def test_target_stack_check_is_fixed_to_isolated_local_ports():
    assert module.PROJECT == "traffic_analyzer_i6_target_full"
    assert module.PLATFORM_URL == "http://127.0.0.1:18007"
    assert module.CONSOLE_URL == "http://127.0.0.1:4178"
