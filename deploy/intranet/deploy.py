#!/usr/bin/env python3
"""Offline-only operations against the root Compose plus production overlay."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ("platform", "console2")


def file_digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def verify_files(root=ROOT):
    lines = (root / "SHA256SUMS").read_text().splitlines()
    for line in lines:
        expected, name = line.split("  ", 1)
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or file_digest(path) != expected:
            raise RuntimeError(f"Release checksum mismatch: {name}")
    release = json.loads((root / "RELEASE.json").read_text())
    if release.get("kind") != "offline-images":
        raise RuntimeError("This is a source preparation archive, not an offline deployment package")
    return release


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "load", "prepare-dirs", "check", "init-db", "up", "stop", "status", "logs", "accept", "rollback"))
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--project", default="traffic_analyzer_prod")
    parser.add_argument("--previous-dir", type=Path)
    args = parser.parse_args()
    release = verify_files()
    if args.command == "verify":
        print(f"Verified {release['version']}; models: {release.get('resource_status', 'unknown')}; site acceptance: {release['site_acceptance']}")
        return
    if args.command == "load":
        subprocess.run(["docker", "load", "-i", str(ROOT / "images/runtime.tar")], check=True)
        return
    if args.command == "up" and release.get("single_compose"):
        subprocess.run([str(ROOT / "docker-compose"), "up", "-d"], check=True)
        return
    environment = args.env_file.resolve(strict=True)
    if environment.stat().st_mode & 0o077:
        raise RuntimeError(".env must be private: chmod 600")
    compose = ["docker", "compose", "--project-name", args.project, "--env-file", str(environment),
               "-f", str(ROOT / "docker-compose.yaml")]
    if not release.get("single_compose"):
        compose += ["-f", str(ROOT / "deploy/intranet/compose.yaml")]
    config = json.loads(subprocess.run(compose + ["config", "--format", "json"],
                                      check=True, capture_output=True, text=True).stdout)
    checks = (("platform", "platform"), ("console2", "console")) if args.command in {"check", "init-db", "up", "accept"} else ()
    for service, key in checks:
        name = config["services"][service]["image"]
        image = json.loads(subprocess.run(["docker", "image", "inspect", name],
                                         check=True, capture_output=True, text=True).stdout)[0]
        if image["Id"] != release["images"][key]["id"] or image["Architecture"] != "arm64":
            raise RuntimeError(f"Loaded image differs from the release: {service}")
    if args.command == "rollback":
        if args.previous_dir is None:
            parser.error("rollback requires --previous-dir")
        previous = args.previous_dir.resolve(strict=True)
        previous_release = verify_files(previous)
        previous_environment = dict(os.environ)
        for variable, service in (("PLATFORM_IMAGE", "platform"), ("CONSOLE_IMAGE", "console")):
            expected = previous_release["images"][service]
            actual = json.loads(subprocess.run(["docker", "image", "inspect", expected["reference"]],
                                              check=True, capture_output=True, text=True).stdout)[0]
            if actual["Id"] != expected["id"] or actual["Architecture"] != "arm64":
                raise RuntimeError(f"Previous image differs from its release: {service}")
            previous_environment[variable] = expected["reference"]
        subprocess.run(compose + ["up", "-d", "--no-deps", "--no-build", "--pull", "never", *SERVICES],
                       check=True, env=previous_environment)
        return
    if args.command == "prepare-dirs":
        for mount in config["services"]["platform"]["volumes"]:
            source = Path(mount["source"])
            if mount["type"] != "bind" or mount.get("read_only"):
                continue
            if not source.is_absolute() or source == Path("/"):
                raise RuntimeError("Writable production mounts must use explicit absolute directories")
            source.mkdir(parents=True, exist_ok=True)
        print("Persistent directories prepared; copy weights, OM models, videos and SRT separately")
        return
    if args.command in {"check", "init-db", "up"}:
        if platform.system() != "Linux" or platform.machine() not in {"arm64", "aarch64"}:
            raise RuntimeError("Run production checks/startup on the Linux ARM64 310P3 host")
        for device in ("/dev/davinci_manager", "/dev/devmm_svm", "/dev/hisi_hdc"):
            if not Path(device).exists():
                raise RuntimeError(f"Missing Ascend device: {device}")
        settings = config["services"]["platform"]["environment"]
        if "REPLACE" in settings["CORS_ORIGINS"]:
            raise RuntimeError("Set CORS_ORIGINS to the actual http://IP:8009 origin")
        subprocess.run(["npu-smi", "info"], check=True)
    if args.command == "check":
        subprocess.run(compose + ["run", "--rm", "--no-deps", "platform",
                                  "python3", "/app/deploy/" + ("intranet/" if release.get("application_source") else "") + "runtime_check.py"], check=True)
    elif args.command == "init-db":
        subprocess.run(compose + ["run", "--rm", "--no-deps", "init-db"], check=True)
    elif args.command == "up":
        subprocess.run(compose + ["up", "-d", "--no-build", "--pull", "never",
                                  "--wait", "--wait-timeout", "180", *SERVICES], check=True)
    elif args.command == "accept":
        port = config["services"]["console2"]["ports"][0]["published"]
        base = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(base + "/ready", timeout=30) as response:
            report = json.load(response)
        if report.get("status") != "ready":
            raise RuntimeError("Platform dependencies are not ready")
        with urllib.request.urlopen(base + "/", timeout=30) as response:
            if response.status != 200:
                raise RuntimeError("Console is not reachable")
        report["validation_scope"] = "dependency_and_entrypoint_smoke_only"
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        commands = {"stop": ["stop"], "status": ["ps"], "logs": ["logs", "--tail", "200"]}
        subprocess.run(compose + commands[args.command] + list(SERVICES), check=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
