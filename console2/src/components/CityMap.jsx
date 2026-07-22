import { useEffect, useMemo, useRef, useState } from 'react'
import { Crosshair, MapPin, Minus, Plus, WarningCircle } from '@phosphor-icons/react'
import { loadAmap } from '../lib/amap'

const colors = { critical: '#ff715b', warning: '#ffbe55', normal: '#5ad3e7' }
const sourceColors = { running: '#58d6b0', ready: '#5ad3e7', degraded: '#ffbe55', invalid: '#ff715b', disabled: '#8290aa' }

function validPoint(item) {
  return Number.isFinite(Number(item?.lon)) && Number.isFinite(Number(item?.lat))
}

function markerContent(item, selected, markerType) {
  const color = markerType === 'drone' && item.source_status
    ? sourceColors[item.source_status] || '#8290aa'
    : colors[item.risk] || '#8290aa'
  const className = markerType === 'drone' ? 'amap-drone-marker' : 'amap-status-marker'
  return `<div class="${className}${selected ? ' selected' : ''}" style="--marker-color:${color}" aria-hidden="true"></div>`
}

export function CityMap({ points = [], selectedId, onSelect, offline = false, compact = false, showHeat = false, coordinateLabel = 'GCJ-02 坐标', markerType = 'status' }) {
  const targetRef = useRef(null)
  const mapRef = useRef(null)
  const overlaysRef = useRef([])
  const [loadFailed, setLoadFailed] = useState(false)
  const validPoints = useMemo(() => points.filter(validPoint), [points])
  const initialCenter = useMemo(() => validPoints.length
    ? validPoints.reduce((center, item) => [center[0] + Number(item.lon) / validPoints.length, center[1] + Number(item.lat) / validPoints.length], [0, 0])
    : [117.028285, 36.703222], [validPoints])

  useEffect(() => {
    let disposed = false
    if (!targetRef.current || offline || loadFailed) return undefined
    loadAmap().then((AMap) => {
      if (disposed || !targetRef.current) return
      const map = new AMap.Map(targetRef.current, {
        center: initialCenter, zoom: compact ? 12 : 12.4, mapStyle: 'amap://styles/darkblue', viewMode: '2D',
      })
      map.addControl(new AMap.Scale())
      const overlays = validPoints.map((item) => {
        const marker = new AMap.Marker({
          position: [Number(item.lon), Number(item.lat)],
          content: markerContent(item, item.id === selectedId, markerType),
          anchor: 'center', extData: item,
        })
        marker.on('click', () => onSelect?.(item))
        return marker
      })
      if (overlays.length) map.add(overlays)
      mapRef.current = map
      overlaysRef.current = overlays
    }).catch(() => { if (!disposed) setLoadFailed(true) })
    return () => {
      disposed = true
      overlaysRef.current = []
      mapRef.current?.destroy()
      mapRef.current = null
    }
  }, [validPoints, selectedId, onSelect, offline, loadFailed, compact, markerType, initialCenter])

  if (offline || loadFailed) return <div className='map-offline'><WarningCircle size={38} weight='duotone' /><strong>高德地图服务不可用</strong><span>保留 KPI、重点关注榜和路口列表；不使用随机点位冒充真实地图。</span>{!offline && <button className='secondary-button' onClick={() => setLoadFailed(false)}>重试底图</button>}</div>

  return <div className={`city-map ${compact ? 'compact' : ''}`}>
    <div ref={targetRef} className='amap-canvas' />
    {showHeat && <img className='map-heat-overlay' src='/assets/bev-intersection-night.png' alt='风险热区空间分布底图' />}
    <div className='map-demo-label'><MapPin size={13} weight='fill' /> {coordinateLabel}</div>
    <div className='map-controls'><button onClick={() => mapRef.current?.zoomIn()} aria-label='放大'><Plus size={18} /></button><button onClick={() => mapRef.current?.zoomOut()} aria-label='缩小'><Minus size={18} /></button><button onClick={() => mapRef.current?.setZoomAndCenter(compact ? 12 : 12.4, initialCenter)} aria-label='复位'><Crosshair size={18} /></button></div>
    <div className='map-attribution'>高德地图 · GCJ-02</div>
  </div>
}
