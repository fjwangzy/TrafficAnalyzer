import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowsClockwise, ArrowSquareOut, CalendarBlank, Camera, ChartLineUp, Check, Clock, Crosshair, DownloadSimple, Funnel, Gauge, ListBullets, MapPin, Pause, Play, RoadHorizon, ShieldWarning, Stack, Truck, VideoCamera, Warning, X } from '@phosphor-icons/react'
import { AppShell } from '../components/AppShell'
import { CityMap } from '../components/CityMap'
import { MonitoringBevMap } from '../components/MonitoringBevMap'
import { DataTable, DetailDrawer, FilterBar, InfoRow, KpiCard, PageHeader, Panel, QualityNotice, Segmented, StatusBadge } from '../components/Common'
import { aiEvents, intersections as prototypeIntersections } from '../data/mockData'
import { useAppState } from '../state/AppState'
import { useAuth } from '../auth/AuthContext'
import { apiErrorMessage, platformApi } from '../lib/api'

const intersections = prototypeIntersections

const trafficSeries = [
  { time: '06:00', flow: 382, congestion: 2.1, speed: 42 }, { time: '08:00', flow: 768, congestion: 6.2, speed: 26 }, { time: '10:00', flow: 842, congestion: 7.2, speed: 24 },
  { time: '12:00', flow: 611, congestion: 4.5, speed: 34 }, { time: '14:00', flow: 584, congestion: 3.8, speed: 37 }, { time: '16:00', flow: 723, congestion: 5.9, speed: 29 }, { time: '18:00', flow: 891, congestion: 7.7, speed: 22 },
]

function mapIntersection(item) {
  const center = item.center_gcj02 || item.position_gcj02 || {}
  const latitude = center.latitude ?? (Array.isArray(center) ? center[1] : undefined)
  const longitude = center.longitude ?? (Array.isArray(center) ? center[0] : undefined)
  return {
    ...item,
    id: item.inter_id || item.id,
    name: item.name || item.inter_id || item.id,
    lat: latitude == null || latitude === '' ? Number.NaN : Number(latitude),
    lon: longitude == null || longitude === '' ? Number.NaN : Number(longitude),
    quality: item.quality || item.quality_status || item.road_context_quality || 'unverified',
    risk: item.risk || (item.status === 'active' ? 'normal' : 'warning'),
  }
}

async function loadProjectIntersections() {
  const response = await platformApi.dashboardIntersections()
  return response?.items || []
}

function conflictEvent(item) {
  const ttc = Number(item.ttc_sec)
  const severity = ['critical', 'warning'].includes(item.severity) ? item.severity : 'warning'
  return {
    ...item,
    id: item.id,
    severity,
    title: item.conflict_scene || '机非冲突候选',
    type: 'conflict',
    metric: Number.isFinite(ttc) ? `TTC ${ttc.toFixed(1)}s` : 'TTC —',
    delivery: 'not_queued',
    review: item.review_status || 'pending',
    quality: item.quality_status || 'unverified',
    occurredAt: item.occurred_at || '—',
    intersectionId: item.inter_id || item.intersection_id,
  }
}

function alertEvent(item) {
  return {
    ...item,
    id: item.id,
    severity: item.severity === 'P1' ? 'critical' : 'warning',
    type: item.alert_type || 'alert',
    metric: item.description || '告警规则触发',
    delivery: 'not_queued',
    review: item.status === 'acknowledged' ? 'confirmed' : 'pending',
    quality: 'unverified',
    occurredAt: item.timestamp || item.created_at || '—',
    intersectionId: item.intersection_id,
    isAlert: true,
  }
}

const eventTypeLabels = {
  conflict: '真实冲突',
  congestion: '持续拥堵',
  quality_degradation: '质量下降',
  survey_result: '测绘成果',
  queue_overflow: '排队超限',
  calibration_drift: '标定漂移',
  high_avg_speed: '平均车速异常',
}

function unifiedEvent(item) {
  const payload = item.payload || {}
  const surveyVersion = String(payload.task?.version ?? '—').replace(/^v/i, '')
  const severity = item.severity === 'P1' || item.severity === 'critical'
    ? 'critical'
    : item.severity === 'P3' ? 'info' : 'warning'
  const metric = item.event_type === 'conflict'
    ? `TTC ${payload.ttc_sec ?? '—'}s · PET ${payload.pet_sec ?? '—'}s`
    : item.event_type === 'congestion'
      ? `拥堵指数 ${payload.metrics?.congestion_index ?? '—'}`
      : item.event_type === 'quality_degradation'
        ? `连续缺口 ${payload.gap_sec ?? '—'}s`
        : item.event_type === 'survey_result'
          ? `${payload.measurements?.length || 0} 项量算 · v${surveyVersion}`
          : item.description || '规则触发'
  return {
    ...payload,
    ...item,
    severity,
    type: eventTypeLabels[item.event_type] || item.event_type,
    metric,
    delivery: item.delivery_status || 'not_queued',
    review: item.review_status || 'pending',
    quality: item.quality_status || 'unverified',
    occurredAt: item.occurred_at || '—',
    intersectionId: item.inter_id,
    isConflict: item.source_kind === 'conflict',
  }
}

function eventMetricTiles(event) {
  if (event.event_type === 'conflict') return [
    ['TTC', `${event.ttc_sec ?? '—'}s`], ['PET', `${event.pet_sec ?? '—'}s`],
    ['风险分', event.risk_score ?? '—'], ['最小距离', `${event.distance_m ?? '—'}m`],
  ]
  if (event.event_type === 'congestion') return [
    ['拥堵指数', event.metrics?.congestion_index ?? '—'],
    ['连续样本', event.metrics?.event_rule?.consecutive_samples ?? 30],
    ['有效覆盖', event.metrics?.coverage_ratio == null ? '—' : `${(event.metrics.coverage_ratio * 100).toFixed(1)}%`],
    ['丢弃样本', event.metrics?.dropped_samples ?? 0],
  ]
  if (event.event_type === 'quality_degradation') return [
    ['连续缺口', `${event.gap_sec ?? '—'}s`], ['样本数', event.sample_count ?? '—'],
    ['阈值', `${event.rule?.threshold_sec ?? '—'}s`], ['时间质量', event.time_quality || '—'],
  ]
  if (event.event_type === 'survey_result') return [
    ['量算成果', event.measurements?.length || 0], ['证据文件', event.evidence_refs?.length || 0],
    ['成果版本', event.task?.version || '—'], ['质量', event.quality || event.quality_status || '—'],
  ]
  return [['事件类型', event.type], ['状态', event.status || 'open'], ['质量', event.quality], ['证据', event.evidence_refs?.length || 0]]
}

const eventEvidenceLabels = {
  conflict_original_frame: '原始画面',
  conflict_detector_frame: '检测器输出的 TCC 画面帧',
  conflict_trajectory_reconstruction: '轨迹投放 BEV 视图',
  conflict_keyframe: '关键帧证据',
}

function EventEvidenceImage({ reference, label }) {
  const [url, setUrl] = useState('')
  const [expanded, setExpanded] = useState(false)
  const triggerRef = useRef(null)
  useEffect(() => {
    let active = true
    let objectUrl = ''
    setUrl('')
    setExpanded(false)
    if (!reference?.id) return undefined
    platformApi.surveyEvidence(reference.id).then((blob) => {
      objectUrl = URL.createObjectURL(blob)
      if (active) setUrl(objectUrl)
    }).catch(() => setUrl(''))
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [reference?.id])
  useEffect(() => {
    if (!expanded) return undefined
    const previousOverflow = document.body.style.overflow
    const handleKeyDown = (event) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      event.stopPropagation()
      setExpanded(false)
    }
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', handleKeyDown, true)
    return () => {
      document.removeEventListener('keydown', handleKeyDown, true)
      document.body.style.overflow = previousOverflow
      triggerRef.current?.focus()
    }
  }, [expanded])
  if (!url) return <div className='live-state'>正在读取{label}…</div>
  return <>
    <button ref={triggerRef} className='event-evidence-trigger' type='button' aria-label={`全屏查看${label}`} onClick={() => setExpanded(true)}>
      <img className='event-evidence-image' src={url} alt={label} />
      <span>点击查看全屏</span>
    </button>
    {expanded && createPortal(<div className='event-evidence-lightbox' role='dialog' aria-modal='true' aria-label={`${label}全屏预览`} onMouseDown={(event) => { if (event.target === event.currentTarget) setExpanded(false) }}>
      <button className='event-evidence-lightbox-close' type='button' aria-label='关闭证据图片全屏预览' autoFocus onClick={() => setExpanded(false)}><X size={20} /><span>关闭</span></button>
      <img src={url} alt={`${label}全屏预览`} />
    </div>, document.body)}
  </>
}

function EventEvidenceGallery({ references }) {
  return <div className='event-evidence-gallery'>
    {references.map((reference, index) => {
      const label = eventEvidenceLabels[reference.kind] || (index === 0 ? '关键帧证据' : `事件证据 ${index + 1}`)
      return <article className='event-evidence-card' key={reference.id}>
        <header><strong>{label}</strong><span>sha256:{reference.sha256?.slice(0, 12)}…</span></header>
        <EventEvidenceImage reference={reference} label={label} />
      </article>
    })}
  </div>
}

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

const MOVEMENT_COLORS = ['#63b3ff', '#ff806b', '#58d6b0', '#c792ff', '#ffca67']
const BUSINESS_CLASS_LABELS = { motor: '机动车', non_motor: '非机动车', unknown: '未分类' }
const MOVEMENT_SOURCE_LABELS = { road_context: '路网匹配', trajectory_quadrant_inferred: '轨迹方位推断', turn_behavior_fallback: '仅按转向降级', unmapped: '未匹配' }
const MOVEMENT_SORTS = ['business', 'vehicle_count', 'avg_speed', 'conflict']
const TRAJECTORY_SLICE_PARAMS = new Set(['slice_start_at', 'slice_end_at'])

function sameTrajectoryAnalysisScope(previousParams, nextParams) {
  if (!previousParams || !nextParams) return false
  const keys = new Set([...Object.keys(previousParams), ...Object.keys(nextParams)])
  return [...keys].every((key) => TRAJECTORY_SLICE_PARAMS.has(key) || previousParams[key] === nextParams[key])
}

export function nextPlayableSliceIndex(timeline, currentIndex) {
  return timeline.findIndex((item, index) => (
    index > currentIndex && (Number(item.active_tracks) > 0 || Number(item.conflict_count) > 0)
  ))
}

export function firstPlayableSliceIndex(timeline) {
  const index = timeline.findIndex((item) => Number(item.active_tracks) > 0 || Number(item.conflict_count) > 0)
  return index >= 0 ? index : 0
}

function analysisTime(value, includeDate = false) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    ...(includeDate ? { month: '2-digit', day: '2-digit' } : {}),
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(date)
}

function shortEvidenceId(value) {
  const text = String(value || '')
  if (!text) return '—'
  return text.length <= 18 ? text : `${text.slice(0, 8)}…${text.slice(-6)}`
}

function trackLineageLabel(track) {
  const parts = []
  if (track.source_profile_id) parts.push(`源 ${shortEvidenceId(track.source_profile_id)}`)
  if (track.mission_id) parts.push(`任务 ${shortEvidenceId(track.mission_id)}`)
  if (track.pipeline_id) parts.push(`管道 ${shortEvidenceId(track.pipeline_id)}`)
  return parts.join(' · ') || `记录 ${shortEvidenceId(track.id)}`
}

export function GisPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const search = new URLSearchParams(location.search)
  const initialStartAt = search.get('start_at')
  const initialEndAt = search.get('end_at')
  const initialSliceStartAt = search.get('slice_start_at')
  const initialSliceEndAt = search.get('slice_end_at')
  const hasExactWindow = Boolean(initialStartAt && initialEndAt && initialSliceStartAt && initialSliceEndAt)
  const [selectedId, setSelectedId] = useState(search.get('intersection_id'))
  const [period, setPeriod] = useState(['latest30m', 'all', '1h', '24h'].includes(search.get('period')) ? search.get('period') : 'latest30m')
  const [missionId, setMissionId] = useState(search.get('mission_id') || 'all')
  const [sourceProfileId, setSourceProfileId] = useState(search.get('source_profile_id') || 'all')
  const [vehicleClass, setVehicleClass] = useState(search.get('vehicle_class') || search.get('class_name') || 'all')
  const [yoloClassId, setYoloClassId] = useState(search.get('yolo_class_id') || 'all')
  const [turnBehavior, setTurnBehavior] = useState(search.get('turn_behavior') || 'all')
  const [selectedMovement, setSelectedMovement] = useState(search.get('movement_key'))
  const [selectedTrackId, setSelectedTrackId] = useState(search.get('track_id'))
  const [analysisTab, setAnalysisTab] = useState(['movement', 'class', 'track'].includes(search.get('analysis_tab')) ? search.get('analysis_tab') : 'movement')
  const [movementSort, setMovementSort] = useState(MOVEMENT_SORTS.includes(search.get('movement_sort')) ? search.get('movement_sort') : 'business')
  const [analysisWindow, setAnalysisWindow] = useState(hasExactWindow ? { start: initialStartAt, end: initialEndAt } : null)
  const [sliceWindow, setSliceWindow] = useState(hasExactWindow ? { start: initialSliceStartAt, end: initialSliceEndAt } : null)
  const [sliceInteractive, setSliceInteractive] = useState(hasExactWindow)
  const [playing, setPlaying] = useState(false)
  const [playbackSpeed, setPlaybackSpeed] = useState(['0.5', '1', '2', '4'].includes(search.get('playback_speed')) ? Number(search.get('playback_speed')) : 1)

  const intersectionsQuery = useQuery({ queryKey: ['i3-project-intersections'], queryFn: loadProjectIntersections, refetchInterval: 30_000 })
  const missionsQuery = useQuery({ queryKey: ['i3-gis-missions'], queryFn: () => platformApi.missions() })
  const sourcesQuery = useQuery({ queryKey: ['i3-gis-sources'], queryFn: () => platformApi.sources() })
  const projectIntersections = (intersectionsQuery.data || []).map(mapIntersection)
  const selected = projectIntersections.find((item) => item.id === selectedId) || projectIntersections[0] || null
  useEffect(() => { if (!selectedId && selected) setSelectedId(selected.id) }, [selectedId, selected])

  const scopeKey = [selectedId, period, missionId, sourceProfileId, vehicleClass, yoloClassId, turnBehavior].join('|')
  const previousScopeKey = useRef(scopeKey)
  useEffect(() => {
    if (previousScopeKey.current === scopeKey) return
    previousScopeKey.current = scopeKey
    setAnalysisWindow(null)
    setSliceWindow(null)
    setSelectedMovement(null)
    setSelectedTrackId(null)
    setPlaying(false)
    setSliceInteractive(false)
  }, [scopeKey])

  useEffect(() => {
    const params = new URLSearchParams(location.search)
    const setOptional = (name, value, emptyValue = 'all') => {
      if (value && value !== emptyValue) params.set(name, value)
      else params.delete(name)
    }
    setOptional('intersection_id', selectedId, null)
    params.set('period', period)
    setOptional('mission_id', missionId)
    setOptional('source_profile_id', sourceProfileId)
    setOptional('vehicle_class', vehicleClass)
    params.delete('class_name')
    setOptional('yolo_class_id', yoloClassId)
    setOptional('turn_behavior', turnBehavior)
    setOptional('movement_key', selectedMovement, null)
    setOptional('track_id', selectedTrackId, null)
    setOptional('analysis_tab', analysisTab === 'movement' ? null : analysisTab, null)
    setOptional('movement_sort', movementSort === 'business' ? null : movementSort, null)
    setOptional('playback_speed', playbackSpeed === 1 ? null : String(playbackSpeed), null)
    if (analysisWindow && sliceWindow) {
      params.set('start_at', analysisWindow.start)
      params.set('end_at', analysisWindow.end)
      params.set('slice_start_at', sliceWindow.start)
      params.set('slice_end_at', sliceWindow.end)
    } else {
      for (const name of ['start_at', 'end_at', 'slice_start_at', 'slice_end_at']) params.delete(name)
    }
    const nextSearch = params.toString()
    if (nextSearch !== location.search.replace(/^\?/, '')) {
      navigate(`${location.pathname}?${nextSearch}`, { replace: true })
    }
  }, [analysisTab, analysisWindow, location.pathname, location.search, missionId, movementSort, navigate, period, playbackSpeed, selectedId, selectedMovement, selectedTrackId, sliceWindow, sourceProfileId, turnBehavior, vehicleClass, yoloClassId])

  const analysisParams = {
    period, bucket_sec: 10, track_limit: 60,
    ...(missionId !== 'all' ? { mission_id: missionId } : {}),
    ...(sourceProfileId !== 'all' ? { source_profile_id: sourceProfileId } : {}),
    ...(vehicleClass !== 'all' ? { vehicle_class: vehicleClass } : {}),
    ...(yoloClassId !== 'all' ? { yolo_class_id: Number(yoloClassId) } : {}),
    ...(turnBehavior !== 'all' ? { turn_behavior: turnBehavior } : {}),
    ...(selectedMovement ? { movement_key: selectedMovement } : {}),
    ...(sliceInteractive && analysisWindow && sliceWindow ? {
      start_at: analysisWindow.start, end_at: analysisWindow.end,
      slice_start_at: sliceWindow.start, slice_end_at: sliceWindow.end,
    } : {}),
  }
  const analysisQuery = useQuery({
    queryKey: ['trajectory-analysis', selected?.id, analysisParams],
    queryFn: () => platformApi.trajectoryAnalysis(selected.id, analysisParams),
    enabled: Boolean(selected?.id),
    placeholderData: (previous, previousQuery) => (
      sameTrajectoryAnalysisScope(previousQuery?.queryKey?.[2], analysisParams) ? previous : undefined
    ),
    staleTime: 30_000,
  })
  const analysis = analysisQuery.data || { query: {}, quality: {}, timeline: [], movement_ranking: [], class_summary: { business: [], yolo: [] }, slice_tracks: [], conflicts: [] }
  const timeline = analysis.timeline || []
  useEffect(() => {
    if (!analysis.query?.start_at) return
    if (!analysisWindow) setAnalysisWindow({ start: analysis.query.start_at, end: analysis.query.end_at })
    if (!sliceWindow) setSliceWindow({ start: analysis.query.slice_start_at, end: analysis.query.slice_end_at })
  }, [analysis.query?.start_at, analysis.query?.end_at, analysis.query?.slice_start_at, analysis.query?.slice_end_at, analysisWindow, sliceWindow])

  const currentSliceIndex = Math.max(0, timeline.findIndex((item) => item.start_at === (sliceWindow?.start || analysis.query?.slice_start_at)))
  const displayedSliceIndex = Math.max(0, timeline.findIndex((item) => item.start_at === analysis.query?.slice_start_at))
  const selectSlice = (index) => {
    const bucket = timeline[index]
    if (bucket) {
      setSliceInteractive(true)
      setSliceWindow({ start: bucket.start_at, end: bucket.end_at })
    }
  }
  useEffect(() => {
    if (!playing || analysisQuery.isFetching || timeline.length < 2) return undefined
    const nextIndex = nextPlayableSliceIndex(timeline, displayedSliceIndex)
    const nextBucket = timeline[nextIndex]
    if (!nextBucket || !selected?.id || !analysisWindow) return undefined
    const nextParams = {
      ...analysisParams,
      start_at: analysisWindow.start,
      end_at: analysisWindow.end,
      slice_start_at: nextBucket.start_at,
      slice_end_at: nextBucket.end_at,
    }
    queryClient.prefetchQuery({
      queryKey: ['trajectory-analysis', selected.id, nextParams],
      queryFn: () => platformApi.trajectoryAnalysis(selected.id, nextParams),
      staleTime: 30_000,
    })
    return undefined
  }, [analysisQuery.isFetching, analysisWindow, displayedSliceIndex, playing, queryClient, selected?.id, timeline])

  useEffect(() => {
    if (!playing || analysisQuery.isFetching || timeline.length < 2) return undefined
    if (analysis.query?.slice_start_at !== sliceWindow?.start) return undefined
    const timer = window.setTimeout(() => {
      const current = timeline.findIndex((item) => item.start_at === sliceWindow?.start)
      const next = nextPlayableSliceIndex(timeline, current)
      if (next < 0) {
        setPlaying(false)
        return
      }
      setSliceInteractive(true)
      setSliceWindow({ start: timeline[next].start_at, end: timeline[next].end_at })
    }, 1400 / playbackSpeed)
    return () => window.clearTimeout(timer)
  }, [analysis.query?.slice_start_at, analysisQuery.isFetching, playbackSpeed, playing, timeline, sliceWindow?.start])

  const tracks = analysis.slice_tracks || []
  const conflicts = analysis.conflicts || []
  const selectedTrack = tracks.find((item) => item.id === selectedTrackId) || tracks[0] || null
  useEffect(() => {
    if (selectedTrack && selectedTrack.id !== selectedTrackId) setSelectedTrackId(selectedTrack.id)
  }, [selectedTrack, selectedTrackId])
  const movementColor = new Map((analysis.movement_ranking || []).map((item, index) => [item.movement_key, index % MOVEMENT_COLORS.length]))
  const sortedMovements = useMemo(() => {
    const movements = analysis.movement_ranking || []
    if (movementSort === 'business') return movements
    const originalIndex = new Map(movements.map((item, index) => [item.movement_key, index]))
    const field = movementSort === 'vehicle_count' ? 'vehicle_count' : movementSort === 'avg_speed' ? 'avg_speed_kmh' : 'conflict_count'
    return [...movements].sort((left, right) => {
      const leftValue = Number(left[field])
      const rightValue = Number(right[field])
      const leftValid = Number.isFinite(leftValue)
      const rightValid = Number.isFinite(rightValue)
      if (leftValid !== rightValid) return leftValid ? -1 : 1
      if (leftValid && rightValid && leftValue !== rightValue) return rightValue - leftValue
      return originalIndex.get(left.movement_key) - originalIndex.get(right.movement_key)
    })
  }, [analysis.movement_ranking, movementSort])
  const mapTracks = tracks.map((track) => ({ ...track, color_index: movementColor.get(track.movement_key) || 0, selected: track.id === selectedTrack?.id }))
  const availableMissions = (missionsQuery.data || []).filter((item) => !selected?.id || item.inter_id === selected.id)
  const selectIntersection = (item) => {
    if (!item) return
    setSelectedId(item.id)
  }
  const selectPeriod = (value) => {
    setPeriod(value)
  }
  const toggleMovement = (movementKey) => {
    setSelectedMovement((value) => value === movementKey ? null : movementKey)
    setSelectedTrackId(null)
    setSliceWindow(null)
    setSliceInteractive(false)
    setPlaying(false)
  }
  const togglePlayback = () => {
    if (playing) {
      setPlaying(false)
      return
    }
    if (timeline.length > 1 && nextPlayableSliceIndex(timeline, currentSliceIndex) < 0) {
      selectSlice(firstPlayableSliceIndex(timeline))
    }
    setPlaying(true)
  }
  const intersectionResult = intersectionsQuery.isLoading ? '路口加载中' : intersectionsQuery.error ? '路口加载失败' : `${projectIntersections.length} 个路口`
  const trajectoryResult = intersectionsQuery.isLoading ? '轨迹等待路口' : analysisQuery.isLoading ? '轨迹分析中' : analysisQuery.error ? '轨迹分析失败' : `${analysis.quality?.total_tracks || 0} 条轨迹`
  const periodLabel = period === 'latest30m' ? '最新数据段 30 分钟' : period === 'all' ? '全部验收数据' : period === '24h' ? '最近 24 小时' : '最近 1 小时'
  const loading = intersectionsQuery.isLoading || analysisQuery.isLoading
  const error = intersectionsQuery.error || analysisQuery.error
  const quality = analysis.quality || {}

  return <AppShell pageTitle='轨迹研判'>
    <PageHeader eyebrow='交通运行诊断' title='历史轨迹分析' description='先看时间片，再按流向和原始识别分类下钻；地图只展示当前切片，避免全量轨迹叠加造成误判。' meta={`${periodLabel} · ${trajectoryResult}`} />
    <FilterBar result={`${intersectionResult} · ${trajectoryResult}`} onReset={() => { setMissionId('all'); setSourceProfileId('all'); setVehicleClass('all'); setYoloClassId('all'); setTurnBehavior('all'); setSelectedMovement(null); setSelectedTrackId(null); setMovementSort('business') }}>
      <label>路口<select aria-label='路口' value={selected?.id || ''} onChange={(event) => selectIntersection(projectIntersections.find((item) => item.id === event.target.value))}>{projectIntersections.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>任务<select aria-label='轨迹任务' value={missionId} onChange={(event) => setMissionId(event.target.value)}><option value='all'>全部任务</option>{availableMissions.map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}</select></label>
      <label>数据源<select aria-label='轨迹数据源' value={sourceProfileId} onChange={(event) => setSourceProfileId(event.target.value)}><option value='all'>全部数据源</option>{(sourcesQuery.data || []).map((item) => <option key={item.profile_id} value={item.profile_id}>{item.display_name || item.profile_id}</option>)}</select></label>
      <label>业务车型<select aria-label='车辆类型' value={vehicleClass} onChange={(event) => setVehicleClass(event.target.value)}><option value='all'>全部车型</option><option value='motor'>机动车</option><option value='non_motor'>非机动车</option><option value='unknown'>未分类</option></select></label>
      <label>原始 YOLO<select aria-label='原始 YOLO 分类' value={yoloClassId} onChange={(event) => setYoloClassId(event.target.value)}><option value='all'>全部原始类别</option>{(analysis.class_summary?.yolo || []).map((item) => <option key={`${item.class_id}-${item.class_name}`} value={String(item.class_id)}>#{item.class_id} {item.class_name || 'unknown'}</option>)}</select></label>
      <label>方向<select aria-label='转向类型' value={turnBehavior} onChange={(event) => setTurnBehavior(event.target.value)}><option value='all'>全部方向</option><option value='straight'>直行</option><option value='left_turn'>左转</option><option value='right_turn'>右转</option><option value='u_turn'>掉头</option></select></label>
      <label>时间窗口<select aria-label='时间窗口' value={period} onChange={(event) => selectPeriod(event.target.value)}><option value='latest30m'>最新数据段 30 分钟</option><option value='all'>全部验收数据</option><option value='1h'>当前时间最近 1 小时</option><option value='24h'>当前时间最近 24 小时</option></select></label>
    </FilterBar>
    {loading && !analysisQuery.data && <QualityNotice tone='info' title='正在建立研判窗口'>{intersectionsQuery.isLoading ? '正在读取项目路口。' : '正在聚合轨迹、流向与冲突事实。'}</QualityNotice>}
    {error && <QualityNotice tone='warning' title='历史轨迹分析不可用'>{apiErrorMessage(error)} <button className='secondary-button' onClick={() => { intersectionsQuery.refetch(); analysisQuery.refetch() }}>重新加载</button></QualityNotice>}
    {!loading && !error && !selected && <QualityNotice tone='info' title='暂无路口'>尚未登记项目路口。</QualityNotice>}
    {selected && <div className='trajectory-analysis-page'>
      <div className='trajectory-analysis-kpis'>
        <div><span>分析轨迹</span><strong>{quality.total_tracks || 0}</strong><small>全窗口事实，不受地图上限影响</small></div>
        <div><span>可回放轨迹</span><strong>{quality.replayable_tracks || 0}</strong><small>空间覆盖 {Math.round((quality.spatial_coverage_ratio || 0) * 100)}%</small></div>
        <div><span>识别流向</span><strong>{analysis.movement_ranking?.length || 0}</strong><small>{selectedMovement ? '已聚焦 1 个流向' : '点击排名可聚焦'}</small></div>
        <div><span>当前切片冲突</span><strong>{conflicts.length}</strong><small>未归因 {quality.unattributed_conflicts || 0} 条</small></div>
      </div>
      <div className='trajectory-quality-notices'>
        {!loading && !error && quality.total_tracks === 0 && <QualityNotice tone='info' title='当前范围无完成轨迹'>请扩大时间窗口或清除车型、任务与数据源筛选。 <button className='secondary-button' onClick={() => { setPeriod('all'); setMissionId('all'); setSourceProfileId('all'); setVehicleClass('all'); setYoloClassId('all'); setTurnBehavior('all') }}>清除并查看全部</button></QualityNotice>}
        {quality.truncated && <QualityNotice tone='warning' title='当前时间片已限量'>仅展示 {quality.returned_tracks || 0} 条可回放轨迹；请选择流向或原始类别缩小范围。 <button className='secondary-button' onClick={() => setAnalysisTab('track')}>查看当前片轨迹</button></QualityNotice>}
        {(quality.spatial_coverage_ratio ?? 1) < 1 && <QualityNotice tone='warning' title='空间覆盖不足'>{quality.total_tracks - quality.replayable_tracks} 条轨迹缺少可投放的世界坐标。 <button className='secondary-button' onClick={() => setAnalysisTab('track')}>查看可回放轨迹</button></QualityNotice>}
        {(analysis.movement_ranking || []).some((item) => item.movement_source !== 'road_context') && <QualityNotice tone='info' title='部分流向使用降级证据'>“轨迹方位推断”与“仅按转向降级”均不是权威路网匹配。 <button className='secondary-button' onClick={() => setAnalysisTab('movement')}>查看来源标记</button></QualityNotice>}
        {(quality.unattributed_conflicts || 0) > 0 && <QualityNotice tone='warning' title='存在未归因冲突'>{quality.unattributed_conflicts} 条冲突因缺少同一任务或管道血缘，未计入流向排名。 <button className='secondary-button' onClick={() => navigate('/events')}>查看事件中心</button></QualityNotice>}
        {(quality.duplicate_tracks_omitted || 0) > 0 && <QualityNotice tone='info' title='重复完成轨迹已去重'>{quality.duplicate_tracks_omitted} 条同血缘重复记录未进入排名和占比。</QualityNotice>}
      </div>
      {(!Number.isFinite(selected.lat) || !Number.isFinite(selected.lon)) && <QualityNotice tone='warning' title='坐标尚未冻结'>缺少可信 GCJ-02 坐标时不投放地图。</QualityNotice>}
      <div className='trajectory-analysis-workspace'>
        <section className='trajectory-map-card'>
          <header><div><strong>{selected.name}</strong><span>当前时间片 · {analysisTime(analysis.query?.slice_start_at || sliceWindow?.start)}—{analysisTime(analysis.query?.slice_end_at || sliceWindow?.end)}</span></div><div className={`analysis-quality ${quality.status || 'empty'}`}>{quality.status === 'complete' ? '数据完整' : quality.status === 'degraded' ? '部分可回放' : '暂无数据'}</div></header>
          <div className='trajectory-map-stage'>
            <MonitoringBevMap centerLat={selected.lat} centerLon={selected.lon} trajectories={mapTracks} embedded showEndpoints={false} label={`${selected.name}当前时间片真实轨迹投放图`} />
            <div className='movement-legend'>{sortedMovements.slice(0, 5).map((item) => <span key={item.movement_key}><i style={{ background: MOVEMENT_COLORS[movementColor.get(item.movement_key) || 0] }} />{item.movement_label}</span>)}</div>
            {tracks.length === 0 && <div className='map-empty-state'><Crosshair size={24} /><strong>当前时间片无可回放轨迹</strong><span>拖动下方时间轴查看其他片段</span></div>}
          </div>
          <div className='analysis-timeline'>
            <div className='timeline-actions'><button className='timeline-play' aria-label={playing ? '暂停历史回放' : '播放历史回放'} onClick={togglePlayback}>{playing ? <Pause size={14} weight='fill' /> : <Play size={14} weight='fill' />}</button><select aria-label='回放速度' value={String(playbackSpeed)} onChange={(event) => setPlaybackSpeed(Number(event.target.value))}><option value='0.5'>0.5×</option><option value='1'>1×</option><option value='2'>2×</option><option value='4'>4×</option></select></div>
            <div className='timeline-window'><strong>{analysisTime(analysis.query?.start_at, true)}</strong><span>—</span><strong>{analysisTime(analysis.query?.end_at, true)}</strong><small>{analysis.query?.bucket_sec || 10}s / 片</small></div>
            <div className='timeline-control'><div className='timeline-bars'>{timeline.map((item, index) => <i key={item.start_at} className={index === currentSliceIndex ? 'active' : ''} style={{ height: item.active_tracks > 0 ? `${Math.max(12, Math.min(100, item.active_tracks * 6))}%` : '0%' }} />)}</div><input aria-label='历史时间片' type='range' min='0' max={Math.max(0, timeline.length - 1)} value={Math.min(currentSliceIndex, Math.max(0, timeline.length - 1))} onChange={(event) => selectSlice(Number(event.target.value))} /></div>
            <div className='timeline-now' aria-live='polite'><strong>{analysisTime(analysis.query?.slice_start_at || sliceWindow?.start)}</strong><span>{tracks.length} 条轨迹 · {conflicts.length} 个冲突</span>{analysisQuery.isPlaceholderData && <small>加载下一片…</small>}</div>
          </div>
        </section>
        <aside className='trajectory-analysis-sidebar'>
          <div className='analysis-tabs' role='tablist' aria-label='轨迹研判维度'><button role='tab' aria-selected={analysisTab === 'movement'} className={analysisTab === 'movement' ? 'active' : ''} onClick={() => setAnalysisTab('movement')}>流向排名</button><button role='tab' aria-selected={analysisTab === 'class'} className={analysisTab === 'class' ? 'active' : ''} onClick={() => setAnalysisTab('class')}>原始分类</button><button role='tab' aria-selected={analysisTab === 'track'} className={analysisTab === 'track' ? 'active' : ''} onClick={() => setAnalysisTab('track')}>代表轨迹</button></div>
          {analysisTab === 'movement' && <div className='movement-ranking' role='tabpanel'><div className='analysis-sidebar-intro'><strong>流向排名</strong><span>有效流向优先；可切换车辆数、均速和冲突排序，当前筛选保持不变。</span></div><div className='movement-sort' role='group' aria-label='流向排序'><button aria-label='按业务优先级排序' aria-pressed={movementSort === 'business'} onClick={() => setMovementSort('business')}>业务优先</button><button aria-label='按车辆数排序' aria-pressed={movementSort === 'vehicle_count'} onClick={() => setMovementSort('vehicle_count')}>车辆数</button><button aria-label='按均速排序' aria-pressed={movementSort === 'avg_speed'} onClick={() => setMovementSort('avg_speed')}>均速</button><button aria-label='按冲突排序' aria-pressed={movementSort === 'conflict'} onClick={() => setMovementSort('conflict')}>冲突</button></div>{sortedMovements.map((item, index) => <button key={item.movement_key} className={selectedMovement === item.movement_key ? 'selected' : ''} aria-label={`${item.movement_label} ${item.vehicle_count} 辆`} onClick={() => toggleMovement(item.movement_key)}><b>{index + 1}</b><i style={{ background: MOVEMENT_COLORS[movementColor.get(item.movement_key) || 0] }} /><div><strong>{item.movement_label}</strong><span>{MOVEMENT_SOURCE_LABELS[item.movement_source] || item.movement_source} · {item.avg_speed_kmh ?? '—'} km/h · P85 {item.p85_speed_kmh ?? '—'}</span></div><em>{item.vehicle_count}<small>辆</small></em><mark className={item.conflict_count ? 'risk' : ''}>{item.conflict_count} 冲突</mark></button>)}</div>}
          {analysisTab === 'class' && <div className='class-analysis'><div className='analysis-sidebar-intro'><strong>原始目标分类</strong><span>保留 YOLO 输出并与业务车型并列，便于发现映射偏差。</span></div><h4>业务分类</h4>{(analysis.class_summary?.business || []).map((item) => <div className='class-row' key={item.class_name}><span>{BUSINESS_CLASS_LABELS[item.class_name] || item.class_name}</span><strong>{item.count}</strong></div>)}<h4>检测器原始分类</h4>{(analysis.class_summary?.yolo || []).map((item) => <button className='class-row raw' key={`${item.class_id}-${item.class_name}`} onClick={() => setYoloClassId(String(item.class_id))}><span><b>YOLO {item.class_name || 'unknown'}</b><small>class #{item.class_id ?? '—'}</small></span><strong>{item.count}</strong><em>{item.model_id || '模型版本缺失'}</em></button>)}{analysis.class_summary?.unknown_yolo_name_count > 0 && <QualityNotice tone='warning' title='原始类名缺失'>{analysis.class_summary.unknown_yolo_name_count} 条轨迹仅有 class id。</QualityNotice>}</div>}
          {analysisTab === 'track' && <div className='representative-tracks'><div className='analysis-sidebar-intro'><strong>当前时间片轨迹</strong><span>点击后在地图高亮，并展示原始识别证据。</span></div>{tracks.slice(0, 20).map((track) => <button key={track.id} className={selectedTrack?.id === track.id ? 'selected' : ''} onClick={() => setSelectedTrackId(track.id)}><i style={{ background: MOVEMENT_COLORS[movementColor.get(track.movement_key) || 0] }} /><div><strong>Track #{track.track_id}</strong><span>{track.movement_label} · {track.avg_speed_kmh ?? '—'} km/h</span><small>{trackLineageLabel(track)}</small><small>YOLO {track.yolo_class_name || 'unknown'} #{track.yolo_class_id ?? '—'} → {BUSINESS_CLASS_LABELS[track.vehicle_class] || track.vehicle_class || 'unknown'}</small></div></button>)}</div>}
        </aside>
      </div>
      <div className='trajectory-evidence-grid'>
        <Panel title={selectedTrack ? `Track #${selectedTrack.track_id} 识别与运行证据` : '轨迹证据'} subtitle={selectedTrack?.movement_label}>{selectedTrack ? <><InfoRow label='业务车型 / 方向' value={`${BUSINESS_CLASS_LABELS[selectedTrack.vehicle_class] || selectedTrack.vehicle_class || 'unknown'} / ${selectedTrack.turn_behavior || '未分类'}`} /><InfoRow label='原始分类' value={`YOLO ${selectedTrack.yolo_class_name || 'unknown'} (#${selectedTrack.yolo_class_id ?? '—'})`} /><InfoRow label='模型 / 映射' value={`${selectedTrack.yolo_model_id || '—'} / ${selectedTrack.class_mapping_version || '—'}`} /><InfoRow label='平均 / 最高速度' value={`${selectedTrack.avg_speed_kmh ?? '—'} / ${selectedTrack.max_speed_kmh ?? '—'} km/h`} /><InfoRow label='任务 / 数据源' value={`${selectedTrack.mission_id || '—'} / ${selectedTrack.source_profile_id || '—'}`} /><InfoRow label='路网 / 质量' value={`${selectedTrack.road_data_version || '—'} / ${selectedTrack.quality_status || '—'}`} badge={selectedTrack.quality_status === 'verified' ? 'good' : 'degraded'} /></> : <span className='muted'>当前时间片没有轨迹。</span>}</Panel>
        <Panel title='当前时间片关联冲突' subtitle='只展示同一任务或管道血缘可归因事件'>{conflicts.length === 0 ? <span className='muted'>当前时间片无可归因冲突</span> : conflicts.map((item) => <button className='compact-event' key={item.id} onClick={() => navigate(`/events?event_id=${item.id}`)}><StatusBadge value={item.severity || 'warning'} /><div><strong>{item.conflict_scene || '冲突候选'}</strong><span>TTC {item.ttc_sec ?? '—'}s · {analysisTime(item.occurred_at)}</span></div></button>)}</Panel>
      </div>
    </div>}
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
  const { dispatch } = useAppState()
  const { platformRole } = useAuth()
  const queryClient = useQueryClient()
  const initialParams = new URLSearchParams(location.search)
  const initialId = initialParams.get('event_id')
  const [selected, setSelected] = useState(null)
  const [actionError, setActionError] = useState('')
  const [severity, setSeverity] = useState(['critical', 'warning'].includes(initialParams.get('severity')) ? initialParams.get('severity') : 'all')
  const [eventType, setEventType] = useState(initialParams.get('event_type') || 'all')
  const [intersection, setIntersection] = useState(initialParams.get('intersection_id') || 'all')
  const [query, setQuery] = useState('')
  const intersectionsQuery = useQuery({ queryKey: ['i3-project-intersections'], queryFn: loadProjectIntersections, refetchInterval: 30_000 })
  const projectIntersections = (intersectionsQuery.data || []).map(mapIntersection)
  const eventsQuery = useQuery({ queryKey: ['i3-events'], queryFn: () => platformApi.events({ limit: 500 }), refetchInterval: 30_000 })
  const events = useMemo(() => (eventsQuery.data || []).map(unifiedEvent), [eventsQuery.data])
  useEffect(() => {
    if (initialId && !selected) setSelected(events.find((item) => item.id === initialId) || null)
  }, [events, initialId, selected])
  const rows = useMemo(() => events.filter((item) =>
    (severity === 'all' || item.severity === severity) &&
    (eventType === 'all' || item.event_type === eventType) &&
    (intersection === 'all' || item.intersectionId === intersection) &&
    (!query.trim() || `${item.id} ${item.title}`.toLowerCase().includes(query.trim().toLowerCase()))
  ), [events, severity, eventType, intersection, query])
  const eventDetailQuery = useQuery({ queryKey: ['i3-event-detail', selected?.id], queryFn: () => platformApi.event(selected.id), enabled: Boolean(selected?.id) })
  const selectedEvent = eventDetailQuery.data ? unifiedEvent(eventDetailQuery.data) : selected ? events.find((item) => item.id === selected.id) || selected : null
  const reviewMutation = useMutation({
    mutationFn: ({ event, reviewStatus }) => platformApi.reviewEvent(event.id, { review_status: reviewStatus, expected_revision: event.review_revision, reason: 'Console2 technical review' }),
    onSuccess: (value) => {
      setActionError('')
      setSelected(unifiedEvent(value))
      queryClient.invalidateQueries({ queryKey: ['i3-events'] })
      queryClient.invalidateQueries({ queryKey: ['i3-event-detail', value.id] })
      dispatch({ type: 'TOAST', value: { tone: 'success', text: value.review_status === 'confirmed' ? 'AI 结果已技术确认' : 'AI 结果已驳回并记录原因' } })
    },
    onError: (error) => setActionError(apiErrorMessage(error, '技术复核失败')),
  })
  const openEvent = (item) => {
    setSelected(item)
    const params = new URLSearchParams(location.search)
    if (item) params.set('event_id', item.id)
    else params.delete('event_id')
    navigate(`${location.pathname}${params.size ? `?${params.toString()}` : ''}`, { replace: true })
  }
  const loading = intersectionsQuery.isLoading || eventsQuery.isLoading
  const loadError = intersectionsQuery.error || eventsQuery.error
  return <AppShell pageTitle='AI 事件中心'>
    <PageHeader eyebrow='S2 / S4 / S6' title='AI 事件中心' description='真实拥堵、质量下降、测绘成果与真实冲突统一查询；每类事件保留自己的指标与证据。' meta={`${events.length} 起真实事件 · ${events.filter((item) => item.review === 'pending').length} 起待复核`} />
    <FilterBar result={`显示 ${rows.length} / ${events.length} 起`} onReset={() => { setSeverity('all'); setEventType('all'); setIntersection('all'); setQuery('') }}><Segmented value={severity} onChange={setSeverity} options={[{ value: 'all', label: '全部' }, { value: 'critical', label: '高风险' }, { value: 'warning', label: '关注' }, { value: 'info', label: '成果' }]} /><label>事件类型<select aria-label='事件类型' value={eventType} onChange={(event) => setEventType(event.target.value)}><option value='all'>全部类型</option><option value='congestion'>持续拥堵</option><option value='quality_degradation'>质量下降</option><option value='survey_result'>测绘成果</option><option value='conflict'>真实冲突</option></select></label><label>路口<select aria-label='事件路口' value={intersection} onChange={(event) => setIntersection(event.target.value)}><option value='all'>全部项目路口</option>{projectIntersections.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className='search-field'><Funnel size={15} /><input aria-label='事件搜索' value={query} onChange={(event) => setQuery(event.target.value)} placeholder='事件 ID / 标题' /></label></FilterBar>
    {loading && <QualityNotice tone='info' title='正在恢复事件台账'>从 road9 加载冲突事实与告警。</QualityNotice>}
    {loadError && <QualityNotice tone='warning' title='事件台账不可用'>{apiErrorMessage(loadError)}</QualityNotice>}
    {!loading && !loadError && <Panel title='AI 事件事实' subtitle='业务时间排序 · REST 为页面刷新后的恢复基线'><DataTable columns={eventColumns(openEvent)} rows={rows} onRowClick={openEvent} /></Panel>}
    {selectedEvent && <DetailDrawer wide title={selectedEvent.title} subtitle={`${selectedEvent.type} · ${selectedEvent.id}`} onClose={() => openEvent(null)} footer={platformRole === 'admin' ? <><button className='danger-button' disabled={reviewMutation.isPending} onClick={() => reviewMutation.mutate({ event: selectedEvent, reviewStatus: 'rejected' })}><X size={15} /> 驳回 AI 结果</button><button className='primary-button' disabled={reviewMutation.isPending} onClick={() => reviewMutation.mutate({ event: selectedEvent, reviewStatus: 'confirmed' })}><Check size={15} /> 技术确认</button></> : <span className='muted'>仅管理员可执行技术复核</span>}>
      <div className='event-hero'><div className='event-primary-metrics'>{eventMetricTiles(selectedEvent).map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div></div>
      {actionError && <QualityNotice tone='warning' title='技术复核失败'>{actionError}</QualityNotice>}
      {selectedEvent.evidence_refs?.length > 0 && <Panel title='事件画面证据' subtitle={`同一事件时刻 · ${selectedEvent.evidence_refs.length} 项内容寻址证据`}><EventEvidenceGallery references={selectedEvent.evidence_refs} /></Panel>}
      <div className='detail-two-col'><Panel title='事件与质量'><InfoRow label='业务时间' value={selectedEvent.occurredAt} /><InfoRow label='路口' value={projectIntersections.find((item) => item.id === selectedEvent.intersectionId)?.name || selectedEvent.intersectionId || '未匹配'} /><InfoRow label='任务 / Pipeline' value={`${selectedEvent.mission_id || '—'} / ${selectedEvent.pipeline_id || '—'}`} /><InfoRow label='数据源' value={selectedEvent.source_profile_id || '—'} /><InfoRow label='路网版本' value={selectedEvent.road_data_version || '—'} /><InfoRow label='质量' value={selectedEvent.quality} badge={selectedEvent.quality === 'verified' ? 'good' : 'degraded'} /></Panel><Panel title='投递与复核'><InfoRow label='投递状态' value={selectedEvent.delivery} badge={selectedEvent.delivery === 'blocked' ? 'blocked' : 'degraded'} /><InfoRow label='事实来源' value={selectedEvent.isConflict ? 'uav_conflict_events' : 'uav_ai_events'} /><InfoRow label='复核 revision' value={selectedEvent.review_revision || '—'} /><InfoRow label='技术复核' value={selectedEvent.review} badge={selectedEvent.review} /></Panel></div>
      {selectedEvent.related_tracks?.length > 0 && <Panel title='关联轨迹' subtitle={`同任务/事件窗口 ${selectedEvent.related_tracks.length} 条`}><div className='related-track-list'>{selectedEvent.related_tracks.slice(0, 8).map((track) => <button key={track.id} className='compact-event' onClick={() => navigate(`/gis?intersection_id=${selectedEvent.intersectionId}&mission_id=${track.mission_id || ''}&track_id=${track.id}`)}><StatusBadge value={track.quality_status || 'unverified'} /><div><strong>Track #{track.track_id}</strong><span>{track.vehicle_class || 'unknown'} · {track.turn_behavior || '未分类'} · {track.duration_sec ?? '—'}s</span></div></button>)}</div></Panel>}
      <Panel title='事实状态时间线'><div className='state-timeline'>{[`事实入库 ${selectedEvent.occurredAt}`, selectedEvent.delivery === 'not_queued' ? '主平台投递未启用' : `投递：${selectedEvent.delivery}`, selectedEvent.review === 'pending' ? '等待技术复核' : `技术复核：${selectedEvent.review}`].map((item, index) => <div key={item} className={index === 2 ? 'current' : ''}><i /><span>{item}</span></div>)}</div></Panel>
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
