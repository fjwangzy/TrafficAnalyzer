import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import { ConsoleFrame } from './components/AppShell'
import { apiErrorMessage, platformApi } from './lib/api'
import { alertChannels, intersectionChannels, telemetryChannels } from './lib/realtime'
import { useWebSocket } from './hooks/useWebSocket'
import { MonitoringBevMap } from './components/MonitoringBevMap'
import {
  ArrowsClockwise, CaretLeft, CaretRight, Crosshair, Drone, Gauge, ListBullets,
  NavigationArrow, Pause, Play, Plus, PushPin, PushPinSlash, RoadHorizon,
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

function normalizeConflict(data, occurredAt) {
  return {
    id: data.id || `conflict-${data.motor_id}-${data.non_motor_id}-${occurredAt || Date.now()}`,
    level: eventTone(data.severity),
    type: 'conflict',
    title: data.title || '机非冲突风险升高',
    detail: data.description || `轨迹 ${data.motor_id ?? '—'} 与 ${data.non_motor_id ?? '—'} 预测交汇`,
    metric: `TTC ${data.ttc_sec ?? '—'}s · PET ${data.pet_sec ?? '—'}s`,
    time: eventTime(occurredAt || data.timestamp),
    raw: data,
    realtime: true,
  }
}

function MetricCard({ label, value, unit, delta, icon: Icon, tone = 'blue' }) {
  return <article className='metric-card'><div className={`metric-icon ${tone}`}><Icon size={17} weight='fill' /></div><div><div className='metric-label'>{label}</div><div className='metric-value'>{value}<small>{unit}</small></div></div><span className={`metric-delta ${delta?.startsWith('+') ? 'up' : ''}`}>{delta}</span></article>
}

function EventIcon({ type }) {
  const icons = { conflict: ShieldWarning, lane: ArrowsClockwise, congestion: RoadHorizon, enforcement: Truck }
  const Icon = icons[type] || Warning
  return <Icon size={18} weight='fill' />
}

export function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const params = new URLSearchParams(location.search)
  const intersectionId = params.get('intersection_id')
  const requestedView = params.get('view')
  const primaryView = requestedView === 'bev' || requestedView === 'raw' ? requestedView : 'detector'
  const [mapMode, setMapMode] = useState('trajectory')
  const [eventFilter, setEventFilter] = useState('all')
  const [selectedEvent, setSelectedEvent] = useState(null)
  const [live, setLive] = useState(true)
  const [droneOpen, setDroneOpen] = useState(false)
  const [layerOpen, setLayerOpen] = useState(false)
  const [leftPanelOpen, setLeftPanelOpen] = useState(false)
  const [leftPanelPinned, setLeftPanelPinned] = useState(false)
  const [rightPanelOpen, setRightPanelOpen] = useState(false)
  const [rightPanelPinned, setRightPanelPinned] = useState(false)
  const [latestStats, setLatestStats] = useState(null)
  const [telemetry, setTelemetry] = useState(null)
  const [activeTrajectories, setActiveTrajectories] = useState([])
  const [completedTrajectories, setCompletedTrajectories] = useState([])
  const [realtimeConflicts, setRealtimeConflicts] = useState([])
  const [visibleTrendRows, setVisibleTrendRows] = useState([])
  const [visibleRestAlerts, setVisibleRestAlerts] = useState([])
  const [lastStatsAt, setLastStatsAt] = useState(0)
  const [lastTelemetryAt, setLastTelemetryAt] = useState(0)
  const [now, setNow] = useState(Date.now())
  const [videoError, setVideoError] = useState(false)
  const [videoRetry, setVideoRetry] = useState(0)
  const [videoNonce, setVideoNonce] = useState(0)
  const statsFingerprint = useRef('')
  const telemetryFingerprint = useRef('')
  const liveRef = useRef(true)
  const pausedBuffer = useRef({ trendRows: null, telemetry: null, alerts: null, realtime: [] })

  const intersectionsQuery = useQuery({ queryKey: ['monitoring-intersections'], queryFn: platformApi.intersections })
  const intersections = Array.isArray(intersectionsQuery.data) ? intersectionsQuery.data : []
  const selectedIntersection = intersections.find((item) => item.id === intersectionId) || intersections[0] || null
  const selectedId = selectedIntersection?.id || ''
  const intersectionQuery = useQuery({ queryKey: ['monitoring-intersection', selectedId], queryFn: () => platformApi.intersection(selectedId), enabled: Boolean(selectedId) })
  const pipelinesQuery = useQuery({ queryKey: ['monitoring-pipelines'], queryFn: platformApi.pipelines, refetchInterval: 5_000 })
  const trendQuery = useQuery({ queryKey: ['monitoring-trend', selectedId], queryFn: () => platformApi.intersectionStats(selectedId), enabled: Boolean(selectedId), refetchInterval: 30_000 })
  const alertsQuery = useQuery({ queryKey: ['monitoring-alerts', selectedId], queryFn: () => platformApi.alerts({ limit: 20 }), enabled: Boolean(selectedId), refetchInterval: 10_000 })

  useEffect(() => {
    if (!intersectionId && selectedId) {
      const next = new URLSearchParams(location.search)
      next.set('intersection_id', selectedId)
      navigate(`${location.pathname}?${next.toString()}`, { replace: true })
    }
  }, [intersectionId, selectedId, location.pathname, location.search, navigate])
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (liveRef.current) setNow(Date.now())
    }, 1000)
    return () => window.clearInterval(timer)
  }, [])
  useEffect(() => {
    setLatestStats(null); setTelemetry(null); setActiveTrajectories([]); setCompletedTrajectories([]); setRealtimeConflicts([]); setVisibleTrendRows([]); setVisibleRestAlerts([]); setSelectedEvent(null); setVideoError(false); setVideoRetry(0); setLastStatsAt(0); setLastTelemetryAt(0); statsFingerprint.current = ''; telemetryFingerprint.current = ''; pausedBuffer.current = { trendRows: null, telemetry: null, alerts: null, realtime: [] }
  }, [selectedId])
  useEffect(() => {
    if (!videoError || videoRetry >= 5) return undefined
    const timer = window.setTimeout(() => {
      setVideoRetry((value) => value + 1)
      setVideoNonce(Date.now())
      setVideoError(false)
    }, 3000)
    return () => window.clearTimeout(timer)
  }, [videoError, videoRetry])

  const pipelines = Array.isArray(pipelinesQuery.data) ? pipelinesQuery.data : []
  const pipeline = pipelines.find((item) => item.intersection_id === selectedId && item.status === 'running') || null
  const cameraId = pipeline?.camera_id
  const telemetryQuery = useQuery({ queryKey: ['monitoring-telemetry', cameraId], queryFn: () => platformApi.telemetry(`drone_${cameraId}`), enabled: cameraId != null, refetchInterval: 10_000 })
  const applyStatsSnapshot = useCallback((snapshot, merge = false) => {
    if (!snapshot) return
    const fingerprint = JSON.stringify(snapshot)
    setLatestStats((previous) => merge ? ({ ...(previous || {}), ...snapshot }) : snapshot)
    setActiveTrajectories(Array.isArray(snapshot.active_trajectories) ? snapshot.active_trajectories : [])
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
    applyStatsSnapshot(snapshot)
  }, [trendQuery.data, applyStatsSnapshot])
  useEffect(() => {
    const rows = Array.isArray(alertsQuery.data) ? alertsQuery.data : []
    if (!liveRef.current) pausedBuffer.current.alerts = rows
    else setVisibleRestAlerts(rows)
  }, [alertsQuery.data])
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
    pipeline?.drone_id,
    latestStats?.drone_id,
    cameraId != null ? `drone_${cameraId}` : null,
  ].filter(Boolean))]
  const droneId = telemetry?.drone_id || telemetryDroneIds[0] || ''
  const applyRealtimeMessage = useCallback((message) => {
    if (message.type === 'uav_stats') {
      applyStatsSnapshot(message.data, true)
    } else if (message.type === 'uav_track_complete') {
      setCompletedTrajectories((items) => [...items.slice(-198), message.data])
    } else if (message.type === 'uav_conflict') {
      const conflict = normalizeConflict(message.data, message.occurredAt)
      setRealtimeConflicts((items) => [conflict, ...items.filter((item) => item.id !== conflict.id)].slice(0, 20))
    } else if (message.type === 'uav_alert_new') {
      const alert = normalizeAlert(message.data)
      setRealtimeConflicts((items) => [alert, ...items.filter((item) => item.id !== alert.id)].slice(0, 20))
    } else if (message.type === 'uav_telemetry') {
      applyTelemetrySnapshot(message.data)
    }
  }, [applyStatsSnapshot, applyTelemetrySnapshot])
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
  const selectIntersection = (id) => setQueryValue('intersection_id', id)
  const selectView = (view) => setQueryValue('view', view)
  const restAlerts = visibleRestAlerts.filter((item) => !selectedId || item.intersection_id === selectedId).map(normalizeAlert)
  const events = useMemo(() => {
    const seen = new Set()
    return [...realtimeConflicts, ...restAlerts].filter((event) => event.id && !seen.has(event.id) && seen.add(event.id)).slice(0, 20)
  }, [realtimeConflicts, restAlerts])
  useEffect(() => {
    if (!selectedEvent && events.length) setSelectedEvent(events[0])
  }, [events, selectedEvent])
  const filteredEvents = eventFilter === 'all' ? events : events.filter((event) => event.level === eventFilter)

  const statsRows = visibleTrendRows
  const trendData = statsRows.map((row, index) => ({ time: eventTime(row.timestamp || row.time || Date.now() - (statsRows.length - index) * 300_000).slice(0, 5), value: asNumber(row.congestion_index ?? row.cars_amount ?? row.cars ?? row.total_vehicles) ?? 0 }))
  const flowData = statsRows.slice(-6).map((row, index) => ({ time: eventTime(row.timestamp || row.time || Date.now() - (6 - index) * 300_000).slice(0, 5), car: asNumber(row.motor_count ?? row.cars_amount ?? row.cars) ?? 0, truck: asNumber(row.truck_count) ?? 0 }))
  const worldTrajectories = [...activeTrajectories, ...completedTrajectories].filter((item) => Array.isArray(item?.trajectory_world_m) && item.trajectory_world_m.length)
  const congestion = asNumber(latestStats?.congestion_index)
  const cars = asNumber(latestStats?.cars ?? latestStats?.total_vehicles ?? latestStats?.cars_amount)
  const avgSpeed = asNumber(latestStats?.avg_speed_kmh ?? latestStats?.average_speed)
  const laneStats = Array.isArray(latestStats?.lane_stats) ? latestStats.lane_stats : Array.isArray(latestStats?.lanes) ? latestStats.lanes : []
  const longestQueue = laneStats.length ? Math.max(...laneStats.map((lane) => asNumber(lane.queue_length_m) ?? 0)) : null
  const fps = asNumber(latestStats?.fps)
  const inferenceMs = asNumber(latestStats?.inference_ms)
  const statsStale = !lastStatsAt || now - lastStatsAt > 10_000
  const telemetryStale = !lastTelemetryAt || now - lastTelemetryAt > 30_000
  const attitude = telemetry || latestStats?.drone_position || {}
  const mapCenterLat = asNumber(selectedIntersection?.center_lat ?? intersectionQuery.data?.center_lat ?? attitude.lat ?? attitude.latitude) ?? 36.7029
  const mapCenterLon = asNumber(selectedIntersection?.center_lon ?? intersectionQuery.data?.center_lon ?? attitude.lon ?? attitude.longitude) ?? 117.0223
  const height = asNumber(attitude.height ?? attitude.altitude ?? attitude.altitude_agl)
  const heading = asNumber(attitude.heading ?? attitude.attitude_head ?? attitude.yaw)
  const pitch = asNumber(attitude.attitude_pitch ?? attitude.pitch ?? attitude.gimbal_pitch)
  const roll = asNumber(attitude.attitude_roll ?? attitude.roll ?? attitude.gimbal_roll)
  const streamActive = Boolean(pipeline)
  const mjpegSrc = cameraId != null ? `/camera_${cameraId}?retry=${videoNonce}` : ''
  const mainIsVideo = primaryView !== 'bev'
  const monitoringError = intersectionsQuery.error || pipelinesQuery.error || trendQuery.error || alertsQuery.error
  const selectedRaw = selectedEvent?.raw || {}
  const timestamp = new Date(now).toLocaleTimeString('zh-CN', { hour12: false })
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
      applyStatsSnapshot(buffered.trendRows.at(-1))
    }
    if (buffered.alerts) setVisibleRestAlerts(buffered.alerts)
    if (buffered.telemetry) applyTelemetrySnapshot(buffered.telemetry)
    buffered.realtime.forEach(applyRealtimeMessage)
    pausedBuffer.current = { trendRows: null, telemetry: null, alerts: null, realtime: [] }
    setNow(Date.now())
    setLive(true)
  }

  return <ConsoleFrame pageTitle='实时监测' immersive>
    <h1 className='sr-only'>实时监测</h1>
    {mainIsVideo && streamActive && !videoError ? <img className={`map-image ${primaryView}`} src={mjpegSrc} alt={primaryView === 'raw' ? '原始视频流' : '检测器输出视频流'} onLoad={() => { setVideoError(false); setVideoRetry(0) }} onError={() => setVideoError(true)} /> : primaryView === 'bev' ? <MonitoringBevMap centerLat={mapCenterLat} centerLon={mapCenterLon} trajectories={worldTrajectories} activeCount={activeTrajectories.length} label='BEV 地图轨迹主视图' /> : <div className='map-image feed-unavailable'><strong>{streamActive ? (videoRetry >= 5 ? '视频流连接失败' : `视频流重连中 · ${videoRetry + 1}/5`) : '当前路口没有运行中的检测管道'}</strong><span>{monitoringError ? apiErrorMessage(monitoringError) : streamActive ? '每 3 秒重试一次，达到上限后保持错误态' : '请在飞行任务中启动执行记录后返回监控'}</span></div>}
    <div className='map-vignette' />

    <section className='context-bar'>
      <div className='context-title'><span className={`status-pulse ${statsStale ? 'stale' : ''}`} /><div><select aria-label='选择监测路口' value={selectedId} onChange={(event) => selectIntersection(event.target.value)} disabled={!intersections.length}>{intersections.length ? intersections.map((item) => <option value={item.id} key={item.id}>{item.name}</option>) : <option>正在加载路口</option>}</select><small>{selectedId || '—'} · {streamActive ? '实时分析中' : '监测离线'}</small></div></div>
      <div className='flight-attitude' aria-label='飞行姿态数据'><div><span>高度</span><strong>{displayNumber(height, 1)}<small>m</small></strong></div><div><span>航向</span><strong>{displayNumber(heading, 1)}<small>°</small></strong></div><div><span>俯仰</span><strong>{displayNumber(pitch, 1)}<small>°</small></strong></div><div><span>横滚</span><strong>{displayNumber(roll, 1)}<small>°</small></strong></div><div><span>云台</span><strong>{telemetryStale ? '过期' : attitude.gimbal_mode || (attitude.is_hovering ? '锁定' : '跟随')}</strong></div></div>
      <div className='view-tabs'>{[['trajectory', '轨迹'], ['lane', '车道'], ['risk', '风险'], ['raw', '原始画面']].map(([id, label]) => <button key={id} className={(id === 'raw' ? primaryView === 'raw' : mapMode === id && primaryView !== 'raw') ? 'active' : ''} onClick={() => id === 'raw' ? selectView('raw') : (setMapMode(id), primaryView === 'raw' && selectView('detector'))}>{label}</button>)}</div>
      <div className='context-meta'><span>{wsStatus === 'connected' ? '实时链路已连接' : wsStatus}</span><i /><span>{statsStale ? '数据过期' : `推理 ${inferenceMs ?? '—'}ms`}</span></div>
    </section>

    <div className={`main-feed-status ${primaryView} ${leftPanelOpen || leftPanelPinned ? '' : 'side-collapsed'}`}>{mainIsVideo ? <VideoCamera size={14} weight='fill' /> : <Crosshair size={14} weight='fill' />}<span>{primaryView === 'bev' ? 'BEV 鸟瞰轨迹 · ENU / GCJ02' : primaryView === 'raw' ? '原始视频流' : '检测器输出 · YOLO11 / ByteTrack'}</span><small><i />{streamActive ? ` LIVE · ${displayNumber(fps, 1)} FPS` : ' OFFLINE'}</small></div>

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
      <div className='panel-heading'><div><span>实时态势</span><small>{lastStatsAt ? eventTime(lastStatsAt) : '等待数据'}</small></div></div>
      <article className='congestion-card'><div className='score-ring'><strong>{displayNumber(congestion, 1)}</strong><small>/ 10</small></div><div className='score-copy'><span>拥堵指数</span><strong>{congestion == null ? '暂无数据' : congestion >= 7 ? '严重拥堵' : congestion >= 4 ? '中度拥堵' : '运行平稳'}</strong><small><TrendUp size={13} />{statsStale ? '实时数据已过期' : '实时计算'}</small></div><Gauge size={24} weight='duotone' /></article>
      <div className='metrics-grid'><MetricCard icon={RoadHorizon} label='断面流量' value={displayNumber(cars)} unit='辆' delta='' /><MetricCard icon={ListBullets} label='最长排队' value={displayNumber(longestQueue)} unit='m' delta='' tone='amber' /><MetricCard icon={Gauge} label='平均车速' value={displayNumber(avgSpeed, 1)} unit='km/h' delta='' tone='cyan' /><MetricCard icon={ShieldWarning} label='活动风险' value={String(events.length)} unit='起' delta='' tone='red' /></div>
      <article className='glass-card trend-card'><div className='card-title'><div><strong>态势趋势</strong><small>最近 30 分钟</small></div><span className='chip'>REST 5m</span></div><div className='chart-box'>{trendData.length ? <ResponsiveContainer width='100%' height='100%'><AreaChart data={trendData} margin={{ top: 8, right: 4, left: -28, bottom: 0 }}><CartesianGrid vertical={false} stroke='rgba(151,171,206,.12)' /><XAxis dataKey='time' tick={{ fill: '#8290aa', fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis tick={{ fill: '#8290aa', fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip contentStyle={{ background: '#111a2a', border: '1px solid #33415b', borderRadius: 8, fontSize: 11 }} /><Area type='monotone' dataKey='value' stroke='#62a1ff' fill='#294c7b' fillOpacity={0.36} strokeWidth={2} /></AreaChart></ResponsiveContainer> : <div className='monitor-empty'>暂无历史态势数据</div>}</div></article>
      <article className='glass-card flow-card'><div className='card-title'><div><strong>车型流量</strong><small>真实分时统计</small></div><div className='legend'><span className='car'>机动车</span><span className='truck'>货车</span></div></div><div className='chart-box small'>{flowData.length ? <ResponsiveContainer width='100%' height='100%'><BarChart data={flowData} margin={{ top: 4, right: 0, left: -34, bottom: 0 }}><XAxis dataKey='time' tick={{ fill: '#8290aa', fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis tick={{ fill: '#8290aa', fontSize: 10 }} axisLine={false} tickLine={false} /><Bar dataKey='car' fill='#6d9eff' radius={[2,2,0,0]} /><Bar dataKey='truck' fill='#c98cf4' radius={[2,2,0,0]} /></BarChart></ResponsiveContainer> : <div className='monitor-empty'>暂无分时车型数据</div>}</div></article>
    </section>

    {primaryView === 'detector' && mapMode === 'risk' && selectedEvent?.type === 'conflict' && <section className='map-overlay' aria-label='风险事件图层'><div className='risk-marker'><ShieldWarning size={16} weight='fill' /><span>高风险交汇</span><strong>TTC {selectedRaw.ttc_sec ?? '—'}s</strong></div></section>}
    <div className='map-label label-north'><NavigationArrow size={15} weight='fill' /> 活动轨迹 · {activeTrajectories.length}</div><div className='map-label label-east'><Target size={15} weight='fill' /> 当前目标 · {displayNumber(cars)}</div><div className='map-label label-south'><Warning size={15} weight='fill' /> 数据质量 · {statsStale ? '过期' : '实时'}</div>
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
      <article className='camera-card'><div className='camera-head'><span>{primaryView === 'bev' ? <VideoCamera size={16} weight='fill' /> : <Crosshair size={16} weight='fill' />}{primaryView === 'bev' ? '检测器输出' : 'BEV 轨迹投放'}</span><small><i />{primaryView === 'bev' ? `${displayNumber(fps, 1)} FPS` : `${activeTrajectories.length} TRACKS`}</small></div>{primaryView === 'bev' ? <div className='detector-preview'>{streamActive && !videoError ? <img src={mjpegSrc} alt='检测器输出视频流预览' onError={() => setVideoError(true)} /> : <div className='monitor-empty'>检测流不可用</div>}</div> : <div className='bev-preview'><MonitoringBevMap compact centerLat={mapCenterLat} centerLon={mapCenterLon} trajectories={worldTrajectories} activeCount={activeTrajectories.length} label='BEV 地图轨迹投放图' /><span className='bev-origin'><Crosshair size={13} weight='bold' /> ENU 0,0</span></div>}<div className='camera-foot'><span>{primaryView === 'bev' ? (streamActive ? '检测器实时输出' : '检测器离线') : `活动轨迹 ${activeTrajectories.length} · 世界坐标投放`}</span><button className='swap-view' onClick={() => selectView(primaryView === 'bev' ? 'detector' : 'bev')}><ArrowsClockwise size={14} weight='bold' />切为主视图</button></div></article>
      <div className='events-head'><div><strong>实时事件</strong><span>{events.length}</span></div><button onClick={() => navigate('/events')}><ListBullets size={16} />全部事件</button></div>
      <div className='event-filters'>{[['all','全部'],['critical','高风险'],['warning','关注']].map(([id,label]) => <button key={id} className={eventFilter === id ? 'active' : ''} onClick={() => setEventFilter(id)}>{label}</button>)}</div>
      <div className='event-list'>{alertsQuery.isLoading && !events.length ? <div className='monitor-empty'>正在加载事件…</div> : filteredEvents.length ? filteredEvents.map((event) => <button key={event.id} className={`event-card ${event.level} ${selectedEvent?.id === event.id ? 'selected' : ''}`} onClick={() => setSelectedEvent(event)}><span className='event-icon'><EventIcon type={event.type} /></span><span className='event-copy'><strong>{event.title}</strong><small>{event.detail}</small><span>{event.metric}</span></span><time>{event.time}</time></button>) : <div className='monitor-empty'>当前路口暂无实时事件</div>}</div>
    </section>

    <section className='timeline'><div className='timeline-controls'><button aria-label={live ? '暂停实时数据' : '恢复实时数据'} onClick={toggleLive}>{live ? <Pause size={15} weight='fill' /> : <Play size={15} weight='fill' />}</button><strong>{live ? '实时' : '数据已冻结'}</strong><span>{timestamp}</span></div><div className='timeline-track'>{Array.from({ length: 42 }).map((_, index) => <i key={index} className={events[index % Math.max(events.length,1)]?.level || ''} />)}<div className='playhead' style={{ left: live ? '92%' : '68%' }} /></div><div className='timeline-range'><span>-30m</span><span>-20m</span><span>-10m</span><span>-5m</span><span>现在</span></div></section>
  </ConsoleFrame>
}
