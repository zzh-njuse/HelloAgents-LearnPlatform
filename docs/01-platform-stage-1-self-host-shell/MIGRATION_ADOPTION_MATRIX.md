# Stage 1：参考实现采用矩阵

状态：规划完成；本文档不迁移任何参考代码。

参考来源为误仓库的 Legacy Phase 1 skeleton。每项处置都被刻意限制，避免把其基线问题带入正确仓库。

| 参考资产 | 决策 | Stage 1 处理方式 | 原因 |
|---|---|---|---|
| `apps/api` 目录分离 | 采用 | 在 `apps/api/learn_platform_api` 重建 | 保持 framework/product 边界，同时使用本仓库自己的名称 |
| FastAPI app factory 与 router 分层 | 采用并重写 | 仅用作结构模式 | 正确仓库需要自己的 settings、包路径与合约 |
| Pydantic Settings 模式 | 采用并重写 | 应用本地 settings 与脱敏 | 适合 `.env`/Compose，但名称和默认值需重新评审 |
| SQLAlchemy sync + Alembic | 采用并重写 | 一个 workspace migration 与本仓库测试 | 与 Stage 1 复杂度匹配；不直接搬运补丁 |
| Workspace schema 与防碰撞 slug | 采用行为和测试 | 重实现 `id/name/slug/description/timestamps` | 有价值的最小所有权根，不引入无关代码 |
| Health、readiness、system 路由 | 采用并重写 | 保留存活/就绪区分，输出脱敏 | 产品 readiness 不能暴露原始 URL 或 secret |
| Request-ID middleware/logging | 概念性采用 | 仅实现非敏感日志 | 与已确认的 review/可运维流程一致 |
| Compose 拓扑 | 采用并重写 | Postgres/Qdrant/Redis/API/Web 与 named volumes | 数据职责模型有效；镜像、环境变量与构建上下文须重验 |
| API Dockerfile | 仅参考 | 针对正确包/安装布局重建 | 直接复制会假定误仓库结构 |
| Web workbench 布局 | 选择性参考 | 重建 workspace-first workbench | 方向正确；源码组件需建立正确仓库所有权并 QA |
| 原型 `academic_companion/webui` | 选择性参考 | 未来仅复用少量 streaming/Markdown 思路 | 它是 chat-first，超出 Stage 1 范围 |
| 原型 FastAPI chat 路由 | Stage 1 不采用 | 保留于 `academic_companion` | chat/SSE 尚无已批准产品 spec，也没有安全默认值 |
| 原型 knowledge status 路由 | 拒绝 | 用脱敏的产品 readiness 替代 | 它暴露 Qdrant URL，并混淆运行细节与产品 API |
| 原型 chapter scanner | 延后，通过 adapter | 所有权设计完成后再作为 catalog capability | 内置数据是测试材料，不是产品事实 |
| 误仓库 Stage 1 测试 | 复用场景，不复用文件 | 编写新的产品合约测试 | 测试意图有价值，import 与 fixture 则依赖特定基线 |
| 误仓库 Stage 1 文档/runbook | 已取代 | 使用本 Stage spec/ADR，并编写新的 runbook | 历史文字和路径不得定义正确仓库 |

## 复制前必须重新分析

1. 依据 0R-A 基线确认依赖版本和 lockfile 策略。
2. 依据本 Stage 1 spec 确认 API 名称和 response schema。
3. 确认 Docker build context 与 Windows 友好的本地命令。
4. 确认 migration 命名和干净 Postgres 的升级行为。
5. 确认 Web 无障碍、响应式布局，以及首屏不是 chat-first。
6. 在实质性代码变更后记录 OCR review。

矩阵中的任何一项都不授权原样复制代码。它只在 Stage 1 spec 与 ADR 被接受后，授权采用指定的实现方式。
