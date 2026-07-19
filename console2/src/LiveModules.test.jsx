import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const liveMocks = vi.hoisted(() => ({
  wsCallback: null,
  wsChannels: [],
  api: {
    intersections: vi.fn(),
    intersection: vi.fn(),
    intersectionStats: vi.fn(),
    alerts: vi.fn(),
    acknowledgeAlert: vi.fn(),
    pipelines: vi.fn(),
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
    laneAnnotations: vi.fn(),
    saveLaneAnnotation: vi.fn(),
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
    return 'connected'
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
  MonitoringBevMap: ({ compact, label, trajectories = [] }) => <div role='img' aria-label={label} data-compact={compact ? 'true' : 'false'} data-trajectory-count={trajectories.length}>OpenLayers BEV 地图</div>,
}))

import { RouterApp } from './RouterApp'

function open(path) {
  window.history.pushState({}, '', path)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } })
  return { ...render(<QueryClientProvider client={queryClient}><RouterApp /></QueryClientProvider>), queryClient }
}

function mockSuccessfulApis() {
  liveMocks.api.intersections.mockResolvedValue([{ id: 'INT-1', name: '小清河北路 × 水屯路' }])
  liveMocks.api.intersection.mockResolvedValue({ id: 'INT-1', current_drone_id: 'UAV-1' })
  liveMocks.api.intersectionStats.mockResolvedValue([{ time: '2026-07-14T10:00:00Z', congestion_index: 4.8, cars: 20 }])
  liveMocks.api.alerts.mockResolvedValue([{ id: 'A-1', intersection_id: 'INT-1', alert_type: 'conflict', severity: 'P1', title: '机非冲突风险升高', description: '预测轨迹交汇', ttc_sec: 1.2, pet_sec: 0.8 }])
  liveMocks.api.acknowledgeAlert.mockResolvedValue({ id: 'A-1', status: 'acknowledged' })
  liveMocks.api.pipelines.mockResolvedValue([{ pipeline_id: 'P-1', intersection_id: 'INT-1', drone_id: 'UAV-1', camera_id: 11, status: 'running' }])
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
  liveMocks.api.laneTasks.mockResolvedValue([{ task_id: 'TASK-1', intersection_id: 'INT-1', image_width: 960, image_height: 540, lane_count: 0, roads: { north: [1, 2, 3] }, status: 'pending' }])
  liveMocks.api.laneTaskImage.mockResolvedValue(new Blob(['jpeg'], { type: 'image/jpeg' }))
  liveMocks.api.laneAnnotations.mockResolvedValue([])
  liveMocks.api.saveLaneAnnotation.mockResolvedValue({ task_id: 'TASK-1', status: 'saved' })
}

describe('Console2 live module migration', () => {
  beforeEach(() => {
    Object.values(liveMocks.api).forEach((mock) => mock.mockReset())
    liveMocks.wsCallback = null
    liveMocks.wsChannels = []
    mockSuccessfulApis()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:lane-task') })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
  })

  it('drives monitoring from REST and realtime data and preserves detector/BEV switching', async () => {
    open('/monitoring')

    await waitFor(() => expect(window.location.search).toContain('intersection_id=INT-1'))
    expect(await screen.findByAltText('检测器输出视频流')).toHaveAttribute('src', expect.stringContaining('/camera_11'))
    expect(liveMocks.wsChannels).toContain('uav_telemetry:UAV-1')
    expect(liveMocks.wsChannels).toContain('uav_telemetry:drone_11')
    expect((await screen.findAllByText('20')).length).toBeGreaterThan(0)
    expect(screen.getByLabelText('飞行姿态数据')).toHaveTextContent('118.6')

    act(() => liveMocks.wsCallback({ type: 'uav_stats', data: { congestion_index: 6.3, cars: 842, avg_speed_kmh: 27.4, fps: 29.7, inference_ms: 33, lane_stats: [{ queue_length_m: 186 }] } }))
    act(() => liveMocks.wsCallback({ type: 'uav_telemetry', data: { drone_id: 'drone_11', height: 112.4, attitude_head: 37.8, attitude_pitch: -1.2, gimbal_roll: 0.6, gimbal_mode: '锁定' } }))

    expect(screen.getByLabelText('飞行姿态数据')).toHaveTextContent('112.4')
    expect(screen.getByLabelText('飞行姿态数据')).toHaveTextContent('37.8')
    expect(screen.getByText('842')).toBeInTheDocument()
    expect(screen.getByText('186')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /切为主视图/ }))
    expect(window.location.search).toContain('view=bev')
    expect(await screen.findByRole('img', { name: 'BEV 地图轨迹主视图' })).toBeInTheDocument()
    expect(screen.queryByAltText('BEV 鸟瞰轨迹投放图')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /机非冲突风险升高/ }))
    expect(screen.queryByText('AI 事件研判')).not.toBeInTheDocument()
  })

  it('freezes visible REST, WebSocket, and clock updates while paused then restores them in order', async () => {
    const { queryClient } = open('/monitoring?intersection_id=INT-1')
    expect((await screen.findAllByText('20')).length).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('button', { name: '暂停实时数据' }))
    const frozenClock = document.querySelector('.timeline-controls span').textContent

    act(() => liveMocks.wsCallback({ type: 'uav_stats', data: { cars: 842, congestion_index: 6.3 } }))
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

  it('auto-collapses translucent monitoring side panels and lets operators lock them open', async () => {
    open('/monitoring?intersection_id=INT-1&view=detector')
    await screen.findByAltText('检测器输出视频流')

    const leftPanel = screen.getByLabelText('实时态势面板')
    const rightPanel = screen.getByLabelText('BEV 与实时事件面板')
    expect(leftPanel).toHaveAttribute('data-state', 'collapsed')
    expect(rightPanel).toHaveAttribute('data-state', 'collapsed')
    expect(leftPanel).toHaveAttribute('data-transparency', '40')
    expect(rightPanel).toHaveAttribute('data-transparency', '40')
    expect(document.querySelector('.main-feed-status')).toHaveClass('side-collapsed')
    expect(document.querySelector('.map-tools')).toHaveClass('side-collapsed')

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

    fireEvent.mouseEnter(rightPanel)
    expect(rightPanel).toHaveAttribute('data-state', 'expanded')
    expect(document.querySelector('.map-tools')).not.toHaveClass('side-collapsed')
    fireEvent.mouseLeave(rightPanel)
    expect(rightPanel).toHaveAttribute('data-state', 'collapsed')
  })

  it('keeps world-coordinate tracks off the detector video and renders them only on the BEV map', async () => {
    open('/monitoring?intersection_id=INT-1&view=detector')
    expect(await screen.findByAltText('检测器输出视频流')).toBeInTheDocument()

    act(() => liveMocks.wsCallback({ type: 'uav_track_complete', data: { track_id: 101, trajectory_world_m: [[0, 0], [10, 8], [20, 12]] } }))
    act(() => liveMocks.wsCallback({ type: 'uav_track_complete', data: { track_id: 102, trajectory_world_m: [[2, 1], [12, 5], [22, 9]] } }))

    expect(screen.queryByLabelText('车辆轨迹图层')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /切为主视图/ }))
    expect(await screen.findByRole('img', { name: 'BEV 地图轨迹主视图' })).toHaveAttribute('data-trajectory-count', '2')
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

  it('saves multiple lane polygons in natural image coordinates and preserves roads', async () => {
    const rect = { left: 0, top: 0, right: 480, bottom: 270, width: 480, height: 270, x: 0, y: 0, toJSON: () => ({}) }
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue(rect)
    open('/admin/calibration?tab=lanes')

    const canvas = await screen.findByLabelText('车道多边形绘制画布')
    for (const [clientX, clientY] of [[50, 25], [100, 25], [100, 75]]) fireEvent.click(canvas, { clientX, clientY })
    fireEvent.click(screen.getByRole('button', { name: '闭合为车道' }))
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'left_turn' } })
    for (const [clientX, clientY] of [[200, 100], [250, 100], [250, 150]]) fireEvent.click(canvas, { clientX, clientY })
    fireEvent.click(screen.getByRole('button', { name: '闭合为车道' }))
    fireEvent.click(screen.getByRole('button', { name: '保存标注参数' }))

    await waitFor(() => expect(liveMocks.api.saveLaneAnnotation).toHaveBeenCalledTimes(1))
    expect(liveMocks.api.saveLaneAnnotation).toHaveBeenCalledWith('TASK-1', {
      lanes: [
        { lane_id: 'L1', name: '车道 1', direction: 'straight', polygon: [100, 50, 200, 50, 200, 150] },
        { lane_id: 'L2', name: '车道 2', direction: 'left_turn', polygon: [400, 200, 500, 200, 500, 300] },
      ],
      roads: { north: [1, 2, 3] },
    })
  })
})
