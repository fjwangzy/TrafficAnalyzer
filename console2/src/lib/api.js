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
  withCredentials: true,
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
const patch = (path, body, config) => api.patch(path, body, config).then((response) => response.data)
const remove = (path, config) => api.delete(path, config).then((response) => response.data)

export const platformApi = {
  login: (username, password) => post('/auth/login', { username, password }),
  logout: () => post('/auth/logout'),
  currentUser: () => get('/auth/me'),

  intersections: () => get('/intersections'),
  intersection: (id) => get(`/intersections/${encodeURIComponent(id)}`),
  intersectionStats: (id, period = '30m', granularity = '5m', sourceProfileId) => get(`/intersections/${encodeURIComponent(id)}/stats`, { params: { period, granularity, ...(sourceProfileId ? { source_profile_id: sourceProfileId } : {}) } }),
  trajectories: (id, params = {}) => get(`/trajectories/${encodeURIComponent(id)}`, { params }),
  trajectoryAnalysis: (id, params = {}) => get(`/trajectories/${encodeURIComponent(id)}/analysis`, { params }),
  replayMissions: (id, params = {}) => get(`/trajectories/${encodeURIComponent(id)}/replay-missions`, { params }),
  trajectoryReplay: (id, params = {}) => get(`/trajectories/${encodeURIComponent(id)}/replay`, { params }),
  conflicts: (id, params = {}) => get(`/trajectories/${encodeURIComponent(id)}/conflicts`, { params }),
  reviewConflict: (intersectionId, eventId, body) => post(`/trajectories/${encodeURIComponent(intersectionId)}/conflicts/${encodeURIComponent(eventId)}/review`, body),
  events: (params = {}) => get('/events', { params }),
  event: (eventId) => get(`/events/${encodeURIComponent(eventId)}`),
  reviewEvent: (eventId, body) => post(`/events/${encodeURIComponent(eventId)}/review`, body),
  createEventSurvey: (eventId, idempotencyKey) => post(`/events/${encodeURIComponent(eventId)}/survey`, {}, { headers: { 'Idempotency-Key': idempotencyKey } }),
  alerts: (params = {}) => get('/alerts', { params }),
  acknowledgeAlert: (id) => post(`/alerts/${encodeURIComponent(id)}/acknowledge`),
  pipelines: () => get('/pipelines'),
  telemetry: (droneId) => get(`/telemetry/${encodeURIComponent(droneId)}`),

  dashboardOverview: () => get('/dashboard/overview'),
  dashboardIntersections: (params = {}) => get('/dashboard/intersections', { params }),
  dashboardIntersection: (interId) => get(`/dashboard/intersections/${encodeURIComponent(interId)}`),
  dashboardDrones: () => get('/dashboard/drones'),
  dashboardSituation: (dayOfWeek, stepIndex) => get('/dashboard/situation', { params: { day_of_week: dayOfWeek, step_index: stepIndex } }),

  drones: () => get('/drones'),
  droneTrajectory: (droneId) => get(`/drones/${encodeURIComponent(droneId)}/trajectory`),
  createDrone: (body) => post('/drones', body),
  updateDrone: (droneId, body) => patch(`/drones/${encodeURIComponent(droneId)}`, body),
  droneSources: (droneId) => get(`/drones/${encodeURIComponent(droneId)}/sources`),
  sources: () => get('/sources'),
  sourceResults: (profileId) => get(`/sources/${encodeURIComponent(profileId)}/results`),
  createSource: (droneId, body) => post(`/drones/${encodeURIComponent(droneId)}/sources`, body),
  updateSource: (droneId, profileId, body) => patch(`/drones/${encodeURIComponent(droneId)}/sources/${encodeURIComponent(profileId)}`, body),
  validateSource: (droneId, profileId) => post(`/drones/${encodeURIComponent(droneId)}/sources/${encodeURIComponent(profileId)}/validate`),
  flightPlans: () => get('/flight-plans'),
  createFlightPlan: (body) => post('/flight-plans', body),
  updateFlightPlan: (planId, body) => patch(`/flight-plans/${encodeURIComponent(planId)}`, body),
  flightPlanAction: (planId, action, revision) => post(`/flight-plans/${encodeURIComponent(planId)}/${action}`, { revision }),
  flightPlanOccurrences: (planId, count = 10) => get(`/flight-plans/${encodeURIComponent(planId)}/occurrences`, { params: { count } }),
  missions: (params = {}) => get('/missions', { params }),
  createMission: (body) => post('/missions', body),
  stopMission: (missionId, reason) => post(`/missions/${encodeURIComponent(missionId)}/stop`, { reason }),
  retryMission: (missionId, reason) => post(`/missions/${encodeURIComponent(missionId)}/retry`, { reason }),

  enforcementZones: () => get('/enforcement/zones'),
  createEnforcementZone: (body) => post('/enforcement/zones', body),
  updateEnforcementZone: (zoneId, body) => patch(`/enforcement/zones/${encodeURIComponent(zoneId)}`, body),
  publishEnforcementZone: (zoneId) => post(`/enforcement/zones/${encodeURIComponent(zoneId)}/publish`),
  enforcementRules: () => get('/enforcement/rules'),
  createEnforcementRule: (body) => post('/enforcement/rules', body),
  updateEnforcementRule: (ruleId, body) => patch(`/enforcement/rules/${encodeURIComponent(ruleId)}`, body),
  enforcementClues: (params = {}) => get('/enforcement/clues', { params }),
  enforcementClue: (eventId) => get(`/enforcement/clues/${encodeURIComponent(eventId)}`),
  reviewEnforcementClue: (eventId, body) => post(`/enforcement/clues/${encodeURIComponent(eventId)}/review`, body),
  enforcementTruckSummary: () => get('/enforcement/truck-summary'),

  systemHealth: () => get('/system/health'),
  gpu: () => get('/system/gpu'),
  kafkaTopics: () => get('/system/kafka/topics'),
  kafkaConsumers: () => get('/system/kafka/consumers'),
  models: () => get('/system/models'),
  users: () => get('/users'),

  calibrationSummary: () => get('/calibration/summary'),
  calibrationRecords: () => get('/calibration/records'),
  calibrationCoverage: (intersectionId) => get(`/calibration/coverage/${encodeURIComponent(intersectionId)}`),
  intersectionProjects: () => get('/calibration/intersection-projects'),
  intersectionProject: (projectId) => get(`/calibration/intersection-projects/${encodeURIComponent(projectId)}`),
  intersectionProjectWorkspace: (projectId) => get(`/calibration/intersection-projects/${encodeURIComponent(projectId)}/workspace`),
  createIntersectionProject: (body) => post('/calibration/intersection-projects', body),
  updateIntersectionProject: (projectId, body) => patch(`/calibration/intersection-projects/${encodeURIComponent(projectId)}`, body),
  createVideoIngestion: (body) => post('/calibration/video-ingestions', body, { timeout: 0 }),
  uploadVideoIngestion: ({ video, telemetry, droneId, projectId }) => {
    const form = new FormData()
    form.append('video', video)
    if (telemetry) form.append('telemetry', telemetry)
    if (droneId) form.append('drone_id', droneId)
    if (projectId) form.append('project_id', projectId)
    return post('/calibration/video-ingestions', form, { timeout: 0, headers: { 'Content-Type': 'multipart/form-data' } })
  },
  videoIngestion: (jobId) => get(`/calibration/video-ingestions/${encodeURIComponent(jobId)}`),
  resolveVideoIngestion: (jobId, body) => post(`/calibration/video-ingestions/${encodeURIComponent(jobId)}/resolve`, body),
  laneTasks: () => get('/calibration/lane-tasks'),
  laneTaskImage: (taskId) => api.get(`/calibration/lane-tasks/${encodeURIComponent(taskId)}/image`, { responseType: 'blob' }).then((response) => response.data),
  startLaneKeyframeExtraction: (body, idempotencyKey) => post('/calibration/lane-keyframe-extractions', body, { headers: { 'Idempotency-Key': idempotencyKey } }),
  createLaneTaskFromSurveyFrame: (frameId) => post('/calibration/lane-tasks/from-survey-frame', { frame_id: frameId }),
  channelizedMaps: (interId) => get('/calibration/channelized-maps', { params: interId ? { inter_id: interId } : {} }),
  channelizedMap: (mapVersionId) => get(`/calibration/channelized-maps/${encodeURIComponent(mapVersionId)}`),
  createChannelizedMap: (body) => post('/calibration/channelized-maps', body),
  deriveChannelizedMapDraft: (mapVersionId) => post(`/calibration/channelized-maps/${encodeURIComponent(mapVersionId)}/derive-draft`),
  bootstrapChannelizedMap: (interId) => post(`/calibration/channelized-maps/bootstrap/${encodeURIComponent(interId)}`),
  fitChannelizedMapFromImage: (mapVersionId, body) => post(`/calibration/channelized-maps/${encodeURIComponent(mapVersionId)}/fit-from-image`, body),
  verifyVisualRegistration: (registrationId, verified = true) => post(`/calibration/visual-registrations/${encodeURIComponent(registrationId)}/verify`, { verified }),
  publishChannelizedMap: (mapVersionId, targetStatus) => post(`/calibration/channelized-maps/${encodeURIComponent(mapVersionId)}/publish`, { target_status: targetStatus }),
  submitChannelizedMapCheck: (mapVersionId) => post(`/calibration/channelized-maps/${encodeURIComponent(mapVersionId)}/submit-check`),
  checkChannelizedMap: (mapVersionId, body) => post(`/calibration/channelized-maps/${encodeURIComponent(mapVersionId)}/check`, body),

  surveyTasks: (state) => get('/survey-tasks', { params: state ? { state } : {} }),
  createSurveyTask: (body, idempotencyKey) => post('/survey-tasks', body, { headers: { 'Idempotency-Key': idempotencyKey } }),
  surveyTask: (taskId) => get(`/survey-tasks/${encodeURIComponent(taskId)}`),
  surveyAction: (taskId, body, idempotencyKey) => post(`/survey-tasks/${encodeURIComponent(taskId)}/actions`, body, { headers: { 'Idempotency-Key': idempotencyKey } }),
  surveyBatches: (taskId) => get(`/survey-tasks/${encodeURIComponent(taskId)}/capture-batches`),
  importSurveyBatch: (taskId, body, idempotencyKey) => post(`/survey-tasks/${encodeURIComponent(taskId)}/capture-batches/import`, body, { timeout: 0, headers: { 'Idempotency-Key': idempotencyKey } }),
  uploadSurveyBatch: (taskId, video, telemetry, idempotencyKey) => {
    const form = new FormData()
    form.append('video', video)
    form.append('telemetry', telemetry)
    return post(`/survey-tasks/${encodeURIComponent(taskId)}/capture-batches/upload`, form, { timeout: 0, headers: { 'Content-Type': 'multipart/form-data', 'Idempotency-Key': idempotencyKey } })
  },
  surveyFrames: (taskId, batchId) => get(`/survey-tasks/${encodeURIComponent(taskId)}/frames`, { params: batchId ? { batch_id: batchId } : {} }),
  surveyMeasurements: (taskId) => get(`/survey-tasks/${encodeURIComponent(taskId)}/measurements`),
  surveyAnnotations: (taskId) => get(`/survey-tasks/${encodeURIComponent(taskId)}/annotations`),
  createSurveyAnnotation: (taskId, body, idempotencyKey) => post(`/survey-tasks/${encodeURIComponent(taskId)}/annotations`, body, { headers: { 'Idempotency-Key': idempotencyKey } }),
  updateSurveyAnnotation: (taskId, annotationId, body) => patch(`/survey-tasks/${encodeURIComponent(taskId)}/annotations/${encodeURIComponent(annotationId)}`, body),
  deleteSurveyAnnotation: (taskId, annotationId, revision) => remove(`/survey-tasks/${encodeURIComponent(taskId)}/annotations/${encodeURIComponent(annotationId)}`, { params: { expected_revision: revision } }),
  createSurveyMeasurement: (taskId, body, idempotencyKey) => post(`/survey-tasks/${encodeURIComponent(taskId)}/measurements`, body, { headers: { 'Idempotency-Key': idempotencyKey } }),
  updateSurveyMeasurement: (taskId, measurementId, body) => patch(`/survey-tasks/${encodeURIComponent(taskId)}/measurements/${encodeURIComponent(measurementId)}`, body),
  deleteSurveyMeasurement: (taskId, measurementId, revision) => remove(`/survey-tasks/${encodeURIComponent(taskId)}/measurements/${encodeURIComponent(measurementId)}`, { params: { expected_revision: revision } }),
  surveyReports: (taskId) => get(`/survey-tasks/${encodeURIComponent(taskId)}/reports`),
  generateSurveyReport: (taskId, idempotencyKey) => post(`/survey-tasks/${encodeURIComponent(taskId)}/reports`, undefined, { headers: { 'Idempotency-Key': idempotencyKey } }),
  deliverSurveyReport: (taskId, reportId, idempotencyKey) => post(`/survey-tasks/${encodeURIComponent(taskId)}/reports/${encodeURIComponent(reportId)}/deliver`, undefined, { headers: { 'Idempotency-Key': idempotencyKey } }),
  surveyEvidence: (evidenceId) => api.get(`/survey-evidence/${encodeURIComponent(evidenceId)}/content`, { responseType: 'blob' }).then((response) => response.data),
}

export function apiErrorMessage(error, fallback = '请求失败，请稍后重试') {
  const detail = error?.response?.data?.detail
  if (Array.isArray(detail)) {
    const validation = detail.slice(0, 3).map((item) => {
      if (!item || typeof item !== 'object') return String(item || '')
      const location = Array.isArray(item.loc)
        ? item.loc.filter((part) => part !== 'body').join('.')
        : ''
      const message = item.type === 'extra_forbidden'
        ? '当前服务不支持该参数，请刷新版本或重启 Platform 后重试'
        : item.msg || item.message || item.type || ''
      return location && message ? `${location}：${message}` : message
    }).filter(Boolean).join('；')
    if (validation) return validation
  }
  return (typeof detail === 'object' ? detail?.message || detail?.code : detail) || error?.message || fallback
}
