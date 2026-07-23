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
