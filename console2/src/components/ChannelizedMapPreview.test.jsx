import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const amapMocks = vi.hoisted(() => ({ maps: [], polygons: [], polylines: [], imageLayers: [] }))

vi.mock('../lib/amap', () => ({
  loadAmap: vi.fn(async () => {
    class Map {
      constructor(_target, options) { this.options = options; amapMocks.maps.push(this) }
      add(items) { this.items = items }
      setFitView(items) { this.fitItems = items }
      destroy() {}
    }
    class Polygon {
      constructor(options) { this.options = options; amapMocks.polygons.push(this) }
    }
    class Polyline {
      constructor(options) { this.options = options; amapMocks.polylines.push(this) }
    }
    class ImageLayer {
      constructor(options) { this.options = options; amapMocks.imageLayers.push(this) }
    }
    class Bounds {
      constructor(southWest, northEast) { this.southWest = southWest; this.northEast = northEast }
    }
    return { Map, Polygon, Polyline, ImageLayer, Bounds }
  }),
}))

import { ChannelizedMapPreview } from './ChannelizedMapPreview'

describe('ChannelizedMapPreview', () => {
  beforeEach(() => {
    amapMocks.maps = []
    amapMocks.polygons = []
    amapMocks.polylines = []
    amapMocks.imageLayers = []
  })

  it('renders published lane_polygons and the registered orthophoto on AMap', async () => {
    render(<ChannelizedMapPreview mapVersion={{
      status: 'lane_verified',
      anchor_gcj02: [117.1, 36.7],
      geometry_gcj02: {
        links: { linkA: { type: 'LineString', coordinates: [[117.09, 36.7], [117.11, 36.7]] } },
        lane_polygons: {
          'local:lane:1': {
            type: 'Polygon',
            coordinates: [[[117.09, 36.699], [117.11, 36.699], [117.11, 36.701], [117.09, 36.699]]],
          },
        },
      },
      visual_registration: {
        orthophoto_url: '/api/v1/calibration/media/ortho.jpg',
        orthophoto_bounds_gcj02: [[117.08, 36.69], [117.12, 36.71]],
      },
    }} />)

    expect(screen.getByText('GCJ-02 · lane_verified')).toBeInTheDocument()
    await waitFor(() => expect(amapMocks.maps).toHaveLength(1))
    expect(amapMocks.polygons).toHaveLength(1)
    expect(amapMocks.polygons[0].options.path[0]).toEqual([117.09, 36.699])
    expect(amapMocks.imageLayers).toHaveLength(1)
    expect(amapMocks.imageLayers[0].options.url).toContain('ortho.jpg')
  })
})
