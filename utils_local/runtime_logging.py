"""Bounded runtime logs and low-frequency evidence for stalled pipeline stages."""

from __future__ import annotations

from contextlib import contextmanager
import logging
import json
from collections import deque
from contextlib import nullcontext
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import sys
import threading
import time


LOG_MAX_BYTES = 20 * 1024 * 1024
LOG_BACKUP_COUNT = 5
_LOG_LEVEL = re.compile(r"^(?:\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[,.]\d+)?(?:Z|[+-]\d{2}:\d{2})?\s+)?(DEBUG|INFO|WARNING|ERROR|CRITICAL)(?=[:\s\[])")
_URL_AUTH = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/\s@]+@")
_AUTHORIZATION = re.compile(
    r"(?i)((?:authorization|proxy-authorization)[\"']?\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|(?:bearer|basic)\s+[^\s,;}]+|[^\s,;}]+)"
)
_SECRET_FIELD = re.compile(
    r"(?i)((?:password|passwd|pwd|secret|access_token|token|authorization|api_key)"
    r"[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;&\"'}]+)"
)
_SECRET_ENV = re.compile(r"(?:^|_)(?:PASSWORD|PASSWD|SECRET|SECRET_KEY|TOKEN|API_KEY|ACCESS_KEY|KEY)$")


def redact_log_text(value: str) -> str:
    for name, secret in os.environ.items():
        if secret and _SECRET_ENV.search(name.upper()):
            value = value.replace(secret, "[redacted]")
    value = _URL_AUTH.sub(r"\1[redacted]@", value)
    value = _AUTHORIZATION.sub(r"\1[redacted]", value)
    value = _SECRET_FIELD.sub(r"\1[redacted]", value)
    return value


def log_level_from_text(value: str, default: int = logging.INFO) -> int:
    if value.lstrip().startswith("Traceback (most recent call last):"):
        return logging.ERROR
    match = _LOG_LEVEL.match(value.lstrip())
    return getattr(logging, match.group(1)) if match else default


def runtime_log_dir(project_root: str | Path | None = None) -> Path:
    return Path(os.environ.get("TRAFFIC_LOG_DIR") or (Path(project_root or Path(__file__).resolve().parents[1]) / "logs"))


class RuntimeFormatter(logging.Formatter):
    converter = time.gmtime

    def __init__(self, pipeline_id: str | None = None):
        super().__init__(
            "%(asctime)s.%(msecs)03dZ %(levelname)s pid=%(process)d pipeline=%(pipeline_id)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        self.pipeline_id = pipeline_id or os.environ.get("PIPELINE_ID") or "-"

    def format(self, record):
        record.pipeline_id = self.pipeline_id
        return redact_log_text(super().format(record))


class PrivateRotatingFileHandler(RotatingFileHandler):
    def _open(self):
        descriptor = os.open(self.baseFilename, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        os.fchmod(descriptor, 0o600)
        return os.fdopen(descriptor, self.mode, encoding=self.encoding, errors=self.errors)


def rotating_log_handler(path: Path, *, pipeline_id: str | None = None):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.name == "pipelines":
        path.parent.chmod(0o700)
    handler = PrivateRotatingFileHandler(path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8")
    handler.setFormatter(RuntimeFormatter(pipeline_id))
    return handler


def configure_runtime_logging(*, persist: bool = False) -> None:
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(RuntimeFormatter())
    root.addHandler(console)
    if persist:
        root.addHandler(rotating_log_handler(runtime_log_dir() / "platform.log"))
    root.setLevel(logging.INFO)
    # Uvicorn installs its own non-propagating loggers before importing app.main.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        log = logging.getLogger(name)
        log.handlers.clear()
        log.propagate = True


def _cpu_fields() -> str:
    facts = {"cpu_threads": "unavailable", "cpu_allowed": os.cpu_count(),
             "cpu_quota": "unavailable", "nr_throttled": "unavailable", "throttled_usec": "unavailable"}
    try:
        if hasattr(os, "sched_getaffinity"):
            facts["cpu_allowed"] = len(os.sched_getaffinity(0))
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("Threads:"):
                facts["cpu_threads"] = int(line.split()[1])
        root = Path("/sys/fs/cgroup")
        group = root
        for line in Path("/proc/self/cgroup").read_text().splitlines():
            if line.startswith("0::"):
                candidate = (root / line[3:].lstrip("/")).resolve()
                if candidate.is_relative_to(root) and (candidate / "cpu.max").is_file():
                    group = candidate
        quota, period = (group / "cpu.max").read_text().split()
        facts["cpu_quota"] = "unlimited" if quota == "max" else round(int(quota) / int(period), 3)
        counters = dict(line.split() for line in (group / "cpu.stat").read_text().splitlines())
        for name in ("nr_throttled", "throttled_usec"):
            facts[name] = int(counters[name]) if name in counters else "unavailable"
    except (OSError, ValueError, ZeroDivisionError):
        # Non-Linux/cgroup-v1 hosts keep unavailable fields; diagnostics must not stop a frame.
        pass
    return " ".join(f"{name}={value}" for name, value in facts.items())


class StageMonitor:
    """One daemon per worker reports an unfinished stage without frame-log floods."""

    def __init__(self, *, interval_sec: float = 30.0, slow_sec: float = 1.0):
        self.interval_sec = interval_sec
        self.slow_sec = slow_sec
        self._lock = threading.Lock()
        self._metrics = {}
        self._metrics_at = time.monotonic()
        self.audit = os.environ.get("PIPELINE_PERF_AUDIT", "0").lower() in {"1", "true"}
        self._active = []
        self._reported = {}
        self._wait_reported = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, name="pipeline-stage-watchdog", daemon=True)
        self._thread.start()

    @contextmanager
    def stage(self, name: str, **fields):
        started = time.monotonic()
        cpu_started = time.process_time()
        details = " ".join(f"{key}={value}" for key, value in fields.items())
        token = {"name": name, "started": started, "cpu_started": cpu_started, "details": details}
        with self._lock:
            sampled = name not in self._reported or started - self._reported[name] >= self.interval_sec
            self._active.append(token)
            if sampled:
                self._reported[name] = started
        log = logging.getLogger("pipeline.stage")
        if sampled:
            log.info("STAGE_BEGIN stage=%s %s %s", name, details, _cpu_fields())
        status = "completed"
        try:
            yield
        except BaseException as exc:
            status = "failed" if isinstance(exc, Exception) else "interrupted"
            if status == "failed":
                log.exception("STAGE_FAILED stage=%s elapsed_ms=%.1f %s", name, (time.monotonic() - started) * 1000, details)
            raise
        finally:
            elapsed = time.monotonic() - started
            with self._lock:
                self._active.remove(token)
                if self.audit:
                    self._observe_locked(name, elapsed * 1000)
                report_slow = elapsed >= self.slow_sec and time.monotonic() - self._reported.get(name, 0) >= self.interval_sec
                if report_slow:
                    self._reported[name] = time.monotonic()
            if sampled or report_slow:
                log.log(logging.WARNING if elapsed >= self.slow_sec else logging.INFO,
                        "STAGE_END stage=%s elapsed_ms=%.1f cpu_ms=%.1f status=%s %s %s", name, elapsed * 1000,
                        (time.process_time() - cpu_started) * 1000, status, details, _cpu_fields())

    def _watch(self):
        while not self._stop.wait(1.0):
            now = time.monotonic()
            if self.audit and now - self._metrics_at >= self.interval_sec:
                self.flush_metrics()
            with self._lock:
                token = next((item for item in reversed(self._active) if now - item["started"] >= 5.0), None)
                if token is None or now - self._wait_reported.get(token["name"], now - self.interval_sec) < self.interval_sec:
                    continue
                self._wait_reported[token["name"]] = now
                name, started, cpu_started, details = token["name"], token["started"], token["cpu_started"], token["details"]
            logging.getLogger("pipeline.stage").warning(
                "STAGE_WAIT stage=%s elapsed_ms=%.1f cpu_ms=%.1f %s %s", name, (now - started) * 1000,
                (time.process_time() - cpu_started) * 1000, details, _cpu_fields(),
            )

    def _observe_locked(self, name, elapsed_ms):
        metric = self._metrics.setdefault(name, {"count": 0, "total_ms": 0.0, "samples": deque(maxlen=4096)})
        metric["count"] += 1
        metric["total_ms"] += elapsed_ms
        metric["samples"].append(elapsed_ms)

    def observe(self, name, elapsed_ms):
        if self.audit:
            with self._lock:
                self._observe_locked(name, elapsed_ms)

    def flush_metrics(self):
        with self._lock:
            metrics, self._metrics = self._metrics, {}
            elapsed = time.monotonic() - self._metrics_at
            self._metrics_at = time.monotonic()
        for name, metric in metrics.items():
            values = sorted(metric.pop("samples"))
            for q in (50, 95, 99):
                metric[f"p{q}_ms"] = values[min(len(values)-1, int((len(values)-1)*q/100))]
            metric.update(stage=name, window_sec=elapsed, percentile_samples=len(values), pid=os.getpid())
            logging.getLogger("pipeline.perf").info("PERF_SUMMARY %s", json.dumps(metric, sort_keys=True))

    def close(self):
        self._stop.set()
        if self.audit:
            self.flush_metrics()
        self._thread.join(timeout=2)


_monitor = None
_monitor_pid = None


def stage(name: str, **fields):
    global _monitor, _monitor_pid
    if _monitor is None or _monitor_pid != os.getpid():
        _monitor = StageMonitor()
        _monitor_pid = os.getpid()
    return _monitor.stage(name, **fields)


def run_stage(name, function, *args, **kwargs):
    with stage(name):
        return function(*args, **kwargs)


def audit_stage(name, **fields):
    """Detailed probes are opt-in; normal runs pay no monitor/SQL-loop logging cost."""
    if os.environ.get("PIPELINE_PERF_AUDIT", "0").lower() not in {"1", "true"}:
        return nullcontext()
    return stage(name, **fields)


def audit_observe(name, elapsed_ms):
    if os.environ.get("PIPELINE_PERF_AUDIT", "0").lower() in {"1", "true"}:
        global _monitor, _monitor_pid
        if _monitor is None or _monitor_pid != os.getpid():
            _monitor = StageMonitor()
            _monitor_pid = os.getpid()
        _monitor.observe(name, elapsed_ms)
