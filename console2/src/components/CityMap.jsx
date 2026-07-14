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

export function CityMap({ points, selectedId, onSelect, offline = false, compact = false, showHeat = false }) {
  const ref = useRef(null)
  const mapRef = useRef(null)
  const [zoom, setZoom] = useState(compact ? 12 : 12.4)

  useEffect(() => {
    if (!ref.current || offline) return undefined
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
    const tile = new TileLayer({ source: new OSM(), className: 'dark-map-tiles' })
    const map = new Map({ target: ref.current, layers: [tile, vector], view: new View({ center: fromLonLat([117.085, 36.674]), zoom }) })
    map.on('singleclick', (event) => {
      map.forEachFeatureAtPixel(event.pixel, (feature) => { onSelect?.(feature.get('item')); return true })
    })
    mapRef.current = map
    return () => { map.setTarget(undefined); mapRef.current = null }
  }, [points, selectedId, onSelect, offline])

  useEffect(() => { if (mapRef.current) mapRef.current.getView().setZoom(zoom) }, [zoom])

  if (offline) return <div className='map-offline'><WarningCircle size={38} weight='duotone' /><strong>城市底图服务不可用</strong><span>保留 KPI、重点关注榜和路口列表；不使用随机点位冒充真实地图。</span></div>

  return (
    <div className={`city-map ${compact ? 'compact' : ''}`}>
      <div ref={ref} className='ol-map' />
      {showHeat && <img className='map-heat-overlay' src='/assets/bev-intersection-night.png' alt='风险热区空间分布底图' />}
      <div className='map-demo-label'><MapPin size={13} weight='fill' /> 演示坐标 · GCJ02 语义待权威源冻结</div>
      <div className='map-controls'><button onClick={() => setZoom((value) => value + 1)} aria-label='放大'><Plus size={18} /></button><button onClick={() => setZoom((value) => value - 1)} aria-label='缩小'><Minus size={18} /></button><button onClick={() => { setZoom(compact ? 12 : 12.4); mapRef.current?.getView().setCenter(fromLonLat([117.085, 36.674])) }} aria-label='复位'><Crosshair size={18} /></button></div>
      <div className='map-attribution'>© OpenStreetMap contributors · 原型演示</div>
    </div>
  )
}
