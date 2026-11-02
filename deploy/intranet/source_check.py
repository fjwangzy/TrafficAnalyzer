#!/usr/bin/env python3
"""Read-only source/dependency and installed schema checks for source upgrades."""

import asyncio
import os
from pathlib import Path
import sys


def main():
    # Import checks can run alongside Platform; its rotating file must stay private.
    os.environ["TRAFFIC_LOG_DIR"] = str(Path(os.environ.get("TRAFFIC_LOG_DIR", "/var/log/traffic-analyzer")) / "source-check")
    root = Path(__file__).resolve().parents[2]
    for path in root.rglob("*.py"):
        if not any(part in {"weights", "test_videos", "logs"} for part in path.relative_to(root).parts):
            compile(path.read_bytes(), str(path), "exec")
    import app.main  # noqa: F401
    import main_optimized  # noqa: F401
    if "--database" in sys.argv:
        from app.core.database import close_db, validate_database

        async def database():
            try:
                await validate_database()
            finally:
                await close_db()

        asyncio.run(database())
    print("Source syntax, imports and requested read-only schema checks passed")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        from app.core.deployment_diagnostics import Report

        report = Report()
        report.error("sources.read_only_check", exc)
        report.emit()
        sys.exit(1)
