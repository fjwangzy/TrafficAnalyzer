import { useEffect, useMemo, useRef } from 'react'
import { MonitoringBevMap } from './MonitoringBevMap'

const COLORS = ['#63b3ff', '#ff806b', '#58d6b0', '#c792ff', '#ffca67']

export function splitReplaySegments(track, coordinateKey, gapThresholdMs = 2500) {
  const result = []
  let current = []
  let previous = null
  for (const point of track?.points || []) {
    const coordinate = point?.[coordinateKey]
    const boundaries = point?.sampling_boundary || []
    const gap = previous && Number(point.offset_ms) - Number(previous.offset_ms) > gapThresholdMs
    const explicitGap = boundaries.some((value) => String(value).includes('gap'))
    if (!Array.isArray(coordinate) || coordinate.length < 2 || gap || explicitGap) {
      if (current.length) result.push(current)
      current = []
      previous = point
      if (!Array.isArray(coordinate) || coordinate.length < 2) continue
    }
    current.push({ ...point, coordinate: coordinate.map(Number) })
    previous = point
  }
  if (current.length) result.push(current)
  return result
}

function PixelReplayCanvas({ tracks, label }) {
  const canvasRef = useRef(null)
  const signature = useMemo(() => JSON.stringify(tracks), [tracks])
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    if (navigator.userAgent.includes('jsdom')) return
    const width = Math.max(canvas.clientWidth || 900, 320)
    const height = Math.max(canvas.clientHeight || 440, 240)
    const ratio = window.devicePixelRatio || 1
    canvas.width = width * ratio
    canvas.height = height * ratio
    const context = canvas.getContext('2d')
    if (!context) return
    context.scale(ratio, ratio)
    context.clearRect(0, 0, width, height)
    const all = tracks.flatMap((track) => splitReplaySegments(track, 'pixel').flat())
    if (!all.length) return
    const xs = all.map((point) => point.coordinate[0])
    const ys = all.map((point) => point.coordinate[1])
    const minX = Math.min(...xs); const maxX = Math.max(...xs)
    const minY = Math.min(...ys); const maxY = Math.max(...ys)
    const padding = 28
    const project = ([x, y]) => [
      padding + (x - minX) / Math.max(maxX - minX, 1) * (width - padding * 2),
      padding + (y - minY) / Math.max(maxY - minY, 1) * (height - padding * 2),
    ]
    tracks.forEach((track, index) => {
      const color = COLORS[index % COLORS.length]
      splitReplaySegments(track, 'pixel').forEach((segment) => {
        context.beginPath()
        segment.forEach((point, pointIndex) => {
          const [x, y] = project(point.coordinate)
          if (pointIndex === 0) context.moveTo(x, y)
          else context.lineTo(x, y)
        })
        context.lineWidth = track.selected ? 4 : 2.5
        context.strokeStyle = color
        context.stroke()
        const [x, y] = project(segment.at(-1).coordinate)
        context.beginPath(); context.arc(x, y, 4, 0, Math.PI * 2)
        context.fillStyle = color; context.fill()
      })
    })
  }, [signature, tracks])
  return <div className='replay-pixel-stage' role='img' aria-label={label || '像素坐标轨迹回放平面'}><canvas ref={canvasRef} /><span>像素坐标回放 · 世界坐标不可用</span></div>
}

export function ReplayStage({ coordinateMode, tracks, centerLat, centerLon, label }) {
  if (coordinateMode === 'gcj02') {
    const mapTracks = tracks.flatMap((track, trackIndex) => (
      splitReplaySegments(track, 'gcj02').map((segment, segmentIndex) => ({
        ...track,
        id: `${track.track_id}:${segmentIndex}`,
        color_index: trackIndex,
        trajectory_gcj02: segment.map((point) => point.coordinate),
      }))
    ))
    return <MonitoringBevMap centerLat={centerLat} centerLon={centerLon} trajectories={mapTracks} embedded showEndpoints label={label} />
  }
  return <PixelReplayCanvas tracks={tracks} label={label} />
}
