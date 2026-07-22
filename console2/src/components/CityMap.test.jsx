import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mapMocks = vi.hoisted(() => ({ maps: [], markers: [] }))

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
    }
    class Marker {
      constructor(options) { this.options = options; mapMocks.markers.push(this) }
      on(_name, handler) { this.click = handler }
    }
    return { Map, Marker, Scale: class {} }
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
  })

  it('renders GCJ-02 attribution and AMap marker coordinates', async () => {
    render(<CityMap points={[{ id: 'INT-1', lat: 36.7, lon: 117, risk: 'normal' }]} />)
    expect(screen.getByText('高德地图 · GCJ-02')).toBeInTheDocument()
    await waitFor(() => expect(mapMocks.markers).toHaveLength(1))
    expect(mapMocks.markers[0].options.position).toEqual([117, 36.7])
  })

  it('uses the source status color for drone markers', async () => {
    render(<CityMap markerType='drone' coordinateLabel='GCJ-02' points={[{ id: 'SRC-1', lat: 36.7, lon: 117, source_status: 'running' }]} />)
    await waitFor(() => expect(mapMocks.markers).toHaveLength(1))
    expect(mapMocks.markers[0].options.content).toContain('#58d6b0')
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
