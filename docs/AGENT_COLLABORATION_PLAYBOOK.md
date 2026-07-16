# Agent 协作开发 Playbook

版本日期：2026-07-16

状态：当前开发流程

## 1. 目标

把 Agent 用于可审查、可验证、可回退的软件开发，而不是让聊天记录代替需求、测试和架构决策。

本项目默认采用：

```text
事实盘点
  -> spec/ADR
  -> 实现计划
  -> 小范围实现
  -> focused verification
  -> self-review
  -> 必要时独立 review
  -> 人工 gate
  -> 阶段总结
```

## 2. 开始任务时必须提供

非平凡任务至少明确：

| 项目 | 内容 |
|---|---|
| Goal | 用户或系统最终获得什么行为 |
| Context | 当前代码、相关历史和已确认决策 |
| Constraints | 不允许修改的范围、依赖、安全与兼容要求 |
| Done when | 可运行的验证命令和人工验收条件 |

模糊需求先分析或写 spec，不通过实现反向定义需求。

## 3. 事实优先级

```text
当前正确仓库代码和可重复验证
  > 已接受 ADR/spec
  > 当前四份高层指导文档
  > 历史总结和误仓库参考实现
  > 聊天记录中的临时假设
```

旧报告中的“已通过”不能替代当前环境重跑。缺依赖、环境失败和代码行为失败必须分开记录。

## 4. 文档工作流

### 路线图

定义 Stage 顺序、用户价值、非目标和完成 Gate，不写逐文件实现细节。

### Spec

用于一个 Stage 或功能切片，至少包含：

- Goal 和 Context。
- 用户故事与关键流程。
- 范围、非目标和文件边界。
- API/数据模型草案。
- 失败模式。
- 验收条件与验证命令。

### ADR

用于不可逆或跨模块决策，例如：

- framework/product 边界。
- 数据事实来源。
- schema、migration、删除和重建语义。
- 任务队列、provider、权限和部署形态。

### 面向人工评审的写法

Spec/ADR 首先是给人做产品与工程决策的材料，不是把实现笔记换成正式标题。默认采用以下顺序：

1. 开头先给“评审结论摘要”或“决策摘要”，让评审者不读实现细节也能知道要接受什么。
2. 明确区分“当前已验证事实”“本次建议”“尚待人工选择”，不得把建议写成既成事实。
3. Spec 先写用户流程、目标、非目标、不变量和失败行为，再写 schema/API 草案与实现顺序。
4. ADR 一份只解决一个相对独立的跨模块决策，包含背景、决策、影响、未采用方案、待确认项和生效条件。
5. 状态机、数据所有权、失败矩阵和 Gate 优先用短表格或简单流程图；避免连续堆叠只有 Agent 容易解析的字段清单。
6. 文档结尾列出可逐条回答的人工 Gate。评审接受的是这些决策，不是笼统的“文档没问题”。
7. 规格仍需足够具体到可测试，但不提前承诺尚未确认的 provider、阈值或后续 Stage 能力；候选默认值必须标出理由和调整代价。

### 阶段总结

记录实际完成、验证结果、暂缓风险和下一阶段输入。旧计划完成后收敛进总结，避免文档根目录持续堆叠相互冲突的“当前计划”。

## 5. 风险等级

| 等级 | 示例 | 默认处理 |
|---|---|---|
| L0 | 解释、盘点、只读分析 | 可直接进行，说明来源和假设 |
| L1 | 文档、测试、小修 | 可实现，运行最窄检查 |
| L2 | 小 API、UI 组件、adapter | 先有 spec，补 focused tests |
| L3 | schema、删除、权限、队列、部署、解析/成本预算 | 先有 spec/ADR，独立 review 和人工 gate |
| L4 | 大迁移、生产部署、批量数据操作 | 分阶段执行，每个阶段人工批准 |

误仓库到正确仓库的代码采用属于 L3/L4，不做整提交 cherry-pick 或无审查目录覆盖。

## 6. 实现规则

- 先读当前代码和相邻测试，遵循已有模式。
- 小步修改，不混合功能、重构、格式化和文档大改。
- 保留用户或其他 Agent 的未知改动，不主动回滚。
- 产品依赖不污染 `hello_agents` framework 包。
- `apps`、`academic_companion`、`hello_agents` 遵守已接受的单向依赖。
- 数据库和删除行为先定义事实来源、失败恢复和幂等。
- 配置、API key、用户资料正文和敏感 prompt 不进入日志或提交。

## 7. 验证基线

### 通用

```powershell
git diff --check
git status --short --branch
```

### Framework/domain Python

目标命令：

```powershell
python -m pytest -q
```

当前本机曾因缺少 `tiktoken` 在 collection 阶段失败。Stage 0R 必须先建立可复现依赖环境，再把该命令作为行为基线。不能为绕过依赖失败随意删除 import 或测试。

### Academic Companion Web prototype

```powershell
cd academic_companion/webui
npm.cmd run lint
npm.cmd run build
```

### Product app

Stage 1 建立后，应分别记录：

- API focused tests。
- migration test。
- Web lint/build。
- `docker compose config`、build、up、readiness 和业务 smoke。

真实 provider、OCR 或大规模 eval 必须显式触发，不作为每次小改的默认成本。

### 异步资料流与人工验收

上传、解析、重试、轮询和删除这类跨 API、worker、存储与 Web 的流程，不能只靠单元测试、API focused tests 或构建成功来判断完成。每个切片应给出一条人工浏览器 smoke：使用有代表性的真实资料，核对用户状态、失败提示、重试/删除结果、网络请求和控制台错误。

真实资料不应提交进仓库或日志。验收记录可以保留脱敏的资料类别、页数、文本量级、操作步骤和结果。人工验收发现的缺口不是偶发噪声：应先修复，再补一个可自动化的回归测试；确实无法自动化时，写明原因、风险和下一阶段输入。

资料解析的测试矩阵至少覆盖正常输入、空或损坏输入、格式/编码边界，以及会跨越存储层约束的规范化字符（例如 NUL、其他控制字符和 surrogate）。对于可能放大资源的格式，还必须覆盖预算触发后的失败路径，不能以静默截断冒充成功。

## 8. Review 策略

### Self-review

每次实现后检查：

- 行为回归和错误路径。
- 数据丢失、权限和敏感信息风险。
- 缺失测试。
- 是否扩大了约定范围。
- 文档与公开行为是否同步。

### 独立 review

OCR/OpenCodeReview 是本项目已经部署的独立代码评审工具。它用于补充 Codex self-review，尤其关注安全暴露、输入边界、容器、部署和测试缺口。

以下情况进入 OCR gate：

- Stage 末或较大 diff。
- schema、删除、权限和部署变更。
- 容器、安全暴露或输入边界。

文档-only 和小型低风险修改默认不运行真实 OCR。真实 review 会调用 OCR 自己配置的 LLM provider，未经用户要求或明确批准不运行。

标准预检：

```powershell
git status --short
git diff --stat
where.exe ocr
ocr version
ocr review --preview
```

准备运行真实 review 时再检查 provider：

```powershell
ocr llm test
```

### OCR 执行前的人工确认点

完成预检、明确审查路径/文件数/命令、并确认 provider 连通后，**不得直接启动会调用 provider 的 OCR 命令**。Agent 必须暂停并向用户说明：

- 将要审查的范围，以及为何选择该范围；
- 建议使用的命令、`--audience`、`--concurrency` 与 `--timeout`；
- 该命令会消耗 OCR provider 配额，且 `--timeout` 只是本地等待上限，不保证不产生消耗；
- 预期输出归档位置和 review 完成后会执行的修复/复验步骤。

仅在用户对这一次具体 OCR 执行明确确认后，才能运行真实 `ocr review` 或 `ocr scan`。若范围、命令、provider 或超时策略发生实质变化，应重新停下确认；不要把此前对其他范围或其他轮次的授权视为持续授权。预检、preview、版本查询和本地日志读取不属于此确认点。

小型 diff 的真实 review：

```powershell
ocr review --audience agent --background "brief business context"
```

`--audience agent` 只在结束时给出摘要，不适合需要观察进度的场景。较大的 Stage diff 应优先按风险边界做 full-file scan，而不是提高全量 diff review 的并发：

```powershell
ocr scan --preview --path apps/api/learn_platform_api
ocr scan --audience human --path apps/api/learn_platform_api --concurrency 1 --timeout 10 --background "brief business context"
```

按 API/数据链路、schema/部署配置、Web 等边界依次扫描；`ocr scan --path` 审的是完整文件而不是仅 Git diff，最后由 Codex 做一次跨块合同核对。`--timeout` 的单位是分钟，应先缩小范围并使用 `--concurrency 1`，再按 provider 实测调整，不因暂无摘要而无限延长等待。

### OCR token 预算与分块

`--timeout` 不是整次审查的 token 或成本上限；`--max-tokens-budget` 是整条 scan 命令共享的派发上限。当剩余预算小于下一个完整文件的预估值时，OCR 会跳过该文件，并可能仍输出“没有评论”或项目摘要；这只能说明命令结束，不能说明该文件已经审过。

本项目当前的默认协作约定是：**用户接受真实 OCR 不设 token 上限**，因此 Agent 不应自行添加 `--max-tokens-budget`，除非用户在某次明确要求成本上限。这个常设决定不替代“真实 OCR 执行前的人工确认点”：每次仍要先展示具体分块命令，再由用户决定自行执行或明确授权执行。

- 每次先对候选路径运行 `ocr scan --preview --path ...`，按风险边界拆分，使每一块的预计 OCR 时间不超过 10 分钟；保持 `--concurrency 1`，每块完成后再执行下一块。
- 当前 OCR CLI 只给出文件数和 token 预估、不直接给出时长。以本机已记录的实测作为保守换算：单块预估总量控制在约 **150K token 以内**，通常应落在 10 分钟内；若单文件本身超过此量，必须单独列为例外，说明预估、原因与预期时长后再确认。
- 每条真实 scan 命令使用 `--timeout 10`；它是单任务超时策略而非总时长保证。结束后必须核对 Summary 的实际文件数、token 用量及是否存在 `token_budget_reached` 或 timeout 告警。
- 只有用户在某次显式要求成本硬上限时，才使用 `--max-tokens-budget`；此时应按单文件或预估相近的小组拆分，并把每组预算设为不低于其中最大单文件预估值，避免未审即跳过。
- 以 `Tee-Object <同一路径>` 保存输出时，默认会覆盖此前不完整的 raw review；只有需要保留两次尝试作比较时才使用 `-Append` 或不同文件名。
- 发现预算截断、超时或遗漏文件后，不得把本组标为通过；先列出实际已审/未审文件，重新取得用户对重跑范围、预算或“不设上限”策略的确认。

若 Codex 运行环境不能把代码送往外部 provider，用户可在本地终端显式运行已确认的命令，并把输出保存到当前 Stage 的 `reviews/raw/`；Codex 读取归档后负责归类、修复、复验和写正式 review 结论。不得在命令、文档或日志中写入 OCR provider key，也不得为了分块 review 临时 stash、移动或提交未知改动。

finding 按 High/Medium/Low 分类。High 优先修复；Medium 结合上下文决定；Low 不盲改。暂缓或拒绝项记录原因并进入阶段输入。修复后运行正常测试，只有实质修复时才考虑一次复审，避免无限 review loop。

Stage 级 OCR 记录放入当前 Stage `reviews/`，至少包含：背景、命令、审查范围、finding、采纳/暂缓项和复验结果。OCR 命令超时后检查残留进程，避免继续消耗 provider quota。

OCR 是独立视角，不是人工验收的替代品。OCR、Codex self-review 与人工 smoke 分别覆盖静态代码风险、实现合同和真实交互/真实输入；三者出现不一致时，以可复现的运行事实为准，并将结论回灌到测试与阶段总结。

## 9. 人工 Gate

以下节点必须停下确认：

- Spec/ADR 从草稿转为接受。
- 开始 Stage 1 代码迁移或重建。
- 修改 schema、删除语义或权限边界。
- 引入新的默认服务或 provider。
- 执行真实部署、批量迁移或不可逆数据操作。
- 合并阶段性大提交。

Agent 可以完成分析、实现、测试和 review，但不能把“技术上能做”当作“产品决策已确认”。

## 10. 使用误仓库参考实现

允许：

- 阅读其高层设计、Stage 1 API/Web/Compose、测试和 review。
- 提取候选合同、失败经验和验证命令。
- 在正确仓库 spec/ADR 下逐文件采用。

不允许：

- 把误仓库测试结果冒充正确仓库当前验证。
- 整提交 cherry-pick 后再补需求。
- 用误仓库缺失 `academic_companion` 的假设设计产品边界。
- 同时迁入 Stage 1 骨架和 Stage 2 业务实现。

## 11. Agent 适合与不适合的任务

适合自主推进：

- 资产盘点、接口清单和文档同步。
- 按既有模式补 focused tests。
- 机械性目录整理和低风险 adapter。
- 运行验证并整理失败证据。

需要更强人工参与：

- 产品边界不清的功能。
- schema、权限、删除和数据迁移。
- 复杂前端信息架构。
- provider 成本、安全和生产部署。

## 12. 当前阶段用法

Stage 3 已于 2026-07-16 收尾并通过自动化、OCR 与人工 Gate。当前进入 Stage 4 事实盘点与 Spec/ADR 分析准备，尚未批准实现练习、掌握度、复习队列或长期 Memory：

- 实现按已接受 Spec/ADR 和 `SLICE_3_GLM_IMPLEMENTATION_PACKET.md` 小步推进，每批运行 focused verification 并保留未知改动。
- Stage 3 固定 eval 默认离线；真实 provider、OCR、人工 smoke、阶段大提交和 push 仍由各自 Gate 控制。
- Stage 4 必须先读取 Stage 3 总结和 Stage 4 输入，再盘点 prototype；Spec/ADR 人工 Gate 通过前不得实现业务 schema 或 Agent。
- 不借 Stage 3 收尾引入练习、掌握度、长期 Memory、Skill、MCP、自主多 Agent、金额账单或完整运维 dashboard。

相关文档：

- [仓库级 Agent 规则](../AGENTS.md)
- [文档索引](./README.md)
- [学习平台蓝图](./LEARNING_AGENT_BLUEPRINT.md)
- [开发路线](./SELF_HOST_DEVELOPMENT_ROADMAP.md)
- [Stage 3 Slice 3 实现任务包](./03-platform-stage-3-chapter-learning-and-tutor/SLICE_3_GLM_IMPLEMENTATION_PACKET.md)
- [Stage 0R Spec](./00R-platform-baseline-reconstruction/specs/001-correct-repository-baseline-reconstruction.md)
