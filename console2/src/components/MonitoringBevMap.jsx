import { useEffect, useRef } from 'react'
import Feature from 'ol/Feature.js'
import Map from 'ol/Map.js'
import View from 'ol/View.js'
import Point from 'ol/geom/Point.js'
import LineString from 'ol/geom/LineString.js'
import TileLayer from 'ol/layer/Tile.js'
import VectorLayer from 'ol/layer/Vector.js'
import { fromLonLat } from 'ol/proj.js'
import OSM from 'ol/source/OSM.js'
import VectorSource from 'ol/source/Vector.js'
import { Circle as CircleStyle, Fill, Stroke, Style } from 'ol/style.js'
import 'ol/ol.css'

const DEFAULT_CENTER = { lat: 36.7029, lon: 117.0223 }
const TRACK_COLORS = ['#63b3ff', '#ff806b', '#58d6b0', '#c792ff', '#ffca67']

const finite = (value) => Number.isFinite(Number(value))

export function validMapCenter(lat, lon) {
  return finite(lat) && finite(lon) && Math.abs(Number(lat)) <= 90 && Math.abs(Number(lon)) <= 180 && (Number(lat) !== 0 || Number(lon) !== 0)
    ? { lat: Number(lat), lon: Number(lon) }
    : DEFAULT_CENTER
}

export function worldToLonLat(easting, northing, anchorLat, anchorLon) {
  const lat = Number(anchorLat) + Number(northing) / 111_320
  const lon = Number(anchorLon) + Number(easting) / (111_320 * Math.cos((Number(anchorLat) * Math.PI) / 180))
  return [lon, lat]
}

export function trajectoryLonLats(item, fallbackLat, fallbackLon) {
  const points = Array.isArray(item?.trajectory_world_m) ? item.trajectory_world_m : []
  const anchor = Array.isArray(item?.world_anchor_lat_lon) && item.world_anchor_lat_lon.length >= 2
    ? item.world_anchor_lat_lon
    : [fallbackLat, fallbackLon]
  const anchorCenter = validMapCenter(anchor[0], anchor[1])
  return points
    .filter((point) => Array.isArray(point) && point.length >= 2 && finite(point[0]) && finite(point[1]))
    .map(([easting, northing]) => worldToLonLat(easting, northing, anchorCenter.lat, anchorCenter.lon))
}

const lineStyle = (feature) => {
  const color = TRACK_COLORS[Number(feature.get('color_index') || 0) % TRACK_COLORS.length]
  return new Style({
    stroke: new Stroke({ color, width: feature.get('active') ? 3.5 : 2.5 }),
  })
}

const pointStyle = (feature) => {
  const color = TRACK_COLORS[Number(feature.get('color_index') || 0) % TRACK_COLORS.length]
  return new Style({
    image: new CircleStyle({
      radius: feature.get('center') ? 7 : 4.5,
      fill: new Fill({ color: feature.get('center') ? 'rgba(255,113,91,.26)' : color }),
      stroke: new Stroke({ color: feature.get('center') ? '#ff806b' : '#eef6ff', width: feature.get('center') ? 2 : 1.4 }),
    }),
  })
}

export function MonitoringBevMap({ centerLat, centerLon, trajectories = [], activeCount = 0, compact = false, label }) {
  const targetRef = useRef(null)
  const mapRef = useRef(null)
  const trackSourceRef = useRef(new VectorSource())
  const centerSourceRef = useRef(new VectorSource())
  const center = validMapCenter(centerLat, centerLon)

  useEffect(() => {
    if (!targetRef.current) return undefined

    const tileLayer = new TileLayer({ source: new OSM(), className: 'monitoring-map-tiles' })
    const trackLayer = new VectorLayer({ source: trackSourceRef.current, style: lineStyle, zIndex: 20 })
    const pointLayer = new VectorLayer({ source: centerSourceRef.current, style: pointStyle, zIndex: 30 })
    const map = new Map({
      target: targetRef.current,
      layers: [tileLayer, trackLayer, pointLayer],
      view: new View({ center: fromLonLat([center.lon, center.lat]), zoom: compact ? 18 : 19, minZoom: 15, maxZoom: 22 }),
      controls: [],
    })
    mapRef.current = map
    return () => {
      map.setTarget(undefined)
      mapRef.current = null
    }
  }, [compact])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    map.getView().setCenter(fromLonLat([center.lon, center.lat]))
  }, [center.lat, center.lon])

  useEffect(() => {
    const lineSource = trackSourceRef.current
    const markerSource = centerSourceRef.current
    lineSource.clear()
    markerSource.clear()
    markerSource.addFeature(new Feature({ geometry: new Point(fromLonLat([center.lon, center.lat])), center: true }))

    trajectories.forEach((item, index) => {
      const coords = trajectoryLonLats(item, center.lat, center.lon).map((coordinate) => fromLonLat(coordinate))
      if (!coords.length) return
      if (coords.length >= 2) {
        lineSource.addFeature(new Feature({
          geometry: new LineString(coords),
          color_index: index,
          active: index < activeCount,
          track_id: item.track_id,
        }))
      }
      markerSource.addFeature(new Feature({ geometry: new Point(coords.at(-1)), color_index: index, track_id: item.track_id }))
    })

    const map = mapRef.current
    if (map && lineSource.getFeatures().length) {
      map.getView().fit(lineSource.getExtent(), { padding: compact ? [12, 12, 12, 12] : [150, 390, 120, 350], maxZoom: compact ? 19 : 20, duration: 350 })
    }
  }, [trajectories, activeCount, center.lat, center.lon, compact])

  return <div className={`monitoring-bev-map ${compact ? 'compact' : 'main'}`} role='img' aria-label={label || (compact ? 'BEV 地图轨迹投放图' : 'BEV 地图轨迹主视图')}>
    <div ref={targetRef} className='monitoring-bev-map-canvas' />
    <div className='monitoring-bev-grid' />
    <div className='monitoring-bev-source'>OSM MAP · ENU WORLD</div>
    <div className='monitoring-bev-attribution'>© OpenStreetMap contributors</div>
  </div>
}
