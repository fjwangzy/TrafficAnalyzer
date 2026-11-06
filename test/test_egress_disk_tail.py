"""Regression for the .2 disk receiver, not the already-fast sender benchmark."""

from types import SimpleNamespace

import pytest

from elements.RenderSnapshot import RenderTrackSnapshot
from services.PipelineEgress import DeltaTracks, POINT_FIELDS, restore_fact_tails
from services.TrajectorySpoolIndex import DiskArray, connection


def point_row(key, start, count=1):
    arrays = {}
    for field in POINT_FIELDS:
        arrays[field] = [
            {"frame": i, "nested": [i]} if field == "point_quality_lineage"
            else i if field == "trajectory_frame_nums"
            else i * .04 if field == "trajectory_timestamps_sec"
            else None if field in {"trajectory_enu_m", "trajectory_gcj02"} and i % 3 == 0
            else [float(i), float(i + 1)]
            for i in range(start, start + count)
        ]
    return {"track_id": str(key), "start": start, "arrays": arrays}


def test_real_receiver_restores_recent_frame_without_sql(tmp_path):
    store = DeltaTracks(tmp_path)
    try:
        for n in range(160):
            for key in range(5):
                store.append(point_row(key, n))
        sql = []
        store.disk.set_trace_callback(sql.append)
        frame = SimpleNamespace(
            active_tracks={key: RenderTrackSnapshot({"trajectory_point_count": 145}) for key in range(5)},
            mature_tracks=None,
        )
        restore_fact_tails(frame, store)
        assert frame.active_tracks[0].trajectory_frame_nums == tuple(range(115, 145))
        assert not [s for s in sql if s.startswith("SELECT")], "recent frame restoration must not query per vehicle/field"
    finally:
        store.disk.close()


def test_cache_bounds_fallback_and_no_shared_values(tmp_path):
    db = connection(tmp_path)
    try:
        a = DiskArray(db, "a", "points")
        values = [{"x": (n, n + 1), "quality": [n]} for n in range(300)]
        a.extend(values)
        values[-1]["quality"][0] = -1
        sql = []
        db.set_trace_callback(sql.append)
        tail = a[-30:]
        # Tail values are frozen once at ingest: coordinates are tuples, and the
        # cache hands out a fresh dict shell so consumers cannot rebind into it.
        assert tail[-1] == {"x": (299, 300), "quality": (299,)}
        assert isinstance(tail, tuple)
        tail[-1]["quality"] = (-2,)
        assert a[-1]["quality"] == (299,)
        assert not sql
        assert a[:5] == [{"x": [n, n + 1], "quality": [n]} for n in range(5)]
        assert any(s.startswith("SELECT") for s in sql)
        assert len(a._tail) <= 128
        assert a[120:200] == list(a)[120:200]
        assert a[::-3] == list(a)[::-3]
        with pytest.raises(IndexError):
            _ = a[-301]
    finally:
        db.close()


def test_cached_tail_matches_plain_contract(tmp_path):
    """A frozen tail slice must equal plain() of the rows it was built from."""
    from services.PipelineEgress import plain

    store = DeltaTracks(tmp_path)
    try:
        rows = [point_row(key, n) for n in range(40) for key in (0, 1)]
        for row in rows:
            store.append(row)
        frame = SimpleNamespace(
            active_tracks={key: RenderTrackSnapshot({"trajectory_point_count": 40}) for key in (0, 1)},
            mature_tracks=None,
        )
        restore_fact_tails(frame, store)
        for key in (0, 1):
            values = frame.active_tracks[key]._values
            expected = {
                field: tuple(plain(row["arrays"][field])[0] for row in rows if row["track_id"] == str(key))
                for field in POINT_FIELDS
            }
            for field in POINT_FIELDS:
                got = values[{"trajectory_bbox_center_px": "trajectory_points", "trajectory_px": "ground_contact_points_px"}.get(field, field)]
                assert got == tuple(expected[field][-30:]), field
                assert isinstance(got, tuple) and all(not isinstance(item, list) for item in got)
    finally:
        store.disk.close()


def test_batch_validation_and_full_archive_equivalence(tmp_path):
    store = DeltaTracks(tmp_path)
    try:
        store.append_batch([point_row("a", 0, 80), point_row("b", 0, 80)])
        store.append_batch([point_row("a", 80, 80), point_row("a", 160, 40)])
        expected = point_row("a", 0, 200)["arrays"]
        assert {field: list(store.rows["a"][field]) for field in POINT_FIELDS} == expected
        invalid = point_row("a", 201)
        with pytest.raises(ValueError, match="sequence gap"):
            store.append_batch([point_row("a", 200), invalid, point_row("a", 201)])
        assert len(store.rows["a"]["trajectory_px"]) == 200
        assert list(store.rows["a"]["trajectory_frame_nums"]) == list(range(200))
        store.finish({"track_id": "a", "point_count": 200, "metadata": {"track_id": "a"}})
        assert all(store.closed["a"][field] == expected[field] for field in POINT_FIELDS)
        with pytest.raises(ValueError, match="closed"):
            store.append_batch([point_row("a", 200)])
    finally:
        store.disk.close()


def test_failed_sql_batch_leaves_disk_counts_and_cache_unchanged(tmp_path):
    store = DeltaTracks(tmp_path)
    try:
        store.append(point_row("a", 0))
        store.disk.execute("CREATE TRIGGER reject_b BEFORE INSERT ON arrays WHEN NEW.track='b' BEGIN SELECT RAISE(ABORT, 'fixture rejection'); END")
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError, match="fixture rejection"):
            store.append_batch([point_row("a", 1), point_row("b", 0)])
        assert set(store.rows) == {"a"}
        assert len(store.rows["a"]["trajectory_px"]) == 1
        assert list(store.rows["a"]["trajectory_frame_nums"]) == [0]
        assert store.rows["a"]["trajectory_frame_nums"][-1] == 0
    finally:
        store.disk.close()


def test_sqlite_cache_budget_preserves_durability_settings(tmp_path):
    for budget in (2048, 16384):
        db = connection(tmp_path/str(budget), cache_kib=budget)
        try:
            assert db.execute('PRAGMA cache_size').fetchone()[0] == -budget
            assert db.execute('PRAGMA synchronous').fetchone()[0] == 2
            assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
            assert db.execute('PRAGMA cache_spill').fetchone()[0] > 0
        finally:
            db.close()
    for invalid in (0, -1, 65537, True, '16384'):
        with pytest.raises(ValueError, match='cache budget'):
            connection(tmp_path/'invalid', cache_kib=invalid)
