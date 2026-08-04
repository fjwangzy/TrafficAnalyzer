export const REGISTRATION_POSE_SCHEMA = 'uav.channelized-editor/registration-pose/v1'

const identity = () => [[1, 0, 0], [0, 1, 0], [0, 0, 1]]

const multiply = (left, right) => left.map((row, rowIndex) => row.map((_, columnIndex) => (
  row.reduce((sum, value, index) => sum + value * right[index][columnIndex], 0)
)))

const inverse = (matrix) => {
  const [[a, b, c], [d, e, f], [g, h, i]] = matrix
  const determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
  if (!Number.isFinite(determinant) || Math.abs(determinant) < 1e-12) throw new Error('registration transform is singular')
  return [
    [(e * i - f * h) / determinant, (c * h - b * i) / determinant, (b * f - c * e) / determinant],
    [(f * g - d * i) / determinant, (a * i - c * g) / determinant, (c * d - a * f) / determinant],
    [(d * h - e * g) / determinant, (b * g - a * h) / determinant, (a * e - b * d) / determinant],
  ]
}

export function createRegistrationPose(value = {}) {
  const center = Array.isArray(value.center_px) ? value.center_px : [0, 0]
  const translation = Array.isArray(value.translation_px) ? value.translation_px : [0, 0]
  const scale = Number(value.uniform_scale ?? 1)
  return {
    schema_version: REGISTRATION_POSE_SCHEMA,
    fixed_surface: 'source_image',
    center_px: [Number(center[0]) || 0, Number(center[1]) || 0],
    translation_px: [Number(translation[0]) || 0, Number(translation[1]) || 0],
    rotation_deg: Number(value.rotation_deg) || 0,
    uniform_scale: Number.isFinite(scale) && scale > 0 ? scale : 1,
  }
}

export function registrationTransform(poseValue) {
  const pose = createRegistrationPose(poseValue)
  const [centerX, centerY] = pose.center_px
  const [offsetX, offsetY] = pose.translation_px
  const angle = pose.rotation_deg * Math.PI / 180
  const cosine = Math.cos(angle) * pose.uniform_scale
  const sine = Math.sin(angle) * pose.uniform_scale
  const translateToOrigin = [[1, 0, -centerX], [0, 1, -centerY], [0, 0, 1]]
  const rotateScale = [[cosine, -sine, 0], [sine, cosine, 0], [0, 0, 1]]
  const translateBack = [[1, 0, centerX + offsetX], [0, 1, centerY + offsetY], [0, 0, 1]]
  return multiply(translateBack, multiply(rotateScale, translateToOrigin))
}

export function projectPoint(matrix, point) {
  const [x, y] = point
  const denominator = matrix[2][0] * x + matrix[2][1] * y + matrix[2][2]
  if (!Number.isFinite(denominator) || Math.abs(denominator) < 1e-12) throw new Error('point projects to infinity')
  return [
    (matrix[0][0] * x + matrix[0][1] * y + matrix[0][2]) / denominator,
    (matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]) / denominator,
  ]
}

export function transformPoint(point, pose) {
  return projectPoint(registrationTransform(pose), point)
}

export function transformPointBetweenPoses(point, previousPose, nextPose) {
  return projectPoint(
    multiply(registrationTransform(nextPose), inverse(registrationTransform(previousPose))),
    point,
  )
}

export function composeRegistrationHomography(basePixelToEnu, pose) {
  const base = Array.isArray(basePixelToEnu) && basePixelToEnu.length === 3 ? basePixelToEnu : identity()
  return multiply(base, inverse(registrationTransform(pose)))
}

const clone = (value) => JSON.parse(JSON.stringify(value))

export function createCubicLaneEdge(lane, edgeIndex) {
  const points = lane?.points || []
  if (points.length < 3 || edgeIndex < 0 || edgeIndex >= points.length) return clone(lane)
  const start = points[edgeIndex]
  const end = points[(edgeIndex + 1) % points.length]
  const curve = {
    edge_index: edgeIndex,
    control1: [start[0] + (end[0] - start[0]) / 3, start[1] + (end[1] - start[1]) / 3],
    control2: [start[0] + (end[0] - start[0]) * 2 / 3, start[1] + (end[1] - start[1]) * 2 / 3],
  }
  return {
    ...clone(lane),
    boundary_curves: [...(lane.boundary_curves || []).filter((item) => item.edge_index !== edgeIndex), curve]
      .sort((left, right) => left.edge_index - right.edge_index),
    manual_override: true,
  }
}

const cubicPoint = (start, control1, control2, end, progress) => {
  const remaining = 1 - progress
  return [0, 1].map((index) => (
    remaining ** 3 * start[index]
    + 3 * remaining ** 2 * progress * control1[index]
    + 3 * remaining * progress ** 2 * control2[index]
    + progress ** 3 * end[index]
  ))
}

export function sampleLaneCurves(lane, samplesPerCurve = 12) {
  const points = lane?.points || []
  if (points.length < 3) return clone(points)
  const curveByEdge = new Map((lane.boundary_curves || []).map((curve) => [curve.edge_index, curve]))
  const samples = Math.max(2, Math.round(samplesPerCurve))
  return points.flatMap((start, edgeIndex) => {
    const curve = curveByEdge.get(edgeIndex)
    if (!curve) return [[...start]]
    const end = points[(edgeIndex + 1) % points.length]
    return [
      [...start],
      ...Array.from({ length: samples - 1 }, (_, index) => (
        cubicPoint(start, curve.control1, curve.control2, end, (index + 1) / samples)
      )),
    ]
  })
}

export function createEditorHistory(initialState) {
  return { past: [], present: clone(initialState), future: [] }
}

export function commitEditorHistory(history, nextState, limit = 50) {
  return {
    past: [...history.past, clone(history.present)].slice(-Math.max(1, limit)),
    present: clone(nextState),
    future: [],
  }
}

export function undoEditorHistory(history) {
  if (!history.past.length) return history
  return {
    past: history.past.slice(0, -1),
    present: clone(history.past.at(-1)),
    future: [clone(history.present), ...history.future],
  }
}

export function redoEditorHistory(history) {
  if (!history.future.length) return history
  return {
    past: [...history.past, clone(history.present)],
    present: clone(history.future[0]),
    future: history.future.slice(1),
  }
}

const pointOnApproach = (center, angleDegrees, distance, lateral = 0) => {
  const angle = angleDegrees * Math.PI / 180
  const forward = [Math.cos(angle), Math.sin(angle)]
  const left = [-forward[1], forward[0]]
  return [
    center[0] + forward[0] * distance + left[0] * lateral,
    center[1] + forward[1] * distance + left[1] * lateral,
  ]
}

const approachStartDistance = (approach) => Math.max(
  24,
  (Number(approach.inbound_lane_count) + Number(approach.outbound_lane_count))
    * Number(approach.lane_width_px) * 0.72,
)

export function approachHandlePoint(model, approach) {
  return pointOnApproach(
    model.center_px,
    approach.angle_deg,
    approachStartDistance(approach) + Number(approach.approach_length_px),
  )
}

export function updateApproachFromHandle(model, approachId, point) {
  const [centerX, centerY] = model.center_px
  const deltaX = Number(point[0]) - centerX
  const deltaY = Number(point[1]) - centerY
  const distance = Math.hypot(deltaX, deltaY)
  return {
    ...clone(model),
    approaches: model.approaches.map((approach) => approach.approach_id === approachId ? {
      ...approach,
      angle_deg: Math.atan2(deltaY, deltaX) * 180 / Math.PI,
      approach_length_px: Math.min(5000, Math.max(11, distance - approachStartDistance(approach))),
    } : approach),
  }
}

export function createDefaultEditorModel(centerPx = [0, 0]) {
  const workingRadius = Math.max(1, Math.min(Number(centerPx[0]) || 0, Number(centerPx[1]) || 0))
  const laneWidth = Math.max(18, Math.min(42, workingRadius / 22))
  const approachLength = Math.max(230, workingRadius * .78)
  const approaches = [
    ['east', 0], ['south', 90], ['west', 180], ['north', -90],
  ].map(([approachId, angle]) => ({
    approach_id: approachId,
    angle_deg: angle,
    inbound_lane_count: 2,
    outbound_lane_count: 2,
    lane_width_px: laneWidth,
    approach_length_px: approachLength,
    flare_length_px: approachLength * .26,
    right_turn_lane: false,
    turn_directions: ['left_turn', 'straight'],
    manual_override: false,
  }))
  return {
    schema_version: 'uav.channelized-editor/model/v1',
    mode: 'parameterized',
    center_px: [Number(centerPx[0]) || 0, Number(centerPx[1]) || 0],
    approaches,
    feature_templates: approaches.flatMap((approach) => [
      {
        feature_id: `crosswalk:${approach.approach_id}`,
        feature_type: 'crosswalk',
        approach_id: approach.approach_id,
        width_px: 12,
        setback_px: 16,
        color: 'white',
        line_style: 'solid',
        manual_override: false,
      },
      {
        feature_id: `stop-line:${approach.approach_id}`,
        feature_type: 'stop_line',
        approach_id: approach.approach_id,
        width_px: 4,
        setback_px: 4,
        color: 'white',
        line_style: 'solid',
        manual_override: false,
      },
    ]),
    manual_overrides: [],
  }
}

export function createFreeformEditorModel(centerPx = [0, 0], lanes = [], features = []) {
  return {
    schema_version: 'uav.channelized-editor/model/v1',
    mode: 'freeform',
    center_px: [Number(centerPx[0]) || 0, Number(centerPx[1]) || 0],
    approaches: [],
    feature_templates: [],
    manual_overrides: [],
    pixel_geometry: { lanes: clone(lanes), features: clone(features) },
  }
}

const generatedLane = (model, approach, flow, index, lateralStart, lateralEnd) => {
  const laneId = `lane:${approach.approach_id}:${flow}:${index + 1}`
  const laneWidth = Number(approach.lane_width_px)
  const roadWidth = (approach.inbound_lane_count + approach.outbound_lane_count) * laneWidth
  const startDistance = approachStartDistance(approach)
  const endDistance = startDistance + Number(approach.approach_length_px)
  const flareLength = Math.min(Number(approach.flare_length_px || 0), Number(approach.approach_length_px))
  const isOuterInbound = flow === 'in' && index === approach.inbound_lane_count - 1 && flareLength > 0
  const turnDirections = approach.turn_directions || []
  const direction = flow === 'in' && approach.right_turn_lane && index === approach.inbound_lane_count - 1
    ? 'right_turn'
    : flow === 'in' ? (turnDirections[index] || 'straight') : 'straight'
  const points = [
    pointOnApproach(model.center_px, approach.angle_deg, startDistance, lateralStart),
    pointOnApproach(model.center_px, approach.angle_deg, endDistance, lateralStart),
    pointOnApproach(model.center_px, approach.angle_deg, endDistance, lateralEnd + (isOuterInbound ? laneWidth * .35 : 0)),
  ]
  if (isOuterInbound) points.push(pointOnApproach(model.center_px, approach.angle_deg, endDistance - flareLength, lateralEnd))
  points.push(pointOnApproach(model.center_px, approach.angle_deg, startDistance, lateralEnd))
  return {
    local_lane_id: laneId,
    source_lane_id: null,
    link_id: `link:${approach.approach_id}`,
    direction,
    special_lane_attribute: flow === 'in' ? (approach.special_lane_attributes?.[`lane_${index + 1}`] || null) : null,
    points,
    generated_from: { approach_id: approach.approach_id, flow, lane_index: index },
    manual_override: false,
  }
}

const generatedFeature = (model, approaches, template) => {
  const approach = approaches.get(template.approach_id)
  if (!approach) return null
  const width = Number(approach.lane_width_px)
  const roadWidth = (approach.inbound_lane_count + approach.outbound_lane_count) * width
  const startDistance = Math.max(24, roadWidth * 0.72) + Number(template.setback_px || 0)
  const featureWidth = Number(template.width_px || Math.max(8, width * 0.65))
  const lateralOffset = Number(template.lateral_offset_px || 0)
  let points
  if (['crosswalk', 'waiting_zone'].includes(template.feature_type)) {
    const halfRoad = roadWidth / 2
    const length = Number(template.length_px || roadWidth)
    const halfLength = Math.min(halfRoad, length / 2)
    points = [
      pointOnApproach(model.center_px, approach.angle_deg, startDistance, lateralOffset - halfLength),
      pointOnApproach(model.center_px, approach.angle_deg, startDistance + featureWidth, lateralOffset - halfLength),
      pointOnApproach(model.center_px, approach.angle_deg, startDistance + featureWidth, lateralOffset + halfLength),
      pointOnApproach(model.center_px, approach.angle_deg, startDistance, lateralOffset + halfLength),
    ]
  } else if (template.feature_type === 'channelizing_island') {
    const outside = approach.inbound_lane_count * width
    points = [
      pointOnApproach(model.center_px, approach.angle_deg, startDistance, outside),
      pointOnApproach(model.center_px, approach.angle_deg, startDistance + Number(template.length_px || width * 3), outside),
      pointOnApproach(model.center_px, approach.angle_deg, startDistance, outside - featureWidth),
    ]
  } else {
    const length = Number(template.length_px || roadWidth)
    if (template.feature_type === 'stop_line') {
      points = [
        pointOnApproach(model.center_px, approach.angle_deg, startDistance, 0),
        pointOnApproach(model.center_px, approach.angle_deg, startDistance, approach.inbound_lane_count * width),
      ]
    } else {
      points = [
        pointOnApproach(model.center_px, approach.angle_deg, startDistance, lateralOffset),
        pointOnApproach(model.center_px, approach.angle_deg, startDistance + length, lateralOffset),
      ]
    }
  }
  return {
    feature_id: template.feature_id,
    feature_type: template.feature_type,
    points,
    properties: {
      approach_id: approach.approach_id,
      variant: template.variant || 'standard',
      width_px: template.width_px ?? null,
      setback_px: Number(template.setback_px || 0),
      length_px: template.length_px ?? null,
      lateral_offset_px: Number(template.lateral_offset_px || 0),
      color: template.color || 'white',
      line_style: template.line_style || 'solid',
      generated_from_editor_model: true,
    },
    manual_override: false,
  }
}

export function generateEditorGeometry(model, current = { lanes: [], features: [] }) {
  const manualIds = new Set(model?.manual_overrides || [])
  const currentLanes = new Map((current.lanes || []).map((lane) => [lane.local_lane_id, lane]))
  const currentFeatures = new Map((current.features || []).map((feature) => [feature.feature_id, feature]))
  const lanes = []
  for (const approach of model?.approaches || []) {
    const width = Number(approach.lane_width_px)
    for (let index = 0; index < approach.inbound_lane_count; index += 1) {
      const generated = generatedLane(model, approach, 'in', index, index * width, (index + 1) * width)
      lanes.push(manualIds.has(generated.local_lane_id) && currentLanes.has(generated.local_lane_id)
        ? clone(currentLanes.get(generated.local_lane_id)) : generated)
    }
    for (let index = 0; index < approach.outbound_lane_count; index += 1) {
      const generated = generatedLane(model, approach, 'out', index, -(index + 1) * width, -index * width)
      lanes.push(manualIds.has(generated.local_lane_id) && currentLanes.has(generated.local_lane_id)
        ? clone(currentLanes.get(generated.local_lane_id)) : generated)
    }
  }
  const approaches = new Map((model?.approaches || []).map((approach) => [approach.approach_id, approach]))
  const features = (model?.feature_templates || []).flatMap((template) => {
    if (manualIds.has(template.feature_id) && currentFeatures.has(template.feature_id)) {
      return [clone(currentFeatures.get(template.feature_id))]
    }
    const feature = generatedFeature(model, approaches, template)
    return feature ? [feature] : []
  })
  return { lanes, features }
}
