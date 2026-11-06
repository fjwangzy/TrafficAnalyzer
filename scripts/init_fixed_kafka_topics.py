#!/usr/bin/env python3
"""Explicit topic initialization. Application startup never creates topics."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kafka.admin import KafkaAdminClient, NewTopic
from utils_local.kafka_security import kafka_security_options
from utils_local.replay_topics import FIXED_TOPICS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", required=True)
    parser.add_argument("--partitions", type=int, default=3)
    parser.add_argument("--replication-factor", type=int, required=True)
    args = parser.parse_args()
    if args.partitions < 1 or args.replication_factor < 1:
        parser.error("partitions and replication factor must be positive")
    admin = KafkaAdminClient(
        bootstrap_servers=args.bootstrap, **kafka_security_options()
    )
    try:
        existing = set(admin.list_topics())
        missing = [
            NewTopic(name, args.partitions, args.replication_factor)
            for name in FIXED_TOPICS.values()
            if name not in existing
        ]
        if missing:
            admin.create_topics(missing)
        from utils_local.kafka_topic_preflight import inspect_topics
        inspect_topics(admin, partitions=args.partitions, replication_factor=args.replication_factor)
    finally:
        admin.close()


if __name__ == "__main__":
    main()
