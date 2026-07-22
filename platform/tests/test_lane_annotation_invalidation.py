import json
from pathlib import Path

from app.services.lane_annotation_store import LaneAnnotationStore


def test_invalidate_all_removes_active_annotations_and_archives_exports(tmp_path):
    db_path = tmp_path / "lane_annotation_db.json"
    export_dir = tmp_path / "lane_annotations"
    export_dir.mkdir()
    export_path = export_dir / "INT-1.json"
    export_path.write_text('{"lanes": {}}', encoding="utf-8")
    db_path.write_text(
        json.dumps(
            {
                "tasks": [{"task_id": "lane-1", "status": "completed"}],
                "annotations": {
                    "INT-1": {
                        "intersection_id": "INT-1",
                        "status": "active",
                        "export_path": str(export_path),
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    store = LaneAnnotationStore(str(db_path))

    result = store.invalidate_all()

    assert result["invalidated_annotations"] == 1
    assert result["invalidated_tasks"] == 1
    assert store.list_annotations() == []
    assert store.list_tasks()[0]["status"] == "invalidated"
    assert not export_path.exists()
    assert len(result["archived_exports"]) == 1
    assert Path(result["archived_exports"][0]).is_file()
    persisted = json.loads(db_path.read_text(encoding="utf-8"))
    assert persisted["annotations"] == {}
    assert persisted["invalidated_annotations"][0]["status"] == "invalidated"


def test_persisted_keyframe_task_retains_registration_context_and_refreshes_idempotently(tmp_path):
    db_path = tmp_path / "lane_annotation_db.json"
    store = LaneAnnotationStore(str(db_path))

    created = store.ensure_task_from_snapshot(
        "INT-1",
        b"jpeg",
        1920,
        1080,
        "FRM-1",
        source_profile_id="SRC-1",
        homography_pixel_to_enu=[[0.1, 0, -10], [0, 0.1, -5], [0, 0, 1]],
    )
    refreshed = store.ensure_task_from_snapshot(
        "INT-1",
        b"new-jpeg-is-not-written-for-the-same-frame",
        1920,
        1080,
        "FRM-1",
        source_profile_id="SRC-2",
        homography_pixel_to_enu=[[0.2, 0, -20], [0, 0.2, -10], [0, 0, 1]],
    )

    assert created["task_id"] == refreshed["task_id"]
    assert refreshed["trigger"] == "persisted_survey_keyframe"
    assert refreshed["source_profile_id"] == "SRC-2"
    assert refreshed["homography_pixel_to_enu"] == [
        [0.2, 0, -20],
        [0, 0.2, -10],
        [0, 0, 1],
    ]
    assert len(store.list_tasks()) == 1
