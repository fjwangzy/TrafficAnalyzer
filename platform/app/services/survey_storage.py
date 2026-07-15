"""Content-addressed local evidence storage for accident survey artifacts."""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredObject:
    storage_key: str
    sha256: str
    size_bytes: int
    path: Path


class ContentAddressedStore:
    def __init__(self, root: str):
        self.root = Path(root).expanduser().resolve()
        (self.root / "objects").mkdir(parents=True, exist_ok=True)

    def _destination(self, digest: str) -> Path:
        return self.root / "objects" / digest[:2] / digest

    @staticmethod
    def _hash_file(path: Path) -> tuple[str, int]:
        hasher = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                hasher.update(chunk)
                size += len(chunk)
        return hasher.hexdigest(), size

    def ingest_path(self, source: str | Path) -> StoredObject:
        source_path = Path(source).expanduser().resolve(strict=True)
        digest, size = self._hash_file(source_path)
        destination = self._destination(digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            try:
                os.link(source_path, destination)
            except OSError:
                shutil.copy2(source_path, destination)
        destination.chmod(0o440)
        return StoredObject(f"objects/{digest[:2]}/{digest}", digest, size, destination)

    def ingest_bytes(self, data: bytes) -> StoredObject:
        digest = hashlib.sha256(data).hexdigest()
        destination = self._destination(digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            temporary = destination.with_suffix(".tmp")
            temporary.write_bytes(data)
            temporary.replace(destination)
            destination.chmod(0o440)
        return StoredObject(f"objects/{digest[:2]}/{digest}", digest, len(data), destination)

    def ingest_fileobj(self, source, max_bytes: int) -> StoredObject:
        """Stream an upload into immutable storage without loading it into RAM."""
        temporary = self.root / "objects" / f".upload-{uuid.uuid4().hex}"
        hasher = hashlib.sha256()
        size = 0
        try:
            with temporary.open("wb") as handle:
                while chunk := source.read(8 * 1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("survey upload exceeds configured size limit")
                    hasher.update(chunk)
                    handle.write(chunk)
            digest = hasher.hexdigest()
            destination = self._destination(digest)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                temporary.unlink()
            else:
                temporary.replace(destination)
                destination.chmod(0o440)
            return StoredObject(f"objects/{digest[:2]}/{digest}", digest, size, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def resolve(self, storage_key: str) -> Path:
        candidate = (self.root / storage_key).resolve(strict=True)
        if self.root not in candidate.parents:
            raise ValueError("evidence storage key escapes configured root")
        return candidate

    def verify(self, storage_key: str, sha256: str, size_bytes: int) -> bool:
        """Re-hash an immutable object before it is included in a report."""
        try:
            candidate = self.resolve(storage_key)
            digest, size = self._hash_file(candidate)
        except (FileNotFoundError, ValueError, OSError):
            return False
        return digest == sha256 and size == size_bytes


def resolve_allowlisted_asset(asset: str, roots: list[str], base_dir: str | Path) -> Path:
    if not asset or Path(asset).is_absolute():
        raise ValueError("asset must be a relative allowlisted key")
    base = Path(base_dir).resolve()
    for root_value in roots:
        root = Path(root_value)
        if not root.is_absolute():
            root = (base / root).resolve()
        else:
            root = root.resolve()
        candidate = (root / asset).resolve()
        if root in candidate.parents and candidate.is_file():
            return candidate
    raise ValueError("asset key is outside configured survey roots or missing")
