from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import source_geo_registration as registration_service
from app.services.source_geo_registration import (
    backfill_verified_visual_registration,
    canonical_registration_checksum,
    runtime_geo_registration,
)


def _row(**overrides):
    values = {
        "id": "SGR-001",
        "source_profile_id": "SRC-001",
        "status": "verified",
        "coordinate_system": "GCJ02",
        "coordinate_transform_version": "gcj02-enu-equirectangular-v1",
        "anchor_gcj02": [117.0, 36.7],
        "homography_pixel_to_enu": [[1, 0, 2], [0, 1, 3], [0, 0, 1]],
        "registration_pose": {"yaw_deg": 3.0},
        "camera_calibration": {"model": "pinhole"},
        "coverage_enu_m": {"type": "Polygon", "coordinates": []},
        "residuals": {"p95_m": 0.3},
        "provenance": {"visual_registration_id": "VRG-001"},
    }
    values.update(overrides)
    values["checksum"] = canonical_registration_checksum(values)
    return SimpleNamespace(**values)


def test_runtime_geo_registration_is_independent_and_checksum_verified():
    row = _row()

    payload = runtime_geo_registration(row)

    assert payload["id"] == "SGR-001"
    assert payload["source_profile_id"] == "SRC-001"
    assert payload["status"] == "verified"
    assert payload["homography_pixel_to_enu"][0][2] == 2
    assert payload["checksum"] == row.checksum


def test_runtime_geo_registration_rejects_mutated_or_non_verified_rows():
    mutated = _row()
    mutated.anchor_gcj02 = [118.0, 36.7]

    try:
        runtime_geo_registration(mutated)
    except ValueError as exc:
        assert "checksum" in str(exc)
    else:
        raise AssertionError("mutated registration must be rejected")

    rejected = _row(status="rejected")
    try:
        runtime_geo_registration(rejected)
    except ValueError as exc:
        assert "verified" in str(exc)
    else:
        raise AssertionError("non-verified registration must be rejected")


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


def _legacy_visual():
    return SimpleNamespace(
        id="VRG-001",
        source_profile_id="SRC-001",
        status="verified",
        homography_pixel_to_enu=[[1, 0, 2], [0, 1, 3], [0, 0, 1]],
        registration_pose={"yaw_deg": 3.0},
        camera_calibration={"model": "pinhole"},
        map_coverage_enu_m={"type": "Polygon", "coordinates": []},
        residuals={"p95_m": 0.3},
        created_by=7,
        source_geo_registration_id=None,
    )


def _legacy_map():
    return SimpleNamespace(
        id="CMV-001",
        coordinate_system="GCJ02",
        coordinate_transform_version="gcj02-enu-equirectangular-v1",
        anchor_gcj02=[117.0, 36.7],
    )


@pytest.mark.asyncio
async def test_verified_visual_registration_backfill_is_idempotent():
    existing = SimpleNamespace(id="SGR-existing")
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(existing))
    )
    visual = _legacy_visual()

    result = await backfill_verified_visual_registration(
        session, visual, _legacy_map()
    )

    assert result is existing
    assert visual.source_geo_registration_id == "SGR-existing"


@pytest.mark.asyncio
async def test_verified_visual_registration_backfill_creates_verified_registration(
    monkeypatch,
):
    created = SimpleNamespace(id="SGR-new")
    create = AsyncMock(return_value=created)
    monkeypatch.setattr(registration_service, "create_registration", create)
    session = SimpleNamespace(execute=AsyncMock(return_value=_ScalarResult(None)))
    visual = _legacy_visual()

    result = await backfill_verified_visual_registration(
        session, visual, _legacy_map()
    )

    assert result is created
    assert visual.source_geo_registration_id == "SGR-new"
    create.assert_awaited_once()
    args, kwargs = create.await_args
    assert args[1] == "SRC-001"
    assert args[2]["homography_pixel_to_enu"] == visual.homography_pixel_to_enu
    assert kwargs == {"actor_id": 7, "status": "verified"}
