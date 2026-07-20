import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import { ArrowRight, Broadcast, Buildings, CheckCircle, ClipboardText, Database, Drone, Funnel, MapPin, Pulse, ShieldWarning, WarningCircle } from '@phosphor-icons/react'
import { AppShell } from '../components/AppShell'
import { CityMap } from '../components/CityMap'
import { DetailDrawer, EmptyState, InfoRow, KpiCard, PageHeader, Panel, QualityNotice, StatusBadge } from '../components/Common'
import { apiErrorMessage, platformApi } from '../lib/api'

const kpiIcons = {
  monitoring_coverage: Broadcast,
  priority_risk: ShieldWarning,
  severe_congestion: Buildings,
  drone_assurance: Drone,
  data_trust: CheckCircle,
}

const taskLabels = {
  ai_review: 'AI 技术复核',
  survey_delivery: '事故测绘交付',
  integration_replay: '集成失败重放',
  configuration_check: '项目配置核验',
}

function kpiValue(item) {
  if (item.value !== null && item.value !== undefined) return item.value
  return '待冻结'
}

export function dashboardSourceStatus(source, pipeline) {
  if (pipeline?.status === 'running') return 'running'
  if (source.enabled === false) return 'disabled'
  if (source.validation_status === 'invalid') return 'invalid'
  if (source.validation_status === 'degraded') return 'degraded'
  return 'ready'
}

export function buildDashboardSourcePoints({ sources = [], drones = [], intersections = [], pipelines = [] }) {
  const droneById = new Map(drones.map((item) => [item.id, item]))
  const intersectionById = new Map(intersections.map((item) => [item.id, item]))
  return sources.flatMap((source) => {
    const drone = droneById.get(source.drone_id)
    const pipeline = pipelines.find((item) => item.source_profile_id === source.profile_id && item.status === 'running')
    const intersectionId = pipeline?.intersection_id || drone?.default_inter_id || drone?.current_intersection_id
    const intersection = intersectionById.get(intersectionId)
    const lat = Number(intersection?.lat ?? drone?.last_telemetry?.latitude)
    const lon = Number(intersection?.lon ?? drone?.last_telemetry?.longitude)
    if (!intersectionId || !Number.isFinite(lat) || !Number.isFinite(lon)) return []
    return [{
      id: source.profile_id,
      source_profile_id: source.profile_id,
      intersection_id: intersectionId,
      drone_id: source.drone_id,
      name: source.display_name || source.video?.location_hint || source.profile_id,
      drone_name: drone?.name || source.drone_id,
      intersection_name: drone?.intersection_name || intersection?.name || intersectionId,
      lat,
      lon,
      source_status: dashboardSourceStatus(source, pipeline),
      validation_status: source.validation_status,
      map_coordinate_status: intersection?.map_coordinate_status || 'telemetry',
    }]
  })
}

export function DashboardPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const initialIntersectionId = new URLSearchParams(location.search).get('intersection_id')
  const [selectedId, setSelectedId] = useState(initialIntersectionId)
  const intersectionParams = { limit: 500 }
  const queryOptions = { refetchInterval: 15_000, retry: (count, error) => error?.response?.status !== 401 && count < 2 }
  const overviewQuery = useQuery({ queryKey: ['dashboard', 'overview'], queryFn: platformApi.dashboardOverview, ...queryOptions })
  const intersectionsQuery = useQuery({ queryKey: ['dashboard', 'intersections', intersectionParams], queryFn: () => platformApi.dashboardIntersections(intersectionParams), placeholderData: (previous) => previous, ...queryOptions })
  const dronesQuery = useQuery({ queryKey: ['dashboard', 'drones'], queryFn: platformApi.dashboardDrones, ...queryOptions })
  const sourcesQuery = useQuery({ queryKey: ['dashboard', 'sources'], queryFn: platformApi.sources, ...queryOptions })
  const sourceDronesQuery = useQuery({ queryKey: ['dashboard', 'source-drones'], queryFn: platformApi.drones, ...queryOptions })
  const pipelinesQuery = useQuery({ queryKey: ['dashboard', 'pipelines'], queryFn: platformApi.pipelines, ...queryOptions })
  const overview = overviewQuery.data
  const intersections = intersectionsQuery.data?.items || []
  const selected = intersections.find((item) => item.id === selectedId) || null
  const sources = Array.isArray(sourcesQuery.data) ? sourcesQuery.data : []
  const sourceDrones = Array.isArray(sourceDronesQuery.data) ? sourceDronesQuery.data : []
  const pipelines = Array.isArray(pipelinesQuery.data) ? pipelinesQuery.data : []
  const mapPoints = useMemo(
    () => buildDashboardSourcePoints({ sources, drones: sourceDrones, intersections, pipelines }),
    [sources, sourceDrones, intersections, pipelines],
  )
  const testCoordinateCount = new Set(mapPoints.filter((item) => item.map_coordinate_status === 'test').map((item) => item.intersection_id)).size
  const selectIntersection = (item) => {
    const id = item?.id || null
    setSelectedId(id)
    const params = new URLSearchParams(location.search)
    if (id) params.set('intersection_id', id)
    else params.delete('intersection_id')
    navigate(`${location.pathname}${params.size ? `?${params.toString()}` : ''}`, { replace: true })
  }
  const openSourceMonitoring = (item) => {
    if (item?.source_profile_id && item?.intersection_id) navigate(`/monitoring?intersection_id=${encodeURIComponent(item.intersection_id)}&source_profile_id=${encodeURIComponent(item.source_profile_id)}`)
  }
  const firstSource = mapPoints[0]
  const loading = overviewQuery.isLoading || intersectionsQuery.isLoading || dronesQuery.isLoading || sourcesQuery.isLoading || sourceDronesQuery.isLoading || pipelinesQuery.isLoading
  const loadError = overviewQuery.error || intersectionsQuery.error || dronesQuery.error || sourcesQuery.error || sourceDronesQuery.error || pipelinesQuery.error
  const asOf = overview?.as_of ? new Date(overview.as_of).toLocaleString('zh-CN', { hour12: false }) : '等待 road9 快照'
  const asOfTime = overview?.as_of ? new Date(overview.as_of).toLocaleTimeString('zh-CN', { hour12: false }) : '等待快照'
  const roadVersion = overview?.road_data_versions?.join('、') || '无可用版本'
  const onlineDrones = (dronesQuery.data?.items || []).filter((item) => item.status === 'online').length

  return (
    <AppShell pageTitle='工作台首屏' topContext={{ scope: overview?.project_scope || '授权范围未加载', window: '最近 30 分钟 · 固定工程窗口', asOf: asOfTime }}>
      <PageHeader eyebrow='S8 · 全域态势' title='无人机交通态势工作台' description='以 road9 事实纵览当前授权范围；验收测试坐标明确标记，不冒充权威坐标，也不使用无来源随机点位。'
        meta={`road_data_version · ${roadVersion} · ${asOf}`}
        actions={<div className='heading-button-row'><button className='primary-button' disabled={!firstSource} onClick={() => firstSource && openSourceMonitoring(firstSource)}>进入值守模式 <ArrowRight size={15} /></button></div>} />

      {loading && <QualityNotice title='正在加载态势数据'>正在同步 KPI、路口、任务和无人机数据。</QualityNotice>}
      {loadError && <QualityNotice tone='danger' title='主任首屏聚合不可用'>{apiErrorMessage(loadError, 'DashboardReadModel 暂不可用')}</QualityNotice>}
      {!loading && intersectionsQuery.isFetching && <QualityNotice title='正在更新当前范围'>保留上一版快照，查询完成后原位更新。</QualityNotice>}

      <div className='kpi-grid five'>
        {(overview?.kpis || []).map((item, index) => <KpiCard key={item.id} icon={kpiIcons[item.id] || Broadcast} label={item.label} value={kpiValue(item)} unit={item.value == null ? '' : item.id === 'data_trust' ? '%' : '处'} change={item.quality} detail={`${item.numerator ?? '—'} / ${item.denominator ?? '—'} · ${item.reason}`} tone={index === 1 ? 'red' : index === 2 ? 'amber' : index === 3 ? 'cyan' : index === 4 ? 'green' : 'blue'} />)}
      </div>

      <div className='dashboard-grid'>
        <Panel className='map-master-panel'>
          {mapPoints.length > 0 ? <CityMap points={mapPoints} onSelect={openSourceMonitoring} markerType='drone' coordinateLabel={testCoordinateCount ? `无人机视频源 ${mapPoints.length} 路 · 验收测试坐标 ${testCoordinateCount} 处 · WGS84` : `无人机视频源 ${mapPoints.length} 路 · 遥测坐标 · WGS84`} /> : <div className='map-offline'><WarningCircle size={38} weight='duotone' /><strong>暂无可上图的无人机视频源</strong><span>已登记视频源尚未绑定可用路口或遥测坐标。</span></div>}
          <div className='map-legend'><span><Drone size={15} weight='fill' />无人机视频源</span><span><i className='source-running' />运行中</span><span><i className='source-ready' />可用离线</span><span><i className='source-degraded' />数据降级</span><span><i className='source-invalid' />无效</span><span><i className='source-disabled' />已停用</span></div>
        </Panel>

        <div className='dashboard-side'>
          <Panel title='重点路口态势' subtitle='仅展示可解释的风险、质量或配置事实' action={<button className='text-button' onClick={() => navigate('/events')}>查看全部</button>}>
            {(overview?.attention || []).length === 0 ? <EmptyState icon={ShieldWarning} title='暂无可复算关注项' description='当前范围没有需要关注的风险或质量事项。' /> : <div className='attention-list'>{overview.attention.map((item, index) => {
              const intersection = intersections.find((row) => row.inter_id === item.inter_id)
              return <button key={item.id} onClick={() => intersection ? selectIntersection(intersection) : navigate(item.target_route)} className={selected?.id === item.inter_id ? 'active' : ''}><span className={`rank rank-${index + 1}`}>{index + 1}</span><div><strong>{intersection?.name || '项目范围配置'}</strong><span>{item.reason}</span><small>{item.kind} · {item.quality}</small></div><StatusBadge value={item.quality} /></button>
            })}</div>}
          </Panel>
          <Panel title='待办任务' subtitle='仅聚合本平台可执行的技术动作'>
            {(overview?.pending_tasks || []).length === 0 ? <EmptyState icon={ClipboardText} title='暂无平台内待办' description='不复制主平台派警、处置、结案或处罚任务。' /> : <div className='todo-list'>{overview.pending_tasks.map((task) => <button key={task.task_type} onClick={() => navigate(task.target_route)}><span className={`todo-icon ${task.quality}`}><ClipboardText size={16} weight='fill' /></span><div><strong>{taskLabels[task.task_type] || task.task_type}</strong><span>{task.count} 项 · {task.quality}</span></div><ArrowRight size={14} /></button>)}</div>}
          </Panel>
          <Panel title='监测保障与系统健康' subtitle='只展示会影响主任判断的事实摘要'>
            <div className='health-list'><InfoRow label='已登记视频源' value={sources.length} badge={sources.length ? 'unverified' : 'missing'} /><InfoRow label='可上图视频源' value={mapPoints.length} badge={mapPoints.length ? 'verified' : 'missing'} /><InfoRow label='验收测试坐标' value={overview?.health?.test_coordinate_intersections ?? 0} badge={overview?.health?.test_coordinate_intersections ? 'unverified' : 'missing'} /><InfoRow label='新鲜遥测无人机' value={`${onlineDrones} / ${dronesQuery.data?.items?.length ?? 0}`} badge={onlineDrones ? 'unverified' : 'offline'} /><InfoRow label='road9 聚合' value={overview?.health?.database || 'unavailable'} badge={overview?.health?.database || 'degraded'} /></div>
            <QualityNotice tone={overview?.health?.status === 'healthy' ? 'success' : 'warning'} title={overview?.health?.status === 'healthy' ? '当前聚合链路可用' : '当前项目范围降级'}>{overview?.health?.test_coordinate_intersections || 0} 个验收测试坐标，{overview?.health?.isolated_intersections || 0} 个坐标隔离，{overview?.health?.failed_delivery_items || 0} 个投递失败项；测试点位不作为权威路网坐标。</QualityNotice>
          </Panel>
        </div>
      </div>

      <div className='dashboard-bottom-strip'>
        <div><Pulse size={16} weight='fill' /><span>连接状态</span><strong>{loadError ? 'REST 聚合不可用' : 'REST 聚合快照已加载'}</strong></div>
        <div><Database size={16} /><span>数据窗口</span><strong>{overview ? `${new Date(overview.window_start).toLocaleTimeString('zh-CN', { hour12: false })}–${new Date(overview.window_end).toLocaleTimeString('zh-CN', { hour12: false })}` : '—'} · coverage 未冻结</strong></div>
        <div><Funnel size={16} /><span>当前范围</span><strong>{overview?.project_scope || '未加载'}</strong></div>
      </div>

      {selected && <DetailDrawer title={selected.name} subtitle='路口事实详情' onClose={() => selectIntersection(null)} footer={<><button className='secondary-button' onClick={() => navigate(`/gis?intersection_id=${selected.id}`)}>进入轨迹研判</button><button className='primary-button' onClick={() => navigate(`/monitoring?intersection_id=${selected.id}`)}>进入实时监测</button></>}>
        <div className='drawer-score'><span className={`risk-orb ${selected.risk}`}><ShieldWarning size={24} weight='fill' /></span><div><strong>{selected.risk === 'unknown' ? '风险未知' : `${selected.risk} 风险事实`}</strong><span>不把缺失或过期数据解释为正常</span></div></div>
        <InfoRow label='权威路口 ID' value={selected.id} /><InfoRow label='路网版本' value={selected.road_data_version} /><InfoRow label='监测状态' value={selected.monitor} badge={selected.monitor} /><InfoRow label='数据质量' value={selected.quality} badge={selected.quality} /><InfoRow label='关联无人机' value={selected.drone_id || '无'} /><InfoRow label='拥堵指数' value={selected.metric?.congestion_index ?? '未计算/未批准'} /><InfoRow label='最后态势时间' value={selected.last_metric_at || '无数据'} />
        <Panel title='最近 AI 事件' className='drawer-inner-panel'>{selected.events.length === 0 ? <EmptyState icon={MapPin} title='当前窗口无事件事实' description='当前时间窗口没有关联事件。' /> : selected.events.map((event) => <button className='drawer-event' key={event.id} onClick={() => navigate(`/events?event_id=${event.id}`)}><MapPin size={15} weight='fill' /><div><strong>{event.event_type}</strong><span>{event.quality_status} · {event.occurred_at || '时间缺失'}</span></div><StatusBadge value={event.review_status} /></button>)}</Panel>
        <QualityNotice tone={selected.quality === 'verified' ? 'success' : 'warning'} title={selected.quality === 'verified' ? '当前事实可用' : '数据质量未验证'}>页面仅提供 AI 技术研判入口，不承担派警、处置、案件归档或处罚。</QualityNotice>
      </DetailDrawer>}
    </AppShell>
  )
}
