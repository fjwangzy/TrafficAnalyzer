import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { detectorVideoStreamSrc } from './lib/videoStream'

describe('detector video runtime contract', () => {
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
