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
