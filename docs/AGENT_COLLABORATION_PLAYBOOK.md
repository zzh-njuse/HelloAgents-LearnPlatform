# Agent 协作开发 Playbook

版本日期：2026-07-10

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

### 阶段总结

记录实际完成、验证结果、暂缓风险和下一阶段输入。旧计划完成后收敛进总结，避免文档根目录持续堆叠相互冲突的“当前计划”。

## 5. 风险等级

| 等级 | 示例 | 默认处理 |
|---|---|---|
| L0 | 解释、盘点、只读分析 | 可直接进行，说明来源和假设 |
| L1 | 文档、测试、小修 | 可实现，运行最窄检查 |
| L2 | 小 API、UI 组件、adapter | 先有 spec，补 focused tests |
| L3 | schema、删除、权限、队列、部署 | 先有 spec/ADR，独立 review 和人工 gate |
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

真实 review：

```powershell
ocr review --audience agent --background "brief business context"
```

确认 review 范围和 provider 成本后，大 diff 可使用：

```powershell
ocr review --audience agent --concurrency 4 --timeout 15 --background "brief business context"
```

如果 `ocr` 不在 PATH，查找 `%USERPROFILE%\bin\ocr.exe`。不得在命令、文档或日志中写入 OCR provider key。

finding 按 High/Medium/Low 分类。High 优先修复；Medium 结合上下文决定；Low 不盲改。暂缓或拒绝项记录原因并进入阶段输入。修复后运行正常测试，只有实质修复时才考虑一次复审，避免无限 review loop。

Stage 级 OCR 记录放入当前 Stage `reviews/`，至少包含：背景、命令、审查范围、finding、采纳/暂缓项和复验结果。OCR 命令超时后检查残留进程，避免继续消耗 provider quota。

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

Platform Stage 0R 只进行：

- 文档规整与高层指导文档修缮。
- 依赖与测试基线。
- prototype contract inventory。
- Stage 1 输入准备。

在 Stage 1 spec/ADR 人工确认前，不迁移误仓库业务代码。

相关文档：

- [仓库级 Agent 规则](../AGENTS.md)
- [文档索引](./README.md)
- [学习平台蓝图](./LEARNING_AGENT_BLUEPRINT.md)
- [开发路线](./SELF_HOST_DEVELOPMENT_ROADMAP.md)
- [Stage 0R Spec](./00R-platform-baseline-reconstruction/specs/001-correct-repository-baseline-reconstruction.md)
