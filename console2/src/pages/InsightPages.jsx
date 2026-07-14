import { useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowsClockwise, ArrowSquareOut, CalendarBlank, Camera, ChartLineUp, Check, Clock, Crosshair, DownloadSimple, Funnel, Gauge, ListBullets, MapPin, Pause, Play, RoadHorizon, ShieldWarning, Stack, Truck, VideoCamera, Warning, X } from '@phosphor-icons/react'
import { AppShell } from '../components/AppShell'
import { CityMap } from '../components/CityMap'
import { DataTable, DetailDrawer, FilterBar, InfoRow, KpiCard, PageHeader, Panel, QualityNotice, Segmented, StatusBadge } from '../components/Common'
import { aiEvents, intersections } from '../data/mockData'
import { useAppState } from '../state/AppState'

const trafficSeries = [
  { time: '06:00', flow: 382, congestion: 2.1, speed: 42 }, { time: '08:00', flow: 768, congestion: 6.2, speed: 26 }, { time: '10:00', flow: 842, congestion: 7.2, speed: 24 },
  { time: '12:00', flow: 611, congestion: 4.5, speed: 34 }, { time: '14:00', flow: 584, congestion: 3.8, speed: 37 }, { time: '16:00', flow: 723, congestion: 5.9, speed: 29 }, { time: '18:00', flow: 891, congestion: 7.7, speed: 22 },
]

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
  const { dispatch } = useAppState()
  const initialId = new URLSearchParams(location.search).get('intersection_id')
  const [selected, setSelected] = useState(intersections.find((item) => item.id === initialId) || intersections[0])
  const initialLayer = new URLSearchParams(location.search).get('layer')
  const [layer, setLayer] = useState(['trajectory', 'conflict', 'hotspot', 'zone'].includes(initialLayer) ? initialLayer : 'trajectory')
  const [playing, setPlaying] = useState(true)
  const selectIntersection = (item) => {
    setSelected(item)
    const params = new URLSearchParams(location.search)
    params.set('intersection_id', item.id)
    navigate(`${location.pathname}?${params.toString()}`, { replace: true })
  }
  const selectLayer = (value) => {
    setLayer(value)
    const params = new URLSearchParams(location.search)
    params.set('layer', value)
    params.set('intersection_id', selected.id)
    navigate(`${location.pathname}?${params.toString()}`, { replace: true })
  }
  return <AppShell pageTitle='轨迹研判'>
    <PageHeader eyebrow='S1 / S2 / S5' title='轨迹研判' description='在权威路网版本上研判历史轨迹、冲突点、风险热区和事件时间线；不承担城市级值守总览。' meta='ROAD-2026.07.1 · 10:00–10:55' actions={<button className='secondary-button' onClick={() => dispatch({ type: 'TOAST', value: { tone: 'success', text: '当前轨迹视图已导出，包含路网与质量版本' } })}><DownloadSimple size={15} /> 导出当前视图</button>} />
    <FilterBar result='5 个项目路口 · 27 条有效轨迹'><label>路口<select value={selected.id} onChange={(event) => selectIntersection(intersections.find((item) => item.id === event.target.value))}>{intersections.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>时间窗口<select><option>最近 1 小时</option><option>今天</option><option>自定义</option></select></label><Segmented value={layer} onChange={selectLayer} options={[{ value: 'trajectory', label: '历史轨迹' }, { value: 'conflict', label: '事件回放' }, { value: 'hotspot', label: '风险热区' }, { value: 'zone', label: '执法区域' }]} /></FilterBar>
    <div className='gis-layout'><Panel className='gis-map-panel' title={selected.name} subtitle={`inter_id ${selected.id} · GCJ02 · 数据质量 ${selected.quality}`}><CityMap points={intersections} selectedId={selected.id} onSelect={selectIntersection} showHeat={layer === 'hotspot'} /><div className={`spatial-overlay overlay-${layer}`}><span className='path path-a' /><span className='path path-b' /><span className='conflict-node'><ShieldWarning size={16} weight='fill' /> TTC 1.2s</span></div><div className='replay-bar'><button onClick={() => setPlaying(!playing)}>{playing ? <Pause size={15} weight='fill' /> : <Play size={15} weight='fill' />}</button><strong>{playing ? '回放中' : '已暂停'}</strong><div className='replay-track'><i style={{ width: playing ? '78%' : '52%' }} /></div><span>10:41:20 / 10:55:28</span></div></Panel>
      <div className='gis-sidebar'><Panel title='空间对象摘要'><div className='summary-quad'><div><strong>27</strong><span>有效轨迹</span></div><div><strong>3</strong><span>冲突点</span></div><div><strong>2</strong><span>热区簇</span></div><div><strong>1.8%</strong><span>unmapped</span></div></div></Panel><Panel title='路口空间上下文'><InfoRow label='进口 Link' value='4 / 4 已映射' /><InfoRow label='视觉车道绑定' value='11 / 12' badge='degraded' /><InfoRow label='坐标质量' value='2.1m 估计误差' badge='good' /><InfoRow label='有效覆盖' value='94.7%' /></Panel><Panel title='关键空间事件'>{aiEvents.slice(0, 3).map((event) => <button className='compact-event' key={event.id} onClick={() => navigate(`/events?event_id=${event.id}`)}><StatusBadge value={event.severity} /><div><strong>{event.title}</strong><span>{event.metric} · {event.occurredAt}</span></div></button>)}</Panel></div></div>
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
  const { state, dispatch } = useAppState()
  const initialParams = new URLSearchParams(location.search)
  const initialId = initialParams.get('event_id')
  const [selected, setSelected] = useState(state.events.find((item) => item.id === initialId) || null)
  const [severity, setSeverity] = useState(['critical', 'warning'].includes(initialParams.get('severity')) ? initialParams.get('severity') : 'all')
  const [delivery, setDelivery] = useState(['delivery_failed', 'delivered'].includes(initialParams.get('delivery')) ? initialParams.get('delivery') : 'all')
  const [intersection, setIntersection] = useState(initialParams.get('intersection_id') || 'all')
  const [query, setQuery] = useState('')
  const rows = useMemo(() => state.events.filter((item) =>
    (severity === 'all' || item.severity === severity) &&
    (delivery === 'all' || item.delivery === delivery) &&
    (intersection === 'all' || item.intersectionId === intersection) &&
    (!query.trim() || `${item.id} ${item.title}`.toLowerCase().includes(query.trim().toLowerCase()))
  ), [state.events, severity, delivery, intersection, query])
  const selectedEvent = selected ? state.events.find((item) => item.id === selected.id) || selected : null
  const openEvent = (item) => {
    setSelected(item)
    const params = new URLSearchParams(location.search)
    if (item) params.set('event_id', item.id)
    else params.delete('event_id')
    navigate(`${location.pathname}${params.size ? `?${params.toString()}` : ''}`, { replace: true })
  }
  return <AppShell pageTitle='AI 事件中心'>
    <PageHeader eyebrow='S2 / S4 / S6' title='AI 事件中心' description='统一查看 AI 事件、证据质量、主平台投递和技术复核；复核结果不代表警情处置或违法认定。' meta={`${state.events.length} 起事件 · 2 起待复核`} actions={<button className='secondary-button' onClick={() => dispatch({ type: 'TOAST', value: { tone: 'success', text: '技术台账已导出，隐私字段保持脱敏' } })}><DownloadSimple size={15} /> 导出技术台账</button>} />
    <FilterBar result={`显示 ${rows.length} / ${state.events.length} 起`} onReset={() => { setSeverity('all'); setDelivery('all'); setIntersection('all'); setQuery('') }}><Segmented value={severity} onChange={setSeverity} options={[{ value: 'all', label: '全部' }, { value: 'critical', label: '高风险' }, { value: 'warning', label: '关注' }]} /><label>投递状态<select aria-label='投递状态' value={delivery} onChange={(event) => setDelivery(event.target.value)}><option value='all'>全部状态</option><option value='delivery_failed'>投递失败</option><option value='delivered'>已投递</option></select></label><label>路口<select aria-label='事件路口' value={intersection} onChange={(event) => setIntersection(event.target.value)}><option value='all'>全部项目路口</option>{intersections.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className='search-field'><Funnel size={15} /><input aria-label='事件搜索' value={query} onChange={(event) => setQuery(event.target.value)} placeholder='事件 ID / 标题' /></label></FilterBar>
    <Panel title='实时 AI 事件' subtitle='业务时间排序 · WebSocket 增量仅用于体验，REST 快照为恢复基线'><DataTable columns={eventColumns(openEvent)} rows={rows} onRowClick={openEvent} /></Panel>
    {selectedEvent && <DetailDrawer wide title={selectedEvent.title} subtitle={selectedEvent.id} onClose={() => openEvent(null)} footer={<><button className='danger-button' onClick={() => dispatch({ type: 'REVIEW_EVENT', id: selectedEvent.id, value: 'rejected' })}><X size={15} /> 驳回 AI 结果</button><button className='primary-button' onClick={() => dispatch({ type: 'REVIEW_EVENT', id: selectedEvent.id, value: 'confirmed' })}><Check size={15} /> 技术确认</button></>}>
      <div className='event-hero'><div className='event-snapshot'><img src='/assets/uav-intersection-night.png' alt='AI 事件关联视频帧' /><span><VideoCamera size={14} /> 原始帧 #18274 · 10:52:16.208</span></div><div className='event-primary-metrics'><div><span>TTC</span><strong>1.2s</strong></div><div><span>PET</span><strong>0.8s</strong></div><div><span>风险分</span><strong>86</strong></div><div><span>置信度</span><strong>94%</strong></div></div></div>
      <div className='detail-two-col'><Panel title='事件与质量'><InfoRow label='业务时间' value={`2026-07-13 ${selectedEvent.occurredAt}`} /><InfoRow label='路口' value={intersections.find((item) => item.id === selectedEvent.intersectionId)?.name} /><InfoRow label='证据完整性' value={selectedEvent.evidence} badge={selectedEvent.evidence} /><InfoRow label='坐标质量' value='GCJ02 · 2.1m 估计误差' badge={selectedEvent.quality} /><InfoRow label='模型 / 规则' value={`conflict-v11 / ${selectedEvent.ruleVersion}`} /></Panel><Panel title='投递与反馈'><InfoRow label='投递状态' value={selectedEvent.delivery} badge={selectedEvent.delivery} /><InfoRow label='主平台映射' value={selectedEvent.delivery === 'delivered' ? 'PLT-AI-804182' : '待获取'} /><InfoRow label='Schema' value={selectedEvent.schemaVersion} /><InfoRow label='幂等键' value='sha256:b281…91dd' /><InfoRow label='技术复核' value={selectedEvent.review} badge={selectedEvent.review} /></Panel></div>
      <Panel title='证据与状态时间线'><div className='state-timeline'>{['AI 结果生成 10:52:16.208', '证据包完整性校验 10:52:16.419', '持久化出站队列 10:52:16.721', '主平台回执 10:52:17.604', selectedEvent.review === 'pending' ? '等待技术复核' : `技术复核：${selectedEvent.review}`].map((item, index) => <div key={item} className={index === 4 ? 'current' : ''}><i /><span>{item}</span></div>)}</div></Panel>
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
