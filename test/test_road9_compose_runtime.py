from pathlib import Path
import os

import yaml
import pytest
import run_platform


def test_platform_uses_init_to_reap_detector_processes():
    compose = yaml.safe_load(Path("docker-compose.yaml").read_text(encoding="utf-8"))

    assert compose["services"]["platform"]["init"] is True


def test_local_replay_defaults_to_stride_ten():
    compose = yaml.safe_load(Path("docker-compose.yaml").read_text(encoding="utf-8"))

    assert compose["services"]["platform"]["environment"]["PIPELINE_FRAME_STRIDE"] == "${PIPELINE_FRAME_STRIDE:-3}"


def test_native_local_platform_defaults_to_the_complete_replay_runtime():
    source = Path("scripts/mac_local_platform.sh").read_text(encoding="utf-8")
    assert 'APP_RUNTIME_PROFILE="${APP_RUNTIME_PROFILE:-replay_v2}"' in source
    assert 'data.get(\'runtime_profile\') != sys.argv[2]' in source


@pytest.mark.parametrize("mode, explicit_profile, expected", [
    ("local", None, "replay_v2"),
    ("local", "live", "live"),
    ("production", None, None),
])
def test_root_startup_uses_local_replay_default_and_preserves_explicit_deployment(monkeypatch, mode, explicit_profile, expected):
    environment = dict(os.environ)
    environment["DEPLOYMENT_MODE"] = mode
    environment.pop("APP_RUNTIME_PROFILE", None)
    if explicit_profile:
        environment["APP_RUNTIME_PROFILE"] = explicit_profile
    monkeypatch.setattr(run_platform.os, "environ", environment)
    run_platform.configure_environment()
    assert environment.get("APP_RUNTIME_PROFILE") == expected
