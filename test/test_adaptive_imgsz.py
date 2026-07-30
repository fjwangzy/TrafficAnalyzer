from utils_local.adaptive_imgsz import AdaptiveImageSizePolicy
import pytest


def _config() -> dict:
    return {
        "enabled": True,
        "low_imgsz": 640,
        "medium_imgsz": 960,
        "high_imgsz": 1280,
        "low_to_medium_agl_m": 112.0,
        "medium_to_high_agl_m": 157.0,
        "hysteresis_m": 5.0,
        "stable_frames": 5,
        "telemetry_hold_sec": 2.0,
    }


def test_first_valid_130m_sample_selects_960_immediately():
    policy = AdaptiveImageSizePolicy(_config(), fallback_imgsz=960)

    decision = policy.select({"altitude_agl": 130.0}, source_timestamp_sec=0.0)

    assert decision.imgsz == 960
    assert decision.diagnostics == {
        "enabled": True,
        "raw_agl_m": 130.0,
        "filtered_agl_m": 130.0,
        "agl_source": "altitude_agl",
        "effective_imgsz": 960,
        "tier": "medium",
        "status": "adaptive",
        "switch_reason": "initial_altitude",
        "switch_count": 0,
    }


@pytest.mark.parametrize(
    ("agl_m", "expected_imgsz", "expected_tier"),
    [
        (90.0, 640, "low"),
        (111.999, 640, "low"),
        (112.0, 960, "medium"),
        (130.0, 960, "medium"),
        (156.999, 960, "medium"),
        (157.0, 1280, "high"),
        (180.0, 1280, "high"),
    ],
)
def test_initial_altitude_uses_exact_three_tier_boundaries(
    agl_m, expected_imgsz, expected_tier
):
    policy = AdaptiveImageSizePolicy(_config(), fallback_imgsz=960)

    decision = policy.select({"altitude_agl": agl_m}, source_timestamp_sec=0.0)

    assert decision.imgsz == expected_imgsz
    assert decision.diagnostics["tier"] == expected_tier


def test_invalid_absolute_altitude_is_not_used_and_height_is_accepted_as_agl():
    policy = AdaptiveImageSizePolicy(_config(), fallback_imgsz=960)

    decision = policy.select(
        {"altitude_agl": -12.0, "height": 90.0, "altitude": 2250.0},
        source_timestamp_sec=0.0,
    )

    assert decision.imgsz == 640
    assert decision.diagnostics["agl_source"] == "height"


@pytest.mark.parametrize("invalid", [None, True, -1.0, 0.0, float("nan"), float("inf"), "130"])
def test_invalid_or_missing_agl_falls_back_to_configured_imgsz(invalid):
    policy = AdaptiveImageSizePolicy(_config(), fallback_imgsz=960)

    decision = policy.select({"altitude_agl": invalid}, source_timestamp_sec=0.0)

    assert decision.imgsz == 960
    assert decision.diagnostics["status"] == "telemetry_missing"


def test_disabled_policy_preserves_fixed_imgsz_even_with_valid_height():
    policy = AdaptiveImageSizePolicy({**_config(), "enabled": False}, fallback_imgsz=1280)

    decision = policy.select({"altitude_agl": 90.0}, source_timestamp_sec=0.0)

    assert decision.imgsz == 1280
    assert decision.diagnostics["status"] == "disabled"


def test_tier_switch_requires_five_filtered_samples_beyond_hysteresis():
    policy = AdaptiveImageSizePolicy(_config(), fallback_imgsz=960)
    assert policy.select({"altitude_agl": 130.0}, source_timestamp_sec=0.0).imgsz == 960

    # The partial median crosses the high-tier hysteresis on the second high
    # sample; five consecutive filtered decisions complete on the sixth.
    for frame_index in range(1, 6):
        decision = policy.select(
            {"altitude_agl": 180.0},
            source_timestamp_sec=frame_index * 0.2,
        )
        assert decision.imgsz == 960

    decision = policy.select({"altitude_agl": 180.0}, source_timestamp_sec=1.2)

    assert decision.imgsz == 1280
    assert decision.diagnostics["filtered_agl_m"] == 180.0
    assert decision.diagnostics["switch_reason"] == "stable_altitude"
    assert decision.diagnostics["switch_count"] == 1


def test_missing_telemetry_holds_last_tier_for_two_seconds_then_falls_back():
    policy = AdaptiveImageSizePolicy(_config(), fallback_imgsz=960)
    assert policy.select({"altitude_agl": 180.0}, source_timestamp_sec=10.0).imgsz == 1280

    held = policy.select(None, source_timestamp_sec=11.9)
    fallback = policy.select(None, source_timestamp_sec=12.1)

    assert held.imgsz == 1280
    assert held.diagnostics["status"] == "telemetry_held"
    assert fallback.imgsz == 960
    assert fallback.diagnostics["status"] == "telemetry_missing"
    assert fallback.diagnostics["switch_reason"] == "configured_fallback"
