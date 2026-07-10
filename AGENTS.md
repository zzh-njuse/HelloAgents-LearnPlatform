# AGENTS.md

## 仓库定位

- 本仓库正在从 HelloAgents framework + Academic Companion prototype 演进为 self-host 学习平台。
- `hello_agents/` 是可复用 framework；`academic_companion/` 是可复用学习/研究领域能力；未来 `apps/` 拥有产品 API/Web、workspace 和业务状态。
- 依赖方向保持 `apps -> academic_companion -> hello_agents`，禁止反向 import。
- 现有 `academic_companion/api` 与 `academic_companion/webui` 是待固化和吸收的 prototype，不是最终产品入口。
- `data/cs_fundamentals` 与 `data/leetcode` 只作为测试、eval 和演示材料，不主导产品 schema。

## 开始任务前

- 先读取 `docs/README.md`。
- 产品方向读取：
  - `docs/LEARNING_AGENT_BLUEPRINT.md`
  - `docs/SELF_HOST_DEVELOPMENT_ROADMAP.md`
  - `docs/DATABASE_AND_DEPLOYMENT_PLAN.md`
  - `docs/AGENT_COLLABORATION_PLAYBOOK.md`
- 再读取当前 Stage 的 README、Spec、ADR、review 和阶段总结。
- 当前阶段是 `docs/00R-platform-baseline-reconstruction/`。
- 先检查 `git status --short --branch`，保留用户和其他 Agent 的未知改动。

## Stage 与文档门禁

- 2026 年 5 月已有成果称为 Legacy Phase；新产品交付称为 Platform Stage。
- 非平凡功能先写或更新当前 Stage Spec。
- 技术栈、schema、migration、任务队列、权限、安全、删除、成本和部署等跨模块决策必须写 ADR。
- Spec/ADR 未经人工确认，不开始对应业务实现。
- Stage 收尾必须记录：实际完成、验证结果、暂缓风险、下一阶段输入和 review 结论。
- 过期计划收敛进阶段总结或 `docs/history/`，不要在 `docs/` 根目录长期保留多份当前计划。

## 当前 Stage 0R 范围

允许：

- 依赖与测试基线。
- Learning/Research/API/SSE prototype contract inventory。
- Stage 1 Spec、ADR 和误仓库参考实现采用矩阵。
- 文档和必要的测试/依赖配置修正。

禁止：

- 未经 Stage 1 gate 迁移误仓库 `apps/` 或 Compose 业务代码。
- 重构现有 Agent 行为来掩盖依赖环境问题。
- 整提交 cherry-pick 误仓库阶段实现。

## 工程边界

- 根 `pyproject.toml` 管理 `hello_agents` framework 依赖。
- Product API/Web 依赖在未来 `apps/api`、`apps/web` 中独立管理。
- Postgres 是产品事实来源；Qdrant 是可重建索引；Redis 是非权威队列；文件字节进入 local/object storage。
- SQLite 和本地 JSON/file memory 只作为 demo、测试或兼容能力，不是正式 self-host 主路径。
- 除非 Spec/ADR 明确批准，不把 Neo4j 加入默认部署。
- 不把 API key、上传原文、敏感 prompt、内部连接 URL 或绝对路径写入日志和公开 API。

## 实现与验证

- 优先小而可审查的 diff，不混合功能、重构、格式化和文档清理。
- 改变公开行为时同步更新测试和文档。
- Python framework/domain 目标基线：`python -m pytest -q`。
- Web prototype：
  - `cd academic_companion/webui`
  - `npm.cmd run lint`
  - `npm.cmd run build`
- 文档-only：`git diff --check`，并检查 Markdown 相对链接。
- Stage 1 self-host 代码建立后，最低验证包括 API focused tests、migration test、Web build、`docker compose config/build/up/ps`、`/ready`、Web HTTP 200 和一个业务 smoke。
- 无法运行的检查必须说明具体缺失依赖或环境条件，不能写成“视为通过”。

## OCR / OpenCodeReview 门禁

- OCR 是 Codex self-review 之外的独立代码审查，不互相替代。
- 文档-only、小型低风险修改默认不跑真实 OCR；Markdown 通常不在 OCR 代码 review 的有效范围内。
- Stage 末、较大代码 diff、schema、删除、权限、容器、部署和安全相关变更应进入 OCR gate。
- 未经用户要求或明确批准，不运行付费真实 OCR review；preview/version/help 属于安全预检。

标准流程：

```powershell
git status --short
git diff --stat
where.exe ocr
ocr version
ocr review --preview
```

仅在准备运行真实 review 时检查 provider：

```powershell
ocr llm test
```

真实 diff review 使用 Agent 友好输出：

```powershell
ocr review --audience agent --background "brief business context"
```

大 diff 可以在确认 provider 成本后使用：

```powershell
ocr review --audience agent --concurrency 4 --timeout 15 --background "brief business context"
```

若 `ocr` 不在 PATH，查找 `%USERPROFILE%\bin\ocr.exe`，不要硬编码或暴露 provider key。

OCR 结果处理：

- High：明显 bug、安全、数据丢失或破坏行为，优先修复。
- Medium：结合上下文判断并记录采纳或暂缓原因。
- Low：默认不盲改，除非能证明收益。
- 修复后运行正常 focused tests；有实质修复时才考虑一次复审，避免无限 review loop。
- Stage 级 OCR 记录放入当前 Stage `reviews/`，包含背景、命令、范围、findings、采纳/暂缓项和复验结果。
- OCR 超时后检查是否有残留进程，避免继续消耗 provider quota。

## Git 与提交

- 不回滚、覆盖或删除未知 dirty files。
- 不使用 `git reset --hard`、`git checkout --` 等破坏性命令，除非用户明确要求。
- 阶段性大提交前保留人工 gate，除非用户明确要求直接提交。
- 提交前运行适用检查并自审 staged diff。
- 不自动 push；由用户决定远端同步时点。

## Review 重点

结束前重点检查：

- 行为回归与错误路径。
- 数据事实来源、删除、重试和幂等。
- workspace 隔离与敏感信息。
- 缺失测试和无法复现的验证。
- 是否意外把 prototype 行为固化为产品合同。
- 是否让误仓库或 fixture 反向定义正确仓库架构。
