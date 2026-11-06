"""Canonical immutable transport checksum, independent of Kafka offsets."""

import hashlib
import json


def content_hash(payload):
    value = {k: v for k, v in payload.items() if k != "content_hash"}
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def seal_payload(payload):
    if payload.get("transport_version") != "uav-fixed/v2":
        return payload
    digest = content_hash(payload)
    if payload.get("content_hash") not in {None, digest}:
        raise ValueError("message content hash conflict")
    return {**payload, "content_hash": digest}


def validate_payload(payload):
    if payload.get("transport_version") == "uav-fixed/v2":
        if payload.get("content_hash") != content_hash(payload):
            raise ValueError("invalid immutable message content hash")
        if payload.get("storage_profile") not in {"live", "replay_v2"}:
            raise ValueError("invalid storage profile")
