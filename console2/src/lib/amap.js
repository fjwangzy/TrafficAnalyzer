import AMapLoader from '@amap/amap-jsapi-loader'
import { loadMineMap } from './minemap'

let loadPromise

export function isMineMap() {
  return (window.__RUNTIME_CONFIG__?.mapProvider || import.meta.env.VITE_MAP_PROVIDER || 'amap') === 'minemap'
}

export function mapProviderLabel() { return isMineMap() ? '四维图新 MineMap' : '高德地图' }

export function amapRuntimeConfig() {
  const runtime = window.__RUNTIME_CONFIG__ || {}
  return {
    key: runtime.amapKey || import.meta.env.VITE_AMAP_KEY || import.meta.env.AMAP_JS_API_KEY || '',
    securityJsCode: runtime.amapSecurityJsCode || import.meta.env.VITE_AMAP_SECURITY_JS_CODE || import.meta.env.AMAP_SECURITY_JS_CODE || '',
  }
}

export function loadAmap() {
  if (window.__RUNTIME_CONFIG__?.mapDisabled) {
    return Promise.reject(new Error('内网底图暂未接入，等待四维图新 MineMap 配置'))
  }
  if (loadPromise) return loadPromise
  const provider = window.__RUNTIME_CONFIG__?.mapProvider || import.meta.env.VITE_MAP_PROVIDER || 'amap'
  if (provider === 'minemap') {
    loadPromise = loadMineMap().catch((error) => { loadPromise = undefined; throw error })
    return loadPromise
  }
  if (provider !== 'amap') return Promise.reject(new Error('不支持的地图服务'))
  const config = amapRuntimeConfig()
  if (!config.key) return Promise.reject(new Error('AMAP_JS_API_KEY is not configured'))
  if (config.securityJsCode) window._AMapSecurityConfig = { securityJsCode: config.securityJsCode }
  else delete window._AMapSecurityConfig
  loadPromise = AMapLoader.load({
    key: config.key,
    version: '2.0',
    plugins: ['AMap.Scale', 'AMap.MoveAnimation'],
  })
  return loadPromise
}

export function resetAmapLoaderForTest() {
  loadPromise = undefined
}
