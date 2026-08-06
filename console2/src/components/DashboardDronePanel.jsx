import { useEffect, useState } from 'react'
import {
  ArrowSquareOut,
  BatteryHigh,
  Compass,
  Crosshair,
  Drone,
  Gauge,
  ListBullets,
  MapPin,
  NavigationArrow,
  ShieldWarning,
  VideoCamera,
  X,
} from '@phosphor-icons/react'
import { detectorVideoStreamSrc } from '../lib/videoStream'

function displayValue(value, digits = 0, suffix = '') {
  const number = Number(value)
  return Number.isFinite(number) ? `${number.toFixed(digits)}${suffix}` : '—'
}

function positionLabel(drone) {
  const lon = Number(drone?.lon)
  const lat = Number(drone?.lat)
  return Number.isFinite(lon) && Number.isFinite(lat) ? `${lon.toFixed(6)}, ${lat.toFixed(6)}` : '—'
}

const flightMetrics = [
  { key: 'battery_pct', label: '电量', icon: BatteryHigh, digits: 0, suffix: '%' },
  { key: 'altitude_m', label: '相对高度', icon: NavigationArrow, digits: 1, suffix: 'm' },
  { key: 'speed_mps', label: '地速', icon: Gauge, digits: 1, suffix: 'm/s' },
  { key: 'heading_deg', label: '航向', icon: Compass, digits: 1, suffix: '°' },
]

const realtimeMetrics = [
  { key: 'vehicles', label: '当前目标', icon: Crosshair, digits: 0, suffix: '辆' },
  { key: 'longestQueueM', label: '最长排队', icon: ListBullets, digits: 0, suffix: 'm', tone: 'amber' },
  { key: 'avgSpeedKmh', label: '平均车速', icon: Gauge, digits: 1, suffix: 'km/h', tone: 'cyan' },
  { key: 'tccEvents', label: '机非事件', icon: ShieldWarning, digits: 0, suffix: '起', tone: 'red' },
]

export function DashboardDronePanel({ drone, stats, statsSource, statsError, socketStatus, onClose, onOpenMonitoring }) {
  const [videoError, setVideoError] = useState(false)
  const streamUrl = detectorVideoStreamSrc({ video_stream_url: drone?.video_stream_url })

  useEffect(() => setVideoError(false), [drone?.id, drone?.pipeline_id, streamUrl])

  if (!drone) return null

  const streamLabel = !drone.is_monitoring
    ? '当前未启动检测任务'
    : !streamUrl
      ? 'Pipeline 未登记浏览器可达视频地址'
      : videoError
        ? '飞行窗口连接失败'
        : ''
  const realtimeAvailable = Boolean(drone.is_monitoring && stats && Object.values(stats).some((value) => Number.isFinite(value)))

  return <aside className='dashboard-drone-panel' aria-label='无人机飞行详情'>
    <header className='dashboard-drone-heading'>
      <span><Drone size={18} weight='fill' /></span>
      <div>
        <strong>{drone.name || drone.drone_id}</strong>
        <small>{drone.location_name || drone.intersection_name || '未绑定任务区域'}</small>
      </div>
      <i className={drone.is_monitoring ? 'live' : ''}>{drone.status_label || '状态未知'}</i>
      <button type='button' aria-label='关闭无人机详情' onClick={onClose}><X size={17} /></button>
    </header>

    <section className='dashboard-drone-video' aria-label='无人机飞行窗口'>
      <div className='dashboard-drone-section-title'><span><VideoCamera size={15} weight='fill' />无人机飞行窗口</span>{drone.is_monitoring && <small><i />LIVE</small>}</div>
      {streamUrl && !videoError
        ? <img src={streamUrl} alt={`${drone.name || drone.drone_id} 无人机飞行窗口`} onError={() => setVideoError(true)} />
        : <div className='dashboard-drone-video-empty'><VideoCamera size={28} /><strong>{streamLabel}</strong><span>{drone.is_monitoring ? '检测任务仍可继续；请检查视频流登记或连接状态。' : '飞行数据保留最后真实遥测，不使用演示画面补齐。'}</span></div>}
    </section>

    <section className='dashboard-drone-section'>
      <div className='dashboard-drone-section-title'><span>飞行数据</span><small className={drone.telemetry_fresh ? 'fresh' : ''}>{drone.telemetry_note || '暂无遥测'}</small></div>
      <div className='dashboard-flight-metrics'>{flightMetrics.map(({ key, label, icon: Icon, digits, suffix }) => <article key={key}>
        <Icon size={15} weight='duotone' />
        <span>{label}</span>
        <strong>{displayValue(drone[key], digits, suffix)}</strong>
      </article>)}</div>
      <div className='dashboard-drone-position'><MapPin size={14} weight='fill' /><span>GCJ-02 位置</span><strong>{positionLabel(drone)}</strong></div>
    </section>

    <section className='dashboard-drone-section'>
      <div className='dashboard-drone-section-title'><span>核心实时指标</span><small className={statsSource === '实时推送' ? 'fresh' : ''}>{statsSource}</small></div>
      {realtimeAvailable
        ? <div className='dashboard-realtime-metrics'>{realtimeMetrics.map(({ key, label, icon: Icon, digits, suffix, tone = '' }) => <article className={tone} key={key}>
          <Icon size={15} weight='duotone' />
          <span>{label}</span>
          <strong>{displayValue(stats[key], digits, suffix)}</strong>
        </article>)}</div>
        : <div className='dashboard-realtime-empty' role='status'><Crosshair size={23} /><strong>{statsError ? '实时指标读取失败' : '暂无核心实时指标'}</strong><span>{drone.is_monitoring ? `等待当前 Pipeline 的统计数据 · ${socketStatus === 'connected' ? '实时链路已连接' : 'REST 轮询保底'}` : '当前无人机未运行检测任务，不展示历史样本冒充实时数据。'}</span></div>}
    </section>

    <footer className='dashboard-drone-actions'>
      <span>{drone.scene_label || '无人机任务'} · {drone.source_profile_id || '未绑定视频源'}</span>
      <button type='button' disabled={!drone.can_open_monitoring} onClick={() => onOpenMonitoring(drone)}>进入完整实时监测 <ArrowSquareOut size={14} /></button>
    </footer>
  </aside>
}
