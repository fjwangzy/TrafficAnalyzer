from pathlib import Path

import yaml


def test_platform_uses_init_to_reap_detector_processes():
    compose = yaml.safe_load(Path("docker-compose.yaml").read_text(encoding="utf-8"))

    assert compose["services"]["platform"]["init"] is True


def test_local_replay_defaults_to_stride_ten():
    compose = yaml.safe_load(Path("docker-compose.yaml").read_text(encoding="utf-8"))

    assert compose["services"]["platform"]["environment"]["PIPELINE_FRAME_STRIDE"] == "${PIPELINE_FRAME_STRIDE:-10}"
