# Console 2 — 云瞳生产前端

`console2/` 是 TrafficAnalyzer 当前唯一的 Web Console。它直接接管登录、系统与身份、标定中心和实时监测；旧 `traffic-fly-console/` 不再参与构建、部署或 URL 兼容。

## 当前数据边界

- 真实模块：`/login`、`/monitoring`、`/admin/calibration`、`/admin/system`。
- 真实数据来源：Platform `/api/v1`、`/ws/realtime`，以及 Pipeline/Mission 登记的检测器 `video_stream_url` MJPEG 直连。
- 其余工作台、轨迹研判、AI 事件、事故测绘、执法线索、飞行任务和集成交付页面暂时保留契约化模拟数据。
- 四个真实模块请求失败时只显示 `loading/empty/stale/error/unauthorized`，不回退模拟数据。
- 数据架构遵循 ADR-019：目标数据库为 PostgreSQL `road9` + TimescaleDB，内部 Topic、消息类型和 WebSocket channel 使用 `uav_` 前缀；当前未完成改名的数据链路由实时消息适配器双识别。

## 正式路由

| 功能 | 路由 |
|---|---|
| 登录 | `/login` |
| 工作台首屏 | `/` |
| 实时监测 | `/monitoring?intersection_id=...&view=detector|bev|raw` |
| 轨迹研判 | `/gis` |
| AI 事件中心 | `/events` |
| 测绘任务 | `/survey` |
| 执法工作台 | `/enforcement` |
| 无人机与计划 | `/drones` |
| 标定中心 | `/admin/calibration?tab=records|lanes|bindings|coordinates` |
| 集成与交付 | `/admin/integration` |
| 系统与身份 | `/admin/system?tab=system|identity` |

没有 `/sign-in`、`/video`、`/calibration`、`/admin`、`/users`、`/alerts` 或 `/reports` 等兼容路由。未知地址在已登录时回到 `/`，未登录时进入 `/login`。

## 认证与权限

- 登录调用 `POST /api/v1/auth/login`，启动恢复调用 `GET /api/v1/auth/me`。
- JWT 仅存放在 `sessionStorage:uav_access_token`；API 自动附加 Bearer Token，401 会清除会话。
- 未登录访问业务路由会跳到 `/login?redirect=...`，且 `redirect` 只接受站内绝对路径。
- 后端角色是授权真源：`admin → 管理员`、`operator → 交通指挥员`、`viewer → 数据分析员`。
- 管理员可使用现有角色预览检查导航，但预览不会改变后端权限。
- Platform 对 `/api/v1/system`、`/api/v1/users` 和 `/api/v1/calibration` 执行管理员校验。

## 本地运行

先启动 Platform，再启动前端：

```bash
cd platform
python scripts/run_local.py

cd ../console2
npm install
npm run dev
```

Vite 只代理 `/api` 和 `/ws` 到 `http://localhost:8000`。监控屏和无人机屏直接使用 Platform 返回的 `video_stream_url`，本机默认为检测器 `http://127.0.0.1:{video_port}/video`；UAT/生产需配置浏览器可达的 HTTPS 地址模板。

## 验证

```bash
npm test
npm run build
```

当前前端回归覆盖统一两级页面壳、正式路由、角色权限、登录成功/失败/恢复/失效、安全跳转、监控 REST/WS/检测器直连 MJPEG、首帧重试、监控与无人机双屏地址一致性、消息重连/退订/去重、告警确认、系统部分失败、只读身份、标注自然尺寸坐标与多车道保存，以及保留的原型工作流。桌面设计基线为 1440×900；1366×768 与 1920×1080 的浏览器像素验收记录在 `design-qa.md`。

## 结构

- `src/auth/`：会话恢复、登录、退出和角色映射。
- `src/lib/api.js`：统一 Platform API Client。
- `src/lib/realtime.js`、`src/hooks/useWebSocket.js`：WebSocket 重连、订阅、规范化和去重。
- `src/RouterApp.jsx`：正式路由、认证守卫和权限边界。
- `src/components/AppShell.jsx`：统一的左侧一级业务域和顶部二级导航。
- `src/App.jsx`：真实实时监测画布。
- `src/pages/AdminPages.jsx`：真实标定中心、系统与身份，以及仍为模拟的集成交付。
- `src/data/mockData.js`：仅供尚未迁移的页面使用。
- `Dockerfile`、`nginx.conf`：Console2 生产构建和反向代理入口。
