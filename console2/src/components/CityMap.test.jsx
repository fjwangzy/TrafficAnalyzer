import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mapMocks = vi.hoisted(() => ({ maps: [], markers: [], polylines: [], trafficLayers: [] }))

vi.mock('@amap/amap-jsapi-loader', () => ({
  default: {
    load: vi.fn(async () => {
    class Map {
      constructor(_target, options) { this.options = options; mapMocks.maps.push(this) }
      add(item) { this.added = [...(this.added || []), item] }
      remove(item) { this.removed = [...(this.removed || []), item] }
      addControl() {}
      destroy() {}
      zoomIn() {}
      zoomOut() {}
      setZoomAndCenter() {}
      setFitView(...args) { this.fitViewArgs = args }
    }
    class Marker {
      constructor(options) { this.options = options; mapMocks.markers.push(this) }
      on(_name, handler) { this.click = handler }
      setPosition(position) { this.options.position = position }
      setContent(content) { this.options.content = content }
      setzIndex(zIndex) { this.options.zIndex = zIndex }
    }
    class Polyline {
      constructor(options) { this.options = options; mapMocks.polylines.push(this) }
      on(_name, handler) { this.click = handler }
      setPath(path) { this.options.path = path }
    }
    class Traffic {
      constructor(options) { this.options = options; mapMocks.trafficLayers.push(this) }
    }
    return { Map, Marker, Polyline, Scale: class {}, TileLayer: { Traffic } }
    }),
  },
}))

import { resetAmapLoaderForTest } from '../lib/amap'
import { CityMap } from './CityMap'

describe('CityMap GCJ-02 AMap rendering', () => {
  beforeEach(() => {
    resetAmapLoaderForTest()
    vi.unstubAllEnvs()
    window.__RUNTIME_CONFIG__ = {
      amapKey: 'web-key',
      amapSecurityJsCode: 'security-code',
    }
    mapMocks.maps = []
    mapMocks.markers = []
    mapMocks.polylines = []
    mapMocks.trafficLayers = []
  })

  it('renders GCJ-02 attribution and AMap marker coordinates', async () => {
    render(<CityMap points={[{ id: 'INT-1', lat: 36.7, lon: 117, risk: 'normal' }]} />)
    expect(screen.getByText('高德地图 · GCJ-02')).toBeInTheDocument()
    await waitFor(() => expect(mapMocks.markers).toHaveLength(1))
    expect(mapMocks.markers[0].options.position).toEqual([117, 36.7])
  })

  it('uses the source status color for drone markers', async () => {
    render(<CityMap coordinateLabel='GCJ-02' sourcePoints={[{ id: 'INT-1', lat: 36.7, lon: 117, source_status: 'running', source_count: 2 }]} />)
    await waitFor(() => expect(mapMocks.markers).toHaveLength(1))
    expect(mapMocks.markers[0].options.content).toContain('#58d6b0')
    expect(mapMocks.markers[0].options.content).toContain('amap-drone-marker-face')
    expect(mapMocks.markers[0].options.content).toContain('2')
    expect(mapMocks.markers[0].options.zIndex).toBe(300)
  })

  it('renders a project intersection without situation metrics as a gray emphasized marker', async () => {
    render(<CityMap points={[{ id: 'INT-MISSING', lat: 36.7, lon: 117, status: 'missing', is_project: true }]} />)

    await waitFor(() => expect(mapMocks.markers).toHaveLength(1))
    expect(mapMocks.markers[0].options.content).toContain('#8290aa')
    expect(mapMocks.markers[0].options.content).toContain(' project')
  })

  it('renders road segments below intersections and UAV source markers with independent callbacks', async () => {
    const intersection = { id: 'INT-1', lat: 36.7, lon: 117, status: 'oversaturated', is_project: true }
    const segment = { id: 'SEG-1', status: 'congested', paths_gcj02: [[[117, 36.7], [117.01, 36.71]]] }
    const source = { id: 'INT-1', lat: 36.7, lon: 117, source_status: 'ready', source_count: 1 }
    const onSelect = vi.fn()
    const onSegmentSelect = vi.fn()
    const onSourceSelect = vi.fn()

    render(<CityMap points={[intersection]} segments={[segment]} sourcePoints={[source]} onSelect={onSelect} onSegmentSelect={onSegmentSelect} onSourceSelect={onSourceSelect} fitToData />)

    await waitFor(() => expect(mapMocks.markers).toHaveLength(2))
    expect(mapMocks.polylines).toHaveLength(1)
    expect(mapMocks.polylines[0].options.strokeColor).toBe('#ff715b')
    expect(mapMocks.polylines[0].options.zIndex).toBeLessThan(mapMocks.markers[0].options.zIndex)
    expect(mapMocks.markers.find((item) => item.options.extData.kind === 'intersection').options.content).toContain(' project')
    expect(mapMocks.markers.find((item) => item.options.extData.kind === 'source').options.zIndex).toBeGreaterThan(
      mapMocks.markers.find((item) => item.options.extData.kind === 'intersection').options.zIndex,
    )
    expect(mapMocks.maps[0].fitViewArgs[2]).toEqual([64, 76, 300, 60])
    mapMocks.polylines[0].click()
    mapMocks.markers.find((item) => item.options.extData.kind === 'intersection').click()
    mapMocks.markers.find((item) => item.options.extData.kind === 'source').click()
    expect(onSegmentSelect).toHaveBeenCalledWith(segment)
    expect(onSelect).toHaveBeenCalledWith(intersection)
    expect(onSourceSelect).toHaveBeenCalledWith(source)
  })

  it('renders pure AMap realtime traffic and restores situation overlays after switching back', async () => {
    const point = { id: 'INT-1', lat: 36.7, lon: 117, status: 'oversaturated' }
    const segment = { id: 'SEG-1', status: 'congested', paths_gcj02: [[[117, 36.7], [117.01, 36.71]]] }
    const source = { id: 'INT-1', lat: 36.7, lon: 117, source_status: 'ready' }
    const view = render(<CityMap displayMode='traffic' points={[point]} segments={[segment]} sourcePoints={[source]} fitToData />)

    await waitFor(() => expect(mapMocks.trafficLayers).toHaveLength(1))
    expect(mapMocks.trafficLayers[0].options).toEqual({ autoRefresh: true, interval: 180, zIndex: 10 })
    expect(mapMocks.maps[0].added).toContain(mapMocks.trafficLayers[0])
    expect(mapMocks.maps[0].fitViewArgs).toBeUndefined()
    expect(mapMocks.markers).toHaveLength(0)
    expect(mapMocks.polylines).toHaveLength(0)
    expect(screen.getByText('高德实时路况 · GCJ-02')).toBeInTheDocument()

    view.rerender(<CityMap displayMode='situation' points={[point]} segments={[segment]} sourcePoints={[source]} fitToData />)

    await waitFor(() => expect(mapMocks.markers).toHaveLength(2))
    expect(mapMocks.polylines).toHaveLength(1)
    expect(mapMocks.maps[1].fitViewArgs[2]).toEqual([64, 76, 300, 60])
  })

  it('keeps one realtime traffic map instance when refreshed data only updates the UAV overlay', async () => {
    const point = { id: 'INT-1', lat: 36.7, lon: 117, status: 'oversaturated' }
    const source = { id: 'INT-1', lat: 36.7, lon: 117, source_status: 'running' }
    const drone = {
      id: 'UAV-LIVE-1', name: '泉城一号', lat: 36.7, lon: 117,
      is_monitoring: true, is_flying: true, is_online: true, status_label: '实时监控',
    }
    const view = render(
      <CityMap displayMode='traffic' points={[point]} sourcePoints={[source]} liveDronePoints={[drone]} />,
    )

    await waitFor(() => expect(mapMocks.markers).toHaveLength(1))
    expect(mapMocks.maps).toHaveLength(1)
    expect(mapMocks.trafficLayers).toHaveLength(1)

    view.rerender(
      <CityMap
        displayMode='traffic'
        points={[{ ...point }]}
        sourcePoints={[{ ...source }]}
        liveDronePoints={[{ ...drone, lon: 117.001 }]}
      />,
    )

    await waitFor(() => expect(mapMocks.markers.at(-1).options.position).toEqual([117.001, 36.7]))
    expect(mapMocks.maps).toHaveLength(1)
    expect(mapMocks.trafficLayers).toHaveLength(1)
  })

  it('keeps truthful live UAV overlays on realtime traffic and opens the detail panel from every marker', async () => {
    const onLiveDroneSelect = vi.fn()
    const drone = {
      id: 'UAV-LIVE-1', name: '泉城一号', lat: 36.7, lon: 117,
      is_monitoring: true, is_flying: true, is_online: true, status_label: '实时监控',
      can_open_monitoring: false,
      intersection_name: '经十路舜华路口', video_stream_url: 'http://127.0.0.1:8127/video',
      battery_pct: 78, altitude_m: 88.6, speed_mps: 6.2, telemetry_note: '遥测质量 verified',
      trail_gcj02: [[116.999, 36.699], [117, 36.7]],
    }
    const view = render(<CityMap displayMode='traffic' liveDronePoints={[drone]} onLiveDroneSelect={onLiveDroneSelect} />)

    await waitFor(() => expect(mapMocks.markers).toHaveLength(1))
    const marker = mapMocks.markers[0]
    expect(marker.options.extData.kind).toBe('live-drone')
    expect(marker.options.content).toBeInstanceOf(HTMLElement)
    expect(marker.options.content).toHaveAttribute('data-drone-id', 'UAV-LIVE-1')
    expect(marker.options.content).toHaveAttribute('role', 'button')
    expect(marker.options.content).toHaveAttribute('tabindex', '0')
    expect(marker.options.content).toHaveAttribute('aria-pressed', 'false')
    expect(marker.options.content).toHaveTextContent('泉城一号')
    expect(marker.options.content).toHaveTextContent('点击查看飞行详情')
    expect(marker.options.content.querySelector('img')).not.toBeInTheDocument()
    expect(mapMocks.polylines.find((item) => item.options.extData.kind === 'live-drone-trail').options).toMatchObject({
      path: [[116.999, 36.699], [117, 36.7]],
      strokeColor: '#ffffff',
      strokeStyle: 'solid',
      showDir: true,
    })
    fireEvent.click(marker.options.content)
    expect(onLiveDroneSelect).toHaveBeenCalledWith(drone)
    fireEvent.keyDown(marker.options.content, { key: 'Enter' })
    fireEvent.keyDown(marker.options.content, { key: ' ' })
    expect(onLiveDroneSelect).toHaveBeenCalledTimes(3)

    view.rerender(<CityMap displayMode='traffic' liveDronePoints={[{ ...drone, lon: 117.001 }]} selectedLiveDroneId='UAV-LIVE-1' onLiveDroneSelect={onLiveDroneSelect} fitToData viewportInsets={{ top: 100, right: 350, bottom: 80, left: 338 }} />)
    await waitFor(() => expect(mapMocks.markers.at(-1).options.position).toEqual([117.001, 36.7]))
    const selectedMarker = mapMocks.markers.at(-1)
    expect(selectedMarker.options.content).toHaveAttribute('aria-pressed', 'true')
    expect(selectedMarker.options.content).toHaveClass('selected')
    expect(mapMocks.maps.at(-1).fitViewArgs).toEqual([[selectedMarker], false, [100, 350, 80, 338], 13])
  })

  it('focuses a selected running replay on its truthful live trail so cruise movement stays visible', async () => {
    const drone = {
      id: 'UAV-REPLAY-1', name: '回放无人机 · 经十路巡航', lat: 36.702, lon: 117.002,
      is_monitoring: true, is_flying: true, is_online: true, is_replay: true,
      status_label: '回放巡航', position_basis: 'replay_gcj02_trajectory',
      trail_gcj02: [[117, 36.7], [117.001, 36.701], [117.002, 36.702]],
    }

    render(<CityMap displayMode='traffic' liveDronePoints={[drone]} selectedLiveDroneId='UAV-REPLAY-1' fitToData viewportInsets={{ top: 100, right: 350, bottom: 80, left: 338 }} />)

    await waitFor(() => expect(mapMocks.markers).toHaveLength(1))
    const marker = mapMocks.markers[0]
    const trail = mapMocks.polylines.find((item) => item.options.extData.kind === 'live-drone-trail')
    expect(mapMocks.maps[0].fitViewArgs).toEqual([[marker, trail], false, [100, 350, 80, 338], 16])
  })

  it('selects a point from its marker', async () => {
    const onSelect = vi.fn()
    const point = { id: 'INT-1', lat: 36.7, lon: 117 }
    render(<CityMap points={[point]} onSelect={onSelect} />)
    await waitFor(() => expect(mapMocks.markers).toHaveLength(1))
    mapMocks.markers[0].click()
    expect(onSelect).toHaveBeenCalledWith(point)
    fireEvent.click(screen.getByRole('button', { name: '复位' }))
  })

  it('keeps the map available when local development only provides an AMap Web Key', async () => {
    window.__RUNTIME_CONFIG__ = {}
    vi.stubEnv('AMAP_JS_API_KEY', 'web-key')

    render(<CityMap points={[{ id: 'INT-1', lat: 36.7, lon: 117, risk: 'normal' }]} />)

    await waitFor(() => expect(mapMocks.markers).toHaveLength(1))
    expect(screen.queryByText('高德地图服务不可用')).not.toBeInTheDocument()
  })
})
