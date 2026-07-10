# 阶段 0R：正确仓库基线对齐与受控迁移矩阵

> 历史说明：本文记录首次双仓差异审计。高层设计文档导入后，架构判断与阶段起点以 `phase-0R-correct-repository-reanalysis.md` 为准；本文保留作为证据清单，不再作为迁移执行合同。

日期：2026-07-10

状态：审计完成，等待迁移 gate

正确仓库：`C:\Users\Admin\Desktop\HelloAgents-LearnPlatform`

误用仓库：`C:\Users\Admin\Desktop\HelloAgents-learn_version\HelloAgents-learn_version`

## 1. 本阶段边界

阶段 0R 只做基线审计、差异分类和迁移设计，不迁移或修改业务代码。

本阶段不做：

- 不覆盖、删除或格式化正确仓库中的 dirty files。
- 不 cherry-pick 误用仓库提交。
- 不复制 `apps/`、Compose、API 或 Web 源码。
- 不改动 `hello_agents/`、`academic_companion/` 或数据内容。
- 不处理真实 `.env`、API key、运行时 memory 或本地 Qdrant 数据。

## 2. 仓库身份与 Git 基线

| 项目 | 正确仓库 | 误用仓库 |
|---|---|---|
| remote | `zzh-njuse/HelloAgents.git` | `zzh-njuse/HelloAgents-learn_version.git` |
| branch | `main` | `main` |
| HEAD | `9b24189` | `ddf9a20` |
| upstream | `origin/main@3197ab2` | `origin/main@77a59ca` |
| ahead | 2 commits | 1 commit |
| dirty | 2 tracked 修改 + 多组 untracked | 1 tracked 文档修改 + 1 untracked 文档 |

两个仓库不能视为同一工作树的新旧副本。按 tracked path 比较：正确仓库 309 项，误用仓库 174 项；仅 41 项路径同名，其中 30 项内容已不同；误用仓库另有 133 项独有路径。阶段 0R 不采用整提交 cherry-pick 或整目录覆盖。

## 3. 正确仓库资产审计

### 3.1 `academic_companion`

正确仓库已经包含可复用的领域能力：

- 学习模式：`LearningAgent`、会话、掌握度评估、用户模型。
- 研究模式：search/filter/analyze/synthesize 多 Agent 编排、研究笔记、MCP 工具。
- RAG：CS 八股与 LeetCode 加载、分块、embedding、Qdrant 检索。
- Skill：`cs-interview`、`leetcode-patterns`、`paper-reading`。
- 运行入口：学习/研究 demo、批量 ingestion、session demo。

这些能力是正确仓库独有资产；误用仓库没有 `academic_companion/`，迁移时必须保留，不能用阶段 1 平台骨架替代。

### 3.2 当前 API 与 Web

正确仓库已有一套未跟踪的原型实现：

- FastAPI：`/api/health`、`/api/chat`、`/api/chat/stream`、`/api/knowledge/status`、`/api/knowledge/chapters`。
- SSE：学习模式转发 `LearningAgent.arun_stream()`；研究模式依赖 dirty `ResearchOrchestrator.run_streaming()`。
- Web：React 19 + TypeScript + Vite，包含学习/研究切换、聊天、thinking/tool call 展示和研究步骤面板。
- Web lint 在本次审计中通过。
- Python AST 解析通过，但当前 Python 环境缺少 `fastapi`，API 无法 import；根 `pyproject.toml` / `requirements.txt` 也未声明 FastAPI、Uvicorn 和 Qdrant client 的产品依赖边界。
- API/Web 没有进入现有 pytest 覆盖；研究步骤 UI 当前没有从 SSE 事件更新的完整接线。
- session 使用进程内字典，不具备多进程、重启恢复、容量控制或 workspace 隔离语义。

结论：这套实现是重要的行为原型和 UI 能力来源，但还不是可直接替代阶段 1 self-host 骨架的产品边界。

### 3.3 数据资产

| 数据集 | 当前状态 | 数量/规模 | Git 状态 |
|---|---|---|---|
| CS-Base 八股 | Markdown | 126 个文件，约 2.45 MB | clean，gitlink `381b846` |
| LeetCode | JSON | 2913 个独立题目 + merged 文件，约 20 MB | clean，gitlink `16c26d1` |
| 章节目录 | `data/chapters.json` | 29 个 CS chapter + 17 个 algorithm chapter | parent repo tracked |

数据质量抽查结果：2913 个题目 JSON 均可解析，`problem_id` 唯一，无重复；merged 文件同样包含 2913 题。现有批量 ingestion 使用 merged 文件并分 500 题处理；CS 批量入口只摄入 `mysql/network/os/redis` 四类，共 109 个 Markdown，未覆盖 `cs_learn`、`reader_nb` 和其他 Markdown。

必须先处理的仓库风险：

- 两个数据目录在父仓库中是 gitlink，但仓库没有 `.gitmodules`，干净 clone 无法通过标准 `git submodule update --init` 恢复数据。
- 两个上游目录均未发现明确 LICENSE 文件；在对外分发或制作默认镜像前需要确认内容许可和来源标注。
- 现有 RAG 把完整 chunk 正文写入 Qdrant payload；误用仓库阶段 2 设计要求 Postgres 保存正文、Qdrant 只存最小定位 metadata。两套事实来源语义不一致。

### 3.4 Dirty worktree

已跟踪但未提交：

- `academic_companion/agents/research/orchestrator.py`：增加研究 SSE 流程，并把子 Agent 结果从 summary 改为 raw result。
- `academic_companion/config.py`：`subagent_max_steps` 从 6 调整为 10。

未跟踪但疑似业务成果：

- `academic_companion/api/routes_chat.py`
- `academic_companion/api/routes_knowledge.py`
- `academic_companion/api/server.py`
- `academic_companion/webui/`
- `docs/phase4-webui-plan.md`

未跟踪的本地/调试资产：

- `.backups/`、`.claude/`、`_check_qdrant.py`、`_test_agent.py`、`research_report.md`

已忽略运行时资产：

- `.env`
- `memory/`：1143 files，约 13.4 MB
- `memory_data/`：约 80 KB
- Web `dist/`：64 files，约 1.74 MB
- Web `node_modules/`：7509 files，约 124 MB

结论：迁移前必须先给正确仓库 dirty 内容建立只读清单和独立保存点。不得把本地 `.env`、memory、构建产物或依赖目录带入迁移提交。

### 3.5 当前验证基线

- `academic_companion` 相关 Python 文件 AST 解析通过。
- Web `npm run lint` 通过。
- 全量 pytest 在 collection 阶段停止：当前环境缺少 `tiktoken`；另有 `pytest-asyncio` marker 未注册警告。
- API import 失败：当前环境缺少 `fastapi`。

这些失败是环境/依赖基线问题，不应被误记为迁移代码回归；迁移实施前应先建立可复现的依赖安装命令。

## 4. 误用仓库成果审计

### 4.1 阶段 0 文档

阶段 0 已形成 self-host 产品方向、数据栈 ADR、协作流程、数据库部署计划和总路线图。核心决策是：Postgres 为事实来源，本地文件保存原始资料，Qdrant 为可重建索引，Redis 为非权威协调层，Neo4j 不作为默认依赖。

这些决策总体可复用，但其“当前仓库真实状态”基于误用仓库，需要用正确仓库的 `academic_companion`、现有数据和 dirty API/Web 重写。

### 4.2 阶段 1 文档与骨架

阶段 1 已实现并记录验证：

- `apps/api`：FastAPI、sync SQLAlchemy、Alembic、Postgres workspace CRUD、health/ready/system API、结构化日志。
- `apps/web`：Vite/React/TypeScript workspace 工作台。
- `docker-compose.yml`：Postgres、Qdrant、Redis、API、Web。
- app 依赖边界：framework 继续由根 `pyproject.toml` 管理，产品 API 使用 `apps/api/requirements.txt`。
- 文档记录显示 focused tests、Web build、Compose build/up、readiness、Web 200 和 workspace smoke 均通过。

阶段 1 骨架不包含学习/研究 Agent、SSE、现有题库或 RAG；它是产品平台壳，不是正确仓库能力的超集。

### 4.3 阶段 2 文档

阶段 2 当前只有文档，没有业务实现：

- 已提交 Spec：上传、解析、索引、引用检索/问答。
- 已提交草稿 ADR：RQ worker、Postgres 任务事实来源、单 Qdrant collection、workspace filter。
- 未提交决策清单：12 个实现边界，状态为“待人工确认”。
- `README.md` 有 1 行未提交修改，用于链接该决策清单。

该决策清单引用的 framework 路径和行为来自误用仓库，例如 `hello_agents/memory/embedding.py` 与 `hello_agents/memory/rag/pipeline.py`；正确仓库实际路径是 `hello_agents/embedding/`、`hello_agents/rag/pipeline.py` 和 `academic_companion/rag_extensions/`。因此阶段 2 文档不能原样作为实现合同。

## 5. 目标边界建议

受控迁移后的单一方向建议如下：

- `hello_agents/`：继续作为 framework 层，阶段 0R 不从误用仓库覆盖任何同名文件。
- `academic_companion/`：保留学习、研究、RAG、Memory、MCP、Skill 等领域能力。
- `apps/api`：作为最终产品 API 边界；阶段 1 workspace/DB/readiness 骨架迁入后，通过 adapter 调用 `academic_companion`，而不是复制一套 Agent。
- `apps/web`：作为最终产品 Web；吸收正确仓库现有 chat/research UI 能力和误用仓库 workspace shell，避免长期维护两个 Vite 应用。
- Postgres：产品事实来源；现有 file memory 和 research notes 先作为 legacy adapter，另立数据迁移计划。
- Qdrant：先明确“现有双 collection + 正文 payload”到“workspace 隔离 + Postgres 正文”的兼容期，再实施阶段 2。
- `data/`：继续作为只读内置种子知识库；用户上传资料进入 workspace/document 模型，二者不要混成同一生命周期。

## 6. 迁移矩阵

| ID | 来源资产 | 目标/动作 | 决策 | 前置条件 | 验证 gate |
|---|---|---|---|---|---|
| M01 | 正确仓库当前 dirty worktree | 建立清单与独立保存点 | 保留，不覆盖 | 用户确认保存方式；排除 `.env`/runtime | `git status` 与审计清单一致 |
| M02 | 误仓库阶段 0 docs | `docs/01-stage-0-foundation/` | 迁移后校订 | 所有“当前状态”改为正确仓库事实 | 文档链接、路径和术语检查 |
| M03 | Blueprint/Roadmap/DB plan/Playbook | `docs/` | 合并迁移 | 与正确仓库 Phase 1-4 文档建立映射，避免阶段编号歧义 | `git diff --check` + 人工 gate |
| M04 | `AGENTS.md` | 正确仓库根目录 | 选择性迁移 | 删除误仓库特有假设，保留阶段 gate/dirty 保护 | 人工确认规则不会阻断现有流程 |
| M05 | 阶段 1 spec/ADR/review/runbook | `docs/02-stage-1-self-host-platform/` | 迁移并加“原仓验证”标记 | 标注验证发生在误仓库，不冒充正确仓库基线 | 路径核对 + 人工 gate |
| M06 | `apps/api` workspace 骨架 | 正确仓库新 `apps/api` | 分文件移植 | 先冻结现有 prototype API contract；明确 app 依赖 | focused API tests + migration test |
| M07 | `academic_companion/api` 原型 | `apps/api` router/service adapter | 行为迁移，暂不删除源文件 | 定义 `/api` 与 `/api/v1` 兼容策略；补依赖与测试 | learning/research SSE contract tests |
| M08 | 误仓库 `apps/web` workspace shell | 正确仓库新 `apps/web` | 作为产品壳移植 | 明确导航、workspace 状态和 API base | lint + build + workspace smoke |
| M09 | 正确仓库 `academic_companion/webui` | 合并到 `apps/web` feature modules | 迁移能力，不整目录覆盖 | 固化聊天、SSE、研究步骤行为；消除双应用 | lint/build + SSE UI smoke |
| M10 | Compose/Dockerfiles/nginx | 正确仓库根 + `apps/*` | 选择性移植 | 合并现有 Qdrant/embedding 环境变量；不复制真实 `.env` | `docker compose config/build/up` |
| M11 | Postgres workspace model/Alembic | `apps/api` | 移植 | 确认 workspace 如何绑定 session、memory、内置题库 | Postgres migration + CRUD tests |
| M12 | 正确仓库 CS/LeetCode gitlinks | `data/` | 原地保留并修复可恢复性 | 决定补 `.gitmodules` 或 vendor；完成许可核查 | 全新 clone 能恢复并校验固定 commit |
| M13 | 现有 ingestion/RAG | legacy adapter + product ingestion service | 暂缓代码迁移，先写兼容 ADR | 决定 collection、payload、embedding、citation 事实来源 | 双数据源检索与重建测试 |
| M14 | 阶段 2 Spec/ADR | `docs/03-stage-2-material-ingestion/` | 迁移后重写 | 替换错误路径；纳入内置数据与现有 RAG 事实 | spec/ADR 人工确认 |
| M15 | 阶段 2 未提交决策清单 | 同阶段 specs，标注 provenance | 单独迁移候选 | 先在误仓库保存其 dirty 状态；12 项逐项重审 | 人工 gate 后才可实现 |
| M16 | 误仓库同名 `hello_agents/*` 变更 | 无 | 阶段 0R 排除 | 另开 framework reconciliation 审计 | 独立 diff/test，不与 app 迁移混合 |
| M17 | `.opencodereview` 与 review 流程 | 正确仓库可选配置 | 选择性迁移 | 确认本仓库需要 OCR 规则 | preview 可用且不扩大 scope |
| M18 | node_modules/dist/.pytest_cache/.tmp/storage/runtime memory | 无 | 明确排除 | 无 | 迁移 diff 中不得出现 |

## 7. 建议实施顺序

1. **R0：保存点**。只处理两个仓库的 dirty 状态归档策略，不合并代码。
2. **R1：文档对齐**。迁入并校订阶段 0、阶段 1、阶段 2 文档，明确 provenance 和阶段编号。
3. **R2：数据可恢复性**。修复 gitlink/`.gitmodules` 或 vendor 策略，并完成许可检查。
4. **R3：产品壳移植**。按小提交移植 `apps/api` workspace/DB/readiness，再移植 `apps/web` shell 和 Compose。
5. **R4：能力接线**。将现有学习/研究 SSE API 和 Web 功能接入 `apps/*`，保持 `academic_companion` 领域层。
6. **R5：阶段 2 重写 gate**。重新确认 ingestion、Qdrant、Postgres、内置题库与上传资料的边界后，才开始阶段 2 业务实现。

## 8. 阻断项与人工 gate

开始任何业务迁移前，至少需要确认：

1. 是否采用 `apps/api` + `apps/web` 作为唯一产品入口，并把 `academic_companion/api` / `webui` 视为待吸收原型。
2. 正确仓库当前 dirty API/Web 和 orchestrator 修改如何建立保存点。
3. 两个数据 gitlink 采用“补 `.gitmodules` 固定上游 commit”还是“转为 vendored 数据”。
4. 阶段 2 是否接受 Postgres 为 chunk/citation 事实来源，并为现有 Qdrant 正文 payload 设计兼容迁移。
5. 误仓库阶段 2 未提交决策清单是否先在原仓库单独保存，再迁入正确仓库重审。

在以上 gate 通过前，不应开始复制 `apps/`、Compose 或阶段 2 业务代码。
