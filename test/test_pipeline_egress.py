import hashlib
import json
import multiprocessing as mp
import pickle
from pathlib import Path
from queue import Queue
import time
import numpy as np
import pytest
from elements.FrameElement import FrameElement
from elements.TrackElement import TrackElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from services.PipelineEgress import (
    PacketJournal,
    DeltaTracks,
    EgressClient,
    freeze_frame,
    run_egress,
    verify_evidence,
    POINT_FIELDS,
)


def frame(count=500):
    f = FrameElement("fixture", np.zeros((20, 20, 3), np.uint8), 1.0, 1, {})
    t = TrackElement(1, 0.0)
    for i in range(count):
        t.trajectory_points.append((float(i), float(i + 1)))
        t.ground_contact_points_px.append((float(i), float(i + 2)))
        t.trajectory_timestamps_sec.append(i * 0.1)
        t.trajectory_frame_nums.append(i)
        t.trajectory_enu_m.append((i * 0.01, 0.0))
        t.trajectory_gcj02.append((117.0 + i * 0.00001, 36.0))
        t.point_quality_lineage.append({"tracking_quality": "verified", "frame_num": i})
    t.class_id_history = list(range(count))
    t.appearance_crop_jpeg = "crop" * 100
    t.trajectory_output_eligible = True
    f.active_tracks = f.buffer_tracks = f.mature_tracks = {1: t}
    return f


def packet(role, seq, kind, data):
    body = pickle.dumps((kind, data), protocol=pickle.HIGHEST_PROTOCOL)
    return role, seq, hashlib.sha256(body).hexdigest(), body


def test_render_snapshot_is_owned_bounded_immutable_and_does_not_contain_pixels():
    source = frame(3000)
    source.frame = None
    frozen = freeze_frame(source)
    assert frozen.frame is None and frozen.frame_result is None
    assert frozen.buffer_tracks is frozen.active_tracks
    t = frozen.active_tracks[1]
    assert len(t.trajectory_points) == 30 and t.trajectory_point_count == 3000
    assert t.class_id_history == () and t.appearance_crop_jpeg is None
    with pytest.raises(AttributeError):
        t.id = 2
    before = t.trajectory_points
    source.active_tracks[1].trajectory_points.append((9999.0, 9999.0))
    assert t.trajectory_points == before
    assert len(pickle.dumps(frozen)) < len(pickle.dumps(source)) * 0.1
    restored = pickle.loads(pickle.dumps(frozen))
    assert restored.active_tracks[1].trajectory_points == before


def test_journal_identity_gap_and_hash_validation(tmp_path):
    journal = PacketJournal(tmp_path)
    p = packet("tracker", 1, "points_batch", [])
    assert journal.accept(p) == ("points_batch", [])
    size = journal.path.stat().st_size
    assert journal.accept(p) is None and journal.path.stat().st_size == size
    with pytest.raises(ValueError, match="identity"):
        journal.accept(packet("tracker", 1, "points_batch", [1]))
    with pytest.raises(ValueError, match="gap"):
        journal.accept(packet("tracker", 3, "eof", None))
    corrupt = (*p[:3], p[3] + b"x")
    with pytest.raises(ValueError, match="hash"):
        journal.accept(corrupt)
    journal.close(False)
    assert journal.path.exists()


def test_disk_error_is_not_acknowledged(tmp_path, monkeypatch):
    journal = PacketJournal(tmp_path)

    def fail():
        raise OSError("disk full")

    monkeypatch.setattr(journal.stream, "flush", fail)
    with pytest.raises(OSError):
        journal.accept(packet("tracker", 1, "eof", None))
    assert journal.sequences == {}
    monkeypatch.undo()
    journal.close(False)


def test_delta_gap_alignment_and_close_counts():
    store = DeltaTracks()
    arrays = {k: [0] for k in POINT_FIELDS}
    arrays["trajectory_timestamps_sec"] = [0.1]
    for key in (
        "trajectory_bbox_center_px",
        "trajectory_px",
        "trajectory_enu_m",
        "trajectory_gcj02",
    ):
        arrays[key] = [[0.0, 0.0]]
    store.append({"track_id": "1", "start": 0, "arrays": arrays})
    with pytest.raises(ValueError, match="sequence"):
        store.append({"track_id": "1", "start": 3, "arrays": arrays})
    with pytest.raises(ValueError, match="count"):
        store.finish({"track_id": "1", "point_count": 2, "metadata": {}})


def test_source_batches_at_most_1024_points_and_does_not_send_full_histories(tmp_path):
    journal = PacketJournal(tmp_path)
    acks = Queue()
    received = []

    class Sink:
        def put(self, p, timeout):
            received.append(journal.accept(p))
            acks.put(p[1])

    client = EgressClient("tracker", Sink(), acks)
    source = frame(2500)
    client.frame(source)
    point_packets = [v for k, v in received if k == "points_batch"]
    assert all(
        sum(len(row["arrays"]["trajectory_px"]) for row in rows) <= 1024
        for rows in point_packets
    )
    assert (
        sum(
            len(row["arrays"]["trajectory_px"])
            for rows in point_packets
            for row in rows
        )
        == 2500
    )
    received.clear()
    source.frame_num = 2
    client.frame(source)
    assert not any(k == "points_batch" for k, v in received)
    assert client.confirmed == client.sequence
    journal.close(False)


def test_evidence_validation_rejects_missing_hash_and_traversal(tmp_path):
    data = b"image"
    p = tmp_path / "a"
    p.write_bytes(data)
    reference = {
        "storage_key": "a",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }
    verify_evidence([reference, reference], tmp_path)
    with pytest.raises(ValueError, match="hash"):
        verify_evidence([{**reference, "sha256": "0" * 64}, reference], tmp_path)
    with pytest.raises(ValueError, match="unsafe"):
        verify_evidence([{**reference, "storage_key": "../a"}, reference], tmp_path)


def _writer(queue, ta, sa, config, root):
    run_egress(queue, ta, sa, config, root)


def test_real_writer_waits_for_both_eofs_and_preserves_failed_journal(tmp_path):
    context = mp.get_context("spawn")
    queue = context.Queue(32)
    ta = context.Queue()
    sa = context.Queue()
    config = {
        "pipeline": {"send_info_kafka": False},
        "geojson_export": {"enabled": False, "output_dir": str(tmp_path / "geo")},
    }
    child = context.Process(
        target=_writer, args=(queue, ta, sa, config, str(tmp_path / "journal"))
    )
    child.start()
    try:
        tracker = EgressClient("tracker", queue, ta)
        show = EgressClient("show", queue, sa)
        tracker.frame(frame(3))
        show.send("render", {"frame_seq": 1, "ok": True})
        tracker.finish(VideoEndBreakElement("fixture", 1.0))
        time.sleep(0.1)
        assert child.is_alive(), "writer must not finish before image EOF"
        show.send("eof", VideoEndBreakElement("fixture", 1.0))
        show.wait()
        child.join(15)
        assert child.exitcode == 0
        assert not (tmp_path / "journal/pending.packets").exists()
    finally:
        if child.is_alive():
            child.terminate()
            child.join(5)
        queue.close()
        ta.close()
        sa.close()


def test_full_queue_and_stale_ack_fail_instead_of_losing_points():
    from queue import Full

    class FullQueue:
        def put(self, *args, **kwargs):
            raise Full

    client = EgressClient("tracker", FullQueue(), Queue(), timeout=0.01)
    with pytest.raises(TimeoutError, match="full"):
        client.send("eof", None)
    client = EgressClient("tracker", Queue(), Queue(), timeout=0.01)
    client.sequence = 1
    client.pending = {1: time.monotonic() - 1}
    client.last_ack = time.monotonic() - 1
    with pytest.raises(TimeoutError, match="ACK"):
        client.drain()


def test_dead_writer_and_wrong_producer_role_are_rejected(tmp_path):
    client = EgressClient("tracker", Queue(), Queue(), alive=lambda: False)
    with pytest.raises(RuntimeError, match="died"):
        client.send("frame", None)
    journal = PacketJournal(tmp_path)
    with pytest.raises(ValueError, match="role"):
        journal.accept(packet("show", 1, "points_batch", []))
    assert journal.sequences == {}
    journal.close(False)


def test_annotation_artifact_matches_old_encoder_rounding(tmp_path):
    from services.PipelineEgress import annotation_snapshot
    from nodes.KafkaProducerNode import KafkaProducerNode
    import base64

    f = FrameElement(
        "fixture",
        np.random.default_rng(20).integers(0, 255, (722, 1280, 3), dtype=np.uint8),
        0.0,
        1,
        {},
    )
    producer = KafkaProducerNode.__new__(KafkaProducerNode)
    producer._snapshot_width = 960
    producer._snapshot_jpeg_quality = 75
    original = producer._encode_annotation_snapshot(f)
    descriptor = annotation_snapshot(f, {}, tmp_path)
    assert descriptor["height"] == original["annotation_snapshot_height"]
    assert (tmp_path / descriptor["storage_key"]).read_bytes() == base64.b64decode(
        original["annotation_snapshot_jpeg"]
    )


def test_v2_rollback_is_blocked_for_an_old_consumer(monkeypatch, tmp_path):
    import importlib.util
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "deploy/host-platform"))
    spec = importlib.util.spec_from_file_location(
        "native_guard", root / "deploy/native-platform/native_platform.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "sampling-v2.active").write_text("event-faithful/v2")
    state = {
        "environment": {"TRAJECTORY_ARCHIVE_SPOOL_DIR": str(tmp_path)},
        "previous_platform_running": True,
    }
    monkeypatch.setattr(
        module,
        "stop",
        lambda: pytest.fail("must reject downgrade before stopping the new consumer"),
    )
    with pytest.raises(ValueError, match="DATA_CONTRACT_DOWNGRADE"):
        module.restore(state)


def test_event_windows_keep_association_and_stable_identity_domains_separate():
    from services.PipelineEgress import register_event_windows
    from types import SimpleNamespace

    archive = SimpleNamespace(
        sampling_policy={"event_before_sec": 2.0, "event_after_sec": 3.0},
        event_windows={},
    )
    f = frame(1)
    f.timestamp = 5.0
    f.track_id_by_association = {1: 101, 2: 202, 101: 901}
    f.conflict_events = [{"motor_id": 1, "non_motor_id": 2}]
    f.enforcement_clues = [{"track_id": "101"}]
    f.lane_change_events = [
        {"track_id": 101, "start_time_sec": 3.0, "end_time_sec": 4.0}
    ]
    register_event_windows(archive, f)
    assert "901" not in archive.event_windows
    assert archive.event_windows["101"] == [(3.0, 8.0), (3.0, 8.0), (1.0, 7.0)]
    assert archive.event_windows["202"] == [(3.0, 8.0)]


def test_missing_render_at_eof_fails_and_keeps_pending_packets(tmp_path):
    context = mp.get_context("spawn")
    queue = context.Queue(32)
    ta = context.Queue()
    sa = context.Queue()
    config = {
        "pipeline": {"send_info_kafka": False},
        "geojson_export": {"enabled": False, "output_dir": str(tmp_path / "geo")},
    }
    child = context.Process(
        target=_writer, args=(queue, ta, sa, config, str(tmp_path / "journal"))
    )
    child.start()
    try:
        tracker = EgressClient("tracker", queue, ta)
        show = EgressClient("show", queue, sa)
        tracker.frame(frame(3))
        tracker.finish(VideoEndBreakElement("fixture", 1.0))
        show.send("eof", VideoEndBreakElement("fixture", 1.0))
        show.wait()
        child.join(15)
        assert child.exitcode != 0 and child.exitcode is not None
        assert (tmp_path / "journal/pending.packets").exists()
        assert (
            json.loads((tmp_path / "journal/incomplete.json").read_text())["status"]
            == "incomplete"
        )
    finally:
        if child.is_alive():
            child.kill()
            child.join(5)
        queue.close()
        ta.close()
        sa.close()


def test_failed_enqueue_retains_unconfirmed_bytes_and_releases_confirmed(tmp_path):
    import struct
    from queue import Full

    queue = Queue()
    acks = Queue()
    client = EgressClient("tracker", queue, acks, failure_spool=tmp_path)
    client.send("frame", "durably accepted")
    accepted = queue.get()
    acks.put(accepted[1])
    client.drain()
    assert not client.unconfirmed_packets

    class FullQueue:
        def put(self, *args, **kwargs):
            raise Full

    client.queue = FullQueue()
    with pytest.raises(TimeoutError, match="full"):
        client.send("points_batch", [{"new_observation": 4}])
    (path,) = tmp_path.glob("unconfirmed-tracker-*.packets")
    assert path.stat().st_mode & 0o777 == 0o600
    encoded = path.read_bytes()
    (length,) = struct.unpack("!Q", encoded[:8])
    restored = pickle.loads(encoded[8 : 8 + length])
    assert restored[1] == 2
    assert hashlib.sha256(restored[3]).hexdigest() == restored[2]
    assert pickle.loads(restored[3]) == ("points_batch", [{"new_observation": 4}])
    client.preserve_pending()
    assert len(list(tmp_path.glob("*.packets"))) == 1


def test_ack_wait_failure_retains_pending_packet_without_realtime_file_io(tmp_path):
    client = EgressClient(
        "show", Queue(), Queue(), timeout=0.01, failure_spool=tmp_path
    )
    client.send("render", {"frame_seq": 1, "ok": True})
    assert not tmp_path.exists() or not list(tmp_path.iterdir())
    client.last_ack = time.monotonic() - 1
    with pytest.raises(TimeoutError, match="ACK"):
        client.wait()
    assert len(list(tmp_path.glob("unconfirmed-show-*.packets"))) == 1


def test_parent_rejects_final_writer_failure_after_other_workers_finished(
    monkeypatch, tmp_path
):
    import main_optimized
    import utils_local.pipeline_processes

    class FinishedProcess:
        def __init__(self, *, target, args, name, daemon):
            self.args = args
            self.name = name
            self.pid = 1
            self.exitcode = 7 if name == "proc_egress" else 0

        def start(self):
            if self.name == "proc_egress":
                (tmp_path / "final-failure/egress").mkdir(parents=True)
                self.args[-1].set()

        def join(self, timeout=None):
            pass

    monkeypatch.setattr(main_optimized, "Process", FinishedProcess)
    monkeypatch.setattr(main_optimized.signal, "signal", lambda *args: None)
    monkeypatch.setattr(
        utils_local.pipeline_processes, "cleanup_frame_segments", lambda *args: None
    )
    monkeypatch.setenv("KAFKA_SPOOL_DIR", str(tmp_path))
    monkeypatch.setenv("PIPELINE_ID", "final-failure")
    monkeypatch.setenv("PIPELINE_EGRESS_ENABLED", "false")
    monkeypatch.setenv("HISTORY_SAMPLING_ENABLED", "false")
    with pytest.raises(SystemExit) as error:
        main_optimized.main.__wrapped__({"pipeline": {"egress_enabled": True}})
    assert error.value.code == 1
    manifest = json.loads(
        (tmp_path / "final-failure/egress/incomplete.json").read_text()
    )
    assert manifest["status"] == "incomplete"


def test_unconfirmed_wire_memory_has_a_hard_packet_bound():
    client=EgressClient('tracker',Queue(),Queue(),timeout=.02)
    for i in range(32):client.send('frame',{'frame':i})
    assert len(client.unconfirmed_packets)==32
    with pytest.raises(TimeoutError,match='ACK'):
        client.send('frame',{'frame':32})
    assert len(client.unconfirmed_packets)==32 and client.sequence==32
