"""S8 project dashboard read model built only from road9 facts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.models.metrics import ConflictEvent, TelemetryMetric, TrafficMetric
from app.models.mission import DroneRecord, MissionRecord, PipelineRecord, RoadContextSnapshot
from app.models.survey import AiEvent, DeadLetter, EventOutbox, SurveyTask


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    normalized = _utc(value)
    return normalized.isoformat() if normalized else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class DashboardReadModel:
    """Aggregate S1-S4/S9 facts without creating a second business truth source."""

    schema_version = "uav.dashboard/v1"
    window = timedelta(minutes=30)
    freshness = timedelta(minutes=2)

    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def _facts(self, as_of: datetime | None = None) -> dict:
        now = _utc(as_of) or datetime.now(UTC)
        window_start = now - self.window
        async with self._session_factory() as session:
            snapshots = (await session.execute(
                select(RoadContextSnapshot)
                .distinct(RoadContextSnapshot.inter_id)
                .order_by(RoadContextSnapshot.inter_id, RoadContextSnapshot.created_at.desc())
            )).scalars().all()
            latest_snapshots = {row.inter_id: row for row in snapshots}

            metrics = (await session.execute(
                select(TrafficMetric)
                .where(TrafficMetric.grain_type == "intersection", TrafficMetric.observed_at <= now)
                .distinct(TrafficMetric.inter_id)
                .order_by(TrafficMetric.inter_id, TrafficMetric.observed_at.desc())
            )).scalars().all()
            latest_metrics = {row.inter_id: row for row in metrics}

            conflicts = (await session.execute(
                select(ConflictEvent)
                .where(ConflictEvent.occurred_at >= window_start, ConflictEvent.occurred_at <= now)
                .order_by(ConflictEvent.occurred_at.desc())
                .limit(500)
            )).scalars().all()
            ai_events = (await session.execute(
                select(AiEvent)
                .where(AiEvent.occurred_at >= window_start, AiEvent.occurred_at <= now)
                .order_by(AiEvent.occurred_at.desc())
                .limit(500)
            )).scalars().all()
            missions = (await session.execute(
                select(MissionRecord).order_by(MissionRecord.created_at.desc()).limit(1000)
            )).scalars().all()
            pipelines = (await session.execute(
                select(PipelineRecord).order_by(PipelineRecord.created_at.desc()).limit(1000)
            )).scalars().all()
            drones = (await session.execute(select(DroneRecord).order_by(DroneRecord.id))).scalars().all()
            telemetry = (await session.execute(
                select(TelemetryMetric)
                .where(TelemetryMetric.observed_at <= now)
                .distinct(TelemetryMetric.drone_id)
                .order_by(TelemetryMetric.drone_id, TelemetryMetric.observed_at.desc())
            )).scalars().all()
            latest_telemetry = {row.drone_id: row for row in telemetry if row.drone_id}

            survey_tasks = (await session.execute(
                select(SurveyTask).order_by(SurveyTask.updated_at.desc()).limit(500)
            )).scalars().all()
            failed_outbox = await session.scalar(
                select(func.count()).select_from(EventOutbox).where(EventOutbox.status.in_(("failed", "retrying")))
            ) or 0
            open_dead_letters = await session.scalar(
                select(func.count()).select_from(DeadLetter).where(DeadLetter.status == "open")
            ) or 0

        return {
            "as_of": now,
            "window_start": window_start,
            "snapshots": latest_snapshots,
            "metrics": latest_metrics,
            "conflicts": conflicts,
            "ai_events": ai_events,
            "missions": missions,
            "pipelines": pipelines,
            "drones": drones,
            "telemetry": latest_telemetry,
            "survey_tasks": survey_tasks,
            "failed_outbox": int(failed_outbox),
            "open_dead_letters": int(open_dead_letters),
        }

    @staticmethod
    def _coordinates(snapshot: RoadContextSnapshot) -> tuple[float | None, float | None]:
        payload = snapshot.payload or {}
        intersection = payload.get("intersection") or {}
        lat = _number(intersection.get("center_lat", intersection.get("lat", payload.get("center_lat"))))
        lon = _number(intersection.get("center_lon", intersection.get("lon", payload.get("center_lon"))))
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None, None
        return lat, lon

    def _intersection_rows(self, facts: dict) -> list[dict]:
        now = facts["as_of"]
        running_missions = {
            row.inter_id: row for row in facts["missions"] if row.status in {"starting", "running"}
        }
        pipelines_by_mission = {row.mission_id: row for row in facts["pipelines"]}
        conflicts_by_inter: dict[str, list[ConflictEvent]] = {}
        for event in facts["conflicts"]:
            conflicts_by_inter.setdefault(event.inter_id, []).append(event)
        events_by_inter: dict[str, list[AiEvent]] = {}
        for event in facts["ai_events"]:
            if event.inter_id:
                events_by_inter.setdefault(event.inter_id, []).append(event)

        rows = []
        for inter_id, snapshot in facts["snapshots"].items():
            payload = snapshot.payload or {}
            intersection = payload.get("intersection") or {}
            metric = facts["metrics"].get(inter_id)
            metric_at = _utc(metric.observed_at) if metric else None
            fresh_metric = bool(metric_at and now - metric_at <= self.freshness)
            mission = running_missions.get(inter_id)
            pipeline = pipelines_by_mission.get(mission.id) if mission else None
            pipeline_running = bool(pipeline and pipeline.observed_status == "running")
            road_verified = snapshot.quality_status == "verified"
            coordinate_reference = snapshot.coordinate_reference or {}
            coordinate_verified = (
                coordinate_reference.get("status") == "verified"
                and coordinate_reference.get("display") == "WGS84"
            )
            coordinate_test = (
                coordinate_reference.get("status") == "test"
                and coordinate_reference.get("display") == "WGS84"
                and coordinate_reference.get("usage") == "local_acceptance_only"
            )
            monitor = "running" if fresh_metric and mission and pipeline_running and road_verified else (
                "degraded" if fresh_metric or mission or pipeline_running else "standby"
            )
            verified_conflicts = [
                event for event in conflicts_by_inter.get(inter_id, []) if event.quality_status == "verified"
            ]
            risk = "critical" if any(event.severity == "critical" for event in verified_conflicts) else (
                "warning" if verified_conflicts else "unknown"
            )
            lat, lon = self._coordinates(snapshot)
            map_coordinate_status = "verified" if road_verified and coordinate_verified else (
                "test" if coordinate_test else "unavailable"
            )
            map_eligible = map_coordinate_status != "unavailable" and lat is not None and lon is not None
            quality = "verified" if road_verified and fresh_metric else (
                "stale" if metric_at and not fresh_metric else "unverified"
            )
            rows.append({
                "id": inter_id,
                "inter_id": inter_id,
                "name": intersection.get("name") or payload.get("name") or inter_id,
                "lat": lat if map_eligible else None,
                "lon": lon if map_eligible else None,
                "map_eligible": map_eligible,
                "map_coordinate_status": map_coordinate_status,
                "map_exclusion_reason": None if map_eligible else (
                    "coordinate_missing" if lat is None or lon is None else (
                        "coordinate_reference_unverified" if not coordinate_verified else "road_context_unverified"
                    )
                ),
                "road_data_version": snapshot.road_data_version,
                "road_context_checksum": snapshot.checksum,
                "road_context_quality": snapshot.quality_status,
                "coordinate_reference": coordinate_reference,
                "monitor": monitor,
                "risk": risk,
                "quality": quality,
                "last_metric_at": _iso(metric_at),
                "metric": {
                    "cars": metric.cars if metric else None,
                    "avg_speed_kmh": metric.avg_speed_kmh if metric else None,
                    "congestion_index": metric.congestion_index if metric else None,
                    "coverage_ratio": metric.coverage_ratio if metric else None,
                    "quality_status": metric.quality_status if metric else "missing",
                },
                "mission_id": mission.id if mission else None,
                "drone_id": mission.drone_id if mission else None,
                "pipeline_id": pipeline.id if pipeline else None,
                "events": [self._event(event) for event in events_by_inter.get(inter_id, [])[:5]],
                "conflict_count": len(verified_conflicts),
            })
        return sorted(rows, key=lambda item: (item["risk"] != "critical", item["name"]))

    @staticmethod
    def _event(event: AiEvent) -> dict:
        return {
            "id": event.id,
            "event_type": event.event_type,
            "inter_id": event.inter_id,
            "occurred_at": _iso(event.occurred_at),
            "review_status": event.review_status,
            "quality_status": event.quality_status,
            "delivery_status": event.delivery_status,
            "validation_fixture": bool((event.payload or {}).get("validation_fixture")),
        }

    async def overview(self) -> dict:
        facts = await self._facts()
        intersections = self._intersection_rows(facts)
        fresh_count = sum(1 for row in intersections if row["last_metric_at"] and row["quality"] == "verified")
        enabled_drones = [row for row in facts["drones"] if row.enabled]
        fresh_drones = sum(
            1 for row in enabled_drones
            if row.id in facts["telemetry"]
            and facts["as_of"] - _utc(facts["telemetry"][row.id].observed_at) <= self.freshness
        )
        verified_risk = sum(1 for row in intersections if row["risk"] in {"critical", "warning"})
        isolated = sum(1 for row in intersections if not row["map_eligible"])
        test_coordinates = sum(1 for row in intersections if row["map_coordinate_status"] == "test")
        pending_review = [event for event in facts["ai_events"] if event.review_status in {"generated", "pending_review"}]
        pending_survey = [task for task in facts["survey_tasks"] if task.delivery_status not in {"delivered"} and task.state in {"technical_reviewed", "reported"}]
        tasks = []
        if pending_review:
            tasks.append({"task_type": "ai_review", "count": len(pending_review), "target_route": "/events", "quality": "unverified"})
        if pending_survey:
            tasks.append({"task_type": "survey_delivery", "count": len(pending_survey), "target_route": "/survey", "quality": "unverified"})
        delivery_count = facts["failed_outbox"] + facts["open_dead_letters"]
        if delivery_count:
            tasks.append({"task_type": "integration_replay", "count": delivery_count, "target_route": "/admin/integration", "quality": "verified"})
        if isolated:
            tasks.append({"task_type": "configuration_check", "count": isolated, "target_route": "/admin/calibration", "quality": "unverified"})
        elif not intersections:
            tasks.append({"task_type": "configuration_check", "count": 1, "target_route": "/admin/calibration", "quality": "missing"})

        attention = []
        if not intersections:
            attention.append({
                "id": "project-scope-missing", "inter_id": None, "kind": "configuration",
                "reason": "当前授权范围没有可用的 RoadContext 项目路口快照",
                "quality": "missing", "target_route": "/admin/calibration",
            })
        for row in intersections:
            if row["risk"] in {"critical", "warning"}:
                attention.append({
                    "id": row["id"], "inter_id": row["inter_id"], "kind": "risk",
                    "reason": f"窗口内 {row['conflict_count']} 条已验证冲突事实",
                    "quality": row["quality"], "target_route": f"/events?intersection_id={row['inter_id']}",
                })
            elif row["quality"] != "verified":
                attention.append({
                    "id": row["id"], "inter_id": row["inter_id"], "kind": "data_quality",
                    "reason": row["map_exclusion_reason"] or "态势数据未达到新鲜度门槛",
                    "quality": row["quality"], "target_route": f"/gis?intersection_id={row['inter_id']}",
                })

        return {
            "schema_version": self.schema_version,
            "project_scope": "local_road9_authorized_scope",
            "as_of": _iso(facts["as_of"]),
            "window_start": _iso(facts["window_start"]),
            "window_end": _iso(facts["as_of"]),
            "road_data_versions": sorted({row["road_data_version"] for row in intersections}),
            "data_quality": "unverified",
            "coverage_ratio": None,
            "coverage_definition_status": "blocked_s8_tbd_001_005",
            "kpis": [
                {"id": "monitoring_coverage", "label": "监测覆盖", "value": None, "numerator": fresh_count, "denominator": len(intersections), "quality": "unverified", "reason": "正式在监定义和 coverage 门槛未批准"},
                {"id": "priority_risk", "label": "重点风险路口", "value": verified_risk if intersections else None, "numerator": verified_risk, "denominator": len(intersections), "quality": "unverified", "reason": "仅计已验证窗口事实；风险阈值仍待批准"},
                {"id": "severe_congestion", "label": "重度拥堵", "value": None, "numerator": None, "denominator": len(intersections), "quality": "unverified", "reason": "拥堵阈值和窗口未批准"},
                {"id": "drone_assurance", "label": "无人机保障", "value": None, "numerator": fresh_drones, "denominator": len(enabled_drones), "quality": "unverified", "reason": "保障资源分母和在线门槛未批准"},
                {"id": "data_trust", "label": "数据可信度", "value": None, "numerator": fresh_count, "denominator": len(intersections), "quality": "unverified", "reason": "综合可信度公式未批准"},
            ],
            "attention": attention[:10],
            "pending_tasks": tasks,
            "health": {
                "status": "degraded" if not intersections or isolated or test_coordinates or delivery_count else "healthy",
                "database": "healthy",
                "project_intersections": len(intersections),
                "map_eligible_intersections": len(intersections) - isolated,
                "test_coordinate_intersections": test_coordinates,
                "isolated_intersections": isolated,
                "failed_delivery_items": delivery_count,
            },
        }

    async def intersections(
        self,
        *,
        risk: str | None = None,
        monitor: str | None = None,
        quality: str | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        query: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> dict:
        facts = await self._facts()
        rows = self._intersection_rows(facts)
        project_total = len(rows)
        if risk:
            rows = [row for row in rows if row["risk"] == risk]
        if monitor:
            rows = [row for row in rows if row["monitor"] == monitor]
        if quality:
            rows = [row for row in rows if row["quality"] == quality]
        if bbox:
            min_lon, min_lat, max_lon, max_lat = bbox
            rows = [
                row for row in rows
                if row["map_eligible"]
                and min_lon <= row["lon"] <= max_lon
                and min_lat <= row["lat"] <= max_lat
            ]
        if query:
            needle = query.casefold().strip()
            rows = [
                row for row in rows
                if needle in row["inter_id"].casefold() or needle in row["name"].casefold()
            ]
        filtered_total = len(rows)
        page = rows[offset:offset + limit]
        return {
            "schema_version": self.schema_version,
            "as_of": _iso(facts["as_of"]),
            "items": page,
            "total": filtered_total,
            "project_total": project_total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(page) < filtered_total,
            "map_eligible": sum(1 for row in rows if row["map_eligible"]),
            "test_coordinates": sum(1 for row in rows if row["map_coordinate_status"] == "test"),
            "isolated": sum(1 for row in rows if not row["map_eligible"]),
            "filters": {
                "risk": risk,
                "monitor": monitor,
                "quality": quality,
                "bbox": list(bbox) if bbox else None,
                "query": query,
            },
        }

    async def intersection(self, inter_id: str) -> dict | None:
        facts = await self._facts()
        row = next((item for item in self._intersection_rows(facts) if item["inter_id"] == inter_id), None)
        return row

    async def drones(self) -> dict:
        facts = await self._facts()
        items = []
        running_by_drone = {
            row.drone_id: row for row in facts["missions"] if row.status in {"starting", "running"}
        }
        for drone in facts["drones"]:
            telemetry = facts["telemetry"].get(drone.id)
            observed_at = _utc(telemetry.observed_at) if telemetry else None
            fresh = bool(observed_at and facts["as_of"] - observed_at <= self.freshness)
            mission = running_by_drone.get(drone.id)
            items.append({
                "id": drone.id, "name": drone.name, "enabled": drone.enabled,
                "status": "online" if fresh and drone.enabled else ("offline" if drone.enabled else "disabled"),
                "telemetry_at": _iso(observed_at), "telemetry_quality": telemetry.quality_status if telemetry else "missing",
                "lat": _number(telemetry.latitude) if fresh else None,
                "lon": _number(telemetry.longitude) if fresh else None,
                "battery_pct": _number(telemetry.battery_pct) if fresh else None,
                "mission_id": mission.id if mission else None, "inter_id": mission.inter_id if mission else None,
            })
        return {"schema_version": self.schema_version, "as_of": _iso(facts["as_of"]), "items": items}
