"""Import only the explicitly exported source configuration, never replay history."""
import json
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath


def load_sources(path):
    payload = json.loads(Path(path).read_text())
    if payload.get("schema_version") != "uav.deployment-sources/v1":
        raise ValueError("Unsupported deployment source catalog")
    drones = {row["id"] for row in payload["drones"]}
    profiles = set()
    for source in payload["sources"]:
        video, telemetry = source["video"], source["telemetry"]
        if video["profile_id"] in profiles or video["profile_id"] != telemetry["profile_id"]:
            raise ValueError("Duplicate or mismatched source profile")
        profiles.add(video["profile_id"])
        if video["drone_id"] != telemetry["drone_id"] or video["drone_id"] not in drones:
            raise ValueError("Missing or mismatched source drone")
        for item in (video, telemetry):
            path = PurePosixPath(item["location"])
            if item["mode"] != "local" or not path.is_relative_to("/app/test_videos") or ".." in path.parts:
                raise ValueError("Deployment sources must use the mounted video directory")
            if item.get("credential_ref"):
                raise ValueError("Test source catalog must not contain credentials")
    return payload


async def seed_sources(session, path):
    from sqlalchemy import select
    from app.models.mission import DroneRecord, TelemetrySourceRecord, VideoSourceRecord
    from app.services.mission_orchestrator import SourceValidator

    payload = load_sources(path)
    changed = 0
    validator = SourceValidator()
    for item in payload["drones"]:
        if await session.get(DroneRecord, item["id"]) is None:
            session.add(DroneRecord(**{name: item[name] for name in (
                "id", "name", "model", "enabled", "default_inter_id",
                "default_video_source_id", "default_telemetry_source_id")}))
            changed += 1
    await session.flush()
    for source in payload["sources"]:
        records = []
        for kind, model in (("video", VideoSourceRecord), ("telemetry", TelemetrySourceRecord)):
            item = source[kind]
            row = (await session.execute(select(model).where(model.profile_id == item["profile_id"]))).scalar_one_or_none()
            if row is None:
                fields = {name: item[name] for name in (
                    "id", "profile_id", "drone_id", "mode", "source_type", "location", "enabled")}
                if kind == "telemetry":
                    fields["config"] = item.get("config") or {}
                row = model(**fields)
                session.add(row)
                changed += 1
            records.append(row)
        status, code = validator.validate(*records)
        for row in records:
            row.validation_status, row.validation_error_code = status, code
            row.validated_at = datetime.now(UTC)
    await session.flush()
    return {"source_profiles": len(payload["sources"]), "drones": len(payload["drones"]), "inserted": changed}
