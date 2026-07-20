import { useEffect, useRef, useState } from 'react'
import Map from 'ol/Map.js'
import View from 'ol/View.js'
import TileLayer from 'ol/layer/Tile.js'
import VectorLayer from 'ol/layer/Vector.js'
import OSM from 'ol/source/OSM.js'
import VectorSource from 'ol/source/Vector.js'
import Feature from 'ol/Feature.js'
import Point from 'ol/geom/Point.js'
import { fromLonLat } from 'ol/proj.js'
import { Circle as CircleStyle, Fill, Icon as IconStyle, Stroke, Style } from 'ol/style.js'
import { Crosshair, MapPin, Minus, Plus, WarningCircle } from '@phosphor-icons/react'
import 'ol/ol.css'

const colors = { critical: '#ff715b', warning: '#ffbe55', normal: '#5ad3e7' }
const sourceColors = { running: '#58d6b0', ready: '#5ad3e7', degraded: '#ffbe55', invalid: '#ff715b', disabled: '#8290aa' }

function droneDisplacement(item, points) {
  const nearby = points
    .filter((candidate) => Math.abs(candidate.lon - item.lon) <= 0.003 && Math.abs(candidate.lat - item.lat) <= 0.003)
    .sort((left, right) => String(left.id).localeCompare(String(right.id)))
  if (nearby.length < 2) return [0, 0]
  const angle = (Math.PI * 2 * nearby.findIndex((candidate) => candidate.id === item.id)) / nearby.length
  return [Math.round(Math.cos(angle) * 18), Math.round(Math.sin(angle) * 18)]
}

function droneMarker(color, selected, displacement) {
  const outline = selected ? '#ffffff' : '#0a101a'
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 40 40"><circle cx="8" cy="8" r="5" fill="#0a101a" stroke="${color}" stroke-width="2.5"/><circle cx="32" cy="8" r="5" fill="#0a101a" stroke="${color}" stroke-width="2.5"/><circle cx="8" cy="32" r="5" fill="#0a101a" stroke="${color}" stroke-width="2.5"/><circle cx="32" cy="32" r="5" fill="#0a101a" stroke="${color}" stroke-width="2.5"/><path d="M11.5 11.5L17 17M28.5 11.5L23 17M11.5 28.5L17 23M28.5 28.5L23 23" stroke="${color}" stroke-width="3" stroke-linecap="round"/><rect x="15" y="15" width="10" height="10" rx="3" fill="${color}" stroke="${outline}" stroke-width="2"/><circle cx="20" cy="20" r="2" fill="#ffffff"/></svg>`
  return new IconStyle({
    src: `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`,
    anchor: [0.5, 0.5],
    scale: selected ? 1 : 0.86,
    displacement,
  })
}

export function CityMap({ points, selectedId, onSelect, offline = false, compact = false, showHeat = false, coordinateLabel = '坐标来源未冻结', markerType = 'status' }) {
  const ref = useRef(null)
  const mapRef = useRef(null)
  const [zoom, setZoom] = useState(compact ? 12 : 12.4)
  const [tileFailed, setTileFailed] = useState(false)
  const validPoints = points.filter((item) => Number.isFinite(item.lon) && Number.isFinite(item.lat))
  const initialCenter = validPoints.length
    ? validPoints.reduce((center, item) => [center[0] + item.lon / validPoints.length, center[1] + item.lat / validPoints.length], [0, 0])
    : [117.085, 36.674]

  useEffect(() => {
    if (!ref.current || offline || tileFailed) return undefined
    const source = new VectorSource({
      features: points.map((item) => {
        const feature = new Feature({ geometry: new Point(fromLonLat([item.lon, item.lat])), item })
        feature.setId(item.id)
        return feature
      }),
    })
    const vector = new VectorLayer({
      source,
      style: (feature) => {
        const item = feature.get('item')
        const selected = item.id === selectedId
        const color = markerType === 'drone' && item.source_status ? sourceColors[item.source_status] || '#8290aa' : colors[item.risk] || '#8290aa'
        return new Style({
          image: markerType === 'drone' ? droneMarker(color, selected, droneDisplacement(item, points)) : new CircleStyle({
            radius: selected ? 12 : item.risk === 'critical' ? 10 : 8,
            fill: new Fill({ color: `${color}d9` }),
            stroke: new Stroke({ color: selected ? '#ffffff' : '#0a101a', width: selected ? 3 : 2 }),
          }),
        })
      },
    })
    const tileSource = new OSM()
    let tileErrors = 0
    tileSource.on('tileloaderror', () => {
      tileErrors += 1
      if (tileErrors >= 3) setTileFailed(true)
    })
    const tile = new TileLayer({ source: tileSource, className: 'dark-map-tiles' })
    const map = new Map({ target: ref.current, layers: [tile, vector], view: new View({ center: fromLonLat(initialCenter), zoom }) })
    map.on('singleclick', (event) => {
      map.forEachFeatureAtPixel(event.pixel, (feature) => { onSelect?.(feature.get('item')); return true })
    })
    mapRef.current = map
    return () => { map.setTarget(undefined); mapRef.current = null }
  }, [points, selectedId, onSelect, offline, tileFailed, markerType])

  useEffect(() => { if (mapRef.current) mapRef.current.getView().setZoom(zoom) }, [zoom])

  if (offline || tileFailed) return <div className='map-offline'><WarningCircle size={38} weight='duotone' /><strong>城市底图服务不可用</strong><span>保留 KPI、重点关注榜和路口列表；不使用随机点位冒充真实地图。</span>{!offline && <button className='secondary-button' onClick={() => setTileFailed(false)}>重试底图</button>}</div>

  return (
    <div className={`city-map ${compact ? 'compact' : ''}`}>
      <div ref={ref} className='ol-map' />
      {showHeat && <img className='map-heat-overlay' src='/assets/bev-intersection-night.png' alt='风险热区空间分布底图' />}
      <div className='map-demo-label'><MapPin size={13} weight='fill' /> {coordinateLabel}</div>
      <div className='map-controls'><button onClick={() => setZoom((value) => value + 1)} aria-label='放大'><Plus size={18} /></button><button onClick={() => setZoom((value) => value - 1)} aria-label='缩小'><Minus size={18} /></button><button onClick={() => { setZoom(compact ? 12 : 12.4); mapRef.current?.getView().setCenter(fromLonLat(initialCenter)) }} aria-label='复位'><Crosshair size={18} /></button></div>
      <div className='map-attribution'>© OpenStreetMap contributors · 开发底图</div>
    </div>
  )
}
