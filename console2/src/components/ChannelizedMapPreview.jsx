import { useEffect, useMemo, useRef, useState } from 'react'
import { WarningCircle } from '@phosphor-icons/react'
import { loadAmap } from '../lib/amap'

function geometries(group) {
  if (!group || typeof group !== 'object') return []
  return Object.entries(group).filter(([, geometry]) => geometry?.type && Array.isArray(geometry.coordinates))
}

export function ChannelizedMapPreview({ mapVersion }) {
  const targetRef = useRef(null)
  const mapRef = useRef(null)
  const [error, setError] = useState('')
  const anchor = useMemo(() => mapVersion?.anchor_gcj02 || [117.028285, 36.703222], [mapVersion])

  useEffect(() => {
    let disposed = false
    if (!targetRef.current || !mapVersion) return undefined
    loadAmap().then((AMap) => {
      if (disposed || !targetRef.current) return
      const map = new AMap.Map(targetRef.current, {
        center: anchor,
        zoom: 19,
        mapStyle: 'amap://styles/darkblue',
        viewMode: '2D',
      })
      const geometry = mapVersion.geometry_gcj02 || {}
      const overlays = []
      const imageLayers = []
      const registration = mapVersion.visual_registration || {}
      const imageBounds = registration.orthophoto_bounds_gcj02
      if (registration.orthophoto_url && Array.isArray(imageBounds) && imageBounds.length === 2) {
        imageLayers.push(new AMap.ImageLayer({
          url: registration.orthophoto_url,
          bounds: new AMap.Bounds(imageBounds[0], imageBounds[1]),
          opacity: 0.72,
          zIndex: 5,
        }))
      }
      for (const [, item] of geometries(geometry.links)) {
        if (item.type === 'LineString') overlays.push(new AMap.Polyline({ path: item.coordinates, strokeColor: '#5ad3e7', strokeWeight: 4, strokeOpacity: 0.85 }))
      }
      for (const [, item] of [
        ...geometries(geometry.lane_candidates),
        ...geometries(geometry.lanes),
        ...geometries(geometry.lane_polygons),
      ]) {
        if (item.type === 'LineString') overlays.push(new AMap.Polyline({ path: item.coordinates, strokeColor: '#ffbe55', strokeWeight: 2, strokeOpacity: 0.8 }))
        if (item.type === 'Polygon') overlays.push(new AMap.Polygon({ path: item.coordinates[0], strokeColor: '#58d6b0', strokeWeight: 2, fillColor: '#58d6b0', fillOpacity: 0.22 }))
      }
      for (const feature of Object.values(geometry.features || {})) {
        const item = feature?.geometry
        if (item?.type === 'LineString') overlays.push(new AMap.Polyline({ path: item.coordinates, strokeColor: feature.feature_type === 'stop_line' ? '#ff4d5a' : '#f3f6ff', strokeWeight: feature.feature_type === 'stop_line' ? 5 : 2, strokeOpacity: 0.95, zIndex: 30 }))
        if (item?.type === 'Polygon') overlays.push(new AMap.Polygon({ path: item.coordinates[0], strokeColor: '#d68cff', strokeWeight: 2, fillColor: '#d68cff', fillOpacity: 0.24, zIndex: 20 }))
      }
      if (imageLayers.length || overlays.length) {
        map.add([...imageLayers, ...overlays])
      }
      if (overlays.length) {
        map.setFitView(overlays, false, [40, 40, 40, 40], 19)
      }
      mapRef.current = map
    }).catch((reason) => { if (!disposed) setError(reason?.message || '高德地图加载失败') })
    return () => {
      disposed = true
      mapRef.current?.destroy()
      mapRef.current = null
    }
  }, [mapVersion, anchor])

  if (!mapVersion) return <div className='live-state empty'>输入路口 ID 后加载本地地图；仅本地无数据时从 YCX 只读按需导入。</div>
  if (error) return <div className='map-offline'><WarningCircle size={32} /><strong>{error}</strong></div>
  return <div className='channelized-map-preview'>
    <div ref={targetRef} className='amap-canvas' />
    <div className='map-demo-label'>GCJ-02 · {mapVersion.status}</div>
    <div className='map-attribution'>高德地图 · YCX 候选仅供拟合参考</div>
  </div>
}
