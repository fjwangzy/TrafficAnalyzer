import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mapMocks = vi.hoisted(() => ({ tileHandlers: {}, views: [] }))

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
vi.mock('ol/layer/Vector.js', () => ({ default: class { constructor(options) { this.options = options } } }))
vi.mock('ol/source/OSM.js', () => ({ default: class {
  on(name, handler) { mapMocks.tileHandlers[name] = handler }
} }))
vi.mock('ol/source/Vector.js', () => ({ default: class { constructor(options) { this.options = options } } }))
vi.mock('ol/Feature.js', () => ({ default: class {
  constructor(options) { this.options = options }
  setId(id) { this.id = id }
  get() { return null }
} }))
vi.mock('ol/geom/Point.js', () => ({ default: class { constructor(value) { this.value = value } } }))
vi.mock('ol/proj.js', () => ({ fromLonLat: (value) => value }))
vi.mock('ol/style.js', () => ({
  Circle: class {}, Fill: class {}, Stroke: class {}, Style: class {},
}))

import { CityMap } from './CityMap'

describe('CityMap failure boundary', () => {
  beforeEach(() => {
    mapMocks.tileHandlers = {}
    mapMocks.views = []
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
})
