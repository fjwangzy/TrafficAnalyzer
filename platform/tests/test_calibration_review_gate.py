from app.api.v1.calibration import (
    _calibration_review_checklist_failures,
    _intersection_project_next_action,
    _project_stage_after_source_binding,
)


def test_empty_review_checklist_cannot_approve_calibration():
    assert _calibration_review_checklist_failures({}) == [
        "imagery_map_alignment",
        "lane_directions",
        "registration_error",
        "stop_lines",
        "topology",
        "version_diff",
    ]


def test_complete_review_checklist_passes_quality_gate():
    checklist = {
        "imagery_map_alignment": True,
        "version_diff": True,
        "registration_error": True,
        "topology": True,
        "lane_directions": True,
        "stop_lines": True,
    }

    assert _calibration_review_checklist_failures(checklist) == []


def test_binding_another_video_does_not_regress_a_published_project():
    assert _project_stage_after_source_binding("road_matched") == "source_ready"
    assert _project_stage_after_source_binding("published") == "published"


def test_published_project_has_runtime_as_its_unique_next_action():
    assert _intersection_project_next_action(
        has_inter_id=True,
        has_verified_road=True,
        has_bindings=True,
        map_statuses={"retired", "lane_verified"},
    ) == "operate_runtime"
