import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, ArrowRight, CalendarBlank, Camera, Check, CheckCircle, Clock, Crosshair, Drone, FilePdf, FolderOpen, Gauge, HardDrive, MapPin, Pause, PencilSimple, Play, Plus, Repeat, ShieldCheck, Trash, UploadSimple, Warning, X } from '@phosphor-icons/react'
import { AppShell } from '../components/AppShell'
import { DataTable, DetailDrawer, FilterBar, InfoRow, KpiCard, PageHeader, Panel, QualityNotice, Segmented, StatusBadge, WorkflowSteps } from '../components/Common'
import { surveyTasks } from '../data/mockData'
import { useAppState } from '../state/AppState'
import { useAuth } from '../auth/AuthContext'
import { apiErrorMessage, platformApi } from '../lib/api'
import { detectorVideoStreamSrc } from '../lib/videoStream'

const missionTabs = [
  { value: 'fleet', label: '无人机' }, { value: 'sources', label: '数据源' }, { value: 'plans', label: '飞行计划' }, { value: 'missions', label: '执行记录' },
]

export function DronesPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const { dispatch } = useAppState()
  const { platformRole } = useAuth()
  const queryClient = useQueryClient()
  const params = new URLSearchParams(location.search)
  const requestedTab = params.get('tab') || 'fleet'
  const tab = requestedTab === 'drones' ? 'fleet' : requestedTab
  const initialDroneId = params.get('drone_id')
  const [selectedId, setSelectedId] = useState(initialDroneId)
  const [createMode, setCreateMode] = useState(null)
  const [actionError, setActionError] = useState('')
  const isAdmin = platformRole === 'admin'
  const dronesQuery = useQuery({ queryKey: ['s9-drones'], queryFn: platformApi.drones, refetchInterval: 10_000 })
  const sourcesQuery = useQuery({ queryKey: ['s9-sources'], queryFn: platformApi.sources, refetchInterval: 30_000 })
  const plansQuery = useQuery({ queryKey: ['s9-flight-plans'], queryFn: platformApi.flightPlans, refetchInterval: 10_000 })
  const missionsQuery = useQuery({ queryKey: ['s9-missions'], queryFn: () => platformApi.missions(), refetchInterval: 2_000 })
  const sourceResultsQuery = useQuery({
    queryKey: ['s9-source-results', selectedId],
    queryFn: () => platformApi.sourceResults(selectedId),
    enabled: tab === 'sources' && Boolean(selectedId),
  })
  const drones = dronesQuery.data || []
  const sources = sourcesQuery.data || []
  const plans = plansQuery.data || []
  const missions = missionsQuery.data || []
  const refresh = () => queryClient.invalidateQueries({ predicate: (query) => String(query.queryKey[0]).startsWith('s9-') })
  const notify = (text, tone = 'success') => dispatch({ type: 'TOAST', value: { tone, text } })
  const actionMutation = useMutation({
    mutationFn: ({ kind, record }) => {
      if (kind === 'validate') return platformApi.validateSource(record.drone_id, record.profile_id)
      if (kind === 'enable' || kind === 'pause' || kind === 'retire') return platformApi.flightPlanAction(record.id, kind, record.revision)
      if (kind === 'stop') return platformApi.stopMission(record.id, 'Console2 人工停止')
      if (kind === 'retry') return platformApi.retryMission(record.id, 'Console2 人工重试')
      if (kind === 'toggle-drone') return platformApi.updateDrone(record.id, { revision: record.revision, enabled: !record.enabled })
      throw new Error('未知操作')
    },
    onSuccess: (_, variables) => { setActionError(''); refresh(); setSelectedId(null); notify(`${variables.kind} 操作已持久化`) },
    onError: (error) => setActionError(apiErrorMessage(error)),
  })
  const createMutation = useMutation({
    mutationFn: ({ mode, body }) => {
      if (mode === 'fleet') return platformApi.createDrone(body)
      if (mode === 'sources') return platformApi.createSource(body.drone_id, body.payload)
      if (mode === 'plans') return platformApi.createFlightPlan(body)
      return platformApi.createMission(body)
    },
    onSuccess: () => { setCreateMode(null); setActionError(''); refresh(); notify('配置已写入 road9') },
    onError: (error) => setActionError(apiErrorMessage(error)),
  })
  const cameraMutation = useMutation({
    mutationFn: ({ kind, drone, sourceProfileId, mission }) => {
      if (kind === 'stop') return platformApi.stopMission(mission.id, 'Console2 路口摄像头人工停止')
      return platformApi.createMission({
        name: `实时检测 · ${drone.intersection_name || drone.name}`,
        drone_id: drone.id,
        source_profile_id: sourceProfileId,
        inter_id: drone.default_inter_id,
        road_data_version: drone.default_road_data_version,
        scheduled_end_at: new Date(Date.now() + 3_600_000).toISOString(),
      })
    },
    onSuccess: (_, variables) => { setActionError(''); refresh(); notify(variables.kind === 'stop' ? '摄像头已停止并保留 Mission 记录' : '检测 Pipeline 已启动') },
    onError: (error) => setActionError(apiErrorMessage(error)),
  })
  const rows = useMemo(() => {
    if (tab === 'fleet') return drones.map((drone) => {
      const current = missions.find((mission) => mission.drone_id === drone.id && ['starting', 'running'].includes(mission.status))
      return { ...drone, battery: drone.battery_pct, intersection: drone.current_intersection_id || drone.default_inter_id || '—', source: drone.default_video_source_id || '—', mission: current?.id, telemetryAt: drone.last_telemetry?.timestamp ? new Date(drone.last_telemetry.timestamp * 1000).toLocaleTimeString() : '—' }
    })
    if (tab === 'sources') return sources.map((source) => ({ ...source, id: source.profile_id, status: source.validation_status, kind: `${source.video.source_type.toUpperCase()} + ${source.telemetry.source_type.toUpperCase()}`, drone: source.drone_id, checkedAt: formatDate(source.validated_at), detail: source.validation_error_code || `${source.video.location_hint} · ${source.telemetry.location_hint}` }))
    if (tab === 'plans') return plans.map((plan) => ({ ...plan, status: plan.state, drone: plan.drone_id, type: plan.schedule.type, scheduleLabel: scheduleLabel(plan.schedule, plan.timezone), next: '通过窗口预览查询' }))
    return missions.map((mission) => ({ ...mission, plan: mission.flight_plan_id || mission.trigger_type, drone: mission.drone_id, scheduled: formatDate(mission.scheduled_start_at), actual: formatDate(mission.actual_start_at), deviation: startDeviation(mission), pipelineStatus: mission.pipeline?.observed_status || '—', reason: mission.reason_code || mission.error_message || '—' }))
  }, [tab, drones, sources, plans, missions])
  const selectedRecord = rows.find((item) => item.id === selectedId) || null
  const changeTab = (value) => {
    const next = new URLSearchParams(location.search)
    next.set('tab', value)
    if (value !== 'fleet') next.delete('drone_id')
    setSelectedId(null)
    navigate(`/drones?${next.toString()}`)
  }
  const selectRecord = (row) => {
    setSelectedId(row.id)
    if (tab !== 'fleet') return
    const next = new URLSearchParams(location.search)
    next.set('tab', 'fleet')
    next.set('drone_id', row.id)
    navigate(`/drones?${next.toString()}`, { replace: true })
  }
  const closeRecord = () => {
    setSelectedId(null)
    if (tab !== 'fleet') return
    const next = new URLSearchParams(location.search)
    next.delete('drone_id')
    navigate(`/drones?${next.toString()}`, { replace: true })
  }
  const startCreate = () => {
    if (!isAdmin) return setActionError('当前角色只有只读权限')
    setCreateMode(tab)
  }
  const loading = [dronesQuery, sourcesQuery, plansQuery, missionsQuery].some((query) => query.isLoading)
  const queryError = [dronesQuery, sourcesQuery, plansQuery, missionsQuery].find((query) => query.error)?.error
  return <AppShell pageTitle='无人机与飞行计划'>
    <PageHeader eyebrow='S9 · 无人机对接' title='无人机与飞行计划' description='管理设备、RTSP+MQTT/MP4+SRT或DJI JSON数据源、单次/周期计划和 Mission 执行审计；这里只启停 AI Pipeline，不下发飞控。' meta='road9 持久化 · 调度扫描 5s' actions={<button className='primary-button' disabled={!isAdmin} onClick={startCreate}><Plus size={15} /> {tab === 'plans' ? '新建飞行计划' : tab === 'sources' ? '登记数据源' : tab === 'missions' ? '新建手动 Mission' : '登记无人机'}</button>} />
    <div className='page-tabs'>{missionTabs.map((item) => <button key={item.value} className={tab === item.value ? 'active' : ''} onClick={() => changeTab(item.value)}>{item.label}<span>{item.value === 'fleet' ? drones.length : item.value === 'sources' ? sources.length : item.value === 'plans' ? plans.length : missions.length}</span></button>)}</div>
    {loading && <QualityNotice title='正在读取 road9'>无人机、数据源、计划和 Mission 正在同步。</QualityNotice>}
    {(queryError || actionError) && <QualityNotice tone='danger' title='数据不可用'>{actionError || apiErrorMessage(queryError)}</QualityNotice>}
    {tab === 'fleet' && <><div className='kpi-grid four'><KpiCard icon={Drone} label='登记无人机' value={drones.length} unit='架' detail={`${drones.filter((item) => item.enabled).length} 已启用`} /><KpiCard icon={Play} label='执行任务' value={missions.filter((item) => item.status === 'running').length} unit='个' tone='cyan' /><KpiCard icon={Gauge} label='遥测有效' value={drones.filter((item) => item.telemetry_status === 'fresh').length} unit='架' detail='由遥测新鲜度派生' tone='amber' /><KpiCard icon={Warning} label='保障缺口' value={drones.filter((item) => !item.enabled || item.status === 'offline').length} unit='项' tone='red' /></div><ReplayCameraControls drones={drones} sources={sources} missions={missions} isAdmin={isAdmin} pending={cameraMutation.isPending} onAction={(payload) => cameraMutation.mutate(payload)} /><Panel title='无人机档案' subtitle='静态设备记录不等于在线；在线状态由遥测新鲜度共同判定'><DataTable onRowClick={selectRecord} rows={rows} columns={[{ key: 'status', label: '状态', render: (value) => <StatusBadge value={value} /> }, { key: 'id', label: '无人机 ID' }, { key: 'battery', label: '电量', render: (value) => value == null ? '—' : `${value}%` }, { key: 'intersection', label: '当前路口' }, { key: 'source', label: '默认源' }, { key: 'mission', label: '当前 Mission', render: (value) => value || '—' }, { key: 'telemetryAt', label: '最后遥测' }]} /></Panel></>}
    {tab === 'sources' && <><QualityNotice tone='info' title='敏感信息已脱敏'>页面只展示文件名或主机摘要和 secret reference 是否存在，不返回完整路径或凭据。</QualityNotice><Panel title='数据源' subtitle='实时源和本地回放源分别校验'><DataTable rows={rows} onRowClick={selectRecord} columns={[{ key: 'status', label: '校验状态', render: (value) => <StatusBadge value={value} /> }, { key: 'id', label: '数据源 ID' }, { key: 'kind', label: '类型' }, { key: 'drone', label: '配对无人机' }, { key: 'enabled', label: '启用', render: (value) => value ? '是' : '否' }, { key: 'checkedAt', label: '最近验证' }, { key: 'detail', label: '验证摘要' }]} /></Panel></>}
    {tab === 'plans' && <><FilterBar result={`${plans.length} 个持久化计划`}><label>状态<select><option>全部</option><option>已启用</option><option>草稿</option></select></label></FilterBar><Panel title='飞行计划' subtitle='启用前检查数据源、RoadContext、跨午夜、例外日期和同无人机冲突'><DataTable rows={rows} onRowClick={selectRecord} columns={[{ key: 'status', label: '状态', render: (value) => <StatusBadge value={value} /> }, { key: 'name', label: '计划名称' }, { key: 'drone', label: '无人机' }, { key: 'type', label: '类型' }, { key: 'scheduleLabel', label: '时间窗口' }, { key: 'timezone', label: '业务时区' }, { key: 'revision', label: 'Revision' }]} /></Panel></>}
    {tab === 'missions' && <><div className='kpi-grid four'><KpiCard icon={Play} label='运行中' value={missions.filter((item) => item.status === 'running').length} unit='个' tone='cyan' /><KpiCard icon={CheckCircle} label='已完成' value={missions.filter((item) => item.status === 'completed').length} unit='个' tone='green' /><KpiCard icon={Warning} label='失败' value={missions.filter((item) => item.status === 'failed').length} unit='个' tone='red' /><KpiCard icon={Clock} label='错过窗口' value={missions.filter((item) => item.reason_code === 'window_missed').length} unit='个' detail='不自动补跑' /></div><Panel title='Mission 执行记录' subtitle='Mission 业务状态与 Pipeline 进程状态分别表达'><DataTable rows={rows} onRowClick={selectRecord} columns={[{ key: 'status', label: 'Mission', render: (value) => <StatusBadge value={value} /> }, { key: 'id', label: 'Mission ID' }, { key: 'plan', label: '计划' }, { key: 'drone', label: '无人机' }, { key: 'scheduled', label: '计划时间' }, { key: 'actual', label: '实际启动' }, { key: 'deviation', label: '偏差' }, { key: 'pipelineStatus', label: 'Pipeline', render: (value) => value === '—' ? '—' : <StatusBadge value={value} /> }, { key: 'reason', label: '完成/失败原因' }]} /></Panel></>}
    {selectedRecord && <DetailDrawer title={selectedRecord.name || selectedRecord.id} subtitle={tab === 'plans' ? 'FlightPlan 详情' : tab === 'missions' ? 'Mission 审计详情' : tab === 'sources' ? '数据源验证详情' : '无人机详情'} onClose={closeRecord} footer={<RecordActions tab={tab} record={selectedRecord} isAdmin={isAdmin} pending={actionMutation.isPending} onAction={(kind) => actionMutation.mutate({ kind, record: selectedRecord })} onClose={closeRecord} />}>
      {Object.entries(selectedRecord).filter(([, value]) => typeof value !== 'object' && typeof value !== 'boolean').map(([key, value]) => <InfoRow key={key} label={key} value={String(value ?? '—')} />)}
      {selectedRecord.kind && <QualityNotice tone={selectedRecord.status === 'valid' ? 'success' : 'warning'} title='最近验证结果'>{selectedRecord.detail}；敏感连接信息未写入页面、日志或审计详情。</QualityNotice>}
      {tab === 'sources' && <SourceResultsPanel result={sourceResultsQuery.data} loading={sourceResultsQuery.isLoading} error={sourceResultsQuery.error} navigate={navigate} />}
      {tab === 'missions' && <Panel title='执行时间线'><div className='state-timeline'>{['计划窗口到期', `实际启动 · ${selectedRecord.actual}`, `Pipeline · ${selectedRecord.pipelineStatus}`, `Mission · ${selectedRecord.status}`, selectedRecord.reason !== '—' ? `原因 · ${selectedRecord.reason}` : '持续运行中'].map((item, index) => <div key={item} className={index === 4 ? 'current' : ''}><i /><span>{item}</span></div>)}</div></Panel>}
    </DetailDrawer>}
    {createMode && <S9CreateDrawer mode={createMode} drones={drones} sources={sources} onClose={() => setCreateMode(null)} pending={createMutation.isPending} onSubmit={(body) => createMutation.mutate({ mode: createMode, body })} />}
  </AppShell>
}

function SourceResultsPanel({ result, loading, error, navigate }) {
  if (loading) return <QualityNotice title='正在关联成果'>从 road9 汇总 Mission、态势、研判、测绘和标注记录。</QualityNotice>
  if (error) return <QualityNotice tone='danger' title='关联成果不可用'>{apiErrorMessage(error)}</QualityNotice>
  if (!result) return null
  const links = [
    ['态势历史', result.links.situation, result.counts.traffic_metrics],
    ['监控画面', result.links.monitoring, result.missions.length],
    ['轨迹研判', result.links.insight, `${result.counts.tracks}/${result.counts.conflicts}`],
    ['测绘关键帧', result.links.survey, result.counts.survey_frames],
    ['场景标注', result.links.scene_annotation, result.counts.scene_annotations],
    ['车道标注', result.links.lane_annotation, result.counts.lane_annotations],
  ]
  return <Panel title='关联成果' subtitle={`${result.telemetry_type} · ${result.survey_tasks.length} 个测绘批次 · ${result.counts.survey_reports} 份成果包`}><div className='source-result-links'>{links.map(([label, href, count]) => <button key={label} className='source-result-link' onClick={() => navigate(href)}><span>{label}</span><strong>{count}</strong></button>)}</div></Panel>
}

function formatDate(value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}

function startDeviation(mission) {
  if (!mission.actual_start_at || !mission.scheduled_start_at) return '—'
  const seconds = Math.round((new Date(mission.actual_start_at) - new Date(mission.scheduled_start_at)) / 1000)
  return `${seconds >= 0 ? '+' : ''}${seconds}s`
}

function scheduleLabel(schedule = {}, timezone) {
  if (schedule.type === 'once') return `${formatDate(schedule.start_at)} — ${formatDate(schedule.end_at)}`
  return `周 ${schedule.weekdays?.join(',')} · ${schedule.local_start}–${schedule.local_end} · ${timezone}`
}

function ReplayCameraControls({ drones, sources, missions, isAdmin, pending, onAction }) {
  const [selection, setSelection] = useState({})
  const cameras = drones.filter((drone) => drone.default_inter_id && sources.some((source) => source.drone_id === drone.id && source.mode === 'local'))
  if (!cameras.length) return <QualityNotice tone='info' title='暂无回放摄像头'>登记本地 MP4 + SRT/JSON 数据源后，可在这里按路口独立启动检测。</QualityNotice>
  return <Panel title='路口实时检测控制' subtitle='每个路口同一时间只运行一个 Mission；不同路口可独立启停'>
    <div className='replay-camera-grid'>
      {cameras.map((drone) => {
        const options = sources.filter((source) => source.drone_id === drone.id && source.mode === 'local' && source.enabled)
        const defaultSource = options.find((source) => source.video.id === drone.default_video_source_id) || options[0]
        const sourceProfileId = selection[drone.id] || defaultSource?.profile_id || ''
        const mission = missions.find((item) => item.drone_id === drone.id && ['pending', 'starting', 'running'].includes(item.status))
        const cameraId = mission?.pipeline?.camera_id
        const videoStreamUrl = detectorVideoStreamSrc(mission?.pipeline)
        const ready = mission?.status === 'running' && mission?.pipeline?.observed_status === 'running' && cameraId != null && Boolean(videoStreamUrl)
        return <article className='replay-camera-card' key={drone.id}>
          <header><div><Camera size={17} /><span><strong>{drone.intersection_name || drone.name}</strong><small>{drone.default_inter_id}</small></span></div><StatusBadge value={mission?.status || 'standby'} /></header>
          <div className='replay-camera-feed'>
            {ready
              ? <img src={videoStreamUrl} alt={`${drone.intersection_name || drone.name} 实时检测画面`} />
              : <div className='replay-camera-empty'><Camera size={27} /><strong>{mission ? 'Pipeline 启动中' : '摄像头待命'}</strong><span>{mission ? (mission.status === 'running' ? '正在等待检测器登记直连视频地址' : '正在等待首个 MJPEG 检测帧') : '选择回放源后启动检测'}</span></div>}
            <div className='replay-camera-overlay'>
              <label><span>回放源</span><select aria-label={`${drone.intersection_name || drone.name}回放源`} value={sourceProfileId} disabled={Boolean(mission)} onChange={(event) => setSelection((current) => ({ ...current, [drone.id]: event.target.value }))}>{options.map((source) => <option key={source.profile_id} value={source.profile_id}>{source.display_name || source.profile_id}</option>)}</select></label>
              <span className='replay-camera-quality'>{drone.road_context_quality === 'unverified' ? '道路未标定 · 仅检测/跟踪/遥测' : drone.default_road_data_version}</span>
              {mission
                ? <button className='danger-button replay-camera-action' disabled={!isAdmin || pending} onClick={() => onAction({ kind: 'stop', drone, mission })}><Pause size={14} />停止</button>
                : <button className='primary-button replay-camera-action' disabled={!isAdmin || pending || !sourceProfileId || !drone.default_road_data_version} onClick={() => onAction({ kind: 'start', drone, sourceProfileId })}><Play size={14} />启动检测</button>}
            </div>
          </div>
        </article>
      })}
    </div>
  </Panel>
}

function RecordActions({ tab, record, isAdmin, pending, onAction, onClose }) {
  if (!isAdmin) return <button className='secondary-button' onClick={onClose}>关闭</button>
  if (tab === 'fleet') return <button className='secondary-button' disabled={pending} onClick={() => onAction('toggle-drone')}>{record.enabled ? '停用无人机' : '启用无人机'}</button>
  if (tab === 'sources') return <button className='primary-button' disabled={pending} onClick={() => onAction('validate')}>重新验证</button>
  if (tab === 'plans') return <>{record.state === 'enabled' ? <button className='secondary-button' disabled={pending} onClick={() => onAction('pause')}>暂停</button> : record.state !== 'retired' && <button className='primary-button' disabled={pending} onClick={() => onAction('enable')}>校验并启用</button>} {record.state !== 'retired' && <button className='danger-button' disabled={pending} onClick={() => onAction('retire')}>退役</button>}</>
  if (record.status === 'running' || record.status === 'starting' || record.status === 'pending') return <button className='danger-button' disabled={pending} onClick={() => onAction('stop')}>停止 Mission</button>
  if (record.status === 'failed') return <button className='primary-button' disabled={pending} onClick={() => onAction('retry')}><Repeat size={15} /> 新建重试</button>
  return <button className='secondary-button' onClick={onClose}>关闭</button>
}

function S9CreateDrawer({ mode, drones, sources, onClose, onSubmit, pending }) {
  const firstDrone = drones[0]?.id || ''
  const firstSource = sources.find((item) => item.drone_id === firstDrone)?.profile_id || ''
  const initialStart = new Date(Date.now() + 60_000)
  const initialEnd = new Date(Date.now() + 3_660_000)
  const localInput = (date) => new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
  const [form, setForm] = useState({
    drone_id: firstDrone, source_profile_id: firstSource, inter_id: 'INT_camera_1',
    road_data_version: 'ROAD-LOCAL-INTER-XQH', name: '', model: '',
    video_src: 'test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4',
    telemetry_file_path: 'test_videos/inter_xqh/telemetry.srt',
    start_at: localInput(initialStart), end_at: localInput(initialEnd),
  })
  const set = (key, value) => setForm((current) => ({ ...current, [key]: value }))
  const submit = () => {
    if (mode === 'fleet') return onSubmit({ id: form.drone_id, name: form.name || form.drone_id, model: form.model || null, enabled: true, default_inter_id: form.inter_id })
    if (mode === 'sources') return onSubmit({ drone_id: form.drone_id, payload: { mode: 'local', video: { source_type: 'mp4', location: form.video_src }, telemetry: { source_type: /\.(json|txt)$/i.test(form.telemetry_file_path) ? 'file' : 'srt', location: form.telemetry_file_path }, enabled: true, set_default: true } })
    if (mode === 'plans') return onSubmit({ name: form.name || '新建飞行计划', drone_id: form.drone_id, source_profile_id: form.source_profile_id, inter_id: form.inter_id, road_data_version: form.road_data_version, timezone: 'Asia/Shanghai', schedule: { type: 'once', start_at: new Date(form.start_at).toISOString(), end_at: new Date(form.end_at).toISOString() } })
    return onSubmit({ name: form.name || '手动 Mission', drone_id: form.drone_id, source_profile_id: form.source_profile_id, inter_id: form.inter_id, road_data_version: form.road_data_version })
  }
  return <DetailDrawer title={mode === 'fleet' ? '登记无人机' : mode === 'sources' ? '登记本地 MP4 + SRT/JSON 数据源' : mode === 'plans' ? '新建单次飞行计划' : '新建手动 Mission'} subtitle='S9 真实配置' onClose={onClose} footer={<><button className='secondary-button' onClick={onClose}>取消</button><button className='primary-button' disabled={pending} onClick={submit}>保存到 road9</button></>}>
    <label>无人机 ID<input value={form.drone_id} onChange={(event) => { set('drone_id', event.target.value); const matched = sources.find((item) => item.drone_id === event.target.value); if (matched) set('source_profile_id', matched.profile_id) }} /></label>
    <label>名称<input value={form.name} onChange={(event) => set('name', event.target.value)} /></label>
    {mode === 'fleet' && <label>型号<input value={form.model || ''} onChange={(event) => set('model', event.target.value)} /></label>}
    {mode === 'sources' && <><label>服务器 MP4 路径<input value={form.video_src} onChange={(event) => set('video_src', event.target.value)} /></label><label>DJI SRT 或 Cloud JSON 路径<input value={form.telemetry_file_path} onChange={(event) => set('telemetry_file_path', event.target.value)} /></label></>}
    {(mode === 'plans' || mode === 'missions') && <><label>数据源<select value={form.source_profile_id} onChange={(event) => set('source_profile_id', event.target.value)}>{sources.filter((item) => !form.drone_id || item.drone_id === form.drone_id).map((item) => <option key={item.profile_id} value={item.profile_id}>{item.profile_id}</option>)}</select></label><label>权威路口 ID<input value={form.inter_id} onChange={(event) => set('inter_id', event.target.value)} /></label><label>路网版本<input value={form.road_data_version} onChange={(event) => set('road_data_version', event.target.value)} /></label></>}
    {mode === 'plans' && <><label>开始时间<input type='datetime-local' value={form.start_at} onChange={(event) => set('start_at', event.target.value)} /></label><label>结束时间<input type='datetime-local' value={form.end_at} onChange={(event) => set('end_at', event.target.value)} /></label></>}
    <QualityNotice tone='info' title='边界说明'>本页面只调度 AI Pipeline，不下发航线、起降、返航或云台控制。</QualityNotice>
  </DetailDrawer>
}

const surveySteps = ['任务核验', '采集质检', '点线面量算', '技术复核', '报告交付']

export function SurveyListPage() {
  const navigate = useNavigate()
  const { state, dispatch } = useAppState()
  const createTask = () => {
    const task = { id: 'SVY-20260713-NEW', title: '新建事故现场测绘', owner: '事故处理一组', status: 'collecting', location: '位置待任务核验', quality: 'unverified', version: 'v1', delivery: '—', updatedAt: '刚刚' }
    dispatch({ type: 'CREATE_SURVEY', value: task })
    navigate(`/survey/${task.id}/capture?task_id=${task.id}`)
  }
  return <AppShell pageTitle='测绘任务'>
    <PageHeader eyebrow='S3 · 事故测绘' title='事故测绘任务' description='从作业前置核验到报告交付完整留痕；系统输出用于辅助量算和技术复核，不替代法定事故认定。' meta={`${state.surveys.length} 个任务 · 1 个待技术复核`} actions={<button className='primary-button' onClick={createTask}><Plus size={15} /> 创建测绘任务</button>} />
    <div className='kpi-grid four'><KpiCard icon={FolderOpen} label='进行中任务' value='2' unit='个' detail='1 量算 · 1 待复核' /><KpiCard icon={Camera} label='采集批次' value='8' unit='组' detail='6 有效 · 2 降级' tone='cyan' /><KpiCard icon={ShieldCheck} label='成果质量' value='1' unit='待确认' detail='阈值未冻结' tone='amber' /><KpiCard icon={FilePdf} label='今日交付' value='3' unit='份' detail='主平台已接收' tone='green' /></div>
    <FilterBar result={`${state.surveys.length} 个任务`}><label>任务状态<select><option>全部状态</option><option>量算中</option><option>待技术复核</option></select></label><label>负责组<select><option>全部</option><option>事故处理一组</option></select></label><label>时间<select><option>今天</option><option>近 7 日</option></select></label></FilterBar>
    <Panel title='任务列表' subtitle='事故民警仅可访问分配给自己的任务'><DataTable onRowClick={(row) => navigate(`/survey/${row.id}/capture?task_id=${row.id}`)} rows={state.surveys} columns={[{ key: 'status', label: '任务状态', render: (value) => <StatusBadge value={value} /> }, { key: 'title', label: '任务' }, { key: 'id', label: '任务 ID' }, { key: 'location', label: '位置' }, { key: 'owner', label: '负责组' }, { key: 'quality', label: '质量', render: (value) => <StatusBadge value={value} /> }, { key: 'version', label: '成果版本' }, { key: 'delivery', label: '投递', render: (value) => value === '—' ? '—' : <StatusBadge value={value} /> }, { key: 'updatedAt', label: '最近更新' }]} /></Panel>
  </AppShell>
}

function useSurveyTask() {
  const { id } = useParams()
  const location = useLocation()
  const { state } = useAppState()
  const taskId = id || new URLSearchParams(location.search).get('task_id')
  return state.surveys.find((item) => item.id === taskId) || state.surveys[0]
}

function SurveyShell({ step, title, description, children, actions }) {
  const task = useSurveyTask()
  const navigate = useNavigate()
  return <AppShell pageTitle={title}><button className='back-link' onClick={() => navigate('/survey')}><ArrowLeft size={15} /> 返回任务列表</button><PageHeader eyebrow={`${task.id} · ${task.version}`} title={title} description={description} meta={`${task.location} · ${task.owner}`} actions={actions} /><WorkflowSteps steps={surveySteps} active={step} />{children}</AppShell>
}

export function SurveyCapturePage() {
  const task = useSurveyTask()
  const navigate = useNavigate()
  const { dispatch } = useAppState()
  const [batch, setBatch] = useState('BATCH-03')
  const [playing, setPlaying] = useState(false)
  return <SurveyShell step={1} title='采集与质量预检' description='选择可追溯采集批次，核验视频、遥测、姿态、标定、覆盖和存储余量；未知阈值只显示观测值。' actions={<button className='primary-button' onClick={() => { dispatch({ type: 'SURVEY_ACTION', id: task.id, value: 'measuring' }); navigate(`/survey/${task.id}/measure?task_id=${task.id}`) }}>选择批次并进入量算 <ArrowRight size={15} /></button>}>
    <div className='survey-capture-layout'><Panel className='capture-stage' title='原始采集视频' subtitle={`${batch} · 原始帧时间 10:18:42.208`}><div className='video-stage'><img src='/assets/uav-intersection-night.png' alt='事故测绘采集视频关键帧' /><button className='center-play' onClick={() => setPlaying(!playing)}>{playing ? <Pause size={22} weight='fill' /> : <Play size={22} weight='fill' />}</button><div className='coverage-mask'>覆盖缺口 6.2%</div></div><div className='frame-strip'>{[1, 2, 3, 4, 5, 6].map((item) => <button key={item} className={item === 3 ? 'active' : ''}><img src='/assets/uav-intersection-night.png' alt={`关键帧 ${item}`} /><span>#{18200 + item * 12}</span></button>)}</div></Panel><div className='capture-side'><Panel title='采集批次'>{['BATCH-01', 'BATCH-02', 'BATCH-03'].map((item, index) => <button className={`batch-row ${batch === item ? 'active' : ''}`} key={item} onClick={() => setBatch(item)}><span><Camera size={16} />{item}</span><StatusBadge value={index === 1 ? 'degraded' : 'good'} /></button>)}</Panel><Panel title='实时质量门禁'><InfoRow label='RTK / 定位' value='FIXED · 0.08m' badge='good' /><InfoRow label='姿态稳定性' value='roll ±0.6°' badge='good' /><InfoRow label='清晰度 / 曝光' value='0.91 / 0.86' badge='good' /><InfoRow label='覆盖度' value='93.8%' badge='unverified' /><InfoRow label='标定版本' value='CAL-XQH-H112-P89-v4' /><InfoRow label='存储余量' value='268 GB' badge='good' /></Panel><QualityNotice tone='warning' title='候选质量口径'>覆盖阈值与成果误差尚未冻结，当前批次标记为 unverified，不显示“验收通过”。</QualityNotice></div></div>
  </SurveyShell>
}

export function SurveyMeasurePage() {
  const task = useSurveyTask()
  const navigate = useNavigate()
  const { dispatch } = useAppState()
  const [tool, setTool] = useState('point')
  const initialObjects = [{ id: 'M-01', type: '车辆轮廓', value: '4.72 × 1.86m', source: 'manual' }, { id: 'M-02', type: '刹车痕迹', value: '12.48m', source: 'auto+edited' }, { id: 'M-03', type: '散落物区域', value: '8.62m²', source: 'manual' }]
  const [history, setHistory] = useState([initialObjects])
  const [historyIndex, setHistoryIndex] = useState(0)
  const objects = history[historyIndex]
  const addObject = () => {
    const nextObjects = [...objects, { id: `M-0${objects.length + 1}`, type: '人工标点', value: '待量算', source: 'manual' }]
    const nextHistory = [...history.slice(0, historyIndex + 1), nextObjects]
    setHistory(nextHistory)
    setHistoryIndex(nextHistory.length - 1)
  }
  return <SurveyShell step={2} title='点线面量算' description='自动候选与人工结果分开标识，所有几何保留来源帧、单位、质量、控制点和版本。' actions={<button className='primary-button' onClick={() => { dispatch({ type: 'SURVEY_ACTION', id: task.id, value: 'pending_review' }); navigate(`/survey/${task.id}/review?task_id=${task.id}`) }}>提交技术复核 <ArrowRight size={15} /></button>}>
    <div className='measure-toolbar'><Segmented value={tool} onChange={setTool} options={[{ value: 'point', label: '标点' }, { value: 'line', label: '线/折线' }, { value: 'area', label: '面积' }, { value: 'object', label: '对象' }]} /><button className='secondary-button' disabled={historyIndex === 0} onClick={() => setHistoryIndex((index) => Math.max(0, index - 1))}><ArrowLeft size={14} /> 撤销</button><button className='secondary-button' disabled={historyIndex === history.length - 1} onClick={() => setHistoryIndex((index) => Math.min(history.length - 1, index + 1))}><ArrowRight size={14} /> 重做</button><span>吸附：控制点 / 道路边界</span></div>
    <div className='measure-layout'><Panel className='measure-stage' title='正射量算画布' subtitle='BATCH-03 · Frame #18236 · ENU 米制平面'><div className='measure-canvas'><img src='/assets/bev-intersection-night.png' alt='事故现场正射测绘底图' /><div className='measurement measurement-line'><i /><i /><strong>12.48 m</strong></div><div className='measurement measurement-area'><span /><strong>8.62 m² · 周长 12.9m</strong></div><div className='measurement measurement-object'><span /><strong>车辆 A · 4.72 × 1.86m</strong></div></div></Panel><div className='measure-side'><Panel title='量算对象' action={<button className='text-button' onClick={addObject}>+ 新增</button>}>{objects.map((item) => <button className='object-row' key={item.id}><span>{item.id}</span><div><strong>{item.type}</strong><small>{item.value}</small></div><StatusBadge value={item.source === 'manual' ? 'info' : 'candidate'}>{item.source}</StatusBadge></button>)}</Panel><Panel title='当前对象质量'><InfoRow label='来源帧' value='#18236' /><InfoRow label='坐标链' value='px → ENU → GCJ02' /><InfoRow label='控制点残差' value='0.84m' badge='good' /><InfoRow label='水平误差估计' value='1.72m' badge='unverified' /><InfoRow label='算法版本' value='survey-measure-r5' /></Panel></div></div>
  </SurveyShell>
}

export function SurveyReviewPage() {
  const task = useSurveyTask()
  const navigate = useNavigate()
  const { dispatch } = useAppState()
  const [reasonOpen, setReasonOpen] = useState(false)
  return <SurveyShell step={3} title='技术复核' description='逐项对照原帧、示意图、控制点、误差和编辑历史；通过只表示技术复核，不等同法定事故认定。' actions={<><button className='danger-button' onClick={() => setReasonOpen(true)}><X size={15} /> 退回修订/补拍</button><button className='primary-button' onClick={() => { dispatch({ type: 'SURVEY_ACTION', id: task.id, value: 'technical_reviewed' }); navigate(`/survey/${task.id}/report?task_id=${task.id}`) }}><Check size={15} /> 技术复核通过</button></>}>
    <div className='review-layout'><Panel title='原始帧与示意图对照'><div className='compare-panes'><div><span>原始帧 #18236</span><img src='/assets/uav-intersection-night.png' alt='事故测绘原始帧' /></div><div><span>量算示意 · v3</span><img src='/assets/bev-intersection-night.png' alt='事故测绘量算示意图' /></div></div></Panel><div className='review-side'><Panel title='复核清单'>{['任务与位置一致', '原始材料引用完整', '控制点与坐标链可追溯', '点线面单位正确', '人工编辑历史完整', '误差阈值待冻结已标识'].map((item) => <label className='check-row' key={item}><input type='checkbox' defaultChecked /><CheckCircle size={16} weight='fill' />{item}</label>)}</Panel><Panel title='版本变化'><InfoRow label='当前版本' value='v3' /><InfoRow label='上一版本' value='v2 · returned' /><InfoRow label='新增对象' value='散落物区域 M-03' /><InfoRow label='修改对象' value='刹车痕迹 +0.42m' /><InfoRow label='操作者' value='事故处理一组 · 王海' /></Panel></div></div>
    {reasonOpen && <div className='modal-backdrop'><div className='modal-card'><header><strong>退回测绘成果</strong><button onClick={() => setReasonOpen(false)}><X size={18} /></button></header><label>返工类型<select><option>补拍</option><option>修订量算</option></select></label><label>退回原因<textarea defaultValue='覆盖缺口影响散落物区域，请补拍南侧区域并保留当前版本。' /></label><footer><button className='secondary-button' onClick={() => setReasonOpen(false)}>取消</button><button className='danger-button' onClick={() => { dispatch({ type: 'SURVEY_ACTION', id: task.id, value: 'returned' }); setReasonOpen(false) }}>确认退回</button></footer></div></div>}
  </SurveyShell>
}

export function SurveyReportPage() {
  const task = useSurveyTask()
  const { dispatch } = useAppState()
  return <SurveyShell step={4} title='测绘报告与交付' description='预览报告、核验完整性和版本差异，再以幂等键投递主平台；未过门禁时不得标记可交付。' actions={<button className='primary-button' onClick={() => dispatch({ type: 'TOAST', value: { tone: 'success', text: '测绘报告演示文件已生成' } })}><FilePdf size={15} /> 导出报告</button>}>
    <div className='report-preview-layout'><Panel className='report-paper-wrap' title='报告预览' subtitle={`${task.id} · v3`}><article className='report-paper'><header><div><AirplaneReportMark /></div><div><h2>无人机辅助事故现场测绘报告</h2><span>技术复核成果 · 非法定事故责任认定书</span></div></header><div className='report-meta'><span>任务：{task.id}</span><span>位置：{task.location}</span><span>采集：2026-07-13 10:18</span><span>版本：v3</span></div><img src='/assets/bev-intersection-night.png' alt='事故现场平面示意图' /><h3>量算摘要</h3><table><tbody><tr><td>车辆 A 轮廓</td><td>4.72m × 1.86m</td><td>人工校正</td></tr><tr><td>刹车痕迹</td><td>12.48m</td><td>自动候选 + 人工编辑</td></tr><tr><td>散落物区域</td><td>8.62m²</td><td>人工标注</td></tr></tbody></table><footer>road_data_version ROAD-2026.07.1 · survey-measure-r5 · schema uav.survey-result.v1</footer></article></Panel><div className='report-side'><Panel title='完整性门禁'><InfoRow label='原始材料' value='18 / 18' badge='good' /><InfoRow label='内容哈希' value='全部一致' badge='good' /><InfoRow label='量算对象' value='3 / 3' badge='good' /><InfoRow label='技术复核' value='已通过' badge='good' /><InfoRow label='误差口径' value='待冻结' badge='unverified' /></Panel><Panel title='主平台投递'><InfoRow label='成果状态' value='generated' badge='generated' /><InfoRow label='幂等键' value='sha256:8ab1…17cc' /><InfoRow label='Schema' value='uav.survey-result.v1' /><InfoRow label='材料引用' value='6 个不可变引用' /><button className='primary-button full' onClick={() => dispatch({ type: 'TOAST', value: { tone: 'success', text: '已按原幂等键提交主平台，等待回执' } })}>投递主平台</button></Panel><QualityNotice tone='info' title='成果边界'>报告用于事故现场处置和人工复核，不替代法定勘查、责任认定、人工签章或案件归档。</QualityNotice></div></div>
  </SurveyShell>
}

function AirplaneReportMark() { return <Drone size={30} weight='duotone' /> }
