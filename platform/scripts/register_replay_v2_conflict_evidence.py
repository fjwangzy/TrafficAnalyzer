#!/usr/bin/env python3
"""Register existing Replay V2 TCC JPEGs as managed event evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import cv2
from sqlalchemy import select


PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from app.core.config import settings  # noqa: E402
from app.core.database import async_session_maker  # noqa: E402
from app.models.replay_v2 import ReplayV2ConflictEvent, ReplayV2MessageInbox  # noqa: E402
from app.models.survey import EvidencePackage  # noqa: E402
from app.services.replay_v2_conflict_evidence import (  # noqa: E402
    register_replay_v2_conflict_evidence,
)
from app.services.survey_storage import ContentAddressedStore  # noqa: E402


def _descriptor(path: Path, kind: str, *, ingest: bool) -> dict:
    source = path.expanduser().resolve(strict=True)
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"{kind} is not a readable image")
    height, width = image.shape[:2]
    storage = ContentAddressedStore(settings.survey_storage_dir)
    if ingest:
        stored = storage.ingest_path(source)
        storage_key = stored.storage_key
        sha256 = stored.sha256
        size_bytes = stored.size_bytes
    else:
        sha256, size_bytes = ContentAddressedStore._hash_file(source)
        storage_key = f"objects/{sha256[:2]}/{sha256}"
    return {
        "kind": kind,
        "storage_backend": "managed",
        "storage_key": storage_key,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "media_type": "image/jpeg",
        "width": width,
        "height": height,
    }


async def _run(args) -> None:
    event_id = str(args.event_id)
    async with async_session_maker() as session:
        event = await session.get(ReplayV2ConflictEvent, event_id)
        if event is None:
            raise LookupError(f"Replay V2 conflict not found: {event_id}")
        existing = (
            await session.execute(
                select(EvidencePackage).where(
                    EvidencePackage.owner_type == "replay_v2_conflict",
                    EvidencePackage.owner_id == event_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            print(json.dumps({
                "status": "already_registered",
                "event_id": event_id,
                "package_id": existing.id,
            }, sort_keys=True))
            return

        inbox_rows = (
            await session.execute(
                select(ReplayV2MessageInbox).where(
                    ReplayV2MessageInbox.msg_type == "uav_conflict"
                )
            )
        ).scalars().all()
        source = next(
            (
                row for row in inbox_rows
                if f"uav_replay_v2_conflict_events:{event_id}" in (row.fact_refs or [])
            ),
            None,
        )
        if source is None:
            raise LookupError("Replay V2 conflict inbox lineage not found")

        files = []
        if args.original_frame:
            files.append(_descriptor(
                Path(args.original_frame), "conflict_original_frame", ingest=args.apply
            ))
        files.append(_descriptor(
            Path(args.detector_frame), "conflict_detector_frame", ingest=args.apply
        ))
        result = {
            "status": "ready" if not args.apply else "registered",
            "event_id": event_id,
            "source_message_id": source.message_id,
            "mission_id": event.mission_id,
            "mission_offset_ms": event.offset_ms,
            "evidence_files": files,
        }
        if args.apply:
            references, _fact_refs = register_replay_v2_conflict_evidence(
                session,
                fact_id=event_id,
                source_message_id=source.message_id,
                evidence_files=files,
                storage_root=settings.survey_storage_dir,
                source_time_raw={"mission_offset_ms": event.offset_ms},
            )
            result["evidence_refs"] = references
            await session.commit()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--detector-frame", required=True)
    parser.add_argument("--original-frame")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="ingest and register evidence; without this flag only validate",
    )
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
