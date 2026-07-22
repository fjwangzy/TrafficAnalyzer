#!/usr/bin/env python3
"""Verify trajectory analysis invariants against several road9 intersections."""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from math import dist
from statistics import median
from time import perf_counter

from sqlalchemy import func, select, text

from app.core.database import async_session_maker
from app.models.metrics import TrackEvent
from app.services.metric_store import PostgresMetricStoreAdapter


async def main(
    intersection_limit: int,
    intersection_id: str | None = None,
    period: str = "all",
    explain: bool = False,
) -> None:
    async with async_session_maker() as session:
        statement = select(
            TrackEvent.inter_id,
            func.count(TrackEvent.id).label("track_count"),
            func.min(func.coalesce(TrackEvent.started_at, TrackEvent.ended_at)).label("start_at"),
            func.max(TrackEvent.ended_at).label("end_at"),
        )
        if intersection_id:
            statement = statement.where(TrackEvent.inter_id == intersection_id)
        rows = (await session.execute(
            statement
            .group_by(TrackEvent.inter_id)
            .order_by(func.count(TrackEvent.id).desc(), TrackEvent.inter_id)
            .limit(intersection_limit)
        )).all()

    store = PostgresMetricStoreAdapter(async_session_maker)
    summaries = []
    for inter_id, expected_count, start_at, end_at in rows:
        started = perf_counter()
        analysis = await store.query_trajectory_analysis(
            inter_id,
            period=period,
            bucket_sec=10,
            track_limit=50,
        )
        elapsed_ms = round((perf_counter() - started) * 1000, 1)
        quality = analysis["quality"]
        ranking = analysis["movement_ranking"]
        business = analysis["class_summary"]["business"]
        yolo = analysis["class_summary"]["yolo"]
        if period == "all":
            assert quality["total_tracks"] + quality["duplicate_tracks_omitted"] == expected_count
        assert sum(item["vehicle_count"] for item in ranking) == quality["total_tracks"]
        assert sum(item["count"] for item in business) == quality["total_tracks"]
        assert sum(item["count"] for item in yolo) == quality["total_tracks"]
        assert len(analysis["timeline"]) <= 720
        assert quality["returned_tracks"] <= 50
        renderable_slice_tracks = sum(
            1 for track in analysis["slice_tracks"]
            if len(track.get("trajectory_enu_m") or []) >= 2
        )
        moving_slice_tracks = sum(
            1 for track in analysis["slice_tracks"]
            if len(track.get("trajectory_enu_m") or []) >= 2
            and track["trajectory_enu_m"][0][:2] != track["trajectory_enu_m"][-1][:2]
        )
        slice_displacements_m = [
            dist(track["trajectory_enu_m"][0][:2], track["trajectory_enu_m"][-1][:2])
            for track in analysis["slice_tracks"]
            if len(track.get("trajectory_enu_m") or []) >= 2
        ]
        slice_path_lengths_m = [
            sum(dist(start[:2], end[:2]) for start, end in zip(points, points[1:]))
            for track in analysis["slice_tracks"]
            if len(points := track.get("trajectory_enu_m") or []) >= 2
        ]
        if quality["replayable_tracks"]:
            assert quality["returned_tracks"] > 0
            assert renderable_slice_tracks == quality["returned_tracks"]
            assert moving_slice_tracks > 0
        summaries.append({
            "intersection_id": inter_id,
            "period": period,
            "window": [analysis["query"]["start_at"], analysis["query"]["end_at"]],
            "source_window": [start_at.isoformat(), end_at.isoformat()],
            "tracks": quality["total_tracks"],
            "duplicate_tracks_omitted": quality["duplicate_tracks_omitted"],
            "replayable_tracks": quality["replayable_tracks"],
            "movements": len(ranking),
            "top_movement": ranking[0] if ranking else None,
            "business_classes": business,
            "raw_yolo_classes": yolo,
            "slice_tracks": quality["returned_tracks"],
            "renderable_slice_tracks": renderable_slice_tracks,
            "moving_slice_tracks": moving_slice_tracks,
            "slice_displacement_m": {
                "median": round(median(slice_displacements_m), 2) if slice_displacements_m else 0.0,
                "max": round(max(slice_displacements_m), 2) if slice_displacements_m else 0.0,
            },
            "slice_path_length_m": {
                "median": round(median(slice_path_lengths_m), 2) if slice_path_lengths_m else 0.0,
                "max": round(max(slice_path_lengths_m), 2) if slice_path_lengths_m else 0.0,
            },
            "slice_conflicts": len(analysis["conflicts"]),
            "timeline_buckets": len(analysis["timeline"]),
            "status": quality["status"],
            "elapsed_ms": elapsed_ms,
        })
    output = {"verified_intersections": len(summaries), "items": summaries}
    if explain and summaries:
        candidate = summaries[0]
        async with async_session_maker() as session:
            plan = (await session.execute(text(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) "
                "SELECT id FROM uav_track_events "
                "WHERE inter_id = :inter_id AND ended_at >= :start_at AND ended_at <= :end_at "
                "ORDER BY ended_at, track_id"
            ), {
                "inter_id": candidate["intersection_id"],
                "start_at": datetime.fromisoformat(candidate["window"][0]),
                "end_at": datetime.fromisoformat(candidate["window"][1]),
            })).scalars().all()
        output["explain_plan"] = plan
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--intersection-limit", type=int, default=3)
    parser.add_argument("--intersection-id")
    parser.add_argument("--period", choices=("all", "latest30m", "1h", "24h"), default="all")
    parser.add_argument("--explain", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(
        max(1, min(args.intersection_limit, 10)),
        args.intersection_id,
        args.period,
        args.explain,
    ))
