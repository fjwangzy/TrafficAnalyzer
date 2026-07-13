# Console 2 — 无人机交通态势原型

基于 `docs/generated/2026-06-29-uav-traffic-ai-prd.md` 设计的独立前端原型，用于验证新一代交通指挥 Console 的信息架构与视觉方向。该目录不会替换现有 `traffic-fly-console/`。

## 原型范围

- 全屏检测器输出主画布与 GCJ02/延迟状态
- 检测器输出和右上角 BEV 鸟瞰轨迹图可一键交换主/辅视图
- 高度、航向、俯仰、横滚和云台锁定等飞行姿态数据
- 拥堵指数、断面流量、排队、车速和活动风险
- 轨迹、车道、风险与原始画面模式切换
- UAV 状态和业务图层控制
- TTC/PET 冲突、换道、拥堵与货车限行事件流
- AI 事件技术复核与底部实时/回看时间轴

所有数据均为交互原型使用的真实感模拟数据；原型不调用平台 API，也不持久化复核状态。

## 本地运行

```bash
npm install
npm run dev
```

生产构建验证：

```bash
npm run build
```

## 视觉资产

`public/assets/uav-intersection-night.png` 使用内置图像生成能力制作，提示词以用户提供的 Smart City Platform 截图作为镜头角度、深色氛围和空间密度参考，要求生成不含 UI、文字、标签和品牌的中国城市夜间无人机路口背景。

`public/assets/bev-intersection-night.png` 以同一视觉语言生成，要求使用严格 90° 正射俯视构图，作为 BEV 世界坐标与轨迹投放的底图。
