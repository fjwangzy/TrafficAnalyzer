import axios from 'axios'

export const TOKEN_KEY = 'uav_access_token'
export const UNAUTHORIZED_EVENT = 'uav:unauthorized'

const hasWindow = typeof window !== 'undefined'

export function getAccessToken() {
  return hasWindow ? window.sessionStorage.getItem(TOKEN_KEY) || '' : ''
}

export function setAccessToken(token) {
  if (!hasWindow) return
  if (token) window.sessionStorage.setItem(TOKEN_KEY, token)
  else window.sessionStorage.removeItem(TOKEN_KEY)
}

export function clearAccessToken() {
  if (hasWindow) window.sessionStorage.removeItem(TOKEN_KEY)
}

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api/v1',
  timeout: 10_000,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401 && hasWindow) {
      clearAccessToken()
      window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT))
    }
    return Promise.reject(error)
  },
)

const get = (path, config) => api.get(path, config).then((response) => response.data)
const post = (path, body, config) => api.post(path, body, config).then((response) => response.data)

export const platformApi = {
  login: (username, password) => post('/auth/login', { username, password }),
  currentUser: () => get('/auth/me'),

  intersections: () => get('/intersections'),
  intersection: (id) => get(`/intersections/${encodeURIComponent(id)}`),
  intersectionStats: (id, period = '30m', granularity = '5m') => get(`/intersections/${encodeURIComponent(id)}/stats`, { params: { period, granularity } }),
  alerts: (params = {}) => get('/alerts', { params }),
  acknowledgeAlert: (id) => post(`/alerts/${encodeURIComponent(id)}/acknowledge`),
  pipelines: () => get('/pipelines'),
  telemetry: (droneId) => get(`/telemetry/${encodeURIComponent(droneId)}`),

  systemHealth: () => get('/system/health'),
  gpu: () => get('/system/gpu'),
  kafkaTopics: () => get('/system/kafka/topics'),
  kafkaConsumers: () => get('/system/kafka/consumers'),
  models: () => get('/system/models'),
  users: () => get('/users'),

  calibrationSummary: () => get('/calibration/summary'),
  calibrationRecords: () => get('/calibration/records'),
  calibrationCoverage: (intersectionId) => get(`/calibration/coverage/${encodeURIComponent(intersectionId)}`),
  laneTasks: () => get('/calibration/lane-tasks'),
  laneTaskImage: (taskId) => api.get(`/calibration/lane-tasks/${encodeURIComponent(taskId)}/image`, { responseType: 'blob' }).then((response) => response.data),
  laneAnnotations: () => get('/calibration/lane-annotations'),
  saveLaneAnnotation: (taskId, body) => post(`/calibration/lane-tasks/${encodeURIComponent(taskId)}/annotation`, body),
}

export function apiErrorMessage(error, fallback = '请求失败，请稍后重试') {
  return error?.response?.data?.detail || error?.message || fallback
}
