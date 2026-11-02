# Console2 Frontend Instructions

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's context workflow when the visual source is unclear or no longer matches the current goal. When the user gives durable Console2-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

## Durable design direction

- 2026-10-19 已登记视频的首页图标不依赖路网开关或检测任务存活。无路口地图坐标时使用配对遥测中的录制位置并标“素材位置”；任务结束保留素材/最后位置，不将缓存回放遥测标为飞行中。没有真实坐标时不得伪造点位，点击仍携带source_profile_id与intersection_id。

- 2026-10-19 实时监测移除左侧来源健康卡片及右侧场景策略入口/内容，右侧BEV下直接展示近期事件及证据复核；保留内部数据新鲜度判断、顶部来源状态与工程诊断。

- 2026-10-19 本地高德同样使用深色底图；栅格模式不支持SDK mapStyle时只对基础瓦片调色，不对整张画布、路况层、轨迹或无人机标记应用滤镜。生产四维图新仍使用既有深色矢量样式。

- Production intranet maps use MineMap 2.1.0 with the site-provided key; local development keeps its existing AMap default. Preserve GCJ-02 inputs and all marker/trajectory/calibration interactions. Do not label MineMap imagery as satellite or live traffic unless those layers are explicitly configured and verified; never fall back to a public provider in the intranet profile.

- Console2 is the production TrafficAnalyzer frontend. `traffic-fly-console` is retired from build and deployment; do not add URL, token, or component compatibility layers for it.
- Visual target: dark, cinematic command-center UI with an aerial road scene as the primary canvas, translucent metric panels, a right-side live-event stream, and a bottom replay timeline.
- The login page keeps the Console 1.0 intersection-trajectory animation language (moving track points, detection-zone pulse, and live indicator) inside Console2-owned components with no legacy runtime dependency. The core fly-through remains visible when the browser reports reduced motion; only the secondary pulse and blink stop.
- Keep the original dark aerial intersection image as the login page's bottom visual layer; place the schematic traffic-flow SVG above it and the continuous vignette above both, without replacing or obscuring the source image into an unreadable flat fill.
- Product target: help traffic commanders assess intersection state, detect risk, confirm UAV health, and technically review AI events without duplicating the parent smart-traffic platform's dispatch workflow.
- Use realistic PRD concepts and vocabulary: congestion index, queues, GCJ02 alignment, TTC/PET, lane changes, accident survey, truck restriction clues, evidence references, and technical/business review.
- The main canvas defaults to the full detector-output video view, not a GIS map or inset video panel.
- The right-top secondary viewport defaults to BEV trajectory projection. Detector output and BEV must swap primary/secondary roles through a clear `切为主视图` action.
- Flight attitude data stays visible in the top intersection context bar: altitude, heading, pitch, roll, and gimbal state.
- The complete prototype covers PRD v2.1 S1–S9. `/` is the city-wide director view, while the detector-first command screen remains at `/monitoring`.
- The formal information architecture is frozen to six domains: 全域态势、智能研判、事故测绘、执法线索、飞行任务、平台治理. `/` is named 工作台首屏; `/events`, `/enforcement`, `/admin/calibration`, `/admin/integration`, and `/admin/system` are the canonical consolidated routes.
- The workbench home uses the city map as the dashboard background and surfaces UAV intersection overview, platform core metrics, prioritized intersections, in-product pending tasks, monitoring assurance, and data trust. Pending tasks never include parent-platform dispatch, handling, closure, or penalty decisions.
- Video analysis is part of `/monitoring`; `/gis` is formally named 轨迹研判, belongs to 智能研判, and includes risk hotspots; enforcement events/truck/zone capabilities are views within `/enforcement`; governance is limited to 标定中心、集成与交付、系统与身份 in the visible menu. Do not add redirects for retired frontend routes.
- Preserve a clear product boundary: this console performs AI technical review and evidence preparation; dispatch, penalty decisions, case closure, and archive authority belong to the parent platform.
- Login, monitoring, calibration, and system/identity must use Platform REST/WebSocket/MJPEG data and must never fall back to `mockData`. Other pages may keep contract-shaped deterministic mock data until their migration is explicitly scheduled. Deep links use `intersection_id`, `event_id`, `drone_id`, `task_id`, `scope`, `window`, `view`, and `tab`.
- Authentication uses `sessionStorage:uav_access_token`, `/api/v1/auth/login`, `/api/v1/auth/me`, and `/ws/realtime?access_token=...`. Backend `admin/operator/viewer` is the permission source; administrator-only role preview cannot grant access.
- Governance UI follows ADR-019 target terminology: PostgreSQL database `road9`, TimescaleDB, and `uav_` topics/channels/tables. Do not expand legacy InfluxDB, Telegraf, or Grafana flows.
- The desktop shell keeps grouped navigation, breadcrumbs, scope/time controls, freshness, role preview, and explicit loading/empty/error/stale/unauthorized states. Page title columns are not rendered; keep one screen-reader-only `h1` per ordinary page and align page-level actions with the breadcrumb row. Do not expose internal phase codes, mock/fallback explanations, contract-freeze commentary, or validation-fixture prompts as normal-page banners; retain real loading, error, permission, quality, and delivery states. Target 1440×900, with 1366×768 and 1920×1080 QA.
- Standard page workspaces must absorb unused vertical viewport space and keep only the shared shell gutter at the bottom; do not leave a large fixed-height blank band on taller screens.
- On the workbench city map, a single click on an intersection marker opens that intersection's `/monitoring?intersection_id=...` real-time detection screen. Keep the detail drawer entry available through the prioritized-intersection list.
- Keep the workbench city map as an uninterrupted canvas: do not render a separate map title/subtitle header or the former all/high-risk/degraded filter strip above it.
- The immersive monitoring screen opens both the real-time situation panel and the BEV/live-event panel by default. Preserve the existing edge collapse and pin controls so operators can reclaim canvas space manually.
- The monitoring context selector is sourced from registered UAV video SourceProfiles, not the legacy in-memory Camera 1/2 intersection registry. Keep `source_profile_id` and its bound `intersection_id` together in deep links so multiple videos at one intersection cannot resolve to the wrong pipeline.
- Workbench map drone markers represent registered UAV video SourceProfiles rather than one generic marker per intersection. Use distinct source-state colors for running, valid-but-offline, degraded, invalid, and disabled sources; clicking a marker must preserve both the source profile and intersection in the monitoring deep link.
- Clicking a workbench UAV marker with a bound source profile and intersection goes directly to real-time detection at `/monitoring`, including offline/last-position markers; automatically select that source and intersection without opening the flight/intersection detail panel first. Only markers without a usable binding retain flight details.
- Keep navigation as one shared two-level shell across every page: the narrow left rail is the six first-level business domains, and the top bar shows only the active domain's second-level pages. Workbench and immersive monitoring share this exact chrome; only their content canvases differ. Do not restore the former wide section sidebar or a collapsible tree unless the user explicitly reverses this preference again.

- 2026-10-17生产暂关闭路网：runtime-config的roadFeaturesEnabled=false隐藏平台治理一级和标定入口，
  阻止/admin/calibration及/admin/intersection-projects深链渲染。系统设置图标保留；视频/事件/轨迹研判/MineMap底图继续。
  本地未配置时默认开启。后端有同名生产开关，不能只隐藏导航而继续调用标注/导入接口。

- 2026-10-18生产媒体统一走同源鉴权MJPEG，Mac开发仍可直连；MineMap加载在应用CSS之后，必须保持画布absolute与满父容器尺寸，防止高度0。公网服务仅由明确的SDK/样式/服务/瓦片地址启用，默认内网2.1.0不变，不自动fallback。

- 2026-10-18用户要求四维图新底图统一深色：工作台/BEV/预览均使用深蓝灰矢量底图，保留道路等级、文字对比与地理标注；只调整底图图层，不对整张画布做CSS滤镜，不改变轨迹/风险/无人机标记业务配色。

- 2026-10-18 Console静态资源使用镜像专用/opt/traffic-console/html，目录755/文件644，runtime-config.js生成后644；发布测试必须覆盖旧目录拒读和umask077，并由实际页面健康检查证明可读，不能只依赖/console-health。

- 2026-10-18 用户确认BEV地图异常应自动降级，不显示服务不可用、资源加载失败或重试错误面板。SDK加载/资源/地图操作失败统一使用本地深色网格与实时轨迹：有GCJ-02则保留俯视地理轨迹，否则使用真实像素轨迹，无数据时等待更新；保留候选/选中/淡化样式，不自动切公网地图或伪造业务坐标。
