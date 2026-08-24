const OFFICIAL_ROAD_STATUSES = new Set(['lane_verified', 'link_verified'])

function finite(value) {
  return value != null && value !== '' && Number.isFinite(Number(value))
}

function coordinate(point) {
  return Array.isArray(point)
    && point.length >= 2
    && finite(point[0])
    && finite(point[1])
    && Math.abs(Number(point[0])) <= 180
    && Math.abs(Number(point[1])) <= 90
    ? [Number(point[0]), Number(point[1])]
    : null
}

function path(points) {
  if (!Array.isArray(points)) return []
  const parsed = points.map(coordinate)
  return parsed.every(Boolean) ? parsed : []
}

function trajectoryTail(points) {
  if (!Array.isArray(points)) return []
  const tail = []
  for (let index = points.length - 1; index >= 0; index -= 1) {
    const parsed = coordinate(points[index])
    if (!parsed) break
    tail.push(parsed)
  }
  return tail.reverse()
}

function geometryOf(value) {
  if (!value || typeof value !== 'object') return null
  return value.type && Array.isArray(value.coordinates) ? value : value.geometry
}

function geometryEntries(group) {
  if (Array.isArray(group)) return group.map((value, index) => [String(index), value])
  if (!group || typeof group !== 'object') return []
  return Object.entries(group)
}

function renderableGeometry(id, value, kind, keys = []) {
  const geometry = geometryOf(value)
  if (!geometry) return []
  const identity = [...new Set([id, ...keys].filter(Boolean).map(String))]
  if (geometry.type === 'LineString') {
    const line = path(geometry.coordinates)
    return line.length >= 2 ? [{ id: `${kind}:${id}`, kind, type: 'line', path: line, keys: identity }] : []
  }
  if (geometry.type === 'MultiLineString') {
    return geometry.coordinates.flatMap((points, index) => {
      const line = path(points)
      return line.length >= 2 ? [{ id: `${kind}:${id}:${index}`, kind, type: 'line', path: line, keys: identity }] : []
    })
  }
  if (geometry.type === 'Polygon') {
    const ring = path(geometry.coordinates?.[0])
    return ring.length >= 3 ? [{ id: `${kind}:${id}`, kind, type: 'polygon', path: ring, keys: identity }] : []
  }
  if (geometry.type === 'MultiPolygon') {
    return geometry.coordinates.flatMap((polygon, index) => {
      const ring = path(polygon?.[0])
      return ring.length >= 3 ? [{ id: `${kind}:${id}:${index}`, kind, type: 'polygon', path: ring, keys: identity }] : []
    })
  }
  return []
}

function dedupe(items) {
  const seen = new Set()
  return items.filter((item) => {
    const signature = `${item.kind}:${item.type}:${JSON.stringify(item.path)}`
    if (seen.has(signature)) return false
    seen.add(signature)
    return true
  })
}

function collectGroup(group, kind) {
  return geometryEntries(group).flatMap(([id, value]) => renderableGeometry(id, value, kind))
}

function collectVerifiedLanes(mapVersion) {
  if (mapVersion?.status !== 'lane_verified') return []
  const bindings = (Array.isArray(mapVersion.lanes) ? mapVersion.lanes : []).flatMap((lane, index) => {
    if (lane?.status && lane.status !== 'lane_verified') return []
    return renderableGeometry(
      lane.local_lane_id || `binding-${index}`,
      lane.geometry_gcj02,
      'lane',
      [lane.local_lane_id, lane.source_lane_id, lane.link_id],
    )
  })
  const geometry = mapVersion.geometry_gcj02 || {}
  return dedupe([
    ...bindings,
    ...collectGroup(geometry.lanes, 'lane'),
    ...collectGroup(geometry.lane_polygons, 'lane'),
  ])
}

function collectRoadLayers(mapVersion) {
  if (!OFFICIAL_ROAD_STATUSES.has(mapVersion?.status)) return { links: [], stopLines: [], areas: [] }
  const geometry = mapVersion.geometry_gcj02 || {}
  const featureEntries = geometryEntries(geometry.features)
  const stopLines = []
  const areas = [
    ...collectGroup(geometry.areas, 'area'),
    ...collectGroup(geometry.channelized_areas, 'area'),
  ]
  featureEntries.forEach(([id, value]) => {
    const featureType = String(value?.feature_type || value?.properties?.feature_type || '').toLowerCase()
    const rendered = renderableGeometry(id, value, featureType === 'stop_line' ? 'stop_line' : 'area')
    if (featureType === 'stop_line') stopLines.push(...rendered.filter((item) => item.type === 'line'))
    else areas.push(...rendered.filter((item) => item.type === 'polygon'))
  })
  return {
    links: dedupe(collectGroup(geometry.links, 'link')),
    stopLines: dedupe(stopLines),
    areas: dedupe(areas),
  }
}

export function normalizeActiveVehicleTracks(stats) {
  const active = Array.isArray(stats?.active_trajectories) ? stats.active_trajectories : []
  return active.flatMap((item, index) => {
    if (!item || item.trajectory_output_eligible === false) return []
    const gcj02Path = trajectoryTail(item.trajectory_gcj02)
    const pixelPath = Array.isArray(item.trajectory_px)
      ? item.trajectory_px.filter((point) => Array.isArray(point) && point.length >= 2 && finite(point[0]) && finite(point[1])).map(([x, y]) => [Number(x), Number(y)])
      : []
    if (gcj02Path.length < 2 && pixelPath.length < 2) return []
    const trackId = item.track_id ?? item.association_id ?? index
    return [{
      id: String(trackId),
      track_id: trackId,
      vehicle_class: item.vehicle_class || item.yolo_class_name || 'vehicle',
      yolo_class_name: item.yolo_class_name || null,
      avg_speed_kmh: finite(item.avg_speed_kmh) ? Number(item.avg_speed_kmh) : null,
      direction_class: item.direction_class || null,
      matched_lane_key: item.matched_lane_key || item.source_lane_id || null,
      matched_link_id: item.matched_link_id || null,
      trajectory_gcj02: gcj02Path,
      trajectory_px: pixelPath,
    }]
  }).slice(0, 200)
}

function inferredPixelFrame(vehicles) {
  const points = vehicles.flatMap((item) => item.trajectory_px || [])
  if (!points.length) return null
  const maxX = Math.max(...points.map(([x]) => Number(x)))
  const maxY = Math.max(...points.map(([, y]) => Number(y)))
  return [[960, 540], [1920, 1080], [2560, 1440], [3840, 2160], [4096, 2304]]
    .find(([width, height]) => maxX <= width && maxY <= height)
    || [Math.ceil(maxX), Math.ceil(maxY)]
}

function rotateGroundOffset(rightM, downM, headingDeg) {
  const heading = Number(headingDeg) * Math.PI / 180
  return {
    eastM: rightM * Math.cos(heading) - downM * Math.sin(heading),
    northM: -rightM * Math.sin(heading) - downM * Math.cos(heading),
  }
}

function offsetGcj02([lon, lat], eastM, northM) {
  const metersPerLon = 111320 * Math.cos(Number(lat) * Math.PI / 180)
  return [Number(lon) + eastM / metersPerLon, Number(lat) + northM / 110540]
}

export function projectPixelPointToGcj02(point, projection) {
  if (!projection || !Array.isArray(point)) return null
  const [width, height] = projection.frameSize
  const x = Math.min(width, Math.max(0, Number(point[0])))
  const y = Math.min(height, Math.max(0, Number(point[1])))
  const rightM = (x / width - 0.5) * projection.widthM
  const downM = (y / height - 0.5) * projection.heightM
  const { eastM, northM } = rotateGroundOffset(rightM, downM, projection.headingDeg)
  return offsetGcj02(projection.center, eastM, northM)
}

export function buildPixelGroundProjection(selectedDrone, vehicles) {
  const lon = Number(selectedDrone?.lon)
  const lat = Number(selectedDrone?.lat)
  const altitudeM = Number(selectedDrone?.altitude_m)
  const gimbalPitchDeg = Number(selectedDrone?.gimbal_pitch_deg)
  const headingDeg = Number(selectedDrone?.gimbal_yaw_deg ?? selectedDrone?.heading_deg)
  const frameSize = inferredPixelFrame(vehicles)
  if (![lon, lat, altitudeM, gimbalPitchDeg, headingDeg].every(Number.isFinite) || altitudeM <= 0 || !frameSize) return null
  if (Math.abs(Math.abs(gimbalPitchDeg) - 90) > 10) return null
  const focalLengthMm = Number(selectedDrone?.focal_length_mm) || 4.5
  // Canonical SRT telemetry stores zoom_factor as 1 / dzoom_ratio. Match the
  // survey-geometry contract so values below 1 narrow, rather than enlarge,
  // the ground footprint.
  const zoomFactor = Number(selectedDrone?.camera_zoom_factor) > 0
    ? Number(selectedDrone.camera_zoom_factor)
    : 1
  const effectiveFocalMm = focalLengthMm / zoomFactor
  const sensorWidthMm = 6.4
  const sensorHeightMm = 3.6
  const widthM = 2 * altitudeM * Math.tan(Math.atan(sensorWidthMm / (2 * effectiveFocalMm)))
  const heightM = 2 * altitudeM * Math.tan(Math.atan(sensorHeightMm / (2 * effectiveFocalMm)))
  const projection = {
    center: [lon, lat], altitudeM, headingDeg, gimbalPitchDeg,
    widthM, heightM, frameSize,
    basis: 'telemetry_camera_footprint_approximate',
  }
  projection.corners = [[0, 0], [frameSize[0], 0], [frameSize[0], frameSize[1]], [0, frameSize[1]]]
    .map((point) => projectPixelPointToGcj02(point, projection))
  return projection
}

export function selectDigitalTwinMap(items) {
  if (!Array.isArray(items)) return null
  return items.find((item) => item?.status === 'lane_verified')
    || items.find((item) => item?.status === 'link_verified')
    || null
}

export function buildDashboardDigitalTwin({ stats, mapVersion, selectedDrone }) {
  const vehicles = normalizeActiveVehicleTracks(stats)
  const spatialVehicles = vehicles.filter((item) => item.trajectory_gcj02.length >= 2)
  const pixelVehicles = vehicles.filter((item) => item.trajectory_gcj02.length < 2 && item.trajectory_px.length >= 2)
  const pixelGroundProjection = buildPixelGroundProjection(selectedDrone, pixelVehicles)
  const lanes = collectVerifiedLanes(mapVersion)
  const { links, stopLines, areas } = collectRoadLayers(mapVersion)
  const reasons = []

  if (!vehicles.length) reasons.push('active_trajectories_missing')
  if (vehicles.length && !spatialVehicles.length) reasons.push('vehicle_world_coordinates_missing')
  if (!OFFICIAL_ROAD_STATUSES.has(mapVersion?.status)) reasons.push('verified_map_missing')
  if (!lanes.length) reasons.push('verified_lane_geometry_missing')
  if (!links.length) reasons.push('verified_link_geometry_missing')

  let level = 'unavailable'
  if (spatialVehicles.length && lanes.length) level = 'lane'
  else if (spatialVehicles.length && links.length) level = 'road'
  else if (spatialVehicles.length) level = 'spatial'
  else if (pixelVehicles.length) level = 'bev_pixel'

  const labels = {
    lane: `车道级 · Lane ${lanes.length} · 活跃车辆 ${spatialVehicles.length}`,
    road: `道路级 · Link ${links.length} · 活跃车辆 ${spatialVehicles.length}`,
    spatial: `空间轨迹 · GCJ-02 · 活跃车辆 ${spatialVehicles.length}`,
    bev_pixel: pixelGroundProjection
      ? `3D 覆盖仿真 · 约 ${Math.round(pixelGroundProjection.widthM)}×${Math.round(pixelGroundProjection.heightM)}m · 活跃车辆 ${pixelVehicles.length}`
      : `像素轨迹 · 缺少 3D 覆盖参数 · 活跃车辆 ${pixelVehicles.length}`,
    unavailable: '等待 BEV 车辆轨迹',
  }

  return {
    active: Boolean(selectedDrone),
    contextKey: selectedDrone ? `${selectedDrone.pipeline_id || 'no-pipeline'}:${selectedDrone.intersection_id || 'no-intersection'}` : null,
    level,
    label: labels[level],
    dataMode: selectedDrone?.is_preview ? 'preview' : selectedDrone?.is_replay ? 'controlled_replay' : 'live',
    reasons,
    availableLayers: {
      lanes: lanes.length > 0,
      links: links.length > 0,
      stopLines: stopLines.length > 0,
      areas: areas.length > 0,
      vehicles: spatialVehicles.length > 0 || pixelVehicles.length > 0,
      georeferencedVehicles: spatialVehicles.length > 0,
      simulatedVehicles: pixelVehicles.length > 0,
      cameraFootprint: Boolean(pixelGroundProjection),
      pixelVehicles: pixelVehicles.length > 0,
    },
    mapVersionId: mapVersion?.id || null,
    geometry: {
      lanes, links, stopLines, areas,
      coverage: pixelGroundProjection ? [{ id: 'camera-footprint', kind: 'coverage', type: 'polygon', path: pixelGroundProjection.corners, keys: [] }] : [],
    },
    vehicles: spatialVehicles,
    pixelVehicles,
    pixelGroundProjection,
  }
}
