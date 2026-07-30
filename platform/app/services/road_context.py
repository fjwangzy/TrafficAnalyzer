"""RoadContext deep module backed only by the authoritative local road9 store."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.mission import (
    ChannelizedMapVersion,
    RoadContextSnapshot,
    VisualLaneBinding,
)


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
    map_version_id: str | None = None
    map_status: str = "missing"
    runtime_map_bundle: dict | None = None
    selection_strategy: str | None = None


class RoadContextAdapter(Protocol):
    async def get(
        self,
        inter_id: str,
        road_data_version: str,
        map_version_id: str | None = None,
    ) -> RoadContextResult | None: ...

    async def select_runtime(
        self,
        inter_id: str,
        source_profile_id: str,
        *,
        road_data_version: str | None = None,
        map_version_id: str | None = None,
    ) -> RoadContextResult | None: ...


class RoadContext:
    """Resolve one immutable road snapshot without leaking storage details."""

    def __init__(self, adapter: RoadContextAdapter):
        self._adapter = adapter

    async def get(
        self,
        inter_id: str,
        road_data_version: str,
        map_version_id: str | None = None,
    ) -> RoadContextResult:
        result = (
            await self._adapter.get(inter_id, road_data_version, map_version_id)
            if map_version_id
            else await self._adapter.get(inter_id, road_data_version)
        )
        if result is None:
            raise LookupError(f"road context not found: {inter_id}@{road_data_version}")
        return result

    async def select_runtime(
        self,
        inter_id: str,
        source_profile_id: str,
        *,
        road_data_version: str | None = None,
        map_version_id: str | None = None,
    ) -> RoadContextResult | None:
        return await self._adapter.select_runtime(
            inter_id,
            source_profile_id,
            road_data_version=road_data_version,
            map_version_id=map_version_id,
        )


def _select_runtime_candidate(
    rows: list[ChannelizedMapVersion],
    road_data_version: str | None = None,
) -> tuple[ChannelizedMapVersion, str] | None:
    if not rows:
        return None
    preferred = [
        item for item in rows
        if road_data_version and item.road_data_version == road_data_version
    ]
    selected_map = (preferred or rows)[0]
    strategy = "requested_road_data_version" if preferred else "latest_lane_verified"
    return selected_map, strategy


async def _resolve_source_checksum(
    session: AsyncSession,
    channelized_map: ChannelizedMapVersion | None,
) -> str | None:
    """Resolve the immutable upstream snapshot through explicit map lineage."""
    if channelized_map is None or channelized_map.source_checksum:
        return channelized_map.source_checksum if channelized_map is not None else None

    # A derived imagery-fit version may retain the exact reviewed geometry of
    # an earlier local map. Follow only that declared parent; using an arbitrary
    # latest snapshot would make a Mission bundle depend on mutable query order.
    source_map_id = (channelized_map.quality or {}).get("source_map_version_id")
    if not source_map_id or source_map_id == channelized_map.id:
        return None
    source_map = await session.get(ChannelizedMapVersion, source_map_id)
    if source_map is None or source_map.inter_id != channelized_map.inter_id:
        return None
    return source_map.source_checksum


class Road9RoadContextAdapter:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def get(
        self,
        inter_id: str,
        road_data_version: str,
        map_version_id: str | None = None,
    ) -> RoadContextResult | None:
        async with self._session_factory() as session:
            map_statement = select(ChannelizedMapVersion).where(
                ChannelizedMapVersion.inter_id == inter_id,
                ChannelizedMapVersion.road_data_version == road_data_version,
                ChannelizedMapVersion.status == "lane_verified",
            )
            if map_version_id:
                map_statement = map_statement.where(ChannelizedMapVersion.id == map_version_id)
            channelized_map = (
                await session.execute(
                    map_statement.order_by(ChannelizedMapVersion.version_no.desc())
                )
            ).scalars().first()
            snapshot_statement = select(RoadContextSnapshot).where(
                RoadContextSnapshot.inter_id == inter_id
            )
            source_checksum = await _resolve_source_checksum(session, channelized_map)
            if channelized_map is not None and source_checksum:
                # A published local map has its own immutable version.  Its
                # source snapshot retains the upstream YCX version and is joined
                # through the content checksum, not by pretending the versions
                # have the same semantics.
                snapshot_statement = snapshot_statement.where(
                    RoadContextSnapshot.checksum == source_checksum
                )
            else:
                snapshot_statement = snapshot_statement.where(
                    RoadContextSnapshot.road_data_version == road_data_version
                )
            snapshot = (
                await session.execute(
                    snapshot_statement.order_by(RoadContextSnapshot.created_at.desc())
                )
            ).scalars().first()
            if snapshot is None:
                return None
            binding_statement = select(VisualLaneBinding).where(
                VisualLaneBinding.inter_id == inter_id,
                VisualLaneBinding.status != "retired",
            )
            if channelized_map is not None:
                binding_statement = binding_statement.where(
                    VisualLaneBinding.map_version_id == channelized_map.id
                )
            else:
                binding_statement = binding_statement.where(
                    VisualLaneBinding.road_data_version == road_data_version
                )
            bindings = (
                await session.execute(
                    binding_statement
                )
            ).scalars().all()
            payload = snapshot.payload
            return RoadContextResult(
                inter_id=snapshot.inter_id,
                road_data_version=(
                    channelized_map.road_data_version
                    if channelized_map else snapshot.road_data_version
                ),
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
                        "map_version_id": item.map_version_id,
                        "geometry_source": item.geometry_source,
                        "geometry_gcj02": item.geometry_gcj02,
                        "geometry_enu_m": item.geometry_enu_m,
                        "match_confidence": item.match_confidence,
                        "status": item.status,
                    }
                    for item in bindings
                ),
                quality_status=("verified" if channelized_map else snapshot.quality_status),
                map_version_id=channelized_map.id if channelized_map else None,
                map_status=channelized_map.status if channelized_map else "missing",
                runtime_map_bundle=(
                    {
                        "schema_version": "uav.runtime-road-map/v1",
                        "map_version_id": channelized_map.id,
                        "map_status": channelized_map.status,
                        "inter_id": channelized_map.inter_id,
                        "road_data_version": channelized_map.road_data_version,
                        "coordinate_system": "GCJ02",
                        "coordinate_transform_version": channelized_map.coordinate_transform_version,
                        "anchor_gcj02": channelized_map.anchor_gcj02,
                        "geometry_gcj02": channelized_map.geometry_gcj02,
                        "geometry_enu_m": channelized_map.geometry_enu_m,
                        "topology": channelized_map.topology,
                        "quality": channelized_map.quality,
                        "lanes": [
                            {
                                "local_lane_id": item.local_lane_id,
                                "source_lane_id": item.canonical_lane_id,
                                "link_id": item.canonical_link_id,
                                "geometry_enu_m": item.geometry_enu_m,
                                "geometry_gcj02": item.geometry_gcj02,
                                "geometry_source": item.geometry_source,
                                "match_confidence": item.match_confidence,
                            }
                            for item in bindings
                            if item.map_version_id == channelized_map.id and item.status != "retired"
                        ],
                    }
                    if channelized_map
                    else None
                ),
            )

    async def select_runtime(
        self,
        inter_id: str,
        source_profile_id: str,
        *,
        road_data_version: str | None = None,
        map_version_id: str | None = None,
    ) -> RoadContextResult | None:
        """Select a deterministic lane map without coupling it to world projection."""
        async with self._session_factory() as session:
            statement = (
                select(ChannelizedMapVersion)
                .where(
                    ChannelizedMapVersion.inter_id == inter_id,
                    ChannelizedMapVersion.status == "lane_verified",
                )
                .order_by(ChannelizedMapVersion.version_no.desc())
            )
            if map_version_id:
                statement = statement.where(ChannelizedMapVersion.id == map_version_id)
            rows = (await session.execute(statement)).scalars().all()

        selected = _select_runtime_candidate(rows, road_data_version)
        if map_version_id and selected is None:
            raise LookupError(
                f"runtime map is not ready for source: {map_version_id}@{source_profile_id}"
            )
        if selected is None:
            return None

        selected_map, strategy = selected
        if map_version_id:
            strategy = "explicit_map_version"
        result = await self.get(
            inter_id,
            selected_map.road_data_version,
            map_version_id=selected_map.id,
        )
        if result is None:
            if map_version_id:
                raise LookupError(
                    f"runtime map context is incomplete: {map_version_id}@{source_profile_id}"
                )
            return None

        return replace(result, selection_strategy=strategy)
