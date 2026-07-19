import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { bundleBudgetPlugin, manualChunks } from './config/build'

describe('release bundle configuration', () => {
  it('separates heavy vendors and enforces a JavaScript bundle budget', () => {
    expect(manualChunks('/repo/node_modules/ol/Map.js')).toBe('map-vendor')
    expect(manualChunks('/repo/node_modules/recharts/es6/chart/AreaChart.js')).toBe('chart-vendor')
    expect(manualChunks('/repo/node_modules/react-dom/client.js')).toBe('react-vendor')
    expect(bundleBudgetPlugin()).toEqual(expect.objectContaining({ name: 'console2-bundle-budget' }))
  })

  it('quotes asset-cache regex locations so Nginx keeps quantifiers inside the regex', () => {
    const nginxConfig = readFileSync(resolve(process.cwd(), 'nginx.conf'), 'utf8')

    expect(nginxConfig).toContain('location ~* "^/assets/.+-[A-Za-z0-9_-]{8,}\\.(?:js|css)$" {')
  })
})
