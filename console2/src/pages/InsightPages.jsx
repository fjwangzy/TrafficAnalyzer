import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowsClockwise, ArrowSquareOut, CalendarBlank, Camera, ChartLineUp, Check, Clock, Crosshair, DownloadSimple, Funnel, Gauge, ListBullets, MapPin, Pause, Play, RoadHorizon, ShieldWarning, Stack, Truck, VideoCamera, Warning, X } from '@phosphor-icons/react'
import { AppShell } from '../components/AppShell'
import { CityMap } from '../components/CityMap'
import { MonitoringBevMap } from '../components/MonitoringBevMap'
import { DataTable, DetailDrawer, FilterBar, InfoRow, KpiCard, PageHeader, Panel, QualityNotice, Segmented, StatusBadge } from '../components/Common'
import { aiEvents, intersections as prototypeIntersections } from '../data/mockData'
import { useAppState } from '../state/AppState'
import { useAuth } from '../auth/AuthContext'
import { apiErrorMessage, platformApi } from '../lib/api'

const intersections = prototypeIntersections

const trafficSeries = [
  { time: '06:00', flow: 382, congestion: 2.1, speed: 42 }, { time: '08:00', flow: 768, congestion: 6.2, speed: 26 }, { time: '10:00', flow: 842, congestion: 7.2, speed: 24 },
  { time: '12:00', flow: 611, congestion: 4.5, speed: 34 }, { time: '14:00', flow: 584, congestion: 3.8, speed: 37 }, { time: '16:00', flow: 723, congestion: 5.9, speed: 29 }, { time: '18:00', flow: 891, congestion: 7.7, speed: 22 },
]

function mapIntersection(item) {
  const latitude = item.center_lat ?? item.lat
  const longitude = item.center_lon ?? item.lon
  return {
    ...item,
    id: item.inter_id || item.id,
    name: item.name || item.inter_id || item.id,
    lat: latitude == null || latitude === '' ? Number.NaN : Number(latitude),
    lon: longitude == null || longitude === '' ? Number.NaN : Number(longitude),
    quality: item.quality || item.quality_status || item.road_context_quality || 'unverified',
    risk: item.risk || (item.status === 'active' ? 'normal' : 'warning'),
  }
}

async function loadProjectIntersections() {
  const response = await platformApi.dashboardIntersections()
  return response?.items || []
}

function conflictEvent(item) {
  const ttc = Number(item.ttc_sec)
  const severity = ['critical', 'warning'].includes(item.severity) ? item.severity : 'warning'
  return {
    ...item,
    id: item.id,
    severity,
    title: item.conflict_scene || '机非冲突候选',
    type: 'conflict',
    metric: Number.isFinite(ttc) ? `TTC ${ttc.toFixed(1)}s` : 'TTC —',
    delivery: 'not_queued',
    review: item.review_status || 'pending',
    quality: item.quality_status || 'unverified',
    occurredAt: item.occurred_at || '—',
    intersectionId: item.inter_id || item.intersection_id,
  }
}

function alertEvent(item) {
  return {
    ...item,
    id: item.id,
    severity: item.severity === 'P1' ? 'critical' : 'warning',
    type: item.alert_type || 'alert',
    metric: item.description || '告警规则触发',
    delivery: 'not_queued',
    review: item.status === 'acknowledged' ? 'confirmed' : 'pending',
    quality: 'unverified',
    occurredAt: item.timestamp || item.created_at || '—',
    intersectionId: item.intersection_id,
    isAlert: true,
  }
}

const eventTypeLabels = {
  conflict: '真实冲突',
  congestion: '持续拥堵',
  quality_degradation: '质量下降',
  survey_result: '测绘成果',
  queue_overflow: '排队超限',
  calibration_drift: '标定漂移',
  high_avg_speed: '平均车速异常',
}

function unifiedEvent(item) {
  const payload = item.payload || {}
  const surveyVersion = String(payload.task?.version ?? '—').replace(/^v/i, '')
  const severity = item.severity === 'P1' || item.severity === 'critical'
    ? 'critical'
    : item.severity === 'P3' ? 'info' : 'warning'
  const metric = item.event_type === 'conflict'
    ? `TTC ${payload.ttc_sec ?? '—'}s · PET ${payload.pet_sec ?? '—'}s`
    : item.event_type === 'congestion'
      ? `拥堵指数 ${payload.metrics?.congestion_index ?? '—'}`
      : item.event_type === 'quality_degradation'
        ? `连续缺口 ${payload.gap_sec ?? '—'}s`
        : item.event_type === 'survey_result'
          ? `${payload.measurements?.length || 0} 项量算 · v${surveyVersion}`
          : item.description || '规则触发'
  return {
    ...payload,
    ...item,
    severity,
    type: eventTypeLabels[item.event_type] || item.event_type,
    metric,
    delivery: item.delivery_status || 'not_queued',
    review: item.review_status || 'pending',
    quality: item.quality_status || 'unverified',
    occurredAt: item.occurred_at || '—',
    intersectionId: item.inter_id,
    isConflict: item.source_kind === 'conflict',
  }
}

function eventMetricTiles(event) {
  if (event.event_type === 'conflict') return [
    ['TTC', `${event.ttc_sec ?? '—'}s`], ['PET', `${event.pet_sec ?? '—'}s`],
    ['风险分', event.risk_score ?? '—'], ['最小距离', `${event.distance_m ?? '—'}m`],
  ]
  if (event.event_type === 'congestion') return [
    ['拥堵指数', event.metrics?.congestion_index ?? '—'],
    ['连续样本', event.metrics?.event_rule?.consecutive_samples ?? 30],
    ['有效覆盖', event.metrics?.coverage_ratio == null ? '—' : `${(event.metrics.coverage_ratio * 100).toFixed(1)}%`],
    ['丢弃样本', event.metrics?.dropped_samples ?? 0],
  ]
  if (event.event_type === 'quality_degradation') return [
    ['连续缺口', `${event.gap_sec ?? '—'}s`], ['样本数', event.sample_count ?? '—'],
    ['阈值', `${event.rule?.threshold_sec ?? '—'}s`], ['时间质量', event.time_quality || '—'],
  ]
  if (event.event_type === 'survey_result') return [
    ['量算成果', event.measurements?.length || 0], ['证据文件', event.evidence_refs?.length || 0],
    ['成果版本', event.task?.version || '—'], ['质量', event.quality || event.quality_status || '—'],
  ]
  return [['事件类型', event.type], ['状态', event.status || 'open'], ['质量', event.quality], ['证据', event.evidence_refs?.length || 0]]
}

function EventEvidenceImage({ reference }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    let active = true
    let objectUrl = ''
    if (!reference?.id) return undefined
    platformApi.surveyEvidence(reference.id).then((blob) => {
      objectUrl = URL.createObjectURL(blob)
      if (active) setUrl(objectUrl)
    }).catch(() => setUrl(''))
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [reference?.id])
  return url ? <img className='event-evidence-image' src={url} alt='冲突事件关键帧证据' /> : <div className='live-state'>正在读取关键帧证据…</div>
}

function eventColumns(onOpen) {
  return [
    { key: 'severity', label: '风险', render: (value) => <StatusBadge value={value} /> },
    { key: 'title', label: 'AI 事件', render: (value, row) => <button className='table-link' onClick={() => onOpen(row)}>{value}<small>{row.id}</small></button> },
    { key: 'type', label: '类型' }, { key: 'metric', label: '核心指标' },
    { key: 'delivery', label: '投递', render: (value) => <StatusBadge value={value} /> },
    { key: 'review', label: 'AI 复核', render: (value) => <StatusBadge value={value} /> },
    { key: 'quality', label: '质量', render: (value) => <StatusBadge value={value} /> },
    { key: 'occurredAt', label: '业务时间' },
  ]
}

export function GisPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const initialId = new URLSearchParams(location.search).get('intersection_id')
  const [selectedId, setSelectedId] = useState(initialId)
  const initialLayer = new URLSearchParams(location.search).get('layer')
  const [layer, setLayer] = useState(['trajectory', 'conflict', 'hotspot'].includes(initialLayer) ? initialLayer : 'trajectory')
  const initialPeriod = new URLSearchParams(location.search).get('period')
  const [period, setPeriod] = useState(['all', '1h', '24h'].includes(initialPeriod) ? initialPeriod : 'all')
  const [missionId, setMissionId] = useState(new URLSearchParams(location.search).get('mission_id') || 'all')
  const [sourceProfileId, setSourceProfileId] = useState(new URLSearchParams(location.search).get('source_profile_id') || 'all')
  const [vehicleClass, setVehicleClass] = useState(new URLSearchParams(location.search).get('class_name') || 'all')
  const [turnBehavior, setTurnBehavior] = useState(new URLSearchParams(location.search).get('turn_behavior') || 'all')
  const [selectedTrackId, setSelectedTrackId] = useState(new URLSearchParams(location.search).get('track_id'))
  const intersectionsQuery = useQuery({ queryKey: ['i3-project-intersections'], queryFn: loadProjectIntersections, refetchInterval: 30_000 })
  const missionsQuery = useQuery({ queryKey: ['i3-gis-missions'], queryFn: () => platformApi.missions() })
  const sourcesQuery = useQuery({ queryKey: ['i3-gis-sources'], queryFn: () => platformApi.sources() })
  const projectIntersections = (intersectionsQuery.data || []).map(mapIntersection)
  const mapIntersections = projectIntersections.filter((item) => Number.isFinite(item.lat) && Number.isFinite(item.lon))
  const selected = projectIntersections.find((item) => item.id === selectedId) || projectIntersections[0] || null
  useEffect(() => { if (!selectedId && selected) setSelectedId(selected.id) }, [selectedId, selected])
  const trajectoriesQuery = useQuery({
    queryKey: ['i3-trajectories', selected?.id, period, missionId, sourceProfileId, vehicleClass, turnBehavior],
    queryFn: () => platformApi.trajectories(selected.id, {
      period, limit: 500, spatial_ready: true, min_world_points: 6,
      ...(missionId !== 'all' ? { mission_id: missionId } : {}),
      ...(sourceProfileId !== 'all' ? { source_profile_id: sourceProfileId } : {}),
      ...(vehicleClass !== 'all' ? { class_name: vehicleClass } : {}),
      ...(turnBehavior !== 'all' ? { turn_behavior: turnBehavior } : {}),
    }),
    enabled: Boolean(selected?.id),
    refetchInterval: 30_000,
  })
  const conflictsQuery = useQuery({
    queryKey: ['i3-conflicts', selected?.id, period],
    queryFn: () => platformApi.conflicts(selected.id, { period, limit: 200 }),
    enabled: Boolean(selected?.id),
    refetchInterval: 30_000,
  })
  const trajectories = trajectoriesQuery.data || []
  const conflicts = conflictsQuery.data || []
  const periodLabel = period === 'all' ? '全部验收数据' : period === '24h' ? '最近 24 小时' : '最近 1 小时'
  const intersectionResult = intersectionsQuery.isLoading
    ? '路口加载中'
    : intersectionsQuery.error ? '路口加载失败' : `${projectIntersections.length} 个路口`
  const trajectoryResult = intersectionsQuery.isLoading
    ? '轨迹等待路口'
    : trajectoriesQuery.isLoading ? '轨迹加载中' : trajectoriesQuery.error ? '轨迹加载失败' : `${trajectories.length} 条轨迹`
  const selectedTrack = trajectories.find((item) => item.id === selectedTrackId) || trajectories[0] || null
  useEffect(() => { if (!selectedTrackId && selectedTrack) setSelectedTrackId(selectedTrack.id) }, [selectedTrackId, selectedTrack])
  const availableMissions = (missionsQuery.data || []).filter((item) => !selected?.id || item.inter_id === selected.id)
  const selectIntersection = (item) => {
    setSelectedId(item.id)
    const params = new URLSearchParams(location.search)
    params.set('intersection_id', item.id)
    navigate(`${location.pathname}?${params.toString()}`, { replace: true })
  }
  const selectLayer = (value) => {
    setLayer(value)
    const params = new URLSearchParams(location.search)
    params.set('layer', value)
    if (selected) params.set('intersection_id', selected.id)
    navigate(`${location.pathname}?${params.toString()}`, { replace: true })
  }
  const selectPeriod = (value) => {
    setPeriod(value)
    const params = new URLSearchParams(location.search)
    params.set('period', value)
    if (selected) params.set('intersection_id', selected.id)
    navigate(`${location.pathname}?${params.toString()}`, { replace: true })
  }
  const loading = intersectionsQuery.isLoading || trajectoriesQuery.isLoading || conflictsQuery.isLoading
  const error = intersectionsQuery.error || trajectoriesQuery.error || conflictsQuery.error
  const retry = () => {
    if (intersectionsQuery.error) intersectionsQuery.refetch()
    if (trajectoriesQuery.error) trajectoriesQuery.refetch()
    if (conflictsQuery.error) conflictsQuery.refetch()
  }
  return <AppShell pageTitle='轨迹研判'>
    <PageHeader eyebrow='S1 / S2 / S5' title='轨迹研判' description='按任务、数据源、车型和方向回放 road9 真实轨迹，并从轨迹追溯事件与检测运行。' meta={`${periodLabel} · ${trajectoryResult}`} />
    <FilterBar result={`${intersectionResult} · ${trajectoryResult}`} onReset={() => { setMissionId('all'); setSourceProfileId('all'); setVehicleClass('all'); setTurnBehavior('all') }}><label>路口<select aria-label='路口' value={selected?.id || ''} onChange={(event) => selectIntersection(projectIntersections.find((item) => item.id === event.target.value))}>{projectIntersections.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>任务<select aria-label='轨迹任务' value={missionId} onChange={(event) => setMissionId(event.target.value)}><option value='all'>全部任务</option>{availableMissions.map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}</select></label><label>数据源<select aria-label='轨迹数据源' value={sourceProfileId} onChange={(event) => setSourceProfileId(event.target.value)}><option value='all'>全部数据源</option>{(sourcesQuery.data || []).map((item) => <option key={item.profile_id} value={item.profile_id}>{item.profile_id}</option>)}</select></label><label>车型<select aria-label='车辆类型' value={vehicleClass} onChange={(event) => setVehicleClass(event.target.value)}><option value='all'>全部车型</option><option value='motor'>机动车</option><option value='non_motor'>非机动车</option><option value='unknown'>未分类</option></select></label><label>方向<select aria-label='转向类型' value={turnBehavior} onChange={(event) => setTurnBehavior(event.target.value)}><option value='all'>全部方向</option><option value='straight'>直行</option><option value='left_turn'>左转</option><option value='right_turn'>右转</option><option value='u_turn'>掉头</option></select></label><label>时间窗口<select aria-label='时间窗口' value={period} onChange={(event) => selectPeriod(event.target.value)}><option value='all'>全部验收数据</option><option value='1h'>最近 1 小时</option><option value='24h'>最近 24 小时</option></select></label><Segmented value={layer} onChange={selectLayer} options={[{ value: 'trajectory', label: '历史轨迹' }, { value: 'conflict', label: '事件回放' }, { value: 'hotspot', label: '风险热区' }]} /></FilterBar>
    {loading && <QualityNotice tone='info' title='正在加载'>{intersectionsQuery.isLoading ? '正在读取项目路口，随后恢复 road9 真实轨迹。' : '正在从 road9 恢复轨迹与冲突事实。'}</QualityNotice>}
    {error && <QualityNotice tone='warning' title='历史数据不可用'>{apiErrorMessage(error)} <button className='secondary-button' onClick={retry}>重新加载真实数据</button></QualityNotice>}
    {!loading && !error && !selected && <QualityNotice tone='info' title='暂无路口'>尚未登记项目路口。</QualityNotice>}
    {selected && <div className='gis-layout'><Panel className='gis-map-panel' title={selected.name} subtitle={`inter_id ${selected.id} · ${missionId === 'all' ? '跨任务' : missionId}`}>{layer === 'hotspot' ? <CityMap points={mapIntersections} selectedId={selected.id} onSelect={selectIntersection} showHeat={conflicts.length > 0} /> : <MonitoringBevMap centerLat={selected.lat} centerLon={selected.lon} trajectories={trajectories} embedded label={`${selected.name}真实轨迹投放图`} />}{(!Number.isFinite(selected.lat) || !Number.isFinite(selected.lon)) && <QualityNotice tone='warning' title='坐标尚未冻结'>使用轨迹自身 ENU 锚点投放；不伪造项目路口坐标。</QualityNotice>}{layer === 'hotspot' && conflicts.length === 0 && <QualityNotice tone='info' title='无热区输入'>当前窗口没有真实冲突事实。</QualityNotice>}<div className='trajectory-timeline'><span>{trajectories.at(-1)?.started_at || '窗口起点'}</span><i><b style={{ width: selectedTrack ? '100%' : '0%' }} /></i><span>{trajectories[0]?.ended_at || '窗口终点'}</span></div></Panel>
      <div className='gis-sidebar'><Panel title='空间对象摘要'><div className='summary-quad'><div><strong>{trajectories.length}</strong><span>历史轨迹</span></div><div><strong>{trajectories.filter((item) => item.trajectory_world_m?.length > 1).length}</strong><span>世界坐标</span></div><div><strong>{conflicts.length}</strong><span>真实冲突</span></div><div><strong>{trajectories.filter((item) => item.quality_status !== 'verified').length}</strong><span>unverified</span></div></div></Panel>{selectedTrack ? <Panel title={`Track #${selectedTrack.track_id}`} subtitle={selectedTrack.id}><InfoRow label='车型 / 方向' value={`${selectedTrack.vehicle_class || 'unknown'} / ${selectedTrack.turn_behavior || '未分类'}`} /><InfoRow label='时间' value={`${selectedTrack.started_at || '—'} → ${selectedTrack.ended_at || '—'}`} /><InfoRow label='时长 / 点数' value={`${selectedTrack.duration_sec ?? '—'}s / ${selectedTrack.trajectory_px?.length || 0}`} /><InfoRow label='平均 / 最高速度' value={`${selectedTrack.avg_speed_kmh ?? '—'} / ${selectedTrack.max_speed_kmh ?? '—'} km/h`} /><InfoRow label='任务' value={selectedTrack.mission_id || '—'} /><InfoRow label='数据源' value={selectedTrack.source_profile_id || '—'} /><InfoRow label='路网 / 质量' value={`${selectedTrack.road_data_version || '—'} / ${selectedTrack.quality_status || '—'}`} badge={selectedTrack.road_context_status === 'complete' ? 'good' : 'degraded'} /></Panel> : <Panel title='轨迹详情'><span className='muted'>当前筛选没有轨迹</span></Panel>}<Panel title='轨迹清单' subtitle='点击同步地图与详情'><div className='trajectory-list'>{trajectories.slice(0, 12).map((track) => <button className={`compact-event ${selectedTrack?.id === track.id ? 'selected' : ''}`} key={track.id} onClick={() => setSelectedTrackId(track.id)}><StatusBadge value={track.quality_status || 'unverified'} /><div><strong>Track #{track.track_id}</strong><span>{track.vehicle_class || 'unknown'} · {track.turn_behavior || '未分类'} · {track.duration_sec ?? '—'}s</span></div></button>)}</div></Panel><Panel title='关联事件'>{conflicts.length === 0 ? <span className='muted'>当前窗口无真实冲突</span> : conflicts.slice(0, 3).map((item) => { const event = conflictEvent(item); return <button className='compact-event' key={event.id} onClick={() => navigate(`/events?event_id=${event.id}`)}><StatusBadge value={event.severity} /><div><strong>{event.title}</strong><span>{event.metric} · {event.occurredAt}</span></div></button> })}</Panel></div></div>}
  </AppShell>
}

export function RiskHotspotsPage() {
  const [status, setStatus] = useState('formal')
  const [selected, setSelected] = useState(intersections[0])
  return <AppShell pageTitle='风险热区'>
    <PageHeader eyebrow='S2 · 空间聚类' title='风险热区' description='按统计窗口、有效覆盖和样本数展示候选与正式热区，避免将低质量点位聚合成结论。' meta='候选参数 · DBSCAN 半径/样本数待冻结' />
    <div className='kpi-grid four'><KpiCard icon={ShieldWarning} label='正式热区' value='6' unit='处' change='+1' tone='red' detail='最高风险：critical' /><KpiCard icon={Crosshair} label='候选热区' value='4' unit='处' change='2 待复核' tone='amber' detail='coverage ≥ 90%' /><KpiCard icon={RoadHorizon} label='有效事件样本' value='286' unit='起' change='+18%' detail='近 7 日窗口' /><KpiCard icon={Gauge} label='空间匹配率' value='96.8' unit='%' change='+0.6%' tone='cyan' detail='unmapped 9 起' /></div>
    <FilterBar result='统计窗口 2026-07-07—2026-07-13'><Segmented value={status} onChange={setStatus} options={[{ value: 'formal', label: '正式' }, { value: 'candidate', label: '候选' }, { value: 'confirmed', label: '已确认' }, { value: 'rejected', label: '已驳回' }]} /><label>事件类型<select><option>冲突 + 换道</option><option>机非冲突</option><option>换道</option></select></label><label>最低覆盖<select><option>90%</option><option>80%</option></select></label></FilterBar>
    <div className='hotspot-layout'><Panel title='热区空间分布' subtitle='GCJ02 · 点位来自演示数据集'><CityMap points={intersections} selectedId={selected.id} onSelect={setSelected} showHeat /></Panel><Panel title='热区详情' subtitle={selected.name}><div className='hotspot-score'><ShieldWarning size={32} weight='fill' /><div><span>最高风险等级</span><strong>{selected.risk === 'critical' ? '高风险' : '关注'}</strong></div><b>R = 50m</b></div><InfoRow label='有效事件' value='37 起' /><InfoRow label='统计窗口' value='近 7 日' /><InfoRow label='有效覆盖' value='94.7%' badge='good' /><InfoRow label='样本构成' value='机非 22 · 换道 15' /><InfoRow label='聚类规则' value='hotspot-candidate-r3' /><QualityNotice tone='info' title='候选参数未冻结'>热区只用于空间研判，不直接等同主平台警情等级。</QualityNotice></Panel></div>
  </AppShell>
}

export function AlertsPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const { dispatch } = useAppState()
  const { platformRole } = useAuth()
  const queryClient = useQueryClient()
  const initialParams = new URLSearchParams(location.search)
  const initialId = initialParams.get('event_id')
  const [selected, setSelected] = useState(null)
  const [actionError, setActionError] = useState('')
  const [severity, setSeverity] = useState(['critical', 'warning'].includes(initialParams.get('severity')) ? initialParams.get('severity') : 'all')
  const [eventType, setEventType] = useState(initialParams.get('event_type') || 'all')
  const [intersection, setIntersection] = useState(initialParams.get('intersection_id') || 'all')
  const [query, setQuery] = useState('')
  const intersectionsQuery = useQuery({ queryKey: ['i3-project-intersections'], queryFn: loadProjectIntersections, refetchInterval: 30_000 })
  const projectIntersections = (intersectionsQuery.data || []).map(mapIntersection)
  const eventsQuery = useQuery({ queryKey: ['i3-events'], queryFn: () => platformApi.events({ limit: 500 }), refetchInterval: 30_000 })
  const events = useMemo(() => (eventsQuery.data || []).map(unifiedEvent), [eventsQuery.data])
  useEffect(() => {
    if (initialId && !selected) setSelected(events.find((item) => item.id === initialId) || null)
  }, [events, initialId, selected])
  const rows = useMemo(() => events.filter((item) =>
    (severity === 'all' || item.severity === severity) &&
    (eventType === 'all' || item.event_type === eventType) &&
    (intersection === 'all' || item.intersectionId === intersection) &&
    (!query.trim() || `${item.id} ${item.title}`.toLowerCase().includes(query.trim().toLowerCase()))
  ), [events, severity, eventType, intersection, query])
  const eventDetailQuery = useQuery({ queryKey: ['i3-event-detail', selected?.id], queryFn: () => platformApi.event(selected.id), enabled: Boolean(selected?.id) })
  const selectedEvent = eventDetailQuery.data ? unifiedEvent(eventDetailQuery.data) : selected ? events.find((item) => item.id === selected.id) || selected : null
  const reviewMutation = useMutation({
    mutationFn: ({ event, reviewStatus }) => platformApi.reviewEvent(event.id, { review_status: reviewStatus, expected_revision: event.review_revision, reason: 'Console2 technical review' }),
    onSuccess: (value) => {
      setActionError('')
      setSelected(unifiedEvent(value))
      queryClient.invalidateQueries({ queryKey: ['i3-events'] })
      queryClient.invalidateQueries({ queryKey: ['i3-event-detail', value.id] })
      dispatch({ type: 'TOAST', value: { tone: 'success', text: value.review_status === 'confirmed' ? 'AI 结果已技术确认' : 'AI 结果已驳回并记录原因' } })
    },
    onError: (error) => setActionError(apiErrorMessage(error, '技术复核失败')),
  })
  const openEvent = (item) => {
    setSelected(item)
    const params = new URLSearchParams(location.search)
    if (item) params.set('event_id', item.id)
    else params.delete('event_id')
    navigate(`${location.pathname}${params.size ? `?${params.toString()}` : ''}`, { replace: true })
  }
  const loading = intersectionsQuery.isLoading || eventsQuery.isLoading
  const loadError = intersectionsQuery.error || eventsQuery.error
  return <AppShell pageTitle='AI 事件中心'>
    <PageHeader eyebrow='S2 / S4 / S6' title='AI 事件中心' description='真实拥堵、质量下降、测绘成果与真实冲突统一查询；每类事件保留自己的指标与证据。' meta={`${events.length} 起真实事件 · ${events.filter((item) => item.review === 'pending').length} 起待复核`} />
    <FilterBar result={`显示 ${rows.length} / ${events.length} 起`} onReset={() => { setSeverity('all'); setEventType('all'); setIntersection('all'); setQuery('') }}><Segmented value={severity} onChange={setSeverity} options={[{ value: 'all', label: '全部' }, { value: 'critical', label: '高风险' }, { value: 'warning', label: '关注' }, { value: 'info', label: '成果' }]} /><label>事件类型<select aria-label='事件类型' value={eventType} onChange={(event) => setEventType(event.target.value)}><option value='all'>全部类型</option><option value='congestion'>持续拥堵</option><option value='quality_degradation'>质量下降</option><option value='survey_result'>测绘成果</option><option value='conflict'>真实冲突</option></select></label><label>路口<select aria-label='事件路口' value={intersection} onChange={(event) => setIntersection(event.target.value)}><option value='all'>全部项目路口</option>{projectIntersections.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className='search-field'><Funnel size={15} /><input aria-label='事件搜索' value={query} onChange={(event) => setQuery(event.target.value)} placeholder='事件 ID / 标题' /></label></FilterBar>
    {loading && <QualityNotice tone='info' title='正在恢复事件台账'>从 road9 加载冲突事实与告警。</QualityNotice>}
    {loadError && <QualityNotice tone='warning' title='事件台账不可用'>{apiErrorMessage(loadError)}</QualityNotice>}
    {!loading && !loadError && <Panel title='AI 事件事实' subtitle='业务时间排序 · REST 为页面刷新后的恢复基线'><DataTable columns={eventColumns(openEvent)} rows={rows} onRowClick={openEvent} /></Panel>}
    {selectedEvent && <DetailDrawer wide title={selectedEvent.title} subtitle={`${selectedEvent.type} · ${selectedEvent.id}`} onClose={() => openEvent(null)} footer={platformRole === 'admin' ? <><button className='danger-button' disabled={reviewMutation.isPending} onClick={() => reviewMutation.mutate({ event: selectedEvent, reviewStatus: 'rejected' })}><X size={15} /> 驳回 AI 结果</button><button className='primary-button' disabled={reviewMutation.isPending} onClick={() => reviewMutation.mutate({ event: selectedEvent, reviewStatus: 'confirmed' })}><Check size={15} /> 技术确认</button></> : <span className='muted'>仅管理员可执行技术复核</span>}>
      <div className='event-hero'><div className='event-primary-metrics'>{eventMetricTiles(selectedEvent).map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div></div>
      {actionError && <QualityNotice tone='warning' title='技术复核失败'>{actionError}</QualityNotice>}
      {selectedEvent.evidence_refs?.length > 0 && <Panel title='关键帧证据' subtitle={`sha256:${selectedEvent.evidence_refs[0].sha256?.slice(0, 16)}…`}><EventEvidenceImage reference={selectedEvent.evidence_refs[0]} /></Panel>}
      <div className='detail-two-col'><Panel title='事件与质量'><InfoRow label='业务时间' value={selectedEvent.occurredAt} /><InfoRow label='路口' value={projectIntersections.find((item) => item.id === selectedEvent.intersectionId)?.name || selectedEvent.intersectionId || '未匹配'} /><InfoRow label='任务 / Pipeline' value={`${selectedEvent.mission_id || '—'} / ${selectedEvent.pipeline_id || '—'}`} /><InfoRow label='数据源' value={selectedEvent.source_profile_id || '—'} /><InfoRow label='路网版本' value={selectedEvent.road_data_version || '—'} /><InfoRow label='质量' value={selectedEvent.quality} badge={selectedEvent.quality === 'verified' ? 'good' : 'degraded'} /></Panel><Panel title='投递与复核'><InfoRow label='投递状态' value={selectedEvent.delivery} badge={selectedEvent.delivery === 'blocked' ? 'blocked' : 'degraded'} /><InfoRow label='事实来源' value={selectedEvent.isConflict ? 'uav_conflict_events' : 'uav_ai_events'} /><InfoRow label='复核 revision' value={selectedEvent.review_revision || '—'} /><InfoRow label='技术复核' value={selectedEvent.review} badge={selectedEvent.review} /></Panel></div>
      {selectedEvent.related_tracks?.length > 0 && <Panel title='关联轨迹' subtitle={`同任务/事件窗口 ${selectedEvent.related_tracks.length} 条`}><div className='related-track-list'>{selectedEvent.related_tracks.slice(0, 8).map((track) => <button key={track.id} className='compact-event' onClick={() => navigate(`/gis?intersection_id=${selectedEvent.intersectionId}&mission_id=${track.mission_id || ''}&track_id=${track.id}`)}><StatusBadge value={track.quality_status || 'unverified'} /><div><strong>Track #{track.track_id}</strong><span>{track.vehicle_class || 'unknown'} · {track.turn_behavior || '未分类'} · {track.duration_sec ?? '—'}s</span></div></button>)}</div></Panel>}
      <Panel title='事实状态时间线'><div className='state-timeline'>{[`事实入库 ${selectedEvent.occurredAt}`, selectedEvent.delivery === 'not_queued' ? '主平台投递未启用' : `投递：${selectedEvent.delivery}`, selectedEvent.review === 'pending' ? '等待技术复核' : `技术复核：${selectedEvent.review}`].map((item, index) => <div key={item} className={index === 2 ? 'current' : ''}><i /><span>{item}</span></div>)}</div></Panel>
      <QualityNotice tone='warning' title='责任边界'>“确认/驳回”仅表示 AI 识别结果技术或业务复核，不生成派警、处罚或案件办结状态。</QualityNotice>
    </DetailDrawer>}
  </AppShell>
}

export function VideoPage() {
  const navigate = useNavigate()
  const [camera, setCamera] = useState('camera-1')
  const [running, setRunning] = useState(true)
  const [layer, setLayer] = useState('all')
  const [replayPlaying, setReplayPlaying] = useState(false)
  return <AppShell pageTitle='视频分析'>
    <PageHeader eyebrow='S1 / S2' title='视频分析' description='检查检测、跟踪、换道与 TTC/PET 叠加结果，并控制单路视频分析 Pipeline。' meta='INT_camera_1 · 29.7 FPS · P95 46ms' actions={<button className={running ? 'danger-button' : 'primary-button'} onClick={() => setRunning(!running)}>{running ? <Pause size={15} /> : <Play size={15} />}{running ? '停止 Pipeline' : '启动 Pipeline'}</button>} />
    <FilterBar><label>视频源<select value={camera} onChange={(event) => setCamera(event.target.value)}><option value='camera-1'>INT_camera_1 · 实时</option><option value='camera-2'>INT_camera_2 · 实时</option><option value='local'>inter_xqh · MP4 + SRT</option></select></label><Segmented value={layer} onChange={setLayer} options={[{ value: 'all', label: '全部叠加' }, { value: 'track', label: '轨迹' }, { value: 'lane', label: '换道' }, { value: 'risk', label: '冲突' }]} /></FilterBar>
    <div className='video-layout'><Panel className='video-stage-panel' title='检测器输出' subtitle={`${camera} · YOLO11 / ByteTrack · ${running ? '实时分析中' : 'Pipeline 已停止'}`}><div className={`video-stage ${running ? '' : 'paused'}`}><img src='/assets/uav-intersection-night.png' alt='无人机检测器视频分析画面' />{(layer === 'all' || layer === 'track') && <><span className='detect-box vbox-a'><em>car 0.96 · #1842 · 28km/h</em></span><span className='detect-box vbox-b'><em>truck 0.91 · #0971 · 34km/h</em></span></>}{(layer === 'all' || layer === 'lane') && <div className='lane-change-tag'><ArrowsClockwise size={15} /> 换道候选 · 几何/运动双验证</div>}{(layer === 'all' || layer === 'risk') && <div className='ttc-tag'><ShieldWarning size={16} weight='fill' /><strong>高风险交汇</strong><span>TTC 1.2s · PET 0.8s</span></div>}{!running && <div className='paused-cover'><Pause size={38} weight='fill' /><strong>Pipeline 已停止</strong></div>}</div><div className='replay-bar'><button aria-label={replayPlaying ? '暂停回放' : '播放回放'} onClick={() => setReplayPlaying(!replayPlaying)}>{replayPlaying ? <Pause size={15} weight='fill' /> : <Play size={15} weight='fill' />}</button><strong>{replayPlaying ? '回放中' : '已暂停'}</strong><div className='replay-track'><i style={{ width: replayPlaying ? '72%' : '46%' }} /></div><span>10:41:20 / 10:55:28</span></div></Panel><div className='video-side'><div className='kpi-grid two'><KpiCard icon={Gauge} label='端到端延迟' value='1.4' unit='s' change='P95' /><KpiCard icon={Camera} label='当前目标' value='37' unit='个' change='+4' tone='cyan' /><KpiCard icon={ArrowsClockwise} label='换道候选' value='2' unit='起' change='1 待确认' tone='amber' /><KpiCard icon={ShieldWarning} label='冲突事件' value='1' unit='起' change='高风险' tone='red' /></div><Panel title='模型与质量'><InfoRow label='检测模型' value='uav_best.pt · v11' /><InfoRow label='跟踪器' value='ByteTrack · 31 活跃轨迹' /><InfoRow label='运动补偿' value='稳定' badge='good' /><InfoRow label='GCJ02 对齐' value='2.1m 估计误差' badge='good' /><InfoRow label='有效覆盖' value='94.7%' /></Panel><Panel title='实时事件'>{aiEvents.slice(0, 3).map((item) => <button className='compact-event' key={item.id} onClick={() => navigate(`/events?event_id=${item.id}`)}><StatusBadge value={item.severity} /><div><strong>{item.title}</strong><span>{item.metric} · {item.occurredAt}</span></div></button>)}</Panel></div></div>
  </AppShell>
}

export function ReportsPage() {
  const [period, setPeriod] = useState('24h')
  const { dispatch } = useAppState()
  return <AppShell pageTitle='报告中心'>
    <PageHeader eyebrow='S1 / S2 / S4 / S7' title='报告中心' description='按统一口径汇总交通态势、风险、执法线索和测绘交付，所有报表保留版本与质量来源。' meta='统计窗口完整率 96.2%' actions={<button className='primary-button' onClick={() => dispatch({ type: 'TOAST', value: { tone: 'success', text: '演示报表已生成，包含版本与质量说明' } })}><DownloadSimple size={15} /> 生成报告</button>} />
    <FilterBar><Segmented value={period} onChange={setPeriod} options={[{ value: '24h', label: '24 小时' }, { value: '7d', label: '7 天' }, { value: '30d', label: '30 天' }]} /><label>路口范围<select><option>全部项目路口</option><option>重点保障路口</option></select></label><label>报告类型<select><option>综合态势报告</option><option>风险专题</option><option>执法线索</option><option>测绘交付</option></select></label></FilterBar>
    <div className='kpi-grid four'><KpiCard icon={RoadHorizon} label='总流量' value='128,460' unit='辆' change='+6.8%' /><KpiCard icon={Gauge} label='平均拥堵指数' value='4.8' unit='/10' change='+0.3' tone='amber' /><KpiCard icon={ShieldWarning} label='有效风险事件' value='186' unit='起' change='确认率 72%' tone='red' /><KpiCard icon={Truck} label='执法线索' value='42' unit='起' change='证据完整 38' tone='cyan' /></div>
    <div className='reports-grid'><Panel className='report-chart-large' title='交通态势趋势' subtitle={`${period} · 不跨缺失窗口连线`}><ResponsiveContainer width='100%' height='100%'><LineChart data={trafficSeries} margin={{ top: 12, right: 12, left: -20, bottom: 0 }}><CartesianGrid vertical={false} stroke='rgba(120,145,185,.12)' /><XAxis dataKey='time' tick={{ fill: '#7989a2', fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis tick={{ fill: '#7989a2', fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip contentStyle={{ background: '#101827', border: '1px solid #2a3952', borderRadius: 8 }} /><Line dataKey='flow' stroke='#6d9eff' strokeWidth={2} dot={false} /><Line dataKey='speed' stroke='#5ad3e7' strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer></Panel><Panel title='风险类型分布'><ResponsiveContainer width='100%' height='100%'><BarChart data={[{ name: '机非冲突', value: 68 }, { name: '换道', value: 54 }, { name: '拥堵', value: 43 }, { name: '执法线索', value: 21 }]} layout='vertical' margin={{ left: 20 }}><XAxis type='number' hide /><YAxis type='category' dataKey='name' tick={{ fill: '#8694aa', fontSize: 10 }} axisLine={false} tickLine={false} width={68} /><Bar dataKey='value' fill='#6d9eff' radius={[0, 4, 4, 0]} /></BarChart></ResponsiveContainer></Panel></div>
    <Panel title='报告交付记录'><DataTable rows={[{ id: 'RPT-0713-01', name: '历下区 24 小时综合态势', type: '综合态势', version: 'v4', quality: 'good', generated: '10:30:04', status: 'completed' }, { id: 'RPT-0712-08', name: '小清河北路风险专题', type: '风险专题', version: 'v2', quality: 'good', generated: '昨天 18:20', status: 'completed' }, { id: 'RPT-0712-04', name: '事故测绘交付清单', type: '测绘', version: 'v1', quality: 'degraded', generated: '昨天 12:04', status: 'blocked' }]} columns={[{ key: 'name', label: '报告名称' }, { key: 'type', label: '类型' }, { key: 'version', label: '版本' }, { key: 'quality', label: '数据质量', render: (value) => <StatusBadge value={value} /> }, { key: 'generated', label: '生成时间' }, { key: 'status', label: '交付状态', render: (value) => <StatusBadge value={value} /> }]} /></Panel>
  </AppShell>
}
