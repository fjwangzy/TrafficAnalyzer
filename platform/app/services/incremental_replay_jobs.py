"""Durable per-window read model jobs, independent of Kafka consumption latency."""

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import Integer, cast, delete, func, select, update
from sqlalchemy.orm import aliased

from app.models.replay_v2 import (
    ReplayV2DirtyWindow as Dirty,
)
from app.models.replay_v2 import (
    ReplayV2Episode as Episode,
)
from app.models.replay_v2 import (
    ReplayV2InterEvaluation5MinMM,
    ReplayV2IntersectionMetric5Min,
    ReplayV2LaneMetric5Min,
    ReplayV2LinkMetric5Min,
    ReplayV2TurnMetric5Min,
)
from app.models.replay_v2 import (
    ReplayV2Maneuver as Maneuver,
)
from app.models.replay_v2 import (
    ReplayV2Mission as Mission,
)
from app.models.replay_v2 import (
    ReplayV2TrackEvent as Track,
)
from app.models.replay_v2 import (
    ReplayV2TrackGroup as Group,
)
from app.models.replay_v2 import (
    ReplayV2TrackRelation as Relation,
)
from app.models.replay_v2 import (
    ReplayV2TrackWindow as Membership,
)
from app.models.replay_v2 import (
    ReplayV2TrafficMetricSample as Sample,
)
from app.services.incremental_window_aggregates import WindowAccumulator
from app.services.replay_v2_aggregates import _at_offset, _window_start

LOG = logging.getLogger(__name__)
MODELS = {
    "intersection": ReplayV2IntersectionMetric5Min,
    "link": ReplayV2LinkMetric5Min,
    "lane": ReplayV2LaneMetric5Min,
    "turn": ReplayV2TurnMetric5Min,
}


def aware(value):
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def dirty_window(session, mission_id, window):
    window = aware(window)
    job = await session.get(Dirty, (mission_id, window))
    if job is None:
        session.add(
            Dirty(
                mission_id=mission_id,
                window_start=window,
                generation=1,
                processed_generation=0,
                dirty=1,
            )
        )
    else:
        job.generation += 1
        job.dirty = 1


async def register_track(session, mission, data):
    track = str(data["track_id"])
    sampling = data.get("sampling") or {}
    summary = sampling.get("full_sequence_summary") or {}
    if summary.get("time_basis"):
        basis = datetime.fromisoformat(summary["time_basis"])
        if (mission.algorithm_versions or {}).get("archive") != "incremental/v1":
            mission.started_at = basis
        elif aware(mission.started_at) != basis:
            raise ValueError("incremental trajectory time basis conflict")
    mission.algorithm_versions = {
        **(mission.algorithm_versions or {}),
        "archive": "incremental/v1",
        "aggregate": "replay-v2-aggregate/v2",
    }
    if mission.status not in {"sealed", "finalizing"}:
        old_count = mission.source_point_count or 0
        world = round(mission.coordinate_coverage_ratio * old_count) + int(
            summary.get("world_point_count", 0)
        )
        mission.source_point_count = old_count + int(data["source_point_count"])
        mission.retained_point_count = (mission.retained_point_count or 0) + int(
            data["retained_point_count"]
        )
        mission.behavior_count = (
            (mission.behavior_count or 0)
            + len(data.get("episodes") or [])
            + len(data.get("maneuvers") or [])
        )
        mission.coordinate_coverage_ratio = (
            world / mission.source_point_count if mission.source_point_count else 0
        )
    basis = aware(mission.started_at)
    if await session.get(Group, (mission.id, track)) is None:
        session.add(Group(mission_id=mission.id, track_id=track, root_track_id=track))
    windows = {_window_start(_at_offset(basis, data["points"][0]["offset_ms"]))}
    for row in summary.get("windows", []):
        windows.add(datetime.fromisoformat(row["window_start"]))
    if sampling.get("algorithm_version") != "event-faithful/v2":
        for point in data["points"]:
            windows.add(_window_start(_at_offset(basis, point["offset_ms"])))
    for kind in ("episodes", "maneuvers"):
        for row in data.get(kind) or []:
            windows.add(_window_start(_at_offset(basis, row["start_offset_ms"])))
    for window in sorted(windows):
        session.add(Membership(mission_id=mission.id, track_id=track, window_start=window))
        await dirty_window(session, mission.id, window)


class IncrementalReplayJobs:
    def __init__(self, sessions, *, page_size=256, batch_size=16):
        self.sessions, self.page_size, self.batch_size = sessions, page_size, batch_size
        self.task = None

    async def start(self):
        self.task = asyncio.create_task(self.run(), name="incremental-replay-jobs")

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def run(self):
        while True:
            try:
                await self.process_pending()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOG.exception("INCREMENTAL_REPLAY_JOBS_DEFERRED")
            await asyncio.sleep(0.5)

    async def process_pending(self):
        async with self.sessions() as session:
            predecessor = aliased(Track)
            successor = aliased(Track)
            left_group = aliased(Group)
            right_group = aliased(Group)
            ids = (
                (
                    await session.execute(
                        select(Relation.id)
                        .join(
                            predecessor,
                            (predecessor.mission_id == Relation.mission_id)
                            & (predecessor.track_id == Relation.predecessor_id),
                        )
                        .join(
                            successor,
                            (successor.mission_id == Relation.mission_id)
                            & (successor.track_id == Relation.successor_id),
                        )
                        .join(
                            left_group,
                            (left_group.mission_id == Relation.mission_id)
                            & (left_group.track_id == Relation.predecessor_id),
                        )
                        .join(
                            right_group,
                            (right_group.mission_id == Relation.mission_id)
                            & (right_group.track_id == Relation.successor_id),
                        )
                        .where(Relation.state == "pending")
                        .order_by(Relation.id)
                        .limit(self.batch_size)
                    )
                )
                .scalars()
                .all()
            )
            jobs = (
                await session.execute(
                    select(Dirty.mission_id, Dirty.window_start)
                    .where(Dirty.dirty.in_([1, 2]))
                    .order_by(Dirty.window_start, Dirty.mission_id)
                    .limit(self.batch_size)
                )
            ).all()
        for relation in ids:
            await self.apply_relation(relation)
        for mission, window in jobs:
            await self.process_window(mission, aware(window))
        # A relation may become eligible only after its endpoint facts arrive.

    async def apply_relation(self, key):
        async with self.sessions() as session:
            async with session.begin():
                relation = await session.get(Relation, key)
                if relation is None or relation.state != "pending":
                    return
                mission = await session.scalar(
                    select(Mission).where(Mission.id == relation.mission_id).with_for_update()
                )
                if mission is None:
                    return
                relation = await session.scalar(
                    select(Relation).where(Relation.id == key).with_for_update()
                )
                if relation.state != "pending":
                    return
                left = await session.scalar(
                    select(Track).where(
                        Track.mission_id == mission.id, Track.track_id == relation.predecessor_id
                    )
                )
                right = await session.scalar(
                    select(Track).where(
                        Track.mission_id == mission.id, Track.track_id == relation.successor_id
                    )
                )
                if left is None or right is None:
                    return
                gap = (right.started_offset_ms - left.ended_offset_ms) / 1000
                if (
                    not 0 < gap <= 2
                    or abs(gap - float(relation.evidence["temporal_gap_sec"])) > 0.001
                ):
                    relation.state = "quarantined"
                    LOG.error("INCREMENTAL_RELATION_TIME_CONFLICT relation=%s", key)
                    return
                left_component = await session.get(Group, (mission.id, left.track_id))
                right_component = await session.get(Group, (mission.id, right.track_id))
                if left_component is None or right_component is None:
                    return  # old facts have no incremental membership
                if left_component.root_track_id == right_component.root_track_id:
                    relation.state = "quarantined"
                    return
                old_root = right_component.root_track_id
                # Dirty only windows belonging to the component whose identity changes.
                after = None
                while True:
                    statement = (
                        select(Membership.window_start)
                        .join(
                            Group,
                            (Membership.mission_id == Group.mission_id)
                            & (Membership.track_id == Group.track_id),
                        )
                        .where(Group.mission_id == mission.id, Group.root_track_id == old_root)
                    )
                    if after is not None:
                        statement = statement.where(Membership.window_start > after)
                    windows = (
                        (
                            await session.execute(
                                statement.distinct()
                                .order_by(Membership.window_start)
                                .limit(self.page_size)
                            )
                        )
                        .scalars()
                        .all()
                    )
                    if not windows:
                        break
                    for window in windows:
                        await dirty_window(session, mission.id, window)
                    after = windows[-1]
                await session.execute(
                    update(Group)
                    .where(Group.mission_id == mission.id, Group.root_track_id == old_root)
                    .values(root_track_id=left_component.root_track_id)
                )
                relation.state = "applied"

    @staticmethod
    def document(event):
        return {
            name: getattr(event, name)
            for name in (
                "track_id",
                "sampling",
                "source_point_count",
                "started_offset_ms",
                "matched_link_id",
                "matched_lane_key",
                "movement_key",
                "turn_behavior",
            )
        }

    async def process_window(self, mission_id, window):
        async with self.sessions() as session:
            async with session.begin():
                # Common lock order with ingestion: Mission, then job. Never invert.
                mission = await session.scalar(
                    select(Mission).where(Mission.id == mission_id).with_for_update()
                )
                if mission is None:
                    return
                job = await session.scalar(
                    select(Dirty)
                    .where(Dirty.mission_id == mission_id, Dirty.window_start == window)
                    .with_for_update()
                )
                if job is None or not job.dirty:
                    return
                if job.dirty == 2:
                    await self.typical_slot(session, mission, window)
                    job.dirty = 0
                    job.processed_generation = job.generation
                    return
                info = {
                    "id": mission.id,
                    "inter_id": mission.inter_id,
                    "source_profile_id": mission.source_profile_id,
                    "started_at": aware(mission.started_at),
                }
                accumulator = WindowAccumulator(info, window)
                root = aliased(Track)
                after = None
                while True:
                    statement = (
                        select(Track, root)
                        .join(
                            Membership,
                            (Membership.mission_id == Track.mission_id)
                            & (Membership.track_id == Track.track_id),
                        )
                        .join(
                            Group,
                            (Group.mission_id == Track.mission_id)
                            & (Group.track_id == Track.track_id),
                        )
                        .join(
                            root,
                            (root.mission_id == Group.mission_id)
                            & (root.track_id == Group.root_track_id),
                        )
                        .where(Track.mission_id == mission_id, Membership.window_start == window)
                    )
                    if after is not None:
                        statement = statement.where(Track.track_id > after)
                    rows = (
                        await session.execute(
                            statement.order_by(Track.track_id).limit(self.page_size)
                        )
                    ).all()
                    if not rows:
                        break
                    ids = [event.track_id for event, _ in rows]
                    episodes = (
                        (
                            await session.execute(
                                select(Episode).where(
                                    Episode.mission_id == mission_id, Episode.track_id.in_(ids)
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    maneuvers = (
                        (
                            await session.execute(
                                select(Maneuver).where(
                                    Maneuver.mission_id == mission_id, Maneuver.track_id.in_(ids)
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    for event, parent in rows:
                        doc = self.document(event)
                        doc["episodes"] = [
                            {"kind": e.kind, "start_offset_ms": e.start_offset_ms}
                            for e in episodes
                            if e.track_id == event.track_id
                        ]
                        doc["maneuvers"] = [
                            {"kind": e.kind, "start_offset_ms": e.start_offset_ms}
                            for e in maneuvers
                            if e.track_id == event.track_id
                        ]
                        if (event.sampling or {}).get("algorithm_version") != "event-faithful/v2":
                            raise ValueError(
                                "incremental window jobs require full-sequence v2 summaries"
                            )
                        accumulator.add(doc, root=self.document(parent))
                    after = rows[-1][0].track_id
                coverage = await session.scalar(
                    select(func.avg(Sample.coverage_ratio)).where(
                        Sample.mission_id == mission_id,
                        Sample.sampled_at >= window,
                        Sample.sampled_at < window + timedelta(minutes=5),
                    )
                )
                accumulator.sample(coverage)
                for grain, model in MODELS.items():
                    await session.execute(
                        delete(model).where(
                            model.mission_id == mission_id,
                            model.window_start == window,
                            model.calc_version == "replay-v2-aggregate/v2",
                        )
                    )
                    for row in accumulator.facts()[grain]:
                        dimension = (
                            row.get("link_id")
                            or row.get("lane_id")
                            or row.get("movement_key")
                            or "intersection"
                        )
                        identity = hashlib.sha256(
                            json.dumps(
                                [grain, mission_id, window.isoformat(), dimension],
                                separators=(",", ":"),
                            ).encode()
                        ).hexdigest()[:40]
                        session.add(model(id=identity, **row))
                job.processed_generation = job.generation
                job.dirty = 0
                await session.flush()
                already_sealed = mission.status == "sealed"
                await self.finalize(session, mission)
                if already_sealed:
                    await self.typical_slot(session, mission, window)

    @staticmethod
    async def typical_slot(session, mission, window):
        metric = ReplayV2IntersectionMetric5Min
        stamp = (
            metric.window_start
            if session.get_bind().dialect.name == "sqlite"
            else func.timezone("UTC", metric.window_start)
        )
        day = (func.extract("dow", stamp) + 6) % 7
        step = func.extract("hour", stamp) * 12 + cast(func.extract("minute", stamp) / 5, Integer)
        weekday = window.weekday()
        slot = window.hour * 12 + window.minute // 5
        averages = (
            await session.execute(
                select(
                    func.count(func.distinct(func.date(stamp))),
                    func.avg(metric.vehicle_count),
                    func.avg(metric.avg_speed_kmh),
                )
                .join(Mission, Mission.id == metric.mission_id)
                .where(
                    metric.source_profile_id == mission.source_profile_id,
                    metric.inter_id == mission.inter_id,
                    metric.calc_version == "replay-v2-aggregate/v2",
                    Mission.status == "sealed",
                    day == weekday,
                    step == slot,
                )
            )
        ).one()
        version = (mission.algorithm_versions or {}).get("typical", "replay-v2-typical/v1")
        await session.execute(
            delete(ReplayV2InterEvaluation5MinMM).where(
                ReplayV2InterEvaluation5MinMM.source_profile_id == mission.source_profile_id,
                ReplayV2InterEvaluation5MinMM.inter_id == mission.inter_id,
                ReplayV2InterEvaluation5MinMM.day_of_week == weekday,
                ReplayV2InterEvaluation5MinMM.step_index == slot,
                ReplayV2InterEvaluation5MinMM.profile_version == version,
            )
        )
        if averages[0]:
            from app.services.replay_v2_metric_store import _fact_id

            session.add(
                ReplayV2InterEvaluation5MinMM(
                    id=_fact_id(
                        "typical",
                        mission.source_profile_id,
                        mission.inter_id,
                        weekday,
                        slot,
                        version,
                    ),
                    source_profile_id=mission.source_profile_id,
                    inter_id=mission.inter_id,
                    day_of_week=weekday,
                    step_index=slot,
                    profile_version=version,
                    sample_days=averages[0],
                    vehicle_count=averages[1],
                    avg_speed_kmh=averages[2],
                    saturation=None,
                    saturation_reason="lane_capacity_unavailable",
                    quality_status="estimated",
                )
            )

    @staticmethod
    async def finalize(session, mission):
        if mission.status != "finalizing":
            return
        totals = (
            await session.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(Track.source_point_count), 0),
                    func.coalesce(func.sum(Track.retained_point_count), 0),
                ).where(Track.mission_id == mission.id)
            )
        ).one()
        dirty = await session.scalar(
            select(Dirty.mission_id)
            .where(Dirty.mission_id == mission.id, Dirty.dirty == 1)
            .limit(1)
        )
        if totals[0] != mission.journey_count or dirty is not None:
            return
        if (totals[1], totals[2]) != (mission.source_point_count, mission.retained_point_count):
            mission.failure_reason = "incremental_manifest_totals_mismatch"
            return
        if mission.expected_relation_count is not None:
            applied = await session.scalar(
                select(func.count())
                .select_from(Relation)
                .where(Relation.mission_id == mission.id, Relation.state == "applied")
            )
            if applied != mission.expected_relation_count:
                return
        if mission.segment_manifest_hash:
            from utils_local.trajectory_manifest import manifest_line

            digest = hashlib.sha256()
            ordering = Track.track_id.collate(
                "BINARY" if session.get_bind().dialect.name == "sqlite" else "C"
            )
            after = None
            while True:
                statement = select(Track.track_id, Track.segment_digest).where(
                    Track.mission_id == mission.id
                )
                if after is not None:
                    statement = statement.where(ordering > after)
                rows = (await session.execute(statement.order_by(ordering).limit(256))).all()
                if not rows:
                    break
                for track, raw_hash in rows:
                    try:
                        digest.update(manifest_line(track, raw_hash))
                    except ValueError:
                        mission.failure_reason = "incremental_manifest_missing_digest"
                        return
                after = rows[-1][0]
            if digest.hexdigest() != mission.segment_manifest_hash:
                mission.failure_reason = "incremental_manifest_hash_mismatch"
                return
        mission.status = "sealed"
        mission.sealed_at = datetime.now(UTC)
        mission.updated_at = mission.sealed_at
        mission.failure_reason = None
        await session.execute(
            update(Dirty).where(Dirty.mission_id == mission.id, Dirty.dirty == 0).values(dirty=2)
        )
