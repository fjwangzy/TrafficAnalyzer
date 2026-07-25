"""SRT遥测解析器：从DJI无人机视频字幕文件(telemetry.srt)中提取逐帧遥测数据。

支持格式：
  FrameCnt: N YYYY-MM-DD HH:MM:SS.mmm
  [iso: ...] ... [latitude: xx] [longitude: yy] [rel_alt: zz abs_alt: ww]
  [gb_yaw: aa gb_pitch: bb gb_roll: cc] ...

输出格式与 TelemetryFileReader 兼容，可直接替换使用。
"""

import re
import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo
from bisect import bisect_left

logger = logging.getLogger(__name__)

# 正则匹配 SRT 条目
_SRT_BLOCK_RE = re.compile(
    r"(\d+)\n"                                    # 序号
    r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*"        # 开始时间
    r"(\d{2}:\d{2}:\d{2},\d{3})\n"               # 结束时间
    r"FrameCnt:\s*(\d+)\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)\n"  # 帧号+时间戳
    r"(.+?)(?=\n\n|\Z)",                          # 元数据行
    re.DOTALL,
)

_KV_RE = re.compile(r"\[([a-z_]+):\s*([^\]]+)\]")


def _parse_srt_time(t: str) -> float:
    """HH:MM:SS,mmm → 秒"""
    h, m, rest = t.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


class SrtTelemetryParser:
    """从 SRT 文件加载遥测数据，提供与 TelemetryFileReader 相同的 get_nearest() 接口。"""

    def __init__(
        self,
        file_path: str,
        sync_tolerance_sec: float = 0.5,
        time_offset_sec: float = 0.0,
    ) -> None:
        self.file_path = file_path
        self.sync_tolerance_sec = sync_tolerance_sec
        self.time_offset_sec = time_offset_sec
        self._records: list[dict] = []
        self._timestamps: list[float] = []
        self._load(file_path)

    def _load(self, file_path: str) -> None:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 按双换行分割 SRT 块
        blocks = content.strip().split("\n\n")
        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 3:
                continue
            try:
                # Line 0: sequence number
                # Line 1: time range
                # Line 2+: data
                time_line = lines[1]
                start_time_str = time_line.split("-->")[0].strip()
                srt_time = _parse_srt_time(start_time_str)

                # 找 FrameCnt 行
                frame_line = lines[2] if len(lines) > 2 else ""
                if not frame_line.startswith("FrameCnt:"):
                    continue
                parts = frame_line.split(None, 2)
                int(parts[1])
                timestamp_str = parts[2] if len(parts) > 2 else ""

                # 元数据行
                meta_line = lines[3] if len(lines) > 3 else ""

                # 提取键值对
                recorded_at = None
                if timestamp_str:
                    recorded_at = (
                        datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S.%f")
                        .replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                        .astimezone(UTC)
                        .isoformat()
                    )
                telemetry = self._extract_fields(meta_line, srt_time, recorded_at)
                self._records.append(telemetry)
                self._timestamps.append(srt_time)
            except (ValueError, IndexError) as e:
                logger.debug(f"跳过无法解析的SRT块: {e}")

        logger.info(f"SrtTelemetryParser: 从 {file_path} 加载了 {len(self._records)} 条遥测记录")

    def _extract_fields(self, meta_line: str, timestamp: float, recorded_at: str | None = None) -> dict:
        """从 SRT 元数据行提取遥测字段。

        注意：某些字段共享同一个方括号，例如：
          [rel_alt: 129.980 abs_alt: 163.436]
          [gb_yaw: 0.8 gb_pitch: -90.0 gb_roll: 0.0]
        需要先展开这些复合括号再提取。
        """
        # 展开复合括号：将 "[a: 1 b: 2 c: 3]" 拆成 "[a: 1] [b: 2] [c: 3]"
        expanded = re.sub(
            r"\[([a-z_]+:\s*[^\[\]]+)\]",
            lambda m: " ".join(
                f"[{part.strip()}]"
                for part in re.split(r"(?<=\S)\s+(?=[a-z_]+:)", m.group(1))
                if ":" in part
            ),
            meta_line,
        )
        kvs = dict(_KV_RE.findall(expanded))

        lat = float(kvs.get("latitude", 0))
        lon = float(kvs.get("longitude", 0))
        rel_alt = float(kvs.get("rel_alt", 0))
        abs_alt = float(kvs.get("abs_alt", 0))

        gb_yaw = float(kvs.get("gb_yaw", 0))
        gb_pitch = float(kvs.get("gb_pitch", -90))
        gb_roll = float(kvs.get("gb_roll", 0))
        focal_len = float(kvs.get("focal_len", 4.5))
        dzoom_ratio = float(kvs.get("dzoom_ratio", 1.0))

        height = rel_alt
        elevation = abs_alt - rel_alt if abs_alt > rel_alt else 0

        return {
            "timestamp": timestamp,
            "recorded_at": recorded_at,
            "latitude": lat,
            "longitude": lon,
            "height": height,
            "elevation": elevation,
            # rel_alt 是相对起飞点高度，即最佳 AGL 近似（无 DEM 时）
            # 旧公式 height-elevation = 2*rel_alt - abs_alt 是错误的
            "altitude_agl": rel_alt,
            "attitude_head": gb_yaw,
            "attitude_pitch": 0,
            "gimbal_pitch": gb_pitch,
            "gimbal_yaw": gb_yaw,
            "gimbal_roll": gb_roll,
            "zoom_factor": 1.0 / dzoom_ratio if dzoom_ratio > 0 else 1.0,
            # SRT normally has no aircraft velocity.  Preserve absence so the
            # shared flight classifier derives it from the 1-second GPS window.
            "horizontal_speed": None,
            "vertical_speed": None,
            "focal_len": focal_len,
            "dzoom_ratio": dzoom_ratio,
        }

    def get_nearest(self, frame_timestamp: float) -> dict | None:
        if not self._records:
            return None
        lookup_t = frame_timestamp + self.time_offset_sec
        idx = bisect_left(self._timestamps, lookup_t)
        best_idx = idx
        best_diff = float("inf")
        for candidate in [idx - 1, idx, idx + 1]:
            if 0 <= candidate < len(self._timestamps):
                diff = abs(self._timestamps[candidate] - lookup_t)
                if diff < best_diff:
                    best_diff = diff
                    best_idx = candidate
        if best_diff <= self.sync_tolerance_sec:
            return self._records[best_idx]
        return None

    @property
    def buffer_count(self) -> int:
        return len(self._records)

    @property
    def duration_sec(self) -> float:
        if len(self._timestamps) < 2:
            return 0
        return self._timestamps[-1] - self._timestamps[0]

    @property
    def time_range(self) -> tuple[float, float]:
        if not self._timestamps:
            return (0, 0)
        return (self._timestamps[0], self._timestamps[-1])

    @property
    def records(self) -> tuple[dict, ...]:
        """Return an immutable view for ingestion-quality analysis."""
        return tuple(dict(record) for record in self._records)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    @property
    def is_connected(self) -> bool:
        return len(self._records) > 0
