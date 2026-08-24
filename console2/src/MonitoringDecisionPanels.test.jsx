import { describe, expect, it } from 'vitest'

import { MONITORING_SCENARIOS, buildMonitoringMovements } from './App'

describe('monitoring decision panels', () => {
  it('keeps the six approved business scenarios in one stable catalog', () => {
    expect(MONITORING_SCENARIOS.map((item) => item.label)).toEqual([
      '行人感应',
      '动态控右',
      '动态控左',
      '动态黄闪',
      '动态可变车道',
      '溢流拥堵',
    ])
  })

  it('defines a complete decision chain for every scenario instead of a fixed-second slogan', () => {
    for (const scenario of MONITORING_SCENARIOS) {
      expect(scenario.useCase.length).toBeGreaterThan(20)
      expect(scenario.objective.length).toBeGreaterThan(20)
      expect(scenario.triggerRules).toHaveLength(3)
      expect(scenario.actions).toHaveLength(3)
      expect(scenario.guardrails.length).toBeGreaterThanOrEqual(2)
      expect(scenario.exitRule.length).toBeGreaterThan(20)
      expect(scenario.reviewMetrics).toHaveLength(4)
      expect(scenario.demoEvidence).toHaveLength(3)
    }
  })

  it('keeps high-risk controls behind explicit operational gates', () => {
    const yellowFlash = MONITORING_SCENARIOS.find((item) => item.id === 'yellow-flash')
    const variableLane = MONITORING_SCENARIOS.find((item) => item.id === 'variable-lane')

    expect(yellowFlash.actions.join('')).toContain('交警值守席审批')
    expect(yellowFlash.guardrails.join('')).toContain('不得仅凭无人机')
    expect(variableLane.actions.join('')).toContain('完全清空')
    expect(variableLane.guardrails.join('')).toContain('禁止切换')
  })

  it('uses explicit physical movements when the realtime contract provides them', () => {
    const result = buildMonitoringMovements({
      movement_flows: [
        { movement_id: 'm-1', approach: '南', exit: '北', flow_veh_per_5min: 38, avg_speed_kmh: 21.5, queue_length_m: 42, saturation: .72 },
        { movement_id: 'm-2', approach: '西', exit: '东', flow_veh_per_5min: 51, avg_speed_kmh: 18.2, queue_length_m: 67, saturation: .93 },
      ],
    })

    expect(result.source).toBe('realtime')
    expect(result.rows.map((item) => item.id)).toEqual(['m-2', 'm-1'])
    expect(result.rows[0]).toMatchObject({ approach: '西进口', exit: '东出口', flow: 51, queue: 67 })
  })

  it('labels the directional fallback as mock instead of presenting it as observation', () => {
    const result = buildMonitoringMovements({ direction_flow: { straight: 12 } })

    expect(result.source).toBe('mock')
    expect(result.rows).toHaveLength(4)
    expect(result.rows[0]).toMatchObject({ approach: '西进口', exit: '东出口' })
  })

  it('aggregates real auto-lane observations and degraded queue estimates by physical direction', () => {
    const result = buildMonitoringMovements({
      road_analytics_eligible: false,
      lanes: [
        { lane_id: 'auto_1', name: '西→东 直行', flow_veh_per_min: 2.1, avg_speed_kmh: 0, queue_length_m: 0 },
        { lane_id: 'auto_2', name: '东→西 直行', flow_veh_per_min: 5.0, avg_speed_kmh: 0, queue_length_m: 0 },
        { lane_id: 'auto_3', name: '西→东 直行', flow_veh_per_min: 3.4, avg_speed_kmh: 0, queue_length_m: 0 },
      ],
    }, { allowMock: false })

    expect(result.source).toBe('observed')
    expect(result.queueMode).toBe('direction-estimate')
    expect(result.periodLabel).toBe('5 分钟滑窗 · 辆/分钟')
    expect(result.rows).toHaveLength(2)
    expect(result.rows[0]).toMatchObject({ approach: '西进口', exit: '东出口', flow: 5.5, speed: null, queue: 0, saturation: null })
    expect(result.rows[1]).toMatchObject({ approach: '东进口', exit: '西出口', flow: 5 })
  })

  it('keeps positive auto-lane speed and direction queue estimates while withholding ungated saturation', () => {
    const result = buildMonitoringMovements({
      road_analytics_eligible: false,
      lanes: [
        { lane_id: 'auto_1', name: '北→南 直行', flow_veh_per_min: 4.6, avg_speed_kmh: 4.9, queue_length_m: 12 },
        { lane_id: 'auto_2', name: '北→南 直行', flow_veh_per_min: 19.0, avg_speed_kmh: 23.7, queue_length_m: 28 },
      ],
    }, { allowMock: false })

    expect(result.rows[0].flow).toBeCloseTo(23.6)
    expect(result.rows[0].speed).toBeCloseTo(20.04, 2)
    expect(result.rows[0]).toMatchObject({ queue: 28, saturation: null })
  })

  it('does not expose pixel fallback distance as a metre queue estimate', () => {
    const result = buildMonitoringMovements({
      road_analytics_eligible: false,
      lanes: [
        { lane_id: 'auto_1', name: '北→南 直行', flow_veh_per_min: 3.0, queue_length_m: 120, queue_length_unit: 'px' },
      ],
    }, { allowMock: false })

    expect(result.queueMode).toBe('unavailable')
    expect(result.rows[0].queue).toBeNull()
  })

  it('does not fall back to mock rows when a strict truth source has no movement observation', () => {
    const result = buildMonitoringMovements({}, { allowMock: false })

    expect(result).toMatchObject({ source: 'unavailable', rows: [] })
  })

  it('infers real cardinal movements from active GCJ-02 trajectory tails when lane statistics are unavailable', () => {
    const result = buildMonitoringMovements({}, {
      allowMock: false,
      trajectories: [
        { track_id: 'east-1', avg_speed_kmh: 18, trajectory_gcj02: [[117, 36.7], [117.0001, 36.7]] },
        { track_id: 'east-2', avg_speed_kmh: 22, trajectory_gcj02: [[117, 36.7], [117.0002, 36.7]] },
        { track_id: 'south-1', avg_speed_kmh: 15, trajectory_gcj02: [[117, 36.7001], [117, 36.7]] },
        { track_id: 'stationary', avg_speed_kmh: 0, trajectory_gcj02: [[117, 36.7], [117.000001, 36.7]] },
      ],
    })

    expect(result.source).toBe('trajectory')
    expect(result.periodLabel).toBe('实时活动轨迹 · 方位推断')
    expect(result.rows).toHaveLength(2)
    expect(result.rows[0]).toMatchObject({ approach: '西进口', exit: '东出口', flow: 2, speed: 20, queue: null, saturation: null })
    expect(result.rows[1]).toMatchObject({ approach: '北进口', exit: '南出口', flow: 1, speed: 15 })
  })
})
