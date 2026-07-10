# ADR 001：产品分层与依赖边界

状态：已接受

日期：2026-07-10

阶段：Platform Stage 0R

## Context

正确仓库同时包含：

- `hello_agents` 通用 Agent framework。
- `academic_companion` 学习、研究、RAG、Memory、MCP 和 Skill 能力。
- `academic_companion/api` 与 `academic_companion/webui` prototype。
- 未来 self-host 平台所需但尚未在正确仓库建立的产品状态与部署层。

如果继续把 workspace、数据库、任务、权限和 UI 导航直接塞进现有 prototype，会让 framework、领域能力和产品生命周期耦合。反过来，如果直接用误仓库的空平台壳覆盖正确仓库，又会丢失已经形成的学习与研究资产。

## Decision

采用三层模型：

| 层 | 主要责任 | 不负责 |
|---|---|---|
| `hello_agents` | Agent runtime、LLM、Tool、Context、Memory/RAG 基础设施抽象 | workspace、产品 API、页面、业务 schema |
| `academic_companion` | 学习/研究 Agent、教学策略、领域 Skill、RAG/MCP/Memory 能力适配 | 产品事实来源、用户权限、部署入口、最终 Web 信息架构 |
| product app | workspace、资料、课程、练习、任务、trace、产品 API/Web 和部署 | 重新实现通用 Agent runtime |

product app 的最终目录在 Stage 1 使用 `apps/api` 与 `apps/web`，除非 Stage 1 ADR 发现明确阻断理由。

## Dependency Direction

允许的依赖方向：

```text
apps/web -> apps/api
apps/api -> academic_companion -> hello_agents
apps/api -> hello_agents
```

禁止：

- `hello_agents` import `academic_companion` 或 `apps`。
- `academic_companion` import product app。
- Web 直接依赖 Python domain 内部实现。
- product persistence model 渗入 framework 基础抽象。

需要双向通知时，通过明确的 DTO、event 或 adapter protocol，而不是反向 import。

## Product State Ownership

product app 拥有：

- workspace 与未来 user/member。
- document/version/chunk/job/citation。
- course/lesson/exercise/attempt。
- product memory、agent run、tool call、eval 和 cost record。
- API contract、鉴权/隔离、配置、migration 和部署健康状态。

数据基础设施约束：

- Postgres 是产品事实来源。
- 本地文件或对象存储是文件字节来源。
- Qdrant 是可从事实数据重建的索引。
- Redis 是队列、锁或缓存，不是任务事实来源。

## Existing Prototype Policy

这里的 existing prototype 明确指：

- `academic_companion/api`
- `academic_companion/webui`

处理策略：

1. 先记录并测试 prototype contract。
2. Stage 1 product API 通过 adapter 调用最小 `academic_companion` 能力。
3. Web 中可复用的 chat、thinking、tool call、research step 组件可以后续吸收。
4. prototype 在兼容行为被 product app 覆盖前不删除。
5. 最终入口、路由和弃用计划由后续 Stage ADR 决定。

prototype 的 in-memory session、本地文件 memory 和 chat-first 导航不成为产品合同。

## Existing Dataset Policy

八股与 LeetCode 数据属于测试和演示资产：

- 可以用于 RAG、citation、课程和练习的 fixture/eval。
- 不为其设计专用 workspace、版本、权限或删除模型。
- 不要求 Stage 1 导入 Postgres。
- Stage 2 用户资料 schema 不由其 JSON/Markdown 格式决定。

## Wrong-repository Code Policy

误仓库 Stage 1 代码证明了一种平台壳可运行，但不自动获得正确仓库中的产品权威性。

在 Stage 1 spec/ADR 确认前：

- 不 cherry-pick 整个提交。
- 不复制整个 `apps/` 目录。
- 可以引用其 API、schema、Compose、测试和 review 作为候选实现证据。
- 最终按正确仓库边界逐项选择移植、重写或放弃。

## Alternatives

### 方案 A：继续扩展 `academic_companion/api` 和 `webui`

拒绝作为默认方向。短期文件更少，但会把 prototype 的 session、导航和依赖选择固化为产品架构。

### 方案 B：直接采用误仓库 `apps/*`

暂不采用。它缺少正确仓库已有能力上下文，直接复制会让平台壳反向定义 domain adapter 与数据合同。

### 方案 C：把学习能力并入 `hello_agents`

拒绝。会扩大 framework 的业务耦合，并迫使通用 framework 安装产品依赖。

## Consequences

正向影响：

- 保留两层已有资产，同时建立清晰产品所有权。
- 可独立测试 framework、domain 和 product contract。
- self-host 依赖不会污染 framework 安装。
- prototype 可以渐进吸收，不需要一次性重写。

成本：

- 需要 adapter/DTO 和兼容期。
- 早期可能暂时存在两个 API/Web 入口。
- Stage 1 必须明确最小接点，避免构建空平台壳或过度集成。

## Follow-up

- Stage 0R：完成依赖/测试基线与 prototype contract inventory。
- Stage 1 spec：定义最小 product app、workspace/readiness 和一个 capability adapter。
- Stage 1 ADR：决定误仓库骨架逐项采用方式及 prototype 路由兼容策略。
- Stage 2：定义用户资料生命周期和引用检索，不以八股/LeetCode 为设计中心。
