import { describe, expect, it } from 'vitest'
import { deleteLaneDrafts, mergeLaneDrafts, selectLaneDraft, splitLaneDraft } from './laneDraftGeometry'

const lane = (id, linkId, points) => ({ local_lane_id: id, source_lane_id: `source:${id}`, link_id: linkId, direction: 'straight', points })

describe('lane draft geometry operations', () => {
  it('deletes only the selected Link group', () => {
    const drafts = [lane('L1', 'LINK-A', [[0, 0], [1, 0], [1, 2], [0, 2]]), lane('L2', 'LINK-A', [[1, 0], [2, 0], [2, 2], [1, 2]]), lane('L3', 'LINK-B', [[3, 0], [4, 0], [4, 2], [3, 2]])]
    expect(deleteLaneDrafts(drafts, selectLaneDraft(drafts, 'L1', 'link')).map((item) => item.local_lane_id)).toEqual(['L3'])
  })

  it('splits a lane across its long axis and keeps both parts on the same Link', () => {
    const drafts = [lane('L1', 'LINK-A', [[0, 0], [4, 0], [4, 20], [0, 20]])]
    const result = splitLaneDraft(drafts, selectLaneDraft(drafts, 'L1', 'lane'))

    expect(result.lanes).toHaveLength(2)
    expect(result.lanes.map((item) => item.link_id)).toEqual(['LINK-A', 'LINK-A'])
    expect(result.lanes.map((item) => item.source_lane_id)).toEqual([null, null])
    expect(result.lanes.every((item) => item.points.length >= 3)).toBe(true)
    const verticalRanges = result.lanes.map((item) => [Math.min(...item.points.map((point) => point[1])), Math.max(...item.points.map((point) => point[1]))]).sort((left, right) => left[0] - right[0])
    expect(verticalRanges).toEqual([[0, 10], [10, 20]])
  })

  it('merges adjacent lanes into one convex envelope with auditable parents', () => {
    const drafts = [lane('L1', 'LINK-A', [[0, 0], [4, 0], [4, 20], [0, 20]]), lane('L2', 'LINK-A', [[4, 0], [8, 0], [8, 20], [4, 20]])]
    const result = mergeLaneDrafts(drafts, selectLaneDraft(drafts, 'L1', 'link'))

    expect(result.lanes).toHaveLength(1)
    expect(result.lanes[0]).toEqual(expect.objectContaining({ local_lane_id: 'L1:merged', link_id: 'LINK-A', source_lane_id: null, parent_lane_ids: ['L1', 'L2'] }))
    expect(result.lanes[0].points).toHaveLength(4)
  })
})
