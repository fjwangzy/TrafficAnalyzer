import { describe, expect, it } from 'vitest'
import { demoMonitoring, demoSituation } from '../config/demoData'
import {
  buildDashboardIntersectionPoints,
  buildDashboardSourcePoints,
  buildDigitalTwinPreviewStats,
  buildLiveDronePoints,
  dashboardStatsMessageMatchesDrone,
  defaultTypicalSlot,
  normalizeDashboardRealtimeStats,
  segmentStatusFromDelayIndex,
  situationStatusFromSaturation,
} from './DashboardPage'

describe('dashboard UAV video source map', () => {
  it('aggregates video sources per mapped intersection and prioritizes the running source', () => {
    const points = buildDashboardSourcePoints({
      sources: [
        { profile_id: 'SRC-RUN', display_name: '运行源', drone_id: 'UAV-1', enabled: true, validation_status: 'valid' },
        { profile_id: 'SRC-DEG', display_name: '降级源', drone_id: 'UAV-1', enabled: true, validation_status: 'degraded' },
      ],
      drones: [{ id: 'UAV-1', name: '一号无人机', default_inter_id: 'INT-1' }],
      intersections: [{ id: 'INT-1', name: '一号路口', center_gcj02: { latitude: 36.7, longitude: 117 }, map_coordinate_status: 'test', has_server_situation: true }],
      pipelines: [{ source_profile_id: 'SRC-RUN', intersection_id: 'INT-1', status: 'running' }],
    })

    expect(points).toHaveLength(1)
    expect(points[0]).toMatchObject({
      id: 'INT-1',
      source_profile_id: 'SRC-RUN',
      source_status: 'running',
      intersection_id: 'INT-1',
      source_count: 2,
    })
    expect(points[0].sources.map((item) => item.source_profile_id)).toEqual(['SRC-RUN', 'SRC-DEG'])
  })

  it('uses valid then degraded source priority and excludes disabled or unmapped sources', () => {
    const sources = [
      { profile_id: 'SRC-RUN', drone_id: 'UAV-1', enabled: true, validation_status: 'valid' },
      { profile_id: 'SRC-READY', drone_id: 'UAV-1', enabled: true, validation_status: 'valid' },
      { profile_id: 'SRC-DEG', drone_id: 'UAV-1', enabled: true, validation_status: 'degraded' },
      { profile_id: 'SRC-BAD', drone_id: 'UAV-1', enabled: true, validation_status: 'invalid' },
      { profile_id: 'SRC-OFF', drone_id: 'UAV-1', enabled: false, validation_status: 'valid' },
      { profile_id: 'SRC-OTHER', drone_id: 'UAV-2', enabled: true, validation_status: 'valid' },
    ]
    const points = buildDashboardSourcePoints({
      sources,
      drones: [{ id: 'UAV-1', default_inter_id: 'INT-1' }],
      intersections: [
        { id: 'INT-1', center_gcj02: { latitude: 36.7, longitude: 117 }, has_server_situation: true },
        { id: 'INT-LOCAL', center_gcj02: { latitude: 36.8, longitude: 117.1 }, has_server_situation: false },
      ],
      pipelines: [{ source_profile_id: 'SRC-RUN', intersection_id: 'INT-1', status: 'running' }],
    })

    expect(points).toHaveLength(1)
    expect(points[0].source_profile_id).toBe('SRC-RUN')
    expect(points[0].sources.map((item) => item.source_profile_id)).toEqual([
      'SRC-RUN',
      'SRC-READY',
      'SRC-DEG',
    ])
  })

  it('places a UAV source on a project intersection even without server situation metrics', () => {
    const points = buildDashboardSourcePoints({
      sources: [{ profile_id: 'SRC-CORRIDOR', drone_id: 'UAV-CORRIDOR', enabled: true, validation_status: 'valid' }],
      drones: [{ id: 'UAV-CORRIDOR', default_inter_id: 'INT-CORRIDOR' }],
      intersections: [{ id: 'INT-CORRIDOR', lon: 117, lat: 36.7, has_server_situation: false }],
      pipelines: [],
    })

    expect(points).toHaveLength(1)
    expect(points[0]).toMatchObject({
      id: 'INT-CORRIDOR',
      intersection_id: 'INT-CORRIDOR',
      source_profile_id: 'SRC-CORRIDOR',
      source_count: 1,
      lon: 117,
      lat: 36.7,
    })
  })

  it('still refuses to invent a UAV marker when the bound intersection has no coordinates', () => {
    const points = buildDashboardSourcePoints({
      sources: [{ profile_id: 'SRC-NO-GEO', drone_id: 'UAV-NO-GEO', enabled: true, validation_status: 'valid' }],
      drones: [{ id: 'UAV-NO-GEO', default_inter_id: 'INT-NO-GEO' }],
      intersections: [{ id: 'INT-NO-GEO', has_server_situation: false }],
      pipelines: [],
    })

    expect(points).toEqual([])
  })

  it('uses true replay trajectory points for a road-inspection marker and its trail', () => {
    const points = buildLiveDronePoints({
      dashboardDrones: [{ id: 'UAV-REPLAY', status: 'online' }],
      drones: [{ id: 'UAV-REPLAY', name: '回放无人机 · 经十路巡航', default_inter_id: 'INT-JINGSHI-CORRIDOR' }],
      sources: [{ profile_id: 'SRC-REPLAY', drone_id: 'UAV-REPLAY', mode: 'local', video: { source_type: 'mp4' } }],
      intersections: [{ id: 'INT-JINGSHI-CORRIDOR', name: '经十路巡检走廊', lon: 117, lat: 36.65 }],
      pipelines: [{ drone_id: 'UAV-REPLAY', source_profile_id: 'SRC-REPLAY', intersection_id: 'INT-JINGSHI-CORRIDOR', status: 'running', video_stream_url: 'http://127.0.0.1:8103/video' }],
      trajectoriesByDrone: {
        'UAV-REPLAY': [
          { position_gcj02: { longitude: 117.01, latitude: 36.651 }, height: 171.4, horizontal_speed: 3.1 },
          { position_gcj02: { longitude: 117.011, latitude: 36.652 }, height: 171.4, horizontal_speed: 3.1 },
        ],
      },
    })

    expect(points).toHaveLength(1)
    expect(points[0]).toMatchObject({
      lon: 117.011,
      lat: 36.652,
      position_basis: 'replay_gcj02_trajectory',
      status_label: '回放巡航',
      scene_label: '道路巡检 · 可控回放',
      altitude_m: 171.4,
      speed_mps: 3.1,
    })
    expect(points[0].trail_gcj02).toEqual([[117.01, 36.651], [117.011, 36.652]])
  })

  it('keeps an offline UAV selectable while preserving truthful empty runtime fields', () => {
    const points = buildLiveDronePoints({
      dashboardDrones: [{ id: 'UAV-OFFLINE', status: 'offline' }],
      drones: [{ id: 'UAV-OFFLINE', name: '离线无人机', default_inter_id: 'INT-1' }],
      sources: [{ profile_id: 'SRC-1', drone_id: 'UAV-OFFLINE', enabled: true }],
      intersections: [{ id: 'INT-1', name: '测试路口', lon: 117, lat: 36.7 }],
      pipelines: [],
      trajectoriesByDrone: {},
    })

    expect(points).toHaveLength(1)
    expect(points[0]).toMatchObject({
      id: 'UAV-OFFLINE',
      is_online: false,
      is_monitoring: false,
      can_open_monitoring: false,
      video_stream_url: null,
      pipeline_id: null,
      telemetry_fresh: false,
    })
  })

  it('normalizes current Stats without inventing unavailable values', () => {
    expect(normalizeDashboardRealtimeStats({
      total: 17,
      lane_stats: [{ queue_length: 23, avg_speed: 18 }, { queue_length: 31, avg_speed: 22 }],
      tcc_events: [{ id: 'TCC-1' }, { id: 'TCC-2' }],
    })).toEqual({ vehicles: 17, longestQueueM: 31, avgSpeedKmh: 20, tccEvents: 2 })
    expect(normalizeDashboardRealtimeStats({})).toEqual({ vehicles: null, longestQueueM: null, avgSpeedKmh: null, tccEvents: null })
  })

  it('builds deterministic dev-preview traffic with stable ids and moving pixel positions', () => {
    const first = buildDigitalTwinPreviewStats(0)
    const next = buildDigitalTwinPreviewStats(1)
    expect(first.active_trajectories).toHaveLength(120)
    expect(first.active_trajectories[0].track_id).toBe(next.active_trajectories[0].track_id)
    expect(first.active_trajectories[0].trajectory_px.at(-1)).not.toEqual(next.active_trajectories[0].trajectory_px.at(-1))
    expect(first).toMatchObject({ pipeline_id: 'frontend-preview', source_profile_id: 'FRONTEND-MOCK-TRAJECTORY', cars: 120 })
  })

  it('accepts realtime Stats only when Pipeline, SourceProfile, and intersection all match', () => {
    const drone = { pipeline_id: 'PIPE-1', source_profile_id: 'SRC-1', intersection_id: 'INT-1' }
    const exact = { type: 'uav_stats', data: { pipeline_id: 'PIPE-1', source_profile_id: 'SRC-1', intersection_id: 'INT-1' } }

    expect(dashboardStatsMessageMatchesDrone(exact, drone)).toBe(true)
    expect(dashboardStatsMessageMatchesDrone({ ...exact, data: { ...exact.data, pipeline_id: 'PIPE-2' } }, drone)).toBe(false)
    expect(dashboardStatsMessageMatchesDrone({ ...exact, data: { ...exact.data, source_profile_id: 'SRC-2' } }, drone)).toBe(false)
    expect(dashboardStatsMessageMatchesDrone({ ...exact, data: { ...exact.data, intersection_id: 'INT-2' } }, drone)).toBe(false)
    expect(dashboardStatsMessageMatchesDrone({ ...exact, type: 'uav_telemetry' }, drone)).toBe(false)
  })

  it('merges server situation with project intersections and keeps missing project data gray', () => {
    const points = buildDashboardIntersectionPoints({
      situationIntersections: [{ inter_id: 'INT-1', name: '服务器路口', lon: 117, lat: 36.7, saturation_max: 0.95 }],
      projectIntersections: [
        { id: 'INT-1', name: '项目路口一', center_gcj02: { longitude: 117, latitude: 36.7 } },
        { id: 'INT-2', name: '项目路口二', center_gcj02: { longitude: 117.1, latitude: 36.8 } },
      ],
    })

    expect(points).toHaveLength(2)
    expect(points.find((item) => item.id === 'INT-1')).toMatchObject({ is_project: true, status: 'near_saturated', has_server_situation: true })
    expect(points.find((item) => item.id === 'INT-2')).toMatchObject({ is_project: true, status: 'missing', saturation_max: null, has_server_situation: false })
  })

  it('applies the approved metric color boundaries', () => {
    expect([0.84, 0.85, 0.95, 0.951, null].map(situationStatusFromSaturation)).toEqual([
      'good', 'near_saturated', 'near_saturated', 'oversaturated', 'missing',
    ])
    expect([1.49, 1.5, 2, 2.01, null].map(segmentStatusFromDelayIndex)).toEqual([
      'smooth', 'slow', 'slow', 'congested', 'missing',
    ])
  })

  it('uses the stable server slot selected for visible demo grading', () => {
    expect(defaultTypicalSlot()).toEqual({
      dayOfWeek: 5,
      stepIndex: 95,
    })
  })

  it('keeps the normal-mode demo story as one fixed snapshot', () => {
    expect(demoSituation.story.map((step) => step.label)).toEqual([
      '发现态势',
      '调度无人机',
      '识别事件',
      '保存快照',
      '治理复盘',
    ])
    expect(demoSituation.events.map((event) => event.title)).toEqual([
      '机非冲突风险升高',
      '轻微事故等待测绘',
    ])
    expect(Math.max(...demoMonitoring.stats.lane_stats.map((lane) => lane.saturation))).toBeGreaterThan(0.95)
    expect(demoSituation.comparison).toContainEqual(expect.objectContaining({ label: '路口饱和度', before: '0.98', after: '0.76' }))
  })
})
