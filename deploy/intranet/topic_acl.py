#!/usr/bin/env python3
"""Print concrete Topic/Group ACL requirements for approved source keys."""

import argparse
import json
import re


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-key", action="append", required=True)
    args = parser.parse_args()
    topics = []
    for source in sorted(set(args.source_key)):
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", source):
            parser.error("Unsupported source_key")
        for kind in ("statistics", "track_complete", "conflicts", "telemetry", "mission", "enforcement_clues"):
            topics.append({"topic": f"uav_replay_v2_{kind}_{source}",
                           "operations": ["Write", "Describe"] + ([] if kind == "enforcement_clues" else ["Read"])})
    print(json.dumps({"topics": topics, "groups": [{"group": "uav-platform-replay-v2", "operations": ["Read", "Describe"]}]}, indent=2))


if __name__ == "__main__":
    main()
