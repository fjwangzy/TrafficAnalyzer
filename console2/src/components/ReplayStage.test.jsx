import { render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mapMocks = vi.hoisted(() => ({
  add: vi.fn(), destroy: vi.fn(), remove: vi.fn(), setCenter: vi.fn(), setFitView: vi.fn(), sdk: null,
}))

vi.mock('../lib/amap', () => ({ loadAmap: vi.fn(async () => mapMocks.sdk) }))

import { ReplayStage, splitReplaySegments } from './ReplayStage'

beforeEach(() => {
  Object.values(mapMocks).forEach((mock) => mock?.mockClear?.())
  mapMocks.sdk = {
    Map: class { constructor() { return mapMocks } },
    Polyline: class { constructor(options) { this.options = options } },
    CircleMarker: class { constructor(options) { this.options = options } },
  }
})

describe('ReplayStage', () => {
  it('never connects a replay line across missing coordinates or a recorded gap', () => {
    const track = { points: [
      { offset_ms: 0, gcj02: [117, 36], sampling_boundary: [] },
      { offset_ms: 400, gcj02: [117.1, 36], sampling_boundary: [] },
      { offset_ms: 800, gcj02: null, sampling_boundary: ['coordinate_invalid'] },
      { offset_ms: 1200, gcj02: [117.2, 36], sampling_boundary: ['coordinate_valid'] },
      { offset_ms: 5000, gcj02: [117.3, 36], sampling_boundary: ['tracking_gap'] },
    ] }

    expect(splitReplaySegments(track, 'gcj02').map((segment) => segment.map((point) => point.offset_ms)))
      .toEqual([[0, 400], [1200], [5000]])
  })

  it('keeps a sample-and-hold track visible when its current segment has one GCJ-02 point', async () => {
    render(<ReplayStage coordinateMode='gcj02' tracks={[{
      track_id: 'T-1',
      points: [{ offset_ms: 408200, gcj02: [117.02, 36.70], sampling_boundary: [] }],
    }]} />)

    await waitFor(() => expect(mapMocks.add).toHaveBeenCalledTimes(1))
    expect(mapMocks.add.mock.calls[0][0]).toHaveLength(1)
  })
})
