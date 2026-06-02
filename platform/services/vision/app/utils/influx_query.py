"""InfluxDB query + write helper.

改进点（审查报告 T-102 / T-201 / T-404）:
  T-102: 新增 write_track_event / write_conflict_event / write_stats
  T-201: query_stats 支持动态道路数（不再硬编码 road_1..5）
  T-404: query_track_events 使用 trajectory_world_m 字段名（与 Kafka 消息一致）
"""
import json
import logging
import time
from influxdb import InfluxDBClient

logger = logging.getLogger(__name__)


class InfluxQuery:
    """InfluxDB 1.8 InfluxQL query + write helper."""

    def __init__(self, host: str, port: int, database: str, user: str = "", password: str = ""):
        self._client = InfluxDBClient(
            host=host,
            port=port,
            username=user or None,
            password=password or None,
            database=database,
        )
        self._db = database

    # ─── Write Methods (T-102) ───

    def write_stats(self, data: dict) -> None:
        """Write a stats message to InfluxDB as intersection_stats measurement."""
        try:
            intersection_id = data.get("intersection_id", "unknown")
            ts = data.get("timestamp", time.time())

            fields = {
                "cars": float(data.get("cars", 0) or 0),
                "fps": float(data.get("fps", 0) or 0),
                "congestion_index": float(data.get("congestion_index", 0) or 0),
                "active_tracks": int(data.get("active_tracks", 0) or 0),
                "total_vehicles": int(data.get("total_vehicles", 0) or 0),
            }

            # 动态道路数：写入 road_1..road_N（向后兼容）
            roads = data.get("roads", [])
            if roads and isinstance(roads, list):
                for r in roads:
                    rid = r.get("id")
                    act = r.get("activity")
                    if rid is not None and act is not None:
                        fields[f"road_{rid}"] = float(act)
            else:
                # 向后兼容：从 road_1..road_N 字段直接提取
                for i in range(1, 9):
                    val = data.get(f"road_{i}")
                    if val is not None:
                        fields[f"road_{i}"] = float(val)

            # 方向流量统计
            direction_flow = data.get("direction_flow")
            if direction_flow and isinstance(direction_flow, dict):
                for d_name in ("straight", "left_turn", "right_turn", "u_turn"):
                    d = direction_flow.get(d_name, {})
                    if isinstance(d, dict):
                        fields[f"dir_{d_name}_count"] = int(d.get("count", 0) or 0)
                        fields[f"dir_{d_name}_avg_speed"] = float(d.get("avg_speed_kmh", 0) or 0)

            # 整体指标
            if "avg_speed_kmh" in data and data["avg_speed_kmh"] is not None:
                fields["avg_speed_kmh"] = float(data["avg_speed_kmh"])
            if "queue_count" in data and data["queue_count"] is not None:
                fields["queue_count"] = int(data["queue_count"])

            point = {
                "measurement": "intersection_stats",
                "tags": {
                    "intersection_id": intersection_id,
                    "camera_id": str(data.get("camera_id", "")),
                },
                "fields": fields,
                "time": int(ts * 1e9),  # 纳秒
            }
            self._client.write_points([point])
        except Exception as e:
            logger.error(f"InfluxDB write_stats error: {e}")

    def write_track_event(self, data: dict) -> None:
        """Write a track_complete event to InfluxDB as track_events measurement."""
        try:
            intersection_id = data.get("intersection_id", "unknown")
            track_id = data.get("track_id", 0)

            fields = {
                "track_id": int(track_id),
                "duration_sec": float(data.get("duration_sec", 0) or 0),
                "avg_speed_kmh": float(data.get("avg_speed_kmh", 0) or 0),
                "max_speed_kmh": float(data.get("max_speed_kmh", 0) or 0),
            }

            # 世界坐标轨迹（T-404: 统一使用 trajectory_world_m 字段名）
            traj_world = data.get("trajectory_world_m")
            if traj_world:
                fields["trajectory_world_m"] = json.dumps(traj_world)

            # 像素坐标轨迹（备用）
            traj_px = data.get("trajectory_px")
            if traj_px:
                fields["trajectory_px"] = json.dumps(traj_px)

            # 入口/出口世界坐标
            entry_m = data.get("entry_point_m")
            if entry_m:
                fields["entry_point_m"] = json.dumps(entry_m)
            exit_m = data.get("exit_point_m")
            if exit_m:
                fields["exit_point_m"] = json.dumps(exit_m)

            # GPS 锚点
            anchor = data.get("world_anchor_lat_lon")
            if anchor:
                fields["world_anchor_lat_lon"] = json.dumps(anchor)

            # 道路信息
            start_road = data.get("start_road")
            if start_road is not None:
                fields["start_road"] = int(start_road)
            exit_road = data.get("exit_road")
            if exit_road is not None:
                fields["exit_road"] = int(exit_road)

            tags = {
                "intersection_id": intersection_id,
                "turn_behavior": str(data.get("turn_behavior", "unknown")),
                "vehicle_class": str(data.get("vehicle_class", "unknown")),
            }

            ts = data.get("timestamp_last", time.time())
            point = {
                "measurement": "track_events",
                "tags": tags,
                "fields": fields,
                "time": int(ts * 1e9),
            }
            self._client.write_points([point])
        except Exception as e:
            logger.error(f"InfluxDB write_track_event error: {e}")

    def write_conflict_event(self, data: dict) -> None:
        """Write a conflict event to InfluxDB as conflict_events measurement."""
        try:
            intersection_id = data.get("intersection_id", "unknown")

            fields = {
                "motor_id": int(data.get("motor_id", 0) or 0),
                "non_motor_id": int(data.get("non_motor_id", 0) or 0),
                "ttc_sec": float(data.get("ttc_sec", 0) or 0),
                "distance_m": float(data.get("distance_m", 0) or 0),
            }

            tags = {
                "intersection_id": intersection_id,
                "severity": str(data.get("severity", "info")),
            }

            ts = data.get("timestamp", time.time())
            point = {
                "measurement": "conflict_events",
                "tags": tags,
                "fields": fields,
                "time": int(ts * 1e9),
            }
            self._client.write_points([point])
        except Exception as e:
            logger.error(f"InfluxDB write_conflict_event error: {e}")

    # ─── Query Methods ───

    def query_stats(
        self,
        intersection_id: str,
        period: str = "1h",
        granularity: str = "1m",
    ) -> list[dict]:
        """Query intersection stats time series.

        T-201: 动态查询所有 road_* 字段，不再硬编码 road_1..5。
        """
        # 先查全部字段（SELECT *），前端/消费方自行取所需
        q = f"""
            SELECT mean("cars") AS "cars",
                   mean("fps") AS "fps",
                   mean("congestion_index") AS "congestion_index",
                   mean("avg_speed_kmh") AS "avg_speed_kmh",
                   mean("active_tracks") AS "active_tracks"
            FROM "intersection_stats"
            WHERE "intersection_id" = '{intersection_id}'
              AND time > now() - {period}
            GROUP BY time({granularity})
            ORDER BY time ASC
        """
        try:
            result = self._client.query(q)
            points = list(result.get_points())

            # T-201: 额外查询动态道路字段（road_1..road_8）
            road_query = f"""
                SELECT *
                FROM "intersection_stats"
                WHERE "intersection_id" = '{intersection_id}'
                  AND time > now() - {period}
                GROUP BY time({granularity})
                ORDER BY time ASC
            """
            road_result = self._client.query(road_query)
            road_points = list(road_result.get_points())

            # 合并：将 road_* 字段加入主查询结果
            if road_points:
                road_fields = {}
                for rp in road_points:
                    for k, v in rp.items():
                        if k.startswith("road_") and v is not None:
                            if k not in road_fields:
                                road_fields[k] = []
                            road_fields[k].append(v)

                # 对每个时间点，计算均值
                for i, point in enumerate(points):
                    for k, vals in road_fields.items():
                        if i < len(vals):
                            point[k] = vals[i]

            return points
        except Exception as e:
            logger.error(f"InfluxDB query error: {e}")
            return []

    def query_lane_stats(
        self,
        intersection_id: str,
        period: str = "10m",
        granularity: str = "1s",
    ) -> list[dict]:
        """Query lane-level stats time series."""
        q = f"""
            SELECT *
            FROM "intersection_stats"
            WHERE "intersection_id" = '{intersection_id}'
              AND time > now() - {period}
            GROUP BY time({granularity})
            ORDER BY time ASC
        """
        try:
            result = self._client.query(q)
            return list(result.get_points())
        except Exception as e:
            logger.error(f"InfluxDB query error: {e}")
            return []

    def query_track_events(
        self,
        intersection_id: str,
        period: str = "1h",
        limit: int = 500,
        turn_behavior: str | None = None,
        class_name: str | None = None,
    ) -> list[dict]:
        """Query track events.

        T-404: 返回的轨迹字段统一为 trajectory_world_m（与 Kafka 消息一致）。
        """
        conditions = f"'intersection_id' = '{intersection_id}' AND time > now() - {period}"
        if turn_behavior:
            conditions += f" AND 'turn_behavior' = '{turn_behavior}'"
        if class_name:
            conditions += f" AND 'vehicle_class' = '{class_name}'"

        q = f"""
            SELECT * FROM "track_events"
            WHERE {conditions}
            ORDER BY time DESC
            LIMIT {limit}
        """
        try:
            result = self._client.query(q)
            points = list(result.get_points())
            # 反序列化 JSON 字段
            for p in points:
                for field in ("trajectory_world_m", "trajectory_px", "entry_point_m",
                              "exit_point_m", "world_anchor_lat_lon"):
                    if field in p and isinstance(p[field], str):
                        try:
                            p[field] = json.loads(p[field])
                        except (json.JSONDecodeError, TypeError):
                            pass
            return points
        except Exception as e:
            logger.error(f"InfluxDB query error: {e}")
            return []

    def query_turn_summary(
        self,
        intersection_id: str,
        period: str = "1h",
    ) -> list[dict]:
        """Query turn behavior aggregation."""
        q = f"""
            SELECT count("track_id") AS "count"
            FROM "track_events"
            WHERE "intersection_id" = '{intersection_id}'
              AND time > now() - {period}
            GROUP BY "turn_behavior"
        """
        try:
            result = self._client.query(q)
            return list(result.get_points())
        except Exception as e:
            logger.error(f"InfluxDB query error: {e}")
            return []

    def query_system_metrics(
        self,
        period: str = "30m",
        granularity: str = "5s",
    ) -> list[dict]:
        """Query system metrics time series."""
        q = f"""
            SELECT mean("fps") AS "fps",
                   mean("inference_ms") AS "inference_ms",
                   mean("gpu_util_pct") AS "gpu_util_pct",
                   mean("gpu_vram_used_mb") AS "gpu_vram_used_mb",
                   mean("gpu_temp_c") AS "gpu_temp_c",
                   mean("kafka_lag") AS "kafka_lag"
            FROM "system_metrics"
            WHERE time > now() - {period}
            GROUP BY time({granularity})
            ORDER BY time ASC
        """
        try:
            result = self._client.query(q)
            return list(result.get_points())
        except Exception as e:
            logger.error(f"InfluxDB query error: {e}")
            return []

    def query_conflict_events(
        self,
        intersection_id: str,
        period: str = "1h",
        limit: int = 200,
    ) -> list[dict]:
        """Query conflict events history."""
        q = f"""
            SELECT * FROM "conflict_events"
            WHERE "intersection_id" = '{intersection_id}'
              AND time > now() - {period}
            ORDER BY time DESC
            LIMIT {limit}
        """
        try:
            result = self._client.query(q)
            return list(result.get_points())
        except Exception as e:
            logger.error(f"InfluxDB query error: {e}")
            return []

    def query_lane_changes(
        self,
        intersection_id: str,
        period: str = "1h",
    ) -> list[dict]:
        """Query lane change events."""
        q = f"""
            SELECT * FROM "track_events"
            WHERE "intersection_id" = '{intersection_id}'
              AND time > now() - {period}
              AND "lane_change" = true
            ORDER BY time DESC
            LIMIT 200
        """
        try:
            result = self._client.query(q)
            return list(result.get_points())
        except Exception as e:
            logger.error(f"InfluxDB query error: {e}")
            return []

    def close(self):
        """Close the InfluxDB client."""
        self._client.close()
