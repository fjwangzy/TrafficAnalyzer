"""文件遥测加载器：从DJI Cloud API JSON文件加载遥测数据。

作为 TelemetrySubscriber 的离线替代品，提供相同的 get_nearest() 接口。
用于开发测试和离线视频回放场景。

支持的文件格式：
- DJI Cloud API JSON 导出（含 data[].time + data[].value）
- 纯遥测记录数组 JSON（[{timestamp, latitude, ...}, ...]）
"""

import json
import logging
import math
from datetime import UTC, datetime
from bisect import bisect_left
from zoneinfo import ZoneInfo

from services.dji_telemetry import extract_dji_telemetry

logger = logging.getLogger(__name__)
DJI_EXPORT_TIMEZONE = ZoneInfo("Asia/Shanghai")


class TelemetryFileReader:
    """从JSON文件加载遥测数据，提供与TelemetrySubscriber相同的get_nearest()接口。"""

    def __init__(
        self,
        file_path: str,
        sync_tolerance_sec: float = 0.5,
        time_offset_sec: float = 0.0,
        agl_policy: str = "legacy_height",
        interpolation_enabled: bool = True,
        max_interpolation_gap_sec: float | None = None,
    ) -> None:
        self.file_path = file_path
        self.sync_tolerance_sec = sync_tolerance_sec
        self.time_offset_sec = time_offset_sec  # 视频t=0对应的遥测相对时间（秒）
        self.agl_policy = agl_policy
        self.interpolation_enabled = bool(interpolation_enabled)
        self.max_interpolation_gap_sec = float(
            sync_tolerance_sec
            if max_interpolation_gap_sec is None
            else max_interpolation_gap_sec
        )
        self._records: list[dict] = []
        self._timestamps: list[float] = []  # 相对时间戳（秒），用于二分查找
        self._load(file_path)

    def _load(self, file_path: str) -> None:
        """加载并解析遥测JSON文件。"""
        with open(file_path, "r") as f:
            raw = json.load(f)

        # 检测格式：DJI Cloud API 导出 vs 纯数组
        if isinstance(raw, dict) and "data" in raw:
            self._load_dji_cloud_api(raw["data"])
        elif isinstance(raw, list):
            self._load_plain_array(raw)
        else:
            raise ValueError(f"不支持的遥测文件格式: {type(raw)}")

        logger.info(f"TelemetryFileReader: 从 {file_path} 加载了 {len(self._records)} 条遥测记录")

    def _load_dji_cloud_api(self, data: list[dict]) -> None:
        """解析DJI Cloud API格式：{time: "2026-04-03 14:39:52.161", key: ..., value: "{...}"}"""
        records_raw = []
        for entry in data:
            time_str = entry.get("time", "")
            value_str = entry.get("value", "")
            try:
                dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S.%f")
                value = json.loads(value_str)
                records_raw.append((dt, value))
            except (ValueError, json.JSONDecodeError) as e:
                logger.debug(f"跳过无法解析的记录: {time_str} -> {e}")

        # 按时间升序排列（DJI导出可能是降序的）
        records_raw.sort(key=lambda x: x[0])

        if not records_raw:
            logger.warning("TelemetryFileReader: 未找到有效遥测记录")
            return

        # 以第一条记录时间为基准，转换为相对秒数
        t0 = records_raw[0][0]
        for dt, value in records_raw:
            relative_sec = (dt - t0).total_seconds()
            telemetry = self._extract_telemetry(value, relative_sec)
            # Offline replay must retain the DJI record time. Without this
            # field KafkaProducerNode falls back to consumer wall-clock time,
            # making synchronized file replay look ``ingest_only`` and
            # downgrading otherwise eligible TCC evidence.
            telemetry["recorded_at"] = dt.replace(
                tzinfo=DJI_EXPORT_TIMEZONE
            ).astimezone(UTC).isoformat()
            self._records.append(telemetry)
            self._timestamps.append(relative_sec)

    def _load_plain_array(self, data: list[dict]) -> None:
        """解析纯数组格式：[{timestamp: float, latitude: ..., ...}, ...]"""
        if not data:
            return

        # 如果timestamp是绝对时间（>1e9），转换为相对时间
        first_ts = data[0].get("timestamp", 0)
        is_absolute = first_ts > 1e9

        for entry in data:
            ts = entry.get("timestamp", 0)
            if is_absolute:
                ts = ts - first_ts
            telemetry = self._extract_telemetry(entry, ts)
            if is_absolute:
                telemetry["recorded_at"] = datetime.fromtimestamp(
                    float(entry["timestamp"]), tz=UTC
                ).isoformat()
            self._records.append(telemetry)
            self._timestamps.append(ts)

        # 确保按时间升序
        if len(self._timestamps) > 1 and self._timestamps[0] > self._timestamps[-1]:
            paired = sorted(zip(self._timestamps, self._records), key=lambda x: x[0])
            self._timestamps = [p[0] for p in paired]
            self._records = [p[1] for p in paired]

    def _extract_telemetry(self, payload: dict, timestamp: float) -> dict:
        """从DJI OSD消息中提取关键字段（与TelemetrySubscriber._extract_telemetry一致）。"""
        return extract_dji_telemetry(
            payload, timestamp, agl_policy=self.agl_policy
        )

    @staticmethod
    def _interpolate_number(left, right, ratio: float):
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            return None
        if not math.isfinite(float(left)) or not math.isfinite(float(right)):
            return None
        return float(left) + (float(right) - float(left)) * ratio

    @staticmethod
    def _interpolate_angle_deg(left, right, ratio: float):
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            return None
        if not math.isfinite(float(left)) or not math.isfinite(float(right)):
            return None
        left_value = float(left)
        delta = (float(right) - left_value + 180.0) % 360.0 - 180.0
        return (left_value + delta * ratio + 180.0) % 360.0 - 180.0

    @staticmethod
    def _interpolate_recorded_at(left, right, ratio: float) -> str | None:
        if not isinstance(left, str) or not isinstance(right, str):
            return None
        try:
            left_dt = datetime.fromisoformat(left.replace("Z", "+00:00"))
            right_dt = datetime.fromisoformat(right.replace("Z", "+00:00"))
        except ValueError:
            return None
        if left_dt.tzinfo is None or right_dt.tzinfo is None:
            return None
        return (left_dt + (right_dt - left_dt) * ratio).astimezone(UTC).isoformat()

    def _interpolate_record(
        self,
        left: dict,
        right: dict,
        lookup_t: float,
        ratio: float,
    ) -> dict:
        result = dict(left)
        for key in (
            "latitude",
            "longitude",
            "height",
            "elevation",
            "altitude_ellipsoid_m",
            "altitude_takeoff_relative_m",
            "laser_target_altitude_m",
            "laser_range_m",
            "altitude_agl",
            "altitude_agl_residual_m",
            "attitude_pitch",
            "gimbal_pitch",
            "gimbal_roll",
            "horizontal_speed",
            "vertical_speed",
        ):
            value = self._interpolate_number(left.get(key), right.get(key), ratio)
            if value is not None:
                result[key] = value
        for key in ("attitude_head", "gimbal_yaw"):
            value = self._interpolate_angle_deg(left.get(key), right.get(key), ratio)
            if value is not None:
                result[key] = value
        recorded_at = self._interpolate_recorded_at(
            left.get("recorded_at"), right.get("recorded_at"), ratio
        )
        if recorded_at is not None:
            result["recorded_at"] = recorded_at
        result.update(
            {
                "timestamp": float(lookup_t),
                "telemetry_interpolated": True,
                "telemetry_left_timestamp_sec": float(left["timestamp"]),
                "telemetry_right_timestamp_sec": float(right["timestamp"]),
                "telemetry_interpolation_ratio": float(ratio),
                "telemetry_gap_sec": float(right["timestamp"] - left["timestamp"]),
            }
        )
        return result

    def get_nearest(self, frame_timestamp: float) -> dict | None:
        """查找与视频帧时间戳最接近的遥测记录（二分查找）。

        Args:
            frame_timestamp: 视频帧的时间戳（秒，从0开始的相对时间）

        Returns:
            最匹配的遥测字典，或 None（若无数据）
        """
        if not self._records:
            return None

        # 对齐视频时间到遥测时间：video_t=0 → telemetry_t=time_offset_sec
        lookup_t = frame_timestamp + self.time_offset_sec

        # 二分查找相邻记录；合格间隔内优先返回当前帧时刻的连续遥测。
        idx = bisect_left(self._timestamps, lookup_t)

        if 0 < idx < len(self._timestamps):
            left_t = float(self._timestamps[idx - 1])
            right_t = float(self._timestamps[idx])
            gap = right_t - left_t
            nearest_diff = min(lookup_t - left_t, right_t - lookup_t)
            if (
                self.interpolation_enabled
                and gap > 0
                and gap <= self.max_interpolation_gap_sec
                and nearest_diff <= self.sync_tolerance_sec
            ):
                ratio = (lookup_t - left_t) / gap
                return self._interpolate_record(
                    self._records[idx - 1],
                    self._records[idx],
                    lookup_t,
                    ratio,
                )

        # 检查 idx-1, idx, idx+1 找到最近的
        best_idx = idx
        best_diff = float("inf")
        for candidate in [idx - 1, idx, idx + 1]:
            if 0 <= candidate < len(self._timestamps):
                diff = abs(self._timestamps[candidate] - lookup_t)
                if diff < best_diff:
                    best_diff = diff
                    best_idx = candidate

        if best_diff <= self.sync_tolerance_sec:
            result = dict(self._records[best_idx])
            result.setdefault("telemetry_interpolated", False)
            result.setdefault("telemetry_gap_sec", None)
            return result
        return None

    @property
    def buffer_count(self) -> int:
        return len(self._records)

    @property
    def duration_sec(self) -> float:
        """遥测数据总时长（秒）。"""
        if len(self._timestamps) < 2:
            return 0
        return self._timestamps[-1] - self._timestamps[0]

    @property
    def time_range(self) -> tuple[float, float]:
        """遥测数据时间范围（相对秒数）。"""
        if not self._timestamps:
            return (0, 0)
        return (self._timestamps[0], self._timestamps[-1])

    @property
    def records(self) -> tuple[dict, ...]:
        """Return an immutable view for ingestion-quality analysis."""
        return tuple(dict(record) for record in self._records)

    def start(self) -> None:
        """兼容TelemetrySubscriber接口（无操作）。"""
        pass

    def stop(self) -> None:
        """兼容TelemetrySubscriber接口（无操作）。"""
        pass

    @property
    def is_connected(self) -> bool:
        """兼容TelemetrySubscriber接口。"""
        return len(self._records) > 0
