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
  const frame = { id: 'FRM-01', task_id: task.id, batch_id: 'BATCH-01', frame_number: 18236, timestamp_sec: 10, has_metric_transform: true, image_url: '/api/v1/survey-evidence/EVI-IMAGE/content', bev_url: '/api/v1/survey-evidence/EVI-BEV/content', quality: {}, telemetry: {} }
  const measurement = { id: 'M-01', revision: 1, frame_id: frame.id, geometry_type: 'line', category: '刹车痕迹', image_geometry: [[10, 10], [40, 40]], display_value: '12.48m', quality_status: 'unverified', source: 'manual' }
  const report = { id: 'RPT-01', task_id: task.id, version: 1, status: 'generated', schema_version: 'uav.survey-result.v1', content_hash: 'a'.repeat(64), payload: {}, pdf_url: '/api/v1/survey-evidence/EVI-PDF/content', delivery_blocked_reason: 'survey quality thresholds are not approved' }
  return {
    ...actual,
    platformApi: {
      ...actual.platformApi,
      intersections: vi.fn().mockResolvedValue([
        { id: '370102000104', name: '小清河北路 × 水屯路', center_lat: 36.7029, center_lon: 117.0223, status: 'active', quality_status: 'unverified' },
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
      trajectories: vi.fn().mockResolvedValue([{ id: 'TRK-1', track_id: 7, trajectory_world_m: [[0, 0], [1, 1]], quality_status: 'unverified' }]),
      conflicts: vi.fn().mockResolvedValue([
        { id: 'UAV-EVT-20260713-001', inter_id: '370102000104', conflict_scene: '机非冲突风险升高', severity: 'critical', ttc_sec: 1.2, pet_sec: 0.8, distance_m: 0, risk_score: 86, evidence: ['path_intersection'], occurred_at: '2026-07-15T02:52:16Z', quality_status: 'unverified', time_quality: 'reconstructed', review_status: 'pending', review_revision: 1 },
      ]),
      alerts: vi.fn().mockResolvedValue([{ id: 'UAV-EVT-20260713-004', intersection_id: '370102000104', alert_type: 'congestion', severity: 'P2', title: '排队增长', description: 'queue', status: 'open', timestamp: '2026-07-15T02:50:00Z' }]),
      reviewConflict: vi.fn().mockImplementation((_interId, _eventId, body) => Promise.resolve({ id: 'UAV-EVT-20260713-001', inter_id: '370102000104', conflict_scene: '机非冲突风险升高', severity: 'critical', ttc_sec: 1.2, pet_sec: 0.8, occurred_at: '2026-07-15T02:52:16Z', quality_status: 'unverified', time_quality: 'reconstructed', review_status: body.review_status, review_revision: 2 })),
      surveyTask: vi.fn().mockResolvedValue(task),
      surveyBatches: vi.fn().mockResolvedValue([{ id: 'BATCH-01', status: 'ready', telemetry_coverage: 0.94, quality_checks: { keyframes_extracted: 1, homography_available: 1 } }]),
      surveyFrames: vi.fn().mockResolvedValue([frame]),
      surveyMeasurements: vi.fn().mockResolvedValue([measurement]),
      surveyAction: vi.fn().mockImplementation((_id, body) => Promise.resolve({ ...task, status: body.action === 'submit_review' ? 'pending_review' : task.status, revision: 5, version: 'v5' })),
      surveyEvidence: vi.fn().mockResolvedValue(new Blob(['image'])),
      importSurveyBatch: vi.fn().mockResolvedValue({ id: 'BATCH-01', status: 'queued' }),
      surveyReports: vi.fn().mockResolvedValue([]),
      generateSurveyReport: vi.fn().mockResolvedValue(report),
      drones: vi.fn().mockResolvedValue([
        { id: 'UAV-M300-03', name: 'M300 test', enabled: true, status: 'offline', telemetry_status: 'stale', battery_pct: null, revision: 1, default_inter_id: 'INT_camera_1', default_road_data_version: 'ROAD-LOCAL-INTER-XQH', intersection_name: '小清河北路 × 水屯路', road_context_quality: 'unverified', default_video_source_id: 'VID-1' },
      ]),
      sources: vi.fn().mockResolvedValue([
        { profile_id: 'SRC-LOCAL-XQH', display_name: 'inter_xqh 早高峰', drone_id: 'UAV-M300-03', mode: 'local', enabled: true, validation_status: 'valid', revision: 1, video: { id: 'VID-1', source_type: 'mp4', location_hint: 'inter_xqh.mp4' }, telemetry: { id: 'TEL-1', source_type: 'srt', location_hint: 'telemetry.srt' } },
        { profile_id: 'SRC-LOCAL-XQH-PM', display_name: 'inter_xqh 晚高峰', drone_id: 'UAV-M300-03', mode: 'local', enabled: true, validation_status: 'valid', revision: 1, video: { id: 'VID-2', source_type: 'mp4', location_hint: 'inter_xqh-pm.mp4' }, telemetry: { id: 'TEL-2', source_type: 'file', location_hint: 'telemetry.txt' } },
      ]),
      flightPlans: vi.fn().mockResolvedValue([
        { id: 'FP-20260713-03', name: '夜间货车限行验证', drone_id: 'UAV-M300-03', state: 'draft', revision: 1, timezone: 'Asia/Shanghai', schedule: { type: 'once', start_at: '2026-07-15T22:30:00+08:00', end_at: '2026-07-16T00:30:00+08:00' } },
      ]),
      missions: vi.fn().mockResolvedValue([
        { id: 'MSN-0713-1050', name: '早高峰巡检', drone_id: 'UAV-M300-03', trigger_type: 'manual', status: 'running', scheduled_start_at: '2026-07-15T10:50:00+08:00', actual_start_at: '2026-07-15T10:50:06+08:00', pipeline: { id: 'pipe-1', observed_status: 'running', camera_id: 17 } },
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
        { id: 'ZONE-I4-01', name: '本地候选限行区', zone_type: 'truck_restriction', geometry: { type: 'Polygon', coordinates: [[[0, 0], [10, 0], [10, 10], [0, 0]]] }, coordinate_system: 'ENU', road_data_version: 'ROAD-I4', source: 'local_candidate', status: 'candidate', schedule: {}, checksum: 'b'.repeat(64), revision: 1, rule_count: 1, authority_status: 'unavailable' },
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
  CityMap: ({ offline = false }) => <div data-testid='city-map'>{offline ? '城市底图服务不可用' : '演示地图'}</div>,
}))

import { RouterApp } from './RouterApp'
import { platformApi } from './lib/api'

function open(path) {
  window.history.pushState({}, '', path)
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(<QueryClientProvider client={queryClient}><RouterApp /></QueryClientProvider>)
}

describe('Console2 full prototype', () => {
  beforeEach(() => {
    Object.assign(authState, {
      user: { username: 'admin', role: 'admin' },
      status: 'authenticated',
      isAuthenticated: true,
      platformRole: 'admin',
      consoleRole: 'admin',
    })
    window.history.pushState({}, '', '/')
  })

  it('renders the S8 city overview at the root route', () => {
    open('/')
    expect(screen.getByRole('heading', { name: '无人机交通态势工作台' })).toBeInTheDocument()
    expect(screen.getByText('无人机路口态势纵览')).toBeInTheDocument()
    expect(screen.getByText('待办任务')).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: '全域态势二级导航' })).toHaveTextContent('工作台首屏实时监测轨迹研判')
    expect(screen.getByRole('complementary', { name: '一级业务域' })).toBeInTheDocument()
  })

  it('uses the same first-level rail and domain secondary navigation on monitoring', () => {
    open('/monitoring')
    expect(screen.getByRole('navigation', { name: '全域态势二级导航' })).toHaveTextContent('工作台首屏实时监测轨迹研判')
    expect(screen.getByRole('link', { name: '实时监测' })).toHaveClass('active')
    expect(screen.getByRole('complementary', { name: '一级业务域' })).toBeInTheDocument()
    expect(screen.getByLabelText('飞行姿态数据')).toBeInTheDocument()
  })

  it('uses the server dashboard scope instead of URL prototype labels', async () => {
    open('/?scope=priority&window=1h')
    expect(await screen.findByRole('button', { name: /local_road9_authorized_scope/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /最近 30 分钟 · 固定工程窗口/ })).toBeDisabled()
  })

  it('restores intersection and drone selections from deep links', async () => {
    open('/gis?intersection_id=370102000104')
    await waitFor(() => expect(screen.getByLabelText('路口')).toHaveValue('370102000104'))
  })

  it('restores the fleet tab and selected drone from a deep link', async () => {
    open('/drones?tab=fleet&drone_id=UAV-M300-03')
    expect(await screen.findByRole('dialog', { name: 'M300 test' })).toBeInTheDocument()
  })

  it('renders the real replay camera stream and stops it from the route card', async () => {
    open('/drones?tab=fleet')
    const stream = await screen.findByRole('img', { name: '小清河北路 × 水屯路 实时检测画面' })
    expect(stream).toHaveAttribute('src', '/camera_17')
    expect(screen.getByRole('combobox', { name: '小清河北路 × 水屯路回放源' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '停止' }))
    await waitFor(() => expect(platformApi.stopMission).toHaveBeenCalledWith('MSN-0713-1050', 'Console2 路口摄像头人工停止'))
  })

  it('starts a selected replay source as a one-hour manual Mission', async () => {
    platformApi.missions.mockResolvedValueOnce([])
    open('/drones?tab=fleet')
    const selector = await screen.findByRole('combobox', { name: '小清河北路 × 水屯路回放源' })
    fireEvent.change(selector, { target: { value: 'SRC-LOCAL-XQH-PM' } })
    fireEvent.click(screen.getByRole('button', { name: '启动检测' }))
    await waitFor(() => expect(platformApi.createMission).toHaveBeenCalledWith(expect.objectContaining({
      drone_id: 'UAV-M300-03',
      source_profile_id: 'SRC-LOCAL-XQH-PM',
      inter_id: 'INT_camera_1',
      road_data_version: 'ROAD-LOCAL-INTER-XQH',
    })))
  })

  it('supports event deep links and persistent technical review', async () => {
    open('/events?event_id=UAV-EVT-20260713-001')
    expect(await screen.findByRole('dialog', { name: '机非冲突风险升高' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '技术确认' }))
    expect(await screen.findByText('AI 结果已技术确认')).toBeInTheDocument()
    expect(platformApi.reviewConflict).toHaveBeenCalledWith('370102000104', 'UAV-EVT-20260713-001', expect.objectContaining({ review_status: 'confirmed', expected_revision: 1 }))
  })

  it('links event filters across persisted event type, intersection, and search', async () => {
    open('/events')
    expect(await screen.findByText('UAV-EVT-20260713-004')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('事件路口'), { target: { value: '370102000104' } })
    expect(screen.getByText('UAV-EVT-20260713-001')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('事件搜索'), { target: { value: '不存在的事件' } })
    expect(screen.getByText('暂无符合条件的数据')).toBeInTheDocument()
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

  it('refreshes the survey revision after importing capture material', async () => {
    open('/survey/SVY-20260713-006/capture')
    expect(await screen.findByRole('heading', { name: '采集与质量预检' })).toBeInTheDocument()
    const taskReadsBeforeImport = platformApi.surveyTask.mock.calls.length
    fireEvent.click(screen.getByRole('button', { name: '导入 inter_xqh 真实材料' }))
    await waitFor(() => expect(platformApi.importSurveyBatch).toHaveBeenCalled())
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
    const generate = await screen.findByRole('button', { name: '生成成果包' })
    fireEvent.click(generate)
    expect(await screen.findByRole('button', { name: '打开真实 PDF' })).toBeInTheDocument()
    expect(screen.getByText(/aaaaaaaaaaaaaaaa/)).toBeInTheDocument()
  })

  it('persists enforcement clue technical confirmation through the I4 API', async () => {
    open('/enforcement?event_id=CLUE-I4-01')
    fireEvent.click(await screen.findByRole('button', { name: '确认 AI 线索' }))
    await waitFor(() => expect(platformApi.reviewEnforcementClue).toHaveBeenCalledWith('CLUE-I4-01', expect.objectContaining({ review_status: 'reviewed_confirmed', expected_revision: 1 })))
    expect(screen.getByText('工程契约样本')).toBeInTheDocument()
  })

  it('saves a zone candidate with PostgreSQL revision state', async () => {
    open('/enforcement/zones')
    fireEvent.click(await screen.findByRole('button', { name: '编辑候选' }))
    fireEvent.click(screen.getByRole('button', { name: '保存候选' }))
    await waitFor(() => expect(platformApi.updateEnforcementZone).toHaveBeenCalledWith('ZONE-I4-01', expect.objectContaining({ revision: 1, coordinate_system: 'ENU' })))
  })

  it('replays a dead letter with the original idempotency key', () => {
    open('/admin/integration')
    fireEvent.click(screen.getByText('DLQ-20260713-004'))
    fireEvent.click(screen.getByRole('button', { name: '按原幂等键重放' }))
    expect(screen.getByText('已按原幂等键发起重放')).toBeInTheDocument()
    expect(screen.getAllByText('MANUAL_REPLAY').length).toBeGreaterThan(0)
    expect(screen.getAllByText('重试中').length).toBeGreaterThan(0)
  })

  it('exposes the consolidated governance workspaces', () => {
    open('/admin/system?tab=identity')
    expect(screen.getByRole('heading', { name: '系统与身份' })).toBeInTheDocument()
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

  it('isolates unverified coordinates instead of plotting demo points', async () => {
    open('/')
    expect(await screen.findByText('暂无可上图的权威路口坐标')).toBeInTheDocument()
    expect(await screen.findByText(/1 个路口因 RoadContext、坐标参考或坐标值未验证被隔离/)).toBeInTheDocument()
    expect(screen.queryByText('演示地图')).not.toBeInTheDocument()
  })

  it('applies dashboard risk filters through the server query contract', async () => {
    open('/')
    await screen.findByText('暂无可上图的权威路口坐标')
    fireEvent.click(screen.getByRole('button', { name: '高风险' }))
    await waitFor(() => expect(platformApi.dashboardIntersections).toHaveBeenCalledWith({ risk: 'critical', limit: 500 }))
  })

  it('exposes loading, stale, and error states from the global exception entry', () => {
    open('/monitoring')
    fireEvent.click(screen.getByRole('button', { name: '异常状态' }))
    expect(screen.getByText('加载中')).toBeInTheDocument()
    expect(screen.getByText('已过期')).toBeInTheDocument()
    expect(screen.getByText('异常')).toBeInTheDocument()
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
