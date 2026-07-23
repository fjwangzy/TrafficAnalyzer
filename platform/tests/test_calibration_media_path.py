from pathlib import Path

from app.api.v1 import calibration


def test_relative_registered_media_is_resolved_from_repository_root(monkeypatch):
    repository_root = Path(calibration.__file__).resolve().parents[4]
    monkeypatch.chdir(repository_root / "platform")
    monkeypatch.setattr(calibration.settings, "calibration_media_roots", ["test_videos"])

    result = calibration._calibration_media_path(
        "test_videos/inter_xqh/telemetry.srt",
        field="telemetry_location",
    )

    assert result == repository_root / "test_videos/inter_xqh/telemetry.srt"
