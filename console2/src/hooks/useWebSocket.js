import { useEffect, useRef, useState } from 'react'
import { normalizeRealtimeMessage, realtimeEventKey } from '../lib/realtime'

export function useWebSocket({ channels = [], onMessage, enabled = true }) {
  const [status, setStatus] = useState(enabled ? 'connecting' : 'disabled')
  const socketRef = useRef(null)
  const retryRef = useRef(0)
  const timerRef = useRef(null)
  const callbackRef = useRef(onMessage)
  const seenRef = useRef(new Map())
  const channelKey = JSON.stringify(channels)

  useEffect(() => { callbackRef.current = onMessage }, [onMessage])

  useEffect(() => {
    if (!enabled || channels.length === 0) {
      setStatus(enabled ? 'idle' : 'disabled')
      return undefined
    }

    let active = true
    const connect = () => {
      if (!active) return
      setStatus('connecting')
      const base = import.meta.env.VITE_WS_URL || `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/realtime`
      const socket = new WebSocket(base)
      socketRef.current = socket

      socket.onopen = () => {
        retryRef.current = 0
        setStatus('connected')
        channels.forEach((channel) => socket.send(JSON.stringify({ action: 'subscribe', channel })))
      }
      socket.onmessage = (event) => {
        try {
          const message = normalizeRealtimeMessage(JSON.parse(event.data))
          if (!message) return
          const key = realtimeEventKey(message)
          const now = Date.now()
          if (key && seenRef.current.has(key) && now - seenRef.current.get(key) < 60_000) return
          if (key) seenRef.current.set(key, now)
          if (seenRef.current.size > 500) {
            for (const [itemKey, timestamp] of seenRef.current) if (now - timestamp > 60_000) seenRef.current.delete(itemKey)
          }
          callbackRef.current?.(message)
        } catch {
          // Ignore malformed non-business frames.
        }
      }
      socket.onerror = () => socket.close()
      socket.onclose = (event) => {
        if (!active || event.code === 1000) return
        setStatus('disconnected')
        const delay = Math.min(1000 * (2 ** retryRef.current), 30_000)
        retryRef.current += 1
        timerRef.current = window.setTimeout(connect, delay)
      }
    }

    connect()
    return () => {
      active = false
      if (timerRef.current) window.clearTimeout(timerRef.current)
      if (socketRef.current) socketRef.current.close(1000, 'route changed')
    }
  }, [channelKey, enabled]) // eslint-disable-line react-hooks/exhaustive-deps

  return status
}
