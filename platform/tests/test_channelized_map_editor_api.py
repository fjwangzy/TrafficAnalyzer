from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1.calibration import (
    ImageFitPayload,
    derive_channelized_map_draft,
    fit_channelized_map_from_image,
)
from app.models.mission import ChannelizedMapVersion, VisualLaneBinding, VisualRegistration


class _Result:
    def __init__(self, value=None):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return list(self.value or [])


class _Session:
    def __init__(self, row, execute_values=(), max_version=1):
        self.rows = {row.id: row}
        self.execute_values = list(execute_values)
        self.max_version = max_version
        self.added = []
        self.commits = 0

    def get_bind(self):
        return None

    async def get(self, model, identifier):
        value = self.rows.get(identifier)
        return value if isinstance(value, model) else None

    async def scalar(self, _statement):
        return self.max_version

    async def execute(self, _statement, *_args, **_kwargs):
        value = self.execute_values.pop(0) if self.execute_values else None
        if callable(value):
            value = value(self)
        return _Result(value)

    def add(self, value):
        self.added.append(value)
        if isinstance(value, ChannelizedMapVersion):
            self.rows[value.id] = value

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1


class _LaneStore:
    def __init__(self, task):
        self.task = task

    def get_task(self, _task_id):
        return self.task

    def get_task_image_path(self, _task_id):
        return "/tmp/retained-keyframe.jpg"


def _request(task=None):
    return SimpleNamespace(
        state=SimpleNamespace(user={"role": "admin", "sub": "7"}),
        app=SimpleNamespace(state=SimpleNamespace(lane_annotation_store=_LaneStore(task or _task()))),
    )


def _task():
    return {
        "task_id": "TASK-1",
        "intersection_id": "INT-1",
        "homography_coordinate_frame": "map_enu",
        "map_anchor_gcj02": [117.0, 36.7],
        "homography_pixel_to_enu": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
    }


def _map(status="candidate"):
    return ChannelizedMapVersion(
        id="CMV-1",
        inter_id="INT-1",
        road_data_version="ROAD-1",
        version_no=1,
        status=status,
        coordinate_system="GCJ02",
        coordinate_transform_version="wgs84-enu-gcj02-v1",
        anchor_gcj02=[117.0, 36.7],
        geometry_gcj02={},
        geometry_enu_m={},
        topology={"links": []},
        quality={"reviewed": status == "lane_verified"},
        source_checksum="abc123",
        created_by=7,
    )


def _payload(*, lanes=None, client_h=None):
    return ImageFitPayload(
        task_id="TASK-1",
        source_profile_id="SRC-1",
        homography_pixel_to_enu=client_h or [[1, 0, -10], [0, 1, -20], [0, 0, 1]],
        registration_pose={
            "schema_version": "uav.channelized-editor/registration-pose/v1",
            "fixed_surface": "source_image",
            "center_px": [0, 0],
            "translation_px": [10, 20],
            "rotation_deg": 0,
            "uniform_scale": 1,
        },
        lanes=lanes or [{
            "local_lane_id": "lane:1", "link_id": "link:east", "direction": "straight",
            "polygon_px": [[20, 30], [40, 30], [40, 50], [20, 50]],
        }],
        features=[{
            "feature_id": "crosswalk:east", "feature_type": "crosswalk",
            "points_px": [[20, 60], [40, 60], [40, 65], [20, 65]],
            "properties": {"variant": "standard"},
        }],
        link_residual_p95_m=1.0,
        lane_residual_median_m=0.4,
        lane_residual_p95_m=0.8,
        topology_errors=0,
        direction_checks_passed=True,
        stop_line_checks_passed=True,
        reviewed=False,
        editor_model={
            "schema_version": "uav.channelized-editor/model/v1",
            "mode": "freeform",
            "center_px": [480, 270],
            "approaches": [],
            "pixel_geometry": {"lanes": [], "features": []},
        },
    )


@pytest.mark.asyncio
async def test_fit_endpoint_recomputes_pose_persists_features_and_allows_cross_link_overlap():
    row = _map()
    session = _Session(row, execute_values=[
        None,
        "VID-1",
        None,
        lambda db: [item for item in db.added if isinstance(item, VisualLaneBinding)],
        lambda db: [item for item in db.added if isinstance(item, VisualRegistration)],
    ])
    polygon = [[20, 30], [40, 30], [40, 50], [20, 50]]
    payload = _payload(lanes=[
        {"local_lane_id": "lane:east", "link_id": "link:east", "special_lane_attribute": "bus", "polygon_px": polygon},
        {"local_lane_id": "lane:north", "link_id": "link:north", "polygon_px": polygon},
    ])

    result = await fit_channelized_map_from_image("CMV-1", payload, _request(), session)

    assert result["status"] == "candidate"
    assert result["quality"]["lane_count"] == 2
    assert row.geometry_enu_m["features"]["crosswalk:east"]["feature_type"] == "crosswalk"
    assert row.topology["editor_model"]["mode"] == "freeform"
    assert row.topology["lane_properties"]["lane:east"]["special_lane_attribute"] == "bus"
    registration = next(item for item in session.added if isinstance(item, VisualRegistration))
    assert registration.homography_pixel_to_enu == [[1.0, 0.0, -10.0], [0.0, 1.0, -20.0], [0.0, 0.0, 1.0]]


@pytest.mark.asyncio
async def test_fit_endpoint_rejects_client_pose_matrix_drift():
    with pytest.raises(HTTPException, match="does not match registration_pose") as raised:
        await fit_channelized_map_from_image(
            "CMV-1", _payload(client_h=[[1, 0, 0], [0, 1, 0], [0, 0, 1]]),
            _request(), _Session(_map()),
        )
    assert raised.value.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("lanes, message", [
    ([{"local_lane_id": "bow", "link_id": "link:east", "polygon_px": [[20, 30], [40, 50], [20, 50], [40, 30]]}], "self-intersecting"),
    ([
        {"local_lane_id": "one", "link_id": "link:east", "polygon_px": [[20, 30], [40, 30], [40, 50], [20, 50]]},
        {"local_lane_id": "two", "link_id": "link:east", "polygon_px": [[20, 30], [40, 30], [40, 50], [20, 50]]},
    ], "overlap by more than 5%"),
])
async def test_fit_endpoint_rejects_invalid_lane_geometry(lanes, message):
    with pytest.raises(HTTPException, match=message) as raised:
        await fit_channelized_map_from_image("CMV-1", _payload(lanes=lanes), _request(), _Session(_map()))
    assert raised.value.status_code == 422


@pytest.mark.asyncio
async def test_fit_endpoint_keeps_published_versions_immutable():
    with pytest.raises(HTTPException, match="immutable") as raised:
        await fit_channelized_map_from_image("CMV-1", _payload(), _request(), _Session(_map("lane_verified")))
    assert raised.value.status_code == 409


@pytest.mark.asyncio
async def test_derive_draft_endpoint_copies_bindings_and_preserves_verified_source():
    source = _map("lane_verified")
    source_lane = VisualLaneBinding(
        id="VLB-SOURCE", inter_id="INT-1", road_data_version="ROAD-1", map_version_id=source.id,
        local_lane_id="lane:1", canonical_link_id="link:east", canonical_lane_id="LANE-1",
        geometry_source="imagery_fitted", geometry_gcj02={"type": "Polygon", "coordinates": []},
        geometry_enu_m={"type": "Polygon", "coordinates": []}, match_confidence=0.98,
        status="lane_verified", confirmed_by=7,
    )
    session = _Session(source, execute_values=[
        [source_lane],
        lambda db: [item for item in db.added if isinstance(item, VisualLaneBinding)],
        [],
    ], max_version=7)

    result = await derive_channelized_map_draft(source.id, _request(), session)

    assert result["status"] == "draft"
    assert result["version_no"] == 8
    assert result["topology"]["derived_from_map_version_id"] == source.id
    assert result["quality"]["reviewed"] is False
    assert result["lanes"][0]["status"] == "candidate"
    assert source.status == "lane_verified"
    assert source.quality == {"reviewed": True}
