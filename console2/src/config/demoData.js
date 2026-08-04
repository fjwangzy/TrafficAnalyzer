// 本机普通模式固定演示快照：不按演示场次生成，不写数据库。
export const demoSituation = {
  asOf: '10:55:28',
  focusIntersectionId: '370102000101',
  kpis: [
    { id: 'network', label: '监测路口', value: 18, unit: '处', detail: '重点保障 8 处', tone: 'blue' },
    { id: 'oversaturated', label: '过饱和路口', value: 3, unit: '处', detail: '饱和度 > 0.95', tone: 'red' },
    { id: 'uav', label: '无人机覆盖', value: 4, unit: '处', detail: '在线 3 · 待命 1', tone: 'cyan' },
    { id: 'conflict', label: '机非冲突', value: 2, unit: '起', detail: '1 起高风险待复核', tone: 'amber' },
    { id: 'efficiency', label: '治理提升', value: 31, unit: '%', detail: '重点路口通行效率', tone: 'green' },
  ],
  story: [
    { id: 1, label: '发现态势', caption: '全域路口与路段' },
    { id: 2, label: '调度无人机', caption: '悬停或路段航拍' },
    { id: 3, label: '识别事件', caption: '机非冲突与事故测绘' },
    { id: 4, label: '保存快照', caption: '事件与交通流留档' },
    { id: 5, label: '治理复盘', caption: '前后对比再调度' },
  ],
  focusIntersections: [
    { id: '370102000101', name: '小清河北路 × 水屯路', saturation: 0.98, status: 'oversaturated', queue: 186, drone: 'UAV-M300-01', note: '南进口直行过饱和' },
    { id: '370102000102', name: '经十路 × 奥体西路', saturation: 0.91, status: 'near_saturated', queue: 124, drone: 'UAV-M350-02', note: '东进口左转接近饱和' },
    { id: '370102000104', name: '旅游路 × 舜华南路', saturation: 0.82, status: 'good', queue: 78, drone: 'UAV-M300-03', note: '运行良好，遥测降级' },
  ],
  mapPoints: [
    { id: 'SRC-DEMO-XQH', source_profile_id: 'SRC-DEMO-XQH', intersection_id: '370102000101', drone_id: 'UAV-M300-01', name: '路口悬停源', drone_name: 'UAV-M300-01', intersection_name: '小清河北路 × 水屯路', lat: 36.7148, lon: 117.0717, source_status: 'running' },
    { id: 'SRC-DEMO-JS', source_profile_id: 'SRC-DEMO-JS', intersection_id: '370102000102', drone_id: 'UAV-M350-02', name: '路段航拍源', drone_name: 'UAV-M350-02', intersection_name: '经十路 × 奥体西路', lat: 36.6529, lon: 117.1182, source_status: 'ready' },
    { id: 'SRC-DEMO-LY', source_profile_id: 'SRC-DEMO-LY', intersection_id: '370102000104', drone_id: 'UAV-M300-03', name: '路口保障源', drone_name: 'UAV-M300-03', intersection_name: '旅游路 × 舜华南路', lat: 36.6281, lon: 117.1131, source_status: 'degraded' },
  ],
  events: [
    { id: 'UAV-EVT-20260713-001', title: '机非冲突风险升高', metric: 'TTC 1.2s · PET 0.8s', time: '10:52:16', tone: 'critical', route: '/events?event_id=UAV-EVT-20260713-001' },
    { id: 'SVY-20260713-006', title: '轻微事故等待测绘', metric: '覆盖 93.8% · 待采集', time: '10:49:02', tone: 'warning', route: '/survey' },
  ],
  comparison: [
    { label: '路口饱和度', before: '0.98', after: '0.76', delta: '-22%' },
    { label: '最长排队', before: '186m', after: '74m', delta: '-60%' },
    { label: '平均车速', before: '18.6', after: '31.4 km/h', delta: '+69%' },
    { label: '机非冲突', before: '6 起', after: '2 起', delta: '-67%' },
  ],
}

export const demoMonitoring = {
  source: {
    profile_id: 'SRC-DEMO-XQH', display_name: '小清河北路路口固定演示源', drone_id: 'UAV-M300-01',
    enabled: true, validation_status: 'valid', intersectionId: '370102000101', intersectionName: '小清河北路 × 水屯路',
    optionLabel: '小清河北路固定演示源 · UAV-M300-01', isDefault: true,
  },
  telemetry: {
    drone_id: 'UAV-M300-01', height: 118.6, altitude_agl: 118.6, heading: 36.2, attitude_pitch: -89.1,
    attitude_roll: 0.4, gimbal_mode: '锁定', is_hovering: true, battery_pct: 78, satellites: 21,
    position_gcj02: { latitude: 36.7148, longitude: 117.0717 },
  },
  stats: {
    cars: 68, avg_speed_kmh: 18.6, fps: 24.8, inference_ms: 38, flight_phase: 'hover_verified',
    trajectory_output_eligible: true, formal_analytics_eligible: true, geo_analytics_eligible: true,
    road_analytics_eligible: true, tcc_analytics_eligible: true,
    geo_reference_quality: {
      status: 'verified', flight_phase: 'hover_verified', reasons: [], telemetry: { status: 'verified' },
      visual_warp: { status: 'verified' }, map_coverage: { status: 'verified' },
    },
    tracking_diagnostics: { tracking_quality: 'verified', tracking_method: 'ByteTrack', termination_reason: 'active', quality_reasons: [] },
    tcc_diagnostics: { enabled: true, status: 'event_emitted', calibration_valid: true, business_events_emitted: 2 },
    lane_stats: [
      { lane: '南进口直行', queue_length_m: 186, saturation: 1.04, green_utilization: 0.96 },
      { lane: '东进口左转', queue_length_m: 124, saturation: 0.91, green_utilization: 0.89 },
      { lane: '北进口直行', queue_length_m: 86, saturation: 0.82, green_utilization: 0.76 },
    ],
  },
  trend: [
    { time: '10:30', congestion_index: 5.8, saturation: 0.82, cars: 48, direction_flow: { straight: 31, left_turn: 11, right_turn: 6 } },
    { time: '10:35', congestion_index: 6.2, saturation: 0.87, cars: 52, direction_flow: { straight: 34, left_turn: 12, right_turn: 6 } },
    { time: '10:40', congestion_index: 6.6, saturation: 0.91, cars: 57, direction_flow: { straight: 38, left_turn: 13, right_turn: 6 } },
    { time: '10:45', congestion_index: 7.0, saturation: 0.95, cars: 61, direction_flow: { straight: 41, left_turn: 14, right_turn: 6 } },
    { time: '10:50', congestion_index: 7.2, saturation: 0.98, cars: 65, direction_flow: { straight: 44, left_turn: 15, right_turn: 6 } },
    { time: '10:55', congestion_index: 7.4, saturation: 1.04, cars: 68, direction_flow: { straight: 46, left_turn: 16, right_turn: 6 } },
  ],
  events: [
    { id: 'UAV-EVT-20260713-001', level: 'critical', type: 'conflict', title: '机非冲突风险升高', detail: '机动车 128 与非机动车 46 预测交汇', metric: 'TTC 1.2s · PET 0.8s', time: '10:52:16', raw: { ttc_sec: 1.2, pet_sec: 0.8, risk_score: 86 } },
    { id: 'UAV-EVT-20260713-003', level: 'warning', type: 'congestion', title: '南进口排队增长', detail: '排队长度超过 180m，持续 8 分钟', metric: '186m · +24%', time: '10:45:37', raw: { queue_length_m: 186 } },
  ],
}
