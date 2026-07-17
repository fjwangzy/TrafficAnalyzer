import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/api', () => ({ getAccessToken: () => 'ws-token' }))

import { useWebSocket } from './useWebSocket'

const sockets = []

class FakeWebSocket {
  constructor(url) {
    this.url = url
    this.sent = []
    this.closeCalls = []
    sockets.push(this)
  }

  send(payload) { this.sent.push(JSON.parse(payload)) }
  close(code, reason) { this.closeCalls.push([code, reason]) }
}

function Probe({ channels = ['uav_intersection:INT-1'], onMessage = vi.fn() }) {
  const status = useWebSocket({ channels, onMessage })
  return <span>{status}</span>
}

describe('useWebSocket', () => {
  beforeEach(() => {
    sockets.length = 0
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('authenticates, subscribes, normalizes, deduplicates, and unsubscribes on unmount', () => {
    const onMessage = vi.fn()
    const view = render(<Probe channels={['uav_intersection:INT-1']} onMessage={onMessage} />)
    expect(sockets[0].url).toContain('access_token=ws-token')

    act(() => sockets[0].onopen())
    expect(screen.getByText('connected')).toBeInTheDocument()
    expect(sockets[0].sent).toEqual([
      { action: 'subscribe', channel: 'uav_intersection:INT-1' },
    ])

    const message = JSON.stringify({ type: 'uav_stats', message_id: 'M-1', data: { cars: 3 } })
    act(() => {
      sockets[0].onmessage({ data: message })
      sockets[0].onmessage({ data: message })
    })
    expect(onMessage).toHaveBeenCalledTimes(1)
    expect(onMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'uav_stats', messageId: 'M-1' }))

    view.unmount()
    expect(sockets[0].closeCalls).toContainEqual([1000, 'route changed'])
  })

  it('reconnects with exponential backoff after an abnormal close', () => {
    vi.useFakeTimers()
    render(<Probe />)
    act(() => sockets[0].onopen())
    act(() => sockets[0].onclose({ code: 1006 }))
    expect(screen.getByText('disconnected')).toBeInTheDocument()

    act(() => vi.advanceTimersByTime(999))
    expect(sockets).toHaveLength(1)
    act(() => vi.advanceTimersByTime(1))
    expect(sockets).toHaveLength(2)
    expect(screen.getByText('connecting')).toBeInTheDocument()
  })
})
