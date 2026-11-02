#!/usr/bin/env python3
"""Offline, read-only Kafka diagnosis from the deployment host and service network."""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid

MARKER = "UAV_KAFKA_REPORT="
DEFAULT_ENDPOINTS = [f"37.12.14.{number}:9093" for number in range(66, 70)]


def error_info(exc):
    # Exception values can contain credentials; retain only types and OS error codes.
    return {"status": "failed", "error_type": type(exc).__name__,
            "errno": getattr(exc, "errno", None)}


def endpoint_parts(endpoint):
    if endpoint.startswith("["):
        host, port = endpoint[1:].split("]:", 1)
    else:
        host, port = endpoint.rsplit(":", 1)
    if not host or any(char in host for char in "@/\\\n\r\t "):
        raise ValueError("Invalid broker endpoint")
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError("Invalid broker port")
    return host, port


def tcp_probe(endpoint):
    started = time.monotonic()
    result = {"endpoint": endpoint}
    try:
        host, port = endpoint_parts(endpoint)
        result["resolved_ips"] = sorted({item[4][0] for item in socket.getaddrinfo(
            host, port, type=socket.SOCK_STREAM)})
        with socket.create_connection((host, port), timeout=3) as connection:
            result.update(status="passed", local_ip=connection.getsockname()[0],
                          peer_ip=connection.getpeername()[0])
    except Exception as exc:
        result.update(error_info(exc))
    result["elapsed_sec"] = round(time.monotonic() - started, 3)
    return result


def tcp_probes(endpoints):
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(tcp_probe, sorted(set(endpoints))))


async def metadata_probe(bootstrap, options, timeout, group=None):
    from aiokafka import AIOKafkaConsumer
    consumer = None
    started = time.monotonic()
    result = {"bootstrap": bootstrap, "timeout_sec": timeout}
    try:
        consumer = AIOKafkaConsumer(bootstrap_servers=bootstrap, **options,
                                   group_id=None, enable_auto_commit=False,
                                   request_timeout_ms=10000,
                                   client_id="uav-readonly-kafka-diagnosis")
        async def fetch():
            await consumer.start()
            topics = await consumer.topics()
            result.update(status="passed", visible_topics=len(topics),
                          uav_topics=sum(topic.startswith("uav_") for topic in topics))
        await asyncio.wait_for(fetch(), timeout)
        result["metadata_elapsed_sec"] = round(time.monotonic() - started, 3)
        # shortcut: aiokafka has no public broker-list API; report extraction errors separately.
        try:
            result["brokers"] = [{"node_id": broker.nodeId, "host": broker.host,
                                  "port": broker.port}
                                 for broker in consumer._client.cluster.brokers()]
        except Exception as exc:
            result["broker_list"] = error_info(exc)
        if group:
            try:
                node = await asyncio.wait_for(consumer._client.coordinator_lookup(0, group), 10)
                result["group_coordinator"] = {"status": "passed", "node_id": node,
                                               "joined_group": False}
            except Exception as exc:
                result["group_coordinator"] = error_info(exc)
    except Exception as exc:
        result.update(error_info(exc))
    finally:
        if consumer is not None:
            try:
                await asyncio.wait_for(consumer.stop(), 5)
            except Exception as exc:
                result["close"] = error_info(exc)
    result["elapsed_sec"] = round(time.monotonic() - started, 3)
    return result


def producer_client_probe(bootstrap, options):
    """Use the detector's installed kafka-python client, without creating a producer."""
    client = None
    try:
        from kafka import KafkaClient
        client = KafkaClient(bootstrap_servers=bootstrap, **options,
                             client_id="uav-readonly-kafka-diagnosis",
                             request_timeout_ms=10000, api_version_auto_timeout_ms=10000)
        future = client.cluster.request_update()
        client.poll(future=future, timeout_ms=15000)
        if not future.is_done:
            raise TimeoutError()
        if future.failed():
            raise future.exception
        return {"status": "passed", "api_version": list(client.config["api_version"]),
                "publishes_messages": False}
    except Exception as exc:
        return error_info(exc)
    finally:
        if client is not None:
            client.close()


async def container_report():
    logging.disable(logging.CRITICAL)
    sys.path[:0] = ["/app/platform", "/app"]
    report = {"python": sys.version.split()[0], "writes_business_data": False}
    try:
        from app.core.config import settings
        endpoints = settings.kafka_bootstrap.split(",")
        endpoints = [item.strip() for item in endpoints]
        for endpoint in endpoints:
            endpoint_parts(endpoint)
        options = settings.kafka_security_options
        report["configuration"] = {
            "bootstrap": endpoints, "security_protocol": settings.kafka_security_protocol,
            "sasl_mechanism": settings.kafka_sasl_mechanism,
            "username_present": bool(settings.kafka_sasl_username),
            "credential_present": bool(settings.kafka_sasl_password),
            "consumer_group": settings.kafka_consumer_group,
        }
    except Exception as exc:
        report["configuration_error"] = error_info(exc)
        return report
    report["versions"] = {}
    for name in ("aiokafka", "kafka-python", "kafka-python-ng"):
        try:
            report["versions"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    report["bootstrap_tcp"] = await asyncio.to_thread(tcp_probes, endpoints)
    report["per_broker_metadata"] = await asyncio.gather(
        *(metadata_probe(endpoint, options, 20) for endpoint in endpoints))
    report["preflight_30s"] = await metadata_probe(settings.kafka_bootstrap, options, 30,
                                                  settings.kafka_consumer_group)
    if report["preflight_30s"]["status"] != "passed":
        report["extended_60s"] = await metadata_probe(settings.kafka_bootstrap, options, 60)
    brokers = [broker for item in report["per_broker_metadata"] + [report["preflight_30s"],
               report.get("extended_60s", {})] for broker in item.get("brokers", [])]
    advertised = set()
    for broker in brokers:
        host = broker["host"]
        endpoint = f"[{host}]:{broker['port']}" if ":" in host else f"{host}:{broker['port']}"
        endpoint_parts(endpoint)
        advertised.add(endpoint)
    report["advertised_tcp"] = await asyncio.to_thread(tcp_probes, advertised)
    report["advertised_metadata"] = await asyncio.gather(
        *(metadata_probe(endpoint, options, 20) for endpoint in sorted(advertised - set(endpoints))))
    report["producer_client_metadata"] = await asyncio.to_thread(
        producer_client_probe, settings.kafka_bootstrap, options)
    report["acl_limit"] = "No JoinGroup, Fetch, Produce, transaction, commit or topic creation; business ACL not proven."
    return report


def command_result(command, timeout=15, input_text=None):
    process = None
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, errors="replace",
                                   start_new_session=True)
        output, _ = process.communicate(input_text, timeout=timeout)
        # Callers explicitly select safe fields; never save raw subprocess stderr.
        return {"returncode": process.returncode, "stdout": output}
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        return error_info(exc)
    except Exception as exc:
        return error_info(exc)


def network_evidence():
    commands = {
        "addresses": ["ip", "-j", "address", "show"],
        "routes": ["ip", "-j", "route", "show", "table", "all"],
        "policy_rules": ["ip", "-j", "rule", "show"],
        "forwarding": ["sysctl", "net.ipv4.ip_forward", "net.ipv4.conf.all.rp_filter"],
        "firewalld": ["firewall-cmd", "--state"],
    }
    evidence = {}
    for name, command in commands.items():
        value = command_result(command)
        if "stdout" in value:
            if name in {"addresses", "routes", "policy_rules"}:
                try:
                    value["data"] = json.loads(value.pop("stdout"))
                except ValueError:
                    value.pop("stdout", None)
            else:
                value["data"] = value.pop("stdout").strip()
        evidence[name] = value
    for name, command in {
        "forward": ["iptables", "-S", "FORWARD"],
        "docker_user": ["iptables", "-S", "DOCKER-USER"],
        "nat": ["iptables", "-t", "nat", "-S", "POSTROUTING"],
    }.items():
        value = command_result(command)
        if "stdout" in value:
            value["rules"] = [re.sub(r' --comment (?:"[^"\n]*"|\S+)', "", line)
                              for line in value.pop("stdout").splitlines()]
        evidence[name] = value
    nft = command_result(["nft", "-j", "list", "ruleset"])
    if "stdout" in nft:
        try:
            rules = json.loads(nft.pop("stdout"))["nftables"]
            nft["chains"] = [{key: item["chain"][key] for key in
                              ("family", "table", "name", "type", "hook", "policy")
                              if key in item["chain"]} for item in rules if "chain" in item]
            nft["rules"] = [{"family": item["rule"].get("family"),
                             "table": item["rule"].get("table"), "chain": item["rule"].get("chain"),
                             "expr": [expr for expr in item["rule"].get("expr", []) if set(expr) <= {
                                 "match", "counter", "accept", "drop", "reject", "masquerade",
                                 "snat", "dnat", "jump", "goto", "return"}]}
                            for item in rules if "rule" in item]
        except (KeyError, ValueError):
            nft.pop("stdout", None)
    evidence["nft_chain_policies"] = nft
    return evidence


def extract_worker(result):
    for line in result.get("stdout", "").splitlines():
        if line.startswith(MARKER):
            try:
                report = json.loads(line[len(MARKER):])
                if isinstance(report, dict):
                    return report
            except ValueError:
                pass
    return {"worker_error": {key: value for key, value in result.items() if key != "stdout"},
            "hint": "No worker report. Check image import, service mounts/devices and Docker permission locally; raw output intentionally omitted."}


def docker_evidence(wrapper, network_definitions, diagnostic_container=None):
    evidence = {"networks": [], "platform_containers": []}
    ids = command_result([str(wrapper), "ps", "--all", "-q", "platform"])
    identifiers = [item for item in ids.get("stdout", "").splitlines()
                   if re.fullmatch(r"[0-9a-f]{12,64}", item)]
    if diagnostic_container:
        identifiers.append(diagnostic_container)
    network_definitions = set(network_definitions)
    for identifier in identifiers:
        result = command_result(["docker", "inspect", identifier])
        try:
            container = json.loads(result.get("stdout", ""))[0]
            environment = dict(item.split("=", 1) for item in container["Config"].get("Env", []) if "=" in item)
            networks = list(container["NetworkSettings"].get("Networks", {}))
            network_definitions.update(networks)
            bootstrap = environment.get("KAFKA_BOOTSTRAP")
            if bootstrap:
                try:
                    for endpoint in bootstrap.split(","):
                        endpoint_parts(endpoint.strip())
                except ValueError:
                    bootstrap = "invalid_endpoint_omitted"
            evidence["platform_containers"].append({
                "id": identifier, "image_id": container["Image"],
                "role": "diagnostic" if identifier == diagnostic_container else "existing",
                "status": container.get("State", {}).get("Status"),
                "network_mode": container["HostConfig"].get("NetworkMode"),
                "networks": networks, "bootstrap": bootstrap,
                "security_protocol": environment.get("KAFKA_SECURITY_PROTOCOL"),
                "sasl_mechanism": environment.get("KAFKA_SASL_MECHANISM"),
                "username_present": bool(environment.get("KAFKA_SASL_USERNAME")),
                "credential_present": bool(environment.get("KAFKA_SASL_PASSWORD")),
            })
        except (ValueError, KeyError, IndexError):
            evidence["platform_containers"].append({"id": identifier, "status": "inspect_unavailable"})
    for name in network_definitions:
        result = command_result(["docker", "network", "inspect", name])
        try:
            network = json.loads(result.get("stdout", ""))[0]
            evidence["networks"].append({
                "name": network["Name"], "driver": network["Driver"],
                "internal": network.get("Internal"),
                "ipam": network.get("IPAM", {}).get("Config"),
                "masquerade": network.get("Options", {}).get("com.docker.network.bridge.enable_ip_masquerade"),
            })
        except (ValueError, KeyError, IndexError):
            evidence["networks"].append({"name": name, "status": "unavailable"})
    return evidence


def conclusions(report):
    worker = report.get("container", {})
    host = {item["endpoint"]: item for item in report.get("host_tcp", [])}
    findings = []
    for item in worker.get("bootstrap_tcp", []) + worker.get("advertised_tcp", []):
        if item["status"] != "passed" and host.get(item["endpoint"], {}).get("status") == "passed":
            findings.append("HOST_OK_CONTAINER_FAILED: " + item["endpoint"] +
                            "；检查Docker转发/NAT、DOCKER-USER、路由、子网重叠及出口白名单。")
        elif item["status"] != "passed":
            findings.append("ENDPOINT_UNREACHABLE: " + item["endpoint"] +
                            "；核对两侧DNS/TCP、broker监听、路由及网络白名单。")
    for item in worker.get("per_broker_metadata", []) + worker.get("advertised_metadata", []):
        if item["status"] != "passed":
            findings.append("BROKER_METADATA_FAILED: " + item["bootstrap"] + " / " +
                            item.get("error_type", "unknown") +
                            "；TCP成功不等于SASL认证成功，对照CLI配置与broker认证日志。")
    if worker.get("extended_60s", {}).get("status") == "passed":
        findings.append("LONGER_PROBE_PASSED: 30秒失败、延长检查成功；检查慢连接、部分broker不可达及服务负载，勿直接绕过预检。")
    if worker.get("preflight_30s", {}).get("status") == "passed":
        findings.append("METADATA_PASSED_NOW: 本次应用认证/元数据成功；与故障时刻对照，仍需检查全部broker与实际运行容器差异。")
    effective = worker.get("configuration", {})
    for container in report.get("docker", {}).get("platform_containers", []):
        if container.get("role") != "existing":
            continue
        for field in ("security_protocol", "sasl_mechanism"):
            if container.get(field) and effective.get(field) and container[field] != effective[field]:
                findings.append("EXISTING_CONTAINER_CONFIG_DIFFERS: " + field + "；旧容器环境与当前部署配置不一致，核对后再安排重建。")
        if container.get("bootstrap") and effective.get("bootstrap"):
            if sorted(container["bootstrap"].split(",")) != sorted(effective["bootstrap"]):
                findings.append("EXISTING_CONTAINER_CONFIG_DIFFERS: bootstrap；旧容器地址与当前部署配置不同，核对后再安排重建。")
    coordinator = worker.get("preflight_30s", {}).get("group_coordinator", {})
    if coordinator.get("status") == "failed":
        findings.append("COORDINATOR_LOOKUP_FAILED: " + coordinator.get("error_type", "unknown") +
                        "；核对消费者组Describe权限与协调器状态；工具没有加入组。")
    producer = worker.get("producer_client_metadata", {})
    if producer.get("status") == "failed":
        findings.append("DETECTOR_CLIENT_METADATA_FAILED: " + producer.get("error_type", "unknown") +
                        "；核对kafka-python版本/协议支持及认证配置。")
    if worker.get("worker_error") or worker.get("configuration_error"):
        findings.append("CONTAINER_CHECK_INCOMPLETE: 容器诊断未完成；先检查工具容器启动条件或配置校验，不据此认定Kafka故障。")
    findings.append("ACL_NOT_FULLY_EVALUATED: 元数据及FindCoordinator不能证明Read/Write/事务/提交权限；按业务Topic/Group清单核对ACL。")
    return list(dict.fromkeys(findings))


def cli_checks(bin_directory, properties, endpoints):
    binary = str(Path(bin_directory) / "kafka-broker-api-versions.sh") if bin_directory else shutil.which("kafka-broker-api-versions.sh")
    if not properties or not binary:
        return {"status": "skipped", "reason": "Provide --client-properties and optionally --kafka-bin for host Java CLI comparison."}
    results = []
    for endpoint in endpoints:
        value = command_result([binary, "--bootstrap-server", endpoint,
                                "--command-config", str(Path(properties).resolve())], timeout=25)
        output = value.pop("stdout", "")
        value.update(endpoint=endpoint, api_versions_seen=bool(re.search(r"ApiVersions\(\d+\)", output)),
                     error_types=[name for name in (
                         "SaslAuthenticationException", "AuthenticationException", "TimeoutException",
                         "UnsupportedSaslMechanismException", "IllegalSaslStateException", "DisconnectException",
                         "UnknownHostException", "ConnectException", "TopicAuthorizationException",
                         "GroupAuthorizationException", "SSLHandshakeException")
                         if re.search(r"\b" + name + r"\b", output)])
        results.append(value)
    return {"results": results, "credential_comparison": "not_evaluated"}


def host_main(args):
    root = Path(args.deployment_root).resolve(strict=True)
    wrapper = root / ("app-compose" if (root / "app-compose").exists() else "docker-compose")
    if not wrapper.is_file():
        raise ValueError("Deployment wrapper missing")
    os.umask(0o077)
    destination = Path(args.output).resolve() if args.output else root / (
        "kafka-diagnosis-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
    destination.mkdir(mode=0o700, exist_ok=False)
    print("报告目录：", destination, flush=True)
    report = {"schema_version": "uav.kafka-diagnosis/v1",
              "time_utc": datetime.now(timezone.utc).isoformat(), "wrapper": wrapper.name}
    print("1/5 采集宿主机路由、转发、防火墙（权限不足会记录，不会自动提权）", flush=True)
    report["host_network"] = network_evidence()
    name = "uav-kafka-diag-" + uuid.uuid4().hex[:12]
    print("2/5 在Platform服务网络检查TCP、逐broker认证、30/60秒元数据和kafka-python（最多约4分钟）", flush=True)
    try:
        result = command_result([str(wrapper), "run", "--no-deps", "-T", "--name", name,
                                 "platform", "python3", "-", "--container-worker"],
                                timeout=240, input_text=Path(__file__).read_text())
        report["container"] = extract_worker(result)
        report["docker"] = docker_evidence(wrapper, [], name)
    finally:
        # Only remove this invocation's uniquely named disposable diagnostic container.
        command_result(["docker", "rm", "-f", name])
    endpoints = set(report["container"].get("configuration", {}).get("bootstrap", DEFAULT_ENDPOINTS))
    endpoints.update(item["endpoint"] for item in report["container"].get("advertised_tcp", []))
    print("3/5 在宿主机测试相同bootstrap/advertised地址", flush=True)
    report["host_tcp"] = tcp_probes(endpoints)
    print("4/5 可选：用既有Java CLI及client.properties逐broker检查", flush=True)
    report["host_cli"] = cli_checks(args.kafka_bin, args.client_properties, sorted(endpoints))
    print("5/5 生成分支建议和报告", flush=True)
    report["findings"] = conclusions(report)
    (destination / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (destination / "SUMMARY.txt").write_text("\n".join(report["findings"]) + "\n\n详见report.json；包含内网地址，按内部资料传输。\n")
    print("\n".join(report["findings"]))
    print("完成。带回整个报告目录：", destination)
    return 2 if report["container"].get("worker_error") or report["container"].get("configuration_error") else 0


def main():
    if sys.argv[1:] == ["--container-worker"]:
        try:
            report = asyncio.run(container_report())
        except Exception as exc:
            report = {"worker_error": error_info(exc)}
        print(MARKER + json.dumps(report, ensure_ascii=False), flush=True)
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-root", default=".")
    parser.add_argument("--output")
    parser.add_argument("--client-properties")
    parser.add_argument("--kafka-bin")
    return host_main(parser.parse_args())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("诊断工具退出：" + type(exc).__name__ + "；未输出异常原文以避免泄露配置。", file=sys.stderr)
        raise SystemExit(2)
