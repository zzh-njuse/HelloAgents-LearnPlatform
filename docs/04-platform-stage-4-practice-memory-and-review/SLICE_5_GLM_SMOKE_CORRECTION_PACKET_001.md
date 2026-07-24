# Stage 4 Slice 5 GLM 人工 Smoke 修正任务包 001

状态：2026-07-23 人工 smoke 已确认问题；允许在本任务包边界内实现。完成后停止并回交 Codex，禁止 commit/push。

## 1. 目标

修复 Slice 5 首轮人工 smoke 暴露的生成稳定性、编程试运行状态和专注模式问题。此次是现有 Spec 005 / ADR 007 范围内的缺陷修正，不增加新的产品能力，不降低确定性验证门槛。

核心原则：

- “避免重复”必须前置到生成约束和有限单题修复；确定性重复拒绝仍保留为最后防线。
- 不通过盲目提高预算掩盖无效调用、重复调用或计数错误。
- 前端状态必须绑定当前 Practice Item；旧 Item 的异步结果不得污染新 Item。
- 前端 Java 试运行必须遵守后端 canonical source / harness 合同。

## 2. 仓库与基线

- 仓库：`C:\Users\Admin\Desktop\HelloAgents-LearnPlatform`
- 分支：`main`
- 基线 HEAD：`96a61eb`
- 当前工作树包含已接受的 Slice 5 实现、文档、测试以及 Codex 的删除链路修复。不得回滚、覆盖或清理任何未知 dirty file。
- 已按人工指令删除 workspace-4 的全部 10 个 Practice Set；当前该 workspace 的 Set、Item、ItemTarget、Attempt 和 Feedback 均为 0。历史终态生成 Job 保留。
- 不读取或输出 `.env`、key、内部 URL、provider 原文、上传原文、hidden tests 或敏感日志。

开始前完整读取：

- `AGENTS.md`
- `docs/README.md`
- `docs/LEARNING_AGENT_BLUEPRINT.md`
- `docs/SELF_HOST_DEVELOPMENT_ROADMAP.md`
- `docs/DATABASE_AND_DEPLOYMENT_PLAN.md`
- `docs/AGENT_COLLABORATION_PLAYBOOK.md`
- `docs/GLM_IMPLEMENTATION_HANDOFF_WORKFLOW.md`
- 本 Stage `README.md`
- `specs/005-practice-generation-and-grading-stability.md`
- `adr/007-versioned-practice-artifact-validation-and-repair-authority.md`
- `SLICE_5_GLM_IMPLEMENTATION_PACKET.md`
- `SLICE_5_GLM_HANDBACK_REPORT.md`

## 3. 人工证据

本机截图仅用于定位 UI，不得复制其中可能出现的用户内容到测试夹具：

- `C:\Users\Admin\Desktop\QQ20260723-170734.png`
- `C:\Users\Admin\Desktop\QQ20260723-172539.png`
- `C:\Users\Admin\Desktop\QQ20260723-174006.png`

已确认的代码事实：

- `PracticePanel.tsx` 对任意 `genJob.science_verification` 都渲染状态，因此普通生成也显示“本题未调用 Wolfram”。这不代表实际调用了 Wolfram，是错误且带噪声的 UI 投影。
- Tutor 右上角图标由 `TutorPanel.tsx` 的 `focused` 状态控制，原意是 Tutor 放大，不是编程专用能力；当前交互没有清晰价值且人工点击近似无效果。
- 编程专注模式只把缩小按钮放在 coding toolbar 内，却让全局上一题/下一题/删除操作保持 sticky。切换到非编程题后仍处于全屏状态，但退出按钮消失。
- `scratchRun` 是面板级单一状态，没有绑定 Item；切换 Item/Set 后会继续显示旧试运行结果。
- Web 的 Java wrapper 把含 `public class Solution` 的 starter code 写入 `Main.java`，再追加 `class Main`，稳定触发文件名编译错误。
- 后端已经把近期题干传给生成链并做 deterministic near-duplicate gate，但前置约束和有限修复仍不足，用户观察到重复题持续导致整次生成失败。
- v2 预算为 provider calls 4、attempt steps 12、searches 3。人工生成 4 道“挑战”题遇到超预算，必须先证明具体耗用链路。

## 4. 实现任务

### A. Wolfram 状态投影

1. 普通生成 Job 的 `not_used` 不再显示“本题未调用 Wolfram”。
2. 只有实际使用、失败，或科学题正式形成的可解释验证/不可评分状态才显示科学验证信息。
3. 生成 Job 是 Set 级状态，不得用“本题”误导用户。
4. 不改变 Wolfram 授权、调用或评分权威。

### B. Tutor 放大控件

删除 Tutor 面板的放大按钮、`focused` 状态和仅为该状态存在的无效样式。Tutor 放大与代码无关；本轮不另造新的 Tutor 全屏体验。

### C. 编程专注模式

1. 专注模式只服务当前 coding Item。
2. 进入专注模式后隐藏全局 `.practice-actions`，不显示上一题、下一题、删除 Set 或提交等会切换上下文的操作。
3. coding toolbar 的退出专注按钮必须始终可见；支持 `Escape` 退出。
4. 切换 Lesson、Set、Item，或当前 Item 不再是 coding 时，必须自动退出专注模式。
5. 删除当前 sticky action block，验证滚动时无漂移、遮挡和页面跟随问题。

### D. 试运行结果隔离

1. 将运行请求和结果绑定到发起时的 `practice_item_id`。
2. 切换 Lesson、Set、Item 时立即清除可见运行结果。
3. 修改 source code 或自测输入后，旧结果不得继续伪装成当前输入的结果。
4. 旧 Item 的迟到响应不得覆盖当前 Item；应丢弃或只写回对应 Item。
5. 不改变正式提交、hidden tests 或评分路径。

### E. Java canonical 试运行

1. Web 试运行 wrapper 与 v2 Java canonical 合同一致。
2. canonical starter 中的 `public class Solution` 必须能在 runner 使用的 `Main.java` 中编译；允许通用地移除 `Solution` 的 `public` 修饰，禁止按某道 LCS 题硬编码。
3. 同时覆盖空白、换行和 `public final class Solution` 等合理声明变体；不得误改字符串或注释中的文本。
4. Python/C++ wrapper 行为不得回归。
5. 最好将 wrapper 变成可独立单测的纯函数，避免测试复制实现。

### F. 重复题前置规避

1. 保留 0.90 hard reject / 0.75 soft observation 及 deterministic 最终 gate。
2. 初次生成 prompt 必须接收有界、脱敏的历史题目负例，并明确要求在任务目标、情境、数据和解题动作上产生实质差异，不能只改写措辞。
3. 检查 `prior_stems` 是否真实进入当前 provider 请求；补测试防止以后“后端查了但 prompt 没用”。
4. duplicate 命中后只修复该 Item，不得重生成整 Set，不得改变其他合法 Item 或不可变字段。
5. 结构修复已经消耗修复机会时，不得通过循环拒绝形成无意义重试。优先合并可同时表达的结构/novelty 反馈，或在现有 provider/step 上限内重排流程。
6. 最终仍重复时使用稳定 `practice_duplicate` 失败，不降低阈值、不直接放行。

### G. 四道挑战题预算

先新增可重复的阶段计数测试，覆盖：

- 4 道普通挑战题；
- 含一个 coding specialized Item；
- 含一个 scientific specialized Item；
- 初稿需要一次结构或 novelty 修复；
- specialized Item 需要一次单题修复的上界路径。

报告每条路径实际消耗的 plan/provider/search/tool/validation/repair/attempt steps，检查 off-by-one、重复验证、重复 starter 生成和无必要 provider call。

修复目标是在已批准的 provider calls 4、attempt steps 12、searches 3 内让正常的 4 道挑战题完成；不得直接提高上限。若证明批准预算无法覆盖 Spec 005 要求的最小合法路径，停止该项并提交精确计数与最小预算变更建议，等待新的人工 Spec/ADR Gate。

## 5. 必须新增的回归

- 普通生成的 `not_used` 不渲染 Wolfram 提示；真实 verified/failed 状态仍正确。
- Tutor 不再有放大控件或残余 focus 状态。
- coding focus 隐藏全局 actions，退出按钮存在，`Escape` 可退出；切换 Item/Set 自动退出。
- Item A 的运行结果不会出现在 Item B；A 的迟到响应不会覆盖 B。
- 修改代码或 stdin 后旧运行结果清除。
- Java canonical starter 经 Web wrapper 后不出现 public class / filename 冲突，并保持正确运行入口。
- initial prompt 带有有界 prior-stem/novelty 约束。
- 首次重复、单题修复后成功；合法兄弟 Item 字节级不变。
- 修复后仍重复稳定失败为 `practice_duplicate`。
- 四道挑战题的正常和边界 fixture 不误报 budget exceeded；计数断言明确。

测试不得依赖真实 provider、真实 Judge0/Wolfram、固定 smoke 题答案或 hidden tests。

## 6. 建议修改范围

优先限制在：

- `apps/web/src/app/PracticePanel.tsx`
- `apps/web/src/app/TutorPanel.tsx`
- `apps/web/src/styles.css`
- 相邻 Web 测试或新增 focused 测试
- `academic_companion/practice_agents.py`
- `apps/api/learn_platform_api/services/practice_generation.py`
- Slice 5 focused tests
- 本任务对应 handback report

如需跨出上述范围，先说明原因。不得趁机重构整页、改变导航、增加 schema/migration/API 状态或扩展 MCP capability。

## 7. 停下重新 Gate

出现以下任一情况立即停止对应实现并回交：

- 提高 provider/search/attempt/tool 预算；
- 改变重复阈值、允许重复题通过或增加无界重试；
- 新增 schema、migration、Job 状态或公开 API 合同；
- 改变科学评分权威、Wolfram 授权或远程执行边界；
- 需要读取 secret、provider 原文、上传原文或 hidden tests；
- 需要真实付费 provider/Judge0/Wolfram 调用。

## 8. 验证

至少运行并如实报告：

```powershell
git diff --check
cd apps/api
python -m pytest -q tests/test_slice5_practice_stability.py tests/test_slice5_practice_worker.py tests/test_slice5_repair_immutability.py
cd ../web
npm.cmd run lint
npm.cmd run build
```

再运行受影响的 Practice API/Web focused tests。若仓库已有 Playwright/browser 测试能力，应在桌面和窄屏各验证一次；否则把以下步骤留给 Codex 人工浏览器 Gate，不得写成已通过：

- 普通生成期间无 Wolfram `not_used` 噪声；
- Tutor 无无效放大图标；
- coding focus 滚动、退出和切换行为；
- 两个 coding Item 间试运行结果隔离；
- Java starter 试运行不再因 `Solution.java` 文件名失败；
- 4 道挑战题生成与重复题修复路径。

## 9. 回交格式

新增 `SLICE_5_GLM_SMOKE_CORRECTION_001_HANDBACK.md`，包含：

- 修改文件；
- 七项问题逐项的根因、修复和测试证据；
- 每条预算路径的阶段计数；
- 未运行检查及具体环境原因；
- 未解决风险和需要重新 Gate 的事项；
- `git status --short`、测试、lint/build 与 `git diff --check` 结果。

完成后停止，等待 Codex 独立复核。不得 commit、push、清理未知文件或进入科学题人工 smoke。
