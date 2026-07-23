import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, ArrowsOutSimple, CheckCircle, CursorClick, Hand, LinkSimple, Minus, Plus, Stack, WarningCircle } from '@phosphor-icons/react'
import { ChannelizedMapPreview } from '../components/ChannelizedMapPreview'
import { QualityNotice, StatusBadge } from '../components/Common'
import { IntersectionWorkbenchShell } from '../components/IntersectionWorkbenchShell'
import { apiErrorMessage, platformApi } from '../lib/api'
import { adoptLaneDrafts, deleteLaneDrafts, emptyLaneSelection, mergeLaneDrafts, selectLaneDraft, splitLaneDraft } from '../lib/laneDraftGeometry'
import { dragImageGeometry, imageContainViewport, projectMetricPolygonToImage } from '../lib/surveyGeometry'

const initialQuality = {
  link_residual_p95_m: '3',
  lane_residual_median_m: '0.75',
  lane_residual_p95_m: '1.5',
  topology_errors: '0',
  direction_checks_passed: false,
  stop_line_checks_passed: false,
  reviewed: false,
}

const geometryLabels = {
  lane: '车道面',
  lane_boundary: '车道边界',
  stop_line: '停止线',
  guide_zone: '导流区',
  waiting_zone: '待转区',
}

const isLineGeometry = (mode) => mode === 'stop_line' || mode === 'lane_boundary'
const isEditableMap = (map) => ['draft', 'candidate'].includes(map?.status)

const laneExtractionChecks = [
  ['task_context', '已确认当前路口与路网版本'],
  ['operator_authorized', '操作员已获素材使用授权'],
  ['site_command_confirmed', '现场指挥与航拍任务已确认'],
  ['device_ready', '无人机正拍视频与遥测源可用'],
  ['storage_ready', '证据存储空间与留存策略已确认'],
]

const requestKey = (prefix) => `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`

function compactMatrix(matrix) {
  return JSON.stringify(matrix || [[1, 0, 0], [0, 1, 0], [0, 0, 1]])
}

function KeyframeExtractionStarter({ sources, starting, resetToken, error, result, onStart }) {
  const [sourceProfileId, setSourceProfileId] = useState('')
  const [checks, setChecks] = useState(() => Object.fromEntries(laneExtractionChecks.map(([key]) => [key, false])))
  const selectedSource = sources.find((source) => source.profile_id === sourceProfileId)
  const allConfirmed = laneExtractionChecks.every(([key]) => checks[key])
  const errorMessage = error?.response?.status === 404
    ? '当前 Platform 未加载抽帧接口，请重启原生 Platform 后重试。'
    : error ? apiErrorMessage(error) : ''

  useEffect(() => {
    if (!sources.some((source) => source.profile_id === sourceProfileId)) {
      setSourceProfileId(sources[0]?.profile_id || '')
    }
  }, [sourceProfileId, sources])

  useEffect(() => {
    if (!resetToken) return
    setChecks(Object.fromEntries(laneExtractionChecks.map(([key]) => [key, false])))
  }, [resetToken])

  return <div className='keyframe-extraction' data-testid='keyframe-extraction'>
    <div className='keyframe-extraction-heading'>
      <strong>从已登记正拍素材抽帧</strong>
      <span>复用测绘证据链，后台异步提取可度量关键帧。</span>
    </div>
    <label className='field-label'>抽帧素材
      <select aria-label='抽帧素材' value={sourceProfileId} onChange={(event) => setSourceProfileId(event.target.value)}>
        <option value=''>选择当前路口的本地素材</option>
        {sources.map((source) => <option key={source.profile_id} value={source.profile_id}>
          {source.display_name} · {source.profile_id}
        </option>)}
      </select>
    </label>
    {selectedSource && <div className='keyframe-meta'>
      <span>无人机 {selectedSource.drone_name}</span>
      <span>校验 {selectedSource.validation_status}</span>
      <span>视频 + {selectedSource.telemetry?.source_type || '遥测'}</span>
    </div>}
    <div className='lane-extraction-checks'>
      {laneExtractionChecks.map(([key, label]) => <label key={key}>
        <input
          type='checkbox'
          checked={checks[key]}
          onChange={(event) => setChecks((current) => ({ ...current, [key]: event.target.checked }))}
        /> {label}
      </label>)}
    </div>
    <button className='secondary-button full' disabled={!sourceProfileId || !allConfirmed || starting} onClick={() => onStart(sourceProfileId, checks)}>
      {starting ? '正在创建任务并入队…' : '完成预检并开始抽帧'}
    </button>
    {errorMessage && <div className='form-error' role='alert'>{errorMessage}</div>}
    {result?.batch?.id && <div className='form-success' role='status'>抽帧任务已入队 · {result.batch.id}</div>}
    {!sources.length && <div className='live-state empty'>当前路口没有已启用且校验通过的本地 SourceProfile；请先在无人机管理中登记视频与遥测。</div>}
  </div>
}

function KeyframeTaskPicker({
  interId,
  extractionSources,
  onStartExtraction,
  extractionStarting,
  extractionResetToken,
  extractionError,
  extractionResult,
  laneTasks,
  selectedTask,
  onSelectTask,
  surveyTasks,
  selectedSurveyTaskId,
  onSelectSurveyTask,
  batches,
  selectedBatchId,
  onSelectBatch,
  frames,
  selectedFrameId,
  onSelectFrame,
  onCreate,
  creating,
  showTaskList = true,
}) {
  const matchingSurveyTasks = surveyTasks.filter((task) => task.inter_id === interId)
  const selectedBatch = batches.find((batch) => batch.id === selectedBatchId)
  const selectedFrame = frames.find((frame) => frame.id === selectedFrameId)
  const canCreate = Boolean(selectedFrame?.has_metric_transform && selectedBatch?.source_profile_id)

  return <>
    <div className='keyframe-picker' data-testid='keyframe-picker'>
      <KeyframeExtractionStarter sources={extractionSources} onStart={onStartExtraction} starting={extractionStarting} resetToken={extractionResetToken} error={extractionError} result={extractionResult} />
      <strong>从真实测绘关键帧创建</strong>
      <span>仅使用已留存、具备 pixel → ENU 变换且绑定 SourceProfile 的帧。</span>
      <label className='field-label'>测绘任务
        <select aria-label='测绘任务' value={selectedSurveyTaskId} onChange={(event) => onSelectSurveyTask(event.target.value)}>
          <option value=''>选择当前路口的测绘任务</option>
          {matchingSurveyTasks.map((task) => <option key={task.id} value={task.id}>{task.title} · {task.id}</option>)}
        </select>
      </label>
      <label className='field-label'>采集批次
        <select aria-label='采集批次' value={selectedBatchId} onChange={(event) => onSelectBatch(event.target.value)} disabled={!selectedSurveyTaskId}>
          <option value=''>选择批次</option>
          {batches.map((batch) => <option key={batch.id} value={batch.id}>{batch.id} · {batch.status}</option>)}
        </select>
      </label>
      <label className='field-label'>正拍关键帧
        <select aria-label='正拍关键帧' value={selectedFrameId} onChange={(event) => onSelectFrame(event.target.value)} disabled={!selectedBatchId}>
          <option value=''>选择关键帧</option>
          {frames.map((frame) => <option key={frame.id} value={frame.id} disabled={!frame.has_metric_transform}>
            #{frame.frame_number} · {Number(frame.timestamp_sec || 0).toFixed(2)}s{frame.has_metric_transform ? '' : ' · 无坐标变换'}
          </option>)}
        </select>
      </label>
      {selectedBatch && <div className='keyframe-meta'>
        <span>来源 {selectedBatch.source_profile_id || '未绑定'}</span>
        <span>变换 {selectedFrame?.has_metric_transform ? '可用' : '不可用'}</span>
      </div>}
      <button className='primary-button full' disabled={!canCreate || creating} onClick={onCreate}>
        {creating ? '正在创建…' : '载入关键帧并开始标注'}
      </button>
      {!matchingSurveyTasks.length && <div className='live-state empty'>当前路口暂无关键帧任务；可在上方选择已登记素材并启动抽帧。</div>}
    </div>
    {showTaskList && <div className='annotation-task-list'>
      {laneTasks.map((task) => <button
        className={`annotation-task ${selectedTask?.task_id === task.task_id ? 'active' : ''}`}
        key={task.task_id}
        onClick={() => onSelectTask(task)}
      >
        <div>
          <strong>{task.intersection_id}</strong>
          <span>{task.source_frame_id || task.task_id}</span>
          {task.source_profile_id && <span>{task.source_profile_id}</span>}
        </div>
        <StatusBadge value={task.status} />
      </button>)}
    </div>}
  </>
}

export function ChannelizationCalibrationPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const projectId = useMemo(() => new URLSearchParams(window.location.search).get('project_id') || '', [])
  const hasScopedIntersection = useMemo(() => {
    const params = new URLSearchParams(window.location.search)
    return Boolean(params.get('inter_id') || params.get('project_id'))
  }, [])
  const [interId, setInterId] = useState(() => new URLSearchParams(window.location.search).get('inter_id') || '011wwe0z19700001')
  const [mapVersion, setMapVersion] = useState(null)
  const [selectedTaskId, setSelectedTaskId] = useState('')
  const [selectedSurveyTaskId, setSelectedSurveyTaskId] = useState('')
  const [selectedBatchId, setSelectedBatchId] = useState('')
  const [selectedFrameId, setSelectedFrameId] = useState('')
  const [draftPoints, setDraftPoints] = useState([])
  const [draftLanes, setDraftLanes] = useState([])
  const [laneSelection, setLaneSelection] = useState(emptyLaneSelection)
  const [showReferenceLanes, setShowReferenceLanes] = useState(true)
  const [draftFeatures, setDraftFeatures] = useState([])
  const [drawingMode, setDrawingMode] = useState('lane')
  const [direction, setDirection] = useState('straight')
  const [homography, setHomography] = useState(compactMatrix())
  const [controlPoints, setControlPoints] = useState('[]')
  const [quality, setQuality] = useState(initialQuality)
  const [registrationId, setRegistrationId] = useState('')
  const [sourceProfileId, setSourceProfileId] = useState('')
  const [taskImageUrl, setTaskImageUrl] = useState('')
  const [canvasMode, setCanvasMode] = useState('image')
  const [editorTool, setEditorTool] = useState('draw')
  const [canvasZoom, setCanvasZoom] = useState(1)
  const [layerVisibility, setLayerVisibility] = useState({ draft: true, boundaries: true, features: true })
  const [sourcePanelOpen, setSourcePanelOpen] = useState(false)
  const laneDragRef = useRef(null)
  const stageRef = useRef(null)
  const autoBootstrapRef = useRef('')

  const workspaceQuery = useQuery({ queryKey: ['intersection-project-workspace', projectId], queryFn: () => platformApi.intersectionProjectWorkspace(projectId), enabled: Boolean(projectId) })
  const workspacePreferredMap = useMemo(() => {
    const maps = workspaceQuery.data?.channelized_maps || []
    const sorted = [...maps].sort((left, right) => right.version_no - left.version_no)
    return sorted.find((item) => ['draft', 'candidate'].includes(item.status)) || sorted.find((item) => item.status === 'lane_verified') || sorted[0] || null
  }, [workspaceQuery.data?.channelized_maps])
  const workspaceMapDetailQuery = useQuery({
    queryKey: ['channelized-map', workspacePreferredMap?.id],
    queryFn: () => platformApi.channelizedMap(workspacePreferredMap.id),
    enabled: Boolean(projectId && workspacePreferredMap?.id),
  })
  const tasksQuery = useQuery({ queryKey: ['lane-tasks'], queryFn: platformApi.laneTasks, refetchInterval: 5_000 })
  const surveyTasksQuery = useQuery({ queryKey: ['survey-tasks'], queryFn: () => platformApi.surveyTasks() })
  const sourcesQuery = useQuery({ queryKey: ['sources'], queryFn: platformApi.sources })
  const dronesQuery = useQuery({ queryKey: ['drones'], queryFn: platformApi.drones })
  const allTasks = Array.isArray(tasksQuery.data) ? tasksQuery.data : []
  const tasks = allTasks.filter((task) => task.status !== 'invalidated' && (!hasScopedIntersection || task.intersection_id === interId))
  const surveyTasks = Array.isArray(surveyTasksQuery.data) ? surveyTasksQuery.data : []
  const sources = Array.isArray(sourcesQuery.data) ? sourcesQuery.data : []
  const drones = Array.isArray(dronesQuery.data) ? dronesQuery.data : []
  const eligibleExtractionSources = useMemo(() => sources.flatMap((source) => {
    const drone = drones.find((item) => item.id === source.drone_id)
    if (!drone || drone.default_inter_id !== interId || drone.enabled === false) return []
    if (!source.enabled || source.mode !== 'local' || source.validation_status !== 'valid') return []
    return [{ ...source, drone_name: drone.name || drone.id, road_data_version: drone.default_road_data_version || null }]
  }), [drones, interId, sources])
  const selectedTask = tasks.find((task) => task.task_id === selectedTaskId) || null
  const selectedSurveyTask = surveyTasks.find((task) => task.id === selectedSurveyTaskId) || null

  const batchesQuery = useQuery({
    queryKey: ['survey-batches', selectedSurveyTaskId],
    queryFn: () => platformApi.surveyBatches(selectedSurveyTaskId),
    enabled: Boolean(selectedSurveyTaskId),
    refetchInterval: (query) => {
      const rows = Array.isArray(query.state.data) ? query.state.data : []
      return rows.some((batch) => ['queued', 'processing'].includes(batch.status)) ? 1_500 : false
    },
  })
  const batches = Array.isArray(batchesQuery.data) ? batchesQuery.data : []
  const selectedBatch = batches.find((batch) => batch.id === selectedBatchId) || null
  const framesQuery = useQuery({
    queryKey: ['survey-frames', selectedSurveyTaskId, selectedBatchId],
    queryFn: () => platformApi.surveyFrames(selectedSurveyTaskId, selectedBatchId),
    enabled: Boolean(selectedSurveyTaskId && selectedBatchId),
    refetchInterval: selectedBatch && ['queued', 'processing'].includes(selectedBatch.status) ? 1_500 : false,
  })
  const frames = Array.isArray(framesQuery.data) ? framesQuery.data : []
  const selectedSurveyFrame = frames.find((frame) => frame.id === selectedFrameId) || null

  const resetGeometry = useCallback(() => {
    setDraftPoints([])
    setDraftLanes([])
    setDraftFeatures([])
    setLaneSelection(emptyLaneSelection)
    laneDragRef.current = null
  }, [])

  const adoptTask = useCallback((task) => {
    if (!task) return
    const intersectionChanged = task.intersection_id !== interId
    setSelectedTaskId(task.task_id)
    setInterId(task.intersection_id)
    setSourceProfileId(task.source_profile_id || '')
    setHomography(compactMatrix(task.homography_pixel_to_enu))
    setControlPoints(JSON.stringify(task.control_points || []))
    setSourcePanelOpen(false)
    resetGeometry()
    if (intersectionChanged) {
      setMapVersion(null)
      setRegistrationId('')
    }
  }, [interId, resetGeometry])

  useEffect(() => {
    if (!hasScopedIntersection) return
    if (selectedTaskId && tasks.some((task) => task.task_id === selectedTaskId)) return
    if (tasks[0]) adoptTask(tasks[0])
  }, [adoptTask, hasScopedIntersection, selectedTaskId, tasks])

  useEffect(() => {
    if (selectedTask) setCanvasMode('image')
    else if (mapVersion) setCanvasMode('map')
  }, [mapVersion?.id, selectedTask?.task_id])

  useEffect(() => {
    const matching = surveyTasks.filter((task) => task.inter_id === interId)
    if (!matching.some((task) => task.id === selectedSurveyTaskId)) {
      setSelectedSurveyTaskId(matching[0]?.id || '')
      setSelectedBatchId('')
      setSelectedFrameId('')
    }
  }, [interId, selectedSurveyTaskId, surveyTasks])

  useEffect(() => {
    if (!selectedSurveyTaskId) return
    if (!batches.some((batch) => batch.id === selectedBatchId)) {
      const preferred = batches.find((batch) => batch.id === selectedSurveyTask?.selected_batch_id)
        || batches.find((batch) => batch.source_profile_id && ['ready', 'degraded', 'selected'].includes(batch.status))
        || batches[0]
      setSelectedBatchId(preferred?.id || '')
      setSelectedFrameId('')
    }
  }, [batches, selectedBatchId, selectedSurveyTask, selectedSurveyTaskId])

  useEffect(() => {
    if (!frames.some((frame) => frame.id === selectedFrameId && frame.has_metric_transform)) {
      setSelectedFrameId(frames.find((frame) => frame.has_metric_transform)?.id || '')
    }
  }, [frames, selectedFrameId])

  const taskImageQuery = useQuery({
    queryKey: ['lane-task-image', selectedTask?.task_id],
    queryFn: () => platformApi.laneTaskImage(selectedTask.task_id),
    enabled: Boolean(selectedTask?.task_id),
    staleTime: 60_000,
  })
  useEffect(() => {
    if (!taskImageQuery.data || typeof URL.createObjectURL !== 'function') return undefined
    const url = URL.createObjectURL(taskImageQuery.data)
    setTaskImageUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [taskImageQuery.data])

  const createKeyframeTask = useMutation({
    mutationFn: () => platformApi.createLaneTaskFromSurveyFrame(selectedSurveyFrame.id),
    onSuccess: (task) => {
      queryClient.setQueryData(['lane-tasks'], (current) => [task, ...(Array.isArray(current) ? current.filter((item) => item.task_id !== task.task_id) : [])])
      adoptTask(task)
    },
  })
  const startExtraction = useMutation({
    mutationFn: ({ sourceProfileId, checklist }) => {
      const source = eligibleExtractionSources.find((item) => item.profile_id === sourceProfileId)
      return platformApi.startLaneKeyframeExtraction({
        inter_id: interId.trim(),
        source_profile_id: sourceProfileId,
        road_data_version: mapVersion?.road_data_version || source?.road_data_version || null,
        checklist,
      }, requestKey('lane-extract'))
    },
    onSuccess: ({ task, batch }) => {
      queryClient.setQueryData(['survey-tasks'], (current) => [
        task,
        ...(Array.isArray(current) ? current.filter((item) => item.id !== task.id) : []),
      ])
      queryClient.setQueryData(['survey-batches', task.id], [batch])
      setSelectedSurveyTaskId(task.id)
      setSelectedBatchId(batch.id)
      setSelectedFrameId('')
      queryClient.invalidateQueries({ queryKey: ['survey-tasks'] })
    },
  })
  const bootstrap = useMutation({
    mutationFn: () => platformApi.bootstrapChannelizedMap(interId.trim()),
    onSuccess: (data) => {
      setMapVersion(data.map)
      const registration = data.map?.visual_registration
      setRegistrationId(registration?.id ? `${registration.id}${registration.status === 'verified' ? ':verified' : ''}` : '')
      resetGeometry()
    },
  })

  useEffect(() => {
    if (mapVersion || !workspacePreferredMap) return
    const preferred = workspaceMapDetailQuery.data || workspacePreferredMap
    if (preferred) {
      setMapVersion(preferred)
      const registration = preferred.visual_registration
      setRegistrationId(registration?.id ? `${registration.id}${registration.status === 'verified' ? ':verified' : ''}` : '')
    }
  }, [mapVersion, workspaceMapDetailQuery.data, workspacePreferredMap])

  useEffect(() => {
    const detail = workspaceMapDetailQuery.data
    if (!detail || mapVersion?.id !== detail.id || mapVersion === detail) return
    setMapVersion(detail)
    const registration = detail.visual_registration
    setRegistrationId(registration?.id ? `${registration.id}${registration.status === 'verified' ? ':verified' : ''}` : '')
  }, [mapVersion, workspaceMapDetailQuery.data])

  useEffect(() => {
    if (!mapVersion?.quality) return
    const saved = mapVersion.quality
    setQuality((current) => ({
      ...current,
      link_residual_p95_m: String(saved.link_residual_p95_m ?? current.link_residual_p95_m),
      lane_residual_median_m: String(saved.lane_residual_median_m ?? current.lane_residual_median_m),
      lane_residual_p95_m: String(saved.lane_residual_p95_m ?? current.lane_residual_p95_m),
      topology_errors: String(saved.topology_errors ?? current.topology_errors),
      direction_checks_passed: Boolean(saved.direction_checks_passed),
      stop_line_checks_passed: Boolean(saved.stop_line_checks_passed),
      reviewed: Boolean(saved.reviewed),
    }))
  }, [mapVersion?.id, mapVersion?.quality])

  useEffect(() => {
    if (!hasScopedIntersection || !interId.trim() || mapVersion || bootstrap.isPending || autoBootstrapRef.current === interId.trim()) return
    if (projectId && (!workspaceQuery.isFetched || workspacePreferredMap)) return
    autoBootstrapRef.current = interId.trim()
    bootstrap.mutate()
  }, [bootstrap, hasScopedIntersection, interId, mapVersion, projectId, workspacePreferredMap, workspaceQuery.isFetched])
  const forkDraft = useMutation({
    mutationFn: () => platformApi.createChannelizedMap({
      inter_id: mapVersion.inter_id,
      road_data_version: mapVersion.road_data_version,
      anchor_gcj02: mapVersion.anchor_gcj02,
      geometry_gcj02: mapVersion.geometry_gcj02 || {},
      geometry_enu_m: mapVersion.geometry_enu_m || {},
      topology: mapVersion.topology || {},
      quality: mapVersion.quality || {},
      source_checksum: mapVersion.source_checksum || null,
      lanes: (mapVersion.lanes || []).map((lane) => ({
        local_lane_id: lane.local_lane_id,
        source_lane_id: lane.source_lane_id || null,
        link_id: lane.link_id || null,
        geometry_source: lane.geometry_source || 'link_offset_derived',
        geometry_gcj02: lane.geometry_gcj02,
        geometry_enu_m: lane.geometry_enu_m,
        match_confidence: lane.match_confidence ?? null,
      })),
    }),
    onSuccess: (data) => {
      setMapVersion(data)
      setRegistrationId('')
      resetGeometry()
      queryClient.invalidateQueries({ queryKey: ['channelized-maps'] })
    },
  })
  const fit = useMutation({
    mutationFn: () => platformApi.fitChannelizedMapFromImage(mapVersion.id, {
      task_id: selectedTask.task_id,
      source_profile_id: sourceProfileId.trim(),
      homography_pixel_to_enu: JSON.parse(homography),
      control_points: JSON.parse(controlPoints),
      lanes: draftLanes.map((lane) => ({
        local_lane_id: lane.local_lane_id,
        source_lane_id: lane.source_lane_id || null,
        link_id: lane.link_id || null,
        direction: lane.direction,
        polygon_px: lane.points,
      })),
      features: draftFeatures.map((feature) => ({
        feature_id: feature.feature_id,
        feature_type: feature.feature_type,
        points_px: feature.points,
        properties: feature.properties || {},
      })),
      link_residual_p95_m: Number(quality.link_residual_p95_m),
      lane_residual_median_m: Number(quality.lane_residual_median_m),
      lane_residual_p95_m: Number(quality.lane_residual_p95_m),
      topology_errors: Number(quality.topology_errors),
      direction_checks_passed: quality.direction_checks_passed,
      stop_line_checks_passed: quality.stop_line_checks_passed,
      reviewed: quality.reviewed,
    }),
    onSuccess: (data) => {
      setMapVersion(data)
      setRegistrationId(data.registration?.id || '')
      queryClient.invalidateQueries({ queryKey: ['channelized-maps'] })
    },
  })
  const verify = useMutation({
    mutationFn: () => platformApi.verifyVisualRegistration(registrationId),
    onSuccess: () => setRegistrationId((value) => `${value}:verified`),
  })
  const publish = useMutation({
    mutationFn: (status) => platformApi.publishChannelizedMap(mapVersion.id, status),
    onSuccess: setMapVersion,
  })

  const imageSize = useMemo(
    () => [selectedTask?.image_width || 960, selectedTask?.image_height || 540],
    [selectedTask],
  )
  const hasMapAlignedTask = Boolean(
    selectedTask?.homography_coordinate_frame === 'map_enu'
    && Array.isArray(selectedTask.map_anchor_gcj02)
    && selectedTask.map_anchor_gcj02.length === 2
    && Array.isArray(mapVersion?.anchor_gcj02)
    && selectedTask.map_anchor_gcj02.every((value, index) => Math.abs(Number(value) - Number(mapVersion.anchor_gcj02[index])) < 1e-9),
  )
  const referenceLanes = useMemo(() => {
    if (!hasMapAlignedTask) return []
    let pixelToEnu
    try {
      pixelToEnu = JSON.parse(homography)
    } catch {
      return []
    }
    return (mapVersion?.lanes || []).flatMap((lane) => {
      const points = projectMetricPolygonToImage(lane.geometry_enu_m, pixelToEnu, {
        width: imageSize[0],
        height: imageSize[1],
      })
      return points.length >= 3 ? [{ ...lane, points }] : []
    })
  }, [hasMapAlignedTask, homography, imageSize, mapVersion])
  const adoptReferenceLane = (reference, mode = 'link') => {
    const selection = selectLaneDraft(referenceLanes, reference.local_lane_id, mode)
    setLaneSelection(selection)
    setDraftLanes((lanes) => adoptLaneDrafts(lanes, referenceLanes, selection))
  }
  const imagePointFromEvent = (event) => {
    const svg = event.currentTarget.ownerSVGElement || event.currentTarget
    const rect = svg.getBoundingClientRect()
    const viewport = imageContainViewport(rect.width, rect.height, imageSize[0], imageSize[1])
    if (!viewport) return null
    const x = event.clientX - rect.left - viewport.offsetX
    const y = event.clientY - rect.top - viewport.offsetY
    if (x < 0 || y < 0 || x > viewport.width || y > viewport.height) return null
    return [Math.round(x / viewport.scale), Math.round(y / viewport.scale)]
  }
  const addPoint = (event) => {
    if (!selectedTask || editorTool !== 'draw') return
    const point = imagePointFromEvent(event)
    if (point) setDraftPoints((points) => [...points, point])
  }
  const moveLaneDrag = (event) => {
    const drag = laneDragRef.current
    if (!drag) return
    const point = imagePointFromEvent(event)
    if (!point) return
    setDraftLanes((lanes) => lanes.map((lane) => {
      if (drag.type === 'translate' && drag.laneIds.includes(lane.local_lane_id)) {
        return {
          ...lane,
          points: dragImageGeometry(drag.originalPointsById[lane.local_lane_id], { type: 'translate', dx: point[0] - drag.origin[0], dy: point[1] - drag.origin[1] }, { width: imageSize[0], height: imageSize[1] }),
        }
      }
      if (drag.type === 'vertex' && lane.local_lane_id === drag.laneId) {
        return { ...lane, points: dragImageGeometry(lane.points, { type: 'vertex', index: drag.index, point }, { width: imageSize[0], height: imageSize[1] }) }
      }
      return lane
    }))
  }
  const finishLaneDrag = () => { laneDragRef.current = null }
  const closeGeometry = () => {
    if (draftPoints.length < (isLineGeometry(drawingMode) ? 2 : 3)) return
    if (drawingMode === 'lane') {
      const index = draftLanes.length + 1
      setDraftLanes((lanes) => [...lanes, {
        local_lane_id: `local:${interId}:${index}`,
        direction,
        points: draftPoints,
      }])
    } else {
      const index = draftFeatures.length + 1
      setDraftFeatures((features) => [...features, {
        feature_id: `local:${interId}:${drawingMode}:${index}`,
        feature_type: drawingMode,
        points: draftPoints,
      }])
    }
    setDraftPoints([])
  }
  const removeLastGeometry = () => {
    if (drawingMode === 'lane') setDraftLanes((lanes) => lanes.slice(0, -1))
    else setDraftFeatures((features) => {
      const index = features.findLastIndex((feature) => feature.feature_type === drawingMode)
      return index < 0 ? features : features.filter((_, itemIndex) => itemIndex !== index)
    })
  }
  const deleteSelectedLanes = () => {
    setDraftLanes((lanes) => deleteLaneDrafts(lanes, laneSelection))
    setLaneSelection(emptyLaneSelection)
  }
  const splitSelectedLane = () => {
    const result = splitLaneDraft(draftLanes, laneSelection)
    setDraftLanes(result.lanes)
    setLaneSelection(result.selection)
  }
  const mergeSelectedLanes = () => {
    const result = mergeLaneDrafts(draftLanes, laneSelection)
    setDraftLanes(result.lanes)
    setLaneSelection(result.selection)
  }
  const hasGeometryForMode = drawingMode === 'lane'
    ? draftLanes.length > 0
    : draftFeatures.some((feature) => feature.feature_type === drawingMode)
  const error = startExtraction.error || createKeyframeTask.error || bootstrap.error || forkDraft.error || fit.error || verify.error || publish.error || taskImageQuery.error
  const registrationVerified = registrationId.endsWith(':verified')
  const isPublished = mapVersion?.status === 'lane_verified'
  const canFit = Boolean(isEditableMap(mapVersion) && hasMapAlignedTask && sourceProfileId.trim() && draftLanes.length)

  const workspace = workspaceQuery.data
  const project = workspace?.project || {
    project_id: projectId || '未绑定项目',
    inter_id: interId,
    name: selectedTask?.intersection_name || interId,
    stage: isPublished ? 'published' : registrationVerified ? 'checking' : draftLanes.length ? 'drafting' : selectedTask ? 'keyframes_ready' : mapVersion ? 'road_matched' : 'discovered',
    revision: 1,
    center_gcj02: mapVersion?.anchor_gcj02,
  }
  const workbenchWorkspace = workspace || {
    bindings: sourceProfileId ? [{ source_profile_id: sourceProfileId }] : [],
    channelized_maps: mapVersion ? [mapVersion] : [],
    readiness: { road_data_version: mapVersion?.road_data_version, road_context_verified: Boolean(mapVersion), source_bound: Boolean(sourceProfileId), formal_intersection: Boolean(interId) },
  }
  const qualityChecks = [
    ['数据完整性', isPublished || Boolean(mapVersion && selectedTask)],
    ['视觉配准精度', isPublished || registrationVerified],
    ['车道拓扑一致性', isPublished || Number(quality.topology_errors) === 0],
    ['渠化要素完整性', isPublished || draftLanes.length > 0 || Boolean(mapVersion?.lanes?.length)],
    ['拓扑连通性', isPublished || Number(quality.topology_errors) === 0 && Boolean(mapVersion)],
    ['方向关系校验', isPublished || quality.direction_checks_passed],
    ['信号灯 / 停止线校验', isPublished || quality.stop_line_checks_passed],
    ['人行横道完整性', isPublished || Boolean(mapVersion?.geometry_gcj02?.features)],
    ['发布前人工复核', isPublished || quality.reviewed],
  ]
  const qualityPassed = qualityChecks.filter(([, passed]) => passed).length
  const handleTabChange = (value) => {
    if (value === 'fit') return
    if (projectId) navigate(`/admin/intersection-projects/${encodeURIComponent(projectId)}?tab=${value}`)
    else navigate('/admin/intersection-projects')
  }
  const openSourcePicker = () => setSourcePanelOpen(true)

  return <IntersectionWorkbenchShell
    project={project}
    workspace={workbenchWorkspace}
    mapVersion={mapVersion}
    activeTab='fit'
    onTabChange={handleTabChange}
    rightRail={<>
      <section className='workbench-side-card'>
        <header><strong>待办任务</strong><span>{isPublished ? 0 : registrationVerified ? 1 : 2}</span></header>
        {!selectedTask && !isPublished && <button type='button' className='workbench-task priority' onClick={openSourcePicker}><i /><div><strong>载入正拍关键帧</strong><span>当前项目尚未选择可度量影像</span></div><b>立即处理</b></button>}
        {selectedTask && !draftLanes.length && !isPublished && <button type='button' className='workbench-task priority' onClick={() => setEditorTool('draw')}><i /><div><strong>完成渠化几何</strong><span>在正拍影像上拟合车道与渠化要素</span></div><b>去处理</b></button>}
        {!registrationVerified && !isPublished && <button type='button' className='workbench-task' disabled={!registrationId} onClick={() => verify.mutate()}><i /><div><strong>修正视觉配准</strong><span>复核影像与 GCJ-02 路网的控制点残差</span></div><b>{registrationId ? '去处理' : '待拟合'}</b></button>}
        {isPublished && <div className='workbench-task-complete'><strong>当前版本已通过全部发布门禁</strong><span>可进入运行应用查看 Runtime Bundle 状态。</span></div>}
      </section>

      <details className='workbench-side-card workbench-disclosure workbench-source-disclosure' open={sourcePanelOpen} onToggle={(event) => setSourcePanelOpen(event.currentTarget.open)}>
        <summary><strong>关键帧与素材</strong><span>{tasks.length} 个任务</span></summary>
        {error && <QualityNotice tone='warning' title='操作未通过'>{apiErrorMessage(error)}</QualityNotice>}
        <div className='workbench-task-select'>
          <label>路口 ID<input aria-label='路口 ID' value={interId} onChange={(event) => setInterId(event.target.value)} /></label>
          <label>已加载关键帧<select value={selectedTaskId} onChange={(event) => adoptTask(tasks.find((task) => task.task_id === event.target.value))}><option value=''>选择当前路口关键帧</option>{tasks.map((task) => <option value={task.task_id} key={task.task_id}>{task.source_frame_id || task.task_id}</option>)}</select></label>
        </div>
        <KeyframeTaskPicker
          interId={interId}
          extractionSources={eligibleExtractionSources}
          onStartExtraction={(profile, checklist) => startExtraction.mutate({ sourceProfileId: profile, checklist })}
          extractionStarting={startExtraction.isPending}
          extractionResetToken={startExtraction.data?.batch?.id || ''}
          extractionError={startExtraction.error}
          extractionResult={startExtraction.data}
          laneTasks={tasks}
          selectedTask={selectedTask}
          onSelectTask={adoptTask}
          surveyTasks={surveyTasks}
          selectedSurveyTaskId={selectedSurveyTaskId}
          onSelectSurveyTask={(value) => { setSelectedSurveyTaskId(value); setSelectedBatchId(''); setSelectedFrameId('') }}
          batches={batches}
          selectedBatchId={selectedBatchId}
          onSelectBatch={(value) => { setSelectedBatchId(value); setSelectedFrameId('') }}
          frames={frames}
          selectedFrameId={selectedFrameId}
          onSelectFrame={setSelectedFrameId}
          onCreate={() => createKeyframeTask.mutate()}
          creating={createKeyframeTask.isPending}
          showTaskList={!hasScopedIntersection}
        />
      </details>

      <section className='workbench-side-card'>
        <header><strong>质量门禁</strong><span className='quality-score'>{qualityPassed}/{qualityChecks.length} 通过</span></header>
        <ul className='workbench-checks'>{qualityChecks.map(([label, passed]) => <li key={label} className={passed ? 'passed' : ''}>{passed ? <CheckCircle size={14} weight='fill' /> : <WarningCircle size={14} />}<span>{label}</span><b>{passed ? '通过' : '待处理'}</b></li>)}</ul>
      </section>

      <details className='workbench-side-card workbench-disclosure'>
        <summary><strong>高级配准参数</strong><span>仅重新测定时修改</span></summary>
        <label className='field-label'>SourceProfile ID<input value={sourceProfileId} onChange={(event) => setSourceProfileId(event.target.value)} /></label>
        <label className='field-label'>pixel → ENU 3×3 单应矩阵<textarea value={homography} onChange={(event) => setHomography(event.target.value)} /></label>
        <label className='field-label'>控制点 JSON<textarea value={controlPoints} onChange={(event) => setControlPoints(event.target.value)} /></label>
        <label className='field-label'>Link 残差 P95（m）<input value={quality.link_residual_p95_m} onChange={(event) => setQuality((item) => ({ ...item, link_residual_p95_m: event.target.value }))} /></label>
        <label className='field-label'>车道残差中位数（m）<input value={quality.lane_residual_median_m} onChange={(event) => setQuality((item) => ({ ...item, lane_residual_median_m: event.target.value }))} /></label>
        <label className='field-label'>车道残差 P95（m）<input value={quality.lane_residual_p95_m} onChange={(event) => setQuality((item) => ({ ...item, lane_residual_p95_m: event.target.value }))} /></label>
        <label className='field-label'>拓扑错误数<input value={quality.topology_errors} onChange={(event) => setQuality((item) => ({ ...item, topology_errors: event.target.value }))} /></label>
        <label className='field-check'><input type='checkbox' checked={quality.direction_checks_passed} onChange={(event) => setQuality((item) => ({ ...item, direction_checks_passed: event.target.checked }))} /> 方向关系检查通过</label>
        <label className='field-check'><input type='checkbox' checked={quality.stop_line_checks_passed} onChange={(event) => setQuality((item) => ({ ...item, stop_line_checks_passed: event.target.checked }))} /> 停止线检查通过</label>
        <label className='field-check'><input type='checkbox' checked={quality.reviewed} onChange={(event) => setQuality((item) => ({ ...item, reviewed: event.target.checked }))} /> 已完成人工复核</label>
      </details>

      <section className='workbench-side-card'>
        <header><strong>版本状态</strong>{mapVersion && <StatusBadge value={mapVersion.status} />}</header>
        <dl className='workbench-version-list'><div><dt>当前版本</dt><dd>{mapVersion ? `v${mapVersion.version_no}` : '尚未加载'}</dd></div><div><dt>路网版本</dt><dd>{mapVersion?.road_data_version || '待验证'}</dd></div><div><dt>坐标转换</dt><dd>{mapVersion?.coordinate_transform_version || 'WGS84 → GCJ-02'}</dd></div></dl>
        <div className='workbench-version-actions'>
          <button className={mapVersion ? 'secondary-button full' : 'primary-button full'} disabled={bootstrap.isPending || !interId.trim()} onClick={() => bootstrap.mutate()}>{bootstrap.isPending ? '加载中…' : '加载本地 / 按需导入'}</button>
          {mapVersion && !isEditableMap(mapVersion) && <button className='secondary-button full' disabled={forkDraft.isPending} onClick={() => forkDraft.mutate()}>{`基于 ${mapVersion.status} 新建拟合草稿`}</button>}
          <button className='secondary-button full' disabled={!registrationVerified || publish.isPending} onClick={() => publish.mutate('link_verified')}>通过 Link 门禁</button>
          <button className='primary-button full' disabled={!registrationVerified || publish.isPending} onClick={() => publish.mutate('lane_verified')}>发布 lane_verified</button>
        </div>
      </section>
    </>}
  >
    <div className='workbench-editor' data-testid='lane-editor-workspace'>
      {fit.isSuccess && <QualityNotice tone='info' title='拟合候选已保存'>服务端已完成 pixel → ENU → GCJ-02，请继续复核视觉配准与质量门禁。</QualityNotice>}
      <section className='workbench-canvas-card'>
        <header className='workbench-canvas-toolbar'>
          <div>
            <select aria-label='画布视图' value={canvasMode} onChange={(event) => setCanvasMode(event.target.value)}><option value='image'>正拍图</option><option value='map'>GCJ-02 路网</option></select>
            <select aria-label='当前关键帧' value={selectedTaskId} onChange={(event) => adoptTask(tasks.find((task) => task.task_id === event.target.value))}><option value=''>选择关键帧</option>{tasks.map((task) => <option key={task.task_id} value={task.task_id}>{task.source_frame_id || task.task_id}</option>)}</select>
            <button type='button' className='secondary-button' onClick={() => setCanvasMode((value) => value === 'image' ? 'map' : 'image')}>影像 / 路网对照</button>
          </div>
          <span>{selectedTask ? `${selectedTask.source_profile_id || 'SourceProfile'} · ${selectedTask.source_frame_id || selectedTask.task_id}` : '尚未载入关键帧'}</span>
        </header>

        <div className='workbench-canvas-stage' ref={stageRef}>
          {canvasMode === 'map' ? <ChannelizedMapPreview mapVersion={mapVersion} /> : <div className='annotation-stage live-annotation' style={{ '--canvas-zoom': canvasZoom }}>
            {selectedTask && taskImageUrl ? <svg
              viewBox={`0 0 ${imageSize[0]} ${imageSize[1]}`}
              preserveAspectRatio='xMidYMid meet'
              onClick={addPoint}
              onPointerMove={moveLaneDrag}
              onPointerUp={finishLaneDrag}
              onPointerCancel={finishLaneDrag}
              aria-label='渠化几何绘制画布'
            >
              <image href={taskImageUrl} width={imageSize[0]} height={imageSize[1]} />
              {showReferenceLanes && referenceLanes.map((lane) => <polygon key={`reference-${lane.local_lane_id}`} aria-label={`路网参考车道 ${lane.local_lane_id}`} className='channelized-reference-lane' points={lane.points.map((point) => point.join(',')).join(' ')} onClick={(event) => { event.stopPropagation(); adoptReferenceLane(lane) }} onDoubleClick={(event) => { event.stopPropagation(); adoptReferenceLane(lane, 'lane') }} />)}
              {layerVisibility.draft && draftLanes.map((lane) => <g key={lane.local_lane_id}>
                <polygon aria-label={`拟合车道 ${lane.local_lane_id}`} aria-selected={laneSelection.laneIds.includes(lane.local_lane_id)} className={laneSelection.laneIds.includes(lane.local_lane_id) ? `channelized-draft-lane selected${laneSelection.mode === 'lane' ? ' single' : ''}` : 'channelized-draft-lane'} points={lane.points.map((point) => point.join(',')).join(' ')} onClick={(event) => { event.stopPropagation(); setLaneSelection(selectLaneDraft(draftLanes, lane.local_lane_id, 'link')) }} onDoubleClick={(event) => { event.stopPropagation(); setLaneSelection(selectLaneDraft(draftLanes, lane.local_lane_id, 'lane')) }} onPointerDown={(event) => {
                  const origin = imagePointFromEvent(event)
                  if (!origin) return
                  event.preventDefault(); event.stopPropagation()
                  const dragSelection = laneSelection.mode === 'lane' && laneSelection.laneIds.includes(lane.local_lane_id)
                    ? laneSelection
                    : selectLaneDraft(draftLanes, lane.local_lane_id, 'link')
                  setLaneSelection(dragSelection)
                  laneDragRef.current = {
                    type: 'translate',
                    laneIds: dragSelection.laneIds,
                    origin,
                    originalPointsById: Object.fromEntries(draftLanes
                      .filter((item) => dragSelection.laneIds.includes(item.local_lane_id))
                      .map((item) => [item.local_lane_id, item.points.map((point) => [...point])])),
                  }
                  event.currentTarget.ownerSVGElement?.setPointerCapture?.(event.pointerId)
                }} />
                {laneSelection.laneIds.length === 1 && laneSelection.laneIds[0] === lane.local_lane_id && lane.points.map(([x, y], index) => <circle key={`${lane.local_lane_id}-${index}`} aria-label={`调整车道顶点 ${index + 1}`} className='channelized-lane-handle' cx={x} cy={y} r='6' onPointerDown={(event) => {
                  event.preventDefault(); event.stopPropagation(); laneDragRef.current = { type: 'vertex', laneId: lane.local_lane_id, index }; event.currentTarget.ownerSVGElement?.setPointerCapture?.(event.pointerId)
                }} onClick={(event) => event.stopPropagation()} />)}
              </g>)}
              {draftFeatures.filter((feature) => feature.feature_type === 'guide_zone' || feature.feature_type === 'waiting_zone' ? layerVisibility.features : layerVisibility.boundaries).map((feature) => feature.feature_type === 'guide_zone' || feature.feature_type === 'waiting_zone'
                ? <polygon key={feature.feature_id} points={feature.points.map((point) => point.join(',')).join(' ')} className='channelized-feature-area' />
                : <polyline key={feature.feature_id} points={feature.points.map((point) => point.join(',')).join(' ')} className={feature.feature_type === 'stop_line' ? 'channelized-stop-line' : 'channelized-boundary'} />)}
              {draftPoints.length > 1 && <polyline points={draftPoints.map((point) => point.join(',')).join(' ')} />}
              {draftPoints.map(([x, y], index) => <circle key={`${x}-${y}-${index}`} cx={x} cy={y} r='5' />)}
            </svg> : <div className='workbench-canvas-empty'><strong>载入正拍关键帧开始渠化拟合</strong><span>右侧“关键帧与素材”只展示当前路口的真实测绘任务。</span><button type='button' className='primary-button' onClick={openSourcePicker}>选择关键帧</button></div>}
          </div>}

          {canvasMode === 'image' && <>
            <div className='workbench-toolstrip' aria-label='画布工具'>
              <button type='button' className={editorTool === 'inspect' ? 'active' : ''} aria-label='查看模式' onClick={() => setEditorTool('inspect')}><Hand size={18} /></button>
              <button type='button' className={editorTool === 'draw' ? 'active' : ''} aria-label='绘制模式' onClick={() => setEditorTool('draw')}><CursorClick size={18} /></button>
              <button type='button' aria-label='图层'><Stack size={18} /></button>
              <button type='button' aria-label='吸附参考车道' onClick={() => setShowReferenceLanes((value) => !value)}><LinkSimple size={18} /></button>
              <button type='button' aria-label='放大' onClick={() => setCanvasZoom((value) => Math.min(2, value + 0.15))}><Plus size={18} /></button>
              <button type='button' aria-label='缩小' onClick={() => setCanvasZoom((value) => Math.max(.7, value - 0.15))}><Minus size={18} /></button>
              <button type='button' aria-label='全屏' onClick={() => stageRef.current?.requestFullscreen?.()}><ArrowsOutSimple size={18} /></button>
            </div>
            <div className='workbench-layer-legend'>
              <strong>图层图例</strong>
              <label><input type='checkbox' checked={showReferenceLanes} onChange={(event) => setShowReferenceLanes(event.target.checked)} /><i className='reference' /> 路网参考车道</label>
              <label><input type='checkbox' checked={layerVisibility.draft} onChange={(event) => setLayerVisibility((value) => ({ ...value, draft: event.target.checked }))} /><i className='draft' /> 拟合车道面</label>
              <label><input type='checkbox' checked={layerVisibility.features} onChange={(event) => setLayerVisibility((value) => ({ ...value, features: event.target.checked }))} /><i className='feature' /> 渠化要素</label>
              <label><input type='checkbox' checked={layerVisibility.boundaries} onChange={(event) => setLayerVisibility((value) => ({ ...value, boundaries: event.target.checked }))} /><i className='boundary' /> 停止线与边界</label>
            </div>
            {mapVersion && <div className='workbench-mini-map'><ChannelizedMapPreview mapVersion={mapVersion} /></div>}
          </>}
        </div>

        {selectedTask && mapVersion && !hasMapAlignedTask && <div className='form-error workbench-inline-error' role='alert'>该关键帧仍是局部量算坐标；请从右侧测绘帧重新载入，刷新为当前地图 ENU。</div>}
        <div className='annotation-toolbar workbench-editor-toolbar'>
          <select aria-label='几何类型' value={drawingMode} onChange={(event) => { setDrawingMode(event.target.value); setDraftPoints([]) }}><option value='lane'>车道面</option><option value='lane_boundary'>车道边界</option><option value='stop_line'>停止线</option><option value='guide_zone'>导流区</option><option value='waiting_zone'>待转区</option></select>
          {drawingMode === 'lane' && <select aria-label='车道方向' value={direction} onChange={(event) => setDirection(event.target.value)}><option value='straight'>直行</option><option value='left_turn'>左转</option><option value='right_turn'>右转</option><option value='u_turn'>掉头</option></select>}
          <button className='secondary-button' disabled={draftPoints.length < (isLineGeometry(drawingMode) ? 2 : 3)} onClick={closeGeometry}>完成{geometryLabels[drawingMode]}</button>
          <button className='secondary-button' disabled={!draftPoints.length} onClick={() => setDraftPoints((points) => points.slice(0, -1))}>撤销一点</button>
          <button className='secondary-button' disabled={!draftPoints.length} onClick={() => setDraftPoints([])}>清空顶点</button>
          <button className='secondary-button' disabled={!hasGeometryForMode} onClick={removeLastGeometry}>移除最后{geometryLabels[drawingMode]}</button>
          {drawingMode === 'lane' && <div className='lane-operation-cluster' role='group' aria-label='车道编辑操作'>
            <button className='secondary-button danger' disabled={!laneSelection.laneIds.length} onClick={deleteSelectedLanes}>删除所选</button>
            <button className='secondary-button' disabled={laneSelection.mode !== 'lane' || laneSelection.laneIds.length !== 1} onClick={splitSelectedLane}>拆分车道</button>
            <button className='secondary-button' disabled={laneSelection.laneIds.length < 2} onClick={mergeSelectedLanes}>合并车道</button>
          </div>}
          {laneSelection.mode === 'link' && laneSelection.laneIds.length > 0 && <strong className='lane-selection-summary'>{`Link ${laneSelection.linkId || '未分组'} · ${laneSelection.laneIds.length} 条车道`}</strong>}
          {laneSelection.mode === 'lane' && laneSelection.laneIds.length === 1 && <strong className='lane-selection-summary'>{`单车道 · ${laneSelection.laneIds[0]}`}</strong>}
          <span>{draftPoints.length} 个顶点 · {draftLanes.length} 条车道 · {draftFeatures.length} 个渠化要素</span>
        </div>
      </section>

      <section className='workbench-next-action'>
        <div><span>当前状态</span><strong>{mapVersion?.status || '待创建草稿'}</strong></div>
        <div><span>下一步</span><strong>{isPublished ? '进入运行应用' : registrationVerified ? '提交复核发布' : canFit ? '保存拟合候选' : '完成渠化几何'}</strong></div>
        <div><span>操作指引</span><p>控制点与路网吸附只影响当前草稿；服务端统一执行 pixel → ENU → GCJ-02。</p></div>
        <button type='button' className='primary-button' disabled={!isPublished && (!canFit || fit.isPending)} onClick={() => isPublished ? handleTabChange('runtime') : fit.mutate()}>{isPublished ? '进入运行应用' : fit.isPending ? '服务端拟合中…' : '保存影像拟合候选'} <ArrowRight size={15} /></button>
      </section>
    </div>
  </IntersectionWorkbenchShell>
}
