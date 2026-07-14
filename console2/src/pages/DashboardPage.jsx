import { useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ArrowRight, Broadcast, Buildings, CheckCircle, ClipboardText, Database, Drone, Funnel, MapPin, Pulse, ShieldWarning } from '@phosphor-icons/react'
import { AppShell } from '../components/AppShell'
import { CityMap } from '../components/CityMap'
import { DetailDrawer, InfoRow, KpiCard, PageHeader, Panel, QualityNotice, StatusBadge } from '../components/Common'
import { aiEvents, asOf, intersections } from '../data/mockData'
import { useAppState } from '../state/AppState'

const pendingTasks = [
  { id: 'review', title: 'AI 高风险事件待复核', detail: '2 起 · 最早等待 8 分钟', tone: 'critical', path: '/events?severity=critical' },
  { id: 'survey', title: '事故测绘任务待交付', detail: '1 项 · SVY-20260713-006', tone: 'warning', path: '/survey' },
  { id: 'delivery', title: '主平台投递失败待重放', detail: '2 条 · 原幂等键保留', tone: 'degraded', path: '/admin/integration' },
]

export function DashboardPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { state, dispatch } = useAppState()
  const initialIntersectionId = new URLSearchParams(location.search).get('intersection_id')
  const [selected, setSelected] = useState(intersections.find((item) => item.id === initialIntersectionId) || null)
  const [riskFilter, setRiskFilter] = useState('all')
  const visible = useMemo(() => riskFilter === 'all' ? intersections : intersections.filter((item) => item.risk === riskFilter || item.monitor === riskFilter), [riskFilter])
  const selectIntersection = (item) => {
    setSelected(item)
    const params = new URLSearchParams(location.search)
    if (item) params.set('intersection_id', item.id)
    else params.delete('intersection_id')
    navigate(`${location.pathname}${params.size ? `?${params.toString()}` : ''}`, { replace: true })
  }

  return (
    <AppShell pageTitle='工作台首屏'>
      <PageHeader eyebrow='S8 · 全域态势' title='无人机交通态势工作台' description='以城市地图为背景纵览无人机覆盖下的路口态势、平台核心指标与当前待办，再进入单路口专业研判。' meta={`road_data_version · ROAD-2026.07.1 · ${asOf}`}
        actions={<div className='heading-button-row'><button className='secondary-button' onClick={() => dispatch({ type: 'TOGGLE_MAP' })}>{state.mapOffline ? '恢复底图' : '演示底图降级'}</button><button className='primary-button' onClick={() => navigate('/monitoring?intersection_id=370102000101')}>进入值守模式 <ArrowRight size={15} /></button></div>} />

      <div className='kpi-grid five'>
        <KpiCard icon={Broadcast} label='监测覆盖' value='14 / 18' unit='路口' change='+2' detail='78% · 2 降级 · 2 待命' />
        <KpiCard icon={ShieldWarning} label='重点风险路口' value='2' unit='处' change='+1 新增' detail='1 处风险升级' tone='red' />
        <KpiCard icon={Buildings} label='重度拥堵' value='3' unit='处' change='-1 缓解' detail='最长持续 28 分钟' tone='amber' />
        <KpiCard icon={Drone} label='无人机保障' value='3 / 4' unit='在线' change='1 降级' detail='2 执行中 · 1 待命' tone='cyan' />
        <KpiCard icon={CheckCircle} label='数据可信度' value='92.4' unit='%' change='+0.8%' detail='遥测与路网版本已核验' tone='green' />
      </div>

      <div className='dashboard-grid'>
        <Panel className='map-master-panel' title='无人机路口态势纵览' subtitle='城市地图背景 · 覆盖、运行、风险、质量四维状态分开编码'
          action={<div className='map-filter-chips'>{[['all', '全部'], ['critical', '高风险'], ['degraded', '降级']].map(([id, label]) => <button key={id} className={riskFilter === id ? 'active' : ''} onClick={() => setRiskFilter(id)}>{label}</button>)}</div>}>
          <CityMap points={visible} selectedId={selected?.id} onSelect={selectIntersection} offline={state.mapOffline} />
          <div className='map-legend'><span><i className='risk-critical' />高风险</span><span><i className='risk-warning' />关注</span><span><i className='risk-normal' />正常</span><span><b className='ring-running' />正在监测</span><span><b className='ring-degraded' />运行降级</span></div>
        </Panel>

        <div className='dashboard-side'>
          <Panel title='重点路口态势' subtitle='按风险、持续、升级和保障缺口解释排序' action={<button className='text-button' onClick={() => navigate('/events')}>查看全部</button>}>
            <div className='attention-list'>{intersections.slice(0, 4).map((item, index) => <button key={item.id} onClick={() => selectIntersection(item)} className={selected?.id === item.id ? 'active' : ''}><span className={`rank rank-${index + 1}`}>{index + 1}</span><div><strong>{item.name}</strong><span>{item.reason}</span><small>{item.duration} · {item.quality === 'good' ? '数据可信' : '质量降级'} · {item.change}</small></div><StatusBadge value={item.risk} /></button>)}</div>
          </Panel>
          <Panel title='待办任务' subtitle='仅列出平台内技术复核与交付动作'>
            <div className='todo-list'>{pendingTasks.map((task) => <button key={task.id} onClick={() => navigate(task.path)}><span className={`todo-icon ${task.tone}`}><ClipboardText size={16} weight='fill' /></span><div><strong>{task.title}</strong><span>{task.detail}</span></div><ArrowRight size={14} /></button>)}</div>
          </Panel>
          <Panel title='监测保障与系统健康' subtitle='技术明细仅在影响保障时展开'>
            <div className='health-list'><InfoRow label='UAV 任务保障' value='3 / 4' badge='degraded' /><InfoRow label='Pipeline' value='14 / 18' badge='degraded' /><InfoRow label='uav_* 消息链路' value='健康' badge='healthy' /><InfoRow label='road9 / TimescaleDB' value='健康' badge='healthy' /></div>
            <QualityNotice tone='warning' title='2 项影响监测保障'>UAV-M300-03 遥测过期；主平台存在 2 条死信。城市一图继续保持只读监控。</QualityNotice>
          </Panel>
        </div>
      </div>

      <div className='dashboard-bottom-strip'>
        <div><Pulse size={16} weight='fill' /><span>连接状态</span><strong>REST 快照正常 · uav_alerts 已连接 · uav_system 已连接</strong></div>
        <div><Database size={16} /><span>数据窗口</span><strong>10:25:28–10:55:28 · coverage 94.7%</strong></div>
        <div><Funnel size={16} /><span>当前范围</span><strong>{state.scope}</strong></div>
      </div>

      {selected && <DetailDrawer title={selected.name} subtitle='路口关注详情' onClose={() => selectIntersection(null)} footer={<><button className='secondary-button' onClick={() => navigate(`/gis?intersection_id=${selected.id}`)}>进入轨迹研判</button><button className='primary-button' onClick={() => navigate(`/monitoring?intersection_id=${selected.id}`)}>进入实时监测</button></>}>
        <div className='drawer-score'><span className={`risk-orb ${selected.risk}`}><ShieldWarning size={24} weight='fill' /></span><div><strong>{selected.reason}</strong><span>入榜原因 · {selected.duration} · {selected.change}</span></div></div>
        <InfoRow label='权威路口 ID' value={selected.id} /><InfoRow label='路网版本' value='ROAD-2026.07.1' /><InfoRow label='监测状态' value={selected.monitor} badge={selected.monitor} /><InfoRow label='数据质量' value={selected.quality} badge={selected.quality} /><InfoRow label='关联无人机' value={selected.drone || '无'} /><InfoRow label='拥堵指数' value={`${selected.congestion} / 10（候选口径）`} /><InfoRow label='窗口流量' value={`${selected.flow} 辆/h`} />
        <Panel title='最近 AI 事件' className='drawer-inner-panel'>{aiEvents.filter((event) => event.intersectionId === selected.id).map((event) => <button className='drawer-event' key={event.id} onClick={() => navigate(`/events?event_id=${event.id}`)}><MapPin size={15} weight='fill' /><div><strong>{event.title}</strong><span>{event.metric} · {event.occurredAt}</span></div><StatusBadge value={event.severity} /></button>)}</Panel>
        <QualityNotice tone={selected.quality === 'good' ? 'success' : 'warning'} title={selected.quality === 'good' ? '数据可用于当前态势研判' : '数据质量降级'}>页面仅提供 AI 技术研判入口，不承担派警、处置或案件归档。</QualityNotice>
      </DetailDrawer>}
    </AppShell>
  )
}
