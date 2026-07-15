import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "audit_adr019_retirement.py"


def test_adr019_audit_is_machine_readable_and_truthfully_blocked():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--format", "json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "uav.adr019-retirement-audit/v1"
    assert payload["ready"] is False
    statuses = {item["code"]: item["status"] for item in payload["checks"]}
    assert statuses["platform_runtime_no_influx_import"] == "pass"
    assert statuses["target_platform_no_influx_dependency"] == "pass"
    assert statuses["target_platform_migration_and_readiness_assets"] == "pass"
    assert statuses["console_no_legacy_datasource"] == "pass"
    assert statuses["local_target_compose_road9_only"] == "pass"
    assert statuses["local_road9_restore_drill"] == "pass"
    assert statuses["local_empty_migration_rollback_drill"] == "pass"
    assert statuses["legacy_influx_read_only_inventory"] == "pass"
    assert statuses["local_non_contract_performance_smoke"] == "pass"
    assert statuses["local_isolated_database_outage_recovery"] == "pass"
    assert statuses["local_full_target_stack"] == "pass"
    assert statuses["local_non_contract_readiness_soak"] == "pass"
    assert statuses["compose_no_legacy_services"] == "blocker"
    assert statuses["retirement_approval_inputs"] == "blocked_external"


def test_adr019_strict_gate_fails_until_retirement_is_safe():
    result = subprocess.run([sys.executable, str(SCRIPT), "--strict"], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 1
    assert "ADR-019 retirement ready: False" in result.stdout


def test_restore_drill_refuses_to_touch_docker_without_explicit_guard():
    script = ROOT / "scripts" / "validate_road9_backup_restore.py"
    result = subprocess.run([sys.executable, str(script)], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode != 0
    assert "ALLOW_LOCAL_RESTORE_DRILL=1" in result.stderr
