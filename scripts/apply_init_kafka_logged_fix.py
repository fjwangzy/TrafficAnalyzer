#!/usr/bin/env python3
"""Apply the reviewed .2 wrapper-only fix without bypassing package checksums.

No DB/Kafka/client configuration is opened. Writes are limited to three source
manifest files and a private, recoverable patch journal under state/patches.
"""

import argparse
from datetime import UTC, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid

PATCH_ID = "init-kafka-logged-stage-v1"
WRAPPER = "app/deploy/intranet/run_logged.py"
APPLICATION = "APPLICATION_SHA256.json"
CHECKSUMS = "SHA256SUMS"
FILES = (WRAPPER, APPLICATION, CHECKSUMS)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def atomic(path, content, mode=0o600):
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def checksums(content):
    rows = {}
    for line in content.decode().splitlines():
        digest, name = line.split("  ", 1)
        if name in rows:
            raise ValueError("duplicate checksum entry")
        rows[name] = digest
    return rows


def desired(original, new_wrapper):
    application = json.loads(original[APPLICATION])
    application["deploy/intranet/run_logged.py"] = sha(new_wrapper)
    encoded = (json.dumps(application, indent=2) + "\n").encode()
    replacements = {WRAPPER: sha(new_wrapper), APPLICATION: sha(encoded)}
    rows = []
    for line in original[CHECKSUMS].decode().splitlines():
        digest, name = line.split("  ", 1)
        rows.append(replacements.get(name, digest) + "  " + name)
    return {
        WRAPPER: new_wrapper,
        APPLICATION: encoded,
        CHECKSUMS: ("\n".join(rows) + "\n").encode(),
    }


def apply(target, patch_root, *, check_only=False):
    target = Path(target).resolve(strict=True)
    patch_root = Path(patch_root).resolve(strict=True)
    spec = json.loads((patch_root / "PATCH.json").read_text())
    if spec["id"] != PATCH_ID:
        raise ValueError("unsupported patch identity")
    new_wrapper = (patch_root / "run_logged.py").read_bytes()
    if sha(new_wrapper) != spec["replacement_sha256"]:
        raise ValueError("patch payload checksum mismatch")
    release = json.loads((target / "HOST_RELEASE.json").read_text())
    if (
        release.get("version") != spec["target_version"]
        or release.get("kind") != "native-platform-full"
    ):
        raise ValueError("patch requires the original 2026.11.04.2 native full package")
    for name in FILES:
        path = target / name
        if path.is_symlink() or not path.resolve().is_relative_to(target):
            raise ValueError("source path escapes target")
    state = target / "state"
    state.mkdir(mode=0o700, exist_ok=True)
    if state.is_symlink() or not state.resolve().is_relative_to(target):
        raise ValueError("state path escapes target")
    with (state / "control.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        directory = state / "patches" / PATCH_ID
        journal = directory / "journal.json"
        original = {}
        modes = {}
        if journal.exists():
            record = json.loads(journal.read_text())
            if record["id"] != PATCH_ID:
                raise ValueError("patch journal identity conflict")
            for index, name in enumerate(FILES):
                original[name] = (directory / f"{index}.original").read_bytes()
                if sha(original[name]) != spec["original_sha256"][name]:
                    raise ValueError("patch backup checksum mismatch")
                modes[name] = record["modes"][name]
        else:
            for name in FILES:
                original[name] = (target / name).read_bytes()
                if sha(original[name]) != spec["original_sha256"][name]:
                    raise ValueError(
                        "unexpected original file; refusing to rewrite checksum manifest: "
                        + name
                    )
                modes[name] = stat.S_IMODE((target / name).stat().st_mode)
        previous = checksums(original[CHECKSUMS])
        if previous.get(WRAPPER) != sha(original[WRAPPER]) or previous.get(
            APPLICATION
        ) != sha(original[APPLICATION]):
            raise ValueError("original source/manifests are inconsistent")
        if json.loads(original[APPLICATION]).get(
            "deploy/intranet/run_logged.py"
        ) != sha(original[WRAPPER]):
            raise ValueError("original application source snapshot is inconsistent")
        updated = desired(original, new_wrapper)
        for name in FILES:
            if (target / name).read_bytes() not in {original[name], updated[name]}:
                raise ValueError("target changed outside the patch journal: " + name)
        already = all((target / name).read_bytes() == updated[name] for name in FILES)
        if check_only:
            return {
                "status": "already_applied" if already else "applicable",
                "patch": PATCH_ID,
            }
        if not journal.exists():
            directory.mkdir(parents=True, mode=0o700, exist_ok=False)
            for index, name in enumerate(FILES):
                atomic(directory / f"{index}.original", original[name])
            record = {
                "id": PATCH_ID,
                "status": "applying",
                "modes": modes,
                "created_at": datetime.now(UTC).isoformat(),
            }
            atomic(journal, (json.dumps(record, indent=2) + "\n").encode())
        for name in FILES:
            if (target / name).read_bytes() != updated[name]:
                atomic(target / name, updated[name], modes[name])
        for name in FILES:
            if (target / name).read_bytes() != updated[name]:
                raise RuntimeError("patch verification failed: " + name)
        current = checksums((target / CHECKSUMS).read_bytes())
        assert current[WRAPPER] == sha(new_wrapper) and current[APPLICATION] == sha(
            updated[APPLICATION]
        )
        record["status"] = "applied"
        record["applied_at"] = datetime.now(UTC).isoformat()
        atomic(journal, (json.dumps(record, indent=2) + "\n").encode())
        return {
            "status": "already_applied" if already else "applied",
            "patch": PATCH_ID,
            "backup": str(directory),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            apply(args.target, Path(__file__).resolve().parent, check_only=args.check)
        )
    )


if __name__ == "__main__":
    main()
