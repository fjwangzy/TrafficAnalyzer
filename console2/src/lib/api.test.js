import { describe, expect, it } from 'vitest'
import { api, apiErrorMessage, platformApi } from './api'

describe('Platform HTTP session contract', () => {
  it('sends credentials so login and logout can manage the HttpOnly media session', () => {
    expect(api.defaults.withCredentials).toBe(true)
    expect(platformApi.logout).toBeTypeOf('function')
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
