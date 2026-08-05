import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const authState = {
  user: { username: 'admin', role: 'admin' },
  status: 'authenticated',
  isAuthenticated: true,
  platformRole: 'admin',
  consoleRole: 'admin',
  login: vi.fn(),
  logout: vi.fn(),
}

vi.mock('./auth/AuthContext', () => ({
  AuthProvider: ({ children }) => children,
  useAuth: () => authState,
  isSafeRedirect: (value) => Boolean(value?.startsWith('/') && !value.startsWith('//') && !value.includes('://')),
}))

vi.mock('./hooks/useWebSocket', () => ({ useWebSocket: () => 'connected' }))

vi.mock('./lib/api', async (importOriginal) => {
  const actual = await importOriginal()
  const task = { id: 'SVY-20260713-006', title: '测试测绘', location: '小清河路口', owner: '事故处理一组', status: 'measuring', quality: 'unverified', delivery: 'not_generated', version: 'v4', revision: 4, selected_batch_id: 'BATCH-01' }
  const frame = { id: 'FRM-01', task_id: task.id, batch_id: 'BATCH-01', frame_number: 18236, timestamp_sec: 10, has_metric_transform: true, metric_transform: [[0.1, 0, 0], [0, 0.1, 0], [0, 0, 1]], image_url: '/api/v1/survey-evidence/EVI-IMAGE/content', bev_url: '/api/v1/survey-evidence/EVI-BEV/content', quality: {}, telemetry: {} }
  const measurement = { id: 'M-01', revision: 1, frame_id: frame.id, geometry_type: 'line', category: '刹车痕迹', image_geometry: [[10, 10], [40, 40]], metric_geometry: [[1, 1], [4, 4]], display_value: '12.48m', quality_status: 'unverified', source: 'manual' }
  const report = { id: 'RPT-01', task_id: task.id, version: 1, status: 'generated', schema_version: 'uav.survey-result.v1', content_hash: 'a'.repeat(64), payload: {}, pdf_url: '/api/v1/survey-evidence/EVI-PDF/content', delivery_blocked_reason: 'survey quality thresholds are not approved' }
  const conflictEvent = { id: 'UAV-EVT-20260713-001', source_kind: 'conflict', event_type: 'conflict', inter_id: 'INT-I5', title: '机非冲突风险升高', severity: 'critical', occurred_at: '2026-07-15T02:52:16Z', quality_status: 'unverified', review_status: 'pending', review_revision: 1, delivery_status: 'not_queued', evidence_refs: [{ id: 'EVI-CONFLICT-ORIGINAL', kind: 'conflict_original_frame', storage_backend: 'managed', storage_key: `objects/00/${'0'.repeat(64)}`, sha256: '0'.repeat(64) }, { id: 'EVI-CONFLICT-DETECTOR', kind: 'conflict_detector_frame', storage_backend: 'managed', storage_key: `objects/11/${'1'.repeat(64)}`, sha256: '1'.repeat(64) }], payload: { conflict_scene: '机非冲突风险升高', ttc_sec: 1.2, pet_sec: 0.8, distance_m: 0, risk_score: 86, evidence_status: 'complete', evidence: ['path_intersection'] } }
  const congestionEvent = { id: 'UAV-EVT-20260713-004', source_kind: 'ai_event', event_type: 'congestion', inter_id: 'INT-I5', title: '排队增长', severity: 'P2', occurred_at: '2026-07-15T02:50:00Z', quality_status: 'unverified', review_status: 'pending', review_revision: 1, delivery_status: 'not_queued', payload: { metrics: { congestion_index: 7.0 } } }
  const surveyEvent = { id: 'UAV-EVT-20260713-005', source_kind: 'ai_event', event_type: 'survey_result', inter_id: 'INT-I5', title: '事故测绘成果', severity: 'P3', occurred_at: '2026-07-15T02:49:00Z', quality_status: 'unverified', review_status: 'technical_reviewed', review_revision: 1, delivery_status: 'blocked', payload: { measurements: [{ id: 'M-01' }], task: { version: 'v7' } } }
  return {
    ...actual,
    platformApi: {
      ...actual.platformApi,
      intersections: vi.fn().mockResolvedValue([
        { id: '370102000104', name: '小清河北路 × 水屯路', center_gcj02: { latitude: 36.7029, longitude: 117.0223 }, coordinate_system: 'GCJ02', status: 'active', quality_status: 'unverified' },
      ]),
      dashboardOverview: vi.fn().mockResolvedValue({
        schema_version: 'uav.dashboard/v1', project_scope: 'local_road9_authorized_scope', as_of: '2026-07-15T05:52:00Z', window_start: '2026-07-15T05:22:00Z', window_end: '2026-07-15T05:52:00Z', road_data_versions: ['ROAD-I5'], coverage_definition_status: 'blocked_s8_tbd_001_005',
        kpis: [
          { id: 'monitoring_coverage', label: '监测覆盖', value: null, numerator: 0, denominator: 1, quality: 'unverified', reason: '正式口径未批准' },
          { id: 'priority_risk', label: '重点风险路口', value: 0, numerator: 0, denominator: 1, quality: 'unverified', reason: '仅计已验证事实' },
          { id: 'severe_congestion', label: '重度拥堵', value: null, numerator: null, denominator: 1, quality: 'unverified', reason: '阈值未批准' },
          { id: 'drone_assurance', label: '无人机保障', value: null, numerator: 0, denominator: 1, quality: 'unverified', reason: '分母未批准' },
          { id: 'data_trust', label: '数据可信度', value: null, numerator: 0, denominator: 1, quality: 'unverified', reason: '公式未批准' },
        ],
        attention: [{ id: 'INT-I5', inter_id: 'INT-I5', kind: 'data_quality', reason: 'road_context_unverified', quality: 'unverified', target_route: '/gis?intersection_id=INT-I5' }],
        pending_tasks: [{ task_type: 'configuration_check', count: 1, target_route: '/admin/calibration', quality: 'unverified' }],
        health: { status: 'degraded', database: 'healthy', project_intersections: 1, map_eligible_intersections: 0, isolated_intersections: 1, failed_delivery_items: 0 },
      }),
      dashboardIntersections: vi.fn().mockResolvedValue({ schema_version: 'uav.dashboard/v1', total: 1, map_eligible: 0, isolated: 1, items: [
        { id: 'INT-I5', inter_id: 'INT-I5', name: 'I5 未验证路口', lat: null, lon: null, map_eligible: false, map_exclusion_reason: 'road_context_unverified', road_data_version: 'ROAD-I5', monitor: 'standby', risk: 'unknown', quality: 'unverified', last_metric_at: null, metric: {}, mission_id: null, drone_id: null, pipeline_id: null, events: [], conflict_count: 0 },
      ] }),
      dashboardDrones: vi.fn().mockResolvedValue({ schema_version: 'uav.dashboard/v1', items: [{ id: 'UAV-I5', name: 'I5 drone', enabled: true, status: 'offline', telemetry_quality: 'missing' }] }),
      dashboardSituation: vi.fn().mockResolvedValue({
        schema_version: 'uav.dashboard-situation/v1',
        source: { database: 'ycx', road_schema: 'road9', metrics_schema: 'xianchang', road_version: '20260501', read_mode: 'readonly' },
        time_profile: { kind: 'typical_5min', timezone: 'Asia/Shanghai', day_of_week: 2, step_index: 120, start_time: '10:00', available_days: [1, 2, 5] },
        cache: { status: 'miss', stale: false },
        summary: { intersections_total: 1, good: 0, near_saturated: 0, oversaturated: 1, missing: 0, segments_total: 1, smooth_segments: 0, slow_segments: 0, congested_segments: 1, missing_segments: 0 },
        intersections: [{ inter_id: 'INT_camera_1', name: '小清河北路 × 水屯路', lon: 117.0223, lat: 36.7029, saturation_max: 0.98, saturation_avg: 0.83, unbalance_index: 0.17, level_of_service: 'E', status: 'oversaturated' }],
        segments: [{ id: 'INT_camera_1:LINK-1', inter_id: 'INT_camera_1', link_id: 'LINK-1', name: '小清河北路东进口', direction: '东进口', delay_index: 2.2, avg_nostop_speed: 18.4, queue_len_est_m: 96, status: 'congested', paths_gcj02: [[[117.01, 36.7], [117.03, 36.705]]] }],
      }),
      trajectories: vi.fn().mockResolvedValue([{ id: 'TRK-1', track_id: 7, trajectory_gcj02: [[117, 36.7], [117.0001, 36.7001]], quality_status: 'unverified' }]),
      trajectoryAnalysis: vi.fn().mockResolvedValue({
        query: { intersection_id: 'INT-I5', period: 'all', start_at: '2026-07-21T08:00:00Z', end_at: '2026-07-21T08:00:20Z', slice_start_at: '2026-07-21T08:00:10Z', slice_end_at: '2026-07-21T08:00:20Z', bucket_sec: 10 },
        quality: { total_tracks: 2, replayable_tracks: 2, returned_tracks: 1, truncated: false, unattributed_conflicts: 0, spatial_coverage_ratio: 1, status: 'complete' },
        timeline: [{ start_at: '2026-07-21T08:00:00Z', end_at: '2026-07-21T08:00:10Z', active_tracks: 1, conflict_count: 0 }, { start_at: '2026-07-21T08:00:10Z', end_at: '2026-07-21T08:00:20Z', active_tracks: 2, conflict_count: 1 }],
        movement_ranking: [{ movement_key: 'entry:1|exit:2', movement_label: '东进口 → 西出口', vehicle_count: 2, share: 1, avg_speed_kmh: 31.5, p85_speed_kmh: 38, conflict_count: 1 }],
        class_summary: { business: [{ class_name: 'motor', count: 2 }], yolo: [{ class_id: 3, class_name: 'car', model_id: 'yolo11s.pt@abc123', count: 2 }], unknown_yolo_name_count: 0 },
        slice_tracks: [{ id: 'TRK-1', track_id: '7', mission_id: 'MSN-1', pipeline_id: 'PIPE-1', source_profile_id: 'SRC-1', movement_key: 'entry:1|exit:2', movement_label: '东进口 → 西出口', trajectory_enu_m: [[0, 0], [1, 1]], trajectory_gcj02: [[117, 36.7], [117.0001, 36.7001]], anchor_gcj02: [117, 36.7], vehicle_class: 'motor', yolo_class_id: 3, yolo_class_name: 'car', yolo_model_id: 'yolo11s.pt@abc123', class_mapping_version: 'visdrone-business/v1', quality_status: 'verified', avg_speed_kmh: 31.5, max_speed_kmh: 42, started_at: '2026-07-21T08:00:00Z', ended_at: '2026-07-21T08:00:20Z' }],
        conflicts: [{ id: 'C-1', occurred_at: '2026-07-21T08:00:15Z', severity: 'warning', ttc_sec: 1.2, attributed_movements: ['entry:1|exit:2'] }],
      }),
      replayMissions: vi.fn().mockResolvedValue({ schema_version: 'uav.replay-missions/v1', items: [
        { mission_id: 'MSN-1', source_profile_id: 'SRC-1', status: 'sealed', duration_ms: 20000, coordinate_coverage_ratio: 1, journey_count: 1, behavior_count: 1, algorithm_versions: { sampling: 'event-faithful/v1' }, accuracy: { idf1: 'not_evaluated', hota: 'not_evaluated', id_switch: 'not_evaluated', position_rmse: 'not_evaluated', speed_mae: 'not_evaluated', reid_accuracy: 'not_evaluated' } },
      ] }),
      trajectoryReplay: vi.fn().mockResolvedValue({
        schema_version: 'uav.trajectory-replay/v1',
        mission: { mission_id: 'MSN-1', source_profile_id: 'SRC-1', pipeline_id: 'PIPE-1', status: 'sealed', duration_ms: 20000, coordinate_coverage_ratio: 1, journey_count: 1, behavior_count: 1, accuracy: { idf1: 'not_evaluated' } },
        cursor: { offset_ms: 0, window_start_ms: 0, window_end_ms: 0, duration_ms: 20000 },
        coordinate_mode: 'gcj02',
        tracks: [{ track_id: '7', source_runtime_track_ids: ['17'], source_point_count: 3, retained_point_count: 3, sampling: { algorithm_version: 'event-faithful/v1' }, vehicle_class: 'motor', yolo_class_id: 3, yolo_class_name: 'car', movement_key: 'entry:1|exit:2', movement_label: '东进口 → 西出口', episodes: [{ kind: 'stopped', start_offset_ms: 8000, end_offset_ms: 12000 }], maneuvers: [], points: [
          { offset_ms: 0, frame_num: 1, pixel: [10, 20], enu_m: [0, 0], gcj02: [117, 36.7], speed: { instant_kmh: 10, ema_kmh: 9, enu_vector_mps: [2.5, 0], quality: 'reconstructed_from_full_sequence' }, quality: {}, sampling_boundary: ['journey_start'] },
          { offset_ms: 5000, frame_num: 2, pixel: [12, 20], enu_m: [1, 0], gcj02: [117.0001, 36.7001], speed: { instant_kmh: 8, ema_kmh: 8.5, enu_vector_mps: [2, 0], quality: 'reconstructed_from_full_sequence' }, quality: {}, sampling_boundary: [] },
          { offset_ms: 10000, frame_num: 3, pixel: [13, 20], enu_m: [2, 0], gcj02: [117.0002, 36.7002], speed: { instant_kmh: 1, ema_kmh: 2, enu_vector_mps: [0.2, 0], quality: 'reconstructed_from_full_sequence' }, quality: {}, sampling_boundary: ['stopped', 'quality_gap_start'] },
        ] }],
        analysis: {
          quality: { total_tracks: 1, replayable_tracks: 1, truncated: false, unattributed_conflicts: 0, spatial_coverage_ratio: 1, status: 'complete' },
          movement_ranking: [{ movement_key: 'entry:1|exit:2', movement_label: '东进口 → 西出口', movement_source: 'road_context', vehicle_count: 2, avg_speed_kmh: 31.5, p85_speed_kmh: 38, conflict_count: 1 }],
          class_summary: { business: [{ class_name: 'motor', count: 1 }], yolo: [{ class_id: 3, class_name: 'car', model_id: 'yolo11s.pt@abc123', count: 1 }], unknown_yolo_name_count: 0 },
          conflicts: [{ id: 'C-1', offset_ms: 10000, severity: 'warning', ttc_sec: 1.2 }],
        },
        conflicts: [{ id: 'C-1', offset_ms: 10000, severity: 'warning', ttc_sec: 1.2 }],
        truncated: false,
        next_cursor_ms: null,
      }),
      conflicts: vi.fn().mockResolvedValue([
        { id: 'UAV-EVT-20260713-001', inter_id: 'INT-I5', conflict_scene: '机非冲突风险升高', severity: 'critical', ttc_sec: 1.2, pet_sec: 0.8, distance_m: 0, risk_score: 86, evidence: ['path_intersection'], occurred_at: '2026-07-15T02:52:16Z', quality_status: 'unverified', time_quality: 'reconstructed', review_status: 'pending', review_revision: 1 },
      ]),
      alerts: vi.fn().mockResolvedValue([{ id: 'UAV-EVT-20260713-004', intersection_id: 'INT-I5', alert_type: 'congestion', severity: 'P2', title: '排队增长', description: 'queue', status: 'open', timestamp: '2026-07-15T02:50:00Z' }]),
      reviewConflict: vi.fn().mockImplementation((_interId, _eventId, body) => Promise.resolve({ id: 'UAV-EVT-20260713-001', inter_id: 'INT-I5', conflict_scene: '机非冲突风险升高', severity: 'critical', ttc_sec: 1.2, pet_sec: 0.8, occurred_at: '2026-07-15T02:52:16Z', quality_status: 'unverified', time_quality: 'reconstructed', review_status: body.review_status, review_revision: 2 })),
      events: vi.fn().mockResolvedValue([conflictEvent, congestionEvent, surveyEvent]),
      event: vi.fn().mockImplementation((eventId) => Promise.resolve({ ...(eventId === conflictEvent.id ? conflictEvent : congestionEvent), related_tracks: [] })),
      reviewEvent: vi.fn().mockImplementation((_eventId, body) => Promise.resolve({ ...conflictEvent, review_status: body.review_status, review_revision: 2 })),
      surveyTask: vi.fn().mockResolvedValue(task),
      surveyBatches: vi.fn().mockResolvedValue([{ id: 'BATCH-01', status: 'ready', telemetry_coverage: 0.94, quality_checks: { keyframes_extracted: 1, homography_available: 1 } }]),
      surveyFrames: vi.fn().mockResolvedValue([frame]),
      surveyMeasurements: vi.fn().mockResolvedValue([measurement]),
      surveyAction: vi.fn().mockImplementation((_id, body) => Promise.resolve({ ...task, status: body.action === 'submit_review' ? 'pending_review' : task.status, revision: 5, version: 'v5' })),
      surveyEvidence: vi.fn().mockResolvedValue(new Blob(['image'])),
      importSurveyBatch: vi.fn().mockResolvedValue({ id: 'BATCH-01', status: 'queued' }),
      surveyAnnotations: vi.fn().mockResolvedValue([]),
      createSurveyAnnotation: vi.fn(),
      updateSurveyAnnotation: vi.fn(),
      deleteSurveyAnnotation: vi.fn(),
      surveyReports: vi.fn().mockResolvedValue([]),
      generateSurveyReport: vi.fn().mockResolvedValue(report),
      drones: vi.fn().mockResolvedValue([
        { id: 'UAV-M300-03', name: 'M300 test', enabled: true, status: 'offline', telemetry_status: 'stale', battery_pct: null, revision: 1, default_inter_id: 'INT_camera_1', default_road_data_version: 'ROAD-LOCAL-INTER-XQH', intersection_name: '小清河北路 × 水屯路', road_context_quality: 'unverified', default_video_source_id: 'VID-1' },
      ]),
      sources: vi.fn().mockResolvedValue([
        { profile_id: 'SRC-LOCAL-XQH', display_name: 'inter_xqh 早高峰', drone_id: 'UAV-M300-03', mode: 'local', enabled: true, validation_status: 'valid', revision: 1, video: { id: 'VID-1', source_type: 'mp4', location_hint: 'inter_xqh.mp4' }, telemetry: { id: 'TEL-1', source_type: 'srt', location_hint: 'telemetry.srt' } },
        { profile_id: 'SRC-LOCAL-XQH-PM', display_name: 'inter_xqh 晚高峰', drone_id: 'UAV-M300-03', mode: 'local', enabled: true, validation_status: 'valid', revision: 1, video: { id: 'VID-2', source_type: 'mp4', location_hint: 'inter_xqh-pm.mp4' }, telemetry: { id: 'TEL-2', source_type: 'file', location_hint: 'telemetry.txt' } },
      ]),
      pipelines: vi.fn().mockResolvedValue([]),
      sourceResults: vi.fn().mockResolvedValue({ profile_id: 'SRC-LOCAL-XQH', telemetry_type: 'dji_srt', missions: [], survey_tasks: [], counts: { traffic_metrics: 0, tracks: 0, conflicts: 0, survey_frames: 0, scene_annotations: 0, survey_reports: 0, lane_annotations: 0 }, links: { situation: '/gis', monitoring: '/drones?tab=fleet', insight: '/insight', survey: '/survey', scene_annotation: '/survey', lane_annotation: '/admin/calibration?tab=lane' } }),
      flightPlans: vi.fn().mockResolvedValue([
        { id: 'FP-20260713-03', name: '夜间货车限行验证', drone_id: 'UAV-M300-03', state: 'draft', revision: 1, timezone: 'Asia/Shanghai', schedule: { type: 'once', start_at: '2026-07-15T22:30:00+08:00', end_at: '2026-07-16T00:30:00+08:00' } },
      ]),
      missions: vi.fn().mockResolvedValue([
        { id: 'MSN-0713-1050', name: '早高峰巡检', drone_id: 'UAV-M300-03', trigger_type: 'manual', status: 'running', scheduled_start_at: '2026-07-15T10:50:00+08:00', actual_start_at: '2026-07-15T10:50:06+08:00', pipeline: { id: 'pipe-1', observed_status: 'running', camera_id: 17, video_stream_url: 'http://127.0.0.1:8127/video', tracking_profile: 'hover_only_legacy' } },
      ]),
      flightPlanAction: vi.fn().mockRejectedValue({ response: { data: { detail: { code: 'flight_plan_overlap', message: '发现同无人机时间冲突，计划保持草稿' } } } }),
      stopMission: vi.fn().mockResolvedValue({ id: 'MSN-0713-1050', status: 'cancelled', pipeline: { observed_status: 'stopped' } }),
      retryMission: vi.fn(),
      validateSource: vi.fn(),
      updateDrone: vi.fn(),
      createDrone: vi.fn(),
      createSource: vi.fn(),
      createFlightPlan: vi.fn(),
      createMission: vi.fn(),
      enforcementZones: vi.fn().mockResolvedValue([
        { id: 'ZONE-I4-01', name: '本地候选限行区', zone_type: 'truck_restriction', geometry: { type: 'Polygon', coordinates: [[[117, 36.7], [117.001, 36.7], [117.001, 36.701], [117, 36.7]]] }, coordinate_system: 'GCJ02', road_data_version: 'ROAD-I4', source: 'local_candidate', status: 'candidate', schedule: {}, checksum: 'b'.repeat(64), revision: 1, rule_count: 1, authority_status: 'unavailable' },
      ]),
      enforcementRules: vi.fn().mockResolvedValue([
        { id: 'RULE-I4-01', name: '候选货车事实规则', clue_type: 'truck_restriction', zone_id: 'ZONE-I4-01', status: 'candidate', quality_status: 'unverified', approval_status: 'blocked', revision: 1 },
      ]),
      enforcementClues: vi.fn().mockResolvedValue([
        { id: 'CLUE-I4-01', source_event_id: 'i4-fixture', clue_type: 'truck_restriction', vehicle_class: 'truck', track_id: 'track-7', video_speed_kmh: 21.4, radar_speed_kmh: null, evidence_integrity_status: 'hash_verified', evidence_count: 2, delivery_status: 'blocked', review_status: 'pending', review_revision: 1, quality_status: 'unverified', class_confidence: 0.91, occurred_at: '2026-07-15T05:20:00Z', validation_fixture: true },
      ]),
      enforcementClue: vi.fn().mockResolvedValue({ id: 'CLUE-I4-01', source_event_id: 'i4-fixture', clue_type: 'truck_restriction', vehicle_class: 'truck', track_id: 'track-7', video_speed_kmh: 21.4, radar_speed_kmh: null, evidence_integrity_status: 'hash_verified', evidence_count: 2, delivery_status: 'blocked', review_status: 'pending', review_revision: 1, quality_status: 'unverified', class_confidence: 0.91, occurred_at: '2026-07-15T05:20:00Z', validation_fixture: true, zone_id: 'ZONE-I4-01', zone_version: 'candidate-r1', rule_id: 'RULE-I4-01', rule_version: 'candidate-r1', evidence: [{ id: 'EVI-I4-01', kind: 'original_video', media_type: 'video/mp4', sha256: 'a'.repeat(64), size_bytes: 1024 }] }),
      reviewEnforcementClue: vi.fn().mockResolvedValue({ id: 'CLUE-I4-01', review_status: 'reviewed_confirmed', review_revision: 2 }),
      updateEnforcementZone: vi.fn().mockResolvedValue({ id: 'ZONE-I4-01', revision: 2, status: 'candidate' }),
      createEnforcementZone: vi.fn(),
      createEnforcementRule: vi.fn(),
      publishEnforcementZone: vi.fn().mockRejectedValue({ response: { data: { detail: { code: 'authority_adapter_unavailable', message: '权威发布 Adapter 未冻结' } } } }),
      enforcementTruckSummary: vi.fn().mockResolvedValue({ status: 'stale', active_count: 0, clue_count: 1, pending_review_count: 1, vehicles: [], reason: '不以历史事实伪造实时车辆位置' }),
    },
  }
})

vi.mock('./components/CityMap', () => ({
  CityMap: ({ offline = false, onSelect, onSourceSelect, points = [], sourcePoints = [] }) => <div data-testid='city-map'>
    {offline ? '城市底图服务不可用' : '演示地图'}
    {points[0] && <button aria-label={`打开路口 ${points[0].id}`} onClick={() => onSelect?.(points[0])}>路口点位</button>}
    {sourcePoints[0] && <button aria-label={`打开无人机 ${sourcePoints[0].id}`} onClick={() => onSourceSelect?.(sourcePoints[0])}>无人机点位</button>}
  </div>,
}))

import { RouterApp } from './RouterApp'
import { platformApi } from './lib/api'
import { buildDemoAnalysisSnapshot, upsertDemoSnapshot } from './lib/demoSnapshots'
import { firstPlayableSliceIndex, nextPlayableSliceIndex } from './pages/InsightPages'

function open(path) {
  window.history.pushState({}, '', path)
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(<QueryClientProvider client={queryClient}><RouterApp /></QueryClientProvider>)
}

describe('Console2 full prototype', () => {
  beforeEach(() => {
    window.localStorage.clear()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:event-evidence') })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
    Object.assign(authState, {
      user: { username: 'admin', role: 'admin' },
      status: 'authenticated',
      isAuthenticated: true,
      platformRole: 'admin',
      consoleRole: 'admin',
    })
    window.history.pushState({}, '', '/')
  })

  it('skips empty timeline buckets during automatic trajectory playback', () => {
    const timeline = [
      { start_at: '00:00:00', active_tracks: 0, conflict_count: 0 },
      { start_at: '00:00:10', active_tracks: 3, conflict_count: 0 },
      { start_at: '00:00:20', active_tracks: 0, conflict_count: 0 },
      { start_at: '00:00:30', active_tracks: 0, conflict_count: 1 },
    ]

    expect(firstPlayableSliceIndex(timeline)).toBe(1)
    expect(nextPlayableSliceIndex(timeline, 1)).toBe(3)
    expect(nextPlayableSliceIndex(timeline, 3)).toBe(-1)
  })

  it('renders the fixed UAV governance story at the root route', async () => {
    const { container } = open('/')
    expect(await screen.findByRole('heading', { name: '无人机交通态势工作台' })).toHaveClass('sr-only')
    expect(container.querySelector('.page-heading')).not.toBeInTheDocument()
    expect(container.querySelector('.page-actions')).toBeInTheDocument()
    expect(screen.queryByText('I5 内部工程口径')).not.toBeInTheDocument()
    expect(screen.queryByText('无人机路口态势纵览')).not.toBeInTheDocument()
    expect(container.querySelector('.map-master-panel > .panel-title')).not.toBeInTheDocument()
    expect(screen.getByText('发现态势')).toBeInTheDocument()
    expect(screen.getAllByText('调度无人机')).not.toHaveLength(0)
    expect(screen.getByText('机非冲突风险升高')).toBeInTheDocument()
    expect(screen.getByText('轻微事故等待测绘')).toBeInTheDocument()
    expect(screen.getByText('治理前后复盘')).toBeInTheDocument()
    expect(screen.getByText('服务器典型时段态势')).toBeInTheDocument()
    expect(screen.getByText('拥堵路段')).toBeInTheDocument()
    expect(screen.getByText('延误指数 > 2.0')).toBeInTheDocument()
    expect(container.querySelector('.situation-map-detail')).not.toBeInTheDocument()
    await waitFor(() => expect(platformApi.dashboardIntersections).toHaveBeenCalledWith({ limit: 500 }))
    expect(screen.getByRole('navigation', { name: '全域态势二级导航' })).toHaveTextContent('工作台首屏实时监测')
    expect(screen.getByRole('navigation', { name: '全域态势二级导航' })).not.toHaveTextContent('轨迹研判')
    expect(screen.getByRole('complementary', { name: '一级业务域' })).toBeInTheDocument()
  })

  it('requests the selected weekday and exact five-minute situation slot', async () => {
    platformApi.dashboardSituation.mockClear()
    open('/')

    await screen.findByRole('heading', { name: '无人机交通态势工作台' })
    fireEvent.change(screen.getByLabelText('星期'), { target: { value: '5' } })
    fireEvent.change(screen.getByLabelText('时间'), { target: { value: '95' } })

    await waitFor(() => expect(platformApi.dashboardSituation).toHaveBeenCalledWith(5, 95))
    expect(screen.getByLabelText('星期')).toHaveValue('5')
    expect(screen.getByLabelText('时间')).toHaveValue('95')
  })

  it('opens the selected intersection monitoring screen from a dashboard map marker', async () => {
    const source = { profile_id: 'SRC-MAP-1', display_name: '地图监测视频源', drone_id: 'UAV-MAP-1', enabled: true, validation_status: 'valid', video: { id: 'VID-MAP-1', source_type: 'mp4' } }
    const drone = { id: 'UAV-MAP-1', name: '地图监测无人机', default_inter_id: 'INT-MAP-1', default_video_source_id: 'VID-MAP-1', intersection_name: '地图监测路口' }
    const pipeline = { pipeline_id: 'PIPE-MAP-1', intersection_id: 'INT-MAP-1', source_profile_id: 'SRC-MAP-1', drone_id: 'UAV-MAP-1', camera_id: 17, video_stream_url: 'http://127.0.0.1:8127/video', status: 'running' }
    platformApi.dashboardIntersections.mockResolvedValueOnce({ schema_version: 'uav.dashboard/v1', total: 1, map_eligible: 1, isolated: 0, items: [
      { id: 'INT-MAP-1', inter_id: 'INT-MAP-1', name: '地图监测路口', center_gcj02: { latitude: 36.67, longitude: 116.99 }, coordinate_system: 'GCJ02', map_eligible: true, map_coordinate_status: 'test', road_data_version: 'ROAD-MAP', monitor: 'running', risk: 'normal', quality: 'unverified', metric: {}, events: [], conflict_count: 0 },
    ] })
    platformApi.dashboardSituation.mockResolvedValueOnce({
      schema_version: 'uav.dashboard-situation/v1',
      source: { road_version: '20260501' },
      time_profile: { kind: 'typical_5min', timezone: 'Asia/Shanghai', available_days: [1, 2, 5] },
      cache: { status: 'miss', stale: false },
      summary: { intersections_total: 1, good: 1, near_saturated: 0, oversaturated: 0, segments_total: 0 },
      intersections: [{ inter_id: 'INT-MAP-1', name: '地图监测路口', lon: 116.99, lat: 36.67, saturation_max: 0.72 }],
      segments: [],
    })
    platformApi.sources.mockResolvedValueOnce([source]).mockResolvedValueOnce([source])
    platformApi.drones.mockResolvedValueOnce([drone]).mockResolvedValueOnce([drone])
    platformApi.pipelines.mockResolvedValueOnce([pipeline]).mockResolvedValueOnce([pipeline])

    open('/')
    fireEvent.click(await screen.findByRole('button', { name: '打开无人机 INT-MAP-1' }))

    await waitFor(() => expect(window.location.pathname).toBe('/monitoring'))
    expect(new URLSearchParams(window.location.search).get('intersection_id')).toBe('INT-MAP-1')
    expect(new URLSearchParams(window.location.search).get('source_profile_id')).toBe('SRC-MAP-1')
    const sourceSelector = await screen.findByRole('combobox', { name: '选择无人机视频源' }, { timeout: 10_000 })
    await waitFor(() => expect(sourceSelector).toHaveDisplayValue('地图监测视频源 · 地图监测无人机'))
    expect(await screen.findByAltText('检测器输出视频流', {}, { timeout: 10_000 })).toHaveAttribute('src', expect.stringMatching(/^http:\/\/127\.0\.0\.1:8127\/video\?retry=/))
    expect(await screen.findByLabelText('飞行姿态数据')).toBeInTheDocument()
  })

  it('redispatches the drone into the governance review stage from the dashboard', async () => {
    open('/')

    const redispatch = await screen.findByRole('button', { name: '再次调度无人机复盘' })
    await waitFor(() => expect(redispatch).not.toBeDisabled())
    fireEvent.click(redispatch)

    await waitFor(() => expect(window.location.pathname).toBe('/monitoring'))
    expect(new URLSearchParams(window.location.search).get('stage')).toBe('review')
    const reviewButton = await screen.findByRole('button', { name: '治理复盘' })
    expect(reviewButton).toHaveClass('active')
    expect(screen.getByText('复用同一指标口径，对比治理前后效果', { exact: false })).toBeInTheDocument()
  })

  it('uses the same first-level rail and domain secondary navigation on monitoring', async () => {
    open('/monitoring')
    expect(await screen.findByRole('navigation', { name: '全域态势二级导航' })).toHaveTextContent('工作台首屏实时监测')
    expect(screen.getByRole('navigation', { name: '全域态势二级导航' })).not.toHaveTextContent('轨迹研判')
    expect(screen.getByRole('link', { name: '实时监测' })).toHaveClass('active')
    expect(screen.getByRole('complementary', { name: '一级业务域' })).toBeInTheDocument()
    expect(screen.getByLabelText('飞行姿态数据')).toBeInTheDocument()
  })

  it('moves trajectory analysis into the intelligent-insight navigation domain', async () => {
    const { container } = open('/gis')
    const navigation = await screen.findByRole('navigation', { name: '智能研判二级导航' })
    expect(navigation).toHaveTextContent('AI 事件中心轨迹研判')
    expect(screen.getByRole('link', { name: '轨迹研判' })).toHaveClass('active')
    expect(container.querySelector('.page-heading')).not.toBeInTheDocument()
    expect(screen.getByLabelText('时间窗口')).toHaveValue('latest30m')
  })

  it('plays only a sealed Mission on a continuous T+ clock', async () => {
    platformApi.sources.mockClear()
    open('/gis')

    await waitFor(() => expect(screen.getByLabelText('轨迹任务')).toHaveValue('MSN-1'))
    expect(screen.getByLabelText('任务回放时间')).toHaveAttribute('max', '20000')
    expect(screen.getAllByText('T+00:00.000').length).toBeGreaterThan(0)
    expect(platformApi.replayMissions).toHaveBeenCalledWith('INT-I5')
    expect(platformApi.sources).not.toHaveBeenCalled()
    expect(platformApi.trajectoryReplay).toHaveBeenCalledWith('INT-I5', expect.objectContaining({
      mission_id: 'MSN-1', cursor_sec: 0,
    }))
    expect(screen.getByTitle('quality_gap')).toBeInTheDocument()
    expect(screen.getByTitle('conflict')).toBeInTheDocument()
    expect(screen.getByText('瞬时 / EMA 速度')).toBeInTheDocument()
    expect(screen.getByText('1 / 2 km/h')).toBeInTheDocument()
    expect(screen.getByText('原始 / 保留点数')).toBeInTheDocument()
    expect(screen.getByText('Runtime segments（1）')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('任务回放时间'), { target: { value: '12000' } })
    await waitFor(() => expect(platformApi.trajectoryReplay).toHaveBeenCalledWith('INT-I5', expect.objectContaining({ cursor_sec: 12 })))

    fireEvent.change(screen.getByLabelText('轨迹任务'), { target: { value: 'all' } })
    await waitFor(() => expect(screen.getByRole('button', { name: '播放历史回放' })).toBeDisabled())
    expect(await screen.findByText('请选择单个封存 Mission')).toBeInTheDocument()
    expect(screen.queryByText('Track #7 识别与运行证据')).not.toBeInTheDocument()
  })

  it('keeps the default Mission replay unfiltered until a representative track is chosen', async () => {
    platformApi.trajectoryReplay.mockClear()
    open('/gis?intersection_id=INT-I5&mission_id=MSN-1')

    expect(await screen.findByText('Track #7 识别与运行证据')).toBeInTheDocument()
    await waitFor(() => expect(platformApi.trajectoryReplay).toHaveBeenCalled())

    expect(new URLSearchParams(window.location.search).get('track_id')).toBeNull()
    expect(platformApi.trajectoryReplay.mock.calls.every(([, options]) => !Object.hasOwn(options, 'track_id'))).toBe(true)
  })

  it('keeps replay queries on a bounded window as the Mission cursor advances', async () => {
    open('/gis?intersection_id=INT-I5&mission_id=MSN-1')

    await waitFor(() => expect(screen.getByLabelText('轨迹任务')).toHaveValue('MSN-1'))
    const slider = await screen.findByLabelText('任务回放时间')
    await waitFor(() => expect(slider).toHaveAttribute('max', '20000'))
    platformApi.trajectoryReplay.mockClear()
    fireEvent.change(slider, { target: { value: '18000' } })

    await waitFor(() => expect(platformApi.trajectoryReplay).toHaveBeenLastCalledWith(
      'INT-I5', expect.objectContaining({ cursor_sec: 18, window_sec: 10 }),
    ))
  })

  it('does not overlap replay requests while continuous playback advances', async () => {
    const baseReplay = await platformApi.trajectoryReplay('INT-I5', {})
    let releaseReplay
    platformApi.trajectoryReplay.mockImplementation((_intersectionId, options = {}) => (
      Number(options.cursor_sec || 0) > 0
        ? new Promise((resolve) => { releaseReplay = () => resolve(baseReplay) })
        : Promise.resolve(baseReplay)
    ))
    open('/gis?intersection_id=INT-I5&mission_id=MSN-1')

    const play = await screen.findByRole('button', { name: '播放历史回放' })
    await waitFor(() => expect(screen.getByLabelText('任务回放时间')).toHaveAttribute('max', '20000'))
    expect(await screen.findByText('1 条轨迹 · 1 个行为')).toBeInTheDocument()
    platformApi.trajectoryReplay.mockClear()
    fireEvent.click(play)
    await new Promise((resolve) => setTimeout(resolve, 1200))

    expect(platformApi.trajectoryReplay).toHaveBeenCalledTimes(1)
    await new Promise((resolve) => setTimeout(resolve, 1200))
    expect(platformApi.trajectoryReplay).toHaveBeenCalledTimes(1)
    releaseReplay?.()
  })

  it('clears focused track and stale replay data when switching Missions', async () => {
    const previousReplayImplementation = platformApi.trajectoryReplay.getMockImplementation()
    platformApi.replayMissions.mockResolvedValueOnce({ items: [
      { mission_id: 'MSN-1', source_profile_id: 'SRC-1', status: 'sealed', duration_ms: 20000, journey_count: 1, behavior_count: 1 },
      { mission_id: 'MSN-2', source_profile_id: 'SRC-2', status: 'sealed', duration_ms: 30000, journey_count: 0, behavior_count: 0 },
    ] })
    platformApi.trajectoryReplay.mockImplementation((_intersectionId, options) => Promise.resolve(
      options.mission_id === 'MSN-2'
        ? { mission: { mission_id: 'MSN-2', source_profile_id: 'SRC-2' }, cursor: { offset_ms: 0, duration_ms: 30000 }, tracks: [], analysis: { quality: {}, movement_ranking: [], class_summary: { business: [], yolo: [] }, conflicts: [] }, conflicts: [] }
        : { mission: { mission_id: 'MSN-1', source_profile_id: 'SRC-1' }, cursor: { offset_ms: 0, duration_ms: 20000 }, tracks: [{ track_id: '7', source_runtime_track_ids: ['17'], source_point_count: 1, retained_point_count: 1, episodes: [], maneuvers: [], points: [{ offset_ms: 0, pixel: [1, 1], gcj02: null, speed: { instant_kmh: null, ema_kmh: null }, quality: {} }] }], analysis: { quality: {}, movement_ranking: [], class_summary: { business: [], yolo: [] }, conflicts: [] }, conflicts: [] }
    ))
    open('/gis?mission_id=MSN-1&track_id=7')

    expect(await screen.findByText('Track #7 识别与运行证据')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('轨迹任务'), { target: { value: 'MSN-2' } })

    await waitFor(() => expect(new URLSearchParams(window.location.search).get('mission_id')).toBe('MSN-2'))
    expect(new URLSearchParams(window.location.search).get('track_id')).toBeNull()
    await waitFor(() => expect(screen.queryByText('Track #7 识别与运行证据')).not.toBeInTheDocument())
    expect(await screen.findByText('当前时间片没有轨迹。')).toBeInTheDocument()
    platformApi.trajectoryReplay.mockImplementation(previousReplayImplementation)
  })

  it('binds the source and trajectory filters to the sealed Mission replay request', async () => {
    platformApi.replayMissions.mockResolvedValueOnce({ items: [
      { mission_id: 'MSN-1', source_profile_id: 'SRC-1', status: 'sealed', duration_ms: 20000, journey_count: 1 },
      { mission_id: 'MSN-2', source_profile_id: 'SRC-2', status: 'sealed', duration_ms: 30000, journey_count: 1 },
    ] })
    open('/gis?intersection_id=INT-I5&source_profile_id=SRC-2')

    await waitFor(() => expect(screen.getByLabelText('轨迹任务')).toHaveValue('MSN-2'))
    await waitFor(() => expect(platformApi.trajectoryReplay).toHaveBeenLastCalledWith(
      'INT-I5', expect.objectContaining({ mission_id: 'MSN-2' }),
    ))

    fireEvent.change(screen.getByLabelText('车辆类型'), { target: { value: 'non_motor' } })
    await waitFor(() => expect(platformApi.trajectoryReplay).toHaveBeenLastCalledWith(
      'INT-I5', expect.objectContaining({ mission_id: 'MSN-2', vehicle_class: 'non_motor' }),
    ))
    fireEvent.change(screen.getByLabelText('转向类型'), { target: { value: 'left_turn' } })
    await waitFor(() => expect(platformApi.trajectoryReplay).toHaveBeenLastCalledWith(
      'INT-I5', expect.objectContaining({ mission_id: 'MSN-2', vehicle_class: 'non_motor', turn_behavior: 'left_turn' }),
    ))
  })

  it('never requests sealed Mission replay from realtime monitoring', async () => {
    platformApi.replayMissions.mockClear()
    platformApi.trajectoryReplay.mockClear()

    open('/monitoring')
    expect(await screen.findByLabelText('飞行姿态数据')).toBeInTheDocument()
    expect(platformApi.replayMissions).not.toHaveBeenCalled()
    expect(platformApi.trajectoryReplay).not.toHaveBeenCalled()
  })

  it('places trajectory quality indicators at the bottom of the analysis page', async () => {
    const { container } = open('/gis')

    expect(await screen.findByText('正式精度尚未评估')).toBeInTheDocument()
    expect(container.querySelector('.trajectory-analysis-page')?.lastElementChild)
      .toHaveClass('trajectory-quality-notices')
  })

  it('uses flow ranking and raw detector classes to explain the selected time slice', async () => {
    open('/gis')

    expect(await screen.findByRole('tab', { name: '流向排名' })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: '东进口 → 西出口 2 辆' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: /原始分类/ }))
    expect(await screen.findByText('YOLO car')).toBeInTheDocument()
    expect(screen.getByText('yolo11s.pt@abc123')).toBeInTheDocument()
    expect(screen.getByLabelText('任务回放时间')).toHaveAttribute('max', '20000')
    fireEvent.click(screen.getByRole('tab', { name: '代表轨迹' }))
    expect(await screen.findByText('源 SRC-1 · 任务 MSN-1 · 管道 PIPE-1')).toBeInTheDocument()
  })

  it('sorts flow ranking accessibly and preserves the analysis state in the URL', async () => {
    const baseReplay = await platformApi.trajectoryReplay('INT-I5', {})
    platformApi.trajectoryReplay.mockClear()
    platformApi.trajectoryReplay.mockResolvedValueOnce({
      ...baseReplay,
      analysis: { ...baseReplay.analysis, movement_ranking: [
        { movement_key: 'entry:1|exit:2', movement_label: '东进口 → 西出口', movement_source: 'road_context', vehicle_count: 2, share: 0.25, avg_speed_kmh: 31.5, p85_speed_kmh: 38, conflict_count: 1 },
        { movement_key: 'entry:3|exit:4', movement_label: '北进口 → 南出口', movement_source: 'road_context', vehicle_count: 6, share: 0.75, avg_speed_kmh: 18, p85_speed_kmh: 24, conflict_count: 0 },
      ] },
    })

    open('/gis?intersection_id=INT-I5&period=all&movement_sort=avg_speed&start_at=2026-07-21T08%3A00%3A00Z&end_at=2026-07-21T08%3A00%3A20Z&slice_start_at=2026-07-21T08%3A00%3A10Z&slice_end_at=2026-07-21T08%3A00%3A20Z')

    const sortBySpeed = await screen.findByRole('button', { name: '按均速排序' })
    expect(sortBySpeed).toHaveAttribute('aria-pressed', 'true')
    const rankedRows = await screen.findAllByRole('button', { name: /进口 → .*出口 .* 辆/ })
    expect(rankedRows[0]).toHaveAccessibleName('东进口 → 西出口 2 辆')

    fireEvent.click(screen.getByRole('button', { name: '按冲突排序' }))
    await waitFor(() => expect(new URLSearchParams(window.location.search).get('movement_sort')).toBe('conflict'))
    fireEvent.change(screen.getByLabelText('回放速度'), { target: { value: '2' } })
    await waitFor(() => expect(new URLSearchParams(window.location.search).get('playback_speed')).toBe('2'))
    fireEvent.click(screen.getByRole('button', { name: '东进口 → 西出口 2 辆' }))
    await waitFor(() => expect(new URLSearchParams(window.location.search).get('movement_key')).toBe('entry:1|exit:2'))

    await waitFor(() => expect(platformApi.trajectoryReplay).toHaveBeenLastCalledWith('INT-I5', expect.objectContaining({
      movement_key: 'entry:1|exit:2',
    })))
    expect(screen.getByRole('tab', { name: '流向排名' })).toHaveAttribute('aria-selected', 'true')
  })

  it('does not present pending road9 trajectory queries as zero data', async () => {
    let resolveIntersections
    platformApi.dashboardIntersections.mockImplementationOnce(() => new Promise((resolve) => {
      resolveIntersections = resolve
    }))

    open('/gis')

    expect(await screen.findByText('路口加载中 · 轨迹等待路口')).toBeInTheDocument()
    expect(screen.queryByText('0 个路口 · 0 条轨迹')).not.toBeInTheDocument()

    resolveIntersections({
      schema_version: 'uav.dashboard/v1', total: 1, items: [
        { id: 'INT-I5', inter_id: 'INT-I5', name: 'I5 未验证路口', lat: null, lon: null, map_eligible: false, map_exclusion_reason: 'road_context_unverified', road_data_version: 'ROAD-I5', monitor: 'standby', risk: 'unknown', quality: 'unverified', metric: {}, events: [], conflict_count: 0 },
      ],
    })

    await waitFor(() => expect(screen.getByText('1 个路口 · 1 条轨迹')).toBeInTheDocument())
    expect(platformApi.replayMissions).toHaveBeenCalledWith('INT-I5')
  })

  it('keeps the current trajectory frame visible while the next replay slice loads', async () => {
    const firstSlice = await platformApi.trajectoryReplay('INT-I5', {})
    const secondSlice = { ...firstSlice, cursor: { ...firstSlice.cursor, offset_ms: 4000, window_end_ms: 4000 } }
    let resolveSecondSlice
    platformApi.trajectoryReplay.mockImplementation((_intersectionId, options = {}) => (
      Number(options.cursor_sec || 0) > 0
        ? new Promise((resolve) => { resolveSecondSlice = resolve })
        : Promise.resolve(firstSlice)
    ))

    open('/gis?intersection_id=INT-I5&period=all&playback_speed=4')

    expect(await screen.findByText('1 条轨迹 · 1 个行为', {}, { timeout: 10_000 })).toBeInTheDocument()
    platformApi.trajectoryReplay.mockClear()
    fireEvent.click(screen.getByRole('button', { name: '播放历史回放' }))
    await waitFor(() => expect(platformApi.trajectoryReplay).toHaveBeenCalledWith(
      'INT-I5',
      expect.objectContaining({ cursor_sec: 4 }),
    ), { timeout: 2500 })
    await waitFor(() => expect(new URLSearchParams(window.location.search).get('cursor_ms')).toBe('4000'))

    expect(screen.getByText('1 条轨迹 · 1 个行为')).toBeInTheDocument()
    expect(screen.queryByText('当前 T+时刻无可回放轨迹')).not.toBeInTheDocument()

    resolveSecondSlice(secondSlice)
    await waitFor(() => expect(screen.getByText('1 条轨迹 · 1 个行为')).toBeInTheDocument())
  })

  it('keeps the fixed demo context independent from URL prototype labels', async () => {
    open('/?scope=priority&window=1h')
    expect(await screen.findByRole('button', { name: /服务器态势 1 路口/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /典型时段/ })).toBeDisabled()
    expect(screen.queryByText('priority')).not.toBeInTheDocument()
  })

  it('restores intersection and drone selections from deep links', async () => {
    open('/gis?intersection_id=INT-I5&period=24h')
    await waitFor(() => expect(screen.getByLabelText('路口')).toHaveValue('INT-I5'))
    expect(screen.getByLabelText('时间窗口')).toHaveValue('24h')
    expect(screen.getByText('坐标尚未冻结')).toBeInTheDocument()
    expect(platformApi.replayMissions).toHaveBeenCalledWith('INT-I5')
  })

  it('restores the fleet tab and selected drone from a deep link', async () => {
    open('/drones?tab=fleet&drone_id=UAV-M300-03')
    expect(await screen.findByRole('dialog', { name: 'M300 test' })).toBeInTheDocument()
  })

  it('renders the real replay camera stream and stops it from the route card', async () => {
    open('/drones?tab=fleet')
    const stream = await screen.findByRole('img', { name: '小清河北路 × 水屯路 实时检测画面' })
    expect(stream).toHaveAttribute('src', 'http://127.0.0.1:8127/video')
    const feed = stream.closest('.replay-camera-feed')
    const sourcePicker = screen.getByRole('combobox', { name: '小清河北路 × 水屯路回放源' })
    const stopButton = screen.getByRole('button', { name: '停止' })
    expect(screen.getByText(/悬停兼容分析/)).toBeInTheDocument()
    expect(sourcePicker).toBeDisabled()
    expect(sourcePicker.closest('.replay-camera-feed')).toBe(feed)
    expect(stopButton.closest('.replay-camera-feed')).toBe(feed)
    expect(stopButton.closest('.replay-camera-overlay')).toBe(sourcePicker.closest('.replay-camera-overlay'))
    expect(stream.closest('.replay-camera-card').querySelector(':scope > footer')).toBeNull()
    fireEvent.click(stopButton)
    await waitFor(() => expect(platformApi.stopMission).toHaveBeenCalledWith('MSN-0713-1050', 'Console2 路口摄像头人工停止'))
  })

  it('starts a selected replay source as a one-hour manual Mission', async () => {
    platformApi.missions.mockResolvedValueOnce([])
    open('/drones?tab=fleet')
    const selector = await screen.findByRole('combobox', { name: '小清河北路 × 水屯路回放源' })
    const strideInput = screen.getByRole('spinbutton', { name: '小清河北路 × 水屯路抽帧步长' })
    expect(strideInput).toHaveValue(3)
    fireEvent.change(selector, { target: { value: 'SRC-LOCAL-XQH-PM' } })
    fireEvent.change(strideInput, { target: { value: '6' } })
    fireEvent.click(screen.getByRole('button', { name: '启动检测' }))
    await waitFor(() => expect(platformApi.createMission).toHaveBeenCalledWith(expect.objectContaining({
      drone_id: 'UAV-M300-03',
      source_profile_id: 'SRC-LOCAL-XQH-PM',
      inter_id: 'INT_camera_1',
      road_data_version: 'ROAD-LOCAL-INTER-XQH',
      frame_stride: 6,
    })))
  })

  it('starts detection without a RoadContext binding and keeps road analytics degraded', async () => {
    platformApi.createMission.mockClear()
    platformApi.drones.mockResolvedValueOnce([
      { id: 'UAV-M300-03', name: 'M300 test', enabled: true, status: 'offline', telemetry_status: 'stale', battery_pct: null, revision: 1, default_inter_id: 'INT_MP4728_JINGSHI_CORRIDOR', intersection_name: '回放无人机 · 经十路巡航', default_video_source_id: 'VID-1' },
    ])
    platformApi.missions.mockResolvedValueOnce([])

    open('/drones?tab=fleet')

    const startButton = await screen.findByRole('button', { name: '启动检测' })
    expect(screen.getByText('道路未标定 · 仅检测/跟踪/遥测')).toBeInTheDocument()
    expect(startButton).toBeEnabled()

    fireEvent.click(startButton)
    await waitFor(() => expect(platformApi.createMission).toHaveBeenCalledWith(expect.objectContaining({
      drone_id: 'UAV-M300-03',
      source_profile_id: 'SRC-LOCAL-XQH',
      inter_id: 'INT_MP4728_JINGSHI_CORRIDOR',
    })))
    expect(platformApi.createMission.mock.calls[0][0]).not.toHaveProperty('road_data_version')
  })

  it('shows the starting state while Mission polling waits for MJPEG readiness', async () => {
    platformApi.missions.mockResolvedValueOnce([
      { id: 'MSN-STARTING', drone_id: 'UAV-M300-03', status: 'starting', pipeline: { observed_status: 'starting', camera_id: 19 } },
    ])
    open('/drones?tab=fleet')

    expect(await screen.findByText('Pipeline 启动中')).toBeInTheDocument()
    expect(screen.getByText('正在等待首个 MJPEG 检测帧')).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: '小清河北路 × 水屯路 实时检测画面' })).not.toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: '小清河北路 × 水屯路回放源' })).toBeDisabled()
  })

  it('shows the backend Mission conflict instead of falling back to demo state', async () => {
    platformApi.missions.mockResolvedValueOnce([])
    platformApi.createMission.mockRejectedValueOnce({
      response: { data: { detail: { code: 'drone_mission_active', message: '该无人机已有运行中的 Mission' } } },
    })
    open('/drones?tab=fleet')

    fireEvent.click(await screen.findByRole('button', { name: '启动检测' }))

    expect(await screen.findByText(/该无人机已有运行中的 Mission/)).toBeInTheDocument()
    expect(screen.queryByText(/Mock 回退/)).not.toBeInTheDocument()
  })

  it('supports event deep links and persistent technical review', async () => {
    open('/events?event_id=UAV-EVT-20260713-001')
    expect(await screen.findByRole('dialog', { name: '机非冲突风险升高' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '技术确认' }))
    expect(await screen.findByText('AI 结果已技术确认')).toBeInTheDocument()
    expect(platformApi.reviewEvent).toHaveBeenCalledWith('UAV-EVT-20260713-001', expect.objectContaining({ review_status: 'confirmed', expected_revision: 1 }))
  })

  it('restores a saved demo snapshot for post-event traffic analysis', async () => {
    const snapshot = buildDemoAnalysisSnapshot({
      intersectionId: 'INT-I5',
      intersectionName: '小清河北路 × 水屯路',
      sourceProfileId: 'SRC-LOCAL-XQH',
      missionMode: 'review',
      stats: { cars: 68, avg_speed_kmh: 18.6, lane_stats: [{ lane: '南进口直行', queue_length_m: 186, saturation: 1.04 }] },
      trend: [{ time: '10:55', congestion_index: 7.4, cars: 68, direction_flow: { straight: 46 } }],
      events: [{ id: 'E-DEMO-1', type: 'conflict', level: 'critical', title: '机非冲突风险升高', detail: '机动车与非机动车预测交汇', metric: 'TTC 1.2s' }],
      comparison: [{ label: '路口饱和度', before: '0.98', after: '0.76', delta: '-22%' }],
      capturedAt: '2026-08-04T02:55:28.000Z',
      savedAt: '2026-08-04T03:00:00.000Z',
    })
    upsertDemoSnapshot(snapshot)

    open(`/events?snapshot_id=${snapshot.id}`)

    expect(await screen.findByRole('dialog', { name: '事件与交通流事后分析' })).toBeInTheDocument()
    expect(screen.getByText('治理后复盘 · DEMO-SNAPSHOT-INT-I5-review')).toBeInTheDocument()
    expect(screen.getByText('南进口直行')).toBeInTheDocument()
    expect(screen.getByText('机动车与非机动车预测交汇')).toBeInTheDocument()
    expect(screen.getByText('治理前后同口径对比')).toBeInTheDocument()
    expect(screen.getByText('0.76')).toBeInTheDocument()
  })

  it('opens event evidence in a fullscreen preview and closes without dismissing the event', async () => {
    open('/events?event_id=UAV-EVT-20260713-001')

    expect(await screen.findByText('原始画面')).toBeInTheDocument()
    expect(screen.getByText('检测器输出的 TCC 画面帧')).toBeInTheDocument()
    expect(screen.queryByText('轨迹投放 BEV 视图')).not.toBeInTheDocument()
    const trigger = await screen.findByRole('button', { name: '全屏查看检测器输出的 TCC 画面帧' })
    fireEvent.click(trigger)
    expect(screen.getByRole('dialog', { name: '检测器输出的 TCC 画面帧全屏预览' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '检测器输出的 TCC 画面帧全屏预览' })).toHaveAttribute('src', 'blob:event-evidence')
    expect(document.body).toHaveStyle({ overflow: 'hidden' })

    fireEvent.click(screen.getByRole('button', { name: '关闭证据图片全屏预览' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '检测器输出的 TCC 画面帧全屏预览' })).not.toBeInTheDocument())
    expect(screen.getByRole('dialog', { name: '机非冲突风险升高' })).toBeInTheDocument()
    expect(trigger).toHaveFocus()

    fireEvent.click(trigger)
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '检测器输出的 TCC 画面帧全屏预览' })).not.toBeInTheDocument())
    expect(screen.getByRole('dialog', { name: '机非冲突风险升高' })).toBeInTheDocument()
  })

  it('links event filters across persisted event type, intersection, and search', async () => {
    open('/events')
    expect(await screen.findByText('UAV-EVT-20260713-004')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('事件路口'), { target: { value: 'INT-I5' } })
    expect(screen.getByText('UAV-EVT-20260713-001')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('事件搜索'), { target: { value: '不存在的事件' } })
    expect(screen.getByText('暂无符合条件的数据')).toBeInTheDocument()
  })

  it('normalizes an already-prefixed survey version in the event metric', async () => {
    open('/events')
    expect(await screen.findByText('1 项量算 · v7')).toBeInTheDocument()
    expect(screen.queryByText('1 项量算 · vv7')).not.toBeInTheDocument()
  })

  it('surfaces the backend overlap decision and keeps the plan as a draft', async () => {
    open('/drones?tab=plans')
    fireEvent.click(await screen.findByText('夜间货车限行验证'))
    fireEvent.click(screen.getByRole('button', { name: '校验并启用' }))
    expect(await screen.findByText(/发现同无人机时间冲突，计划保持草稿/)).toBeInTheDocument()
    expect(platformApi.flightPlanAction).toHaveBeenCalledWith('FP-20260713-03', 'enable', 1)
  })

  it('persists a Mission stop through the real S9 API interface', async () => {
    open('/drones?tab=missions')
    fireEvent.click(await screen.findByText('MSN-0713-1050'))
    fireEvent.click(screen.getByRole('button', { name: '停止 Mission' }))
    expect(await screen.findByText('stop 操作已持久化')).toBeInTheDocument()
    expect(platformApi.stopMission).toHaveBeenCalledWith('MSN-0713-1050', 'Console2 人工停止')
  })

  it('keeps the survey workflow deep-linkable', async () => {
    open('/survey/SVY-20260713-006/capture?task_id=SVY-20260713-006')
    expect(await screen.findByRole('heading', { name: '采集与质量预检' })).toBeInTheDocument()
    expect(screen.getByText('点线面量算')).toBeInTheDocument()
  })

  it.each([
    ['/survey/SVY-MISSING/precheck', '任务核验'],
    ['/survey/SVY-MISSING/capture', '采集与质量预检'],
    ['/survey/SVY-MISSING/measure', '点线面量算'],
    ['/survey/SVY-MISSING/review', '技术复核'],
    ['/survey/SVY-MISSING/report', '测绘报告与交付'],
  ])('keeps the survey deep link %s usable when the task cannot be loaded', async (path, title) => {
    platformApi.surveyTask.mockRejectedValueOnce(new Error('task not found'))

    open(path)

    expect(await screen.findByRole('heading', { name: title })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('task not found')
    expect(screen.getByRole('button', { name: '返回任务列表' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    await waitFor(() => expect(platformApi.surveyTask).toHaveBeenLastCalledWith('SVY-MISSING'))
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  })

  it('requires all six technical review checks and submits their exact audit keys', async () => {
    platformApi.surveyTask.mockResolvedValueOnce({
      id: 'SVY-REVIEW', title: '待复核测绘', location: '测试路口', owner: '事故处理一组',
      status: 'pending_review', quality: 'unverified', delivery: 'not_generated',
      version: 'v4', revision: 4, selected_batch_id: 'BATCH-01',
    })
    open('/survey/SVY-REVIEW/review')

    const approve = await screen.findByRole('button', { name: '技术复核通过' })
    const checks = screen.getAllByRole('checkbox')
    expect(checks).toHaveLength(6)
    checks.forEach((checkbox) => expect(checkbox).not.toBeChecked())
    expect(approve).toBeDisabled()

    checks.forEach((checkbox) => fireEvent.click(checkbox))
    expect(approve).toBeEnabled()
    fireEvent.click(approve)

    await waitFor(() => expect(platformApi.surveyAction).toHaveBeenCalledWith(
      'SVY-REVIEW',
      {
        action: 'approve_review',
        expected_revision: 4,
        checklist: {
          task_and_location: true,
          source_materials: true,
          coordinate_chain: true,
          measurements: true,
          edit_history: true,
          quality_status: true,
        },
      },
      expect.any(String),
    ))
  })

  it('refreshes the survey revision after importing capture material', async () => {
    open('/survey/SVY-20260713-006/capture')
    expect(await screen.findByRole('heading', { name: '采集与质量预检' })).toBeInTheDocument()
    const taskReadsBeforeImport = platformApi.surveyTask.mock.calls.length
    fireEvent.click(screen.getByRole('button', { name: '引用目录素材' }))
    await waitFor(() => expect(platformApi.importSurveyBatch).toHaveBeenCalledWith(
      'SVY-20260713-006',
      { source_profile_id: 'SRC-LOCAL-XQH' },
      expect.any(String),
    ))
    await waitFor(() => expect(platformApi.surveyTask.mock.calls.length).toBeGreaterThan(taskReadsBeforeImport))
  })

  it('loads persisted measurements and submits the real review transition', async () => {
    open('/survey/SVY-20260713-006/measure?task_id=SVY-20260713-006')
    expect(await screen.findByText('12.48m')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '提交技术复核' }))
    expect(await screen.findByRole('heading', { name: '技术复核' })).toBeInTheDocument()
  })

  it('renders a generated survey report without requiring a page reload', async () => {
    open('/survey/SVY-20260713-006/report')
    expect(await screen.findByText('测绘标注图')).toBeInTheDocument()
    expect(await screen.findByText('Frame #18236 · 1 项标注')).toBeInTheDocument()
    const generate = await screen.findByRole('button', { name: '生成成果包' })
    fireEvent.click(generate)
    expect(await screen.findByRole('button', { name: '打开真实 PDF' })).toBeInTheDocument()
    expect(screen.getByText(/aaaaaaaaaaaaaaaa/)).toBeInTheDocument()
  })

  it('persists enforcement clue technical confirmation through the I4 API', async () => {
    open('/enforcement?event_id=CLUE-I4-01')
    fireEvent.click(await screen.findByRole('button', { name: '确认 AI 线索' }))
    await waitFor(() => expect(platformApi.reviewEnforcementClue).toHaveBeenCalledWith('CLUE-I4-01', expect.objectContaining({ review_status: 'reviewed_confirmed', expected_revision: 1 })))
    expect(screen.queryByText('工程契约样本')).not.toBeInTheDocument()
  })

  it('saves a zone candidate with PostgreSQL revision state', async () => {
    open('/enforcement/zones')
    fireEvent.click(await screen.findByRole('button', { name: '编辑候选' }))
    fireEvent.click(screen.getByRole('button', { name: '保存候选' }))
    await waitFor(() => expect(platformApi.updateEnforcementZone).toHaveBeenCalledWith('ZONE-I4-01', expect.objectContaining({ revision: 1, coordinate_system: 'GCJ02' })))
  })

  it('keeps demo governance disabled unless it is explicitly enabled', async () => {
    open('/admin/integration')
    expect(await screen.findByRole('heading', { name: '集成与交付未启用' })).toBeInTheDocument()
    expect(screen.queryByText('DLQ-20260713-004')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '按原幂等键重放' })).not.toBeInTheDocument()
  })

  it('exposes the consolidated governance workspaces', async () => {
    open('/admin/system?tab=identity')
    expect(await screen.findByRole('heading', { name: '系统与身份' })).toBeInTheDocument()
    expect(screen.getByText('身份同步结果')).toBeInTheDocument()
  })

  it('drops legacy routes and returns authenticated users to the workspace', () => {
    open('/admin/rules')
    expect(screen.getByRole('heading', { name: '无人机交通态势工作台' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/')
  })

  it('redirects unauthenticated business routes to login with an internal return path', () => {
    Object.assign(authState, {
      user: null,
      status: 'anonymous',
      isAuthenticated: false,
      platformRole: null,
      consoleRole: 'analyst',
    })
    open('/monitoring?intersection_id=INT_camera_1&view=bev')
    expect(screen.getByRole('heading', { name: '登录系统' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/login')
    expect(new URLSearchParams(window.location.search).get('redirect')).toBe('/monitoring?intersection_id=INT_camera_1&view=bev')
  })

  it('does not invent fixed demo points when the selected server slot has no mappable intersections', async () => {
    platformApi.dashboardSituation.mockResolvedValueOnce({
      schema_version: 'uav.dashboard-situation/v1',
      source: { road_version: '20260501' },
      time_profile: { kind: 'typical_5min', timezone: 'Asia/Shanghai', available_days: [1, 2, 5] },
      cache: { status: 'miss', stale: false },
      summary: { intersections_total: 0, good: 0, near_saturated: 0, oversaturated: 0, segments_total: 0 },
      intersections: [],
      segments: [],
    })
    open('/')
    expect(await screen.findByText('当前典型时槽暂无态势数据。')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /SRC-DEMO-XQH/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '再次调度无人机复盘' })).toBeDisabled()
  })

  it('does not invent global exceptions or a fixed freshness timestamp', () => {
    open('/monitoring')
    expect(screen.queryByRole('button', { name: '异常状态' })).not.toBeInTheDocument()
    expect(screen.getByText('未提供实时水位')).toBeInTheDocument()
    expect(screen.queryByText(/候选路网同步中/)).not.toBeInTheDocument()
  })

  it('applies role-aware navigation', () => {
    open('/')
    fireEvent.click(screen.getByRole('button', { name: '当前用户' }))
    fireEvent.click(screen.getByRole('button', { name: /交通指挥员/ }))
    expect(screen.queryByRole('button', { name: '事故测绘' })).not.toBeInTheDocument()
    expect(screen.getByText('已切换为交通指挥员预览')).toBeInTheDocument()
  })

  it('uses the backend role rather than role preview for governance authorization', () => {
    Object.assign(authState, {
      user: { username: 'operator', role: 'operator' },
      platformRole: 'operator',
      consoleRole: 'commander',
    })
    open('/admin/system')
    expect(screen.getByRole('heading', { name: '当前账号无权访问平台治理' })).toBeInTheDocument()
    expect(screen.getByText('平台治理仅向系统管理员开放，前端角色预览不会改变真实权限。')).toBeInTheDocument()
  })
})
