export function normalizeRealtimeMessage(message) {
  if (!message || typeof message !== 'object') return null
  const data = message.data && typeof message.data === 'object' ? message.data : {}
  return {
    ...message,
    type: message.type,
    data,
    occurredAt: message.occurred_at || data.occurred_at || (message.ts ? new Date(message.ts * 1000).toISOString() : null),
    messageId: message.message_id || data.message_id || null,
  }
}

export function intersectionChannels(intersectionId) {
  if (!intersectionId) return []
  return [`uav_intersection:${intersectionId}`]
}

export function telemetryChannels(droneId) {
  if (!droneId) return []
  return [`uav_telemetry:${droneId}`]
}

export function alertChannels(intersectionId) {
  if (!intersectionId) return []
  return ['uav_alerts', `uav_alerts:${intersectionId}`]
}

export function realtimeEventKey(message) {
  if (message.messageId) return message.messageId
  const data = message.data || {}
  if (data.id) return `${message.type}:${data.id}`
  if (message.type === 'uav_conflict') {
    return `${message.type}:${data.motor_id ?? 'm'}:${data.non_motor_id ?? 'n'}:${message.occurredAt ?? data.timestamp ?? ''}`
  }
  return null
}
