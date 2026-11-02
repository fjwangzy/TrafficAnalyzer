import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mapMocks = vi.hoisted(() => ({
  add: vi.fn(),
  destroy: vi.fn(),
  remove: vi.fn(),
  setCenter: vi.fn(),
  setFitView: vi.fn(),
  on: vi.fn(),
  sdk: null,
}))

vi.mock('../lib/amap', () => ({
  loadAmap: vi.fn(async () => mapMocks.sdk),
  mapProviderLabel: () => '高德地图',
}))

import { loadAmap } from '../lib/amap'
import { MonitoringBevMap, localGeographicTrajectories, mapFitDuration, mapFitPadding, pixelTrajectoryViewBox, trajectoryGcj02, trajectoryPx, validMapCenter } from './MonitoringBevMap'

beforeEach(() => {
  Object.values(mapMocks).forEach((mock) => mock?.mockReset?.())
  vi.mocked(loadAmap).mockReset().mockImplementation(async () => mapMocks.sdk)
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
  it('silently replaces a failed map with local geographic trajectories that keep updating', async () => {
    const trajectory = { track_id: 7, trajectory_gcj02: [[117, 36.7], [117.001, 36.701]] }
    const view = render(<MonitoringBevMap compact trajectories={[trajectory]} pixelTrajectories={[{ trajectory_px: [[100, 200], [140, 220]] }]} label='recoverable BEV' />)
    await waitFor(() => expect(mapMocks.on).toHaveBeenCalledWith('error', expect.any(Function)))
    const onError = mapMocks.on.mock.calls.find(([event]) => event === 'error')[1]
    act(() => onError({ error: new Error('tile failed') }))
    const stage = screen.getByRole('img', { name: 'recoverable BEV' })
    const firstPath = stage.querySelector('polyline').getAttribute('points')
    expect(stage).toHaveTextContent('GCJ-02 实时轨迹')
    expect(stage.querySelectorAll('polyline')).toHaveLength(1)
    expect(firstPath).not.toBe('100,200 140,220')
    expect(screen.queryByText(/失败|服务不可用|世界坐标不可用/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(mapMocks.destroy).toHaveBeenCalledTimes(1)

    view.rerender(<MonitoringBevMap compact trajectories={[{ ...trajectory, trajectory_gcj02: [[117, 36.7], [117.001, 36.701], [117.002, 36.7]] }]} label='recoverable BEV' />)
    expect(stage.querySelector('polyline').getAttribute('points')).not.toBe(firstPath)
    act(() => onError({ error: new Error('late tile error') }))
    expect(loadAmap).toHaveBeenCalledTimes(1)
    view.unmount()
    expect(mapMocks.destroy).toHaveBeenCalledTimes(1)
  })

  it('renders local geographic paths after SDK rejection without requiring pixel paths', async () => {
    vi.mocked(loadAmap).mockRejectedValueOnce(new Error('SDK unavailable'))
    render(<MonitoringBevMap trajectories={[{ trajectory_gcj02: [[117, 36.7], [117.001, 36.701]] }]} />)

    const stage = await screen.findByRole('img', { name: 'GCJ-02 实时轨迹' })
    expect(stage.querySelector('polyline')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('1 条')
    expect(screen.queryByText(/失败|不可用/)).not.toBeInTheDocument()
    expect(mapMocks.add).not.toHaveBeenCalled()
  })

  it('uses pixel paths arriving after SDK failure and waits neutrally when paths are empty', async () => {
    vi.mocked(loadAmap).mockRejectedValueOnce(new Error('SDK unavailable'))
    const view = render(<MonitoringBevMap emptyMessage='候选目标 3 · 地理投影不可用' label='local BEV' />)
    expect(await screen.findByText('等待实时轨迹')).toBeInTheDocument()
    const stage = screen.getByRole('img', { name: 'local BEV' })
    expect(stage.querySelector('svg')).toHaveAttribute('viewBox', '0 0 1280 720')
    expect(stage.querySelector('polyline')).not.toBeInTheDocument()
    expect(screen.queryByText(/失败|不可用/)).not.toBeInTheDocument()

    view.rerender(<MonitoringBevMap pixelTrajectories={[{ track_id: 7, trajectory_px: [[100, 200], [140, 220]] }]} label='local BEV' />)
    expect(stage).toHaveTextContent('像素坐标实时轨迹')
    expect(stage.querySelector('polyline')).toHaveAttribute('points', '100,200 140,220')
    expect(screen.getByRole('status')).toHaveTextContent('1 条')
    expect(loadAmap).toHaveBeenCalledTimes(1)
  })

  it.each(['Map', 'Polyline', 'CircleMarker'])('falls back when the SDK %s constructor throws', async (constructor) => {
    mapMocks.sdk[constructor] = class { constructor() { throw new Error('SDK constructor failed') } }
    render(<MonitoringBevMap trajectories={[{ trajectory_gcj02: [[117, 36.7], [117.001, 36.701]] }]} />)

    expect((await screen.findByRole('img', { name: 'GCJ-02 实时轨迹' })).querySelector('polyline')).toBeInTheDocument()
    expect(screen.queryByText(/失败|不可用/)).not.toBeInTheDocument()
  })

  it.each(['setCenter', 'add', 'setFitView'])('falls back when the SDK %s operation throws', async (operation) => {
    mapMocks[operation].mockImplementationOnce(() => { throw new Error('SDK operation failed') })
    render(<MonitoringBevMap trajectories={[{ trajectory_gcj02: [[117, 36.7], [117.001, 36.701]] }]} />)

    expect((await screen.findByRole('img', { name: 'GCJ-02 实时轨迹' })).querySelector('polyline')).toBeInTheDocument()
    expect(mapMocks.destroy).toHaveBeenCalledTimes(1)
  })

  it('keeps the local view working when overlay removal and partial SDK cleanup throw', async () => {
    const trajectory = { trajectory_gcj02: [[117, 36.7], [117.001, 36.701]] }
    const view = render(<MonitoringBevMap trajectories={[trajectory]} />)
    await waitFor(() => expect(mapMocks.add).toHaveBeenCalledTimes(1))
    mapMocks.remove.mockImplementationOnce(() => { throw new Error('overlay removal failed') })
    mapMocks.destroy.mockImplementationOnce(() => { throw new Error('partial SDK cleanup failed') })
    view.rerender(<MonitoringBevMap trajectories={[{ trajectory_gcj02: [[117, 36.7], [117.002, 36.702]] }]} />)

    expect((await screen.findByRole('img', { name: 'GCJ-02 实时轨迹' })).querySelector('polyline')).toBeInTheDocument()
    expect(mapMocks.destroy).toHaveBeenCalledTimes(1)
  })

  it('projects local paths north-up with latitude scaling without changing canonical coordinates', () => {
    const trajectory = { track_id: 7, selected: true, trajectory_gcj02: [[117, 60], [118, 60], [117, 61]], trajectory_px: [[100, 200]] }
    const original = JSON.stringify(trajectory)
    const [projected] = localGeographicTrajectories([trajectory, { trajectory_enu_m: [[0, 0], [10, 20]] }])
    const [origin, east, north] = projected.trajectory_px
    expect(east[0]).toBeGreaterThan(origin[0])
    expect(north[1]).toBeLessThan(origin[1])
    expect((east[0] - origin[0]) / (origin[1] - north[1])).toBeCloseTo(Math.cos(60.5 * Math.PI / 180))
    expect(projected).toMatchObject({ track_id: 7, selected: true })
    expect(JSON.stringify(trajectory)).toBe(original)
    expect(localGeographicTrajectories([{ trajectory_gcj02: [[117, 36.7]] }])[0].trajectory_px).toEqual([[640, 360]])
    expect(localGeographicTrajectories([])).toEqual([])
  })

  it('preserves selected endpoints, dimming and candidate styles in local geographic mode', async () => {
    vi.mocked(loadAmap).mockRejectedValueOnce(new Error('SDK unavailable'))
    render(<MonitoringBevMap showEndpoints={false} trajectories={[
      { id: 'SELECTED', selected: true, trajectory_gcj02: [[117, 36.7], [117.001, 36.701]] },
      { id: 'CANDIDATE', dimmed: true, trajectory_display_role: 'candidate', trajectory_gcj02: [[117.002, 36.7], [117.003, 36.701]] },
    ]} />)
    const stage = await screen.findByRole('img', { name: 'GCJ-02 实时轨迹' })
    const [selected, candidate] = stage.querySelectorAll('polyline')
    expect(selected).toHaveAttribute('stroke-width', '5')
    expect(candidate).toHaveAttribute('stroke', '#ffb454')
    expect(candidate).toHaveAttribute('stroke-dasharray', '10 7')
    expect(candidate).toHaveAttribute('stroke-opacity', '0.16')
    expect(stage.querySelectorAll('circle')).toHaveLength(1)
  })

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

  it('dims non-participant trajectories while preserving the selected event pair', async () => {
    render(
      <MonitoringBevMap compact trajectories={[
        { id: 'FOCUS-1', selected: true, trajectory_gcj02: [[117.1, 36.7], [117.2, 36.8]] },
        { id: 'OTHER-1', dimmed: true, trajectory_gcj02: [[117.2, 36.7], [117.3, 36.8]] },
      ]} label='focused BEV map' />,
    )

    await waitFor(() => expect(mapMocks.add).toHaveBeenCalledTimes(1))
    const overlays = mapMocks.add.mock.calls[0][0]
    expect(overlays[0].options.strokeWeight).toBe(5)
    expect(overlays[0].options.strokeOpacity).toBe(.92)
    expect(overlays[2].options.strokeOpacity).toBe(.16)
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
