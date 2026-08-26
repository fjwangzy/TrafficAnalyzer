const numberOrNull = (value) => {
  if (value == null || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

const timestampMs = (value) => {
  if (value == null || value === '') return null
  if (typeof value === 'number') return value > 10_000_000_000 ? value : null
  const parsed = new Date(value).getTime()
  return Number.isFinite(parsed) ? parsed : null
}

const severityRank = { info: 0, warning: 1, critical: 2 }
const reviewLabel = { pending: '待复核', confirmed: '已确认', rejected: '已驳回' }

export function buildMonitoringSourceHealth({
  sourceMode,
  usingDemoMetrics = false,
  streamActive = false,
  wsStatus = 'disconnected',
  lastStatsAt = 0,
  now = Date.now(),
  videoError = false,
  endToEndLatencyMs = null,
  pipelineProcessingMs = null,
  sourceDropCount = null,
} = {}) {
  const receiptAgeSec = lastStatsAt ? Math.max(0, (now - lastStatsAt) / 1000) : null
  const diagnostics = {
    receiptAgeSec,
    endToEndLatencyMs: numberOrNull(endToEndLatencyMs),
    pipelineProcessingMs: numberOrNull(pipelineProcessingMs),
    sourceDropCount: numberOrNull(sourceDropCount),
    wsStatus,
    videoAvailable: !videoError,
  }
  if (usingDemoMetrics) return {
    id: 'fixed-demo', label: '固定演示', tone: 'testing', detail: '固定演示数据不参与实时决策验收', adviceAllowed: false, diagnostics,
  }
  if (sourceMode === 'local') return {
    id: 'development', label: '开发回放', tone: 'testing', detail: '开发测试回放不参与生产实时性验收', adviceAllowed: false, diagnostics,
  }
  if (!streamActive) return {
    id: 'stopped', label: '未启动', tone: 'stopped', detail: '当前来源没有运行中的检测 Pipeline', adviceAllowed: false, diagnostics,
  }
  if (!lastStatsAt) return {
    id: 'starting', label: '启动中', tone: 'waiting', detail: 'Pipeline 已运行，等待首条实时统计', adviceAllowed: false, diagnostics,
  }
  if (wsStatus !== 'connected' || videoError) return {
    id: 'interrupted', label: '链路中断', tone: 'critical', detail: wsStatus !== 'connected' ? '实时消息链路中断，REST 仅作恢复基线' : '实时画面不可复核', adviceAllowed: false, diagnostics,
  }
  const endToEndLatencySec = diagnostics.endToEndLatencyMs == null ? null : diagnostics.endToEndLatencyMs / 1000
  if (endToEndLatencySec > 45) return {
    id: 'stale', label: '数据过期', tone: 'critical', detail: `源消息端到端延迟已超过 45 秒（${Math.round(endToEndLatencySec)} 秒）`, adviceAllowed: false, diagnostics,
  }
  if (endToEndLatencySec > 15) return {
    id: 'delayed', label: '数据延迟', tone: 'warning', detail: `源消息端到端延迟 ${Math.round(endToEndLatencySec)} 秒`, adviceAllowed: false, diagnostics,
  }
  if (receiptAgeSec > 45) return {
    id: 'stale', label: '数据过期', tone: 'critical', detail: `最近统计已超过 45 秒（${Math.round(receiptAgeSec)} 秒）`, adviceAllowed: false, diagnostics,
  }
  if (receiptAgeSec > 15) return {
    id: 'delayed', label: '数据延迟', tone: 'warning', detail: `最近统计已延迟 ${Math.round(receiptAgeSec)} 秒`, adviceAllowed: false, diagnostics,
  }
  return {
    id: 'healthy', label: '实时正常', tone: 'healthy', detail: `最近统计 ${Math.max(0, Math.round(receiptAgeSec))} 秒前到达`, adviceAllowed: true, diagnostics,
  }
}

const conflictPair = (event) => {
  const raw = event?.raw || event || {}
  const motorId = raw.motor_id ?? event?.motorId
  const nonMotorId = raw.non_motor_id ?? event?.nonMotorId
  if (motorId == null || nonMotorId == null) return null
  return { motorId: String(motorId), nonMotorId: String(nonMotorId) }
}

const eventOccurredAtMs = (event) => event?.occurredAtMs
  ?? timestampMs(event?.raw?.occurred_at ?? event?.raw?.timestamp ?? event?.occurredAt)

const deduplicateReferences = (references) => [...new Map(references.filter(Boolean).map((reference) => [
  reference.id || `${reference.kind || 'evidence'}:${reference.sha256 || reference.uri || reference.url || ''}`,
  reference,
])).values()]

export function clusterMonitoringConflictEpisodes(events = [], { gapMs = 60_000 } = {}) {
  const exact = [...new Map(events.filter((event) => event?.id).map((event) => [event.id, event])).values()]
  const sorted = exact.sort((left, right) => (eventOccurredAtMs(left) ?? 0) - (eventOccurredAtMs(right) ?? 0))
  const episodes = []
  sorted.forEach((event) => {
    const pair = event.type === 'conflict' ? conflictPair(event) : null
    const raw = event.raw || {}
    const occurredAtMs = eventOccurredAtMs(event)
    const key = pair
      ? `${raw.source_profile_id || ''}:${raw.pipeline_id || raw.run_id || ''}:${pair.motorId}:${pair.nonMotorId}`
      : `event:${event.id}`
    const previous = [...episodes].reverse().find((episode) => episode.key === key)
    const withinWindow = previous && occurredAtMs != null && previous.endMs != null && occurredAtMs - previous.endMs <= gapMs
    if (!withinWindow) {
      episodes.push({
        ...event,
        key,
        eventIds: [event.id],
        triggerCount: Math.max(1, numberOrNull(raw.trigger_count ?? raw.occurrence_count) ?? 1),
        startMs: occurredAtMs,
        endMs: occurredAtMs,
        motorId: pair?.motorId || null,
        nonMotorId: pair?.nonMotorId || null,
        minTtcSec: numberOrNull(raw.ttc_sec),
        minPetSec: numberOrNull(raw.pet_sec),
        reviewStatuses: [raw.review_status || event.reviewStatus || 'pending'],
        evidenceRefs: deduplicateReferences(raw.evidence_refs || event.evidenceRefs || []),
      })
      return
    }
    previous.eventIds.push(event.id)
    previous.triggerCount += Math.max(1, numberOrNull(raw.trigger_count ?? raw.occurrence_count) ?? 1)
    previous.endMs = occurredAtMs
    previous.minTtcSec = previous.minTtcSec == null ? numberOrNull(raw.ttc_sec) : Math.min(previous.minTtcSec, numberOrNull(raw.ttc_sec) ?? previous.minTtcSec)
    previous.minPetSec = previous.minPetSec == null ? numberOrNull(raw.pet_sec) : Math.min(previous.minPetSec, numberOrNull(raw.pet_sec) ?? previous.minPetSec)
    previous.reviewStatuses.push(raw.review_status || event.reviewStatus || 'pending')
    previous.evidenceRefs = deduplicateReferences([...previous.evidenceRefs, ...(raw.evidence_refs || event.evidenceRefs || [])])
    if ((severityRank[event.level] ?? 0) > (severityRank[previous.level] ?? 0) || (raw.evidence_refs?.length || 0) > (previous.raw?.evidence_refs?.length || 0)) {
      const episodeFields = {
        key: previous.key,
        eventIds: previous.eventIds,
        triggerCount: previous.triggerCount,
        startMs: previous.startMs,
        endMs: previous.endMs,
        motorId: previous.motorId,
        nonMotorId: previous.nonMotorId,
        minTtcSec: previous.minTtcSec,
        minPetSec: previous.minPetSec,
        reviewStatuses: previous.reviewStatuses,
        evidenceRefs: previous.evidenceRefs,
      }
      Object.assign(previous, event, episodeFields)
    }
  })
  return episodes.map((episode) => {
    const statuses = episode.reviewStatuses
    const reviewStatus = statuses.includes('pending') ? 'pending' : statuses.includes('confirmed') ? 'confirmed' : 'rejected'
    const durationSec = episode.startMs != null && episode.endMs != null ? Math.max(0, Math.round((episode.endMs - episode.startMs) / 1000)) : null
    return {
      ...episode,
      reviewStatus,
      reviewLabel: reviewLabel[reviewStatus] || reviewStatus,
      durationSec,
      detail: episode.type === 'conflict'
        ? `轨迹 ${episode.motorId ?? '—'} / ${episode.nonMotorId ?? '—'} · ${episode.triggerCount} 次触发${durationSec ? ` · ${durationSec} 秒窗口` : ''}`
        : episode.detail,
      metric: episode.type === 'conflict'
        ? `最低 TTC ${episode.minTtcSec ?? '—'}s · PET ${episode.minPetSec ?? '—'}s`
        : episode.metric,
    }
  }).sort((left, right) => (right.endMs ?? 0) - (left.endMs ?? 0))
}

export function buildMonitoringRiskSummary(episodes = []) {
  return episodes.reduce((summary, episode) => {
    summary.triggers += episode.triggerCount || 1
    summary.episodes += 1
    if (episode.reviewStatus === 'pending') summary.pending += 1
    else summary.reviewed += 1
    if (episode.reviewStatus === 'confirmed') summary.confirmed += 1
    if (episode.reviewStatus === 'rejected') summary.rejected += 1
    return summary
  }, { triggers: 0, episodes: 0, reviewed: 0, pending: 0, confirmed: 0, rejected: 0 })
}

const assessmentLabels = {
  candidate: '可形成候选',
  review: '先复核事件',
  partial: '需联控补证',
  waiting: '证据未齐',
  blocked: '实时门禁阻断',
  testing: '开发测试',
}

export function buildMonitoringScenarioAssessments({
  scenarios = [],
  sourceHealth,
  longestQueue = null,
  maxSaturation = null,
  queueMetricMode = 'unavailable',
  episodes = [],
  usingDemoMetrics = false,
} = {}) {
  const pendingConflicts = episodes.filter((episode) => episode.type === 'conflict' && episode.reviewStatus === 'pending').length
  const confirmedConflicts = episodes.filter((episode) => episode.type === 'conflict' && episode.reviewStatus === 'confirmed').length
  const liveGateBlocked = !sourceHealth?.adviceAllowed
  const testing = usingDemoMetrics || ['development', 'fixed-demo'].includes(sourceHealth?.id)
  const assessments = scenarios.map((scenario, index) => {
    let status = testing ? 'testing' : liveGateBlocked ? 'blocked' : 'waiting'
    let evidence = testing ? scenario.demoEvidence : [`实时来源：${sourceHealth?.label || '状态未知'}`]
    const missing = []
    if (scenario.id === 'right-control') {
      evidence = [
        pendingConflicts ? `机非冲突事件：${pendingConflicts} 起待复核` : confirmedConflicts ? `机非冲突事件：${confirmedConflicts} 起已确认` : '机非冲突事件：当前无已确认事件',
        '慢行到达率：等待慢行检测',
        '右转蓄车余量：等待 lane_verified 车道与信控接口',
      ]
      missing.push('慢行需求', '右转灯组', '蓄车余量')
      if (!testing && !liveGateBlocked && pendingConflicts) status = 'review'
      else if (!testing && !liveGateBlocked && confirmedConflicts) status = 'partial'
    } else if (scenario.id === 'overflow') {
      evidence = [
        longestQueue == null ? '进口排队：等待可信米制排队' : `进口最大排队：${Math.round(longestQueue)}m${queueMetricMode === 'direction-estimate' ? '（方向降级估算）' : ''}`,
        maxSaturation == null ? '路口饱和度：等待 lane_verified 标定' : `路口最高饱和度：${Number(maxSaturation).toFixed(2)}`,
        '下游接收空间：等待走廊信控或下游检测',
      ]
      if (longestQueue == null) missing.push('可信米制排队')
      if (maxSaturation == null) missing.push('正式饱和度')
      missing.push('下游接收空间', '联控预案')
      if (!testing && !liveGateBlocked && (longestQueue != null || maxSaturation != null)) status = 'partial'
    } else {
      evidence = testing ? scenario.demoEvidence : scenario.triggerRules.map((rule) => `${rule.metric}：待接 ${rule.source}`)
      missing.push(...scenario.triggerRules.map((rule) => rule.metric))
    }
    if (testing) status = 'testing'
    else if (liveGateBlocked) {
      status = 'blocked'
      evidence = [`实时来源：${sourceHealth?.label || '状态未知'}，不形成在线建议`, ...evidence.slice(1)]
    }
    const priority = status === 'candidate' ? 0 : status === 'review' ? 1 : status === 'partial' ? 2 : status === 'waiting' ? 3 : status === 'testing' ? 4 : 5
    return { ...scenario, status, statusLabel: assessmentLabels[status], evidence, missing, priority, originalIndex: index, executable: status === 'candidate' }
  })
  return assessments.sort((left, right) => left.priority - right.priority || left.originalIndex - right.originalIndex)
}
