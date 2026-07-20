import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mapMocks = vi.hoisted(() => ({ tileHandlers: {}, views: [], vectorLayers: [] }))

vi.mock('ol/Map.js', () => ({ default: class {
  constructor({ view }) { this.view = view }
  on() {}
  setTarget() {}
  getView() { return this.view }
  forEachFeatureAtPixel() {}
} }))
vi.mock('ol/View.js', () => ({ default: class {
  constructor(options) { this.options = options; mapMocks.views.push(this) }
  setZoom() {}
  setCenter() {}
} }))
vi.mock('ol/layer/Tile.js', () => ({ default: class { constructor(options) { this.options = options } } }))
vi.mock('ol/layer/Vector.js', () => ({ default: class { constructor(options) { this.options = options; mapMocks.vectorLayers.push(this) } } }))
vi.mock('ol/source/OSM.js', () => ({ default: class {
  on(name, handler) { mapMocks.tileHandlers[name] = handler }
} }))
vi.mock('ol/source/Vector.js', () => ({ default: class { constructor(options) { this.options = options } } }))
vi.mock('ol/Feature.js', () => ({ default: class {
  constructor(options) { this.options = options }
  setId(id) { this.id = id }
  get(name) { return this.options[name] }
} }))
vi.mock('ol/geom/Point.js', () => ({ default: class { constructor(value) { this.value = value } } }))
vi.mock('ol/proj.js', () => ({ fromLonLat: (value) => value }))
vi.mock('ol/style.js', () => ({
  Circle: class { constructor(options) { this.options = options } },
  Fill: class { constructor(options) { this.options = options } },
  Icon: class { constructor(options) { this.options = options } },
  Stroke: class { constructor(options) { this.options = options } },
  Style: class { constructor(options) { this.options = options } },
}))

import { CityMap } from './CityMap'

describe('CityMap failure boundary', () => {
  beforeEach(() => {
    mapMocks.tileHandlers = {}
    mapMocks.views = []
    mapMocks.vectorLayers = []
  })

  it('keeps the dashboard truthful when the development basemap repeatedly fails', () => {
    render(<CityMap points={[{ id: 'INT-1', lat: 36.7, lon: 117, risk: 'normal' }]} />)
    expect(screen.getByText(/OpenStreetMap contributors · 开发底图/)).toBeInTheDocument()

    act(() => {
      mapMocks.tileHandlers.tileloaderror()
      mapMocks.tileHandlers.tileloaderror()
      mapMocks.tileHandlers.tileloaderror()
    })

    expect(screen.getByText('城市底图服务不可用')).toBeInTheDocument()
    expect(screen.getByText(/不使用随机点位冒充真实地图/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重试底图' }))
    expect(screen.getByText(/OpenStreetMap contributors · 开发底图/)).toBeInTheDocument()
  })

  it('renders acceptance intersections with a drone SVG marker', () => {
    render(<CityMap markerType='drone' coordinateLabel='验收测试坐标 4 处' points={[{ id: 'SRC-1', lat: 36.7, lon: 117, source_status: 'running' }]} />)
    const layer = mapMocks.vectorLayers[0]
    const feature = layer.options.source.options.features[0]
    const style = layer.options.style(feature)
    expect(style.options.image.options.src).toMatch(/^data:image\/svg\+xml/)
    expect(style.options.image.options.src).toContain('%2358d6b0')
    expect(screen.getByText(/验收测试坐标 4 处/)).toBeInTheDocument()
  })

  it('uses distinct marker colors for degraded UAV video sources', () => {
    render(<CityMap markerType='drone' points={[{ id: 'SRC-D', lat: 36.7, lon: 117, source_status: 'degraded' }]} />)
    const layer = mapMocks.vectorLayers[0]
    const feature = layer.options.source.options.features[0]
    expect(layer.options.style(feature).options.image.options.src).toContain('%23ffbe55')
  })

  it('centers the view across all acceptance intersections', () => {
    render(<CityMap points={[
      { id: 'INT-1', lat: 36.7, lon: 117, risk: 'normal' },
      { id: 'INT-2', lat: 36.8, lon: 117.1, risk: 'normal' },
    ]} />)
    expect(mapMocks.views[0].options.center[0]).toBeCloseTo(117.05)
    expect(mapMocks.views[0].options.center[1]).toBeCloseTo(36.75)
  })

  it('visually separates nearby drone markers without changing their coordinates', () => {
    render(<CityMap markerType='drone' points={[
      { id: 'INT-A', lat: 36.66278, lon: 117.09309, risk: 'normal' },
      { id: 'INT-B', lat: 36.66278, lon: 117.0954, risk: 'normal' },
    ]} />)
    const layer = mapMocks.vectorLayers[0]
    const [leftFeature, rightFeature] = layer.options.source.options.features
    expect(layer.options.style(leftFeature).options.image.options.displacement).not.toEqual(
      layer.options.style(rightFeature).options.image.options.displacement,
    )
    expect(leftFeature.options.geometry.value).toEqual([117.09309, 36.66278])
    expect(rightFeature.options.geometry.value).toEqual([117.0954, 36.66278])
  })
})
