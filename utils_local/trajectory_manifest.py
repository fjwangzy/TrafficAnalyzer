"""Streaming SHA-256 manifest of immutable source-segment identities."""

import hashlib
import json


def manifest_line(track_id, digest):
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise ValueError("invalid source segment digest")
    return (
        json.dumps([str(track_id), digest], ensure_ascii=False, separators=(",", ":"))
        + "\n"
    ).encode()


def manifest_hash(ordered_rows):
    result = hashlib.sha256()
    for track, digest in ordered_rows:
        result.update(manifest_line(track, digest))
    return result.hexdigest()
