import { describe, expect, it, vi } from 'vitest'
import { api, apiErrorMessage, platformApi } from './api'

describe('Platform HTTP session contract', () => {
  it('sends credentials so login and logout can manage the HttpOnly media session', () => {
    expect(api.defaults.withCredentials).toBe(true)
    expect(platformApi.logout).toBeTypeOf('function')
  })

  it('lets mission startup and retry outlast the production detector readiness deadline', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { status: 'running' } })
    try {
      await platformApi.createMission({ source_profile_id: 'SRC-1' })
      await platformApi.retryMission('MIS-1', 'retry')
      expect(post).toHaveBeenNthCalledWith(1, '/missions', { source_profile_id: 'SRC-1' }, { timeout: 180_000 })
      expect(post).toHaveBeenNthCalledWith(2, '/missions/MIS-1/retry', { reason: 'retry' }, { timeout: 180_000 })
      expect(api.defaults.timeout).toBe(10_000)
    } finally {
      post.mockRestore()
    }
  })

  it('renders FastAPI validation arrays instead of the generic Axios status', () => {
    expect(apiErrorMessage({
      message: 'Request failed with status code 422',
      response: {
        data: {
          detail: [{
            type: 'extra_forbidden',
            loc: ['body', 'frame_stride'],
            msg: 'Extra inputs are not permitted',
          }],
        },
      },
    })).toBe('frame_stride：当前服务不支持该参数，请刷新版本或重启 Platform 后重试')
  })
})
