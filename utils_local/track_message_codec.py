"""Bounded optional encoding for dense v2 track geometry on existing Kafka Topics."""

import base64
import gzip
import hashlib
import io
import json
import zlib

CODEC = "gzip-json/v1"
MAX_INFLATED = 64 * 1024 * 1024


def pack_track_message(message, *, trigger_bytes=700000, max_bytes=950000):
    data = message.get("data") or {}
    if (
        message.get("msg_type") != "uav_track_complete"
        or (data.get("sampling") or {}).get("algorithm_version") != "event-faithful/v2"
    ):
        return message
    encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) <= trigger_bytes or "points_blob" in data:
        return message
    points = json.dumps(
        data["points"], ensure_ascii=False, separators=(",", ":")
    ).encode()
    if len(points) > MAX_INFLATED:
        raise ValueError("dense track exceeds bounded geometry transport limit")
    result = {**message, "data": {k: v for k, v in data.items() if k != "points"}}
    result["data"]["points_blob"] = {
        "codec": CODEC,
        "sha256": hashlib.sha256(points).hexdigest(),
        "decoded_bytes": len(points),
        "count": len(data["points"]),
        "base64": base64.b64encode(
            gzip.compress(points, compresslevel=3, mtime=0)
        ).decode("ascii"),
    }
    if (
        len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode())
        > max_bytes
    ):
        raise ValueError(
            "packed track exceeds Kafka contract budget; raw archive retained"
        )
    return result


def unpack_track_message(message):
    if not isinstance(message, dict) or not isinstance(message.get("data"), dict):
        raise ValueError("track payload requires an object data field")
    data = message["data"]
    blob = data.get("points_blob")
    if blob is None:
        return message
    if (
        message.get("msg_type") != "uav_track_complete"
        or blob.get("codec") != CODEC
        or "points" in data
    ):
        raise ValueError("unsupported or ambiguous packed track")
    size = blob.get("decoded_bytes")
    if type(size) is not int or not 0 < size <= MAX_INFLATED:
        raise ValueError("invalid inflated geometry size")
    if type(blob.get("count")) is not int or blob["count"] < 1:
        raise ValueError("invalid packed point count")
    if not isinstance(blob.get("base64"), str) or len(blob["base64"]) > 950000:
        raise ValueError("packed geometry exceeds transport budget")
    compressed = base64.b64decode(blob["base64"], validate=True)
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
            content = stream.read(size + 1)
    except (OSError, EOFError, zlib.error) as error:
        raise ValueError("invalid gzip track geometry") from error
    if len(content) != size or hashlib.sha256(content).hexdigest() != blob["sha256"]:
        raise ValueError("packed geometry size/hash mismatch")
    points = json.loads(content)
    if (
        not isinstance(points, list)
        or len(points) != blob["count"]
        or len(points) != data.get("retained_point_count")
    ):
        raise ValueError("packed track point count mismatch")
    return {
        **message,
        "data": {
            **{k: v for k, v in data.items() if k != "points_blob"},
            "points": points,
        },
    }


def transport_messages(message, *, budget=950000, chunk_bytes=400000):
    """Split bounded logical trajectories; each chunk is an immutable Kafka fact."""
    from utils_local.message_identity import seal_payload
    import uuid

    message = seal_payload(message)
    try:
        packed = pack_track_message(message, max_bytes=budget)
        # Re-sign because optional geometry packing changes the transport bytes.
        if (
            len(json.dumps(packed, ensure_ascii=False, separators=(",", ":")).encode())
            > budget
        ):
            raise ValueError("logical trajectory requires chunking")
        packed.pop("content_hash", None)
        return [seal_payload(packed)]
    except ValueError:
        if message.get("msg_type") != "uav_track_complete":
            raise
    raw = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode()
    if len(raw) > MAX_INFLATED:
        raise ValueError("logical trajectory exceeds bounded transport size")
    compressed = gzip.compress(raw, compresslevel=3, mtime=0)
    count = (len(compressed) + chunk_bytes - 1) // chunk_bytes
    if not 1 <= count <= 256:
        raise ValueError("invalid track chunk count")
    result = []
    lineage = {
        k: v
        for k, v in message["data"].items()
        if k
        in {"mission_id", "source_profile_id", "pipeline_id", "run_id", "offset_ms"}
    }
    for seq in range(count):
        chunk = {
            **{k: v for k, v in message.items() if k not in {"data", "content_hash"}},
            "msg_type": "uav_track_chunk",
            "schema_version": "uav_track_chunk/v1",
            "message_id": str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL, message["message_id"] + ":chunk:" + str(seq)
                )
            ),
            "data": {
                **lineage,
                "logical_message_id": message["message_id"],
                "chunk_seq": seq,
                "chunk_count": count,
                "logical_sha256": hashlib.sha256(raw).hexdigest(),
                "decoded_bytes": len(raw),
                "base64": base64.b64encode(
                    compressed[seq * chunk_bytes : (seq + 1) * chunk_bytes]
                ).decode(),
            },
        }
        result.append(seal_payload(chunk))
    return result
