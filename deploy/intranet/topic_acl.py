#!/usr/bin/env python3
"""Fixed business Topic/Group requirements; source keys are event attributes."""

import argparse
import json
import re
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-key", action="append", default=[])
    args = parser.parse_args()
    if any(
        re.fullmatch(r"[A-Za-z0-9._-]{1,128}", source) is None
        for source in args.source_key
    ):
        parser.error("Unsupported source_key")
    value = json.loads(
        Path(__file__).with_name("TEST_SOURCE_TOPIC_ACL.json").read_text()
    )
    value["source_attributes"] = sorted(set(args.source_key))
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    main()
