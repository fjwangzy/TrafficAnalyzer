import { useEffect, useMemo, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import {
  AirplaneTilt, Buildings, CaretDown, CheckCircle, Clock, Crosshair, Drone,
  Gear, GridFour, MapTrifold, Question, ShieldWarning, SlidersHorizontal,
  User, Warning,
  SignOut,
} from '@phosphor-icons/react'
import { roles, scopeOptions, windowOptions } from '../data/mockData'
import { useAppState } from '../state/AppState'
import { useAuth } from '../auth/AuthContext'
import { DEMO_GOVERNANCE_ENABLED } from '../config/features'

export const navigationGroups = [
  { id: 'situation', label: '全域态势', icon: GridFour, roles: ['admin', 'commander', 'enforcement', 'survey', 'analyst'], items: [
    ['/', '工作台首屏'], ['/monitoring', '实时监测'],
  ] },
  { id: 'insight', label: '智能研判', icon: ShieldWarning, roles: ['admin', 'commander', 'enforcement', 'analyst'], items: [
    ['/events', 'AI 事件中心'], ['/gis', '轨迹研判'],
  ] },
  { id: 'survey', label: '事故测绘', icon: Crosshair, roles: ['admin', 'survey'], items: [['/survey', '测绘任务']] },
  { id: 'enforcement', label: '执法线索', icon: Buildings, roles: ['admin', 'enforcement', 'analyst'], items: [['/enforcement', '执法工作台']] },
  { id: 'mission', label: '飞行任务', icon: Drone, roles: ['admin', 'commander', 'analyst'], items: [['/drones', '无人机与计划']] },
  { id: 'governance', label: '平台治理', icon: Gear, roles: ['admin'], items: [
    ['/admin/calibration', '标定中心'],
    ...(DEMO_GOVERNANCE_ENABLED ? [['/admin/integration', '集成与交付']] : []),
    ['/admin/system', '系统与身份'],
  ] },
]

function currentGroup(pathname) {
  return navigationGroups.find((group) => group.items.some(([path]) => path === '/' ? pathname === '/' : pathname.startsWith(path)))
    || (pathname.startsWith('/admin') ? navigationGroups.find((group) => group.id === 'governance') : navigationGroups[0])
}

function isSectionActive(pathname, path) {
  if (path === '/') return pathname === path
  return pathname.startsWith(path)
}

export function ConsoleFrame({ children, pageTitle, immersive = false, topContext = null }) {
  const location = useLocation()
  const navigate = useNavigate()
  const { state, dispatch } = useAppState()
  const { user, platformRole, consoleRole, logout } = useAuth()
  const [scopeOpen, setScopeOpen] = useState(false)
  const [timeOpen, setTimeOpen] = useState(false)
  const [roleOpen, setRoleOpen] = useState(false)
  const activeGroup = currentGroup(location.pathname)
  const visibleGroups = navigationGroups.filter((group) => group.roles.includes(state.role))
  const visibleSections = activeGroup.items
  const role = roles.find((item) => item.id === state.role)
  const updateQuery = (key, value) => {
    const params = new URLSearchParams(location.search)
    params.set(key, value)
    navigate(`${location.pathname}?${params.toString()}`, { replace: true })
  }

  useEffect(() => {
    if (!state.toast) return
    const timer = window.setTimeout(() => dispatch({ type: 'CLEAR_TOAST' }), 2600)
    return () => window.clearTimeout(timer)
  }, [state.toast, dispatch])

  const crumbs = useMemo(() => {
    const item = navigationGroups.flatMap((group) => group.items).find(([path]) => path === '/' ? location.pathname === '/' : location.pathname.startsWith(path))
    return [activeGroup.label, pageTitle || item?.[1]].filter(Boolean)
  }, [activeGroup.label, location.pathname, pageTitle])

  return (
    <div className={`app-shell${immersive ? ' immersive-shell' : ''}`}>
      <header className='shell-topbar'>
        <Link to='/' className='shell-brand'><span><AirplaneTilt size={23} weight='fill' /></span><div><strong>云瞳</strong><small>无人机交通智能感知平台</small></div></Link>
        <nav className='secondary-nav' aria-label={`${activeGroup.label}二级导航`}>
          {visibleSections.map(([path, label]) => <Link key={path} to={path} className={isSectionActive(location.pathname, path) ? 'active' : ''}>{label}</Link>)}
        </nav>
        <div className='shell-actions'>
          <button className='scope-button' disabled={Boolean(topContext)} onClick={() => { setScopeOpen(!scopeOpen); setTimeOpen(false) }}><MapTrifold size={16} weight='fill' /><span>{topContext?.scope || state.scope}</span>{!topContext && <CaretDown size={13} />}</button>
          <button className='time-button' disabled={Boolean(topContext)} onClick={() => { setTimeOpen(!timeOpen); setScopeOpen(false) }}><Clock size={15} /><span>{topContext?.window || state.window}</span>{!topContext && <CaretDown size={12} />}</button>
          <span className='freshness'><i /> {topContext?.asOf ? `数据截至 ${topContext.asOf}` : '未提供实时水位'}</span>
          <button className='circle-button' aria-label='帮助'><Question size={18} /></button>
          <button className='role-button' aria-label='当前用户' onClick={() => setRoleOpen(!roleOpen)}><User size={17} weight='fill' /><span>{user?.username || role.label}</span><CaretDown size={12} /></button>
        </div>
        {!topContext && scopeOpen && <div className='top-popover scope-popover'><strong>项目范围</strong>{scopeOptions.map((value) => <button key={value.id} onClick={() => { dispatch({ type: 'SET_SCOPE', value }); updateQuery('scope', value.id); setScopeOpen(false) }}><CheckCircle size={15} weight={state.scopeId === value.id ? 'fill' : 'regular'} />{value.label}</button>)}</div>}
        {!topContext && timeOpen && <div className='top-popover time-popover'><strong>全局时间窗口</strong>{windowOptions.map((value) => <button key={value.id} onClick={() => { dispatch({ type: 'SET_WINDOW', value }); updateQuery('window', value.id); setTimeOpen(false) }}><Clock size={15} weight={state.windowId === value.id ? 'fill' : 'regular'} />{value.label}</button>)}</div>}
        {roleOpen && <div className='top-popover role-popover'><strong>{platformRole === 'admin' ? '管理员角色预览' : role.label}</strong>{platformRole === 'admin' && roles.map((item) => <button key={item.id} onClick={() => { dispatch({ type: 'SET_ROLE', value: item.id, label: item.label }); setRoleOpen(false); navigate('/') }}><User size={15} weight={state.role === item.id ? 'fill' : 'regular'} />{item.label}</button>)}<button onClick={async () => { setRoleOpen(false); await logout(); navigate('/login', { replace: true }) }}><SignOut size={15} />退出登录</button></div>}
      </header>

      <aside className='shell-rail' aria-label='一级业务域'>
        <button className='rail-menu' onClick={() => navigate('/')} aria-label='返回工作台'><AirplaneTilt size={20} weight='fill' /></button>
        <nav>
          {visibleGroups.map((group) => { const Icon = group.icon; return <button key={group.id} className={activeGroup.id === group.id ? 'active' : ''} onClick={() => navigate(group.items[0][0])} aria-label={group.label} title={group.label}><Icon size={21} weight={activeGroup.id === group.id ? 'fill' : 'regular'} /><span>{group.label}</span></button> })}
        </nav>
        <button className='rail-settings' onClick={() => navigate('/admin/system')} aria-label='系统设置'><SlidersHorizontal size={21} /></button>
      </aside>

      <main className={immersive ? 'workspace' : 'shell-main'}>
        {!immersive && <div className='breadcrumb'>{crumbs.map((item, index) => <span key={item}>{index > 0 && '/'} {item}</span>)}</div>}
        {children}
      </main>
      {state.toast && <div className={`toast ${state.toast.tone}`}><CheckCircle size={18} weight='fill' />{state.toast.text}</div>}
    </div>
  )
}

export function AppShell({ children, pageTitle, topContext }) {
  return <ConsoleFrame pageTitle={pageTitle} topContext={topContext}>{children}</ConsoleFrame>
}

export const routeAccess = {
  '/survey': ['admin', 'survey'],
  '/enforcement': ['admin', 'enforcement', 'analyst'],
  '/admin': ['admin'],
}

export function AccessBoundary({ children }) {
  const location = useLocation()
  const { consoleRole, platformRole } = useAuth()
  const rule = Object.entries(routeAccess).find(([prefix]) => location.pathname.startsWith(prefix))
  if (location.pathname.startsWith('/admin') && platformRole !== 'admin') {
    return <AppShell pageTitle='无权限'><div className='access-denied'><Warning size={44} weight='duotone' /><h1>当前账号无权访问平台治理</h1><p>平台治理仅向系统管理员开放，前端角色预览不会改变真实权限。</p><Link to='/'>返回工作台</Link></div></AppShell>
  }
  if (rule && !rule[1].includes(consoleRole) && platformRole !== 'admin') {
    return <AppShell pageTitle='无权限'><div className='access-denied'><Warning size={44} weight='duotone' /><h1>当前角色无权访问此工作区</h1><p>这是角色预览下的真实权限状态。请切换为具备该模块权限的角色。</p><Link to='/'>返回城市一图</Link></div></AppShell>
  }
  return children
}
