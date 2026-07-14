import { createContext, useContext, useEffect, useMemo, useReducer } from 'react'
import { useLocation } from 'react-router-dom'
import { aiEvents, enforcementZones, flightPlans, integrations, missions, scopeOptions, surveyTasks, windowOptions } from '../data/mockData'

const AppStateContext = createContext(null)

const initialState = {
  role: 'admin',
  scope: scopeOptions[0].label,
  scopeId: scopeOptions[0].id,
  window: windowOptions[0].label,
  windowId: windowOptions[0].id,
  events: aiEvents,
  zones: enforcementZones,
  plans: flightPlans,
  missions,
  surveys: surveyTasks,
  integrations,
  toast: null,
  mapOffline: false,
}

function initializeState({ search, role }) {
  const params = new URLSearchParams(search)
  const scope = scopeOptions.find((item) => item.id === params.get('scope')) || scopeOptions[0]
  const windowOption = windowOptions.find((item) => item.id === params.get('window')) || windowOptions[0]
  return { ...initialState, role: role || 'analyst', scope: scope.label, scopeId: scope.id, window: windowOption.label, windowId: windowOption.id }
}

function reducer(state, action) {
  switch (action.type) {
    case 'SET_ROLE': return { ...state, role: action.value, toast: { tone: 'info', text: `已切换为${action.label}预览` } }
    case 'SYNC_ROLE': return { ...state, role: action.value }
    case 'SET_SCOPE': return { ...state, scope: action.value.label, scopeId: action.value.id }
    case 'SET_WINDOW': return { ...state, window: action.value.label, windowId: action.value.id }
    case 'REVIEW_EVENT': return { ...state, events: state.events.map((item) => item.id === action.id ? { ...item, review: action.value } : item), toast: { tone: 'success', text: action.value === 'confirmed' ? 'AI 结果已技术确认' : 'AI 结果已驳回并记录原因' } }
    case 'SAVE_ZONE': return { ...state, zones: state.zones.map((item) => item.id === action.id ? { ...item, status: 'candidate', version: `${item.version}-edited` } : item), toast: { tone: 'success', text: '候选围栏已保存，未覆盖权威版本' } }
    case 'CHECK_PLAN': return { ...state, toast: { tone: action.conflict ? 'warning' : 'success', text: action.conflict ? '发现同无人机时间冲突，计划保持草稿' : '未来窗口校验通过' } }
    case 'MISSION_ACTION': return { ...state, missions: state.missions.map((item) => item.id === action.id ? { ...item, status: action.value, pipeline: action.value === 'cancelled' ? 'stopped' : 'starting' } : item), toast: { tone: 'success', text: action.value === 'cancelled' ? 'Mission 已停止并记录审计' : '已创建新的重试 Mission' } }
    case 'CREATE_SURVEY': return { ...state, surveys: [action.value, ...state.surveys], toast: { tone: 'success', text: '测绘任务已创建，进入采集质检' } }
    case 'SURVEY_ACTION': return { ...state, surveys: state.surveys.map((item) => item.id === action.id ? { ...item, status: action.value, version: action.value === 'returned' ? item.version : item.version } : item), toast: { tone: action.value === 'returned' ? 'warning' : 'success', text: action.value === 'returned' ? '已退回补拍，原版本完整保留' : '已提交技术复核' } }
    case 'REPLAY_DEAD_LETTER': return { ...state, integrations: state.integrations.map((item) => item.id === action.id ? { ...item, status: 'retrying', attempts: item.attempts + 1, reason: 'MANUAL_REPLAY' } : item), toast: { tone: 'success', text: '已按原幂等键发起重放' } }
    case 'TOGGLE_MAP': return { ...state, mapOffline: !state.mapOffline }
    case 'TOAST': return { ...state, toast: action.value }
    case 'CLEAR_TOAST': return { ...state, toast: null }
    default: return state
  }
}

export function AppStateProvider({ children, role }) {
  const location = useLocation()
  const [state, dispatch] = useReducer(reducer, { search: location.search, role }, initializeState)
  useEffect(() => { dispatch({ type: 'SYNC_ROLE', value: role }) }, [role])
  const value = useMemo(() => ({ state, dispatch }), [state])
  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>
}

export function useAppState() {
  const context = useContext(AppStateContext)
  if (!context) throw new Error('useAppState must be used inside AppStateProvider')
  return context
}
