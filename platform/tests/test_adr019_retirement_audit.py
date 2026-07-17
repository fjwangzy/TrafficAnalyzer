import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "audit_adr019_retirement.py"


def test_adr019_production_audit_is_machine_readable_and_truthfully_blocked():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--scope", "production", "--format", "json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "uav.adr019-retirement-audit/v2"
    assert payload["scope"] == "production"
    assert payload["ready"] is False
    statuses = {item["code"]: item["status"] for item in payload["checks"]}
    assert statuses["canonical_root_compose"] == "pass"
    assert statuses["platform_no_legacy_database_or_influx"] == "pass"
    assert statuses["canonical_runtime_contract_only"] == "pass"
    assert statuses["legacy_runtime_assets_removed"] == "pass"
    assert statuses["production_retirement_approval"] == "blocked_external"


def test_adr019_strict_gate_fails_until_retirement_is_safe():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--scope", "production", "--strict"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "ADR-019 retirement scope=production ready: False" in result.stdout


def test_restore_drill_refuses_to_touch_docker_without_explicit_guard():
    script = ROOT / "scripts" / "validate_road9_backup_restore.py"
    result = subprocess.run([sys.executable, str(script)], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode != 0
    assert "ALLOW_LOCAL_RESTORE_DRILL=1" in result.stderr
