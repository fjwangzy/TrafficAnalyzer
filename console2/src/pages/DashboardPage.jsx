import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Broadcast, Buildings, CheckCircle, Database, Drone, Funnel, Pulse, ShieldWarning } from '@phosphor-icons/react'
import { AppShell } from '../components/AppShell'
import { CityMap } from '../components/CityMap'
import { KpiCard, PageHeader, Panel } from '../components/Common'
import { platformApi } from '../lib/api'
import { demoSituation } from '../config/demoData'

const DAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const SOURCE_PRIORITY = { running: 0, ready: 1, degraded: 2, invalid: 3, disabled: 4 }
const TIME_SLOTS = Array.from({ length: 288 }, (_, stepIndex) => ({ stepIndex, label: timeValue(stepIndex) }))

const kpiIcons = {
  network: Buildings,
  oversaturated: ShieldWarning,
  segments: Buildings,
  conflict: Broadcast,
  efficiency: CheckCircle,
}

function finiteNumber(value) {
  if (value == null || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

export function situationStatusFromSaturation(value) {
  const number = finiteNumber(value)
  if (number == null) return 'missing'
  if (number < 0.85) return 'good'
  if (number <= 0.95) return 'near_saturated'
  return 'oversaturated'
}

export function segmentStatusFromDelayIndex(value) {
  const number = finiteNumber(value)
  if (number == null) return 'missing'
  if (number < 1.5) return 'smooth'
  if (number <= 2) return 'slow'
  return 'congested'
}

function projectPosition(item) {
  const position = item?.center_gcj02 || item?.position_gcj02
  const lon = finiteNumber(position?.longitude ?? item?.lon)
  const lat = finiteNumber(position?.latitude ?? item?.lat)
  return lon == null || lat == null ? null : { lon, lat }
}

export function buildDashboardIntersectionPoints({ situationIntersections = [], projectIntersections = [] }) {
  const points = new Map()
  situationIntersections.forEach((item) => {
    const position = projectPosition(item)
    if (!position) return
    const saturation = finiteNumber(item.saturation_max)
    points.set(item.inter_id, {
      ...item,
      id: item.inter_id,
      ...position,
      saturation_max: saturation,
      status: situationStatusFromSaturation(saturation),
      is_project: false,
      has_server_situation: true,
    })
  })
  projectIntersections.forEach((item) => {
    const id = item.inter_id || item.id
    const existing = points.get(id)
    const position = projectPosition(existing || item) || projectPosition(item)
    if (!id || !position) return
    points.set(id, existing
      ? { ...existing, is_project: true, project_name: item.name }
      : {
          id,
          inter_id: id,
          name: item.name || id,
          ...position,
          saturation_max: null,
          saturation_avg: null,
          unbalance_index: null,
          level_of_service: null,
          updated_at: null,
          status: 'missing',
          is_project: true,
          has_server_situation: false,
        })
  })
  return [...points.values()]
}

export function dashboardSourceStatus(source, pipeline) {
  if (pipeline?.status === 'running' || pipeline?.observed_status === 'running') return 'running'
  if (source.enabled === false) return 'disabled'
  if (source.validation_status === 'invalid') return 'invalid'
  if (source.validation_status === 'degraded') return 'degraded'
  return 'ready'
}

export function buildDashboardSourcePoints({ sources = [], drones = [], intersections = [], pipelines = [] }) {
  const droneById = new Map(drones.map((item) => [item.id, item]))
  const intersectionById = new Map(intersections.flatMap((item) => [[item.id, item], [item.inter_id, item]]).filter(([id]) => id))
  const grouped = new Map()

  sources.forEach((source) => {
    const pipeline = pipelines.find((item) => item.source_profile_id === source.profile_id && (item.status === 'running' || item.observed_status === 'running'))
    const drone = droneById.get(source.drone_id)
    const intersectionId = pipeline?.intersection_id || drone?.default_inter_id || drone?.current_intersection_id
    const intersection = intersectionById.get(intersectionId)
    const position = projectPosition(intersection)
    const sourceStatus = dashboardSourceStatus(source, pipeline)
    if (!intersectionId || !intersection || intersection.has_server_situation === false || !position || sourceStatus === 'disabled' || sourceStatus === 'invalid') return
    const mapped = {
      source_profile_id: source.profile_id,
      intersection_id: intersectionId,
      drone_id: source.drone_id,
      name: source.display_name || source.video?.location_hint || source.profile_id,
      drone_name: drone?.name || source.drone_id,
      source_status: sourceStatus,
      validation_status: source.validation_status,
      pipeline_id: pipeline?.pipeline_id || pipeline?.id || null,
    }
    if (!grouped.has(intersectionId)) grouped.set(intersectionId, [])
    grouped.get(intersectionId).push(mapped)
  })

  return [...grouped.entries()].map(([intersectionId, mappedSources]) => {
    const intersection = intersectionById.get(intersectionId)
    const position = projectPosition(intersection)
    const sorted = mappedSources.sort((left, right) => SOURCE_PRIORITY[left.source_status] - SOURCE_PRIORITY[right.source_status])
    const primary = sorted[0]
    return {
      id: intersectionId,
      ...primary,
      intersection_name: intersection.name || intersectionId,
      ...position,
      source_count: sorted.length,
      sources: sorted,
    }
  })
}

export function defaultTypicalSlot() {
  return { dayOfWeek: 5, stepIndex: 95 }
}

function timeValue(stepIndex) {
  return `${String(Math.floor(stepIndex / 12)).padStart(2, '0')}:${String((stepIndex % 12) * 5).padStart(2, '0')}`
}

function formatMetric(value, digits = 2, suffix = '—') {
  const number = finiteNumber(value)
  return number == null ? suffix : number.toFixed(digits)
}

export function DashboardPage() {
  const navigate = useNavigate()
  const initialSlot = useMemo(() => defaultTypicalSlot(), [])
  const [dayOfWeek, setDayOfWeek] = useState(initialSlot.dayOfWeek)
  const [stepIndex, setStepIndex] = useState(initialSlot.stepIndex)
  const [selectedIntersectionId, setSelectedIntersectionId] = useState(null)
  const [selectedSegmentId, setSelectedSegmentId] = useState(null)
  const queryOptions = { refetchInterval: 60_000, retry: (count, error) => error?.response?.status !== 401 && count < 2 }
  const intersectionParams = { limit: 500 }
  const situationQuery = useQuery({ queryKey: ['dashboard', 'situation', dayOfWeek, stepIndex], queryFn: () => platformApi.dashboardSituation(dayOfWeek, stepIndex), ...queryOptions })
  const intersectionsQuery = useQuery({ queryKey: ['dashboard', 'intersections', intersectionParams], queryFn: () => platformApi.dashboardIntersections(intersectionParams), placeholderData: (previous) => previous, ...queryOptions })
  const sourcesQuery = useQuery({ queryKey: ['dashboard', 'sources'], queryFn: platformApi.sources, ...queryOptions })
  const sourceDronesQuery = useQuery({ queryKey: ['dashboard', 'source-drones'], queryFn: platformApi.drones, ...queryOptions })
  const pipelinesQuery = useQuery({ queryKey: ['dashboard', 'pipelines'], queryFn: platformApi.pipelines, ...queryOptions })

  const situation = situationQuery.data
  const projectIntersections = intersectionsQuery.data?.items || []
  const intersections = useMemo(() => buildDashboardIntersectionPoints({
    situationIntersections: situation?.intersections || [],
    projectIntersections,
  }), [situation?.intersections, projectIntersections])
  const segments = useMemo(() => (situation?.segments || []).map((item) => ({
    ...item,
    status: item.status || segmentStatusFromDelayIndex(item.delay_index),
  })), [situation?.segments])
  const sources = Array.isArray(sourcesQuery.data) ? sourcesQuery.data : []
  const sourceDrones = Array.isArray(sourceDronesQuery.data) ? sourceDronesQuery.data : []
  const pipelines = Array.isArray(pipelinesQuery.data) ? pipelinesQuery.data : []
  const sourcePoints = useMemo(
    () => buildDashboardSourcePoints({ sources, drones: sourceDrones, intersections, pipelines }),
    [sources, sourceDrones, intersections, pipelines],
  )

  const rankedIntersections = useMemo(() => [...intersections]
    .filter((item) => item.saturation_max != null)
    .sort((left, right) => right.saturation_max - left.saturation_max), [intersections])

  useEffect(() => {
    if (!selectedIntersectionId && rankedIntersections[0]) setSelectedIntersectionId(rankedIntersections[0].id)
  }, [rankedIntersections, selectedIntersectionId])

  const selectedIntersection = intersections.find((item) => item.id === selectedIntersectionId) || rankedIntersections[0] || intersections[0]
  const selectedSource = sourcePoints.find((item) => item.intersection_id === selectedIntersection?.id)
  const focusIntersections = rankedIntersections.slice(0, 3)
  const firstSource = sourcePoints[0]

  const openSourceMonitoring = useCallback((item, review = false) => {
    if (!item?.source_profile_id || !item?.intersection_id) return
    const suffix = review ? '&stage=review' : ''
    navigate(`/monitoring?intersection_id=${encodeURIComponent(item.intersection_id)}&source_profile_id=${encodeURIComponent(item.source_profile_id)}${suffix}`)
  }, [navigate])
  const selectIntersection = useCallback((item) => {
    setSelectedIntersectionId(item.id)
    setSelectedSegmentId(null)
  }, [])
  const selectSegment = useCallback((item) => {
    setSelectedIntersectionId(item.inter_id)
    setSelectedSegmentId(item.id)
  }, [])
  const selectSource = useCallback((item) => openSourceMonitoring(item), [openSourceMonitoring])

  const serverSummary = situation?.summary || {}
  const kpis = [
    { id: 'network', label: '态势路口', value: serverSummary.intersections_total ?? '—', unit: '处', detail: `路段 ${serverSummary.segments_total ?? '—'} 条`, tone: 'blue' },
    { id: 'oversaturated', label: '过饱和路口', value: serverSummary.oversaturated ?? '—', unit: '处', detail: '饱和度 > 0.95', tone: 'red' },
    { id: 'segments', label: '拥堵路段', value: serverSummary.congested_segments ?? '—', unit: '条', detail: '延误指数 > 2.0', tone: 'cyan' },
    ...demoSituation.kpis.filter((item) => ['conflict', 'efficiency'].includes(item.id)).map((item) => ({ ...item, detail: `${item.detail} · 演示` })),
  ]
  const situationError = situationQuery.error
  const otherLoadError = intersectionsQuery.error || sourcesQuery.error || sourceDronesQuery.error || pipelinesQuery.error
  const slotLabel = `${DAY_LABELS[dayOfWeek - 1]} ${timeValue(stepIndex)}`
  const storyRoutes = ['/', '/monitoring', '/events', '/events', '/monitoring?stage=review']

  return (
    <AppShell pageTitle='全局态势' topContext={{ scope: `服务器态势 ${serverSummary.intersections_total ?? '—'} 路口 · 项目 ${projectIntersections.length} 路口`, window: `${slotLabel} 典型时段`, asOf: situation?.cache?.stale ? '缓存降级' : '服务器典型矩阵' }}>
      <PageHeader title='无人机交通态势工作台' actions={<div className='heading-button-row'><span className={`server-situation-badge ${situation?.cache?.stale ? 'stale' : ''}`}>{situation?.cache?.stale ? '服务器缓存态势' : '服务器典型时段态势'}</span><button className='primary-button' disabled={!firstSource} onClick={() => firstSource && openSourceMonitoring(firstSource)}>进入无人机监控 <ArrowRight size={15} /></button></div>} />

      <section className='demo-story-strip' aria-label='演示故事线'>
        {demoSituation.story.map((step, index) => <button key={step.id} onClick={() => navigate(storyRoutes[index])}><span>{step.id}</span><div><strong>{step.label}</strong><small>{step.caption}</small></div>{index < demoSituation.story.length - 1 && <ArrowRight size={14} />}</button>)}
      </section>

      <div className='kpi-grid dashboard-kpis'>
        {kpis.map((item) => <KpiCard key={item.id} icon={kpiIcons[item.id] || Broadcast} label={item.label} value={item.value} unit={item.unit} detail={item.detail} tone={item.tone} />)}
      </div>

      <div className='dashboard-grid'>
        <Panel className='map-master-panel'>
          <CityMap
            points={intersections}
            segments={segments}
            sourcePoints={sourcePoints}
            selectedId={selectedIntersection?.id}
            selectedSegmentId={selectedSegmentId}
            selectedSourceId={selectedSource?.id}
            onSelect={selectIntersection}
            onSegmentSelect={selectSegment}
            onSourceSelect={selectSource}
            fitToData
            coordinateLabel={`路口 ${intersections.length} · 路段 ${segments.length} · 无人机覆盖 ${sourcePoints.length}`}
          />
          <div className='situation-map-toolbar' aria-label='典型时段选择'>
            <span>服务器典型时段</span>
            <label>星期<select aria-label='星期' value={dayOfWeek} onChange={(event) => setDayOfWeek(Number(event.target.value))}>{DAY_LABELS.map((label, index) => <option key={label} value={index + 1}>{label}</option>)}</select></label>
            <label>时间<select aria-label='时间' value={stepIndex} onChange={(event) => setStepIndex(Number(event.target.value))}>{TIME_SLOTS.map((slot) => <option key={slot.stepIndex} value={slot.stepIndex}>{slot.label}</option>)}</select></label>
          </div>
          <div className='map-legend situation-legend'><span><i className='situation-good' />良好</span><span><i className='situation-slow' />接近饱和 / 缓行</span><span><i className='situation-bad' />过饱和 / 拥堵</span><span><i className='situation-missing' />暂无态势</span><span><Drone size={15} weight='fill' />无人机视频源</span></div>
        </Panel>

        <div className='dashboard-side'>
          <Panel title='重点路口态势' subtitle='服务器典型时段 · 饱和度排序' action={<button className='text-button' onClick={() => navigate('/gis')}>历史分析</button>}>
            {focusIntersections.length
              ? <div className='demo-intersection-list'>{focusIntersections.map((item, index) => { const segment = [...segments.filter((row) => row.inter_id === item.id)].sort((left, right) => (right.delay_index ?? -1) - (left.delay_index ?? -1))[0]; const source = sourcePoints.find((row) => row.intersection_id === item.id); return <button key={item.id} onClick={() => selectIntersection(item)}><span className={`rank rank-${index + 1}`}>{index + 1}</span><div><strong>{item.name}</strong><span>{segment ? `${segment.direction || ''}${segment.name}延误指数 ${formatMetric(segment.delay_index)}` : '暂无路段指标'}</span><small>{source ? `${source.source_count} 路无人机源` : '无无人机覆盖'} · 排队 {formatMetric(segment?.queue_len_est_m, 0)}m</small></div><b className={item.status}>{formatMetric(item.saturation_max)}</b></button> })}</div>
              : <div className='situation-empty'>{situationError ? '服务器态势读取失败；未使用 mock 补齐。' : '当前典型时槽暂无态势数据。'}</div>}
          </Panel>
          <Panel title='重点事件' subtitle='固定演示样例 · 机非冲突与事故测绘' action={<button className='text-button' onClick={() => navigate('/events')}>事件中心</button>}>
            <div className='demo-event-list'>{demoSituation.events.map((event) => <button key={event.id} onClick={() => navigate(event.route)}><span className={event.tone}><ShieldWarning size={16} weight='fill' /></span><div><strong>{event.title}</strong><small>{event.metric}</small></div><time>{event.time}</time></button>)}</div>
          </Panel>
          <Panel title='治理前后复盘' subtitle='固定演示样例 · 同口径对比'>
            <div className='demo-comparison'>{demoSituation.comparison.map((item) => <div key={item.label}><span>{item.label}</span><small>{item.before}</small><ArrowRight size={12} /><strong>{item.after}</strong><b>{item.delta}</b></div>)}</div>
            <button className='review-dispatch-button' disabled={!firstSource} onClick={() => firstSource && openSourceMonitoring(firstSource, true)}><Drone size={15} weight='fill' />再次调度无人机复盘</button>
          </Panel>
        </div>
      </div>

      <div className='dashboard-bottom-strip'>
        <div><Pulse size={16} weight='fill' /><span>态势口径</span><strong>{slotLabel} · 5 分钟典型矩阵{!situation ? ' · 未加载' : ''}</strong></div>
        <div><Database size={16} /><span>服务器只读数据</span><strong>{situationError ? '暂不可用，地图不回退 mock' : situation?.cache?.stale ? '连接失败，展示同槽最近缓存' : `road ${situation?.source?.road_version || '—'} · ${situation?.cache?.status || '加载中'}`}</strong></div>
        <div><Funnel size={16} /><span>指标口径</span><strong>饱和度：良好 &lt; 0.85 · 接近饱和 0.85–0.95 · 过饱和 &gt; 0.95{otherLoadError ? ' · 视频源信息部分不可用' : ''}</strong></div>
      </div>
    </AppShell>
  )
}
