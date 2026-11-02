import logging
import os
import subprocess
import sys
import threading

from utils_local.runtime_logging import (
    RuntimeFormatter,
    StageMonitor,
    log_level_from_text,
    redact_log_text,
    rotating_log_handler,
)


def test_runtime_logs_redact_stream_credentials_secret_fields_and_environment(monkeypatch):
    monkeypatch.setenv("KAFKA_SASL_PASSWORD", "fixture-kafka-private")
    monkeypatch.setenv("JWT_SECRET_KEY", "private spaced signing key")
    monkeypatch.setenv("MINEMAP_KEY", "xy7")
    value = redact_log_text(
        'rtsp://pilot:camera-private@example.test/live?token=stream-private '
        'password="db-private" sasl=fixture-kafka-private key=private spaced signing key map=xy7'
    )
    assert "example.test/live" in value
    assert all(secret not in value for secret in (
        "camera-private", "stream-private", "db-private", "fixture-kafka-private", "spaced signing key", "xy7",
    ))


def test_authorization_and_quoted_secrets_are_fully_redacted():
    for value in (
        'Authorization: Bearer example.jwt.signature',
        '"Authorization": "Bearer example.jwt.signature"',
        "Authorization='Basic example.jwt.signature'",
        'password="example private password"',
    ):
        assert "example" not in redact_log_text(value)


def test_relay_preserves_structured_levels_and_traceback_continuations():
    assert log_level_from_text("2026-10-18 08:00:00,100 WARNING pid=1 pipeline=x n slow") == logging.WARNING
    assert log_level_from_text("2026-10-18T08:00:00.100Z WARNING pid=1 pipeline=x n slow") == logging.WARNING
    assert log_level_from_text("ERROR: server failed") == logging.ERROR
    assert log_level_from_text("Traceback (most recent call last):") == logging.ERROR
    assert log_level_from_text("  File fixture.py, line 1", logging.ERROR) == logging.ERROR


def test_log_rotation_is_bounded_private_and_includes_identity(tmp_path):
    log = logging.Logger("fixture.component", logging.INFO)
    handler = rotating_log_handler(tmp_path / "pipelines" / "pipe-test.log", pipeline_id="pipe-test")
    handler.maxBytes = 200
    handler.backupCount = 2
    log.addHandler(handler)
    try:
        for index in range(20):
            log.info("fixture number=%s", index)
    finally:
        handler.close()
    files = list((tmp_path / "pipelines").iterdir())
    assert len(files) == 3
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in files)
    assert (tmp_path / "pipelines").stat().st_mode & 0o777 == 0o700
    current = (tmp_path / "pipelines" / "pipe-test.log").read_text()
    assert "INFO pid=" in current
    assert "Z INFO" in current
    assert "pipeline=pipe-test fixture.component" in current


def test_platform_and_uvicorn_share_console_and_persistent_logging(tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", """
import logging
from utils_local.runtime_logging import configure_runtime_logging
configure_runtime_logging(persist=True)
logging.getLogger('app.startup').info('PLATFORM_READY')
logging.getLogger('uvicorn.access').info('GET /health 200')
logging.getLogger('uvicorn.error').error('server fixture')
"""],
        env={**os.environ, "TRAFFIC_LOG_DIR": str(tmp_path)},
        text=True, capture_output=True, check=True,
    )
    output = (tmp_path / "platform.log").read_text()
    for marker in ("PLATFORM_READY", "GET /health 200", "server fixture"):
        assert marker in output
        assert marker in result.stdout
    assert "ERROR pid=" in output


def test_stage_begin_precedes_work_and_repeated_fast_frames_do_not_flood(caplog):
    monitor = StageMonitor()
    try:
        with caplog.at_level(logging.INFO, logger="pipeline.stage"):
            for _ in range(10):
                with monitor.stage("fixture.decode"):
                    assert any("STAGE_BEGIN" in record.message for record in caplog.records)
        assert len(caplog.records) == 2
        assert "STAGE_END" in caplog.records[-1].message
    finally:
        monitor.close()


def test_watchdog_reports_an_unfinished_stage_before_it_returns(caplog, monkeypatch):
    import utils_local.runtime_logging as module
    monitor = StageMonitor()
    reported = threading.Event()

    class Once:
        calls = 0

        def wait(self, _timeout):
            self.calls += 1
            return self.calls > 1

    try:
        monitor.close()
        monitor._stop = Once()
        with caplog.at_level(logging.INFO, logger="pipeline.stage"):
            with monitor.stage("ascend.om_execute"):
                started = monitor._active[-1]["started"]
                monkeypatch.setattr(module.time, "monotonic", lambda: started + 6)
                monitor._watch()
                reported.set()
                assert "STAGE_WAIT stage=ascend.om_execute" in caplog.records[-1].message
                assert not any("STAGE_END" in record.message for record in caplog.records)
        assert reported.is_set()
    finally:
        # The real daemon was already stopped; Once only drives a deterministic tick.
        monitor._thread.join(timeout=1)


def test_watchdog_reports_slow_parent_while_short_child_stages_keep_changing(caplog, monkeypatch):
    import utils_local.runtime_logging as module
    monitor = StageMonitor()
    monitor.close()

    class Once:
        calls = 0

        def wait(self, _timeout):
            self.calls += 1
            return self.calls > 1

    monitor._stop = Once()
    with caplog.at_level(logging.INFO, logger="pipeline.stage"):
        with monitor.stage("bytetrack.shadow_gate", tracks=128, detections=256):
            started = monitor._active[-1]["started"]
            monkeypatch.setattr(module.time, "monotonic", lambda: started + 6)
            with monitor.stage("bytetrack.mahalanobis_solve"):
                monitor._watch()
    waits = [record.message for record in caplog.records if "STAGE_WAIT" in record.message]
    assert len(waits) == 1
    assert "stage=bytetrack.shadow_gate" in waits[0]
    assert "tracks=128 detections=256" in waits[0]
    assert "cpu_ms=" in waits[0]
    assert "cpu_threads=" in waits[0]


def test_exception_traceback_is_redacted_by_the_same_formatter():
    try:
        raise RuntimeError("rtsp://operator:private-camera@example.test/live")
    except RuntimeError:
        import sys
        record = logging.LogRecord("fixture", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    formatted = RuntimeFormatter("pipe-test").format(record)
    assert "Traceback" in formatted
    assert "RuntimeError" in formatted
    assert "private-camera" not in formatted


def test_cpu_fields_report_cgroup_quota_and_counters_without_secrets(monkeypatch):
    import utils_local.runtime_logging as module
    from pathlib import Path

    contents = {
        '/proc/self/status': 'Name:\tpython\nThreads:\t12\n',
        '/proc/self/cgroup': '0::/\n',
        '/sys/fs/cgroup/cpu.max': '250000 100000\n',
        '/sys/fs/cgroup/cpu.stat': 'usage_usec 123\nnr_throttled 7\nthrottled_usec 456\n',
    }
    monkeypatch.setattr(Path, 'read_text', lambda path: contents[str(path)])
    monkeypatch.setattr(Path, 'is_file', lambda path: str(path) in contents)
    rendered = module._cpu_fields()
    assert 'cpu_threads=12' in rendered and 'cpu_quota=2.5' in rendered
    assert 'nr_throttled=7' in rendered and 'throttled_usec=456' in rendered


def test_unavailable_process_diagnostics_cannot_interrupt_a_frame(monkeypatch):
    import utils_local.runtime_logging as module
    from pathlib import Path

    def denied(_path):
        raise PermissionError('fixture restricted procfs')

    monkeypatch.setattr(Path, 'read_text', denied)
    assert 'cpu_threads=unavailable' in module._cpu_fields()


def test_terminated_stage_is_not_reported_as_completed(caplog):
    import pytest
    monitor = StageMonitor()
    try:
        with caplog.at_level(logging.INFO, logger='pipeline.stage'):
            with pytest.raises(SystemExit):
                with monitor.stage('fixture.terminated'):
                    raise SystemExit(143)
        ending = next(r.message for r in caplog.records if 'STAGE_END' in r.message)
        assert 'status=interrupted' in ending and 'status=completed' not in ending
    finally:
        monitor.close()
