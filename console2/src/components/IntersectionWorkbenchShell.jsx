import { AirplaneTilt, CaretDown, ChartDonut, Check, MapPin, PencilSimple, User } from '@phosphor-icons/react'
import { Link } from 'react-router-dom'

export const intersectionWorkbenchTabs = [
  ['overview', '概览'],
  ['sources', '数据接入'],
  ['fit', '渠化拟合'],
  ['review', '复核发布'],
  ['runtime', '运行应用'],
]

const projectStages = [
  ['sources', '数据接入'],
  ['fit', '渠化拟合'],
  ['review', '复核校验'],
  ['review', '复核发布'],
  ['runtime', '运行应用'],
]

const stageProgress = {
  discovered: 12,
  road_matched: 24,
  source_ready: 40,
  keyframes_ready: 56,
  drafting: 68,
  checking: 78,
  published: 100,
  retired: 100,
}

const stageStep = {
  discovered: 0,
  road_matched: 0,
  source_ready: 1,
  keyframes_ready: 1,
  drafting: 1,
  checking: 2,
  published: 4,
  retired: 4,
}

function displayCoordinate(center) {
  if (!Array.isArray(center) || center.length < 2) return '待悬停定位'
  return center.map((value) => Number(value).toFixed(6)).join(', ')
}

export function IntersectionWorkbenchShell({
  project,
  workspace,
  mapVersion,
  activeTab,
  onTabChange,
  children,
  rightRail,
}) {
  const mapStage = mapVersion?.status === 'lane_verified'
    ? 'published'
    : mapVersion?.status === 'candidate'
      ? 'checking'
      : mapVersion?.status === 'draft'
        ? 'drafting'
        : null
  const stage = mapStage || project?.stage || 'discovered'
  const progress = stageProgress[stage] ?? 0
  const activeStep = stageStep[stage] ?? 0
  const lanes = mapVersion?.lanes?.length || 0
  const bindings = workspace?.bindings?.length || 0
  const owner = project?.created_by || 'admin'

  return <div className='intersection-workbench' data-testid='intersection-workbench'>
    <header className='workbench-topbar'>
      <Link to='/' className='workbench-brand'>
        <span><AirplaneTilt size={23} weight='fill' /></span>
        <div><strong>云瞳</strong><small>无人机交通智能感知平台</small></div>
      </Link>
      <div className='workbench-project-title'><MapPin size={19} weight='fill' /><strong>{project?.name || '路口渠化项目'}</strong></div>
      <div className='workbench-progress'><span>项目就绪度</span><b><ChartDonut size={30} weight='duotone' />{progress}%</b></div>
      <div className='workbench-version'><span>{mapVersion?.status || '待创建版本'}</span><strong>{mapVersion ? `v${mapVersion.version_no}` : '—'}</strong></div>
      <div className='workbench-owner'><span>负责人</span><strong>{owner}</strong><CaretDown size={12} /></div>
      <button className='workbench-scope'><span>济南市历下区 · 18 个项目路口</span><CaretDown size={12} /></button>
      <div className='workbench-user'><User size={18} weight='fill' /><span>admin</span></div>
    </header>

    <div className='workbench-body'>
      <aside className='workbench-archive'>
        <section>
          <header><strong>路口档案</strong><button type='button'><PencilSimple size={14} /> 编辑</button></header>
          <dl>
            <div><dt>路口名称</dt><dd>{project?.name || '未命名项目'}</dd></div>
            <div><dt>路口编码</dt><dd>{project?.inter_id || '待匹配 inter_id'}</dd></div>
            <div><dt>项目编号</dt><dd>{project?.project_id || '—'}</dd></div>
            <div><dt>中心坐标</dt><dd>{displayCoordinate(project?.center_gcj02)}</dd></div>
            <div><dt>坐标系</dt><dd>GCJ-02</dd></div>
            <div><dt>素材绑定</dt><dd>{bindings} 段</dd></div>
            <div><dt>渠化车道</dt><dd>{lanes ? `${lanes} 条` : '待拟合'}</dd></div>
            <div><dt>路网版本</dt><dd>{mapVersion?.road_data_version || workspace?.readiness?.road_data_version || '待验证'}</dd></div>
            <div><dt>项目修订</dt><dd>revision {project?.revision || 1}</dd></div>
          </dl>
        </section>
        <section className='workbench-stage-list'>
          <header><strong>项目进度</strong><span>{Math.min(activeStep + 1, 5)}/5 阶段</span></header>
          <ol>
            {projectStages.map(([tab, label], index) => <li key={`${tab}-${label}`} className={index < activeStep ? 'done' : index === activeStep ? 'active' : ''}>
              <button type='button' onClick={() => onTabChange(tab)}>
                <i>{index < activeStep ? <Check size={12} weight='bold' /> : index + 1}</i>
                <span><strong>{label}</strong><small>{index < activeStep ? '已完成' : index === activeStep ? '进行中' : '待开始'}</small></span>
              </button>
            </li>)}
          </ol>
        </section>
      </aside>

      <main className='workbench-main'>
        <nav className='workbench-tabs' aria-label='路口项目工作台'>
          {intersectionWorkbenchTabs.map(([value, label]) => <button type='button' key={value} className={activeTab === value ? 'active' : ''} onClick={() => onTabChange(value)}>{label}</button>)}
        </nav>
        <div className='workbench-content'>{children}</div>
      </main>

      <aside className='workbench-inspector'>{rightRail}</aside>
    </div>
  </div>
}
