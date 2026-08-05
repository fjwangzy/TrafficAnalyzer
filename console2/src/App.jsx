import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import { ConsoleFrame } from './components/AppShell'
import { apiErrorMessage, platformApi } from './lib/api'
import { alertChannels, intersectionChannels, telemetryChannels } from './lib/realtime'
import { detectorVideoStreamSrc } from './lib/videoStream'
import { useWebSocket } from './hooks/useWebSocket'
import { MonitoringBevMap } from './components/MonitoringBevMap'
import { useAuth } from './auth/AuthContext'
import { useAppState } from './state/AppState'
import { demoMonitoring, demoSituation } from './config/demoData'
import { buildDemoAnalysisSnapshot, upsertDemoSnapshot } from './lib/demoSnapshots'
import {
  ArrowsClockwise, CaretDown, CaretLeft, CaretRight, Crosshair, Drone, Gauge, ListBullets,
  Pause, Play, Plus, PushPin, PushPinSlash, RoadHorizon,
  ShieldWarning, Stack, Target, TrendUp, Truck, VideoCamera, Warning,
} from '@phosphor-icons/react'
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'

const asNumber = (value) => {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}
const displayNumber = (value, digits = 0) => value == null ? '—' : Number(value).toFixed(digits)
const eventTime = (value) => {
  const date = value ? new Date(value) : new Date()
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleTimeString('zh-CN', { hour12: false })
}
const eventTone = (severity) => severity === 'critical' || severity === 'P1' ? 'critical' : severity === 'warning' || severity === 'P2' ? 'warning' : 'info'
const LIVE_BEV_TRAJECTORY_MIN_COUNT = 150
const LIVE_BEV_TRAJECTORY_WINDOW_MS = 5 * 60 * 1000
const BEV_RECEIVED_AT_FIELD = '__console_received_at_ms'

const latestItems = (items, limit) => limit > 0 ? items.slice(-limit) : []
const projectableTrajectories = (items) => items.filter(
  (item) => Array.isArray(item?.trajectory_gcj02) && item.trajectory_gcj02.filter(
    (point) => Array.isArray(point) && point.length >= 2,
  ).length >= 2,
)
const splitRecentTrajectories = (items, now) => {
  const cutoff = now - LIVE_BEV_TRAJECTORY_WINDOW_MS
  return items.reduce((groups, item) => {
    groups[Number(item?.[BEV_RECEIVED_AT_FIELD]) >= cutoff ? 1 : 0].push(item)
    return groups
  }, [[], []])
}
const retainCompletedTrajectories = (items, now) => {
  const [older, recent] = splitRecentTrajectories(items, now)
  return [...latestItems(older, LIVE_BEV_TRAJECTORY_MIN_COUNT - recent.length), ...recent]
}

const FLIGHT_PHASE_LABELS = {
  hover_candidate: '悬停确认中',
  hover_verified: '悬停正拍',
  cruise_nadir: '近正射巡航',
  transition: '模式过渡',
  unsupported_pose: '姿态不支持',
  telemetry_unavailable: '遥测不可用',
}
const QUALITY_LABELS = {
  verified: '可信',
  bootstrap: '建立基线',
  degraded: '降级',
  unavailable: '不可用',
  unverified: '未验证',
}
const QUALITY_REASON_LABELS = {
  telemetry_gap: '遥测短缺或超出同步窗口',
  telemetry_unavailable: '遥测不可用',
  telemetry_inconsistent: '报告速度与派生速度不一致',
  target_outside_map_coverage: '目标已离开发布地图覆盖范围',
  map_coverage_not_verified: '地图覆盖未通过验证',
  registration_pose_lineage_required: '配准帧缺少位姿/相机谱系',
  visual_warp_not_verified: '视觉变换未通过质量门禁',
  flight_pose_not_eligible: '飞行姿态超出正式包线',
  flight_phase_not_verified: '飞行阶段尚未稳定确认',
  lane_verified_map_required: '缺少 lane_verified 运行时地图',
  pixel_to_map_projection_unavailable: '逐帧像素到地图投影不可用',
  formal_analytics_disabled: '正式研判未启用',
}

export function monitoringQualitySummary(stats) {
  const geo = stats?.geo_reference_quality || {}
  const tracking = stats?.tracking_diagnostics || {}
  const formal = stats?.formal_analytics_eligible
  const trajectoryOutput = stats?.trajectory_output_eligible
  const roadAnalytics = stats?.road_analytics_eligible ?? formal
  const reasons = [...new Set([
    ...(Array.isArray(geo.reasons) ? geo.reasons : []),
    ...(Array.isArray(tracking.quality_reasons) ? tracking.quality_reasons : []),
  ])]
  return {
    phase: stats?.flight_phase || geo.flight_phase || 'telemetry_unavailable',
    phaseLabel: FLIGHT_PHASE_LABELS[stats?.flight_phase || geo.flight_phase] || '等待飞行状态',
    formal,
    trajectoryOutput,
    roadAnalytics,
    geoAnalytics: stats?.geo_analytics_eligible,
    tccAnalytics: stats?.tcc_analytics_eligible,
    formalLabel: roadAnalytics === true ? '道路研判开启' : roadAnalytics === false ? '路网能力降级' : '道路研判待定',
    tone: roadAnalytics === true ? 'verified' : roadAnalytics === false ? 'degraded' : 'unavailable',
    reasonLabels: reasons.map((reason) => QUALITY_REASON_LABELS[reason] || reason),
    qualities: [
      ['地理参考', geo.status],
      ['遥测', geo.telemetry?.status],
      ['视觉变换', geo.visual_warp?.status],
      ['地图覆盖', geo.map_coverage?.status],
      ['目标跟踪', tracking.tracking_quality],
    ].map(([label, status]) => ({ label, status: status || 'unavailable', value: QUALITY_LABELS[status] || status || '不可用' })),
    method: tracking.tracking_method || '—',
    terminationReason: tracking.termination_reason || '—',
  }
}

function normalizeAlert(alert) {
  const rawType = alert.alert_type || alert.event_type || 'risk'
  return {
    id: alert.id,
    level: eventTone(alert.severity),
    type: rawType.includes('conflict') ? 'conflict' : rawType.includes('lane') ? 'lane' : rawType.includes('congestion') ? 'congestion' : 'enforcement',
    title: alert.title || 'AI 风险事件',
    detail: alert.description || '等待技术复核',
    metric: alert.ttc_sec != null ? `TTC ${alert.ttc_sec}s · PET ${alert.pet_sec ?? '—'}s` : alert.status || '待复核',
    time: eventTime(alert.timestamp || alert.occurred_at),
    raw: alert,
  }
}

export function isBusinessTccConflict(data) {
  const distance = asNumber(data?.distance_m)
  return distance != null && Math.abs(distance) <= 0.01 && (data?.prediction_type == null || data.prediction_type === 'path_intersection')
}

export function realtimeMessageMatchesPipeline(message, pipelineId) {
  if (!['uav_stats', 'uav_track_complete', 'uav_conflict'].includes(message?.type)) return true
  const messagePipelineId = message?.data?.pipeline_id || message?.data?.run_id
  return Boolean(pipelineId && messagePipelineId === pipelineId)
}

function normalizeConflict(data, occurredAt, realtime = true) {
  return {
    id: data.message_id || data.source_message_id || data.id || `conflict-${data.motor_id}-${data.non_motor_id}-${occurredAt || Date.now()}`,
    level: eventTone(data.severity),
    type: 'conflict',
    title: data.title || '机非冲突风险升高',
    detail: data.description || `轨迹 ${data.motor_id ?? '—'} 与 ${data.non_motor_id ?? '—'} 预测交汇`,
    metric: `TTC ${data.ttc_sec ?? '—'}s · PET ${data.pet_sec ?? '—'}s`,
    time: eventTime(occurredAt || data.occurred_at || data.timestamp),
    raw: data,
    realtime,
  }
}

export function tccStatusText(diagnostics, streamActive) {
  if (!streamActive) return 'TCC 未运行：当前视频源无检测管道'
  if (!diagnostics) return 'TCC 状态等待统计'
  if (!diagnostics.enabled) return 'TCC 检测已停用'
  if (diagnostics.status === 'quality_gate_blocked') return 'TCC 已关闭：正式质量门禁未通过'
  if (!diagnostics.calibration_valid || diagnostics.status === 'missing_calibration') return 'TCC 无法检测：缺少有效标定'
  if ((diagnostics.business_events_emitted ?? diagnostics.events_emitted ?? 0) > 0) return `TCC 已产生 ${diagnostics.business_events_emitted ?? diagnostics.events_emitted} 条事件`
  if (diagnostics.status === 'deduplicated') return `TCC 已启用：候选事件已去重 ${diagnostics.deduplicated ?? 0} 条`
  if (!(diagnostics.eligible_motor_tracks > 0) || !(diagnostics.eligible_non_motor_tracks > 0)) return 'TCC 已启用：无合格机非候选'
  if (!(diagnostics.prediction_candidates > 0)) return 'TCC 已启用：无合格预测候选'
  if (!(diagnostics.evidence_passed > 0)) return 'TCC 已启用：候选未通过风险证据门禁'
  return 'TCC 已启用：本帧未产生事件'
}

function MetricCard({ label, value, unit, delta, icon: Icon, tone = 'blue' }) {
  return <article className='metric-card'><div className={`metric-icon ${tone}`}><Icon size={17} weight='fill' /></div><div><div className='metric-label'>{label}</div><div className='metric-value'>{value}<small>{unit}</small></div></div><span className={`metric-delta ${delta?.startsWith('+') ? 'up' : ''}`}>{delta}</span></article>
}

function EventIcon({ type }) {
  const icons = { conflict: ShieldWarning, lane: ArrowsClockwise, congestion: RoadHorizon, enforcement: Truck }
  const Icon = icons[type] || Warning
  return <Icon size={18} weight='fill' />
}

export function buildMonitoringSourceOptions({ sources = [], drones = [], intersections = [], pipelines = [] }) {
  const droneById = new Map(drones.map((item) => [item.id, item]))
  const intersectionById = new Map(intersections.map((item) => [item.id, item]))
  return sources.map((source) => {
    const drone = droneById.get(source.drone_id)
    const runningPipeline = pipelines.find((item) => item.status === 'running' && item.source_profile_id === source.profile_id)
    const intersectionId = runningPipeline?.intersection_id || drone?.default_inter_id || drone?.current_intersection_id || ''
    const intersection = intersectionById.get(intersectionId)
    const displayName = source.display_name || source.video?.location_hint || source.profile_id
    const droneName = drone?.name || source.drone_id
    return {
      ...source,
      runningPipeline,
      drone,
      droneName,
      intersectionId,
      intersectionName: drone?.intersection_name || intersection?.name || intersectionId || '未绑定路口',
      isDefault: Boolean(drone?.default_video_source_id && drone.default_video_source_id === source.video?.id),
      optionLabel: `${displayName} · ${droneName}`,
    }
  })
}

export function selectMonitoringSource(options, sourceProfileId, intersectionId) {
  const requestedSource = options.find((item) => item.profile_id === sourceProfileId)
  const runningSource = options.find((item) => item.runningPipeline?.intersection_id === intersectionId)
  return (requestedSource?.runningPipeline ? requestedSource : runningSource)
    || requestedSource
    || options.find((item) => item.intersectionId === intersectionId && item.isDefault)
    || options.find((item) => item.intersectionId === intersectionId)
    || options.find((item) => item.enabled !== false && item.intersectionId)
    || options[0]
    || null
}

export function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const { platformRole } = useAuth()
  const { dispatch } = useAppState()
  const params = new URLSearchParams(location.search)
  const intersectionId = params.get('intersection_id')
  const sourceProfileId = params.get('source_profile_id')
  const requestedView = params.get('view')
  const primaryView = requestedView === 'bev' || requestedView === 'raw' ? requestedView : 'detector'
  const [mapMode, setMapMode] = useState('trajectory')
  const [eventFilter, setEventFilter] = useState('all')
  const [selectedEvent, setSelectedEvent] = useState(null)
  const [live, setLive] = useState(true)
  const [droneOpen, setDroneOpen] = useState(false)
  const [layerOpen, setLayerOpen] = useState(false)
  const [leftPanelOpen, setLeftPanelOpen] = useState(true)
  const [leftPanelPinned, setLeftPanelPinned] = useState(true)
  const [rightPanelOpen, setRightPanelOpen] = useState(true)
  const [rightPanelPinned, setRightPanelPinned] = useState(true)
  const [timelineOpen, setTimelineOpen] = useState(false)
  const [historicalStats, setHistoricalStats] = useState(null)
  const [realtimeStats, setRealtimeStats] = useState(null)
  const [telemetry, setTelemetry] = useState(null)
  const [activeTrajectories, setActiveTrajectories] = useState([])
  const [completedTrajectories, setCompletedTrajectories] = useState([])
  const [realtimeConflicts, setRealtimeConflicts] = useState([])
  const [visibleHistoryConflicts, setVisibleHistoryConflicts] = useState([])
  const [visibleTrendRows, setVisibleTrendRows] = useState([])
  const [lastStatsAt, setLastStatsAt] = useState(0)
  const [lastTelemetryAt, setLastTelemetryAt] = useState(0)
  const [now, setNow] = useState(Date.now())
  const [videoError, setVideoError] = useState(false)
  const [videoRetry, setVideoRetry] = useState(0)
  const [videoNonce, setVideoNonce] = useState(0)
  const [quickStartFrameStride, setQuickStartFrameStride] = useState(3)
  const [missionMode, setMissionMode] = useState(params.get('stage') === 'review' ? 'review' : 'hover')
  const [savedSnapshotId, setSavedSnapshotId] = useState('')
  const statsFingerprint = useRef('')
  const telemetryFingerprint = useRef('')
  const liveRef = useRef(true)
  const videoRef = useRef(null)
  const pausedBuffer = useRef({ trendRows: null, telemetry: null, conflicts: null, realtime: [] })
  const latestStats = useMemo(() => historicalStats || realtimeStats
    ? { ...(historicalStats || {}), ...(realtimeStats || {}) }
    : null, [historicalStats, realtimeStats])
  const displayStats = latestStats || demoMonitoring.stats

  const intersectionsQuery = useQuery({ queryKey: ['monitoring-intersections'], queryFn: platformApi.intersections })
  const sourcesQuery = useQuery({ queryKey: ['monitoring-sources'], queryFn: platformApi.sources })
  const dronesQuery = useQuery({ queryKey: ['monitoring-drones'], queryFn: platformApi.drones })
  const pipelinesQuery = useQuery({ queryKey: ['monitoring-pipelines'], queryFn: platformApi.pipelines, refetchInterval: 5_000 })
  const intersections = Array.isArray(intersectionsQuery.data) ? intersectionsQuery.data : []
  const sources = Array.isArray(sourcesQuery.data) ? sourcesQuery.data : []
  const drones = Array.isArray(dronesQuery.data) ? dronesQuery.data : []
  const pipelines = Array.isArray(pipelinesQuery.data) ? pipelinesQuery.data : []
  const monitoringSources = useMemo(
    () => buildMonitoringSourceOptions({ sources, drones, intersections, pipelines }),
    [sources, drones, intersections, pipelines],
  )
  const displayMonitoringSources = useMemo(
    () => monitoringSources.length ? monitoringSources : [demoMonitoring.source],
    [monitoringSources],
  )
  const selectedSource = useMemo(
    () => selectMonitoringSource(displayMonitoringSources, sourceProfileId, intersectionId),
    [displayMonitoringSources, sourceProfileId, intersectionId],
  )
  const selectedId = selectedSource?.intersectionId || intersectionId || intersections[0]?.id || demoMonitoring.source.intersectionId
  const selectedIntersection = intersections.find((item) => item.id === selectedId) || (selectedSource ? {
    id: selectedId,
    name: selectedSource.intersectionName,
    center_gcj02: selectedSource.drone?.last_telemetry?.position_gcj02 || demoMonitoring.telemetry.position_gcj02,
    current_drone_id: selectedSource.drone_id,
  } : null)
  const intersectionQuery = useQuery({ queryKey: ['monitoring-intersection', selectedId], queryFn: () => platformApi.intersection(selectedId), enabled: Boolean(selectedId) })
  const trendQuery = useQuery({ queryKey: ['monitoring-trend', selectedId, selectedSource?.profile_id], queryFn: () => platformApi.intersectionStats(selectedId, '30m', '5m', selectedSource?.profile_id), enabled: Boolean(selectedId), refetchInterval: 30_000 })
  const conflictsQuery = useQuery({
    queryKey: ['monitoring-conflicts', selectedId, selectedSource?.profile_id],
    queryFn: () => platformApi.conflicts(selectedId, { period: '24h', limit: 20, source_profile_id: selectedSource.profile_id, prediction_type: 'path_intersection' }),
    enabled: Boolean(selectedId && selectedSource?.profile_id),
    refetchInterval: 10_000,
  })
  useEffect(() => {
    if (selectedSource && (sourceProfileId !== selectedSource.profile_id || intersectionId !== selectedId)) {
      const next = new URLSearchParams(location.search)
      next.set('intersection_id', selectedId)
      next.set('source_profile_id', selectedSource.profile_id)
      navigate(`${location.pathname}?${next.toString()}`, { replace: true })
    }
  }, [sourceProfileId, intersectionId, selectedSource, selectedId, location.pathname, location.search, navigate])
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (liveRef.current) setNow(Date.now())
    }, 1000)
    return () => window.clearInterval(timer)
  }, [])
  useEffect(() => {
    setHistoricalStats(null); setRealtimeStats(null); setTelemetry(null); setActiveTrajectories([]); setCompletedTrajectories([]); setRealtimeConflicts([]); setVisibleHistoryConflicts([]); setVisibleTrendRows([]); setSelectedEvent(null); setSavedSnapshotId(''); setVideoError(false); setVideoRetry(0); setLastStatsAt(0); setLastTelemetryAt(0); statsFingerprint.current = ''; telemetryFingerprint.current = ''; pausedBuffer.current = { trendRows: null, telemetry: null, conflicts: null, realtime: [] }
  }, [selectedId, selectedSource?.profile_id])
  const pipeline = pipelines.find((item) => item.status === 'running' && (
    selectedSource
      ? item.source_profile_id === selectedSource.profile_id
      : item.intersection_id === selectedId
  )) || null
  const intersectionPipeline = pipelines.find((item) => item.status === 'running' && item.intersection_id === selectedId) || null
  useEffect(() => {
    setRealtimeStats(null); setActiveTrajectories([]); setCompletedTrajectories([]); setRealtimeConflicts([]); setLastStatsAt(0); statsFingerprint.current = ''; pausedBuffer.current = { ...pausedBuffer.current, realtime: [] }
  }, [pipeline?.pipeline_id])
  const quickStartMutation = useMutation({
    mutationFn: async ({ source, intersection }) => {
      const mission = await platformApi.createMission({
        name: `快速演示 · ${source.intersectionName || intersection}`,
        drone_id: source.drone_id,
        source_profile_id: source.profile_id,
        inter_id: intersection,
        frame_stride: quickStartFrameStride,
        scheduled_end_at: new Date(Date.now() + 3_600_000).toISOString(),
      })
      if (mission?.status !== 'running') {
        throw new Error(mission?.error_message || mission?.reason_code || '演示检测启动失败')
      }
      return mission
    },
    onSuccess: () => pipelinesQuery.refetch(),
  })
  const cameraId = pipeline?.camera_id
  const telemetryDroneId = pipeline?.drone_id || selectedSource?.drone_id || (cameraId != null ? `drone_${cameraId}` : '')
  const telemetryQuery = useQuery({ queryKey: ['monitoring-telemetry', telemetryDroneId], queryFn: () => platformApi.telemetry(telemetryDroneId), enabled: Boolean(telemetryDroneId), refetchInterval: 10_000 })
  const applyHistoricalStatsSnapshot = useCallback((snapshot) => {
    if (snapshot) setHistoricalStats(snapshot)
  }, [])
  const applyRealtimeStatsSnapshot = useCallback((snapshot) => {
    if (!snapshot) return
    const fingerprint = JSON.stringify(snapshot)
    setRealtimeStats((previous) => ({ ...(previous || {}), ...snapshot }))
    if (Array.isArray(snapshot.active_trajectories)) {
      setActiveTrajectories(snapshot.active_trajectories)
    }
    if (fingerprint !== statsFingerprint.current) {
      statsFingerprint.current = fingerprint
      setLastStatsAt(Date.now())
    }
  }, [])
  const applyTelemetrySnapshot = useCallback((snapshot) => {
    if (!snapshot || snapshot.error) return
    const fingerprint = JSON.stringify(snapshot)
    setTelemetry(snapshot)
    if (fingerprint !== telemetryFingerprint.current) {
      telemetryFingerprint.current = fingerprint
      setLastTelemetryAt(Date.now())
    }
  }, [])
  useEffect(() => {
    const rows = Array.isArray(trendQuery.data) ? trendQuery.data : []
    const snapshot = rows.at(-1)
    if (!snapshot) return
    if (!liveRef.current) {
      pausedBuffer.current.trendRows = rows
      return
    }
    setVisibleTrendRows(rows)
    applyHistoricalStatsSnapshot(snapshot)
  }, [trendQuery.data, applyHistoricalStatsSnapshot])
  useEffect(() => {
    const rows = Array.isArray(conflictsQuery.data) ? conflictsQuery.data : []
    if (!liveRef.current) pausedBuffer.current.conflicts = rows
    else setVisibleHistoryConflicts(rows)
  }, [conflictsQuery.data])
  useEffect(() => {
    const snapshot = telemetryQuery.data
    if (!snapshot || snapshot.error) return
    if (!liveRef.current) {
      pausedBuffer.current.telemetry = snapshot
      return
    }
    applyTelemetrySnapshot(snapshot)
  }, [telemetryQuery.data, applyTelemetrySnapshot])
  const telemetryDroneIds = [...new Set([
    intersectionQuery.data?.current_drone_id,
    selectedSource?.drone_id,
    pipeline?.drone_id,
    latestStats?.drone_id,
    cameraId != null ? `drone_${cameraId}` : null,
  ].filter(Boolean))]
  const droneId = telemetry?.drone_id || telemetryDroneIds[0] || ''
  const applyRealtimeMessage = useCallback((message) => {
    if (message.data?.source_profile_id && selectedSource?.profile_id && message.data.source_profile_id !== selectedSource.profile_id) return
    if (!realtimeMessageMatchesPipeline(message, pipeline?.pipeline_id)) return
    if (message.type === 'uav_stats') {
      applyRealtimeStatsSnapshot(message.data)
    } else if (message.type === 'uav_track_complete') {
      const receivedAt = Date.now()
      const completed = { ...message.data, [BEV_RECEIVED_AT_FIELD]: receivedAt }
      setCompletedTrajectories((items) => retainCompletedTrajectories([...items, completed], receivedAt))
    } else if (message.type === 'uav_conflict') {
      if (!isBusinessTccConflict(message.data)) return
      const conflict = normalizeConflict(message.data, message.occurredAt || message.occurred_at)
      setRealtimeConflicts((items) => [conflict, ...items.filter((item) => item.id !== conflict.id)].slice(0, 20))
    } else if (message.type === 'uav_alert_new') {
      if (!selectedSource?.profile_id || message.data?.source_profile_id !== selectedSource.profile_id) return
      const alert = normalizeAlert(message.data)
      setRealtimeConflicts((items) => [alert, ...items.filter((item) => item.id !== alert.id)].slice(0, 20))
    } else if (message.type === 'uav_telemetry') {
      applyTelemetrySnapshot(message.data)
    }
  }, [applyRealtimeStatsSnapshot, applyTelemetrySnapshot, pipeline?.pipeline_id, selectedSource?.profile_id])
  const onRealtimeMessage = useCallback((message) => {
    if (!liveRef.current) {
      pausedBuffer.current.realtime = [...pausedBuffer.current.realtime.slice(-499), message]
      return
    }
    applyRealtimeMessage(message)
  }, [applyRealtimeMessage])
  const wsStatus = useWebSocket({ channels: [...intersectionChannels(selectedId), ...alertChannels(selectedId), ...telemetryDroneIds.flatMap(telemetryChannels)], onMessage: onRealtimeMessage, enabled: Boolean(selectedId) })

  const setQueryValue = (key, value) => {
    const next = new URLSearchParams(location.search)
    next.set(key, value)
    navigate(`${location.pathname}?${next.toString()}`, { replace: true })
  }
  const selectSource = (profileId) => {
    const source = displayMonitoringSources.find((item) => item.profile_id === profileId)
    if (!source) return
    const next = new URLSearchParams(location.search)
    next.set('source_profile_id', profileId)
    if (source.intersectionId) next.set('intersection_id', source.intersectionId)
    navigate(`${location.pathname}?${next.toString()}`, { replace: true })
  }
  const selectView = (view) => setQueryValue('view', view)
  const historyConflicts = visibleHistoryConflicts.filter(isBusinessTccConflict).map((item) => normalizeConflict(item, item.occurred_at, false))
  const events = useMemo(() => {
    const seen = new Set()
    return [...realtimeConflicts, ...historyConflicts].filter((event) => event.id && !seen.has(event.id) && seen.add(event.id)).slice(0, 20)
  }, [realtimeConflicts, historyConflicts])
  const displayedEvents = events.length ? events : demoMonitoring.events
  useEffect(() => {
    if (!selectedEvent && displayedEvents.length) setSelectedEvent(displayedEvents[0])
  }, [displayedEvents, selectedEvent])
  const filteredEvents = eventFilter === 'all' ? displayedEvents : displayedEvents.filter((event) => event.level === eventFilter)

  const statsRows = pipeline && visibleTrendRows.length ? visibleTrendRows : demoMonitoring.trend
  const trendData = statsRows.map((row, index) => ({ time: eventTime(row.timestamp || row.time || Date.now() - (statsRows.length - index) * 300_000).slice(0, 5), value: asNumber(row.congestion_index ?? row.cars_amount ?? row.cars ?? row.total_vehicles) ?? 0 }))
  const flowData = statsRows.slice(-6).map((row, index) => {
    const direction = row.direction_flow || {}
    const directionCount = (...keys) => {
      const value = keys.map((key) => direction[key]).find((item) => item != null)
      return asNumber(value?.count ?? value) ?? 0
    }
    return {
      time: eventTime(row.timestamp || row.time || Date.now() - (6 - index) * 300_000).slice(0, 5),
      straight: directionCount('straight'),
      left: directionCount('left_turn', 'left'),
      right: directionCount('right_turn', 'right'),
    }
  })
  const streamActive = Boolean(pipeline)
  const usingDemoMetrics = !streamActive || !latestStats
  const metricStats = usingDemoMetrics ? demoMonitoring.stats : displayStats
  useEffect(() => {
    if (!videoError || !streamActive) return undefined
    const retryDelay = videoRetry >= 5 ? 10_000 : 3_000
    const timer = window.setTimeout(() => {
      setVideoRetry((value) => value + 1)
      setVideoNonce(Date.now())
      setVideoError(false)
    }, retryDelay)
    return () => window.clearTimeout(timer)
  }, [videoError, videoRetry, streamActive])
  const candidateTrajectories = useMemo(
    () => (Array.isArray(realtimeStats?.candidate_trajectories) ? realtimeStats.candidate_trajectories : [])
      .map((item) => ({ ...item, trajectory_display_role: 'candidate' })),
    [realtimeStats?.candidate_trajectories],
  )
  const pixelTrajectories = [
    ...candidateTrajectories,
    ...activeTrajectories.map((item) => ({ ...item, trajectory_display_role: 'active' })),
  ]
  const drawablePixelTrajectoryCount = pixelTrajectories.filter(
    (item) => Array.isArray(item?.trajectory_px) && item.trajectory_px.filter(
      (point) => Array.isArray(point) && point.length >= 2,
    ).length >= 2,
  ).length
  const liveWorldTrajectories = useMemo(() => {
    const active = projectableTrajectories(activeTrajectories)
    const candidates = projectableTrajectories(candidateTrajectories)
    const [olderCompleted, recentCompleted] = splitRecentTrajectories(
      projectableTrajectories(completedTrajectories),
      now,
    )
    const olderBackfill = latestItems(
      olderCompleted,
      LIVE_BEV_TRAJECTORY_MIN_COUNT - active.length - candidates.length - recentCompleted.length,
    )
    return [...olderBackfill, ...recentCompleted, ...candidates, ...active]
  }, [activeTrajectories, candidateTrajectories, completedTrajectories, now])
  const worldTrajectories = liveWorldTrajectories
  const cars = asNumber(metricStats?.cars ?? metricStats?.total_vehicles ?? metricStats?.cars_amount)
  const avgSpeed = asNumber(metricStats?.avg_speed_kmh ?? metricStats?.average_speed)
  const laneStats = Array.isArray(metricStats?.lane_stats) ? metricStats.lane_stats : Array.isArray(metricStats?.lanes) ? metricStats.lanes : []
  const longestQueue = laneStats.length ? Math.max(...laneStats.map((lane) => asNumber(lane.queue_length_m) ?? 0)) : null
  const maxSaturation = laneStats.length ? Math.max(...laneStats.map((lane) => asNumber(lane.saturation) ?? 0)) : null
  const fps = asNumber(metricStats?.fps)
  const inferenceMs = asNumber(metricStats?.inference_ms)
  const inferenceImgSize = asNumber(metricStats?.inference_context?.effective_imgsz)
  const statsStale = usingDemoMetrics ? false : (!lastStatsAt || now - lastStatsAt > 45_000)
  const fixedDemoSource = selectedSource?.profile_id === demoMonitoring.source.profile_id
  const realtimeTrajectoryCount = fixedDemoSource ? 42 : (statsStale || !streamActive ? null : activeTrajectories.length)
  const telemetryStale = usingDemoMetrics ? false : (!lastTelemetryAt || now - lastTelemetryAt > 30_000)
  const attitude = usingDemoMetrics ? demoMonitoring.telemetry : telemetry || displayStats?.drone_position || demoMonitoring.telemetry
  const mapCenterLat = asNumber(selectedIntersection?.center_gcj02?.latitude ?? intersectionQuery.data?.center_gcj02?.latitude ?? attitude.position_gcj02?.latitude) ?? 36.703222
  const mapCenterLon = asNumber(selectedIntersection?.center_gcj02?.longitude ?? intersectionQuery.data?.center_gcj02?.longitude ?? attitude.position_gcj02?.longitude) ?? 117.028285
  const height = asNumber(attitude.height ?? attitude.altitude ?? attitude.altitude_agl)
  const heading = asNumber(attitude.heading ?? attitude.attitude_head ?? attitude.yaw)
  const pitch = asNumber(attitude.attitude_pitch ?? attitude.pitch ?? attitude.gimbal_pitch)
  const roll = asNumber(attitude.attitude_roll ?? attitude.roll ?? attitude.gimbal_roll)
  const tccStatus = usingDemoMetrics ? '固定演示 · 机非冲突 2 起' : tccStatusText(displayStats?.tcc_diagnostics, streamActive)
  const flightQuality = monitoringQualitySummary(usingDemoMetrics ? demoMonitoring.stats : displayStats)
  const unprojectedTrajectoryCount = [...activeTrajectories, ...completedTrajectories]
    .filter((item) => !Array.isArray(item?.trajectory_gcj02) || item.trajectory_gcj02.filter(Boolean).length < 2).length
  const unprojectedCandidateCount = candidateTrajectories.filter((item) => !Array.isArray(item?.trajectory_gcj02) || item.trajectory_gcj02.filter(Boolean).length < 2).length
  const bevEmptyMessage = streamActive
    ? unprojectedTrajectoryCount
      ? `像素轨迹 ${unprojectedTrajectoryCount} 条 · 地理投影不可用`
      : unprojectedCandidateCount
        ? `候选目标 ${unprojectedCandidateCount} · 地理投影不可用`
      : '等待 GCJ-02 实时轨迹'
    : '等待实时 Pipeline 轨迹投放'
  const realtimeStatus = usingDemoMetrics ? '固定演示指标已加载' : wsStatus === 'connected'
    ? '实时链路已连接'
    : wsStatus === 'connecting'
      ? '实时链路连接中，当前展示历史/REST 数据'
      : '实时链路已断开，当前展示历史/REST 数据'
  const sourceModeLabel = selectedSource?.profile_id === demoMonitoring.source.profile_id
    ? '固定演示指标'
    : streamActive ? '实时分析中' : '监测离线'
  const snapshotPreparing = intersectionsQuery.isLoading || sourcesQuery.isLoading || dronesQuery.isLoading || pipelinesQuery.isLoading || (streamActive && !latestStats)
  const quickStartUnavailableReason = platformRole !== 'admin'
    ? '仅管理员可启动演示检测'
    : selectedSource?.enabled === false
      ? '当前视频源已停用'
      : !selectedSource?.drone_id || !selectedId
        ? '当前视频源未绑定无人机或路口'
        : intersectionPipeline
          ? '当前路口已有其他检测任务运行'
          : ''
  const mjpegSrc = detectorVideoStreamSrc(pipeline, videoNonce)
  const videoStreamAvailable = Boolean(mjpegSrc)
  const mainIsVideo = primaryView !== 'bev'
  const selectedRaw = selectedEvent?.raw || {}
  const timestamp = new Date(now).toLocaleTimeString('zh-CN', { hour12: false })
  const activateMissionMode = (mode) => {
    setMissionMode(mode)
    const labels = { hover: '路口悬停', cruise: '路段航拍', review: '治理后复盘' }
    dispatch({ type: 'TOAST', value: { tone: 'success', text: `${labels[mode]}演示已启动，指标保持固定快照` } })
  }
  const saveDemoSnapshot = () => {
    const savedAt = new Date().toISOString()
    const snapshot = buildDemoAnalysisSnapshot({
      intersectionId: selectedId,
      intersectionName: selectedSource?.intersectionName || selectedIntersection?.name || selectedId,
      sourceProfileId: selectedSource?.profile_id,
      missionMode,
      sourceMode: usingDemoMetrics ? 'fixed_demo' : 'live',
      stats: metricStats,
      trend: statsRows,
      events: displayedEvents,
      comparison: demoSituation.comparison,
      capturedAt: new Date(now).toISOString(),
      savedAt,
    })
    upsertDemoSnapshot(snapshot)
    setSavedSnapshotId(snapshot.id)
    dispatch({ type: 'TOAST', value: { tone: 'success', text: '事件与交通流快照已保存，可在事件中心继续分析' } })
  }
  useEffect(() => {
    if (!streamActive || !videoStreamAvailable || videoError) return undefined
    const timer = window.setTimeout(() => {
      if (!videoRef.current || videoRef.current.naturalWidth === 0) setVideoError(true)
    }, 8_000)
    return () => window.clearTimeout(timer)
  }, [streamActive, videoStreamAvailable, videoError, mjpegSrc, primaryView])
  const toggleLive = () => {
    if (liveRef.current) {
      liveRef.current = false
      setLive(false)
      return
    }
    liveRef.current = true
    const buffered = pausedBuffer.current
    if (buffered.trendRows) {
      setVisibleTrendRows(buffered.trendRows)
      applyHistoricalStatsSnapshot(buffered.trendRows.at(-1))
    }
    if (buffered.conflicts) setVisibleHistoryConflicts(buffered.conflicts)
    if (buffered.telemetry) applyTelemetrySnapshot(buffered.telemetry)
    buffered.realtime.forEach(applyRealtimeMessage)
    pausedBuffer.current = { trendRows: null, telemetry: null, conflicts: null, realtime: [] }
    setNow(Date.now())
    setLive(true)
  }

  return <ConsoleFrame pageTitle='实时监测' immersive>
    <h1 className='sr-only'>实时监测</h1>
    {mainIsVideo && streamActive && videoStreamAvailable && !videoError ? <img ref={videoRef} className={`map-image ${primaryView}`} src={mjpegSrc} alt={primaryView === 'raw' ? '原始视频流' : '检测器输出视频流'} onLoad={() => { setVideoError(false); setVideoRetry(0) }} onError={() => setVideoError(true)} /> : primaryView === 'bev' ? <MonitoringBevMap centerLat={mapCenterLat} centerLon={mapCenterLon} trajectories={worldTrajectories} pixelTrajectories={pixelTrajectories} activeCount={activeTrajectories.length} emptyMessage={bevEmptyMessage} label={worldTrajectories.length || !drawablePixelTrajectoryCount ? 'BEV 地图轨迹主视图' : '像素坐标实时轨迹主视图'} /> : <div className='map-image feed-unavailable'><strong>{streamActive ? (!videoStreamAvailable ? '检测器未登记直连视频地址' : videoRetry >= 5 ? '视频流连接失败' : `视频流重连中 · ${videoRetry + 1}/5`) : '当前没有实时视频，固定演示指标已加载'}</strong><span>{streamActive ? (videoStreamAvailable ? (videoRetry >= 5 ? '检测器仍在运行，10 秒后继续自动重试视频流' : '每 3 秒直连检测器重试；持续失败后转为每 10 秒自动恢复') : '请重启 Pipeline 以登记浏览器可访问的 MJPEG 地址') : '可继续演示路口悬停、路段航拍、机非冲突与治理复盘'}</span>{!streamActive && selectedSource?.profile_id !== demoMonitoring.source.profile_id && <div className='quick-start-actions'><label className='quick-start-stride'>抽帧步长<input aria-label='抽帧步长' type='number' min='1' max='30' value={quickStartFrameStride} onChange={(event) => setQuickStartFrameStride(Math.min(30, Math.max(1, Number(event.target.value) || 1)))} /><small>每 N 帧处理 1 帧</small></label><button className='quick-start-button' type='button' title={quickStartUnavailableReason || '启动当前视频源的一小时演示检测'} disabled={Boolean(quickStartUnavailableReason) || quickStartMutation.isPending} onClick={() => quickStartMutation.mutate({ source: selectedSource, intersection: selectedId })}><Play size={15} weight='fill' />{quickStartMutation.isPending ? '正在启动…' : '启动演示检测'}</button>{quickStartMutation.error && <span className='quick-start-error' role='alert'>{apiErrorMessage(quickStartMutation.error, '演示检测启动失败')}</span>}</div>}</div>}
    <div className='map-vignette' />

    <section className='context-bar'>
      <div className='context-title'>
        <span className={`status-pulse ${statsStale ? 'stale' : ''}`} />
        <div>
          <div className='monitoring-source-picker'>
            <select
              aria-label='选择无人机视频源'
              title={selectedSource?.optionLabel || '选择无人机视频源'}
              value={selectedSource?.profile_id || ''}
              onChange={(event) => selectSource(event.target.value)}
              disabled={!displayMonitoringSources.length}
            >
              {displayMonitoringSources.map((item) => <option value={item.profile_id} key={item.profile_id} disabled={item.enabled === false}>{item.optionLabel}{item.enabled === false ? ' · 已停用' : ''}</option>)}
            </select>
            <CaretDown className='monitoring-source-caret' size={14} weight='bold' aria-hidden='true' />
          </div>
          <small title={`${selectedSource?.intersectionName || selectedId || '—'} · ${selectedSource?.profile_id || '未绑定视频源'} · ${sourceModeLabel}`}>{selectedSource?.intersectionName || selectedId || '—'} · {selectedSource?.profile_id || '未绑定视频源'} · {sourceModeLabel}</small>
        </div>
      </div>
      <div className='flight-attitude' aria-label='飞行姿态数据'><div><span>高度</span><strong>{displayNumber(height, 1)}<small>m</small></strong></div><div><span>航向</span><strong>{displayNumber(heading, 1)}<small>°</small></strong></div><div><span>俯仰</span><strong>{displayNumber(pitch, 1)}<small>°</small></strong></div><div><span>横滚</span><strong>{displayNumber(roll, 1)}<small>°</small></strong></div><div><span>云台</span><strong>{telemetryStale ? '过期' : attitude.gimbal_mode || (attitude.is_hovering ? '锁定' : '跟随')}</strong></div></div>
      <div className='view-tabs'>{[['trajectory', '轨迹'], ['lane', '车道'], ['risk', '风险'], ['raw', '原始画面']].map(([id, label]) => <button key={id} className={(id === 'raw' ? primaryView === 'raw' : mapMode === id && primaryView !== 'raw') ? 'active' : ''} onClick={() => id === 'raw' ? selectView('raw') : (setMapMode(id), primaryView === 'raw' && selectView('detector'))}>{label}</button>)}</div>
      <div className='context-meta'><span>{realtimeStatus}</span><i /><span role='status'>{tccStatus}</span><i /><span>{statsStale ? '数据过期' : `YOLO 单处理帧 ${inferenceMs ?? '—'}ms${inferenceImgSize ? ` · ${inferenceImgSize}` : ''}`}</span></div>
    </section>

    <div className={`main-feed-status ${primaryView} ${leftPanelOpen || leftPanelPinned ? '' : 'side-collapsed'}`}>{mainIsVideo ? <VideoCamera size={14} weight='fill' /> : <Crosshair size={14} weight='fill' />}<span>{primaryView === 'bev' ? (streamActive ? 'BEV 鸟瞰轨迹 · ENU / GCJ02' : 'BEV 实时轨迹投放 · 等待 Pipeline') : primaryView === 'raw' ? '原始视频流' : '检测器输出 · YOLO11 → 位姿感知 ByteTrack'}</span><small><i />{streamActive ? ` LIVE · ${displayNumber(fps, 1)} FPS` : ' OFFLINE'}</small></div>

    <section
      className={`left-panel monitoring-side-panel ${leftPanelOpen || leftPanelPinned ? 'expanded' : 'collapsed'} ${leftPanelPinned ? 'pinned' : ''}`}
      aria-label='实时态势面板'
      data-state={leftPanelOpen || leftPanelPinned ? 'expanded' : 'collapsed'}
      data-transparency='40'
      onMouseEnter={() => setLeftPanelOpen(true)}
      onMouseLeave={() => { if (!leftPanelPinned) setLeftPanelOpen(false) }}
      onFocusCapture={() => setLeftPanelOpen(true)}
      onBlurCapture={(event) => { if (!leftPanelPinned && !event.currentTarget.contains(event.relatedTarget)) setLeftPanelOpen(false) }}
    >
      <button className='side-panel-edge' aria-label={leftPanelOpen || leftPanelPinned ? '收缩实时态势面板' : '展开实时态势面板'} onClick={() => { setLeftPanelPinned(false); setLeftPanelOpen((value) => !value) }}>{leftPanelOpen || leftPanelPinned ? <CaretLeft size={17} /> : <CaretRight size={17} />}</button>
      {(leftPanelOpen || leftPanelPinned) && <button className='side-panel-pin' aria-label={leftPanelPinned ? '取消锁定实时态势面板' : '锁定实时态势面板'} aria-pressed={leftPanelPinned} onClick={() => { setLeftPanelPinned((value) => !value); setLeftPanelOpen(true) }}>{leftPanelPinned ? <PushPinSlash size={16} /> : <PushPin size={16} />}</button>}
      <div className='panel-heading'><div><span>实时态势</span><small>{lastStatsAt ? eventTime(lastStatsAt) : '固定演示快照'}</small></div></div>
      <article className='demo-mission-control'>
        <header><div><Drone size={15} weight='fill' /><strong>无人机调度</strong></div><span>{missionMode === 'review' ? '治理后复盘' : missionMode === 'cruise' ? '路段航拍' : '路口悬停'}</span></header>
        <div role='group' aria-label='无人机演示任务'>{[['hover', '路口悬停'], ['cruise', '路段航拍'], ['review', '治理复盘']].map(([id, label]) => <button key={id} className={missionMode === id ? 'active' : ''} onClick={() => activateMissionMode(id)}>{label}</button>)}</div>
        <small>{missionMode === 'cruise' ? '沿重点路段巡航，观察流量与排队变化' : missionMode === 'review' ? '复用同一指标口径，对比治理前后效果' : '保持路口正拍，诊断相位饱和度与机非冲突'} · 最高饱和度 {displayNumber(maxSaturation, 2)}</small>
      </article>
      <article className='congestion-card'><div className='score-ring'><strong>{displayNumber(realtimeTrajectoryCount)}</strong><small>条</small></div><div className='score-copy'><span>实时轨迹数量</span><strong>{realtimeTrajectoryCount == null ? '暂无实时数据' : `活动轨迹 · 已完成 ${completedTrajectories.length}`}</strong><small><TrendUp size={13} />{usingDemoMetrics ? '固定演示快照' : statsStale ? '实时数据已过期' : '实时更新'}</small></div><Crosshair size={24} weight='duotone' /></article>
      <div className='metrics-grid'><MetricCard icon={Target} label='当前目标' value={displayNumber(cars)} unit='辆' delta='' /><MetricCard icon={ListBullets} label='最长排队' value={displayNumber(longestQueue)} unit='m' delta='' tone='amber' /><MetricCard icon={Gauge} label='平均车速' value={displayNumber(avgSpeed, 1)} unit='km/h' delta='' tone='cyan' /><MetricCard icon={ShieldWarning} label='活动风险' value={String(displayedEvents.length)} unit='起' delta='' tone='red' /></div>
      <article className='glass-card trend-card'><div className='card-title'><div><strong>态势趋势</strong><small>最近 30 分钟</small></div><span className='chip'>{usingDemoMetrics ? '固定 5m' : 'REST 5m'}</span></div><div className='chart-box'>{trendData.length ? <ResponsiveContainer width='100%' height='100%'><AreaChart data={trendData} margin={{ top: 8, right: 4, left: -28, bottom: 0 }}><CartesianGrid vertical={false} stroke='rgba(151,171,206,.12)' /><XAxis dataKey='time' tick={{ fill: '#8290aa', fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis tick={{ fill: '#8290aa', fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip contentStyle={{ background: '#111a2a', border: '1px solid #33415b', borderRadius: 8, fontSize: 11 }} /><Area type='monotone' dataKey='value' stroke='#62a1ff' fill='#294c7b' fillOpacity={0.36} strokeWidth={2} /></AreaChart></ResponsiveContainer> : <div className='monitor-empty'>暂无态势数据</div>}</div></article>
      <article className='glass-card flow-card'><div className='card-title'><div><strong>转向流量</strong><small>最近 30 分钟{usingDemoMetrics ? '演示统计' : '真实统计'}</small></div><div className='legend'><span className='straight'>直行</span><span className='left'>左转</span><span className='right'>右转</span></div></div><div className='chart-box small'>{flowData.length ? <ResponsiveContainer width='100%' height='100%'><BarChart data={flowData} margin={{ top: 4, right: 0, left: -34, bottom: 0 }}><XAxis dataKey='time' tick={{ fill: '#8290aa', fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis tick={{ fill: '#8290aa', fontSize: 10 }} axisLine={false} tickLine={false} /><Bar dataKey='straight' fill='#6d9eff' radius={[2,2,0,0]} /><Bar dataKey='left' fill='#c98cf4' radius={[2,2,0,0]} /><Bar dataKey='right' fill='#5fd2a5' radius={[2,2,0,0]} /></BarChart></ResponsiveContainer> : <div className='monitor-empty'>暂无转向流量</div>}</div></article>
      <article className={`flight-quality-card ${flightQuality.tone}`} aria-label='巡航与悬停融合质量状态'>
        <header><div><Drone size={15} weight='fill' /><strong>{flightQuality.phaseLabel}</strong></div><span>{flightQuality.formalLabel}</span></header>
        <div className='flight-quality-grid'>{flightQuality.qualities.map((item) => <span key={item.label} className={item.status}><small>{item.label}</small><strong>{item.value}</strong></span>)}</div>
        {flightQuality.trajectoryOutput === true && flightQuality.roadAnalytics === false && <div className='candidate-only-notice'><strong>轨迹已输出，路网匹配降级</strong><small>Lane ID、Link ID 与匹配质量不可用；世界坐标、速度、方向、统计和 TCC 使用各自独立门禁{flightQuality.reasonLabels.length ? ` · ${flightQuality.reasonLabels.join('；')}` : ''}</small></div>}
        {flightQuality.trajectoryOutput !== true && flightQuality.formal === false && <div className='candidate-only-notice'><strong>目标轨迹暂不可用</strong><small>{flightQuality.reasonLabels.join('；') || '等待检测关联'}{candidateTrajectories.length ? ` · 兼容候选轨迹 ${candidateTrajectories.length} 条` : ''}</small></div>}
        <footer title={`终止原因 ${flightQuality.terminationReason}`}>关联 {flightQuality.method} · 终止 {flightQuality.terminationReason}</footer>
      </article>
    </section>

    {primaryView === 'detector' && mapMode === 'risk' && selectedEvent?.type === 'conflict' && <section className='map-overlay' aria-label='风险事件图层'><div className='risk-marker'><ShieldWarning size={16} weight='fill' /><span>高风险交汇</span><strong>TTC {selectedRaw.ttc_sec ?? '—'}s</strong></div></section>}
    <div className={`map-tools ${rightPanelOpen || rightPanelPinned ? '' : 'side-collapsed'}`}><button onClick={() => setDroneOpen(!droneOpen)} className={droneOpen ? 'active' : ''} aria-label='无人机状态'><Drone size={19} /></button><button onClick={() => setLayerOpen(!layerOpen)} className={layerOpen ? 'active' : ''} aria-label='图层'><Stack size={19} /></button><button aria-label='放大'><Plus size={19} /></button><button aria-label='定位'><Crosshair size={19} /></button></div>
    {droneOpen && <div className={`floating-popover drone-popover ${rightPanelOpen || rightPanelPinned ? '' : 'side-collapsed'}`}><div><strong>{droneId || '未绑定无人机'}</strong><span className={telemetryStale ? '' : 'online'}>{telemetryStale ? '遥测过期' : '在线'}</span></div><dl><dt>高度</dt><dd>{displayNumber(height, 1)} m</dd><dt>电量</dt><dd>{displayNumber(asNumber(attitude.battery_percent ?? attitude.battery_pct))}%</dd><dt>卫星</dt><dd>{displayNumber(asNumber(attitude.satellites ?? attitude.gps_satellites))}</dd><dt>模式</dt><dd>{attitude.is_hovering ? '悬停' : '巡飞'}</dd></dl></div>}
    {layerOpen && <div className={`floating-popover layer-popover ${rightPanelOpen || rightPanelPinned ? '' : 'side-collapsed'}`}>{[['活动轨迹','trajectory'],['风险事件','risk'],['车道拓扑','lane']].map(([label,id]) => <label key={id}><input type='radio' name='map-layer' checked={mapMode === id} onChange={() => setMapMode(id)} /><span>{label}</span></label>)}</div>}

    <section
      className={`right-panel monitoring-side-panel ${rightPanelOpen || rightPanelPinned ? 'expanded' : 'collapsed'} ${rightPanelPinned ? 'pinned' : ''}`}
      aria-label='BEV 与实时事件面板'
      data-state={rightPanelOpen || rightPanelPinned ? 'expanded' : 'collapsed'}
      data-transparency='40'
      onMouseEnter={() => setRightPanelOpen(true)}
      onMouseLeave={() => { if (!rightPanelPinned) setRightPanelOpen(false) }}
      onFocusCapture={() => setRightPanelOpen(true)}
      onBlurCapture={(event) => { if (!rightPanelPinned && !event.currentTarget.contains(event.relatedTarget)) setRightPanelOpen(false) }}
    >
      <button className='side-panel-edge' aria-label={rightPanelOpen || rightPanelPinned ? '收缩BEV与实时事件面板' : '展开BEV与实时事件面板'} onClick={() => { setRightPanelPinned(false); setRightPanelOpen((value) => !value) }}>{rightPanelOpen || rightPanelPinned ? <CaretRight size={17} /> : <CaretLeft size={17} />}</button>
      {(rightPanelOpen || rightPanelPinned) && <button className='side-panel-pin' aria-label={rightPanelPinned ? '取消锁定BEV与实时事件面板' : '锁定BEV与实时事件面板'} aria-pressed={rightPanelPinned} onClick={() => { setRightPanelPinned((value) => !value); setRightPanelOpen(true) }}>{rightPanelPinned ? <PushPinSlash size={16} /> : <PushPin size={16} />}</button>}
      <article className='camera-card'><div className='camera-head'><span>{primaryView === 'bev' ? <VideoCamera size={16} weight='fill' /> : <Crosshair size={16} weight='fill' />}{primaryView === 'bev' ? '检测器输出' : 'BEV 轨迹投放'}</span><small><i />{primaryView === 'bev' ? `${displayNumber(fps, 1)} FPS` : `${worldTrajectories.length || drawablePixelTrajectoryCount} TRACKS`}</small></div>{primaryView === 'bev' ? <div className='detector-preview'>{streamActive && videoStreamAvailable && !videoError ? <img ref={videoRef} src={mjpegSrc} alt='检测器输出视频流预览' onLoad={() => { setVideoError(false); setVideoRetry(0) }} onError={() => setVideoError(true)} /> : <div className='monitor-empty'>{streamActive && !videoStreamAvailable ? '检测器未登记直连地址' : '检测流不可用'}</div>}</div> : <div className='bev-preview'><MonitoringBevMap compact centerLat={mapCenterLat} centerLon={mapCenterLon} trajectories={worldTrajectories} pixelTrajectories={pixelTrajectories} activeCount={streamActive ? activeTrajectories.length : 0} emptyMessage={bevEmptyMessage} label={worldTrajectories.length || !drawablePixelTrajectoryCount ? 'BEV 地图轨迹投放图' : '像素坐标实时轨迹投放图'} /><span className='bev-origin'><Crosshair size={13} weight='bold' /> {worldTrajectories.length ? 'ENU 0,0' : drawablePixelTrajectoryCount ? 'PIXEL' : '—'}</span></div>}<div className='camera-foot'><span>{primaryView === 'bev' ? (streamActive && videoStreamAvailable ? '检测器直连输出' : '检测器离线') : streamActive ? (worldTrajectories.length ? `空间轨迹 ${worldTrajectories.length} · GCJ-02 投放` : bevEmptyMessage) : '等待实时 Pipeline 轨迹'}</span><button className='swap-view' onClick={() => selectView(primaryView === 'bev' ? 'detector' : 'bev')}><ArrowsClockwise size={14} weight='bold' />切为主视图</button></div></article>
      <div className='events-head'><div><strong>近期事件</strong><span>{displayedEvents.length}</span></div><button onClick={() => navigate('/events')}><ListBullets size={16} />全部事件</button></div>
      <div className='event-filters'>{[['all','全部'],['critical','高风险'],['warning','关注']].map(([id,label]) => <button key={id} className={eventFilter === id ? 'active' : ''} onClick={() => setEventFilter(id)}>{label}</button>)}</div>
      <div className='event-list'>{filteredEvents.length ? filteredEvents.map((event) => <button key={event.id} className={`event-card ${event.level} ${selectedEvent?.id === event.id ? 'selected' : ''}`} onClick={() => setSelectedEvent(event)}><span className='event-icon'><EventIcon type={event.type} /></span><span className='event-copy'><strong>{event.title}</strong><small>{event.detail}</small><span>{event.metric}</span></span><time>{event.time}</time></button>) : <div className='monitor-empty'>当前视频源暂无近期事件</div>}</div>
      <div className='monitoring-event-actions'><button className={savedSnapshotId ? 'saved' : ''} disabled={snapshotPreparing} onClick={saveDemoSnapshot}>{snapshotPreparing ? '正在准备快照…' : savedSnapshotId ? '重新保存当前快照' : '保存事件与流量快照'}</button><button onClick={() => navigate('/survey')}>事故测绘</button>{savedSnapshotId && <button className='snapshot-link' onClick={() => navigate(`/events?snapshot_id=${encodeURIComponent(savedSnapshotId)}`)}>查看已保存快照</button>}</div>
    </section>

    <section
      className={`timeline ${timelineOpen ? 'expanded' : 'collapsed'}`}
      aria-label='实时数据时间轴'
      aria-expanded={timelineOpen}
      data-state={timelineOpen ? 'expanded' : 'collapsed'}
      tabIndex={0}
      onMouseEnter={() => setTimelineOpen(true)}
      onMouseLeave={(event) => { if (!event.currentTarget.contains(document.activeElement)) setTimelineOpen(false) }}
      onFocusCapture={() => setTimelineOpen(true)}
      onBlurCapture={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setTimelineOpen(false) }}
    ><div className='timeline-controls'><button aria-label={live ? '暂停实时数据' : '恢复实时数据'} onClick={toggleLive}>{live ? <Pause size={15} weight='fill' /> : <Play size={15} weight='fill' />}</button><strong>{live ? (usingDemoMetrics ? '演示快照' : '实时') : '数据已冻结'}</strong><span>{timestamp}</span></div><div className='timeline-track'>{Array.from({ length: 42 }).map((_, index) => <i key={index} className={displayedEvents[index % Math.max(displayedEvents.length,1)]?.level || ''} />)}<div className='playhead' style={{ left: live ? '92%' : '68%' }} /></div><div className='timeline-range'><span>-30m</span><span>-20m</span><span>-10m</span><span>-5m</span><span>现在</span></div></section>
  </ConsoleFrame>
}
