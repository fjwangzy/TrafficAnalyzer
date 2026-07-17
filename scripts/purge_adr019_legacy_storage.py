#!/usr/bin/env python3
"""Record and, after seven days, explicitly purge ADR-019 legacy storage."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "output" / "adr019-retirement" / "retention.json"
FIXED_VOLUME_ALLOWLIST = frozenset({
    "trafficanalyzer_postgres_data",
    "trafficanalyzer_timescaledb_local_data",
    "traffic_analyzer_mp4new_road9_target_data",
})
FIXED_BIND_ALLOWLIST = frozenset({str((ROOT / "services" / "influxdb_data").resolve())})
CONFIRMATION = "DELETE_EXPIRED_ADR019_LEGACY_STORAGE"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC)


def record_manifest(path: Path, now: datetime | None = None) -> dict[str, Any]:
    retired_at = (now or _utc_now()).astimezone(UTC)
    manifest = {
        "schema_version": "uav.adr019-legacy-retention/v1",
        "retired_at": _iso(retired_at),
        "purge_after": _iso(retired_at + timedelta(days=7)),
        "volumes": sorted(FIXED_VOLUME_ALLOWLIST),
        "bind_paths": sorted(FIXED_BIND_ALLOWLIST),
        "policy": "保留 7 天且不再挂载；到期后仅允许人工显式执行，不迁移、不备份、不校验旧内容。",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "uav.adr019-legacy-retention/v1":
        raise RuntimeError("retention manifest schema_version is invalid")
    if set(manifest.get("volumes", [])) != FIXED_VOLUME_ALLOWLIST:
        raise RuntimeError("retention manifest volume allowlist does not exactly match the fixed allowlist")
    if set(manifest.get("bind_paths", [])) != FIXED_BIND_ALLOWLIST:
        raise RuntimeError("retention manifest bind allowlist does not exactly match the fixed allowlist")
    retired_at = _parse(str(manifest["retired_at"]))
    purge_after = _parse(str(manifest["purge_after"]))
    if purge_after - retired_at < timedelta(days=7):
        raise RuntimeError("retention manifest is shorter than seven days")
    return manifest


def _mounted_sources() -> set[str]:
    result = subprocess.run(
        ["docker", "ps", "-aq"], check=True, capture_output=True, text=True
    )
    container_ids = result.stdout.split()
    if not container_ids:
        return set()
    inspected = subprocess.run(
        ["docker", "inspect", *container_ids], check=True, capture_output=True, text=True
    )
    sources: set[str] = set()
    for container in json.loads(inspected.stdout):
        for mount in container.get("Mounts", []):
            source = mount.get("Name") or mount.get("Source")
            if source:
                sources.add(str(source))
    return sources


def purge(path: Path, confirmation: str, now: datetime | None = None) -> dict[str, Any]:
    if os.getenv("ALLOW_ADR019_LEGACY_PURGE") != "1":
        raise RuntimeError("set ALLOW_ADR019_LEGACY_PURGE=1 before an expired purge")
    if confirmation != CONFIRMATION:
        raise RuntimeError(f"pass --confirm {CONFIRMATION}")
    manifest = load_manifest(path)
    current = (now or _utc_now()).astimezone(UTC)
    purge_after = _parse(str(manifest["purge_after"]))
    if current < purge_after:
        raise RuntimeError(f"seven-day retention is active until {_iso(purge_after)}")
    mounted = _mounted_sources()
    forbidden = (FIXED_VOLUME_ALLOWLIST | FIXED_BIND_ALLOWLIST) & mounted
    if forbidden:
        raise RuntimeError(f"refusing to purge mounted legacy storage: {sorted(forbidden)}")

    deleted_volumes: list[str] = []
    for volume in sorted(FIXED_VOLUME_ALLOWLIST):
        exists = subprocess.run(
            ["docker", "volume", "inspect", volume], capture_output=True, text=True
        ).returncode == 0
        if exists:
            subprocess.run(["docker", "volume", "rm", volume], check=True)
            deleted_volumes.append(volume)
    deleted_paths: list[str] = []
    for raw_path in sorted(FIXED_BIND_ALLOWLIST):
        bind_path = Path(raw_path)
        if bind_path.exists():
            shutil.rmtree(bind_path)
            deleted_paths.append(raw_path)
    return {
        "schema_version": "uav.adr019-legacy-purge/v1",
        "purged_at": _iso(current),
        "deleted_volumes": deleted_volumes,
        "deleted_bind_paths": deleted_paths,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("record", "status", "purge"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if args.action == "record":
        result = record_manifest(args.manifest)
    elif args.action == "status":
        result = load_manifest(args.manifest)
        result = {
            **result,
            "eligible": _utc_now() >= _parse(str(result["purge_after"])),
        }
    else:
        result = purge(args.manifest, args.confirm)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
