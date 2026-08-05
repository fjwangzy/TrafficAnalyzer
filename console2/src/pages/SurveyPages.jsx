import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft, ArrowRight, Camera, Check, CheckCircle, Crosshair, FilePdf,
  FolderOpen, Plus, ShieldCheck, Trash, UploadSimple, Warning, X,
} from '@phosphor-icons/react'
import { AppShell } from '../components/AppShell'
import {
  DataTable, InfoRow, KpiCard, PageHeader, Panel, QualityNotice,
  Segmented, StatusBadge, WorkflowSteps,
} from '../components/Common'
import { apiErrorMessage, platformApi } from '../lib/api'
import {
  geometrySegments, imageContainViewport, metricPolygonAreaLabel, metricSegmentLabel,
  polygonArea, polygonCentroid,
} from '../lib/surveyGeometry'
import { useAppState } from '../state/AppState'

const surveySteps = ['任务核验', '采集质检', '点线面量算', '技术复核', '报告交付']
const completeChecklist = ['task_context', 'operator_authorized', 'site_command_confirmed', 'device_ready', 'storage_ready']
const checklistLabels = {
  task_context: '任务来源、现场位置与处置上下文一致',
  operator_authorized: '当前操作者已获得该任务授权',
  site_command_confirmed: '已与现场指挥确认起降和采集范围',
  device_ready: '无人机、相机、遥测与时间同步可用',
  storage_ready: '本地原始材料存储空间充足',
}
const reviewChecklist = [
  ['task_and_location', '任务与位置一致'],
  ['source_materials', '原始材料引用完整'],
  ['coordinate_chain', '像素至 ENU 坐标链可追溯'],
  ['measurements', '量算对象及结果已核验'],
  ['edit_history', '人工编辑版本完整'],
  ['quality_status', '量算质量状态已记录'],
]

const requestKey = (prefix) => `${prefix}-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`}`

function notify(dispatch, tone, text) {
  dispatch({ type: 'TOAST', value: { tone, text } })
}

function useSurveyTask() {
  const { id } = useParams()
  const [task, setTask] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const reload = useCallback(async () => {
    setLoading(true)
    try {
      setTask(await platformApi.surveyTask(id))
      setError('')
    } catch (value) {
      setTask(null)
      setError(apiErrorMessage(value, '测绘任务加载失败'))
    } finally {
      setLoading(false)
    }
  }, [id])
  useEffect(() => { reload() }, [reload])
  return { id, task, setTask, loading, error, reload }
}

function SurveyShell({ task, step, title, description, children, actions }) {
  const navigate = useNavigate()
  if (!task) return <AppShell pageTitle={title}><QualityNotice tone='warning' title='任务不可用'>无法读取任务，请返回列表重试。</QualityNotice></AppShell>
  return <AppShell pageTitle={title}>
    <button className='back-link' onClick={() => navigate('/survey')}><ArrowLeft size={15} /> 返回任务列表</button>
    <PageHeader eyebrow={`${task.id} · ${task.version}`} title={title} description={description} meta={`${task.location} · ${task.owner}`} actions={actions} />
    <WorkflowSteps steps={surveySteps} active={step} />
    {children}
  </AppShell>
}

function LoadingState({ text = '正在读取本地 road9 数据…' }) {
  return <Panel><div className='survey-empty'><span className='survey-spinner' />{text}</div></Panel>
}

function SurveyTaskUnavailable({ title, error, onRetry }) {
  const navigate = useNavigate()
  return <AppShell pageTitle={title}>
    <h1 className='sr-only'>{title}</h1>
    <div className='survey-task-unavailable' role='alert'>
      <QualityNotice tone='warning' title='任务不可用'>{error || '无法读取任务，请重试或返回任务列表。'}</QualityNotice>
      <div className='page-actions'>
        <button className='secondary-button' onClick={() => navigate('/survey')}><ArrowLeft size={15} /> 返回任务列表</button>
        <button className='primary-button' onClick={onRetry}>重试</button>
      </div>
    </div>
  </AppShell>
}

function EvidenceImage({ url, alt, className, imageRef, onLoad, onClick, onDoubleClick, onMouseMove, onMouseLeave }) {
  const [source, setSource] = useState('')
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const evidenceId = url?.match(/survey-evidence\/([^/]+)\/content/)?.[1]
  useEffect(() => {
    let active = true
    let objectUrl = ''
    setSource('')
    setError('')
    if (!evidenceId) {
      setError('证据图片地址无效')
      return undefined
    }
    platformApi.surveyEvidence(evidenceId).then((blob) => {
      objectUrl = URL.createObjectURL(blob)
      if (active) setSource(objectUrl)
    }).catch((value) => {
      if (active) setError(apiErrorMessage(value, '证据图片读取失败'))
    })
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [attempt, evidenceId])
  if (error) return <div className={`evidence-error ${className || ''}`} role='alert'><span>{error}</span><button type='button' onClick={() => setAttempt((value) => value + 1)}>重试图片</button></div>
  if (!source) return <div className={`evidence-loading ${className || ''}`}>正在校验证据哈希并读取图像…</div>
  return <img ref={imageRef} src={source} alt={alt} className={className} onLoad={onLoad} onClick={onClick} onDoubleClick={onDoubleClick} onMouseMove={onMouseMove} onMouseLeave={onMouseLeave} />
}

export function SurveyListPage() {
  const navigate = useNavigate()
  const { dispatch } = useAppState()
  const [tasks, setTasks] = useState([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ title: '事故现场无人机测绘', scene_location: '小清河北路与水屯路路口', owner_name: '事故处理一组' })
  const load = useCallback(async () => {
    try { setTasks(await platformApi.surveyTasks()) }
    catch (error) { notify(dispatch, 'error', apiErrorMessage(error, '任务列表加载失败')) }
    finally { setLoading(false) }
  }, [dispatch])
  useEffect(() => { load() }, [load])
  const createTask = async () => {
    try {
      const task = await platformApi.createSurveyTask(form, requestKey('survey-create'))
      const started = await platformApi.surveyAction(task.id, { action: 'start_precheck', expected_revision: task.revision }, requestKey('survey-precheck-start'))
      setCreating(false)
      navigate(`/survey/${started.id}/precheck`)
    } catch (error) { notify(dispatch, 'error', apiErrorMessage(error, '创建任务失败')) }
  }
  const pendingReview = tasks.filter((item) => item.status === 'pending_review').length
  return <AppShell pageTitle='测绘任务'>
    <PageHeader eyebrow='S3 · 事故测绘' title='事故测绘任务' description='从作业前置核验到报告交付完整留痕；系统输出用于辅助量算和技术复核，不替代法定事故认定。' meta={`${tasks.length} 个任务 · ${pendingReview} 个待技术复核`} actions={<button className='primary-button' onClick={() => setCreating(true)}><Plus size={15} /> 创建测绘任务</button>} />
    <div className='kpi-grid four'><KpiCard icon={FolderOpen} label='进行中任务' value={tasks.filter((item) => !['completed', 'cancelled'].includes(item.status)).length} unit='个' detail='实时来自 road9' /><KpiCard icon={Camera} label='待采集/处理中' value={tasks.filter((item) => ['ready', 'collecting'].includes(item.status)).length} unit='个' tone='cyan' /><KpiCard icon={ShieldCheck} label='待技术复核' value={pendingReview} unit='个' tone='amber' /><KpiCard icon={FilePdf} label='已完成交付' value={tasks.filter((item) => item.delivery === 'delivered').length} unit='份' tone='green' /></div>
    {loading ? <LoadingState /> : <Panel title='任务列表' subtitle='事故民警仅可访问分配给自己或未分配的任务'><DataTable onRowClick={(row) => navigate(`/survey/${row.id}/${row.status === 'prechecking' || row.status === 'precheck_failed' ? 'precheck' : row.status === 'measuring' || row.status === 'returned' ? 'measure' : row.status === 'pending_review' ? 'review' : row.status === 'technical_reviewed' || row.delivery !== 'not_generated' ? 'report' : 'capture'}`)} rows={tasks} columns={[{ key: 'status', label: '任务状态', render: (value) => <StatusBadge value={value} /> }, { key: 'title', label: '任务' }, { key: 'id', label: '任务 ID' }, { key: 'location', label: '位置' }, { key: 'owner', label: '负责组' }, { key: 'quality', label: '质量', render: (value) => <StatusBadge value={value} /> }, { key: 'version', label: '成果版本' }, { key: 'delivery', label: '投递', render: (value) => <StatusBadge value={value} /> }]} /></Panel>}
    {creating && <div className='modal-backdrop'><div className='modal-card'><header><strong>创建事故现场测绘任务</strong><button onClick={() => setCreating(false)}><X size={18} /></button></header><label>任务名称<input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label><label>现场位置<input value={form.scene_location} onChange={(event) => setForm({ ...form, scene_location: event.target.value })} /></label><label>负责组<input value={form.owner_name} onChange={(event) => setForm({ ...form, owner_name: event.target.value })} /></label><footer><button className='secondary-button' onClick={() => setCreating(false)}>取消</button><button className='primary-button' onClick={createTask}>创建并开始核验</button></footer></div></div>}
  </AppShell>
}

export function SurveyPrecheckPage() {
  const { task, setTask, loading, error, reload } = useSurveyTask()
  const navigate = useNavigate()
  const { dispatch } = useAppState()
  const [checks, setChecks] = useState(Object.fromEntries(completeChecklist.map((key) => [key, false])))
  if (loading) return <AppShell pageTitle='任务核验'><LoadingState /></AppShell>
  if (!task) return <SurveyTaskUnavailable title='任务核验' error={error} onRetry={reload} />
  const complete = async () => {
    try {
      const next = await platformApi.surveyAction(task.id, { action: 'complete_precheck', expected_revision: task.revision, checklist: checks }, requestKey('survey-precheck-complete'))
      setTask(next)
      if (next.status === 'ready') navigate(`/survey/${task.id}/capture`)
      else notify(dispatch, 'warning', '前置核验未完成，任务已标记为 precheck_failed')
    } catch (value) { notify(dispatch, 'error', apiErrorMessage(value, '核验提交失败')) }
  }
  return <SurveyShell task={task} step={0} title='任务与作业前置核验' description='开始采集前确认任务授权、现场指挥、设备状态和原始材料存储；任一必选项缺失都不能进入采集。' actions={<button className='primary-button' disabled={!completeChecklist.every((key) => checks[key])} onClick={complete}>完成核验并进入采集 <ArrowRight size={15} /></button>}>
    {error && <QualityNotice tone='warning' title='读取失败'>{error}</QualityNotice>}
    <div className='precheck-layout'><Panel title='强制核验清单' subtitle='结果、操作者与时间写入不可变审计日志'>{completeChecklist.map((key) => <label className='check-row precheck-row' key={key}><input type='checkbox' checked={checks[key]} onChange={(event) => setChecks({ ...checks, [key]: event.target.checked })} /><CheckCircle size={18} weight={checks[key] ? 'fill' : 'regular'} />{checklistLabels[key]}</label>)}</Panel><Panel title='任务上下文'><InfoRow label='任务 ID' value={task.id} /><InfoRow label='现场位置' value={task.location} /><InfoRow label='负责组' value={task.owner} /><InfoRow label='当前状态' value={task.status} badge={task.status} /><InfoRow label='数据库' value='local PostgreSQL · road9' /></Panel></div>
  </SurveyShell>
}

export function SurveyCapturePage() {
  const { task, setTask, loading, error, reload: reloadTask } = useSurveyTask()
  const navigate = useNavigate()
  const { dispatch } = useAppState()
  const [batches, setBatches] = useState([])
  const [batchId, setBatchId] = useState('')
  const [frames, setFrames] = useState([])
  const [frameId, setFrameId] = useState('')
  const [sources, setSources] = useState([])
  const [sourceProfileId, setSourceProfileId] = useState('')
  const [video, setVideo] = useState(null)
  const [telemetry, setTelemetry] = useState(null)
  const [busy, setBusy] = useState(false)
  const selectedBatch = batches.find((item) => item.id === batchId)
  const selectedFrame = frames.find((item) => item.id === frameId) || frames[0]
  const loadBatches = useCallback(async () => {
    if (!task) return
    const rows = await platformApi.surveyBatches(task.id)
    setBatches(rows)
    setBatchId((current) => current || rows[0]?.id || '')
  }, [task])
  useEffect(() => { loadBatches().catch((error) => notify(dispatch, 'error', apiErrorMessage(error))) }, [loadBatches, dispatch])
  useEffect(() => {
    platformApi.sources().then((rows) => {
      const local = rows.filter((item) => item.mode === 'local' && item.enabled)
      setSources(local)
      setSourceProfileId((current) => current || local.find((item) => item.validation_status !== 'invalid')?.profile_id || '')
    }).catch((error) => notify(dispatch, 'error', apiErrorMessage(error, '本地来源加载失败')))
  }, [dispatch])
  useEffect(() => {
    if (!task || !batchId) return
    platformApi.surveyFrames(task.id, batchId).then((rows) => { setFrames(rows); setFrameId((current) => current || rows[0]?.id || '') })
  }, [task, batchId, batches])
  useEffect(() => {
    if (!batches.some((item) => ['queued', 'processing'].includes(item.status))) return undefined
    const timer = window.setInterval(() => loadBatches().catch(() => {}), 1500)
    return () => window.clearInterval(timer)
  }, [batches, loadBatches])
  if (loading) return <AppShell pageTitle='采集与质量预检'><LoadingState /></AppShell>
  if (!task) return <SurveyTaskUnavailable title='采集与质量预检' error={error} onRetry={reloadTask} />
  const importAssets = async () => {
    setBusy(true)
    try {
      await platformApi.importSurveyBatch(task.id, { source_profile_id: sourceProfileId }, requestKey('survey-import'))
      await Promise.all([loadBatches(), reloadTask()]); notify(dispatch, 'info', '服务器本地素材已零复制进入后台处理队列')
    } catch (error) { notify(dispatch, 'error', apiErrorMessage(error, '服务器材料导入失败')) }
    finally { setBusy(false) }
  }
  const upload = async () => {
    if (!video || !telemetry) return
    setBusy(true)
    try { await platformApi.uploadSurveyBatch(task.id, video, telemetry, requestKey('survey-upload')); await Promise.all([loadBatches(), reloadTask()]); notify(dispatch, 'info', '上传完成，后台开始提取关键帧') }
    catch (error) { notify(dispatch, 'error', apiErrorMessage(error, '上传失败')) }
    finally { setBusy(false) }
  }
  const selectAndContinue = async () => {
    try {
      const next = await platformApi.surveyAction(task.id, { action: 'select_batch', expected_revision: task.revision, batch_id: batchId }, requestKey('survey-select-batch'))
      setTask(next); navigate(`/survey/${task.id}/measure`)
    } catch (error) { notify(dispatch, 'error', apiErrorMessage(error, '批次选择失败')) }
  }
  const quality = selectedBatch?.quality_checks || {}
  return <SurveyShell task={task} step={1} title='采集与质量预检' description='从已登记服务器目录引用 MP4 与 DJI 遥测，后台提取可追溯关键帧；原始大文件不重复上传或复制。' actions={<button className='primary-button' disabled={!['ready', 'collecting', 'returned', 'measuring'].includes(task.status) || !['ready', 'degraded', 'selected'].includes(selectedBatch?.status) || !frames.some((item) => item.has_metric_transform)} onClick={selectAndContinue}>选择批次并进入量算 <ArrowRight size={15} /></button>}>
    <div className='survey-ingest-bar'><select aria-label='服务器本地来源' value={sourceProfileId} onChange={(event) => setSourceProfileId(event.target.value)}>{sources.map((item) => <option key={item.profile_id} value={item.profile_id}>{item.display_name} · {item.telemetry.source_type} · {item.validation_status}</option>)}</select><button className='secondary-button' disabled={busy || !sourceProfileId} onClick={importAssets}><FolderOpen size={15} /> 引用目录素材</button><details><summary>其他材料上传</summary><label className='file-button'><UploadSimple size={15} /> 选择 MP4<input type='file' accept='video/mp4' onChange={(event) => setVideo(event.target.files?.[0] || null)} /></label><label className='file-button'><UploadSimple size={15} /> 选择 SRT<input type='file' accept='.srt' onChange={(event) => setTelemetry(event.target.files?.[0] || null)} /></label><button className='secondary-button' disabled={busy || !video || !telemetry} onClick={upload}>上传并处理</button></details><span>{selectedBatch?.source_profile_id || '请选择已登记来源'}</span></div>
    <div className='survey-capture-layout'><Panel className='capture-stage' title='原始关键帧' subtitle={selectedFrame ? `${selectedBatch?.id} · Frame #${selectedFrame.frame_number} · ${selectedFrame.timestamp_sec.toFixed(2)}s` : '等待真实材料处理'}><div className='video-stage'>{selectedFrame ? <EvidenceImage url={selectedFrame.image_url} alt='事故测绘真实采集关键帧' /> : <div className='survey-empty'><Camera size={30} />导入或上传 MP4+SRT 后在此显示真实关键帧</div>}{selectedBatch?.telemetry_coverage != null && <div className='coverage-mask'>遥测覆盖 {(selectedBatch.telemetry_coverage * 100).toFixed(1)}%</div>}</div><div className='frame-strip'>{frames.map((frame) => <button key={frame.id} className={frame.id === selectedFrame?.id ? 'active' : ''} onClick={() => setFrameId(frame.id)}><EvidenceImage url={frame.image_url} alt={`关键帧 ${frame.frame_number}`} /><span>#{frame.frame_number}</span></button>)}</div></Panel><div className='capture-side'><Panel title='采集批次'>{batches.length ? batches.map((item) => <button className={`batch-row ${batchId === item.id ? 'active' : ''}`} key={item.id} onClick={() => { setBatchId(item.id); setFrameId('') }}><span><Camera size={16} />{item.id}</span><StatusBadge value={item.status} /></button>) : <div className='survey-empty'>暂无采集批次</div>}</Panel><Panel title='实测质量观测'><InfoRow label='处理状态' value={selectedBatch?.status || '—'} badge={selectedBatch?.status} /><InfoRow label='遥测覆盖' value={selectedBatch ? `${((selectedBatch.telemetry_coverage || 0) * 100).toFixed(2)}%` : '—'} badge='unverified' /><InfoRow label='关键帧 / 变换' value={`${quality.keyframes_extracted || 0} / ${quality.homography_available || 0}`} /><InfoRow label='清晰度 Laplacian' value={quality.clarity_laplacian_mean ?? '—'} badge='unverified' /><InfoRow label='曝光均值' value={quality.exposure_mean ?? '—'} badge='unverified' /><InfoRow label='RTK / 空间覆盖' value={`${quality.rtk_status || 'unavailable'} / ${quality.spatial_coverage || 'unavailable'}`} badge='unverified' /></Panel></div></div>
  </SurveyShell>
}

function MeasurementCanvas({ frame, tool, draft, onPoint, onFinish, measurements, editable }) {
  const imageRef = useRef(null)
  const canvasRef = useRef(null)
  const [hoverPoint, setHoverPoint] = useState(null)
  const draw = useCallback(() => {
    const image = imageRef.current
    const canvas = canvasRef.current
    if (!image || !canvas || !image.naturalWidth) return
    const pixelRatio = globalThis.devicePixelRatio || 1
    const viewport = imageContainViewport(image.clientWidth, image.clientHeight, image.naturalWidth, image.naturalHeight)
    if (!viewport) return
    canvas.width = image.clientWidth * pixelRatio
    canvas.height = image.clientHeight * pixelRatio
    canvas.style.width = `${image.clientWidth}px`
    canvas.style.height = `${image.clientHeight}px`
    const context = canvas.getContext('2d')
    context.scale(pixelRatio, pixelRatio)
    const screenPoint = ([x, y]) => [viewport.offsetX + x * viewport.scale, viewport.offsetY + y * viewport.scale]
    const draftPoints = editable && draft.length && hoverPoint ? [...draft, hoverPoint] : draft
    const shapes = [
      ...measurements.filter((item) => item.frame_id === frame.id).map((item) => ({
        points: item.image_geometry,
        metricPoints: item.metric_geometry,
        type: item.geometry_type,
        saved: true,
      })),
      { points: draftPoints, committedPoints: draft.length, type: tool, saved: false },
    ]
    shapes.forEach((shape) => {
      if (!shape.points?.length) return
      context.beginPath()
      shape.points.forEach((point, index) => {
        const [x, y] = screenPoint(point)
        if (index) context.lineTo(x, y)
        else context.moveTo(x, y)
      })
      if (['area', 'object'].includes(shape.type) && shape.points.length > 2) context.closePath()
      context.lineWidth = shape.saved ? 2 : 2.5
      context.strokeStyle = shape.saved ? '#20c8d8' : '#f4c95d'
      context.fillStyle = shape.saved ? 'rgba(32,200,216,.12)' : 'rgba(244,201,93,.14)'
      if (['area', 'object'].includes(shape.type) && shape.points.length > 2) context.fill()
      context.stroke()
      shape.points.slice(0, shape.saved ? undefined : shape.committedPoints).forEach((point) => {
        const [x, y] = screenPoint(point)
        context.beginPath(); context.arc(x, y, 4, 0, Math.PI * 2)
        context.fillStyle = shape.saved ? '#20c8d8' : '#f4c95d'; context.fill()
      })
      const closeForLabels = shape.saved || Boolean(hoverPoint && ['area', 'object'].includes(shape.type))
      geometrySegments(shape.points, shape.type, closeForLabels).forEach(([start, end], index) => {
        const metricStart = shape.metricPoints?.[index]
        const metricEnd = shape.metricPoints?.[(index + 1) % shape.metricPoints.length]
        const label = metricStart && metricEnd
          ? `${Math.hypot(metricEnd[0] - metricStart[0], metricEnd[1] - metricStart[1]).toFixed(2)} m`
          : metricSegmentLabel(start, end, frame.metric_transform)
        if (!label) return
        const [x1, y1] = screenPoint(start)
        const [x2, y2] = screenPoint(end)
        const x = (x1 + x2) / 2
        const y = (y1 + y2) / 2
        context.font = '600 11px system-ui, sans-serif'
        context.textAlign = 'center'
        context.textBaseline = 'middle'
        context.lineJoin = 'round'
        context.lineWidth = 3
        context.strokeStyle = 'rgba(2, 8, 15, .86)'
        context.strokeText(label, x, y)
        context.fillStyle = shape.saved ? '#a9f5fb' : '#ffe69a'
        context.fillText(label, x, y)
      })
      if (shape.type === 'area' && shape.points.length > 2) {
        const measuredArea = shape.metricPoints?.length > 2 ? polygonArea(shape.metricPoints) : null
        const areaLabel = Number.isFinite(measuredArea)
          ? `${measuredArea.toFixed(2)} m²`
          : metricPolygonAreaLabel(shape.points, frame.metric_transform)
        const center = polygonCentroid(shape.points)
        if (areaLabel && center) {
          const [x, y] = screenPoint(center)
          context.font = '700 14px system-ui, sans-serif'
          context.textAlign = 'center'
          context.textBaseline = 'middle'
          context.lineJoin = 'round'
          context.lineWidth = 4
          context.strokeStyle = 'rgba(2, 8, 15, .9)'
          context.strokeText(areaLabel, x, y)
          context.fillStyle = shape.saved ? '#d9ffff' : '#fff2a8'
          context.fillText(areaLabel, x, y)
        }
      }
    })
  }, [draft, editable, frame.id, frame.metric_transform, hoverPoint, measurements, tool])
  useEffect(() => { draw(); window.addEventListener('resize', draw); return () => window.removeEventListener('resize', draw) }, [draw])
  const eventPoint = (event) => {
    const image = imageRef.current
    const rect = image.getBoundingClientRect()
    const viewport = imageContainViewport(rect.width, rect.height, image.naturalWidth, image.naturalHeight)
    if (!viewport) return null
    const x = event.clientX - rect.left - viewport.offsetX
    const y = event.clientY - rect.top - viewport.offsetY
    if (x < 0 || y < 0 || x > viewport.width || y > viewport.height) return null
    return [x / viewport.scale, y / viewport.scale]
  }
  const click = (event) => {
    if (!editable) return
    const point = eventPoint(event)
    if (point) onPoint(point)
  }
  const livePoints = draft.length && hoverPoint ? [...draft, hoverPoint] : draft
  const liveAreaLabel = tool === 'area' && livePoints.length > 2 ? metricPolygonAreaLabel(livePoints, frame.metric_transform) : ''
  const liveLabel = draft.length && hoverPoint ? metricSegmentLabel(draft.at(-1), hoverPoint, frame.metric_transform) : ''
  return <div className='measure-canvas live-measure-canvas'>
    <EvidenceImage imageRef={imageRef} url={frame.bev_url} alt='由真实关键帧生成的正射量算底图' onLoad={draw} onClick={click} onDoubleClick={editable ? onFinish : undefined} onMouseMove={editable ? (event) => setHoverPoint(eventPoint(event)) : undefined} onMouseLeave={() => setHoverPoint(null)} />
    <canvas ref={canvasRef} aria-hidden='true' />
    <span className='sr-only' aria-live='polite'>{liveAreaLabel ? `当前面积 ${liveAreaLabel}` : liveLabel ? `当前边长 ${liveLabel}` : ''}</span>
  </div>
}

export function SurveyMeasurePage() {
  const { task, loading, error, reload: reloadTask } = useSurveyTask()
  const navigate = useNavigate()
  const { dispatch } = useAppState()
  const [frames, setFrames] = useState([])
  const [measurements, setMeasurements] = useState([])
  const [annotations, setAnnotations] = useState([])
  const [frameId, setFrameId] = useState('')
  const [tool, setTool] = useState('line')
  const [draft, setDraft] = useState([])
  const [category, setCategory] = useState('人工量算')
  const frame = frames.find((item) => item.id === frameId) || frames.find((item) => item.has_metric_transform)
  const reload = useCallback(async () => {
    if (!task) return
    const [frameRows, measurementRows, annotationRows] = await Promise.all([platformApi.surveyFrames(task.id, task.selected_batch_id), platformApi.surveyMeasurements(task.id), platformApi.surveyAnnotations(task.id)])
    setFrames(frameRows); setMeasurements(measurementRows); setAnnotations(annotationRows); setFrameId((current) => current || frameRows.find((item) => item.has_metric_transform)?.id || '')
  }, [task])
  useEffect(() => { reload().catch((error) => notify(dispatch, 'error', apiErrorMessage(error))) }, [reload, dispatch])
  if (loading) return <AppShell pageTitle='点线面量算'><LoadingState /></AppShell>
  if (!task) return <SurveyTaskUnavailable title='点线面量算' error={error} onRetry={reloadTask} />
  const editable = ['measuring', 'returned'].includes(task.status)
  const required = tool === 'point' ? 1 : tool === 'line' ? 2 : 3
  const save = async (points = draft) => {
    if (!frame || points.length < required) return
    try {
      await platformApi.createSurveyMeasurement(task.id, { frame_id: frame.id, geometry_type: tool, category, image_geometry: points }, requestKey('survey-measure'))
      if (tool === 'object') await platformApi.createSurveyAnnotation(task.id, { frame_id: frame.id, category, image_geometry: points, source: 'manual' }, requestKey('survey-annotation'))
      setDraft([]); await reload(); notify(dispatch, 'success', '量算结果与像素/ENU 几何已保存')
    } catch (error) { notify(dispatch, 'error', apiErrorMessage(error, '量算保存失败')) }
  }
  const addPoint = (point) => {
    const next = [...draft, point]
    setDraft(next)
    if ((tool === 'point' && next.length === 1) || (tool === 'line' && next.length === 2)) save(next)
  }
  const submit = async () => {
    try { await platformApi.surveyAction(task.id, { action: 'submit_review', expected_revision: task.revision }, requestKey('survey-submit-review')); navigate(`/survey/${task.id}/review`) }
    catch (error) { notify(dispatch, 'error', apiErrorMessage(error, '提交复核失败')) }
  }
  return <SurveyShell task={task} step={2} title='点线面量算' description='在真实 BEV 关键帧上标点、测线、测面积或勾画对象；服务端用帧变换计算 ENU 米制结果并保留版本。' actions={<button className='primary-button' disabled={task.status !== 'measuring' || !measurements.length} onClick={submit}>提交技术复核 <ArrowRight size={15} /></button>}>
    <div className='measure-toolbar'><Segmented value={tool} onChange={(value) => { if (editable) { setTool(value); setDraft([]) } }} options={[{ value: 'point', label: '标点' }, { value: 'line', label: '线段' }, { value: 'polyline', label: '折线' }, { value: 'area', label: '面积' }, { value: 'object', label: '对象' }]} /><input aria-label='量算分类' disabled={!editable} value={category} onChange={(event) => setCategory(event.target.value)} /><button className='secondary-button' disabled={!editable || !draft.length} onClick={() => setDraft((points) => points.slice(0, -1))}>撤销点</button><button className='secondary-button' disabled={!editable || draft.length < required || ['point', 'line'].includes(tool)} onClick={() => save()}>完成量算</button><span>{editable ? '折线/面积可双击完成 · 坐标由服务端计算' : '当前任务已离开量算态，仅可查看历史成果'}</span></div>
    <div className='measure-layout'><Panel className='measure-stage' title='正射量算画布' subtitle={frame ? `${frame.batch_id} · Frame #${frame.frame_number} · ENU 米制平面` : '等待有效测量变换'}>{frame ? <MeasurementCanvas frame={frame} tool={tool} draft={draft} onPoint={addPoint} onFinish={() => save()} measurements={measurements} editable={editable} /> : <div className='survey-empty'><Warning size={30} />当前批次没有可量算帧</div>}</Panel><div className='measure-side'><Panel title='量算对象'>{measurements.length ? measurements.map((item) => <div className='object-row' key={item.id}><span>{item.id}</span><div><strong>{item.category || item.geometry_type}</strong><small>{item.display_value}</small></div><button disabled={!editable} aria-label={`删除 ${item.id}`} onClick={async () => { await platformApi.deleteSurveyMeasurement(task.id, item.id, item.revision); reload() }}><Trash size={15} /></button></div>) : <div className='survey-empty'>点击画布开始第一项量算</div>}</Panel><Panel title={`场景标注 · ${annotations.length}`}>{annotations.length ? annotations.map((item) => <div className='object-row' key={item.id}><span>{item.id}</span><div><strong>{item.category}</strong><small>{item.review_state} · v{item.revision}</small></div><button disabled={!editable} aria-label={`删除标注 ${item.id}`} onClick={async () => { await platformApi.deleteSurveyAnnotation(task.id, item.id, item.revision); reload() }}><Trash size={15} /></button></div>) : <div className='survey-empty'>使用“对象”工具保存车辆、痕迹或散落物标注</div>}</Panel><Panel title='当前帧质量'><InfoRow label='来源帧' value={frame ? `#${frame.frame_number}` : '—'} /><InfoRow label='坐标链' value='BEV px → image px → ENU m' /><InfoRow label='测量变换' value={frame?.has_metric_transform ? 'available' : 'unavailable'} badge={frame?.has_metric_transform ? 'unverified' : 'warning'} /><InfoRow label='成果质量' value='unverified' badge='unverified' /></Panel></div></div>
  </SurveyShell>
}

export function SurveyReviewPage() {
  const { task, loading, error, reload } = useSurveyTask()
  const navigate = useNavigate()
  const { dispatch } = useAppState()
  const [frames, setFrames] = useState([])
  const [measurements, setMeasurements] = useState([])
  const [reasonOpen, setReasonOpen] = useState(false)
  const [reason, setReason] = useState('覆盖或量算结果需重新确认')
  const [returnType, setReturnType] = useState('measurement')
  const [checks, setChecks] = useState(() => Object.fromEntries(reviewChecklist.map(([key]) => [key, false])))
  useEffect(() => { if (task) Promise.all([platformApi.surveyFrames(task.id, task.selected_batch_id), platformApi.surveyMeasurements(task.id)]).then(([a, b]) => { setFrames(a); setMeasurements(b) }) }, [task])
  useEffect(() => {
    setChecks(Object.fromEntries(reviewChecklist.map(([key]) => [key, false])))
  }, [task?.id])
  if (loading) return <AppShell pageTitle='技术复核'><LoadingState /></AppShell>
  if (!task) return <SurveyTaskUnavailable title='技术复核' error={error} onRetry={reload} />
  const frame = frames.find((item) => item.has_metric_transform) || frames[0]
  const reviewComplete = reviewChecklist.every(([key]) => checks[key])
  const act = async (action, payload = {}) => {
    try {
      await platformApi.surveyAction(task.id, { action, expected_revision: task.revision, ...payload }, requestKey(`survey-${action}`))
      navigate(action === 'approve_review' ? `/survey/${task.id}/report` : action === 'return' && returnType === 'capture' ? `/survey/${task.id}/capture` : `/survey/${task.id}/measure`)
    } catch (error) { notify(dispatch, 'error', apiErrorMessage(error, '复核操作失败')) }
  }
  return <SurveyShell task={task} step={3} title='技术复核' description='逐项对照原始帧、BEV 示意、量算结果和质量边界；通过只表示技术复核，不等同法定事故认定。' actions={<><button className='danger-button' disabled={task.status !== 'pending_review'} onClick={() => setReasonOpen(true)}><X size={15} /> 退回修订/补拍</button><button className='primary-button' disabled={task.status !== 'pending_review' || !reviewComplete} onClick={() => act('approve_review', { checklist: checks })}><Check size={15} /> 技术复核通过</button></>}>
    <div className='review-layout'><Panel title='原始帧与正射图对照'><div className='compare-panes'>{frame ? <><div><span>原始帧 #{frame.frame_number}</span><EvidenceImage url={frame.image_url} alt='真实原始关键帧' /></div><div><span>BEV 量算底图</span><EvidenceImage url={frame.bev_url} alt='真实 BEV 关键帧' /></div></> : <div className='survey-empty'>未找到证据帧</div>}</div></Panel><div className='review-side'><Panel title='复核清单'>{reviewChecklist.map(([key, label]) => <label className='check-row' key={key}><input type='checkbox' checked={checks[key]} onChange={(event) => setChecks((current) => ({ ...current, [key]: event.target.checked }))} /><CheckCircle size={16} weight={checks[key] ? 'fill' : 'regular'} />{key === 'measurements' ? `${label} · ${measurements.length} 项` : label}</label>)}</Panel><Panel title='量算结果'>{measurements.map((item) => <InfoRow key={item.id} label={item.category || item.id} value={item.display_value} badge={item.quality_status} />)}</Panel></div></div>
    {reasonOpen && <div className='modal-backdrop'><div className='modal-card'><header><strong>退回测绘成果</strong><button onClick={() => setReasonOpen(false)}><X size={18} /></button></header><label>返工类型<select value={returnType} onChange={(event) => setReturnType(event.target.value)}><option value='capture'>补拍</option><option value='measurement'>修订量算</option></select></label><label>退回原因<textarea value={reason} onChange={(event) => setReason(event.target.value)} /></label><footer><button className='secondary-button' onClick={() => setReasonOpen(false)}>取消</button><button className='danger-button' onClick={() => act('return', { return_type: returnType, reason })}>确认退回</button></footer></div></div>}
  </SurveyShell>
}

export function SurveyReportPage() {
  const { task, loading, error, reload: reloadTask } = useSurveyTask()
  const { dispatch } = useAppState()
  const [reports, setReports] = useState([])
  const [measurements, setMeasurements] = useState([])
  const [frames, setFrames] = useState([])
  const load = useCallback(async () => {
    if (!task) return
    const [reportRows, measurementRows, frameRows] = await Promise.all([platformApi.surveyReports(task.id), platformApi.surveyMeasurements(task.id), platformApi.surveyFrames(task.id, task.selected_batch_id)])
    setReports(reportRows); setMeasurements(measurementRows); setFrames(frameRows)
  }, [task])
  useEffect(() => { load().catch((error) => notify(dispatch, 'error', apiErrorMessage(error))) }, [load, dispatch])
  if (loading) return <AppShell pageTitle='测绘报告与交付'><LoadingState /></AppShell>
  if (!task) return <SurveyTaskUnavailable title='测绘报告与交付' error={error} onRetry={reloadTask} />
  const report = reports[0]
  const generate = async () => {
    try {
      const generated = await platformApi.generateSurveyReport(task.id, requestKey('survey-report'))
      setReports((current) => [generated, ...current.filter((item) => item.id !== generated.id)])
      await Promise.all([reloadTask(), platformApi.surveyMeasurements(task.id).then(setMeasurements)])
    } catch (error) { notify(dispatch, 'error', apiErrorMessage(error, '报告生成失败')) }
  }
  const openPdf = async () => {
    if (!report?.pdf_url) return
    const evidenceId = report.pdf_url.match(/survey-evidence\/([^/]+)\/content/)?.[1]
    const blob = await platformApi.surveyEvidence(evidenceId)
    const url = URL.createObjectURL(blob); window.open(url, '_blank', 'noopener,noreferrer'); window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }
  const deliver = async () => { try { await platformApi.deliverSurveyReport(task.id, report.id, report.content_hash); await load() } catch (error) { notify(dispatch, 'warning', apiErrorMessage(error, '投递门禁未通过')) } }
  const annotatedImages = report?.annotated_images || report?.payload?.annotated_images || []
  const measuredFrames = frames.filter((item) => measurements.some((measurement) => measurement.frame_id === item.id))
  return <SurveyShell task={task} step={4} title='测绘报告与交付' description='生成带内容哈希的 PDF/JSON/GeoJSON 成果包；只有批准质量规则且配置目标地址后，才可经 outbox 幂等投递。' actions={<button className='primary-button' onClick={report ? openPdf : generate}><FilePdf size={15} /> {report ? '打开真实 PDF' : '生成成果包'}</button>}>
    <div className='report-preview-layout'><Panel className='report-paper-wrap' title='报告预览' subtitle={report ? `${task.id} · v${report.version} · sha256:${report.content_hash.slice(0, 12)}…` : '尚未生成'}><article className='report-paper'><header><div><Crosshair size={30} weight='duotone' /></div><div><h2>无人机辅助事故现场测绘报告</h2><span>技术复核成果 · 非法定事故责任认定书</span></div></header><div className='report-meta'><span>任务：{task.id}</span><span>位置：{task.location}</span><span>任务版本：{task.version}</span><span>质量：{task.quality}</span></div><h3>测绘标注图</h3><div className='report-annotation-gallery'>{annotatedImages.length ? annotatedImages.map((item) => <figure key={item.evidence_id || item.frame_id}><EvidenceImage url={item.url} alt={`测绘报告标注图 Frame #${item.frame_number}`} /><figcaption>Frame #{item.frame_number} · {item.measurement_count} 项标注</figcaption></figure>) : measuredFrames.map((item) => { const frameMeasurements = measurements.filter((measurement) => measurement.frame_id === item.id); return <figure key={item.id}><MeasurementCanvas frame={item} tool='line' draft={[]} measurements={frameMeasurements} editable={false} /><figcaption>Frame #{item.frame_number} · {frameMeasurements.length} 项标注</figcaption></figure> })}</div>{!annotatedImages.length && !measuredFrames.length && <div className='report-annotation-empty'>该历史任务没有可回放的标注帧</div>}<h3>真实量算摘要</h3><table><tbody>{measurements.map((item) => <tr key={item.id}><td>{item.category || item.id}</td><td>{item.display_value}</td><td>{item.source} · {item.quality_status}</td></tr>)}</tbody></table><footer>schema uav.survey-result.v1 · local PostgreSQL road9 · evidence SHA-256</footer></article></Panel><div className='report-side'><Panel title='完整性门禁'><InfoRow label='标注图片' value={`${annotatedImages.length || measuredFrames.length} 张`} badge={annotatedImages.length || measuredFrames.length ? 'good' : 'warning'} /><InfoRow label='量算对象' value={`${measurements.length} 项`} badge={measurements.length ? 'good' : 'warning'} /><InfoRow label='技术复核' value={task.status === 'technical_reviewed' ? '已通过' : task.status} badge={task.status === 'technical_reviewed' ? 'good' : 'warning'} /><InfoRow label='内容哈希' value={report ? `${report.content_hash.slice(0, 16)}…` : '未生成'} badge={report ? 'good' : 'warning'} /><InfoRow label='误差口径' value='待批准' badge='unverified' /></Panel><Panel title='主平台投递'><InfoRow label='成果状态' value={report?.status || 'not_generated'} badge={report?.status} /><InfoRow label='Schema' value={report?.schema_version || 'uav.survey-result.v1'} /><InfoRow label='Outbox' value={task.delivery} badge={task.delivery} /><button className='primary-button full' disabled={!report || Boolean(report.delivery_blocked_reason)} onClick={deliver}>投递主平台</button></Panel>{report?.delivery_blocked_reason && <QualityNotice tone='warning' title='真实投递门禁'>{report.delivery_blocked_reason}</QualityNotice>}<QualityNotice tone='info' title='成果边界'>报告用于事故现场处置和人工复核，不替代法定勘查、责任认定、人工签章或案件归档。</QualityNotice></div></div>
  </SurveyShell>
}
