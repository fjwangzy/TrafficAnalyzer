import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { AirplaneTilt, LockKey, SignIn, User } from '@phosphor-icons/react'
import { useAuth, isSafeRedirect } from '../auth/AuthContext'
import { LoginTrafficFlow } from '../components/LoginTrafficFlow'
import { apiErrorMessage } from '../lib/api'

export function LoginPage() {
  const { login, isAuthenticated } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const requested = new URLSearchParams(location.search).get('redirect')
  const destination = isSafeRedirect(requested) ? requested : '/'

  if (isAuthenticated) return <Navigate to={destination} replace />

  const submit = async (event) => {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      await login(username.trim(), password)
      navigate(destination, { replace: true })
    } catch (requestError) {
      setError(apiErrorMessage(requestError, '登录失败，请检查用户名和密码'))
      setSubmitting(false)
    }
  }

  return <main className='login-screen'>
    <div className='login-backdrop'>
      <img src='/assets/uav-intersection-night.png' alt='' />
      <LoginTrafficFlow />
    </div>
    <section className='login-card' aria-labelledby='login-title'>
      <div className='login-brand'><span><AirplaneTilt size={26} weight='fill' /></span><div><strong>云瞳</strong><small>无人机交通智能感知平台</small></div></div>
      <div className='login-copy'><span>CONSOLE 2.0</span><h1 id='login-title'>登录系统</h1><p>进入全域态势、实时监测与平台治理工作区。</p></div>
      <form onSubmit={submit}>
        <label><span>用户名</span><div><User size={17} /><input aria-label='用户名' autoComplete='username' value={username} onChange={(event) => setUsername(event.target.value)} placeholder='请输入用户名' required /></div></label>
        <label><span>密码</span><div><LockKey size={17} /><input aria-label='密码' type='password' autoComplete='current-password' value={password} onChange={(event) => setPassword(event.target.value)} placeholder='请输入密码' required /></div></label>
        {error && <div className='login-error' role='alert'>{error}</div>}
        <button type='submit' disabled={submitting}><SignIn size={17} weight='bold' />{submitting ? '正在验证…' : '进入系统'}</button>
      </form>
      <footer><i /> 连接 Platform API · 会话结束后自动清除凭证</footer>
    </section>
  </main>
}
