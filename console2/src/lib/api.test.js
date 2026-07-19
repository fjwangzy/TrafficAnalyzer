import { describe, expect, it } from 'vitest'
import { api, platformApi } from './api'

describe('Platform HTTP session contract', () => {
  it('sends credentials so login and logout can manage the HttpOnly media session', () => {
    expect(api.defaults.withCredentials).toBe(true)
    expect(platformApi.logout).toBeTypeOf('function')
  })
})
