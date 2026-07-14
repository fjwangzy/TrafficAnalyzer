import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { App as MonitoringPage } from './App'
import { AccessBoundary } from './components/AppShell'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { AppStateProvider } from './state/AppState'
import { DashboardPage } from './pages/DashboardPage'
import { AlertsPage, GisPage } from './pages/InsightPages'
import { DronesPage, SurveyCapturePage, SurveyListPage, SurveyMeasurePage, SurveyReportPage, SurveyReviewPage } from './pages/MissionSurveyPages'
import { EnforcementEventsPage, EnforcementZonesPage, TrucksPage } from './pages/EnforcementPages'
import { CalibrationPage, IntegrationPage, SystemPage } from './pages/AdminPages'
import { LoginPage } from './pages/LoginPage'

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
  return <AccessBoundary><Routes>
    <Route path='/' element={<DashboardPage />} />
    <Route path='/monitoring' element={<MonitoringPage />} />
    <Route path='/gis' element={<GisPage />} />
    <Route path='/events' element={<AlertsPage />} />
    <Route path='/drones' element={<DronesPage />} />
    <Route path='/survey' element={<SurveyListPage />} />
    <Route path='/survey/:id/capture' element={<SurveyCapturePage />} />
    <Route path='/survey/:id/measure' element={<SurveyMeasurePage />} />
    <Route path='/survey/:id/review' element={<SurveyReviewPage />} />
    <Route path='/survey/:id/report' element={<SurveyReportPage />} />
    <Route path='/enforcement' element={<EnforcementEventsPage />} />
    <Route path='/enforcement/zones' element={<EnforcementZonesPage />} />
    <Route path='/enforcement/trucks' element={<TrucksPage />} />
    <Route path='/admin/calibration' element={<CalibrationPage />} />
    <Route path='/admin/integration' element={<IntegrationPage />} />
    <Route path='/admin/system' element={<SystemPage />} />

    <Route path='*' element={<Navigate to='/' replace />} />
  </Routes></AccessBoundary>
}

function AuthenticatedApplication() {
  const { consoleRole } = useAuth()
  return <RequireAuth><AppStateProvider role={consoleRole}><ProtectedRoutes /></AppStateProvider></RequireAuth>
}

export function RouterApp() {
  return <BrowserRouter><AuthProvider><Routes>
    <Route path='/login' element={<LoginPage />} />
    <Route path='/*' element={<AuthenticatedApplication />} />
  </Routes></AuthProvider></BrowserRouter>
}
