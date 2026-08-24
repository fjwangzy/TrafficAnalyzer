import pytest

from utils_local.coordinates import enu_to_gcj02
from utils_local.flight_motion import FlightMotionClassifier


ANCHOR = (117.0, 36.0)


def _sample(
    timestamp: float, east_m: float, *, pitch: float = -90.0, roll: float = 0.0
) -> dict:
    lon, lat = enu_to_gcj02(east_m, 0.0, ANCHOR)
    return {
        "timestamp": timestamp,
        "position_gcj02": {"longitude": lon, "latitude": lat},
        "coordinate_system": "GCJ02",
        "altitude_agl": 100.0,
        "gimbal_pitch": pitch,
        "gimbal_roll": roll,
        "gimbal_yaw": 0.0,
        "zoom_factor": 1.0,
    }


def test_derives_cruise_speed_when_source_does_not_report_it():
    classifier = FlightMotionClassifier()

    classifier.observe(_sample(0.0, 0.0))
    snapshot = classifier.observe(_sample(1.0, 5.0))

    assert snapshot.phase == "cruise_nadir"
    assert snapshot.speed_source == "derived"
    assert snapshot.horizontal_speed_mps == pytest.approx(5.0, abs=0.05)
    assert snapshot.formal_pose_eligible is True


def test_enters_verified_hover_after_stable_nadir_window():
    classifier = FlightMotionClassifier()

    snapshots = [classifier.observe(_sample(float(second), 0.0)) for second in range(17)]

    assert snapshots[1].phase == "hover_candidate"
    assert snapshots[-1].phase == "hover_verified"
    assert snapshots[-1].formal_pose_eligible is True


def test_rejects_non_nadir_pose_even_when_position_is_stable():
    classifier = FlightMotionClassifier()

    snapshot = classifier.observe(_sample(0.0, 0.0, pitch=-70.0))

    assert snapshot.phase == "unsupported_pose"
    assert snapshot.formal_pose_eligible is False
    assert "gimbal_pitch_out_of_range" in snapshot.reasons


def test_roll_above_default_limit_requires_explicit_visual_validation_policy():
    telemetry = _sample(0.0, 0.0, roll=10.0)

    default = FlightMotionClassifier().observe(telemetry)
    visual_checked = FlightMotionClassifier(
        allow_roll_with_visual_validation=True,
        max_roll_visual_validation_deg=15.0,
    ).observe(telemetry)

    assert default.formal_pose_eligible is False
    assert "gimbal_roll_out_of_range" in default.reasons
    assert visual_checked.formal_pose_eligible is True
    assert "gimbal_roll_visual_validation_required" in visual_checked.reasons


def test_missing_telemetry_is_explicitly_unavailable():
    snapshot = FlightMotionClassifier().observe(None)

    assert snapshot.phase == "telemetry_unavailable"
    assert snapshot.formal_pose_eligible is False


def test_hover_exit_uses_transition_hysteresis_before_cruise():
    classifier = FlightMotionClassifier(hover_confirm_sec=2.0)
    for second in range(3):
        snapshot = classifier.observe(_sample(second, 0.0) | {"horizontal_speed": 0.0})
    assert snapshot.phase == "hover_verified"

    transition = classifier.observe(_sample(3.0, 2.0) | {"horizontal_speed": 2.0})
    still_transition = classifier.observe(_sample(4.0, 4.0) | {"horizontal_speed": 2.0})
    cruise = classifier.observe(_sample(5.0, 6.0) | {"horizontal_speed": 2.0})

    assert transition.phase == "transition"
    assert still_transition.phase == "transition"
    assert cruise.phase == "cruise_nadir"


def test_slow_drift_outside_hover_radius_never_verifies_hover():
    classifier = FlightMotionClassifier(hover_confirm_sec=15.0)
    for second in range(21):
        snapshot = classifier.observe(
            _sample(second, second * 0.8) | {"horizontal_speed": 0.8}
        )

    assert snapshot.phase == "hover_candidate"
    assert snapshot.position_radius_p95_m > 5.0


def test_sustained_reported_and_derived_speed_mismatch_blocks_formal_pose():
    classifier = FlightMotionClassifier(speed_inconsistency_confirm_sec=1.0)
    classifier.observe(_sample(0.0, 0.0) | {"horizontal_speed": 0.0})

    transient = classifier.observe(
        _sample(1.0, 5.0) | {"horizontal_speed": 0.0}
    )
    sustained = classifier.observe(
        _sample(2.0, 10.0) | {"horizontal_speed": 0.0}
    )

    assert "telemetry_speed_inconsistent" not in transient.reasons
    assert transient.formal_pose_eligible is True
    assert "telemetry_speed_inconsistent" in sustained.reasons
    assert sustained.phase == "unsupported_pose"
    assert sustained.formal_pose_eligible is False


def test_yaw_wrap_across_180_degrees_does_not_create_false_rate_spike():
    classifier = FlightMotionClassifier()
    classifier.observe(
        _sample(0.0, 0.0) | {"horizontal_speed": 2.0, "gimbal_yaw": 179.0}
    )

    snapshot = classifier.observe(
        _sample(1.0, 2.0) | {"horizontal_speed": 2.0, "gimbal_yaw": -179.0}
    )

    assert "gimbal_yaw_rate_out_of_range" not in snapshot.reasons
    assert snapshot.phase == "cruise_nadir"
    assert snapshot.formal_pose_eligible is True


def test_gps_jump_exceeding_cruise_envelope_is_unsupported():
    classifier = FlightMotionClassifier()
    classifier.observe(_sample(0.0, 0.0))

    snapshot = classifier.observe(_sample(1.0, 100.0))

    assert snapshot.horizontal_speed_mps > 12.0
    assert "horizontal_speed_out_of_range" in snapshot.reasons
    assert snapshot.phase == "unsupported_pose"


def test_telemetry_time_reversal_is_rejected_but_equal_timestamp_is_allowed():
    classifier = FlightMotionClassifier()
    classifier.observe(_sample(2.0, 0.0) | {"horizontal_speed": 2.0})
    repeated = classifier.observe(
        _sample(2.0, 0.0) | {"horizontal_speed": 2.0}
    )

    reversed_snapshot = classifier.observe(
        _sample(1.5, 0.0) | {"horizontal_speed": 2.0}
    )

    assert "telemetry_time_reversal" not in repeated.reasons
    assert "telemetry_time_reversal" in reversed_snapshot.reasons
    assert reversed_snapshot.phase == "unsupported_pose"
    assert reversed_snapshot.formal_pose_eligible is False
