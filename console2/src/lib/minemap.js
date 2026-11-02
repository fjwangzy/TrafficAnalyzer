// Keep the existing overlay contract at the SDK boundary; business coordinates stay GCJ-02.
export function mineMapConfig() {
  const runtime = window.__RUNTIME_CONFIG__ || {}
  const domain = String(runtime.minemapDomain || import.meta.env.VITE_MINEMAP_DOMAIN || '').replace(/\/$/, '')
  const key = runtime.minemapKey || import.meta.env.VITE_MINEMAP_KEY || ''
  const solution = String(runtime.minemapSolution || import.meta.env.VITE_MINEMAP_SOLUTION || '17000')
  if (!/^https?:\/\/[^/?#\s]+$/.test(domain) || !key || !/^\d+$/.test(solution)) {
    throw new Error('请配置 MineMap 服务地址、Key 和方案 ID')
  }
  const parsed = new URL(domain)
  if (parsed.username || parsed.password) throw new Error('MineMap 地址必须是不含路径和凭据的 HTTP(S) origin')
  const extras = {
    sdkBaseUrl: runtime.minemapSdkBaseUrl,
    serviceUrl: runtime.minemapServiceUrl,
    serverDomain: runtime.minemapServerDomain,
    styleUrl: runtime.minemapStyleUrl,
  }
  for (const [name, value] of Object.entries(extras)) {
    if (!value) continue
    const target = new URL(value)
    if (!['http:', 'https:'].includes(target.protocol) || target.username || target.password || target.search || target.hash || (name === 'serverDomain' && target.pathname !== '/')) {
      throw new Error('MineMap 服务 URL 必须是无凭据、查询参数和片段的 HTTP(S) 地址')
    }
    extras[name] = target.href.replace(/\/$/, '')
  }
  return { domain: parsed.origin, key, solution, ...Object.fromEntries(Object.entries(extras).filter(([, value]) => value)) }
}

function loadAsset(tag, url) {
  return new Promise((resolve, reject) => {
    const element = document.createElement(tag)
    const timer = setTimeout(() => fail(), 15000)
    const fail = () => { clearTimeout(timer); element.remove(); reject(new Error('MineMap SDK 或样式加载失败')) }
    element.onload = () => { clearTimeout(timer); resolve() }
    element.onerror = fail
    if (tag === 'link') { element.rel = 'stylesheet'; element.href = url }
    else { element.src = url; element.async = true }
    document.head.append(element)
  })
}

export async function loadMineMap() {
  const config = mineMapConfig()
  await Promise.all([
    loadAsset('link', `${config.sdkBaseUrl || `${config.domain}/minemapapi/v2.1.0`}/minemap.css`),
    loadAsset('script', `${config.sdkBaseUrl || `${config.domain}/minemapapi/v2.1.0`}/minemap.js`),
  ])
  const sdk = window.minemap
  if (!sdk?.Map || !sdk?.Marker) throw new Error('MineMap 2.1.0 SDK 不完整')
  Object.assign(sdk, {
    domainUrl: config.domain, dataDomainUrl: config.domain, serverDomainUrl: config.serverDomain || config.domain,
    serviceUrl: config.serviceUrl || `${config.domain}/service`, key: config.key, solution: config.solution,
  })
  return createMineMapAdapter(sdk, config)
}

export function applyMineMapDarkStyle(map) {
  for (const layer of map.getStyle().layers || []) {
    if (layer.id.startsWith('uav-overlay-')) continue
    const source = String(layer['source-layer'] || layer.id).toLowerCase()
    const water = /water|lake|sea|ocean|hydro/.test(source)
    const green = /green|park|forest|vegetation/.test(source)
    const majorRoad = /expressway|highway|trunk|primary/.test(source)
    let paint = {}
    if (layer.type === 'background') paint = { 'background-color': '#091321' }
    else if (layer.type === 'fill') {
      paint = { 'fill-color': water ? '#102e46' : green ? '#122d2c' : /building|residential/.test(source) ? '#172638' : '#101d2c' }
      if ('fill-outline-color' in (layer.paint || {})) paint['fill-outline-color'] = '#23374c'
    } else if (layer.type === 'fill-extrusion') paint = { 'fill-extrusion-color': '#1b3044' }
    else if (layer.type === 'line') {
      paint = { 'line-color': water ? '#23516d' : majorRoad ? '#537b98' : '#2c435a' }
      if ('line-border-color' in (layer.paint || {})) paint['line-border-color'] = '#0a1726'
    } else if (layer.type === 'symbol' && layer.layout?.['text-field'] !== undefined) {
      paint = { 'text-color': water ? '#7ea9c4' : '#b1c2d5', 'text-halo-color': '#091321' }
    }
    for (const [name, value] of Object.entries(paint)) map.setPaintProperty(layer.id, name, value)
  }
}

export function createMineMapAdapter(sdk, config) {
  let sequence = 0
  const allowedOrigins = new Set([window.location.origin, config.domain, ...[config.sdkBaseUrl, config.serviceUrl, config.serverDomain, config.styleUrl].filter(Boolean).map((value) => new URL(value).origin)])
  const list = (value) => Array.isArray(value) ? value : [value]
  class Map {
    constructor(container, options) {
      this.container = container
      this.overlays = new Set()
      this.ready = false
      this.destroyed = false
      this.native = new sdk.Map({
        container, style: config.styleUrl || `${config.domain}/service/solu/style/id/${config.solution}`,
        center: options.center, zoom: options.zoom, pitch: options.pitch || 0,
        minZoom: options.zooms?.[0] ?? 0, maxZoom: options.zooms?.[1] ?? 22,
        projection: 'MERCATOR',
        transformRequest: (url) => {
          const target = new URL(url, `${config.domain}/`)
          if (!['blob:', 'data:'].includes(target.protocol) && !allowedOrigins.has(target.origin)) {
            throw new Error('MineMap 资源必须来自配置的内网地图服务')
          }
          return { url: target.href }
        },
      })
      this.native.on('load', () => {
        if (this.destroyed) return
        applyMineMapDarkStyle(this.native)
        this.ready = true
        ;[...this.overlays].sort((a, b) => a.zIndex - b.zIndex).forEach((overlay) => overlay.attach(this))
      })
      this.resizeObserver = typeof ResizeObserver === 'function' ? new ResizeObserver(() => this.native.resize()) : null
      this.resizeObserver?.observe(container)
    }
    on(...args) { this.native.on(...args) }
    add(value) { list(value).forEach((overlay) => { if (!this.overlays.has(overlay)) { this.overlays.add(overlay); if (this.ready) overlay.attach(this) } }) }
    remove(value) { list(value).forEach((overlay) => { this.overlays.delete(overlay); overlay.detach() }) }
    addControl(control) { this.native.addControl(control) }
    setCenter(value) { this.native.setCenter(value) }
    setPitch(value) { this.native.setPitch(value) }
    setRotation(value) { this.native.setBearing(value) }
    setZoomAndCenter(zoom, center) { this.native.jumpTo({ zoom, center }) }
    zoomIn() { this.native.zoomIn() }
    zoomOut() { this.native.zoomOut() }
    getSize() { return { getWidth: () => this.container.clientWidth, getHeight: () => this.container.clientHeight } }
    containerToLngLat(pixel) { return this.native.unproject([pixel.x, pixel.y]) }
    nextLayer(zIndex) {
      return [...this.overlays].filter((item) => item instanceof Geometry && item.map && item.zIndex > zIndex)
        .sort((a, b) => a.zIndex - b.zIndex)[0]?.layerIds[0]
    }
    setFitView(overlays, immediate = false, padding = [0, 0, 0, 0], maxZoom = 19) {
      const points = overlays.flatMap((overlay) => overlay.points())
      if (!points.length) return
      const bounds = [[Infinity, Infinity], [-Infinity, -Infinity]]
      points.forEach(([lng, lat]) => {
        bounds[0][0] = Math.min(bounds[0][0], lng); bounds[0][1] = Math.min(bounds[0][1], lat)
        bounds[1][0] = Math.max(bounds[1][0], lng); bounds[1][1] = Math.max(bounds[1][1], lat)
      })
      this.native.fitBounds(bounds, {
        padding: { top: padding[0], right: padding[1], bottom: padding[2], left: padding[3] },
        maxZoom, duration: immediate || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 0 : 350,
      })
    }
    destroy() {
      this.destroyed = true
      this.remove([...this.overlays])
      this.resizeObserver?.disconnect()
      this.native.remove()
    }
  }
  class Marker {
    constructor(options) {
      this.position = options.position
      this.zIndex = options.zIndex ?? 100
      this.element = document.createElement('div')
      this.setContent(options.content)
      this.setzIndex(this.zIndex)
      this.native = new sdk.Marker({ element: this.element, anchor: options.anchor || 'center' }).setLngLat(this.position)
    }
    on(name, handler) { this.element.addEventListener(name, (event) => { if (name === 'click') event.stopPropagation(); handler(event) }) }
    attach(map) { this.native.addTo(map.native) }
    detach() { cancelAnimationFrame(this.animation); this.native.remove() }
    points() { return [this.position] }
    setPosition(position) { cancelAnimationFrame(this.animation); this.position = position; this.native.setLngLat(position) }
    setContent(content) { if (typeof content === 'string') this.element.innerHTML = content; else this.element.replaceChildren(content) }
    setzIndex(value) { this.element.style.zIndex = String(value) }
    moveTo(position, { duration = 900 } = {}) {
      cancelAnimationFrame(this.animation)
      const start = this.position; const since = performance.now()
      const animate = (now) => {
        const fraction = Math.min(1, (now - since) / Math.max(1, duration))
        this.position = start.map((value, index) => value + (position[index] - value) * fraction)
        this.native.setLngLat(this.position)
        if (fraction < 1) this.animation = requestAnimationFrame(animate)
      }
      this.animation = requestAnimationFrame(animate)
    }
  }
  class Geometry {
    constructor(options, type) {
      this.options = options; this.type = type; this.zIndex = options.zIndex ?? (type === 'Polygon' ? 10 : 50)
      this.id = `uav-overlay-${++sequence}`; this.layerIds = []; this.handlers = []
    }
    points() { return this.type === 'Point' ? [this.options.center] : this.options.path }
    data() {
      let coordinates = this.points()
      if (this.type === 'Polygon') {
        coordinates = [...coordinates]
        if (coordinates.length && (coordinates[0][0] !== coordinates.at(-1)[0] || coordinates[0][1] !== coordinates.at(-1)[1])) coordinates.push(coordinates[0])
        coordinates = [coordinates]
      } else if (this.type === 'Point') coordinates = coordinates[0]
      return { type: 'Feature', properties: {}, geometry: { type: this.type, coordinates } }
    }
    attach(map) {
      this.map = map
      map.native.addSource(this.id, { type: 'geojson', data: this.data() })
      const o = this.options
      const linePaint = { 'line-color': o.strokeColor || '#ffffff', 'line-width': o.strokeWeight ?? 1, 'line-opacity': o.strokeOpacity ?? 1 }
      if (o.strokeStyle === 'dashed') linePaint['line-dasharray'] = o.strokeDasharray || [3, 2]
      const layers = this.type === 'Polygon'
        ? [{ type: 'fill', paint: { 'fill-color': o.fillColor || '#ffffff', 'fill-opacity': o.fillOpacity ?? 0.2 } }, { type: 'line', paint: linePaint }]
        : this.type === 'Point'
          ? [{ type: 'circle', paint: { 'circle-radius': o.radius ?? 4, 'circle-color': o.fillColor || '#ffffff', 'circle-opacity': o.fillOpacity ?? 1, 'circle-stroke-color': o.strokeColor || '#ffffff', 'circle-stroke-width': o.strokeWeight ?? 1 } }]
          : [{ type: 'line', layout: { 'line-join': o.lineJoin || 'round', 'line-cap': o.lineCap || 'round' }, paint: linePaint }]
      layers.forEach((layer, index) => {
        const id = `${this.id}-${index}`
        map.native.addLayer({ ...layer, id, source: this.id }, map.nextLayer(this.zIndex))
        this.layerIds.push(id)
      })
      this.handlers.forEach(([event, handler]) => map.native.on(event, this.layerIds[0], handler))
    }
    on(event, handler) { this.handlers.push([event, handler]); if (this.map) this.map.native.on(event, this.layerIds[0], handler) }
    setPath(path) { this.options.path = path; this.map?.native.getSource(this.id)?.setData(this.data()) }
    detach() {
      if (!this.map) return
      const native = this.map.native
      this.handlers.forEach(([event, handler]) => native.off(event, this.layerIds[0], handler))
      this.layerIds.forEach((id) => native.removeLayer(id))
      native.removeSource(this.id); this.layerIds = []; this.map = null
    }
  }
  class ImageLayer extends Geometry {
    constructor(options) { super(options, 'Image') }
    points() { return this.options.bounds.points }
    attach(map) {
      this.map = map
      const [[west, south], [east, north]] = this.points()
      map.native.addSource(this.id, { type: 'image', url: new URL(this.options.url, window.location.href).href,
        coordinates: [[west, north], [east, north], [east, south], [west, south]] })
      this.layerIds = [`${this.id}-0`]
      map.native.addLayer({ id: this.layerIds[0], type: 'raster', source: this.id,
        paint: { 'raster-opacity': this.options.opacity ?? 1 } }, map.nextLayer(this.zIndex))
    }
  }
  return {
    Map, Marker, ImageLayer, Bounds: class { constructor(sw, ne) { this.points = [sw, ne] } },
    Scale: sdk.Scale, Pixel: class { constructor(x, y) { this.x = x; this.y = y } },
    Polyline: class extends Geometry { constructor(options) { super(options, 'LineString') } },
    Polygon: class extends Geometry { constructor(options) { super(options, 'Polygon') } },
    CircleMarker: class extends Geometry { constructor(options) { super(options, 'Point') } },
  }
}
