#!/usr/bin/env python3
"""Stage and switch application sources using existing offline runtime images."""

import argparse
import fcntl
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

SERVICES = ("platform", "console2")
URL_AUTH = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/\s@]+@")
AUTHORIZATION = re.compile(r"(?i)((?:authorization|proxy-authorization)[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|(?:bearer|basic)\s+[^\s,;}]+|[^\s,;}]+)")
SECRET_FIELD = re.compile(r"(?i)((?:password|passwd|pwd|secret|access_token|token|authorization|api_key)[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;&\"'}]+)")


def redact_log_text(value, secrets=()):
    for secret in secrets:
        if len(secret) >= 4:
            value = value.replace(secret, "[redacted]")
    value = URL_AUTH.sub(r"\1[redacted]@", value)
    value = AUTHORIZATION.sub(r"\1[redacted]", value)
    return SECRET_FIELD.sub(r"\1[redacted]", value)


class PrivateRotatingFileHandler(RotatingFileHandler):
    def _open(self):
        descriptor = os.open(self.baseFilename, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        os.fchmod(descriptor, 0o600)
        return os.fdopen(descriptor, self.mode, encoding=self.encoding, errors=self.errors)


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def verify_package(directory):
    directory = directory.resolve(strict=True)
    expected = {}
    for line in (directory / "SHA256SUMS").read_text().splitlines():
        checksum, name = line.split("  ", 1)
        relative = Path(name)
        if (not re.fullmatch(r"[a-f0-9]{64}", checksum) or relative.is_absolute()
                or ".." in relative.parts or any(part.startswith(".") for part in relative.parts)
                or name in expected):
            raise ValueError("Invalid source checksum entry")
        path = directory / relative
        if path.is_symlink() or not path.is_file() or digest(path) != checksum:
            raise ValueError(f"Source checksum mismatch: {name}")
        expected[name] = checksum
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    if actual != set(expected) | {"SHA256SUMS"} or any(p.is_symlink() for p in directory.rglob("*")):
        raise ValueError("Source package contains unlisted files or links")
    release = json.loads((directory / "APP_RELEASE.json").read_text())
    if release.get("kind") != "app-source" or release.get("platform") != "linux/arm64":
        raise ValueError("Expected a Linux ARM64 application source package")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", release["version"]):
        raise ValueError("Invalid application version")
    migrations = {p.relative_to(directory / "app").as_posix()
                  for folder in ("platform/alembic", "platform/alembic_replay_v2")
                  for p in (directory / "app" / folder).rglob("*") if p.is_file()}
    expected_migrations = {name for name in release["runtime_baseline"]
                           if name.startswith(("platform/alembic/", "platform/alembic_replay_v2/"))}
    if not migrations or migrations != expected_migrations:
        raise ValueError("Migration file set changed; a separate schema upgrade is required")
    for name, checksum in release["runtime_baseline"].items():
        if not name.startswith("platform/") or ".." in Path(name).parts:
            raise ValueError("Invalid runtime compatibility baseline")
        if digest(directory / "app" / name) != checksum:
            raise ValueError("Source dependency or migration changed; a separate runtime/schema upgrade is required")
    return release


def captured(command, env=None):
    result = subprocess.run(command, env=env, check=True, capture_output=True, text=True)
    return result.stdout.strip()


class Deployment:
    def __init__(self, root):
        self.root = root.resolve(strict=True)
        environment = self.root / ".env"
        if not environment.is_file() or environment.stat().st_mode & 0o077:
            raise ValueError("Existing deployment .env must exist with mode 600")
        self.directory = self.root / "app"
        self.directory.mkdir(mode=0o755, exist_ok=True)
        self.state_path = self.directory / "state.json"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.base_files = self.state.get("base_files", [str(self.root / "docker-compose.yaml")])
        if not self.state:
            # Preserve an already installed Console .5 overlay when returning to image mode.
            ids = captured(self.compose() + ["ps", "--all", "-q", "console2"])
            if ids:
                labels = json.loads(captured(["docker", "inspect", "--format", "{{json .Config.Labels}}", ids.splitlines()[0]]))
                files = labels.get("com.docker.compose.project.config_files", "").split(",")
                if files and all(Path(name).is_file() for name in files):
                    self.base_files = files
        config = json.loads(captured(self.compose() + ["config", "--format", "json"]))
        self.secrets = [str(value) for service in config["services"].values()
                        for key, value in service.get("environment", {}).items()
                        if any(part in key.upper() for part in ("PASSWORD", "SECRET", "TOKEN", "KEY")) and value]
        mounts = config["services"]["platform"]["volumes"]
        log_root = next(Path(m["source"]) for m in mounts if m["target"] == "/app/logs")
        if not log_root.is_absolute() or log_root == Path("/"):
            raise ValueError("Expected an absolute existing DATA_ROOT/logs mount")
        for name in ("containers", "deployment", "nginx", "pipelines"):
            (log_root / name).mkdir(parents=True, mode=0o755, exist_ok=True)
        self.logger = logging.getLogger("source-upgrade")
        self.logger.setLevel(logging.INFO)
        self.handler = PrivateRotatingFileHandler(log_root / "deployment" / "source-upgrade.log",
                                                 maxBytes=20 * 1024 * 1024, backupCount=5, encoding="utf-8")
        formatter = logging.Formatter(
            "%(asctime)s.%(msecs)03dZ %(levelname)s pid=%(process)d %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        formatter.converter = time.gmtime
        self.handler.setFormatter(formatter)
        self.logger.addHandler(self.handler)

    def compose(self, release=None):
        command = ["docker", "compose", "--project-directory", str(self.root), "--env-file", str(self.root / ".env")]
        for name in self.base_files:
            command.extend(("-f", name))
        if release is not None:
            command.extend(("-f", str(release / "source-compose.yaml")))
        return command

    def environment(self, release):
        manifest = verify_package(release)
        return {**os.environ, "APP_ROOT": str(release / "app"),
                "APP_PLATFORM_IMAGE": manifest["images"]["platform"]["reference"],
                "APP_CONSOLE_IMAGE": manifest["images"]["console"]["reference"]}

    def run(self, arguments, release=None):
        command = self.compose(release) + list(arguments)
        process = subprocess.Popen(command, env=self.environment(release) if release else None,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        for line in process.stdout:
            line = redact_log_text(line, self.secrets)
            print(line, end="", flush=True)
            self.logger.info(line.rstrip("\n"))
        if process.wait():
            raise RuntimeError(f"Compose operation failed: {arguments[0]}")

    def compatible(self, directory):
        manifest = verify_package(directory)
        for image in manifest["images"].values():
            actual = json.loads(captured(["docker", "image", "inspect", image["reference"]]))[0]
            if actual["Id"] != image["id"] or actual["Architecture"] != "arm64" or actual["Os"] != "linux":
                raise ValueError("Runtime image ID/architecture differs; do not pull or rebuild during a source upgrade")
        captured(self.compose(directory) + ["config", "--quiet"], env=self.environment(directory))

    def stage(self, package):
        manifest = verify_package(package)
        self.compatible(package)
        target = self.directory / "releases" / manifest["version"]
        target.parent.mkdir(mode=0o755, exist_ok=True)
        if target.exists():
            if digest(target / "SHA256SUMS") != digest(package / "SHA256SUMS"):
                raise ValueError("This source version already exists with different content")
            verify_package(target)
        else:
            with tempfile.TemporaryDirectory(prefix=".stage-", dir=target.parent) as temporary:
                staged = Path(temporary) / "release"
                shutil.copytree(package, staged)
                for path in staged.rglob("*"):
                    path.chmod(0o755 if path.is_dir() else 0o644)
                staged.chmod(0o755)
                verify_package(staged)
                staged.rename(target)
        self.run(["run", "--rm", "--no-deps", "-T", "init-db", "python3",
                  "/app/deploy/intranet/run_logged.py", "source-check", "python3", "-u",
                  "/app/deploy/intranet/source_check.py", "--database"], target)
        print(f"Source staged and read-only checks passed: {manifest['version']}")
        return target

    def save(self, current, previous):
        self.state = {"base_files": self.base_files, "current": str(current) if current else None,
                      "previous": str(previous) if previous else None}
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, indent=2) + "\n")
        temporary.replace(self.state_path)
        for name, target in (("current", current), ("previous", previous)):
            link = self.directory / name
            if target:
                pending = self.directory / (name + ".tmp")
                pending.unlink(missing_ok=True)
                pending.symlink_to(target, target_is_directory=True)
                pending.replace(link)
            else:
                link.unlink(missing_ok=True)

    def start(self, target):
        try:
            self.run(["up", "-d", "--no-deps", "--no-build", "--pull", "never", "--force-recreate",
                      "--wait", "--wait-timeout", "180", *SERVICES], target)
        except Exception:
            # Include failures in the image's CANN entrypoint before Python logging starts.
            try:
                self.run(["logs", "--no-color", "--tail", "200", *SERVICES], target)
            except Exception:
                self.logger.exception("Could not collect failed container startup logs")
            raise

    def switch(self, target, *, preflight=True):
        old = Path(self.state["current"]) if self.state.get("current") else None
        previous = old
        if target == old:
            previous = Path(self.state["previous"]) if self.state.get("previous") else None
        if target:
            self.compatible(target)
        try:
            self.run(["stop", "--timeout", "30", *SERVICES], old)
            if target and preflight:
                self.run(["run", "--rm", "--no-deps", "-T", "platform", "python3",
                          "/app/deploy/intranet/run_logged.py", "preflight", "python3", "-u",
                          "/app/deploy/intranet/runtime_check.py"], target)
            self.start(target)
        except BaseException:
            self.logger.exception("Source switch failed; restoring the previous application configuration")
            self.run(["stop", "--timeout", "30", *SERVICES], target)
            self.start(old)
            raise
        self.save(target, previous)
        self.install_launcher(target or old)
        print("Application switch passed health checks; database, assets and private .env were retained")

    def install_launcher(self, release):
        if release is None:
            return
        shutil.copy2(release / "upgrade_source.py", self.directory / "upgrade_source.py")
        launcher = self.root / "app-compose"
        launcher.write_text('#!/bin/sh\nset -eu\nroot=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
                            'exec python3 "$root/app/upgrade_source.py" --deployment-root "$root" compose "$@"\n')
        launcher.chmod(0o755)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-root", type=Path, required=True)
    parser.add_argument("command", choices=("prepare", "apply", "rollback", "compose"))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    deployment = Deployment(args.deployment_root)
    with (deployment.directory / "upgrade.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.command in {"prepare", "apply"}:
            package = Path(__file__).resolve().parent
            target = deployment.stage(package)
            if args.command == "apply":
                if platform.system() != "Linux" or platform.machine() not in {"aarch64", "arm64"}:
                    raise ValueError("Apply only on the production Linux ARM64 host")
                deployment.switch(target)
        elif args.command == "rollback":
            if "previous" not in deployment.state:
                raise ValueError("There is no recorded application rollback")
            previous = Path(deployment.state["previous"]) if deployment.state["previous"] else None
            deployment.switch(previous)
        else:
            current = Path(deployment.state["current"]) if deployment.state.get("current") else None
            if not args.arguments or args.arguments[0] in {"build", "pull"}:
                raise ValueError("Use an offline Compose command such as ps/logs/stop/up")
            if args.arguments[0] == "up":
                deployment.start(current)
            else:
                deployment.run(args.arguments, current)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"Source upgrade blocked: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
