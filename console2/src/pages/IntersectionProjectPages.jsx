import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowRight, CheckCircle, FolderPlus, MapPin, VideoCamera, WarningCircle } from '@phosphor-icons/react'
import { AppShell } from '../components/AppShell'
import { ChannelizedMapPreview } from '../components/ChannelizedMapPreview'
import { CityMap } from '../components/CityMap'
import { DataTable, InfoRow, PageHeader, Panel, QualityNotice, StatusBadge } from '../components/Common'
import { IntersectionWorkbenchShell } from '../components/IntersectionWorkbenchShell'
import { apiErrorMessage, platformApi } from '../lib/api'

const stageLabels = {
  discovered: '待匹配路网', road_matched: '路网已匹配', source_ready: '素材已绑定',
  keyframes_ready: '关键帧就绪', drafting: '拟合中', checking: '检查中', published: '已发布', retired: '已退役',
}
const nextActionLabels = {
  match_road_context: '匹配正式路网', verify_road_context: '验证 RoadContext',
  connect_video: '接入并校验视频', extract_keyframes: '抽取正拍关键帧',
  continue_draft: '继续渠化拟合', operate_runtime: '进入运行应用',
}

export function IntersectionProjectsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [mode, setMode] = useState('')
  const [view, setView] = useState('list')
  const [form, setForm] = useState({ name: '', inter_id: '', source_profile_id: '', drone_id: '', video_location: '', telemetry_location: '', telemetry_type: 'srt', video_file: null, telemetry_file: null })
  const projectsQuery = useQuery({ queryKey: ['intersection-projects'], queryFn: platformApi.intersectionProjects })
  const sourcesQuery = useQuery({ queryKey: ['sources'], queryFn: platformApi.sources })
  const dronesQuery = useQuery({ queryKey: ['drones'], queryFn: platformApi.drones })
  const projects = Array.isArray(projectsQuery.data) ? projectsQuery.data : []
  const sources = Array.isArray(sourcesQuery.data) ? sourcesQuery.data : []
  const drones = Array.isArray(dronesQuery.data) ? dronesQuery.data : []
  const createProject = useMutation({
    mutationFn: () => platformApi.createIntersectionProject({ name: form.name.trim(), inter_id: form.inter_id.trim() || null }),
    onSuccess: (project) => { queryClient.invalidateQueries({ queryKey: ['intersection-projects'] }); navigate(`/admin/intersection-projects/${project.project_id}`) },
  })
  const ingest = useMutation({
    mutationFn: () => form.video_file
      ? platformApi.uploadVideoIngestion({ video: form.video_file, telemetry: form.telemetry_file, droneId: form.drone_id })
      : platformApi.createVideoIngestion({ source_profile_id: form.source_profile_id || null, drone_id: form.drone_id || null, video_location: form.video_location || null, telemetry_location: form.telemetry_location || null, telemetry_type: form.telemetry_location ? form.telemetry_type : null }),
    onSuccess: (job) => navigate(`/admin/intersection-projects/discover?job_id=${encodeURIComponent(job.job_id)}`),
  })
  const error = projectsQuery.error || createProject.error || ingest.error
  return <AppShell pageTitle='路口项目库'>
    <PageHeader title='路口项目库' actions={<div className='project-primary-actions'>
      <button className='primary-button' onClick={() => setMode('ingest')}><VideoCamera size={16} /> 接入视频并发现路口</button>
      <button className='secondary-button' onClick={() => setMode('project')}><FolderPlus size={16} /> 新建路口项目</button>
    </div>} />
    <div className='project-hero'><div><span>路口渠化工作台</span><h2>从视频发现，或从路口建档开始</h2><p>两条路径最终汇聚到同一个项目、SourceProfile 与分段素材绑定。</p></div><div className='project-route-cards'><article><VideoCamera size={22} /><strong>视频优先</strong><span>识别悬停坐标并匹配路口</span></article><article><MapPin size={22} /><strong>路口优先</strong><span>建档后校验接入素材归属</span></article></div></div>
    {error && <QualityNotice tone='danger' title='操作未完成'>{apiErrorMessage(error)}</QualityNotice>}
    {mode && <Panel title={mode === 'ingest' ? '接入视频并发现路口' : '新建路口项目'} subtitle={mode === 'ingest' ? '先解析遥测，再由 admin 确认路口归属' : '支持正式 inter_id；也可先创建待匹配项目'}>
      <div className='project-form'>
        {mode === 'project' ? <><label>项目名称<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder='例如：小清河北路 × 水屯路' /></label><label>正式 inter_id（可选）<input value={form.inter_id} onChange={(event) => setForm({ ...form, inter_id: event.target.value })} /></label></> : <>
          <label>已登记 SourceProfile<select value={form.source_profile_id} onChange={(event) => setForm({ ...form, source_profile_id: event.target.value, video_file: null, telemetry_file: null })}><option value=''>上传或服务器素材</option>{sources.map((source) => <option key={source.profile_id} value={source.profile_id}>{source.display_name || source.profile_id}</option>)}</select></label>
          {!form.source_profile_id && <><label>登记无人机<select value={form.drone_id} onChange={(event) => setForm({ ...form, drone_id: event.target.value })}><option value=''>选择无人机</option>{drones.map((drone) => <option key={drone.id} value={drone.id}>{drone.name || drone.id}</option>)}</select></label><label>浏览器上传 MP4<input type='file' accept='.mp4,video/mp4' onChange={(event) => setForm({ ...form, video_file: event.target.files?.[0] || null, video_location: '' })} /></label><label>SRT / JSON（可选）<input type='file' accept='.srt,.json,.txt' onChange={(event) => setForm({ ...form, telemetry_file: event.target.files?.[0] || null })} /></label><label>或服务器 MP4 路径<input value={form.video_location} onChange={(event) => setForm({ ...form, video_location: event.target.value, video_file: null })} placeholder='批准素材目录中的 MP4' /></label><label>服务器遥测路径（可空）<input value={form.telemetry_location} onChange={(event) => setForm({ ...form, telemetry_location: event.target.value, telemetry_file: null })} placeholder='批准素材目录中的 SRT / JSON' /></label><label>遥测类型<select value={form.telemetry_type} onChange={(event) => setForm({ ...form, telemetry_type: event.target.value })}><option value='srt'>DJI SRT</option><option value='json'>DJI JSON</option></select></label></>}
        </>}
        <div className='project-form-actions'><button className='text-button' onClick={() => setMode('')}>取消</button><button className='primary-button' disabled={mode === 'project' ? !form.name.trim() : (!form.source_profile_id && (!(form.video_file || form.video_location) || !form.drone_id))} onClick={() => mode === 'project' ? createProject.mutate() : ingest.mutate()}>{mode === 'project' ? '创建并进入工作台' : '解析并发现路口'}</button></div>
      </div>
    </Panel>}
    <Panel title={`路口项目 · ${projects.length}`} subtitle='阶段只表达业务就绪度，不把候选路网当作已验证事实' action={<div className='project-view-toggle'><button className={view === 'map' ? 'active' : ''} onClick={() => setView('map')}>地图</button><button className={view === 'list' ? 'active' : ''} onClick={() => setView('list')}>列表</button></div>}>
      {view === 'map' && <div className='project-map-view'><CityMap points={projects.flatMap((item) => item.center_gcj02 ? [{ id: item.project_id, name: item.name, lon: item.center_gcj02[0], lat: item.center_gcj02[1], risk: item.stage === 'published' ? 'normal' : 'warning' }] : [])} onSelect={(item) => navigate(`/admin/intersection-projects/${item.id}`)} coordinateLabel='路口项目 · GCJ-02' /></div>}
      {view === 'list' && <DataTable rowKey='project_id' rows={projects.map((item) => ({ ...item, stageLabel: stageLabels[item.stage] || item.stage, center: item.center_gcj02?.map((value) => Number(value).toFixed(6)).join(', ') || '待定位' }))} onRowClick={(row) => navigate(`/admin/intersection-projects/${row.project_id}`)} columns={[
        { key: 'stage', label: '阶段', render: (value, row) => <StatusBadge value={value}>{row.stageLabel}</StatusBadge> },
        { key: 'name', label: '项目' }, { key: 'inter_id', label: '正式 inter_id', render: (value) => value || '待匹配' },
        { key: 'center', label: 'GCJ-02 中心' }, { key: 'revision', label: '修订' },
      ]} empty='尚无路口项目；可从视频发现或直接建档。' />}
    </Panel>
  </AppShell>
}

export function IntersectionProjectWorkspacePage() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const [tab, setTab] = useState(() => new URLSearchParams(window.location.search).get('tab') || 'overview')
  const [compareOpen, setCompareOpen] = useState(false)
  const [compareMapId, setCompareMapId] = useState('')
  const workspaceQuery = useQuery({ queryKey: ['intersection-project-workspace', projectId], queryFn: () => platformApi.intersectionProjectWorkspace(projectId), enabled: projectId !== 'discover' })
  const workspace = workspaceQuery.data
  const project = workspace?.project
  const maps = [...(workspace?.channelized_maps || [])].sort((left, right) => right.version_no - left.version_no)
  const activeMapSummary = maps.find((item) => item.status === 'lane_verified') || maps[0] || null
  const activeMapQuery = useQuery({
    queryKey: ['channelized-map', activeMapSummary?.id],
    queryFn: () => platformApi.channelizedMap(activeMapSummary.id),
    enabled: Boolean(activeMapSummary?.id),
  })
  const activeMap = activeMapQuery.data || activeMapSummary
  const compareCandidates = maps.filter((item) => item.id !== activeMapSummary?.id)
  const selectedCompareMapId = compareMapId || compareCandidates[0]?.id || ''
  const compareMapQuery = useQuery({
    queryKey: ['channelized-map', selectedCompareMapId],
    queryFn: () => platformApi.channelizedMap(selectedCompareMapId),
    enabled: Boolean(compareOpen && selectedCompareMapId),
  })
  const previewMap = compareOpen && compareMapQuery.data ? compareMapQuery.data : activeMap
  if (projectId === 'discover') return <VideoDiscoveryResolution />
  if (workspaceQuery.error) return <AppShell pageTitle='项目不可用'><QualityNotice tone='danger' title='项目不可用'>{apiErrorMessage(workspaceQuery.error)}</QualityNotice></AppShell>
  if (!workspace) return <div className='workbench-loading'>正在载入路口项目工作台…</div>

  const handleTabChange = (value) => {
    if (value === 'fit') {
      navigate(`/admin/calibration/editor?inter_id=${encodeURIComponent(project.inter_id || '')}&project_id=${encodeURIComponent(project.project_id)}`)
      return
    }
    setTab(value)
    navigate(`/admin/intersection-projects/${project.project_id}?tab=${value}`, { replace: true })
  }
  const handleNextAction = () => {
    if (workspace.readiness.next_action === 'operate_runtime') handleTabChange('runtime')
    else if (workspace.readiness.next_action === 'connect_video') handleTabChange('sources')
    else handleTabChange('fit')
  }

  return <IntersectionWorkbenchShell
    project={project}
    workspace={workspace}
    mapVersion={activeMap}
    activeTab={tab}
    onTabChange={handleTabChange}
    rightRail={<WorkspaceInspector workspace={workspace} mapVersion={activeMap} onNextAction={handleNextAction} />}
  >
    {tab === 'overview' && <div className='workbench-overview'>
      <section className='workbench-canvas-card'>
        <header><div><select aria-label='预览底图' value='map' onChange={() => {}}><option value='image' disabled>正拍图</option><option value='map'>GCJ-02 路网</option></select><button type='button' className='secondary-button' aria-expanded={compareOpen} onClick={() => setCompareOpen((value) => !value)}>{compareOpen ? '收起对比' : '版本对比'}</button></div><span>{activeMap ? `${activeMap.status} · v${activeMap.version_no}` : '尚无渠化版本'}</span></header>
        <div className='workbench-map-stage'>
          <ChannelizedMapPreview mapVersion={previewMap} />
          {compareOpen && <div className='workbench-version-compare' role='region' aria-label='版本对比面板'>
            <strong>版本对比</strong>
            <span>当前：{activeMap ? `v${activeMap.version_no} · ${activeMap.status}` : '无版本'}</span>
            {compareCandidates.length ? <label>对照：<select aria-label='对照版本' value={selectedCompareMapId} onChange={(event) => setCompareMapId(event.target.value)}>{compareCandidates.map((item) => <option key={item.id} value={item.id}>v{item.version_no} · {item.status}</option>)}</select></label> : <span>暂无可对比历史版本</span>}
          </div>}
        </div>
      </section>
      <section className='workbench-next-action'>
        <div><span>当前状态</span><strong>{stageLabels[project.stage] || project.stage}</strong></div>
        <div><span>下一步</span><strong>{nextActionLabels[workspace.readiness.next_action] || workspace.readiness.next_action}</strong></div>
        <div><span>操作指引</span><p>核对正拍影像、GCJ-02 路网与质量门禁后进入下一处理环节。</p></div>
        <button type='button' className='primary-button' onClick={handleNextAction}>去处理 <ArrowRight size={15} /></button>
      </section>
    </div>}
    {tab === 'sources' && <Panel title='视频与遥测绑定' action={<button className='primary-button' onClick={() => navigate(`/admin/intersection-projects/discover?project_id=${project.project_id}`)}>接入并校验新视频</button>}><DataTable rows={workspace.bindings.map((item) => ({ ...item, id: item.binding_id, range: `${item.start_offset_sec}s – ${item.end_offset_sec ?? '结束'}` }))} columns={[{ key: 'binding_quality', label: '质量', render: (value) => <StatusBadge value={value} /> }, { key: 'source_profile_id', label: 'SourceProfile' }, { key: 'range', label: '视频范围' }, { key: 'inter_id', label: '路口' }]} /></Panel>}
    {tab === 'review' && <CalibrationReviewPanel workspace={workspace} projectId={projectId} />}
    {tab === 'runtime' && <Panel title='运行应用'><InfoRow label='当前 lane_verified' value={workspace.channelized_maps.find((item) => item.status === 'lane_verified')?.id || '尚未发布'} /><InfoRow label='Runtime 规则' value='只接受不可变 lane_verified Bundle' /></Panel>}
  </IntersectionWorkbenchShell>
}

function WorkspaceInspector({ workspace, mapVersion, onNextAction }) {
  const quality = mapVersion?.quality || {}
  const isPublished = mapVersion?.status === 'lane_verified'
  const checks = [
    ['数据完整性', isPublished || Boolean(workspace.readiness.formal_intersection && workspace.readiness.source_bound)],
    ['视觉配准精度', isPublished || mapVersion?.visual_registration?.status === 'verified'],
    ['车道拓扑一致性', isPublished || Number(quality.topology_errors || 0) === 0 && Boolean(mapVersion)],
    ['渠化要素完整性', isPublished || Boolean(mapVersion?.geometry_gcj02?.features)],
    ['正式路网验证', isPublished || workspace.readiness.road_context_verified],
    ['发布前人工复核', isPublished || mapVersion?.latest_review?.result === 'approved'],
  ]
  const passed = checks.filter(([, value]) => value).length
  return <>
    <section className='workbench-side-card'>
      <header><strong>待办任务</strong><span>{workspace.readiness.next_action === 'operate_runtime' ? 0 : 1}</span></header>
      <button type='button' className='workbench-task' onClick={onNextAction}><i /><div><strong>{nextActionLabels[workspace.readiness.next_action] || '继续渠化拟合'}</strong><span>依据当前项目就绪度生成的唯一下一步</span></div><b>去处理</b></button>
    </section>
    <section className='workbench-side-card'>
      <header><strong>质量门禁</strong><span className='quality-score'>{passed}/{checks.length} 通过</span></header>
      <ul className='workbench-checks'>{checks.map(([label, value]) => <li key={label} className={value ? 'passed' : ''}>{value ? <CheckCircle size={14} weight='fill' /> : <WarningCircle size={14} />}<span>{label}</span><b>{value ? '通过' : '待处理'}</b></li>)}</ul>
    </section>
    <section className='workbench-side-card'>
      <header><strong>版本状态</strong></header>
      <dl className='workbench-version-list'><div><dt>当前版本</dt><dd>{mapVersion ? `${mapVersion.status} v${mapVersion.version_no}` : '尚未创建'}</dd></div><div><dt>路网版本</dt><dd>{mapVersion?.road_data_version || '待验证'}</dd></div><div><dt>历史版本</dt><dd>{workspace.channelized_maps.length} 个</dd></div></dl>
    </section>
  </>
}

const calibrationChecks = [
  ['imagery_map_alignment', '影像与地图对照'],
  ['version_diff', '版本差异'],
  ['registration_error', '配准误差'],
  ['topology', '拓扑检查'],
  ['lane_directions', '车道方向'],
  ['stop_lines', '停止线'],
]

function CalibrationReviewPanel({ workspace, projectId }) {
  const queryClient = useQueryClient()
  const [checklist, setChecklist] = useState(Object.fromEntries(calibrationChecks.map(([key]) => [key, false])))
  const [comment, setComment] = useState('')
  const [message, setMessage] = useState('')
  const maps = [...(workspace.channelized_maps || [])].sort((left, right) => right.version_no - left.version_no)
  const active = maps.find((item) => ['draft', 'candidate'].includes(item.status)) || maps[0]
  const refresh = (text) => {
    setMessage(text)
    queryClient.invalidateQueries({ queryKey: ['intersection-project-workspace', projectId] })
  }
  const submit = useMutation({ mutationFn: () => platformApi.submitChannelizedMapCheck(active.id), onSuccess: () => refresh('草稿已提交检查。') })
  const approve = useMutation({
    mutationFn: () => platformApi.checkChannelizedMap(active.id, { result: 'approved', issues: [], checklist, comment: comment || 'admin 完成六项质量检查' }),
    onSuccess: () => refresh('六项质量检查已通过。'),
  })
  const reject = useMutation({
    mutationFn: () => platformApi.checkChannelizedMap(active.id, { result: 'rejected', issues: [{ code: 'admin_review_returned', message: comment || '需要继续修改' }], checklist, comment: comment || '退回修改' }),
    onSuccess: () => refresh('版本已退回修改。'),
  })
  const publish = useMutation({ mutationFn: () => platformApi.publishChannelizedMap(active.id, 'lane_verified'), onSuccess: () => refresh('新版本已发布为 lane_verified。') })
  const error = submit.error || approve.error || reject.error || publish.error
  if (!active) return <Panel title='检查与发布'><QualityNotice tone='info' title='尚无渠化版本'>请先进入渠化拟合工作室创建草稿。</QualityNotice></Panel>
  const reviewResult = active.latest_review?.result
  const allChecked = calibrationChecks.every(([key]) => checklist[key])
  return <Panel title='检查与发布' subtitle={`V${active.version_no} · ${active.id}`}>
    <QualityNotice tone='info' title='当前阶段统一由 admin 操作'>保存草稿 → 提交检查 → 检查通过/退回 → 发布；用户、版本、清单与结果持续审计。</QualityNotice>
    {error && <QualityNotice tone='danger' title='操作未完成'>{apiErrorMessage(error)}</QualityNotice>}
    {message && <QualityNotice tone='success' title='操作成功'>{message}</QualityNotice>}
    <div className='project-overview-grid'>
      <div><InfoRow label='版本状态' value={active.status} badge={active.status} /><InfoRow label='最近检查' value={reviewResult || '尚未提交'} /><InfoRow label='配准 P95' value={`${active.quality?.control_point_residuals?.p95_m ?? '—'} m`} /><InfoRow label='车道 / 拓扑问题' value={`${active.quality?.lane_count ?? 0} / ${active.quality?.topology_errors ?? '—'}`} /></div>
      <div className='project-form'><strong>发布前六项质量门禁</strong>{calibrationChecks.map(([key, label]) => <label key={key}><input type='checkbox' checked={checklist[key]} onChange={(event) => setChecklist({ ...checklist, [key]: event.target.checked })} /> {label}</label>)}<label>检查意见<textarea value={comment} onChange={(event) => setComment(event.target.value)} placeholder='通过说明或退回原因' /></label></div>
    </div>
    <div className='project-primary-actions'>
      <button className='secondary-button' disabled={!['draft', 'candidate'].includes(active.status) || reviewResult === 'submitted' || submit.isPending} onClick={() => submit.mutate()}>提交检查</button>
      <button className='primary-button' disabled={reviewResult !== 'submitted' || !allChecked || approve.isPending} onClick={() => approve.mutate()}>检查通过</button>
      <button className='secondary-button' disabled={reviewResult !== 'submitted' || reject.isPending} onClick={() => reject.mutate()}>退回修改</button>
      <button className='primary-button' disabled={reviewResult !== 'approved' || active.status !== 'candidate' || publish.isPending} onClick={() => publish.mutate()}>发布 lane_verified</button>
    </div>
  </Panel>
}

function VideoDiscoveryResolution() {
  const navigate = useNavigate()
  const jobId = new URLSearchParams(window.location.search).get('job_id')
  const expectedProjectId = new URLSearchParams(window.location.search).get('project_id')
  const jobQuery = useQuery({ queryKey: ['video-ingestion', jobId], queryFn: () => platformApi.videoIngestion(jobId), enabled: Boolean(jobId) })
  const job = jobQuery.data
  const segment = job?.hover_evidence?.hover_segments?.[0]
  const candidate = segment?.candidates?.[0]
  const resolve = useMutation({
    mutationFn: () => platformApi.resolveVideoIngestion(jobId, expectedProjectId
      ? { action: 'bind_expected_project', segment_index: 0 }
      : { action: 'create_project', segment_index: 0, inter_id: candidate?.inter_id || null, project_name: candidate?.name || '视频发现路口' }),
    onSuccess: (result) => navigate(`/admin/intersection-projects/${result.project.project_id}`),
  })
  if (!jobId) return <ProjectVideoIngestionStart projectId={expectedProjectId} />
  return <AppShell pageTitle='视频接入向导'><PageHeader title='视频接入向导' actions={<button className='secondary-button' onClick={() => navigate('/admin/intersection-projects')}>取消接入</button>} />
    <Panel title='识别悬停段与路口候选' subtitle='WGS84 原始坐标只作证据，GCJ-02 中心用于路网匹配'>
      {jobQuery.isLoading && <div className='live-state'>正在读取接入结果…</div>}
      {(jobQuery.error || resolve.error) && <QualityNotice tone='danger' title='无法确认'>{apiErrorMessage(jobQuery.error || resolve.error)}</QualityNotice>}
      {job && <><WorkflowSteps steps={['选择素材', '解析遥测', '识别悬停', '核对 84/02', '匹配路口', '建档/绑定', '进入抽帧']} active={5} /><div className='project-evidence-grid'><InfoRow label='任务状态' value={job.status} badge={job.status} /><InfoRow label='接入路径' value={job.mode === 'video_first' ? '视频优先' : '路口优先'} /><InfoRow label='WGS84 中心' value={segment?.center_wgs84?.join(', ') || '无有效遥测'} /><InfoRow label='GCJ-02 中心' value={segment?.center_gcj02?.join(', ') || '需人工确认'} /><InfoRow label='最近候选' value={candidate ? `${candidate.name} · ${candidate.distance_m}m` : '无明确候选'} /><InfoRow label='绑定质量' value={segment?.confidence || 'manual_unverified'} /></div><button className='primary-button' disabled={(!job.source_profile_id && !(job.drone_id && job.video_location)) || resolve.isPending} onClick={() => resolve.mutate()}>{expectedProjectId ? '确认素材属于当前项目' : '确认候选并创建项目'}</button>{!job.source_profile_id && <QualityNotice tone='info' title='确认时创建 SourceProfile'>上传素材将在确认事务中完成 SourceProfile、项目（需要时）和分段绑定；无遥测标记为 manual_unverified。</QualityNotice>}</>}
    </Panel>
  </AppShell>
}

function ProjectVideoIngestionStart({ projectId }) {
  const navigate = useNavigate()
  const [sourceProfileId, setSourceProfileId] = useState('')
  const [droneId, setDroneId] = useState('')
  const [video, setVideo] = useState(null)
  const [telemetry, setTelemetry] = useState(null)
  const sourcesQuery = useQuery({ queryKey: ['sources'], queryFn: platformApi.sources })
  const dronesQuery = useQuery({ queryKey: ['drones'], queryFn: platformApi.drones })
  const ingest = useMutation({
    mutationFn: () => video
      ? platformApi.uploadVideoIngestion({ video, telemetry, droneId, projectId })
      : platformApi.createVideoIngestion({ project_id: projectId, source_profile_id: sourceProfileId }),
    onSuccess: (job) => navigate(`/admin/intersection-projects/discover?project_id=${encodeURIComponent(projectId)}&job_id=${encodeURIComponent(job.job_id)}`),
  })
  const sources = Array.isArray(sourcesQuery.data) ? sourcesQuery.data : []
  const drones = Array.isArray(dronesQuery.data) ? dronesQuery.data : []
  return <AppShell pageTitle='为路口接入视频'><PageHeader title='为路口接入视频' actions={<button className='secondary-button' onClick={() => navigate(`/admin/intersection-projects/${projectId}`)}>返回项目</button>} />
    <Panel title='选择素材' subtitle='即使从路口项目开始，仍执行完整悬停识别和坐标归属校验'>
      {ingest.error && <QualityNotice tone='danger' title='接入失败'>{apiErrorMessage(ingest.error)}</QualityNotice>}
      <div className='project-form'><label>已登记 SourceProfile<select value={sourceProfileId} onChange={(event) => { setSourceProfileId(event.target.value); setVideo(null); setTelemetry(null) }}><option value=''>浏览器上传</option>{sources.map((source) => <option key={source.profile_id} value={source.profile_id}>{source.display_name || source.profile_id}</option>)}</select></label>{!sourceProfileId && <><label>登记无人机<select value={droneId} onChange={(event) => setDroneId(event.target.value)}><option value=''>选择无人机</option>{drones.map((drone) => <option key={drone.id} value={drone.id}>{drone.name || drone.id}</option>)}</select></label><label>MP4<input type='file' accept='.mp4,video/mp4' onChange={(event) => setVideo(event.target.files?.[0] || null)} /></label><label>SRT / JSON（可选）<input type='file' accept='.srt,.json,.txt' onChange={(event) => setTelemetry(event.target.files?.[0] || null)} /></label></>}<div className='project-form-actions'><button className='primary-button' disabled={ingest.isPending || (!sourceProfileId && (!video || !droneId))} onClick={() => ingest.mutate()}>解析并校验所属路口</button></div></div>
    </Panel>
  </AppShell>
}
