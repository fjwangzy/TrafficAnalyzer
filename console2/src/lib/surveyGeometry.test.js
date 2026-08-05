import { describe, expect, it } from 'vitest'

import {
  geometrySegments,
  dragImageGeometry,
  imageContainViewport,
  metricPolygonAreaLabel,
  metricSegmentLabel,
  polygonCentroid,
  projectMetricPolygonToImage,
  projectPoint,
} from './surveyGeometry'

describe('survey measurement geometry', () => {
  const metricTransform = [
    [0.1, 0, -2],
    [0, -0.1, 5],
    [0, 0, 1],
  ]

  it('projects BEV pixels into metric coordinates and formats a live edge length', () => {
    expect(projectPoint([20, 10], metricTransform)).toEqual([0, 4])
    expect(metricSegmentLabel([20, 10], [50, 50], metricTransform)).toBe('5.00 m')
  })

  it('computes a metric polygon area and its visual center for an in-canvas label', () => {
    const polygon = [[20, 10], [50, 10], [50, 50], [20, 50]]

    expect(metricPolygonAreaLabel(polygon, metricTransform)).toBe('12.00 m²')
    expect(polygonCentroid(polygon)).toEqual([35, 30])
  })

  it('returns every visible edge and closes saved polygonal annotations', () => {
    expect(geometrySegments([[0, 0], [3, 0], [3, 4]], 'polyline')).toEqual([
      [[0, 0], [3, 0]],
      [[3, 0], [3, 4]],
    ])
    expect(geometrySegments([[0, 0], [3, 0], [3, 4]], 'area', true)).toEqual([
      [[0, 0], [3, 0]],
      [[3, 0], [3, 4]],
      [[3, 4], [0, 0]],
    ])
  })

  it('accounts for object-fit contain letterboxing when drawing overlays', () => {
    expect(imageContainViewport(1000, 600, 1600, 900)).toEqual({
      scale: 0.625,
      offsetX: 0,
      offsetY: 18.75,
      width: 1000,
      height: 562.5,
    })
  })

  it('reverse-projects an ENU lane polygon onto its authoritative image', () => {
    const pixelToEnu = [
      [0.1, 0, -10],
      [0, 0.1, -5],
      [0, 0, 1],
    ]
    const geometry = {
      type: 'Polygon',
      coordinates: [[
        [0, 0],
        [10, 0],
        [10, 10],
        [0, 0],
      ]],
    }

    const projected = projectMetricPolygonToImage(geometry, pixelToEnu)
    expect(projected).toHaveLength(3)
    expect(projected[0][0]).toBeCloseTo(100)
    expect(projected[0][1]).toBeCloseTo(50)
    expect(projected[1][0]).toBeCloseTo(200)
    expect(projected[1][1]).toBeCloseTo(50)
    expect(projected[2][0]).toBeCloseTo(200)
    expect(projected[2][1]).toBeCloseTo(150)
  })

  it('clips a projected reference lane to the visible source-image rectangle', () => {
    expect(projectMetricPolygonToImage({
      type: 'Polygon',
      coordinates: [[[-10, 10], [50, 10], [50, 50], [-10, 50], [-10, 10]]],
    }, [[1, 0, 0], [0, 1, 0], [0, 0, 1]], { width: 40, height: 40 })).toEqual([
      [0, 40],
      [0, 10],
      [40, 10],
      [40, 40],
    ])
  })

  it('moves one lane vertex while keeping it inside the source image', () => {
    expect(dragImageGeometry(
      [[10, 10], [80, 10], [80, 80]],
      { type: 'vertex', index: 1, point: [130, -20] },
      { width: 100, height: 90 },
    )).toEqual([[10, 10], [100, 0], [80, 80]])
  })

  it('translates a whole lane without changing its shape or leaving the image', () => {
    expect(dragImageGeometry(
      [[70, 20], [90, 20], [90, 50], [70, 50]],
      { type: 'translate', dx: 30, dy: -40 },
      { width: 100, height: 90 },
    )).toEqual([[80, 0], [100, 0], [100, 30], [80, 30]])
  })

  it('allows channelized-editor geometry to move beyond the retained image boundary without distortion', () => {
    expect(dragImageGeometry(
      [[10, 20], [30, 20], [30, 50], [10, 50]],
      { type: 'translate', dx: -40, dy: 70 },
    )).toEqual([[-30, 90], [-10, 90], [-10, 120], [-30, 120]])
    expect(dragImageGeometry(
      [[10, 20], [30, 20], [30, 50]],
      { type: 'vertex', index: 0, point: [-25, 110] },
    )).toEqual([[-25, 110], [30, 20], [30, 50]])
  })
})
