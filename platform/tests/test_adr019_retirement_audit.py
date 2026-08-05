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
    assert 'DEFAULT_SURVEY_STORAGE_DIR="$PROJECT_ROOT/.runtime/survey"' in script
    assert "/private/tmp/traffic-analyzer-replay-v2-survey" not in script
    assert 'LOCAL_SURVEY_STORAGE_DIR="${SURVEY_STORAGE_DIR:-$DEFAULT_SURVEY_STORAGE_DIR}"' in script
    assert 'mkdir -p "$LOCAL_SURVEY_STORAGE_DIR"' in script
    assert 'SURVEY_STORAGE_DIR="$LOCAL_SURVEY_STORAGE_DIR"' in script


def test_mac_local_platform_defaults_detector_frame_stride_to_three():
    script = (ROOT / "scripts" / "mac_local_platform.sh").read_text(encoding="utf-8")
    assert 'PIPELINE_FRAME_STRIDE="${PIPELINE_FRAME_STRIDE:-3}"' in script


def test_mac_local_platform_does_not_override_platform_dotenv_with_empty_ycx_values():
    script = (ROOT / "scripts" / "mac_local_platform.sh").read_text(encoding="utf-8")
    for key in (
        "YCX_DB_HOST",
        "YCX_DB_PORT",
        "YCX_DB_USER",
        "YCX_DB_PASSWORD",
        "YCX_DB_NAME",
        "YCX_DB_SCHEMA",
        "YCX_METRICS_SCHEMA",
    ):
        assert f'{key}="${{{key}:-}}"' not in script


def test_mac_local_platform_fails_closed_on_duplicate_uvicorn_instances():
    script = (ROOT / "scripts" / "mac_local_platform.sh").read_text(encoding="utf-8")
    assert "platform_instance_pids" in script
    assert "launchd_platform_pid" in script
    assert "assert_single_platform" in script
    assert "Platform single-instance check failed" in script


def test_mac_local_platform_supports_a_named_replay_v2_instance_without_replacing_live_demo():
    script = (ROOT / "scripts" / "mac_local_platform.sh").read_text(encoding="utf-8")
    assert 'PLATFORM_INSTANCE="${PLATFORM_INSTANCE:-live}"' in script
    assert 'traffic-analyzer-local-platform-${PLATFORM_INSTANCE}-${UID}' in script
    assert 'com.traffic-analyzer.local-platform-${PLATFORM_INSTANCE}-${UID}' in script
    assert 'APP_RUNTIME_PROFILE="${APP_RUNTIME_PROFILE:-live}"' in script
