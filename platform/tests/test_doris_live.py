"""Opt-in read-only public Doris verification; no external writes or copied secrets."""
import json
import os
from pathlib import Path
import time

import pytest

pytestmark = pytest.mark.skipif(os.environ.get('RUN_DORIS_INTEGRATION') != '1', reason='requires explicitly enabled external Doris SELECT access')


@pytest.mark.asyncio
async def test_live_doris_roads_metrics_cache_and_independent_values():
    from app.core.config import Settings
    from app.core.doris_connection import query
    from app.services.dashboard_situation import DashboardSituationReadModel
    from app.services.ycx_road_import import YcxRoadImporter

    root = Path(__file__).resolve().parents[2]
    settings = Settings(_env_file=root / 'platform/.env')
    assert settings.db_name == 'road9' and settings.deployment_mode == 'local'
    assert not settings.ycx_db_host
    started = time.monotonic()
    reader = DashboardSituationReadModel(settings)
    payload = await reader.situation(day_of_week=5, step_index=95)
    elapsed = time.monotonic() - started
    assert payload['source']['database'] == 'ycx_xc'
    assert payload['source']['intersection_table'] == 'dws_tfc_inter_index_m_5mi'
    assert payload['source']['segment_table'] == 'dws_tfc_link_index_m_5mi'
    assert payload['intersections'] and payload['segments']
    assert len({row['inter_id'] for row in payload['intersections']}) == len(payload['intersections'])
    assert len({row['link_id'] for row in payload['segments']}) == len(payload['segments'])
    assert all(row['saturation_max'] is None for row in payload['intersections'])
    assert all(row['queue_len_est_m'] is None for row in payload['segments'])
    item = next(row for row in payload['intersections'] if row['delay_index'] is not None)
    expected = await query(settings,
        'SELECT MAX(avg_jam_delay_index_avg) AS value FROM dws_tfc_inter_index_m_5mi '
        'WHERE stat_month=%s AND version_id=%s AND inter_id=%s AND day_of_week=%s AND step_index=%s '
        'AND COALESCE(is_deleted,0)=0',payload['source']['stat_month'],payload['source']['road_version'],item['inter_id'],5,95)
    assert item['delay_index'] == pytest.approx(float(expected[0]['value']))
    cache_started = time.monotonic()
    cached = await reader.situation(day_of_week=5,step_index=95)
    cache_elapsed = time.monotonic() - cache_started
    assert cached['cache']['status'] == 'hit' and cached['summary'] == payload['summary']
    roads = []
    importer = YcxRoadImporter(settings)
    for inter_id in ('011wwe0z19700001','011wwe28dm500001','011wwe28dr400003','011wwe29k1q00001'):
        if inter_id == '011wwe28dr400003':
            with pytest.raises(LookupError):
                await importer.import_intersection(inter_id)
            roads.append({'inter_id':inter_id,'status':'not_in_current_version'})
            continue
        road = await importer.import_intersection(inter_id)
        assert road.payload['links'] and road.payload['lanes']
        nearby = await importer.nearby_intersections(road.anchor_gcj02)
        assert inter_id in {row['inter_id'] for row in nearby}
        roads.append({'inter_id':inter_id,'version':road.road_data_version,'links':len(road.payload['links']),
                      'lanes':len(road.payload['lanes']),'nearby':len(nearby),'checksum':road.checksum})
    result = {'source':payload['source'],'summary':payload['summary'], 'cold_seconds':round(elapsed,3),
              'cache_seconds':round(cache_elapsed,3),'roads':roads,'external_writes':0,'numeric_cross_check':'passed'}
    output = root / '.runtime/doris-validation.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
