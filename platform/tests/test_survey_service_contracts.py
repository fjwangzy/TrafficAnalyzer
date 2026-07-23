import hashlib
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.models.survey import AuditLog, EvidenceItem, SceneAnnotation, SurveyFrame
from app.services.survey_service import SurveyService


class _Scalars:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class _Result:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return _Scalars(self._values)

    def scalar_one_or_none(self):
        return None


class _FakeSession:
    def __init__(self):
        self.objects = {}
        self.added = []
        self.deleted = []

    async def get(self, model, identifier):
        return self.objects.get((model, identifier))

    def add(self, value):
        self.added.append(value)
        identifier = getattr(value, "id", None)
        if identifier is not None:
            self.objects[(type(value), identifier)] = value

    async def flush(self):
        return None

    async def delete(self, value):
        self.deleted.append(value)
        self.objects.pop((type(value), value.id), None)

    async def execute(self, _statement):
        return _Result(
            value
            for (model, _identifier), value in self.objects.items()
            if model is SceneAnnotation
        )


def _server_evidence(path, digest, *, fingerprint=True):
    stat = path.stat()
    metadata = {"asset_key": path.name}
    if fingerprint:
        metadata["source_fingerprint"] = {
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "ctime_ns": stat.st_ctime_ns,
        }
    return EvidenceItem(
        id="EVI-SERVER",
        package_id="EVP-SERVER",
        task_id=None,
        kind="original_video",
        storage_backend="server_asset",
        storage_key=path.name,
        sha256=digest,
        media_type="video/mp4",
        size_bytes=path.stat().st_size,
        item_metadata=metadata,
    )


@pytest.mark.asyncio
async def test_server_asset_status_distinguishes_hash_mismatch_and_missing(tmp_path, monkeypatch):
    source_root = tmp_path / "sources"
    source_root.mkdir()
    source = source_root / "capture.mp4"
    source.write_bytes(b"immutable-source")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(settings, "survey_asset_roots", [str(source_root)])
    monkeypatch.setattr(settings, "survey_storage_dir", str(tmp_path / "managed"))
    session = _FakeSession()
    item = _server_evidence(source, digest)
    session.add(item)
    service = SurveyService(session)

    assert service._evidence_reference_status(item) == "verified"

    source.write_bytes(b"tampered-source")
    assert service._evidence_reference_status(item) == "hash_mismatch"
    with pytest.raises(RuntimeError, match="hash_mismatch"):
        await service.evidence_item(item.id, None, "admin")

    source.unlink()
    assert service._evidence_reference_status(item) == "missing"
    with pytest.raises(RuntimeError, match="missing"):
        await service.evidence_item(item.id, None, "admin")


def test_unchanged_server_asset_uses_persisted_fingerprint_without_rehash(tmp_path, monkeypatch):
    source_root = tmp_path / "sources"
    source_root.mkdir()
    source = source_root / "capture.mp4"
    source.write_bytes(b"immutable-source")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(settings, "survey_asset_roots", [str(source_root)])
    monkeypatch.setattr(settings, "survey_storage_dir", str(tmp_path / "managed"))
    service = SurveyService(_FakeSession())
    item = _server_evidence(source, digest)

    def unexpected_rehash(_path):
        raise AssertionError("unchanged server asset must not be rehashed")

    monkeypatch.setattr("app.services.survey_service.ContentAddressedStore._hash_file", unexpected_rehash)
    assert service._evidence_reference_status(item) == "verified"


@pytest.mark.asyncio
async def test_source_profile_capture_import_resolves_server_asset_paths(tmp_path, monkeypatch):
    source_root = tmp_path / "sources"
    source_root.mkdir()
    video_path = source_root / "capture.mp4"
    telemetry_path = source_root / "telemetry.srt"
    video_path.write_bytes(b"video")
    telemetry_path.write_text("telemetry", encoding="utf-8")
    monkeypatch.setattr(settings, "survey_asset_roots", [str(source_root)])
    monkeypatch.setattr(settings, "survey_storage_dir", str(tmp_path / "managed"))

    class Session(_FakeSession):
        def __init__(self):
            super().__init__()
            self.results = [
                SimpleNamespace(
                    location="capture.mp4", mode="local", enabled=True
                ),
                SimpleNamespace(
                    location="telemetry.srt",
                    mode="local",
                    enabled=True,
                    source_type="srt",
                    config={},
                    validation_status="valid",
                ),
            ]

        async def execute(self, _statement):
            value = self.results.pop(0)

            class Result:
                def scalar_one_or_none(self):
                    return value

            return Result()

    service = SurveyService(Session())

    async def no_prior(_action, _request_id):
        return None

    async def ready_task(_task_id, _actor_id, _role):
        return SimpleNamespace(id="SVY-1", state="ready")

    async def package(_task_id):
        return SimpleNamespace(id="EVP-1")

    captured = {}

    async def enqueue(task, package_value, video, telemetry, *_args, **_kwargs):
        captured.update(
            task=task,
            package=package_value,
            video=video,
            telemetry=telemetry,
        )
        return {"id": "BATCH-1"}

    async def batch_details(_batch):
        return {"id": "BATCH-1", "status": "queued"}

    service._prior = no_prior
    service._task = ready_task
    service._package = package
    service.enqueue_capture_batch = enqueue
    service._batch_details = batch_details
    original_get = service.session.get

    async def get(model, identifier):
        if identifier == "BATCH-1":
            return SimpleNamespace(id="BATCH-1")
        return await original_get(model, identifier)

    service.session.get = get

    result = await service.import_capture_batch(
        "SVY-1",
        None,
        None,
        "SRC-1",
        actor_id=1,
        role="admin",
        request_id="import-source-profile",
    )

    assert result == {"id": "BATCH-1", "status": "queued"}
    assert captured["video"].path == video_path
    assert captured["telemetry"].path == telemetry_path
    assert captured["video"].storage_backend == "server_asset"


@pytest.mark.asyncio
async def test_scene_annotation_full_crud_preserves_revision_and_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "survey_storage_dir", str(tmp_path / "managed"))
    session = _FakeSession()
    frame = SimpleNamespace(id="FRM-1", task_id="SVY-1")
    session.objects[(SurveyFrame, frame.id)] = frame
    service = SurveyService(session)

    async def editable_task(_task_id, _actor_id, _role):
        return SimpleNamespace(id="SVY-1", state="measuring")

    service._task = editable_task
    created = []
    for index, category in enumerate(("车辆", "痕迹", "散落物", "其他对象"), start=1):
        created.append(await service.create_annotation(
            "SVY-1",
            {
                "frame_id": frame.id,
                "category": category,
                "image_geometry": [[index * 10, 20], [index * 10 + 5, 25]],
                "source": "manual",
                "confidence": None,
            },
            actor_id=1,
            role="admin",
            request_id=f"create-{index}",
        ))

    listed = await service.list_annotations("SVY-1", 1, "admin")
    assert {item["category"] for item in listed} == {"车辆", "痕迹", "散落物", "其他对象"}
    assert all(item["revision"] == 1 for item in listed)

    updated = await service.update_annotation(
        "SVY-1",
        created[0]["id"],
        {
            "expected_revision": 1,
            "category": "车辆",
            "image_geometry": [[100, 100], [180, 180]],
            "review_state": "confirmed",
        },
        actor_id=1,
        role="admin",
    )
    assert updated["revision"] == 2
    assert updated["review_state"] == "confirmed"

    with pytest.raises(RuntimeError, match="revision conflict"):
        await service.delete_annotation("SVY-1", created[0]["id"], 1, 1, "admin")
    await service.delete_annotation("SVY-1", created[3]["id"], 1, 1, "admin")
    remaining = await service.list_annotations("SVY-1", 1, "admin")
    assert len(remaining) == 3
    assert {item["category"] for item in remaining} == {"车辆", "痕迹", "散落物"}

    audit_actions = [item.action for item in session.added if isinstance(item, AuditLog)]
    assert audit_actions.count("survey.annotation.created") == 4
    assert "survey.annotation.updated" in audit_actions
    assert "survey.annotation.deleted" in audit_actions
