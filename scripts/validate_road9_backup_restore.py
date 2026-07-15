#!/usr/bin/env python3
"""Run a guarded local pg_dump/pg_restore drill inside a TimescaleDB container."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time


def run(args: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(args, check=True, capture_output=capture, text=True)
    return result.stdout.strip() if capture else ""


def exec_db(container: str, user: str, database: str, sql: str) -> str:
    return run(
        ["docker", "exec", container, "psql", "-X", "-A", "-t", "-U", user, "-d", database, "-c", sql],
        capture=True,
    )


def table_counts(container: str, user: str, database: str) -> dict[str, int]:
    tables = exec_db(
        container, user, database,
        "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'uav_%' ORDER BY tablename",
    ).splitlines()
    result = {}
    for table in tables:
        if not re.fullmatch(r"uav_[a-z0-9_]+", table):
            raise RuntimeError(f"unsafe table name returned by PostgreSQL: {table}")
        result[table] = int(exec_db(container, user, database, f'SELECT count(*) FROM "{table}"'))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", default=os.environ.get("ROAD9_CONTAINER", "traffic_timescaledb_local"))
    parser.add_argument("--user", default=os.environ.get("ROAD9_USER", "traffic"))
    parser.add_argument("--source", default=os.environ.get("ROAD9_DB", "road9"))
    parser.add_argument("--restore", default=f"road9_restore_{int(time.time())}")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    if os.environ.get("ALLOW_LOCAL_RESTORE_DRILL") != "1":
        raise SystemExit("refusing restore drill: set ALLOW_LOCAL_RESTORE_DRILL=1")
    if args.source != "road9" or not re.fullmatch(r"road9_restore_[a-zA-Z0-9_]+", args.restore):
        raise SystemExit("refusing unsafe database names; source must be road9 and restore must start road9_restore_")
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", args.container) or not re.fullmatch(r"[a-zA-Z0-9_]+", args.user):
        raise SystemExit("refusing unsafe container/user value")

    dump_path = f"/tmp/{args.restore}.dump"
    restored = False
    pre_restore = False
    post_restore = False
    try:
        source_counts = table_counts(args.container, args.user, args.source)
        source_revision = exec_db(args.container, args.user, args.source, "SELECT version_num FROM uav_alembic_version LIMIT 1")
        source_timescale = exec_db(args.container, args.user, args.source, "SELECT extversion FROM pg_extension WHERE extname='timescaledb'")
        source_hypertables = int(exec_db(args.container, args.user, args.source, "SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_schema='public'"))

        run(["docker", "exec", args.container, "pg_dump", "-Fc", "-U", args.user, "-d", args.source, "-f", dump_path])
        run(["docker", "exec", args.container, "dropdb", "--if-exists", "--force", "-U", args.user, args.restore])
        run(["docker", "exec", args.container, "createdb", "-U", args.user, args.restore])
        restored = True
        exec_db(args.container, args.user, args.restore, "CREATE EXTENSION IF NOT EXISTS timescaledb")
        exec_db(args.container, args.user, args.restore, "SELECT timescaledb_pre_restore()")
        pre_restore = True
        run([
            "docker", "exec", args.container, "pg_restore", "--exit-on-error",
            "--no-owner", "--no-privileges", "-U", args.user, "-d", args.restore, dump_path,
        ])
        exec_db(args.container, args.user, args.restore, "SELECT timescaledb_post_restore()")
        post_restore = True

        restored_counts = table_counts(args.container, args.user, args.restore)
        restored_revision = exec_db(args.container, args.user, args.restore, "SELECT version_num FROM uav_alembic_version LIMIT 1")
        restored_timescale = exec_db(args.container, args.user, args.restore, "SELECT extversion FROM pg_extension WHERE extname='timescaledb'")
        restored_hypertables = int(exec_db(args.container, args.user, args.restore, "SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_schema='public'"))

        checks = {
            "table_counts_equal": source_counts == restored_counts,
            "migration_revision_equal": source_revision == restored_revision,
            "timescale_version_equal": source_timescale == restored_timescale,
            "hypertable_count_equal": source_hypertables == restored_hypertables,
        }
        payload = {
            "schema_version": "uav.road9-restore-drill/v1",
            "source": args.source,
            "restore": args.restore,
            "alembic_revision": source_revision,
            "timescaledb_version": source_timescale,
            "hypertables": source_hypertables,
            "uav_tables": len(source_counts),
            "rows": sum(source_counts.values()),
            "checks": checks,
            "passed": all(checks.values()),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["passed"] else 1
    finally:
        if restored and pre_restore and not post_restore:
            try:
                exec_db(args.container, args.user, args.restore, "SELECT timescaledb_post_restore()")
            except subprocess.CalledProcessError:
                pass
        if restored and not args.keep:
            run(["docker", "exec", args.container, "dropdb", "--if-exists", "--force", "-U", args.user, args.restore])
        run(["docker", "exec", args.container, "rm", "-f", dump_path])


if __name__ == "__main__":
    raise SystemExit(main())
