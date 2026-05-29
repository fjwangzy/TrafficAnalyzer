"""InfluxDB query helper."""
import logging
from influxdb import InfluxDBClient

logger = logging.getLogger(__name__)


class InfluxQuery:
    """InfluxDB 1.8 InfluxQL query helper."""

    def __init__(self, host: str, port: int, database: str, user: str = "", password: str = ""):
        self._client = InfluxDBClient(
            host=host,
            port=port,
            username=user or None,
            password=password or None,
            database=database,
        )
        self._db = database

    def query_stats(
        self,
        intersection_id: str,
        period: str = "1h",
        granularity: str = "1m",
    ) -> list[dict]:
        """Query intersection stats time series."""
        q = f"""
            SELECT mean("cars") AS "cars",
                   mean("road_1") AS "road_1",
                   mean("road_2") AS "road_2",
                   mean("road_3") AS "road_3",
                   mean("road_4") AS "road_4",
                   mean("road_5") AS "road_5"
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
        """Query track events."""
        conditions = f"'intersection_id' = '{intersection_id}' AND time > now() - {period}"
        if turn_behavior:
            conditions += f" AND 'turn_behavior' = '{turn_behavior}'"
        if class_name:
            conditions += f" AND 'class_name' = '{class_name}'"

        q = f"""
            SELECT * FROM "track_events"
            WHERE {conditions}
            ORDER BY time DESC
            LIMIT {limit}
        """
        try:
            result = self._client.query(q)
            return list(result.get_points())
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
