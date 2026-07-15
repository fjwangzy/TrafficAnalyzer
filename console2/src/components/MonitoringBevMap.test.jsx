import { describe, expect, it } from 'vitest'
import { trajectoryLonLats, validMapCenter, worldToLonLat } from './MonitoringBevMap'

describe('MonitoringBevMap world-coordinate projection', () => {
  it('converts ENU points around the trajectory anchor', () => {
    const [lon, lat] = worldToLonLat(100, 50, 36.7, 117.0)
    expect(lat).toBeCloseTo(36.700449, 6)
    expect(lon).toBeCloseTo(117.00112, 5)
  })

  it('uses the intersection center when a trajectory has no own anchor', () => {
    const points = trajectoryLonLats({ trajectory_world_m: [[0, 0], [10, 20]] }, 36.7029, 117.0223)
    expect(points).toHaveLength(2)
    expect(points[0]).toEqual([117.0223, 36.7029])
    expect(points[1][0]).toBeGreaterThan(points[0][0])
    expect(points[1][1]).toBeGreaterThan(points[0][1])
  })

  it('falls back from invalid zero coordinates to the configured monitoring center', () => {
    expect(validMapCenter(0, 0)).toEqual({ lat: 36.7029, lon: 117.0223 })
  })
})
