import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { Crosshair, Drone, MapPin, Minus, Plus, TrafficSignal, WarningCircle } from '@phosphor-icons/react'
import { loadAmap } from '../lib/amap'
import { projectPixelPointToGcj02 } from '../lib/dashboardDigitalTwin'

const riskColors = { critical: '#ff715b', warning: '#ffbe55', normal: '#5ad3e7' }
const EMPTY_ITEMS = []
const situationColors = { good: '#58d6b0', near_saturated: '#ffbe55', oversaturated: '#ff715b', missing: '#8290aa' }
const segmentColors = { smooth: '#58d6b0', slow: '#ffbe55', congested: '#ff715b', missing: '#8290aa' }
const sourceColors = { running: '#58d6b0', ready: '#5ad3e7', degraded: '#ffbe55', invalid: '#ff715b', disabled: '#8290aa' }
const liveDroneColors = { monitoring: '#48e4d2', flying: '#68a7ff', online: '#8ec5ff', history: '#9c88d8', connected: '#667f9f', offline: '#8290aa' }
const liveDroneTrailColor = '#ffffff'
const vehicleColors = { car: '#68a7ff', van: '#8ec5ff', bus: '#ffca67', truck: '#ff806b', pedestrian: '#d68cff', bicycle: '#58d6b0', vehicle: '#eef6ff' }
const digitalTwinFocusScreenXRatio = 0.7

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

function liveDroneMarkerZIndex(item, selected, digitalTwinActive) {
  if (digitalTwinActive) return selected ? 1000 : 680
  return selected ? 560 : item.is_monitoring ? 520 : item.position_basis === 'assigned_intersection' ? 480 : 500
}

function liveDroneMarkerContent(item, onSelect, selected, hideHoverCard = false) {
  const state = item.is_monitoring ? 'monitoring' : item.position_basis === 'assigned_intersection' ? 'connected' : item.position_basis === 'last_gcj02_telemetry' ? 'history' : item.is_flying ? 'flying' : item.is_online ? 'online' : 'offline'
  const color = liveDroneColors[state]
  const heading = Number.isFinite(Number(item.heading_deg)) ? Number(item.heading_deg) : 0
  const icon = renderToStaticMarkup(<Drone size={22} weight='fill' />)
  const root = document.createElement('div')
  root.className = `amap-live-drone ${state}${selected ? ' selected' : ''}${hideHoverCard ? ' digital-twin-minimal' : ''}${item.position_basis === 'last_gcj02_telemetry' ? ' stale-position' : ''}${item.position_basis === 'assigned_intersection' ? ' assigned-position' : ''}`
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
    ${hideHoverCard ? '' : `<section class="amap-drone-hover-card compact" role="tooltip">
      <header><div><strong>${escapeHtml(item.name || item.id)}</strong><small>${escapeHtml(item.location_name || item.intersection_name || item.intersection_id || '未绑定任务区域')} · ${escapeHtml(item.scene_label || '无人机任务')}</small></div><i class="${item.is_monitoring ? 'live' : ''}">${item.is_monitoring ? 'LIVE' : 'DETAIL'}</i></header>
      <footer><span>${escapeHtml(item.telemetry_note || '暂无实时遥测')}</span><strong>点击查看飞行详情</strong></footer>
    </section>`}
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

function normalizedHeading(value) {
  return ((Number(value) % 360) + 360) % 360
}

function usesVerifiedWorldCamera(digitalTwin) {
  return digitalTwin?.level !== 'bev_pixel'
    || Boolean(
      digitalTwin?.availableLayers?.lanes
      || digitalTwin?.availableLayers?.links
      || digitalTwin?.availableLayers?.georeferencedVehicles,
    )
}

function cameraMapRotationDeg(digitalTwin) {
  const heading = Number(digitalTwin?.pixelGroundProjection?.headingDeg)
  return digitalTwin?.level === 'bev_pixel' && !usesVerifiedWorldCamera(digitalTwin) && Number.isFinite(heading)
    ? normalizedHeading(360 - heading)
    : 0
}

function cameraPitchDeg(digitalTwin) {
  return digitalTwin?.level === 'bev_pixel' && !usesVerifiedWorldCamera(digitalTwin) ? 50 : 42
}

function continuousHeadingDeg(rawHeading, previousHeading = null) {
  if (!Number.isFinite(rawHeading)) return previousHeading
  if (!Number.isFinite(previousHeading)) return rawHeading
  const shortestTurn = ((rawHeading - previousHeading + 540) % 360) - 180
  return previousHeading + shortestTurn
}

function trajectoryHeadingDeg(points) {
  if (!validPath(points)) return null
  const end = points.at(-1)
  let start = null
  for (let index = points.length - 2, inspected = 0; index >= 0 && inspected < 8; index -= 1, inspected += 1) {
    const candidate = points[index]
    if (Math.hypot(Number(end[0]) - Number(candidate[0]), Number(end[1]) - Number(candidate[1])) > 1e-8) {
      start = candidate
    }
  }
  if (!start) return null
  const meanLatitude = (Number(start[1]) + Number(end[1])) * Math.PI / 360
  const east = (Number(end[0]) - Number(start[0])) * Math.cos(meanLatitude)
  const north = Number(end[1]) - Number(start[1])
  return normalizedHeading(Math.atan2(east, north) * 180 / Math.PI)
}

function vehicleMarkerContent(item, headingDeg) {
  const vehicleType = String(item.yolo_class_name || item.vehicle_class || 'vehicle').toLowerCase()
  const vehicleClass = vehicleType.replace(/[^a-z0-9_-]/g, '-')
  const tone = vehicleColors[vehicleType] || vehicleColors.vehicle
  const root = document.createElement('div')
  root.className = `amap-digital-twin-vehicle ${vehicleClass}${item.simulated ? ' simulated' : ''}`
  root.dataset.trackId = String(item.track_id)
  root.dataset.headingDeg = Number.isFinite(headingDeg) ? headingDeg.toFixed(1) : ''
  root.style.setProperty('--vehicle-color', tone)
  root.style.setProperty('--vehicle-heading', `${Number.isFinite(headingDeg) ? headingDeg : 0}deg`)
  root.setAttribute('role', 'img')
  root.setAttribute('aria-label', `${item.simulated ? '像素仿真' : ''}车辆 ${item.track_id}，${item.vehicle_class || '类型未知'}，${Number.isFinite(item.avg_speed_kmh) ? `${item.avg_speed_kmh.toFixed(1)} 公里每小时` : '速度未知'}`)
  root.innerHTML = '<span aria-hidden="true"><i></i><b></b></span>'
  root.title = `Track ${item.track_id} · ${item.vehicle_class || 'vehicle'}${item.simulated ? ' · trajectory_px 仿真位置' : ''}${Number.isFinite(item.avg_speed_kmh) ? ` · ${item.avg_speed_kmh.toFixed(1)} km/h` : ''}${item.matched_lane_key ? ` · Lane ${item.matched_lane_key}` : ''}`
  return root
}

function projectPixelTrajectory(points, projection) {
  return points.flatMap((point) => {
    const coordinate = projectPixelPointToGcj02(point, projection)
    return coordinate ? [coordinate] : []
  })
}

function removeMapOverlay(map, overlay) {
  if (!overlay) return
  if (typeof map.remove === 'function') map.remove(overlay)
  else overlay.setMap?.(null)
}

function placeMapTargetAtScreenRatio(map, AMap, target, screenXRatio) {
  if (!map?.setCenter || !Array.isArray(target)) return
  map.setCenter(target)
  const size = map.getSize?.()
  const width = Number(size?.getWidth?.())
  const height = Number(size?.getHeight?.())
  if (!Number.isFinite(width) || !Number.isFinite(height) || typeof map.containerToLngLat !== 'function' || typeof AMap?.Pixel !== 'function') return
  const shiftedCenter = map.containerToLngLat(new AMap.Pixel(width * (1 - screenXRatio), height / 2))
  if (shiftedCenter) map.setCenter(shiftedCenter)
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
  onMapSelect,
  digitalTwin,
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
  const trafficLayerRef = useRef(null)
  const satelliteLayerRef = useRef(null)
  const roadNetLayerRef = useRef(null)
  const liveOverlaysRef = useRef(new Map())
  const liveTrailsRef = useRef(new Map())
  const digitalTwinGeometryRef = useRef([])
  const digitalTwinCoverageRef = useRef([])
  const digitalTwinVehiclesRef = useRef(new Map())
  const digitalTwinContextRef = useRef(null)
  const digitalTwinFitKeyRef = useRef(null)
  const digitalTwinPixelProjectionRef = useRef(null)
  const liveSelectRef = useRef(onLiveDroneSelect)
  const mapSelectRef = useRef(onMapSelect)
  const [loadFailed, setLoadFailed] = useState(false)
  const [mapReadyToken, setMapReadyToken] = useState(0)
  const validPoints = useMemo(() => points.filter(validPoint), [points])
  const validSources = useMemo(() => sourcePoints.filter(validPoint), [sourcePoints])
  const validLiveDrones = useMemo(() => liveDronePoints.filter(validPoint), [liveDronePoints])
  const trafficMode = displayMode === 'traffic'
  const digitalTwinActive = Boolean(digitalTwin?.active)
  const digitalTwinGeometry = useMemo(() => [
    ...(digitalTwin?.geometry?.links || []),
    ...(digitalTwin?.geometry?.areas || []),
    ...(digitalTwin?.geometry?.lanes || []),
    ...(digitalTwin?.geometry?.stopLines || []),
    ...(digitalTwin?.geometry?.coverage || []),
  ], [digitalTwin?.geometry])
  const matchedLaneKeys = useMemo(() => [...new Set((digitalTwin?.vehicles || []).flatMap((item) => [item.matched_lane_key, item.matched_link_id]).filter(Boolean).map(String))].sort(), [digitalTwin?.vehicles])
  const digitalTwinGeometrySignature = useMemo(() => JSON.stringify([
    digitalTwin?.mapVersionId,
    digitalTwinGeometry.map((item) => [item.id, item.kind, item.type, item.path]),
    matchedLaneKeys,
  ]), [digitalTwin?.mapVersionId, digitalTwinGeometry, matchedLaneKeys])
  const hasDigitalTwinSpatialContent = digitalTwinGeometry.length > 0 || (digitalTwin?.vehicles || []).length > 0 || (digitalTwin?.pixelVehicles || []).length > 0
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

  const focusSelectedDrone = useCallback(() => {
    const selectedDrone = validLiveDrones.find((item) => item.id === selectedLiveDroneId)
    if (!selectedDrone) return
    placeMapTargetAtScreenRatio(
      mapRef.current,
      amapRef.current,
      [Number(selectedDrone.lon), Number(selectedDrone.lat)],
      digitalTwinFocusScreenXRatio,
    )
  }, [selectedLiveDroneId, validLiveDrones])

  const resetViewport = () => {
    const map = mapRef.current
    if (!map) return
    if (digitalTwinActive && typeof map.setFitView === 'function') {
      const fitOverlays = digitalTwin?.level === 'bev_pixel' && !usesVerifiedWorldCamera(digitalTwin)
        ? digitalTwinCoverageRef.current
        : [...digitalTwinVehiclesRef.current.values()].map(({ marker }) => marker)
      if (fitOverlays.length) {
        map.setPitch?.(cameraPitchDeg(digitalTwin))
        map.setRotation?.(cameraMapRotationDeg(digitalTwin))
        map.setFitView(fitOverlays, true, fitPadding, 19)
        focusSelectedDrone()
        return
      }
    }
    map.setZoomAndCenter?.(compact ? 12 : 12.4, initialCenter)
  }

  useEffect(() => { liveSelectRef.current = onLiveDroneSelect }, [onLiveDroneSelect])
  useEffect(() => { mapSelectRef.current = onMapSelect }, [onMapSelect])

  useEffect(() => {
    let disposed = false
    if (!targetRef.current || offline || loadFailed) return undefined
    loadAmap().then((AMap) => {
      if (disposed || !targetRef.current) return
      const map = new AMap.Map(targetRef.current, {
        center: initialCenter, zoom: compact ? 12 : 12.4, mapStyle: 'amap://styles/darkblue', viewMode: '3D', pitch: 0,
      })
      map.on('click', () => mapSelectRef.current?.())
      amapRef.current = AMap
      map.addControl(new AMap.Scale())

      if (trafficMode) {
        const trafficLayer = new AMap.TileLayer.Traffic({
          autoRefresh: true,
          interval: 180,
          zIndex: 10,
        })
        map.add(trafficLayer)
        trafficLayerRef.current = trafficLayer
      }

      if (typeof AMap.TileLayer?.Satellite === 'function') {
        satelliteLayerRef.current = new AMap.TileLayer.Satellite({ zIndex: 6 })
        satelliteLayerRef.current.hide?.()
        map.add(satelliteLayerRef.current)
      }
      if (typeof AMap.TileLayer?.RoadNet === 'function') {
        roadNetLayerRef.current = new AMap.TileLayer.RoadNet({ zIndex: 7 })
        roadNetLayerRef.current.hide?.()
        map.add(roadNetLayerRef.current)
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
      trafficLayerRef.current = null
      satelliteLayerRef.current = null
      roadNetLayerRef.current = null
      liveOverlaysRef.current = new Map()
      digitalTwinGeometryRef.current = []
      digitalTwinCoverageRef.current = []
      digitalTwinVehiclesRef.current = new Map()
      digitalTwinContextRef.current = null
      digitalTwinFitKeyRef.current = null
      digitalTwinPixelProjectionRef.current = null
      mapRef.current?.destroy()
      mapRef.current = null
      amapRef.current = null
    }
  }, [renderedPoints, renderedSources, renderedSegments, selectedId, selectedSegmentId, selectedSourceId, onSelect, onSegmentSelect, onSourceSelect, offline, loadFailed, compact, markerType, fitToData, fitPadding, initialCenter, trafficMode])

  useEffect(() => {
    const trafficLayer = trafficLayerRef.current
    if (digitalTwinActive) trafficLayer?.hide?.()
    else trafficLayer?.show?.()
    if (digitalTwinActive) {
      satelliteLayerRef.current?.show?.()
      roadNetLayerRef.current?.show?.()
      mapRef.current?.setPitch?.(cameraPitchDeg(digitalTwin))
      mapRef.current?.setRotation?.(cameraMapRotationDeg(digitalTwin))
    } else {
      satelliteLayerRef.current?.hide?.()
      roadNetLayerRef.current?.hide?.()
      mapRef.current?.setPitch?.(0)
      mapRef.current?.setRotation?.(0)
    }
  }, [digitalTwinActive, digitalTwin?.level, digitalTwin?.pixelGroundProjection?.headingDeg, mapReadyToken])

  useEffect(() => {
    const map = mapRef.current
    const AMap = amapRef.current
    if (!map || !AMap) return undefined
    if (!trafficMode) {
      liveOverlaysRef.current.forEach(({ marker, trail }) => {
        removeMapOverlay(map, marker)
        removeMapOverlay(map, trail)
      })
      liveOverlaysRef.current.clear()
      return undefined
    }

    const nextIds = new Set(validLiveDrones.map((item) => item.id))
    liveOverlaysRef.current.forEach(({ marker, trail }, id) => {
      if (nextIds.has(id)) return
      removeMapOverlay(map, marker)
      removeMapOverlay(map, trail)
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
      const hideHoverCard = digitalTwinActive
      const content = liveDroneMarkerContent(item, (selectedItem) => liveSelectRef.current?.(selectedItem), selected, hideHoverCard)
      const markerZIndex = liveDroneMarkerZIndex(item, selected, digitalTwinActive)
      let entry = liveOverlaysRef.current.get(item.id)
      if (!entry) {
        const marker = new AMap.Marker({
          position,
          content,
          anchor: 'center',
          zIndex: markerZIndex,
          extData: { ...item, kind: 'live-drone' },
        })
        entry = { marker, trail: null, content, hideHoverCard }
        marker.on('mouseover', () => entry.content?.classList.add('hovered'))
        marker.on('mouseout', () => entry.content?.classList.remove('hovered'))
        map.add(marker)
        liveOverlaysRef.current.set(item.id, entry)
      } else {
        entry.marker.setPosition?.(position)
        const interacting = entry.content?.matches?.(':hover') || entry.content?.contains?.(document.activeElement)
        if (entry.hideHoverCard !== hideHoverCard || !interacting) {
          entry.content = content
          entry.marker.setContent?.(content)
          entry.hideHoverCard = hideHoverCard
        }
        entry.marker.setzIndex?.(markerZIndex)
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
    if (selectedEntry && fitToData && (!digitalTwinActive || !hasDigitalTwinSpatialContent) && typeof map.setFitView === 'function') {
      map.setFitView(selectedEntry.focusTrail ? [selectedEntry.marker, selectedEntry.trail] : [selectedEntry.marker], false, fitPadding, selectedEntry.focusTrail ? 16 : 13)
    }

    return undefined
  }, [validLiveDrones, trafficMode, mapReadyToken, selectedLiveDroneId, fitToData, fitPadding, digitalTwinActive, hasDigitalTwinSpatialContent])

  useEffect(() => {
    const map = mapRef.current
    const AMap = amapRef.current
    if (!map || !AMap) return
    digitalTwinGeometryRef.current.forEach((overlay) => removeMapOverlay(map, overlay))
    digitalTwinGeometryRef.current = []
    digitalTwinCoverageRef.current = []
    if (!digitalTwinActive) return

    const matched = new Set(matchedLaneKeys)
    const overlays = digitalTwinGeometry.flatMap((item) => {
      const isMatched = item.keys?.some((key) => matched.has(String(key)))
      if (item.type === 'polygon') {
        const overlay = new AMap.Polygon({
          path: item.path,
          strokeColor: item.kind === 'lane' ? '#58d6b0' : item.kind === 'coverage' ? '#ffca67' : '#c792ff',
          strokeWeight: isMatched ? 3.5 : 1.5,
          strokeOpacity: isMatched ? 1 : 0.7,
          fillColor: item.kind === 'lane' ? '#58d6b0' : item.kind === 'coverage' ? '#ffca67' : '#c792ff',
          fillOpacity: item.kind === 'coverage' ? 0.035 : isMatched ? 0.26 : 0.12,
          zIndex: item.kind === 'lane' ? 42 : item.kind === 'coverage' ? 28 : 32,
          extData: { kind: `digital-twin-${item.kind}`, source_id: item.id },
        })
        if (item.kind === 'coverage') digitalTwinCoverageRef.current.push(overlay)
        return [overlay]
      }
      const style = item.kind === 'lane'
        ? { strokeColor: isMatched ? '#ffca67' : '#58d6b0', strokeWeight: isMatched ? 4 : 2.2, zIndex: 46 }
        : item.kind === 'stop_line'
          ? { strokeColor: '#ff715b', strokeWeight: 4.5, zIndex: 48 }
          : { strokeColor: '#5ad3e7', strokeWeight: 4, zIndex: 38 }
      return [new AMap.Polyline({
        path: item.path,
        ...style,
        strokeOpacity: isMatched ? 1 : 0.82,
        lineJoin: 'round',
        lineCap: 'round',
        extData: { kind: `digital-twin-${item.kind}`, source_id: item.id },
      })]
    })
    if (overlays.length) map.add(overlays)
    digitalTwinGeometryRef.current = overlays
  }, [digitalTwinActive, digitalTwinGeometrySignature, mapReadyToken])

  useEffect(() => {
    const map = mapRef.current
    const AMap = amapRef.current
    if (!map || !AMap) return
    const entries = digitalTwinVehiclesRef.current
    const clearVehicles = () => {
      entries.forEach(({ marker, trail }) => {
        removeMapOverlay(map, marker)
        removeMapOverlay(map, trail)
      })
      entries.clear()
    }

    if (!digitalTwinActive) {
      clearVehicles()
      digitalTwinContextRef.current = null
      digitalTwinFitKeyRef.current = null
      digitalTwinPixelProjectionRef.current = null
      return
    }
    if (digitalTwinContextRef.current !== digitalTwin.contextKey) {
      clearVehicles()
      digitalTwinContextRef.current = digitalTwin.contextKey
      digitalTwinFitKeyRef.current = null
      digitalTwinPixelProjectionRef.current = digitalTwin.pixelGroundProjection || null
    }

    if (digitalTwin.pixelGroundProjection) digitalTwinPixelProjectionRef.current = digitalTwin.pixelGroundProjection
    const vehicles = [
      ...(digitalTwin.vehicles || []),
      ...(digitalTwin.pixelVehicles || []).map((item) => ({ ...item, simulated: true })),
    ]
    const nextIds = new Set(vehicles.map((item) => item.id))
    entries.forEach((entry, id) => {
      if (nextIds.has(id)) return
      entry.misses = (entry.misses || 0) + 1
      if (entry.misses < 2) return
      removeMapOverlay(map, entry.marker)
      removeMapOverlay(map, entry.trail)
      entries.delete(id)
    })

    const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches === true
    vehicles.forEach((item) => {
      const path = item.simulated
        ? projectPixelTrajectory(item.trajectory_px, digitalTwinPixelProjectionRef.current)
        : item.trajectory_gcj02
      if (!validPath(path)) return
      const position = path.at(-1)
      let entry = entries.get(item.id)
      const geographicHeading = trajectoryHeadingDeg(path)
      const screenHeading = Number.isFinite(geographicHeading)
        ? normalizedHeading(geographicHeading + cameraMapRotationDeg(digitalTwin))
        : null
      const headingDeg = continuousHeadingDeg(screenHeading, entry?.lastHeading)
      const content = vehicleMarkerContent(item, headingDeg)
      if (!entry) {
        const marker = new AMap.Marker({
          position,
          content,
          anchor: 'center',
          zIndex: 620,
          extData: { ...item, kind: item.simulated ? 'digital-twin-simulated-vehicle' : 'digital-twin-vehicle', simulation_basis: item.simulated ? 'trajectory_px' : null },
        })
        const trail = new AMap.Polyline({
          path,
          strokeColor: vehicleColors[String(item.yolo_class_name || item.vehicle_class || '').toLowerCase()] || vehicleColors.vehicle,
          strokeWeight: 2,
          strokeOpacity: 0.52,
          lineJoin: 'round',
          lineCap: 'round',
          zIndex: 590,
          extData: { track_id: item.track_id, kind: item.simulated ? 'digital-twin-simulated-vehicle-trail' : 'digital-twin-vehicle-trail', simulation_basis: item.simulated ? 'trajectory_px' : null },
        })
        map.add([trail, marker])
        entry = { marker, trail, misses: 0, lastPosition: position, lastHeading: headingDeg }
        entries.set(item.id, entry)
      } else {
        const moved = entry.lastPosition?.[0] !== position[0] || entry.lastPosition?.[1] !== position[1]
        if (moved) {
          if (!reducedMotion && typeof entry.marker.moveTo === 'function') {
            entry.marker.moveTo(position, { duration: 900, autoRotation: false })
          } else {
            entry.marker.setPosition?.(position)
          }
          entry.lastPosition = position
        }
        entry.marker.setContent?.(content)
        entry.trail.setPath?.(path)
        entry.misses = 0
        entry.lastHeading = headingDeg
      }
    })

    // One selected task owns one stable observation viewport. Stats and
    // telemetry polling may change level, map metadata or the approximate
    // footprint centre; none of those updates may continuously move the map.
    const fitKey = digitalTwin.contextKey
    if (fitToData && digitalTwinFitKeyRef.current !== fitKey && typeof map.setFitView === 'function') {
      const fitOverlays = digitalTwin?.level === 'bev_pixel' && !usesVerifiedWorldCamera(digitalTwin)
        ? digitalTwinCoverageRef.current
        : [...entries.values()].map(({ marker }) => marker)
      if (fitOverlays.length) {
        map.setFitView(fitOverlays, true, fitPadding, 19)
        focusSelectedDrone()
        digitalTwinFitKeyRef.current = fitKey
      }
    }
  }, [digitalTwin, digitalTwinActive, fitToData, fitPadding, focusSelectedDrone, mapReadyToken])

  if (offline || loadFailed) return <div className='map-offline'><WarningCircle size={38} weight='duotone' /><strong>高德地图服务不可用</strong><span>保留 KPI、重点关注榜和路口列表；不使用随机点位冒充真实地图。</span>{!offline && <button className='secondary-button' onClick={() => setLoadFailed(false)}>重试底图</button>}</div>

  return <div className={`city-map ${compact ? 'compact' : ''}${digitalTwinActive ? ` digital-twin-mode ${digitalTwin?.level || 'unavailable'}` : ''}`}>
    <div ref={targetRef} className='amap-canvas' />
    {digitalTwinActive && <div className='digital-twin-map-grid' aria-hidden='true' />}
    {showHeat && <img className='map-heat-overlay' src='/assets/bev-intersection-night.png' alt='风险热区空间分布底图' />}
    <div className={`map-demo-label${digitalTwinActive ? ` digital-twin-active ${digitalTwin?.level || 'unavailable'}` : ''}`}><MapPin size={13} weight='fill' /> {digitalTwinActive ? digitalTwin.label : coordinateLabel}</div>
    <div className='map-controls'><button onClick={() => mapRef.current?.zoomIn()} aria-label='放大'><Plus size={18} /></button><button onClick={() => mapRef.current?.zoomOut()} aria-label='缩小'><Minus size={18} /></button><button onClick={resetViewport} aria-label='复位'><Crosshair size={18} /></button></div>
    <div className='map-attribution'>{digitalTwinActive ? digitalTwin.level === 'bev_pixel' ? `高德卫星影像 · 镜头跟随 ${Math.round(normalizedHeading(digitalTwin?.pixelGroundProjection?.headingDeg || 0))}° · 3D 倾斜 · ${digitalTwin.dataMode === 'preview' ? '前端 Mock 预览' : digitalTwin.dataMode === 'controlled_replay' ? '可控回放' : '实时检测'}` : `高德卫星影像 · 道路标注 · 3D 数字孪生 · ${digitalTwin.dataMode === 'controlled_replay' ? '可控回放' : '实时检测'}` : trafficMode ? '高德实时路况 · GCJ-02' : '高德地图 · GCJ-02'}</div>
  </div>
}
