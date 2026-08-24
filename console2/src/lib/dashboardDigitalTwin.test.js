import { describe, expect, it } from 'vitest'
import { buildDashboardDigitalTwin, buildPixelGroundProjection, normalizeActiveVehicleTracks, projectPixelPointToGcj02, selectDigitalTwinMap } from './dashboardDigitalTwin'

const stats = (trajectory) => ({ active_trajectories: [{ track_id: 7, vehicle_class: 'car', trajectory_output_eligible: true, ...trajectory }] })
const drone = { pipeline_id: 'PIPE-1', intersection_id: 'INT-1', is_replay: false }

describe('dashboard digital twin capability degradation', () => {
  it('uses verified lane bindings without requiring links, stop lines, or areas', () => {
    const twin = buildDashboardDigitalTwin({
      stats: stats({ trajectory_gcj02: [[117, 36.7], [117.0001, 36.7001]], matched_lane_key: 'LANE-1' }),
      mapVersion: {
        id: 'MAP-1', status: 'lane_verified', geometry_gcj02: {},
        lanes: [{ local_lane_id: 'LANE-1', status: 'lane_verified', geometry_gcj02: { type: 'LineString', coordinates: [[117, 36.7], [117.001, 36.701]] } }],
      },
      selectedDrone: drone,
    })

    expect(twin.level).toBe('lane')
    expect(twin.availableLayers).toEqual({ lanes: true, links: false, stopLines: false, areas: false, vehicles: true, georeferencedVehicles: true, simulatedVehicles: false, cameraFootprint: false, pixelVehicles: false })
    expect(twin.label).toBe('车道级 · Lane 1 · 活跃车辆 1')
  })

  it('degrades independently from road to spatial and pixel modes', () => {
    const spatialStats = stats({ trajectory_gcj02: [[117, 36.7], [117.0001, 36.7001]] })
    const road = buildDashboardDigitalTwin({
      stats: spatialStats,
      mapVersion: { id: 'MAP-LINK', status: 'link_verified', geometry_gcj02: { links: { 'LINK-1': { type: 'LineString', coordinates: [[117, 36.7], [117.001, 36.701]] } } } },
      selectedDrone: drone,
    })
    const spatial = buildDashboardDigitalTwin({ stats: spatialStats, mapVersion: null, selectedDrone: drone })
    const pixel = buildDashboardDigitalTwin({
      stats: stats({ trajectory_px: [[10, 20], [900, 500]] }), mapVersion: null,
      selectedDrone: { ...drone, lon: 117, lat: 36.7, altitude_m: 100, gimbal_pitch_deg: -90, gimbal_yaw_deg: 0, focal_length_mm: 4.5 },
    })

    expect(road.level).toBe('road')
    expect(spatial.level).toBe('spatial')
    expect(pixel.level).toBe('bev_pixel')
    expect(pixel.vehicles).toEqual([])
    expect(pixel.pixelVehicles[0].trajectory_px).toEqual([[10, 20], [900, 500]])
    expect(pixel.availableLayers).toMatchObject({ vehicles: true, georeferencedVehicles: false, simulatedVehicles: true, cameraFootprint: true })
    expect(pixel.label).toBe('3D 覆盖仿真 · 约 142×80m · 活跃车辆 1')
    expect(pixel.pixelGroundProjection).toMatchObject({ frameSize: [960, 540], headingDeg: 0, basis: 'telemetry_camera_footprint_approximate' })
  })

  it('never promotes candidate maps or invalid coordinates to a georeferenced vehicle layer', () => {
    const twin = buildDashboardDigitalTwin({
      stats: stats({ trajectory_gcj02: [[117, 36.7], [null, 36.8]], trajectory_px: [[20, 30], [22, 31]] }),
      mapVersion: { status: 'candidate', geometry_gcj02: { lanes: { fake: { type: 'LineString', coordinates: [[117, 36.7], [117.1, 36.8]] } } } },
      selectedDrone: drone,
    })

    expect(twin.level).toBe('bev_pixel')
    expect(twin.geometry.lanes).toEqual([])
    expect(twin.vehicles).toEqual([])
    expect(twin.reasons).toContain('verified_map_missing')
  })

  it('selects lane-verified then link-verified maps and ignores drafts', () => {
    const draft = { id: 'DRAFT', status: 'draft' }
    const link = { id: 'LINK', status: 'link_verified' }
    const lane = { id: 'LANE', status: 'lane_verified' }
    expect(selectDigitalTwinMap([draft, link, lane])).toBe(lane)
    expect(selectDigitalTwinMap([draft, link])).toBe(link)
    expect(selectDigitalTwinMap([draft])).toBeNull()
  })

  it('accepts only mature active trajectories and caps the overlay contract', () => {
    const active = Array.from({ length: 205 }, (_, index) => ({ track_id: index, trajectory_gcj02: [[117, 36.7], [117.0001, 36.7001]] }))
    active[0].trajectory_output_eligible = false
    expect(normalizeActiveVehicleTracks({ active_trajectories: active })).toHaveLength(200)
    expect(normalizeActiveVehicleTracks({ candidate_trajectories: active })).toEqual([])
  })

  it('keeps pixel scale tied to the camera footprint and rotates it by gimbal yaw', () => {
    const projection = buildPixelGroundProjection(
      { lon: 117, lat: 36.7, altitude_m: 100, gimbal_pitch_deg: -90, gimbal_yaw_deg: 90, focal_length_mm: 4.5 },
      [{ trajectory_px: [[0, 0], [960, 540]] }],
    )
    expect(projection.widthM).toBeCloseTo(142.22, 1)
    expect(projection.heightM).toBeCloseTo(80, 1)
    const center = projectPixelPointToGcj02([480, 270], projection)
    expect(center).toEqual([117, 36.7])
    const right = projectPixelPointToGcj02([960, 270], projection)
    expect(right[1]).toBeLessThan(36.7)
  })

  it('uses the canonical inverse digital-zoom scale for the ground footprint', () => {
    const vehicle = { trajectory_px: [[0, 0], [960, 540]] }
    const fullFrame = buildPixelGroundProjection(
      { lon: 117, lat: 36.7, altitude_m: 100, gimbal_pitch_deg: -90, gimbal_yaw_deg: 0, focal_length_mm: 4.5, camera_zoom_factor: 1 },
      [vehicle],
    )
    const narrowed = buildPixelGroundProjection(
      { lon: 117, lat: 36.7, altitude_m: 100, gimbal_pitch_deg: -90, gimbal_yaw_deg: 0, focal_length_mm: 4.5, camera_zoom_factor: 0.5 },
      [vehicle],
    )

    expect(narrowed.widthM).toBeCloseTo(fullFrame.widthM * 0.5, 6)
    expect(narrowed.heightM).toBeCloseTo(fullFrame.heightM * 0.5, 6)
  })
})
