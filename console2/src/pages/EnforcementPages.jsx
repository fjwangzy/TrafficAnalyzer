import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import { Check, Crosshair, Funnel, Gauge, MapPin, PencilSimple, Plus, ShieldCheck, Truck, Warning, X } from '@phosphor-icons/react'
import { AppShell } from '../components/AppShell'
import { DataTable, DetailDrawer, FilterBar, InfoRow, KpiCard, PageHeader, Panel, QualityNotice, Segmented, StatusBadge } from '../components/Common'
import { useAuth } from '../auth/AuthContext'
import { apiErrorMessage, platformApi } from '../lib/api'

const clueLabels = {
  truck_restriction: '货车限行候选', speed_observation: '速度观测候选',
  no_parking: '禁停候选', dwell: '区域滞留候选', occupation: '占道候选',
}

const zoneLabels = {
  truck_restriction: '货车限行', speed_observation: '速度观测',
  no_parking: '禁停', dwell: '区域滞留', occupation: '占道',
}

function displayTime(value) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', dateStyle: 'short', timeStyle: 'medium' }).format(new Date(value))
}

function EnforcementTabs() {
  const location = useLocation()
  const navigate = useNavigate()
  const active = location.pathname.endsWith('/zones') ? 'zones' : location.pathname.endsWith('/trucks') ? 'trucks' : 'events'
  return <div className='page-tabs' role='tablist' aria-label='执法工作台视图'>{[
    ['events', '线索事件', '/enforcement'],
    ['trucks', '货车专题', '/enforcement/trucks'],
    ['zones', '区域与规则', '/enforcement/zones'],
  ].map(([id, label, path]) => <button key={id} role='tab' aria-selected={active === id} className={active === id ? 'active' : ''} onClick={() => navigate(path)}>{label}</button>)}</div>
}

export function EnforcementEventsPage() {
  const { platformRole } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const initialId = new URLSearchParams(location.search).get('event_id')
  const [selectedId, setSelectedId] = useState(initialId)
  const [filter, setFilter] = useState('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [actionError, setActionError] = useState('')
  const cluesQuery = useQuery({ queryKey: ['i4-enforcement-clues'], queryFn: () => platformApi.enforcementClues(), refetchInterval: 30_000 })
  const detailQuery = useQuery({ queryKey: ['i4-enforcement-clue', selectedId], queryFn: () => platformApi.enforcementClue(selectedId), enabled: Boolean(selectedId) })
  const clues = cluesQuery.data || []
  const selectedClue = detailQuery.data || clues.find((item) => item.id === selectedId) || null
  const rows = useMemo(() => clues.filter((item) =>
    (filter === 'all' || item.review_status === filter) &&
    (typeFilter === 'all' || item.clue_type === typeFilter) &&
    (!query.trim() || `${item.id} ${item.source_event_id} ${item.track_id}`.toLowerCase().includes(query.trim().toLowerCase()))
  ), [clues, filter, typeFilter, query])
  const openClue = (item) => {
    const id = item?.id || null
    setSelectedId(id)
    const params = new URLSearchParams(location.search)
    if (id) params.set('event_id', id)
    else params.delete('event_id')
    navigate(`${location.pathname}${params.size ? `?${params.toString()}` : ''}`, { replace: true })
  }
  const reviewMutation = useMutation({
    mutationFn: ({ status, reason }) => platformApi.reviewEnforcementClue(selectedClue.id, { review_status: status, expected_revision: selectedClue.review_revision, reason }),
    onSuccess: async () => {
      setActionError('')
      await queryClient.invalidateQueries({ predicate: (query) => String(query.queryKey[0]).startsWith('i4-enforcement') })
    },
    onError: (error) => setActionError(apiErrorMessage(error)),
  })
  const review = (status) => reviewMutation.mutate({
    status,
    reason: status === 'reviewed_confirmed' ? 'Console2 AI 技术事实确认；不构成违法认定' : 'Console2 AI 技术事实驳回',
  })
  const truckCount = clues.filter((item) => item.clue_type === 'truck_restriction').length
  const speedCount = clues.filter((item) => item.clue_type === 'speed_observation').length
  const pendingCount = clues.filter((item) => item.review_status === 'pending').length
  const evidenceCount = clues.filter((item) => item.evidence_integrity_status === 'hash_verified').length
  const loading = cluesQuery.isLoading
  const error = cluesQuery.error
  return <AppShell pageTitle='执法工作台'>
    <PageHeader eyebrow='S4 · AI 执法线索' title='执法工作台' description='复核持久化 AI 事实线索；确认不代表违法认定、处罚或案件办结。' meta={`road9 · ${pendingCount} 起待复核`} />
    <EnforcementTabs />
    <div className='kpi-grid four'><KpiCard icon={Truck} label='货车候选' value={truckCount} unit='起' /><KpiCard icon={Gauge} label='速度候选' value={speedCount} unit='起' detail='视频/雷达分源' /><KpiCard icon={MapPin} label='待复核' value={pendingCount} unit='起' tone='amber' /><KpiCard icon={ShieldCheck} label='哈希已核验' value={`${evidenceCount} / ${clues.length}`} unit='起' tone='green' /></div>
    <FilterBar result={`${rows.length} 起线索`} onReset={() => { setFilter('all'); setTypeFilter('all'); setQuery('') }}><Segmented label='复核状态' value={filter} onChange={setFilter} options={[{ value: 'all', label: '全部' }, { value: 'pending', label: '待复核' }, { value: 'reviewed_confirmed', label: 'AI 已确认' }, { value: 'reviewed_rejected', label: 'AI 已驳回' }]} /><label>线索类型<select aria-label='线索类型' value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}><option value='all'>全部类型</option>{Object.entries(clueLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className='search-field'><Funnel size={15} /><input aria-label='线索搜索' value={query} onChange={(event) => setQuery(event.target.value)} placeholder='线索 / source / track' /></label></FilterBar>
    {loading && <QualityNotice tone='info' title='正在加载'>正在读取 AI 线索与复核记录。</QualityNotice>}
    {error && <QualityNotice tone='danger' title='执法线索不可用'>{apiErrorMessage(error)}</QualityNotice>}
    {!loading && !error && <Panel title='AI 执法线索' subtitle='车辆类别严格为 truck / non_truck / unknown'><DataTable rows={rows.map((item) => ({ ...item, type_label: clueLabels[item.clue_type] || item.clue_type, speed_label: item.video_speed_kmh == null ? '—' : `${item.video_speed_kmh.toFixed(1)} km/h`, radar_label: item.radar_speed_kmh == null ? '无雷达观测' : `${item.radar_speed_kmh.toFixed(1)} km/h`, time_label: displayTime(item.occurred_at) }))} onRowClick={openClue} empty='当前没有 AI 执法线索' columns={[{ key: 'review_status', label: 'AI 复核', render: (value) => <StatusBadge value={value} /> }, { key: 'id', label: '线索 ID' }, { key: 'type_label', label: '类型' }, { key: 'vehicle_class', label: '车辆类别' }, { key: 'track_id', label: 'Track' }, { key: 'speed_label', label: '视频速度' }, { key: 'radar_label', label: '雷达速度' }, { key: 'evidence_integrity_status', label: '证据', render: (value) => <StatusBadge value={value} /> }, { key: 'delivery_status', label: '投递', render: (value) => <StatusBadge value={value} /> }, { key: 'time_label', label: '业务时间' }]} /></Panel>}
    {selectedClue && <DetailDrawer wide title={clueLabels[selectedClue.clue_type] || selectedClue.clue_type} subtitle={selectedClue.id} onClose={() => openClue(null)} footer={<>{platformRole !== 'admin' && <span className='muted'>只读角色不可复核</span>}<button disabled={platformRole !== 'admin' || reviewMutation.isPending} className='danger-button' onClick={() => review('reviewed_rejected')}><X size={15} /> 驳回 AI 线索</button><button disabled={platformRole !== 'admin' || reviewMutation.isPending} className='primary-button' onClick={() => review('reviewed_confirmed')}><Check size={15} /> 确认 AI 线索</button></>}>
      {actionError && <QualityNotice tone='danger' title='复核未保存'>{actionError}</QualityNotice>}
      {detailQuery.isLoading && <QualityNotice tone='info' title='正在恢复证据'>正在读取证据清单与不可变引用。</QualityNotice>}
      <div className='event-primary-metrics'><div><span>视频速度</span><strong>{selectedClue.video_speed_kmh == null ? '—' : `${selectedClue.video_speed_kmh.toFixed(1)} km/h`}</strong></div><div><span>雷达速度</span><strong>{selectedClue.radar_speed_kmh == null ? '无观测' : `${selectedClue.radar_speed_kmh.toFixed(1)} km/h`}</strong></div><div><span>分类</span><strong>{selectedClue.vehicle_class}</strong></div><div><span>置信度</span><strong>{selectedClue.class_confidence == null ? '—' : `${(selectedClue.class_confidence * 100).toFixed(1)}%`}</strong></div></div>
      <div className='detail-two-col'><Panel title='规则事实'><InfoRow label='围栏' value={selectedClue.zone_id || '未绑定'} /><InfoRow label='围栏版本' value={selectedClue.zone_version || '未冻结'} /><InfoRow label='候选规则' value={selectedClue.rule_id || '未绑定'} /><InfoRow label='规则版本' value={selectedClue.rule_version || '未冻结'} /><InfoRow label='Track' value={selectedClue.track_id} /></Panel><Panel title='证据与质量'><InfoRow label='证据完整性' value={selectedClue.evidence_integrity_status} badge={selectedClue.evidence_integrity_status} /><InfoRow label='证据项' value={`${selectedClue.evidence_count || 0} 项`} /><InfoRow label='质量状态' value={selectedClue.quality_status} badge={selectedClue.quality_status} /><InfoRow label='投递状态' value={selectedClue.delivery_status} badge={selectedClue.delivery_status} /><InfoRow label='复核 revision' value={`r${selectedClue.review_revision}`} /></Panel></div>
      <Panel title='不可变证据引用' subtitle='只展示对象引用和 SHA-256，不把通用夜景图冒充原始证据'>{selectedClue.evidence?.length ? selectedClue.evidence.map((item) => <div className='info-row' key={item.id}><span>{item.kind} · {item.media_type}</span><strong title={item.sha256}>{item.sha256.slice(0, 16)}… · {item.size_bytes} B</strong></div>) : <span className='muted'>当前线索没有证据项，状态不得显示为完整。</span>}</Panel>
      <QualityNotice tone='warning' title='事实与结论分离'>视频、雷达和融合值不会相互覆盖；复核仅改变 AI 线索状态。</QualityNotice>
    </DetailDrawer>}
  </AppShell>
}

function ZoneDialog({ zone, onClose, onSave, pending, error }) {
  const [name, setName] = useState(zone?.name || '')
  const [type, setType] = useState(zone?.zone_type || 'truck_restriction')
  const coordinateSystem = 'GCJ02'
  const [roadVersion, setRoadVersion] = useState(zone?.road_data_version || '')
  const [geometry, setGeometry] = useState(zone ? JSON.stringify(zone.geometry) : '')
  const submit = () => {
    try {
      onSave({ name, zone_type: type, coordinate_system: coordinateSystem, road_data_version: roadVersion || null, geometry: JSON.parse(geometry), schedule: zone?.schedule || {} })
    } catch {
      onSave(null, '几何必须是闭合的 GeoJSON Polygon JSON')
    }
  }
  return <div className='modal-backdrop'><div className='modal-card wide' role='dialog' aria-modal='true' aria-label={zone ? '编辑候选执法区域' : '新建候选执法区域'}><header><strong>{zone ? '编辑候选执法区域' : '新建候选执法区域'}</strong><button className='icon-action' aria-label='关闭候选区域表单' onClick={onClose}><X size={18} /></button></header><div className='form-grid'><label>区域名称<input aria-label='区域名称' value={name} onChange={(event) => setName(event.target.value)} /></label><label>区域类型<select aria-label='区域类型' value={type} onChange={(event) => setType(event.target.value)}>{Object.entries(zoneLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>坐标系统<input aria-label='坐标系统' value={coordinateSystem} readOnly /></label><label>路网版本<input aria-label='路网版本' value={roadVersion} onChange={(event) => setRoadVersion(event.target.value)} /></label><label style={{ gridColumn: '1 / -1' }}>GCJ-02 GeoJSON Polygon<textarea aria-label='区域几何' rows='5' value={geometry} onChange={(event) => setGeometry(event.target.value)} placeholder='{"type":"Polygon","coordinates":[[[117.0,36.7],[117.1,36.7],[117.1,36.8],[117.0,36.7]]]}' /></label></div>{error && <QualityNotice tone='danger' title='候选未保存'>{error}</QualityNotice>}<QualityNotice tone='info' title='只保存候选'>本地没有权威发布权限；保存后保持 candidate/unverified。</QualityNotice><footer><button className='secondary-button' onClick={onClose}>取消</button><button disabled={pending} className='primary-button' onClick={submit}>保存候选</button></footer></div></div>
}

function RuleDialog({ zones, onClose, onSave, pending, error }) {
  const [name, setName] = useState('')
  const [zoneId, setZoneId] = useState(zones[0]?.id || '')
  const [type, setType] = useState('truck_restriction')
  return <div className='modal-backdrop'><div className='modal-card wide' role='dialog' aria-modal='true' aria-label='新建候选执法规则'><header><strong>新建候选事实规则</strong><button className='icon-action' aria-label='关闭候选规则表单' onClick={onClose}><X size={18} /></button></header><div className='form-grid'><label>规则名称<input aria-label='规则名称' value={name} onChange={(event) => setName(event.target.value)} /></label><label>候选区域<select aria-label='候选区域' value={zoneId} onChange={(event) => setZoneId(event.target.value)}><option value=''>不绑定</option>{zones.map((zone) => <option key={zone.id} value={zone.id}>{zone.name}</option>)}</select></label><label>线索类型<select aria-label='规则线索类型' value={type} onChange={(event) => setType(event.target.value)}>{Object.entries(clueLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div>{error && <QualityNotice tone='danger' title='规则未保存'>{error}</QualityNotice>}<QualityNotice tone='warning' title='阈值与审批未冻结'>只保存候选事实 schema，不设置法定阈值、例外或处罚字段。</QualityNotice><footer><button className='secondary-button' onClick={onClose}>取消</button><button disabled={pending || !name} className='primary-button' onClick={() => onSave({ name, zone_id: zoneId || null, clue_type: type, definition: { mode: 'fact_only', vehicle_class: type === 'truck_restriction' ? 'truck' : 'unknown' } })}>保存候选规则</button></footer></div></div>
}

export function EnforcementZonesPage() {
  const { platformRole } = useAuth()
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState(null)
  const [editing, setEditing] = useState(false)
  const [ruleEditing, setRuleEditing] = useState(false)
  const [actionError, setActionError] = useState('')
  const zonesQuery = useQuery({ queryKey: ['i4-enforcement-zones'], queryFn: platformApi.enforcementZones })
  const rulesQuery = useQuery({ queryKey: ['i4-enforcement-rules'], queryFn: platformApi.enforcementRules })
  const zones = zonesQuery.data || []
  const rules = rulesQuery.data || []
  const selectedZone = zones.find((item) => item.id === selectedId) || zones[0] || null
  useEffect(() => { if (!selectedId && zones[0]) setSelectedId(zones[0].id) }, [selectedId, zones])
  const saved = async () => {
    setActionError('')
    setEditing(false)
    setRuleEditing(false)
    await queryClient.invalidateQueries({ predicate: (query) => String(query.queryKey[0]).startsWith('i4-enforcement') })
  }
  const zoneMutation = useMutation({
    mutationFn: (value) => value.id ? platformApi.updateEnforcementZone(value.id, value.body) : platformApi.createEnforcementZone(value.body),
    onSuccess: saved,
    onError: (error) => setActionError(apiErrorMessage(error)),
  })
  const ruleMutation = useMutation({ mutationFn: platformApi.createEnforcementRule, onSuccess: saved, onError: (error) => setActionError(apiErrorMessage(error)) })
  const publishMutation = useMutation({ mutationFn: platformApi.publishEnforcementZone, onError: (error) => setActionError(apiErrorMessage(error)) })
  const saveZone = (body, localError) => {
    if (localError) return setActionError(localError)
    setActionError('')
    zoneMutation.mutate(editing === 'edit' ? { id: selectedZone.id, body: { ...body, revision: selectedZone.revision } } : { body })
  }
  const loading = zonesQuery.isLoading || rulesQuery.isLoading
  const error = zonesQuery.error || rulesQuery.error
  return <AppShell pageTitle='区域与规则'>
    <PageHeader eyebrow='S4 / S5 · 候选围栏与规则' title='区域与规则' description='本地只管理 candidate/retired；权威发布 Adapter 不可用时拒绝发布。' meta={`${zones.length} 个候选区 · ${rules.length} 条候选规则`} actions={<>{platformRole === 'admin' && <button className='secondary-button' onClick={() => { setActionError(''); setRuleEditing(true) }}><Plus size={15} /> 新建候选规则</button>} {platformRole === 'admin' && <button className='primary-button' onClick={() => { setActionError(''); setEditing('new') }}><Plus size={15} /> 新建候选区域</button>}</>} />
    <EnforcementTabs />
    {loading && <QualityNotice tone='info' title='正在加载'>正在从 road9 读取候选版本。</QualityNotice>}
    {error && <QualityNotice tone='danger' title='候选配置不可用'>{apiErrorMessage(error)}</QualityNotice>}
    {actionError && !editing && !ruleEditing && <QualityNotice tone='warning' title='操作未完成'>{actionError}</QualityNotice>}
    {!loading && !error && zones.length === 0 && <QualityNotice tone='info' title='暂无候选区域'>当前没有候选区域配置。</QualityNotice>}
    {!loading && !error && <div className='zone-layout'><Panel title='空间语义状态' subtitle='候选配置详情'>{selectedZone && <div className='zone-detail-grid'><InfoRow label='坐标系统' value={selectedZone.coordinate_system} /><InfoRow label='路网版本' value={selectedZone.road_data_version || '未绑定'} /><InfoRow label='checksum' value={`${selectedZone.checksum.slice(0, 16)}…`} /><InfoRow label='权威状态' value={selectedZone.authority_status} badge='blocked' /></div>}</Panel><Panel title='候选区域'>{zones.length === 0 ? <span className='muted'>无持久化候选区域</span> : zones.map((zone) => <button key={zone.id} className={`zone-row ${selectedZone?.id === zone.id ? 'active' : ''}`} onClick={() => setSelectedId(zone.id)}><div><strong>{zone.name}</strong><span>{zone.id} · r{zone.revision}</span></div><StatusBadge value={zone.status} /></button>)}</Panel></div>}
    {selectedZone && <Panel title={selectedZone.name} subtitle={`${selectedZone.id} · revision ${selectedZone.revision}`} action={<>{platformRole === 'admin' && <button className='secondary-button' onClick={() => { setActionError(''); setEditing('edit') }}><PencilSimple size={15} /> 编辑候选</button>} {platformRole === 'admin' && <button className='secondary-button' onClick={() => publishMutation.mutate(selectedZone.id)}>尝试权威发布</button>}</>}><div className='zone-detail-grid'><InfoRow label='区域类型' value={zoneLabels[selectedZone.zone_type] || selectedZone.zone_type} /><InfoRow label='本地状态' value={selectedZone.status} badge={selectedZone.status} /><InfoRow label='来源' value={selectedZone.source} /><InfoRow label='关联规则' value={`${selectedZone.rule_count} 条`} /><InfoRow label='坐标系统' value={selectedZone.coordinate_system} /><InfoRow label='路网版本' value={selectedZone.road_data_version || '未冻结'} /></div></Panel>}
    <Panel title='候选规则' subtitle='规则内容仍为 unverified，不能进入运行任务'><DataTable rows={rules} empty='暂无候选规则' columns={[{ key: 'status', label: '状态', render: (value) => <StatusBadge value={value} /> }, { key: 'id', label: '规则 ID' }, { key: 'name', label: '名称' }, { key: 'clue_type', label: '线索类型', render: (value) => clueLabels[value] || value }, { key: 'zone_id', label: '候选区域', render: (value) => value || '未绑定' }, { key: 'quality_status', label: '质量', render: (value) => <StatusBadge value={value} /> }, { key: 'approval_status', label: '审批', render: (value) => <StatusBadge value={value} /> }]} /></Panel>
    {editing && <ZoneDialog zone={editing === 'edit' ? selectedZone : null} onClose={() => setEditing(false)} onSave={saveZone} pending={zoneMutation.isPending} error={actionError} />}
    {ruleEditing && <RuleDialog zones={zones} onClose={() => setRuleEditing(false)} onSave={(body) => ruleMutation.mutate(body)} pending={ruleMutation.isPending} error={actionError} />}
  </AppShell>
}

export function TrucksPage() {
  const summaryQuery = useQuery({ queryKey: ['i4-enforcement-truck-summary'], queryFn: platformApi.enforcementTruckSummary, refetchInterval: 30_000 })
  const summary = summaryQuery.data || { status: 'stale', active_count: 0, clue_count: 0, pending_review_count: 0, vehicles: [] }
  return <AppShell pageTitle='货车专题'>
    <PageHeader eyebrow='S4 · truck / non_truck' title='货车专题' description='仅展示持久化货车 AI 线索摘要；不扩展车型，也不以历史线索伪造实时车辆位置。' meta={summary.as_of ? `as_of ${displayTime(summary.as_of)}` : '尚无真实时间点'} />
    <EnforcementTabs />
    {summaryQuery.isLoading && <QualityNotice tone='info' title='正在加载'>正在从 S4 线索投影恢复货车摘要。</QualityNotice>}
    {summaryQuery.error && <QualityNotice tone='danger' title='货车摘要不可用'>{apiErrorMessage(summaryQuery.error)}</QualityNotice>}
    <div className='kpi-grid four'><KpiCard icon={Truck} label='当前实时货车' value={summary.active_count} unit='辆' detail='无实时事实时为 0' /><KpiCard icon={MapPin} label='历史候选线索' value={summary.clue_count} unit='起' /><KpiCard icon={Gauge} label='待复核' value={summary.pending_review_count} unit='起' tone='amber' /><KpiCard icon={Warning} label='数据新鲜度' value={summary.status} unit='' tone={summary.status === 'fresh' ? 'green' : 'amber'} /></div>
    <div className='truck-layout'><Panel title='实时空间位置' subtitle='没有真实在线位置时保持空态'><QualityNotice tone='info' title='暂无实时位置'>{summary.reason || '当前没有可用实时货车位置。'}</QualityNotice></Panel><Panel title='围栏命中车辆'>{summary.vehicles?.length ? summary.vehicles.map((truck) => <div className='info-row' key={truck.id}><span>{truck.id}</span><strong>{truck.status}</strong></div>) : <span className='muted'>当前没有实时车辆事实</span>}<QualityNotice tone='info' title='模型范围冻结'>只输出 truck / non_truck / unknown；低置信候选只能转人工复核。</QualityNotice></Panel></div>
  </AppShell>
}
