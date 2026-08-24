import AMapLoader from '@amap/amap-jsapi-loader'

let loadPromise

export function amapRuntimeConfig() {
  const runtime = window.__RUNTIME_CONFIG__ || {}
  return {
    key: runtime.amapKey || import.meta.env.VITE_AMAP_KEY || import.meta.env.AMAP_JS_API_KEY || '',
    securityJsCode: runtime.amapSecurityJsCode || import.meta.env.VITE_AMAP_SECURITY_JS_CODE || import.meta.env.AMAP_SECURITY_JS_CODE || '',
  }
}

export function loadAmap() {
  if (loadPromise) return loadPromise
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
