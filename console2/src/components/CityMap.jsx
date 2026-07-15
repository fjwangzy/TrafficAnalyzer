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
import { Circle as CircleStyle, Fill, Stroke, Style } from 'ol/style.js'
import { Crosshair, MapPin, Minus, Plus, WarningCircle } from '@phosphor-icons/react'
import 'ol/ol.css'

const colors = { critical: '#ff715b', warning: '#ffbe55', normal: '#5ad3e7' }

export function CityMap({ points, selectedId, onSelect, offline = false, compact = false, showHeat = false, coordinateLabel = '坐标来源未冻结' }) {
  const ref = useRef(null)
  const mapRef = useRef(null)
  const [zoom, setZoom] = useState(compact ? 12 : 12.4)
  const [tileFailed, setTileFailed] = useState(false)
  const firstPoint = points.find((item) => Number.isFinite(item.lon) && Number.isFinite(item.lat))
  const initialCenter = firstPoint ? [firstPoint.lon, firstPoint.lat] : [117.085, 36.674]

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
        return new Style({
          image: new CircleStyle({
            radius: selected ? 12 : item.risk === 'critical' ? 10 : 8,
            fill: new Fill({ color: `${colors[item.risk] || '#8290aa'}d9` }),
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
  }, [points, selectedId, onSelect, offline, tileFailed])

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
