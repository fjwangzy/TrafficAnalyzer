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
