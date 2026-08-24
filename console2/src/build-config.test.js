import { beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

vi.mock('@amap/amap-jsapi-loader', () => ({
  default: { load: vi.fn() },
}))

import AMapLoader from '@amap/amap-jsapi-loader'
import { bundleBudgetPlugin, manualChunks } from './config/build'
import { amapRuntimeConfig, loadAmap, resetAmapLoaderForTest } from './lib/amap'

describe('release bundle configuration', () => {
  it('separates heavy vendors and enforces a JavaScript bundle budget', () => {
    expect(manualChunks('/repo/node_modules/@amap/amap-jsapi-loader/dist/index.js')).toBe('map-vendor')
    expect(manualChunks('/repo/node_modules/recharts/es6/chart/AreaChart.js')).toBe('chart-vendor')
    expect(manualChunks('/repo/node_modules/react-dom/client.js')).toBe('react-vendor')
    expect(bundleBudgetPlugin()).toEqual(expect.objectContaining({ name: 'console2-bundle-budget' }))
  })

  it('quotes asset-cache regex locations so Nginx keeps quantifiers inside the regex', () => {
    const nginxConfig = readFileSync(resolve(process.cwd(), 'nginx.conf'), 'utf8')

    expect(nginxConfig).toContain('location ~* "^/assets/.+-[A-Za-z0-9_-]{8,}\\.(?:js|css)$" {')
  })

  it('injects both AMap browser-direct credentials into runtime configuration', () => {
    const runtimeTemplate = readFileSync(resolve(process.cwd(), 'public/runtime-config.template.js'), 'utf8')
    const entrypoint = readFileSync(resolve(process.cwd(), 'docker-entrypoint.d/40-amap-runtime-config.sh'), 'utf8')

    expect(runtimeTemplate).toContain("amapSecurityJsCode: '${AMAP_SECURITY_JS_CODE}'")
    expect(entrypoint).toContain("envsubst '${AMAP_JS_API_KEY} ${AMAP_SECURITY_JS_CODE}'")
  })

  it('allows production startup without the optional AMap security code', () => {
    const composeConfig = readFileSync(resolve(process.cwd(), '../docker-compose.yaml'), 'utf8')

    expect(composeConfig).toContain('AMAP_SECURITY_JS_CODE: ${AMAP_SECURITY_JS_CODE:-}')
  })

  it('does not expose an AMap same-origin proxy in development or production', () => {
    const viteConfigSource = readFileSync(resolve(process.cwd(), 'vite.config.mjs'), 'utf8')
    const nginxConfig = readFileSync(resolve(process.cwd(), 'nginx.conf'), 'utf8')

    expect(viteConfigSource).not.toContain('/_AMapService')
    expect(nginxConfig).not.toContain('/_AMapService')
    expect(viteConfigSource).toContain('envPrefix: ["VITE_", "AMAP_"]')
  })
})

describe('AMap browser-direct security configuration', () => {
  beforeEach(() => {
    resetAmapLoaderForTest()
    AMapLoader.load.mockReset().mockResolvedValue({})
    window.__RUNTIME_CONFIG__ = {
      amapKey: 'web-key',
      amapSecurityJsCode: 'security-code',
    }
    delete window._AMapSecurityConfig
  })

  it('loads JSAPI with the browser security code instead of a service proxy', async () => {
    expect(amapRuntimeConfig()).toEqual({
      key: 'web-key',
      securityJsCode: 'security-code',
    })

    await loadAmap()

    expect(window._AMapSecurityConfig).toEqual({ securityJsCode: 'security-code' })
    expect(AMapLoader.load).toHaveBeenCalledWith({
      key: 'web-key',
      version: '2.0',
      plugins: ['AMap.Scale', 'AMap.MoveAnimation'],
    })
  })

  it('loads with the Web Key when the optional browser security code is missing', async () => {
    window.__RUNTIME_CONFIG__.amapSecurityJsCode = ''

    await loadAmap()

    expect(window._AMapSecurityConfig).toBeUndefined()
    expect(AMapLoader.load).toHaveBeenCalledWith({
      key: 'web-key',
      version: '2.0',
      plugins: ['AMap.Scale', 'AMap.MoveAnimation'],
    })
  })
})
