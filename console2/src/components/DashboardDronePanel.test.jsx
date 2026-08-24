import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DashboardDronePanel } from './DashboardDronePanel'

describe('DashboardDronePanel', () => {
  it('shows last truthful telemetry and honest empty states for an offline UAV', () => {
    const onBack = vi.fn()
    const onOpenMonitoring = vi.fn()
    render(<DashboardDronePanel
      drone={{
        id: 'UAV-OFFLINE', name: '离线无人机', status_label: '离线',
        is_monitoring: false, can_open_monitoring: false,
        lon: 117.123456, lat: 36.654321, battery_pct: 42,
        telemetry_note: '最后遥测 · 12 分钟前', telemetry_fresh: false,
      }}
      stats={null}
      statsSource='无当前任务数据'
      socketStatus='disconnected'
      onBack={onBack}
      onOpenMonitoring={onOpenMonitoring}
    />)

    expect(screen.getByText('当前未启动检测任务')).toBeInTheDocument()
    expect(screen.getByText('117.123456, 36.654321')).toBeInTheDocument()
    expect(screen.getByText('当前无人机未运行检测任务，不展示历史样本冒充实时数据。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /进入完整实时监测/ })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '返回态势面板' }))
    expect(onBack).toHaveBeenCalledOnce()
    expect(onOpenMonitoring).not.toHaveBeenCalled()
  })

  it('renders current scoped metrics and enables the full monitoring entry', () => {
    const onOpenMonitoring = vi.fn()
    const drone = {
      id: 'UAV-LIVE', name: '在航无人机', is_monitoring: true, can_open_monitoring: true,
      pipeline_id: 'PIPE-1', source_profile_id: 'SRC-1', intersection_id: 'INT-1',
      video_stream_url: 'http://127.0.0.1:8127/video', telemetry_fresh: true,
    }
    render(<DashboardDronePanel
      drone={drone}
      stats={{ vehicles: 18, longestQueueM: 31, avgSpeedKmh: 22.5, tccEvents: 2 }}
      statsSource='实时推送'
      socketStatus='connected'
      digitalTwin={{ level: 'lane', label: '车道级 · Lane 12 · 活跃车辆 18', dataMode: 'live', availableLayers: { vehicles: true }, pixelVehicles: [] }}
      onBack={() => {}}
      onOpenMonitoring={onOpenMonitoring}
    />)

    expect(screen.getByAltText('在航无人机 无人机飞行窗口')).toHaveAttribute('src', expect.stringContaining('127.0.0.1:8127'))
    expect(screen.getByText('18辆')).toBeInTheDocument()
    expect(screen.getByText('31m')).toBeInTheDocument()
    expect(screen.getByText('22.5km/h')).toBeInTheDocument()
    expect(screen.getByText('2起')).toBeInTheDocument()
    expect(screen.getByText('车道级 · Lane 12 · 活跃车辆 18')).toBeInTheDocument()
    expect(screen.getByText('已验证车道与车辆世界轨迹独立叠加')).toBeInTheDocument()
    fireEvent.doubleClick(screen.getByAltText('在航无人机 无人机飞行窗口'))
    expect(onOpenMonitoring).toHaveBeenCalledWith(drone)
    fireEvent.click(screen.getByRole('button', { name: /进入完整实时监测/ }))
    expect(onOpenMonitoring).toHaveBeenCalledTimes(2)
  })

  it('does not navigate when a displayed stream has no complete monitoring context', () => {
    const onOpenMonitoring = vi.fn()
    render(<DashboardDronePanel
      drone={{
        id: 'UAV-NO-CONTEXT', name: '未绑定监控无人机', is_monitoring: true,
        can_open_monitoring: false, video_stream_url: 'http://127.0.0.1:8127/video',
      }}
      stats={null}
      statsSource='等待实时数据'
      socketStatus='connected'
      onBack={() => {}}
      onOpenMonitoring={onOpenMonitoring}
    />)

    fireEvent.doubleClick(screen.getByAltText('未绑定监控无人机 无人机飞行窗口'))
    expect(onOpenMonitoring).not.toHaveBeenCalled()
  })

  it('describes the main-map pixel simulation without claiming georeferenced placement', () => {
    render(<DashboardDronePanel
      drone={{ id: 'UAV-PIXEL', name: '像素轨迹无人机', is_monitoring: true, can_open_monitoring: true }}
      stats={null}
      statsSource='等待实时数据'
      socketStatus='connected'
      digitalTwin={{
        level: 'bev_pixel', label: '3D 覆盖仿真 · 约 142×80m · 活跃车辆 1', dataMode: 'preview',
        availableLayers: { vehicles: true, simulatedVehicles: true, cameraFootprint: true, pixelVehicles: true },
        pixelVehicles: [{ id: '7', track_id: 7, trajectory_px: [[10, 20], [20, 30]] }],
        pixelGroundProjection: { widthM: 142, heightM: 80 },
      }}
      onBack={() => {}}
      onOpenMonitoring={() => {}}
    />)

    expect(screen.getByText('3D 覆盖仿真 · 约 142×80m · 活跃车辆 1')).toBeInTheDocument()
    expect(screen.getByText('前端 Mock 预览')).toBeInTheDocument()
    expect(screen.getByText('车辆按无人机高度、云台航向和相机视场投影到 3D 地面覆盖框；未做 GCP 精配准')).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: 'BEV 像素坐标车辆轨迹' })).not.toBeInTheDocument()
  })

  it('distinguishes an unregistered video address from a stream connection failure', () => {
    const baseDrone = { id: 'UAV-VIDEO', name: '视频状态无人机', is_monitoring: true, can_open_monitoring: true, pipeline_id: 'PIPE-VIDEO' }
    const view = render(<DashboardDronePanel
      drone={baseDrone}
      stats={null}
      statsSource='等待实时数据'
      socketStatus='connected'
      onBack={() => {}}
      onOpenMonitoring={() => {}}
    />)

    expect(screen.getByText('Pipeline 未登记浏览器可达视频地址')).toBeInTheDocument()

    view.rerender(<DashboardDronePanel
      drone={{ ...baseDrone, video_stream_url: 'http://127.0.0.1:8127/video' }}
      stats={null}
      statsSource='等待实时数据'
      socketStatus='connected'
      onBack={() => {}}
      onOpenMonitoring={() => {}}
    />)
    fireEvent.error(screen.getByAltText('视频状态无人机 无人机飞行窗口'))
    expect(screen.getByText('飞行窗口连接失败')).toBeInTheDocument()
  })

  it('keeps a running Pipeline in the waiting state when its normalized Stats contain no values', () => {
    render(<DashboardDronePanel
      drone={{ id: 'UAV-WAIT', name: '等待统计无人机', is_monitoring: true, can_open_monitoring: true, pipeline_id: 'PIPE-WAIT' }}
      stats={{ vehicles: null, longestQueueM: null, avgSpeedKmh: null, tccEvents: null }}
      statsSource='等待实时数据'
      socketStatus='connected'
      onBack={() => {}}
      onOpenMonitoring={() => {}}
    />)

    expect(screen.getByText('暂无核心实时指标')).toBeInTheDocument()
    expect(screen.getByText(/等待当前 Pipeline 的统计数据/)).toBeInTheDocument()
    expect(screen.queryByText('—辆')).not.toBeInTheDocument()
  })
})
