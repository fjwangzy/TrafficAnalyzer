import { render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mapMocks = vi.hoisted(() => ({
  add: vi.fn(),
  destroy: vi.fn(),
  remove: vi.fn(),
  setCenter: vi.fn(),
  setFitView: vi.fn(),
}))

vi.mock('../lib/amap', () => ({
  loadAmap: vi.fn(async () => window.AMap),
}))

import { MonitoringBevMap, mapFitDuration, mapFitPadding, trajectoryGcj02, validMapCenter } from './MonitoringBevMap'

beforeEach(() => {
  Object.values(mapMocks).forEach((mock) => mock.mockClear())
  window.AMap = {
    Map: class {
      constructor() { return mapMocks }
    },
    Polyline: class {
      constructor(options) { this.options = options }
    },
    CircleMarker: class {
      constructor(options) { this.options = options }
    },
  }
})

describe('MonitoringBevMap GCJ-02 contract', () => {
  it('consumes canonical GCJ-02 trajectories directly', () => {
    expect(trajectoryGcj02({ trajectory_gcj02: [[117.1, 36.7], [117.2, 36.8]] }))
      .toEqual([[117.1, 36.7], [117.2, 36.8]])
  })

  it('does not interpret ENU-only trajectories as map coordinates', () => {
    expect(trajectoryGcj02({ trajectory_enu_m: [[0, 0], [10, 20]] })).toEqual([])
  })

  it('falls back from invalid zero coordinates to the configured GCJ-02 center', () => {
    expect(validMapCenter(0, 0)).toEqual({ lat: 36.703222, lon: 117.028285 })
  })

  it('keeps fit helpers stable', () => {
    expect(mapFitPadding({ embedded: true })).toEqual([32, 32, 32, 32])
    expect(mapFitDuration(true)).toBe(0)
  })

  it('does not rebuild and refit unchanged trajectory overlays', async () => {
    const trajectory = { id: 'TRK-1', trajectory_gcj02: [[117.1, 36.7], [117.2, 36.8]] }
    const { rerender } = render(
      <MonitoringBevMap compact trajectories={[trajectory]} label='BEV test map' />,
    )

    await waitFor(() => expect(mapMocks.add).toHaveBeenCalledTimes(1))
    rerender(
      <MonitoringBevMap compact trajectories={[{ ...trajectory, trajectory_gcj02: trajectory.trajectory_gcj02.map((point) => [...point]) }]} label='BEV test map' />,
    )

    expect(mapMocks.add).toHaveBeenCalledTimes(1)
    expect(mapMocks.remove).not.toHaveBeenCalled()
    expect(mapMocks.setFitView).toHaveBeenCalledTimes(1)
  })

  it('swaps changed trajectory overlays without a blank frame or camera refit', async () => {
    const firstTrajectory = { id: 'TRK-1', trajectory_gcj02: [[117.1, 36.7], [117.2, 36.8]] }
    const secondTrajectory = { id: 'TRK-2', trajectory_gcj02: [[117.2, 36.8], [117.3, 36.9]] }
    const { rerender } = render(
      <MonitoringBevMap embedded trajectories={[firstTrajectory]} label='BEV test map' />,
    )

    await waitFor(() => expect(mapMocks.add).toHaveBeenCalledTimes(1))
    rerender(
      <MonitoringBevMap embedded trajectories={[secondTrajectory]} label='BEV test map' />,
    )

    await waitFor(() => expect(mapMocks.add).toHaveBeenCalledTimes(2))
    expect(mapMocks.remove).toHaveBeenCalledTimes(1)
    expect(mapMocks.add.mock.invocationCallOrder[1]).toBeLessThan(mapMocks.remove.mock.invocationCallOrder[0])
    expect(mapMocks.setFitView).toHaveBeenCalledTimes(1)
  })
})
