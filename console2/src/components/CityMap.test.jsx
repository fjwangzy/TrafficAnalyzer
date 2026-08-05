import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mapMocks = vi.hoisted(() => ({ maps: [], markers: [], polylines: [] }))

vi.mock('@amap/amap-jsapi-loader', () => ({
  default: {
    load: vi.fn(async () => {
    class Map {
      constructor(_target, options) { this.options = options; mapMocks.maps.push(this) }
      add() {}
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
    }
    class Polyline {
      constructor(options) { this.options = options; mapMocks.polylines.push(this) }
      on(_name, handler) { this.click = handler }
    }
    return { Map, Marker, Polyline, Scale: class {} }
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
