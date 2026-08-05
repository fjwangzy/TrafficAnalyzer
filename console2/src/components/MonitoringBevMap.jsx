import { useEffect, useMemo, useRef, useState } from 'react'
import { loadAmap } from '../lib/amap'

const DEFAULT_CENTER = { lat: 36.703222, lon: 117.028285 }
const TRACK_COLORS = ['#63b3ff', '#ff806b', '#58d6b0', '#c792ff', '#ffca67']
const finite = (value) => Number.isFinite(Number(value))

export function validMapCenter(lat, lon) {
  return finite(lat) && finite(lon) && Math.abs(Number(lat)) <= 90 && Math.abs(Number(lon)) <= 180 && (Number(lat) !== 0 || Number(lon) !== 0)
    ? { lat: Number(lat), lon: Number(lon) }
    : DEFAULT_CENTER
}

export function trajectoryGcj02(item) {
  return (Array.isArray(item?.trajectory_gcj02) ? item.trajectory_gcj02 : [])
    .filter((point) => Array.isArray(point) && point.length >= 2 && finite(point[0]) && finite(point[1]))
    .map(([longitude, latitude]) => [Number(longitude), Number(latitude)])
}

export function trajectoryPx(item) {
  return (Array.isArray(item?.trajectory_px) ? item.trajectory_px : [])
    .filter((point) => Array.isArray(point) && point.length >= 2 && finite(point[0]) && finite(point[1]))
    .map(([x, y]) => [Number(x), Number(y)])
}

export function pixelTrajectoryViewBox(trajectories = []) {
  const points = trajectories.flatMap(trajectoryPx)
  const maxX = Math.max(1280, ...points.map(([x]) => x * 1.04))
  const maxY = Math.max(720, ...points.map(([, y]) => y * 1.04))
  const width = Math.max(maxX, maxY * (16 / 9))
  const height = Math.max(maxY, width * (9 / 16))
  return `0 0 ${Math.ceil(width)} ${Math.ceil(height)}`
}

export function isCandidateTrajectory(item) {
  if (item?.trajectory_display_role === 'active' || item?.trajectory_output_eligible === true) return false
  if (item?.trajectory_display_role === 'candidate' || item?.is_candidate_trajectory === true) return true
  return item?.tracking_quality === 'degraded'
    || item?.quality_status === 'degraded'
    || item?.formal_analytics_eligible === false
}

export function mapFitPadding({ compact = false, embedded = false } = {}) {
  if (compact) return [12, 12, 12, 12]
  if (embedded) return [32, 32, 32, 32]
  return [150, 390, 120, 350]
}

export function mapFitDuration(reducedMotion = false) { return reducedMotion ? 0 : 350 }

export function trajectoryOverlaySignature(trajectories = []) {
  return JSON.stringify(trajectories.map((item, index) => [
    Number(item?.color_index ?? index) % TRACK_COLORS.length,
    Boolean(item?.selected),
    isCandidateTrajectory(item),
    trajectoryGcj02(item),
  ]))
}

export function MonitoringBevMap({ centerLat, centerLon, trajectories = [], pixelTrajectories = [], activeCount = 0, compact = false, embedded = false, showEndpoints = true, emptyMessage = '', label }) {
  const targetRef = useRef(null)
  const mapRef = useRef(null)
  const amapRef = useRef(null)
  const overlaysRef = useRef([])
  const hasFittedTrajectoriesRef = useRef(false)
  const [loadFailed, setLoadFailed] = useState(false)
  const [mapReady, setMapReady] = useState(false)
  const center = validMapCenter(centerLat, centerLon)
  const drawablePixelTrajectories = useMemo(
    () => pixelTrajectories.filter((item) => trajectoryPx(item).length >= 2),
    [pixelTrajectories],
  )
  const hasCandidateTrajectories = [...trajectories, ...drawablePixelTrajectories]
    .some(isCandidateTrajectory)
  const trajectoryLegend = <div className='monitoring-bev-legend'>
    <span><i className='solid' />目标轨迹</span>
    {hasCandidateTrajectories ? <span><i className='candidate' />兼容候选轨迹</span> : null}
  </div>
  const pixelMode = !trajectories.some((item) => trajectoryGcj02(item).length) && drawablePixelTrajectories.length > 0
  const pixelViewBox = useMemo(
    () => pixelTrajectoryViewBox(drawablePixelTrajectories),
    [drawablePixelTrajectories],
  )
  const overlaySignature = useMemo(() => trajectoryOverlaySignature(trajectories), [trajectories])
  const stableTrajectoriesRef = useRef({ signature: overlaySignature, value: trajectories })
  if (stableTrajectoriesRef.current.signature !== overlaySignature) {
    stableTrajectoriesRef.current = { signature: overlaySignature, value: trajectories }
  }
  const stableTrajectories = stableTrajectoriesRef.current.value

  useEffect(() => {
    let disposed = false
    if (!targetRef.current || loadFailed || pixelMode) return undefined
    loadAmap().then((AMap) => {
      if (disposed || !targetRef.current) return
      amapRef.current = AMap
      mapRef.current = new AMap.Map(targetRef.current, {
        center: [center.lon, center.lat], zoom: compact ? 18 : 19,
        zooms: [15, 22], mapStyle: 'amap://styles/darkblue', viewMode: '2D',
      })
      setMapReady(true)
    }).catch(() => { if (!disposed) setLoadFailed(true) })
    return () => { disposed = true; setMapReady(false); mapRef.current?.destroy(); mapRef.current = null; amapRef.current = null; overlaysRef.current = []; hasFittedTrajectoriesRef.current = false }
  }, [compact, loadFailed, pixelMode])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    map.setCenter([center.lon, center.lat])
  }, [center.lat, center.lon, mapReady])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const previousOverlays = overlaysRef.current
    const AMap = amapRef.current
    if (!AMap) return
    const overlays = []
    stableTrajectories.forEach((item, index) => {
      const path = trajectoryGcj02(item)
      if (!path.length) return
      const candidate = isCandidateTrajectory(item)
      const color = candidate ? '#ffb454' : TRACK_COLORS[Number(item.color_index ?? index) % TRACK_COLORS.length]
      if (path.length >= 2) overlays.push(new AMap.Polyline({
        path, strokeColor: color, strokeWeight: item.selected ? 5 : (item.selected || index < activeCount ? 3.5 : 2.5),
        strokeOpacity: candidate ? 0.82 : 0.92,
        strokeStyle: candidate ? 'dashed' : 'solid',
        strokeDasharray: candidate ? [10, 7] : undefined,
        lineJoin: 'round', lineCap: 'round', zIndex: candidate ? 19 : 20,
      }))
      if (showEndpoints || item.selected) overlays.push(new AMap.CircleMarker({
        center: path.at(-1), radius: 4.5, fillColor: color, fillOpacity: 1,
        strokeColor: '#eef6ff', strokeWeight: 1.4, zIndex: 30,
      }))
    })
    if (overlays.length) {
      map.add(overlays)
      if (!hasFittedTrajectoriesRef.current) {
        map.setFitView(overlays, false, mapFitPadding({ compact, embedded }), compact || embedded ? 19 : 20)
        hasFittedTrajectoriesRef.current = true
      }
    }
    if (previousOverlays.length) map.remove(previousOverlays)
    overlaysRef.current = overlays
  }, [stableTrajectories, activeCount, compact, embedded, showEndpoints, mapReady])

  if (pixelMode) return <div className={`monitoring-bev-map ${compact ? 'compact' : 'main'} pixel-mode`} role='img' aria-label={label || '像素坐标实时轨迹'}>
    <svg className='monitoring-bev-pixel-stage' viewBox={pixelViewBox} preserveAspectRatio='xMidYMid meet' aria-hidden='true'>
      {drawablePixelTrajectories.map((item, index) => {
        const path = trajectoryPx(item)
        const candidate = isCandidateTrajectory(item)
        const color = candidate ? '#ffb454' : TRACK_COLORS[Number(item.color_index ?? index) % TRACK_COLORS.length]
        const key = item.track_id ?? item.association_id ?? item.id ?? index
        return <g key={key}>
          <polyline
            points={path.map(([x, y]) => `${x},${y}`).join(' ')}
            fill='none'
            stroke={color}
            strokeWidth={item.selected ? 5 : 3}
            strokeOpacity={candidate ? .82 : .94}
            strokeDasharray={candidate ? '10 7' : undefined}
            strokeLinecap='round'
            strokeLinejoin='round'
            vectorEffect='non-scaling-stroke'
          />
          {showEndpoints || item.selected ? <circle cx={path.at(-1)[0]} cy={path.at(-1)[1]} r='5' fill={color} stroke='#eef6ff' strokeWidth='1.4' vectorEffect='non-scaling-stroke' /> : null}
        </g>
      })}
    </svg>
    <div className='monitoring-bev-grid' />
    <div className='monitoring-bev-source'>像素坐标实时轨迹</div>
    {trajectoryLegend}
    <div className='monitoring-bev-attribution' role='status'>世界坐标不可用 · {drawablePixelTrajectories.length} 条</div>
  </div>
  if (loadFailed) return <div className='map-offline'><strong>高德地图服务不可用</strong><button className='secondary-button' onClick={() => setLoadFailed(false)}>重试底图</button></div>
  return <div className={`monitoring-bev-map ${compact ? 'compact' : 'main'}`} role='img' aria-label={label || 'GCJ-02 轨迹地图'}>
    <div ref={targetRef} className='monitoring-bev-map-canvas amap-map' />
    <div className='monitoring-bev-grid' />
    <div className='monitoring-bev-source'>高德地图 · GCJ-02</div>
    {trajectoryLegend}
    {!trajectories.length && emptyMessage ? <div className='monitoring-bev-empty' role='status'>{emptyMessage}</div> : null}
  </div>
}
