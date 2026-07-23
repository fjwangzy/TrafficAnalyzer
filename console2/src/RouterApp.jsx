import { Component, lazy, Suspense } from 'react'
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AccessBoundary, AppShell } from './components/AppShell'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { AppStateProvider } from './state/AppState'
import { LoginPage } from './pages/LoginPage'
import { DEMO_GOVERNANCE_ENABLED } from './config/features'

const lazyNamed = (loader, name) => lazy(() => loader().then((module) => ({ default: module[name] })))
const MonitoringPage = lazyNamed(() => import('./App'), 'App')
const DashboardPage = lazyNamed(() => import('./pages/DashboardPage'), 'DashboardPage')
const AlertsPage = lazyNamed(() => import('./pages/InsightPages'), 'AlertsPage')
const GisPage = lazyNamed(() => import('./pages/InsightPages'), 'GisPage')
const DronesPage = lazyNamed(() => import('./pages/MissionSurveyPages'), 'DronesPage')
const SurveyListPage = lazyNamed(() => import('./pages/SurveyPages'), 'SurveyListPage')
const SurveyPrecheckPage = lazyNamed(() => import('./pages/SurveyPages'), 'SurveyPrecheckPage')
const SurveyCapturePage = lazyNamed(() => import('./pages/SurveyPages'), 'SurveyCapturePage')
const SurveyMeasurePage = lazyNamed(() => import('./pages/SurveyPages'), 'SurveyMeasurePage')
const SurveyReviewPage = lazyNamed(() => import('./pages/SurveyPages'), 'SurveyReviewPage')
const SurveyReportPage = lazyNamed(() => import('./pages/SurveyPages'), 'SurveyReportPage')
const EnforcementEventsPage = lazyNamed(() => import('./pages/EnforcementPages'), 'EnforcementEventsPage')
const EnforcementZonesPage = lazyNamed(() => import('./pages/EnforcementPages'), 'EnforcementZonesPage')
const TrucksPage = lazyNamed(() => import('./pages/EnforcementPages'), 'TrucksPage')
const CalibrationPage = lazyNamed(() => import('./pages/AdminPages'), 'CalibrationPage')
const IntersectionProjectsPage = lazyNamed(() => import('./pages/IntersectionProjectPages'), 'IntersectionProjectsPage')
const IntersectionProjectWorkspacePage = lazyNamed(() => import('./pages/IntersectionProjectPages'), 'IntersectionProjectWorkspacePage')
const SystemPage = lazyNamed(() => import('./pages/AdminPages'), 'SystemPage')
const IntegrationPage = DEMO_GOVERNANCE_ENABLED ? lazyNamed(() => import('./pages/IntegrationPage'), 'IntegrationPage') : null

export class RouteErrorBoundary extends Component {
  state = { error: null }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidUpdate(previousProps) {
    if (this.state.error && previousProps.resetKey !== this.props.resetKey) this.setState({ error: null })
  }

  render() {
    if (!this.state.error) return this.props.children
    return <main className='route-error' role='alert'>
      <h1>页面加载失败</h1>
      <p>{this.state.error.message || '当前页面发生未知错误'}</p>
      <button className='primary-button' onClick={() => window.location.reload()}>重新加载页面</button>
    </main>
  }
}

function ApplicationErrorBoundary({ children }) {
  const location = useLocation()
  return <RouteErrorBoundary resetKey={`${location.pathname}${location.search}`}>{children}</RouteErrorBoundary>
}

function RouteLoading() {
  return <div className='route-loading' role='status'><span />正在加载工作区…</div>
}

function DisabledIntegrationPage() {
  return <AppShell pageTitle='集成与交付未启用'>
    <div className='access-denied'>
      <h1>集成与交付未启用</h1>
      <p>演示治理能力默认关闭，当前环境没有可执行的死信重放或交付操作。</p>
      <Link to='/admin/system'>前往系统与身份</Link>
    </div>
  </AppShell>
}

function LegacyCalibrationRoute() {
  const location = useLocation()
  if (new URLSearchParams(location.search).get('tab') === 'lanes') return <CalibrationPage />
  return <Navigate to='/admin/intersection-projects' replace />
}

function RequireAuth({ children }) {
  const location = useLocation()
  const { status, isAuthenticated } = useAuth()
  if (status === 'checking') return <div className='auth-loading'><span /><strong>正在恢复安全会话</strong></div>
  if (!isAuthenticated) {
    const redirect = encodeURIComponent(`${location.pathname}${location.search}`)
    return <Navigate to={`/login?redirect=${redirect}`} replace />
  }
  return children
}

function ProtectedRoutes() {
  return <AccessBoundary><Suspense fallback={<RouteLoading />}><Routes>
    <Route path='/' element={<DashboardPage />} />
    <Route path='/monitoring' element={<MonitoringPage />} />
    <Route path='/gis' element={<GisPage />} />
    <Route path='/events' element={<AlertsPage />} />
    <Route path='/drones' element={<DronesPage />} />
    <Route path='/survey' element={<SurveyListPage />} />
    <Route path='/survey/:id/precheck' element={<SurveyPrecheckPage />} />
    <Route path='/survey/:id/capture' element={<SurveyCapturePage />} />
    <Route path='/survey/:id/measure' element={<SurveyMeasurePage />} />
    <Route path='/survey/:id/review' element={<SurveyReviewPage />} />
    <Route path='/survey/:id/report' element={<SurveyReportPage />} />
    <Route path='/enforcement' element={<EnforcementEventsPage />} />
    <Route path='/enforcement/zones' element={<EnforcementZonesPage />} />
    <Route path='/enforcement/trucks' element={<TrucksPage />} />
    <Route path='/admin/calibration' element={<LegacyCalibrationRoute />} />
    <Route path='/admin/calibration/editor' element={<CalibrationPage />} />
    <Route path='/admin/intersection-projects' element={<IntersectionProjectsPage />} />
    <Route path='/admin/intersection-projects/:projectId' element={<IntersectionProjectWorkspacePage />} />
    <Route path='/admin/integration' element={DEMO_GOVERNANCE_ENABLED ? <IntegrationPage /> : <DisabledIntegrationPage />} />
    <Route path='/admin/system' element={<SystemPage />} />

    <Route path='*' element={<Navigate to='/' replace />} />
  </Routes></Suspense></AccessBoundary>
}

function AuthenticatedApplication() {
  const { consoleRole } = useAuth()
  return <RequireAuth><AppStateProvider role={consoleRole}><ProtectedRoutes /></AppStateProvider></RequireAuth>
}

export function RouterApp() {
  return <BrowserRouter><ApplicationErrorBoundary><AuthProvider><Routes>
    <Route path='/login' element={<LoginPage />} />
    <Route path='/*' element={<AuthenticatedApplication />} />
  </Routes></AuthProvider></ApplicationErrorBoundary></BrowserRouter>
}
