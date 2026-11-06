"""Bounded, acknowledged delta transport and the fourth pipeline worker.

Only builtin values, bounded frame facts and evidence descriptors cross this
boundary. Neither live TrackElement objects nor video pixels are accepted.
"""

from __future__ import annotations
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import pickle
import re
from queue import Empty, Full
import struct
import time
import uuid
import weakref
from types import SimpleNamespace

import numpy as np
from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from elements.RenderSnapshot import RenderSnapshot, RenderTrackSnapshot
from utils_local.runtime_logging import stage, audit_stage, audit_observe

LOG = logging.getLogger("pipeline.egress")
_CLIENTS = weakref.WeakSet()
POINT_FIELDS = (
    "trajectory_bbox_center_px",
    "trajectory_px",
    "trajectory_enu_m",
    "trajectory_gcj02",
    "trajectory_timestamps_sec",
    "trajectory_frame_nums",
    "point_quality_lineage",
)
TRACK_FIELDS = {
    "trajectory_points": "trajectory_bbox_center_px",
    "ground_contact_points_px": "trajectory_px",
    **{
        k: k
        for k in POINT_FIELDS
        if k not in {"trajectory_bbox_center_px", "trajectory_px"}
    },
}
TAIL_FIELDS = set(TRACK_FIELDS) | {"position_history", "position_history_enu_m"}
DROP_TRACK_FIELDS = {
    "appearance_crop_jpeg",
    "class_id_history",
    "class_name_history",
    "vehicle_class_history",
    "point_quality_lineage",
    "lane_history",
    "conflict_events",
    "flight_phases",
    "flight_segment_ids",
}
# Fields that change almost every frame; everything else per track is sent once
# per track and re-sent only when its value actually changes (see the delta
# payload builder below).
_DYNAMIC_TRACK_FIELDS = frozenset(
    {
        "trajectory_point_count",
        "trajectory_history_start",
        "trajectory_time_offsets_sec",
        "timestamp_last",
        # Measured on a live corridor run: speeds/heading/observation time change on
        # 24-52% of tracks per frame, so keeping them static re-sends a whole block.
        "avg_speed_kmh",
        "speed_kmh",
        "heading_angle",
        "current_observation_timestamp_sec",
        "max_speed_kmh",
        "current_bbox_xyxy",
        "current_position_enu_m",
        "velocity_ms",
        "is_trajectory_tail",
        "current_frame_size",
    }
)
# ``render_snapshot`` is the display view rebuilt for the image owner; the egress
# writer never reads it.  Inside the full facts packet pickle deduplicates its
# track dictionaries against ``active_tracks``, but a delta packet re-serialises
# them standalone, so it must be dropped to keep the delta smaller than the full
# snapshot.
_DELTA_DROP_FIELDS = frozenset({"render_snapshot"})
_TRACK_CONTAINER_FIELDS = ("active_tracks", "buffer_tracks", "mature_tracks")

DROP_FRAME_FIELDS = {
    "frame",
    "frame_result",
    "buffer_tracks",
    "active_tracks",
    "mature_tracks",
    "completed_tracks",
    "candidate_trajectories",
    "association_trajectories",
    "render_snapshot",
}


def queue_depth(queue):
    try:
        return queue.qsize()
    except (AttributeError, NotImplementedError, OSError):
        return -1


def plain(value):
    if value is None or type(value) in (str, bytes, bool, int, float):
        return value
    if isinstance(value, np.ndarray):
        if value.ndim >= 2 and value.shape[0] > 8 and value.shape[1] > 8:
            raise ValueError("video/image matrices cannot cross the egress boundary")
        return plain(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return tuple(plain(v) for v in value)
    if value is None or isinstance(value, (str, bytes, bool, int, float)):
        return value
    if hasattr(value, "__dict__"):
        return SimpleNamespace(**plain(vars(value)))
    raise TypeError("unsupported egress value: " + type(value).__name__)


def facts_delta_payload(facts, static_cache: dict) -> dict:
    """Build an incremental facts packet for ``EgressClient``.

    ``frame_meta`` is sent every frame, but only the per-track fields listed in
    ``_DYNAMIC_TRACK_FIELDS`` (plus any track whose static fields changed) go on
    the wire; the receiver rebuilds the exact same ``RenderTrackSnapshot`` values.
    """
    meta = {
        key: value
        for key, value in vars(facts).items()
        if key not in _TRACK_CONTAINER_FIELDS and key not in _DELTA_DROP_FIELDS
    }
    tracks = getattr(facts, "active_tracks", None) or {}
    present = list(tracks)
    mature = getattr(facts, "mature_tracks", None)
    static_changed = {}
    dynamic = {}
    for key, track in tracks.items():
        values = track._values
        static, moving = {}, {}
        for name, value in values.items():
            (moving if name in _DYNAMIC_TRACK_FIELDS else static)[name] = value
        dynamic[key] = moving
        if static_cache.get(key) != static:
            static_changed[key] = static
            static_cache[key] = static
    live = set(dynamic)
    for key in [key for key in static_cache if key not in live]:
        static_cache.pop(key, None)
    return {
        "frame_seq": int(facts.egress_frame_seq),
        "meta": meta,
        "present": present,
        "mature": None if mature is None else list(mature),
        "static": static_changed,
        "dynamic": dynamic,
    }


def apply_facts_delta(payload: dict, static_cache: dict):
    """Rebuild the full facts object a ``frame_delta`` packet describes."""
    from elements.FrameElement import FrameElement

    for key, values in payload["static"].items():
        static_cache[key] = values
    present = payload["present"]
    dynamic = payload["dynamic"]
    tracks = {}
    for key in present:
        static = static_cache.get(key)
        if static is None:
            raise ValueError("frame delta references an unknown track static block")
        tracks[key] = RenderTrackSnapshot({**static, **dynamic.get(key, {})})
    result = object.__new__(FrameElement)
    result.__dict__ = dict(payload["meta"])
    for dropped in _DELTA_DROP_FIELDS:
        # Keep the attribute present so readers that use ``getattr`` without a
        # default see ``None`` instead of raising.
        setattr(result, dropped, None)
    result.active_tracks = tracks
    result.buffer_tracks = tracks
    mature = payload["mature"]
    result.mature_tracks = (
        None
        if mature is None
        else {key: tracks[key] for key in mature if key in tracks}
    )
    live = set(present)
    for key in [key for key in static_cache if key not in live]:
        static_cache.pop(key, None)
    return result


def freeze_display_frame(frame):
    """Own only the track fields read by ShowNode, after analysis/publication."""
    return freeze_frame(frame, display_only=True)


def freeze_frame(frame, tail_points=30, *, display_only=False):
    if isinstance(frame, VideoEndBreakElement):
        return frame
    result = object.__new__(FrameElement)
    result.__dict__ = {
        k: plain(v) for k, v in vars(frame).items() if k not in DROP_FRAME_FIELDS
    }
    result.frame = result.frame_result = None
    views = {}
    active = getattr(frame, "active_tracks", None)
    if active is None:
        active = getattr(frame, "buffer_tracks", None) or {}
    for key, track in active.items():
        values = {}
        for name, value in vars(track).items():
            if display_only and name not in {
                "id",
                "start_road",
                "avg_speed_kmh",
                "trajectory_output_eligible",
                "trajectory_points",
            }:
                continue
            if name in DROP_TRACK_FIELDS:
                values[name] = None if name == "appearance_crop_jpeg" else ()
            elif name in TAIL_FIELDS:
                values[name] = plain(
                    (value or [])[-tail_points:] if tail_points else ()
                )
            else:
                values[name] = plain(value)
        values["trajectory_point_count"] = getattr(track, "trajectory_history_start", 0) + len(
            getattr(track, "trajectory_points", ()) or ()
        )
        views[key] = RenderTrackSnapshot(values)
    result.buffer_tracks = result.active_tracks = views
    result.mature_tracks = (
        {
            k: views[k]
            for k in (getattr(frame, "mature_tracks", None) or {})
            if k in views
        }
        if getattr(frame, "mature_tracks", None) is not None
        else None
    )
    for name in ("candidate_trajectories", "association_trajectories"):
        rows = []
        for row in getattr(frame, name, None) or []:
            rows.append(
                {
                    k: plain(
                        (v[-tail_points:] if tail_points else ())
                        if isinstance(v, (tuple, list))
                        and (
                            k.startswith("trajectory_") or k == "point_quality_lineage"
                        )
                        else v
                    )
                    for k, v in row.items()
                    if not display_only
                    or k
                    in {
                        "track_id",
                        "association_id",
                        "trajectory_px",
                        "trajectory_display_px",
                    }
                }
            )
        setattr(result, name, rows)
    result.completed_tracks = None
    result.render_snapshot = RenderSnapshot(
        int(frame.frame_num), tuple(views.values()), tail_points
    )
    return result


_DISPLAY_TRACK_FIELDS = (
    "id",
    "start_road",
    "avg_speed_kmh",
    "trajectory_output_eligible",
)
_DISPLAY_TRAJECTORY_FIELDS = frozenset(
    {"track_id", "association_id", "trajectory_px", "trajectory_display_px"}
)


def freeze_egress_views(frame):
    """Freeze once, then form separate image-owner and archive views.

    Shared metadata is detached from live P2 state. EgressClient serializes the
    archive view synchronously before handing the display view to its feeder;
    the two consumers therefore cannot mutate one another's dictionaries.
    """
    with stage("egress.freeze_metadata"):
        metadata = {
            k: plain(v) for k, v in vars(frame).items() if k not in DROP_FRAME_FIELDS
        }
    active = getattr(frame, "active_tracks", None)
    if active is None:
        active = getattr(frame, "buffer_tracks", None) or {}
    archive_tracks, display_tracks = {}, {}
    with stage("egress.freeze_tracks", tracks=len(active)):
        for key, track in active.items():
            values = {}
            for name, value in vars(track).items():
                if name in DROP_TRACK_FIELDS:
                    values[name] = None if name == "appearance_crop_jpeg" else ()
                elif name in TAIL_FIELDS:
                    values[name] = ()
                else:
                    values[name] = plain(value)
            values["trajectory_point_count"] = getattr(track,"trajectory_history_start",0) + len(track.trajectory_points)
            archive_tracks[key] = RenderTrackSnapshot(values)
            display = {
                name: values[name] for name in _DISPLAY_TRACK_FIELDS if name in values
            }
            display["trajectory_point_count"] = values["trajectory_point_count"]
            display["trajectory_points"] = plain(track.trajectory_points[-30:])
            display_tracks[key] = RenderTrackSnapshot(display)

    with stage("egress.freeze_previews"):
        candidates = []
        for row in getattr(frame, "candidate_trajectories", None) or []:
            candidates.append(
                {
                    k: plain(
                        v[-30:]
                        if isinstance(v, (tuple, list))
                        and (
                            k.startswith("trajectory_") or k == "point_quality_lineage"
                        )
                        else v
                    )
                    for k, v in row.items()
                }
            )
        display_candidates = [
            {k: v for k, v in row.items() if k in _DISPLAY_TRAJECTORY_FIELDS}
            for row in candidates
        ]
        associations, display_associations = [], []
        for row in getattr(frame, "association_trajectories", None) or []:
            facts, display = {}, {}
            for key, value in row.items():
                history = isinstance(value, (tuple, list)) and (
                    key.startswith("trajectory_") or key == "point_quality_lineage"
                )
                facts[key] = () if history else plain(value)
                if key in _DISPLAY_TRAJECTORY_FIELDS:
                    display[key] = plain(value[-30:]) if history else facts[key]
            associations.append(facts)
            display_associations.append(display)

    def view(tracks, candidate_rows, association_rows, tail):
        result = object.__new__(FrameElement)
        result.__dict__ = dict(metadata)
        result.frame = result.frame_result = None
        result.active_tracks = result.buffer_tracks = tracks
        mature = getattr(frame, "mature_tracks", None)
        result.mature_tracks = (
            {k: tracks[k] for k in mature if k in tracks}
            if mature is not None
            else None
        )
        result.candidate_trajectories = candidate_rows
        result.association_trajectories = association_rows
        result.completed_tracks = None
        result.render_snapshot = RenderSnapshot(
            int(frame.frame_num), tuple(tracks.values()), tail
        )
        return result

    return view(display_tracks, display_candidates, display_associations, 30), view(
        archive_tracks, candidates, associations, 0
    )


class EgressClient:
    """ACK only after an immutable packet has reached the writer's fsynced journal."""

    def __init__(
        self,
        role,
        queue,
        acknowledgements,
        *,
        timeout=10.0,
        max_points=1024,
        alive=None,
        failure_spool=None,
        optimized_views=True,
        bounded_history=False,
        history_tail_points=128,
    ):
        if (
            role not in {"tracker", "show"}
            or not 1 <= max_points <= 1024
            or timeout <= 0
        ):
            raise ValueError("invalid egress client limits/role")
        self.role, self.queue, self.acks = role, queue, acknowledgements
        self.optimized_views = optimized_views
        # Incremental per-frame facts: only dynamic track fields plus changed
        # static blocks cross the queue.  ``PIPELINE_FACTS_DELTA=0`` restores the
        # full snapshot packet for A/B and rollback.
        self.facts_delta = os.environ.get(
            "PIPELINE_FACTS_DELTA", "1"
        ).strip().lower() not in {"0", "false", "no", "off"}
        self._static_facts: dict = {}
        self.bounded_history = bounded_history
        if history_tail_points < 60:
            raise ValueError("online history tail must cover the existing 60-point analysis window")
        self.history_tail_points = history_tail_points
        self.timeout, self.max_points, self.alive = timeout, max_points, alive
        self.sequence = self.confirmed = 0
        self.pending = {}
        self.unconfirmed_packets = {}
        self.failure_spool = Path(failure_spool) if failure_spool else None
        self.failure_saved = False
        _CLIENTS.add(self)
        self.offsets = {}
        self.open_ids = set()
        self.frame_counter = 0
        self.last_ack = time.monotonic()

    def drain(self):
        while True:
            try:
                seq = self.acks.get_nowait()
            except Empty:
                break
            if seq <= self.confirmed:
                continue
            if seq != self.confirmed + 1 or seq > self.sequence:
                raise RuntimeError("egress ACK sequence invalid")
            self.confirmed = seq
            sent_at = self.pending.pop(seq, None)
            if sent_at is not None:
                audit_observe("egress.durable_ack_latency", (time.monotonic()-sent_at)*1000)
            self.unconfirmed_packets.pop(seq, None)
            self.last_ack = time.monotonic()
        if self.pending and time.monotonic() - self.last_ack > self.timeout:
            raise TimeoutError("egress durable ACK stalled")
        if self.alive is not None and not self.alive():
            raise RuntimeError("egress worker died")

    def send(self, kind, data):
        # A stalled ACK channel must not retain a Mission-sized set of wire bytes.
        if len(self.pending) >= 32:
            self.wait()
        with stage("egress.serialize." + kind, role=self.role):
            payload = pickle.dumps((kind, data), protocol=pickle.HIGHEST_PROTOCOL)
        self.sequence += 1
        packet = (
            self.role,
            self.sequence,
            hashlib.sha256(payload).hexdigest(),
            payload,
        )
        # Keep immutable wire bytes until durable ACK, including the packet whose
        # enqueue fails. Disk IO remains off the real-time path until a failure.
        self.unconfirmed_packets[self.sequence] = packet
        try:
            self.drain()
            was_empty = not self.pending
            with stage(
                "egress.enqueue",
                role=self.role,
                seq=self.sequence,
                bytes=len(payload),
                kind=kind,
            ):
                try:
                    self.queue.put(packet, timeout=self.timeout)
                except Full:
                    raise TimeoutError("egress queue remained full") from None
            self.pending[self.sequence] = time.monotonic()
            if was_empty:
                self.last_ack = time.monotonic()
            self.drain()
        except BaseException:
            self.preserve_pending()
            raise

    def preserve_pending(self):
        if (
            self.failure_spool is None
            or self.failure_saved
            or not self.unconfirmed_packets
        ):
            return
        try:
            self.failure_spool.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = self.failure_spool / (
                "unconfirmed-" + self.role + "-" + uuid.uuid4().hex + ".packets"
            )
            with os.fdopen(
                os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
            ) as stream:
                for packet in self.unconfirmed_packets.values():
                    encoded = pickle.dumps(packet, protocol=pickle.HIGHEST_PROTOCOL)
                    stream.write(struct.pack("!Q", len(encoded)) + encoded)
                stream.flush()
                os.fsync(stream.fileno())
            directory = os.open(self.failure_spool, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            self.failure_saved = True
            LOG.error(
                "EGRESS_UNCONFIRMED_RETAINED role=%s packets=%s path=%s",
                self.role,
                len(self.unconfirmed_packets),
                path,
            )
        except OSError:
            LOG.exception(
                "EGRESS_UNCONFIRMED_SAVE_FAILED role=%s packets=%s",
                self.role,
                len(self.unconfirmed_packets),
            )

    def wait(self):
        try:
            with stage("egress.ack_wait", role=self.role, pending=len(self.pending)):
                while self.confirmed != self.sequence:
                    self.drain()
                    time.sleep(0.01)
        except BaseException:
            self.preserve_pending()
            raise

    def point_rows(self, track_id, arrays, base=0):
        local_count = len(arrays["trajectory_px"])
        count = base + local_count
        if any(len(arrays[k]) != local_count for k in POINT_FIELDS):
            raise ValueError("delta trajectory arrays are not aligned")
        start = self.offsets.get(str(track_id), 0)
        if start < base:
            raise ValueError("authoritative history was evicted before durable transfer")
        if count < start:
            raise ValueError("authoritative point history regressed")
        rows = []
        for offset in range(start, count, self.max_points):
            end = min(offset + self.max_points, count)
            rows.append(
                {
                    "track_id": str(track_id),
                    "start": offset,
                    "arrays": {k: plain(arrays[k][offset-base:end-base]) for k in POINT_FIELDS},
                }
            )
        self.offsets[str(track_id)] = count
        if count:
            self.open_ids.add(str(track_id))
        return rows

    def points(self, track_id, arrays, base=0):
        for row in self.point_rows(track_id, arrays, base):
            self.send("points_batch", [row])

    def track_arrays(self, track):
        return {
            target: getattr(track, source) for source, target in TRACK_FIELDS.items()
        }

    def closed(self, rows):
        for row in rows or []:
            arrays = {k: row.get(k) for k in POINT_FIELDS}
            arrays["trajectory_bbox_center_px"] = (
                row.get("trajectory_bbox_center_px") or row["trajectory_px"]
            )
            base = int(row.get("trajectory_history_start", 0))
            self.points(row["track_id"], arrays, base)
            meta = {
                k: plain(v)
                for k, v in row.items()
                if k
                not in {
                    *POINT_FIELDS,
                    "ground_contact_points_px",
                    "trajectory_time_offsets_sec",
                }
            }
            self.send(
                "close",
                {
                    "track_id": str(row["track_id"]),
                    "point_count": base + len(arrays["trajectory_px"]),
                    "metadata": meta,
                },
            )
            self.open_ids.discard(str(row["track_id"]))
            self.offsets.pop(str(row["track_id"]), None)

    def frame(self, frame):
        tracks = (
            getattr(frame, "active_tracks", None)
            or getattr(frame, "buffer_tracks", None)
            or {}
        )
        batch = []
        size = 0
        for key, track in tracks.items():
            for row in self.point_rows(key, self.track_arrays(track), getattr(track, "trajectory_history_start", 0)):
                count = len(row["arrays"]["trajectory_px"])
                if batch and size + count > self.max_points:
                    self.send("points_batch", batch)
                    batch = []
                    size = 0
                batch.append(row)
                size += count
        if batch:
            self.send("points_batch", batch)
        closed = getattr(frame, "completed_tracks", None) or []
        self.closed(closed)
        for key in sorted(self.open_ids - {str(k) for k in tracks}):
            self.discard(key, "lifecycle_did_not_emit_completed_track")
        if self.optimized_views:
            snapshot, facts = freeze_egress_views(frame)
        else:
            snapshot, facts = freeze_frame(frame), freeze_frame(frame, 0)
            facts.candidate_trajectories = snapshot.candidate_trajectories
        self.frame_counter += 1
        snapshot.egress_frame_seq = self.frame_counter
        snapshot.egress_closed_ids = [str(row["track_id"]) for row in closed]
        facts.egress_frame_seq = snapshot.egress_frame_seq
        facts.egress_closed_ids = snapshot.egress_closed_ids
        if self.facts_delta and self.optimized_views:
            self.send("frame_delta", facts_delta_payload(facts, self._static_facts))
        else:
            self.send("frame", facts)
        if self.bounded_history and self.confirmed == self.sequence:
            # Only evict after the writer's fsynced ACK covers this whole frame.
            for track in tracks.values():
                remove = max(0, len(track.trajectory_points)-self.history_tail_points)
                if remove:
                    for source in TRACK_FIELDS:
                        del getattr(track, source)[:remove]
                    track.trajectory_history_start = getattr(track,'trajectory_history_start',0)+remove
        frame.completed_tracks = None
        return snapshot

    def mark_replay_mission_incomplete(self, *, failure_reason):
        self.send("abort", failure_reason)

    def discard(self, key, reason):
        self.send(
            "discard",
            {"track_id": key, "point_count": self.offsets[key], "reason": reason},
        )
        self.open_ids.remove(key)

    def finish(self, eof):
        for key in sorted(self.open_ids):
            self.discard(key, "not_eligible_at_eof")
        self.send("eof", eof)
        self.wait()


def pipeline_egress_root():
    identity = os.environ.get("PIPELINE_ID") or ("offline-" + str(os.getppid()))
    if not re.fullmatch("[A-Za-z0-9_.-]{1,128}", identity) or identity in {".", ".."}:
        raise ValueError("invalid pipeline working-directory identity")
    base = Path(os.environ.get("KAFKA_SPOOL_DIR", "output/kafka-spool")).resolve()
    root = (base / identity / "egress").resolve()
    if not root.is_relative_to(base):
        raise ValueError("pipeline working directory escapes its spool root")
    return root


def preserve_client_pending():
    for client in list(_CLIENTS):
        client.preserve_pending()


class PacketJournal:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / "pending.packets"
        self.stream = os.fdopen(
            os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
        )
        self.sequences = {}
        from services.TrajectorySpoolIndex import DiskHashes
        self.hashes = DiskHashes(self.root)

    def accept(self, packet):
        role, seq, checksum, payload = packet
        if (
            role not in {"tracker", "show"}
            or type(seq) is not int
            or seq < 1
            or hashlib.sha256(payload).hexdigest() != checksum
        ):
            raise ValueError("invalid egress packet/hash")
        key = (role, seq)
        if key in self.hashes:
            if self.hashes[key] != checksum:
                raise ValueError("egress packet identity conflict")
            return None
        if seq != self.sequences.get(role, 0) + 1:
            raise ValueError("egress packet gap")
        decoded = pickle.loads(payload)
        allowed = {
            "tracker": {"points_batch", "close", "discard", "frame", "frame_delta", "eof", "abort"},
            "show": {"render", "eof", "abort"},
        }
        if (
            not isinstance(decoded, tuple)
            or len(decoded) != 2
            or decoded[0] not in allowed[role]
        ):
            raise ValueError("egress producer role/kind mismatch")
        encoded = pickle.dumps(packet, protocol=pickle.HIGHEST_PROTOCOL)
        with stage("egress.journal", role=role, seq=seq, bytes=len(encoded)):
            with audit_stage("egress.journal_write"):
                self.stream.write(struct.pack("!Q", len(encoded)) + encoded)
                self.stream.flush()
            with audit_stage("egress.journal_fsync"):
                os.fsync(self.stream.fileno())
        self.sequences[role] = seq
        self.hashes[key] = checksum
        return decoded

    def close(self, success=False):
        self.stream.close()
        self.hashes.close()
        if success:
            self.path.unlink()


class DeltaTracks:
    def __init__(self, root=None, *, cache_kib=16384):
        self.rows = {}
        self.closed = {}
        from services.TrajectorySpoolIndex import connection, DiskIdentities
        import tempfile
        self.disk = connection(root or tempfile.mkdtemp(prefix='trajectory-state-'), cache_kib=cache_kib)
        self.completed_ids = DiskIdentities(self.disk, 'completed')
        self.discarded_ids = DiskIdentities(self.disk, 'discarded')
        self.retired = {}

    def append(self, value):
        self.append_batch([value])

    def append_batch(self, values):
        """Validate a packet before writing; keep the journal as the ACK boundary."""
        from services.TrajectorySpoolIndex import DiskArray

        staged, writes, updates = {}, [], []
        for value in values:
            key = value["track_id"]
            if key not in staged:
                row = self.rows.get(key)
                if row is None:
                    if key in self.completed_ids or key in self.discarded_ids:
                        raise ValueError("points appended to closed trajectory")
                    row = {k: DiskArray(self.disk, key, k) for k in POINT_FIELDS}
                times = row["trajectory_timestamps_sec"]
                staged[key] = (row, len(row["trajectory_px"]), times[-1] if len(times) else None)
            row, start, last_time = staged[key]
            self._validate_append(value, start, last_time)
            arrays = value["arrays"]
            count = len(arrays["trajectory_px"])
            for field in POINT_FIELDS:
                array = row[field]
                record, tail = array.prepare(arrays[field], start)
                writes.append(record)
                updates.append((array, count, tail))
            staged[key] = (row, start + count, arrays["trajectory_timestamps_sec"][-1])
        if not writes:
            return
        # An outer transaction already spans the private index until EOF. Do not
        # accidentally make RELEASE of an outermost savepoint commit each packet.
        if not self.disk.in_transaction:
            self.disk.execute("BEGIN")
        self.disk.execute("SAVEPOINT points_packet")
        try:
            with audit_stage("egress.sql_insert", rows=len(writes)):
                self.disk.executemany("INSERT INTO arrays VALUES (?,?,?,?,?)", writes)
        except BaseException:
            self.disk.execute("ROLLBACK TO points_packet")
            raise
        finally:
            self.disk.execute("RELEASE points_packet")
        for array, count, tail in updates:
            array.accept(count, tail)
        self.rows.update((key, state[0]) for key, state in staged.items())

    @staticmethod
    def _validate_append(value, start, last_time):
        if value["start"] != start:
            raise ValueError("trajectory point sequence gap")
        arrays = value["arrays"]
        count = len(arrays["trajectory_px"])
        if not 1 <= count <= 1024 or any(len(arrays[k]) != count for k in POINT_FIELDS):
            raise ValueError("invalid trajectory batch size/alignment")
        times = ([last_time] if last_time is not None else []) + list(arrays["trajectory_timestamps_sec"])
        if any(not math.isfinite(float(t)) for t in times) or any(
            b <= a for a, b in zip(times, times[1:])
        ):
            raise ValueError("trajectory source time regressed")
        for key in (
            "trajectory_bbox_center_px",
            "trajectory_px",
            "trajectory_enu_m",
            "trajectory_gcj02",
        ):
            for value in arrays[key]:
                if value is None and key in {"trajectory_enu_m", "trajectory_gcj02"}:
                    continue
                if (
                    not isinstance(value, (list, tuple))
                    or len(value) != 2
                    or not all(math.isfinite(float(v)) for v in value)
                ):
                    raise ValueError("invalid trajectory geometry")

    def finish(self, value):
        key = value["track_id"]
        if key in self.completed_ids:
            raise ValueError("duplicate trajectory close")
        row = self.rows.pop(key, None)
        if row is None or len(row["trajectory_px"]) != value["point_count"]:
            raise ValueError("trajectory close point count mismatch")
        if str(value["metadata"].get("track_id")) != key:
            raise ValueError("trajectory close identity mismatch")
        row = {k: list(values) for k, values in row.items()}
        self.disk.execute("DELETE FROM arrays WHERE track=?", (key,))
        row.update(value["metadata"])
        classifier = row.pop('_deferred_turn_classifier', None)
        if classifier and not row.get('turn_behavior'):
            from utils_local.trajectory_classifier import classify_turning_movement
            row['turn_behavior'] = classify_turning_movement(row['trajectory_px'],
                roundabout_center=classifier.get('roundabout_center'), thresholds=classifier['thresholds'])
        if row.pop('trajectory_history_start', 0):
            valid = [p for p in row['trajectory_enu_m'] if p is not None]
            if valid:
                row['entry_point_enu_m'] = [round(float(v),2) for v in valid[0]]
                row['exit_point_enu_m'] = [round(float(v),2) for v in valid[-1]]
            row['trajectory_length'] = len(row['trajectory_px'])
        row["ground_contact_points_px"] = row["trajectory_px"]
        row["trajectory_time_offsets_sec"] = (
            [
                round(t - row["timestamp_first"], 3)
                for t in row["trajectory_timestamps_sec"]
            ]
            if "timestamp_first" in row
            else []
        )
        self.closed[key] = row
        self.completed_ids.add(key)


def restore_fact_tails(frame, tracks, limit=30):
    """Build only the tail belonging to this frame, never a later queued frame."""
    views = {}
    for key, view in (frame.active_tracks or {}).items():
        identity = str(key)
        row = (
            tracks.rows.get(identity)
            or tracks.closed.get(identity)
            or tracks.retired.get(identity)
        )
        count = view.trajectory_point_count
        if count and (row is None or len(row["trajectory_px"]) < count):
            raise ValueError("frame references missing trajectory points")
        values = dict(view._values)
        for source, target in TRACK_FIELDS.items():
            if row is None:
                values[source] = ()
                continue
            tail = row[target][max(0, count - limit) : count]
            # The disk tail cache is frozen at ingest, so a tuple needs no plain()
            # walk; only the SQL fallback (a list) still has to be normalised.
            values[source] = tail if type(tail) is tuple else plain(tail)
        views[key] = RenderTrackSnapshot(values)
    mature = frame.mature_tracks
    frame.active_tracks = frame.buffer_tracks = views
    frame.mature_tracks = (
        {key: views[key] for key in mature} if mature is not None else None
    )


def legacy_completed_export(rows, *, thin=True):
    """Keep canonical/v1 regular completion wire geometry compatible after handoff."""
    for row in rows:
        for key, precision in (("trajectory_enu_m", 2), ("trajectory_gcj02", 8)):
            row[key] = [
                [round(float(v), precision) for v in point]
                if point is not None
                else None
                for point in row[key]
            ]
        if not thin:
            continue
        size = len(row["trajectory_px"])
        if size <= 50:
            continue
        indices = list(range(0, size, size // 50))
        timestamps = row["trajectory_timestamps_sec"]
        for key in (*POINT_FIELDS, "ground_contact_points_px"):
            values = row.get(key)
            if isinstance(values, (list, tuple)) and len(values) == size:
                row[key] = [values[i] for i in indices]
        row["trajectory_time_offsets_sec"] = [
            round(t - timestamps[0], 3) for t in row["trajectory_timestamps_sec"]
        ]


def verify_evidence(files, root, expected_kinds=None):
    root = Path(root).resolve()
    if expected_kinds is not None and {f.get("kind") for f in files} != set(
        expected_kinds
    ):
        raise ValueError("evidence original/detector kinds mismatch")
    if len(files) != 2:
        raise ValueError("event requires original and detector evidence")
    for descriptor in files:
        path = (root / descriptor["storage_key"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("evidence path missing/unsafe")
        content = path.read_bytes()
        if (
            len(content) != descriptor["size_bytes"]
            or hashlib.sha256(content).hexdigest() != descriptor["sha256"]
        ):
            raise ValueError("evidence content hash mismatch")


def annotation_snapshot(frame, config, root):
    """Called by the image owner, with the original annotation resize rounding."""
    import cv2
    from utils_local.event_evidence import _store_jpeg

    cfg = config.get("kafka_producer_node", {})
    image = frame.frame
    height, width = image.shape[:2]
    target = int(cfg.get("annotation_snapshot_width", 960))
    if width > target:
        image = cv2.resize(
            image,
            (target, max(1, int(height * target / width))),
            interpolation=cv2.INTER_AREA,
        )
    ok, buffer = cv2.imencode(
        ".jpg",
        image,
        [
            int(cv2.IMWRITE_JPEG_QUALITY),
            int(cfg.get("annotation_snapshot_jpeg_quality", 75)),
        ],
    )
    if not ok:
        raise ValueError("annotation image encoding failed")
    return _store_jpeg(
        root, "annotation_snapshot", buffer.tobytes(), image.shape[1], image.shape[0]
    )


class SnapshotScheduler:
    def __init__(self, config):
        from nodes.KafkaProducerNode import KafkaProducerNode

        self.helper = KafkaProducerNode.__new__(KafkaProducerNode)
        cfg = config.get("kafka_producer_node", {})
        self.helper._capacity_veh_per_min = cfg.get("capacity_veh_per_min", 30.0)
        self.helper._queue_threshold_m = cfg.get("queue_threshold_m", 80.0)
        self.helper._hover_annotation_snapshot_enabled = cfg.get(
            "hover_annotation_snapshot_enabled", True
        )
        self.helper.road_context_status = os.environ.get(
            "ROAD_CONTEXT_STATUS", "missing"
        )
        self.interval = cfg.get("how_often_sec", 1.0)
        self.threshold = cfg.get("event_snapshot_congestion_threshold", 4.0)
        self.samples = cfg.get("event_snapshot_consecutive_samples", 30)
        self.last = None
        self.consecutive = 0
        self.fps = []

    def apply(self, frame):
        now = time.time()
        tick = time.monotonic()
        self.fps.append(tick)
        while len(self.fps) > 2 and self.fps[1] <= tick - 2:
            self.fps.pop(0)
        frame.pipeline_fps = (
            round((len(self.fps) - 1) / (self.fps[-1] - self.fps[0]), 3)
            if len(self.fps) > 1
            else 0.0
        )
        frame.fact_wall_time = now
        frame.annotation_snapshot_requested = False
        if self.last is None or frame.frame_num == 1:
            self.last = now
        if now - self.last > self.interval or self.last == now:
            congestion = self.helper._compute_congestion_index(
                int((frame.info or {}).get("cars_amount") or 0),
                (frame.info or {}).get("roads_activity") or {},
                frame,
            )
            self.consecutive = (
                self.consecutive + 1 if congestion > self.threshold else 0
            )
            frame.annotation_snapshot_requested = (
                self.consecutive == self.samples
                or self.helper._needs_hover_annotation_snapshot(frame)
            )
            self.last = now


def register_event_windows(archive, frame):
    mapping = getattr(frame, "track_id_by_association", None) or {}
    limits = archive.sampling_policy or {}
    before = limits.get("event_before_sec", 5.0)
    after = limits.get("event_after_sec", 5.0)

    def add(identity, start, end):
        archive.event_windows.setdefault(str(identity), []).append(
            (start - before, end + after)
        )

    for event in getattr(frame, "conflict_events", None) or []:
        for key in ("motor_id", "non_motor_id"):
            if event.get(key) is not None:
                value = int(event[key])
                add(mapping.get(value, value), frame.timestamp, frame.timestamp)
    for event in getattr(frame, "enforcement_clues", None) or []:
        if event.get("track_id") is not None:
            add(event["track_id"], frame.timestamp, frame.timestamp)
    for event in getattr(frame, "lane_change_events", None) or []:
        if event.get("track_id") is not None:
            add(
                event["track_id"],
                float(event.get("start_time_sec", frame.timestamp)),
                float(event.get("end_time_sec", frame.timestamp)),
            )


def run_egress(queue, tracker_acks, show_acks, config, root, ready_event=None):
    from nodes.KafkaProducerNode import KafkaProducerNode
    from nodes.GeoJsonExportNode import GeoJsonExportNode

    producer = (
        KafkaProducerNode(config) if config["pipeline"]["send_info_kafka"] else None
    )
    geojson = GeoJsonExportNode(config)
    if (
        producer is not None
        and producer.trajectory_archive is not None
        and producer.trajectory_archive.sampling_policy is not None
    ):
        # GeoJSON is a spatial-only derivative, not the replay/business source.
        geojson.simplify_tolerance_m = (
            min(
                geojson.simplify_tolerance_m,
                producer.trajectory_archive.sampling_policy["enu_error_m"],
            )
            if producer.trajectory_archive.sampling_policy["enabled"]
            else 0.0
        )
    journal = PacketJournal(root)
    tracks = DeltaTracks(root, cache_kib=config["pipeline"].get("egress_sqlite_cache_kib", 16384))
    frames = {}
    renders = {}
    audit_join_times = {}
    committed_watermark = [0]
    ends = {}
    facts_static: dict = {}
    frame_watermarks = {"tracker": 0, "show": 0}
    acknowledgements = {"tracker": tracker_acks, "show": show_acks}
    success = False
    status_at = time.monotonic()
    if producer is not None and producer.trajectory_archive is not None:
        producer.trajectory_archive.spool_root.mkdir(parents=True, exist_ok=True)
    LOG.info(
        "ARCHIVER_READY protocol=1 pid=%s queue_capacity=%s sqlite_cache_kib=%s",
        os.getpid(),
        config["pipeline"].get("egress_queue_maxsize", 32),
        config["pipeline"].get("egress_sqlite_cache_kib", 16384),
    )
    if ready_event is not None:
        ready_event.set()

    def commit_frame(number):
        with stage("egress.commit_frame"):
            return _commit_frame(number)

    def _commit_frame(number):
        frame = frames.pop(number)
        rendered = renders.pop(number)
        with stage("egress.restore_tails", tracks=len(frame.active_tracks or {})):
            restore_fact_tails(frame, tracks)
        if not rendered["ok"]:
            raise RuntimeError(
                "evidence production failed: " + rendered.get("error", "missing")
            )
        storage = os.environ.get("SURVEY_STORAGE_DIR", ".runtime/survey")
        for kind in ("tcc", "enforcement"):
            events = (
                getattr(
                    frame,
                    "conflict_events" if kind == "tcc" else "enforcement_clues",
                    None,
                )
                or []
            )
            files = rendered.get(kind) or []
            if events and producer is not None:
                verify_evidence(
                    files,
                    storage,
                    ("conflict_original_frame", "conflict_detector_frame")
                    if kind == "tcc"
                    else ("enforcement_original_frame", "enforcement_detector_frame"),
                )
                for event in events:
                    event.update(evidence_files=files, evidence_status="complete")
        frame.annotation_snapshot = rendered.get("annotation")
        frame.completed_tracks = [
            tracks.closed.pop(key) for key in frame.egress_closed_ids
        ]
        if (
            producer is None
            or producer.trajectory_archive is None
            or producer.trajectory_archive.sampling_policy is None
        ):
            legacy_completed_export(frame.completed_tracks)
        with stage("egress.geojson"):
            geojson.process(frame)
        if producer is not None:
            archive = producer.trajectory_archive
            if archive is not None:
                register_event_windows(archive, frame)
            with stage("egress.producer", tracks=len(frame.active_tracks or {})):
                producer.process(frame)
            for envelopes, topic in (
                (frame.pending_tcc_envelopes, producer.conflicts_topic),
                (frame.pending_enforcement_envelopes, producer.enforcement_topic),
            ):
                for envelope in envelopes:
                    producer.publisher.publish(topic, envelope, durable=True)
        audit_observe("egress.frame_age", max(0.0, time.time()-frame.timestamp_date)*1000)
        frame.completed_tracks = None
        committed_watermark[0] = number
        audit_join_times.pop(number, None)

    try:
        while True:
            try:
                packet = queue.get(timeout=10)
            except Empty:
                LOG.info(
                    "EGRESS_WAIT watermarks=%s frames=%s renders=%s eof=%s",
                    journal.sequences,
                    len(frames),
                    len(renders),
                    sorted(ends),
                )
                continue
            if time.monotonic() - status_at >= 30:
                LOG.info(
                    "EGRESS_STATUS durable=%s frames=%s joins=%s queue_depth=%s journal_bytes=%s delivery=%s committed=%s",
                    journal.sequences,
                    frame_watermarks,
                    len(frames),
                    queue_depth(queue),
                    journal.stream.tell(),
                    producer._delivery_snapshot() if producer is not None else {},
                    committed_watermark[0],
                )
                status_at = time.monotonic()
            accepted = journal.accept(packet)
            acknowledgements[packet[0]].put(packet[1], timeout=10)
            if accepted is None:
                continue
            kind, data = accepted
            if kind == "points_batch":
                if sum(len(row["arrays"]["trajectory_px"]) for row in data) > 1024:
                    raise ValueError("oversized aggregate point batch")
                with stage("egress.append_points", tracks=len(data)):
                    tracks.append_batch(data)
            elif kind == "close":
                with audit_stage("egress.close_track"):
                    tracks.finish(data)
            elif kind == "discard":
                row = tracks.rows.pop(data["track_id"], None)
                if row is None or len(row["trajectory_px"]) != data["point_count"]:
                    raise ValueError("discard count mismatch")
                tracks.discarded_ids.add(data["track_id"])
                tracks.retired[data["track_id"]] = row
            elif kind == "frame":
                number = int(data.egress_frame_seq)
                if number != frame_watermarks["tracker"] + 1:
                    raise ValueError("tracker frame sequence gap")
                frame_watermarks["tracker"] = number
                if number in frames:
                    raise ValueError("duplicate frame")
                frames[number] = data
            elif kind == "frame_delta":
                number = int(data["frame_seq"])
                if number != frame_watermarks["tracker"] + 1:
                    raise ValueError("tracker frame sequence gap")
                frame_watermarks["tracker"] = number
                if number in frames:
                    raise ValueError("duplicate frame")
                frames[number] = apply_facts_delta(data, facts_static)
            elif kind == "render":
                number = int(data["frame_seq"])
                if number != frame_watermarks["show"] + 1:
                    raise ValueError("show frame sequence gap")
                frame_watermarks["show"] = number
                if number in renders:
                    raise ValueError("duplicate render result")
                renders[number] = data
            elif kind == "eof":
                if packet[0] in ends:
                    raise ValueError("duplicate EOF")
                ends[packet[0]] = data
            elif kind == "abort":
                raise RuntimeError("upstream abort: " + str(data))
            else:
                raise ValueError("unknown egress command")
            if kind in {"frame", "frame_delta", "render"}:
                audit_join_times.setdefault(number, time.monotonic())
            # Respect tracker frame order even when show results race through the queue.
            if len(frames) > int(
                config["pipeline"].get("egress_queue_maxsize", 32)
            ) or len(renders) > int(config["pipeline"].get("egress_queue_maxsize", 32)):
                raise RuntimeError("egress frame/evidence join overflow")
            while frames and min(frames) in renders:
                number = min(frames)
                audit_observe("egress.join_wait", (time.monotonic()-audit_join_times[number])*1000)
                commit_frame(number)
            referenced = {
                str(key)
                for frame in frames.values()
                for key in (frame.active_tracks or {})
            }
            for key in list(tracks.retired):
                if key not in referenced:
                    del tracks.retired[key]
            if len(ends) == 2:
                if (
                    frames
                    or renders
                    or tracks.rows
                    or frame_watermarks["tracker"] != frame_watermarks["show"]
                ):
                    raise ValueError("EOF has unmatched frames or unclosed tracks")
                eof = ends["tracker"]
                flush = FrameElement(
                    str(eof.video_source), None, float(eof.timestamp), 0, {}
                )
                flush.completed_tracks = list(tracks.closed.values())
                tracks.closed = {}
                if (
                    producer is None
                    or producer.trajectory_archive is None
                    or producer.trajectory_archive.sampling_policy is None
                ):
                    legacy_completed_export(flush.completed_tracks, thin=False)
                geojson.process(flush)
                geojson.process(eof)
                if producer is not None:
                    producer.publish_completed_tracks(flush)
                    with stage("egress.seal"):
                        producer.seal_replay_mission(
                            eof, termination_reason=getattr(eof, "termination_reason", "natural_eof")
                        )
                    with stage("egress.drain"):
                        producer.process(eof)
                tracks.disk.commit()
                journal.hashes.db.commit()
                success = True
                LOG.info(
                    "EGRESS_COMPLETE watermarks=%s tracks=%s",
                    journal.sequences,
                    len(tracks.completed_ids),
                )
                return
    except BaseException as error:
        with (journal.root / "incomplete.json").open("w") as f:
            json.dump(
                {
                    "status": "incomplete",
                    "error_type": type(error).__name__,
                    "watermarks": journal.sequences,
                },
                f,
            )
        if producer is not None:
            try:
                producer.mark_replay_mission_incomplete(failure_reason="egress_failed")
            except Exception:
                LOG.exception("EGRESS_INCOMPLETE_PUBLISH_FAILED")
            finally:
                producer.publisher.close(timeout_sec=1.0)
        raise
    finally:
        close_features=getattr(getattr(geojson,'_collected_tracks',None),'close',None)
        if close_features is not None:
            close_features()
        tracks.disk.commit()
        tracks.disk.close()
        journal.close(success)


def mark_failed_pipeline(reason):
    from services.MissionTrajectoryArchive import _atomic_json
    import re

    identity = os.environ.get("PIPELINE_ID") or ("offline-" + str(os.getpid()))
    identity = re.sub(r"[^A-Za-z0-9_.-]", "_", identity)
    directory = (
        Path(os.environ.get("KAFKA_SPOOL_DIR", "output/kafka-spool"))
        / identity
        / "egress"
    )
    if directory.is_dir():
        path = directory / "incomplete.json"
        value = json.loads(path.read_text()) if path.exists() else {}
        value.update(status="incomplete", failure_reason=reason)
        _atomic_json(path, value)
    mission = os.environ.get("MISSION_ID")
    root = os.environ.get("TRAJECTORY_ARCHIVE_SPOOL_DIR")
    if (
        root
        and mission
        and "/" not in mission
        and ".." not in mission
        and "\\" not in mission
    ):
        path = Path(root) / mission / "manifest.json"
        if path.exists():
            manifest = json.loads(path.read_text())
            if manifest.get("status") != "sealed":
                manifest.update(status="incomplete", failure_reason=reason)
                _atomic_json(path, manifest)
