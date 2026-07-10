# 正确仓库现状评估与重新计划

日期：2026-07-10

状态：Stage 0R 当前结论

## 1. Executive Summary

正确仓库不是空白项目。它已经拥有较完整的 Agent framework、学习/研究领域能力、RAG/Memory/MCP 原型和双模式 API/Web prototype。

当前短板不是“还缺几个 Agent”，而是缺少产品运行系统：workspace、权威数据库、资料生命周期、后台任务、最终信息架构、部署和可复现验证基线。

新的开发策略是：

> 保留 `hello_agents` 与 `academic_companion` 作为可复用已有资产，在其外建立 product app；先完成产品壳，再按资料生命周期、章节学习、练习记忆和质量加固逐阶段交付。

## 2. 当前资产评估

| 资产 | 状态 | 可直接复用 | 主要缺口 |
|---|---|---|---|
| `hello_agents` | framework 已成型 | Agent、Tool、Context、Memory/RAG、MCP、streaming、trace | 依赖环境需重建验证；不是产品层 |
| `academic_companion/agents` | 领域原型较完整 | Learning、Assessor、research pipeline | 无 workspace/product persistence contract |
| RAG/embedding/Qdrant | 可运行原型 | loader、chunk、embedding、retrieval | 当前 payload/collection 语义不是产品事实合同 |
| Memory/research notes | 可运行原型 | 用户模型、研究笔记、四类 memory | 本地持久化，不是产品可见/可删 memory |
| `academic_companion/api` | prototype | chat、SSE、knowledge endpoints | in-memory session、无产品依赖/数据库边界 |
| `academic_companion/webui` | prototype | chat、thinking、tool call、research step 组件 | chat-first，不是学习工作台 |
| CS/LeetCode data | fixture | 测试、eval、演示 | 不参与产品 schema 设计 |
| product app | 尚不存在 | 无 | `apps/api`、`apps/web`、Postgres、migration、Compose |

## 3. 当前验证状态

最近已确认：

- Web prototype `npm.cmd run lint` 通过。
- Web prototype `npm.cmd run build` 通过，但有单 chunk 超过 500 kB 的 warning。
- `academic_companion` API/config/orchestrator Python AST 解析通过。
- 全量 pytest 在 collection 阶段因当前环境缺少 `tiktoken` 停止。
- API import 因当前环境缺少 `fastapi` 失败。

Web 结果可以作为当前 prototype baseline。Python 失败首先属于依赖环境未复现，尚不能判定为业务回归。Stage 0R 下一步需要建立明确的 framework/domain 与 prototype API 依赖安装方式。

## 4. 文档整理结果

当前文档分为三层：

1. 根目录四份指导文档：产品蓝图、路线图、数据库部署、协作流程。
2. `00R-platform-baseline-reconstruction/`：当前 Stage 的 Spec、ADR 和评估。
3. `framework/`：仍与 `hello_agents` 相关的技术指南。

Legacy Phase 计划、旧立项书、逐日开发报告和仓库恢复过程稿已经收敛进 `history/LEGACY_AND_RECOVERY_SUMMARY.md` 后删除。逐行证据继续由 Git 历史保存。

## 5. 与误仓库行为模式的关系

已经采用：

- self-host first。
- Postgres/Qdrant/Redis/storage 职责分离。
- framework/domain/product 分层。
- Stage、Spec、ADR、review、人工 gate 的工作方式。
- 产品不是 chat-first，先做 workspace 和平台壳。

暂未采用：

- 误仓库 `apps/api`、`apps/web` 和 Compose 源码。
- 误仓库 Stage 2 ingestion schema 和 worker 细节。
- 误仓库的测试结果作为当前验证结论。

Stage 1 spec/ADR 将逐项判断参考实现是移植、重写还是放弃。

## 6. 重新计划

### Work Package 0R-A：依赖与测试基线

产物：

- Python framework/domain 安装方式。
- Prototype API 独立依赖清单。
- Web 安装、lint、build 命令。
- 当前测试通过/失败矩阵和环境说明。

限制：不修改业务行为，只允许必要的依赖/测试配置修正，且单独提交。

### Work Package 0R-B：Prototype Contract Inventory

产物：

- Learning/research Agent 输入输出。
- `/api/chat`、`/api/chat/stream`、knowledge endpoints 合同。
- SSE event 类型、字段和 Web 消费关系。
- session、配置、持久化和错误边界。
- Stage 1 需要保留、包装、改变或废弃的行为清单。

### Work Package 0R-C：Stage 1 输入

产物：

- Stage 1 self-host platform spec。
- App stack/layout ADR。
- 误仓库 Stage 1 逐项采用矩阵。
- 验证计划：API tests、migration、Web build、Compose smoke。

需要人工确认后才能开始 Stage 1 实现。

## 7. Stage 1 推荐起点

第一实现切片只包含：

- Product API/Web 空间建立。
- Postgres workspace schema 与 Alembic。
- readiness 与 workspace CRUD。
- Docker Compose 启动链路。
- 一个低风险 `academic_companion` capability adapter smoke。

不包含上传、worker、课程、练习、memory 迁移或完整 chat UI。

## 8. 当前风险

| 风险 | 当前处理 |
|---|---|
| 依赖声明与本机环境不一致 | 0R-A 单独处理 |
| Prototype 行为未测试固化 | 0R-B 建立 contract inventory |
| 两仓代码直接混合 | Stage 1 采用矩阵 + 人工 gate |
| Root README 仍以 framework 为中心 | 当前保留历史定位；Stage 1 再决定产品入口改写 |
| 数据 gitlink/许可 | 记录为非阻断维护项，fixture 使用保持克制 |
| 当前 main 领先远端 | 不自动 push；由用户决定远端同步时点 |

## 9. 下一步

文档规整完成后，按顺序执行 0R-A、0R-B、0R-C。完成 0R-C 并经过人工确认，项目才进入 Platform Stage 1 实现。
