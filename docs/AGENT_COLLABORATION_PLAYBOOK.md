# Agent 协作开发 Playbook

版本日期：2026-07-08

目标：把“会用 Codex”变成项目级工程能力。从现在开始，Agent 协作开发不是 Phase 4 展示项，而是每个阶段默认遵守的工作方式。

## 1. 调研结论

OpenAI 官方 Codex 最佳实践把 Codex 定位成需要长期配置和改进的队友，而不是一次性问答助手。官方建议的基本结构是：给出明确任务上下文，用 `AGENTS.md` 保存持久规则，用配置匹配工作流，用 MCP 连接外部系统，把重复工作沉淀为 skills，再把稳定流程自动化。

对我们这个项目，最重要的结论有六条：

1. 每个任务都要给 `Goal / Context / Constraints / Done when`，避免 agent 自己猜范围。
2. 复杂或模糊任务先 plan，不直接写代码。
3. `AGENTS.md` 必须从现在开始维护，因为它能把重复反馈变成仓库规则。
4. 测试、lint、diff review、OCR review 要进入默认闭环，而不是最后补。
5. MCP 只接真正能减少复制粘贴的外部上下文，不把所有东西都 MCP 化。
6. 重复三次的提示词和审查清单，应该沉淀为 skill；需要团队分发时再打包成 plugin。

另外，一篇 2026 年关于 `AGENTS.md` 的实证研究发现，在 10 个仓库、124 个 PR 任务中，加入 `AGENTS.md` 与更低的中位运行时间和更低的输出 token 消耗相关。这个结论不是说 `AGENTS.md` 会自动提高正确率，但足以支持我们把它当成成本和效率控制工具。

## 2. 本项目当前 Codex 能力盘点

当前本机已经具备这些能力：

| 类别 | 当前可用项 | 用法定位 |
|---|---|---|
| Repo guidance | 新增 `AGENTS.md` | 每次任务自动加载仓库规则 |
| Local skill | `ocr-codex-app` | 调用本地 OpenCodeReview 做代码 diff 审查 |
| Plugins | browser、github、documents、pdf、spreadsheets、presentations、template-creator | 浏览器验证、GitHub 工作流、文档/表格/演示稿处理 |
| MCP servers | `node_repl`、`llm_research_sources` | 浏览器/JS 执行、研究资料接口 |
| OCR marketplace | `open-code-review` 本地 marketplace | 后续可把 OCR 从个人 skill 升级为团队 plugin |

不建议马上做的事：

- 不要现在就写大量 project MCP server。等 API、DB、job 基本稳定后再 MCP 化。
- 不要把所有开发流程都做成 automations。先手动跑 3-5 次，流程稳定后再自动化。
- 不要把 skill 写得很泛。每个 skill 只覆盖一个可复用任务。

## 3. 从现在开始的标准开发闭环

每个非平凡功能都走这条链：

```text
idea
  -> spec
  -> Codex plan
  -> implementation
  -> focused tests
  -> self-review
  -> OCR preview/review when code changes are meaningful
  -> fixes
  -> final verification
  -> human decision
  -> retrospective update to AGENTS.md/skills/docs
```

各步骤要求：

| 步骤 | 产物 | 通过条件 |
|---|---|---|
| spec | `docs/<NN-stage-name>/specs/<id>-<topic>.md` | 目标、范围、接口、数据、失败模式、验收标准清楚 |
| plan | Codex plan 或任务清单 | 文件范围和验证命令明确 |
| implementation | 小 diff | 不混入无关重构 |
| focused tests | pytest/lint/type/eval | 至少覆盖本次变更主路径 |
| self-review | 简短风险检查 | 明确测试缺口和残余风险 |
| OCR review | review 摘要 | High 必修，Medium 逐项判断，Low 不盲改 |
| final verification | 命令和结果 | 用户能看到实际验证过什么 |
| retrospective | AGENTS/skill/doc 更新 | 重复问题不再只靠记忆 |

## 4. 风险分级授权

| 等级 | 任务类型 | Agent 自主度 | 必须验证 |
|---|---|---|---|
| L0 | 解释、调研、计划 | 可自由分析，不改代码 | 来源和假设说清楚 |
| L1 | 文档、测试、小修 | 可直接改 | `git diff --check` 或相关测试 |
| L2 | 小功能、API、存储适配 | 可实现，但要 spec | 单测 + self-review |
| L3 | 数据库 schema、删除逻辑、权限、部署 | 必须先 spec/ADR | 测试 + OCR review + 人工确认 |
| L4 | 大范围重构、自动迁移、真实部署操作 | 不允许无审核 | 分阶段 PR 和人工 gate |

无审核长时间开发只允许从 L1/L2 开始，且必须在独立分支或 worktree 中进行。

## 5. 需要马上补齐的仓库资产

已完成：

- 根目录 `AGENTS.md`：仓库级 Codex 规则。
- `.opencodereview/rule.json`：项目级 OCR 审查规则。
- 本文档：Agent 协作开发 playbook。

下一步建议：

1. 进入阶段 1 时，建立 `docs/02-stage-1-self-host-platform/`，并保留 `specs/`、`adr/`、`evals/`、`reviews/` 子目录。
2. 为阶段 1 平台骨架编写第一份 spec，例如 `docs/02-stage-1-self-host-platform/specs/001-self-host-platform-skeleton.md`。
3. 后端技术栈、migration 方案等若无法在 spec 中轻量确认，则写阶段 1 ADR。
4. 有实质代码变更并运行 OCR review 时，把摘要保存到当前阶段的 `reviews/` 目录。
5. 等连续 3 个功能都用同一套流程完成后，再考虑沉淀 repo-local skill 或打包 plugin。

## 6. Codex 辅助能力如何用

### AGENTS.md

用途：仓库级持久约定。应该保持短小、准确、可执行。

放入：

- 项目结构。
- 测试和验证命令。
- 不要做什么。
- self-host 方向的关键架构约束。
- OCR review 的触发条件。

不要放入：

- 长篇蓝图。
- 临时任务细节。
- 私密 API key。
- 大量容易过期的外部资料。

### Skills

用途：重复工作流。适合本项目的 skill 候选：

| Skill | 触发语 | 价值 |
|---|---|---|
| `self-host-feature` | “实现一个 self-host 功能” | 固化 spec、实现、测试、review 流程 |
| `db-schema-change` | “改数据库/迁移/schema” | 强制 ADR、迁移检查、回滚思考 |
| `rag-eval` | “补 RAG eval/评测” | 固化 eval case、指标、报告格式 |
| `frontend-qa` | “检查前端页面/截图验收” | 固化响应式截图和 UI 检查 |
| `ocr-review-gate` | “用 OCR 审一下” | 固化 preview、review、分类、修复、复验 |

Windows 下手动检查 OCR 规则时，路径尽量写成正斜杠，例如：

```powershell
C:\Users\Admin\bin\ocr.exe rules check hello_agents/tools/builtin/rag_tool.py
```

### Plugins

用途：可安装分发的工作流包。现在先用现有插件：

- GitHub plugin：后续 PR、issue、CI 检查。
- Browser plugin：前端本地页面验证、截图。
- PDF/documents/spreadsheets/presentations：处理用户学习资料和面试展示材料。
- OCR 本地 marketplace：等 OCR skill 稳定后升级成项目 plugin。

不要一开始就自建 plugin。先把 skill 跑顺。

### MCP

用途：连接仓库外部的活上下文和工具。

本项目早期适合接：

- GitHub/GitLab：issue、PR、CI。
- OCR/OpenCodeReview：代码审查工具。
- 本地文档资料库：后续可暴露课程资料或 eval 结果。
- 浏览器或设计工具：前端验证阶段再接。

暂时不 MCP 化：

- Postgres CRUD。
- RAG 主检索路径。
- 内部 Python 函数。

### Hooks 和 Automations

Hooks 适合机械约束，比如禁止直接提交 `.env`、阻止无 spec 的 migration、运行格式检查。现在先不加 hook，等目录结构稳定后再做。

Automations 适合稳定重复任务，比如每日检查依赖、每晚跑 eval、每周扫描 AGENTS.md 是否需要更新。现在先不做自动化，等 Phase 1 跑通后再开。

## 7. 每阶段如何贯穿 Agent 协作

| 阶段 | 协作要求 | 证明材料 |
|---|---|---|
| Phase 0 地基 | 每次修复都更新 AGENTS/docs/tests | commit、测试结果、doc diff |
| Phase 1 self-host MVP | 每个功能先 spec，代码走 OCR gate | spec、review 摘要、pytest |
| Phase 2 学习闭环 | 生成能力必须有 eval case | eval 结果、失败样例 |
| Phase 3 成本质量 | agent run 和 token 进入看板 | trace、cost_events |
| Phase 4 展示整理 | 不再新建流程，只整理案例 | 复盘、指标、面试叙事 |

也就是说，Phase 4 不再是“才开始做 Agent 协作”，而是“把之前一直在做的协作方式产品化、案例化、可讲述化”。

## 8. 调研来源

- OpenAI Codex Best practices：上下文、Plan mode、AGENTS.md、配置、测试/review、MCP、skills、automations。https://developers.openai.com/codex/learn/best-practices
- OpenAI Codex Customization：AGENTS.md、memories、skills、MCP、subagents 的分层关系和建议建设顺序。https://developers.openai.com/codex/concepts/customization
- OpenAI Codex AGENTS.md：Codex 如何发现和合并 `AGENTS.md`。https://developers.openai.com/codex/guides/agents-md
- OpenAI Codex Skills：skills 的结构、渐进加载和触发方式。https://developers.openai.com/codex/skills
- OpenAI Codex Plugins：plugin 如何打包 skills、apps 和 MCP servers。https://developers.openai.com/codex/plugins
- OpenAI Codex Automations：后台定期任务和 worktree 隔离。https://developers.openai.com/codex/app/automations
- OpenAI Codex Review：本地 review pane、inline comments 和 `/review`。https://developers.openai.com/codex/app/review
- Lulla et al., On the Impact of AGENTS.md Files on the Efficiency of AI Coding Agents, 2026。https://arxiv.org/abs/2601.20404
