import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { applyMineMapDarkStyle, createMineMapAdapter, mineMapConfig } from './minemap'

vi.mock('@amap/amap-jsapi-loader', () => ({ default: { load: vi.fn() } }))
import AMapLoader from '@amap/amap-jsapi-loader'
import { loadAmap, resetAmapLoaderForTest } from './amap'

let native
class NativeMap {
  constructor(options) {
    this.options = options; this.events = {}; this.sources = new Map(); this.layers = []
    native = this
  }
  on(event, ...args) { if (args.length === 1) this.events[event] = args[0] }
  off = vi.fn()
  addSource(id, source) { this.sources.set(id, { ...source, setData: vi.fn() }) }
  getSource(id) { return this.sources.get(id) }
  addLayer(layer, before) { this.layers.push({ ...layer, before }) }
  removeSource = vi.fn()
  removeLayer = vi.fn()
  remove = vi.fn()
  fitBounds = vi.fn()
  setBearing = vi.fn()
  setPitch = vi.fn()
  setCenter = vi.fn()
  jumpTo = vi.fn()
  resize = vi.fn()
  unproject = vi.fn(() => [117, 36.7])
  addControl = vi.fn()
  getStyle = () => ({ layers: [] })
  setPaintProperty = vi.fn()
}
class NativeMarker {
  constructor(options) { this.options = options }
  setLngLat(position) { this.position = position; return this }
  addTo(map) { this.map = map; return this }
  remove = vi.fn()
}
const sdk = { Map: NativeMap, Marker: NativeMarker, Scale: class {} }
const config = { domain: 'http://37.8.188.98:21009', key: 'site-key', solution: '17000' }

beforeEach(() => {
  resetAmapLoaderForTest(); AMapLoader.load.mockClear()
  window.__RUNTIME_CONFIG__ = { mapProvider: 'minemap', minemapDomain: config.domain, minemapKey: config.key }
  delete window.minemap
})
afterEach(() => {
  document.querySelectorAll('script[src*="minemapapi"],link[href*="minemapapi"]').forEach((node) => node.remove())
  vi.unstubAllGlobals(); delete window.__RUNTIME_CONFIG__; delete window.minemap
})

describe('MineMap SDK and offline boundary', () => {
  it('uses explicitly configured SDK, style and split MineMap service origins', async () => {
    Object.assign(window.__RUNTIME_CONFIG__, {
      minemapSdkBaseUrl: 'https://minedata.cn/minemapapi/v2/latest',
      minemapServiceUrl: 'https://service.minedata.cn/service',
      minemapServerDomain: 'https://ol-data.minedata.cn',
      minemapStyleUrl: 'https://service.minedata.cn/map/solu/style/11001',
    })
    const loading = loadAmap()
    const script = document.querySelector('script[src*="minemapapi"]')
    const css = document.querySelector('link[href*="minemapapi"]')
    expect(script.src).toBe('https://minedata.cn/minemapapi/v2/latest/minemap.js')
    window.minemap = { ...sdk }; script.onload(); css.onload()
    const api = await loading
    const map = new api.Map(document.createElement('div'), { center: [117, 36.7], zoom: 12 })
    expect(native.options.style).toBe('https://service.minedata.cn/map/solu/style/11001')
    expect(window.minemap.serverDomainUrl).toBe('https://ol-data.minedata.cn')
    expect(window.minemap.serviceUrl).toBe('https://service.minedata.cn/service')
    expect(native.options.transformRequest('https://ol-data.minedata.cn/tile.pbf').url).toContain('ol-data')
    expect(() => native.options.transformRequest('https://unconfigured.example/tile.pbf')).toThrow('地图服务')
    map.destroy()
  })

  it('requires the site key and rejects origins containing credentials or paths', () => {
    expect(mineMapConfig()).toEqual(config)
    window.__RUNTIME_CONFIG__.minemapKey = ''
    expect(mineMapConfig).toThrow('Key')
    window.__RUNTIME_CONFIG__.minemapKey = config.key
    window.__RUNTIME_CONFIG__.minemapDomain = 'http://user:pass@map.example'
    expect(mineMapConfig).toThrow('不含路径和凭据')
  })

  it('loads only the configured SDK/CSS, configures internal services and never calls AMap', async () => {
    const loading = loadAmap()
    const script = document.querySelector('script[src*="minemapapi"]')
    const css = document.querySelector('link[href*="minemapapi"]')
    expect(script.src).toBe(`${config.domain}/minemapapi/v2.1.0/minemap.js`)
    expect(css.href).toBe(`${config.domain}/minemapapi/v2.1.0/minemap.css`)
    window.minemap = { ...sdk }
    script.onload(); css.onload()
    const api = await loading
    expect(window.minemap.key).toBe(config.key)
    expect(window.minemap.accessToken).toBeUndefined()
    expect(window.minemap.dataDomainUrl).toBe(config.domain)
    expect(window.minemap.serviceUrl).toBe(`${config.domain}/service`)
    expect(api.Marker).toBeTypeOf('function')
    expect(AMapLoader.load).not.toHaveBeenCalled()
    expect(loadAmap()).toBe(loading)
  })

  it('reports SDK failure without falling back and permits retry', async () => {
    const loading = loadAmap()
    const rejected = expect(loading).rejects.toThrow('加载失败')
    document.querySelector('script[src*="minemapapi"]').onerror()
    document.querySelector('link[href*="minemapapi"]').onerror()
    await rejected
    expect(AMapLoader.load).not.toHaveBeenCalled()
    expect(document.querySelectorAll('script[src*="minemapapi"]')).toHaveLength(0)
  })
})

describe('MineMap overlay and lifecycle contract', () => {
  it('queues only current overlays until style load, preserves GCJ-02 and releases resources', () => {
    const api = createMineMapAdapter(sdk, config)
    const map = new api.Map(document.createElement('div'), { center: [117, 36.7], zoom: 18 })
    const stale = new api.Polyline({ path: [[117, 36.7], [117.1, 36.8]] })
    const line = new api.Polyline({ path: [[117, 36.7], [117.2, 36.9]], strokeStyle: 'dashed', strokeOpacity: 0.16 })
    map.add([stale, line]); map.remove(stale)
    line.setPath([[117, 36.7], [117.3, 37]])
    native.events.load()
    expect(native.sources.size).toBe(1)
    expect(native.getSource(line.id).data.geometry.coordinates).toEqual([[117, 36.7], [117.3, 37]])
    expect(native.layers[0].paint).toMatchObject({ 'line-dasharray': [3, 2], 'line-opacity': 0.16 })
    line.setPath([[118, 37], [118.1, 37.1]])
    expect(native.getSource(line.id).setData).toHaveBeenCalledWith(expect.objectContaining({ geometry: { type: 'LineString', coordinates: [[118, 37], [118.1, 37.1]] } }))
    map.destroy()
    expect(native.removeLayer).toHaveBeenCalledWith(line.layerIds[0] || `${line.id}-0`)
    expect(native.removeSource).toHaveBeenCalledWith(line.id)
    expect(native.remove).toHaveBeenCalledOnce()
  })

  it('closes polygon rings without changing input and maps endpoint radius to circle layers', () => {
    const api = createMineMapAdapter(sdk, config)
    const map = new api.Map(document.createElement('div'), { center: [117, 36.7], zoom: 18 })
    native.events.load()
    const path = [[117, 36.7], [117.1, 36.8], [117.2, 36.7]]
    const polygon = new api.Polygon({ path, fillOpacity: 0.2 })
    map.add(polygon)
    map.add(new api.CircleMarker({ center: [117.1, 36.8], radius: 4.5 }))
    expect(path).toHaveLength(3)
    expect(native.getSource(polygon.id).data.geometry.coordinates).toEqual([[...path, path[0]]])
    expect(native.layers.map((layer) => layer.type)).toEqual(['fill', 'line', 'circle'])
    expect(native.layers[2].paint['circle-radius']).toBe(4.5)
  })

  it('keeps marker events when content changes and updates the actual position', () => {
    const api = createMineMapAdapter(sdk, config)
    const marker = new api.Marker({ position: [117, 36.7], content: '<span>UAV</span>', zIndex: 500 })
    const click = vi.fn(); marker.on('click', click)
    marker.setContent(document.createElement('button'))
    marker.element.firstChild.click()
    marker.setPosition([117.1, 36.8])
    expect(click).toHaveBeenCalledOnce()
    expect(marker.native.position).toEqual([117.1, 36.8])
    expect(marker.element.style.zIndex).toBe('500')
  })

  it('keeps registered orthophotos at the app origin and places road geometry above imagery', () => {
    const api = createMineMapAdapter(sdk, config)
    const map = new api.Map(document.createElement('div'), { center: [117, 36.7], zoom: 18 })
    native.events.load()
    const image = new api.ImageLayer({ url: '/api/v1/calibration/media', bounds: new api.Bounds([117, 36], [118, 37]), opacity: 0.72, zIndex: 5 })
    map.add(image)
    const line = new api.Polyline({ path: [[117, 36], [118, 37]] })
    map.add(line)
    expect(native.getSource(image.id)).toMatchObject({ type: 'image', url: `${window.location.origin}/api/v1/calibration/media`, coordinates: [[117, 37], [118, 37], [118, 36], [117, 36]] })
    expect(line.zIndex).toBeGreaterThan(image.zIndex)
    expect(native.options.transformRequest(`${window.location.origin}/api/v1/calibration/media`).url).toBe(`${window.location.origin}/api/v1/calibration/media`)
    map.remove(image)
    expect(native.removeSource).toHaveBeenCalledWith(image.id)
  })

  it('maps viewport padding, pitch and bearing and forbids external style resources', () => {
    const api = createMineMapAdapter(sdk, config)
    const map = new api.Map(document.createElement('div'), { center: [117, 36.7], zoom: 18 })
    map.setFitView([new api.Marker({ position: [117, 36.7], content: '' }), new api.Marker({ position: [118, 37], content: '' })], true, [10, 20, 30, 40], 20)
    expect(native.fitBounds).toHaveBeenCalledWith([[117, 36.7], [118, 37]], { padding: { top: 10, right: 20, bottom: 30, left: 40 }, maxZoom: 20, duration: 0 })
    map.setPitch(42); map.setRotation(180)
    expect(native.setPitch).toHaveBeenCalledWith(42)
    expect(native.setBearing).toHaveBeenCalledWith(180)
    expect(native.options.transformRequest('/service/tile')).toEqual({ url: `${config.domain}/service/tile` })
    expect(() => native.options.transformRequest('https://webapi.amap.com/tile')).toThrow('内网地图服务')
  })
})


describe('MineMap dark basemap', () => {
  it('retains road hierarchy and readable labels while preserving business overlay colors', () => {
    const layers = [
      { id: 'base', type: 'background', paint: { 'background-color': '#ffffff' } },
      { id: 'river', type: 'fill', 'source-layer': 'water_surface', paint: { 'fill-color': '#9fd7fc' } },
      { id: 'park', type: 'fill', 'source-layer': 'green_surface', paint: { 'fill-color': '#afe6c5' } },
      { id: 'main-road', type: 'line', 'source-layer': 'expressway', paint: { 'line-color': '#ffff00', 'line-border-color': '#ffffff', 'line-width': 5 } },
      { id: 'street', type: 'line', 'source-layer': 'otherRoad', paint: { 'line-color': '#ffffff', 'line-width': 2 } },
      { id: 'labels', type: 'symbol', layout: { 'text-field': '{name}' }, paint: { 'text-color': '#222222', 'text-halo-color': '#ffffff' } },
      { id: 'uav-overlay-1-0', type: 'line', paint: { 'line-color': '#ff7043' } },
    ]
    const snapshot = JSON.stringify(layers)
    const map = { getStyle: () => ({ layers }), setPaintProperty: vi.fn() }
    applyMineMapDarkStyle(map)
    expect(map.setPaintProperty).toHaveBeenCalledWith('base', 'background-color', '#091321')
    expect(map.setPaintProperty).toHaveBeenCalledWith('river', 'fill-color', '#102e46')
    expect(map.setPaintProperty).toHaveBeenCalledWith('park', 'fill-color', '#122d2c')
    expect(map.setPaintProperty).toHaveBeenCalledWith('main-road', 'line-color', '#537b98')
    expect(map.setPaintProperty).toHaveBeenCalledWith('street', 'line-color', '#2c435a')
    expect(map.setPaintProperty).toHaveBeenCalledWith('labels', 'text-color', '#b1c2d5')
    expect(map.setPaintProperty.mock.calls.some(([id, name]) => id.startsWith('uav-overlay-') || name === 'line-width')).toBe(false)
    expect(JSON.stringify(layers)).toBe(snapshot)
  })
})
