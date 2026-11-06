"""Append-only spatial derivative spool; never retain a Mission's features in RAM."""

import json
from pathlib import Path
import uuid


class SpatialFeatureSpool:
    def __init__(self, root):
        Path(root).mkdir(parents=True, exist_ok=True)
        self.path = Path(root) / (".features-" + uuid.uuid4().hex + ".ndjson")
        self.stream = self.path.open("x", encoding="utf-8")
        self.count = 0

    def append(self, feature):
        json.dump(feature, self.stream, ensure_ascii=False, separators=(",", ":"))
        self.stream.write("\n")
        self.count += 1

    def __len__(self):
        return self.count

    def __iter__(self):
        self.stream.flush()
        with self.path.open(encoding="utf-8") as source:
            for line in source:
                yield json.loads(line)

    def close(self):
        self.stream.close()
