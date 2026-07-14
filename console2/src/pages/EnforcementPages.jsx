import { useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Check, Crosshair, DownloadSimple, Funnel, Gauge, MapPin, PencilSimple, Plus, ShieldCheck, Truck, Warning, X } from '@phosphor-icons/react'
import { AppShell } from '../components/AppShell'
import { CityMap } from '../components/CityMap'
import { DataTable, DetailDrawer, FilterBar, InfoRow, KpiCard, PageHeader, Panel, QualityNotice, Segmented, StatusBadge } from '../components/Common'
import { aiEvents, enforcementZones, intersections } from '../data/mockData'
import { useAppState } from '../state/AppState'

const clues = [
  { id: 'CLUE-0713-022', type: '货车限行', vehicle: 'truck', plate: '鲁A·8K2**', zone: '历下核心区货车限行', speed: '34 km/h', radar: '—', review: 'pending', delivery: 'delivery_failed', evidence: 'partial', quality: 'degraded', time: '10:41:05' },
  { id: 'CLUE-0713-021', type: '疑似超速', vehicle: 'non_truck', plate: '鲁A·73F**', zone: '快速路速度观测区', speed: '72 km/h', radar: '74 km/h', review: 'pending', delivery: 'delivered', evidence: 'complete', quality: 'good', time: '10:32:48' },
  { id: 'CLUE-0713-018', type: '禁停区域滞留', vehicle: 'unknown', plate: '待人工核验', zone: '学校周边禁停区', speed: '0 km/h', radar: '—', review: 'rejected', delivery: 'delivered', evidence: 'complete', quality: 'good', time: '09:58:21' },
]

function EnforcementTabs() {
  const location = useLocation()
  const navigate = useNavigate()
  const active = location.pathname.endsWith('/zones') ? 'zones' : location.pathname.endsWith('/trucks') ? 'trucks' : 'events'
  return <div className='page-tabs' aria-label='执法工作台视图'>{[
    ['events', '线索事件', '/enforcement'],
    ['trucks', '货车专题', '/enforcement/trucks'],
    ['zones', '区域与规则', '/enforcement/zones'],
  ].map(([id, label, path]) => <button key={id} className={active === id ? 'active' : ''} onClick={() => navigate(path)}>{label}</button>)}</div>
}

export function EnforcementEventsPage() {
  const { dispatch } = useAppState()
  const location = useLocation()
  const navigate = useNavigate()
  const initialId = new URLSearchParams(location.search).get('event_id')
  const [clueRows, setClueRows] = useState(clues)
  const [selected, setSelected] = useState(clues.find((item) => item.id === initialId) || null)
  const [filter, setFilter] = useState('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [query, setQuery] = useState('')
  const selectedClue = selected ? clueRows.find((item) => item.id === selected.id) || selected : null
  const rows = useMemo(() => clueRows.filter((item) =>
    (filter === 'all' || item.review === filter) &&
    (typeFilter === 'all' || item.type === typeFilter) &&
    (!query.trim() || `${item.id} ${item.plate}`.toLowerCase().includes(query.trim().toLowerCase()))
  ), [clueRows, filter, typeFilter, query])
  const openClue = (item) => {
    setSelected(item)
    const params = new URLSearchParams(location.search)
    if (item) params.set('event_id', item.id)
    else params.delete('event_id')
    navigate(`${location.pathname}${params.size ? `?${params.toString()}` : ''}`, { replace: true })
  }
  const reviewClue = (value) => {
    setClueRows((items) => items.map((item) => item.id === selectedClue.id ? { ...item, review: value } : item))
    dispatch({ type: 'TOAST', value: { tone: value === 'confirmed' ? 'success' : 'warning', text: value === 'confirmed' ? 'AI 线索已技术确认，等待主平台研判' : 'AI 线索已驳回；未生成违法认定状态' } })
  }
  return <AppShell pageTitle='执法工作台'>
    <PageHeader eyebrow='S4 · AI 执法线索' title='执法工作台' description='在同一工作台复核线索事件、货车专题与区域规则；页面确认只表示 AI 线索复核，不代表违法认定。' meta='货车/非货车二分类 · 3 起待处理' actions={<button className='secondary-button' onClick={() => dispatch({ type: 'TOAST', value: { tone: 'success', text: '脱敏线索已导出；不包含处罚或案件状态' } })}><DownloadSimple size={15} /> 导出脱敏线索</button>} />
    <EnforcementTabs />
    <div className='kpi-grid four'><KpiCard icon={Truck} label='货车限行线索' value='12' unit='起' change='+3' tone='amber' /><KpiCard icon={Gauge} label='速度线索' value='8' unit='起' detail='视频/雷达分源' tone='red' /><KpiCard icon={MapPin} label='区域滞留' value='4' unit='起' detail='2 待复核' /><KpiCard icon={ShieldCheck} label='证据完整' value='21 / 24' unit='起' detail='3 不完整' tone='green' /></div>
    <FilterBar result={`${rows.length} 起线索`} onReset={() => { setFilter('all'); setTypeFilter('all'); setQuery('') }}><Segmented value={filter} onChange={setFilter} options={[{ value: 'all', label: '全部' }, { value: 'pending', label: '待复核' }, { value: 'confirmed', label: '已确认' }, { value: 'rejected', label: '已驳回' }]} /><label>线索类型<select aria-label='线索类型' value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}><option value='all'>全部类型</option><option value='货车限行'>货车限行</option><option value='疑似超速'>疑似超速</option><option value='禁停区域滞留'>区域滞留</option></select></label><label className='search-field'><Funnel size={15} /><input aria-label='线索搜索' value={query} onChange={(event) => setQuery(event.target.value)} placeholder='线索 ID / 号牌' /></label></FilterBar>
    <Panel title='AI 执法线索' subtitle='车辆类别仅显示 truck / non_truck / unknown'><DataTable rows={rows} onRowClick={openClue} columns={[{ key: 'review', label: 'AI 复核', render: (value) => <StatusBadge value={value} /> }, { key: 'id', label: '线索 ID' }, { key: 'type', label: '类型' }, { key: 'vehicle', label: '车辆类别' }, { key: 'plate', label: '脱敏号牌' }, { key: 'zone', label: '命中区域' }, { key: 'speed', label: '视频速度' }, { key: 'radar', label: '雷达速度' }, { key: 'evidence', label: '证据', render: (value) => <StatusBadge value={value} /> }, { key: 'delivery', label: '投递', render: (value) => <StatusBadge value={value} /> }, { key: 'time', label: '业务时间' }]} /></Panel>
    {selectedClue && <DetailDrawer wide title={selectedClue.type} subtitle={selectedClue.id} onClose={() => openClue(null)} footer={<><button className='danger-button' onClick={() => reviewClue('rejected')}><X size={15} /> 驳回线索</button><button className='primary-button' onClick={() => reviewClue('confirmed')}><Check size={15} /> 确认 AI 线索</button></>}>
      <div className='event-hero'><div className='event-snapshot'><img src='/assets/uav-intersection-night.png' alt='执法线索原始证据帧' /><span><Truck size={14} /> 证据帧 #20642 · 内容哈希已核验</span></div><div className='event-primary-metrics'><div><span>视频速度</span><strong>{selectedClue.speed}</strong></div><div><span>雷达速度</span><strong>{selectedClue.radar}</strong></div><div><span>分类</span><strong>{selectedClue.vehicle}</strong></div><div><span>置信度</span><strong>91%</strong></div></div></div>
      <div className='detail-two-col'><Panel title='规则事实'><InfoRow label='围栏' value={selectedClue.zone} /><InfoRow label='围栏版本' value='ZONE-v12' /><InfoRow label='命中规则' value='truck-restriction-r4' /><InfoRow label='进入 / 停留' value='10:40:51 / 14s' /><InfoRow label='车辆分类' value={selectedClue.vehicle} /></Panel><Panel title='证据与质量'><InfoRow label='证据完整性' value={selectedClue.evidence} badge={selectedClue.evidence} /><InfoRow label='坐标质量' value='degraded · 3.4m' badge={selectedClue.quality} /><InfoRow label='雷达检定' value={selectedClue.radar === '—' ? '无雷达观测' : '有效至 2027-03'} /><InfoRow label='投递状态' value={selectedClue.delivery} badge={selectedClue.delivery} /><InfoRow label='复核状态' value={selectedClue.review} badge={selectedClue.review} /></Panel></div>
      <QualityNotice tone='warning' title='事实与结论分离'>视频速度、雷达速度和融合结果不会互相覆盖；AI 线索确认不等于违法定案、处罚或案件办结。</QualityNotice>
    </DetailDrawer>}
  </AppShell>
}

export function EnforcementZonesPage() {
  const { state, dispatch } = useAppState()
  const [selected, setSelected] = useState(state.zones[0])
  const selectedZone = selected ? state.zones.find((item) => item.id === selected.id) || selected : null
  const [editing, setEditing] = useState(false)
  return <AppShell pageTitle='区域与规则'>
    <PageHeader eyebrow='S4 / S5 · 围栏与规则' title='区域与规则' description='查看权威围栏与本地候选版本；本地编辑只形成候选配置，不覆盖外部权威数据。' meta='GCJ02 · ZONE-v12 · 2026-07-13' actions={<button className='primary-button' onClick={() => setEditing(true)}><Plus size={15} /> 新建候选区域</button>} />
    <EnforcementTabs />
    <div className='zone-layout'><Panel title='区域地图' subtitle='候选多边形使用虚线，已发布版本使用实线'><CityMap points={intersections} selectedId={intersections[0].id} compact /><div className='zone-polygon zone-a'><span>历下核心区货车限行 · v12</span></div><div className='zone-polygon zone-b candidate'><span>学校周边禁停候选 · v3</span></div></Panel><Panel title='区域与规则'>{state.zones.map((zone) => <button key={zone.id} className={`zone-row ${selected?.id === zone.id ? 'active' : ''}`} onClick={() => setSelected(zone)}><div><strong>{zone.name}</strong><span>{zone.id} · {zone.version}</span></div><StatusBadge value={zone.status} /></button>)}</Panel></div>
    {selectedZone && <Panel title={selectedZone.name} subtitle={`${selectedZone.id} · ${selectedZone.version}`} action={<button className='secondary-button' onClick={() => setEditing(true)}><PencilSimple size={15} /> 编辑候选</button>}><div className='zone-detail-grid'><InfoRow label='区域类型' value={selectedZone.type} /><InfoRow label='发布状态' value={selectedZone.status} badge={selectedZone.status} /><InfoRow label='有效时段' value={selectedZone.valid} /><InfoRow label='关联规则' value={`${selectedZone.rules} 条`} /><InfoRow label='坐标系统' value='GCJ02 · 语义待权威源冻结' /><InfoRow label='路网版本' value='ROAD-2026.07.1' /></div></Panel>}
    {editing && <div className='modal-backdrop'><div className='modal-card wide'><header><strong>编辑候选执法区域</strong><button onClick={() => setEditing(false)}><X size={18} /></button></header><div className='form-grid'><label>区域名称<input defaultValue={selectedZone?.name} /></label><label>区域类型<select defaultValue={selectedZone?.type}><option value='truck_restriction'>货车限行</option><option value='no_parking'>禁停</option><option value='speed'>速度观测</option></select></label><label>有效时段<input defaultValue={selectedZone?.valid} /></label><label>关联规则<select><option>truck-restriction-r4</option><option>parking-r3</option></select></label></div><QualityNotice tone='info' title='候选版本'>保存后生成候选版本，未经过批准和发布流程不会进入运行任务。</QualityNotice><footer><button className='secondary-button' onClick={() => setEditing(false)}>取消</button><button className='primary-button' onClick={() => { dispatch({ type: 'SAVE_ZONE', id: selectedZone.id }); setEditing(false) }}>保存候选</button></footer></div></div>}
  </AppShell>
}

export function TrucksPage() {
  const [selected, setSelected] = useState(intersections[0])
  return <AppShell pageTitle='货车专题'>
    <PageHeader eyebrow='S4 · truck / non_truck' title='货车专题' description='展示货车二分类、围栏进入事实和待复核线索；不扩展重/中/轻型货车或核定载质量识别。' meta='当前 18 辆 truck · 2 起区域命中' />
    <EnforcementTabs />
    <div className='kpi-grid four'><KpiCard icon={Truck} label='当前货车' value='18' unit='辆' change='+4' /><KpiCard icon={MapPin} label='围栏内' value='3' unit='辆' detail='2 起待复核' tone='amber' /><KpiCard icon={Gauge} label='平均视频速度' value='36.2' unit='km/h' detail='不含雷达值' tone='cyan' /><KpiCard icon={Warning} label='低置信候选' value='2' unit='辆' detail='转人工核验' tone='red' /></div>
    <div className='truck-layout'><Panel title='实时空间位置' subtitle='最近位置过期时灰显并标注时间'><CityMap points={intersections} selectedId={selected.id} onSelect={setSelected} /></Panel><Panel title='围栏命中车辆'><div className='truck-list'>{[{ id: '#0971', confidence: '91%', speed: '34km/h', zone: '核心区限行', status: 'warning' }, { id: '#1264', confidence: '88%', speed: '41km/h', zone: '核心区限行', status: 'warning' }, { id: '#2038', confidence: '63%', speed: '28km/h', zone: '边界徘徊', status: 'unverified' }].map((truck) => <button key={truck.id}><span className='truck-icon'><Truck size={18} weight='fill' /></span><div><strong>{truck.id} · truck {truck.confidence}</strong><span>{truck.zone} · 视频速度 {truck.speed}</span></div><StatusBadge value={truck.status} /></button>)}</div><QualityNotice tone='info' title='模型范围冻结'>只输出 truck / non_truck / unknown；低置信候选不按货车规则生成高置信线索。</QualityNotice></Panel></div>
  </AppShell>
}
