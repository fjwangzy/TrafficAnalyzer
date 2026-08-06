import { useEffect, useMemo, useRef, useState } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { Crosshair, Drone, MapPin, Minus, Plus, TrafficSignal, WarningCircle } from '@phosphor-icons/react'
import { loadAmap } from '../lib/amap'

const riskColors = { critical: '#ff715b', warning: '#ffbe55', normal: '#5ad3e7' }
const EMPTY_ITEMS = []
const situationColors = { good: '#58d6b0', near_saturated: '#ffbe55', oversaturated: '#ff715b', missing: '#8290aa' }
const segmentColors = { smooth: '#58d6b0', slow: '#ffbe55', congested: '#ff715b', missing: '#8290aa' }
const sourceColors = { running: '#58d6b0', ready: '#5ad3e7', degraded: '#ffbe55', invalid: '#ff715b', disabled: '#8290aa' }
const liveDroneColors = { monitoring: '#48e4d2', flying: '#68a7ff', online: '#8ec5ff', history: '#9c88d8', connected: '#667f9f', offline: '#8290aa' }
const liveDroneTrailColor = '#ffffff'

function validPoint(item) {
  return Number.isFinite(Number(item?.lon)) && Number.isFinite(Number(item?.lat))
}

function validPath(path) {
  return Array.isArray(path) && path.length >= 2 && path.every((point) => (
    Array.isArray(point)
    && Number.isFinite(Number(point[0]))
    && Number.isFinite(Number(point[1]))
  ))
}

function intersectionMarkerContent(item, selected) {
  const color = situationColors[item.status] || riskColors[item.risk] || situationColors.missing
  const icon = renderToStaticMarkup(<TrafficSignal size={17} weight='fill' />)
  return `<div class="amap-status-marker${item.is_project ? ' project' : ''}${selected ? ' selected' : ''}" style="--marker-color:${color}" aria-hidden="true">${icon}</div>`
}

function sourceMarkerContent(item, selected) {
  const color = sourceColors[item.source_status] || sourceColors.disabled
  const icon = renderToStaticMarkup(<Drone size={20} weight='fill' />)
  const count = Math.max(1, Number(item.source_count) || 1)
  return `<div class="amap-drone-marker${selected ? ' selected' : ''}" style="--marker-color:${color}" aria-hidden="true"><span class="amap-drone-marker-face">${icon}</span>${count > 1 ? `<b>${count}</b>` : ''}</div>`
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}

function liveDroneMarkerContent(item, onSelect, selected) {
  const state = item.is_monitoring ? 'monitoring' : item.position_basis === 'assigned_intersection' ? 'connected' : item.position_basis === 'last_gcj02_telemetry' ? 'history' : item.is_flying ? 'flying' : item.is_online ? 'online' : 'offline'
  const color = liveDroneColors[state]
  const heading = Number.isFinite(Number(item.heading_deg)) ? Number(item.heading_deg) : 0
  const icon = renderToStaticMarkup(<Drone size={22} weight='fill' />)
  const root = document.createElement('div')
  root.className = `amap-live-drone ${state}${selected ? ' selected' : ''}${item.position_basis === 'last_gcj02_telemetry' ? ' stale-position' : ''}${item.position_basis === 'assigned_intersection' ? ' assigned-position' : ''}`
  root.dataset.droneId = item.id
  root.dataset.lon = String(item.lon)
  root.dataset.lat = String(item.lat)
  root.dataset.positionBasis = item.position_basis || ''
  root.style.setProperty('--drone-color', color)
  root.style.setProperty('--drone-heading', `${heading}deg`)
  root.setAttribute('role', 'button')
  root.setAttribute('tabindex', '0')
  root.setAttribute('aria-pressed', selected ? 'true' : 'false')
  root.setAttribute('aria-label', `${item.name || item.id}，${item.status_label || '无人机状态'}，查看飞行详情`)
  root.innerHTML = `
    <span class="amap-live-drone-pulse" aria-hidden="true"></span>
    <span class="amap-live-drone-face" aria-hidden="true">${icon}</span>
    <span class="amap-live-drone-state">${escapeHtml(item.status_label)}</span>
    <section class="amap-drone-hover-card compact" role="tooltip">
      <header><div><strong>${escapeHtml(item.name || item.id)}</strong><small>${escapeHtml(item.location_name || item.intersection_name || item.intersection_id || '未绑定任务区域')} · ${escapeHtml(item.scene_label || '无人机任务')}</small></div><i class="${item.is_monitoring ? 'live' : ''}">${item.is_monitoring ? 'LIVE' : 'DETAIL'}</i></header>
      <footer><span>${escapeHtml(item.telemetry_note || '暂无实时遥测')}</span><strong>点击查看飞行详情</strong></footer>
    </section>
  `
  const activate = (event) => {
    if (event.type === 'keydown' && !['Enter', ' '].includes(event.key)) return
    if (event.type === 'keydown') event.preventDefault()
    onSelect?.(item)
  }
  root.addEventListener('keydown', activate)
  root.addEventListener('click', activate)
  return root
}

export function CityMap({
  points = EMPTY_ITEMS,
  segments = EMPTY_ITEMS,
  sourcePoints = EMPTY_ITEMS,
  liveDronePoints = EMPTY_ITEMS,
  selectedId,
  selectedSegmentId,
  selectedSourceId,
  selectedLiveDroneId,
  onSelect,
  onSegmentSelect,
  onSourceSelect,
  onLiveDroneSelect,
  offline = false,
  compact = false,
  showHeat = false,
  coordinateLabel = 'GCJ-02 坐标',
  markerType = 'status',
  fitToData = false,
  displayMode = 'situation',
  viewportInsets,
}) {
  const targetRef = useRef(null)
  const mapRef = useRef(null)
  const amapRef = useRef(null)
  const overlaysRef = useRef([])
  const liveOverlaysRef = useRef(new Map())
  const liveTrailsRef = useRef(new Map())
  const liveSelectRef = useRef(onLiveDroneSelect)
  const [loadFailed, setLoadFailed] = useState(false)
  const [mapReadyToken, setMapReadyToken] = useState(0)
  const validPoints = useMemo(() => points.filter(validPoint), [points])
  const validSources = useMemo(() => sourcePoints.filter(validPoint), [sourcePoints])
  const validLiveDrones = useMemo(() => liveDronePoints.filter(validPoint), [liveDronePoints])
  const trafficMode = displayMode === 'traffic'
  const renderedPoints = trafficMode ? EMPTY_ITEMS : validPoints
  const renderedSources = trafficMode ? EMPTY_ITEMS : validSources
  const renderedSegments = trafficMode ? EMPTY_ITEMS : segments
  const centerPoints = useMemo(() => validPoints.length ? validPoints : validSources, [validPoints, validSources])
  const centerLongitude = centerPoints.length
    ? centerPoints.reduce((sum, item) => sum + Number(item.lon) / centerPoints.length, 0)
    : 117.028285
  const centerLatitude = centerPoints.length
    ? centerPoints.reduce((sum, item) => sum + Number(item.lat) / centerPoints.length, 0)
    : 36.703222
  // Query refreshes replace point arrays even when their coordinates are unchanged.
  // Keep the AMap initializer stable so realtime telemetry only updates UAV overlays.
  const initialCenter = useMemo(() => [centerLongitude, centerLatitude], [centerLongitude, centerLatitude])
  const fitPadding = useMemo(() => [
    viewportInsets?.top ?? 64,
    viewportInsets?.right ?? 76,
    viewportInsets?.bottom ?? 300,
    viewportInsets?.left ?? 60,
  ], [viewportInsets?.top, viewportInsets?.right, viewportInsets?.bottom, viewportInsets?.left])

  useEffect(() => { liveSelectRef.current = onLiveDroneSelect }, [onLiveDroneSelect])

  useEffect(() => {
    let disposed = false
    if (!targetRef.current || offline || loadFailed) return undefined
    loadAmap().then((AMap) => {
      if (disposed || !targetRef.current) return
      const map = new AMap.Map(targetRef.current, {
        center: initialCenter, zoom: compact ? 12 : 12.4, mapStyle: 'amap://styles/darkblue', viewMode: '2D',
      })
      amapRef.current = AMap
      map.addControl(new AMap.Scale())

      if (trafficMode) {
        map.add(new AMap.TileLayer.Traffic({
          autoRefresh: true,
          interval: 180,
          zIndex: 10,
        }))
      }

      const segmentOverlays = renderedSegments.flatMap((segment) => (segment.paths_gcj02 || [])
        .filter(validPath)
        .map((path, pathIndex) => {
          const polyline = new AMap.Polyline({
            path: path.map((point) => [Number(point[0]), Number(point[1])]),
            strokeColor: segmentColors[segment.status] || segmentColors.missing,
            strokeWeight: segment.id === selectedSegmentId ? 8 : 5,
            strokeOpacity: segment.id === selectedSegmentId ? 1 : 0.82,
            lineJoin: 'round',
            lineCap: 'round',
            zIndex: segment.id === selectedSegmentId ? 55 : 40,
            extData: { ...segment, kind: 'segment', pathIndex },
          })
          polyline.on('click', () => onSegmentSelect?.(segment))
          return polyline
        }))

      const pointOverlays = renderedPoints.map((item) => {
        const isLegacySource = markerType === 'drone'
        const marker = new AMap.Marker({
          position: [Number(item.lon), Number(item.lat)],
          content: isLegacySource
            ? sourceMarkerContent(item, item.id === selectedId)
            : intersectionMarkerContent(item, item.id === selectedId),
          anchor: 'center',
          zIndex: isLegacySource ? (item.id === selectedId ? 320 : 300) : 100,
          extData: { ...item, kind: isLegacySource ? 'source' : 'intersection' },
        })
        marker.on('click', () => onSelect?.(item))
        return marker
      })

      const sourceOverlays = renderedSources.map((item) => {
        const marker = new AMap.Marker({
          position: [Number(item.lon), Number(item.lat)],
          content: sourceMarkerContent(item, item.id === selectedSourceId),
          anchor: 'center',
          zIndex: item.id === selectedSourceId ? 320 : 300,
          extData: { ...item, kind: 'source' },
        })
        marker.on('click', () => onSourceSelect?.(item))
        return marker
      })

      const overlays = [...segmentOverlays, ...pointOverlays, ...sourceOverlays]
      if (overlays.length) {
        map.add(overlays)
        if (fitToData && typeof map.setFitView === 'function') {
          // Reserve the left overlay rail so extreme-west intersections and UAV markers stay clickable.
          map.setFitView(overlays, false, fitPadding)
        }
      }
      mapRef.current = map
      overlaysRef.current = overlays
      setMapReadyToken((value) => value + 1)
    }).catch(() => { if (!disposed) setLoadFailed(true) })
    return () => {
      disposed = true
      overlaysRef.current = []
      liveOverlaysRef.current = new Map()
      mapRef.current?.destroy()
      mapRef.current = null
      amapRef.current = null
    }
  }, [renderedPoints, renderedSources, renderedSegments, selectedId, selectedSegmentId, selectedSourceId, onSelect, onSegmentSelect, onSourceSelect, offline, loadFailed, compact, markerType, fitToData, fitPadding, initialCenter, trafficMode])

  useEffect(() => {
    const map = mapRef.current
    const AMap = amapRef.current
    if (!map || !AMap) return undefined
    const removeOverlay = (overlay) => {
      if (!overlay) return
      if (typeof map.remove === 'function') map.remove(overlay)
      else overlay.setMap?.(null)
    }
    if (!trafficMode) {
      liveOverlaysRef.current.forEach(({ marker, trail }) => {
        removeOverlay(marker)
        removeOverlay(trail)
      })
      liveOverlaysRef.current.clear()
      return undefined
    }

    const nextIds = new Set(validLiveDrones.map((item) => item.id))
    liveOverlaysRef.current.forEach(({ marker, trail }, id) => {
      if (nextIds.has(id)) return
      removeOverlay(marker)
      removeOverlay(trail)
      liveOverlaysRef.current.delete(id)
      liveTrailsRef.current.delete(id)
    })

    validLiveDrones.forEach((item) => {
      const position = [Number(item.lon), Number(item.lat)]
      const suppliedTrail = validPath(item.trail_gcj02) ? item.trail_gcj02.map(([lon, lat]) => [Number(lon), Number(lat)]) : null
      const path = suppliedTrail || [...(liveTrailsRef.current.get(item.id) || [])]
      const previous = path.at(-1)
      if (!suppliedTrail && (!previous || previous[0] !== position[0] || previous[1] !== position[1])) path.push(position)
      if (path.length > 80) path.splice(0, path.length - 80)
      liveTrailsRef.current.set(item.id, path)

      const selected = item.id === selectedLiveDroneId
      const content = liveDroneMarkerContent(item, (selectedItem) => liveSelectRef.current?.(selectedItem), selected)
      let entry = liveOverlaysRef.current.get(item.id)
      if (!entry) {
        const marker = new AMap.Marker({
          position,
          content,
          anchor: 'center',
          zIndex: selected ? 560 : item.is_monitoring ? 520 : item.position_basis === 'assigned_intersection' ? 480 : 500,
          extData: { ...item, kind: 'live-drone' },
        })
        entry = { marker, trail: null, content }
        marker.on('mouseover', () => entry.content?.classList.add('hovered'))
        marker.on('mouseout', () => entry.content?.classList.remove('hovered'))
        map.add(marker)
        liveOverlaysRef.current.set(item.id, entry)
      } else {
        entry.marker.setPosition?.(position)
        const interacting = entry.content?.matches?.(':hover') || entry.content?.contains?.(document.activeElement)
        if (!interacting) {
          entry.content = content
          entry.marker.setContent?.(content)
        }
        entry.marker.setzIndex?.(selected ? 560 : item.is_monitoring ? 520 : item.position_basis === 'assigned_intersection' ? 480 : 500)
      }

      if (path.length >= 2) {
        if (!entry.trail) {
          entry.trail = new AMap.Polyline({
            path: [...path],
            strokeColor: liveDroneTrailColor,
            strokeWeight: 3,
            strokeOpacity: 0.82,
            strokeStyle: suppliedTrail ? 'solid' : 'dashed',
            showDir: true,
            lineJoin: 'round',
            lineCap: 'round',
            zIndex: 470,
            extData: { drone_id: item.id, kind: 'live-drone-trail', truthful_points: path.length },
          })
          map.add(entry.trail)
        } else {
          entry.trail.setPath?.([...path])
        }
      }
      entry.focusTrail = Boolean(item.is_monitoring && item.is_replay && entry.trail)
    })

    const selectedEntry = selectedLiveDroneId ? liveOverlaysRef.current.get(selectedLiveDroneId) : null
    if (selectedEntry && fitToData && typeof map.setFitView === 'function') {
      map.setFitView(selectedEntry.focusTrail ? [selectedEntry.marker, selectedEntry.trail] : [selectedEntry.marker], false, fitPadding, selectedEntry.focusTrail ? 16 : 13)
    }

    return undefined
  }, [validLiveDrones, trafficMode, mapReadyToken, selectedLiveDroneId, fitToData, fitPadding])

  if (offline || loadFailed) return <div className='map-offline'><WarningCircle size={38} weight='duotone' /><strong>高德地图服务不可用</strong><span>保留 KPI、重点关注榜和路口列表；不使用随机点位冒充真实地图。</span>{!offline && <button className='secondary-button' onClick={() => setLoadFailed(false)}>重试底图</button>}</div>

  return <div className={`city-map ${compact ? 'compact' : ''}`}>
    <div ref={targetRef} className='amap-canvas' />
    {showHeat && <img className='map-heat-overlay' src='/assets/bev-intersection-night.png' alt='风险热区空间分布底图' />}
    <div className='map-demo-label'><MapPin size={13} weight='fill' /> {coordinateLabel}</div>
    <div className='map-controls'><button onClick={() => mapRef.current?.zoomIn()} aria-label='放大'><Plus size={18} /></button><button onClick={() => mapRef.current?.zoomOut()} aria-label='缩小'><Minus size={18} /></button><button onClick={() => mapRef.current?.setZoomAndCenter(compact ? 12 : 12.4, initialCenter)} aria-label='复位'><Crosshair size={18} /></button></div>
    <div className='map-attribution'>{trafficMode ? '高德实时路况 · GCJ-02' : '高德地图 · GCJ-02'}</div>
  </div>
}
