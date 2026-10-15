# 根级测试

本目录集中存放检测管道及仓库级契约测试。Platform 自身的测试仍保留在
`platform/tests/`，Console2 测试仍与前端源码同目录维护。

## 分类

- 普通 pytest：节点、坐标、Kafka、Compose、遥测和入口契约测试。
- 脚本式回归：`test_refactor_unit.py`、`test_pipeline_no_yolo.py`、
  `test_pipeline_inter_xqh.py`。
- 运行态 E2E：`test_e2e_inter_xqh.py`、`test_e2e_mps_streaming.py`、
  `test_live_api.py`，需要对应的 Kafka、Platform 或 Nginx 环境。

## 常用命令

从仓库根目录执行：

```bash
python -m pytest test -q
python test/test_refactor_unit.py
python test/test_pipeline_no_yolo.py
python test/test_pipeline_inter_xqh.py
```

`conftest.py` 会让 pytest 从仓库根目录解析项目模块，并排除脚本式回归和运行态
E2E；这些脚本需要按上面的独立命令显式执行。

## 2026-10-04 回归入口维护

`test_refactor_unit.py` 复用当前速度、统计、Kafka、图像生命周期、TCC、渲染及EOF pytest套件，不再维护一套把像素速度当km/h的旧断言。`test_pipeline_no_yolo.py` 仍处理200帧真实素材，检测为合成输入，图像关联/世界投影采用当前节点；素材不满足地理质量时验证可空速度，不伪造米制运动。

Platform 真库用例只在显式 `RUN_PG_INTEGRATION=1` 且已指定隔离 road9 时运行；Mission测试会清理控制面夹具，禁止指向现有业务库。功能验收证据见 `docs/test_report_functional_acceptance_20261004.md`。
