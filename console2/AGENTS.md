# Console2 Frontend Instructions

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's context workflow when the visual source is unclear or no longer matches the current goal. When the user gives durable Console2-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

## Durable design direction

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
- Keep navigation as one shared two-level shell across every page: the narrow left rail is the six first-level business domains, and the top bar shows only the active domain's second-level pages. Workbench and immersive monitoring share this exact chrome; only their content canvases differ. Do not restore the former wide section sidebar or a collapsible tree unless the user explicitly reverses this preference again.
