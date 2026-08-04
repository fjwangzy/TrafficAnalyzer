export function projectPoint(point, matrix) {
  if (!point || !Array.isArray(matrix) || matrix.length !== 3) return null
  const [x, y] = point
  const denominator = matrix[2][0] * x + matrix[2][1] * y + matrix[2][2]
  if (!Number.isFinite(denominator) || Math.abs(denominator) < 1e-12) return null
  const projected = [
    (matrix[0][0] * x + matrix[0][1] * y + matrix[0][2]) / denominator,
    (matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]) / denominator,
  ]
  return projected.every(Number.isFinite) ? projected : null
}

function invertProjectiveMatrix(matrix) {
  if (!Array.isArray(matrix) || matrix.length !== 3 || matrix.some((row) => !Array.isArray(row) || row.length !== 3)) return null
  const [a, b, c] = matrix
  const determinant = (
    a[0] * (b[1] * c[2] - b[2] * c[1])
    - a[1] * (b[0] * c[2] - b[2] * c[0])
    + a[2] * (b[0] * c[1] - b[1] * c[0])
  )
  if (!Number.isFinite(determinant) || Math.abs(determinant) < 1e-12) return null
  return [
    [b[1] * c[2] - b[2] * c[1], a[2] * c[1] - a[1] * c[2], a[1] * b[2] - a[2] * b[1]],
    [b[2] * c[0] - b[0] * c[2], a[0] * c[2] - a[2] * c[0], a[2] * b[0] - a[0] * b[2]],
    [b[0] * c[1] - b[1] * c[0], a[1] * c[0] - a[0] * c[1], a[0] * b[1] - a[1] * b[0]],
  ].map((row) => row.map((value) => value / determinant))
}

function clipPolygonBoundary(points, inside, intersect) {
  if (!points.length) return []
  const clipped = []
  let previous = points.at(-1)
  for (const current of points) {
    const currentInside = inside(current)
    const previousInside = inside(previous)
    if (currentInside !== previousInside) clipped.push(intersect(previous, current))
    if (currentInside) clipped.push(current)
    previous = current
  }
  return clipped
}

function clipPolygonToImage(points, bounds) {
  if (!Number.isFinite(bounds?.width) || !Number.isFinite(bounds?.height)) return points
  let clipped = clipPolygonBoundary(points, ([x]) => x >= 0, (start, end) => {
    const ratio = (0 - start[0]) / (end[0] - start[0])
    return [0, start[1] + ratio * (end[1] - start[1])]
  })
  clipped = clipPolygonBoundary(clipped, ([x]) => x <= bounds.width, (start, end) => {
    const ratio = (bounds.width - start[0]) / (end[0] - start[0])
    return [bounds.width, start[1] + ratio * (end[1] - start[1])]
  })
  clipped = clipPolygonBoundary(clipped, ([, y]) => y >= 0, (start, end) => {
    const ratio = (0 - start[1]) / (end[1] - start[1])
    return [start[0] + ratio * (end[0] - start[0]), 0]
  })
  return clipPolygonBoundary(clipped, ([, y]) => y <= bounds.height, (start, end) => {
    const ratio = (bounds.height - start[1]) / (end[1] - start[1])
    return [start[0] + ratio * (end[0] - start[0]), bounds.height]
  })
}

export function projectMetricPolygonToImage(geometry, pixelToEnu, bounds) {
  if (geometry?.type !== 'Polygon' || !Array.isArray(geometry.coordinates?.[0])) return []
  const enuToPixel = invertProjectiveMatrix(pixelToEnu)
  if (!enuToPixel) return []
  const projected = geometry.coordinates[0].map((point) => projectPoint(point, enuToPixel))
  if (projected.some((point) => !point)) return []
  const [first] = projected
  const last = projected.at(-1)
  if (projected.length > 1 && Math.hypot(first[0] - last[0], first[1] - last[1]) < 1e-7) projected.pop()
  return clipPolygonToImage(projected, bounds)
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value))
}

export function dragImageGeometry(points, interaction, bounds) {
  const next = points.map((point) => [...point])
  const constrained = Number.isFinite(bounds?.width) && Number.isFinite(bounds?.height)
  const width = constrained ? bounds.width : Number.POSITIVE_INFINITY
  const height = constrained ? bounds.height : Number.POSITIVE_INFINITY
  if (interaction?.type === 'vertex' && next[interaction.index]) {
    next[interaction.index] = constrained
      ? [clamp(interaction.point[0], 0, width), clamp(interaction.point[1], 0, height)]
      : [...interaction.point]
  }
  if (interaction?.type === 'translate' && next.length) {
    if (!constrained) return next.map(([x, y]) => [x + interaction.dx, y + interaction.dy])
    const xs = next.map(([x]) => x)
    const ys = next.map(([, y]) => y)
    const dx = clamp(interaction.dx, -Math.min(...xs), width - Math.max(...xs))
    const dy = clamp(interaction.dy, -Math.min(...ys), height - Math.max(...ys))
    return next.map(([x, y]) => [x + dx, y + dy])
  }
  return next
}

export function metricSegmentLength(start, end, metricTransform) {
  const metricStart = projectPoint(start, metricTransform)
  const metricEnd = projectPoint(end, metricTransform)
  if (!metricStart || !metricEnd) return null
  return Math.hypot(metricEnd[0] - metricStart[0], metricEnd[1] - metricStart[1])
}

export function metricSegmentLabel(start, end, metricTransform) {
  const length = metricSegmentLength(start, end, metricTransform)
  return Number.isFinite(length) ? `${length.toFixed(2)} m` : ''
}

export function geometrySegments(points = [], geometryType, closed = false) {
  const segments = points.slice(1).map((point, index) => [points[index], point])
  if (closed && ['area', 'object'].includes(geometryType) && points.length > 2) {
    segments.push([points.at(-1), points[0]])
  }
  return segments
}

export function imageContainViewport(clientWidth, clientHeight, naturalWidth, naturalHeight) {
  if (![clientWidth, clientHeight, naturalWidth, naturalHeight].every((value) => Number.isFinite(value) && value > 0)) {
    return null
  }
  const scale = Math.min(clientWidth / naturalWidth, clientHeight / naturalHeight)
  const width = naturalWidth * scale
  const height = naturalHeight * scale
  return {
    scale,
    offsetX: (clientWidth - width) / 2,
    offsetY: (clientHeight - height) / 2,
    width,
    height,
  }
}
