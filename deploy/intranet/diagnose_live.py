#!/usr/bin/env python3
"""Read-only diagnosis of the latest Mission's Kafka statistics and database inbox."""
import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

for candidate in Path(__file__).resolve().parents:
    if (candidate / 'platform/app').is_dir():
        sys.path.insert(0, str(candidate))
        sys.path.insert(0, str(candidate / 'platform'))
        break


async def sample_mjpeg(port, seconds=10):
    """Read only complete JPEG frames from the detector's loopback listener."""
    import httpx

    result = {'frames_received': 0, 'distinct_frames': 0}
    if not isinstance(port, int) or not 1 <= port <= 65535:
        return {**result, 'status': 'video_port_missing'}
    seen = set()
    buffer = b''
    started = time.monotonic()
    try:
        async with asyncio.timeout(seconds):
            async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(2, read=None)) as client:
                async with client.stream('GET', f'http://127.0.0.1:{port}/video') as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        buffer += chunk
                        if len(buffer) > 10 * 1024 * 1024:
                            raise ValueError('frame_too_large')
                        while b'\xff\xd8' in buffer and b'\xff\xd9' in buffer:
                            start = buffer.index(b'\xff\xd8')
                            end = buffer.index(b'\xff\xd9', start) + 2
                            seen.add(hashlib.sha256(buffer[start:end]).digest())
                            result['frames_received'] += 1
                            buffer = buffer[end:]
        result['status'] = 'stream_ended'
    except TimeoutError:
        result['status'] = 'sample_complete'
    except Exception as exc:
        result['status'] = type(exc).__name__
    return {**result, 'distinct_frames': len(seen), 'sample_seconds': round(time.monotonic() - started, 2)}


async def main():
    from aiokafka import AIOKafkaConsumer
    from sqlalchemy import text
    from app.core.config import settings
    from app.core.database import engine, close_db

    report = {'operation': 'read_only', 'runtime_profile': settings.app_runtime_profile}
    device_id = os.environ.get('ASCEND_DEVICE_ID', '0')
    device_path = f'/dev/davinci{device_id}' if device_id.isdecimal() else '/dev/invalid-device-id'
    report['detector_configuration'] = {
        'device': settings.pipeline_device,
        'ascend_device_id': device_id,
        'manifest': settings.pipeline_ascend_manifest,
        'manifest_exists': bool(settings.pipeline_ascend_manifest and Path(settings.pipeline_ascend_manifest).is_file()),
        'device_nodes': {name: Path(name).exists() for name in (
            device_path, '/dev/davinci_manager', '/dev/devmm_svm', '/dev/hisi_hdc')},
    }
    consumer = None
    try:
        async with engine.connect() as connection:
            async with connection.begin():
                await connection.execute(text('SET TRANSACTION READ ONLY'))
                await connection.execute(text("SET LOCAL statement_timeout = '10s'"))
                mission = (await connection.execute(text(
                    "SELECT m.id, m.pipeline_id, p.video_port, v.profile_id AS source_profile_id, m.inter_id, m.status FROM uav_missions m JOIN uav_video_sources v ON v.id=m.video_source_id "
                    "LEFT JOIN uav_pipelines p ON p.id=m.pipeline_id "
                    "WHERE m.pipeline_id IS NOT NULL ORDER BY (m.status='running') DESC, m.created_at DESC LIMIT 1"
                ))).mappings().first()
                if mission is None:
                    report['status'] = 'no_mission'
                    return report
                report['mission'] = dict(mission)
                topic = 'uav_replay_v2_statistics_' + mission['source_profile_id']
                report['database'] = dict((await connection.execute(text(
                    'SELECT count(*) AS samples, max(sampled_at) AS latest_sample_at '
                    'FROM uav_replay_v2_traffic_metric_samples WHERE mission_id=:mission'
                ), {'mission': mission['id']})).mappings().one())
                report['database']['topic_max_stored_offset'] = await connection.scalar(text(
                    'SELECT max("offset") FROM uav_replay_v2_message_inbox WHERE topic=:topic'
                ), {'topic': topic})
        if settings.app_runtime_profile != 'replay_v2':
            report['status'] = 'requires_replay_v2_profile'
            return report
        topic = 'uav_replay_v2_statistics_' + mission['source_profile_id']
        report['topic'] = topic
        consumer = AIOKafkaConsumer(bootstrap_servers=settings.kafka_bootstrap,
                                   group_id=None, enable_auto_commit=False,
                                   **settings.kafka_security_options)
        async with asyncio.timeout(30):
            await consumer.start()
            if topic not in await consumer.topics():
                report['status'] = 'statistics_topic_not_visible'
                return report
            consumer.subscribe([topic])
            await consumer.getmany(timeout_ms=1000, max_records=1)
            assigned = sorted(consumer.assignment(), key=lambda item: item.partition)
            ends = await consumer.end_offsets(assigned)
            report['kafka_end_offsets'] = {str(p.partition): offset for p, offset in ends.items()}
            for partition in assigned:
                consumer.seek(partition, max(0, ends[partition] - 1))
            batches = await consumer.getmany(timeout_ms=5000, max_records=len(assigned))
            report['detector_video'] = await sample_mjpeg(mission['video_port'])
            later_ends = await consumer.end_offsets(assigned)
            report['kafka_records_added_during_video_sample'] = sum(later_ends[p] - ends[p] for p in assigned)
        records = [record for rows in batches.values() for record in rows]
        if not records:
            report['status'] = 'no_statistics_record'
            return report
        message = json.loads(max(records, key=lambda row: row.timestamp).value)
        data = message.get('data', {})
        report['statistics'] = {key: data.get(key) for key in (
            'pipeline_id', 'source_profile_id', 'cars', 'active_tracks', 'fps', 'inference_ms',
            'pipeline_processing_ms',
            'avg_speed_kmh', 'geo_analytics_eligible', 'road_analytics_eligible', 'inference_context')}
        quality = data.get('geo_reference_quality') or {}
        report['quality'] = {key: quality.get(key) for key in ('status', 'geo_reasons', 'road_reasons')}
        report['produced_at'] = message.get('produced_at')
        try:
            produced = datetime.fromisoformat(str(message.get('produced_at')).replace('Z', '+00:00'))
            report['statistics_age_seconds'] = round((datetime.now(timezone.utc) - produced).total_seconds(), 1)
        except (ValueError, TypeError):
            report['statistics_age_seconds'] = None
        stored_offset = report['database']['topic_max_stored_offset']
        if stored_offset is not None and ends and stored_offset >= max(ends.values()):
            report['warning'] = 'Kafka offsets are behind existing inbox offsets; inspect offset reuse errors before any data repair'
        report['status'] = ('statistics_identity_mismatch'
                            if data.get('pipeline_id') != mission['pipeline_id']
                            else 'statistics_available')
        return report
    finally:
        if consumer is not None:
            await consumer.stop()
        await close_db()


if __name__ == '__main__':
    try:
        result = asyncio.run(main())
    except Exception as exc:
        # SQL/broker exception text can include credentials or full payloads.
        result = {'operation': 'read_only', 'status': 'diagnostic_failed', 'error_type': type(exc).__name__}
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
