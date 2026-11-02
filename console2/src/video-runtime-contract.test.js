import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { detectorVideoStreamSrc } from './lib/videoStream'

describe('detector video runtime contract', () => {
  afterEach(() => vi.unstubAllEnvs())

  it('routes production MJPEG through the authenticated same-origin endpoint', () => {
    vi.stubEnv('PROD', true)
    const src = detectorVideoStreamSrc({ camera_id: 17, video_stream_url: 'http://127.0.0.1:8117/video' }, 3)
    const url = new URL(src, window.location.origin)
    expect(url.origin).toBe(window.location.origin)
    expect(url.pathname).toBe('/api/v1/video/camera/17')
    expect(url.searchParams.get('retry')).toBe('3')
    expect(detectorVideoStreamSrc({ camera_id: -1, video_stream_url: 'http://127.0.0.1:8117/video' })).toBe('')
  })

  it('keeps detector MJPEG off the Vite proxy data path', () => {
    const viteConfig = readFileSync('vite.config.mjs', 'utf8')
    expect(viteConfig).not.toMatch(/['"]\/camera['"]\s*:/)
    expect(viteConfig).not.toMatch(/api\/v1\/video\/camera/)
  })

  it('uses only a registered HTTP detector address and adds a retry nonce', () => {
    expect(detectorVideoStreamSrc({ video_stream_url: 'http://127.0.0.1:8101/video' }, 3))
      .toBe('http://127.0.0.1:8101/video?retry=3')
    expect(detectorVideoStreamSrc({ video_stream_url: 'javascript:alert(1)' }, 3)).toBe('')
    expect(detectorVideoStreamSrc({}, 3)).toBe('')
  })

  it('allows local direct detector images through the production CSP', () => {
    const nginxConfig = readFileSync('nginx.conf', 'utf8')
    expect(nginxConfig).toContain('http://127.0.0.1:*')
    expect(nginxConfig).toContain('http://localhost:*')
  })
})
