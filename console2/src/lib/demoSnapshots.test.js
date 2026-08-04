import { beforeEach, describe, expect, it } from 'vitest'
import {
  buildDemoAnalysisSnapshot,
  DEMO_SNAPSHOT_STORAGE_KEY,
  readDemoSnapshots,
  upsertDemoSnapshot,
} from './demoSnapshots'

const build = (overrides = {}) => buildDemoAnalysisSnapshot({
  intersectionId: 'INT-1',
  intersectionName: '测试路口',
  sourceProfileId: 'SRC-1',
  missionMode: 'hover',
  stats: {
    cars: 68,
    avg_speed_kmh: 18.6,
    lane_stats: [{ lane: '南进口直行', queue_length_m: 186, saturation: 1.04, green_utilization: 0.96 }],
  },
  trend: [{ time: '10:55', congestion_index: 7.4, cars: 68, direction_flow: { straight: 46 } }],
  events: [{ id: 'E-1', type: 'conflict', title: '机非冲突', raw: { ttc_sec: 1.2 } }],
  comparison: [{ label: '路口饱和度', before: '0.98', after: '0.76', delta: '-22%' }],
  capturedAt: '2026-08-04T02:55:28.000Z',
  savedAt: '2026-08-04T03:00:00.000Z',
  ...overrides,
})

describe('local demo analysis snapshots', () => {
  beforeEach(() => window.localStorage.clear())

  it('captures event, traffic flow, lane saturation, and comparison facts together', () => {
    const snapshot = build()

    expect(snapshot).toMatchObject({
      id: 'DEMO-SNAPSHOT-INT-1-hover',
      mission_label: '路口悬停',
      metrics: { vehicle_count: 68, avg_speed_kmh: 18.6, longest_queue_m: 186, max_saturation: 1.04, conflict_count: 1 },
    })
    expect(snapshot.traffic_flow).toHaveLength(1)
    expect(snapshot.events[0]).toMatchObject({ id: 'E-1', ttc_sec: 1.2 })
    expect(snapshot.comparison[0]).toMatchObject({ before: '0.98', after: '0.76' })
  })

  it('upserts the same intersection and phase instead of generating duplicate demo records', () => {
    upsertDemoSnapshot(build())
    upsertDemoSnapshot(build({ savedAt: '2026-08-04T03:05:00.000Z' }))
    upsertDemoSnapshot(build({ missionMode: 'review' }))

    expect(readDemoSnapshots()).toHaveLength(2)
    expect(readDemoSnapshots().map((item) => item.id)).toEqual([
      'DEMO-SNAPSHOT-INT-1-review',
      'DEMO-SNAPSHOT-INT-1-hover',
    ])
    expect(readDemoSnapshots()[1].saved_at).toBe('2026-08-04T03:05:00.000Z')
  })

  it('treats malformed browser storage as an empty ledger', () => {
    window.localStorage.setItem(DEMO_SNAPSHOT_STORAGE_KEY, '{broken')
    expect(readDemoSnapshots()).toEqual([])
  })
})
