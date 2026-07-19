import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { CloudArrowUp, Database, DownloadSimple, Gauge, GitDiff, Link as LinkIcon, LockKey, Pulse, ShieldCheck, Stack, Warning, X } from '@phosphor-icons/react'
import { AppShell } from '../components/AppShell'
import { CityMap } from '../components/CityMap'
import { DataTable, DetailDrawer, InfoRow, KpiCard, PageHeader, Panel, QualityNotice, StatusBadge } from '../components/Common'
import { intersections, qualityRuns, roadVersions, systemServices, users } from '../data/mockData'
import { useAppState } from '../state/AppState'
import { apiErrorMessage, platformApi } from '../lib/api'

export function CalibrationPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const requestedTab = new URLSearchParams(location.search).get('tab')
  const [tab, setTab] = useState(['records', 'lanes', 'bindings', 'coordinates'].includes(requestedTab) ? requestedTab : 'records')
  const [selected, setSelected] = useState(null)
  const [selectedTaskId, setSelectedTaskId] = useState(null)
  const [draftPoints, setDraftPoints] = useState([])
  const [draftLanes, setDraftLanes] = useState([])
  const [direction, setDirection] = useState('straight')
  const summaryQuery = useQuery({ queryKey: ['calibration-summary'], queryFn: platformApi.calibrationSummary, refetchInterval: 10_000 })
  const recordsQuery = useQuery({ queryKey: ['calibration-records'], queryFn: platformApi.calibrationRecords, refetchInterval: 10_000 })
  const tasksQuery = useQuery({ queryKey: ['lane-tasks'], queryFn: platformApi.laneTasks, refetchInterval: 5_000 })
  const annotationsQuery = useQuery({ queryKey: ['lane-annotations'], queryFn: platformApi.laneAnnotations, refetchInterval: 10_000 })
  const records = Array.isArray(recordsQuery.data) ? recordsQuery.data.map((record, index) => {
    const qualityObject = record.quality && typeof record.quality === 'object' ? record.quality : {}
    const score = Number(qualityObject.score ?? record.quality_score)
    return {
      ...record,
      id: String(record.key ?? record.id ?? `CAL-${index + 1}`),
      intersection: String(record.intersection_id ?? record.intersection ?? '—'),
      type: record.mode ?? record.type ?? (Number(record.gimbal_pitch) <= -85 ? 'Nadir' : 'Oblique'),
      quality: record.quality?.level ?? record.quality ?? (Number.isFinite(score) ? (score > 0.9 ? 'good' : 'degraded') : 'unknown'),
      residual: record.reprojection_error != null ? `${record.reprojection_error}px` : '—',
      coverage: record.coverage != null ? `${record.coverage}%` : '—',
      version: record.version ?? '—',
    }
  }) : []
  const tasks = Array.isArray(tasksQuery.data) ? tasksQuery.data : []
  const annotations = Array.isArray(annotationsQuery.data) ? annotationsQuery.data : []
  const selectedTask = tasks.find((task) => task.task_id === selectedTaskId) || tasks[0] || null
  const taskImageQuery = useQuery({ queryKey: ['lane-task-image', selectedTask?.task_id], queryFn: () => platformApi.laneTaskImage(selectedTask.task_id), enabled: Boolean(selectedTask?.task_id), staleTime: 60_000 })
  const [taskImageUrl, setTaskImageUrl] = useState('')
  useEffect(() => {
    if (!taskImageQuery.data || typeof URL.createObjectURL !== 'function') {
      setTaskImageUrl('')
      return undefined
    }
    const url = URL.createObjectURL(taskImageQuery.data)
    setTaskImageUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [taskImageQuery.data])
  const coverageIntersection = annotations[0]?.intersection_id || records[0]?.intersection_id
  const coverageQuery = useQuery({ queryKey: ['calibration-coverage', coverageIntersection], queryFn: () => platformApi.calibrationCoverage(coverageIntersection), enabled: Boolean(coverageIntersection), refetchInterval: 10_000 })
  const coverage = Array.isArray(coverageQuery.data) ? coverageQuery.data : []
  const saveMutation = useMutation({
    mutationFn: () => platformApi.saveLaneAnnotation(selectedTask.task_id, { lanes: draftLanes, roads: selectedTask.roads }),
    onSuccess: () => {
      setDraftPoints([])
      setDraftLanes([])
      queryClient.invalidateQueries({ queryKey: ['lane-tasks'] })
      queryClient.invalidateQueries({ queryKey: ['lane-annotations'] })
      queryClient.invalidateQueries({ queryKey: ['calibration-coverage'] })
    },
  })
  const selectTab = (value) => {
    setTab(value)
    const params = new URLSearchParams(location.search)
    params.set('tab', value)
    navigate(`${location.pathname}?${params.toString()}`, { replace: true })
  }
  const addPoint = (event) => {
    if (!selectedTask) return
    const rect = event.currentTarget.getBoundingClientRect()
    const width = selectedTask.image_width || 960
    const height = selectedTask.image_height || 540
    const x = Math.round(((event.clientX - rect.left) / rect.width) * width)
    const y = Math.round(((event.clientY - rect.top) / rect.height) * height)
    setDraftPoints((points) => [...points, [Math.max(0, Math.min(width, x)), Math.max(0, Math.min(height, y))]])
  }
  const closeLane = () => {
    if (draftPoints.length < 3) return
    const laneNumber = draftLanes.length + 1
    setDraftLanes((lanes) => [...lanes, { lane_id: `L${laneNumber}`, name: `车道 ${laneNumber}`, direction, polygon: draftPoints.flat() }])
    setDraftPoints([])
  }
  const queryError = summaryQuery.error || recordsQuery.error || tasksQuery.error || annotationsQuery.error
  return <AppShell pageTitle='标定中心'>
    <PageHeader eyebrow='S1 / S5 · 标定与绑定' title='标定中心' description='管理单应性、车道多边形、视觉车道与权威 lane/link 绑定，并显示坐标质量门禁。' meta={`${summaryQuery.data?.total ?? summaryQuery.data?.records_count ?? records.length} 条记录 · ${tasks.length} 个任务`} />
    <div className='page-tabs'>{[['records', '标定记录'], ['lanes', '车道标注'], ['bindings', '视觉绑定'], ['coordinates', '坐标校验']].map(([id, label]) => <button className={tab === id ? 'active' : ''} key={id} onClick={() => selectTab(id)}>{label}</button>)}</div>
    {queryError && <QualityNotice tone='warning' title='标定服务不可用'>{apiErrorMessage(queryError)}</QualityNotice>}
    {tab === 'records' && <Panel title='单应性标定记录'>{recordsQuery.isLoading ? <div className='live-state'>正在加载标定记录…</div> : records.length ? <DataTable rows={records} onRowClick={setSelected} columns={[{ key: 'quality', label: '质量', render: (value) => <StatusBadge value={String(value)} /> }, { key: 'id', label: '标定 ID' }, { key: 'intersection', label: '路口' }, { key: 'type', label: '模式' }, { key: 'residual', label: '重投影误差' }, { key: 'coverage', label: '覆盖度' }, { key: 'version', label: '版本' }]} /> : <div className='live-state empty'>暂无真实标定记录</div>}</Panel>}
    {tab === 'lanes' && <div className='calibration-layout'><Panel title='车道多边形编辑器' subtitle='点击画面添加顶点；至少三个顶点闭合为车道'><div className='annotation-stage live-annotation'>{selectedTask && taskImageUrl ? <svg viewBox={`0 0 ${selectedTask.image_width || 960} ${selectedTask.image_height || 540}`} preserveAspectRatio='xMidYMid meet' onClick={addPoint} aria-label='车道多边形绘制画布'><image href={taskImageUrl} width={selectedTask.image_width || 960} height={selectedTask.image_height || 540} />{draftLanes.map((lane) => <polygon key={lane.lane_id} points={lane.polygon.reduce((items, value, index) => index % 2 === 0 ? [...items, `${value},${lane.polygon[index + 1]}`] : items, []).join(' ')} />)}{draftPoints.length > 1 && <polyline points={draftPoints.map((point) => point.join(',')).join(' ')} />}{draftPoints.map(([x, y], index) => <circle key={`${x}-${y}-${index}`} cx={x} cy={y} r='5' />)}</svg> : <div className='live-state empty'>{taskImageQuery.isError ? apiErrorMessage(taskImageQuery.error, '任务图片加载失败') : selectedTask ? '正在加载任务图片…' : '暂无标注任务，悬停任务生成后会自动出现'}</div>}</div><div className='annotation-toolbar'><select value={direction} onChange={(event) => setDirection(event.target.value)}><option value='straight'>直行</option><option value='left_turn'>左转</option><option value='right_turn'>右转</option><option value='u_turn'>掉头</option></select><button className='secondary-button' disabled={draftPoints.length < 3} onClick={closeLane}>闭合为车道</button><button className='secondary-button' onClick={() => setDraftPoints([])}>清空顶点</button><span>{draftPoints.length} 个顶点 · {draftLanes.length} 条车道</span></div></Panel><Panel title={`标注任务 · ${tasks.length}`}>{tasksQuery.isLoading ? <div className='live-state'>正在加载任务…</div> : tasks.map((task) => <button className={`annotation-task ${selectedTask?.task_id === task.task_id ? 'active' : ''}`} key={task.task_id} onClick={() => { setSelectedTaskId(task.task_id); setDraftPoints([]); setDraftLanes([]) }}><div><strong>{task.intersection_id}</strong><span>{task.task_id}</span></div><StatusBadge value={task.status} /></button>)}{selectedTask && <><InfoRow label='画面尺寸' value={`${selectedTask.image_width || 960} × ${selectedTask.image_height || 540}`} /><InfoRow label='已有车道' value={String(selectedTask.lane_count ?? 0)} /><button className='primary-button full' disabled={draftLanes.length === 0 || saveMutation.isPending} onClick={() => saveMutation.mutate()}>{saveMutation.isPending ? '保存中…' : '保存标注参数'}</button>{saveMutation.isError && <div className='form-error'>{apiErrorMessage(saveMutation.error)}</div>}{saveMutation.isSuccess && <div className='form-success'>标注参数已保存并进入复用参数库</div>}</>}</Panel></div>}
    {tab === 'bindings' && <div className='binding-layout'><Panel title='已保存视觉参数'><div className='compare-panes'><div><span>视觉车道</span><img src='/assets/uav-intersection-night.png' alt='视觉车道参数背景' /></div><div><span>BEV 投放</span><img src='/assets/bev-intersection-night.png' alt='BEV 投放背景' /></div></div></Panel><Panel title={`参数库 · ${annotations.length}`}>{annotations.length ? annotations.map((annotation) => <div className='binding-candidate' key={`${annotation.intersection_id}-${annotation.task_id}`}><strong>{annotation.intersection_id}</strong><span>{annotation.lanes?.length || 0} 条车道 · {annotation.source || 'manual'} · {annotation.status}</span><div><button className='secondary-button' disabled>权威绑定接口待接入</button></div></div>) : <div className='live-state empty'>暂无已保存的视觉车道参数</div>}</Panel></div>}
    {tab === 'coordinates' && <div className='governance-grid'><Panel title={`姿态覆盖 · ${coverageIntersection || '未选择路口'}`}>{coverage.length ? coverage.map((item, index) => <div className='service-row' key={item.key || index}><StatusBadge value={item.quality || 'unknown'} /><strong>{item.key || `coverage-${index + 1}`}</strong><span>H {item.altitude ?? '—'}m · Pitch {item.pitch ?? '—'}°</span></div>) : <div className='live-state empty'>暂无覆盖度数据</div>}</Panel><Panel title='坐标质量门禁'><QualityNotice tone='warning' title='SRID 语义待权威源冻结'>当前仅展示真实接口返回的覆盖度和姿态质量，不将未知数据库 SRID 自动解释为 GCJ02。</QualityNotice><InfoRow label='覆盖记录' value={String(coverage.length)} /><InfoRow label='转换链' value='px → ENU → GCJ02' /></Panel></div>}
    {selected && <DetailDrawer title={selected.id} subtitle='标定记录详情' onClose={() => setSelected(null)}>{Object.entries(selected).map(([key, value]) => <InfoRow key={key} label={key} value={value} />)}<QualityNotice tone={selected.quality === 'good' ? 'success' : 'warning'} title='质量影响'>{selected.quality === 'good' ? '可用于当前坐标转换和车道绑定。' : '暂停自动绑定与依赖高精度坐标的业务输出。'}</QualityNotice></DetailDrawer>}
  </AppShell>
}

export function RoadDataPage() {
  const [tab, setTab] = useState('versions')
  return <AppShell pageTitle='路网与坐标'>
    <PageHeader eyebrow='S5 · 路网共性能力' title='路网、版本与坐标治理' description='只读加载权威路网、冻结任务版本、管理视觉绑定和坐标质量；历史结果不被新版本重解释。' meta='database road9 · ROAD-2026.07.1' actions={<button className='secondary-button'><CloudArrowUp size={15} /> 拉取候选快照</button>} />
    <div className='page-tabs'>{[['versions', '版本中心'], ['browser', '路网浏览'], ['diagnostics', '运维诊断']].map(([id, label]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>{label}</button>)}</div>
    {tab === 'versions' && <><div className='kpi-grid four'><KpiCard icon={Database} label='权威路口' value='8,335' unit='个' /><KpiCard icon={LinkIcon} label='Link 关系' value='40,188' unit='条' tone='cyan' /><KpiCard icon={Stack} label='车道关系' value='95,548' unit='条' /><KpiCard icon={Warning} label='版本不一致' value='1' unit='任务' tone='amber' /></div><Panel title='路网版本快照' subtitle='新版本只作用于新任务；运行中任务继续原版本'><DataTable rows={roadVersions} columns={[{ key: 'status', label: '状态', render: (value) => <StatusBadge value={value} /> }, { key: 'id', label: '版本' }, { key: 'intersections', label: '路口' }, { key: 'links', label: 'Link 关系' }, { key: 'lanes', label: '车道关系' }, { key: 'checksum', label: 'Checksum' }, { key: 'usedBy', label: '运行任务' }]} /></Panel></>}
    {tab === 'browser' && <div className='road-browser'><Panel title='路网空间浏览' subtitle='高缩放级别按需加载 Link / Lane'><CityMap points={intersections} selectedId={intersections[0].id} /></Panel><Panel title='路口拓扑'><InfoRow label='inter_id' value='370102000101' /><InfoRow label='进口 Link' value='4' /><InfoRow label='出口 Link' value='4' /><InfoRow label='权威车道' value='12' /><InfoRow label='视觉绑定' value='11 / 12' badge='degraded' /><InfoRow label='有效期' value='2026-07-01 起' /></Panel></div>}
    {tab === 'diagnostics' && <Panel title='数据质量诊断'><DataTable rows={[{ id: 'DG-01', type: 'version_mismatch', object: 'MSN-0713-1045', impact: '停止空间规则', status: 'warning', reason: '任务绑定 ROAD-2026.06.3' }, { id: 'DG-02', type: 'unmapped', object: 'local_lane_E2', impact: '车道级指标降级', status: 'degraded', reason: '候选分数差异 < 0.05' }, { id: 'DG-03', type: 'stale', object: 'road-cache-worker-2', impact: '使用最近验证快照', status: 'stale', reason: '远程源 8m 未更新' }]} columns={[{ key: 'status', label: '状态', render: (value) => <StatusBadge value={value} /> }, { key: 'type', label: '类型' }, { key: 'object', label: '对象' }, { key: 'impact', label: '业务影响' }, { key: 'reason', label: '原因' }]} /></Panel>}
  </AppShell>
}

export function QualityPage() {
  const { dispatch } = useAppState()
  return <AppShell pageTitle='质量与发布'>
    <PageHeader eyebrow='S7 · 质量验收与运营' title='质量、验收与发布门禁' description='按模型、事件、路口、质量和版本追踪指标、样本与故障演练，不以单一 Precision 替代完整验收。' meta='验收数据集 UAV-ACCEPT-2026.07-r3' actions={<button className='secondary-button'><DownloadSimple size={15} /> 导出追踪矩阵</button>} />
    <div className='kpi-grid four'><KpiCard icon={ShieldCheck} label='通过门禁' value='1 / 3' unit='模型' tone='green' /><KpiCard icon={Gauge} label='有效覆盖' value='92.4' unit='%' /><KpiCard icon={Warning} label='验收阻断' value='4' unit='项' tone='red' /><KpiCard icon={GitDiff} label='灰度范围' value='8' unit='路口' tone='cyan' /></div>
    <Panel title='模型质量门禁' subtitle='Precision、Recall、误报、覆盖和分场景结果共同判断'><DataTable rows={qualityRuns} columns={[{ key: 'gate', label: '门禁', render: (value) => <StatusBadge value={value} /> }, { key: 'model', label: '模型' }, { key: 'version', label: '版本' }, { key: 'precision', label: 'Precision' }, { key: 'recall', label: 'Recall' }, { key: 'coverage', label: '有效覆盖' }, { key: 'note', label: '限制与待办' }]} /></Panel>
    <div className='governance-grid'><Panel title='强制故障演练'><div className='drill-list'>{['遥测中断与 RTK 退化', 'Kafka / 主平台断连', 'road9 / TimescaleDB 短时不可用', 'Pipeline 进程崩溃', '新旧链路双写不一致'].map((item, index) => <div key={item}><StatusBadge value={index < 3 ? 'passed' : 'candidate'} /><strong>{item}</strong><span>{index < 3 ? '最近演练通过' : '待安排窗口'}</span></div>)}</div></Panel><Panel title='发布包与回滚'><InfoRow label='候选发布' value='uav-ai-2026.07-r17' /><InfoRow label='模型卡' value='3 / 3' badge='good' /><InfoRow label='已知限制' value='已记录' badge='good' /><InfoRow label='回滚版本' value='uav-ai-2026.06-r12' /><button className='primary-button full' onClick={() => dispatch({ type: 'TOAST', value: { tone: 'warning', text: '发布门禁仍有阻断项，保持候选状态' } })}>执行门禁检查</button></Panel></div>
  </AppShell>
}

const ruleJson = [
  '{',
  '  "schema_version": "uav.rule.v1",',
  '  "status": "candidate",',
  '  "conditions": {',
  '    "quality_gate": "good|degraded",',
  '    "ttc_sec": { "candidate_max": 1.5 },',
  '    "pet_sec": { "candidate_max": 1.0 }',
  '  },',
  '  "note": "阈值待业务书面冻结"',
  '}',
].join('\n')

export function RulesPage() {
  const { dispatch } = useAppState()
  const [selected, setSelected] = useState('conflict-r17')
  const [rules, setRules] = useState([{ id: 'conflict-r17', domain: '冲突', status: 'candidate', version: 'r17', updated: '10:20:14' }, { id: 'traffic-r12', domain: '拥堵', status: 'published', version: 'r12', updated: '昨天 18:02' }, { id: 'truck-r4', domain: '执法', status: 'blocked', version: 'r4', updated: '昨天 11:46' }])
  const submitCandidate = () => {
    setRules((items) => items.map((item) => item.id === selected ? { ...item, status: 'pending_approval', updated: '刚刚' } : item))
    dispatch({ type: 'TOAST', value: { tone: 'warning', text: '候选规则已提交审批；阈值冻结前不会进入运行任务' } })
  }
  return <AppShell pageTitle='规则配置'>
    <PageHeader eyebrow='S5 · 共性规则引擎' title='规则版本与候选配置' description='规则支持版本差异、审批、发布和回滚；未批准配置不可进入运行任务。' meta='规则热更新 · 审计开启' />
    <div className='rules-layout'><Panel title='规则目录'>{rules.map((rule) => <button className={`rule-row ${selected === rule.id ? 'active' : ''}`} key={rule.id} onClick={() => setSelected(rule.id)}><div><strong>{rule.id}</strong><span>{rule.domain} · {rule.updated}</span></div><StatusBadge value={rule.status} /></button>)}</Panel><Panel title={`${selected} · JSON 候选`} action={<button className='secondary-button'><GitDiff size={15} /> 与已发布版对比</button>}><pre className='code-editor'>{ruleJson.replace('"status"', `"rule_id": "${selected}",\n  "status"`)}</pre><div className='editor-actions'><button className='secondary-button' onClick={() => dispatch({ type: 'TOAST', value: { tone: 'success', text: '候选规则已保存，不影响运行任务' } })}>保存候选</button><button className='primary-button' onClick={submitCandidate}>提交发布审批</button></div></Panel></div>
  </AppShell>
}

export function EvidencePage() {
  const [selected, setSelected] = useState(null)
  const evidence = [{ id: 'EVD-0713-001', event: 'UAV-EVT-20260713-001', type: '冲突事件', integrity: 'complete', items: 6, size: '86.4 MB', retention: '30 天热数据', access: '脱敏副本' }, { id: 'EVD-0713-004', event: 'CLUE-0713-022', type: '执法线索', integrity: 'partial', items: 4, size: '42.1 MB', retention: '法制口径待冻结', access: '脱敏副本' }]
  return <AppShell pageTitle='证据链'>
    <PageHeader eyebrow='S4 / S5 / S6' title='证据链与调阅审计' description='管理帧、片段、轨迹、位置、规则、时间戳和内容哈希；原件、展示副本和授权调阅分离。' meta='对象存储健康 · 审计开启' />
    <QualityNotice tone='warning' title='证据保留与法制口径待冻结'>原件导出、删除申请和模型优化使用范围均需独立授权；普通热数据策略不得自动删除未归档测绘材料。</QualityNotice>
    <Panel title='证据包'><DataTable rows={evidence} onRowClick={setSelected} columns={[{ key: 'integrity', label: '完整性', render: (value) => <StatusBadge value={value} /> }, { key: 'id', label: '证据包' }, { key: 'event', label: '关联事实' }, { key: 'type', label: '类型' }, { key: 'items', label: '材料项' }, { key: 'size', label: '大小' }, { key: 'retention', label: '保留策略' }, { key: 'access', label: '默认访问' }]} /></Panel>
    {selected && <DetailDrawer title={selected.id} subtitle='证据包详情' onClose={() => setSelected(null)} footer={<button className='secondary-button'><LockKey size={15} /> 申请原件调阅</button>}><InfoRow label='关联事实' value={selected.event} /><InfoRow label='完整性' value={selected.integrity} badge={selected.integrity} /><InfoRow label='内容哈希' value='sha256:7ca2…110e' /><InfoRow label='材料项' value={`${selected.items} 项`} /><Panel title='材料清单'>{['原始关键帧 × 3', '原始视频片段 × 1', '完整轨迹 × 1', '规则与路网上下文 × 1'].map((item) => <div className='audit-line' key={item}>{item}</div>)}</Panel><Panel title='最近调阅审计'><div className='audit-line'>10:31:04 · admin · 查看脱敏副本</div><div className='audit-line'>10:12:48 · integration-service · 哈希校验</div></Panel></DetailDrawer>}
  </AppShell>
}

export function SystemPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const requestedTab = new URLSearchParams(location.search).get('tab')
  const [tab, setTab] = useState(requestedTab === 'identity' ? 'identity' : 'system')
  const [resource, setResource] = useState([])
  const healthQuery = useQuery({ queryKey: ['system-health'], queryFn: platformApi.systemHealth, refetchInterval: 5_000 })
  const gpuQuery = useQuery({ queryKey: ['system-gpu'], queryFn: platformApi.gpu, refetchInterval: 5_000 })
  const topicsQuery = useQuery({ queryKey: ['kafka-topics'], queryFn: platformApi.kafkaTopics, refetchInterval: 10_000 })
  const consumersQuery = useQuery({ queryKey: ['kafka-consumers'], queryFn: platformApi.kafkaConsumers, refetchInterval: 10_000 })
  const modelsQuery = useQuery({ queryKey: ['system-models'], queryFn: platformApi.models, refetchInterval: 30_000 })
  const usersQuery = useQuery({ queryKey: ['system-users'], queryFn: platformApi.users, refetchInterval: 30_000 })
  useEffect(() => {
    if (!gpuQuery.data || gpuQuery.data.error) return
    setResource((rows) => [...rows.slice(-23), { t: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }), gpu: Number(gpuQuery.data.gpu_util_pct || 0), vram: Number(gpuQuery.data.gpu_vram_used_mb || 0) }])
  }, [gpuQuery.dataUpdatedAt]) // eslint-disable-line react-hooks/exhaustive-deps
  const models = Array.isArray(modelsQuery.data?.models) ? modelsQuery.data.models.map((model) => ({ id: model.name, status: model.name === modelsQuery.data.current ? 'running' : 'standby', type: model.type || 'model', size: `${model.size_mb ?? '—'} MB` })) : []
  const platformUsers = Array.isArray(usersQuery.data) ? usersQuery.data.map((user) => ({ id: user.id, status: user.is_active ? 'active' : 'disabled', name: user.username, account: user.email, role: user.role, scope: user.role === 'admin' ? '全平台' : '授权范围', syncedAt: user.created_at ? new Date(user.created_at).toLocaleString('zh-CN') : '—' })) : []
  const topics = Array.isArray(topicsQuery.data?.topics) ? topicsQuery.data.topics : []
  const systemError = healthQuery.error || gpuQuery.error || topicsQuery.error || modelsQuery.error
  const selectTab = (value) => {
    setTab(value)
    const params = new URLSearchParams(location.search)
    params.set('tab', value)
    navigate(`${location.pathname}?${params.toString()}`, { replace: true })
  }
  return <AppShell pageTitle='系统与身份'>
    <PageHeader eyebrow='平台运行态 / 统一身份' title='系统与身份' description='统一查看运行健康、模型状态和身份同步；主任首屏只接收影响保障的摘要。' meta={`Platform API · ${healthQuery.data?.status || (healthQuery.isLoading ? 'loading' : 'unavailable')}`} />
    <div className='page-tabs'>{[['system', '系统运行'], ['identity', '身份同步']].map(([id, label]) => <button className={tab === id ? 'active' : ''} key={id} onClick={() => selectTab(id)}>{label}</button>)}</div>
    {systemError && <QualityNotice tone='warning' title='部分系统数据不可用'>{apiErrorMessage(systemError)}</QualityNotice>}
    {tab === 'system' && <>
    <div className='kpi-grid four'><KpiCard icon={Pulse} label='Platform 服务' value={healthQuery.data?.status || '—'} unit='' tone={healthQuery.data?.status === 'healthy' ? 'green' : 'amber'} /><KpiCard icon={Gauge} label='GPU 利用率' value={gpuQuery.data?.error ? '—' : gpuQuery.data?.gpu_util_pct ?? '—'} unit='%' tone='amber' /><KpiCard icon={Database} label='运行管道' value={healthQuery.data?.pipelines_active ?? '—'} unit='条' tone='cyan' /><KpiCard icon={Warning} label='WS 连接' value={healthQuery.data?.ws_connections ?? '—'} unit='个' tone='red' /></div>
    <div className='system-grid'><Panel title='服务健康'><div className='service-row'><StatusBadge value={healthQuery.data?.status === 'healthy' ? 'healthy' : 'degraded'} /><strong>Platform API</strong><span>{healthQuery.data?.service || 'unavailable'}</span></div><div className='service-row'><StatusBadge value={healthQuery.data?.kafka_connected ? 'healthy' : 'degraded'} /><strong>UAV 消息链路</strong><span>{healthQuery.data?.kafka_connected ? 'connected' : 'no data'}</span></div><div className='service-row'><StatusBadge value={consumersQuery.data?.state === 'Stable' ? 'healthy' : 'degraded'} /><strong>Consumer</strong><span>{consumersQuery.data?.group_id || '—'} · {consumersQuery.data?.members ?? 0} member</span></div><div className='service-row'><StatusBadge value='unknown' /><strong>road9 / TimescaleDB</strong><span>当前健康接口未返回数据库指标</span></div></Panel><Panel title='GPU 会话实时趋势'>{resource.length ? <ResponsiveContainer width='100%' height='100%'><AreaChart data={resource}><CartesianGrid vertical={false} stroke='rgba(120,145,185,.12)' /><XAxis dataKey='t' tick={{ fill: '#7c8aa0', fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis tick={{ fill: '#7c8aa0', fontSize: 10 }} axisLine={false} tickLine={false} /><Area dataKey='gpu' stroke='#ffbe55' fill='#6b4f25' /><Area dataKey='vram' stroke='#6d9eff' fill='#294c7b' /></AreaChart></ResponsiveContainer> : <div className='live-state'>等待 GPU 实时采样…</div>}</Panel></div>
    <Panel title='AI 模型文件'>{models.length ? <DataTable rows={models} columns={[{ key: 'status', label: '状态', render: (value) => <StatusBadge value={value} /> }, { key: 'id', label: '模型文件' }, { key: 'type', label: '类型' }, { key: 'size', label: '大小' }]} /> : <div className='live-state empty'>weights 目录未返回模型文件</div>}</Panel>
    <Panel title='消息 Topic' subtitle='非 uav_ Topic 仅作为迁移期遗留链路如实展示'>{topics.length ? <DataTable rows={topics.map((topic) => ({ ...topic, status: String(topic.name || '').startsWith('uav_') ? 'healthy' : 'legacy' }))} columns={[{ key: 'status', label: '状态', render: (value) => <StatusBadge value={value} /> }, { key: 'name', label: 'Topic' }, { key: 'partitions', label: '分区' }, { key: 'tps', label: 'TPS' }, { key: 'lag', label: 'Lag' }]} /> : <div className='live-state empty'>暂无 Topic 观测数据</div>}</Panel>
    </>}
    {tab === 'identity' && <><QualityNotice tone='info' title='只读身份源'>当前仅支持查看用户同步结果，邀请、编辑和删除功能尚未开放。</QualityNotice><Panel title='身份同步结果'>{usersQuery.isLoading ? <div className='live-state'>正在加载用户…</div> : platformUsers.length ? <DataTable rows={platformUsers} columns={[{ key: 'status', label: '状态', render: (value) => <StatusBadge value={value} /> }, { key: 'id', label: '用户 ID' }, { key: 'name', label: '用户名' }, { key: 'account', label: '邮箱' }, { key: 'role', label: '平台角色' }, { key: 'scope', label: '数据范围' }, { key: 'syncedAt', label: '创建时间' }]} /> : <div className='live-state empty'>暂无用户数据</div>}</Panel></>}
  </AppShell>
}

export function UsersPage() {
  return <AppShell pageTitle='用户同步'>
    <PageHeader eyebrow='统一身份 · 只读视图' title='用户与权限同步' description='业务用户、组织、角色和管辖范围由统一身份或主平台管理；本地只查看同步结果和最小运维账号。' meta='最近同步 10:30:04 · 0 个冲突' />
    <QualityNotice tone='info' title='权限边界'>本地页面不复制主平台警情、派警、处置和案件归档权限；本地运维账号不承载业务辖区分配。</QualityNotice>
    <Panel title='身份同步结果'><DataTable rows={users} columns={[{ key: 'status', label: '状态', render: (value) => <StatusBadge value={value} /> }, { key: 'id', label: '用户 ID' }, { key: 'name', label: '姓名' }, { key: 'account', label: '账号' }, { key: 'role', label: '角色' }, { key: 'scope', label: '数据范围' }, { key: 'syncedAt', label: '同步时间' }]} /></Panel>
  </AppShell>
}
