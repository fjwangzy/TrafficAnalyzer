from types import SimpleNamespace

import pytest

from app.services.road_context import _resolve_source_checksum, _select_runtime_candidate


class _FakeSession:
    def __init__(self, maps):
        self.maps = maps
        self.requested_ids = []

    async def get(self, _model, item_id):
        self.requested_ids.append(item_id)
        return self.maps.get(item_id)


def test_runtime_map_selection_depends_only_on_lane_verified_map_version():
    latest_map = SimpleNamespace(id="CMV-2", road_data_version="ROAD-2")
    requested_map = SimpleNamespace(id="CMV-1", road_data_version="ROAD-1")
    rows = [latest_map, requested_map]

    assert _select_runtime_candidate(rows, "ROAD-1") == (
        requested_map,
        "requested_road_data_version",
    )
    assert _select_runtime_candidate(rows, "RAW-ROAD-VERSION") == (
        latest_map,
        "latest_lane_verified",
    )


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
