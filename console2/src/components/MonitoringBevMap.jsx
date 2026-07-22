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
    trajectoryGcj02(item),
  ]))
}

export function MonitoringBevMap({ centerLat, centerLon, trajectories = [], activeCount = 0, compact = false, embedded = false, showEndpoints = true, label }) {
  const targetRef = useRef(null)
  const mapRef = useRef(null)
  const amapRef = useRef(null)
  const overlaysRef = useRef([])
  const [loadFailed, setLoadFailed] = useState(false)
  const [mapReady, setMapReady] = useState(false)
  const center = validMapCenter(centerLat, centerLon)
  const overlaySignature = useMemo(() => trajectoryOverlaySignature(trajectories), [trajectories])
  const stableTrajectoriesRef = useRef({ signature: overlaySignature, value: trajectories })
  if (stableTrajectoriesRef.current.signature !== overlaySignature) {
    stableTrajectoriesRef.current = { signature: overlaySignature, value: trajectories }
  }
  const stableTrajectories = stableTrajectoriesRef.current.value

  useEffect(() => {
    let disposed = false
    if (!targetRef.current || loadFailed) return undefined
    loadAmap().then((AMap) => {
      if (disposed || !targetRef.current) return
      amapRef.current = AMap
      mapRef.current = new AMap.Map(targetRef.current, {
        center: [center.lon, center.lat], zoom: compact ? 18 : 19,
        zooms: [15, 22], mapStyle: 'amap://styles/darkblue', viewMode: '2D',
      })
      setMapReady(true)
    }).catch(() => { if (!disposed) setLoadFailed(true) })
    return () => { disposed = true; setMapReady(false); mapRef.current?.destroy(); mapRef.current = null; amapRef.current = null; overlaysRef.current = [] }
  }, [compact, loadFailed])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    map.setCenter([center.lon, center.lat])
    const previousOverlays = overlaysRef.current
    const AMap = amapRef.current
    if (!AMap) return
    const overlays = []
    stableTrajectories.forEach((item, index) => {
      const path = trajectoryGcj02(item)
      if (!path.length) return
      const color = TRACK_COLORS[Number(item.color_index ?? index) % TRACK_COLORS.length]
      if (path.length >= 2) overlays.push(new AMap.Polyline({
        path, strokeColor: color, strokeWeight: item.selected ? 5 : (item.selected || index < activeCount ? 3.5 : 2.5),
        strokeOpacity: 0.92, lineJoin: 'round', lineCap: 'round', zIndex: 20,
      }))
      if (showEndpoints || item.selected) overlays.push(new AMap.CircleMarker({
        center: path.at(-1), radius: 4.5, fillColor: color, fillOpacity: 1,
        strokeColor: '#eef6ff', strokeWeight: 1.4, zIndex: 30,
      }))
    })
    if (overlays.length) {
      map.add(overlays)
      if (!previousOverlays.length) {
        map.setFitView(overlays, false, mapFitPadding({ compact, embedded }), compact || embedded ? 19 : 20)
      }
    }
    if (previousOverlays.length) map.remove(previousOverlays)
    overlaysRef.current = overlays
  }, [stableTrajectories, activeCount, center.lat, center.lon, compact, embedded, showEndpoints, mapReady])

  if (loadFailed) return <div className='map-offline'><strong>高德地图服务不可用</strong><button className='secondary-button' onClick={() => setLoadFailed(false)}>重试底图</button></div>
  return <div className={`monitoring-bev-map ${compact ? 'compact' : 'main'}`} role='img' aria-label={label || 'GCJ-02 轨迹地图'}>
    <div ref={targetRef} className='monitoring-bev-map-canvas amap-map' />
    <div className='monitoring-bev-grid' />
    <div className='monitoring-bev-source'>高德地图 · GCJ-02</div>
  </div>
}
