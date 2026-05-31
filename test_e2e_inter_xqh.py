#!/usr/bin/env python3
"""端到端集成测试：inter_xqh视频+SRT遥测 → Kafka → Platform → Monitor页面。

运行方式:
  python3 test_e2e_inter_xqh.py

前置条件:
  - Kafka 容器运行 (localhost:9093 = HOST PLAINTEXT listener)
  - Platform 容器运行 (localhost:8000)
  - inter_xqh 视频和SRT文件存在
  - inter_xqh_lanes.json 配置存在
"""

import os
import sys
import json
import time
import logging
import signal
import subprocess
import threading
import numpy as np
from kafka import KafkaConsumer, KafkaProducer
import requests

# ─── 设置环境变量 ───
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"  # MPS设备NMS回退CPU

VIDEO_SRC = "test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4"
ROADS_JSON = "configs/inter_xqh_lanes.json"
TELEMETRY_FILE = "test_videos/inter_xqh/telemetry.srt"
KAFKA_BOOTSTRAP = "localhost:9093"  # HOST listener (PLAINTEXT, no SASL)
TOPIC_NAME = "statistics_1"
CAMERA_ID = "1"
INTERSECTION_ID = "INT_camera_1"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("e2e_test")


class E2ETestResults:
    """测试结果收集器"""
    def __init__(self):
        self.checks = []
        self.warnings = []

    def check(self, name: str, condition: bool, detail: str = ""):
        status = "PASS" if condition else "FAIL"
        self.checks.append({"name": name, "status": status, "detail": detail})
        icon = "✅" if condition else "❌"
        logger.info(f"  {icon} {name}" + (f" — {detail}" if detail else ""))

    def warn(self, msg: str):
        self.warnings.append(msg)
        logger.warning(f"  ⚠️  {msg}")

    def summary(self):
        passed = sum(1 for c in self.checks if c["status"] == "PASS")
        failed = sum(1 for c in self.checks if c["status"] == "FAIL")
        logger.info(f"\n{'='*60}")
        logger.info(f"测试结果: {passed} PASS / {failed} FAIL / {len(self.warnings)} WARN")
        logger.info(f"{'='*60}")
        return failed == 0


def check_kafka_connectivity(results: E2ETestResults):
    """验证 Kafka 连接"""
    global KAFKA_BOOTSTRAP
    logger.info("\n" + "="*60)
    logger.info("Phase 1: Kafka 连接验证")
    logger.info("="*60)

    # 尝试连接 Kafka HOST listener (localhost:9093, PLAINTEXT)
    try:
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            value_serializer=lambda x: json.dumps(x).encode("utf-8"),
        )
        # 发送测试消息
        test_msg = {"test": "e2e_connectivity", "ts": time.time()}
        future = producer.send("test_topic", value=test_msg)
        future.get(timeout=5)
        producer.flush()
        producer.close()
        results.check("Kafka HOST listener 连接", True, f"bootstrap={KAFKA_BOOTSTRAP}")
    except Exception as e:
        results.check("Kafka HOST listener 连接", False, str(e))
        # 尝试 EXTERNAL listener (SASL_PLAINTEXT)
        try:
            from kafka import KafkaProducer
            producer = KafkaProducer(
                bootstrap_servers="localhost:9092",
                value_serializer=lambda x: json.dumps(x).encode("utf-8"),
                security_protocol="SASL_PLAINTEXT",
                sasl_mechanism="PLAIN",
                sasl_plain_username=os.environ.get("KAFKA_USERNAME", "admin"),
                sasl_plain_password=os.environ.get("KAFKA_PASSWORD", "admin"),
            )
            future = producer.send("test_topic", value={"test": "sasl_connectivity"})
            future.get(timeout=5)
            producer.close()
            results.check("Kafka EXTERNAL listener (SASL)", True)
            # 更新 KAFKA_BOOTSTRAP 为 SASL 版本
            KAFKA_BOOTSTRAP = "localhost:9092"
            logger.info("切换到 SASL_PLAINTEXT listener")
        except Exception as e2:
            results.check("Kafka EXTERNAL listener (SASL)", False, str(e2))


def check_platform_api(results: E2ETestResults):
    """验证 Platform API"""
    logger.info("\n" + "="*60)
    logger.info("Phase 2: Platform API 验证")
    logger.info("="*60)

    try:
        resp = requests.get("http://localhost:8000/health", timeout=5)
        results.check("Platform health", resp.status_code == 200,
                      f"status={resp.status_code}")
    except Exception as e:
        results.check("Platform health", False, str(e))

    try:
        resp = requests.get("http://localhost:8000/ready", timeout=5)
        data = resp.json()
        results.check("Platform readiness", resp.status_code == 200,
                      f"services={data.get('services', {})}")
        kafka_status = data.get("services", {}).get("kafka", "unknown")
        if kafka_status != "healthy":
            results.warn(f"Kafka consumer状态: {kafka_status}")
    except Exception as e:
        results.check("Platform readiness", False, str(e))

    try:
        resp = requests.get("http://localhost:8000/api/v1/intersections", timeout=5)
        intersections = resp.json()
        results.check("Intersections API", resp.status_code == 200,
                      f"count={len(intersections)}, ids={[i['id'] for i in intersections]}")
        # 检查是否有 INT_camera_1
        has_int1 = any(i['id'] == INTERSECTION_ID for i in intersections)
        results.check(f"Intersection {INTERSECTION_ID} 存在", has_int1)
    except Exception as e:
        results.check("Intersections API", False, str(e))


def check_kafka_topics(results: E2ETestResults):
    """验证 Kafka topic 配置"""
    logger.info("\n" + "="*60)
    logger.info("Phase 3: Kafka Topics 验证")
    logger.info("="*60)

    from kafka.admin import KafkaAdminClient
    try:
        admin = KafkaAdminClient(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            security_protocol="SASL_PLAINTEXT" if KAFKA_BOOTSTRAP == "localhost:9092" else "PLAINTEXT",
            sasl_mechanism="PLAIN" if KAFKA_BOOTSTRAP == "localhost:9092" else None,
            sasl_plain_username=os.environ.get("KAFKA_USERNAME", "admin") if KAFKA_BOOTSTRAP == "localhost:9092" else None,
            sasl_plain_password=os.environ.get("KAFKA_PASSWORD", "admin") if KAFKA_BOOTSTRAP == "localhost:9092" else None,
        )
        topics = admin.list_topics()
        admin.close()
        results.check("Kafka topic list获取", True, f"topics={topics}")
        results.check(f"statistics_1 存在", "statistics_1" in topics)
        results.check(f"track_complete_1 存在", "track_complete_1" in topics)
    except Exception as e:
        results.check("Kafka topic list获取", False, str(e))


def run_pipeline_subprocess(results: E2ETestResults, max_duration_sec=120):
    """运行管道子进程"""
    logger.info("\n" + "="*60)
    logger.info("Phase 4: 运行检测管道")
    logger.info("="*60)

    # 构建命令
    env = {
        **os.environ,
        "VIDEO_SRC": VIDEO_SRC,
        "ROADS_JSON": ROADS_JSON,
        "TOPIC_NAME": TOPIC_NAME,
        "CAMERA_ID": CAMERA_ID,
        "KAFKA_BOOTSTRAP": KAFKA_BOOTSTRAP,
        "PYTORCH_ENABLE_MPS_FALLBACK": "1",
        "INTERSECTION_ID": INTERSECTION_ID,
    }

    # 管道命令: main_optimized.py + Hydra overrides
    cmd = [
        sys.executable, "main_optimized.py",
        "pipeline.send_info_kafka=True",
        "pipeline.show_in_web=True",
        "pipeline.save_video=False",
        "kafka_producer_node.bootstrap_servers=" + KAFKA_BOOTSTRAP,
        "telemetry.enabled=true",
        "telemetry.source=srt",
        "+telemetry.file_path=" + TELEMETRY_FILE,
        "telemetry.sync_tolerance_sec=0.033",
        "+telemetry.time_offset_sec=0",
        "calibration.mode=telemetry",
        "video_server_node.port=8103",  # 使用不同端口避免冲突
    ]

    logger.info(f"启动管道: {' '.join(cmd)}")
    logger.info(f"  VIDEO_SRC={VIDEO_SRC}")
    logger.info(f"  KAFKA_BOOTSTRAP={KAFKA_BOOTSTRAP}")
    logger.info(f"  TELEMETRY={TELEMETRY_FILE}")

    process = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=os.getcwd(),
    )

    results.check("管道进程启动", process.poll() is None, f"PID={process.pid}")

    # 启动线程收集输出
    stdout_lines = []
    stderr_lines = []

    def read_stdout():
        for line in iter(process.stdout.readline, b''):
            stdout_lines.append(line.decode('utf-8', errors='replace'))

    def read_stderr():
        for line in iter(process.stderr.readline, b''):
            stderr_lines.append(line.decode('utf-8', errors='replace'))

    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    # 等待管道运行一段时间
    logger.info(f"等待管道运行 {max_duration_sec}秒...")
    start_time = time.time()

    # 检查 Kafka 消息
    kafka_msg_received = False
    kafka_consumer = None

    try:
        security_protocol = "SASL_PLAINTEXT" if KAFKA_BOOTSTRAP == "localhost:9092" else "PLAINTEXT"
        sasl_config = {}
        if security_protocol == "SASL_PLAINTEXT":
            sasl_config = {
                "sasl_mechanism": "PLAIN",
                "sasl_plain_username": os.environ.get("KAFKA_USERNAME", "admin"),
                "sasl_plain_password": os.environ.get("KAFKA_PASSWORD", "admin"),
            }

        kafka_consumer = KafkaConsumer(
            TOPIC_NAME,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            security_protocol=security_protocol,
            **sasl_config,
            auto_offset_reset="latest",
            consumer_timeout_ms=5000,
            value_deserializer=lambda x: json.loads(x.decode("utf-8")),
        )
        logger.info(f"Kafka consumer 已连接: topic={TOPIC_NAME}")
    except Exception as e:
        results.warn(f"Kafka consumer 连接失败: {e}")

    # 同时检查 Platform WebSocket 接收消息
    ws_msg_received = False

    while time.time() - start_time < max_duration_sec:
        if process.poll() is not None:
            logger.info(f"管道进程已退出 (code={process.returncode})")
            break

        # 尝试从 Kafka 读取消息
        if kafka_consumer:
            try:
                msgs = list(kafka_consumer.poll(timeout_ms=2000).values())
                for msg_batch in msgs:
                    for msg in msg_batch:
                        kafka_msg_received = True
                        logger.info(f"收到Kafka消息: topic={msg.topic}, value_keys={list(msg.value.keys())}")
            except Exception as e:
                logger.debug(f"Kafka poll error: {e}")

        # 检查 Platform API 是否有数据
        try:
            resp = requests.get("http://localhost:8000/api/v1/intersections", timeout=3)
            if resp.status_code == 200:
                for int_data in resp.json():
                    if int_data.get("id") == INTERSECTION_ID:
                        latest_stats = int_data.get("latest_stats")
                        if latest_stats:
                            ws_msg_received = True
                            logger.info(f"Platform intersection数据: cars={latest_stats.get('cars')}, "
                                       f"fps={latest_stats.get('fps')}, "
                                       f"drone_position={latest_stats.get('drone_position')}")
        except Exception as e:
            logger.debug(f"Platform API poll error: {e}")

        if kafka_msg_received and ws_msg_received:
            logger.info("✅ Kafka消息和Platform数据都已接收!")
            break

        # 打印管道进度
        elapsed = int(time.time() - start_time)
        if elapsed % 10 == 0:
            logger.info(f"  管道运行 {elapsed}秒, Kafka={kafka_msg_received}, Platform={ws_msg_received}")

    # 关闭消费者
    if kafka_consumer:
        kafka_consumer.close()

    results.check("管道进程运行中", process.poll() is None or kafka_msg_received,
                  f"poll={process.poll()}, returncode={process.returncode}")
    results.check("Kafka消息接收", kafka_msg_received)

    # 终止管道
    if process.poll() is None:
        logger.info("终止管道进程...")
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    # 打印最后几行输出
    logger.info(f"\n管道stdout (last 10 lines):")
    for line in stdout_lines[-10:]:
        logger.info(f"  {line.rstrip()}")

    logger.info(f"\n管道stderr (last 10 lines):")
    for line in stderr_lines[-10:]:
        logger.info(f"  {line.rstrip()}")

    return kafka_msg_received, ws_msg_received


def check_mjpeg_stream(results: E2ETestResults):
    """验证 MJPEG 视频流"""
    logger.info("\n" + "="*60)
    logger.info("Phase 5: MJPEG 视频流验证")
    logger.info("="*60)

    # 直接访问 Flask 视频流 (localhost:8103)
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:8103/video")
        resp = urllib.request.urlopen(req, timeout=5)
        content_type = resp.headers.get('Content-Type', '')
        results.check("Flask MJPEG /video 可访问",
                      'multipart' in content_type or 'image' in content_type,
                      f"Content-Type={content_type}")
        # 读取几帧
        data = resp.read(10240)
        results.check("MJPEG数据读取", len(data) > 0, f"bytes={len(data)}")
    except Exception as e:
        results.check("Flask MJPEG /video 可访问", False, str(e))

    # 通过 nginx 代理访问 (localhost:8009/camera_1)
    try:
        req = urllib.request.Request("http://localhost:8009/camera_1")
        resp = urllib.request.urlopen(req, timeout=5)
        content_type = resp.headers.get('Content-Type', '')
        results.check("Nginx MJPEG proxy /camera_1",
                      'multipart' in content_type or 'image' in content_type,
                      f"Content-Type={content_type}")
    except Exception as e:
        results.warn(f"Nginx MJPEG proxy不可用 (可能是本地Flask在不同端口): {e}")


def main():
    results = E2ETestResults()

    # Phase 1: Kafka connectivity
    check_kafka_connectivity(results)

    # Phase 2: Platform API
    check_platform_api(results)

    # Phase 3: Kafka topics
    check_kafka_topics(results)

    # Phase 4: Run pipeline (with 120s timeout)
    kafka_received, platform_received = run_pipeline_subprocess(results, max_duration_sec=120)

    # Phase 5: MJPEG stream
    check_mjpeg_stream(results)

    # Summary
    all_passed = results.summary()

    if results.warnings:
        logger.info("\n警告:")
        for w in results.warnings:
            logger.info(f"  ⚠️  {w}")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
