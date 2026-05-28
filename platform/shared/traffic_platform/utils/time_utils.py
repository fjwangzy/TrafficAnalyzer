"""Time utility functions"""
from datetime import datetime, timedelta
from typing import Tuple
from enum import Enum


class TimeRange(str, Enum):
    """预定义时间范围"""
    LAST_HOUR = "1h"
    LAST_6_HOURS = "6h"
    LAST_24_HOURS = "24h"
    LAST_7_DAYS = "7d"
    LAST_30_DAYS = "30d"
    TODAY = "today"
    YESTERDAY = "yesterday"


def format_timestamp(dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    格式化时间戳

    Args:
        dt: datetime 对象
        fmt: 格式字符串，默认为 "YYYY-MM-DD HH:MM:SS"

    Returns:
        格式化后的时间字符串
    """
    return dt.strftime(fmt)


def parse_timestamp(time_str: str, fmt: str = "%Y-%m-%d %H:%M:%S") -> datetime:
    """
    解析时间字符串

    Args:
        time_str: 时间字符串
        fmt: 格式字符串，默认为 "YYYY-MM-DD HH:MM:SS"

    Returns:
        datetime 对象
    """
    return datetime.strptime(time_str, fmt)


def get_time_range(
    time_range: TimeRange,
    reference_time: datetime = None,
) -> Tuple[datetime, datetime]:
    """
    获取时间范围的起止时间

    Args:
        time_range: 时间范围枚举
        reference_time: 参考时间，默认为当前时间

    Returns:
        (start_time, end_time) 元组
    """
    if reference_time is None:
        reference_time = datetime.now()

    if time_range == TimeRange.LAST_HOUR:
        start = reference_time - timedelta(hours=1)
        end = reference_time
    elif time_range == TimeRange.LAST_6_HOURS:
        start = reference_time - timedelta(hours=6)
        end = reference_time
    elif time_range == TimeRange.LAST_24_HOURS:
        start = reference_time - timedelta(hours=24)
        end = reference_time
    elif time_range == TimeRange.LAST_7_DAYS:
        start = reference_time - timedelta(days=7)
        end = reference_time
    elif time_range == TimeRange.LAST_30_DAYS:
        start = reference_time - timedelta(days=30)
        end = reference_time
    elif time_range == TimeRange.TODAY:
        start = reference_time.replace(hour=0, minute=0, second=0, microsecond=0)
        end = reference_time
    elif time_range == TimeRange.YESTERDAY:
        yesterday = reference_time - timedelta(days=1)
        start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
    else:
        raise ValueError(f"Unknown time range: {time_range}")

    return start, end


def to_influx_timestamp(dt: datetime) -> int:
    """
    转换为 InfluxDB 纳秒时间戳

    Args:
        dt: datetime 对象

    Returns:
        纳秒时间戳
    """
    return int(dt.timestamp() * 1_000_000_000)


def from_influx_timestamp(ns_timestamp: int) -> datetime:
    """
    从 InfluxDB 纳秒时间戳转换

    Args:
        ns_timestamp: 纳秒时间戳

    Returns:
        datetime 对象
    """
    return datetime.fromtimestamp(ns_timestamp / 1_000_000_000)


def format_duration(seconds: float) -> str:
    """
    格式化持续时间

    Args:
        seconds: 秒数

    Returns:
        格式化后的字符串，如 "2h 15m 30s"
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours}h {minutes}m {secs}s"
