# Stage 4 Slice 5 GLM 人工 Smoke 修正任务包 002

状态：2026-07-23 人工 Gate 已确认。目标是继续修复编程练习生成低成功率，并将**练习生成链**从 DeepSeek v4 Flash 切换到 v4 Pro 做受控对照。完成后停止回交 Codex；不得 commit、push 或自行运行大规模真实 provider eval。

## 1. 已确认事实

Codex 从产品数据库只读取了 Practice Job、AgentRun 和 AgentToolCall 的安全投影，没有读取 prompt、provider 原文、hidden tests、上传正文、key 或内部 URL。

最近 14 个带编程语言选择的生成 Job 中，真正进入 coding reference/starter 验证的 9 个 Job 只有约 3 个成功。主要失败簇：

1. `ValidateCodingReference: reference_failed_tests` 后，`RepairSpecializedItem: invalid_practice_artifact`；
2. `SubmitPracticeSet: practice_artifact_schema_invalid` 先消耗 whole-Set repair，随后 coding reference 失败并触发 `practice_budget_exceeded`；
3. Java 的 `coding_reference_test_failed` 明显多于成功；
4. `ValidateCodingReference/Starter: infrastructure_failure` 偶发存在；
5. 少量 novelty repair 后仍为 `practice_duplicate`。

这证明当前主要问题已不是单一 Java wrapper，而是：

- specialized repair 的返回合同过宽且脆弱；
- schema 错误没有充分区分 Set 结构与单个 specialized Item；
- repair 失败信息与再次验证之间缺少可执行、有限且安全的反馈；
- 基础设施失败与内容失败仍可能放大重试成本；
- Flash 对复杂 JSON、不可变字段和可执行 reference 的遵循率不足。

## 2. 模型决策

人工已明确批准：将**练习生成及其生成期 repair 调用**从 `deepseek-v4-flash` 切换为 `deepseek-v4-pro`，观察 Java/C++ 成功率是否改善。

边界：

- 新增 `practice_generation_model` 独立配置，默认 `deepseek-v4-pro`。
- `practice_generation.py` 的 plan、initial generation、structure/novelty/specialized repair 均使用该配置。
- Tutor、课程生成、RAG answer 和练习简答评分继续使用现有 `product_generation_model`，不得因本任务整体切换到 Pro。
- Docker Compose 为 API 和 practice-worker 显式传入：
  `PRACTICE_GENERATION_MODEL=${PRACTICE_GENERATION_MODEL:-deepseek-v4-pro}`。
- 更新 `.env.example`，但不得读取、修改或提交真实 `.env`。
- AgentRun/Job 的安全 trace 应能记录实际 model；若当前 generation run 没有 model 字段，不新增 migration，只在现有允许的 generation config/trace 投影中记录。需要 schema 才能完成时停下回交。
- 不增加 provider call、attempt step、search、tool 或 token 上限。

模型升级不能替代 deterministic schema、compiler、hidden-test、immutability 和 duplicate gate。

## 3. 修复目标

### A. 最小 specialized repair DTO

不要再要求 provider 为 coding specialized repair 返回完整 `PracticeSetArtifact` 或完整 Item。

新增严格、额外字段禁止的最小响应模型，例如：

```text
CodingReferenceRepairArtifact
  item_key
  reference_solution
  starter_code (optional)
```

要求：

- 只允许上述字段；
- `item_key` 必须与失败 Item 一致；
- hidden_tests、stem、citation_ids、public_examples、constraints、语言、输入输出合同和 rubric 根本不进入 provider 可返回的 schema；
- merge 仍从 original Item 复制所有不可变字段；
- repair 响应 malformed 时稳定归类为 `coding_repair_artifact_invalid` 或 Spec 005 已有等价稳定码，不能塌缩成普通 schema 错误；
- scientific repair 若共用当前宽合同，也建立对应最小 DTO，但不得改变科学评分权威。

### B. 分流 Set 结构错误与 specialized Item 错误

当前 `validation_issues()` 和 whole-Set repair 不能把所有 schema/citation/formula 问题视为同一类。

实现有界分类：

- Set 级：item count、target coverage、重复 item_key、跨 Item 约束、citation ledger 等；
- 普通 Item 级：single-choice/short-answer schema；
- specialized Item 级：coding/scientific 字段、canonical source、reference/starter contract。

行为：

- 只有真正的 Set/跨 Item 结构错误才使用 whole-Set structure repair；
- 单个 coding/scientific Item 的结构错误直接进入最小单题 repair；
- 单题 repair 只替换允许变化字段，合法兄弟 Item 字节级保持不变；
- structure 与 novelty 仍共享现有一次修复机会；
- 不通过降低 validator 要求换取成功率。

若 Pydantic 在当前解析阶段无法恢复到具体 Item，先做两阶段解析：外层 Set envelope/identity，再逐 Item 严格验证。不得以字符串搜索异常文本作为长期分类器。

### C. 改善 coding repair 输入

repair prompt 继续禁止传入 hidden input/output、完整 harness 和 provider 原始观察，但应提供：

- 稳定失败类别：compile、runtime、test mismatch、starter reveals solution；
- 语言和 harness version；
- 有界、脱敏的位置摘要；
- public input/output contract；
- 明确的 canonical signature；
- Java 特别明确：无 package、非 public `Solution`、`static String solve(String input)`、不读取 stdin、不声明 Main；
- C++ 特别明确：只定义 `string solve(const string&)`、无 main、无非标准依赖。

位置摘要不得包含临时绝对路径、hidden test 内容或完整 compiler stderr；只保留阶段、return code、错误类别和有限行列信息。

### D. Repair 后再次验证与失败语义

- specialized repair 成功返回后，必须使用 original hidden tests 和 pinned harness version 重新验证；
- provider 返回的任何 tests 都没有权威；
- 修复 artifact 无效与修复后的 reference 再次失败使用不同稳定错误码；
- 已用完 provider 预算且 reference 仍失败时，最终用户错误应表达 reference 修复失败，而不是笼统声称“题数导致超预算”；内部 trace 可同时记录 budget exhausted；
- 不增加第二次 specialized repair。

### E. 基础设施失败隔离

- compiler/Judge0/MCP unavailable、timeout、connection failure 只进入 retryable infrastructure path；
- 不消费 specialized content repair 名额；
- 不把基础设施失败改写成 `coding_reference_test_failed`；
- retry 后仍使用同一 artifact contract/model snapshot；
- 无活动 retry 时最终错误保持可诊断。

### F. Novelty 与结构修复的组合

- 继续在初始 prompt 使用有界 prior stems；
- duplicate 只修重复 Item；
- 若 specialized Item 同时存在结构错误和 novelty 问题，优先形成一次包含两类公开约束的单题 repair，而不是先 whole-Set repair 再单题 repair；
- deterministic duplicate gate 必须保留。

## 4. 必须新增的测试

### 最小 repair 合同

- provider 只返回 `item_key/reference_solution/starter_code` 时成功；
- 多返回 `hidden_tests/stem/citation_ids/language` 时因 extra forbidden 拒绝；
- 错 item_key 拒绝；
- malformed minimal artifact 得到稳定 repair-artifact error；
- 合法兄弟 Item 和 original hidden tests 保持不变；
- repair 后仍失败时不再调用 provider。

### 错误分流

- Set 级错误只走 whole-Set repair；
- coding Item schema/canonical 错误只走 specialized repair；
- coding Item 错误不重生成整 Set；
- coding Item + novelty 组合仍只替换该 Item；
- infrastructure failure 零 specialized repair call，并进入 retryable 状态。

### 模型配置

- `Settings().practice_generation_model == "deepseek-v4-pro"`；
- practice generation 的每类 provider call 使用 `practice_generation_model`；
- Tutor、course generation、RAG answer 和 grading 没有被意外改成该配置；
- Compose API/practice-worker 环境包含独立配置且默认 Pro；
- `.env.example` 只包含变量名和公开默认值，不含 secret。

### 按语言 Gate

离线 fixture 至少覆盖：

- Python happy + reference repair；
- Java happy、compile failure、test mismatch、repair success、repair invalid；
- C++ happy、compile failure、test mismatch、repair success；
- Java/C++ infrastructure failure。

测试必须执行真实 generation orchestration；纯源码字符串检查、手写整数相加或仅验证常量不算行为测试。

## 5. 真实模型对照 Gate

实现期间不得由 GLM 自动运行真实 provider。

回交后由人工/Codex显式执行小样本对照：

- 固定同一批已脱敏 lesson fixtures；
- Flash 基线使用现有历史安全统计，不重新大量调用；
- Pro 新样本：Python、Java、C++ 各最多 5 个 generation Job；
- 总 provider call 上限由运行前人工再次确认；
- 统计：Set 成功率、首次 artifact 合法率、reference 首次通过率、repair 合法率、最终成功率、平均 provider calls 和 steps；
- 不保存 prompt、题目正文、provider 原文或 hidden tests；
- 结果不足以证明改善时不得宣称 Pro 已解决问题。

## 6. 允许修改范围

优先限制在：

- `apps/api/learn_platform_api/settings.py`
- `apps/api/learn_platform_api/services/practice_generation.py`
- `academic_companion/practice_agents.py`
- `docker-compose.yml`
- `.env.example`
- Slice 5 focused tests/eval
- Correction 002 handback report

不得修改 schema/migration、公开 API、Practice Job 状态、评分权威、duplicate 阈值或预算上限。

## 7. 停下重新 Gate

以下任一情况立即停止对应部分：

- Provider calls 从 4 提高到 5 或任何预算增加；
- 新增 migration、数据库列、公开状态或 API；
- 放宽 hidden tests/compiler/immutability/duplicate gate；
- 需要读取 `.env`、key、provider 原文、hidden tests、上传正文或敏感日志；
- 需要自动真实调用 Pro/Flash、Judge0 或 Wolfram；
- 需要让 Tutor、课程生成或 RAG 默认切换到 Pro。

## 8. 验证与回交

至少运行：

```powershell
git diff --check
cd apps/api
.\.venv-test\Scripts\python.exe -m pytest -q `
  tests/test_slice5_practice_stability.py `
  tests/test_slice5_practice_worker.py `
  tests/test_slice5_repair_immutability.py `
  tests/test_slice5_smoke_correction_001.py `
  <Correction 002 新测试> `
  --basetemp=.pytest-tmp-slice5-c002
cd ../web
npm.cmd run lint
npm.cmd run build
```

新增：

`SLICE_5_GLM_SMOKE_CORRECTION_002_HANDBACK.md`

报告必须包含：

- 修改文件和依赖边界；
- 每个失败簇的旧路径、新路径及测试；
- Flash → Pro 的实际配置作用域；
- 按语言离线 Gate 结果；
- 未运行的真实 provider Gate；
- 预算、schema、状态和敏感边界未改变的证明；
- 未解决风险。

完成后停止。不得 commit、push、重建生产容器、修改真实 `.env` 或宣布编程生成成功率已经改善。
