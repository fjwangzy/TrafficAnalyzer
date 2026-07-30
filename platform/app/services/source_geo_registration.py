"""Versioned source-to-geography registration independent of road maps.

This module owns the immutable runtime payload seam.  Road maps may refer to a
registration, but neither registration selection nor pixel trajectory output
depends on a map being present.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mission import (
    ChannelizedMapVersion,
    SourceGeoRegistration,
    VisualRegistration,
)


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _checksum_payload(source: Any) -> dict:
    return {
        "schema_version": "uav.source-geo-registration/v1",
        "source_profile_id": _value(source, "source_profile_id"),
        "coordinate_system": _value(source, "coordinate_system", "GCJ02"),
        "coordinate_transform_version": _value(
            source, "coordinate_transform_version"
        ),
        "anchor_gcj02": _value(source, "anchor_gcj02"),
        "homography_pixel_to_enu": _value(source, "homography_pixel_to_enu"),
        "registration_pose": _value(source, "registration_pose", {}) or {},
        "camera_calibration": _value(source, "camera_calibration", {}) or {},
        "coverage_enu_m": _value(source, "coverage_enu_m", {}) or {},
        "residuals": _value(source, "residuals", {}) or {},
        "provenance": _value(source, "provenance", {}) or {},
    }


def canonical_registration_checksum(source: Any) -> str:
    encoded = json.dumps(
        _checksum_payload(source),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def runtime_geo_registration(row: SourceGeoRegistration | Any) -> dict:
    """Return the verified, checksum-protected detector runtime payload."""
    if _value(row, "status") != "verified":
        raise ValueError("source geo registration must be verified")
    expected = canonical_registration_checksum(row)
    if _value(row, "checksum") != expected:
        raise ValueError("source geo registration checksum mismatch")
    payload = _checksum_payload(row)
    return {
        **payload,
        "id": _value(row, "id"),
        "status": "verified",
        "checksum": expected,
    }


async def select_verified_registration(
    session: AsyncSession,
    source_profile_id: str,
    *,
    registration_id: str | None = None,
    checksum: str | None = None,
) -> SourceGeoRegistration | None:
    statement = select(SourceGeoRegistration).where(
        SourceGeoRegistration.source_profile_id == source_profile_id,
        SourceGeoRegistration.status == "verified",
    )
    if registration_id:
        statement = statement.where(SourceGeoRegistration.id == registration_id)
    if checksum:
        statement = statement.where(SourceGeoRegistration.checksum == checksum)
    statement = statement.order_by(
        SourceGeoRegistration.version_no.desc(),
        SourceGeoRegistration.created_at.desc(),
    ).limit(1)
    return (await session.execute(statement)).scalar_one_or_none()


async def create_registration(
    session: AsyncSession,
    source_profile_id: str,
    payload: dict,
    *,
    actor_id: int | None = None,
    status: str = "draft",
) -> SourceGeoRegistration:
    current = await session.scalar(
        select(func.max(SourceGeoRegistration.version_no)).where(
            SourceGeoRegistration.source_profile_id == source_profile_id
        )
    )
    values = {
        "source_profile_id": source_profile_id,
        "coordinate_system": payload.get("coordinate_system", "GCJ02"),
        "coordinate_transform_version": payload["coordinate_transform_version"],
        "anchor_gcj02": payload["anchor_gcj02"],
        "homography_pixel_to_enu": payload["homography_pixel_to_enu"],
        "registration_pose": payload.get("registration_pose") or {},
        "camera_calibration": payload.get("camera_calibration") or {},
        "coverage_enu_m": payload.get("coverage_enu_m") or {},
        "residuals": payload.get("residuals") or {},
        "provenance": payload.get("provenance") or {},
    }
    if values["coordinate_system"] != "GCJ02":
        raise ValueError("source geo registration coordinate_system must be GCJ02")
    row = SourceGeoRegistration(
        id=f"SGR-{uuid.uuid4().hex[:24]}",
        version_no=int(current or 0) + 1,
        status=status,
        checksum=canonical_registration_checksum(values),
        created_by=actor_id,
        verified_at=datetime.now(UTC) if status == "verified" else None,
        **values,
    )
    session.add(row)
    await session.flush()
    return row


async def verify_registration(
    session: AsyncSession,
    row: SourceGeoRegistration,
    *,
    verified: bool,
) -> SourceGeoRegistration:
    if canonical_registration_checksum(row) != row.checksum:
        raise ValueError("source geo registration checksum mismatch")
    if verified:
        existing = (
            await session.execute(
                select(SourceGeoRegistration).where(
                    SourceGeoRegistration.source_profile_id == row.source_profile_id,
                    SourceGeoRegistration.status == "verified",
                    SourceGeoRegistration.id != row.id,
                )
            )
        ).scalars().all()
        for item in existing:
            item.status = "retired"
        row.status = "verified"
        row.verified_at = datetime.now(UTC)
    else:
        row.status = "rejected"
        row.verified_at = None
    return row


async def backfill_verified_visual_registration(
    session: AsyncSession,
    visual: VisualRegistration,
    channelized_map: ChannelizedMapVersion,
) -> SourceGeoRegistration | None:
    """Idempotently promote an old verified map registration to the new seam."""
    if (
        visual.status != "verified"
        or not visual.source_profile_id
        or not visual.homography_pixel_to_enu
    ):
        return None
    payload = {
        "coordinate_system": channelized_map.coordinate_system,
        "coordinate_transform_version": channelized_map.coordinate_transform_version,
        "anchor_gcj02": channelized_map.anchor_gcj02,
        "homography_pixel_to_enu": visual.homography_pixel_to_enu,
        "registration_pose": visual.registration_pose,
        "camera_calibration": visual.camera_calibration,
        "coverage_enu_m": visual.map_coverage_enu_m,
        "residuals": visual.residuals,
        "provenance": {
            "visual_registration_id": visual.id,
            "map_version_id": channelized_map.id,
            "backfill": True,
        },
    }
    checksum = canonical_registration_checksum(
        {"source_profile_id": visual.source_profile_id, **payload}
    )
    row = (
        await session.execute(
            select(SourceGeoRegistration).where(
                SourceGeoRegistration.source_profile_id == visual.source_profile_id,
                SourceGeoRegistration.checksum == checksum,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = await create_registration(
            session,
            visual.source_profile_id,
            payload,
            actor_id=visual.created_by,
            status="verified",
        )
    visual.source_geo_registration_id = row.id
    return row
