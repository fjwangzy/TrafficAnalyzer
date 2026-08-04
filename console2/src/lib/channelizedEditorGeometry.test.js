import { describe, expect, it } from 'vitest'

import {
  approachHandlePoint,
  commitEditorHistory,
  composeRegistrationHomography,
  createCubicLaneEdge,
  createDefaultEditorModel,
  createEditorHistory,
  createFreeformEditorModel,
  createRegistrationPose,
  generateEditorGeometry,
  projectPoint,
  redoEditorHistory,
  sampleLaneCurves,
  transformPoint,
  transformPointBetweenPoses,
  undoEditorHistory,
  updateApproachFromHandle,
} from './channelizedEditorGeometry'

describe('channelized editor registration geometry', () => {
  it('keeps the source image fixed while the transformed road overlay maps to the same ENU point', () => {
    const basePixelToEnu = [
      [0.2, 0, -100],
      [0, -0.2, 60],
      [0, 0, 1],
    ]
    const pose = createRegistrationPose({
      center_px: [960, 540],
      translation_px: [34, -21],
      rotation_deg: 7.5,
      uniform_scale: 1.08,
    })
    const basePixel = [1120, 610]
    const alignedPixel = transformPoint(basePixel, pose)
    const finalPixelToEnu = composeRegistrationHomography(basePixelToEnu, pose)

    expect(projectPoint(finalPixelToEnu, alignedPixel)[0]).toBeCloseTo(
      projectPoint(basePixelToEnu, basePixel)[0],
      8,
    )
    expect(projectPoint(finalPixelToEnu, alignedPixel)[1]).toBeCloseTo(
      projectPoint(basePixelToEnu, basePixel)[1],
      8,
    )
  })

  it('samples cubic lane boundaries deterministically without changing the original vertices', () => {
    const lane = { local_lane_id: 'lane:1', points: [[0, 0], [12, 0], [12, 8], [0, 8]] }
    const curved = createCubicLaneEdge(lane, 0)
    curved.boundary_curves[0].control1 = [3, -4]
    curved.boundary_curves[0].control2 = [9, -4]
    const sampled = sampleLaneCurves(curved, 4)

    expect(lane.boundary_curves).toBeUndefined()
    expect(sampled).toHaveLength(7)
    expect(sampled[0]).toEqual([0, 0])
    expect(sampled[4]).toEqual([12, 0])
    expect(sampled[2][1]).toBeLessThan(0)
  })

  it('supports bounded undo and redo for whole-editor changes', () => {
    let history = createEditorHistory({ pose: createRegistrationPose(), lanes: [] })
    history = commitEditorHistory(history, { ...history.present, lanes: [{ local_lane_id: 'lane:1' }] })
    expect(undoEditorHistory(history).present.lanes).toEqual([])
    expect(redoEditorHistory(undoEditorHistory(history)).present.lanes).toHaveLength(1)
  })

  it('applies only the delta when the global registration pose changes', () => {
    const before = createRegistrationPose({ translation_px: [10, 0], uniform_scale: 1 })
    const after = createRegistrationPose({ translation_px: [30, -4], uniform_scale: 1 })
    expect(transformPointBetweenPoses([110, 50], before, after)).toEqual([130, 46])
  })

  it('creates a four-approach parameter model centered on the retained source frame', () => {
    const model = createDefaultEditorModel([960, 540])
    expect(model.center_px).toEqual([960, 540])
    expect(model.approaches.map((approach) => approach.approach_id)).toEqual(['east', 'south', 'west', 'north'])
    expect(model.approaches[0].approach_length_px).toBeGreaterThan(400)
    expect(model.feature_templates.some((feature) => feature.feature_type === 'crosswalk')).toBe(true)
  })

  it('persists freeform curves and features without inventing an approach skeleton', () => {
    const lanes = [{
      local_lane_id: 'lane:freeform',
      points: [[10, 10], [90, 10], [90, 40], [10, 40]],
      boundary_curves: [{ edge_index: 0, control1: [30, 2], control2: [70, 2] }],
    }]
    const features = [{ feature_id: 'stop:1', feature_type: 'stop_line', points: [[10, 50], [90, 50]] }]
    const model = createFreeformEditorModel([50, 30], lanes, features)

    expect(model.mode).toBe('freeform')
    expect(model.approaches).toEqual([])
    expect(model.pixel_geometry).toEqual({ lanes, features })
  })

  it('reverse-updates approach angle and length when its skeleton handle is dragged', () => {
    const model = createDefaultEditorModel([500, 300])
    const moved = updateApproachFromHandle(model, 'east', [500, 700])
    const east = moved.approaches.find((approach) => approach.approach_id === 'east')

    expect(east.angle_deg).toBeCloseTo(90, 6)
    expect(east.approach_length_px).toBeGreaterThan(300)
    expect(approachHandlePoint(moved, east)[0]).toBeCloseTo(500, 6)
    expect(approachHandlePoint(moved, east)[1]).toBeCloseTo(700, 6)
  })

  it('generates linked lane polygons and formal features from approach parameters while preserving manual overrides', () => {
    const model = {
      schema_version: 'uav.channelized-editor/model/v1',
      center_px: [500, 300],
      approaches: [{
        approach_id: 'east', angle_deg: 0, inbound_lane_count: 2, outbound_lane_count: 1,
        lane_width_px: 16, approach_length_px: 220, flare_length_px: 60,
        right_turn_lane: true, turn_directions: ['straight', 'right_turn'],
        special_lane_attributes: { lane_2: 'bus' },
      }],
      feature_templates: [
        { feature_id: 'crosswalk:east', feature_type: 'crosswalk', approach_id: 'east', width_px: 12, setback_px: 18 },
        { feature_id: 'marking:east', feature_type: 'lane_marking', approach_id: 'east', line_style: 'dashed', color: 'white', setback_px: 20, length_px: 130 },
      ],
      manual_overrides: ['lane:east:in:1'],
    }
    const manualLane = { local_lane_id: 'lane:east:in:1', link_id: 'link:east', points: [[1, 1], [2, 1], [2, 2], [1, 2]], manual_override: true }
    const generated = generateEditorGeometry(model, { lanes: [manualLane], features: [] })

    expect(generated.lanes).toHaveLength(3)
    expect(generated.lanes.find((lane) => lane.local_lane_id === manualLane.local_lane_id)).toEqual(manualLane)
    expect(generated.lanes.every((lane) => lane.link_id === 'link:east')).toBe(true)
    expect(generated.lanes.find((lane) => lane.local_lane_id === 'lane:east:in:2').direction).toBe('right_turn')
    expect(generated.lanes.find((lane) => lane.local_lane_id === 'lane:east:in:2').special_lane_attribute).toBe('bus')
    expect(generated.lanes.find((lane) => lane.local_lane_id === 'lane:east:in:2').points).toHaveLength(5)
    expect(generated.features.map((feature) => feature.feature_type)).toEqual(['crosswalk', 'lane_marking'])
  })
})
