from pathlib import Path
import importlib.util
import json
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "logged_patch", ROOT / "scripts/apply_init_kafka_logged_fix.py"
)
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)


def fixture(tmp_path):
    target = tmp_path / "native"
    package = tmp_path / "patch"
    package.mkdir()
    (target / "app/deploy/intranet").mkdir(parents=True)
    old = b'print("old")\n'
    new = b'print("fixed")\n'
    (target / patch.WRAPPER).write_bytes(old)
    application = (
        json.dumps(
            {"deploy/intranet/run_logged.py": patch.sha(old), "other.py": "f" * 64},
            indent=2,
        )
        + "\n"
    ).encode()
    (target / patch.APPLICATION).write_bytes(application)
    (target / patch.CHECKSUMS).write_text(
        patch.sha(old)
        + "  "
        + patch.WRAPPER
        + "\n"
        + patch.sha(application)
        + "  "
        + patch.APPLICATION
        + "\n"
        + "f" * 64
        + "  app/other.py\n"
    )
    (target / "HOST_RELEASE.json").write_text(
        json.dumps({"version": "2026.11.04.2", "kind": "native-platform-full"})
    )
    original = {name: (target / name).read_bytes() for name in patch.FILES}
    (package / "run_logged.py").write_bytes(new)
    (package / "PATCH.json").write_text(
        json.dumps(
            {
                "id": patch.PATCH_ID,
                "target_version": "2026.11.04.2",
                "replacement_sha256": patch.sha(new),
                "original_sha256": {
                    name: patch.sha(value) for name, value in original.items()
                },
            }
        )
    )
    return target, package, original


def test_exact_patch_updates_both_manifests_and_retains_original_backup(tmp_path):
    target, package, original = fixture(tmp_path)
    assert patch.apply(target, package, check_only=True)["status"] == "applicable"
    assert all(
        (target / name).read_bytes() == value for name, value in original.items()
    )
    result = patch.apply(target, package)
    assert result["status"] == "applied"
    current = patch.checksums((target / patch.CHECKSUMS).read_bytes())
    assert current[patch.WRAPPER] == patch.sha((target / patch.WRAPPER).read_bytes())
    assert current[patch.APPLICATION] == patch.sha(
        (target / patch.APPLICATION).read_bytes()
    )
    assert current["app/other.py"] == "f" * 64
    assert patch.apply(target, package)["status"] == "already_applied"
    for index, name in enumerate(patch.FILES):
        assert (Path(result["backup"]) / f"{index}.original").read_bytes() == original[
            name
        ]


def test_unknown_source_is_rejected_without_rewriting_manifests(tmp_path):
    target, package, original = fixture(tmp_path)
    (target / patch.WRAPPER).write_bytes(b"foreign\n")
    with pytest.raises(ValueError, match="unexpected original"):
        patch.apply(target, package)
    assert (target / patch.CHECKSUMS).read_bytes() == original[patch.CHECKSUMS]
    assert (target / patch.APPLICATION).read_bytes() == original[patch.APPLICATION]


def test_interrupted_write_resumes_only_known_old_or_new_contents(
    tmp_path, monkeypatch
):
    target, package, original = fixture(tmp_path)
    real = patch.atomic

    def interrupt(path, content, mode=0o600):
        real(path, content, mode)
        if path == target / patch.WRAPPER:
            raise OSError("fixture interruption")

    monkeypatch.setattr(patch, "atomic", interrupt)
    with pytest.raises(OSError):
        patch.apply(target, package)
    monkeypatch.setattr(patch, "atomic", real)
    assert patch.apply(target, package)["status"] == "applied"
