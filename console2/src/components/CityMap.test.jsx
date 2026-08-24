import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mapMocks = vi.hoisted(() => ({ maps: [], markers: [], polylines: [], polygons: [], trafficLayers: [], satelliteLayers: [], roadNetLayers: [] }))

vi.mock('@amap/amap-jsapi-loader', () => ({
  default: {
    load: vi.fn(async () => {
    class Map {
      constructor(_target, options) { this.options = options; this.handlers = {}; this.fitViewCalls = []; this.rotationCalls = []; this.pitchCalls = []; this.centerCalls = []; this.containerPixels = []; mapMocks.maps.push(this) }
      on(name, handler) { this.handlers[name] = handler }
      add(item) { this.added = [...(this.added || []), item] }
      remove(item) { this.removed = [...(this.removed || []), item] }
      addControl() {}
      destroy() {}
      zoomIn() {}
      zoomOut() {}
      setZoomAndCenter(...args) { this.zoomAndCenterArgs = args }
      setCenter(value) { this.centerCalls.push(value) }
      setPitch(value) { this.pitch = value; this.pitchCalls.push(value) }
      setRotation(value) { this.rotation = value; this.rotationCalls.push(value) }
      setFitView(...args) { this.fitViewArgs = args; this.fitViewCalls.push(args) }
      getSize() { return { getWidth: () => 1200, getHeight: () => 800 } }
      containerToLngLat(pixel) { this.containerPixels.push([pixel.x, pixel.y]); return [116 + pixel.x / 10000, 36 + pixel.y / 10000] }
    }
    class Marker {
      constructor(options) { this.options = options; mapMocks.markers.push(this) }
      on(_name, handler) { this.click = handler }
      setPosition(position) { this.options.position = position }
      moveTo(position, options) { this.moveToArgs = [position, options]; this.options.position = position }
      setContent(content) { this.options.content = content }
      setzIndex(zIndex) { this.options.zIndex = zIndex }
    }
    class Polyline {
      constructor(options) { this.options = options; mapMocks.polylines.push(this) }
      on(_name, handler) { this.click = handler }
      setPath(path) { this.options.path = path }
    }
    class Polygon {
      constructor(options) { this.options = options; mapMocks.polygons.push(this) }
    }
    class Traffic {
      constructor(options) { this.options = options; mapMocks.trafficLayers.push(this) }
      hide() { this.hidden = true }
      show() { this.hidden = false }
    }
    class Satellite {
      constructor(options) { this.options = options; mapMocks.satelliteLayers.push(this) }
      hide() { this.hidden = true }
      show() { this.hidden = false }
    }
    class RoadNet {
      constructor(options) { this.options = options; mapMocks.roadNetLayers.push(this) }
      hide() { this.hidden = true }
      show() { this.hidden = false }
    }
    class Pixel { constructor(x, y) { this.x = x; this.y = y } }
    return { Map, Marker, Polyline, Polygon, Pixel, Scale: class {}, TileLayer: { Traffic, Satellite, RoadNet } }
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
    mapMocks.polygons = []
    mapMocks.trafficLayers = []
    mapMocks.satelliteLayers = []
    mapMocks.roadNetLayers = []
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

  it('hides UAV hover details and keeps UAV markers above vehicles while digital twin mode is active', async () => {
    const drone = {
      id: 'UAV-TWIN-1', name: '回放无人机 · 经十路巡航', lat: 36.7, lon: 117,
      is_monitoring: true, is_flying: true, is_online: true, status_label: '回放巡航',
      scene_label: '道路巡检 · 可控回放', telemetry_note: '回放遥测 · degraded',
    }
    const twin = {
      active: true, contextKey: 'PIPE-1:INT-1', level: 'spatial',
      label: '空间轨迹 · GCJ-02 · 活跃车辆 1', dataMode: 'controlled_replay',
      availableLayers: { georeferencedVehicles: true },
      geometry: { lanes: [], links: [], stopLines: [], areas: [], coverage: [] },
      vehicles: [{ id: '7', track_id: 7, vehicle_class: 'car', trajectory_gcj02: [[117, 36.7], [117.0001, 36.7001]] }],
      pixelVehicles: [],
    }
    const view = render(<CityMap
      displayMode='traffic'
      liveDronePoints={[drone]}
      selectedLiveDroneId='UAV-TWIN-1'
      digitalTwin={twin}
    />)

    await waitFor(() => expect(mapMocks.markers.find((item) => item.options.extData.kind === 'digital-twin-vehicle')).toBeTruthy())
    const vehicle = mapMocks.markers.find((item) => item.options.extData.kind === 'digital-twin-vehicle')
    const uav = mapMocks.markers.find((item) => item.options.extData.kind === 'live-drone')
    expect(uav.options.content.querySelector('[role="tooltip"]')).toBeNull()
    expect(uav.options.zIndex).toBeGreaterThan(vehicle.options.zIndex)
    expect(uav.options.zIndex).toBe(1000)

    view.rerender(<CityMap
      displayMode='traffic'
      liveDronePoints={[drone]}
      selectedLiveDroneId='UAV-TWIN-1'
      digitalTwin={{ active: false }}
    />)
    await waitFor(() => expect(uav.options.content.querySelector('[role="tooltip"]')).not.toBeNull())
    expect(uav.options.zIndex).toBe(560)
    expect(mapMocks.maps).toHaveLength(1)
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

  it('renders verified twin layers and incrementally animates mature GCJ-02 vehicles without rebuilding AMap', async () => {
    const digitalTwin = {
      active: true,
      contextKey: 'PIPE-1:INT-1',
      level: 'lane',
      label: '车道级 · Lane 1 · 活跃车辆 1',
      dataMode: 'live',
      mapVersionId: 'MAP-1',
      geometry: {
        lanes: [{ id: 'lane:LANE-1', kind: 'lane', type: 'line', path: [[117, 36.7], [117.001, 36.701]], keys: ['LANE-1'] }],
        links: [{ id: 'link:LINK-1', kind: 'link', type: 'line', path: [[116.999, 36.699], [117.002, 36.702]], keys: ['LINK-1'] }],
        stopLines: [{ id: 'stop:1', kind: 'stop_line', type: 'line', path: [[117, 36.7], [117.0001, 36.7001]], keys: [] }],
        areas: [{ id: 'area:1', kind: 'area', type: 'polygon', path: [[117, 36.7], [117.001, 36.7], [117, 36.701]], keys: [] }],
      },
      vehicles: [{ id: '7', track_id: 7, vehicle_class: 'car', avg_speed_kmh: 24.5, matched_lane_key: 'LANE-1', trajectory_gcj02: [[117, 36.7], [117.0001, 36.7001]] }],
    }
    const view = render(<CityMap displayMode='traffic' digitalTwin={digitalTwin} fitToData />)

    await waitFor(() => expect(mapMocks.markers.find((item) => item.options.extData.kind === 'digital-twin-vehicle')).toBeTruthy())
    const vehicle = mapMocks.markers.find((item) => item.options.extData.kind === 'digital-twin-vehicle')
    expect(vehicle.options.content).toHaveAttribute('data-track-id', '7')
    expect(vehicle.options.content).toHaveAccessibleName(/车辆 7/)
    expect(mapMocks.polylines.find((item) => item.options.extData.kind === 'digital-twin-lane').options.strokeColor).toBe('#ffca67')
    expect(mapMocks.polygons.find((item) => item.options.extData.kind === 'digital-twin-area')).toBeTruthy()
    expect(mapMocks.trafficLayers[0].hidden).toBe(true)
    expect(screen.getByText('车道级 · Lane 1 · 活跃车辆 1')).toBeInTheDocument()

    view.rerender(<CityMap displayMode='traffic' digitalTwin={{
      ...digitalTwin,
      vehicles: [{ ...digitalTwin.vehicles[0], trajectory_gcj02: [[117.0001, 36.7001], [117.0002, 36.7002]] }],
    }} fitToData />)

    await waitFor(() => expect(vehicle.moveToArgs).toEqual([[117.0002, 36.7002], { duration: 900, autoRotation: false }]))
    expect(Number(vehicle.options.content.dataset.headingDeg)).toBeGreaterThan(0)
    expect(mapMocks.maps).toHaveLength(1)
    expect(mapMocks.trafficLayers).toHaveLength(1)
  })

  it('fits a verified intersection to current vehicle positions instead of the full road-map extent', async () => {
    const digitalTwin = {
      active: true,
      contextKey: 'PIPE-XQH:INT-XQH',
      level: 'lane',
      label: '车道级 · Lane 64 · 活跃车辆 1',
      dataMode: 'controlled_replay',
      mapVersionId: 'MAP-XQH',
      availableLayers: { lanes: true, links: true, georeferencedVehicles: true },
      geometry: {
        lanes: [{ id: 'lane:far', kind: 'lane', type: 'line', path: [[117.022, 36.701], [117.034, 36.705]], keys: ['LANE-FAR'] }],
        links: [], stopLines: [], areas: [], coverage: [],
      },
      vehicles: [{ id: '7', track_id: 7, vehicle_class: 'car', trajectory_gcj02: [[117.0281, 36.7031], [117.0282, 36.7032]] }],
      pixelVehicles: [],
    }

    render(<CityMap
      displayMode='traffic'
      digitalTwin={digitalTwin}
      liveDronePoints={[{ id: 'UAV-XQH', lon: 117.02815, lat: 36.70315, is_monitoring: true, status_label: '回放巡航' }]}
      selectedLiveDroneId='UAV-XQH'
      fitToData
    />)

    await waitFor(() => expect(mapMocks.maps[0].fitViewCalls).toHaveLength(1))
    const vehicle = mapMocks.markers.find((item) => item.options.extData.kind === 'digital-twin-vehicle')
    expect(mapMocks.maps[0].fitViewArgs).toEqual([[vehicle], true, [64, 76, 300, 60], 19])
    expect(mapMocks.maps[0].centerCalls[0]).toEqual([117.02815, 36.70315])
    expect(mapMocks.maps[0].containerPixels[0][0]).toBeCloseTo(360)
    expect(mapMocks.maps[0].containerPixels[0][1]).toBe(400)
    fireEvent.click(screen.getByRole('button', { name: '复位' }))
    expect(mapMocks.maps[0].fitViewCalls).toHaveLength(2)
    expect(mapMocks.maps[0].fitViewArgs).toEqual([[vehicle], true, [64, 76, 300, 60], 19])
    expect(mapMocks.maps[0].containerPixels).toHaveLength(2)
    expect(mapMocks.maps[0].containerPixels[1][0]).toBeCloseTo(360)
    expect(mapMocks.maps[0].containerPixels[1][1]).toBe(400)
    expect(mapMocks.maps[0].zoomAndCenterArgs).toBeUndefined()
  })

  it('keeps a verified XQH camera north-up and does not refit when a polling sample temporarily loses world tracks', async () => {
    const baseTwin = {
      active: true,
      contextKey: 'PIPE-XQH:INT-XQH',
      level: 'lane',
      label: '车道级 · Lane 64 · 活跃车辆 1',
      dataMode: 'controlled_replay',
      mapVersionId: 'MAP-XQH',
      availableLayers: { lanes: true, links: true, georeferencedVehicles: true },
      geometry: {
        lanes: [{ id: 'lane:1', kind: 'lane', type: 'line', path: [[117.028, 36.703], [117.029, 36.704]], keys: ['LANE-1'] }],
        links: [], stopLines: [], areas: [], coverage: [],
      },
      vehicles: [{ id: '7', track_id: 7, vehicle_class: 'car', trajectory_gcj02: [[117.0281, 36.7031], [117.0282, 36.7032]] }],
      pixelVehicles: [],
    }
    const view = render(<CityMap displayMode='traffic' digitalTwin={baseTwin} fitToData />)

    await waitFor(() => expect(mapMocks.maps[0].fitViewCalls).toHaveLength(1))
    view.rerender(<CityMap displayMode='traffic' digitalTwin={{
      ...baseTwin,
      level: 'bev_pixel',
      label: '3D 覆盖仿真 · 活跃车辆 1',
      availableLayers: { ...baseTwin.availableLayers, georeferencedVehicles: false, simulatedVehicles: true },
      vehicles: [],
      pixelVehicles: [{ id: '9', track_id: 9, vehicle_class: 'car', trajectory_px: [[100, 100], [110, 100]] }],
      pixelGroundProjection: {
        center: [117.028285, 36.703222], widthM: 180, heightM: 102,
        frameSize: [960, 540], headingDeg: 126,
      },
    }} fitToData />)

    await waitFor(() => expect(mapMocks.markers.find((item) => item.options.extData?.kind === 'digital-twin-simulated-vehicle')).toBeTruthy())
    expect(mapMocks.maps[0].fitViewCalls).toHaveLength(1)
    expect(mapMocks.maps[0].rotation).toBe(0)
    expect(mapMocks.maps[0].pitch).toBe(42)
    expect(mapMocks.maps).toHaveLength(1)
  })

  it('projects pixel-only tracks as simulated vehicles across the main AMap and restores traffic after leaving twin mode', async () => {
    const twin = {
      active: true, contextKey: 'PIPE-1:INT-1', level: 'bev_pixel',
      label: '3D 覆盖仿真 · 约 142×80m · 活跃车辆 1', dataMode: 'preview',
      geometry: { lanes: [], links: [], stopLines: [], areas: [], coverage: [{ id: 'camera-footprint', kind: 'coverage', type: 'polygon', path: [[117, 36.7], [117.001, 36.7], [117.001, 36.701], [117, 36.701]], keys: [] }] }, vehicles: [],
      pixelVehicles: [{ id: '7', track_id: 7, vehicle_class: 'car', trajectory_px: [[10, 20], [20, 30]] }],
      pixelGroundProjection: { center: [117, 36.7], widthM: 142.22, heightM: 80, frameSize: [960, 540], headingDeg: 180 },
    }
    const view = render(<CityMap displayMode='traffic' digitalTwin={twin} />)

    await waitFor(() => expect(mapMocks.markers.find((item) => item.options.extData?.kind === 'digital-twin-simulated-vehicle')).toBeTruthy())
    const simulated = mapMocks.markers.find((item) => item.options.extData?.kind === 'digital-twin-simulated-vehicle')
    expect(simulated.options.extData.simulation_basis).toBe('trajectory_px')
    expect(simulated.options.content).toHaveAccessibleName(/像素仿真车辆 7/)
    expect(mapMocks.polylines.find((item) => item.options.extData?.kind === 'digital-twin-simulated-vehicle-trail')).toBeTruthy()
    expect(mapMocks.trafficLayers[0].hidden).toBe(true)
    expect(mapMocks.satelliteLayers[0].hidden).toBe(false)
    expect(mapMocks.roadNetLayers[0].hidden).toBe(false)
    expect(mapMocks.maps[0].pitch).toBe(50)
    expect(mapMocks.maps[0].rotation).toBe(180)
    expect(Number(simulated.options.content.dataset.headingDeg)).toBeGreaterThan(90)
    expect(mapMocks.polygons.find((item) => item.options.extData?.kind === 'digital-twin-coverage')).toBeTruthy()
    expect(screen.getByText('高德卫星影像 · 镜头跟随 180° · 3D 倾斜 · 前端 Mock 预览')).toBeInTheDocument()

    view.rerender(<CityMap displayMode='traffic' digitalTwin={{
      ...twin,
      pixelGroundProjection: { ...twin.pixelGroundProjection, headingDeg: 90 },
    }} />)
    await waitFor(() => expect(mapMocks.maps[0].rotation).toBe(270))
    expect(mapMocks.maps).toHaveLength(1)

    view.rerender(<CityMap displayMode='traffic' digitalTwin={{ active: false }} />)
    await waitFor(() => expect(mapMocks.trafficLayers[0].hidden).toBe(false))
    expect(mapMocks.satelliteLayers[0].hidden).toBe(true)
    expect(mapMocks.roadNetLayers[0].hidden).toBe(true)
    expect(mapMocks.maps[0].pitch).toBe(0)
    expect(mapMocks.maps[0].rotation).toBe(0)
    expect(mapMocks.maps).toHaveLength(1)
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

  it('notifies the dashboard when the map background is selected', async () => {
    const onMapSelect = vi.fn()
    render(<CityMap points={[{ id: 'INT-1', lat: 36.7, lon: 117 }]} onMapSelect={onMapSelect} />)

    await waitFor(() => expect(mapMocks.maps).toHaveLength(1))
    mapMocks.maps[0].handlers.click()

    expect(onMapSelect).toHaveBeenCalledOnce()
  })

  it('keeps the map available when local development only provides an AMap Web Key', async () => {
    window.__RUNTIME_CONFIG__ = {}
    vi.stubEnv('AMAP_JS_API_KEY', 'web-key')

    render(<CityMap points={[{ id: 'INT-1', lat: 36.7, lon: 117, risk: 'normal' }]} />)

    await waitFor(() => expect(mapMocks.markers).toHaveLength(1))
    expect(screen.queryByText('高德地图服务不可用')).not.toBeInTheDocument()
  })
})
