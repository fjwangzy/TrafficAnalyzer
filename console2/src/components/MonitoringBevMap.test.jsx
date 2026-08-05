import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mapMocks = vi.hoisted(() => ({
  add: vi.fn(),
  destroy: vi.fn(),
  remove: vi.fn(),
  setCenter: vi.fn(),
  setFitView: vi.fn(),
  sdk: null,
}))

vi.mock('../lib/amap', () => ({
  loadAmap: vi.fn(async () => mapMocks.sdk),
}))

import { MonitoringBevMap, mapFitDuration, mapFitPadding, pixelTrajectoryViewBox, trajectoryGcj02, trajectoryPx, validMapCenter } from './MonitoringBevMap'

beforeEach(() => {
  Object.values(mapMocks).forEach((mock) => mock?.mockClear?.())
  mapMocks.sdk = {
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
  window.AMap = mapMocks.sdk
})

describe('MonitoringBevMap GCJ-02 contract', () => {
  it('consumes canonical GCJ-02 trajectories directly', () => {
    expect(trajectoryGcj02({ trajectory_gcj02: [[117.1, 36.7], [117.2, 36.8]] }))
      .toEqual([[117.1, 36.7], [117.2, 36.8]])
  })

  it('does not interpret ENU-only trajectories as map coordinates', () => {
    expect(trajectoryGcj02({ trajectory_enu_m: [[0, 0], [10, 20]] })).toEqual([])
  })

  it('renders actual pixel trajectories when world projection is unavailable', () => {
    const pixelTrajectory = { track_id: 7, trajectory_px: [[100, 200], [140, 220]] }
    expect(trajectoryPx(pixelTrajectory)).toEqual([[100, 200], [140, 220]])
    expect(pixelTrajectoryViewBox([pixelTrajectory])).toBe('0 0 1280 720')

    render(
      <MonitoringBevMap
        compact
        trajectories={[]}
        pixelTrajectories={[pixelTrajectory]}
        label='像素坐标实时轨迹投放图'
      />,
    )

    const stage = screen.getByRole('img', { name: '像素坐标实时轨迹投放图' })
    expect(stage).toHaveTextContent('像素坐标实时轨迹')
    expect(stage).toHaveTextContent('目标轨迹')
    expect(stage).not.toHaveTextContent('兼容候选轨迹')
    expect(stage.querySelector('polyline')).toHaveAttribute('points', '100,200 140,220')
    expect(mapMocks.add).not.toHaveBeenCalled()
  })

  it('falls back from invalid zero coordinates to the configured GCJ-02 center', () => {
    expect(validMapCenter(0, 0)).toEqual({ lat: 36.703222, lon: 117.028285 })
  })

  it('keeps fit helpers stable', () => {
    expect(mapFitPadding({ embedded: true })).toEqual([32, 32, 32, 32])
    expect(mapFitDuration(true)).toBe(0)
  })

  it('shows an explicit projection state when no spatial path can be drawn', () => {
    render(<MonitoringBevMap compact trajectories={[]} emptyMessage='候选目标 3 · 地理投影不可用' label='empty BEV map' />)

    expect(screen.getByRole('img', { name: 'empty BEV map' })).toHaveTextContent('候选目标 3 · 地理投影不可用')
  })

  it('renders overlays from the loaded SDK without requiring a window global', async () => {
    delete window.AMap
    render(
      <MonitoringBevMap compact trajectories={[{
        id: 'TRK-1',
        trajectory_gcj02: [[117.1, 36.7], [117.2, 36.8]],
      }]} label='BEV test map' />,
    )

    await waitFor(() => expect(mapMocks.add).toHaveBeenCalledTimes(1))
  })

  it('renders degraded candidate trajectories as amber dashed overlays', async () => {
    render(
      <MonitoringBevMap compact trajectories={[{
        id: 'CANDIDATE-1',
        tracking_quality: 'degraded',
        trajectory_gcj02: [[117.1, 36.7], [117.2, 36.8]],
      }]} label='candidate BEV map' />,
    )

    await waitFor(() => expect(mapMocks.add).toHaveBeenCalledTimes(1))
    expect(screen.getByRole('img', { name: 'candidate BEV map' })).toHaveTextContent('兼容候选轨迹')
    const overlays = mapMocks.add.mock.calls[0][0]
    expect(overlays[0].options.strokeColor).toBe('#ffb454')
    expect(overlays[0].options.strokeStyle).toBe('dashed')
    expect(overlays[0].options.strokeDasharray).toEqual([10, 7])
  })

  it('keeps mature image trajectories solid when only geo analytics are degraded', async () => {
    render(
      <MonitoringBevMap compact trajectories={[{
        id: 'ACTIVE-1',
        trajectory_output_eligible: true,
        quality_status: 'degraded',
        formal_analytics_eligible: false,
        trajectory_gcj02: [[117.1, 36.7], [117.2, 36.8]],
      }]} label='mature degraded BEV map' />,
    )

    await waitFor(() => expect(mapMocks.add).toHaveBeenCalledTimes(1))
    const overlays = mapMocks.add.mock.calls[0][0]
    expect(overlays[0].options.strokeColor).toBe('#63b3ff')
    expect(overlays[0].options.strokeStyle).toBe('solid')
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

  it('keeps the camera stable across live trajectory batches and transient empty batches', async () => {
    const firstTrajectory = { id: 'TRK-1', trajectory_gcj02: [[117.1, 36.7], [117.2, 36.8]] }
    const secondTrajectory = { id: 'TRK-2', trajectory_gcj02: [[117.2, 36.8], [117.3, 36.9]] }
    const { rerender } = render(
      <MonitoringBevMap compact centerLat={36.7} centerLon={117.1} trajectories={[firstTrajectory]} label='live BEV map' />,
    )

    await waitFor(() => expect(mapMocks.setFitView).toHaveBeenCalledTimes(1))
    expect(mapMocks.setCenter).toHaveBeenCalledTimes(1)

    rerender(
      <MonitoringBevMap compact centerLat={36.7} centerLon={117.1} trajectories={[secondTrajectory]} label='live BEV map' />,
    )
    await waitFor(() => expect(mapMocks.add).toHaveBeenCalledTimes(2))

    rerender(
      <MonitoringBevMap compact centerLat={36.7} centerLon={117.1} trajectories={[]} label='live BEV map' />,
    )
    await waitFor(() => expect(mapMocks.remove).toHaveBeenCalledTimes(2))

    rerender(
      <MonitoringBevMap compact centerLat={36.7} centerLon={117.1} trajectories={[firstTrajectory]} label='live BEV map' />,
    )
    await waitFor(() => expect(mapMocks.add).toHaveBeenCalledTimes(3))

    expect(mapMocks.setCenter).toHaveBeenCalledTimes(1)
    expect(mapMocks.setFitView).toHaveBeenCalledTimes(1)
  })
})
