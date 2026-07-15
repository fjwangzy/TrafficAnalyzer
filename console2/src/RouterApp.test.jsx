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
      surveyTask: vi.fn().mockResolvedValue(task),
      surveyBatches: vi.fn().mockResolvedValue([{ id: 'BATCH-01', status: 'ready', telemetry_coverage: 0.94, quality_checks: { keyframes_extracted: 1, homography_available: 1 } }]),
      surveyFrames: vi.fn().mockResolvedValue([frame]),
      surveyMeasurements: vi.fn().mockResolvedValue([measurement]),
      surveyAction: vi.fn().mockImplementation((_id, body) => Promise.resolve({ ...task, status: body.action === 'submit_review' ? 'pending_review' : task.status, revision: 5, version: 'v5' })),
      surveyEvidence: vi.fn().mockResolvedValue(new Blob(['image'])),
      importSurveyBatch: vi.fn().mockResolvedValue({ id: 'BATCH-01', status: 'queued' }),
      surveyReports: vi.fn().mockResolvedValue([]),
      generateSurveyReport: vi.fn().mockResolvedValue(report),
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

  it('restores global scope and time window from the URL', () => {
    open('/?scope=priority&window=1h')
    expect(screen.getByRole('button', { name: /重点路口保障 · 8 个/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /最近 1 小时/ })).toBeInTheDocument()
  })

  it('restores intersection and drone selections from deep links', () => {
    open('/gis?intersection_id=370102000104')
    expect(screen.getByLabelText('路口')).toHaveValue('370102000104')
  })

  it('restores the fleet tab and selected drone from a deep link', () => {
    open('/drones?tab=fleet&drone_id=UAV-M300-03')
    expect(screen.getByRole('dialog', { name: 'UAV-M300-03' })).toBeInTheDocument()
  })

  it('supports event deep links and technical review', () => {
    open('/events?event_id=UAV-EVT-20260713-001')
    expect(screen.getByRole('dialog', { name: '机非冲突风险升高' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '技术确认' }))
    expect(screen.getByText('AI 结果已技术确认')).toBeInTheDocument()
    expect(screen.getByText('confirmed')).toBeInTheDocument()
  })

  it('links event filters across delivery, intersection, and search', () => {
    open('/events')
    fireEvent.change(screen.getByLabelText('投递状态'), { target: { value: 'delivery_failed' } })
    expect(screen.getByText('UAV-EVT-20260713-004')).toBeInTheDocument()
    expect(screen.queryByText('UAV-EVT-20260713-001')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('事件搜索'), { target: { value: '不存在的事件' } })
    expect(screen.getByText('暂无符合条件的数据')).toBeInTheDocument()
  })

  it('blocks a conflicting flight plan and keeps it as a draft', () => {
    open('/drones?tab=plans')
    fireEvent.click(screen.getByRole('button', { name: '新建飞行计划' }))
    expect(screen.getByText('计划冲突')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '校验并启用' }))
    expect(screen.getByText('发现同无人机时间冲突，计划保持草稿')).toBeInTheDocument()
    expect(screen.getByText('draft')).toBeInTheDocument()
  })

  it('updates Mission and Pipeline state after stopping a run', () => {
    open('/drones?tab=missions')
    fireEvent.click(screen.getByText('MSN-0713-1050'))
    fireEvent.click(screen.getByRole('button', { name: '停止 Mission' }))
    expect(screen.getByText('Mission 已停止并记录审计')).toBeInTheDocument()
    expect(screen.getByText('cancelled')).toBeInTheDocument()
    expect(screen.getAllByText('stopped').length).toBeGreaterThan(0)
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

  it('updates the enforcement clue list after technical confirmation', () => {
    open('/enforcement?event_id=CLUE-0713-022')
    fireEvent.click(screen.getByRole('button', { name: '确认 AI 线索' }))
    expect(screen.getByText('AI 线索已技术确认，等待主平台研判')).toBeInTheDocument()
    expect(screen.getAllByText('已确认').length).toBeGreaterThan(0)
  })

  it('saves a zone candidate with current detail state', () => {
    open('/enforcement/zones')
    fireEvent.click(screen.getByRole('button', { name: '编辑候选' }))
    fireEvent.click(screen.getByRole('button', { name: '保存候选' }))
    expect(screen.getByText('候选围栏已保存，未覆盖权威版本')).toBeInTheDocument()
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

  it('shows the explicit map service fallback', () => {
    open('/')
    fireEvent.click(screen.getByRole('button', { name: '演示底图降级' }))
    expect(screen.getByText('城市底图服务不可用')).toBeInTheDocument()
  })

  it('exposes loading, stale, and error states from the global exception entry', () => {
    open('/')
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
