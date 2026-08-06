import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DashboardDronePanel } from './DashboardDronePanel'

describe('DashboardDronePanel', () => {
  it('shows last truthful telemetry and honest empty states for an offline UAV', () => {
    const onClose = vi.fn()
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
      onClose={onClose}
      onOpenMonitoring={onOpenMonitoring}
    />)

    expect(screen.getByText('当前未启动检测任务')).toBeInTheDocument()
    expect(screen.getByText('117.123456, 36.654321')).toBeInTheDocument()
    expect(screen.getByText('当前无人机未运行检测任务，不展示历史样本冒充实时数据。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /进入完整实时监测/ })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '关闭无人机详情' }))
    expect(onClose).toHaveBeenCalledOnce()
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
      onClose={() => {}}
      onOpenMonitoring={onOpenMonitoring}
    />)

    expect(screen.getByAltText('在航无人机 无人机飞行窗口')).toHaveAttribute('src', expect.stringContaining('127.0.0.1:8127'))
    expect(screen.getByText('18辆')).toBeInTheDocument()
    expect(screen.getByText('31m')).toBeInTheDocument()
    expect(screen.getByText('22.5km/h')).toBeInTheDocument()
    expect(screen.getByText('2起')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /进入完整实时监测/ }))
    expect(onOpenMonitoring).toHaveBeenCalledWith(drone)
  })

  it('distinguishes an unregistered video address from a stream connection failure', () => {
    const baseDrone = { id: 'UAV-VIDEO', name: '视频状态无人机', is_monitoring: true, can_open_monitoring: true, pipeline_id: 'PIPE-VIDEO' }
    const view = render(<DashboardDronePanel
      drone={baseDrone}
      stats={null}
      statsSource='等待实时数据'
      socketStatus='connected'
      onClose={() => {}}
      onOpenMonitoring={() => {}}
    />)

    expect(screen.getByText('Pipeline 未登记浏览器可达视频地址')).toBeInTheDocument()

    view.rerender(<DashboardDronePanel
      drone={{ ...baseDrone, video_stream_url: 'http://127.0.0.1:8127/video' }}
      stats={null}
      statsSource='等待实时数据'
      socketStatus='connected'
      onClose={() => {}}
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
      onClose={() => {}}
      onOpenMonitoring={() => {}}
    />)

    expect(screen.getByText('暂无核心实时指标')).toBeInTheDocument()
    expect(screen.getByText(/等待当前 Pipeline 的统计数据/)).toBeInTheDocument()
    expect(screen.queryByText('—辆')).not.toBeInTheDocument()
  })
})
