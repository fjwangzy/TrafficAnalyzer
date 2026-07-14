import { describe, expect, it } from 'vitest'
import { alertChannels, intersectionChannels, normalizeRealtimeMessage, realtimeEventKey, telemetryChannels } from './realtime'

describe('realtime data migration adapter', () => {
  it('normalizes current messages to the uav-prefixed target model', () => {
    expect(normalizeRealtimeMessage({ type: 'stats', ts: 1, data: { cars: 3 } })).toMatchObject({
      type: 'uav_stats',
      occurredAt: '1970-01-01T00:00:01.000Z',
      data: { cars: 3 },
    })
    expect(normalizeRealtimeMessage({ type: 'uav_telemetry', data: {} }).type).toBe('uav_telemetry')
  })

  it('subscribes to canonical and temporary current channel names', () => {
    expect(intersectionChannels('INT-1')).toEqual(['uav_intersection:INT-1', 'intersection:INT-1'])
    expect(alertChannels('INT-1')).toEqual(['uav_alerts:INT-1', 'alerts:INT-1'])
    expect(telemetryChannels('UAV-1')).toEqual(['uav_telemetry:UAV-1', 'telemetry:UAV-1'])
  })

  it('builds stable deduplication keys for persisted and realtime conflicts', () => {
    expect(realtimeEventKey({ type: 'uav_stats', messageId: 'm-1', data: {} })).toBe('m-1')
    expect(realtimeEventKey({ type: 'uav_track_complete', data: { id: 'T-8' } })).toBe('uav_track_complete:T-8')
    expect(realtimeEventKey({
      type: 'uav_conflict',
      occurredAt: '2026-07-14T10:00:00Z',
      data: { motor_id: 3, non_motor_id: 9 },
    })).toBe('uav_conflict:3:9:2026-07-14T10:00:00Z')
  })
})
