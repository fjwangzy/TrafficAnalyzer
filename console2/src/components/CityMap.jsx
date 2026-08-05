import { useEffect, useMemo, useRef, useState } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { Crosshair, Drone, MapPin, Minus, Plus, TrafficSignal, WarningCircle } from '@phosphor-icons/react'
import { loadAmap } from '../lib/amap'

const riskColors = { critical: '#ff715b', warning: '#ffbe55', normal: '#5ad3e7' }
const situationColors = { good: '#58d6b0', near_saturated: '#ffbe55', oversaturated: '#ff715b', missing: '#8290aa' }
const segmentColors = { smooth: '#58d6b0', slow: '#ffbe55', congested: '#ff715b', missing: '#8290aa' }
const sourceColors = { running: '#58d6b0', ready: '#5ad3e7', degraded: '#ffbe55', invalid: '#ff715b', disabled: '#8290aa' }

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

export function CityMap({
  points = [],
  segments = [],
  sourcePoints = [],
  selectedId,
  selectedSegmentId,
  selectedSourceId,
  onSelect,
  onSegmentSelect,
  onSourceSelect,
  offline = false,
  compact = false,
  showHeat = false,
  coordinateLabel = 'GCJ-02 坐标',
  markerType = 'status',
  fitToData = false,
}) {
  const targetRef = useRef(null)
  const mapRef = useRef(null)
  const overlaysRef = useRef([])
  const [loadFailed, setLoadFailed] = useState(false)
  const validPoints = useMemo(() => points.filter(validPoint), [points])
  const validSources = useMemo(() => sourcePoints.filter(validPoint), [sourcePoints])
  const centerPoints = useMemo(() => validPoints.length ? validPoints : validSources, [validPoints, validSources])
  const initialCenter = useMemo(() => centerPoints.length
    ? centerPoints.reduce((center, item) => [center[0] + Number(item.lon) / centerPoints.length, center[1] + Number(item.lat) / centerPoints.length], [0, 0])
    : [117.028285, 36.703222], [centerPoints])

  useEffect(() => {
    let disposed = false
    if (!targetRef.current || offline || loadFailed) return undefined
    loadAmap().then((AMap) => {
      if (disposed || !targetRef.current) return
      const map = new AMap.Map(targetRef.current, {
        center: initialCenter, zoom: compact ? 12 : 12.4, mapStyle: 'amap://styles/darkblue', viewMode: '2D',
      })
      map.addControl(new AMap.Scale())

      const segmentOverlays = segments.flatMap((segment) => (segment.paths_gcj02 || [])
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

      const pointOverlays = validPoints.map((item) => {
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

      const sourceOverlays = validSources.map((item) => {
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
          map.setFitView(overlays, false, [64, 76, 300, 60])
        }
      }
      mapRef.current = map
      overlaysRef.current = overlays
    }).catch(() => { if (!disposed) setLoadFailed(true) })
    return () => {
      disposed = true
      overlaysRef.current = []
      mapRef.current?.destroy()
      mapRef.current = null
    }
  }, [validPoints, validSources, segments, selectedId, selectedSegmentId, selectedSourceId, onSelect, onSegmentSelect, onSourceSelect, offline, loadFailed, compact, markerType, fitToData, initialCenter])

  if (offline || loadFailed) return <div className='map-offline'><WarningCircle size={38} weight='duotone' /><strong>高德地图服务不可用</strong><span>保留 KPI、重点关注榜和路口列表；不使用随机点位冒充真实地图。</span>{!offline && <button className='secondary-button' onClick={() => setLoadFailed(false)}>重试底图</button>}</div>

  return <div className={`city-map ${compact ? 'compact' : ''}`}>
    <div ref={targetRef} className='amap-canvas' />
    {showHeat && <img className='map-heat-overlay' src='/assets/bev-intersection-night.png' alt='风险热区空间分布底图' />}
    <div className='map-demo-label'><MapPin size={13} weight='fill' /> {coordinateLabel}</div>
    <div className='map-controls'><button onClick={() => mapRef.current?.zoomIn()} aria-label='放大'><Plus size={18} /></button><button onClick={() => mapRef.current?.zoomOut()} aria-label='缩小'><Minus size={18} /></button><button onClick={() => mapRef.current?.setZoomAndCenter(compact ? 12 : 12.4, initialCenter)} aria-label='复位'><Crosshair size={18} /></button></div>
    <div className='map-attribution'>高德地图 · GCJ-02</div>
  </div>
}
