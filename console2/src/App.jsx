import { useMemo, useState } from 'react'
import {
  AirplaneTilt,
  ArrowsClockwise,
  Bell,
  Buildings,
  CaretDown,
  CaretRight,
  ChartLineUp,
  Check,
  Crosshair,
  Drone,
  Gauge,
  GridFour,
  Info,
  ListBullets,
  MapPin,
  NavigationArrow,
  Pause,
  Play,
  Plus,
  Question,
  RoadHorizon,
  ShieldWarning,
  SlidersHorizontal,
  Stack,
  Target,
  TrendUp,
  Truck,
  User,
  VideoCamera,
  Warning,
  X,
} from '@phosphor-icons/react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

const trendData = [
  { time: '10:20', value: 3.2 },
  { time: '10:25', value: 3.8 },
  { time: '10:30', value: 4.6 },
  { time: '10:35', value: 5.1 },
  { time: '10:40', value: 6.4 },
  { time: '10:45', value: 7.2 },
  { time: '10:50', value: 6.8 },
  { time: '10:55', value: 6.3 },
]

const flowData = [
  { time: '08', car: 46, truck: 18 },
  { time: '09', car: 68, truck: 24 },
  { time: '10', car: 82, truck: 31 },
  { time: '11', car: 58, truck: 22 },
  { time: '12', car: 76, truck: 26 },
  { time: '13', car: 48, truck: 18 },
]

const tracks = [
  { x: 7, a: 77, b: null },
  { x: 20, a: 72, b: null },
  { x: 34, a: 63, b: 88 },
  { x: 48, a: 54, b: 77 },
  { x: 62, a: 43, b: 65 },
  { x: 76, a: 34, b: 54 },
  { x: 91, a: 28, b: 48 },
]

const bevTracks = [
  { x: 6, north: 18, east: null, risk: null },
  { x: 18, north: 28, east: null, risk: null },
  { x: 30, north: 41, east: 83, risk: null },
  { x: 42, north: 52, east: 70, risk: 34 },
  { x: 54, north: 63, east: 58, risk: 48 },
  { x: 66, north: 74, east: 45, risk: 62 },
  { x: 78, north: 83, east: 34, risk: 77 },
  { x: 92, north: 90, east: 23, risk: 88 },
]

const initialEvents = [
  {
    id: 1,
    level: 'critical',
    type: 'conflict',
    title: '机非冲突风险升高',
    detail: '东进口右转机动车与直行非机动车轨迹交汇',
    metric: 'TTC 1.2s · PET 0.8s',
    time: '10:52:16',
  },
  {
    id: 2,
    level: 'warning',
    type: 'lane',
    title: '连续变道行为',
    detail: '北进口车辆 #A142 在 3.6 秒内跨越两条车道',
    metric: '置信度 92%',
    time: '10:49:02',
  },
  {
    id: 3,
    level: 'warning',
    type: 'congestion',
    title: '南进口排队增长',
    detail: '排队长度持续 5 分钟高于动态阈值',
    metric: '186m · +24%',
    time: '10:45:37',
  },
  {
    id: 4,
    level: 'info',
    type: 'enforcement',
    title: '货车限行线索',
    detail: '检测到货车进入电子围栏，等待业务复核',
    metric: '证据 4 项',
    time: '10:41:05',
  },
]

const navItems = [
  { id: 'overview', label: '全域态势', icon: GridFour },
  { id: 'monitor', label: '实时监测', icon: VideoCamera },
  { id: 'risk', label: '安全风险', icon: ShieldWarning },
  { id: 'survey', label: '事故测绘', icon: Crosshair },
  { id: 'enforcement', label: '执法线索', icon: Truck },
]

function MetricCard({ label, value, unit, delta, icon: Icon, tone = 'blue' }) {
  return (
    <article className='metric-card'>
      <div className={`metric-icon ${tone}`}><Icon size={17} weight='fill' /></div>
      <div>
        <div className='metric-label'>{label}</div>
        <div className='metric-value'>{value}<small>{unit}</small></div>
      </div>
      <span className={`metric-delta ${delta?.startsWith('+') ? 'up' : ''}`}>{delta}</span>
    </article>
  )
}

function EventIcon({ type }) {
  const icons = { conflict: ShieldWarning, lane: ArrowsClockwise, congestion: RoadHorizon, enforcement: Truck }
  const Icon = icons[type] || Warning
  return <Icon size={18} weight='fill' />
}

export function App() {
  const [activeNav, setActiveNav] = useState('overview')
  const [mapMode, setMapMode] = useState('trajectory')
  const [eventFilter, setEventFilter] = useState('all')
  const [events, setEvents] = useState(initialEvents)
  const [selectedEvent, setSelectedEvent] = useState(initialEvents[0])
  const [live, setLive] = useState(true)
  const [droneOpen, setDroneOpen] = useState(false)
  const [layerOpen, setLayerOpen] = useState(false)
  const [primaryView, setPrimaryView] = useState('detector')

  const filteredEvents = useMemo(
    () => eventFilter === 'all' ? events : events.filter((event) => event.level === eventFilter),
    [eventFilter, events]
  )

  const acknowledge = (id) => {
    setEvents((items) => items.filter((item) => item.id !== id))
    setSelectedEvent(null)
  }

  return (
    <div className='command-shell'>
      <header className='topbar'>
        <div className='brand'>
          <div className='brand-mark'><AirplaneTilt size={24} weight='fill' /></div>
          <div><strong>云瞳</strong><span>无人机交通智能感知平台</span></div>
        </div>
        <nav className='topnav' aria-label='主导航'>
          {['态势总览', '实时监测', '智能研判', '任务管理'].map((item, index) => (
            <button key={item} className={index === 0 ? 'active' : ''}>{item}</button>
          ))}
        </nav>
        <div className='top-actions'>
          <button className='location-button'><MapPin size={15} weight='fill' /> 济南市历下区 <CaretDown size={13} /></button>
          <div className='weather'><span>24°C</span><small>多云 · 东北风2级</small></div>
          <button className='icon-button alert-dot' aria-label='通知'><Bell size={19} /></button>
          <button className='icon-button' aria-label='帮助'><Question size={19} /></button>
          <button className='avatar' aria-label='用户菜单'><User size={18} weight='fill' /></button>
        </div>
      </header>

      <aside className='rail'>
        <button className='rail-launcher'><GridFour size={20} weight='fill' /></button>
        <div className='rail-nav'>
          {navItems.map(({ id, label, icon: Icon }) => (
            <button key={id} className={activeNav === id ? 'active' : ''} onClick={() => setActiveNav(id)} aria-label={label} title={label}>
              <Icon size={21} weight={activeNav === id ? 'fill' : 'regular'} />
              <span>{label}</span>
            </button>
          ))}
        </div>
        <button className='rail-bottom' aria-label='设置'><SlidersHorizontal size={21} /></button>
      </aside>

      <main className='workspace'>
        <img
          className={`map-image ${primaryView === 'bev' ? 'bev' : 'detector'}`}
          src={primaryView === 'bev' ? '/assets/bev-intersection-night.png' : '/assets/uav-intersection-night.png'}
          alt={primaryView === 'bev' ? 'BEV 鸟瞰轨迹主视图' : '检测器输出主视图'}
        />
        <div className='map-vignette' />

        <section className='context-bar'>
          <div className='context-title'>
            <span className='status-pulse' />
            <div><strong>小清河北路 × 水屯路</strong><small>INT_camera_1 · 实时分析中</small></div>
          </div>
          <div className='flight-attitude' aria-label='飞行姿态数据'>
            <div><span>高度</span><strong>112.4<small>m</small></strong></div>
            <div><span>航向</span><strong>037.8<small>°</small></strong></div>
            <div><span>俯仰</span><strong>-89.2<small>°</small></strong></div>
            <div><span>横滚</span><strong>+0.6<small>°</small></strong></div>
            <div><span>云台</span><strong>锁定</strong></div>
          </div>
          <div className='view-tabs'>
            {[['trajectory', '轨迹'], ['lane', '车道'], ['risk', '风险'], ['video', '原始画面']].map(([id, label]) => (
              <button key={id} className={mapMode === id ? 'active' : ''} onClick={() => setMapMode(id)}>{label}</button>
            ))}
          </div>
          <div className='context-meta'><span>GCJ02 已对齐</span><i /> <span>延迟 1.4s</span></div>
        </section>

        <div className={`main-feed-status ${primaryView}`}>
          {primaryView === 'detector' ? <VideoCamera size={14} weight='fill' /> : <Crosshair size={14} weight='fill' />}
          <span>{primaryView === 'detector' ? '检测器输出 · YOLO11 / ByteTrack' : 'BEV 鸟瞰轨迹 · ENU / GCJ02'}</span>
          <small><i /> LIVE · 29.7 FPS</small>
        </div>

        {primaryView === 'detector' && (
          <div className='main-detection-layer' aria-label='检测器识别结果叠加层'>
            <span className='detect-box detection-main-a'><em>car 0.96 · #1842</em></span>
            <span className='detect-box detection-main-b'><em>truck 0.91 · #0971</em></span>
            <span className='detect-box detection-main-c'><em>car 0.94 · #2264</em></span>
            <span className='detect-box detection-main-d'><em>non-motor 0.88 · #0416</em></span>
            <span className='detect-box detection-main-e'><em>car 0.93 · #1735</em></span>
          </div>
        )}

        <section className='left-panel'>
          <div className='panel-heading'>
            <div><span>实时态势</span><small>10:55:28 更新</small></div>
            <button aria-label='详情'><CaretRight size={17} /></button>
          </div>

          <article className='congestion-card'>
            <div className='score-ring'><strong>6.3</strong><small>/ 10</small></div>
            <div className='score-copy'><span>拥堵指数</span><strong>中度拥堵</strong><small><TrendUp size={13} /> 较昨日同期上升 8.6%</small></div>
            <Gauge size={24} weight='duotone' />
          </article>

          <div className='metrics-grid'>
            <MetricCard icon={RoadHorizon} label='断面流量' value='842' unit='辆/h' delta='+12%' />
            <MetricCard icon={ListBullets} label='最长排队' value='186' unit='m' delta='+24%' tone='amber' />
            <MetricCard icon={Gauge} label='平均车速' value='27.4' unit='km/h' delta='-8%' tone='cyan' />
            <MetricCard icon={ShieldWarning} label='活动风险' value='4' unit='起' delta='+2' tone='red' />
          </div>

          <article className='glass-card trend-card'>
            <div className='card-title'><div><strong>拥堵趋势</strong><small>最近 35 分钟</small></div><span className='chip'>预测 +5 min</span></div>
            <div className='chart-box'>
              <ResponsiveContainer width='100%' height='100%'>
                <AreaChart data={trendData} margin={{ top: 8, right: 4, left: -28, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke='rgba(151,171,206,.12)' />
                  <XAxis dataKey='time' tick={{ fill: '#8290aa', fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis domain={[0, 10]} tick={{ fill: '#8290aa', fontSize: 10 }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ background: '#111a2a', border: '1px solid #33415b', borderRadius: 8, fontSize: 11 }} />
                  <Area type='monotone' dataKey='value' stroke='#62a1ff' fill='#294c7b' fillOpacity={0.36} strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </article>

          <article className='glass-card flow-card'>
            <div className='card-title'><div><strong>车型流量</strong><small>分时统计</small></div><div className='legend'><span className='car'>机动车</span><span className='truck'>货车</span></div></div>
            <div className='chart-box small'>
              <ResponsiveContainer width='100%' height='100%'>
                <BarChart data={flowData} margin={{ top: 4, right: 0, left: -34, bottom: 0 }}>
                  <XAxis dataKey='time' tick={{ fill: '#8290aa', fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: '#8290aa', fontSize: 10 }} axisLine={false} tickLine={false} />
                  <Bar dataKey='car' fill='#6d9eff' radius={[2, 2, 0, 0]} />
                  <Bar dataKey='truck' fill='#c98cf4' radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </article>
        </section>

        <section className='map-overlay' aria-label='车辆轨迹图层'>
          <ResponsiveContainer width='100%' height='100%'>
            <LineChart data={tracks} margin={{ top: 6, right: 6, bottom: 6, left: 6 }}>
              <XAxis dataKey='x' hide domain={[0, 100]} />
              <YAxis hide domain={[0, 100]} />
              <Line type='monotone' dataKey='a' stroke='#64a5ff' strokeWidth={3} dot={{ fill: '#d8e9ff', r: 3, strokeWidth: 0 }} connectNulls />
              <Line type='monotone' dataKey='b' stroke='#ff7c62' strokeWidth={3} dot={{ fill: '#ffe2dc', r: 3, strokeWidth: 0 }} connectNulls />
            </LineChart>
          </ResponsiveContainer>
          <div className='risk-marker'><ShieldWarning size={16} weight='fill' /><span>高风险交汇</span><strong>TTC 1.2s</strong></div>
        </section>

        <div className='map-label label-north'><NavigationArrow size={15} weight='fill' /> 北进口 · 排队 124m</div>
        <div className='map-label label-east'><Target size={15} weight='fill' /> 东进口 · 流量 286辆/h</div>
        <div className='map-label label-south'><Warning size={15} weight='fill' /> 南进口 · 拥堵</div>

        <div className='map-tools'>
          <button onClick={() => setDroneOpen(!droneOpen)} className={droneOpen ? 'active' : ''} aria-label='无人机状态'><Drone size={19} /></button>
          <button onClick={() => setLayerOpen(!layerOpen)} className={layerOpen ? 'active' : ''} aria-label='图层'><Stack size={19} /></button>
          <button aria-label='放大'><Plus size={19} /></button>
          <button aria-label='定位'><Crosshair size={19} /></button>
        </div>

        {droneOpen && (
          <div className='floating-popover drone-popover'>
            <div><strong>UAV-M300-01</strong><span className='online'>在线</span></div>
            <dl><dt>高度</dt><dd>112 m</dd><dt>电量</dt><dd>78%</dd><dt>卫星</dt><dd>24</dd><dt>模式</dt><dd>悬停</dd></dl>
          </div>
        )}
        {layerOpen && (
          <div className='floating-popover layer-popover'>
            {['活动轨迹', '风险热区', '车道拓扑', '电子围栏'].map((label, index) => <label key={label}><input type='checkbox' defaultChecked={index < 3} /> <span>{label}</span></label>)}
          </div>
        )}

        <section className='right-panel'>
          <article className='camera-card'>
            <div className='camera-head'>
              <span>{primaryView === 'detector' ? <Crosshair size={16} weight='fill' /> : <VideoCamera size={16} weight='fill' />}{primaryView === 'detector' ? 'BEV 轨迹投放' : '检测器输出'}</span>
              <small><i /> {primaryView === 'detector' ? 'GCJ02 LOCK' : '29.7 FPS'}</small>
            </div>
            {primaryView === 'detector' ? (
              <div className='bev-preview'>
                <img src='/assets/bev-intersection-night.png' alt='BEV 鸟瞰轨迹投放图' />
                <div className='bev-chart'>
                  <ResponsiveContainer width='100%' height='100%'>
                    <LineChart data={bevTracks} margin={{ top: 3, right: 3, bottom: 3, left: 3 }}>
                      <XAxis dataKey='x' hide domain={[0, 100]} />
                      <YAxis hide domain={[0, 100]} />
                      <Line type='monotone' dataKey='north' stroke='#63a2ff' strokeWidth={2} dot={{ r: 2, fill: '#cfe2ff', strokeWidth: 0 }} connectNulls />
                      <Line type='monotone' dataKey='east' stroke='#58d7cb' strokeWidth={2} dot={false} connectNulls />
                      <Line type='monotone' dataKey='risk' stroke='#ff7762' strokeWidth={2} dot={{ r: 2, fill: '#ffd2cb', strokeWidth: 0 }} connectNulls />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                <span className='bev-origin'><Crosshair size={13} weight='bold' /> ENU 0,0</span>
              </div>
            ) : (
              <div className='detector-preview'>
                <img src='/assets/uav-intersection-night.png' alt='检测器输出视频流预览' />
                <span className='detect-box preview-box-a'><em>car 0.96</em></span>
                <span className='detect-box preview-box-b'><em>truck 0.91</em></span>
                <span className='detect-box preview-box-c'><em>non-motor 0.88</em></span>
              </div>
            )}
            <div className='camera-foot'>
              <span>{primaryView === 'detector' ? '活动轨迹 27 · 世界坐标已锁定' : '目标 37 · 轨迹 31 · P95 46ms'}</span>
              <button className='swap-view' onClick={() => setPrimaryView(primaryView === 'detector' ? 'bev' : 'detector')}><ArrowsClockwise size={14} weight='bold' /> 切为主视图</button>
            </div>
          </article>

          <div className='events-head'>
            <div><strong>实时事件</strong><span>{events.length}</span></div>
            <button><ListBullets size={16} /> 全部事件</button>
          </div>
          <div className='event-filters'>
            {[['all', '全部'], ['critical', '高风险'], ['warning', '关注']].map(([id, label]) => (
              <button key={id} className={eventFilter === id ? 'active' : ''} onClick={() => setEventFilter(id)}>{label}</button>
            ))}
          </div>
          <div className='event-list'>
            {filteredEvents.map((event) => (
              <button key={event.id} className={`event-card ${event.level} ${selectedEvent?.id === event.id ? 'selected' : ''}`} onClick={() => setSelectedEvent(event)}>
                <span className='event-icon'><EventIcon type={event.type} /></span>
                <span className='event-copy'><strong>{event.title}</strong><small>{event.detail}</small><span>{event.metric}</span></span>
                <time>{event.time}</time>
              </button>
            ))}
          </div>
        </section>

        {selectedEvent && (
          <section className='event-detail'>
            <div className='detail-accent'><EventIcon type={selectedEvent.type} /></div>
            <div className='detail-copy'><span>AI 事件研判</span><strong>{selectedEvent.title}</strong><small>系统已关联 2 条轨迹、1 段视频和 GCJ02 坐标，等待技术复核。</small></div>
            <div className='detail-metrics'><div><span>TTC</span><strong>1.2s</strong></div><div><span>PET</span><strong>0.8s</strong></div><div><span>风险分</span><strong>86</strong></div></div>
            <button className='secondary' onClick={() => setSelectedEvent(null)}><X size={15} /> 关闭</button>
            <button className='primary' onClick={() => acknowledge(selectedEvent.id)}><Check size={15} weight='bold' /> 标记已复核</button>
          </section>
        )}

        <section className='timeline'>
          <div className='timeline-controls'><button onClick={() => setLive(!live)}>{live ? <Pause size={15} weight='fill' /> : <Play size={15} weight='fill' />}</button><strong>{live ? '实时' : '回看'}</strong><span>10:55:28</span></div>
          <div className='timeline-track'>
            {Array.from({ length: 42 }).map((_, index) => <i key={index} className={index % 11 === 0 ? 'critical' : index % 7 === 0 ? 'warning' : ''} />)}
            <div className='playhead' style={{ left: live ? '92%' : '68%' }} />
          </div>
          <div className='timeline-range'><span>10:00</span><span>10:15</span><span>10:30</span><span>10:45</span><span>现在</span></div>
        </section>
      </main>
    </div>
  )
}
