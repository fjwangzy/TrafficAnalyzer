import { describe, expect, it } from 'vitest'
import { buildDashboardSourcePoints } from './DashboardPage'

describe('dashboard UAV video source map', () => {
  it('creates one map point per registered source and derives runtime state', () => {
    const points = buildDashboardSourcePoints({
      sources: [
        { profile_id: 'SRC-RUN', display_name: '运行源', drone_id: 'UAV-1', enabled: true, validation_status: 'valid' },
        { profile_id: 'SRC-DEG', display_name: '降级源', drone_id: 'UAV-1', enabled: true, validation_status: 'degraded' },
      ],
      drones: [{ id: 'UAV-1', name: '一号无人机', default_inter_id: 'INT-1' }],
      intersections: [{ id: 'INT-1', name: '一号路口', lat: 36.7, lon: 117, map_coordinate_status: 'test' }],
      pipelines: [{ source_profile_id: 'SRC-RUN', intersection_id: 'INT-1', status: 'running' }],
    })

    expect(points).toHaveLength(2)
    expect(points.find((item) => item.id === 'SRC-RUN')).toMatchObject({ source_status: 'running', intersection_id: 'INT-1' })
    expect(points.find((item) => item.id === 'SRC-DEG')).toMatchObject({ source_status: 'degraded', intersection_id: 'INT-1' })
  })

  it('keeps all five source states distinct', () => {
    const sources = [
      { profile_id: 'SRC-RUN', drone_id: 'UAV-1', enabled: true, validation_status: 'valid' },
      { profile_id: 'SRC-READY', drone_id: 'UAV-1', enabled: true, validation_status: 'valid' },
      { profile_id: 'SRC-DEG', drone_id: 'UAV-1', enabled: true, validation_status: 'degraded' },
      { profile_id: 'SRC-BAD', drone_id: 'UAV-1', enabled: true, validation_status: 'invalid' },
      { profile_id: 'SRC-OFF', drone_id: 'UAV-1', enabled: false, validation_status: 'valid' },
    ]
    const points = buildDashboardSourcePoints({
      sources,
      drones: [{ id: 'UAV-1', default_inter_id: 'INT-1' }],
      intersections: [{ id: 'INT-1', lat: 36.7, lon: 117 }],
      pipelines: [{ source_profile_id: 'SRC-RUN', intersection_id: 'INT-1', status: 'running' }],
    })

    expect(Object.fromEntries(points.map((item) => [item.id, item.source_status]))).toEqual({
      'SRC-RUN': 'running',
      'SRC-READY': 'ready',
      'SRC-DEG': 'degraded',
      'SRC-BAD': 'invalid',
      'SRC-OFF': 'disabled',
    })
  })
})
