export const emptyLaneSelection = Object.freeze({ mode: 'none', laneIds: [], linkId: null })

export function selectLaneDraft(lanes, laneId, mode = 'link') {
  const target = lanes.find((lane) => lane.local_lane_id === laneId)
  if (!target) return emptyLaneSelection
  const laneIds = mode === 'link' && target.link_id
    ? lanes.filter((lane) => lane.link_id === target.link_id).map((lane) => lane.local_lane_id)
    : [target.local_lane_id]
  return {
    mode: mode === 'link' ? 'link' : 'lane',
    laneIds,
    linkId: target.link_id || null,
  }
}

export function adoptLaneDrafts(drafts, references, selection) {
  const selectedIds = new Set(selection.laneIds)
  const existingIds = new Set(drafts.map((lane) => lane.local_lane_id))
  const adopted = references
    .filter((lane) => selectedIds.has(lane.local_lane_id) && !existingIds.has(lane.local_lane_id))
    .map((lane) => ({
      local_lane_id: lane.local_lane_id,
      source_lane_id: lane.source_lane_id,
      link_id: lane.link_id,
      direction: lane.direction || 'straight',
      points: lane.points.map((point) => [...point]),
    }))
  return adopted.length ? [...drafts, ...adopted] : drafts
}

export function deleteLaneDrafts(drafts, selection) {
  const selectedIds = new Set(selection.laneIds)
  return drafts.filter((lane) => !selectedIds.has(lane.local_lane_id))
}

function samePoint(left, right) {
  return Math.abs(left[0] - right[0]) < 1e-6 && Math.abs(left[1] - right[1]) < 1e-6
}

function normalizePolygon(points) {
  const normalized = points.reduce((items, point) => {
    if (!items.length || !samePoint(items.at(-1), point)) items.push([...point])
    return items
  }, [])
  if (normalized.length > 1 && samePoint(normalized[0], normalized.at(-1))) normalized.pop()
  return normalized
}

function clipPolygon(points, axis, offset, keepLower) {
  const value = (point) => point[0] * axis[0] + point[1] * axis[1] - offset
  const inside = (point) => keepLower ? value(point) <= 1e-6 : value(point) >= -1e-6
  const output = []
  for (let index = 0; index < points.length; index += 1) {
    const current = points[index]
    const previous = points[(index + points.length - 1) % points.length]
    const currentInside = inside(current)
    const previousInside = inside(previous)
    if (currentInside !== previousInside) {
      const previousValue = value(previous)
      const currentValue = value(current)
      const ratio = previousValue / (previousValue - currentValue)
      output.push([
        previous[0] + (current[0] - previous[0]) * ratio,
        previous[1] + (current[1] - previous[1]) * ratio,
      ])
    }
    if (currentInside) output.push([...current])
  }
  return normalizePolygon(output)
}

function uniqueLaneId(drafts, stem) {
  const ids = new Set(drafts.map((lane) => lane.local_lane_id))
  const clippedStem = stem.slice(0, 100)
  if (!ids.has(clippedStem)) return clippedStem
  let suffix = 2
  let candidate = clippedStem
  do {
    const tail = `-${suffix}`
    candidate = `${stem.slice(0, 100 - tail.length)}${tail}`
    suffix += 1
  } while (ids.has(candidate))
  return candidate
}

function polygonMajorAxis(points) {
  const center = points.reduce((sum, point) => [sum[0] + point[0], sum[1] + point[1]], [0, 0]).map((value) => value / points.length)
  const covariance = points.reduce((value, point) => {
    const dx = point[0] - center[0]
    const dy = point[1] - center[1]
    return { xx: value.xx + dx * dx, xy: value.xy + dx * dy, yy: value.yy + dy * dy }
  }, { xx: 0, xy: 0, yy: 0 })
  if (covariance.xx + covariance.yy < 1e-6) return null
  const angle = .5 * Math.atan2(2 * covariance.xy, covariance.xx - covariance.yy)
  return [Math.cos(angle), Math.sin(angle)]
}

export function splitLaneDraft(drafts, selection) {
  if (selection.laneIds.length !== 1) return { lanes: drafts, selection }
  const lane = drafts.find((item) => item.local_lane_id === selection.laneIds[0])
  const points = normalizePolygon(lane?.points || [])
  if (!lane || points.length < 3) return { lanes: drafts, selection }

  const axis = polygonMajorAxis(points)
  if (!axis) return { lanes: drafts, selection }
  const projections = points.map((point) => point[0] * axis[0] + point[1] * axis[1])
  const offset = (Math.min(...projections) + Math.max(...projections)) / 2
  const firstPoints = clipPolygon(points, axis, offset, true)
  const secondPoints = clipPolygon(points, axis, offset, false)
  if (firstPoints.length < 3 || secondPoints.length < 3) return { lanes: drafts, selection }

  const firstId = uniqueLaneId(drafts, `${lane.local_lane_id}:split-a`)
  const secondId = uniqueLaneId([...drafts, { local_lane_id: firstId }], `${lane.local_lane_id}:split-b`)
  const makeLane = (localLaneId, polygon) => ({
    ...lane,
    local_lane_id: localLaneId,
    source_lane_id: null,
    parent_lane_ids: [lane.local_lane_id],
    points: polygon,
  })
  const lanes = drafts.flatMap((item) => item.local_lane_id === lane.local_lane_id
    ? [makeLane(firstId, firstPoints), makeLane(secondId, secondPoints)]
    : [item])
  return { lanes, selection: selectLaneDraft(lanes, firstId, 'lane') }
}

function convexHull(points) {
  const unique = [...new Map(normalizePolygon(points).map((point) => [`${point[0]}:${point[1]}`, point])).values()]
    .sort((left, right) => left[0] - right[0] || left[1] - right[1])
  if (unique.length < 3) return unique
  const cross = (origin, left, right) => (left[0] - origin[0]) * (right[1] - origin[1]) - (left[1] - origin[1]) * (right[0] - origin[0])
  const half = (items) => {
    const hull = []
    items.forEach((point) => {
      while (hull.length >= 2 && cross(hull.at(-2), hull.at(-1), point) <= 0) hull.pop()
      hull.push(point)
    })
    return hull
  }
  const lower = half(unique)
  const upper = half([...unique].reverse())
  return [...lower.slice(0, -1), ...upper.slice(0, -1)].map((point) => [...point])
}

export function mergeLaneDrafts(drafts, selection) {
  if (selection.laneIds.length < 2) return { lanes: drafts, selection }
  const selectedIds = new Set(selection.laneIds)
  const selected = drafts.filter((lane) => selectedIds.has(lane.local_lane_id))
  const linkIds = new Set(selected.map((lane) => lane.link_id).filter(Boolean))
  if (selected.length !== selection.laneIds.length || linkIds.size > 1) return { lanes: drafts, selection }
  const points = convexHull(selected.flatMap((lane) => lane.points || []))
  if (points.length < 3) return { lanes: drafts, selection }

  const first = selected[0]
  const mergedId = uniqueLaneId(drafts, `${first.local_lane_id}:merged`)
  const directions = new Set(selected.map((lane) => lane.direction).filter(Boolean))
  const merged = {
    ...first,
    local_lane_id: mergedId,
    source_lane_id: null,
    parent_lane_ids: selected.map((lane) => lane.local_lane_id),
    direction: directions.size === 1 ? selected[0].direction : 'straight',
    points,
  }
  const firstIndex = drafts.findIndex((lane) => selectedIds.has(lane.local_lane_id))
  const lanes = drafts.filter((lane) => !selectedIds.has(lane.local_lane_id))
  lanes.splice(firstIndex, 0, merged)
  return { lanes, selection: selectLaneDraft(lanes, mergedId, 'lane') }
}
