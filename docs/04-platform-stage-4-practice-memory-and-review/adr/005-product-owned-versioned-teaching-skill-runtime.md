# ADR 005：产品拥有的版本化教学 Skill 与 Tutor 执行边界

状态：已接受（2026-07-18 人工 Gate）

日期：2026-07-18

## 1. 决策摘要

教学方法正文由 `academic_companion` 领域层以不可变版本目录维护；Product Tutor 为所有 Slice 3 新 Turn 确定性加载 allowlist 中当前发布的 Skill，并在 `tutor_turns` 保存 Skill ID/version/content hash。v1 不让用户或模型自由选择通用 `SkillTool`，不建立数据库 Skill 市场，也不让 Skill 拥有学习状态。

Stage 3 普通 Tutor 仅作为离线 eval 基线和 Slice 3 前历史 Turn 的兼容路径保留，不作为生产用户选项。Slice 3 新 Turn 固定当前发布的 `evidence-guided-diagnostic-scaffold`。运行时仍沿用现有 Tutor queue、worker、AgentRun、证据检索、预算和最终提交权威。

## 2. 背景

Framework `SkillLoader/SkillTool` 解决的是 Markdown 方法论的渐进加载，不解决产品需要的选择权限、版本锚点、历史追溯、retry、删除、预算和 eval。若直接把通用 SkillTool 暴露给 Tutor，模型可以选择任意本地 Skill，实际版本难以稳定追踪，并会额外扩大工具和 step 边界。

另一方面，把整段教学 prompt 硬编码进 Product API 会反转 `apps -> academic_companion -> hello_agents` 的领域责任，也会继续形成不可评估的散落 prompt。

## 3. 决策

### 3.1 所有权与依赖

- `academic_companion/teaching_skills/<skill-id>/v1/` 保存不可变 `SKILL.md` 和必要的结构化定义；领域 adapter 输出 Skill metadata、计划 schema、回答 schema 和 messages。
- 可复用 `hello_agents.skills.SkillLoader` 解析文件，但 Product 不注册通用 `SkillTool` 给模型，不接受客户端路径或任意 Skill 名称。
- `apps/api` 拥有 allowlist、Turn 选择、版本/hash 快照、数据库权威、队列、权限、上下文最小化、trace 和公开投影。
- `apps/web` 只显示当前与历史 Skill/version，不读取 Skill 文件或 prompt，也不提供普通模式开关。

依赖保持 `apps -> academic_companion -> hello_agents`。

### 3.2 版本与不可变性

- Skill ID 和语义版本由目录及 metadata 共同定义，加载时计算规范化正文 SHA-256。
- 已发布版本不得原位改变语义；修订产生 v2。格式或错字若改变 hash，也视为新版本，避免历史 snapshot 失真。
- 当前发布版本为 v2；它修正 v1 在诊断/规划回答锚点、历史 scope 和课节证据范围上的合同缺陷。v1 目录和 allowlist 条目继续保留，历史 Turn 与 retry 仍解析各自快照版本。
- Product 启动/ready 检查 allowlist 指向的 Skill 是否存在、metadata 是否匹配、hash 是否可计算。
- Turn 创建时服务端写入 ID/version/hash；retry 解析原 snapshot。若部署已删除旧版，retry 明确失败，不改用新版。

### 3.3 Schema

在 `tutor_turns` 增加 `teaching_skill_id`、`teaching_skill_version`、`teaching_skill_hash`。Slice 3 前的历史 Turn 三者为空；Slice 3 新 Turn 由服务端保证三者全部非空。使用 check constraint 保证只能“全部为空或全部非空”。无需新增 Skill catalog 表；版本目录和部署 allowlist 是静态能力，Turn snapshot 是用户运行事实。

公开 API 返回稳定显示名与 version，不返回 hash 或 prompt。hash 仅用于服务端权威和安全 trace。

### 3.4 运行时

```text
Create Turn
  -> validate scope/session + resolve current published Skill
  -> snapshot Skill metadata
  -> existing Redis Tutor queue
  -> worker claims owner/lease
  -> deterministic Skill load + hash check
  -> structured plan (intent + queries + context use)
  -> bounded RAG and authorized learning-context selection
  -> structured answer + one repair
  -> final workspace/session/turn/owner/lease/source authority check
  -> atomic answer/citation/run commit
```

Skill load 是确定性服务步骤，不是一次 provider call。模型不能选择其他 Skill、修改预算或调用额外工具。

### 3.5 学习状态边界

- Product service 继续按 Workspace/Course/Lesson 精确过滤。
- 允许投影给诊断式 Skill：目标标题、Memory display text、公开 mastery band、weakness certainty/status、Completion 标题/日期，以及每类数量。
- 禁止：projection score、原始 Answer、rubric、Feedback、evidence 正文、Memory revision、其他 scope 和已删除/paused/archived Memory。
- Memory policy 关闭时不读取、不计数、不外发；Skill 不能要求绕过 policy。

### 3.6 失败与降级

- 计划 schema 无效可确定性退化为 `other + 原问题`，不做关键词分类。
- Skill 不可用、version/hash 不符或回答合同失败均使 Turn 失败并可重试，不自动改走旧基础 Tutor。
- 资料不足可以成功提交 limitation；它不是运行失败，也不能伪造 citation。
- provider、lease、取消、重复投递、来源降级和 late result 沿用 ADR 004（Stage 3）的权威检查。

### 3.7 Trace、删除与隐私

- trace 只保存 Skill ID/version/hash、选择结果类型、输入类别计数、step/token/latency/error，不保存正文。
- Session/Workspace 删除继续硬删除 Turn、citation、AgentRun 和 tool call；静态 Skill 文件不含用户数据，不随用户删除。
- 普通日志不得写 question、Memory、Completion、evidence、prompt、provider 原始响应或绝对 Skill 路径。

## 4. 备选方案

### 4.1 直接加强通用 Tutor prompt

拒绝。无法证明独立教学方法、版本和基线，也会继续产生散落、不可选择的 prompt 行为。

### 4.2 给 Tutor 注册通用 SkillTool，由模型决定加载

拒绝用于 v1。它扩大工具白名单和预算，选择不稳定，允许发现无关 Skill，并使历史版本和失败语义复杂化。未来多个受信 Skill 的路由需另行 ADR。

### 4.3 把 Skill 正文存入 Postgres 并建设管理 UI

拒绝。首个内置 Skill 没有运行时编辑需求；会提前引入发布、权限、迁移和不可信自定义代码问题。

### 4.4 向用户提供普通 Tutor 与 Skill 切换

拒绝。诊断式 Skill 已包含直接回答、解释、引用和拒答等普通问答能力，额外开关只增加理解和测试成本。普通 Tutor 只用于离线基线与历史兼容。

### 4.5 Skill 失败自动回退旧基础 Tutor

拒绝。会把用户选择和 eval 变成不可见的行为漂移，也可能把结构验证失败伪装成成功。

## 5. 后果

正面：

- 教学方法与产品事实、权限和版本边界清楚。
- 保留普通 Tutor 基线，可做同输入配对 eval。
- 不新增 provider 调用或任意工具权限。
- 历史 Turn 和 retry 可以说明实际采用的方法。

代价：

- 需要 migration、Skill 版本目录、ready 检查、API/Web 字段和新 eval。
- v1 只有一个内置 Skill，不支持用户自定义或自动路由多个 Skill。
- 旧 Skill 版本需随部署保留，直到相关历史 retry 政策另行改变。

## 6. 验证

- loader：metadata/version/hash、缺失、篡改、旧版本和路径注入。
- migration：历史 backfill、check constraint、upgrade/downgrade。
- API：自动 Skill snapshot、拒绝客户端伪造 Skill metadata、workspace/scope、幂等冲突和公开白名单。
- worker：duplicate delivery、retry 原 snapshot、owner/lease/cancel/late result 和 Skill 缺失。
- context：Memory policy、范围隔离、状态白名单、上限和敏感字段负面断言。
- eval：内部 baseline/Skill 配对、等价措辞、反例、引用、资料不足、结构修复与 prompt injection。
- Web/Chrome：选择、锁定、历史标识、状态保留、窄视口和长内容。

## 7. 人工 Gate

接受本 ADR 意味着确认：

1. v1 采用产品确定性选择，不给模型通用 SkillTool。
2. Skill 定义在领域层不可变版本目录，Turn 保存 ID/version/hash；不建数据库 Skill 市场。
3. 所有新 Turn 自动固定当前 Skill snapshot，retry 沿用原 snapshot；不增加用户切换。
4. Skill 可以读取安全学习状态投影，但不拥有或修改学习事实。
5. Skill 失败不静默回退旧基础 Tutor。
