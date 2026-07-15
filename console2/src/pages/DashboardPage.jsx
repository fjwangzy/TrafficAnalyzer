import { useState } from 'react'
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

export function DashboardPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const initialIntersectionId = new URLSearchParams(location.search).get('intersection_id')
  const [selectedId, setSelectedId] = useState(initialIntersectionId)
  const [riskFilter, setRiskFilter] = useState('all')
  const intersectionParams = riskFilter === 'critical' ? { risk: 'critical', limit: 500 } : riskFilter === 'degraded' ? { monitor: 'degraded', limit: 500 } : { limit: 500 }
  const queryOptions = { refetchInterval: 15_000, retry: (count, error) => error?.response?.status !== 401 && count < 2 }
  const overviewQuery = useQuery({ queryKey: ['dashboard', 'overview'], queryFn: platformApi.dashboardOverview, ...queryOptions })
  const intersectionsQuery = useQuery({ queryKey: ['dashboard', 'intersections', intersectionParams], queryFn: () => platformApi.dashboardIntersections(intersectionParams), placeholderData: (previous) => previous, ...queryOptions })
  const dronesQuery = useQuery({ queryKey: ['dashboard', 'drones'], queryFn: platformApi.dashboardDrones, ...queryOptions })
  const overview = overviewQuery.data
  const intersections = intersectionsQuery.data?.items || []
  const selected = intersections.find((item) => item.id === selectedId) || null
  const mapPoints = intersections.filter((item) => item.map_eligible)
  const selectIntersection = (item) => {
    const id = item?.id || null
    setSelectedId(id)
    const params = new URLSearchParams(location.search)
    if (id) params.set('intersection_id', id)
    else params.delete('intersection_id')
    navigate(`${location.pathname}${params.size ? `?${params.toString()}` : ''}`, { replace: true })
  }
  const firstIntersection = mapPoints[0] || intersections[0]
  const loading = overviewQuery.isLoading || intersectionsQuery.isLoading || dronesQuery.isLoading
  const loadError = overviewQuery.error || intersectionsQuery.error || dronesQuery.error
  const asOf = overview?.as_of ? new Date(overview.as_of).toLocaleString('zh-CN', { hour12: false }) : '等待 road9 快照'
  const asOfTime = overview?.as_of ? new Date(overview.as_of).toLocaleTimeString('zh-CN', { hour12: false }) : '等待快照'
  const roadVersion = overview?.road_data_versions?.join('、') || '无可用版本'
  const onlineDrones = (dronesQuery.data?.items || []).filter((item) => item.status === 'online').length

  return (
    <AppShell pageTitle='工作台首屏' topContext={{ scope: overview?.project_scope || '授权范围未加载', window: '最近 30 分钟 · 固定工程窗口', asOf: asOfTime }}>
      <PageHeader eyebrow='S8 · 全域态势' title='无人机交通态势工作台' description='以 road9 事实纵览当前授权范围；口径或权威坐标未冻结时明确降级，不使用前端模拟 KPI 和点位。'
        meta={`road_data_version · ${roadVersion} · ${asOf}`}
        actions={<div className='heading-button-row'><button className='primary-button' disabled={!firstIntersection} onClick={() => firstIntersection && navigate(`/monitoring?intersection_id=${firstIntersection.id}`)}>进入值守模式 <ArrowRight size={15} /></button></div>} />

      {loading && <QualityNotice title='正在加载 road9 聚合快照'>KPI、路口、任务和无人机使用同一类只读事实源，页面不会先填充演示数字。</QualityNotice>}
      {loadError && <QualityNotice tone='danger' title='主任首屏聚合不可用'>{apiErrorMessage(loadError, 'DashboardReadModel 暂不可用')}</QualityNotice>}
      {!loading && intersectionsQuery.isFetching && <QualityNotice title='正在应用服务端范围筛选'>保留上一版快照，查询完成后原位更新；不会在筛选期间清空为 0。</QualityNotice>}
      {overview && <QualityNotice tone='warning' title='I5 内部工程口径'>{overview.coverage_definition_status}；覆盖、拥堵、保障和综合可信度未获批准时显示“待冻结”，不以 0 或百分比代替。</QualityNotice>}

      <div className='kpi-grid five'>
        {(overview?.kpis || []).map((item, index) => <KpiCard key={item.id} icon={kpiIcons[item.id] || Broadcast} label={item.label} value={kpiValue(item)} unit={item.value == null ? '' : item.id === 'data_trust' ? '%' : '处'} change={item.quality} detail={`${item.numerator ?? '—'} / ${item.denominator ?? '—'} · ${item.reason}`} tone={index === 1 ? 'red' : index === 2 ? 'amber' : index === 3 ? 'cyan' : index === 4 ? 'green' : 'blue'} />)}
      </div>

      <div className='dashboard-grid'>
        <Panel className='map-master-panel' title='无人机路口态势纵览' subtitle='仅展示质量已验证且具备权威坐标的项目路口'
          action={<div className='map-filter-chips' role='group' aria-label='地图状态筛选'>{[['all', '全部'], ['critical', '高风险'], ['degraded', '降级']].map(([id, label]) => <button key={id} className={riskFilter === id ? 'active' : ''} onClick={() => setRiskFilter(id)}>{label}</button>)}</div>}>
          {mapPoints.length > 0 ? <CityMap points={mapPoints} selectedId={selected?.id} onSelect={selectIntersection} coordinateLabel='已验证 WGS84 · OSM 开发底图' /> : <div className='map-offline'><WarningCircle size={38} weight='duotone' /><strong>暂无可上图的权威路口坐标</strong><span>{intersectionsQuery.data?.isolated || 0} 个路口因 RoadContext、坐标参考或坐标值未验证被隔离；不按数组序号或遥测锚点随机上图。</span></div>}
          <div className='map-legend'><span><i className='risk-critical' />高风险</span><span><i className='risk-warning' />关注</span><span><i className='risk-normal' />正常</span><span><b className='ring-running' />正在监测</span><span><b className='ring-degraded' />运行降级</span></div>
        </Panel>

        <div className='dashboard-side'>
          <Panel title='重点路口态势' subtitle='仅展示可解释的风险、质量或配置事实' action={<button className='text-button' onClick={() => navigate('/events')}>查看全部</button>}>
            {(overview?.attention || []).length === 0 ? <EmptyState icon={ShieldWarning} title='暂无可复算关注项' description='没有用模拟风险或技术运维指标填充榜单。' /> : <div className='attention-list'>{overview.attention.map((item, index) => {
              const intersection = intersections.find((row) => row.inter_id === item.inter_id)
              return <button key={item.id} onClick={() => intersection ? selectIntersection(intersection) : navigate(item.target_route)} className={selected?.id === item.inter_id ? 'active' : ''}><span className={`rank rank-${index + 1}`}>{index + 1}</span><div><strong>{intersection?.name || '项目范围配置'}</strong><span>{item.reason}</span><small>{item.kind} · {item.quality}</small></div><StatusBadge value={item.quality} /></button>
            })}</div>}
          </Panel>
          <Panel title='待办任务' subtitle='仅聚合本平台可执行的技术动作'>
            {(overview?.pending_tasks || []).length === 0 ? <EmptyState icon={ClipboardText} title='暂无平台内待办' description='不复制主平台派警、处置、结案或处罚任务。' /> : <div className='todo-list'>{overview.pending_tasks.map((task) => <button key={task.task_type} onClick={() => navigate(task.target_route)}><span className={`todo-icon ${task.quality}`}><ClipboardText size={16} weight='fill' /></span><div><strong>{taskLabels[task.task_type] || task.task_type}</strong><span>{task.count} 项 · {task.quality}</span></div><ArrowRight size={14} /></button>)}</div>}
          </Panel>
          <Panel title='监测保障与系统健康' subtitle='只展示会影响主任判断的事实摘要'>
            <div className='health-list'><InfoRow label='项目路口快照' value={overview?.health?.project_intersections ?? '—'} badge={overview?.health?.project_intersections ? 'unverified' : 'missing'} /><InfoRow label='可上图路口' value={overview?.health?.map_eligible_intersections ?? '—'} badge={overview?.health?.map_eligible_intersections ? 'verified' : 'missing'} /><InfoRow label='新鲜遥测无人机' value={`${onlineDrones} / ${dronesQuery.data?.items?.length ?? 0}`} badge={onlineDrones ? 'unverified' : 'offline'} /><InfoRow label='road9 聚合' value={overview?.health?.database || 'unavailable'} badge={overview?.health?.database || 'degraded'} /></div>
            <QualityNotice tone={overview?.health?.status === 'healthy' ? 'success' : 'warning'} title={overview?.health?.status === 'healthy' ? '当前聚合链路可用' : '当前项目范围降级'}>{overview?.health?.isolated_intersections || 0} 个坐标隔离，{overview?.health?.failed_delivery_items || 0} 个投递失败项；主平台不可用时首屏保持只读。</QualityNotice>
          </Panel>
        </div>
      </div>

      <div className='dashboard-bottom-strip'>
        <div><Pulse size={16} weight='fill' /><span>连接状态</span><strong>{loadError ? 'REST 聚合不可用' : 'REST 聚合快照已加载 · 全局增量待 I5 后续接入'}</strong></div>
        <div><Database size={16} /><span>数据窗口</span><strong>{overview ? `${new Date(overview.window_start).toLocaleTimeString('zh-CN', { hour12: false })}–${new Date(overview.window_end).toLocaleTimeString('zh-CN', { hour12: false })}` : '—'} · coverage 未冻结</strong></div>
        <div><Funnel size={16} /><span>当前范围</span><strong>{overview?.project_scope || '未加载'}</strong></div>
      </div>

      {selected && <DetailDrawer title={selected.name} subtitle='路口事实详情' onClose={() => selectIntersection(null)} footer={<><button className='secondary-button' onClick={() => navigate(`/gis?intersection_id=${selected.id}`)}>进入轨迹研判</button><button className='primary-button' onClick={() => navigate(`/monitoring?intersection_id=${selected.id}`)}>进入实时监测</button></>}>
        <div className='drawer-score'><span className={`risk-orb ${selected.risk}`}><ShieldWarning size={24} weight='fill' /></span><div><strong>{selected.risk === 'unknown' ? '风险未知' : `${selected.risk} 风险事实`}</strong><span>不把缺失或过期数据解释为正常</span></div></div>
        <InfoRow label='权威路口 ID' value={selected.id} /><InfoRow label='路网版本' value={selected.road_data_version} /><InfoRow label='监测状态' value={selected.monitor} badge={selected.monitor} /><InfoRow label='数据质量' value={selected.quality} badge={selected.quality} /><InfoRow label='关联无人机' value={selected.drone_id || '无'} /><InfoRow label='拥堵指数' value={selected.metric?.congestion_index ?? '未计算/未批准'} /><InfoRow label='最后态势时间' value={selected.last_metric_at || '无数据'} />
        <Panel title='最近 AI 事件' className='drawer-inner-panel'>{selected.events.length === 0 ? <EmptyState icon={MapPin} title='当前窗口无事件事实' description='未使用前端示例事件。' /> : selected.events.map((event) => <button className='drawer-event' key={event.id} onClick={() => navigate(`/events?event_id=${event.id}`)}><MapPin size={15} weight='fill' /><div><strong>{event.event_type}</strong><span>{event.quality_status} · {event.occurred_at || '时间缺失'}</span></div><StatusBadge value={event.review_status} /></button>)}</Panel>
        <QualityNotice tone={selected.quality === 'verified' ? 'success' : 'warning'} title={selected.quality === 'verified' ? '当前事实满足内部显示门禁' : '数据质量未验证'}>页面仅提供 AI 技术研判入口，不承担派警、处置、案件归档或处罚。</QualityNotice>
      </DetailDrawer>}
    </AppShell>
  )
}
