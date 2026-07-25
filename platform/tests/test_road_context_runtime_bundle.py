from types import SimpleNamespace

import pytest

from app.services.road_context import (
    _resolve_source_checksum,
    _runtime_registration_payload,
    _runtime_registration_ready,
    _select_runtime_candidate,
)


class _FakeSession:
    def __init__(self, maps):
        self.maps = maps
        self.requested_ids = []

    async def get(self, _model, item_id):
        self.requested_ids.append(item_id)
        return self.maps.get(item_id)


def test_runtime_registration_payload_preserves_cruise_coordinate_lineage():
    registration = SimpleNamespace(
        id="VRG-1",
        source_profile_id="SRC-1",
        status="verified",
        homography_pixel_to_enu=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        residuals={"rmse_m": 0.2},
        registration_pose={
            "altitude_agl": 130.0,
            "telemetry_homography_pixel_to_local_enu": [
                [1, 0, 0],
                [0, 1, 0],
                [0, 0, 1],
            ],
        },
        camera_calibration={"version": "camera/v1"},
        map_coverage_enu_m={
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
        },
    )

    payload = _runtime_registration_payload(registration)

    assert payload["status"] == "verified"
    assert payload["registration_pose"]["altitude_agl"] == 130.0
    assert payload["camera_calibration"] == {"version": "camera/v1"}
    assert payload["map_coverage_enu_m"]["type"] == "Polygon"


def _registration(**overrides):
    values = {
        "id": "VRG-READY",
        "source_profile_id": "SRC-1",
        "status": "verified",
        "homography_pixel_to_enu": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "registration_pose": {"altitude_agl": 130.0},
        "camera_calibration": {"version": "camera/v1"},
        "map_coverage_enu_m": {"type": "Polygon", "coordinates": []},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_runtime_registration_requires_complete_source_coordinate_lineage():
    assert _runtime_registration_ready(_registration())
    assert not _runtime_registration_ready(_registration(registration_pose={}))
    assert not _runtime_registration_ready(_registration(source_profile_id=None))


def test_runtime_map_selection_prefers_requested_ready_version_then_latest_ready():
    latest_map = SimpleNamespace(id="CMV-2", road_data_version="ROAD-2")
    requested_map = SimpleNamespace(id="CMV-1", road_data_version="ROAD-1")
    incomplete_map = SimpleNamespace(id="CMV-0", road_data_version="ROAD-0")
    rows = [
        (latest_map, _registration(id="VRG-2")),
        (requested_map, _registration(id="VRG-1")),
        (incomplete_map, _registration(id="VRG-0", map_coverage_enu_m={})),
    ]

    selected = _select_runtime_candidate(rows, "ROAD-1")
    assert selected == (requested_map, rows[1][1], "requested_road_data_version")
    selected = _select_runtime_candidate(rows, "RAW-ROAD-VERSION")
    assert selected == (latest_map, rows[0][1], "latest_source_verified")


@pytest.mark.asyncio
async def test_source_checksum_follows_only_explicit_same_intersection_parent():
    parent = SimpleNamespace(
        id="CMV-PARENT",
        inter_id="INTER-1",
        source_checksum="sha256:reviewed-snapshot",
    )
    session = _FakeSession({parent.id: parent})
    derived = SimpleNamespace(
        id="CMV-DERIVED",
        inter_id="INTER-1",
        source_checksum=None,
        quality={"source_map_version_id": parent.id},
    )

    assert await _resolve_source_checksum(session, derived) == parent.source_checksum
    assert session.requested_ids == [parent.id]

    wrong_intersection = SimpleNamespace(
        id="CMV-WRONG",
        inter_id="INTER-2",
        source_checksum="sha256:wrong",
    )
    session = _FakeSession({wrong_intersection.id: wrong_intersection})
    derived.quality = {"source_map_version_id": wrong_intersection.id}
    assert await _resolve_source_checksum(session, derived) is None


@pytest.mark.asyncio
async def test_source_checksum_does_not_query_parent_when_direct_checksum_exists():
    session = _FakeSession({})
    published = SimpleNamespace(
        id="CMV-DIRECT",
        inter_id="INTER-1",
        source_checksum="sha256:direct",
        quality={"source_map_version_id": "CMV-PARENT"},
    )

    assert await _resolve_source_checksum(session, published) == "sha256:direct"
    assert session.requested_ids == []
