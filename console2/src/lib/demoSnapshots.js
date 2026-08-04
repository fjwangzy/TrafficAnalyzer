export const DEMO_SNAPSHOT_STORAGE_KEY = 'uav.console.demo-analysis-snapshots.v1'
export const DEMO_SNAPSHOT_SCHEMA = 'uav.demo-analysis-snapshot/v1'

const storage = () => typeof window === 'undefined' ? null : window.localStorage
const numberOrNull = (value) => {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}
const safeId = (value) => String(value || 'unknown').replace(/[^a-zA-Z0-9_-]/g, '-')

export function readDemoSnapshots() {
  try {
    const raw = storage()?.getItem(DEMO_SNAPSHOT_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((item) => item?.schema_version === DEMO_SNAPSHOT_SCHEMA && item?.id)
  } catch {
    return []
  }
}

export function buildDemoAnalysisSnapshot({
  intersectionId,
  intersectionName,
  sourceProfileId,
  missionMode = 'hover',
  sourceMode = 'fixed_demo',
  stats = {},
  trend = [],
  events = [],
  comparison = [],
  capturedAt = new Date().toISOString(),
  savedAt = new Date().toISOString(),
}) {
  const laneStats = Array.isArray(stats.lane_stats) ? stats.lane_stats : Array.isArray(stats.lanes) ? stats.lanes : []
  const queues = laneStats.map((item) => numberOrNull(item.queue_length_m)).filter((item) => item != null)
  const saturations = laneStats.map((item) => numberOrNull(item.saturation)).filter((item) => item != null)
  const lastTrend = Array.isArray(trend) && trend.length ? trend.at(-1) : {}
  const missionLabels = { hover: '路口悬停', cruise: '路段航拍', review: '治理后复盘' }
  const normalizedMode = missionLabels[missionMode] ? missionMode : 'hover'
  const normalizedEvents = (Array.isArray(events) ? events : []).map((event) => ({
    id: event.id,
    type: event.type,
    level: event.level,
    title: event.title,
    detail: event.detail,
    metric: event.metric,
    time: event.time,
    ttc_sec: numberOrNull(event.raw?.ttc_sec ?? event.ttc_sec),
    pet_sec: numberOrNull(event.raw?.pet_sec ?? event.pet_sec),
  }))

  return {
    schema_version: DEMO_SNAPSHOT_SCHEMA,
    id: `DEMO-SNAPSHOT-${safeId(intersectionId)}-${normalizedMode}`,
    title: `${intersectionName || intersectionId || '路口'} · ${missionLabels[normalizedMode]}分析快照`,
    intersection_id: intersectionId || null,
    intersection_name: intersectionName || intersectionId || '未命名路口',
    source_profile_id: sourceProfileId || null,
    source_mode: sourceMode,
    mission_mode: normalizedMode,
    mission_label: missionLabels[normalizedMode],
    captured_at: capturedAt,
    saved_at: savedAt,
    metrics: {
      vehicle_count: numberOrNull(stats.cars ?? stats.total_vehicles ?? stats.cars_amount),
      avg_speed_kmh: numberOrNull(stats.avg_speed_kmh ?? stats.average_speed),
      longest_queue_m: queues.length ? Math.max(...queues) : null,
      max_saturation: saturations.length ? Math.max(...saturations) : null,
      conflict_count: normalizedEvents.filter((event) => event.type === 'conflict').length,
      congestion_index: numberOrNull(lastTrend?.congestion_index),
    },
    lane_stats: laneStats.map((lane) => ({
      lane: lane.lane || lane.lane_name || lane.lane_id || '未命名车道',
      queue_length_m: numberOrNull(lane.queue_length_m),
      saturation: numberOrNull(lane.saturation),
      green_utilization: numberOrNull(lane.green_utilization),
    })),
    traffic_flow: (Array.isArray(trend) ? trend : []).slice(-6).map((row) => ({
      time: row.time || row.timestamp || null,
      congestion_index: numberOrNull(row.congestion_index),
      saturation: numberOrNull(row.saturation),
      cars: numberOrNull(row.cars ?? row.cars_amount ?? row.total_vehicles),
      direction_flow: row.direction_flow || {},
    })),
    events: normalizedEvents,
    comparison: Array.isArray(comparison) ? comparison : [],
  }
}

export function upsertDemoSnapshot(snapshot) {
  if (!snapshot?.id || snapshot.schema_version !== DEMO_SNAPSHOT_SCHEMA) throw new Error('invalid demo analysis snapshot')
  const next = [snapshot, ...readDemoSnapshots().filter((item) => item.id !== snapshot.id)].slice(0, 24)
  storage()?.setItem(DEMO_SNAPSHOT_STORAGE_KEY, JSON.stringify(next))
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('uav-demo-snapshots-changed', { detail: snapshot }))
  return snapshot
}
