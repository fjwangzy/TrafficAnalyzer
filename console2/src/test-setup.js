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

const localStorageValues = new Map()
const localStorageMock = {
  get length() { return localStorageValues.size },
  clear() { localStorageValues.clear() },
  getItem(key) { return localStorageValues.has(String(key)) ? localStorageValues.get(String(key)) : null },
  key(index) { return [...localStorageValues.keys()][index] ?? null },
  removeItem(key) { localStorageValues.delete(String(key)) },
  setItem(key, value) { localStorageValues.set(String(key), String(value)) },
}
Object.defineProperty(window, 'localStorage', { configurable: true, value: localStorageMock })
