"""RoadContext deep module and its road9/fixture adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.mission import RoadContextSnapshot, VisualLaneBinding


@dataclass(frozen=True)
class RoadContextResult:
    inter_id: str
    road_data_version: str
    source: str
    checksum: str
    coordinate_reference: dict
    intersection: dict
    links: tuple[dict, ...]
    lanes: tuple[dict, ...]
    visual_bindings: tuple[dict, ...]
    quality_status: str


class RoadContextAdapter(Protocol):
    async def get(self, inter_id: str, road_data_version: str) -> RoadContextResult | None: ...


class RoadContext:
    """Resolve one immutable road snapshot without leaking storage details."""

    def __init__(self, adapter: RoadContextAdapter):
        self._adapter = adapter

    async def get(self, inter_id: str, road_data_version: str) -> RoadContextResult:
        result = await self._adapter.get(inter_id, road_data_version)
        if result is None:
            raise LookupError(f"road context not found: {inter_id}@{road_data_version}")
        return result


class Road9RoadContextAdapter:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def get(self, inter_id: str, road_data_version: str) -> RoadContextResult | None:
        async with self._session_factory() as session:
            snapshot = (
                await session.execute(
                    select(RoadContextSnapshot).where(
                        RoadContextSnapshot.inter_id == inter_id,
                        RoadContextSnapshot.road_data_version == road_data_version,
                    )
                )
            ).scalar_one_or_none()
            if snapshot is None:
                return None
            bindings = (
                await session.execute(
                    select(VisualLaneBinding).where(
                        VisualLaneBinding.inter_id == inter_id,
                        VisualLaneBinding.road_data_version == road_data_version,
                        VisualLaneBinding.status != "retired",
                    )
                )
            ).scalars().all()
            payload = snapshot.payload
            return RoadContextResult(
                inter_id=snapshot.inter_id,
                road_data_version=snapshot.road_data_version,
                source=snapshot.source,
                checksum=snapshot.checksum,
                coordinate_reference=dict(snapshot.coordinate_reference),
                intersection=dict(payload.get("intersection") or {}),
                links=tuple(payload.get("links") or ()),
                lanes=tuple(payload.get("lanes") or ()),
                visual_bindings=tuple(
                    {
                        "local_lane_id": item.local_lane_id,
                        "canonical_link_id": item.canonical_link_id,
                        "canonical_lane_id": item.canonical_lane_id,
                        "roads_json": item.roads_json,
                        "status": item.status,
                    }
                    for item in bindings
                ),
                quality_status=snapshot.quality_status,
            )


class FixtureRoadContextAdapter:
    """Test/local adapter; fixture values remain explicitly unverified."""

    def __init__(self, fixtures: dict[tuple[str, str], RoadContextResult]):
        self._fixtures = dict(fixtures)

    async def get(self, inter_id: str, road_data_version: str) -> RoadContextResult | None:
        return self._fixtures.get((inter_id, road_data_version))


class FallbackRoadContextAdapter:
    """Try the authoritative road9 snapshot before an explicit local fixture."""

    def __init__(self, *adapters: RoadContextAdapter):
        self._adapters = adapters

    async def get(self, inter_id: str, road_data_version: str) -> RoadContextResult | None:
        for adapter in self._adapters:
            result = await adapter.get(inter_id, road_data_version)
            if result is not None:
                return result
        return None
