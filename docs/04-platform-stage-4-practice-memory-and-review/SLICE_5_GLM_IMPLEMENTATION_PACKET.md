# Stage 4 Slice 5 GLM 基线诊断与实现任务包

状态：正式任务包；Spec 005 / ADR 007 已于 2026-07-23 通过人工 Gate

交接对象：GLM

执行方式：先完成 Phase A 基线诊断并停止回交；Codex 复核后，才按同一任务包继续 Phase B-F 主体实现

## 1. Goal

在不新增题型、MCP capability、Memory/Mastery 目标或产品内多 Agent 的前提下，定位并修复普通题、Python/Java/C++ 编程题和科学题从课节画像到正式 Feedback 的稳定性问题，尤其是人工 smoke 中 Java/C++ 生成成功率为 0 的问题。

必须交付：

- 可复现、分阶段、无敏感内容的基线诊断；
- `practice_artifact_v2` / `solve_utf8_string_v2` 与 v1 兼容读取；
- 只增加 `practice_jobs.artifact_contract_version` 的 migration；
- 分阶段 validator、单题 repair、有限基础设施 retry 和稳定错误投影；
- 三语言真实 compiler/runtime 与产品 MCP/Judge0 合同测试；
- 科学验证与 LLM 评分权威修复；
- 有界去重、Web 状态和完整自动化。

完成不等于 Slice 5 或 Stage 4 已关闭。GLM 回交后仍由 Codex 独立复验、组织真实 provider/OCR Gate、配合人工 Chrome/删除 smoke 并写阶段总结。

## 2. 已接受的硬决策

以下不是实现者可选项：

1. 新 Job 使用 `practice_artifact_v2`；coding 使用 `solve_utf8_string_v2`。
2. v1 历史题不迁移、不重跑、不改变旧分数；缺失版本按 v1 读取。
3. 每个 Set 最多一个 `coding` 或 `scientific` specialized item。
4. 结构 repair 最多一次；specialized item 只修失败 Item，最多一次。
5. delivery retry 只覆盖临时 provider/queue/MCP/lease 故障，最多三次。
6. 只新增 `practice_jobs.artifact_contract_version`；不新增其他列、表或 Job 状态。
7. 编程分数只由 immutable tests/weights/comparator/harness version 决定；LLM 不改分。
8. 科学验证缺失时 LLM 不猜分；未授权、临时不可用、结果不足分别收敛。
9. exact + 有界本地 near-duplicate；不增加 Qdrant exercise index、embedding 或 LLM 判重。
10. 真实 Gate 候选为每语言 5 次至少 4 次完整成功；实现者不得自行降低。

## 3. 仓库与真实运行环境

### 3.1 仓库状态

| 项目 | 当前值 |
|---|---|
| 仓库 | `C:\Users\Admin\Desktop\HelloAgents-LearnPlatform` |
| 分支 | `main`，相对 `origin/main` ahead 1 |
| 基线提交 | `96a61eb7617914a2df6b35cfd2c8e3eb8aecf3e2` (`feat: complete stage 4 controlled MCP slice`) |
| Shell | Windows PowerShell 5.1 |
| Host | Windows；Docker Desktop 运行产品 Compose |

开始时先运行：

```powershell
cd C:\Users\Admin\Desktop\HelloAgents-LearnPlatform
git status --short --branch
git rev-parse HEAD
```

HEAD 或 dirty 状态变化时不要 reset、checkout、stash 或覆盖；先阅读差异并在报告中说明。当前已知 dirty：

- 本任务对应的 Slice 5 事实盘点、Spec 005、ADR 007、任务包和索引/状态文档；这些是已接受输入，不得回滚。
- 未跟踪 `.tmp/` 与 `artifacts/`；视为用户/Codex 既有产物，不读取其敏感内容、不清理、不纳入实现提交。

### 3.2 本机工具链

当前探测值：

| 工具 | 版本/位置 |
|---|---|
| API focused Python | `apps/api/.venv-test/Scripts/python.exe`，Python 3.13.5 |
| Node | 24.14.0 |
| npm | 11.9.0 |
| Docker client | 28.5.1 |
| Docker Compose | 2.40.2-desktop.1 |
| 本机 javac | 21.0.9 |
| 本机 g++ | MSYS2 16.1.0 |

本机 javac/g++ 只用于快速 compiler fixture；不能冒充产品执行结果。API Docker test stage/Compose 环境和经产品 MCP adapter 到隔离 Judge0 的结果才是正式集成依据。

### 3.3 产品拓扑

当前 Compose 已运行：`postgres`、`redis`、`qdrant`、`api`、`web`、`worker`、`practice-worker`、`reconciler`、`mcp-execution`、`code-lab-worker`、`capability-probe`。API/Postgres/Redis 当前 healthy；其他服务为 running。

代码执行后端沿用 Slice 4 已接受拓扑：Windows 主机内独立 Ubuntu VM + Judge0 1.13.1，主 Compose 只通过固定产品 MCP `run_code` 访问。不得把 Judge0 加入主 Compose、不得挂载仓库/secret、不得开放网络或绕过 MCP 直接调用后端。

Wolfram 是可选远程 capability。GLM 不运行真实 Wolfram、不读取其配置；只用 fake/recorded safe observation 测试。真实 provider、Wolfram、OCR 和 Chrome smoke 均由后续人工 Gate 控制。

### 3.4 环境安全

- 不读取、打印或复制 `.env`、API key、provider base URL、Judge0/MCP 私有地址、内部域名或凭据。
- 不读取/提交真实上传资料、用户答案、代码、prompt、日志、hidden tests 或 provider/Tool 原文。
- 不在任务包、报告、测试快照或错误消息中写宿主机绝对运行路径；本节仓库路径仅用于交接定位。
- 需要真实 provider 或远程服务才能继续时停止并报告，不自行尝试凭据。

## 4. 开始前必须完整读取

不得只读摘要或本任务包。按顺序完整读取：

1. `AGENTS.md`
2. `docs/README.md`
3. `docs/LEARNING_AGENT_BLUEPRINT.md`
4. `docs/SELF_HOST_DEVELOPMENT_ROADMAP.md`
5. `docs/DATABASE_AND_DEPLOYMENT_PLAN.md`
6. `docs/AGENT_COLLABORATION_PLAYBOOK.md`
7. `docs/GLM_IMPLEMENTATION_HANDOFF_WORKFLOW.md`
8. 当前 Stage `README.md`、`STAGE_4_INPUTS.md`、`STAGE_4_SLICE_PLAN.md`
9. `SLICE_4_SUMMARY.md` 与 `reviews/2026-07-23-slice-4-ocr.md`
10. `SLICE_5_INPUTS.md`
11. `SLICE_5_PRACTICE_STABILITY_FACT_INVENTORY.md`
12. `specs/001-lesson-practice-attempts-and-trustworthy-feedback.md`
13. `adr/001-practice-snapshots-attempts-and-deletion-authority.md`
14. `adr/002-controlled-practice-generation-grading-queue-and-trace.md`
15. `specs/004-controlled-python-execution-mcp-lab.md`
16. `adr/006-product-owned-mcp-python-execution-boundary.md`
17. `specs/005-practice-generation-and-grading-stability.md`
18. `adr/007-versioned-practice-artifact-validation-and-repair-authority.md`

再完整读取当前相邻代码和测试，至少包括：

- `academic_companion/practice_agents.py`
- `academic_companion/course_agents.py`
- `apps/api/learn_platform_api/services/practice_type_adaptation.py`
- `apps/api/learn_platform_api/services/practice_generation.py`
- `apps/api/learn_platform_api/services/practice.py`
- `apps/api/learn_platform_api/practice_workers.py`
- `apps/api/learn_platform_api/db/models.py`
- `apps/api/learn_platform_api/schemas/practice.py`
- `apps/api/learn_platform_api/routers/practice.py`
- `apps/api/learn_platform_api/settings.py`
- `apps/shared/mcp_execution_contract.py`
- `apps/api/tests/test_practice_*.py`
- `apps/api/tests/test_slice4_codex_correction_013.py`
- `apps/api/stage4_eval/`
- `apps/web/src/app/PracticePanel.tsx`、`CodeWorkbench.tsx`、`AgentRunsPanel.tsx`
- `apps/web/src/lib/api.ts`

## 5. 绝对禁止

- 不按课程名、关键词、固定题干、固定 compiler 文本或 smoke 答案增加特判。
- 不取消 reference validation、减少 hidden-test 合同或发布失败题来提高成功率。
- 不把结构/reference 错误伪装成 transient 后无限 retry。
- 不新增第三项 MCP、任意 Tool discovery、网络、shell、依赖安装或产品内多 Agent。
- 不修改掌握度公式、Memory/Review 投影目标或让 Tool observation 直接产生学习事实。
- 不修改旧 migration；新 migration 必须为当前 head 后的单一增量。
- 不新增 `validation_stage`、诊断表或其他未批准 schema；运行中无法可靠投影精确阶段时显示“生成与验证中”。
- 不改 Judge0/VM/MCP 拓扑，除非 Phase A 证明现有 canonical MCP 合同自身冲突；此时停止重新 Gate。
- 不删除 lockfile、重建无关依赖、格式化无关文件或清理未知 dirty files。
- 不 commit、push、stash、reset、checkout、运行真实 OCR 或宣布 Stage 完成。

## 6. Phase A：无业务改动基线诊断

Phase A 只允许新增测试/fixture 和 `SLICE_5_GLM_BASELINE_REPORT.md`，不得修改产品业务代码、migration、Web 或既有合同文档。

### 6.1 建立失败阶段矩阵

对当前 v1 链路逐步标注：

- profile/suitability；
- evidence search；
- artifact Pydantic/schema/citation/target/formula/novelty；
- coding canonical wrapper/reference/starter；
- science answer verification；
- final authority/commit；
- coding/scientific grading 与 learning projection。

对每阶段记录现有 error code、是否 repair、是否 retry、provider/tool call 数、是否产生 Set/Feedback/Learning Event。只保存合成 fixture 和安全统计。

### 6.2 三语言真实 compiler/runtime 基线

新增独立 Slice 5 测试文件，不继续堆叠 `correction_014` 命名。至少覆盖：

- Python/Java/C++ 正确 reference；
- compile error、runtime error、test mismatch；
- 空输入、Unicode、CRLF/LF、多行输出、空白规范化；
- numeric tolerance 边界；
- Java `public/non-public Solution`、禁止 `Main/main/package`；
- C++ `std::string/string`、禁止 `main`；
- starter 空、合法 scaffold、泄露完整解；
- public + hidden tests 权重与 safe summary。

先用本机 compiler 做快速 fixture，再通过现有产品 MCP adapter 对合成代码做最小三语言 Judge0 probe。不得直接 curl Judge0、不得记录 URL/source/test 正文。若产品 MCP probe 需要读取 secret 或环境不 ready，跳过真实 probe并在报告中说明，不能伪报通过。

### 6.3 验证六项根因假设

逐项给出 `confirmed | rejected | unresolved` 与证据：

1. provider/validator/wrapper/Judge0 canonical source 不一致；
2. repair 信息不足；
3. 整组 repair 放大；
4. 预算口径冲突；
5. 自动化代表性不足；
6. 科学题 deterministic evidence 不完整仍被 LLM 评分。

不得因为 Java/C++ 人工成功率为 0 就预先确认任一项。真实 provider 根因无法在无凭据环境确认时标为 unresolved，并给出后续最小真实 Gate case。

### 6.4 Phase A 验证

至少运行：

```powershell
cd C:\Users\Admin\Desktop\HelloAgents-LearnPlatform\apps\api
.venv-test\Scripts\python.exe -m pytest tests/test_slice4_codex_correction_013.py -q -p no:cacheprovider
.venv-test\Scripts\python.exe -m pytest tests/test_slice5_practice_stability.py -q -p no:cacheprovider
```

若 Docker test stage 可用，再运行新增 focused tests；报告 Python 版本、compiler 路径差异、passed/failed/skipped 和真实原因。

### 6.5 Phase A 回交并停止

新增 `docs/04-platform-stage-4-practice-memory-and-review/SLICE_5_GLM_BASELINE_REPORT.md`，包含：

1. 当前 HEAD/branch/dirty files；
2. 实际环境与未读取敏感配置声明；
3. 完整链路和阶段矩阵；
4. 六项假设的 confirmed/rejected/unresolved；
5. 三语言 compiler 与产品 MCP probe 结果；
6. 当前错误/repair/retry/预算冲突；
7. 建议修改文件和为何符合 Spec/ADR；
8. 所有命令、结果和未运行原因；
9. 新增测试文件；
10. 是否发现需要额外 schema、状态、预算或范围。

写完后停止。不得继续 Phase B。Codex 将独立阅读 diff/报告并明确回复“继续 Phase B-F”或发修正指令。

## 7. Phase B：版本与最小 migration

仅在 Codex 明确放行后执行。

### 7.1 Migration

在当前 Alembic head 后新增 migration（预计为 0023，但以实际 head 为准）：

- `practice_jobs.artifact_contract_version`，有限长度字符串；
- 既有行回填 `practice_artifact_v1` 后设为 non-null；
- 新 Job 显式写版本，不依赖长期 server default；
- downgrade 只删除该列；
- 不修改旧 migration 或历史 Practice Set/Item。

真实 Postgres migration test 必须使用隔离测试数据库，不对当前开发 volume 执行 downgrade。覆盖旧 head -> 新 head、backfill、non-null、downgrade/upgrade 和 ORM 一致性。

### 7.2 Snapshot 与幂等

- create Job 时固定 artifact version；request hash 包含版本。
- retry、duplicate delivery、reconciler 和 late worker 使用 Job snapshot，不读部署当前默认切换版本。
- Set 成功时写 `generation_config.artifact_contract_version` 和 novelty policy version。
- coding Item 的 `answer_spec.harness_version` 与 `interaction_spec.contract` 必须一致。
- 缺失 Item/Set version 按 v1，不能静默升级。

## 8. Phase C：v2 Artifact、canonical harness 与 validator

### 8.1 Domain contract

在 `academic_companion` 保持纯 Pydantic/dataclass/prompt builder，不连接数据库、HTTP、MCP 或产品 queue。

- 建立明确 v2 artifact/Item repair artifact；repair 只返回失败 Item，固定 item key、target、type、language 和 citations。
- 每 Set 最多一个 specialized item；多题 Set 至少一个普通题。
- scientific 必须有 normalized answer、完整 worked solution、rubric、tolerance/unit/equivalence/provenance。
- prompt 提供 canonical contract 和正反结构示例，但不能针对固定课程/题目硬编码。

### 8.2 Canonical v2

- Python：唯一 `solve(input_text)`；无 `__main__`、文件/网络/依赖。
- Java：`Solution.solve(String)`；产品唯一 `Main`；拒绝 package/Main/main/外部依赖。
- C++：`solve(const std::string&)`；产品唯一 main/includes；拒绝 provider main/外部依赖。
- 只做 ADR 允许的无语义 normalization；不修改算法、expected output 或 tests。
- UTF-8、escaping、empty/multiline/CRLF 和 numeric comparator 三语言一致。

不得复制第二套 MCP protocol client。继续经共享 execution contract 与现有 product-owned service 调用。

### 8.3 Validator 顺序

实现并测试：

```text
profile/scope
-> suitability/auth/readiness
-> evidence
-> schema/citation/target/formula
-> exact/near novelty
-> coding contract/reference/starter 或 science reference
-> final authority
-> atomic commit
```

所有失败零 Set/Item/Citation。修复后重跑失败 Item 的全部后续 Gate。

## 9. Phase D：repair、retry、预算与错误投影

### 9.1 预算

落实 Spec 005：

- search plan 1、search 3；
- initial artifact 1；
- structure/novelty repair 合计 1；
- specialized Item repair 1；
- provider calls 总计 4；
- reference 初次/repair 后各 1；
- starter leak 初次/repair 后各最多 1；
- science generation calls 每 Set 3；
- attempt 总 step 12；
- transient delivery attempts 3；
- wall time 10 分钟。

只保留一套运行时权威 step counter。移除未使用/冲突配置，或保留兼容字段但不得继续形成第二有效口径。不得借 retry 扩大 auth/source/schema snapshot。

### 9.2 错误

实现 Spec 005 第 8 节稳定码，并确保：

- Pydantic/citation/formula/duplicate/canonical/reference/science/infra/budget/cancel 分开；
- compiler/provider/Tool 原文不进入 API、日志、trace 或报告；
- UI 映射为材料、artifact、reference、科学验证、基础设施、预算、取消；
- running 无可靠精确阶段时显示“生成与验证中”；
- retry 按钮只对权威可重试故障启用。

### 9.3 单题 repair

- 合法普通题、target、citation ledger、题数不漂移；
- reference repair 只获取语言、contract version、稳定类别和有界位置摘要；
- 不给 provider hidden input/output、harness、远端正文或完整错误输出；
- repair 失败不降级 required 类型、不减少题数、不发布部分 Set。

## 10. Phase E：评分权威与学习副作用

### 10.1 Coding

- grader 按 Item harness version 分发 v1/v2；
- source + immutable tests 只执行一次正式评分；基础设施 retry 不新增正式结果；
- compile/runtime/timeout/output-limit 为学生程序结果，产生确定性 0/部分分和安全反馈；
- MCP infra failure 不产生 0 分/Feedback/Learning Event；
- LLM feedback provider 失败时保留确定性分和最小安全反馈；
- hidden tests/reference/harness/source 不泄露。

### 10.2 Scientific

- exact/numeric 可本地充分判定时零 Wolfram；
- 未授权且必须远程：正式 `ungradable`、score null、limitation、零学习投影；
- 临时工具不可用：Job retry/fail，不提交 Feedback；
- 工具成功但 observation 不足：`ungradable`、score null、零学习投影；
- LLM 评价推导步骤，不能把 unknown verification 变成数值结论。

### 10.3 权威与删除

保留现有 Attempt/Feedback immutable、idempotency、cancel/delete/lease/late-result 和 Workspace scope。v1/v2 均覆盖 Attempt/Set/Course/Workspace 删除；不得复活资源或遗留 source code/private grading facts。

## 11. Phase F：去重、Web 与 eval

### 11.1 去重

- 同 Lesson Version 最近 50 题、最多 6,000 字符安全题干摘要；
- exact normalized repeat 硬拒绝；
- same target/type/task signature + char 3-gram Jaccard `>=0.90` 硬拒绝；
- `0.75-0.90` 只作为一次 repair negative hint/观察，不硬拒绝；
- 中英文正反 fixture 必须证明同目标不同角度不会被普遍误杀；
- policy/version/threshold 写 Set generation config。

### 11.2 Web

保持 Reader 现有信息架构和 CodeMirror 工作台：

- 新 v2 coding 题显示人类可读 canonical contract；
- v1 题继续正常显示和提交；
- Job/Attempt 显示可行动错误和可重试性；
- science feedback 区分本地、Wolfram verified、未授权、不可用、结果不足；
- 不显示内部 error、source/test/harness、URL 或绝对路径；
- 桌面/窄视口、长错误文本、刷新恢复不重叠。

### 11.3 Eval

扩展 Stage 4 offline eval，至少覆盖 artifact variants、三语言 canonical 正反例、repair isolation、retry taxonomy、v1 compatibility、science authority、near duplicate 和零学习副作用。固定 fixture 不得主导产品 schema或写测试专用生产分支。

## 12. 必须新增/更新的测试

建议使用清晰的 Slice 5 文件名：

- `test_slice5_practice_stability.py`：domain/validator/harness/error/repair；
- `test_slice5_practice_worker.py`：Job/retry/budget/authority/side effect；
- `test_slice5_practice_migration_postgres.py`：隔离 Postgres migration；
- Web 现有测试体系若无组件测试框架，不临时引入大框架；以 TypeScript/lint/build 和人工 smoke 状态矩阵补充。

硬门禁包括：

- v1 read/grade；v2 snapshot/dispatcher；
- Java/C++ 真实 compile/run，不只字符串断言；
- reference 全过、starter 不泄露、代表性错误解不全过；
- repair 只替换失败 Item；
- exact/near bilingual boundaries；
- provider/MCP/queue retry 与确定性错误不 retry；
- cancellation/deletion/late delivery；
- failed/ungradable 零 Learning Event/Mastery/Memory；
- public API/Web/trace/log safe projection。

## 13. 验证命令与环境选择

### 13.1 API focused

快速 focused 可用本机 venv：

```powershell
cd C:\Users\Admin\Desktop\HelloAgents-LearnPlatform\apps\api
.venv-test\Scripts\python.exe -m pytest tests/test_slice5_practice_stability.py tests/test_slice5_practice_worker.py -q -p no:cacheprovider
.venv-test\Scripts\python.exe -m pytest tests/test_practice_domain.py tests/test_practice_worker.py tests/test_practice_api.py tests/test_slice4_codex_correction_013.py -q -p no:cacheprovider
```

正式 API/MCP 回归首选 Docker test stage：

```powershell
cd C:\Users\Admin\Desktop\HelloAgents-LearnPlatform
docker build --target test -t helloagents-api-slice5-test -f apps/api/Dockerfile .
docker run --rm helloagents-api-slice5-test python -m pytest -q <focused paths>
docker run --rm helloagents-api-slice5-test python -m pytest -q
```

所有 skip/timeout 必须列出，不得把 focused 当 full。

### 13.2 Migration

- 使用隔离 Postgres test database 验证旧 head -> 新 head、backfill、non-null、downgrade/upgrade。
- 禁止对当前开发 Postgres volume 做 downgrade。
- 报告实际 database kind；SQLite ORM test 不冒充 Postgres migration。

### 13.3 Web

```powershell
cd C:\Users\Admin\Desktop\HelloAgents-LearnPlatform\apps\web
npm.cmd run lint
npm.cmd run build
```

依赖已安装时不运行 `npm install`。确需更新依赖时先证明必要性；本 Slice 预计不新增前端依赖。

### 13.4 Compose 与回归

```powershell
cd C:\Users\Admin\Desktop\HelloAgents-LearnPlatform
docker compose config --quiet
docker compose build api web practice-worker mcp-execution capability-probe
docker compose up -d postgres redis qdrant mcp-execution api practice-worker capability-probe web
docker compose ps
docker compose exec api alembic current
curl.exe -fsS http://127.0.0.1:8000/ready
curl.exe -I http://127.0.0.1:8080/
git diff --check
git status --short --branch
```

同时运行 Stage 4 offline eval、完整 API pytest、MCP focused tests。GLM 不运行真实 provider、Wolfram、OCR、Chrome 人工 smoke 或破坏性删除 smoke。

## 14. 必须停下并报告的条件

- Phase A 需要读取 key、URL、真实用户资料或原始日志才能复现。
- 发现 Java/C++ 失败来自共享 MCP/Judge0 schema 或 VM 拓扑，必须修改 ADR 006 范围。
- 需要新增 `validation_stage`、诊断表、额外列/状态、多个 specialized item 或提高预算。
- 只能通过课程/关键词/题干/答案特判提高成功率。
- 无法保持 v1 历史可读/可评分。
- repair 必须看到 hidden tests、完整 compiler/provider 原文才可工作。
- 需要修改 Mastery/Memory/Review 规则或让 ungradable 产生学习事实。
- migration 不能安全 backfill/downgrade，或只能在当前开发 volume 验证。
- 发现未知 dirty change 与本任务文件冲突。
- 真实 provider/Wolfram/OCR/付费操作成为继续条件。

停止对应 Phase并精确报告，不得降低合同或用 fallback 冒充完成。

## 15. 最终回交报告

Phase B-F 完成后新增 `SLICE_5_GLM_HANDBACK_REPORT.md`：

1. 修改/新增文件与完成 Phase；
2. baseline findings 如何被采纳或排除；
3. migration、v1/v2 snapshot/dispatcher 和 downgrade/backfill；
4. 三语言 canonical、reference/starter repair 与真实 compiler/MCP 结果；
5. science 本地/远程/ungradable/infra 分界；
6. budget、retry、error、safe trace 和 UI 投影；
7. exact/near duplicate 算法版本与正反例；
8. idempotency/cancel/delete/late-result/learning side-effect；
9. 每条验证命令、passed/failed/skipped/timeout；
10. 未运行的真实 provider/Wolfram/OCR/Chrome/删除 Gate；
11. 需要 Codex 独立复核的高风险点；
12. 完整 `git status --short --branch`。

然后停止。不得 commit、push、OCR 或宣称 Slice 5/Stage 4 完成。

## 16. 给 GLM 的首次接手 Prompt

```text
你正在正确仓库 C:\Users\Admin\Desktop\HelloAgents-LearnPlatform 执行 Platform Stage 4 Slice 5。

先完整读取根 AGENTS.md、四份高层指导文档、Playbook、GLM 交接流程，以及任务包列出的 Stage 4/Slice 4/Slice 5 Spec、ADR、总结、review、代码和测试。Spec 005 与 ADR 007 已通过人工 Gate，不能自行改变。

本轮只执行任务包 Phase A：新增独立 Slice 5 基线测试和 SLICE_5_GLM_BASELINE_REPORT.md，调查 Java/C++ 为 0 及完整生成/评分链路。不得修改产品业务代码、migration、Web 或合同文档。不得读取/输出 .env、key、内部 URL、真实用户资料、prompt、日志、hidden tests/reference/provider 原文。不得回滚未知 dirty files、commit 或 push。

完成 Phase A 报告和指定 focused tests 后停止回交，等待 Codex 明确允许继续 Phase B-F。
```

## 17. Phase B-F 恢复 Prompt

Codex 复核 baseline 后，只有收到以下含义明确的指令才继续：

```text
基线报告已由 Codex 复核。按 SLICE_5_GLM_IMPLEMENTATION_PACKET.md 继续 Phase B-F；保持 Spec 005/ADR 007、当前 dirty files 和所有敏感边界。发现任务包停止条件立即停下报告，不自行扩 schema、预算或范围。
```
