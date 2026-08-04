import numpy as np
import pytest
from pydantic import ValidationError

from app.api.v1.calibration import EditorModelV1, ImageFittedFeaturePayload, RegistrationPoseV1
from app.services.channelized_editor_geometry import (
    compose_registration_homography,
    homographies_match,
    overlap_must_be_disjoint,
    resolve_registration_homography,
    transform_pixel,
)


def test_pose_composition_keeps_aligned_overlay_on_original_world_geometry():
    base_pixel_to_enu = [
        [0.2, 0.0, -100.0],
        [0.0, -0.2, 60.0],
        [0.0, 0.0, 1.0],
    ]
    pose = {
        "schema_version": "uav.channelized-editor/registration-pose/v1",
        "fixed_surface": "source_image",
        "center_px": [960.0, 540.0],
        "translation_px": [34.0, -21.0],
        "rotation_deg": 7.5,
        "uniform_scale": 1.08,
    }

    aligned_pixel = transform_pixel([1120.0, 610.0], pose)
    final_pixel_to_enu = compose_registration_homography(base_pixel_to_enu, pose)

    expected = np.asarray(base_pixel_to_enu) @ np.asarray([1120.0, 610.0, 1.0])
    actual = np.asarray(final_pixel_to_enu) @ np.asarray([*aligned_pixel, 1.0])
    assert np.allclose(actual[:2] / actual[2], expected[:2] / expected[2])
    assert homographies_match(final_pixel_to_enu, final_pixel_to_enu)


def test_homography_comparison_is_scale_invariant_but_rejects_pose_drift():
    expected = [[2.0, 0.0, 4.0], [0.0, 2.0, 6.0], [0.0, 0.0, 2.0]]
    assert homographies_match(expected, [[1.0, 0.0, 2.0], [0.0, 1.0, 3.0], [0.0, 0.0, 1.0]])
    assert not homographies_match(expected, [[1.0, 0.0, 2.1], [0.0, 1.0, 3.0], [0.0, 0.0, 1.0]])


def test_resolver_recomputes_pose_and_rejects_a_client_matrix_that_does_not_match():
    base = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    pose = {
        "schema_version": "uav.channelized-editor/registration-pose/v1",
        "fixed_surface": "source_image",
        "center_px": [0.0, 0.0],
        "translation_px": [10.0, 20.0],
        "rotation_deg": 0.0,
        "uniform_scale": 2.0,
    }
    expected = [[0.5, 0.0, -5.0], [0.0, 0.5, -10.0], [0.0, 0.0, 1.0]]
    assert homographies_match(resolve_registration_homography(base, expected, pose), expected)

    try:
        resolve_registration_homography(base, base, pose)
    except ValueError as exc:
        assert "does not match registration_pose" in str(exc)
    else:
        raise AssertionError("pose drift must be rejected")


def test_registration_pose_and_editor_model_are_versioned_and_typed():
    pose = RegistrationPoseV1(
        schema_version="uav.channelized-editor/registration-pose/v1",
        fixed_surface="source_image",
        center_px=[960, 540],
        translation_px=[0, 0],
        rotation_deg=0,
        uniform_scale=1,
    )
    model = EditorModelV1(
        schema_version="uav.channelized-editor/model/v1",
        center_px=[960, 540],
        approaches=[{
            "approach_id": "north",
            "angle_deg": 90,
            "inbound_lane_count": 3,
            "outbound_lane_count": 2,
            "lane_width_px": 18,
            "approach_length_px": 260,
            "flare_length_px": 80,
            "right_turn_lane": True,
            "turn_directions": ["left_turn", "straight", "right_turn"],
        }],
    )
    assert pose.fixed_surface == "source_image"
    assert model.approaches[0].inbound_lane_count == 3

    freeform = EditorModelV1(
        schema_version="uav.channelized-editor/model/v1",
        mode="freeform",
        center_px=[960, 540],
        approaches=[],
        pixel_geometry={"lanes": [], "features": []},
    )
    assert freeform.mode == "freeform"

    with pytest.raises(ValidationError):
        EditorModelV1(
            schema_version="uav.channelized-editor/model/v1",
            mode="parameterized",
            center_px=[960, 540],
            approaches=[],
        )

    with pytest.raises(ValidationError):
        RegistrationPoseV1(
            schema_version="unversioned",
            fixed_surface="road_overlay",
            center_px=[0, 0],
            translation_px=[0, 0],
            rotation_deg=0,
            uniform_scale=0,
        )


@pytest.mark.parametrize(
    "feature_type",
    ["crosswalk", "channelizing_island", "waiting_zone", "stop_line", "lane_boundary", "lane_marking"],
)
def test_formal_channelization_feature_types_are_accepted(feature_type):
    payload = ImageFittedFeaturePayload(
        feature_id=f"feature:{feature_type}",
        feature_type=feature_type,
        points_px=[[0, 0], [1, 1], [2, 0]],
    )
    assert payload.feature_type == feature_type


def test_overlap_gate_applies_within_one_link_but_allows_conflicting_movements_to_cross():
    assert overlap_must_be_disjoint("link:east", "link:east")
    assert not overlap_must_be_disjoint("link:east", "link:north")
    assert overlap_must_be_disjoint(None, "link:north")
