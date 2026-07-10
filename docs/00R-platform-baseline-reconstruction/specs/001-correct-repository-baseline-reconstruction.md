# Spec 001：正确仓库基线重建

状态：已确认，可执行文档与验证工作

日期：2026-07-10

阶段：Platform Stage 0R

## Goal

在不迁移业务代码的前提下，把正确仓库整理成一个事实清楚、依赖可复现、prototype contract 可验证、能够安全进入 Platform Stage 1 设计的基线。

## Context

此前在误仓库完成了高层文档、Stage 1 self-host 骨架和 Stage 2 设计。正确仓库同时保留了更完整的 `academic_companion` 学习/研究/RAG 能力、FastAPI/SSE 原型、React WebUI 和八股/LeetCode 测试材料。

当前已完成：

- 正确仓库现有成果 checkpoint：`b51f03b`。
- 高层设计文档导入：`3d8c7f6`。
- 正确仓库重新分析：`de6338e`。
- 七项架构 gate 已人工确认。

## Product Position

主产品是资料驱动的个人学习 Agent 平台。Chat、research pipeline、八股与 LeetCode 都是可复用能力或测试材料，不是产品信息架构本身。

## Scope

### 1. 仓库事实基线

- 记录当前 branch、commit、历史 Legacy Phase、现有模块和验证状态。
- 区分 framework、domain capability、prototype app 和未来 product app。
- 保留首次双仓审计，但不执行旧迁移矩阵。

### 2. 产品边界

- 接受 `hello_agents` / `academic_companion` / product app 三层模型。
- 明确单向依赖、数据所有权、配置与测试责任。
- 明确 prototype API/Web 的兼容期和退出条件。

### 3. 验证基线

- 给 Python framework/domain、prototype API 和 Web 分别建立依赖与验证命令。
- 将“缺依赖导致未运行”和“代码行为失败”分开记录。
- 不为了让测试变绿而修改业务行为。

### 4. Prototype contract inventory

至少记录：

- learning/research 模式的输入输出。
- `/api/chat` 与 `/api/chat/stream` 请求、SSE event 和错误行为。
- knowledge status/chapters 的响应边界。
- Web 当前消费的 event 类型与组件行为。
- in-memory session、配置和持久化限制。

该清单用于 Stage 1 判断哪些行为保留、包装、修改或废弃。

### 5. Stage 1 handoff

形成 Stage 1 spec/ADR 的输入：

- 最小 self-host 平台验收范围。
- product API 与 `academic_companion` adapter 的最小接点。
- workspace 与 readiness 的第一版合同。
- 误仓库 Stage 1 代码的采用评估标准。

## Non-goals

- 不复制误仓库 `apps/`、Compose、migration 或业务代码。
- 不创建 Postgres schema。
- 不实现 worker、上传、解析或 RAG 产品管线。
- 不重构 `hello_agents` 或 `academic_companion`。
- 不把 prototype API/Web 改造成最终产品。
- 不为八股/LeetCode 设计专用产品模型、权限或生命周期。
- 不处理真实 API key、`.env`、本地 memory 或 Qdrant 运行数据。

## Deliverables

- 本 Stage README、Spec 和产品边界 ADR。
- 依赖与测试基线报告。
- prototype contract inventory。
- Stage 1 输入与待决项清单。

## Constraints

- 文档中的“当前状态”必须能由正确仓库代码或 Git 记录验证。
- 导入文档中的旧路径、版本和测试结果不得冒充正确仓库事实。
- 所有写操作只发生在正确仓库。
- 每个提交只包含一种性质的工作，文档、依赖修复和业务实现不得混合。
- Stage 1 业务代码开始前保留人工 gate。

## Failure Modes

| 失败模式 | 防护 |
|---|---|
| 把误仓库实现当作既定架构 | 只引用为候选，Stage 1 spec/ADR 重新决策 |
| 为兼容 prototype 绑死产品模型 | 先写 contract inventory，再决定兼容范围 |
| 高层目标覆盖真实代码事实 | 正确仓库代码和测试优先 |
| 把缺依赖误判为代码回归 | 依赖失败与行为失败分开记录 |
| 八股/LeetCode 反向塑造产品 schema | 只作为 fixture，不进入 Stage 1 产品合同 |
| 为追求 clean 删除本地成果 | 使用 checkpoint 和 ignore，不回滚未知改动 |

## Done When

- README、Spec、ADR 经人工确认。
- 依赖与验证基线能够说明当前哪些命令通过、失败及原因。
- prototype contract inventory 足以支持 Stage 1 adapter 设计。
- Stage 1 输入不再依赖误仓库的空白基线假设。
- `git diff --check` 通过，工作区干净。

## Validation

文档阶段至少运行：

```powershell
git diff --check
git status --short --branch
```

依赖与 contract inventory 阶段再补充只读/import/lint/build 检查；不在本 Spec 中预先承诺真实 provider 或 Docker 集成验证。
