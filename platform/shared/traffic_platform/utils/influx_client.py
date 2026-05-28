"""InfluxDB client utilities"""
from typing import Optional
from influxdb import InfluxDBClient
from functools import lru_cache
from ..config import get_settings


class InfluxDBClient:
    """InfluxDB 客户端封装"""

    def __init__(self):
        settings = get_settings()
        self.client = InfluxDBClient(
            host=settings.influx.host,
            port=settings.influx.port,
            username=settings.influx.username or None,
            password=settings.influx.password or None,
            database=settings.influx.database,
        )
        self.database = settings.influx.database
        self.retention_policy = settings.influx.retention_policy

    def query_stats(
        self,
        intersection_id: str,
        time_range: str = "1h",
        group_by: str = "1m",
    ) -> list[dict]:
        """
        查询路口统计指标

        Args:
            intersection_id: 路口 ID
            time_range: 时间范围，如 "1h", "24h", "7d"
            group_by: 分组粒度，如 "1m", "5m", "1h"

        Returns:
            时间序列数据列表
        """
        query = f"""
        SELECT mean(*)
        FROM "intersection_stats"
        WHERE "intersection_id" = '{intersection_id}'
          AND time > now() - {time_range}
        GROUP BY time({group_by})
        ORDER BY time DESC
        """
        result = self.client.query(query)
        points = list(result.get_points())
        return points

    def query_lane_stats(
        self,
        intersection_id: str,
        lane_id: int,
        time_range: str = "1h",
        group_by: str = "1m",
    ) -> list[dict]:
        """
        查询车道级统计指标

        Args:
            intersection_id: 路口 ID
            lane_id: 车道 ID
            time_range: 时间范围
            group_by: 分组粒度

        Returns:
            时间序列数据列表
        """
        query = f"""
        SELECT mean("lane_{lane_id}_flow") AS "flow",
               mean("lane_{lane_id}_headway") AS "headway",
               mean("lane_{lane_id}_queue") AS "queue",
               mean("lane_{lane_id}_vehicle_count") AS "vehicle_count",
               mean("lane_{lane_id}_avg_speed") AS "avg_speed"
        FROM "intersection_stats"
        WHERE "intersection_id" = '{intersection_id}'
          AND time > now() - {time_range}
        GROUP BY time({group_by})
        ORDER BY time DESC
        """
        result = self.client.query(query)
        points = list(result.get_points())
        return points

    def query_track_events(
        self,
        intersection_id: str,
        time_range: str = "1h",
    ) -> list[dict]:
        """
        查询轨迹事件

        Args:
            intersection_id: 路口 ID
            time_range: 时间范围

        Returns:
            轨迹事件列表
        """
        query = f"""
        SELECT *
        FROM "track_events"
        WHERE "intersection_id" = '{intersection_id}'
          AND time > now() - {time_range}
        ORDER BY time DESC
        """
        result = self.client.query(query)
        points = list(result.get_points())
        return points

    def query_turn_stats(
        self,
        intersection_id: str,
        time_range: str = "1h",
    ) -> list[dict]:
        """
        查询转向统计

        Args:
            intersection_id: 路口 ID
            time_range: 时间范围

        Returns:
            转向统计列表
        """
        query = f"""
        SELECT count("track_id")
        FROM "track_events"
        WHERE "intersection_id" = '{intersection_id}'
          AND time > now() - {time_range}
        GROUP BY "turn_behavior"
        """
        result = self.client.query(query)
        points = list(result.get_points())
        return points

    def query_lane_changes(
        self,
        intersection_id: str,
        time_range: str = "1h",
    ) -> list[dict]:
        """
        查询换道事件

        Args:
            intersection_id: 路口 ID
            time_range: 时间范围

        Returns:
            换道事件列表
        """
        query = f"""
        SELECT *
        FROM "lane_changes"
        WHERE "intersection_id" = '{intersection_id}'
          AND time > now() - {time_range}
        ORDER BY time DESC
        """
        result = self.client.query(query)
        points = list(result.get_points())
        return points

    def query_system_metrics(
        self,
        time_range: str = "1h",
        group_by: str = "1m",
    ) -> list[dict]:
        """
        查询系统指标

        Args:
            time_range: 时间范围
            group_by: 分组粒度

        Returns:
            时间序列数据列表
        """
        query = f"""
        SELECT mean(*)
        FROM "system_metrics"
        WHERE time > now() - {time_range}
        GROUP BY time({group_by})
        ORDER BY time DESC
        """
        result = self.client.query(query)
        points = list(result.get_points())
        return points

    def write_point(
        self,
        measurement: str,
        tags: dict,
        fields: dict,
        timestamp: Optional[int] = None,
    ) -> bool:
        """
        写入单个数据点

        Args:
            measurement: 测量名称
            tags: 标签字典
            fields: 字段字典
            timestamp: 时间戳（纳秒），默认当前时间

        Returns:
            是否写入成功
        """
        point = {
            "measurement": measurement,
            "tags": tags,
            "fields": fields,
        }
        if timestamp:
            point["time"] = timestamp

        return self.client.write_points(
            [point],
            database=self.database,
            retention_policy=self.retention_policy,
        )


@lru_cache()
def get_influx_client() -> InfluxDBClient:
    """获取 InfluxDB 客户端单例"""
    return InfluxDBClient()
