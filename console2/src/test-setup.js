import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(cleanup)

class ResizeObserverMock {
  constructor(callback) { this.callback = callback }
  observe(target) { this.callback([{ target, contentRect: { width: 800, height: 400 } }]) }
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = ResizeObserverMock
