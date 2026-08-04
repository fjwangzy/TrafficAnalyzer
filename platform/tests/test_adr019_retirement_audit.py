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


def test_mac_local_platform_uses_persistent_evidence_storage():
    script = (ROOT / "scripts" / "mac_local_platform.sh").read_text(encoding="utf-8")
    assert 'LOCAL_SURVEY_STORAGE_DIR="${SURVEY_STORAGE_DIR:-$PROJECT_ROOT/.runtime/survey}"' in script
    assert 'mkdir -p "$LOCAL_SURVEY_STORAGE_DIR"' in script
    assert 'SURVEY_STORAGE_DIR="$LOCAL_SURVEY_STORAGE_DIR"' in script


def test_mac_local_platform_defaults_detector_frame_stride_to_three():
    script = (ROOT / "scripts" / "mac_local_platform.sh").read_text(encoding="utf-8")
    assert 'PIPELINE_FRAME_STRIDE="${PIPELINE_FRAME_STRIDE:-3}"' in script


def test_mac_local_platform_fails_closed_on_duplicate_uvicorn_instances():
    script = (ROOT / "scripts" / "mac_local_platform.sh").read_text(encoding="utf-8")
    assert "platform_instance_pids" in script
    assert "launchd_platform_pid" in script
    assert "assert_single_platform" in script
    assert "Platform single-instance check failed" in script
