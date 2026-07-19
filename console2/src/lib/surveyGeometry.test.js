import { describe, expect, it } from 'vitest'

import {
  geometrySegments,
  imageContainViewport,
  metricSegmentLabel,
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
})
