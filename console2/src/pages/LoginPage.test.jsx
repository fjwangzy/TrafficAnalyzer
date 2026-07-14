import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const loginMocks = vi.hoisted(() => ({ login: vi.fn() }))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ login: loginMocks.login, isAuthenticated: false }),
  isSafeRedirect: (value) => Boolean(value?.startsWith('/') && !value.startsWith('//') && !value.includes('://')),
}))

vi.mock('../lib/api', () => ({
  apiErrorMessage: (error, fallback) => error?.response?.data?.detail || error?.message || fallback,
}))

import { LoginPage } from './LoginPage'

function open(entry) {
  return render(<MemoryRouter initialEntries={[entry]}><Routes>
    <Route path='/login' element={<LoginPage />} />
    <Route path='/monitoring' element={<h1>监控已打开</h1>} />
    <Route path='/' element={<h1>工作台已打开</h1>} />
  </Routes></MemoryRouter>)
}

function fillAndSubmit() {
  fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'admin' } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'admin123' } })
  fireEvent.click(screen.getByRole('button', { name: '进入系统' }))
}

describe('LoginPage', () => {
  beforeEach(() => loginMocks.login.mockReset())

  it('uses valid internal redirects and rejects external redirect targets', async () => {
    loginMocks.login.mockResolvedValue({ username: 'admin', role: 'admin' })
    const first = open('/login?redirect=/monitoring')
    fillAndSubmit()
    expect(await screen.findByRole('heading', { name: '监控已打开' })).toBeInTheDocument()
    first.unmount()

    open('/login?redirect=https://evil.example')
    fillAndSubmit()
    await waitFor(() => expect(screen.getByRole('heading', { name: '工作台已打开' })).toBeInTheDocument())
  })
})
