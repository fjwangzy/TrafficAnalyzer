import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const liveMocks = vi.hoisted(() => ({
  wsCallback: null,
  wsChannels: [],
  wsStatus: 'connected',
  api: {
    intersections: vi.fn(),
    intersection: vi.fn(),
    intersectionStats: vi.fn(),
    alerts: vi.fn(),
    conflicts: vi.fn(),
    trajectories: vi.fn(),
    acknowledgeAlert: vi.fn(),
    createMission: vi.fn(),
    pipelines: vi.fn(),
    sources: vi.fn(),
    drones: vi.fn(),
    telemetry: vi.fn(),
    systemHealth: vi.fn(),
    gpu: vi.fn(),
    kafkaTopics: vi.fn(),
    kafkaConsumers: vi.fn(),
    models: vi.fn(),
    users: vi.fn(),
    calibrationSummary: vi.fn(),
    calibrationRecords: vi.fn(),
    calibrationCoverage: vi.fn(),
    laneTasks: vi.fn(),
    laneTaskImage: vi.fn(),
    startLaneKeyframeExtraction: vi.fn(),
    createLaneTaskFromSurveyFrame: vi.fn(),
    surveyTasks: vi.fn(),
    surveyBatches: vi.fn(),
    surveyFrames: vi.fn(),
    bootstrapChannelizedMap: vi.fn(),
    channelizedMap: vi.fn(),
    createChannelizedMap: vi.fn(),
    fitChannelizedMapFromImage: vi.fn(),
    verifyVisualRegistration: vi.fn(),
    publishChannelizedMap: vi.fn(),
    intersectionProjectWorkspace: vi.fn(),
  },
}))

vi.mock('./auth/AuthContext', () => ({
  AuthProvider: ({ children }) => children,
  useAuth: () => ({
    user: { username: 'admin', role: 'admin' },
    status: 'authenticated',
    isAuthenticated: true,
    platformRole: 'admin',
    consoleRole: 'admin',
    logout: vi.fn(),
  }),
  isSafeRedirect: (value) => Boolean(value?.startsWith('/') && !value.startsWith('//') && !value.includes('://')),
}))

vi.mock('./hooks/useWebSocket', () => ({
  useWebSocket: ({ channels, onMessage }) => {
    liveMocks.wsCallback = onMessage
    liveMocks.wsChannels = channels
    return liveMocks.wsStatus
  },
}))

vi.mock('./lib/api', () => ({
  platformApi: liveMocks.api,
  apiErrorMessage: (error, fallback = '请求失败') => error?.message || fallback,
}))

vi.mock('./components/CityMap', () => ({
  CityMap: () => <div data-testid='city-map'>城市地图</div>,
}))

vi.mock('./components/MonitoringBevMap', () => ({
  MonitoringBevMap: ({ compact, emptyMessage, label, trajectories = [] }) => <div role='img' aria-label={label} data-compact={compact ? 'true' : 'false'} data-trajectory-count={trajectories.length} data-track-ids={trajectories.map((item) => item.track_id).join(',')}>高德 GCJ-02 轨迹地图{!trajectories.length && emptyMessage ? <span>{emptyMessage}</span> : null}</div>,
}))

import { RouterApp } from './RouterApp'

function open(path) {
  window.history.pushState({}, '', path)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } })
  return { ...render(<QueryClientProvider client={queryClient}><RouterApp /></QueryClientProvider>), queryClient }
}

function groupedLaneMap() {
  return {
    id: 'CMV-GROUPED', inter_id: 'INT-1', version_no: 1, status: 'draft', coordinate_system: 'GCJ02', coordinate_transform_version: 'v1', road_data_version: 'ROAD-1', anchor_gcj02: [117, 36.7], geometry_gcj02: {},
    lanes: [
      { local_lane_id: 'candidate:LANE-1', source_lane_id: 'LANE-1', link_id: 'LINK-1', geometry_source: 'link_offset_derived', geometry_enu_m: { type: 'Polygon', coordinates: [[[0, 0], [10, 0], [10, 30], [0, 30], [0, 0]]] } },
      { local_lane_id: 'candidate:LANE-2', source_lane_id: 'LANE-2', link_id: 'LINK-1', geometry_source: 'link_offset_derived', geometry_enu_m: { type: 'Polygon', coordinates: [[[12, 0], [22, 0], [22, 30], [12, 30], [12, 0]]] } },
      { local_lane_id: 'candidate:LANE-3', source_lane_id: 'LANE-3', link_id: 'LINK-2', geometry_source: 'link_offset_derived', geometry_enu_m: { type: 'Polygon', coordinates: [[[24, 0], [34, 0], [34, 30], [24, 30], [24, 0]]] } },
    ],
  }
}

function mockSuccessfulApis() {
  liveMocks.api.intersections.mockResolvedValue([{ id: 'INT-1', name: '小清河北路 × 水屯路' }])
  liveMocks.api.sources.mockResolvedValue([
    { profile_id: 'SRC-1', display_name: '小清河北路早高峰', drone_id: 'UAV-1', mode: 'local', enabled: true, validation_status: 'valid', video: { id: 'VID-1', source_type: 'mp4', location_hint: 'xqh-am.mp4' }, telemetry: { source_type: 'srt' } },
    { profile_id: 'SRC-2', display_name: '崇华路晚高峰', drone_id: 'UAV-2', mode: 'local', enabled: true, validation_status: 'valid', video: { id: 'VID-2', source_type: 'mp4', location_hint: 'ch-pm.mp4' }, telemetry: { source_type: 'srt' } },
  ])
  liveMocks.api.drones.mockResolvedValue([
    { id: 'UAV-1', name: '小清河无人机', default_inter_id: 'INT-1', default_video_source_id: 'VID-1', default_road_data_version: 'ROAD-1', intersection_name: '小清河北路 × 水屯路' },
    { id: 'UAV-2', name: '崇华路无人机', default_inter_id: 'INT-2', default_video_source_id: 'VID-2', default_road_data_version: 'ROAD-2', intersection_name: '新泺大街 × 崇华路' },
  ])
  liveMocks.api.intersection.mockResolvedValue({ id: 'INT-1', current_drone_id: 'UAV-1' })
  liveMocks.api.intersectionStats.mockResolvedValue([{ time: '2026-07-14T10:00:00Z', congestion_index: 4.8, cars: 20, direction_flow: { straight: { count: 14 }, left_turn: { count: 4 }, right_turn: { count: 2 }, u_turn: { count: 0 } } }])
  liveMocks.api.alerts.mockResolvedValue([{ id: 'A-1', intersection_id: 'INT-1', alert_type: 'conflict', severity: 'P1', title: '机非冲突风险升高', description: '预测轨迹交汇', ttc_sec: 1.2, pet_sec: 0.8 }])
  liveMocks.api.conflicts.mockResolvedValue([
    { id: 'DB-C-1', message_id: 'C-1', source_profile_id: 'SRC-1', pipeline_id: 'P-old', prediction_type: 'path_intersection', distance_m: 0.0, motor_id: 96, non_motor_id: 88, severity: 'critical', title: '历史路径交点事件', occurred_at: '2026-07-14T09:59:58Z', ttc_sec: 1.1, pet_sec: 0.3 },
    { id: 'C-CPA', source_profile_id: 'SRC-1', prediction_type: 'same_time_cpa', distance_m: 0.4, motor_id: 7, non_motor_id: 8, severity: 'warning', title: '实验 CPA 事件', occurred_at: '2026-07-14T09:59:57Z' },
  ])
  liveMocks.api.trajectories.mockResolvedValue([
    { id: 'TRK-HIST-1', track_id: 96, source_profile_id: 'SRC-1', pipeline_id: 'P-old', trajectory_gcj02: [[117, 36.7], [117.0001, 36.7001], [117.0002, 36.7002]], anchor_gcj02: [117, 36.7] },
    { id: 'TRK-HIST-2', track_id: 88, source_profile_id: 'SRC-1', pipeline_id: 'P-old', trajectory_gcj02: [[117.0001, 36.7], [117.0002, 36.7001], [117.0003, 36.7002]], anchor_gcj02: [117, 36.7] },
  ])
  liveMocks.api.acknowledgeAlert.mockResolvedValue({ id: 'A-1', status: 'acknowledged' })
  liveMocks.api.createMission.mockResolvedValue({ id: 'MSN-DEMO-1', status: 'running' })
  liveMocks.api.pipelines.mockResolvedValue([{ pipeline_id: 'P-1', intersection_id: 'INT-1', source_profile_id: 'SRC-1', drone_id: 'UAV-1', camera_id: 11, video_stream_url: 'http://127.0.0.1:8101/video', status: 'running' }])
  liveMocks.api.telemetry.mockResolvedValue({ drone_id: 'drone_11', height: 118.6, attitude_head: 36.2, attitude_pitch: -0.8, gimbal_roll: 0.4 })
  liveMocks.api.systemHealth.mockResolvedValue({ status: 'healthy', service: 'platform', kafka_connected: true, ws_connections: 2, pipelines_active: 1 })
  liveMocks.api.gpu.mockResolvedValue({ gpu_util_pct: 42, gpu_vram_used_mb: 2048 })
  liveMocks.api.kafkaTopics.mockResolvedValue({ topics: [{ name: 'uav_statistics_11', partitions: 1, tps: 3, lag: 0 }] })
  liveMocks.api.kafkaConsumers.mockResolvedValue({ group_id: 'traffic-platform', state: 'Stable', members: 1 })
  liveMocks.api.models.mockResolvedValue({ current: 'uav_best.pt', models: [{ name: 'uav_best.pt', type: 'custom', size_mb: 12.1 }] })
  liveMocks.api.users.mockResolvedValue([{ id: 1, username: 'admin', email: 'admin@example.com', role: 'admin', is_active: true, created_at: '2026-07-14T10:00:00Z' }])
  liveMocks.api.calibrationSummary.mockResolvedValue({ total: 1, ok: 1 })
  liveMocks.api.calibrationRecords.mockResolvedValue([{ key: 'CAL-1', intersection_id: 'INT-1', quality: { score: 0.95 }, reprojection_error: 1.2 }])
  liveMocks.api.calibrationCoverage.mockResolvedValue([{ key: 'INT-1-H112', altitude: 112, pitch: -89, quality: 'ok' }])
  const laneTask = { task_id: 'TASK-1', intersection_id: 'INT-1', source_frame_id: 'FRM-LANE-1', source_profile_id: 'SRC-1', homography_pixel_to_enu: [[0.1, 0, -10], [0, 0.1, -5], [0, 0, 1]], homography_coordinate_frame: 'map_enu', map_version_id: 'CMV-1', map_anchor_gcj02: [117, 36.7], image_width: 960, image_height: 540, lane_count: 0, roads: { north: [1, 2, 3] }, status: 'pending' }
  liveMocks.api.laneTasks.mockResolvedValue([laneTask])
  liveMocks.api.laneTaskImage.mockResolvedValue(new Blob(['jpeg'], { type: 'image/jpeg' }))
  liveMocks.api.createLaneTaskFromSurveyFrame.mockResolvedValue(laneTask)
  liveMocks.api.startLaneKeyframeExtraction.mockResolvedValue({
    task: { id: 'SVY-CAL-1', title: '渠化标注抽帧 · 小清河北路 × 水屯路', inter_id: 'INT-1', status: 'collecting', revision: 4 },
    batch: { id: 'BATCH-CAL-1', status: 'queued', source_profile_id: 'SRC-1' },
  })
  liveMocks.api.surveyTasks.mockResolvedValue([{ id: 'SVY-LANE-1', title: '路口正拍采集', inter_id: 'INT-1', selected_batch_id: 'BATCH-LANE-1', status: 'measuring' }])
  liveMocks.api.surveyBatches.mockResolvedValue([{ id: 'BATCH-LANE-1', status: 'selected', source_profile_id: 'SRC-1' }])
  liveMocks.api.surveyFrames.mockResolvedValue([{ id: 'FRM-LANE-1', frame_number: 120, timestamp_sec: 4, has_metric_transform: true, metric_transform: [[0.1, 0, -10], [0, 0.1, -5], [0, 0, 1]] }])
  const map = {
    id: 'CMV-1', inter_id: 'INT-1', version_no: 1, status: 'draft', coordinate_system: 'GCJ02', coordinate_transform_version: 'v1', road_data_version: 'ROAD-1', anchor_gcj02: [117, 36.7], geometry_gcj02: {},
    lanes: [{
      local_lane_id: 'candidate:LANE-1', source_lane_id: 'LANE-1', link_id: 'LINK-1', geometry_source: 'link_offset_derived',
      geometry_enu_m: { type: 'Polygon', coordinates: [[[0, 0], [10, 0], [10, 10], [0, 0]]] },
      geometry_gcj02: { type: 'Polygon', coordinates: [[[117, 36.7], [117.0001, 36.7], [117.0001, 36.7001], [117, 36.7]]] },
    }],
  }
  liveMocks.api.bootstrapChannelizedMap.mockResolvedValue({ source: 'local', map })
  liveMocks.api.channelizedMap.mockResolvedValue({ ...map, status: 'lane_verified', quality: { reviewed: true } })
  liveMocks.api.createChannelizedMap.mockResolvedValue({ ...map, id: 'CMV-2', version_no: 2, status: 'draft' })
  liveMocks.api.fitChannelizedMapFromImage.mockResolvedValue({ ...map, status: 'candidate', registration: { id: 'VRG-1', status: 'registered' } })
  liveMocks.api.verifyVisualRegistration.mockResolvedValue({ id: 'VRG-1', status: 'verified' })
  liveMocks.api.publishChannelizedMap.mockResolvedValue({ ...map, status: 'lane_verified' })
  liveMocks.api.intersectionProjectWorkspace.mockResolvedValue({
    project: { project_id: 'IPR-1', inter_id: 'INT-1', name: '小清河北路 × 水屯路', stage: 'published', revision: 2, center_gcj02: [117, 36.7], created_by: 'admin' },
    bindings: [{ source_profile_id: 'SRC-1' }],
    channelized_maps: [{ ...map, status: 'lane_verified', quality: { reviewed: true } }],
    readiness: { formal_intersection: true, road_context_verified: true, source_bound: true, road_data_version: 'ROAD-1', next_action: 'operate_runtime' },
  })
}

describe('Console2 live module migration', () => {
  beforeEach(() => {
    Object.values(liveMocks.api).forEach((mock) => mock.mockReset())
    liveMocks.wsCallback = null
    liveMocks.wsChannels = []
    liveMocks.wsStatus = 'connected'
    mockSuccessfulApis()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:lane-task') })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
  })

  it('drives monitoring from REST and realtime data and preserves detector/BEV switching', async () => {
    open('/monitoring')

    await waitFor(
      () => expect(window.location.search).toContain('intersection_id=INT-1'),
      { timeout: 10_000 },
    )
    expect(await screen.findByAltText('检测器输出视频流', {}, { timeout: 10_000 })).toHaveAttribute('src', expect.stringMatching(/^http:\/\/127\.0\.0\.1:8101\/video\?retry=/))
    expect(liveMocks.wsChannels).toContain('uav_telemetry:UAV-1')
    expect(liveMocks.wsChannels).toContain('uav_telemetry:drone_11')
    expect((await screen.findAllByText('20')).length).toBeGreaterThan(0)
    expect(screen.getByLabelText('飞行姿态数据')).toHaveTextContent('118.6')

    act(() => liveMocks.wsCallback({
      type: 'uav_stats',
      data: {
        pipeline_id: 'P-1',
        congestion_index: 6.3,
        cars: 842,
        avg_speed_kmh: 27.4,
        fps: 29.7,
        inference_ms: 33,
        lane_stats: [{ queue_length_m: 186 }],
        active_trajectories: [{ track_id: 101 }, { track_id: 102 }],
      },
    }))
    act(() => liveMocks.wsCallback({ type: 'uav_telemetry', data: { drone_id: 'drone_11', height: 112.4, attitude_head: 37.8, attitude_pitch: -1.2, gimbal_roll: 0.6, gimbal_mode: '锁定' } }))

    expect(screen.getByLabelText('飞行姿态数据')).toHaveTextContent('112.4')
    expect(screen.getByLabelText('飞行姿态数据')).toHaveTextContent('37.8')
    expect(screen.getByText('842')).toBeInTheDocument()
    expect(screen.getByText('186')).toBeInTheDocument()
    const trajectoryCard = screen.getByText('实时轨迹数量').closest('.congestion-card')
    expect(trajectoryCard).toHaveTextContent('2')
    expect(screen.queryByText('拥堵指数')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /切为主视图/ }))
    expect(window.location.search).toContain('view=bev')
    expect(await screen.findByRole('img', { name: 'BEV 地图轨迹主视图' })).toBeInTheDocument()
    expect(screen.queryByAltText('BEV 鸟瞰轨迹投放图')).not.toBeInTheDocument()

    expect(screen.getByText('转向流量')).toBeInTheDocument()
    expect(screen.getByText('直行')).toBeInTheDocument()
    expect(liveMocks.api.alerts).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: /历史路径交点事件/ }))
    expect(screen.queryByText('AI 事件研判')).not.toBeInTheDocument()
  })

  it('shows cruise quality gates and keeps degraded trajectories candidate-only', async () => {
    open('/monitoring?intersection_id=INT-1&source_profile_id=SRC-1')
    expect(await screen.findByText('历史路径交点事件')).toBeInTheDocument()

    act(() => liveMocks.wsCallback({
      type: 'uav_stats',
      data: {
        pipeline_id: 'P-1',
        cars: null,
        active_trajectories: [],
        candidate_trajectories: [{
          track_id: 44,
          tracking_method: 'pose_aware_world_v1',
          tracking_quality: 'degraded',
          quality_reasons: ['telemetry_gap'],
          trajectory_gcj02: [[117, 36.7], [117.0001, 36.7001]],
        }],
        flight_phase: 'cruise_nadir',
        formal_analytics_eligible: false,
        geo_reference_quality: {
          status: 'degraded',
          telemetry: { status: 'degraded' },
          visual_warp: { status: 'verified' },
          map_coverage: { status: 'verified' },
          reasons: ['telemetry_gap'],
        },
        tracking_diagnostics: {
          tracking_method: 'pose_aware_world_v1',
          tracking_quality: 'degraded',
          termination_reason: 'mode_transition_quality_break',
        },
      },
    }))

    expect(screen.getByText('近正射巡航')).toBeInTheDocument()
    expect(screen.getByText('正式研判关闭')).toBeInTheDocument()
    expect(screen.getByText('仅候选，不进入统计/TCC')).toBeInTheDocument()
    expect(screen.getByText(/遥测短缺或超出同步窗口/)).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'BEV 地图轨迹投放图' })).toHaveAttribute('data-trajectory-count', '1')
  })

  it('keeps realtime map trajectories when a historical REST snapshot refreshes', async () => {
    const { queryClient } = open('/monitoring?intersection_id=INT-1&source_profile_id=SRC-1')
    expect(await screen.findByText('历史路径交点事件')).toBeInTheDocument()

    act(() => liveMocks.wsCallback({
      type: 'uav_stats',
      data: {
        pipeline_id: 'P-1',
        cars: 9,
        active_trajectories: [],
        candidate_trajectories: [{
          track_id: 51,
          tracking_quality: 'degraded',
          trajectory_gcj02: [[117, 36.7], [117.0001, 36.7001]],
        }],
      },
    }))
    expect(screen.getByRole('img', { name: 'BEV 地图轨迹投放图' })).toHaveAttribute('data-trajectory-count', '1')

    liveMocks.api.intersectionStats.mockResolvedValueOnce([{ time: '2026-07-14T10:05:00Z', cars: 30 }])
    await act(async () => queryClient.refetchQueries({ queryKey: ['monitoring-trend', 'INT-1', 'SRC-1'] }))

    expect(screen.getByRole('img', { name: 'BEV 地图轨迹投放图' })).toHaveAttribute('data-trajectory-count', '1')
    expect(screen.getByText('实时轨迹数量').closest('.congestion-card')).toHaveTextContent('0')
  })

  it('rejects stale realtime stats from an older pipeline on the same source', async () => {
    open('/monitoring?intersection_id=INT-1&source_profile_id=SRC-1')
    expect(await screen.findByText('历史路径交点事件')).toBeInTheDocument()

    act(() => liveMocks.wsCallback({
      type: 'uav_stats',
      data: {
        pipeline_id: 'P-1',
        active_trajectories: [],
        candidate_trajectories: [{
          track_id: 61,
          tracking_quality: 'degraded',
          trajectory_gcj02: [[117, 36.7], [117.0001, 36.7001]],
        }],
        geo_reference_quality: {
          status: 'degraded',
          map_coverage: { status: 'verified' },
          reasons: ['flight_phase_not_verified'],
        },
      },
    }))
    expect(screen.getByRole('img', { name: 'BEV 地图轨迹投放图' })).toHaveAttribute('data-trajectory-count', '1')

    act(() => liveMocks.wsCallback({
      type: 'uav_stats',
      data: {
        pipeline_id: 'P-OLD',
        active_trajectories: [],
        candidate_trajectories: [{ track_id: 99, trajectory_px: [[1, 2], [3, 4]] }],
        geo_reference_quality: {
          status: 'degraded',
          map_coverage: { status: 'unavailable' },
          reasons: ['lane_verified_map_required'],
        },
      },
    }))

    expect(screen.getByRole('img', { name: 'BEV 地图轨迹投放图' })).toHaveAttribute('data-trajectory-count', '1')
    expect(screen.queryByText(/缺少 lane_verified 运行时地图/)).not.toBeInTheDocument()
  })

  it('clears same-source realtime session state when the running pipeline changes', async () => {
    const { queryClient } = open('/monitoring?intersection_id=INT-1&source_profile_id=SRC-1')
    expect(await screen.findByText('历史路径交点事件')).toBeInTheDocument()
    act(() => liveMocks.wsCallback({
      type: 'uav_stats',
      data: {
        pipeline_id: 'P-1',
        active_trajectories: [],
        candidate_trajectories: [{
          track_id: 71,
          tracking_quality: 'degraded',
          trajectory_gcj02: [[117, 36.7], [117.0001, 36.7001]],
        }],
      },
    }))
    expect(screen.getByRole('img', { name: 'BEV 地图轨迹投放图' })).toHaveAttribute('data-trajectory-count', '1')

    liveMocks.api.pipelines.mockResolvedValueOnce([{ pipeline_id: 'P-2', intersection_id: 'INT-1', source_profile_id: 'SRC-1', drone_id: 'UAV-1', camera_id: 12, video_stream_url: 'http://127.0.0.1:8102/video', status: 'running' }])
    await act(async () => queryClient.refetchQueries({ queryKey: ['monitoring-pipelines'] }))

    await waitFor(() => expect(screen.getByRole('img', { name: 'BEV 地图轨迹投放图' })).toHaveAttribute('data-trajectory-count', '0'))
    expect(screen.getByRole('img', { name: 'BEV 地图轨迹投放图' })).toHaveTextContent('等待 GCJ-02 实时轨迹')
  })

  it('reports unprojected candidates instead of presenting an unexplained empty map', async () => {
    open('/monitoring?intersection_id=INT-1&source_profile_id=SRC-1')
    expect(await screen.findByText('历史路径交点事件')).toBeInTheDocument()

    act(() => liveMocks.wsCallback({
      type: 'uav_stats',
      data: {
        pipeline_id: 'P-1',
        active_trajectories: [],
        candidate_trajectories: [{
          track_id: 52,
          tracking_quality: 'degraded',
          trajectory_px: [[10, 20], [12, 24]],
        }],
      },
    }))

    const map = screen.getByRole('img', { name: 'BEV 地图轨迹投放图' })
    expect(map).toHaveAttribute('data-trajectory-count', '0')
    expect(map).toHaveTextContent('候选目标 1 · 地理投影不可用')
    expect(screen.getByText('实时轨迹数量').closest('.congestion-card')).toHaveTextContent('0')
  })

  it('rejects realtime alerts without current SourceProfile lineage', async () => {
    open('/monitoring?intersection_id=INT-1&source_profile_id=SRC-1')
    expect(await screen.findByText('历史路径交点事件')).toBeInTheDocument()

    act(() => liveMocks.wsCallback({
      type: 'uav_alert_new',
      data: { id: 'UNSCOPED-1', intersection_id: 'INT-1', title: '无来源固定告警', severity: 'P1' },
    }))
    expect(screen.queryByText('无来源固定告警')).not.toBeInTheDocument()

    act(() => liveMocks.wsCallback({
      type: 'uav_alert_new',
      data: { id: 'SCOPED-1', intersection_id: 'INT-1', source_profile_id: 'SRC-1', title: '当前源实时告警', severity: 'P1' },
    }))
    expect(screen.getByText('当前源实时告警')).toBeInTheDocument()
  })

  it('backfills source-scoped path conflicts and deduplicates their realtime replay', async () => {
    open('/monitoring?intersection_id=INT-1&source_profile_id=SRC-1')

    expect(await screen.findByText('历史路径交点事件')).toBeInTheDocument()
    expect(liveMocks.api.conflicts).toHaveBeenCalledWith('INT-1', {
      period: '24h',
      limit: 20,
      source_profile_id: 'SRC-1',
      prediction_type: 'path_intersection',
    })
    expect(screen.queryByText('实验 CPA 事件')).not.toBeInTheDocument()

    act(() => liveMocks.wsCallback({
      type: 'uav_conflict',
      occurredAt: '2026-07-14T09:59:58Z',
      data: { message_id: 'C-1', pipeline_id: 'P-1', source_profile_id: 'SRC-1', prediction_type: 'path_intersection', distance_m: 0.0, motor_id: 96, non_motor_id: 88, severity: 'critical', title: '历史路径交点事件', ttc_sec: 1.1, pet_sec: 0.3 },
    }))

    expect(screen.getAllByText('历史路径交点事件')).toHaveLength(1)
  })

  it('loads source-scoped historical trajectories for offline BEV replay', async () => {
    liveMocks.api.pipelines.mockResolvedValue([])
    open('/monitoring?intersection_id=INT-1&source_profile_id=SRC-1&view=bev')

    await waitFor(() => expect(screen.getByRole('img', { name: 'BEV 地图轨迹主视图' })).toHaveAttribute('data-trajectory-count', '2'))
    expect(liveMocks.api.trajectories).toHaveBeenCalledWith('INT-1', {
      period: '24h',
      limit: 500,
      source_profile_id: 'SRC-1',
      spatial_ready: true,
      min_gcj02_points: 2,
    })
    expect(screen.getByText('BEV 历史轨迹回放 · 2 TRACKS')).toBeInTheDocument()
    expect(screen.queryByText(/数据质量 ·/)).not.toBeInTheDocument()
  })

  it('shows explanatory TCC and WebSocket downgrade states', async () => {
    liveMocks.wsStatus = 'disconnected'
    liveMocks.api.intersectionStats.mockResolvedValue([{
      time: '2026-07-14T10:00:00Z',
      congestion_index: 4.8,
      cars: 20,
      tcc_diagnostics: { enabled: true, calibration_valid: true, eligible_motor_tracks: 3, eligible_non_motor_tracks: 2, prediction_candidates: 0, events_emitted: 0, status: 'no_prediction_candidates' },
    }])

    open('/monitoring?intersection_id=INT-1&source_profile_id=SRC-1')

    expect(await screen.findByText('TCC 已启用：无合格预测候选')).toBeInTheDocument()
    expect(screen.getByText('实时链路已断开，当前展示历史/REST 数据')).toBeInTheDocument()
  })

  it('aligns the monitoring selector with registered UAV video sources and their intersections', async () => {
    open('/monitoring?intersection_id=INT-1')

    const selector = await screen.findByRole('combobox', { name: '选择无人机视频源' })
    await waitFor(() => expect(window.location.search).toContain('source_profile_id=SRC-1'))
    expect(selector).toHaveDisplayValue('小清河北路早高峰 · 小清河无人机')
    expect(selector).toHaveAttribute('title', '小清河北路早高峰 · 小清河无人机')
    expect(selector.closest('.monitoring-source-picker')).not.toBeNull()
    expect(screen.queryByRole('option', { name: /Camera 1/ })).not.toBeInTheDocument()

    fireEvent.change(selector, { target: { value: 'SRC-2' } })
    await waitFor(() => {
      const params = new URLSearchParams(window.location.search)
      expect(params.get('source_profile_id')).toBe('SRC-2')
      expect(params.get('intersection_id')).toBe('INT-2')
    })
    expect(screen.getByText(/新泺大街 × 崇华路 · SRC-2 · 监测离线/)).toBeInTheDocument()
  })

  it('follows the running source when the monitoring URL points to a stopped source at the same intersection', async () => {
    liveMocks.api.sources.mockResolvedValue([
      { profile_id: 'SRC-STOPPED', display_name: '崇华路晚高峰', drone_id: 'UAV-1', enabled: true, video: { id: 'VID-1', source_type: 'mp4', location_hint: 'ch-pm.mp4' } },
      { profile_id: 'SRC-RUNNING', display_name: '崇华路早高峰', drone_id: 'UAV-1', enabled: true, video: { id: 'VID-3', source_type: 'mp4', location_hint: 'ch-am.mp4' } },
    ])
    liveMocks.api.pipelines.mockResolvedValue([
      { pipeline_id: 'P-RUNNING', intersection_id: 'INT-1', source_profile_id: 'SRC-RUNNING', drone_id: 'UAV-1', camera_id: 13, video_stream_url: 'http://127.0.0.1:8103/video', status: 'running' },
    ])

    open('/monitoring?intersection_id=INT-1&source_profile_id=SRC-STOPPED')

    await waitFor(
      () => expect(new URLSearchParams(window.location.search).get('source_profile_id')).toBe('SRC-RUNNING'),
      { timeout: 10_000 },
    )
    expect(screen.getByRole('combobox', { name: '选择无人机视频源' })).toHaveDisplayValue('崇华路早高峰 · 小清河无人机')
    expect(await screen.findByAltText('检测器输出视频流')).toHaveAttribute('src', expect.stringMatching(/^http:\/\/127\.0\.0\.1:8103\/video\?retry=/))
    expect(liveMocks.api.intersectionStats).toHaveBeenCalledWith('INT-1', '30m', '5m', 'SRC-RUNNING')
  })

  it('starts the selected source from the offline canvas and keeps target counts in the metric panel', async () => {
    liveMocks.api.pipelines.mockResolvedValue([])
    open('/monitoring?intersection_id=INT-1&source_profile_id=SRC-1')

    const startButton = await screen.findByRole('button', { name: '启动演示检测' })
    expect(screen.queryByText(/活动轨迹 ·/)).not.toBeInTheDocument()
    expect(screen.getByText('当前目标').closest('.metric-card')).not.toBeNull()

    fireEvent.click(startButton)
    await waitFor(() => expect(liveMocks.api.createMission).toHaveBeenCalledWith(expect.objectContaining({
      name: '快速演示 · 小清河北路 × 水屯路',
      drone_id: 'UAV-1',
      source_profile_id: 'SRC-1',
      inter_id: 'INT-1',
      scheduled_end_at: expect.any(String),
    })))
    expect(liveMocks.api.createMission.mock.calls[0][0]).not.toHaveProperty('road_data_version')
  })

  it('allows demo detection without a bound road context', async () => {
    liveMocks.api.pipelines.mockResolvedValue([])
    liveMocks.api.drones.mockResolvedValue([
      { id: 'UAV-1', name: '小清河无人机', default_inter_id: 'INT-1', default_video_source_id: 'VID-1', intersection_name: '小清河北路 × 水屯路' },
    ])
    open('/monitoring?intersection_id=INT-1&source_profile_id=SRC-1')

    const startButton = await screen.findByRole('button', { name: '启动演示检测' })
    expect(startButton).toBeEnabled()
    expect(startButton).toHaveAttribute('title', '启动当前视频源的一小时演示检测')

    fireEvent.click(startButton)
    await waitFor(() => expect(liveMocks.api.createMission).toHaveBeenCalledWith({
      name: '快速演示 · 小清河北路 × 水屯路',
      drone_id: 'UAV-1',
      source_profile_id: 'SRC-1',
      inter_id: 'INT-1',
      scheduled_end_at: expect.any(String),
    }))
  })

  it('shows a Mission business failure instead of silently treating it as started', async () => {
    liveMocks.api.pipelines.mockResolvedValue([])
    liveMocks.api.createMission.mockResolvedValueOnce({
      id: 'MSN-FAILED-1',
      status: 'failed',
      reason_code: 'pipeline_start_failed',
      error_message: '检测器进程启动失败',
    })
    open('/monitoring?intersection_id=INT-1&source_profile_id=SRC-1')

    fireEvent.click(await screen.findByRole('button', { name: '启动演示检测' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('检测器进程启动失败')
  })

  it('freezes visible REST, WebSocket, and clock updates while paused then restores them in order', async () => {
    const { queryClient } = open('/monitoring?intersection_id=INT-1')
    expect((await screen.findAllByText('20')).length).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('button', { name: '暂停实时数据' }))
    const frozenClock = document.querySelector('.timeline-controls span').textContent

    act(() => liveMocks.wsCallback({ type: 'uav_stats', data: { pipeline_id: 'P-1', cars: 842, congestion_index: 6.3 } }))
    liveMocks.api.intersectionStats.mockResolvedValueOnce([{ time: '2026-07-14T10:05:00Z', congestion_index: 5.1, cars: 30 }])
    await act(async () => queryClient.refetchQueries({ queryKey: ['monitoring-trend', 'INT-1'] }))
    await act(async () => new Promise((resolve) => window.setTimeout(resolve, 1_100)))

    expect(screen.queryByText('842')).not.toBeInTheDocument()
    expect(screen.queryByText('30')).not.toBeInTheDocument()
    expect((screen.getAllByText('20')).length).toBeGreaterThan(0)
    expect(document.querySelector('.timeline-controls span')).toHaveTextContent(frozenClock)

    fireEvent.click(screen.getByRole('button', { name: '恢复实时数据' }))
    expect(await screen.findByText('842')).toBeInTheDocument()
    expect(screen.queryByText('30')).not.toBeInTheDocument()
  })

  it('auto-collapses the monitoring timeline and expands it while hovered', async () => {
    open('/monitoring?intersection_id=INT-1&source_profile_id=SRC-1')
    await screen.findByAltText('检测器输出视频流', {}, { timeout: 10_000 })

    const timeline = screen.getByRole('region', { name: '实时数据时间轴' })
    expect(timeline).toHaveAttribute('data-state', 'collapsed')

    fireEvent.mouseEnter(timeline)
    expect(timeline).toHaveAttribute('data-state', 'expanded')

    fireEvent.mouseLeave(timeline)
    expect(timeline).toHaveAttribute('data-state', 'collapsed')
  })

  it('opens monitoring side panels by default and keeps manual collapse and pin controls', async () => {
    open('/monitoring?intersection_id=INT-1&view=detector')
    await screen.findByAltText('检测器输出视频流', {}, { timeout: 10_000 })

    const leftPanel = screen.getByLabelText('实时态势面板')
    const rightPanel = screen.getByLabelText('BEV 与实时事件面板')
    expect(leftPanel).toHaveAttribute('data-state', 'expanded')
    expect(rightPanel).toHaveAttribute('data-state', 'expanded')
    expect(leftPanel).toHaveClass('pinned')
    expect(rightPanel).toHaveClass('pinned')
    expect(screen.getAllByRole('button', { name: '取消锁定实时态势面板' })).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: '取消锁定BEV与实时事件面板' })).toHaveLength(1)
    expect(leftPanel).toHaveAttribute('data-transparency', '40')
    expect(rightPanel).toHaveAttribute('data-transparency', '40')
    expect(document.querySelector('.main-feed-status')).not.toHaveClass('side-collapsed')
    expect(document.querySelector('.map-tools')).not.toHaveClass('side-collapsed')

    fireEvent.click(screen.getByRole('button', { name: '收缩实时态势面板' }))
    expect(leftPanel).toHaveAttribute('data-state', 'collapsed')
    expect(document.querySelector('.main-feed-status')).toHaveClass('side-collapsed')
    fireEvent.mouseEnter(leftPanel)
    expect(leftPanel).toHaveAttribute('data-state', 'expanded')
    expect(document.querySelector('.main-feed-status')).not.toHaveClass('side-collapsed')
    fireEvent.click(screen.getByRole('button', { name: '锁定实时态势面板' }))
    fireEvent.mouseLeave(leftPanel)
    expect(leftPanel).toHaveAttribute('data-state', 'expanded')
    expect(screen.getByRole('button', { name: '取消锁定实时态势面板' })).toHaveAttribute('aria-pressed', 'true')

    fireEvent.click(screen.getByRole('button', { name: '取消锁定实时态势面板' }))
    fireEvent.mouseLeave(leftPanel)
    expect(leftPanel).toHaveAttribute('data-state', 'collapsed')

    fireEvent.click(screen.getByRole('button', { name: '收缩BEV与实时事件面板' }))
    expect(rightPanel).toHaveAttribute('data-state', 'collapsed')
    expect(document.querySelector('.map-tools')).toHaveClass('side-collapsed')
    fireEvent.mouseEnter(rightPanel)
    expect(rightPanel).toHaveAttribute('data-state', 'expanded')
    expect(document.querySelector('.map-tools')).not.toHaveClass('side-collapsed')
    fireEvent.mouseLeave(rightPanel)
    expect(rightPanel).toHaveAttribute('data-state', 'collapsed')
  })

  it('keeps world-coordinate tracks off the detector video and renders them only on the BEV map', async () => {
    open('/monitoring?intersection_id=INT-1&view=detector')
    expect(await screen.findByAltText('检测器输出视频流')).toBeInTheDocument()

    act(() => liveMocks.wsCallback({ type: 'uav_track_complete', data: { pipeline_id: 'P-1', track_id: 101, trajectory_gcj02: [[117, 36.7], [117.0001, 36.7001], [117.0002, 36.7002]] } }))
    act(() => liveMocks.wsCallback({ type: 'uav_track_complete', data: { pipeline_id: 'P-1', track_id: 102, trajectory_gcj02: [[117.0001, 36.7], [117.0002, 36.7001], [117.0003, 36.7002]] } }))

    expect(screen.queryByLabelText('车辆轨迹图层')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /切为主视图/ }))
    expect(await screen.findByRole('img', { name: 'BEV 地图轨迹主视图' })).toHaveAttribute('data-trajectory-count', '2')
  })

  it('keeps every BEV trajectory from the latest five minutes even when the total exceeds 150', async () => {
    open('/monitoring?intersection_id=INT-1&source_profile_id=SRC-1&view=bev')
    expect(await screen.findByText('历史路径交点事件')).toBeInTheDocument()
    const map = await screen.findByRole('img', { name: 'BEV 地图轨迹主视图' })
    const recentOccurredAt = new Date().toISOString()

    act(() => liveMocks.wsCallback({
      type: 'uav_stats',
      data: {
        pipeline_id: 'P-1',
        active_trajectories: [{
          track_id: 9001,
          trajectory_gcj02: [[117, 36.7], [117.0001, 36.7001]],
        }],
        candidate_trajectories: [{
          track_id: 9002,
          tracking_quality: 'degraded',
          trajectory_gcj02: [[117.0001, 36.7], [117.0002, 36.7001]],
        }],
      },
    }))
    act(() => {
      for (let trackId = 1; trackId <= 160; trackId += 1) {
        liveMocks.wsCallback({
          type: 'uav_track_complete',
          occurredAt: recentOccurredAt,
          data: {
            pipeline_id: 'P-1',
            track_id: trackId,
            trajectory_gcj02: [[117, 36.7], [117.0001, 36.7001]],
          },
        })
      }
    })

    expect(map).toHaveAttribute('data-trajectory-count', '162')
    expect(map.getAttribute('data-track-ids').split(',')).toEqual(expect.arrayContaining(['9001', '9002', '1', '160']))
  })

  it('backfills older BEV trajectories to 150 when the five-minute window has fewer tracks', async () => {
    open('/monitoring?intersection_id=INT-1&source_profile_id=SRC-1&view=bev')
    expect(await screen.findByText('历史路径交点事件')).toBeInTheDocument()
    const map = await screen.findByRole('img', { name: 'BEV 地图轨迹主视图' })
    const oldReceiptTime = Date.now() - (6 * 60 * 1000)
    const dateNow = vi.spyOn(Date, 'now').mockReturnValue(oldReceiptTime)
    try {
      act(() => {
        for (let trackId = 1; trackId <= 160; trackId += 1) {
          liveMocks.wsCallback({
            type: 'uav_track_complete',
            data: {
              pipeline_id: 'P-1',
              track_id: trackId,
              trajectory_gcj02: [[117, 36.7], [117.0001, 36.7001]],
            },
          })
        }
      })
    } finally {
      dateNow.mockRestore()
    }
    act(() => liveMocks.wsCallback({
      type: 'uav_stats',
      data: {
        pipeline_id: 'P-1',
        active_trajectories: [{
          track_id: 9001,
          trajectory_gcj02: [[117, 36.7], [117.0001, 36.7001]],
        }],
        candidate_trajectories: [{
          track_id: 9002,
          tracking_quality: 'degraded',
          trajectory_gcj02: [[117.0001, 36.7], [117.0002, 36.7001]],
        }],
      },
    }))

    expect(map).toHaveAttribute('data-trajectory-count', '150')
    expect(map.getAttribute('data-track-ids').split(',')).toEqual(expect.arrayContaining(['9001', '9002', '13', '160']))
    expect(map.getAttribute('data-track-ids').split(',')).not.toContain('12')
  })

  it('retries a failed MJPEG stream on the fixed three-second interval', async () => {
    open('/monitoring?intersection_id=INT-1')
    const video = await screen.findByAltText('检测器输出视频流')
    vi.useFakeTimers()
    fireEvent.error(video)
    expect(screen.getByText('视频流重连中 · 1/5')).toBeInTheDocument()

    act(() => vi.advanceTimersByTime(3_000))
    expect(screen.getByAltText('检测器输出视频流')).toHaveAttribute('src', expect.stringContaining('retry='))
    vi.useRealTimers()
  })

  it('restarts an MJPEG connection that never produces its first frame', async () => {
    open('/monitoring?intersection_id=INT-1')
    const video = await screen.findByAltText('检测器输出视频流')
    vi.useFakeTimers()

    fireEvent.error(video)
    act(() => vi.advanceTimersByTime(3_000))
    expect(screen.getByAltText('检测器输出视频流')).toBeInTheDocument()

    act(() => vi.advanceTimersByTime(8_000))
    expect(screen.getByText('视频流重连中 · 2/5')).toBeInTheDocument()
    vi.useRealTimers()
  })

  it('keeps recovering after the initial MJPEG retry window is exhausted', async () => {
    open('/monitoring?intersection_id=INT-1')
    await screen.findByAltText('检测器输出视频流')
    vi.useFakeTimers()
    try {
      for (let attempt = 1; attempt <= 5; attempt += 1) {
        fireEvent.error(screen.getByAltText('检测器输出视频流'))
        expect(screen.getByText(`视频流重连中 · ${attempt}/5`)).toBeInTheDocument()
        act(() => vi.advanceTimersByTime(3_000))
      }
      fireEvent.error(screen.getByAltText('检测器输出视频流'))
      expect(screen.getByText('视频流连接失败')).toBeInTheDocument()

      act(() => vi.advanceTimersByTime(10_000))
      expect(screen.getByAltText('检测器输出视频流')).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it('shows real system data, marks legacy topics, and keeps identity read-only', async () => {
    open('/admin/system?tab=system')

    expect(await screen.findByText('uav_statistics_11')).toBeInTheDocument()
    expect(screen.getByText('非 uav_ Topic 仅作为迁移期遗留链路如实展示')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '身份同步' }))
    expect(await screen.findByText('admin@example.com')).toBeInTheDocument()
    expect(screen.getByText('当前仅支持查看用户同步结果，邀请、编辑和删除功能尚未开放。')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /邀请|新建用户|删除用户/ })).not.toBeInTheDocument()
  })

  it('keeps usable system panels when one backend service fails', async () => {
    liveMocks.api.gpu.mockRejectedValue(new Error('GPU 指标暂不可用'))
    open('/admin/system')

    expect(await screen.findByText('部分系统数据不可用')).toBeInTheDocument()
    expect(screen.getByText('GPU 指标暂不可用')).toBeInTheDocument()
    expect(await screen.findByText('uav_statistics_11')).toBeInTheDocument()
  })

  it('projects multiple image polygons through the versioned channelized-map workflow', async () => {
    const rect = { left: 0, top: 0, right: 600, bottom: 270, width: 600, height: 270, x: 0, y: 0, toJSON: () => ({}) }
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue(rect)
    open('/admin/calibration?tab=lanes')
    fireEvent.click(await screen.findByText('INT-1'))
    fireEvent.click(screen.getByRole('button', { name: '加载本地 / 按需导入' }))
    const canvas = await screen.findByLabelText('渠化几何绘制画布')
    for (const [clientX, clientY] of [[110, 25], [160, 25], [160, 75]]) fireEvent.click(canvas, { clientX, clientY })
    fireEvent.click(screen.getByRole('button', { name: '完成车道面' }))
    fireEvent.change(screen.getByLabelText('车道方向'), { target: { value: 'left_turn' } })
    for (const [clientX, clientY] of [[260, 100], [310, 100], [310, 150]]) fireEvent.click(canvas, { clientX, clientY })
    fireEvent.click(screen.getByRole('button', { name: '完成车道面' }))
    fireEvent.click(screen.getByRole('button', { name: '保存影像拟合候选' }))

    await waitFor(() => expect(liveMocks.api.fitChannelizedMapFromImage).toHaveBeenCalledTimes(1))
    expect(liveMocks.api.fitChannelizedMapFromImage).toHaveBeenCalledWith('CMV-1', expect.objectContaining({
      task_id: 'TASK-1',
      lanes: [
        expect.objectContaining({ direction: 'straight', polygon_px: [[100, 50], [200, 50], [200, 150]] }),
        expect.objectContaining({ direction: 'left_turn', polygon_px: [[400, 200], [500, 200], [500, 300]] }),
      ],
    }))
  })

  it('overlays the current channelized lanes and adopts one as an editable image draft', async () => {
    open('/admin/calibration?tab=lanes')
    fireEvent.click(await screen.findByText('INT-1'))
    fireEvent.click(screen.getByRole('button', { name: '加载本地 / 按需导入' }))

    const referenceLane = await screen.findByLabelText('路网参考车道 candidate:LANE-1')
    fireEvent.click(referenceLane)

    expect(screen.getByText('0 个顶点 · 1 条车道 · 0 个渠化要素')).toBeInTheDocument()
    expect(screen.getByLabelText('调整车道顶点 1')).toBeInTheDocument()
  })

  it('selects and adopts the whole Link group when a reference lane is clicked once', async () => {
    liveMocks.api.bootstrapChannelizedMap.mockResolvedValue({ source: 'local', map: groupedLaneMap() })

    open('/admin/calibration?tab=lanes')
    fireEvent.click(await screen.findByText('INT-1'))
    fireEvent.click(screen.getByRole('button', { name: '加载本地 / 按需导入' }))
    fireEvent.click(await screen.findByLabelText('路网参考车道 candidate:LANE-1'))

    expect(screen.getByText('Link LINK-1 · 2 条车道')).toBeInTheDocument()
    expect(screen.getByLabelText('拟合车道 candidate:LANE-1')).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByLabelText('拟合车道 candidate:LANE-2')).toHaveAttribute('aria-selected', 'true')
    expect(screen.queryByLabelText('拟合车道 candidate:LANE-3')).not.toBeInTheDocument()
  })

  it('switches from Link group editing to one lane when a draft lane is double-clicked', async () => {
    liveMocks.api.bootstrapChannelizedMap.mockResolvedValue({ source: 'local', map: groupedLaneMap() })
    open('/admin/calibration?tab=lanes')
    fireEvent.click(await screen.findByText('INT-1'))
    fireEvent.click(screen.getByRole('button', { name: '加载本地 / 按需导入' }))
    fireEvent.click(await screen.findByLabelText('路网参考车道 candidate:LANE-1'))

    fireEvent.doubleClick(screen.getByLabelText('拟合车道 candidate:LANE-1'))

    expect(screen.getByText('单车道 · candidate:LANE-1')).toBeInTheDocument()
    expect(screen.getByLabelText('拟合车道 candidate:LANE-1')).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByLabelText('拟合车道 candidate:LANE-2')).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByLabelText('调整车道顶点 1')).toBeInTheDocument()
  })

  it('deletes the selected Link group without removing lanes from other Links', async () => {
    liveMocks.api.bootstrapChannelizedMap.mockResolvedValue({ source: 'local', map: groupedLaneMap() })
    open('/admin/calibration?tab=lanes')
    fireEvent.click(await screen.findByText('INT-1'))
    fireEvent.click(screen.getByRole('button', { name: '加载本地 / 按需导入' }))
    fireEvent.click(await screen.findByLabelText('路网参考车道 candidate:LANE-1'))
    fireEvent.click(await screen.findByLabelText('路网参考车道 candidate:LANE-3'))
    fireEvent.click(screen.getByLabelText('拟合车道 candidate:LANE-1'))

    fireEvent.click(screen.getByRole('button', { name: '删除所选' }))

    expect(screen.queryByLabelText('拟合车道 candidate:LANE-1')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('拟合车道 candidate:LANE-2')).not.toBeInTheDocument()
    expect(screen.getByLabelText('拟合车道 candidate:LANE-3')).toBeInTheDocument()
  })

  it('splits one double-clicked lane into two editable lanes on the same Link', async () => {
    liveMocks.api.bootstrapChannelizedMap.mockResolvedValue({ source: 'local', map: groupedLaneMap() })
    open('/admin/calibration?tab=lanes')
    fireEvent.click(await screen.findByText('INT-1'))
    fireEvent.click(screen.getByRole('button', { name: '加载本地 / 按需导入' }))
    fireEvent.click(await screen.findByLabelText('路网参考车道 candidate:LANE-1'))
    fireEvent.doubleClick(screen.getByLabelText('拟合车道 candidate:LANE-1'))

    fireEvent.click(screen.getByRole('button', { name: '拆分车道' }))

    expect(screen.queryByLabelText('拟合车道 candidate:LANE-1')).not.toBeInTheDocument()
    expect(screen.getAllByLabelText(/拟合车道 candidate:LANE-1:split-/)).toHaveLength(2)
    expect(screen.getByText('0 个顶点 · 3 条车道 · 0 个渠化要素')).toBeInTheDocument()
  })

  it('merges the selected Link group into one editable lane envelope', async () => {
    liveMocks.api.bootstrapChannelizedMap.mockResolvedValue({ source: 'local', map: groupedLaneMap() })
    open('/admin/calibration?tab=lanes')
    fireEvent.click(await screen.findByText('INT-1'))
    fireEvent.click(screen.getByRole('button', { name: '加载本地 / 按需导入' }))
    fireEvent.click(await screen.findByLabelText('路网参考车道 candidate:LANE-1'))

    fireEvent.click(screen.getByRole('button', { name: '合并车道' }))

    expect(screen.queryByLabelText('拟合车道 candidate:LANE-1')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('拟合车道 candidate:LANE-2')).not.toBeInTheDocument()
    expect(screen.getByLabelText('拟合车道 candidate:LANE-1:merged')).toBeInTheDocument()
    expect(screen.getByText('单车道 · candidate:LANE-1:merged')).toBeInTheDocument()
    expect(screen.getByText('0 个顶点 · 1 条车道 · 0 个渠化要素')).toBeInTheDocument()
  })

  it('drags an adopted lane vertex in source-image coordinates before fitting', async () => {
    const rect = { left: 0, top: 0, right: 600, bottom: 270, width: 600, height: 270, x: 0, y: 0, toJSON: () => ({}) }
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue(rect)
    open('/admin/calibration?tab=lanes')
    fireEvent.click(await screen.findByText('INT-1'))
    fireEvent.click(screen.getByRole('button', { name: '加载本地 / 按需导入' }))
    fireEvent.click(await screen.findByLabelText('路网参考车道 candidate:LANE-1'))

    const canvas = screen.getByLabelText('渠化几何绘制画布')
    const handle = screen.getByLabelText('调整车道顶点 1')
    fireEvent.pointerDown(handle, { pointerId: 1, clientX: 110, clientY: 25 })
    fireEvent.pointerMove(canvas, { pointerId: 1, clientX: 135, clientY: 50 })
    fireEvent.pointerUp(canvas, { pointerId: 1, clientX: 135, clientY: 50 })
    fireEvent.click(screen.getByRole('button', { name: '保存影像拟合候选' }))

    await waitFor(() => expect(liveMocks.api.fitChannelizedMapFromImage).toHaveBeenCalledTimes(1))
    const [mapId, payload] = liveMocks.api.fitChannelizedMapFromImage.mock.calls[0]
    expect(mapId).toBe('CMV-1')
    expect(payload.lanes[0].polygon_px[0]).toEqual([150, 100])
    expect(payload.lanes[0].polygon_px[1][0]).toBeCloseTo(200)
    expect(payload.lanes[0].polygon_px[2][1]).toBeCloseTo(150)
  })

  it('drags an adopted lane as one shape before fitting', async () => {
    const rect = { left: 0, top: 0, right: 600, bottom: 270, width: 600, height: 270, x: 0, y: 0, toJSON: () => ({}) }
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue(rect)
    open('/admin/calibration?tab=lanes')
    fireEvent.click(await screen.findByText('INT-1'))
    fireEvent.click(screen.getByRole('button', { name: '加载本地 / 按需导入' }))
    fireEvent.click(await screen.findByLabelText('路网参考车道 candidate:LANE-1'))

    const canvas = screen.getByLabelText('渠化几何绘制画布')
    const lane = screen.getByLabelText('拟合车道 candidate:LANE-1')
    fireEvent.pointerDown(lane, { pointerId: 2, clientX: 110, clientY: 25 })
    fireEvent.pointerMove(canvas, { pointerId: 2, clientX: 120, clientY: 35 })
    fireEvent.pointerUp(canvas, { pointerId: 2, clientX: 120, clientY: 35 })
    fireEvent.click(screen.getByRole('button', { name: '保存影像拟合候选' }))

    await waitFor(() => expect(liveMocks.api.fitChannelizedMapFromImage).toHaveBeenCalledTimes(1))
    const payload = liveMocks.api.fitChannelizedMapFromImage.mock.calls[0][1]
    expect(payload.lanes[0].polygon_px[0][0]).toBeCloseTo(120)
    expect(payload.lanes[0].polygon_px[0][1]).toBeCloseTo(70)
    expect(payload.lanes[0].polygon_px[2][0]).toBeCloseTo(220)
    expect(payload.lanes[0].polygon_px[2][1]).toBeCloseTo(170)
  })

  it('drags every lane in the selected Link group by the same image offset', async () => {
    const rect = { left: 0, top: 0, right: 600, bottom: 270, width: 600, height: 270, x: 0, y: 0, toJSON: () => ({}) }
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue(rect)
    liveMocks.api.bootstrapChannelizedMap.mockResolvedValue({ source: 'local', map: groupedLaneMap() })
    open('/admin/calibration?tab=lanes')
    fireEvent.click(await screen.findByText('INT-1'))
    fireEvent.click(screen.getByRole('button', { name: '加载本地 / 按需导入' }))
    fireEvent.click(await screen.findByLabelText('路网参考车道 candidate:LANE-1'))

    const canvas = screen.getByLabelText('渠化几何绘制画布')
    fireEvent.pointerDown(screen.getByLabelText('拟合车道 candidate:LANE-1'), { pointerId: 3, clientX: 110, clientY: 25 })
    fireEvent.pointerMove(canvas, { pointerId: 3, clientX: 120, clientY: 35 })
    fireEvent.pointerUp(canvas, { pointerId: 3, clientX: 120, clientY: 35 })
    fireEvent.click(screen.getByRole('button', { name: '保存影像拟合候选' }))

    await waitFor(() => expect(liveMocks.api.fitChannelizedMapFromImage).toHaveBeenCalledTimes(1))
    const lanes = liveMocks.api.fitChannelizedMapFromImage.mock.calls[0][1].lanes
    expect(lanes[0].polygon_px[0][0]).toBeCloseTo(120)
    expect(lanes[0].polygon_px[0][1]).toBeCloseTo(70)
    expect(lanes[1].polygon_px[0][0]).toBeCloseTo(240)
    expect(lanes[1].polygon_px[0][1]).toBeCloseTo(70)
  })

  it('drags only one lane after double-click switches to single-lane editing', async () => {
    const rect = { left: 0, top: 0, right: 600, bottom: 270, width: 600, height: 270, x: 0, y: 0, toJSON: () => ({}) }
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue(rect)
    liveMocks.api.bootstrapChannelizedMap.mockResolvedValue({ source: 'local', map: groupedLaneMap() })
    open('/admin/calibration?tab=lanes')
    fireEvent.click(await screen.findByText('INT-1'))
    fireEvent.click(screen.getByRole('button', { name: '加载本地 / 按需导入' }))
    fireEvent.click(await screen.findByLabelText('路网参考车道 candidate:LANE-1'))
    fireEvent.doubleClick(screen.getByLabelText('拟合车道 candidate:LANE-1'))

    const canvas = screen.getByLabelText('渠化几何绘制画布')
    fireEvent.pointerDown(screen.getByLabelText('拟合车道 candidate:LANE-1'), { pointerId: 4, clientX: 110, clientY: 25 })
    fireEvent.pointerMove(canvas, { pointerId: 4, clientX: 120, clientY: 35 })
    fireEvent.pointerUp(canvas, { pointerId: 4, clientX: 120, clientY: 35 })
    fireEvent.click(screen.getByRole('button', { name: '保存影像拟合候选' }))

    await waitFor(() => expect(liveMocks.api.fitChannelizedMapFromImage).toHaveBeenCalledTimes(1))
    const lanes = liveMocks.api.fitChannelizedMapFromImage.mock.calls[0][1].lanes
    expect(lanes[0].polygon_px[0][0]).toBeCloseTo(120)
    expect(lanes[0].polygon_px[0][1]).toBeCloseTo(70)
    expect(lanes[1].polygon_px[0][0]).toBeCloseTo(220)
    expect(lanes[1].polygon_px[0][1]).toBeCloseTo(50)
  })

  it('forks an immutable verified map into a new editable fitting draft', async () => {
    const publishedMap = {
      id: 'CMV-PUBLISHED', inter_id: 'INT-1', version_no: 7, status: 'lane_verified', coordinate_system: 'GCJ02', coordinate_transform_version: 'v1', road_data_version: 'ROAD-1', anchor_gcj02: [117, 36.7],
      geometry_gcj02: { links: {} }, geometry_enu_m: { links: {} }, topology: { links: [] }, quality: { reviewed: true }, source_checksum: 'abc123',
      lanes: [{ local_lane_id: 'lane:verified:1', source_lane_id: 'LANE-1', link_id: 'LINK-1', geometry_source: 'imagery_fitted', geometry_gcj02: { type: 'Polygon', coordinates: [] }, geometry_enu_m: { type: 'Polygon', coordinates: [] }, match_confidence: 0.98 }],
    }
    liveMocks.api.bootstrapChannelizedMap.mockResolvedValue({ source: 'local', map: publishedMap })
    liveMocks.api.createChannelizedMap.mockResolvedValue({ ...publishedMap, id: 'CMV-DRAFT', version_no: 8, status: 'draft' })
    open('/admin/calibration?tab=lanes')
    fireEvent.click(await screen.findByRole('button', { name: '加载本地 / 按需导入' }))

    const fork = await screen.findByRole('button', { name: '基于 lane_verified 新建拟合草稿' })
    fireEvent.click(fork)

    await waitFor(() => expect(liveMocks.api.createChannelizedMap).toHaveBeenCalledWith(expect.objectContaining({
      inter_id: 'INT-1',
      road_data_version: 'ROAD-1',
      lanes: [expect.objectContaining({ local_lane_id: 'lane:verified:1', geometry_source: 'imagery_fitted' })],
    })))
    await waitFor(() => expect(screen.queryByRole('button', { name: '基于 lane_verified 新建拟合草稿' })).not.toBeInTheDocument())
  })

  it('keeps a published project inspector compact when no keyframe is selected', async () => {
    liveMocks.api.laneTasks.mockResolvedValue([])
    open('/admin/calibration/editor?inter_id=INT-1&project_id=IPR-1')

    expect(await screen.findByText('9/9 通过')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('画布视图')).toHaveValue('map'))
    expect(screen.getByText('关键帧与素材').closest('details')).not.toHaveAttribute('open')
    expect(screen.getByRole('button', { name: '进入运行应用' })).toBeEnabled()
  })

  it('hydrates the project overview map and routes its published next action to runtime', async () => {
    open('/admin/intersection-projects/IPR-1?tab=overview')

    expect(await screen.findByText('6/6 通过')).toBeInTheDocument()
    expect(screen.getByLabelText('预览底图')).toHaveValue('map')
    expect(liveMocks.api.channelizedMap).toHaveBeenCalledWith('CMV-1')

    fireEvent.click(screen.getByRole('button', { name: '版本对比' }))
    expect(screen.getByRole('region', { name: '版本对比面板' })).toHaveTextContent('暂无可对比历史版本')

    fireEvent.click(screen.getAllByRole('button', { name: /去处理/ })[0])
    await waitFor(() => expect(window.location.search).toContain('tab=runtime'))
    expect(await screen.findByText('Runtime 规则')).toBeInTheDocument()
  })

  it('creates a recoverable lane task from a real survey keyframe and hydrates registration context', async () => {
    liveMocks.api.laneTasks.mockResolvedValue([])
    open('/admin/calibration?tab=lanes')

    fireEvent.change(await screen.findByLabelText('路口 ID'), { target: { value: 'INT-1' } })
    const loadFrame = await screen.findByRole('button', { name: '载入关键帧并开始标注' })
    await waitFor(() => expect(loadFrame).toBeEnabled())
    fireEvent.click(loadFrame)

    await waitFor(() => expect(liveMocks.api.createLaneTaskFromSurveyFrame).toHaveBeenCalledWith('FRM-LANE-1'))
    expect(await screen.findByLabelText('渠化几何绘制画布')).toBeInTheDocument()
    expect(screen.getByLabelText('SourceProfile ID')).toHaveValue('SRC-1')
    expect(screen.getByLabelText('pixel → ENU 3×3 单应矩阵')).toHaveValue('[[0.1,0,-10],[0,0.1,-5],[0,0,1]]')
  })

  it('starts retained source extraction inside lane calibration after explicit precheck', async () => {
    const extractedTask = { id: 'SVY-CAL-1', title: '渠化标注抽帧 · 小清河北路 × 水屯路', inter_id: 'INT-1', status: 'collecting', revision: 4 }
    const extractedBatch = { id: 'BATCH-CAL-1', status: 'queued', source_profile_id: 'SRC-1' }
    let extractionStarted = false
    liveMocks.api.laneTasks.mockResolvedValue([])
    liveMocks.api.surveyTasks.mockImplementation(() => Promise.resolve(extractionStarted ? [extractedTask] : []))
    liveMocks.api.surveyBatches.mockImplementation((taskId) => Promise.resolve(taskId === extractedTask.id ? [extractedBatch] : []))
    liveMocks.api.startLaneKeyframeExtraction.mockImplementation(() => {
      extractionStarted = true
      return Promise.resolve({ task: extractedTask, batch: extractedBatch })
    })
    open('/admin/calibration?tab=lanes')

    fireEvent.change(screen.getByLabelText('路口 ID'), { target: { value: 'INT-1' } })
    expect(await screen.findByRole('option', { name: /小清河北路早高峰 · SRC-1/ })).toBeInTheDocument()
    for (const [, label] of [
      ['task_context', '已确认当前路口与路网版本'],
      ['operator_authorized', '操作员已获素材使用授权'],
      ['site_command_confirmed', '现场指挥与航拍任务已确认'],
      ['device_ready', '无人机正拍视频与遥测源可用'],
      ['storage_ready', '证据存储空间与留存策略已确认'],
    ]) fireEvent.click(screen.getByRole('checkbox', { name: label }))
    fireEvent.click(screen.getByRole('button', { name: '完成预检并开始抽帧' }))

    await waitFor(() => expect(liveMocks.api.startLaneKeyframeExtraction).toHaveBeenCalledTimes(1))
    expect(liveMocks.api.startLaneKeyframeExtraction).toHaveBeenCalledWith({
      inter_id: 'INT-1',
      source_profile_id: 'SRC-1',
      road_data_version: 'ROAD-1',
      checklist: {
        task_context: true,
        operator_authorized: true,
        site_command_confirmed: true,
        device_ready: true,
        storage_ready: true,
      },
    }, expect.stringMatching(/^lane-extract-/))
    await waitFor(() => expect(screen.getByLabelText('采集批次')).toHaveValue('BATCH-CAL-1'))
    expect(within(screen.getByTestId('keyframe-extraction')).getByRole('status')).toHaveTextContent('抽帧任务已入队 · BATCH-CAL-1')
    expect(screen.getByRole('button', { name: '完成预检并开始抽帧' })).toBeDisabled()
  })

  it('shows lane extraction failures beside the action that failed', async () => {
    liveMocks.api.laneTasks.mockResolvedValue([])
    liveMocks.api.surveyTasks.mockResolvedValue([])
    liveMocks.api.startLaneKeyframeExtraction.mockRejectedValue(new Error('抽帧接口暂不可用'))
    open('/admin/calibration?tab=lanes')

    fireEvent.change(await screen.findByLabelText('路口 ID'), { target: { value: 'INT-1' } })
    expect(await screen.findByRole('option', { name: /小清河北路早高峰 · SRC-1/ })).toBeInTheDocument()
    for (const label of [
      '已确认当前路口与路网版本',
      '操作员已获素材使用授权',
      '现场指挥与航拍任务已确认',
      '无人机正拍视频与遥测源可用',
      '证据存储空间与留存策略已确认',
    ]) fireEvent.click(screen.getByRole('checkbox', { name: label }))
    fireEvent.click(screen.getByRole('button', { name: '完成预检并开始抽帧' }))

    const extraction = screen.getByTestId('keyframe-extraction')
    expect(await within(extraction).findByText('抽帧接口暂不可用')).toBeInTheDocument()
  })
})
