import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from utils_local.kafka_security import kafka_security_options


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, Path(path))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


release = module("scripts/build_intranet_release.py", "intranet_release")
deployment = module("deploy/intranet/deploy.py", "intranet_deployment")


def test_offline_build_accepts_arm_headers_and_rejects_existing_x86_driver(tmp_path):
    with pytest.raises(ValueError, match="Missing aarch64"):
        release.validate_driver(tmp_path)
    with pytest.raises(ValueError, match="Non-aarch64"):
        release.validate_driver(Path("deploy/highgo-reference/tools/highgo-psycopg2/x86_64"))
    header = bytearray(20)
    header[:4] = b"\x7fELF"
    header[5] = 1
    header[18:20] = (183).to_bytes(2, "little")
    (tmp_path / "libpq.so.5").write_bytes(header)
    assert list(release.validate_driver(tmp_path)) == ["libpq.so.5"]
    header[18:20] = (62).to_bytes(2, "little")
    (tmp_path / "libpq.so.5").write_bytes(header)
    with pytest.raises(ValueError, match="Non-aarch64"):
        release.validate_driver(tmp_path)
    with pytest.raises(ValueError, match="immutable"):
        release.pinned_reference("cann:latest")


def test_source_archive_cannot_pass_as_runnable_offline_delivery(tmp_path):
    (tmp_path / "RELEASE.json").write_text(json.dumps({"kind": "source-preparation-only"}))
    (tmp_path / "SHA256SUMS").write_text(f"{release.digest(tmp_path / 'RELEASE.json')}  RELEASE.json\n")
    with pytest.raises(RuntimeError, match="source preparation"):
        deployment.verify_files(tmp_path)
    (tmp_path / "RELEASE.json").write_text("tampered")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        deployment.verify_files(tmp_path)


@pytest.mark.parametrize("valid_image", [True, False])
def test_application_rollback_checks_images_and_never_runs_initialization(tmp_path, monkeypatch, valid_image):
    import sys

    previous = tmp_path / "previous"
    previous.mkdir()
    environment = tmp_path / ".env"
    environment.write_text("fixture-only")
    environment.chmod(0o600)
    images = {service: {"reference": f"fixture/{service}:previous", "id": f"sha256:{service}"}
              for service in ("platform", "console")}
    monkeypatch.setattr(deployment, "ROOT", tmp_path)
    monkeypatch.setattr(deployment, "verify_files", lambda root=None: {"single_compose": True, "images": images})
    monkeypatch.setattr(sys, "argv", ["deploy.py", "rollback", "--previous-dir", str(previous)])
    commands = []

    def run(command, **kwargs):
        commands.append((command, kwargs))
        if "inspect" in command:
            item = next(row for row in images.values() if row["reference"] == command[-1])
            return SimpleNamespace(stdout=json.dumps([{"Id": item["id"] if valid_image else "wrong", "Architecture": "arm64"}]))
        return SimpleNamespace(stdout=json.dumps({"services": {}}))

    monkeypatch.setattr(deployment.subprocess, "run", run)
    if not valid_image:
        with pytest.raises(RuntimeError, match="Previous image"):
            deployment.main()
        assert not any("up" in command for command, _ in commands)
        return
    deployment.main()
    command, options = commands[-1]
    assert command[-2:] == ["platform", "console2"] and "--no-deps" in command
    assert "init-db" not in command and "run" not in command and "--no-build" in command
    assert options["env"]["PLATFORM_IMAGE"] == images["platform"]["reference"]


def test_cann_build_is_blocked_before_large_pull_when_docker_storage_is_full(monkeypatch):
    commands = []

    def run(*arguments, capture=False):
        commands.append(arguments)
        return "Filesystem 1024-blocks Used Available Capacity Mounted on\noverlay 131000000 120000000 6000000 95% /\n" if capture else None

    monkeypatch.setattr(release, "run", run)
    monkeypatch.setattr(release, "ensure_base_image", lambda reference: None)
    with pytest.raises(ValueError, match="60 GiB free"):
        release.require_builder_space("nginx@sha256:" + "a" * 64)
    assert not any("cann" in str(command) for command in commands)


@pytest.mark.parametrize("cached", [True, False])
def test_pinned_base_is_verified_locally_and_only_missing_image_is_pulled(monkeypatch, cached):
    import subprocess
    inspected, pulled = [], []
    def inspect(reference):
        inspected.append(reference)
        if not cached and len(inspected) == 1:
            raise subprocess.CalledProcessError(1, "docker image inspect")
        return {"architecture": "arm64"}
    monkeypatch.setattr(release, "inspect_image", inspect)
    monkeypatch.setattr(release, "run", lambda *args: pulled.append(args))
    reference = "fixture@sha256:" + "a" * 64
    release.ensure_base_image(reference)
    assert inspected == [reference] * (1 if cached else 2)
    assert pulled == ([] if cached else [("docker", "pull", "--platform", "linux/arm64", reference)])


def test_wrong_architecture_is_never_replaced_or_accepted_as_cached(monkeypatch):
    monkeypatch.setattr(release, "inspect_image", lambda reference: (_ for _ in ()).throw(ValueError("Image must be linux/arm64")))
    monkeypatch.setattr(release, "run", lambda *args: pytest.fail("Do not hide an architecture mismatch"))
    with pytest.raises(ValueError, match="linux/arm64"):
        release.ensure_base_image("fixture@sha256:" + "a" * 64)


def test_archive_is_private_before_first_byte_and_env_remains_editable(tmp_path, monkeypatch):
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    (delivery / ".env").write_text("fixture-password")
    (delivery / "README.md").write_text("fixture")
    original = release.tarfile.open

    def checked(path, *args, **kwargs):
        assert path.stat().st_mode & 0o777 == 0o600
        return original(path, *args, **kwargs)

    monkeypatch.setattr(release.tarfile, "open", checked)
    archive = tmp_path / "delivery.tar.gz"
    release.seal_archive(delivery, archive, mutable=(".env",))
    assert archive.stat().st_mode & 0o777 == 0o600
    assert ".env" not in (delivery / "SHA256SUMS").read_text()


def test_package_rejects_images_that_failed_application_validation(tmp_path, monkeypatch):
    from utils_local import ascend_model_manifest

    monkeypatch.setattr(ascend_model_manifest, "load_manifest", lambda _: ({}, tmp_path))
    (tmp_path / "build-unverified.json").write_text(json.dumps({"validation_status": "failed"}))
    with pytest.raises(ValueError, match="application-import checks"):
        release.package(SimpleNamespace(output=tmp_path, version="unverified", model_manifest=tmp_path / "manifest.json"))
    assert not list(tmp_path.glob("*.tar.gz"))


def test_full_package_requires_source_version_and_images_to_match_before_export(tmp_path, monkeypatch):
    from deploy.intranet import upgrade_source
    from utils_local import ascend_model_manifest

    image = {"reference": "fixture:arm64", "id": "sha256:fixture"}
    monkeypatch.setattr(ascend_model_manifest, "load_manifest", lambda _: ({"prepared": True}, tmp_path))
    monkeypatch.setattr(release, "inspect_image", lambda _: image)
    monkeypatch.setattr(release, "copy_delivery_files", lambda _: None)
    monkeypatch.setattr(upgrade_source, "verify_package", lambda _: {"version": "wrong", "images": {}})
    (tmp_path / "build-fixture.json").write_text(json.dumps({
        "validation_status": "passed", "images": {name: image for name in ("platform", "console")}}))
    with pytest.raises(ValueError, match="source version/images"):
        release.package(SimpleNamespace(output=tmp_path, version="fixture", model_manifest=tmp_path / "manifest.json",
                                        deployment_env=tmp_path / "private.env", app_source=tmp_path / "source"))
    assert not list(tmp_path.glob("*.tar.gz"))


def test_sasl_validation_has_no_unauthenticated_fallback():
    with pytest.raises(ValueError, match="username and password"):
        kafka_security_options({"KAFKA_SECURITY_PROTOCOL": "SASL_PLAINTEXT"})
    options = kafka_security_options({"KAFKA_SECURITY_PROTOCOL": "SASL_PLAINTEXT",
                                      "KAFKA_SASL_USERNAME": "user", "KAFKA_SASL_PASSWORD": "private"})
    assert options["security_protocol"] == "SASL_PLAINTEXT"
    assert options["sasl_plain_password"] == "private"
    assert "sasl_plain_password" not in kafka_security_options({})


@pytest.mark.parametrize("name", ["KafkaProducerNode", "TccEvidencePublisherNode", "EnforcementEvidencePublisherNode"])
def test_every_publisher_receives_sasl_credentials(monkeypatch, name):
    import importlib
    target = importlib.import_module(f"nodes.{name}")
    captured = {}

    class Captured(Exception):
        pass

    def producer(**options):
        captured.update(options)
        raise Captured()

    monkeypatch.setenv("KAFKA_SECURITY_PROTOCOL", "SASL_PLAINTEXT")
    monkeypatch.setenv("KAFKA_SASL_USERNAME", "user")
    monkeypatch.setenv("KAFKA_SASL_PASSWORD", "private")
    monkeypatch.delenv("TRAJECTORY_STORAGE_PROFILE", raising=False)
    monkeypatch.setattr(target, "KafkaProducer", producer)
    config = {"kafka_producer_node": {"bootstrap_servers": "broker:9093", "camera_id": 1, "how_often_sec": 1}}
    with pytest.raises(Captured):
        getattr(target, name)(config)
    assert captured["security_protocol"] == "SASL_PLAINTEXT"
    assert captured["sasl_plain_username"] == "user"
    assert captured["sasl_plain_password"] == "private"
