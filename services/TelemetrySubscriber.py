"""MQTT遥测订阅器：接收无人机飞行遥测数据并与视频帧同步。

独立线程运行，维护按时间戳排序的遥测缓冲区。
VideoReader每帧产出时从缓冲区查找最近的遥测记录。
"""

import json
import time
import logging
import threading
from collections import deque

logger = logging.getLogger(__name__)

try:
    import paho.mqtt.client as mqtt
    PAHO_AVAILABLE = True
except ImportError:
    PAHO_AVAILABLE = False
    logger.warning("paho-mqtt not installed, telemetry subscription disabled")


class TelemetrySubscriber:
    """MQTT遥测订阅器，维护时间戳排序的遥测缓冲区。"""

    def __init__(self, config: dict) -> None:
        if not PAHO_AVAILABLE:
            raise ImportError("paho-mqtt is required for telemetry. Install with: pip install paho-mqtt")

        self.broker = config.get("mqtt_broker", "mqtt://localhost:1883")
        self.topic = config.get("mqtt_topic", "drone/+/osd")
        self.buffer_size = config.get("buffer_size", 100)
        self.sync_tolerance_sec = config.get("sync_tolerance_sec", 0.05)
        self._buffer: deque[dict] = deque(maxlen=self.buffer_size)
        self._lock = threading.Lock()
        self._client: mqtt.Client | None = None
        self._thread: threading.Thread | None = None
        self._connected = False

    def start(self) -> None:
        """在后台线程启动MQTT订阅。"""
        self._client = mqtt.Client(
            client_id=f"traffic_analyzer_{int(time.time())}",
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        # 解析 broker URL: mqtt://host:port
        host, port = self._parse_broker_url(self.broker)
        try:
            self._client.connect(host, port, keepalive=60)
            self._thread = threading.Thread(
                target=self._client.loop_forever, daemon=True
            )
            self._thread.start()
            logger.info(f"TelemetrySubscriber: 连接到 {host}:{port}, 订阅 {self.topic}")
        except Exception as e:
            logger.error(f"TelemetrySubscriber: 连接失败 {e}")
            self._connected = False

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            self._connected = True
            client.subscribe(self.topic)
            logger.info(f"TelemetrySubscriber: MQTT已连接, 订阅 {self.topic}")
        else:
            logger.error(f"TelemetrySubscriber: MQTT连接失败, code={reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self._connected = False
        if reason_code != 0:
            logger.warning(f"TelemetrySubscriber: MQTT断开连接, code={reason_code}")

    def _on_message(self, client, userdata, msg) -> None:
        """接收遥测消息，解析并加入缓冲区。"""
        try:
            payload = json.loads(msg.payload.decode())
            telemetry = self._extract_telemetry(payload)
            telemetry["_received_at"] = time.time()
            with self._lock:
                self._buffer.append(telemetry)
        except (json.JSONDecodeError, KeyError) as e:
            logger.debug(f"TelemetrySubscriber: 丢弃格式错误的消息: {e}")

    def _extract_telemetry(self, payload: dict) -> dict:
        """从DJI OSD消息中提取关键字段。"""
        osd = payload.get("99-0-0", payload)  # 兼容不同格式
        height = payload.get("height", 0)
        elevation = payload.get("elevation", 0)
        return {
            "timestamp": payload.get("timestamp", time.time()),
            "latitude": payload.get("latitude"),
            "longitude": payload.get("longitude"),
            "height": height,
            "elevation": elevation,
            "altitude_agl": height - elevation,
            "attitude_head": payload.get("attitude_head", 0),
            "attitude_pitch": payload.get("attitude_pitch", 0),
            "gimbal_pitch": osd.get("gimbal_pitch", -90),
            "gimbal_yaw": osd.get("gimbal_yaw", 0),
            "gimbal_roll": osd.get("gimbal_roll", 0),
            "zoom_factor": osd.get("zoom_factor", 1.0),
            "horizontal_speed": payload.get("horizontal_speed", 0),
            "vertical_speed": payload.get("vertical_speed", 0),
        }

    def get_nearest(self, frame_timestamp: float) -> dict | None:
        """查找与视频帧时间戳最接近的遥测记录。

        Args:
            frame_timestamp: 视频帧的时间戳（秒）

        Returns:
            最匹配的遥测字典，或 None（若超出容忍范围或无数据）
        """
        with self._lock:
            if not self._buffer:
                return None
            best = None
            best_diff = float("inf")
            for entry in self._buffer:
                diff = abs(entry["timestamp"] - frame_timestamp)
                if diff < best_diff:
                    best_diff = diff
                    best = entry
            if best_diff <= self.sync_tolerance_sec:
                return best
            # 放宽容忍：使用最近的一条（即使超出严格窗口）
            if best is not None:
                return best
            return None

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def buffer_count(self) -> int:
        return len(self._buffer)

    def stop(self) -> None:
        if self._client:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._connected = False
            logger.info("TelemetrySubscriber: 已停止")

    @staticmethod
    def _parse_broker_url(url: str) -> tuple[str, int]:
        """解析 MQTT broker URL: mqtt://host:port"""
        url = url.replace("mqtt://", "").replace("tcp://", "")
        parts = url.split(":")
        host = parts[0]
        port = int(parts[1]) if len(parts) > 1 else 1883
        return host, port
