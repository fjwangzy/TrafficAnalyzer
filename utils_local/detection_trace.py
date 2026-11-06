"""Streaming detection capture for controlled node A/B; no production entrypoint."""

import hashlib
import json
from pathlib import Path

FIELDS = (
    "detected_xyxy",
    "detected_conf",
    "detected_cls",
    "detected_cls_ids",
    "detection_diagnostics",
    "yolo_model_id",
    "inference_context",
)


class DetectionTrace:
    def __init__(self, path, *, replay, identity):
        self.replay = replay
        self.digest = hashlib.sha256()
        identity = dict(identity)
        video = Path(identity["video"])
        digest = hashlib.sha256()
        with video.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        identity["video_sha256"] = digest.hexdigest()
        self.stream = Path(path).open("r" if replay else "x")
        if replay:
            if self._read() != {"version": 1, "identity": identity}:
                self.stream.close()
                raise ValueError("detection trace input/stride/offset mismatch")
        else:
            self._write({"version": 1, "identity": identity})

    def _write(self, value):
        line = (
            json.dumps(
                value,
                sort_keys=True,
                allow_nan=False,
                default=lambda value: (
                    value.tolist() if hasattr(value, "tolist") else value.item()
                ),
            )
            + "\n"
        )
        self.digest.update(line.encode())
        self.stream.write(line)

    def _read(self):
        line = self.stream.readline()
        if not line:
            raise ValueError("detection trace ended before video")
        self.digest.update(line.encode())
        return json.loads(line)

    def record(self, frame):
        self._write(
            {
                "frame_num": frame.frame_num,
                "timestamp": frame.timestamp,
                "fields": {name: getattr(frame, name, None) for name in FIELDS},
            }
        )

    def apply(self, frame):
        row = self._read()
        if (
            row["frame_num"] != frame.frame_num
            or abs(row["timestamp"] - frame.timestamp) > 1e-6
        ):
            raise ValueError("detection trace frame/time mismatch")
        if set(row["fields"]) != set(FIELDS):
            raise ValueError("incomplete detection trace fields")
        for name, value in row["fields"].items():
            setattr(frame, name, value)

    def close(self):
        self.stream.close()
