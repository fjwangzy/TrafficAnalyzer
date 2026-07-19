import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowCounterClockwise, CloudArrowUp, Gauge, GitDiff, ShieldCheck, Warning } from '@phosphor-icons/react'
import { AppShell } from '../components/AppShell'
import { DataTable, DetailDrawer, InfoRow, KpiCard, PageHeader, Panel, QualityNotice, StatusBadge } from '../components/Common'
import { qualityRuns } from '../data/mockData'
import { useAppState } from '../state/AppState'

export function IntegrationPage() {
  const { state, dispatch } = useAppState()
  const location = useLocation()
  const navigate = useNavigate()
  const requestedTab = new URLSearchParams(location.search).get('tab')
  const [tab, setTab] = useState(['integration', 'delivery', 'evidence'].includes(requestedTab) ? requestedTab : 'integration')
  const [selected, setSelected] = useState(null)
  const selectedDelivery = selected ? state.integrations.find((item) => item.id === selected.id) || selected : null
  const selectTab = (value) => {
    setTab(value)
    const params = new URLSearchParams(location.search)
    params.set('tab', value)
    navigate(`${location.pathname}?${params.toString()}`, { replace: true })
  }
  const evidence = [{ id: 'EVD-0713-001', event: 'UAV-EVT-20260713-001', integrity: 'complete', items: 6, retention: '30 天热数据' }, { id: 'EVD-0713-004', event: 'CLUE-0713-022', integrity: 'partial', items: 4, retention: '法制口径待冻结' }]
  return <AppShell pageTitle='集成与交付'>
    <PageHeader eyebrow='S6 / S7 · 可靠交付闭环' title='集成与交付' description='统一查看主平台联调、质量门禁和证据交付；重放复用原事件、原时间和原幂等键。' meta='uav_ai_events → 主平台 · schema v2' />
    <div className='page-tabs'>{[['integration', '接口联调'], ['delivery', '质量交付'], ['evidence', '证据审计']].map(([id, label]) => <button className={tab === id ? 'active' : ''} key={id} onClick={() => selectTab(id)}>{label}</button>)}</div>
    {tab === 'integration' && <>
    <div className='kpi-grid five'><KpiCard icon={CloudArrowUp} label='投递成功率' value='99.72' unit='%' change='+0.08%' tone='green' /><KpiCard icon={Gauge} label='投递 P95' value='1.84' unit='s' detail='候选 SLA' /><KpiCard icon={ArrowCounterClockwise} label='重试中' value='12' unit='条' tone='amber' /><KpiCard icon={Warning} label='死信' value='2' unit='条' tone='red' /><KpiCard icon={ShieldCheck} label='反馈覆盖' value='72.6' unit='%' tone='cyan' /></div>
    <div className='integration-grid'><Panel title='延迟与失败趋势'><ResponsiveContainer width='100%' height='100%'><AreaChart data={[{ t: '10:20', p95: 1.4, fail: 0 }, { t: '10:30', p95: 1.7, fail: 1 }, { t: '10:40', p95: 2.2, fail: 2 }, { t: '10:50', p95: 1.84, fail: 2 }]}><CartesianGrid vertical={false} stroke='rgba(120,145,185,.12)' /><XAxis dataKey='t' tick={{ fill: '#7c8aa0', fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis tick={{ fill: '#7c8aa0', fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip contentStyle={{ background: '#101827', border: '1px solid #2a3952' }} /><Area dataKey='p95' stroke='#6d9eff' fill='#294c7b' /><Area dataKey='fail' stroke='#ff715b' fill='#69322d' /></AreaChart></ResponsiveContainer></Panel><Panel title='队列健康'><InfoRow label='出站积压' value='38 条' /><InfoRow label='最老消息龄' value='14m' badge='warning' /><InfoRow label='重试分布' value='1× 8 · 2× 3 · 6× 1' /><InfoRow label='Schema 拒绝' value='1 条' badge='degraded' /><InfoRow label='对账差异' value='2 条' badge='warning' /></Panel></div>
    <Panel title='重试与死信' subtitle='授权运维可执行原键重放；不可编辑原 payload'><DataTable rows={state.integrations} onRowClick={setSelected} columns={[{ key: 'status', label: '状态', render: (value) => <StatusBadge value={value} /> }, { key: 'id', label: '记录 ID' }, { key: 'eventId', label: '来源事件' }, { key: 'endpoint', label: '端点' }, { key: 'attempts', label: '尝试次数' }, { key: 'age', label: '消息龄' }, { key: 'reason', label: '原因' }]} /></Panel>
    {selectedDelivery && <DetailDrawer title={selectedDelivery.id} subtitle='脱敏投递记录' onClose={() => setSelected(null)} footer={<button className='primary-button' onClick={() => dispatch({ type: 'REPLAY_DEAD_LETTER', id: selectedDelivery.id })}><ArrowCounterClockwise size={15} /> 按原幂等键重放</button>}><InfoRow label='来源事件' value={selectedDelivery.eventId} /><InfoRow label='状态' value={selectedDelivery.status} badge={selectedDelivery.status} /><InfoRow label='失败原因' value={selectedDelivery.reason} /><InfoRow label='尝试次数' value={String(selectedDelivery.attempts)} /><InfoRow label='幂等键' value='sha256:b281…91dd' /><Panel title='尝试历史'>{['10:41:06 · ACK_TIMEOUT', '10:41:18 · ACK_TIMEOUT', '10:42:02 · SCHEMA_ENUM_REJECTED'].map((item) => <div className='audit-line' key={item}>{item}</div>)}</Panel><QualityNotice tone='warning' title='载荷不可编辑'>重放复用原事件 ID、幂等键与业务发生时间；如需修复事实，必须生成新 revision。</QualityNotice></DetailDrawer>}
    </>}
    {tab === 'delivery' && <><div className='kpi-grid four'><KpiCard icon={ShieldCheck} label='通过门禁' value='1 / 3' unit='模型' tone='green' /><KpiCard icon={Gauge} label='有效覆盖' value='92.4' unit='%' /><KpiCard icon={Warning} label='验收阻断' value='4' unit='项' tone='red' /><KpiCard icon={GitDiff} label='灰度范围' value='8' unit='路口' tone='cyan' /></div><Panel title='模型质量与交付门禁' subtitle='Precision、Recall、误报、覆盖和分场景结果共同判断'><DataTable rows={qualityRuns} columns={[{ key: 'gate', label: '门禁', render: (value) => <StatusBadge value={value} /> }, { key: 'model', label: '模型' }, { key: 'version', label: '版本' }, { key: 'precision', label: 'Precision' }, { key: 'recall', label: 'Recall' }, { key: 'coverage', label: '有效覆盖' }, { key: 'note', label: '限制与待办' }]} /></Panel></>}
    {tab === 'evidence' && <><QualityNotice tone='warning' title='证据保留与法制口径待冻结'>原件、展示副本和授权调阅分离；证据查看下沉到事件与测绘详情，本页只管理交付完整性和审计。</QualityNotice><Panel title='交付证据包'><DataTable rows={evidence} columns={[{ key: 'integrity', label: '完整性', render: (value) => <StatusBadge value={value} /> }, { key: 'id', label: '证据包' }, { key: 'event', label: '关联事实' }, { key: 'items', label: '材料项' }, { key: 'retention', label: '保留策略' }]} /></Panel></>}
  </AppShell>
}

