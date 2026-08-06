import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, CaretLeft, CaretRight, Database, Drone, Funnel, Pulse, ShieldWarning } from '@phosphor-icons/react'
import { AppShell } from '../components/AppShell'
import { CityMap } from '../components/CityMap'
import { DashboardDronePanel } from '../components/DashboardDronePanel'
import { Panel } from '../components/Common'
import { useWebSocket } from '../hooks/useWebSocket'
import { platformApi } from '../lib/api'
import { intersectionChannels, telemetryChannels } from '../lib/realtime'
import { demoSituation } from '../config/demoData'

const DAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const SOURCE_PRIORITY = { running: 0, ready: 1, degraded: 2, invalid: 3, disabled: 4 }
const TIME_SLOTS = Array.from({ length: 288 }, (_, stepIndex) => ({ stepIndex, label: timeValue(stepIndex) }))

function finiteNumber(value) {
  if (value == null || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

export function situationStatusFromSaturation(value) {
  const number = finiteNumber(value)
  if (number == null) return 'missing'
  if (number < 0.85) return 'good'
  if (number <= 0.95) return 'near_saturated'
  return 'oversaturated'
}

export function segmentStatusFromDelayIndex(value) {
  const number = finiteNumber(value)
  if (number == null) return 'missing'
  if (number < 1.5) return 'smooth'
  if (number <= 2) return 'slow'
  return 'congested'
}

function projectPosition(item) {
  const position = item?.center_gcj02 || item?.position_gcj02
  const lon = finiteNumber(position?.longitude ?? item?.lon)
  const lat = finiteNumber(position?.latitude ?? item?.lat)
  return lon == null || lat == null ? null : { lon, lat }
}

function telemetryPosition(item) {
  const position = item?.position_gcj02
  const lon = finiteNumber(position?.longitude ?? position?.lon)
  const lat = finiteNumber(position?.latitude ?? position?.lat)
  return lon == null || lat == null ? null : { lon, lat }
}

function firstFinite(...values) {
  for (const value of values) {
    const number = finiteNumber(value)
    if (number != null) return number
  }
  return null
}

export function buildDashboardIntersectionPoints({ situationIntersections = [], projectIntersections = [] }) {
  const points = new Map()
  situationIntersections.forEach((item) => {
    const position = projectPosition(item)
    if (!position) return
    const saturation = finiteNumber(item.saturation_max)
    points.set(item.inter_id, {
      ...item,
      id: item.inter_id,
      ...position,
      saturation_max: saturation,
      status: situationStatusFromSaturation(saturation),
      is_project: false,
      has_server_situation: true,
    })
  })
  projectIntersections.forEach((item) => {
    const id = item.inter_id || item.id
    const existing = points.get(id)
    const position = projectPosition(existing || item) || projectPosition(item)
    if (!id || !position) return
    points.set(id, existing
      ? { ...existing, is_project: true, project_name: item.name }
      : {
          id,
          inter_id: id,
          name: item.name || id,
          ...position,
          saturation_max: null,
          saturation_avg: null,
          unbalance_index: null,
          level_of_service: null,
          updated_at: null,
          status: 'missing',
          is_project: true,
          has_server_situation: false,
        })
  })
  return [...points.values()]
}

export function dashboardSourceStatus(source, pipeline) {
  if (pipeline?.status === 'running' || pipeline?.observed_status === 'running') return 'running'
  if (source.enabled === false) return 'disabled'
  if (source.validation_status === 'invalid') return 'invalid'
  if (source.validation_status === 'degraded') return 'degraded'
  return 'ready'
}

export function buildDashboardSourcePoints({ sources = [], drones = [], intersections = [], pipelines = [] }) {
  const droneById = new Map(drones.map((item) => [item.id, item]))
  const intersectionById = new Map(intersections.flatMap((item) => [[item.id, item], [item.inter_id, item]]).filter(([id]) => id))
  const grouped = new Map()

  sources.forEach((source) => {
    const pipeline = pipelines.find((item) => item.source_profile_id === source.profile_id && (item.status === 'running' || item.observed_status === 'running'))
    const drone = droneById.get(source.drone_id)
    const intersectionId = pipeline?.intersection_id || drone?.default_inter_id || drone?.current_intersection_id
    const intersection = intersectionById.get(intersectionId)
    const position = projectPosition(intersection)
    const sourceStatus = dashboardSourceStatus(source, pipeline)
    // A verified project intersection remains a truthful UAV source location
    // even when the selected server typical-situation matrix has no matching
    // row.  Only missing coordinates or unusable sources exclude a marker.
    if (!intersectionId || !intersection || !position || sourceStatus === 'disabled' || sourceStatus === 'invalid') return
    const mapped = {
      source_profile_id: source.profile_id,
      intersection_id: intersectionId,
      drone_id: source.drone_id,
      name: source.display_name || source.video?.location_hint || source.profile_id,
      drone_name: drone?.name || source.drone_id,
      source_status: sourceStatus,
      validation_status: source.validation_status,
      pipeline_id: pipeline?.pipeline_id || pipeline?.id || null,
    }
    if (!grouped.has(intersectionId)) grouped.set(intersectionId, [])
    grouped.get(intersectionId).push(mapped)
  })

  return [...grouped.entries()].map(([intersectionId, mappedSources]) => {
    const intersection = intersectionById.get(intersectionId)
    const position = projectPosition(intersection)
    const sorted = mappedSources.sort((left, right) => SOURCE_PRIORITY[left.source_status] - SOURCE_PRIORITY[right.source_status])
    const primary = sorted[0]
    return {
      id: intersectionId,
      ...primary,
      intersection_name: intersection.name || intersectionId,
      ...position,
      source_count: sorted.length,
      sources: sorted,
    }
  })
}

export function buildLiveDronePoints({ dashboardDrones = [], drones = [], sources = [], intersections = [], pipelines = [], telemetryByDrone = {}, trajectoriesByDrone = {} }) {
  const dashboardById = new Map(dashboardDrones.map((item) => [item.id, item]))
  const droneById = new Map(drones.map((item) => [item.id, item]))
  const sourceByProfile = new Map(sources.map((item) => [item.profile_id, item]))
  const intersectionById = new Map(intersections.flatMap((item) => [[item.id, item], [item.inter_id, item]]).filter(([id]) => id))
  const ids = [...new Set([...dashboardById.keys(), ...droneById.keys()])]

  return ids.flatMap((id) => {
    const dashboardDrone = dashboardById.get(id) || {}
    const drone = droneById.get(id) || {}
    const pipeline = pipelines.find((item) => item.drone_id === id && (item.status === 'running' || item.observed_status === 'running'))
    const source = sourceByProfile.get(pipeline?.source_profile_id)
      || sources.find((item) => item.drone_id === id && item.video?.id === drone.default_video_source_id)
      || sources.find((item) => item.drone_id === id && item.enabled !== false)
    const isMonitoring = Boolean(pipeline)
    const isReplay = String(drone.name || '').includes('回放') || source?.mode === 'local' || ['mp4', 'file'].includes(String(source?.video?.source_type || '').toLowerCase())
    const isReplayMonitoring = isMonitoring && isReplay
    const intersectionId = pipeline?.intersection_id || pipeline?.inter_id || dashboardDrone.inter_id || drone.current_intersection_id || drone.default_inter_id
    const intersection = intersectionById.get(intersectionId)
    const liveTelemetry = telemetryByDrone[id]
    const trajectory = Array.isArray(trajectoriesByDrone[id]) ? trajectoriesByDrone[id] : []
    const trajectoryTelemetry = trajectory.at(-1) || null
    const trailGcj02 = trajectory.reduce((path, point) => {
      const projected = telemetryPosition(point)
      if (!projected) return path
      const coordinate = [projected.lon, projected.lat]
      const previous = path.at(-1)
      if (!previous || previous[0] !== coordinate[0] || previous[1] !== coordinate[1]) path.push(coordinate)
      return path
    }, []).slice(-80)
    const storedTelemetry = drone.last_telemetry || null
    const freshStoredTelemetry = drone.telemetry_status === 'fresh' ? storedTelemetry : null
    const telemetry = liveTelemetry || trajectoryTelemetry || storedTelemetry || dashboardDrone
    const livePosition = telemetryPosition(liveTelemetry)
      || telemetryPosition(trajectoryTelemetry)
      || telemetryPosition(dashboardDrone)
      || telemetryPosition(freshStoredTelemetry)
      || (isReplayMonitoring ? telemetryPosition(storedTelemetry) : null)
    const lastPosition = telemetryPosition(storedTelemetry)
    const assignedPosition = projectPosition(intersection)
    const position = livePosition || lastPosition || assignedPosition
    if (!position) return []

    const runtimeStatus = String(drone.status || dashboardDrone.status || '').toLowerCase()
    const isFlying = runtimeStatus === 'flying' || runtimeStatus === 'hovering'
    const isOnline = dashboardDrone.status === 'online' || (!['offline', 'disabled'].includes(runtimeStatus) && Boolean(runtimeStatus))
    const telemetryQuality = liveTelemetry?.quality_status || liveTelemetry?.telemetry_quality || dashboardDrone.telemetry_quality || drone.telemetry_status
    const isCorridorInspection = String(intersectionId || '').includes('CORRIDOR') || String(drone.name || '').includes('巡航')
    const sceneLabel = isCorridorInspection ? '道路巡检' : '路口监测'
    const statusLabel = !livePosition
      ? isMonitoring ? lastPosition ? '监控中 · 最后位置' : '监控中 · 任务区域' : lastPosition ? '最后位置' : '任务区域'
      : isMonitoring
      ? runtimeStatus === 'hovering' ? '悬停监控' : isReplayMonitoring ? '回放巡航' : '实时监控'
      : isFlying ? runtimeStatus === 'hovering' ? '悬停中' : '飞行中'
        : isOnline ? '在线待命' : '最近位置'

    return [{
      id,
      drone_id: id,
      name: drone.name || dashboardDrone.name || id,
      ...position,
      status_label: statusLabel,
      is_monitoring: isMonitoring,
      is_flying: (isFlying || isReplayMonitoring) && Boolean(livePosition),
      runtime_flying: isFlying || isReplayMonitoring,
      is_replay: isReplay,
      is_online: isOnline,
      position_basis: livePosition ? isReplayMonitoring && trajectoryTelemetry ? 'replay_gcj02_trajectory' : isReplayMonitoring ? 'replay_gcj02_telemetry' : 'live_gcj02_telemetry' : lastPosition ? 'last_gcj02_telemetry' : 'assigned_intersection',
      trail_gcj02: trailGcj02,
      intersection_id: intersectionId || null,
      intersection_name: intersection?.name || intersectionId || '未绑定路口',
      location_name: intersection?.name || drone.intersection_name || (isCorridorInspection ? drone.name : intersectionId) || '未绑定任务区域',
      scene_label: isReplayMonitoring ? `${sceneLabel} · 可控回放` : sceneLabel,
      source_profile_id: pipeline?.source_profile_id || source?.profile_id || null,
      pipeline_id: pipeline?.pipeline_id || pipeline?.id || null,
      pipeline_status: pipeline?.observed_status || pipeline?.status || null,
      video_stream_url: pipeline?.video_stream_url || null,
      can_open_monitoring: Boolean(isMonitoring && (pipeline?.source_profile_id || source?.profile_id) && intersectionId),
      battery_pct: firstFinite(telemetry?.battery_pct, dashboardDrone.battery_pct, drone.battery_pct),
      altitude_m: firstFinite(telemetry?.height, telemetry?.altitude, telemetry?.alt_agl, telemetry?.altitude_m, telemetry?.altitude_agl, telemetry?.relative_altitude, telemetry?.height_m),
      speed_mps: firstFinite(telemetry?.horizontal_speed, telemetry?.ground_speed_mps, telemetry?.horizontal_speed_mps, telemetry?.speed_mps, telemetry?.speed),
      heading_deg: firstFinite(telemetry?.heading_deg, telemetry?.heading, telemetry?.yaw, telemetry?.flight_yaw_degree),
      telemetry_fresh: Boolean(liveTelemetry || trajectoryTelemetry || drone.telemetry_status === 'fresh'),
      telemetry_note: telemetryQuality ? `${isReplay ? '回放' : '实时'}遥测 · ${telemetryQuality}` : isReplay ? '回放遥测' : '实时遥测',
    }]
  })
}

export function defaultTypicalSlot() {
  return { dayOfWeek: 5, stepIndex: 95 }
}

function timeValue(stepIndex) {
  return `${String(Math.floor(stepIndex / 12)).padStart(2, '0')}:${String((stepIndex % 12) * 5).padStart(2, '0')}`
}

function formatMetric(value, digits = 2, suffix = '—') {
  const number = finiteNumber(value)
  return number == null ? suffix : number.toFixed(digits)
}

export function normalizeDashboardRealtimeStats(stats) {
  if (!stats || typeof stats !== 'object') return null
  const laneStats = Array.isArray(stats.lane_stats)
    ? stats.lane_stats
    : stats.lane_stats && typeof stats.lane_stats === 'object'
      ? Object.values(stats.lane_stats)
      : Array.isArray(stats.lanes) ? stats.lanes : []
  const queueValues = [
    finiteNumber(stats.queue_length_m),
    finiteNumber(stats.longest_queue_m),
    ...laneStats.map((lane) => firstFinite(lane?.queue_length_m, lane?.queue_length)),
  ].filter((value) => value != null)
  const tcc = stats.tcc_diagnostics || {}
  const laneSpeeds = laneStats.map((lane) => firstFinite(lane?.avg_speed_kmh, lane?.avg_speed)).filter((value) => value != null)
  return {
    vehicles: firstFinite(stats.cars, stats.total_vehicles, stats.cars_amount, stats.total),
    longestQueueM: queueValues.length ? Math.max(...queueValues) : null,
    avgSpeedKmh: firstFinite(stats.avg_speed_kmh, stats.average_speed, laneSpeeds.length ? laneSpeeds.reduce((sum, value) => sum + value, 0) / laneSpeeds.length : null),
    tccEvents: firstFinite(tcc.business_events_emitted, tcc.events_emitted, tcc.formal_events_emitted, Array.isArray(stats.tcc_events) ? stats.tcc_events.length : null),
  }
}

export function dashboardStatsMessageMatchesDrone(message, drone) {
  if (message?.type !== 'uav_stats' || !drone?.pipeline_id || !drone?.source_profile_id || !drone?.intersection_id) return false
  const data = message.data || {}
  return (data.pipeline_id || data.run_id) === drone.pipeline_id
    && data.source_profile_id === drone.source_profile_id
    && (data.intersection_id || data.inter_id) === drone.intersection_id
}

export function DashboardPage() {
  const navigate = useNavigate()
  const initialSlot = useMemo(() => defaultTypicalSlot(), [])
  const [dayOfWeek, setDayOfWeek] = useState(initialSlot.dayOfWeek)
  const [stepIndex, setStepIndex] = useState(initialSlot.stepIndex)
  const [mapDisplayMode, setMapDisplayMode] = useState('traffic')
  const [selectedIntersectionId, setSelectedIntersectionId] = useState(null)
  const [selectedSegmentId, setSelectedSegmentId] = useState(null)
  const [selectedDroneId, setSelectedDroneId] = useState(null)
  const [rightPanelOpen, setRightPanelOpen] = useState(true)
  const [telemetryByDrone, setTelemetryByDrone] = useState({})
  const [realtimeDroneStats, setRealtimeDroneStats] = useState(null)
  const trafficMode = mapDisplayMode === 'traffic'
  const queryOptions = { refetchInterval: 60_000, retry: (count, error) => error?.response?.status !== 401 && count < 2 }
  const intersectionParams = { limit: 500 }
  const situationQuery = useQuery({ queryKey: ['dashboard', 'situation', dayOfWeek, stepIndex], queryFn: () => platformApi.dashboardSituation(dayOfWeek, stepIndex), ...queryOptions })
  const intersectionsQuery = useQuery({ queryKey: ['dashboard', 'intersections', intersectionParams], queryFn: () => platformApi.dashboardIntersections(intersectionParams), placeholderData: (previous) => previous, ...queryOptions })
  const sourcesQuery = useQuery({ queryKey: ['dashboard', 'sources'], queryFn: platformApi.sources, ...queryOptions })
  const sourceDronesQuery = useQuery({ queryKey: ['dashboard', 'source-drones'], queryFn: platformApi.drones, ...queryOptions, refetchInterval: 5_000 })
  const dashboardDronesQuery = useQuery({ queryKey: ['dashboard', 'drones'], queryFn: platformApi.dashboardDrones, ...queryOptions, refetchInterval: 10_000 })
  const pipelinesQuery = useQuery({ queryKey: ['dashboard', 'pipelines'], queryFn: platformApi.pipelines, ...queryOptions, refetchInterval: 5_000 })

  const situation = situationQuery.data
  const projectIntersections = intersectionsQuery.data?.items || []
  const intersections = useMemo(() => buildDashboardIntersectionPoints({
    situationIntersections: situation?.intersections || [],
    projectIntersections,
  }), [situation?.intersections, projectIntersections])
  const segments = useMemo(() => (situation?.segments || []).map((item) => ({
    ...item,
    status: item.status || segmentStatusFromDelayIndex(item.delay_index),
  })), [situation?.segments])
  const sources = Array.isArray(sourcesQuery.data) ? sourcesQuery.data : []
  const sourceDrones = Array.isArray(sourceDronesQuery.data) ? sourceDronesQuery.data : []
  const dashboardDrones = Array.isArray(dashboardDronesQuery.data?.items) ? dashboardDronesQuery.data.items : []
  const pipelines = Array.isArray(pipelinesQuery.data) ? pipelinesQuery.data : []
  const activeDroneIds = useMemo(() => [...new Set(pipelines
    .filter((item) => item.drone_id && (item.status === 'running' || item.observed_status === 'running'))
    .map((item) => item.drone_id))], [pipelines])
  const trajectoryQueries = useQueries({
    queries: activeDroneIds.map((droneId) => ({
      queryKey: ['dashboard', 'drone-trajectory', droneId],
      queryFn: () => platformApi.droneTrajectory(droneId),
      enabled: trafficMode,
      refetchInterval: 3_000,
      retry: (count, error) => error?.response?.status !== 401 && count < 2,
    })),
  })
  const trajectoriesByDrone = useMemo(() => Object.fromEntries(activeDroneIds.map((droneId, index) => [
    droneId,
    Array.isArray(trajectoryQueries[index]?.data) ? trajectoryQueries[index].data : [],
  ])), [activeDroneIds, trajectoryQueries])
  const sourcePoints = useMemo(
    () => buildDashboardSourcePoints({ sources, drones: sourceDrones, intersections, pipelines }),
    [sources, sourceDrones, intersections, pipelines],
  )
  const liveDronePoints = useMemo(
    () => buildLiveDronePoints({ dashboardDrones, drones: sourceDrones, sources, intersections, pipelines, telemetryByDrone, trajectoriesByDrone }),
    [dashboardDrones, sourceDrones, sources, intersections, pipelines, telemetryByDrone, trajectoriesByDrone],
  )
  const telemetryDroneIds = useMemo(() => [...new Set([
    ...dashboardDrones.map((item) => item.id),
    ...sourceDrones.map((item) => item.id),
  ].filter(Boolean))], [dashboardDrones, sourceDrones])
  const telemetryChannelList = useMemo(() => telemetryDroneIds.flatMap(telemetryChannels), [telemetryDroneIds])
  const selectedDrone = liveDronePoints.find((item) => item.id === selectedDroneId) || null
  const selectedStatsQuery = useQuery({
    queryKey: ['dashboard', 'selected-drone-stats', selectedDrone?.intersection_id, selectedDrone?.source_profile_id, selectedDrone?.pipeline_id],
    queryFn: () => platformApi.intersectionStats(selectedDrone.intersection_id, '30m', '5m', selectedDrone.source_profile_id),
    enabled: Boolean(selectedDrone?.is_monitoring && selectedDrone?.intersection_id && selectedDrone?.source_profile_id && selectedDrone?.pipeline_id),
    refetchInterval: 30_000,
    retry: (count, error) => error?.response?.status !== 401 && count < 2,
  })
  const realtimeChannels = useMemo(() => [...new Set([
    ...telemetryChannelList,
    ...(selectedDrone?.is_monitoring ? intersectionChannels(selectedDrone.intersection_id) : []),
  ])], [telemetryChannelList, selectedDrone?.is_monitoring, selectedDrone?.intersection_id])
  const onDashboardMessage = useCallback((message) => {
    if (message.type === 'uav_telemetry' && message.data?.drone_id) {
      setTelemetryByDrone((current) => ({ ...current, [message.data.drone_id]: message.data }))
      return
    }
    if (dashboardStatsMessageMatchesDrone(message, selectedDrone)) setRealtimeDroneStats(message.data)
  }, [selectedDrone])
  const dashboardSocketStatus = useWebSocket({ channels: realtimeChannels, onMessage: onDashboardMessage, enabled: realtimeChannels.length > 0 })

  useEffect(() => setRealtimeDroneStats(null), [selectedDrone?.id, selectedDrone?.pipeline_id])

  const historicalStats = Array.isArray(selectedStatsQuery.data) ? selectedStatsQuery.data.at(-1) : null
  const selectedStats = normalizeDashboardRealtimeStats(realtimeDroneStats || historicalStats)
  const selectedStatsSource = realtimeDroneStats
    ? dashboardSocketStatus === 'connected' ? '实时推送' : '实时快照'
    : historicalStats ? 'REST 最近样本' : selectedDrone?.is_monitoring ? '等待实时数据' : '无实时任务'

  const rankedIntersections = useMemo(() => [...intersections]
    .filter((item) => item.saturation_max != null)
    .sort((left, right) => right.saturation_max - left.saturation_max), [intersections])

  useEffect(() => {
    if (!selectedIntersectionId && rankedIntersections[0]) setSelectedIntersectionId(rankedIntersections[0].id)
  }, [rankedIntersections, selectedIntersectionId])

  const selectedIntersection = intersections.find((item) => item.id === selectedIntersectionId) || rankedIntersections[0] || intersections[0]
  const selectedSource = sourcePoints.find((item) => item.intersection_id === selectedIntersection?.id)
  const focusIntersections = rankedIntersections.slice(0, 3)
  const firstSource = sourcePoints[0]
  const fleetSummary = useMemo(() => ({
    connected: new Set([...dashboardDrones, ...sourceDrones].filter((item) => item.enabled !== false).map((item) => item.id)).size,
    flying: new Set([
      ...sourceDrones.filter((item) => ['flying', 'hovering'].includes(String(item.status).toLowerCase())).map((item) => item.id),
      ...liveDronePoints.filter((item) => item.runtime_flying).map((item) => item.id),
    ]).size,
    monitoring: new Set(pipelines.filter((item) => item.status === 'running' || item.observed_status === 'running').map((item) => item.drone_id)).size,
  }), [dashboardDrones, sourceDrones, liveDronePoints, pipelines])

  const openSourceMonitoring = useCallback((item, review = false) => {
    if (!item?.source_profile_id || !item?.intersection_id) return
    const suffix = review ? '&stage=review' : ''
    navigate(`/monitoring?intersection_id=${encodeURIComponent(item.intersection_id)}&source_profile_id=${encodeURIComponent(item.source_profile_id)}${suffix}`)
  }, [navigate])
  const selectIntersection = useCallback((item) => {
    setSelectedIntersectionId(item.id)
    setSelectedSegmentId(null)
  }, [])
  const selectSegment = useCallback((item) => {
    setSelectedIntersectionId(item.inter_id)
    setSelectedSegmentId(item.id)
  }, [])
  const selectDrone = useCallback((item) => {
    const droneId = item?.drone_id || item?.id
    if (!droneId) return
    setSelectedDroneId(droneId)
    if (item.intersection_id) setSelectedIntersectionId(item.intersection_id)
    setSelectedSegmentId(null)
  }, [])

  const serverSummary = situation?.summary || {}
  const situationError = situationQuery.error
  const otherLoadError = intersectionsQuery.error || sourcesQuery.error || sourceDronesQuery.error || dashboardDronesQuery.error || pipelinesQuery.error
  const slotLabel = `${DAY_LABELS[dayOfWeek - 1]} ${timeValue(stepIndex)}`
  const storyRoutes = ['/', '/monitoring', '/events', '/events', '/monitoring?stage=review']
  const viewportInsets = {
    top: 104,
    right: rightPanelOpen ? 354 : 70,
    bottom: 78,
    left: selectedDrone ? 338 : 70,
  }

  return <AppShell immersive pageTitle='全局态势' topContext={{ scope: `服务器态势 ${serverSummary.intersections_total ?? '—'} 路口 · 项目 ${projectIntersections.length} 路口`, window: `${slotLabel} 典型时段`, asOf: situation?.cache?.stale ? '缓存降级' : '服务器典型矩阵' }}>
    <div
      className={`dashboard-command-workspace${selectedDrone ? ' drone-open' : ''}${rightPanelOpen ? ' summary-open' : ''}`}
      style={{ '--dashboard-left-inset': `${selectedDrone ? 332 : 14}px`, '--dashboard-right-inset': `${rightPanelOpen ? 344 : 14}px` }}
    >
      <h1 className='sr-only'>无人机交通态势工作台</h1>
      <CityMap
        points={intersections}
        segments={segments}
        sourcePoints={sourcePoints}
        liveDronePoints={liveDronePoints}
        selectedId={selectedIntersection?.id}
        selectedSegmentId={selectedSegmentId}
        selectedSourceId={selectedSource?.id}
        selectedLiveDroneId={selectedDrone?.id}
        onSelect={selectIntersection}
        onSegmentSelect={selectSegment}
        onSourceSelect={selectDrone}
        onLiveDroneSelect={selectDrone}
        fitToData
        displayMode={mapDisplayMode}
        viewportInsets={viewportInsets}
        coordinateLabel={trafficMode ? '高德实时路况 · UAV 实时遥测' : `路口 ${intersections.length} · 路段 ${segments.length} · 无人机覆盖 ${sourcePoints.length}`}
      />

      <header className='dashboard-command-bar'>
        <div className='dashboard-command-title'><span><Drone size={19} weight='fill' /></span><div><strong>无人机交通态势工作台</strong><small>{trafficMode ? '高德实时路况与无人机遥测' : `${slotLabel} · road9 典型态势`}</small></div></div>
        <section className='demo-story-strip dashboard-story-strip' aria-label='演示故事线'>
          {demoSituation.story.map((step, index) => <button key={step.id} onClick={() => navigate(storyRoutes[index])}><span>{step.id}</span><div><strong>{step.label}</strong><small>{step.caption}</small></div>{index < demoSituation.story.length - 1 && <ArrowRight size={12} />}</button>)}
        </section>
        <div className='dashboard-command-controls'>
          <div className='uav-fleet-summary' aria-label='无人机实时接入状态'>
            <strong><Drone size={13} weight='fill' />实时态势</strong>
            <span><i className='connected' />接入 <b>{fleetSummary.connected}</b></span>
            <span><i className='flying' />飞行/回放 <b>{fleetSummary.flying}</b></span>
            <span><i className='monitoring' />监控 <b>{fleetSummary.monitoring}</b></span>
            <small>{dashboardSocketStatus === 'connected' ? '推送已连接' : '轮询保底'}</small>
          </div>
          <div className={`situation-map-toolbar dashboard-map-toolbar ${trafficMode ? 'traffic-mode' : ''}`} aria-label='地图展示与典型时段选择'>
            <div className='map-display-mode' role='group' aria-label='地图展示模式'>
              <button type='button' className={!trafficMode ? 'active' : ''} aria-pressed={!trafficMode} onClick={() => setMapDisplayMode('situation')}>road9 典型态势</button>
              <button type='button' className={trafficMode ? 'active' : ''} aria-pressed={trafficMode} onClick={() => setMapDisplayMode('traffic')}>高德实时路况</button>
            </div>
            {trafficMode
              ? <span className='traffic-refresh-note'>约 3 分钟刷新</span>
              : <><label>星期<select aria-label='星期' value={dayOfWeek} onChange={(event) => setDayOfWeek(Number(event.target.value))}>{DAY_LABELS.map((label, index) => <option key={label} value={index + 1}>{label}</option>)}</select></label><label>时间<select aria-label='时间' value={stepIndex} onChange={(event) => setStepIndex(Number(event.target.value))}>{TIME_SLOTS.map((slot) => <option key={slot.stepIndex} value={slot.stepIndex}>{slot.label}</option>)}</select></label></>}
          </div>
        </div>
      </header>

      {selectedDrone && <DashboardDronePanel
        drone={selectedDrone}
        stats={selectedStats}
        statsSource={selectedStatsSource}
        statsError={selectedStatsQuery.error}
        socketStatus={dashboardSocketStatus}
        onClose={() => setSelectedDroneId(null)}
        onOpenMonitoring={openSourceMonitoring}
      />}

      <aside className={`dashboard-summary-rail ${rightPanelOpen ? 'expanded' : 'collapsed'}`} aria-label='首页治理摘要'>
        <button className='dashboard-summary-edge' type='button' aria-expanded={rightPanelOpen} aria-label={rightPanelOpen ? '收起首页治理摘要' : '展开首页治理摘要'} onClick={() => setRightPanelOpen((value) => !value)}>{rightPanelOpen ? <CaretRight size={17} /> : <CaretLeft size={17} />}</button>
        {rightPanelOpen && <div className='dashboard-side'>
          <Panel title='重点路口态势' subtitle='服务器典型时段 · 饱和度排序' action={<button className='text-button' onClick={() => navigate('/gis')}>历史分析</button>}>
            {focusIntersections.length
              ? <div className='demo-intersection-list'>{focusIntersections.map((item, index) => { const segment = [...segments.filter((row) => row.inter_id === item.id)].sort((left, right) => (right.delay_index ?? -1) - (left.delay_index ?? -1))[0]; const source = sourcePoints.find((row) => row.intersection_id === item.id); return <button key={item.id} onClick={() => selectIntersection(item)}><span className={`rank rank-${index + 1}`}>{index + 1}</span><div><strong>{item.name}</strong><span>{segment ? `${segment.direction || ''}${segment.name}延误指数 ${formatMetric(segment.delay_index)}` : '暂无路段指标'}</span><small>{source ? `${source.source_count} 路无人机源` : '无无人机覆盖'} · 排队 {formatMetric(segment?.queue_len_est_m, 0)}m</small></div><b className={item.status}>{formatMetric(item.saturation_max)}</b></button> })}</div>
              : <div className='situation-empty'>{situationError ? '服务器态势读取失败；未使用 mock 补齐。' : '当前典型时槽暂无态势数据。'}</div>}
          </Panel>
          <Panel title='重点事件' subtitle='固定演示样例 · 机非冲突与事故测绘' action={<button className='text-button' onClick={() => navigate('/events')}>事件中心</button>}>
            <div className='demo-event-list'>{demoSituation.events.map((event) => <button key={event.id} onClick={() => navigate(event.route)}><span className={event.tone}><ShieldWarning size={16} weight='fill' /></span><div><strong>{event.title}</strong><small>{event.metric}</small></div><time>{event.time}</time></button>)}</div>
          </Panel>
          <Panel title='治理前后复盘' subtitle='固定演示样例 · 同口径对比'>
            <div className='demo-comparison'>{demoSituation.comparison.map((item) => <div key={item.label}><span>{item.label}</span><small>{item.before}</small><ArrowRight size={12} /><strong>{item.after}</strong><b>{item.delta}</b></div>)}</div>
            <button className='review-dispatch-button' disabled={!firstSource} onClick={() => firstSource && openSourceMonitoring(firstSource, true)}><Drone size={15} weight='fill' />再次调度无人机复盘</button>
          </Panel>
        </div>}
      </aside>

      {trafficMode
        ? <div className='map-legend traffic-legend' aria-label='高德实时路况图例'><span><i className='traffic-free' />通畅</span><span><i className='traffic-slow' />缓行</span><span><i className='traffic-congested' />拥堵</span><span><i className='traffic-severe' />严重拥堵</span><span><i className='traffic-unknown' />未知</span><em /><span><i className='uav-monitoring' />无人机监控</span><span><i className='uav-flying' />飞行中</span><span><i className='uav-history' />最后遥测</span><span><i className='uav-connected' />配置任务区域</span></div>
        : <div className='map-legend situation-legend'><span><i className='situation-good' />良好</span><span><i className='situation-slow' />接近饱和 / 缓行</span><span><i className='situation-bad' />过饱和 / 拥堵</span><span><i className='situation-missing' />暂无态势</span><span><Drone size={15} weight='fill' />无人机视频源</span></div>}

      <div className='dashboard-bottom-strip'>
        <div><Pulse size={16} weight='fill' /><span>态势口径</span><strong>{slotLabel} · 5 分钟典型矩阵{!situation ? ' · 未加载' : ''}</strong></div>
        <div><Database size={16} /><span>服务器只读数据</span><strong>{situationError ? '暂不可用，地图不回退 mock' : situation?.cache?.stale ? '连接失败，展示同槽最近缓存' : `road ${situation?.source?.road_version || '—'} · ${situation?.cache?.status || '加载中'}`}</strong></div>
        <div><Funnel size={16} /><span>指标口径</span><strong>饱和度：良好 &lt; 0.85 · 接近饱和 0.85–0.95 · 过饱和 &gt; 0.95{otherLoadError ? ' · 视频源信息部分不可用' : ''}</strong></div>
      </div>
    </div>
  </AppShell>
}
