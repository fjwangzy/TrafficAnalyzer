import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "purge_adr019_legacy_storage.py"
SPEC = importlib.util.spec_from_file_location("purge_adr019_legacy_storage", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

CONFIRMATION = module.CONFIRMATION
FIXED_BIND_ALLOWLIST = module.FIXED_BIND_ALLOWLIST
FIXED_VOLUME_ALLOWLIST = module.FIXED_VOLUME_ALLOWLIST
load_manifest = module.load_manifest
purge = module.purge
record_manifest = module.record_manifest


def test_retention_manifest_uses_exact_allowlist_and_seven_days(tmp_path: Path):
    now = datetime(2026, 7, 16, tzinfo=UTC)
    path = tmp_path / "retention.json"
    manifest = record_manifest(path, now)

    assert set(manifest["volumes"]) == FIXED_VOLUME_ALLOWLIST
    assert set(manifest["bind_paths"]) == FIXED_BIND_ALLOWLIST
    assert load_manifest(path) == manifest
    assert datetime.fromisoformat(manifest["purge_after"].replace("Z", "+00:00")) == now + timedelta(days=7)


def test_purge_refuses_without_explicit_environment_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "retention.json"
    record_manifest(path, datetime(2026, 7, 1, tzinfo=UTC))
    monkeypatch.delenv("ALLOW_ADR019_LEGACY_PURGE", raising=False)

    with pytest.raises(RuntimeError, match="ALLOW_ADR019_LEGACY_PURGE"):
        purge(path, CONFIRMATION, datetime(2026, 7, 10, tzinfo=UTC))


def test_purge_refuses_before_expiry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    retired_at = datetime(2026, 7, 16, tzinfo=UTC)
    path = tmp_path / "retention.json"
    record_manifest(path, retired_at)
    monkeypatch.setenv("ALLOW_ADR019_LEGACY_PURGE", "1")

    with pytest.raises(RuntimeError, match="seven-day retention"):
        purge(path, CONFIRMATION, retired_at + timedelta(days=6, hours=23))


def test_purge_refuses_wrong_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    retired_at = datetime(2026, 7, 1, tzinfo=UTC)
    path = tmp_path / "retention.json"
    record_manifest(path, retired_at)
    monkeypatch.setenv("ALLOW_ADR019_LEGACY_PURGE", "1")

    with pytest.raises(RuntimeError, match="--confirm"):
        purge(path, "WRONG_CONFIRMATION", retired_at + timedelta(days=8))


def test_purge_refuses_mounted_allowlisted_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    retired_at = datetime(2026, 7, 1, tzinfo=UTC)
    path = tmp_path / "retention.json"
    record_manifest(path, retired_at)
    monkeypatch.setenv("ALLOW_ADR019_LEGACY_PURGE", "1")
    mounted = next(iter(FIXED_VOLUME_ALLOWLIST))
    monkeypatch.setattr(module, "_mounted_sources", lambda: {mounted})

    with pytest.raises(RuntimeError, match="mounted legacy storage"):
        purge(path, CONFIRMATION, retired_at + timedelta(days=8))


def test_manifest_rejects_tampered_allowlist(tmp_path: Path):
    path = tmp_path / "retention.json"
    manifest = record_manifest(path, datetime(2026, 7, 1, tzinfo=UTC))
    manifest["volumes"].append("unexpected_volume")
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RuntimeError, match="fixed allowlist"):
        load_manifest(path)
