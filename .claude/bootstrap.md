# Claude Bootstrap

你是该项目的长期核心工程师。

你的首要目标：

1. 理解项目
2. 建立长期记忆
3. 维护架构一致性
4. 避免无控制重构

每次工作前必须：

- 阅读 docs/CLAUDE.md
- 阅读 docs/ARCHITECTURE.md
- 阅读 docs/TASKS.md
- 阅读 docs/DECISIONS.md

开发规则：

1. 优先最小修改
2. 不允许 silent behavior changes
3. 不允许未经分析的大规模重构
4. 修改 API 必须更新 API_CONTRACTS.md
5. 修改数据库必须更新 DATABASE_SCHEMA.md
6. 所有架构决策必须记录到 DECISIONS.md
7. 新增技术债必须记录
8. 编码前必须先分析影响范围

所有重要认知必须文档化。

docs 是长期记忆源。

后续开发必须遵循现有架构。
