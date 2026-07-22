import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AppShell } from '../components/AppShell'
import { ChannelizedMapPreview } from '../components/ChannelizedMapPreview'
import { InfoRow, PageHeader, Panel, QualityNotice, StatusBadge } from '../components/Common'
import { apiErrorMessage, platformApi } from '../lib/api'
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
    <div className='annotation-task-list'>
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
    </div>
  </>
}

export function ChannelizationCalibrationPage() {
  const queryClient = useQueryClient()
  const [interId, setInterId] = useState('011wwe0z19700001')
  const [mapVersion, setMapVersion] = useState(null)
  const [selectedTaskId, setSelectedTaskId] = useState('')
  const [selectedSurveyTaskId, setSelectedSurveyTaskId] = useState('')
  const [selectedBatchId, setSelectedBatchId] = useState('')
  const [selectedFrameId, setSelectedFrameId] = useState('')
  const [draftPoints, setDraftPoints] = useState([])
  const [draftLanes, setDraftLanes] = useState([])
  const [selectedLaneId, setSelectedLaneId] = useState('')
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
  const laneDragRef = useRef(null)

  const tasksQuery = useQuery({ queryKey: ['lane-tasks'], queryFn: platformApi.laneTasks, refetchInterval: 5_000 })
  const surveyTasksQuery = useQuery({ queryKey: ['survey-tasks'], queryFn: () => platformApi.surveyTasks() })
  const sourcesQuery = useQuery({ queryKey: ['sources'], queryFn: platformApi.sources })
  const dronesQuery = useQuery({ queryKey: ['drones'], queryFn: platformApi.drones })
  const allTasks = Array.isArray(tasksQuery.data) ? tasksQuery.data : []
  const tasks = allTasks.filter((task) => task.status !== 'invalidated')
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
    setSelectedLaneId('')
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
    resetGeometry()
    if (intersectionChanged) {
      setMapVersion(null)
      setRegistrationId('')
    }
  }, [interId, resetGeometry])

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
  const adoptReferenceLane = (reference) => {
    setSelectedLaneId(reference.local_lane_id)
    setDraftLanes((lanes) => lanes.some((lane) => lane.local_lane_id === reference.local_lane_id)
      ? lanes
      : [...lanes, {
        local_lane_id: reference.local_lane_id,
        source_lane_id: reference.source_lane_id,
        link_id: reference.link_id,
        direction: 'straight',
        points: reference.points.map((point) => [...point]),
      }])
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
    if (!selectedTask) return
    const point = imagePointFromEvent(event)
    if (point) setDraftPoints((points) => [...points, point])
  }
  const moveLaneDrag = (event) => {
    const drag = laneDragRef.current
    if (!drag) return
    const point = imagePointFromEvent(event)
    if (!point) return
    setDraftLanes((lanes) => lanes.map((lane) => lane.local_lane_id === drag.laneId
      ? {
        ...lane,
        points: drag.type === 'translate'
          ? dragImageGeometry(drag.originalPoints, { type: 'translate', dx: point[0] - drag.origin[0], dy: point[1] - drag.origin[1] }, { width: imageSize[0], height: imageSize[1] })
          : dragImageGeometry(lane.points, { type: 'vertex', index: drag.index, point }, { width: imageSize[0], height: imageSize[1] }),
      }
      : lane))
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
  const hasGeometryForMode = drawingMode === 'lane'
    ? draftLanes.length > 0
    : draftFeatures.some((feature) => feature.feature_type === drawingMode)
  const error = startExtraction.error || createKeyframeTask.error || bootstrap.error || forkDraft.error || fit.error || verify.error || publish.error || taskImageQuery.error
  const registrationVerified = registrationId.endsWith(':verified')
  const canFit = Boolean(isEditableMap(mapVersion) && hasMapAlignedTask && sourceProfileId.trim() && draftLanes.length)

  return <AppShell pageTitle='渠化车道标注'>
    <PageHeader eyebrow='第一阶段 · GCJ-02 + 高德地图' title='渠化车道标注工作台' description='本地无路口数据时才从 YCX 只读导入候选 Link/车道；基于正拍影像拟合后发布不可变 lane_verified 地图。' meta={mapVersion ? `${mapVersion.inter_id} · v${mapVersion.version_no}` : '未加载地图'} />
    {error && <QualityNotice tone='warning' title='操作未通过'>{apiErrorMessage(error)}</QualityNotice>}
    {fit.isSuccess && <QualityNotice tone='info' title='拟合候选已保存'>服务端已完成 pixel → ENU → GCJ-02，下一步请复核视觉配准和质量门禁。</QualityNotice>}
    <Panel title='路口与地图版本' subtitle='YCX lane_info 为 Link 偏移候选，不作为车道真值'>
      <div className='annotation-toolbar'>
        <input aria-label='路口 ID' value={interId} onChange={(event) => setInterId(event.target.value)} placeholder='inter_id' />
        <button className='primary-button' disabled={!interId.trim() || bootstrap.isPending} onClick={() => bootstrap.mutate()}>{bootstrap.isPending ? '加载中…' : '加载本地 / 按需导入'}</button>
        {mapVersion && <StatusBadge value={mapVersion.status} />}
      </div>
      {bootstrap.data?.source && <QualityNotice tone='info' title='数据来源'>{bootstrap.data.source === 'local' ? '已使用本地版本，未访问 YCX。' : '本地无数据，已从 YCX 只读导入该路口。'}</QualityNotice>}
    </Panel>
    <div className='calibration-layout'>
      <Panel title='高德叠加预览' subtitle='青色 Link、黄色候选中心线、绿色拟合车道面'><ChannelizedMapPreview mapVersion={mapVersion} /></Panel>
      <Panel title='版本门禁'>{mapVersion ? <>
        <InfoRow label='坐标系' value={mapVersion.coordinate_system} />
        <InfoRow label='路网版本' value={mapVersion.road_data_version} />
        <InfoRow label='候选/拟合车道' value={String(mapVersion.lanes?.length || 0)} />
        <InfoRow label='转换版本' value={mapVersion.coordinate_transform_version} />
        {!isEditableMap(mapVersion) && <button className='secondary-button full' disabled={forkDraft.isPending} onClick={() => forkDraft.mutate()}>
          {forkDraft.isPending ? '正在创建草稿…' : `基于 ${mapVersion.status} 新建拟合草稿`}
        </button>}
        <button className='secondary-button full' disabled={!registrationVerified || publish.isPending} onClick={() => publish.mutate('link_verified')}>通过 Link 门禁</button>
        <button className='primary-button full' disabled={!registrationVerified || publish.isPending} onClick={() => publish.mutate('lane_verified')}>发布 lane_verified</button>
      </> : <div className='live-state empty'>尚未加载地图</div>}</Panel>
    </div>
    <div className='calibration-layout' data-testid='lane-editor-workspace'>
      <Panel title='无人机正拍车道编辑器' subtitle='点击影像添加顶点；画布按真实影像比例换算，服务端统一执行 pixel → ENU → GCJ-02'>
        <div className='annotation-stage live-annotation'>
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
            {showReferenceLanes && referenceLanes.map((lane) => <polygon
              key={`reference-${lane.local_lane_id}`}
              aria-label={`路网参考车道 ${lane.local_lane_id}`}
              className='channelized-reference-lane'
              points={lane.points.map((point) => point.join(',')).join(' ')}
              onClick={(event) => { event.stopPropagation(); adoptReferenceLane(lane) }}
            />)}
            {draftLanes.map((lane) => <g key={lane.local_lane_id}>
              <polygon
                aria-label={`拟合车道 ${lane.local_lane_id}`}
                className={selectedLaneId === lane.local_lane_id ? 'channelized-draft-lane selected' : 'channelized-draft-lane'}
                points={lane.points.map((point) => point.join(',')).join(' ')}
                onClick={(event) => { event.stopPropagation(); setSelectedLaneId(lane.local_lane_id) }}
                onPointerDown={(event) => {
                  const origin = imagePointFromEvent(event)
                  if (!origin) return
                  event.preventDefault()
                  event.stopPropagation()
                  setSelectedLaneId(lane.local_lane_id)
                  laneDragRef.current = { type: 'translate', laneId: lane.local_lane_id, origin, originalPoints: lane.points.map((point) => [...point]) }
                  event.currentTarget.ownerSVGElement?.setPointerCapture?.(event.pointerId)
                }}
              />
              {selectedLaneId === lane.local_lane_id && lane.points.map(([x, y], index) => <circle
                key={`${lane.local_lane_id}-${index}`}
                aria-label={`调整车道顶点 ${index + 1}`}
                className='channelized-lane-handle'
                cx={x}
                cy={y}
                r='6'
                onPointerDown={(event) => {
                  event.preventDefault()
                  event.stopPropagation()
                  laneDragRef.current = { type: 'vertex', laneId: lane.local_lane_id, index }
                  event.currentTarget.ownerSVGElement?.setPointerCapture?.(event.pointerId)
                }}
                onClick={(event) => event.stopPropagation()}
              />)}
            </g>)}
            {draftFeatures.map((feature) => feature.feature_type === 'guide_zone' || feature.feature_type === 'waiting_zone'
              ? <polygon key={feature.feature_id} points={feature.points.map((point) => point.join(',')).join(' ')} className='channelized-feature-area' />
              : <polyline key={feature.feature_id} points={feature.points.map((point) => point.join(',')).join(' ')} className={feature.feature_type === 'stop_line' ? 'channelized-stop-line' : 'channelized-boundary'} />)}
            {draftPoints.length > 1 && <polyline points={draftPoints.map((point) => point.join(',')).join(' ')} />}
            {draftPoints.map(([x, y], index) => <circle key={`${x}-${y}-${index}`} cx={x} cy={y} r='5' />)}
          </svg> : <div className='live-state empty'>从右侧选择真实测绘关键帧，载入后即可开始标注</div>}
        </div>
        {selectedTask && mapVersion && !hasMapAlignedTask && <div className='form-error' role='alert'>该任务仍是帧局部量算坐标；请点击右侧“载入关键帧并开始标注”，刷新为当前地图 ENU 后再叠加与拟合。</div>}
        <div className='annotation-toolbar'>
          <label className='lane-overlay-toggle'><input type='checkbox' checked={showReferenceLanes} onChange={(event) => setShowReferenceLanes(event.target.checked)} /> 叠加路网车道</label>
          <select aria-label='几何类型' value={drawingMode} onChange={(event) => { setDrawingMode(event.target.value); setDraftPoints([]) }}>
            <option value='lane'>车道面</option><option value='lane_boundary'>车道边界</option><option value='stop_line'>停止线</option><option value='guide_zone'>导流区</option><option value='waiting_zone'>待转区</option>
          </select>
          {drawingMode === 'lane' && <select aria-label='车道方向' value={direction} onChange={(event) => setDirection(event.target.value)}><option value='straight'>直行</option><option value='left_turn'>左转</option><option value='right_turn'>右转</option><option value='u_turn'>掉头</option></select>}
          <button className='secondary-button' disabled={draftPoints.length < (isLineGeometry(drawingMode) ? 2 : 3)} onClick={closeGeometry}>完成{geometryLabels[drawingMode]}</button>
          <button className='secondary-button' disabled={!draftPoints.length} onClick={() => setDraftPoints((points) => points.slice(0, -1))}>撤销一点</button>
          <button className='secondary-button' disabled={!draftPoints.length} onClick={() => setDraftPoints([])}>清空顶点</button>
          <button className='secondary-button' disabled={!hasGeometryForMode} onClick={removeLastGeometry}>移除最后{geometryLabels[drawingMode]}</button>
          <span>{draftPoints.length} 个顶点 · {draftLanes.length} 条车道 · {draftFeatures.length} 个渠化要素</span>
        </div>
      </Panel>
      <Panel title={`关键帧任务 · ${tasks.length}`} subtitle='先从真实测绘帧创建，再进入影像标注'>
        <KeyframeTaskPicker
          interId={interId}
          extractionSources={eligibleExtractionSources}
          onStartExtraction={(sourceProfileId, checklist) => startExtraction.mutate({ sourceProfileId, checklist })}
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
        />
      </Panel>
    </div>
    <div className='calibration-layout'>
      <Panel title='配准参数' subtitle='关键帧来源自动带入；仅在重新测定控制点时手工修改'>
        <label className='field-label'>SourceProfile ID<input value={sourceProfileId} onChange={(event) => setSourceProfileId(event.target.value)} placeholder='从关键帧批次自动带入' /></label>
        <label className='field-label'>pixel → ENU 3×3 单应矩阵<textarea value={homography} onChange={(event) => setHomography(event.target.value)} /></label>
        <label className='field-label'>控制点 JSON（pixel / enu_m）<textarea value={controlPoints} onChange={(event) => setControlPoints(event.target.value)} /></label>
      </Panel>
      <Panel title='质量结果与人工复核'>
        {mapVersion && !isEditableMap(mapVersion) && <QualityNotice tone='info' title='当前版本只读'>请先在版本门禁中基于 {mapVersion.status} 新建拟合草稿。</QualityNotice>}
        <label className='field-label'>Link 残差 P95（m）<input value={quality.link_residual_p95_m} onChange={(event) => setQuality((item) => ({ ...item, link_residual_p95_m: event.target.value }))} /></label>
        <label className='field-label'>车道边界残差中位数（m）<input value={quality.lane_residual_median_m} onChange={(event) => setQuality((item) => ({ ...item, lane_residual_median_m: event.target.value }))} /></label>
        <label className='field-label'>车道边界残差 P95（m）<input value={quality.lane_residual_p95_m} onChange={(event) => setQuality((item) => ({ ...item, lane_residual_p95_m: event.target.value }))} /></label>
        <label className='field-label'>拓扑错误数<input value={quality.topology_errors} onChange={(event) => setQuality((item) => ({ ...item, topology_errors: event.target.value }))} /></label>
        <label className='field-label'><input type='checkbox' checked={quality.direction_checks_passed} onChange={(event) => setQuality((item) => ({ ...item, direction_checks_passed: event.target.checked }))} /> 进口、出口和转向关系检查通过</label>
        <label className='field-label'><input type='checkbox' checked={quality.stop_line_checks_passed} onChange={(event) => setQuality((item) => ({ ...item, stop_line_checks_passed: event.target.checked }))} /> 停止线检查通过</label>
        <label className='field-label'><input type='checkbox' checked={quality.reviewed} onChange={(event) => setQuality((item) => ({ ...item, reviewed: event.target.checked }))} /> 已完成人工复核</label>
        <button className='primary-button full' disabled={!canFit || fit.isPending} onClick={() => fit.mutate()}>{fit.isPending ? '服务端拟合中…' : '保存影像拟合候选'}</button>
        <button className='secondary-button full' disabled={!registrationId || registrationVerified || verify.isPending} onClick={() => verify.mutate()}>复核并确认视觉配准</button>
      </Panel>
    </div>
  </AppShell>
}
