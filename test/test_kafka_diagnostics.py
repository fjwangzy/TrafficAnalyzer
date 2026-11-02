import importlib.util
import json
from pathlib import Path
import socket
import sys
from types import SimpleNamespace

import pytest


spec = importlib.util.spec_from_file_location(
    "kafka_diagnostics", Path(__file__).resolve().parents[1] / "deploy/intranet/diagnose_kafka.py")
diagnostics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostics)


def test_tcp_probe_real_loopback_and_refused_port():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        endpoint = f"127.0.0.1:{server.getsockname()[1]}"
        assert diagnostics.tcp_probe(endpoint)["status"] == "passed"
    failure = diagnostics.tcp_probe(endpoint)
    assert failure["status"] == "failed"
    assert failure["errno"] is not None


@pytest.mark.parametrize("endpoint", ["user:secret@host:9093", "host:0", "host:65536", "host/path:9093"])
def test_endpoint_rejects_credentials_paths_and_invalid_ports(endpoint):
    with pytest.raises(ValueError):
        diagnostics.endpoint_parts(endpoint)


def test_ipv6_endpoint():
    assert diagnostics.endpoint_parts("[::1]:9093") == ("::1", 9093)


@pytest.mark.asyncio
async def test_metadata_uses_no_group_or_commit_and_keeps_advertised_addresses(monkeypatch):
    import aiokafka
    observed = {}
    class Consumer:
        def __init__(self, **kwargs):
            observed.update(kwargs)
            broker = SimpleNamespace(nodeId=7, host="broker.internal", port=9093)
            async def lookup(kind, group):
                assert (kind, group) == (0, "business-group")
                return 7
            self._client = SimpleNamespace(cluster=SimpleNamespace(brokers=lambda: [broker]),
                                           coordinator_lookup=lookup)
        async def start(self):
            pass
        async def topics(self):
            return {"uav_statistics_1", "other"}
        async def stop(self):
            observed["closed"] = True
    monkeypatch.setattr(aiokafka, "AIOKafkaConsumer", Consumer)
    result = await diagnostics.metadata_probe("bootstrap:9093", {}, 1, "business-group")
    assert observed["group_id"] is None and observed["enable_auto_commit"] is False
    assert observed["closed"] is True
    assert result["status"] == "passed" and result["uav_topics"] == 1
    assert result["brokers"][0]["host"] == "broker.internal"
    assert result["group_coordinator"]["joined_group"] is False


@pytest.mark.asyncio
async def test_metadata_failure_closes_client_and_never_echoes_secrets(monkeypatch):
    import aiokafka
    closed = []
    class Consumer:
        def __init__(self, **kwargs):
            pass
        async def start(self):
            raise RuntimeError("private-password secret connection string")
        async def stop(self):
            closed.append(True)
    monkeypatch.setattr(aiokafka, "AIOKafkaConsumer", Consumer)
    report = await diagnostics.metadata_probe("host:9093", {}, 1)
    assert report["error_type"] == "RuntimeError" and closed == [True]
    assert "private-password" not in json.dumps(report)


def test_producer_library_check_only_requests_metadata(monkeypatch):
    import kafka
    observed = []
    class Client:
        def __init__(self, **kwargs):
            self.config = {"api_version": (3, 0)}
            self.cluster = SimpleNamespace(request_update=lambda: SimpleNamespace(
                is_done=True, failed=lambda: False))
        def poll(self, **kwargs):
            observed.append("poll")
        def close(self):
            observed.append("close")
    monkeypatch.setattr(kafka, "KafkaClient", Client)
    result = diagnostics.producer_client_probe("host:9093", {})
    assert result["status"] == "passed" and result["publishes_messages"] is False
    assert observed == ["poll", "close"]


def test_failure_extraction_discards_raw_subprocess_output():
    report = diagnostics.extract_worker({"returncode": 1, "stdout": "PASSWORD=private-secret"})
    assert "private-secret" not in json.dumps(report)
    assert report["worker_error"]["returncode"] == 1


def test_subprocess_timeout_is_bounded_and_never_exports_partial_output():
    report = diagnostics.command_result([sys.executable, "-c",
        "import time; print('private-secret', flush=True); time.sleep(10)"], timeout=0.1)
    assert report["error_type"] == "TimeoutExpired"
    assert "private-secret" not in json.dumps(report)


def test_findings_separate_bridge_failure_from_metadata_and_slow_preflight():
    report = {
        "host_tcp": [{"endpoint": "host:9093", "status": "passed"}],
        "container": {
            "bootstrap_tcp": [{"endpoint": "host:9093", "status": "failed"}],
            "per_broker_metadata": [{"bootstrap": "host:9093", "status": "failed", "error_type": "TimeoutError"}],
            "preflight_30s": {"status": "failed"}, "extended_60s": {"status": "passed"},
        },
    }
    findings = "\n".join(diagnostics.conclusions(report))
    assert "HOST_OK_CONTAINER_FAILED" in findings and "LONGER_PROBE_PASSED" in findings
    assert "METADATA_PASSED_NOW" not in findings and "ACL_NOT_FULLY_EVALUATED" in findings


def test_docker_inspection_exports_whitelist_only(monkeypatch):
    identifier = "a" * 64
    def command(command, **kwargs):
        if "ps" in command:
            return {"stdout": identifier, "returncode": 0}
        return {"stdout": json.dumps([{
            "Config": {"Env": ["KAFKA_BOOTSTRAP=host:9093", "KAFKA_SASL_PASSWORD=private-secret",
                                "JWT_SECRET_KEY=another-secret"]},
            "Image": "sha256:abc", "HostConfig": {"NetworkMode": "bridge"},
            "NetworkSettings": {"Networks": {"my-network": {}}}, "State": {"Status": "running"},
        }]), "returncode": 0}
    monkeypatch.setattr(diagnostics, "command_result", command)
    result = diagnostics.docker_evidence(Path("/wrapper"), [])
    encoded = json.dumps(result)
    assert "private-secret" not in encoded and "another-secret" not in encoded
    assert result["platform_containers"][0]["credential_present"] is True


def test_host_collects_report_even_when_container_does_not_start(monkeypatch, tmp_path):
    (tmp_path / "docker-compose").touch()
    removed = []
    def command(command, **kwargs):
        if command[:3] == ["docker", "rm", "-f"]:
            removed.append(command[-1])
        return {"returncode": 1, "stdout": "password=must-not-be-exported"}
    monkeypatch.setattr(diagnostics, "command_result", command)
    monkeypatch.setattr(diagnostics, "network_evidence", lambda: {})
    monkeypatch.setattr(diagnostics, "tcp_probes", lambda endpoints: [])
    args = SimpleNamespace(deployment_root=str(tmp_path), output=str(tmp_path / "out"),
                           kafka_bin=None, client_properties=None)
    assert diagnostics.host_main(args) == 2
    report = (tmp_path / "out/report.json").read_text()
    assert "CONTAINER_CHECK_INCOMPLETE" in report and "must-not-be-exported" not in report
    assert len(removed) == 1 and removed[0].startswith("uav-kafka-diag-")
    assert (tmp_path / "out/report.json").stat().st_mode & 0o077 == 0
