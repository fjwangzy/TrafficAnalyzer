# Console 2 四模块迁移 Design QA

## Evidence

- source visual truth path: `/var/folders/pn/nqzgl4zn26v8_864_4nws7_r0000gn/T/codex-clipboard-26f15801-ebd3-42d1-bf1e-1d6304c61d6a.png`
- source interaction truth: 当前任务中的 Browser 标注，要求“左侧一级、上方二级”，并统一工作台与实时监测页面框架
- implementation route: `http://localhost:4173/login`、`/monitoring`、`/admin/calibration`、`/admin/system`
- implementation screenshot path: 未生成；本轮再次连接 Codex 应用内浏览器时初始化失败（`Cannot redefine property: process`）
- intended viewport: 1305×892（标注视口）；补充目标 1366×768、1440×900、1920×1080
- state: 管理员、全域态势；分别选中“工作台首屏”和“实时监测”

## Findings

- [P0] 当前四模块迁移缺少浏览器渲染证据
  - Location: `/login`、`/monitoring`、`/admin/calibration`、`/admin/system`。
  - Evidence: 源截图和浏览器标注可见，但应用内浏览器运行时无法建立连接，因而没有同视口实现截图，也无法形成同帧对比。
  - Impact: 无法确认登录卡片、监控主画布、标注画布和系统表格在目标分辨率下是否裁切，也无法完成检测器/BEV 主次切换的点击级视觉验收。
  - Fix: 恢复应用内浏览器连接并启动 Platform 后，在 1366×768、1440×900、1920×1080 采集四个真实模块，验证登录、路口切换、视频重试、BEV 主次切换、标注保存、系统页签和无权限状态，再进行同帧对比。

## Implemented Structure

- `ConsoleFrame` 是唯一页面壳层；工作台使用滚动内容区，实时监测使用沉浸式内容区。
- 左侧窄栏由同一份 `navigationGroups` 渲染六个一级业务域，并按角色权限过滤。
- 顶部只渲染当前业务域的二级页面；全域态势显示“工作台首屏 / 实时监测 / 轨迹研判”。
- 已移除工作台原宽二级侧栏和监测页独立菜单副本。
- 品牌、项目范围、时间窗口、新鲜度、异常入口、角色预览和 Toast 状态由共享壳层统一提供。

## Required Fidelity Surfaces

- Fonts and typography: 代码继续复用 Inter、PingFang SC 与现有字号/字重 token；缺少本轮浏览器截图，目视结论阻塞。
- Spacing and layout rhythm: 64px 顶栏与 62px 一级窄栏保持不变；工作台内容左边界由 272px 收敛为 62px；缺少截图，裁切与节奏目视结论阻塞。
- Colors and visual tokens: 复用现有蓝黑背景、冷蓝选中态、琥珀降级和珊瑚风险 token；未新增视觉语言。
- Image quality and asset fidelity: 实时监测继续使用原 UAV/BEV 栅格资产，未改动图片裁切策略；本轮未生成或替换资产。
- Copy and content: 一级域、二级页面名称与 PRD v2.1 六域目录一致；测试验证工作台和监测页均显示全域态势三个二级入口。

## Interaction Verification

- `npm test -- --run`: 36/36 passed。
- 新增回归覆盖认证会话、安全跳转、角色映射、后端权限边界、WebSocket 目标/现状消息规范化与去重，以及 `/` 与 `/monitoring` 的统一页面壳。
- Platform 全量回归：37/37 passed；验证系统/用户/标定管理员权限、标注图片鉴权，以及 WebSocket 缺失/无效/有效 Token。
- 真实模块组件回归覆盖检测器/BEV 主次切换、实时姿态和统计、告警确认、MJPEG 3 秒重试、WS 重连/退订/去重、系统部分失败、只读身份、多车道自然尺寸坐标和 `roads` 原样保存。
- `npm run build`: passed；仅有既存的大 chunk 性能提示。
- `git diff --check`: passed。
- Browser primary interactions tested: blocked；未执行点击级浏览器验证。
- Browser console errors checked: blocked；未取得浏览器连接。

## Comparison History

1. 本轮首次比较在实现截图采集阶段阻塞；未形成可用于判断 P1/P2 视觉差异的同帧证据，也未进行伪视觉验收。

## Implementation Checklist

- [x] 抽取并复用统一 ConsoleFrame。
- [x] 左侧固定六个一级业务域。
- [x] 顶部按当前域渲染二级页面。
- [x] 保留监控沉浸式内容和飞行姿态/BEV 主次切换。
- [x] 登录、实时监测、标定中心、系统与身份接入真实 REST/WS/MJPEG。
- [x] 旧 Console 从 Compose/发布入口移除，删除旧前端路由兼容。
- [x] 同步主 PRD、README/AGENTS、架构、API 契约、项目结构与任务记录。
- [ ] 浏览器恢复后补采同视口截图并完成最终视觉对比。

final result: blocked
