"""Relations must be final during a running mission without racing open candidates."""

from types import SimpleNamespace
import pytest
from services.MissionTrajectoryArchive import MissionTrajectoryArchive


def segment(track, start, end, x, embedding=(1.0, 0.0)):
    return {
        "track_id": str(track),
        "trajectory_timestamps_sec": [start, end],
        "trajectory_enu_m": [[x, 0], [x + 1, 0]],
        "trajectory_px": [[x * 10, 0], [(x + 1) * 10, 0]],
        "appearance_embedding": list(embedding) if embedding else None,
    }


def resolver(tmp_path):
    from services.StreamingTrajectoryRelations import StreamingRelations

    archive = MissionTrajectoryArchive(tmp_path)
    sent = []
    return StreamingRelations(
        archive, "M1", lambda p, s, e: sent.append((p, s, e))
    ), sent


def test_links_are_ready_without_eof_and_are_published_once(tmp_path):
    r, sent = resolver(tmp_path)
    r.closed(segment("a", 0, 1, 0))
    r.closed(segment("b", 1.5, 2, 1.2))
    r.observe([], source_time=4)
    r.process_once()
    assert [(p, s) for p, s, e in sent] == [("a", "b")]
    r.process_once()
    assert len(sent) == 1


def test_open_alternative_prevents_premature_identity_freeze(tmp_path):
    r, sent = resolver(tmp_path)
    r.closed(segment("a", 0, 1, 0))
    r.closed(segment("b", 1.5, 2, 1.2))
    r.observe(
        [SimpleNamespace(id="c", timestamp_first=1.6, timestamp_last=4)], source_time=4
    )
    r.process_once()
    assert not sent
    r.closed(segment("c", 1.6, 4, 1.2))
    r.observe([], source_time=7)
    r.process_once()
    assert not sent  # ambiguous equal appearances and motion


def test_missing_appearance_never_merges_on_motion_only(tmp_path):
    r, sent = resolver(tmp_path)
    r.closed(segment("a", 0, 1, 0, None))
    r.closed(segment("b", 1.5, 2, 1.2, None))
    r.observe([], source_time=4)
    r.process_once()
    assert not sent


def test_no_link_before_source_window_closes(tmp_path):
    r, sent = resolver(tmp_path)
    r.closed(segment("a", 0, 1, 0))
    r.closed(segment("b", 1.5, 2, 1.2))
    r.observe([], source_time=2)
    r.process_once()
    assert not sent
    r.observe([], source_time=3.1)
    r.process_once()
    assert len(sent) == 1


def test_restart_recovers_candidates_and_immutable_relation_outbox(tmp_path):
    r, sent = resolver(tmp_path)
    r.closed(segment("a", 0, 1, 0))
    r.closed(segment("b", 1.5, 2, 1.2))
    r.observe([], source_time=4)
    restarted, new_sent = resolver(tmp_path)
    restarted.process_once()
    assert len(new_sent) == 1
