import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMocks = vi.hoisted(() => ({
  token: '',
  login: vi.fn(),
  logout: vi.fn(),
  currentUser: vi.fn(),
  setAccessToken: vi.fn((value) => { apiMocks.token = value }),
  clearAccessToken: vi.fn(() => { apiMocks.token = '' }),
}))

vi.mock('../lib/api', () => ({
  UNAUTHORIZED_EVENT: 'uav:unauthorized',
  getAccessToken: () => apiMocks.token,
  setAccessToken: apiMocks.setAccessToken,
  clearAccessToken: apiMocks.clearAccessToken,
  platformApi: {
    login: apiMocks.login,
    logout: apiMocks.logout,
    currentUser: apiMocks.currentUser,
  },
}))

import { AuthProvider, isSafeRedirect, useAuth } from './AuthContext'

function AuthProbe() {
  const auth = useAuth()
  return <div>
    <span data-testid='status'>{auth.status}</span>
    <span data-testid='role'>{auth.consoleRole}</span>
    <span data-testid='user'>{auth.user?.username || 'none'}</span>
    <button onClick={() => auth.login('admin', 'admin123')}>登录</button>
    <button onClick={auth.logout}>退出</button>
  </div>
}

let capturedAuth
function AuthCapture() {
  capturedAuth = useAuth()
  return null
}

describe('AuthProvider', () => {
  beforeEach(() => {
    apiMocks.token = ''
    apiMocks.login.mockReset()
    apiMocks.logout.mockReset()
    apiMocks.currentUser.mockReset()
    apiMocks.setAccessToken.mockClear()
    apiMocks.clearAccessToken.mockClear()
  })

  it('creates a new session and maps the backend role', async () => {
    apiMocks.login.mockResolvedValue({
      access_token: 'new-token',
      user: { username: 'operator', role: 'operator' },
    })
    render(<AuthProvider><AuthProbe /></AuthProvider>)

    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))
    expect(screen.getByTestId('user')).toHaveTextContent('operator')
    expect(screen.getByTestId('role')).toHaveTextContent('commander')
    expect(apiMocks.setAccessToken).toHaveBeenCalledWith('new-token')
  })

  it('restores and invalidates a stored session', async () => {
    apiMocks.token = 'stored-token'
    apiMocks.currentUser.mockResolvedValue({ username: 'viewer', role: 'viewer' })
    render(<AuthProvider><AuthProbe /></AuthProvider>)

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))
    expect(screen.getByTestId('role')).toHaveTextContent('analyst')

    window.dispatchEvent(new CustomEvent('uav:unauthorized'))
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'))
    expect(apiMocks.clearAccessToken).toHaveBeenCalled()
  })

  it('does not create a session when backend login fails', async () => {
    apiMocks.login.mockRejectedValue(new Error('Incorrect username or password'))
    render(<AuthProvider><AuthCapture /></AuthProvider>)

    await expect(capturedAuth.login('admin', 'wrong-password')).rejects.toThrow('Incorrect username or password')
    expect(apiMocks.setAccessToken).not.toHaveBeenCalled()
    expect(capturedAuth.status).toBe('anonymous')
  })

  it.each([
    ['服务器成功响应', () => Promise.resolve()],
    ['服务器请求失败', () => Promise.reject(new Error('network unavailable'))],
  ])('clears the local session when logging out even if %s', async (_label, response) => {
    apiMocks.token = 'stored-token'
    apiMocks.currentUser.mockResolvedValue({ username: 'admin', role: 'admin' })
    apiMocks.logout.mockImplementation(response)
    render(<AuthProvider><AuthProbe /></AuthProvider>)
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))

    fireEvent.click(screen.getByRole('button', { name: '退出' }))

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'))
    expect(apiMocks.logout).toHaveBeenCalledOnce()
    expect(apiMocks.clearAccessToken).toHaveBeenCalled()
  })
})

describe('isSafeRedirect', () => {
  it('accepts internal paths and rejects external or scheme-relative redirects', () => {
    expect(isSafeRedirect('/monitoring?intersection_id=1')).toBe(true)
    expect(isSafeRedirect('//evil.example')).toBe(false)
    expect(isSafeRedirect('https://evil.example')).toBe(false)
    expect(isSafeRedirect('/https://evil.example')).toBe(false)
  })
})
