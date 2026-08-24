"""Register Replay V2 TCC image evidence in the shared managed evidence store."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.models.survey import EvidenceItem, EvidencePackage
from app.services.survey_storage import ContentAddressedStore


CONFLICT_EVIDENCE_KINDS = (
    "conflict_original_frame",
    "conflict_detector_frame",
)


def _identifier(*parts: Any) -> str:
    return hashlib.sha256(":".join(str(part) for part in parts).encode()).hexdigest()[:40]


def register_replay_v2_conflict_evidence(
    session,
    *,
    fact_id: str,
    source_message_id: str,
    evidence_files: list[dict],
    storage_root: str,
    source_time_raw: dict | None = None,
) -> tuple[list[dict], list[str]]:
    """Verify managed objects, then register portable evidence references.

    The detector process writes immutable content-addressed objects before Kafka
    publication.  Platform only registers descriptors whose hash and size still
    match the managed object; local filesystem paths never enter the API model.
    """
    if not isinstance(evidence_files, list) or not evidence_files:
        raise ValueError("evidence_files_missing")
    if not all(isinstance(item, dict) for item in evidence_files):
        raise ValueError("invalid_evidence_descriptor")

    kinds = [str(item.get("kind") or "") for item in evidence_files]
    expected_order = [kind for kind in CONFLICT_EVIDENCE_KINDS if kind in kinds]
    if (
        len(kinds) != len(set(kinds))
        or any(kind not in CONFLICT_EVIDENCE_KINDS for kind in kinds)
        or kinds != expected_order
    ):
        raise ValueError("invalid_kind_order")

    storage = ContentAddressedStore(storage_root)
    verified_files = []
    for item in evidence_files:
        storage_key = str(item.get("storage_key") or "")
        sha256 = str(item.get("sha256") or "")
        try:
            size_bytes = int(item.get("size_bytes"))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid_size") from exc
        if item.get("storage_backend") != "managed":
            raise ValueError("unsupported_storage_backend")
        if item.get("media_type") != "image/jpeg":
            raise ValueError("invalid_media_type")
        if not re.fullmatch(r"objects/[0-9a-f]{2}/[0-9a-f]{64}", storage_key):
            raise ValueError("invalid_storage_key")
        if not re.fullmatch(r"[0-9a-f]{64}", sha256) or not storage_key.endswith(sha256):
            raise ValueError("invalid_sha256")
        if size_bytes <= 0:
            raise ValueError("invalid_size")
        if not storage.verify(storage_key, sha256, size_bytes):
            raise ValueError("content_verification_failed")
        verified_files.append({
            **item,
            "storage_key": storage_key,
            "sha256": sha256,
            "size_bytes": size_bytes,
        })

    source_message_id = str(source_message_id)
    if len(source_message_id) > 80:
        raise ValueError("source_message_id_too_long")
    package_id = _identifier("replay-v2-conflict-package", fact_id)
    manifest_hash = hashlib.sha256(
        json.dumps(
            [{"kind": item["kind"], "sha256": item["sha256"]} for item in verified_files],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    package = EvidencePackage(
        id=package_id,
        task_id=None,
        owner_type="replay_v2_conflict",
        owner_id=fact_id,
        source_event_id=source_message_id,
        integrity_status="hash_verified",
        manifest_hash=manifest_hash,
    )
    session.add(package)

    original_id = (
        _identifier("replay-v2-conflict-frame", "conflict_original_frame", fact_id)
        if "conflict_original_frame" in kinds
        else None
    )
    evidence_refs = []
    fact_refs = []
    frame_timestamp_sec = (source_time_raw or {}).get("frame_timestamp_sec")
    mission_offset_ms = (source_time_raw or {}).get("mission_offset_ms")
    for item in verified_files:
        kind = item["kind"]
        evidence_id = _identifier("replay-v2-conflict-frame", kind, fact_id)
        session.add(EvidenceItem(
            id=evidence_id,
            package_id=package_id,
            package=package,
            task_id=None,
            kind=kind,
            storage_backend="managed",
            storage_key=item["storage_key"],
            sha256=item["sha256"],
            media_type="image/jpeg",
            size_bytes=item["size_bytes"],
            derived_from_id=(
                original_id
                if kind == "conflict_detector_frame" and original_id is not None
                else None
            ),
            item_metadata={
                "width": item.get("width"),
                "height": item.get("height"),
                "frame_timestamp_sec": frame_timestamp_sec,
                "mission_offset_ms": mission_offset_ms,
            },
        ))
        evidence_refs.append({
            "id": evidence_id,
            "kind": kind,
            "url": f"/api/v1/survey-evidence/{evidence_id}/content",
            "sha256": item["sha256"],
        })
        fact_refs.append(f"uav_evidence_items:{evidence_id}")
    return evidence_refs, fact_refs
