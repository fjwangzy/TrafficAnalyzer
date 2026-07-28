# 算法精度改进任务清单

## 第一阶段 — 无痛改进（不改架构，不增依赖）

- [x] **改进 12**：激活 Mahalanobis 门控（`byte_tracker_model.py`）
- [x] **改进 7**：前景感知 NMS — 按类别独立 NMS（`DetectionNode.py`）
- [x] **改进 1**：检测后置信度分层 + 大目标初始化门控（`app_config.yaml` + `GroundTrajectoryTrackerNode.py`）
- [x] **改进 6**：轨迹分类多帧投票更新（`TrackElement.py` + `TrackerInfoUpdateNode.py`）

## 第二阶段 — 参数调优（需回归测试）

- [ ] **改进 2**：Kalman 滤波器航拍适配 — 动态 dt + 噪声放大（`kalman_filter.py` + `byte_tracker_model.py`）
- [ ] **改进 3**：背景运动估计质量提升（`image_motion.py` + `app_config.yaml`）
- [ ] **改进 5**：IoU + 中心点距离融合关联（`matching.py` + `byte_tracker_model.py`）
- [ ] **改进 8**：模型升级评估（配置变更）

## 第三阶段 — 架构增强（新增依赖）

- [ ] **改进 4**：推理尺寸自适应（`DetectionNode.py`）
- [ ] **改进 9**：SAHI 切片推理（`DetectionNode.py` + `app_config.yaml`）
- [ ] **改进 10**：ReID 外观辅助关联（新增模块）
- [ ] **改进 11**：TTA 精修评估（`DetectionNode.py`）

## 验证

- [x] 运行 `python -m pytest platform/tests -q`
- [x] 运行 `python -m pytest test/test_byte_tracker_core.py -q`
- [x] 运行 `python -m pytest test/test_refactor_unit.py -q` (如存在)
- [x] 运行回归 `python test/test_pipeline_inter_xqh.py`（预期 56 PASS）
- [ ] 更新相关文档
