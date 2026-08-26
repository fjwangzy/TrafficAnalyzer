import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import { ConsoleFrame } from './components/AppShell'
import { apiErrorMessage, platformApi } from './lib/api'
import { alertChannels, intersectionChannels, telemetryChannels } from './lib/realtime'
import { detectorVideoStreamSrc } from './lib/videoStream'
import { useWebSocket } from './hooks/useWebSocket'
import { MonitoringBevMap } from './components/MonitoringBevMap'
import { useAuth } from './auth/AuthContext'
import { useAppState } from './state/AppState'
import { demoMonitoring, demoSituation } from './config/demoData'
import { buildDemoAnalysisSnapshot, upsertDemoSnapshot } from './lib/demoSnapshots'
import {
  buildMonitoringRiskSummary,
  buildMonitoringScenarioAssessments,
  buildMonitoringSourceHealth,
  clusterMonitoringConflictEpisodes,
} from './lib/monitoringBusiness'
import {
  ArrowRight, ArrowsClockwise, CaretDown, CaretLeft, CaretRight, Crosshair, Drone, Gauge, ListBullets,
  Check, Clock, Play, Plus, PushPin, PushPinSlash, RoadHorizon,
  ShieldWarning, Stack, Target, TrendUp, Truck, VideoCamera, Warning, X,
} from '@phosphor-icons/react'
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'

const asNumber = (value) => {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}
const displayNumber = (value, digits = 0) => value == null ? '—' : Number(value).toFixed(digits)
const eventTime = (value) => {
  if (value == null || value === '') return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleTimeString('zh-CN', { hour12: false })
}
const eventTone = (severity) => severity === 'critical' || severity === 'P1' ? 'critical' : severity === 'warning' || severity === 'P2' ? 'warning' : 'info'
const LIVE_BEV_TRAJECTORY_MIN_COUNT = 150
const LIVE_BEV_TRAJECTORY_WINDOW_MS = 5 * 60 * 1000
const BEV_RECEIVED_AT_FIELD = '__console_received_at_ms'

export {
  buildMonitoringRiskSummary,
  buildMonitoringScenarioAssessments,
  buildMonitoringSourceHealth,
  clusterMonitoringConflictEpisodes,
}

const APPROACH_EXIT = {
  '东': { '直行': '西', '左转': '南', '右转': '北' },
  '西': { '直行': '东', '左转': '北', '右转': '南' },
  '南': { '直行': '北', '左转': '西', '右转': '东' },
  '北': { '直行': '南', '左转': '东', '右转': '西' },
}

export const MONITORING_SCENARIOS = [
  {
    id: 'pedestrian', label: '行人感应', domain: '慢行优先',
    useCase: '学校、医院、公交站及宽幅过街口，行人需求间歇集中、固定配时容易久等或二次过街。',
    objective: '在不截断安全清空时间的前提下，降低行人高分位等待和滞留。',
    triggerRules: [
      { metric: '有效请求', rule: '等待人数、按钮请求或特殊人群需求持续达到点位阈值', source: '行人检测 / 按钮' },
      { metric: '服务缺口', rule: '预计等待超过服务上限，或现有绿灯不足以一次安全通过', source: '信号相位 / 过街宽度' },
      { metric: '冲突确认', rule: '左、右转冲突流与过街占用区已完成同周期校核', source: '慢行检测 / 信控相位' },
    ],
    actions: ['在允许窗口登记行人请求，不抢断正在执行的安全相位', '按过街宽度核算最小绿灯与清空时间，必要时插入或延长行人相位', '同步约束冲突左、右转；清空后再恢复机动车基准方案'],
    guardrails: ['检测盲区、相位未知或过街宽度未标定时禁止自动建议时长', '已进入人行横道的行人清空时间不得因机动车排队提前结束'],
    exitRule: '确认过街区清空，且连续多个周期无新请求后恢复基准配时。',
    reviewMetrics: ['P95 等待', '一次过街率', '人车冲突', '机动车增量延误'],
    demoEvidence: ['等待人数 12 人，已超过演示阈值 8 人', '最长等待 48s，已超过演示阈值 40s', '过街宽度与当前相位仍待信控接口校核'],
  },
  {
    id: 'right-control', label: '动态控右', domain: '安全干预',
    useCase: '右转不断流、慢行过街集中，或大车转弯盲区导致机非与人车冲突反复出现的进口。',
    objective: '把无保护右转切换为受控放行，同时避免右转队列回堵直行车道。',
    triggerRules: [
      { metric: '冲突风险', rule: '冲突区占用、急制动或已复核近冲突在多个周期持续出现', source: 'TCC / 视频复核' },
      { metric: '慢行需求', rule: '行人、非机动车到达率进入点位高需求区间', source: '慢行检测' },
      { metric: '蓄车余量', rule: '右转排队仍低于专用车道有效蓄车上限', source: '车道级排队 / 地图' },
    ],
    actions: ['优先采用红灯禁右或独立右转相位，明确分离冲突路权', '按慢行占用晚启、早断右转，机动车清空后再放慢行', '持续看守右转排队；接近蓄车上限时转人工优化相邻相位'],
    guardrails: ['单个未复核候选冲突不得直接触发控右', '未确认右转灯组、机非清空和停车视距时不得形成下发方案'],
    exitRule: '冲突需求连续回落且过街区清空后，在受保护窗口逐步恢复。',
    reviewMetrics: ['冲突率', '礼让率', '慢行等待', '右转最大排队'],
    demoEvidence: ['右转冲突率 6.2%，超过演示阈值 5%', '非机动车过街流量连续上升', '右转专用道蓄车余量待路网校核'],
  },
  {
    id: 'left-control', label: '动态控左', domain: '相位优化',
    useCase: '高峰左转需求集中、车辆需等待多个周期，且左转排队接近展宽段或反压直行车道。',
    objective: '消化左转积压，但不以牺牲对向直行、慢行安全或下游接收能力为代价。',
    triggerRules: [
      { metric: '左转积压', rule: '排队占用有效蓄车长度，或连续等待周期超过点位上限', source: '左转 Lane / 信控周期' },
      { metric: '相位平衡', rule: '对向直行饱和与可让渡绿灯时间处于允许范围', source: 'Movement / 相位方案' },
      { metric: '出口承接', rule: '目标出口未发生回堵，行人清空时间可完整保留', source: '下游检测 / 慢行相位' },
    ],
    actions: ['在周期上下限内增加保护左转绿信比，而不是固定增加秒数', '优先回收低需求相位空放，必要时采用分段或二次左转放行', '联动相邻路口相位差，防止本路口放行后把队列推向下游'],
    guardrails: ['下游无接收空间时禁止继续放大左转绿灯', '不得压缩法定行人清空、全红间隔和主干协调底线'],
    exitRule: '左转队列回落至恢复阈值并稳定多个周期后，回归基准绿信比。',
    reviewMetrics: ['左转最大排队', '等候周期数', '对向直行延误', '出口回堵'],
    demoEvidence: ['左转排队 96m，超过演示蓄车阈值 80m', '对向直行饱和度 0.72，存在有限让渡空间', '目标出口接收能力待下游检测确认'],
  },
  {
    id: 'yellow-flash', label: '动态黄闪', domain: '高风险控制',
    useCase: '经交管批准的夜间低流量点位；不适用于学校、医院、施工、活动保障或视距不良路口。',
    objective: '在极低需求时减少无效等待，但始终把瞭望安全和控制权审批置于效率之前。',
    triggerRules: [
      { metric: '持续低需求', rule: '机动车与慢行流量在批准时段内连续多个窗口低于点位阈值', source: '多窗口流量' },
      { metric: '安全环境', rule: '无活动风险，照明、天气、视距和路面状态均满足预案', source: '事件 / 气象 / 设备' },
      { metric: '设备就绪', rule: '信号机支持批准的转换序列，中心通信与回退方案正常', source: '信控平台' },
    ],
    actions: ['仅生成黄闪候选并提交交警值守席审批', '按信号机批准的清空与转换序列切换，不由前端直接控灯', '黄闪期间持续监测来车、慢行和冲突，任何异常立即请求回退'],
    guardrails: ['不得仅凭无人机“未发现车辆”进入黄闪', '视距不良、雨雾、设备故障、施工或保障任务期间一律禁用'],
    exitRule: '任一交通参与者、风险或环境门禁越界即按信号机预案恢复正常控制。',
    reviewMetrics: ['平均等待', '停车次数', '速度离散', '黄闪期间风险'],
    demoEvidence: ['低流量窗口持续 18min', '演示窗口内风险事件为 0', '气象、照明和信号机回退能力待外部接口确认'],
  },
  {
    id: 'variable-lane', label: '动态可变车道', domain: '设施联动',
    useCase: '转向或潮汐需求具有稳定时段性不均衡，且现场已具备可变导向标志、车道灯和清空检测。',
    objective: '把闲置车道能力转给高需求方向，并保证切换过程无占道、无误导。',
    triggerRules: [
      { metric: '需求失衡', rule: '方向流量比和排队差在多个周期稳定越过启用阈值', source: 'Movement / 排队' },
      { metric: '能力富余', rule: '相邻方向车道利用率低，切换后各出口仍可承接进口车道', source: '车道利用率 / 路网' },
      { metric: '切换就绪', rule: '目标车道已清空，车道灯、LED 与信号相位可同步切换', source: '清空检测 / 设施状态' },
    ],
    actions: ['先发布预告并停止原方向进入，等待目标车道完全清空', '核验空车道后同步切换车道灯、可变标志和对应信号相位', '小流量试放并监测误入、出口承接和排队变化，再进入稳定方案'],
    guardrails: ['车道未清空或任一指示设施离线时禁止切换', '公交、应急、专用车道与出口车道数约束不得被破坏'],
    exitRule: '需求比回落至退出阈值后，按同一“预告—清空—切换—确认”流程恢复。',
    reviewMetrics: ['方向排队差', '通行能力', '误入次数', '切换成功率'],
    demoEvidence: ['潮汐方向流量比 2.4:1', '低需求方向车道利用率 31%', '车道清空与可变标志状态待设施接口确认'],
  },
  {
    id: 'overflow', label: '溢流拥堵', domain: '防锁死',
    useCase: '短间距路口或瓶颈下游排队逼近上游停止线，继续放行会占满交叉口冲突区。',
    objective: '遵循“以出量进”，先保护路口净空，再协调下游疏散和上游控流。',
    triggerRules: [
      { metric: '空间占用', rule: '下游排队接近可用路段长度或车辆已侵入交叉口净空区', source: '下游排队 / 占有率' },
      { metric: '供需失衡', rule: '上游到达持续大于下游消散，低速状态跨多个周期延续', source: '上下游 Movement' },
      { metric: '联控条件', rule: '相邻路口、横向交通和应急通道具备可执行的协调方案', source: '走廊信控 / 预案' },
    ],
    actions: ['立即抑制驶入拥堵路段的上游放行，避免继续填满路口', '确认下游存在接收空间后优先疏散瓶颈方向并调整相位差', '必要时逐级向上游限流、绕行；恢复阶段按小步增量放开'],
    guardrails: ['下游无接收空间时禁止简单增加上游绿灯', '不得造成横向路口锁死，必须保留行人清空与应急通道'],
    exitRule: '下游队尾退出控制线并稳定多个周期后，分级恢复上游流入。',
    reviewMetrics: ['路口占堵时长', '最大排队', '走廊通过量', '恢复时间'],
    demoEvidence: ['西进口排队 128m，超过演示阈值 100m', '饱和度 1.08，超过演示阈值 0.90', '下游占有率偏高，仍需信控接口确认'],
  },
]

const MOCK_MOVEMENT_ROWS = [
  { id: 'west-east', approach: '西进口', exit: '东出口', flow: 84, speed: 23, queue: 128, saturation: 1.08 },
  { id: 'east-west', approach: '东进口', exit: '西出口', flow: 75, speed: 28, queue: 82, saturation: 0.86 },
  { id: 'north-south', approach: '北进口', exit: '南出口', flow: 71, speed: 27, queue: 96, saturation: 0.94 },
  { id: 'south-north', approach: '南进口', exit: '北出口', flow: 61, speed: 25, queue: 74, saturation: 0.79 },
]

const movementNumber = (item, ...keys) => {
  const value = keys.map((key) => item?.[key]).find((candidate) => candidate != null)
  return asNumber(value)
}

const normalizeMovementRow = (item, index) => {
  const approach = item.approach || item.entry || item.from || item.entrance || item.origin
  const exit = item.exit || item.to || item.destination || item.outbound
  if (!approach || !exit) return null
  return {
    id: item.id || item.movement_id || `${approach}-${exit}-${index}`,
    approach: String(approach).includes('进口') ? String(approach) : `${approach}进口`,
    exit: String(exit).includes('出口') ? String(exit) : `${exit}出口`,
    flow: movementNumber(item, 'flow_veh_per_5min', 'vehicle_count_5min', 'flow_veh_per_min', 'flow', 'count'),
    speed: movementNumber(item, 'avg_speed_kmh', 'average_speed', 'speed_kmh'),
    queue: movementNumber(item, 'queue_length_m', 'queue_m'),
    saturation: movementNumber(item, 'saturation', 'degree_of_saturation'),
  }
}

const aggregateMovementRows = (rows) => [...rows.reduce((groups, row) => {
  const key = `${row.approach}-${row.exit}`
  const current = groups.get(key) || {
    id: row.id,
    approach: row.approach,
    exit: row.exit,
    flow: null,
    speed: null,
    queue: null,
    saturation: null,
    _speedWeight: 0,
    _speedTotal: 0,
    _rowCount: 0,
  }
  current._rowCount += 1
  if (current._rowCount > 1) current.id = key
  if (row.flow != null) current.flow = (current.flow ?? 0) + row.flow
  if (row.speed != null) {
    const weight = row.flow > 0 ? row.flow : 1
    current._speedTotal += row.speed * weight
    current._speedWeight += weight
    current.speed = current._speedTotal / current._speedWeight
  }
  if (row.queue != null) current.queue = Math.max(current.queue ?? row.queue, row.queue)
  if (row.saturation != null) current.saturation = Math.max(current.saturation ?? row.saturation, row.saturation)
  groups.set(key, current)
  return groups
}, new Map()).values()].map(({ _speedWeight, _speedTotal, _rowCount, ...row }) => row)

const trajectoryMovementRow = (trajectory, index) => {
  const points = (Array.isArray(trajectory?.trajectory_gcj02) ? trajectory.trajectory_gcj02 : [])
    .filter((point) => Array.isArray(point) && point.length >= 2 && point.every((value) => Number.isFinite(Number(value))))
  if (points.length < 2) return null
  const [startLon, startLat] = points[0].map(Number)
  const [endLon, endLat] = points.at(-1).map(Number)
  const meanLat = (startLat + endLat) / 2 * Math.PI / 180
  const eastM = (endLon - startLon) * 111_320 * Math.cos(meanLat)
  const northM = (endLat - startLat) * 110_540
  if (Math.hypot(eastM, northM) < 1.5) return null
  const eastWest = Math.abs(eastM) >= Math.abs(northM)
  const approach = eastWest ? (eastM >= 0 ? '西' : '东') : (northM >= 0 ? '南' : '北')
  const exit = eastWest ? (eastM >= 0 ? '东' : '西') : (northM >= 0 ? '北' : '南')
  return normalizeMovementRow({
    id: trajectory.track_id || `trajectory-${index}`,
    approach,
    exit,
    count: 1,
    avg_speed_kmh: movementNumber(trajectory, 'avg_speed_kmh', 'average_speed'),
  }, index)
}

export function buildMonitoringMovements(stats, { allowMock = true, trajectories = [] } = {}) {
  const explicit = [stats?.movement_flows, stats?.direction_movements, stats?.movements]
    .find((value) => Array.isArray(value) && value.length)
  const explicitRows = (explicit || []).map(normalizeMovementRow).filter(Boolean)
  if (explicitRows.length) {
    return { source: 'realtime', queueMode: 'formal', periodLabel: '5 分钟统计', rows: aggregateMovementRows(explicitRows).sort((left, right) => (right.flow ?? -1) - (left.flow ?? -1)).slice(0, 4) }
  }

  const lanes = Array.isArray(stats?.lane_stats) ? stats.lane_stats : Array.isArray(stats?.lanes) ? stats.lanes : []
  const formalLaneRows = lanes.map((lane, index) => {
    const laneLabel = String(lane.lane || lane.lane_name || lane.name || '')
    const match = laneLabel.match(/([东西南北])进口.*?(直行|左转|右转)/)
    if (!match) return null
    const [, approach, turn] = match
    const exit = APPROACH_EXIT[approach]?.[turn]
    return normalizeMovementRow({ ...lane, id: lane.lane_id || `${approach}-${turn}-${index}`, approach, exit }, index)
  }).filter(Boolean)
  if (formalLaneRows.length) {
    return { source: 'realtime', queueMode: 'formal', periodLabel: '5 分钟滑窗 · 辆/分钟', rows: aggregateMovementRows(formalLaneRows).sort((left, right) => (right.flow ?? -1) - (left.flow ?? -1)).slice(0, 4) }
  }

  const autoLaneRows = lanes.map((lane, index) => {
    const laneLabel = String(lane.lane || lane.lane_name || lane.name || '')
    const match = laneLabel.match(/([东西南北])\s*(?:→|->|至)\s*([东西南北])(?:.*?(直行|左转|右转))?/)
    if (!match) return null
    const [, approach, exit] = match
    const row = normalizeMovementRow({
      ...lane,
      id: lane.lane_id || `auto-${approach}-${exit}-${index}`,
      approach,
      exit,
    }, index)
    if (!row) return null
    // Auto-lane directions, positive speeds and homography-derived queue length
    // remain useful degraded observations without a lane_verified map. They are
    // presented by physical movement, never as formal lane-level analytics.
    if (!(row.speed > 0)) row.speed = null
    if (stats?.road_analytics_eligible !== true) {
      if (lane.queue_length_unit === 'px') row.queue = null
      row.saturation = null
    }
    return row
  }).filter(Boolean)
  if (autoLaneRows.length) {
    return {
      source: 'observed',
      queueMode: stats?.road_analytics_eligible === true ? 'formal' : autoLaneRows.some((row) => row.queue != null) ? 'direction-estimate' : 'unavailable',
      periodLabel: '5 分钟滑窗 · 辆/分钟',
      rows: aggregateMovementRows(autoLaneRows).sort((left, right) => (right.flow ?? -1) - (left.flow ?? -1)).slice(0, 4),
    }
  }

  const trajectoryRows = trajectories.map(trajectoryMovementRow).filter(Boolean)
  if (trajectoryRows.length) {
    return { source: 'trajectory', queueMode: 'unavailable', periodLabel: '实时活动轨迹 · 方位推断', rows: aggregateMovementRows(trajectoryRows).sort((left, right) => (right.flow ?? -1) - (left.flow ?? -1)).slice(0, 4) }
  }

  return allowMock
    ? { source: 'mock', queueMode: 'formal', periodLabel: '5 分钟统计', rows: MOCK_MOVEMENT_ROWS }
    : { source: 'unavailable', queueMode: 'unavailable', periodLabel: '5 分钟统计', rows: [] }
}

const latestItems = (items, limit) => limit > 0 ? items.slice(-limit) : []
const projectableTrajectories = (items) => items.filter(
  (item) => Array.isArray(item?.trajectory_gcj02) && item.trajectory_gcj02.filter(
    (point) => Array.isArray(point) && point.length >= 2,
  ).length >= 2,
)
const splitRecentTrajectories = (items, now) => {
  const cutoff = now - LIVE_BEV_TRAJECTORY_WINDOW_MS
  return items.reduce((groups, item) => {
    groups[Number(item?.[BEV_RECEIVED_AT_FIELD]) >= cutoff ? 1 : 0].push(item)
    return groups
  }, [[], []])
}
const retainCompletedTrajectories = (items, now) => {
  const [older, recent] = splitRecentTrajectories(items, now)
  return [...latestItems(older, LIVE_BEV_TRAJECTORY_MIN_COUNT - recent.length), ...recent]
}

const FLIGHT_PHASE_LABELS = {
  hover_candidate: '悬停确认中',
  hover_verified: '悬停正拍',
  cruise_nadir: '近正射巡航',
  transition: '模式过渡',
  unsupported_pose: '姿态不支持',
  telemetry_unavailable: '遥测不可用',
}
const QUALITY_LABELS = {
  verified: '可信',
  bootstrap: '建立基线',
  degraded: '降级',
  unavailable: '不可用',
  unverified: '未验证',
}
const QUALITY_REASON_LABELS = {
  telemetry_gap: '遥测短缺或超出同步窗口',
  telemetry_unavailable: '遥测不可用',
  telemetry_inconsistent: '报告速度与派生速度不一致',
  target_outside_map_coverage: '目标已离开发布地图覆盖范围',
  map_coverage_not_verified: '地图覆盖未通过验证',
  registration_pose_lineage_required: '配准帧缺少位姿/相机谱系',
  visual_warp_not_verified: '视觉变换未通过质量门禁',
  flight_pose_not_eligible: '飞行姿态超出正式包线',
  flight_phase_not_verified: '飞行阶段尚未稳定确认',
  lane_verified_map_required: '缺少 lane_verified 运行时地图',
  pixel_to_map_projection_unavailable: '逐帧像素到地图投影不可用',
  formal_analytics_disabled: '正式研判未启用',
}

export function monitoringQualitySummary(stats) {
  const geo = stats?.geo_reference_quality || {}
  const tracking = stats?.tracking_diagnostics || {}
  const formal = stats?.formal_analytics_eligible
  const trajectoryOutput = stats?.trajectory_output_eligible
  const roadAnalytics = stats?.road_analytics_eligible ?? formal
  const reasons = [...new Set([
    ...(Array.isArray(geo.reasons) ? geo.reasons : []),
    ...(Array.isArray(tracking.quality_reasons) ? tracking.quality_reasons : []),
  ])]
  return {
    phase: stats?.flight_phase || geo.flight_phase || 'telemetry_unavailable',
    phaseLabel: FLIGHT_PHASE_LABELS[stats?.flight_phase || geo.flight_phase] || '等待飞行状态',
    formal,
    trajectoryOutput,
    roadAnalytics,
    geoAnalytics: stats?.geo_analytics_eligible,
    tccAnalytics: stats?.tcc_analytics_eligible,
    formalLabel: roadAnalytics === true ? '道路研判开启' : roadAnalytics === false ? '路网能力降级' : '道路研判待定',
    tone: roadAnalytics === true ? 'verified' : roadAnalytics === false ? 'degraded' : 'unavailable',
    reasonLabels: reasons.map((reason) => QUALITY_REASON_LABELS[reason] || reason),
    qualities: [
      ['地理参考', geo.status],
      ['遥测', geo.telemetry?.status],
      ['视觉变换', geo.visual_warp?.status],
      ['地图覆盖', geo.map_coverage?.status],
      ['目标跟踪', tracking.tracking_quality],
    ].map(([label, status]) => ({ label, status: status || 'unavailable', value: QUALITY_LABELS[status] || status || '不可用' })),
    method: tracking.tracking_method || '—',
    terminationReason: tracking.termination_reason || '—',
  }
}

function normalizeAlert(alert) {
  const rawType = alert.alert_type || alert.event_type || 'risk'
  const occurredAt = alert.timestamp || alert.occurred_at
  const occurredAtMs = occurredAt ? new Date(occurredAt).getTime() : null
  return {
    id: alert.id,
    level: eventTone(alert.severity),
    type: rawType.includes('conflict') ? 'conflict' : rawType.includes('lane') ? 'lane' : rawType.includes('congestion') ? 'congestion' : 'enforcement',
    title: alert.title || 'AI 风险事件',
    detail: alert.description || '等待技术复核',
    metric: alert.ttc_sec != null ? `TTC ${alert.ttc_sec}s · PET ${alert.pet_sec ?? '—'}s` : alert.status || '待复核',
    time: eventTime(occurredAt),
    occurredAtMs: Number.isFinite(occurredAtMs) ? occurredAtMs : null,
    reviewStatus: alert.review_status || 'pending',
    evidenceRefs: alert.evidence_refs || [],
    raw: alert,
  }
}

export function isBusinessTccConflict(data) {
  const distance = asNumber(data?.distance_m)
  return distance != null && Math.abs(distance) <= 0.01 && (data?.prediction_type == null || data.prediction_type === 'path_intersection')
}

export function realtimeMessageMatchesPipeline(message, pipelineId) {
  if (!['uav_stats', 'uav_track_complete', 'uav_conflict'].includes(message?.type)) return true
  const messagePipelineId = message?.data?.pipeline_id || message?.data?.run_id
  return Boolean(pipelineId && messagePipelineId === pipelineId)
}

function normalizeConflict(data, occurredAt, realtime = true) {
  const businessTime = occurredAt || data.occurred_at || data.timestamp
  const occurredAtMs = businessTime ? new Date(businessTime).getTime() : null
  return {
    id: data.message_id || data.source_message_id || data.id || `conflict-${data.motor_id}-${data.non_motor_id}-${businessTime || 'unknown'}`,
    level: eventTone(data.severity),
    type: 'conflict',
    title: data.title || (data.review_status === 'confirmed' ? '已确认机非冲突' : data.review_status === 'rejected' ? '已驳回机非冲突候选' : '待复核机非冲突候选'),
    detail: data.description || `轨迹 ${data.motor_id ?? '—'} 与 ${data.non_motor_id ?? '—'} 预测交汇`,
    metric: `TTC ${data.ttc_sec ?? '—'}s · PET ${data.pet_sec ?? '—'}s`,
    time: eventTime(businessTime),
    occurredAtMs: Number.isFinite(occurredAtMs) ? occurredAtMs : null,
    reviewStatus: data.review_status || 'pending',
    evidenceRefs: data.evidence_refs || [],
    raw: data,
    realtime,
  }
}

export function monitoringEventCenterUrl({ intersectionId, sourceProfileId, event }) {
  const params = new URLSearchParams({ event_type: 'conflict' })
  if (intersectionId) params.set('intersection_id', intersectionId)
  if (sourceProfileId) params.set('source_profile_id', sourceProfileId)
  const raw = event?.raw || event || {}
  const eventId = raw.message_id || raw.source_message_id || raw.id || event?.id
  const missionId = raw.mission_id || event?.mission_id
  if (missionId) params.set('mission_id', missionId)
  if (eventId) params.set('event_id', eventId)
  return `/events?${params.toString()}`
}

export function tccStatusText(diagnostics, streamActive) {
  if (!streamActive) return 'TCC 未运行：当前视频源无检测管道'
  if (!diagnostics) return 'TCC 状态等待统计'
  if (!diagnostics.enabled) return 'TCC 检测已停用'
  if (diagnostics.status === 'quality_gate_blocked') return 'TCC 已关闭：正式质量门禁未通过'
  if (!diagnostics.calibration_valid || diagnostics.status === 'missing_calibration') return 'TCC 无法检测：缺少有效标定'
  if ((diagnostics.business_events_emitted ?? diagnostics.events_emitted ?? 0) > 0) return `TCC 已产生 ${diagnostics.business_events_emitted ?? diagnostics.events_emitted} 条事件`
  if (diagnostics.status === 'deduplicated') return `TCC 已启用：候选事件已去重 ${diagnostics.deduplicated ?? 0} 条`
  if (!(diagnostics.eligible_motor_tracks > 0) || !(diagnostics.eligible_non_motor_tracks > 0)) return 'TCC 已启用：无合格机非候选'
  if (!(diagnostics.prediction_candidates > 0)) return 'TCC 已启用：无合格预测候选'
  if (!(diagnostics.evidence_passed > 0)) return 'TCC 已启用：候选未通过风险证据门禁'
  return 'TCC 已启用：本帧未产生事件'
}

function MetricCard({ label, value, unit, delta, icon: Icon, tone = 'blue', title }) {
  return <article className='metric-card' title={title}><div className={`metric-icon ${tone}`}><Icon size={17} weight='fill' /></div><div><div className='metric-label'>{label}</div><div className='metric-value'>{value}<small>{unit}</small></div></div><span className={`metric-delta ${delta?.startsWith('+') ? 'up' : ''}`}>{delta}</span></article>
}

function EventIcon({ type }) {
  const icons = { conflict: ShieldWarning, lane: ArrowsClockwise, congestion: RoadHorizon, enforcement: Truck }
  const Icon = icons[type] || Warning
  return <Icon size={18} weight='fill' />
}

const monitoringEvidenceLabels = {
  conflict_original_frame: '原始画面',
  conflict_detector_frame: '检测器 TCC 画面',
  conflict_trajectory_reconstruction: '轨迹投放图',
  conflict_keyframe: '关键帧',
}

export function MonitoringEvidenceThumb({ reference }) {
  const [url, setUrl] = useState('')
  const [expanded, setExpanded] = useState(false)
  const label = monitoringEvidenceLabels[reference?.kind] || reference?.kind || '事件证据'
  useEffect(() => {
    let active = true
    let objectUrl = ''
    if (!reference?.id) return undefined
    platformApi.surveyEvidence(reference.id).then((blob) => {
      objectUrl = URL.createObjectURL(blob)
      if (active) setUrl(objectUrl)
    }).catch(() => { if (active) setUrl('') })
    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [reference?.id])
  return <>
    <figure className='monitoring-evidence-thumb'>
      {url ? <button type='button' className='monitoring-evidence-open' aria-label={`查看${label}大图`} onClick={() => setExpanded(true)}><img src={url} alt={label} /></button> : <div><Clock size={16} />{reference?.id ? '证据加载中' : '证据引用不可读取'}</div>}
      <figcaption>{label}</figcaption>
    </figure>
    {expanded && url ? <div className='monitoring-evidence-lightbox' role='dialog' aria-modal='true' aria-label={`${label}大图`} onClick={() => setExpanded(false)}>
      <div onClick={(event) => event.stopPropagation()}>
        <img src={url} alt={`${label}大图`} />
        <button type='button' aria-label='关闭证据大图' onClick={() => setExpanded(false)}>关闭</button>
      </div>
    </div> : null}
  </>
}

export function buildMonitoringSourceOptions({ sources = [], drones = [], intersections = [], pipelines = [] }) {
  const droneById = new Map(drones.map((item) => [item.id, item]))
  const intersectionById = new Map(intersections.map((item) => [item.id, item]))
  return sources.map((source) => {
    const drone = droneById.get(source.drone_id)
    const runningPipeline = pipelines.find((item) => item.status === 'running' && item.source_profile_id === source.profile_id)
    const intersectionId = runningPipeline?.intersection_id || drone?.default_inter_id || drone?.current_intersection_id || ''
    const intersection = intersectionById.get(intersectionId)
    const displayName = source.display_name || source.video?.location_hint || source.profile_id
    const droneName = drone?.name || source.drone_id
    return {
      ...source,
      runningPipeline,
      drone,
      droneName,
      intersectionId,
      intersectionName: drone?.intersection_name || intersection?.name || intersectionId || '未绑定路口',
      isDefault: Boolean(drone?.default_video_source_id && drone.default_video_source_id === source.video?.id),
      optionLabel: `${displayName} · ${droneName}`,
    }
  })
}

export function selectMonitoringSource(options, sourceProfileId, intersectionId) {
  const requestedSource = options.find((item) => item.profile_id === sourceProfileId)
  const runningSource = options.find((item) => item.runningPipeline?.intersection_id === intersectionId)
  return (requestedSource?.runningPipeline ? requestedSource : runningSource)
    || requestedSource
    || options.find((item) => item.intersectionId === intersectionId && item.isDefault)
    || options.find((item) => item.intersectionId === intersectionId)
    || options.find((item) => item.enabled !== false && item.intersectionId)
    || options[0]
    || null
}

export function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const { platformRole } = useAuth()
  const { dispatch } = useAppState()
  const params = new URLSearchParams(location.search)
  const intersectionId = params.get('intersection_id')
  const sourceProfileId = params.get('source_profile_id')
  const requestedView = params.get('view')
  const primaryView = requestedView === 'bev' || requestedView === 'raw' ? requestedView : 'detector'
  const [mapMode, setMapMode] = useState('trajectory')
  const [eventFilter, setEventFilter] = useState('all')
  const [rightWorkspaceTab, setRightWorkspaceTab] = useState('strategy')
  const [selectedScenarioId, setSelectedScenarioId] = useState('overflow')
  const [selectedEvent, setSelectedEvent] = useState(null)
  const [droneOpen, setDroneOpen] = useState(false)
  const [layerOpen, setLayerOpen] = useState(false)
  const [leftPanelOpen, setLeftPanelOpen] = useState(true)
  const [leftPanelPinned, setLeftPanelPinned] = useState(true)
  const [rightPanelOpen, setRightPanelOpen] = useState(true)
  const [rightPanelPinned, setRightPanelPinned] = useState(true)
  const [historicalStats, setHistoricalStats] = useState(null)
  const [realtimeStats, setRealtimeStats] = useState(null)
  const [telemetry, setTelemetry] = useState(null)
  const [activeTrajectories, setActiveTrajectories] = useState([])
  const [completedTrajectories, setCompletedTrajectories] = useState([])
  const [realtimeConflicts, setRealtimeConflicts] = useState([])
  const [visibleHistoryConflicts, setVisibleHistoryConflicts] = useState([])
  const [visibleTrendRows, setVisibleTrendRows] = useState([])
  const [lastStatsAt, setLastStatsAt] = useState(0)
  const [lastStatsProducedAt, setLastStatsProducedAt] = useState(0)
  const [lastTelemetryAt, setLastTelemetryAt] = useState(0)
  const [now, setNow] = useState(Date.now())
  const [videoError, setVideoError] = useState(false)
  const [videoRetry, setVideoRetry] = useState(0)
  const [videoNonce, setVideoNonce] = useState(0)
  const [quickStartFrameStride, setQuickStartFrameStride] = useState(3)
  const [missionMode, setMissionMode] = useState(params.get('stage') === 'review' ? 'review' : 'hover')
  const [savedSnapshotId, setSavedSnapshotId] = useState('')
  const [eventReviewError, setEventReviewError] = useState('')
  const [eventSurveyError, setEventSurveyError] = useState('')
  const telemetryFingerprint = useRef('')
  const rightWorkspaceAutoSelected = useRef(false)
  const liveRef = useRef(true)
  const videoRef = useRef(null)
  const pausedBuffer = useRef({ trendRows: null, telemetry: null, conflicts: null, realtime: [] })
  const latestStats = useMemo(() => historicalStats || realtimeStats
    ? { ...(historicalStats || {}), ...(realtimeStats || {}) }
    : null, [historicalStats, realtimeStats])

  const intersectionsQuery = useQuery({ queryKey: ['monitoring-intersections'], queryFn: platformApi.intersections })
  const sourcesQuery = useQuery({ queryKey: ['monitoring-sources'], queryFn: platformApi.sources })
  const dronesQuery = useQuery({ queryKey: ['monitoring-drones'], queryFn: platformApi.drones })
  const pipelinesQuery = useQuery({ queryKey: ['monitoring-pipelines'], queryFn: platformApi.pipelines, refetchInterval: 5_000 })
  const intersections = Array.isArray(intersectionsQuery.data) ? intersectionsQuery.data : []
  const sources = Array.isArray(sourcesQuery.data) ? sourcesQuery.data : []
  const drones = Array.isArray(dronesQuery.data) ? dronesQuery.data : []
  const pipelines = Array.isArray(pipelinesQuery.data) ? pipelinesQuery.data : []
  const monitoringSources = useMemo(
    () => buildMonitoringSourceOptions({ sources, drones, intersections, pipelines }),
    [sources, drones, intersections, pipelines],
  )
  const monitoringSourcesReady = !intersectionsQuery.isLoading
    && !sourcesQuery.isLoading
    && !dronesQuery.isLoading
    && !pipelinesQuery.isLoading
  const displayMonitoringSources = useMemo(
    () => monitoringSources.length ? monitoringSources : monitoringSourcesReady ? [demoMonitoring.source] : [],
    [monitoringSources, monitoringSourcesReady],
  )
  const selectedSource = useMemo(
    () => selectMonitoringSource(displayMonitoringSources, sourceProfileId, intersectionId)
      || (!monitoringSourcesReady ? demoMonitoring.source : null),
    [displayMonitoringSources, sourceProfileId, intersectionId, monitoringSourcesReady],
  )
  const fixedDemoSource = selectedSource?.profile_id === demoMonitoring.source.profile_id
  // Only the explicit fixed-demo source may render the fixed snapshot. Every
  // registered replay or live source must expose its own data or an empty state.
  const displayStats = latestStats || (fixedDemoSource ? demoMonitoring.stats : null)
  const selectedId = selectedSource?.intersectionId || intersectionId || intersections[0]?.id || demoMonitoring.source.intersectionId
  const selectedIntersection = intersections.find((item) => item.id === selectedId) || (selectedSource ? {
    id: selectedId,
    name: selectedSource.intersectionName,
    center_gcj02: selectedSource.drone?.last_telemetry?.position_gcj02 || demoMonitoring.telemetry.position_gcj02,
    current_drone_id: selectedSource.drone_id,
  } : null)
  const pipeline = pipelines.find((item) => item.status === 'running' && (
    selectedSource
      ? item.source_profile_id === selectedSource.profile_id
      : item.intersection_id === selectedId
  )) || null
  const intersectionQuery = useQuery({ queryKey: ['monitoring-intersection', selectedId], queryFn: () => platformApi.intersection(selectedId), enabled: Boolean(selectedId) })
  const trendPeriod = selectedSource?.mode === 'local' ? 'all' : '30m'
  const trendWindowLabel = selectedSource?.mode === 'local' ? '原始视频时间轴' : '最近 30 分钟'
  const trendQuery = useQuery({ queryKey: ['monitoring-trend', selectedId, selectedSource?.profile_id, pipeline?.pipeline_id, trendPeriod], queryFn: () => platformApi.intersectionStats(selectedId, trendPeriod, '5m', selectedSource?.profile_id, pipeline?.pipeline_id), enabled: Boolean(selectedId), refetchInterval: 30_000 })
  const conflictPeriod = selectedSource?.mode === 'local' ? 'all' : '24h'
  const conflictsQuery = useQuery({
    queryKey: ['monitoring-conflicts', selectedId, selectedSource?.profile_id, pipeline?.pipeline_id, conflictPeriod],
    queryFn: () => platformApi.conflicts(selectedId, { period: conflictPeriod, limit: 20, source_profile_id: selectedSource.profile_id, pipeline_id: pipeline?.pipeline_id, prediction_type: 'path_intersection' }),
    enabled: Boolean(selectedId && selectedSource?.profile_id),
    refetchInterval: 10_000,
  })
  useEffect(() => {
    if (monitoringSourcesReady && selectedSource && (sourceProfileId !== selectedSource.profile_id || intersectionId !== selectedId)) {
      const next = new URLSearchParams(location.search)
      next.set('intersection_id', selectedId)
      next.set('source_profile_id', selectedSource.profile_id)
      navigate(`${location.pathname}?${next.toString()}`, { replace: true })
    }
  }, [sourceProfileId, intersectionId, selectedSource, selectedId, location.pathname, location.search, navigate, monitoringSourcesReady])
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (liveRef.current) setNow(Date.now())
    }, 1000)
    return () => window.clearInterval(timer)
  }, [])
  useEffect(() => {
    setHistoricalStats(null); setRealtimeStats(null); setTelemetry(null); setActiveTrajectories([]); setCompletedTrajectories([]); setRealtimeConflicts([]); setVisibleHistoryConflicts([]); setVisibleTrendRows([]); setSelectedEvent(null); setSavedSnapshotId(''); setEventReviewError(''); setEventSurveyError(''); setVideoError(false); setVideoRetry(0); setLastStatsAt(0); setLastStatsProducedAt(0); setLastTelemetryAt(0); setRightWorkspaceTab('strategy'); rightWorkspaceAutoSelected.current = false; telemetryFingerprint.current = ''; pausedBuffer.current = { trendRows: null, telemetry: null, conflicts: null, realtime: [] }
  }, [selectedId, selectedSource?.profile_id])
  const intersectionPipeline = pipelines.find((item) => item.status === 'running' && item.intersection_id === selectedId) || null
  useEffect(() => {
    setRealtimeStats(null); setActiveTrajectories([]); setCompletedTrajectories([]); setRealtimeConflicts([]); setLastStatsAt(0); setLastStatsProducedAt(0); pausedBuffer.current = { ...pausedBuffer.current, realtime: [] }
  }, [pipeline?.pipeline_id])
  const quickStartMutation = useMutation({
    mutationFn: async ({ source, intersection }) => {
      const mission = await platformApi.createMission({
        name: `快速演示 · ${source.intersectionName || intersection}`,
        drone_id: source.drone_id,
        source_profile_id: source.profile_id,
        inter_id: intersection,
        frame_stride: quickStartFrameStride,
        scheduled_end_at: new Date(Date.now() + 3_600_000).toISOString(),
      })
      if (mission?.status !== 'running') {
        throw new Error(mission?.error_message || mission?.reason_code || '演示检测启动失败')
      }
      return mission
    },
    onSuccess: () => pipelinesQuery.refetch(),
  })
  const cameraId = pipeline?.camera_id
  const telemetryDroneId = pipeline?.drone_id || selectedSource?.drone_id || (cameraId != null ? `drone_${cameraId}` : '')
  const telemetryQuery = useQuery({ queryKey: ['monitoring-telemetry', telemetryDroneId], queryFn: () => platformApi.telemetry(telemetryDroneId), enabled: Boolean(telemetryDroneId), refetchInterval: 10_000 })
  const applyHistoricalStatsSnapshot = useCallback((snapshot) => {
    if (snapshot) setHistoricalStats(snapshot)
  }, [])
  const applyRealtimeStatsSnapshot = useCallback((snapshot, producedAt) => {
    if (!snapshot) return
    setRealtimeStats((previous) => ({ ...(previous || {}), ...snapshot }))
    if (Array.isArray(snapshot.active_trajectories)) {
      setActiveTrajectories(snapshot.active_trajectories)
    }
    setLastStatsAt(Date.now())
    const producedAtMs = producedAt ? new Date(producedAt).getTime() : null
    setLastStatsProducedAt(Number.isFinite(producedAtMs) ? producedAtMs : 0)
  }, [])
  const applyTelemetrySnapshot = useCallback((snapshot) => {
    if (!snapshot || snapshot.error) return
    const fingerprint = JSON.stringify(snapshot)
    setTelemetry(snapshot)
    if (fingerprint !== telemetryFingerprint.current) {
      telemetryFingerprint.current = fingerprint
      setLastTelemetryAt(Date.now())
    }
  }, [])
  useEffect(() => {
    const rows = Array.isArray(trendQuery.data) ? trendQuery.data : []
    const snapshot = rows.at(-1)
    if (!snapshot) return
    if (!liveRef.current) {
      pausedBuffer.current.trendRows = rows
      return
    }
    setVisibleTrendRows(rows)
    applyHistoricalStatsSnapshot(snapshot)
  }, [trendQuery.data, applyHistoricalStatsSnapshot])
  useEffect(() => {
    const rows = Array.isArray(conflictsQuery.data) ? conflictsQuery.data : []
    if (!liveRef.current) pausedBuffer.current.conflicts = rows
    else setVisibleHistoryConflicts(rows)
  }, [conflictsQuery.data])
  useEffect(() => {
    const snapshot = telemetryQuery.data
    if (!snapshot || snapshot.error) return
    if (!liveRef.current) {
      pausedBuffer.current.telemetry = snapshot
      return
    }
    applyTelemetrySnapshot(snapshot)
  }, [telemetryQuery.data, applyTelemetrySnapshot])
  const telemetryDroneIds = [...new Set([
    intersectionQuery.data?.current_drone_id,
    selectedSource?.drone_id,
    pipeline?.drone_id,
    latestStats?.drone_id,
    cameraId != null ? `drone_${cameraId}` : null,
  ].filter(Boolean))]
  const droneId = telemetry?.drone_id || telemetryDroneIds[0] || ''
  const applyRealtimeMessage = useCallback((message) => {
    if (message.data?.source_profile_id && selectedSource?.profile_id && message.data.source_profile_id !== selectedSource.profile_id) return
    if (!realtimeMessageMatchesPipeline(message, pipeline?.pipeline_id)) return
    if (message.type === 'uav_stats') {
      applyRealtimeStatsSnapshot(message.data, message.producedAt || message.produced_at || message.occurredAt || message.occurred_at)
    } else if (message.type === 'uav_track_complete') {
      const receivedAt = Date.now()
      const completed = { ...message.data, [BEV_RECEIVED_AT_FIELD]: receivedAt }
      setCompletedTrajectories((items) => retainCompletedTrajectories([...items, completed], receivedAt))
    } else if (message.type === 'uav_conflict') {
      if (!isBusinessTccConflict(message.data)) return
      const conflict = normalizeConflict(message.data, message.occurredAt || message.occurred_at)
      setRealtimeConflicts((items) => [conflict, ...items.filter((item) => item.id !== conflict.id)].slice(0, 20))
    } else if (message.type === 'uav_alert_new') {
      if (!selectedSource?.profile_id || message.data?.source_profile_id !== selectedSource.profile_id) return
      const alert = normalizeAlert(message.data)
      setRealtimeConflicts((items) => [alert, ...items.filter((item) => item.id !== alert.id)].slice(0, 20))
    } else if (message.type === 'uav_telemetry') {
      applyTelemetrySnapshot(message.data)
    }
  }, [applyRealtimeStatsSnapshot, applyTelemetrySnapshot, pipeline?.pipeline_id, selectedSource?.profile_id])
  const onRealtimeMessage = useCallback((message) => {
    if (!liveRef.current) {
      pausedBuffer.current.realtime = [...pausedBuffer.current.realtime.slice(-499), message]
      return
    }
    applyRealtimeMessage(message)
  }, [applyRealtimeMessage])
  const wsStatus = useWebSocket({ channels: [...intersectionChannels(selectedId), ...alertChannels(selectedId), ...telemetryDroneIds.flatMap(telemetryChannels)], onMessage: onRealtimeMessage, enabled: Boolean(selectedId) })

  const setQueryValue = (key, value) => {
    const next = new URLSearchParams(location.search)
    next.set(key, value)
    navigate(`${location.pathname}?${next.toString()}`, { replace: true })
  }
  const selectSource = (profileId) => {
    const source = displayMonitoringSources.find((item) => item.profile_id === profileId)
    if (!source) return
    const next = new URLSearchParams(location.search)
    next.set('source_profile_id', profileId)
    if (source.intersectionId) next.set('intersection_id', source.intersectionId)
    navigate(`${location.pathname}?${next.toString()}`, { replace: true })
  }
  const selectView = (view) => setQueryValue('view', view)
  const historyConflicts = visibleHistoryConflicts.filter(isBusinessTccConflict).map((item) => normalizeConflict(item, item.occurred_at, false))
  const rawEvents = useMemo(() => {
    const seen = new Set()
    return [...realtimeConflicts, ...historyConflicts].filter((event) => event.id && !seen.has(event.id) && seen.add(event.id)).slice(0, 20)
  }, [realtimeConflicts, historyConflicts])
  const events = useMemo(() => clusterMonitoringConflictEpisodes(rawEvents), [rawEvents])
  const riskSummary = useMemo(() => buildMonitoringRiskSummary(events), [events])
  const displayedEvents = events.length ? events : fixedDemoSource ? demoMonitoring.events : []
  useEffect(() => {
    if (!rightWorkspaceAutoSelected.current && displayedEvents.length) {
      rightWorkspaceAutoSelected.current = true
      setRightWorkspaceTab('events')
    }
  }, [displayedEvents.length])
  useEffect(() => {
    if (displayedEvents.length && !displayedEvents.some((event) => event.id === selectedEvent?.id)) {
      setSelectedEvent(displayedEvents[0])
    }
  }, [displayedEvents, selectedEvent])
  const filteredEvents = eventFilter === 'all' ? displayedEvents : displayedEvents.filter((event) => event.level === eventFilter)
  const eventCenterEvent = events.find((event) => event.id === selectedEvent?.id) || events[0] || null
  const selectedPersistentEvent = events.find((event) => event.id === selectedEvent?.id) || null
  const eventDetailQuery = useQuery({
    queryKey: ['monitoring-event-detail', selectedPersistentEvent?.id],
    queryFn: () => platformApi.event(selectedPersistentEvent.id),
    enabled: Boolean(selectedPersistentEvent?.id),
  })
  const eventDetail = eventDetailQuery.data
    ? { ...(eventDetailQuery.data.payload || {}), ...eventDetailQuery.data }
    : selectedPersistentEvent?.raw || null
  const selectedEvidenceRefs = eventDetail?.evidence_refs || selectedPersistentEvent?.evidenceRefs || []
  const selectedReviewStatus = eventDetail?.review_status || selectedPersistentEvent?.reviewStatus || 'pending'
  const selectedReviewRevision = asNumber(eventDetail?.review_revision)
  const eventReviewMutation = useMutation({
    mutationFn: (reviewStatus) => platformApi.reviewEvent(selectedPersistentEvent.id, {
      review_status: reviewStatus,
      expected_revision: selectedReviewRevision,
      reason: '实时监控技术复核',
    }),
    onSuccess: async (value) => {
      setEventReviewError('')
      await Promise.all([eventDetailQuery.refetch(), conflictsQuery.refetch()])
      dispatch({ type: 'TOAST', value: { tone: 'success', text: value.review_status === 'confirmed' ? '事件已技术确认并回写台账' : '事件已驳回并回写台账' } })
    },
    onError: (error) => setEventReviewError(apiErrorMessage(error, '技术复核失败')),
  })
  const reviewAllowed = platformRole === 'admin' && eventDetail?.review_supported !== false && Number.isInteger(selectedReviewRevision) && selectedReviewRevision >= 1
  const hasReusableEventFrame = selectedEvidenceRefs.some((reference) => ['conflict_original_frame', 'conflict_keyframe'].includes(reference.kind))
  const eventSurveyAllowed = platformRole === 'admin' && selectedSource?.mode === 'local' && hasReusableEventFrame
  const eventSurveyMutation = useMutation({
    mutationFn: () => platformApi.createEventSurvey(selectedPersistentEvent.id, `monitoring-event-survey-${selectedPersistentEvent.id}`),
    onSuccess: (value) => {
      setEventSurveyError('')
      dispatch({ type: 'TOAST', value: { tone: 'success', text: '已从事件原始画面建立证据复核任务' } })
      navigate(`/survey/${value.task.id}/measure`)
    },
    onError: (error) => setEventSurveyError(apiErrorMessage(error, '建立证据复核任务失败')),
  })
  const selectRightWorkspaceTab = (tab) => {
    rightWorkspaceAutoSelected.current = true
    setRightWorkspaceTab(tab)
  }
  const selectMonitoringEvent = (event) => {
    setSelectedEvent(event)
    setEventReviewError('')
    setEventSurveyError('')
    if (event?.type === 'conflict') setMapMode('risk')
  }

  const statsRows = visibleTrendRows.length ? visibleTrendRows : fixedDemoSource ? demoMonitoring.trend : []
  const trendData = statsRows.map((row, index) => ({ time: eventTime(row.timestamp || row.time || Date.now() - (statsRows.length - index) * 300_000).slice(0, 5), value: asNumber(row.congestion_index ?? row.cars_amount ?? row.cars ?? row.total_vehicles) })).filter((row) => row.value != null)
  const flowData = statsRows.slice(-6).map((row, index) => {
    const direction = row.direction_flow || {}
    const directionCount = (...keys) => {
      const value = keys.map((key) => direction[key]).find((item) => item != null)
      return asNumber(value?.count ?? value)
    }
    return {
      time: eventTime(row.timestamp || row.time || Date.now() - (6 - index) * 300_000).slice(0, 5),
      straight: directionCount('straight'),
      left: directionCount('left_turn', 'left'),
      right: directionCount('right_turn', 'right'),
    }
  }).filter((row) => row.straight != null || row.left != null || row.right != null)
  const streamActive = Boolean(pipeline)
  const usingDemoMetrics = fixedDemoSource
  // A local source can legitimately arrive through REST before a fresh socket
  // message.  Its source-time is historical by design, so calling that fact a
  // "fixed demo snapshot" (or wall-clock stale) would misrepresent replay
  // evidence as synthetic data.
  const replaySnapshot = selectedSource?.mode === 'local' && !usingDemoMetrics && Boolean(latestStats)
  const metricStats = usingDemoMetrics ? demoMonitoring.stats : displayStats
  useEffect(() => {
    if (!videoError || !streamActive) return undefined
    const retryDelay = videoRetry >= 5 ? 10_000 : 3_000
    const timer = window.setTimeout(() => {
      setVideoRetry((value) => value + 1)
      setVideoNonce(Date.now())
      setVideoError(false)
    }, retryDelay)
    return () => window.clearTimeout(timer)
  }, [videoError, videoRetry, streamActive])
  const candidateTrajectories = useMemo(
    () => (Array.isArray(realtimeStats?.candidate_trajectories) ? realtimeStats.candidate_trajectories : [])
      .map((item) => ({ ...item, trajectory_display_role: 'candidate' })),
    [realtimeStats?.candidate_trajectories],
  )
  const pixelTrajectories = [
    ...candidateTrajectories,
    ...activeTrajectories.map((item) => ({ ...item, trajectory_display_role: 'active' })),
  ]
  const drawablePixelTrajectoryCount = pixelTrajectories.filter(
    (item) => Array.isArray(item?.trajectory_px) && item.trajectory_px.filter(
      (point) => Array.isArray(point) && point.length >= 2,
    ).length >= 2,
  ).length
  const liveWorldTrajectories = useMemo(() => {
    const active = projectableTrajectories(activeTrajectories)
    const candidates = projectableTrajectories(candidateTrajectories)
    const [olderCompleted, recentCompleted] = splitRecentTrajectories(
      projectableTrajectories(completedTrajectories),
      now,
    )
    const olderBackfill = latestItems(
      olderCompleted,
      LIVE_BEV_TRAJECTORY_MIN_COUNT - active.length - candidates.length - recentCompleted.length,
    )
    return [...olderBackfill, ...recentCompleted, ...candidates, ...active]
  }, [activeTrajectories, candidateTrajectories, completedTrajectories, now])
  const focusedTrackIds = useMemo(() => new Set([
    selectedEvent?.motorId,
    selectedEvent?.nonMotorId,
    selectedEvent?.raw?.motor_id,
    selectedEvent?.raw?.non_motor_id,
  ].filter((value) => value != null).map(String)), [selectedEvent])
  const eventFocusActive = rightWorkspaceTab === 'events' && focusedTrackIds.size > 0
  const focusTrajectory = (item) => {
    const trackId = item?.track_id ?? item?.association_id ?? item?.id
    const selected = eventFocusActive && focusedTrackIds.has(String(trackId))
    return { ...item, selected, dimmed: eventFocusActive && !selected }
  }
  const worldTrajectories = eventFocusActive ? liveWorldTrajectories.map(focusTrajectory) : liveWorldTrajectories
  const displayPixelTrajectories = eventFocusActive ? pixelTrajectories.map(focusTrajectory) : pixelTrajectories
  const cars = asNumber(metricStats?.cars ?? metricStats?.total_vehicles ?? metricStats?.cars_amount)
  const avgSpeed = asNumber(metricStats?.avg_speed_kmh ?? metricStats?.average_speed)
  const laneStats = Array.isArray(metricStats?.lane_stats) ? metricStats.lane_stats : Array.isArray(metricStats?.lanes) ? metricStats.lanes : []
  const movementPanel = useMemo(() => buildMonitoringMovements(metricStats, { allowMock: fixedDemoSource, trajectories: activeTrajectories }), [metricStats, fixedDemoSource, activeTrajectories])
  const formalRoadMetricsAvailable = fixedDemoSource || metricStats?.road_analytics_eligible === true
  const directionQueueValues = movementPanel.queueMode === 'direction-estimate'
    ? movementPanel.rows.map((movement) => asNumber(movement.queue)).filter((value) => value != null)
    : []
  const queueValues = formalRoadMetricsAvailable
    ? laneStats.map((lane) => asNumber(lane.queue_length_m)).filter((value) => value != null)
    : directionQueueValues
  const saturationValues = formalRoadMetricsAvailable ? laneStats.map((lane) => asNumber(lane.saturation)).filter((value) => value != null) : []
  const longestQueue = queueValues.length ? Math.max(...queueValues) : null
  const maxSaturation = saturationValues.length ? Math.max(...saturationValues) : null
  const queueMetricMode = formalRoadMetricsAvailable ? 'formal' : directionQueueValues.length ? 'direction-estimate' : 'unavailable'
  const fps = asNumber(metricStats?.fps)
  const inferenceMs = asNumber(metricStats?.inference_ms)
  const inferenceImgSize = asNumber(metricStats?.inference_context?.effective_imgsz)
  const pipelineProcessingMs = asNumber(metricStats?.pipeline_processing_ms ?? metricStats?.processing_ms)
  const sourceDropCount = asNumber(metricStats?.source_drop_count ?? metricStats?.source_diagnostics?.drop_count)
  const endToEndLatencyMs = lastStatsAt && lastStatsProducedAt ? Math.max(0, lastStatsAt - lastStatsProducedAt) : null
  const sourceHealth = buildMonitoringSourceHealth({
    sourceMode: selectedSource?.mode,
    usingDemoMetrics,
    streamActive,
    wsStatus,
    lastStatsAt,
    now,
    videoError,
    endToEndLatencyMs,
    pipelineProcessingMs,
    sourceDropCount,
  })
  const scenarioAssessments = useMemo(() => buildMonitoringScenarioAssessments({
    scenarios: MONITORING_SCENARIOS,
    sourceHealth,
    longestQueue,
    maxSaturation,
    queueMetricMode,
    episodes: events,
    usingDemoMetrics,
  }), [sourceHealth.id, sourceHealth.adviceAllowed, longestQueue, maxSaturation, queueMetricMode, events, usingDemoMetrics])
  const selectedScenario = scenarioAssessments.find((scenario) => scenario.id === selectedScenarioId) || scenarioAssessments[0]
  const scenarioEvidenceMode = selectedScenario.status
  const scenarioEvidence = selectedScenario.evidence
  const statsStale = usingDemoMetrics || replaySnapshot ? false : ['stale', 'interrupted', 'stopped'].includes(sourceHealth.id)
  const realtimeTrajectoryCount = fixedDemoSource ? 42 : (statsStale || !streamActive ? null : (asNumber(metricStats?.active_tracks) ?? activeTrajectories.length))
  const telemetryStale = usingDemoMetrics ? false : (!lastTelemetryAt || now - lastTelemetryAt > 30_000)
  const attitude = usingDemoMetrics ? demoMonitoring.telemetry : telemetry || displayStats?.drone_position || {}
  const mapCenterLat = asNumber(selectedIntersection?.center_gcj02?.latitude ?? intersectionQuery.data?.center_gcj02?.latitude ?? attitude.position_gcj02?.latitude) ?? 36.703222
  const mapCenterLon = asNumber(selectedIntersection?.center_gcj02?.longitude ?? intersectionQuery.data?.center_gcj02?.longitude ?? attitude.position_gcj02?.longitude) ?? 117.028285
  const height = asNumber(attitude.height ?? attitude.altitude ?? attitude.altitude_agl)
  const heading = asNumber(attitude.heading ?? attitude.attitude_head ?? attitude.yaw)
  const pitch = asNumber(attitude.attitude_pitch ?? attitude.pitch ?? attitude.gimbal_pitch)
  const roll = asNumber(attitude.attitude_roll ?? attitude.roll ?? attitude.gimbal_roll)
  const tccStatus = usingDemoMetrics ? '固定演示 · 机非冲突 2 起' : tccStatusText(displayStats?.tcc_diagnostics, streamActive)
  const flightQuality = monitoringQualitySummary(usingDemoMetrics ? demoMonitoring.stats : displayStats)
  const unprojectedTrajectoryCount = [...activeTrajectories, ...completedTrajectories]
    .filter((item) => !Array.isArray(item?.trajectory_gcj02) || item.trajectory_gcj02.filter(Boolean).length < 2).length
  const unprojectedCandidateCount = candidateTrajectories.filter((item) => !Array.isArray(item?.trajectory_gcj02) || item.trajectory_gcj02.filter(Boolean).length < 2).length
  const bevEmptyMessage = streamActive
    ? unprojectedTrajectoryCount
      ? `像素轨迹 ${unprojectedTrajectoryCount} 条 · 地理投影不可用`
      : unprojectedCandidateCount
        ? `候选目标 ${unprojectedCandidateCount} · 地理投影不可用`
      : '等待 GCJ-02 实时轨迹'
    : '等待实时 Pipeline 轨迹投放'
  const realtimeStatus = usingDemoMetrics ? '固定演示指标已加载' : wsStatus === 'connected'
    ? '实时链路已连接'
    : wsStatus === 'connecting'
      ? '实时链路连接中，当前展示历史/REST 数据'
      : '实时链路已断开，当前展示历史/REST 数据'
  const sourceModeLabel = selectedSource?.profile_id === demoMonitoring.source.profile_id
    ? '固定演示指标'
    : !streamActive ? '监测离线'
      : selectedSource?.mode === 'local' ? '开发回放'
        : sourceHealth.label
  const snapshotPreparing = intersectionsQuery.isLoading || sourcesQuery.isLoading || dronesQuery.isLoading || pipelinesQuery.isLoading || (streamActive && !latestStats)
  const quickStartUnavailableReason = platformRole !== 'admin'
    ? '仅管理员可启动演示检测'
    : selectedSource?.enabled === false
      ? '当前视频源已停用'
      : !selectedSource?.drone_id || !selectedId
        ? '当前视频源未绑定无人机或路口'
        : intersectionPipeline
          ? '当前路口已有其他检测任务运行'
          : ''
  const mjpegSrc = detectorVideoStreamSrc(pipeline, videoNonce)
  const videoStreamAvailable = Boolean(mjpegSrc)
  const mainIsVideo = primaryView !== 'bev'
  const selectedRaw = eventDetail || selectedEvent?.raw || {}
  const timestamp = new Date(now).toLocaleTimeString('zh-CN', { hour12: false })
  const activateMissionMode = (mode) => {
    setMissionMode(mode)
    const labels = { hover: '路口悬停', cruise: '路段航拍', review: '治理后复盘' }
    dispatch({ type: 'TOAST', value: { tone: 'success', text: `${labels[mode]}演示已启动，指标保持固定快照` } })
  }
  const saveDemoSnapshot = () => {
    const savedAt = new Date().toISOString()
    const snapshot = buildDemoAnalysisSnapshot({
      intersectionId: selectedId,
      intersectionName: selectedSource?.intersectionName || selectedIntersection?.name || selectedId,
      sourceProfileId: selectedSource?.profile_id,
      missionMode,
      sourceMode: usingDemoMetrics ? 'fixed_demo' : 'live',
      stats: metricStats,
      trend: statsRows,
      events: displayedEvents,
      comparison: demoSituation.comparison,
      capturedAt: new Date(now).toISOString(),
      savedAt,
    })
    upsertDemoSnapshot(snapshot)
    setSavedSnapshotId(snapshot.id)
    dispatch({ type: 'TOAST', value: { tone: 'success', text: '事件与交通流快照已保存，可在事件中心继续分析' } })
  }
  useEffect(() => {
    if (!streamActive || !videoStreamAvailable || videoError) return undefined
    const timer = window.setTimeout(() => {
      if (!videoRef.current || videoRef.current.naturalWidth === 0) setVideoError(true)
    }, 8_000)
    return () => window.clearTimeout(timer)
  }, [streamActive, videoStreamAvailable, videoError, mjpegSrc, primaryView])
  return <ConsoleFrame pageTitle='实时监测' immersive>
    <h1 className='sr-only'>实时监测</h1>
    {mainIsVideo && streamActive && videoStreamAvailable && !videoError ? <img ref={videoRef} className={`map-image ${primaryView}`} src={mjpegSrc} alt={primaryView === 'raw' ? '原始视频流' : '检测器输出视频流'} onLoad={() => { setVideoError(false); setVideoRetry(0) }} onError={() => setVideoError(true)} /> : primaryView === 'bev' ? <MonitoringBevMap centerLat={mapCenterLat} centerLon={mapCenterLon} trajectories={worldTrajectories} pixelTrajectories={displayPixelTrajectories} activeCount={activeTrajectories.length} emptyMessage={bevEmptyMessage} label={worldTrajectories.length || !drawablePixelTrajectoryCount ? 'BEV 地图轨迹主视图' : '像素坐标实时轨迹主视图'} /> : <div className='map-image feed-unavailable'><strong>{streamActive ? (!videoStreamAvailable ? '检测器未登记直连视频地址' : videoRetry >= 5 ? '视频流连接失败' : `视频流重连中 · ${videoRetry + 1}/5`) : '当前没有实时视频，固定演示指标已加载'}</strong><span>{streamActive ? (videoStreamAvailable ? (videoRetry >= 5 ? '检测器仍在运行，10 秒后继续自动重试视频流' : '每 3 秒直连检测器重试；持续失败后转为每 10 秒自动恢复') : '请重启 Pipeline 以登记浏览器可访问的 MJPEG 地址') : '可继续演示路口悬停、路段航拍、机非冲突与治理复盘'}</span>{!streamActive && selectedSource?.profile_id !== demoMonitoring.source.profile_id && <div className='quick-start-actions'><label className='quick-start-stride'>抽帧步长<input aria-label='抽帧步长' type='number' min='1' max='30' value={quickStartFrameStride} onChange={(event) => setQuickStartFrameStride(Math.min(30, Math.max(1, Number(event.target.value) || 1)))} /><small>每 N 帧处理 1 帧</small></label><button className='quick-start-button' type='button' title={quickStartUnavailableReason || '启动当前视频源的一小时演示检测'} disabled={Boolean(quickStartUnavailableReason) || quickStartMutation.isPending} onClick={() => quickStartMutation.mutate({ source: selectedSource, intersection: selectedId })}><Play size={15} weight='fill' />{quickStartMutation.isPending ? '正在启动…' : '启动演示检测'}</button>{quickStartMutation.error && <span className='quick-start-error' role='alert'>{apiErrorMessage(quickStartMutation.error, '演示检测启动失败')}</span>}</div>}</div>}
    <div className='map-vignette' />

    <section className='context-bar'>
      <div className='context-title'>
        <span className={`status-pulse ${sourceHealth.tone}`} />
        <div>
          <div className='monitoring-source-picker'>
            <select
              aria-label='选择无人机视频源'
              title={selectedSource?.optionLabel || '选择无人机视频源'}
              value={selectedSource?.profile_id || ''}
              onChange={(event) => selectSource(event.target.value)}
              disabled={!displayMonitoringSources.length}
            >
              {displayMonitoringSources.map((item) => <option value={item.profile_id} key={item.profile_id} disabled={item.enabled === false}>{item.optionLabel}{item.enabled === false ? ' · 已停用' : ''}</option>)}
            </select>
            <CaretDown className='monitoring-source-caret' size={14} weight='bold' aria-hidden='true' />
          </div>
          <small title={`${selectedSource?.intersectionName || selectedId || '—'} · ${selectedSource?.profile_id || '未绑定视频源'} · ${sourceModeLabel}`}>{selectedSource?.intersectionName || selectedId || '—'} · {selectedSource?.profile_id || '未绑定视频源'} · {sourceModeLabel}</small>
        </div>
      </div>
      <div className='flight-attitude' aria-label='飞行姿态数据'><div><span>高度</span><strong>{displayNumber(height, 1)}<small>m</small></strong></div><div><span>航向</span><strong>{displayNumber(heading, 1)}<small>°</small></strong></div><div><span>俯仰</span><strong>{displayNumber(pitch, 1)}<small>°</small></strong></div><div><span>横滚</span><strong>{displayNumber(roll, 1)}<small>°</small></strong></div><div><span>云台</span><strong>{telemetryStale ? '过期' : attitude.gimbal_mode || (attitude.is_hovering ? '锁定' : '跟随')}</strong></div></div>
      <div className='view-tabs'>{[['trajectory', '轨迹'], ['lane', '车道'], ['risk', '风险'], ['raw', '原始画面']].map(([id, label]) => <button key={id} className={(id === 'raw' ? primaryView === 'raw' : mapMode === id && primaryView !== 'raw') ? 'active' : ''} onClick={() => id === 'raw' ? selectView('raw') : (setMapMode(id), primaryView === 'raw' && selectView('detector'))}>{label}</button>)}</div>
      <div className='context-meta'><span className={`source-health-inline ${sourceHealth.tone}`} title={sourceHealth.detail}>{sourceHealth.label}</span><i /><span role='status'>{tccStatus}</span><i /><span>{sourceHealth.adviceAllowed ? '策略门禁可研判' : '策略门禁已阻断'}</span></div>
    </section>

    <div className={`main-feed-status ${primaryView} ${leftPanelOpen || leftPanelPinned ? '' : 'side-collapsed'}`}>{mainIsVideo ? <VideoCamera size={14} weight='fill' /> : <Crosshair size={14} weight='fill' />}<span>{primaryView === 'bev' ? (streamActive ? 'BEV 鸟瞰轨迹 · ENU / GCJ02' : 'BEV 实时轨迹投放 · 等待 Pipeline') : primaryView === 'raw' ? '原始视频流' : '检测器输出 · YOLO11 → 位姿感知 ByteTrack'}</span><small><i />{streamActive ? ` LIVE · ${displayNumber(fps, 1)} FPS` : ' OFFLINE'}</small></div>

    <section
      className={`left-panel monitoring-side-panel ${leftPanelOpen || leftPanelPinned ? 'expanded' : 'collapsed'} ${leftPanelPinned ? 'pinned' : ''}`}
      aria-label='实时态势面板'
      data-state={leftPanelOpen || leftPanelPinned ? 'expanded' : 'collapsed'}
      data-transparency='40'
      onMouseEnter={() => setLeftPanelOpen(true)}
      onMouseLeave={() => { if (!leftPanelPinned) setLeftPanelOpen(false) }}
      onFocusCapture={() => setLeftPanelOpen(true)}
      onBlurCapture={(event) => { if (!leftPanelPinned && !event.currentTarget.contains(event.relatedTarget)) setLeftPanelOpen(false) }}
    >
      <button className='side-panel-edge' aria-label={leftPanelOpen || leftPanelPinned ? '收缩实时态势面板' : '展开实时态势面板'} onClick={() => { setLeftPanelPinned(false); setLeftPanelOpen((value) => !value) }}>{leftPanelOpen || leftPanelPinned ? <CaretLeft size={17} /> : <CaretRight size={17} />}</button>
      {(leftPanelOpen || leftPanelPinned) && <button className='side-panel-pin' aria-label={leftPanelPinned ? '取消锁定实时态势面板' : '锁定实时态势面板'} aria-pressed={leftPanelPinned} onClick={() => { setLeftPanelPinned((value) => !value); setLeftPanelOpen(true) }}>{leftPanelPinned ? <PushPinSlash size={16} /> : <PushPin size={16} />}</button>}
      <div className='panel-heading'><div><span>实时态势</span><small>{lastStatsAt ? eventTime(lastStatsAt) : replaySnapshot ? '原始视频回放快照' : usingDemoMetrics ? '固定演示快照' : '暂无统计数据'}</small></div></div>
      <div className='left-panel-scroll'>
      <article className={`source-health-card ${sourceHealth.tone}`} aria-label='实时来源健康状态'>
        <header><div><Clock size={15} weight='fill' /><strong>来源健康</strong></div><span>{sourceHealth.label}</span></header>
        <p>{sourceHealth.detail}</p>
        <span className='source-link-state'>{realtimeStatus}</span>
        <small>{sourceHealth.adviceAllowed ? '实时证据可进入场景研判' : '当前不形成在线策略候选'}</small>
      </article>
      <article className='demo-mission-control'>
        <header><div><Drone size={15} weight='fill' /><strong>无人机调度</strong></div><span>{missionMode === 'review' ? '治理后复盘' : missionMode === 'cruise' ? '路段航拍' : '路口悬停'}</span></header>
        <div role='group' aria-label='无人机演示任务'>{[['hover', '路口悬停'], ['cruise', '路段航拍'], ['review', '治理复盘']].map(([id, label]) => <button key={id} className={missionMode === id ? 'active' : ''} onClick={() => activateMissionMode(id)}>{label}</button>)}</div>
        <small>{missionMode === 'cruise' ? '沿重点路段巡航，观察流量与排队变化' : missionMode === 'review' ? '复用同一指标口径，对比治理前后效果' : '保持路口正拍，诊断相位饱和度与机非冲突'} · 最高饱和度 {displayNumber(maxSaturation, 2)}</small>
      </article>
      <article className='congestion-card'><div className='score-ring'><strong>{displayNumber(realtimeTrajectoryCount)}</strong><small>条</small></div><div className='score-copy'><span>实时轨迹数量</span><strong>{realtimeTrajectoryCount == null ? '暂无实时数据' : `活动轨迹 · 已完成 ${completedTrajectories.length}`}</strong><small><TrendUp size={13} />{usingDemoMetrics ? '固定演示快照' : replaySnapshot ? '原始视频回放' : statsStale ? '实时数据已过期' : '实时更新'}</small></div><Crosshair size={24} weight='duotone' /></article>
      <div className='metrics-grid'><MetricCard icon={Target} label='当前目标' value={displayNumber(cars)} unit='辆' delta='' /><MetricCard icon={ListBullets} label='最长排队' value={queueMetricMode === 'unavailable' ? '等待数据' : displayNumber(longestQueue)} unit={queueMetricMode === 'unavailable' ? '' : 'm'} delta={queueMetricMode === 'direction-estimate' ? '方向估算' : ''} tone='amber' title={queueMetricMode === 'formal' ? '正式道路指标已开启' : queueMetricMode === 'direction-estimate' ? '无 lane_verified 路网；按 AutoLane 物理方向输出降级排队估算' : '当前没有可用排队观测'} /><MetricCard icon={Gauge} label='平均车速' value={displayNumber(avgSpeed, 1)} unit='km/h' delta='' tone='cyan' /><MetricCard icon={ShieldWarning} label='待复核风险' value={usingDemoMetrics ? String(displayedEvents.length) : String(riskSummary.pending)} unit='起' delta={usingDemoMetrics ? '演示' : `${riskSummary.triggers}触发/${riskSummary.episodes}事件`} tone='red' /></div>
      <article className='movement-flow-panel' aria-label='按方向实时流量'>
        <header><div><strong>实时流向</strong><small>{movementPanel.periodLabel}</small></div><span className={movementPanel.source}>{movementPanel.source === 'realtime' ? (statsStale ? 'REST 快照' : '实时统计') : movementPanel.source === 'observed' ? (movementPanel.queueMode === 'direction-estimate' ? '降级观测' : statsStale ? '观测快照' : '实时观测') : movementPanel.source === 'trajectory' ? '轨迹推断' : movementPanel.source === 'mock' ? 'Mock 接口' : '等待数据'}</span></header>
        <div className='movement-flow-head' aria-hidden='true'><span>流向</span><span>{movementPanel.source === 'trajectory' ? '轨迹数' : '流量'}</span><span>均速</span><span>排队</span><span>饱和度</span></div>
        <ol className='movement-flow-list'>
          {movementPanel.rows.map((movement, index) => <li key={movement.id} aria-label={`${movement.approach}到${movement.exit}`}>
            <b>{index + 1}</b>
            <div className='movement-name'><span>{movement.approach}</span><ArrowRight size={10} weight='bold' aria-hidden='true' /><span>{movement.exit}</span></div>
            <strong>{displayNumber(movement.flow, movementPanel.source === 'observed' ? 1 : 0)}</strong>
            <span>{displayNumber(movement.speed, movementPanel.source === 'observed' ? 1 : 0)}<small>km/h</small></span>
            <span title={movementPanel.queueMode === 'direction-estimate' ? 'AutoLane 按物理方向聚合的降级排队估算' : undefined}>{movement.queue != null ? <>{displayNumber(movement.queue)}<small>m</small></> : '等待数据'}</span>
            <span className={(movement.saturation ?? 0) > .9 ? 'warning' : ''} title={formalRoadMetricsAvailable ? undefined : '饱和度仍需 lane_verified 路网'}>{formalRoadMetricsAvailable ? displayNumber(movement.saturation, 2) : '未标定'}</span>
          </li>)}
        </ol>
        {!movementPanel.rows.length && <div className='monitor-empty'>当前 Pipeline 暂无可用方向流量</div>}
      </article>
      <article className='glass-card trend-card'><div className='card-title'><div><strong>态势趋势</strong><small>{trendWindowLabel}</small></div><span className='chip'>{usingDemoMetrics ? '固定 5m' : 'REST 5m'}</span></div><div className='chart-box'>{trendData.length ? <ResponsiveContainer width='100%' height='100%'><AreaChart data={trendData} margin={{ top: 8, right: 4, left: -28, bottom: 0 }}><CartesianGrid vertical={false} stroke='rgba(151,171,206,.12)' /><XAxis dataKey='time' tick={{ fill: '#8290aa', fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis tick={{ fill: '#8290aa', fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip contentStyle={{ background: '#111a2a', border: '1px solid #33415b', borderRadius: 8, fontSize: 11 }} /><Area type='monotone' dataKey='value' stroke='#62a1ff' fill='#294c7b' fillOpacity={0.36} strokeWidth={2} /></AreaChart></ResponsiveContainer> : <div className='monitor-empty'>暂无态势数据</div>}</div></article>
      <article className='glass-card flow-card'><div className='card-title'><div><strong>转向流量</strong><small>{trendWindowLabel}{usingDemoMetrics ? '演示统计' : '真实统计'}</small></div><div className='legend'><span className='straight'>直行</span><span className='left'>左转</span><span className='right'>右转</span></div></div><div className='chart-box small'>{flowData.length ? <ResponsiveContainer width='100%' height='100%'><BarChart data={flowData} margin={{ top: 4, right: 0, left: -34, bottom: 0 }}><XAxis dataKey='time' tick={{ fill: '#8290aa', fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis tick={{ fill: '#8290aa', fontSize: 10 }} axisLine={false} tickLine={false} /><Bar dataKey='straight' fill='#6d9eff' radius={[2,2,0,0]} /><Bar dataKey='left' fill='#c98cf4' radius={[2,2,0,0]} /><Bar dataKey='right' fill='#5fd2a5' radius={[2,2,0,0]} /></BarChart></ResponsiveContainer> : <div className='monitor-empty'>暂无转向流量</div>}</div></article>
      <details className='engineering-diagnostics'>
        <summary>工程诊断 <span>展开查看</span></summary>
        <div className='engineering-diagnostic-grid'>
          <span>消息接收 <b>{sourceHealth.diagnostics.receiptAgeSec == null ? '—' : `${Math.round(sourceHealth.diagnostics.receiptAgeSec)}s`}</b></span>
          <span>端到端 <b>{endToEndLatencyMs == null ? '—' : `${Math.round(endToEndLatencyMs)}ms`}</b></span>
          <span>Pipeline <b>{pipelineProcessingMs == null ? '—' : `${pipelineProcessingMs}ms`}</b></span>
          <span>源丢帧 <b>{sourceDropCount == null ? '—' : sourceDropCount}</b></span>
          <span>WebSocket <b>{wsStatus}</b></span>
        </div>
        <p>YOLO 单处理帧 {inferenceMs ?? '—'}ms{inferenceImgSize ? ` · ${inferenceImgSize}` : ''}</p>
      <article className={`flight-quality-card ${flightQuality.tone}`} aria-label='巡航与悬停融合质量状态'>
        <header><div><Drone size={15} weight='fill' /><strong>{flightQuality.phaseLabel}</strong></div><span>{flightQuality.formalLabel}</span></header>
        <div className='flight-quality-grid'>{flightQuality.qualities.map((item) => <span key={item.label} className={item.status}><small>{item.label}</small><strong>{item.value}</strong></span>)}</div>
        {flightQuality.trajectoryOutput === true && flightQuality.roadAnalytics === false && <div className='candidate-only-notice'><strong>轨迹已输出，路网匹配降级</strong><small>Lane ID、Link ID 与匹配质量不可用；世界坐标、速度、方向、统计和 TCC 使用各自独立门禁{flightQuality.reasonLabels.length ? ` · ${flightQuality.reasonLabels.join('；')}` : ''}</small></div>}
        {flightQuality.trajectoryOutput !== true && flightQuality.formal === false && <div className='candidate-only-notice'><strong>目标轨迹暂不可用</strong><small>{flightQuality.reasonLabels.join('；') || '等待检测关联'}{candidateTrajectories.length ? ` · 兼容候选轨迹 ${candidateTrajectories.length} 条` : ''}</small></div>}
        <footer title={`终止原因 ${flightQuality.terminationReason}`}>关联 {flightQuality.method} · 终止 {flightQuality.terminationReason}</footer>
      </article>
      </details>
      </div>
    </section>

    {primaryView === 'detector' && mapMode === 'risk' && selectedEvent?.type === 'conflict' && <section className='map-overlay' aria-label='风险事件图层'><div className='risk-marker'><ShieldWarning size={16} weight='fill' /><span>高风险交汇</span><strong>TTC {selectedRaw.ttc_sec ?? '—'}s</strong></div></section>}
    <div className={`map-tools ${rightPanelOpen || rightPanelPinned ? '' : 'side-collapsed'}`}><button onClick={() => setDroneOpen(!droneOpen)} className={droneOpen ? 'active' : ''} aria-label='无人机状态'><Drone size={19} /></button><button onClick={() => setLayerOpen(!layerOpen)} className={layerOpen ? 'active' : ''} aria-label='图层'><Stack size={19} /></button><button aria-label='放大'><Plus size={19} /></button><button aria-label='定位'><Crosshair size={19} /></button></div>
    {droneOpen && <div className={`floating-popover drone-popover ${rightPanelOpen || rightPanelPinned ? '' : 'side-collapsed'}`}><div><strong>{droneId || '未绑定无人机'}</strong><span className={telemetryStale ? '' : 'online'}>{telemetryStale ? '遥测过期' : '在线'}</span></div><dl><dt>高度</dt><dd>{displayNumber(height, 1)} m</dd><dt>电量</dt><dd>{displayNumber(asNumber(attitude.battery_percent ?? attitude.battery_pct))}%</dd><dt>卫星</dt><dd>{displayNumber(asNumber(attitude.satellites ?? attitude.gps_satellites))}</dd><dt>模式</dt><dd>{attitude.is_hovering ? '悬停' : '巡飞'}</dd></dl></div>}
    {layerOpen && <div className={`floating-popover layer-popover ${rightPanelOpen || rightPanelPinned ? '' : 'side-collapsed'}`}>{[['活动轨迹','trajectory'],['风险事件','risk'],['车道拓扑','lane']].map(([label,id]) => <label key={id}><input type='radio' name='map-layer' checked={mapMode === id} onChange={() => setMapMode(id)} /><span>{label}</span></label>)}</div>}

    <section
      className={`right-panel monitoring-side-panel ${rightPanelOpen || rightPanelPinned ? 'expanded' : 'collapsed'} ${rightPanelPinned ? 'pinned' : ''}`}
      aria-label='BEV 与实时事件面板'
      data-state={rightPanelOpen || rightPanelPinned ? 'expanded' : 'collapsed'}
      data-transparency='40'
      onMouseEnter={() => setRightPanelOpen(true)}
      onMouseLeave={() => { if (!rightPanelPinned) setRightPanelOpen(false) }}
      onFocusCapture={() => setRightPanelOpen(true)}
      onBlurCapture={(event) => { if (!rightPanelPinned && !event.currentTarget.contains(event.relatedTarget)) setRightPanelOpen(false) }}
    >
      <button className='side-panel-edge' aria-label={rightPanelOpen || rightPanelPinned ? '收缩BEV与实时事件面板' : '展开BEV与实时事件面板'} onClick={() => { setRightPanelPinned(false); setRightPanelOpen((value) => !value) }}>{rightPanelOpen || rightPanelPinned ? <CaretRight size={17} /> : <CaretLeft size={17} />}</button>
      {(rightPanelOpen || rightPanelPinned) && <button className='side-panel-pin' aria-label={rightPanelPinned ? '取消锁定BEV与实时事件面板' : '锁定BEV与实时事件面板'} aria-pressed={rightPanelPinned} onClick={() => { setRightPanelPinned((value) => !value); setRightPanelOpen(true) }}>{rightPanelPinned ? <PushPinSlash size={16} /> : <PushPin size={16} />}</button>}
      <article className='camera-card'><div className='camera-head'><span>{primaryView === 'bev' ? <VideoCamera size={16} weight='fill' /> : <Crosshair size={16} weight='fill' />}{primaryView === 'bev' ? '检测器输出' : eventFocusActive ? '事件参与轨迹聚焦' : 'BEV 轨迹投放'}</span><small><i />{primaryView === 'bev' ? `${displayNumber(fps, 1)} FPS` : `${worldTrajectories.length || drawablePixelTrajectoryCount} TRACKS`}</small></div>{primaryView === 'bev' ? <div className='detector-preview'>{streamActive && videoStreamAvailable && !videoError ? <img ref={videoRef} src={mjpegSrc} alt='检测器输出视频流预览' onLoad={() => { setVideoError(false); setVideoRetry(0) }} onError={() => setVideoError(true)} /> : <div className='monitor-empty'>{streamActive && !videoStreamAvailable ? '检测器未登记直连地址' : '检测流不可用'}</div>}</div> : <div className='bev-preview'><MonitoringBevMap compact centerLat={mapCenterLat} centerLon={mapCenterLon} trajectories={worldTrajectories} pixelTrajectories={displayPixelTrajectories} activeCount={streamActive ? activeTrajectories.length : 0} emptyMessage={bevEmptyMessage} label={worldTrajectories.length || !drawablePixelTrajectoryCount ? 'BEV 地图轨迹投放图' : '像素坐标实时轨迹投放图'} /><span className='bev-origin'><Crosshair size={13} weight='bold' /> {worldTrajectories.length ? 'ENU 0,0' : drawablePixelTrajectoryCount ? 'PIXEL' : '—'}</span></div>}<div className='camera-foot'><span>{primaryView === 'bev' ? (streamActive && videoStreamAvailable ? '检测器直连输出' : '检测器离线') : streamActive ? eventFocusActive ? `聚焦轨迹 ${[...focusedTrackIds].join(' / ')}` : worldTrajectories.length ? `空间轨迹 ${worldTrajectories.length} · GCJ-02 投放` : bevEmptyMessage : '等待实时 Pipeline 轨迹'}</span><button className='swap-view' onClick={() => selectView(primaryView === 'bev' ? 'detector' : 'bev')}><ArrowsClockwise size={14} weight='bold' />切为主视图</button></div></article>
      <div className='right-workspace-tabs' role='tablist' aria-label='右侧分析工作区'>
        <button role='tab' aria-selected={rightWorkspaceTab === 'strategy'} className={rightWorkspaceTab === 'strategy' ? 'active' : ''} onClick={() => selectRightWorkspaceTab('strategy')}>场景策略</button>
        <button role='tab' aria-selected={rightWorkspaceTab === 'events'} className={rightWorkspaceTab === 'events' ? 'active' : ''} onClick={() => selectRightWorkspaceTab('events')}>近期事件 <span>{displayedEvents.length}</span></button>
      </div>
      {rightWorkspaceTab === 'strategy' ? <article className='scenario-strategy-panel' role='tabpanel' aria-label='场景策略'>
        <header><div><strong>场景研判</strong><small>按证据完备度排序</small></div></header>
        <div className='scenario-selector' role='group' aria-label='重点业务场景'>{scenarioAssessments.map((scenario) => <button key={scenario.id} className={`${selectedScenario.id === scenario.id ? 'active' : ''} ${scenario.status}`} aria-label={scenario.label} aria-pressed={selectedScenario.id === scenario.id} onClick={() => setSelectedScenarioId(scenario.id)}><span>{scenario.label}</span>{scenario.status !== 'testing' && <small>{scenario.statusLabel}</small>}</button>)}</div>
        <div className='scenario-brief'>
          <div><span>{selectedScenario.domain}</span><strong>{selectedScenario.objective}</strong></div>
          <p><b>适用：</b>{selectedScenario.useCase}</p>
        </div>
        <section className='scenario-current'>
          <header><strong>当前研判</strong><span className={scenarioEvidenceMode}>{selectedScenario.status === 'testing' ? '不形成在线建议' : selectedScenario.statusLabel}</span></header>
          <ul>{scenarioEvidence.map((item) => <li key={item}>{item}</li>)}</ul>
        </section>
        <div key={selectedScenario.id} className='scenario-detail-scroll'>
          <section className='scenario-block'>
            <header><strong>触发判据</strong><small>需同时校核，不以单指标下发</small></header>
            <ul className='scenario-rules'>{selectedScenario.triggerRules.map((rule) => <li key={rule.metric}><span>{rule.metric}</span><div><strong>{rule.rule}</strong><small>数据：{rule.source}</small></div></li>)}</ul>
          </section>
          <section className='scenario-block'>
            <header><strong>处置链</strong><small>建议顺序</small></header>
            <ol>{selectedScenario.actions.map((item) => <li key={item}>{item}</li>)}</ol>
          </section>
          <section className='scenario-block guardrail'>
            <header><strong>控制边界</strong><small>任一不满足即转人工</small></header>
            <ul>{selectedScenario.guardrails.map((item) => <li key={item}>{item}</li>)}</ul>
          </section>
          <section className='scenario-block scenario-review'>
            <header><strong>退出与复盘</strong></header>
            <p>{selectedScenario.exitRule}</p>
            <div>{selectedScenario.reviewMetrics.map((item) => <span key={item}>{item}</span>)}</div>
          </section>
        </div>
        <footer><div><small>能力边界</small><strong>仅生成建议，不自动下发</strong></div><div><small>审批与下发</small><span>交警 / 信控平台确认</span></div></footer>
      </article> : <div className='events-workspace' role='tabpanel' aria-label='近期事件'>
        <div className='events-head'><div><strong>风险事件</strong><span>{displayedEvents.length}</span></div><button aria-label='全部事件' onClick={() => navigate(monitoringEventCenterUrl({ intersectionId: selectedId, sourceProfileId: selectedSource?.profile_id, event: eventCenterEvent }))}><ListBullets size={16} />事件台账</button></div>
        {!usingDemoMetrics && <div className='risk-summary' aria-label='风险事件统计'><span><small>触发</small><b>{riskSummary.triggers}</b></span><span><small>事件</small><b>{riskSummary.episodes}</b></span><span><small>已复核</small><b>{riskSummary.reviewed}</b></span><span className={riskSummary.pending ? 'pending' : ''}><small>待复核</small><b>{riskSummary.pending}</b></span></div>}
        <div className='event-filters'>{[['all','全部'],['critical','高风险'],['warning','关注']].map(([id,label]) => <button key={id} className={eventFilter === id ? 'active' : ''} onClick={() => setEventFilter(id)}>{label}</button>)}</div>
        <div className='event-list'>{filteredEvents.length ? filteredEvents.map((event) => <button key={event.id} className={`event-card ${event.level} ${selectedEvent?.id === event.id ? 'selected' : ''}`} onClick={() => selectMonitoringEvent(event)}><span className='event-icon'><EventIcon type={event.type} /></span><span className='event-copy'><strong>{event.title}</strong><small>{event.detail}</small><span>{event.metric}</span></span><span className={`event-review-status ${event.reviewStatus || 'pending'}`}>{event.reviewLabel || (event.reviewStatus === 'confirmed' ? '已确认' : event.reviewStatus === 'rejected' ? '已驳回' : '待复核')}</span><time>{event.time}</time></button>) : <div className='monitor-empty'>当前视频源暂无近期事件</div>}</div>
        {selectedPersistentEvent && <section className='monitoring-event-detail' aria-label='事件证据与复核'>
          <header><div><strong>证据与复核</strong><small>轨迹 {selectedPersistentEvent.motorId ?? '—'} / {selectedPersistentEvent.nonMotorId ?? '—'}</small></div><span className={selectedReviewStatus}>{selectedReviewStatus === 'confirmed' ? '已确认' : selectedReviewStatus === 'rejected' ? '已驳回' : '待复核'}</span></header>
          {selectedEvidenceRefs.length ? <div className='monitoring-evidence-grid'>{selectedEvidenceRefs.slice(0, 3).map((reference) => <MonitoringEvidenceThumb key={reference.id || reference.kind} reference={reference} />)}</div> : <div className='evidence-empty'>当前事件没有可复核画面证据，不据此形成控制建议</div>}
          {eventReviewError && <p className='event-review-error' role='alert'>{eventReviewError}</p>}
          {eventSurveyError && <p className='event-review-error' role='alert'>{eventSurveyError}</p>}
          <div className='event-review-actions'>
            <button disabled={!reviewAllowed || eventReviewMutation.isPending} onClick={() => eventReviewMutation.mutate('rejected')}><X size={14} />驳回</button>
            <button disabled={!reviewAllowed || eventReviewMutation.isPending} onClick={() => eventReviewMutation.mutate('confirmed')}><Check size={14} />技术确认</button>
            <button disabled={!eventSurveyAllowed || eventSurveyMutation.isPending} onClick={() => eventSurveyMutation.mutate()}><Crosshair size={14} />建立证据复核任务</button>
            <button onClick={() => navigate(monitoringEventCenterUrl({ intersectionId: selectedId, sourceProfileId: selectedSource?.profile_id, event: selectedPersistentEvent }))}><ListBullets size={14} />完整证据</button>
          </div>
          {!reviewAllowed && <small className='review-boundary'>{eventDetailQuery.isLoading ? '正在加载事件台账 revision…' : eventDetail?.review_supported === false ? '该历史事实只读' : platformRole !== 'admin' ? '仅管理员可执行技术复核' : '请在事件台账补齐可复核 revision'}</small>}
          {!eventSurveyAllowed && hasReusableEventFrame && <small className='review-boundary'>实时无人机事件的治理工单需由外部警务 / 信控平台承接；本地证据复核任务仅用于开发验证</small>}
        </section>}
        <div className='monitoring-event-actions'><button className={savedSnapshotId ? 'saved' : ''} disabled={snapshotPreparing} onClick={saveDemoSnapshot}>{snapshotPreparing ? '正在准备快照…' : savedSnapshotId ? '重新保存当前快照' : '保存事件与流量快照'}</button><button onClick={() => navigate('/events')}>事件治理台账</button>{savedSnapshotId && <button className='snapshot-link' onClick={() => navigate(`/events?snapshot_id=${encodeURIComponent(savedSnapshotId)}`)}>查看已保存快照</button>}</div>
      </div>}
    </section>

  </ConsoleFrame>
}
