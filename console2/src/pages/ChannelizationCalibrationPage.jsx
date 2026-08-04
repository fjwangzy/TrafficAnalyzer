import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ArrowClockwise, ArrowCounterClockwise, ArrowRight, ArrowsOutSimple, CheckCircle, CursorClick, Hand, LinkSimple, Minus, Plus, Stack, WarningCircle } from '@phosphor-icons/react'
import { ChannelizedMapPreview } from '../components/ChannelizedMapPreview'
import { QualityNotice, StatusBadge } from '../components/Common'
import { IntersectionWorkbenchShell } from '../components/IntersectionWorkbenchShell'
import { apiErrorMessage, platformApi } from '../lib/api'
import { adoptLaneDrafts, deleteLaneDrafts, emptyLaneSelection, mergeLaneDrafts, selectLaneDraft, splitLaneDraft } from '../lib/laneDraftGeometry'
import { dragImageGeometry, imageContainViewport, projectMetricPolygonToImage } from '../lib/surveyGeometry'
import {
  approachHandlePoint,
  commitEditorHistory,
  composeRegistrationHomography,
  createCubicLaneEdge,
  createDefaultEditorModel,
  createEditorHistory,
  createFreeformEditorModel,
  createRegistrationPose,
  generateEditorGeometry,
  redoEditorHistory,
  sampleLaneCurves,
  transformPoint,
  transformPointBetweenPoses,
  undoEditorHistory,
  updateApproachFromHandle,
} from '../lib/channelizedEditorGeometry'

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
  crosswalk: '人行横道',
  channelizing_island: '渠化岛',
  lane_marking: '分段标线',
}

const isLineGeometry = (mode) => ['stop_line', 'lane_boundary', 'lane_marking'].includes(mode)
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
  const [registrationPose, setRegistrationPose] = useState(() => createRegistrationPose())
  const [overlayOpacity, setOverlayOpacity] = useState(.72)
  const [editorModel, setEditorModel] = useState(null)
  const [selectedApproachId, setSelectedApproachId] = useState('east')
  const [curveEdgeIndex, setCurveEdgeIndex] = useState(0)
  const [quality, setQuality] = useState(initialQuality)
  const [registrationId, setRegistrationId] = useState('')
  const [sourceProfileId, setSourceProfileId] = useState('')
  const [taskImageUrl, setTaskImageUrl] = useState('')
  const [canvasMode, setCanvasMode] = useState('image')
  const [editorTool, setEditorTool] = useState('draw')
  const [canvasZoom, setCanvasZoom] = useState(1)
  const [layerVisibility, setLayerVisibility] = useState({ draft: true, boundaries: true, features: true })
  const [sourcePanelOpen, setSourcePanelOpen] = useState(false)
  const [registrationPanelOpen, setRegistrationPanelOpen] = useState(false)
  const laneDragRef = useRef(null)
  const editorHistoryRef = useRef(createEditorHistory({
    pose: createRegistrationPose(), lanes: [], features: [], editorModel: null,
  }))
  const stageRef = useRef(null)
  const autoBootstrapRef = useRef('')
  const hydratedMapRef = useRef('')
  const hydratedCandidateRef = useRef('')

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
    setEditorModel(null)
    setRegistrationPose(createRegistrationPose())
    laneDragRef.current = null
    editorHistoryRef.current = createEditorHistory({
      pose: createRegistrationPose(), lanes: [], features: [], editorModel: null,
    })
  }, [])

  const adoptTask = useCallback((task) => {
    if (!task) return
    const intersectionChanged = task.intersection_id !== interId
    resetGeometry()
    const initialPose = createRegistrationPose({
      center_px: [(task.image_width || 960) / 2, (task.image_height || 540) / 2],
    })
    setSelectedTaskId(task.task_id)
    setInterId(task.intersection_id)
    setSourceProfileId(task.source_profile_id || '')
    setHomography(compactMatrix(task.homography_pixel_to_enu))
    setControlPoints(JSON.stringify(task.control_points || []))
    setRegistrationPose(initialPose)
    editorHistoryRef.current = createEditorHistory({ pose: initialPose, lanes: [], features: [], editorModel: null })
    setSourcePanelOpen(false)
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
    const detail = workspaceMapDetailQuery.data
    if (!detail?.id) return
    const savedPose = detail.visual_registration?.registration_pose
    const savedModel = detail.topology?.editor_model || null
    const pixelGeometry = savedModel?.pixel_geometry || {}
    const pose = savedPose?.schema_version ? createRegistrationPose(savedPose) : registrationPose
    const lanes = Array.isArray(pixelGeometry.lanes) ? pixelGeometry.lanes : []
    const features = Array.isArray(pixelGeometry.features) ? pixelGeometry.features : []
    const hydrationKey = `${detail.id}:${savedModel?.mode || savedModel?.schema_version || 'canonical'}:${lanes.length}:${features.length}`
    if (hydratedMapRef.current === hydrationKey) return
    hydratedMapRef.current = hydrationKey
    if (savedPose?.schema_version) setRegistrationPose(pose)
    if (savedModel) setEditorModel(savedModel)
    if (lanes.length) setDraftLanes(lanes)
    if (features.length) setDraftFeatures(features)
    editorHistoryRef.current = createEditorHistory({ pose, lanes, features, editorModel: savedModel })
  }, [registrationPose, workspaceMapDetailQuery.data])

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
    mutationFn: () => platformApi.deriveChannelizedMapDraft(mapVersion.id),
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
      homography_pixel_to_enu: effectiveHomography,
      control_points: JSON.parse(controlPoints),
      lanes: draftLanes.map((lane) => ({
        local_lane_id: lane.local_lane_id,
        source_lane_id: lane.source_lane_id || null,
        link_id: lane.link_id || null,
        direction: lane.direction,
        special_lane_attribute: lane.special_lane_attribute || null,
        polygon_px: sampleLaneCurves(lane),
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
      registration_pose: registrationPose,
      editor_model: {
        ...(editorModel ? { ...editorModel, mode: editorModel.mode || 'parameterized' } : createFreeformEditorModel(
          [imageSize[0] / 2, imageSize[1] / 2],
          draftLanes,
          draftFeatures,
        )),
        pixel_geometry: { lanes: draftLanes, features: draftFeatures },
      },
    }),
    onSuccess: (data) => {
      queryClient.setQueryData(['channelized-map', data.id], data)
      setMapVersion(data)
      setRegistrationId(data.registration?.id || '')
      queryClient.invalidateQueries({ queryKey: ['channelized-maps'] })
      queryClient.invalidateQueries({ queryKey: ['intersection-project-workspace', projectId] })
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
  const baseHomography = useMemo(() => {
    try { return JSON.parse(homography) } catch { return [[1, 0, 0], [0, 1, 0], [0, 0, 1]] }
  }, [homography])
  const effectiveHomography = useMemo(
    () => composeRegistrationHomography(baseHomography, registrationPose),
    [baseHomography, registrationPose],
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
    return (mapVersion?.lanes || []).flatMap((lane) => {
      const points = projectMetricPolygonToImage(lane.geometry_enu_m, baseHomography, {
        width: imageSize[0],
        height: imageSize[1],
      }).map((point) => transformPoint(point, registrationPose))
      return points.length >= 3 ? [{ ...lane, points }] : []
    })
  }, [baseHomography, hasMapAlignedTask, imageSize, mapVersion, registrationPose])
  useEffect(() => {
    const hydrationKey = `${mapVersion?.id || ''}:${selectedTask?.task_id || ''}`
    const savedPixelLanes = (
      workspaceMapDetailQuery.data?.topology?.editor_model?.pixel_geometry?.lanes
      || mapVersion?.topology?.editor_model?.pixel_geometry?.lanes
    )
    if (
      mapVersion?.status !== 'candidate'
      || !selectedTask
      || !referenceLanes.length
      || draftLanes.length
      || (Array.isArray(savedPixelLanes) && savedPixelLanes.length)
      || hydratedCandidateRef.current === hydrationKey
    ) return
    hydratedCandidateRef.current = hydrationKey
    const lanes = referenceLanes.map((lane) => ({
      ...lane,
      points: lane.points.map((point) => [...point]),
    }))
    setDraftLanes(lanes)
    editorHistoryRef.current = createEditorHistory({
      pose: registrationPose,
      lanes,
      features: draftFeatures,
      editorModel,
    })
  }, [draftFeatures, draftLanes.length, editorModel, mapVersion?.id, mapVersion?.status, mapVersion?.topology, referenceLanes, registrationPose, selectedTask, workspaceMapDetailQuery.data?.topology])
  const editorSnapshot = () => ({
    pose: registrationPose,
    lanes: draftLanes,
    features: draftFeatures,
    editorModel,
  })
  const restoreEditorSnapshot = (snapshot) => {
    setRegistrationPose(snapshot.pose)
    setDraftLanes(snapshot.lanes)
    setDraftFeatures(snapshot.features)
    setEditorModel(snapshot.editorModel)
  }
  const commitEditorSnapshot = (next) => {
    editorHistoryRef.current = commitEditorHistory(
      { ...editorHistoryRef.current, present: editorSnapshot() },
      next,
    )
    restoreEditorSnapshot(next)
  }
  const registrationAdjustedSnapshot = (source, nextPose) => {
    const previous = source.pose
    const transformPoints = (points = []) => points.map((point) => transformPointBetweenPoses(point, previous, nextPose))
    const scaleRatio = nextPose.uniform_scale / previous.uniform_scale
    const rotationDelta = nextPose.rotation_deg - previous.rotation_deg
    const nextLanes = source.lanes.map((lane) => ({
      ...lane,
      points: transformPoints(lane.points),
      boundary_curves: lane.boundary_curves?.map((curve) => ({
        ...curve,
        control1: transformPointBetweenPoses(curve.control1, previous, nextPose),
        control2: transformPointBetweenPoses(curve.control2, previous, nextPose),
      })),
    }))
    const nextFeatures = source.features.map((feature) => ({ ...feature, points: transformPoints(feature.points) }))
    const nextModel = source.editorModel ? {
      ...source.editorModel,
      center_px: transformPointBetweenPoses(source.editorModel.center_px, previous, nextPose),
      approaches: source.editorModel.approaches.map((approach) => ({
        ...approach,
        angle_deg: approach.angle_deg + rotationDelta,
        lane_width_px: approach.lane_width_px * scaleRatio,
        approach_length_px: approach.approach_length_px * scaleRatio,
        flare_length_px: approach.flare_length_px * scaleRatio,
      })),
      feature_templates: source.editorModel.feature_templates.map((feature) => ({
        ...feature,
        width_px: feature.width_px == null ? null : feature.width_px * scaleRatio,
        setback_px: Number(feature.setback_px || 0) * scaleRatio,
        length_px: feature.length_px == null ? null : feature.length_px * scaleRatio,
        lateral_offset_px: Number(feature.lateral_offset_px || 0) * scaleRatio,
      })),
    } : null
    return { pose: nextPose, lanes: nextLanes, features: nextFeatures, editorModel: nextModel }
  }
  const updateRegistrationPose = (patch) => {
    const nextPose = createRegistrationPose({ ...registrationPose, ...patch })
    commitEditorSnapshot(registrationAdjustedSnapshot(editorSnapshot(), nextPose))
  }
  const undoEditor = () => {
    editorHistoryRef.current = undoEditorHistory({ ...editorHistoryRef.current, present: editorSnapshot() })
    restoreEditorSnapshot(editorHistoryRef.current.present)
  }
  const redoEditor = () => {
    editorHistoryRef.current = redoEditorHistory({ ...editorHistoryRef.current, present: editorSnapshot() })
    restoreEditorSnapshot(editorHistoryRef.current.present)
  }
  const generateFromParameters = () => {
    const model = editorModel && editorModel.mode !== 'freeform'
      ? editorModel
      : createDefaultEditorModel([imageSize[0] / 2, imageSize[1] / 2])
    const generated = generateEditorGeometry(model, { lanes: draftLanes, features: draftFeatures })
    commitEditorSnapshot({ pose: registrationPose, lanes: generated.lanes, features: generated.features, editorModel: model })
  }
  const curveSelectedLaneEdge = () => {
    if (laneSelection.mode !== 'lane' || laneSelection.laneIds.length !== 1) return
    const laneId = laneSelection.laneIds[0]
    const nextLanes = draftLanes.map((lane) => lane.local_lane_id === laneId
      ? createCubicLaneEdge(lane, Math.min(Math.max(0, curveEdgeIndex), lane.points.length - 1))
      : lane)
    const manualOverrides = new Set(editorModel?.manual_overrides || [])
    manualOverrides.add(laneId)
    commitEditorSnapshot({
      pose: registrationPose,
      lanes: nextLanes,
      features: draftFeatures,
      editorModel: editorModel ? { ...editorModel, manual_overrides: [...manualOverrides] } : null,
    })
  }
  const updateEditorApproach = (field, value) => {
    const model = editorModel || createDefaultEditorModel([imageSize[0] / 2, imageSize[1] / 2])
    const nextModel = {
      ...model,
      approaches: model.approaches.map((approach) => approach.approach_id === selectedApproachId
        ? { ...approach, [field]: value }
        : approach),
    }
    const generated = generateEditorGeometry(nextModel, { lanes: draftLanes, features: draftFeatures })
    commitEditorSnapshot({ pose: registrationPose, lanes: generated.lanes, features: generated.features, editorModel: nextModel })
  }
  const updateFeatureTemplate = (featureId, field, value) => {
    const nextModel = {
      ...editorModel,
      feature_templates: editorModel.feature_templates.map((item) => item.feature_id === featureId
        ? { ...item, [field]: value }
        : item),
    }
    const generated = generateEditorGeometry(nextModel, { lanes: draftLanes, features: draftFeatures })
    commitEditorSnapshot({ pose: registrationPose, lanes: generated.lanes, features: generated.features, editorModel: nextModel })
  }
  const addFeatureTemplate = (featureType, variant = 'standard') => {
    const model = editorModel || createDefaultEditorModel([imageSize[0] / 2, imageSize[1] / 2])
    const existingId = featureType === 'crosswalk' && variant === 'right_turn'
      ? `crosswalk-right:${selectedApproachId}`
      : `${featureType}:${selectedApproachId}`
    const template = {
      feature_id: existingId,
      feature_type: featureType,
      variant,
      approach_id: selectedApproachId,
      width_px: featureType === 'waiting_zone' ? 28 : 16,
      setback_px: 28,
      length_px: featureType === 'lane_marking' ? 150 : 72,
      lateral_offset_px: featureType === 'waiting_zone' ? 18 : 0,
      color: 'white',
      line_style: featureType === 'lane_marking' ? 'dashed' : 'solid',
      manual_override: false,
    }
    const nextModel = {
      ...model,
      feature_templates: [...model.feature_templates.filter((item) => item.feature_id !== existingId), template],
    }
    const generated = generateEditorGeometry(nextModel, { lanes: draftLanes, features: draftFeatures })
    commitEditorSnapshot({ pose: registrationPose, lanes: generated.lanes, features: generated.features, editorModel: nextModel })
  }
  const adoptReferenceLane = (reference, mode = 'link') => {
    const selection = selectLaneDraft(referenceLanes, reference.local_lane_id, mode)
    setLaneSelection(selection)
    setDraftLanes((lanes) => adoptLaneDrafts(lanes, referenceLanes, selection))
  }
  const adoptAllReferenceLanes = () => {
    const nextLanes = referenceLanes.map((lane) => ({
      ...lane,
      points: lane.points.map((point) => [...point]),
      manual_override: false,
    }))
    commitEditorSnapshot({ pose: registrationPose, lanes: nextLanes, features: draftFeatures, editorModel })
    setLaneSelection(emptyLaneSelection)
  }
  const imagePointFromEvent = (event, allowOutside = false) => {
    const svg = event.currentTarget.ownerSVGElement || event.currentTarget
    const rect = svg.getBoundingClientRect()
    const viewport = imageContainViewport(rect.width, rect.height, imageSize[0], imageSize[1])
    if (!viewport) return null
    const x = event.clientX - rect.left - viewport.offsetX
    const y = event.clientY - rect.top - viewport.offsetY
    if (!allowOutside && (x < 0 || y < 0 || x > viewport.width || y > viewport.height)) return null
    return [Math.round(x / viewport.scale), Math.round(y / viewport.scale)]
  }
  const addPoint = (event) => {
    if (!selectedTask || editorTool !== 'draw') return
    const point = imagePointFromEvent(event)
    if (point) setDraftPoints((points) => [...points, point])
  }
  const startCanvasPointer = (event) => {
    if (editorTool !== 'align' || event.target !== event.currentTarget && event.target.tagName !== 'image') return
    const origin = imagePointFromEvent(event)
    if (!origin) return
    const source = editorSnapshot()
    laneDragRef.current = { type: 'registration', origin, source, preview: source }
    event.currentTarget.setPointerCapture?.(event.pointerId)
    event.preventDefault()
  }
  const moveLaneDrag = (event) => {
    const drag = laneDragRef.current
    if (!drag) return
    const point = imagePointFromEvent(event, true)
    if (!point) return
    if (drag.type === 'registration') {
      const nextPose = createRegistrationPose({
        ...drag.source.pose,
        translation_px: [
          drag.source.pose.translation_px[0] + point[0] - drag.origin[0],
          drag.source.pose.translation_px[1] + point[1] - drag.origin[1],
        ],
      })
      drag.preview = registrationAdjustedSnapshot(drag.source, nextPose)
      restoreEditorSnapshot(drag.preview)
      return
    }
    if (drag.type === 'approach_parameter') {
      const nextModel = updateApproachFromHandle(drag.source.editorModel, drag.approachId, point)
      const generated = generateEditorGeometry(nextModel, {
        lanes: drag.source.lanes,
        features: drag.source.features,
      })
      drag.preview = { ...drag.source, lanes: generated.lanes, features: generated.features, editorModel: nextModel }
      restoreEditorSnapshot(drag.preview)
      return
    }
    const nextLanes = drag.source.lanes.map((lane) => {
      if (drag.type === 'translate' && drag.laneIds.includes(lane.local_lane_id)) {
        return {
          ...lane,
          manual_override: true,
          points: dragImageGeometry(drag.originalPointsById[lane.local_lane_id], { type: 'translate', dx: point[0] - drag.origin[0], dy: point[1] - drag.origin[1] }),
        }
      }
      if (drag.type === 'vertex' && lane.local_lane_id === drag.laneId) {
        return { ...lane, manual_override: true, points: dragImageGeometry(lane.points, { type: 'vertex', index: drag.index, point }) }
      }
      if (drag.type === 'curve_control' && lane.local_lane_id === drag.laneId) {
        return {
          ...lane,
          manual_override: true,
          boundary_curves: lane.boundary_curves.map((curve) => curve.edge_index === drag.edgeIndex
            ? { ...curve, [drag.control]: point }
            : curve),
        }
      }
      return lane
    })
    drag.preview = { ...drag.source, lanes: nextLanes }
    if (!drag.historyCommitted) {
      editorHistoryRef.current = commitEditorHistory(
        { ...editorHistoryRef.current, present: drag.source },
        drag.preview,
      )
      drag.historyCommitted = true
    } else {
      editorHistoryRef.current = { ...editorHistoryRef.current, present: drag.preview }
    }
    setDraftLanes(nextLanes)
  }
  const finishLaneDrag = () => {
    const drag = laneDragRef.current
    if (['registration', 'approach_parameter'].includes(drag?.type) && drag.preview !== drag.source) {
      editorHistoryRef.current = commitEditorHistory(
        { ...editorHistoryRef.current, present: drag.source },
        drag.preview,
      )
    }
    if (['translate', 'vertex', 'curve_control'].includes(drag?.type) && drag.preview) {
      let nextModel = drag.preview.editorModel
      const manualOverrides = new Set(nextModel?.manual_overrides || [])
      for (const laneId of drag.laneIds || [drag.laneId]) if (laneId) manualOverrides.add(laneId)
      if (nextModel) nextModel = { ...nextModel, manual_overrides: [...manualOverrides] }
      const next = { ...drag.preview, editorModel: nextModel }
      editorHistoryRef.current = { ...editorHistoryRef.current, present: next }
      restoreEditorSnapshot(next)
    }
    laneDragRef.current = null
  }
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

      <details className='workbench-side-card workbench-disclosure' open>
        <summary><strong>参数化渠化</strong><span>{editorModel && editorModel.mode !== 'freeform' ? `${editorModel.approaches.length} 个进口方向` : '自由编辑模式'}</span></summary>
        <div className='channelized-parameter-panel'>
          <button type='button' className='primary-button full' disabled={!selectedTask || isPublished} onClick={generateFromParameters}>{editorModel && editorModel.mode !== 'freeform' ? '按参数刷新几何' : '生成四进口模板'}</button>
          {editorModel && editorModel.mode !== 'freeform' && <>
            <label>进口方向<select aria-label='参数进口方向' value={selectedApproachId} onChange={(event) => setSelectedApproachId(event.target.value)}>{editorModel.approaches.map((approach) => <option key={approach.approach_id} value={approach.approach_id}>{approach.approach_id}</option>)}</select></label>
            {(() => {
              const approach = editorModel.approaches.find((item) => item.approach_id === selectedApproachId) || editorModel.approaches[0]
              if (!approach) return null
              return <div className='channelized-parameter-grid'>
                <label>方向角<input aria-label='进口方向角' type='number' step='1' value={approach.angle_deg} onChange={(event) => updateEditorApproach('angle_deg', Number(event.target.value))} /></label>
                <label>进口车道<input aria-label='进口车道数' type='number' min='1' max='12' value={approach.inbound_lane_count} onChange={(event) => updateEditorApproach('inbound_lane_count', Number(event.target.value))} /></label>
                <label>出口车道<input aria-label='出口车道数' type='number' min='1' max='12' value={approach.outbound_lane_count} onChange={(event) => updateEditorApproach('outbound_lane_count', Number(event.target.value))} /></label>
                <label>车道宽度<input aria-label='车道宽度像素' type='number' min='2' value={approach.lane_width_px} onChange={(event) => updateEditorApproach('lane_width_px', Number(event.target.value))} /></label>
                <label>进口长度<input aria-label='进口长度像素' type='number' min='11' value={approach.approach_length_px} onChange={(event) => updateEditorApproach('approach_length_px', Number(event.target.value))} /></label>
                <label>展宽长度<input aria-label='展宽长度像素' type='number' min='0' value={approach.flare_length_px} onChange={(event) => updateEditorApproach('flare_length_px', Number(event.target.value))} /></label>
                <label className='parameter-check'><input type='checkbox' checked={approach.right_turn_lane} onChange={(event) => updateEditorApproach('right_turn_lane', event.target.checked)} /> 右转专用道</label>
                {Array.from({ length: approach.inbound_lane_count }, (_, index) => <label key={`turn-${index}`}>{`进口 ${index + 1} 转向`}<select aria-label={`进口车道 ${index + 1} 转向`} value={approach.turn_directions?.[index] || 'straight'} onChange={(event) => {
                  const directions = [...(approach.turn_directions || [])]
                  directions[index] = event.target.value
                  updateEditorApproach('turn_directions', directions)
                }}><option value='left_turn'>左转</option><option value='straight'>直行</option><option value='right_turn'>右转</option><option value='u_turn'>掉头</option></select></label>)}
                {Array.from({ length: approach.inbound_lane_count }, (_, index) => <label key={`special-${index}`}>{`进口 ${index + 1} 属性`}<select aria-label={`进口车道 ${index + 1} 特殊属性`} value={approach.special_lane_attributes?.[`lane_${index + 1}`] || ''} onChange={(event) => {
                  const attributes = { ...(approach.special_lane_attributes || {}) }
                  if (event.target.value) attributes[`lane_${index + 1}`] = event.target.value
                  else delete attributes[`lane_${index + 1}`]
                  updateEditorApproach('special_lane_attributes', attributes)
                }}><option value=''>无</option><option value='bus'>公交</option><option value='tidal'>潮汐</option></select></label>)}
              </div>
            })()}
            <div className='channelized-template-actions' role='group' aria-label='渠化要素模板'>
              <button type='button' className='secondary-button' onClick={() => addFeatureTemplate('crosswalk')}>标准人行横道</button>
              <button type='button' className='secondary-button' onClick={() => addFeatureTemplate('crosswalk', 'right_turn')}>右转人行横道</button>
              <button type='button' className='secondary-button' onClick={() => addFeatureTemplate('channelizing_island', 'right_turn')}>右转渠化岛</button>
              <button type='button' className='secondary-button' onClick={() => addFeatureTemplate('waiting_zone')}>左转待转区</button>
              <button type='button' className='secondary-button' onClick={() => addFeatureTemplate('lane_boundary')}>车道边界</button>
              <button type='button' className='secondary-button' onClick={() => addFeatureTemplate('lane_marking')}>分段标线</button>
            </div>
            <div className='channelized-template-parameters'>{editorModel.feature_templates.filter((item) => item.approach_id === selectedApproachId).map((template) => <div key={template.feature_id}>
              <strong>{template.variant === 'right_turn' ? '右转人行横道' : geometryLabels[template.feature_type] || template.feature_type}</strong>
              <label>宽度<input aria-label={`${template.feature_id} 宽度`} type='number' min='1' value={template.width_px || 1} onChange={(event) => updateFeatureTemplate(template.feature_id, 'width_px', Number(event.target.value))} /></label>
              <label>退距<input aria-label={`${template.feature_id} 退距`} type='number' value={template.setback_px || 0} onChange={(event) => updateFeatureTemplate(template.feature_id, 'setback_px', Number(event.target.value))} /></label>
              <label>长度<input aria-label={`${template.feature_id} 长度`} type='number' min='1' value={template.length_px || 1} onChange={(event) => updateFeatureTemplate(template.feature_id, 'length_px', Number(event.target.value))} /></label>
              <select aria-label={`${template.feature_id} 颜色`} value={template.color || 'white'} onChange={(event) => updateFeatureTemplate(template.feature_id, 'color', event.target.value)}><option value='white'>白</option><option value='yellow'>黄</option><option value='blue'>蓝</option></select>
              <select aria-label={`${template.feature_id} 线型`} value={template.line_style || 'solid'} onChange={(event) => updateFeatureTemplate(template.feature_id, 'line_style', event.target.value)}><option value='solid'>实线</option><option value='dashed'>虚线</option></select>
            </div>)}</div>
            <small>公交、潮汐等特殊车道仅记录属性；专用运行规则尚未实现。</small>
          </>}
        </div>
      </details>

      <section className='workbench-side-card'>
        <header><strong>质量门禁</strong><span className='quality-score'>{qualityPassed}/{qualityChecks.length} 通过</span></header>
        <ul className='workbench-checks'>{qualityChecks.map(([label, passed]) => <li key={label} className={passed ? 'passed' : ''}>{passed ? <CheckCircle size={14} weight='fill' /> : <WarningCircle size={14} />}<span>{label}</span><b>{passed ? '通过' : '待处理'}</b></li>)}</ul>
      </section>

      <details className='workbench-side-card workbench-disclosure'>
        <summary><strong>高级配准参数</strong><span>仅重新测定时修改</span></summary>
        <label className='field-label'>SourceProfile ID<input value={sourceProfileId} onChange={(event) => setSourceProfileId(event.target.value)} /></label>
        <label className='field-label'>原始 pixel → ENU 3×3 单应矩阵（只读诊断）<textarea aria-label='pixel → ENU 3×3 单应矩阵' value={homography} readOnly /></label>
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
            <select aria-label='画布视图' value={canvasMode} onChange={(event) => setCanvasMode(event.target.value)}><option value='image'>影像叠加</option><option value='clean'>干净渠化图</option>{!selectedTask && <option value='map'>GCJ-02 发布预览</option>}</select>
            <select aria-label='当前关键帧' value={selectedTaskId} onChange={(event) => adoptTask(tasks.find((task) => task.task_id === event.target.value))}><option value=''>选择关键帧</option>{tasks.map((task) => <option key={task.task_id} value={task.task_id}>{task.source_frame_id || task.task_id}</option>)}</select>
            <button type='button' className='secondary-button' onClick={() => setCanvasMode((value) => value === 'image' ? 'clean' : 'image')}>影像 / 干净渠化图</button>
          </div>
          <span>{selectedTask ? `${selectedTask.source_profile_id || 'SourceProfile'} · ${selectedTask.source_frame_id || selectedTask.task_id}` : '尚未载入关键帧'}</span>
        </header>

        <div className='workbench-canvas-stage' ref={stageRef}>
          {canvasMode === 'map' ? <ChannelizedMapPreview mapVersion={mapVersion} /> : <div className={`annotation-stage live-annotation${canvasMode === 'clean' ? ' channelized-clean-canvas' : ''}`} style={{ '--canvas-zoom': canvasZoom }}>
            {selectedTask && (taskImageUrl || canvasMode === 'clean') ? <svg
              viewBox={`0 0 ${imageSize[0]} ${imageSize[1]}`}
              preserveAspectRatio='xMidYMid meet'
              onClick={addPoint}
              onPointerDown={startCanvasPointer}
              onPointerMove={moveLaneDrag}
              onPointerUp={finishLaneDrag}
              onPointerCancel={finishLaneDrag}
              aria-label='渠化几何绘制画布'
            >
              {canvasMode === 'image' && <image href={taskImageUrl} width={imageSize[0]} height={imageSize[1]} />}
              {canvasMode !== 'clean' && showReferenceLanes && referenceLanes.map((lane) => <polygon style={{ opacity: overlayOpacity }} key={`reference-${lane.local_lane_id}`} aria-label={`路网参考车道 ${lane.local_lane_id}`} className='channelized-reference-lane' points={lane.points.map((point) => point.join(',')).join(' ')} onClick={(event) => { event.stopPropagation(); adoptReferenceLane(lane) }} onDoubleClick={(event) => { event.stopPropagation(); adoptReferenceLane(lane, 'lane') }} />)}
              {layerVisibility.draft && draftLanes.map((lane) => <g style={{ opacity: canvasMode === 'clean' ? 1 : overlayOpacity }} key={lane.local_lane_id}>
                <polygon aria-label={`拟合车道 ${lane.local_lane_id}`} aria-selected={laneSelection.laneIds.includes(lane.local_lane_id)} className={laneSelection.laneIds.includes(lane.local_lane_id) ? `channelized-draft-lane selected${laneSelection.mode === 'lane' ? ' single' : ''}` : 'channelized-draft-lane'} points={sampleLaneCurves(lane).map((point) => point.join(',')).join(' ')} onClick={(event) => { event.stopPropagation(); setLaneSelection(selectLaneDraft(draftLanes, lane.local_lane_id, 'link')) }} onDoubleClick={(event) => { event.stopPropagation(); setLaneSelection(selectLaneDraft(draftLanes, lane.local_lane_id, 'lane')) }} onPointerDown={(event) => {
                  const origin = imagePointFromEvent(event)
                  if (!origin) return
                  event.preventDefault(); event.stopPropagation()
                  const dragSelection = laneSelection.mode === 'lane' && laneSelection.laneIds.includes(lane.local_lane_id)
                    ? laneSelection
                    : selectLaneDraft(draftLanes, lane.local_lane_id, 'link')
                  setLaneSelection(dragSelection)
                  laneDragRef.current = {
                    type: 'translate',
                    source: editorSnapshot(),
                    laneIds: dragSelection.laneIds,
                    origin,
                    originalPointsById: Object.fromEntries(draftLanes
                      .filter((item) => dragSelection.laneIds.includes(item.local_lane_id))
                      .map((item) => [item.local_lane_id, item.points.map((point) => [...point])])),
                  }
                  event.currentTarget.ownerSVGElement?.setPointerCapture?.(event.pointerId)
                }} />
                {laneSelection.laneIds.length === 1 && laneSelection.laneIds[0] === lane.local_lane_id && lane.points.map(([x, y], index) => <circle key={`${lane.local_lane_id}-${index}`} aria-label={`调整车道顶点 ${index + 1}`} className='channelized-lane-handle' cx={x} cy={y} r='6' onPointerDown={(event) => {
                  event.preventDefault(); event.stopPropagation(); laneDragRef.current = { type: 'vertex', laneId: lane.local_lane_id, index, source: editorSnapshot() }; event.currentTarget.ownerSVGElement?.setPointerCapture?.(event.pointerId)
                }} onClick={(event) => event.stopPropagation()} />)}
                {laneSelection.laneIds.length === 1 && laneSelection.laneIds[0] === lane.local_lane_id && (lane.boundary_curves || []).map((curve) => {
                  const start = lane.points[curve.edge_index]
                  const end = lane.points[(curve.edge_index + 1) % lane.points.length]
                  return <g className='channelized-curve-controls' key={`${lane.local_lane_id}-curve-${curve.edge_index}`}>
                    <line x1={start[0]} y1={start[1]} x2={curve.control1[0]} y2={curve.control1[1]} />
                    <line x1={end[0]} y1={end[1]} x2={curve.control2[0]} y2={curve.control2[1]} />
                    {['control1', 'control2'].map((control) => <circle key={control} aria-label={`调整曲线控制点 ${control === 'control1' ? 1 : 2}`} className='channelized-curve-handle' cx={curve[control][0]} cy={curve[control][1]} r='7' onPointerDown={(event) => {
                      event.preventDefault(); event.stopPropagation(); laneDragRef.current = { type: 'curve_control', laneId: lane.local_lane_id, edgeIndex: curve.edge_index, control, source: editorSnapshot() }; event.currentTarget.ownerSVGElement?.setPointerCapture?.(event.pointerId)
                    }} />)}
                  </g>
                })}
              </g>)}
              {draftFeatures.filter((feature) => ['guide_zone', 'waiting_zone', 'crosswalk', 'channelizing_island'].includes(feature.feature_type) ? layerVisibility.features : layerVisibility.boundaries).map((feature) => ['guide_zone', 'waiting_zone', 'crosswalk', 'channelizing_island'].includes(feature.feature_type)
                ? <polygon style={{ opacity: canvasMode === 'clean' ? 1 : overlayOpacity }} key={feature.feature_id} points={feature.points.map((point) => point.join(',')).join(' ')} className={`channelized-feature-area ${feature.feature_type}`} />
                : <polyline style={{ opacity: canvasMode === 'clean' ? 1 : overlayOpacity }} key={feature.feature_id} points={feature.points.map((point) => point.join(',')).join(' ')} className={feature.feature_type === 'stop_line' ? 'channelized-stop-line' : `channelized-boundary ${feature.properties?.line_style || ''}`} />)}
              {editorModel && editorModel.approaches.map((approach) => {
                const handle = approachHandlePoint(editorModel, approach)
                return <g className={`channelized-approach-guide${approach.approach_id === selectedApproachId ? ' selected' : ''}`} key={`approach-guide-${approach.approach_id}`}>
                  <line x1={editorModel.center_px[0]} y1={editorModel.center_px[1]} x2={handle[0]} y2={handle[1]} />
                  <circle aria-label={`调整进口骨架 ${approach.approach_id}`} cx={handle[0]} cy={handle[1]} r='10' onPointerDown={(event) => {
                    event.preventDefault(); event.stopPropagation()
                    const source = editorSnapshot()
                    laneDragRef.current = { type: 'approach_parameter', approachId: approach.approach_id, source, preview: source }
                    setSelectedApproachId(approach.approach_id)
                    event.currentTarget.ownerSVGElement?.setPointerCapture?.(event.pointerId)
                  }} />
                </g>
              })}
              {draftPoints.length > 1 && <polyline points={draftPoints.map((point) => point.join(',')).join(' ')} />}
              {draftPoints.map(([x, y], index) => <circle key={`${x}-${y}-${index}`} cx={x} cy={y} r='5' />)}
            </svg> : <div className='workbench-canvas-empty'><strong>载入正拍关键帧开始渠化拟合</strong><span>右侧“关键帧与素材”只展示当前路口的真实测绘任务。</span><button type='button' className='primary-button' onClick={openSourcePicker}>选择关键帧</button></div>}
          </div>}

          {canvasMode === 'image' && <>
            <div className='workbench-toolstrip' aria-label='画布工具'>
              <button type='button' className={editorTool === 'inspect' ? 'active' : ''} aria-label='查看模式' onClick={() => setEditorTool('inspect')}><Hand size={18} /></button>
              <button type='button' className={editorTool === 'draw' ? 'active' : ''} aria-label='绘制模式' onClick={() => setEditorTool('draw')}><CursorClick size={18} /></button>
              <button type='button' className={editorTool === 'align' ? 'active' : ''} aria-label='整体对齐模式' onClick={() => setEditorTool('align')}><LinkSimple size={18} /></button>
              <button type='button' aria-label='撤销编辑' disabled={!editorHistoryRef.current.past.length} onClick={undoEditor}><ArrowCounterClockwise size={18} /></button>
              <button type='button' aria-label='重做编辑' disabled={!editorHistoryRef.current.future.length} onClick={redoEditor}><ArrowClockwise size={18} /></button>
              <button type='button' aria-label='图层'><Stack size={18} /></button>
              <button type='button' aria-label='吸附参考车道' onClick={() => setShowReferenceLanes((value) => !value)}><LinkSimple size={18} /></button>
              <button type='button' aria-label='放大' onClick={() => setCanvasZoom((value) => Math.min(2, value + 0.15))}><Plus size={18} /></button>
              <button type='button' aria-label='缩小' onClick={() => setCanvasZoom((value) => Math.max(.7, value - 0.15))}><Minus size={18} /></button>
              <button type='button' aria-label='全屏' onClick={() => stageRef.current?.requestFullscreen?.()}><ArrowsOutSimple size={18} /></button>
            </div>
            <div className={`workbench-registration-panel${registrationPanelOpen ? ' expanded' : ''}`}>
              <button
                type='button'
                className='registration-panel-toggle'
                aria-expanded={registrationPanelOpen}
                aria-controls='registration-panel-details'
                aria-label={`${registrationPanelOpen ? '收起' : '展开'}整体配准`}
                onClick={() => setRegistrationPanelOpen((value) => !value)}
              >
                <strong>整体配准</strong>
                <span>X {Number(registrationPose.translation_px[0].toFixed(1))} · Y {Number(registrationPose.translation_px[1].toFixed(1))} · {Number(registrationPose.rotation_deg.toFixed(1))}° · {Number(registrationPose.uniform_scale.toFixed(2))}×</span>
                <i aria-hidden='true'>{registrationPanelOpen ? '收起' : '调整'}</i>
              </button>
              {registrationPanelOpen && <div id='registration-panel-details' className='registration-panel-details'>
                <header><span>固定正拍图，移动路网覆盖层</span><button type='button' onClick={() => updateRegistrationPose({ translation_px: [0, 0], rotation_deg: 0, uniform_scale: 1 })}>复位</button></header>
                <div className='registration-fields'>
                  <label>X<input aria-label='路网 X 位移' type='number' value={Number(registrationPose.translation_px[0].toFixed(2))} onChange={(event) => updateRegistrationPose({ translation_px: [Number(event.target.value), registrationPose.translation_px[1]] })} /></label>
                  <label>Y<input aria-label='路网 Y 位移' type='number' value={Number(registrationPose.translation_px[1].toFixed(2))} onChange={(event) => updateRegistrationPose({ translation_px: [registrationPose.translation_px[0], Number(event.target.value)] })} /></label>
                  <label>角度<input aria-label='路网旋转角' type='number' step='.1' value={Number(registrationPose.rotation_deg.toFixed(2))} onChange={(event) => updateRegistrationPose({ rotation_deg: Number(event.target.value) })} /></label>
                  <label>缩放<input aria-label='路网统一缩放' type='number' min='.1' max='10' step='.01' value={Number(registrationPose.uniform_scale.toFixed(3))} onChange={(event) => updateRegistrationPose({ uniform_scale: Number(event.target.value) })} /></label>
                </div>
                <label className='registration-opacity'>透明度<input aria-label='路网覆盖层透明度' type='range' min='.1' max='1' step='.05' value={overlayOpacity} onChange={(event) => setOverlayOpacity(Number(event.target.value))} /></label>
              </div>}
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
          <select aria-label='几何类型' value={drawingMode} onChange={(event) => { setDrawingMode(event.target.value); setDraftPoints([]) }}><option value='lane'>车道面</option><option value='lane_boundary'>车道边界</option><option value='stop_line'>停止线</option><option value='guide_zone'>导流区</option><option value='waiting_zone'>待转区</option><option value='crosswalk'>人行横道</option><option value='channelizing_island'>渠化岛</option><option value='lane_marking'>分段标线</option></select>
          {drawingMode === 'lane' && <select aria-label='车道方向' value={direction} onChange={(event) => setDirection(event.target.value)}><option value='straight'>直行</option><option value='left_turn'>左转</option><option value='right_turn'>右转</option><option value='u_turn'>掉头</option></select>}
          <button className='secondary-button' disabled={draftPoints.length < (isLineGeometry(drawingMode) ? 2 : 3)} onClick={closeGeometry}>完成{geometryLabels[drawingMode]}</button>
          <button className='secondary-button' disabled={!draftPoints.length} onClick={() => setDraftPoints((points) => points.slice(0, -1))}>撤销一点</button>
          <button className='secondary-button' disabled={!draftPoints.length} onClick={() => setDraftPoints([])}>清空顶点</button>
          <button className='secondary-button' disabled={!hasGeometryForMode} onClick={removeLastGeometry}>移除最后{geometryLabels[drawingMode]}</button>
          {drawingMode === 'lane' && <button className='secondary-button' disabled={!referenceLanes.length} onClick={adoptAllReferenceLanes}>采用整套路网（{referenceLanes.length} 条）</button>}
          {drawingMode === 'lane' && <div className='lane-operation-cluster' role='group' aria-label='车道编辑操作'>
            <button className='secondary-button danger' disabled={!laneSelection.laneIds.length} onClick={deleteSelectedLanes}>删除所选</button>
            <button className='secondary-button' disabled={laneSelection.mode !== 'lane' || laneSelection.laneIds.length !== 1} onClick={splitSelectedLane}>拆分车道</button>
            <button className='secondary-button' disabled={laneSelection.laneIds.length < 2} onClick={mergeSelectedLanes}>合并车道</button>
            <label className='curve-edge-input'>边界段<input aria-label='曲线边界段序号' type='number' min='1' value={curveEdgeIndex + 1} onChange={(event) => setCurveEdgeIndex(Math.max(0, Number(event.target.value) - 1))} /></label>
            <button className='secondary-button' disabled={laneSelection.mode !== 'lane' || laneSelection.laneIds.length !== 1} onClick={curveSelectedLaneEdge}>边界段转曲线</button>
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
