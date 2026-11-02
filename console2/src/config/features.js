export const DEMO_GOVERNANCE_ENABLED = import.meta.env.VITE_ENABLE_DEMO_GOVERNANCE === 'true'
export const roadFeaturesEnabled = () => window.__RUNTIME_CONFIG__?.roadFeaturesEnabled !== false
export const isRoadRoute = (path) => path.startsWith('/admin/calibration') || path.startsWith('/admin/intersection-projects')
