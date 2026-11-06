"""Per-segment publication with a disk-backed index; no Mission-sized object graph.

SQLite is a private spool index, never a second business database. Kafka remains
our sole fact transport. Original segments and immutable messages survive crashes.
"""

from datetime import datetime, timedelta
from contextlib import closing
import hashlib
import json
import sqlite3
import uuid

from services.MissionTrajectoryArchive import (
    _atomic_json,
    _combine_segments,
    _journey_from_segment,
)
from utils_local.trajectory_sampling import compact_journey


def index(archive, mission):
    directory = archive._mission_dir(mission)
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / "incremental.sqlite3")
    db.execute("PRAGMA synchronous=FULL")
    db.execute(
        "CREATE TABLE IF NOT EXISTS segments (id TEXT PRIMARY KEY, start REAL, end REAL, points INTEGER, retained INTEGER, world INTEGER, behaviors INTEGER, boundary TEXT, digest TEXT)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS segment_start ON segments(start)")
    db.execute("CREATE INDEX IF NOT EXISTS segment_end ON segments(end)")
    db.execute(
        "CREATE TABLE IF NOT EXISTS relations (predecessor TEXT UNIQUE, successor TEXT UNIQUE, payload TEXT)"
    )
    return db


def identity(*parts):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join(map(str, parts))))


def publish_segment(producer, frame, segment):
    from services.MissionTrajectoryArchive import _validate_segment

    _validate_segment(segment)
    archive = producer.trajectory_archive
    manifest = archive.begin_mission(
        mission_id=producer.mission_id,
        source_profile_id=producer.source_profile_id,
        intersection_id=producer.intersection_id,
        source_timestamp_sec=segment["trajectory_timestamps_sec"][0],
    )
    start = float(manifest["observed_start_source_sec"])
    producer._replay_source_start_sec = start
    if manifest.get("incremental_time_basis"):
        producer._replay_time_basis = datetime.fromisoformat(
            manifest["incremental_time_basis"]
        )
    directory = archive._mission_dir(producer.mission_id)
    track = str(segment["track_id"])
    key = hashlib.sha256(track.encode()).hexdigest()
    message_path = directory / "incremental" / (key + ".json")
    digest = hashlib.sha256(json.dumps(segment, sort_keys=True).encode()).hexdigest()
    with closing(index(archive, producer.mission_id)) as db:
        existing = db.execute(
            "SELECT digest FROM segments WHERE id=?", (track,)
        ).fetchone()
        if existing and existing[0] != digest:
            raise ValueError("incremental segment identity conflict")
    if manifest.get("incremental_terminal") and not message_path.exists():
        raise ValueError("terminal incremental Mission cannot accept new segments")
    # Reuse exact wire bytes/identity on recovery, including envelope timestamps.
    if message_path.exists():
        raw_path = directory / "raw" / (key + ".json")
        original = json.loads(raw_path.read_text())
        if (
            hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest()
            != digest
        ):
            raise ValueError("incremental segment identity conflict")
        message = json.loads(message_path.read_text())
    else:
        _atomic_json(directory / "raw" / (key + ".json"), segment)
        journey = _journey_from_segment(_combine_segments([segment]), start, True)
        journey["source_runtime_track_ids"] = [track]
        journey["track_id"] = track
        journey["reid_evidence"] = []
        basis = manifest.get("incremental_time_basis")
        if basis is None:
            clock = producer._canonical_envelope("uav_track_complete", {}, frame)
            basis = (
                datetime.fromisoformat(clock["occurred_at"])
                - timedelta(seconds=float(frame.timestamp) - start)
            ).isoformat()
            manifest["incremental_time_basis"] = basis
            _atomic_json(directory / "manifest.json", manifest)
        compact_journey(
            journey,
            time_basis=basis,
            policy=archive.sampling_policy or {"enabled": False},
            event_windows=archive.event_windows.get(track, []),
        )
        message = producer._canonical_envelope(
            "uav_track_complete",
            {
                "intersection_id": producer.intersection_id,
                "archive_schema_version": "incremental/v1",
                "mission_start_source_sec": start,
                "segment_digest": digest,
                **journey,
            },
            frame,
            message_id=identity("traffic-analyzer", producer.mission_id, track),
        )
        message["schema_version"] = "uav_track_complete/replay-v2"
        # Transport packing/chunking belongs to the publisher boundary.
        _atomic_json(message_path, message)
    # A crash after enqueue is safe: consumers deduplicate by identity and hash.
    producer._enqueue(producer.track_complete_topic, message, durable=True)
    with closing(index(archive, producer.mission_id)) as db:
        old = db.execute("SELECT digest FROM segments WHERE id=?", (track,)).fetchone()
        digest = hashlib.sha256(
            json.dumps(segment, sort_keys=True).encode()
        ).hexdigest()
        if old and old[0] != digest:
            raise ValueError("incremental segment identity conflict")
        if not old:
            from utils_local.track_message_codec import unpack_track_message

            journey = unpack_track_message(message)["data"]
            summary = journey.get("sampling", {}).get("full_sequence_summary", {})
            boundary = {k: segment.get(k) for k in ("track_id", "appearance_embedding")}
            for k in ("trajectory_timestamps_sec", "trajectory_enu_m", "trajectory_px"):
                boundary[k] = [segment[k][0], segment[k][-1]]
            db.execute(
                "INSERT INTO segments VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    track,
                    segment["trajectory_timestamps_sec"][0],
                    segment["trajectory_timestamps_sec"][-1],
                    journey["source_point_count"],
                    journey["retained_point_count"],
                    summary.get(
                        "world_point_count",
                        sum(p.get("enu_m") is not None for p in journey["points"]),
                    ),
                    len(journey.get("episodes", []))
                    + len(journey.get("maneuvers", [])),
                    json.dumps(boundary),
                    digest,
                ),
            )
        db.commit()
    archive.event_windows.pop(track, None)
    relation_worker(producer).closed(segment)
    return 1


def publish_manifest(producer, frame, reason):
    archive = producer.trajectory_archive
    with closing(index(archive, producer.mission_id)) as db:
        count, points, retained, world, behaviors, end = db.execute(
            "SELECT count(*),coalesce(sum(points),0),coalesce(sum(retained),0),coalesce(sum(world),0),coalesce(sum(behaviors),0),max(end) FROM segments"
        ).fetchone()
    manifest = archive.begin_mission(
        mission_id=producer.mission_id,
        source_profile_id=producer.source_profile_id,
        intersection_id=producer.intersection_id,
    )
    start = float(manifest["observed_start_source_sec"])
    producer._replay_source_start_sec = start
    relation_worker(producer).finish()
    from utils_local.trajectory_manifest import manifest_hash

    with closing(index(archive, producer.mission_id)) as db:
        final_hash = manifest_hash(
            db.execute("SELECT id,digest FROM segments ORDER BY id COLLATE BINARY")
        )
        relation_count = db.execute("SELECT count(*) FROM relations").fetchone()[0]
    status = "sealed" if reason == "natural_eof" else "incomplete"
    payload = {
        "mission_id": producer.mission_id,
        "status": status,
        "termination_reason": reason,
        "duration_sec": max(float(frame.timestamp) - start, 0),
        "journey_count": count,
        "expected_relation_count": relation_count,
        "segment_manifest_hash": final_hash,
        "source_point_count": points,
        "retained_point_count": retained,
        "behavior_count": behaviors,
        "coordinate_coverage_ratio": world / points if points else 0,
        "algorithm_versions": {
            "archive": "incremental/v1",
            "aggregate": "replay-v2-aggregate/v2",
            "sampling": "event-faithful/v2",
        },
    }
    path = archive._mission_dir(producer.mission_id) / (
        "incremental-" + status + ".json"
    )
    if path.exists():
        message = json.loads(path.read_text())
    else:
        message = producer._canonical_envelope(
            "uav_replay_mission",
            payload,
            frame,
            message_id=identity("traffic-analyzer", producer.mission_id, status),
        )
        message["schema_version"] = "uav_replay_mission/v2"
        _atomic_json(path, message)
    producer._enqueue(producer.mission_topic, message, durable=True)
    manifest["incremental_terminal"] = True
    _atomic_json(archive._mission_dir(producer.mission_id) / "manifest.json", manifest)
    return count


def relation_worker(producer):
    worker = getattr(producer, "_streaming_relations", None)
    if worker is None:
        from services.StreamingTrajectoryRelations import StreamingRelations

        worker = StreamingRelations(
            producer.trajectory_archive,
            producer.mission_id,
            lambda predecessor, successor, evidence: publish_relation(
                producer, predecessor, successor, evidence
            ),
        )
        producer._streaming_relations = worker
    return worker


def publish_relation(producer, predecessor, successor, evidence):
    directory = producer.trajectory_archive._mission_dir(producer.mission_id)
    path = directory / "relations" / (identity(predecessor, successor) + ".json")
    if path.exists():
        message = json.loads(path.read_text())
    else:
        successor_message = json.loads(
            (
                directory
                / "incremental"
                / (hashlib.sha256(successor.encode()).hexdigest() + ".json")
            ).read_text()
        )
        message = {
            **{k: v for k, v in successor_message.items() if k != "content_hash"},
            "msg_type": "uav_track_relation",
            "schema_version": "uav_track_relation/v1",
            "message_id": identity(
                "relation", producer.mission_id, predecessor, successor
            ),
            "data": {
                **{
                    k: v
                    for k, v in successor_message["data"].items()
                    if k
                    in {
                        "mission_id",
                        "source_profile_id",
                        "pipeline_id",
                        "run_id",
                        "offset_ms",
                    }
                },
                "mission_id": producer.mission_id,
                "predecessor_id": predecessor,
                "successor_id": successor,
                "evidence": evidence,
            },
        }
        _atomic_json(path, message)
    producer._enqueue("uav_track_relations", message, durable=True)
    with closing(index(producer.trajectory_archive, producer.mission_id)) as db:
        db.execute(
            "INSERT OR IGNORE INTO relations VALUES (?,?,?)",
            (predecessor, successor, json.dumps(message["data"])),
        )
        db.commit()


def reconcile_relations(producer):
    # Kept as a callable seam for tooling; normal frames run the bounded worker.
    return relation_worker(producer).process_once()
