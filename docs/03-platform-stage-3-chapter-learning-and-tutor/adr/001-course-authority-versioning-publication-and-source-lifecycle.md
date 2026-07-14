# ADR 001：课程事实、版本、发布与来源生命周期

状态：已接受（2026-07-14 人工 Gate）
日期：2026-07-13
适用阶段：Platform Stage 3 Slice 1

## 1. 决策摘要

Stage 3 将 Course 建模为 workspace 内独立、可删除的产品资源；将 Course Version 和 Lesson Version 建模为不可原地改写的内容快照。Postgres 是课程身份、来源快照、结构、发布状态、引用和删除状态的唯一事实来源。

每个 Course Version 固定一组精确的 `document_version_id`，不自动跟随资料的 current version。只有通过完整校验且至少包含一个已发布课节的 Course Version 才能被显式激活。生成失败、重试或取消不得覆盖当前激活课程或已发布课节。

来源资料被换版、删除或失去 ready 状态后，不级联删除课程，也不静默改用新版本。受影响课程进入 `source_degraded`；已有发布内容仍可阅读，但受影响引用显示不可用，并禁止继续生成、发布或激活，直到用户基于有效来源创建新的 Course Version，或删除该课程。

## 2. 背景

Stage 2 已经确立以下事实：

- document 是稳定身份，document version 是不可变内容版本；
- 只有 active/current/ready version 可以进入正常检索和回答路径；
- citation 必须回到 Postgres 校验 workspace、document、version 和 chunk；
- Qdrant 可重建，不能成为课程发布或引用可用性的事实来源。

Stage 3 需要在这些资料事实之上增加可长期阅读的课程。如果课程只保存“当前文档”或一份可变 JSON，那么资料换版、生成重试和课程发布会互相覆盖，用户也无法判断当前课程究竟基于哪一版材料。因此必须先确定身份、版本、发布和来源删除语义。

## 3. 决策驱动因素

1. 已发布课程在刷新、重试和 worker 失败后必须保持稳定。
2. 每条课程内容和引用必须能追溯到生成时的精确资料版本。
3. 用户需要逐课节控制生成成本，并在发布前审阅结果。
4. 删除资料时不能留下看似有效、实际已失去来源的引用。
5. 课程与上传资料具有不同所有权，不能因删除一份来源而静默销毁用户课程。
6. 后续 Tutor、练习和进度必须能引用稳定的 Course/Lesson 身份，而不是依赖一份可变生成结果。

## 4. 数据所有权与候选模型

下表定义逻辑合同；最终字段名、索引和约束在 migration 实现前根据现有 ORM 再做机械细化，不改变本 ADR 的语义。

| 实体 | 责任 | 关键约束 |
|---|---|---|
| `courses` | workspace 内稳定课程身份 | 含 `workspace_id`、展示元数据、`current_active_version_id`、生命周期状态和软删除时间 |
| `course_versions` | 一次不可原地改写的大纲快照 | 属于一个 Course；状态为 `draft/active/archived`；同一 Course 最多一个 active |
| `course_version_sources` | Course Version 的精确来源快照 | 唯一键覆盖 `course_version_id + document_version_id`；同时保留 document 身份用于影响分析 |
| `course_sections` | Course Version 内有序章节 | 标题、目标和位置只属于该版本 |
| `course_section_citations` | 章节级证据 | 引用 Stage 2 的 document version/chunk 定位 |
| `lessons` | 某 Course Version/Section 内稳定课节身份 | 保存标题、目标、位置与 `current_published_version_id` |
| `lesson_versions` | 不可原地改写的课节内容 | 状态为 `draft/published/superseded`；结构化内容由服务端校验后持久化 |
| `lesson_citations` | 课节内容块到资料证据的映射 | 必须属于该 Course Version 的 source snapshot |
| `course_generation_jobs` | 大纲或单课节异步生成事实 | 独立状态、attempt、租约、取消和错误合同；不以 Redis 状态代替 |
| `course_generation_job_sources` | 大纲 job 创建时的来源快照 | 在 Course Version 尚未产生前保存精确 document versions；成功提交后原样形成 `course_version_sources` |

所有课程表都必须能通过外键链回 `workspace_id`，所有查询仍显式带 workspace 条件；不能仅依赖难以审计的间接关系完成隔离。

## 5. 身份、版本与发布语义

### 5.1 Course 与 Course Version

- Course 保存稳定 URL、标题、目标、受众和生命周期，不保存可变大纲正文。
- 每次成功的大纲生成创建一个新的 Course Version；失败、取消和无效 artifact 不创建半成品版本。
- Course Version 一经生成，不在原记录上修改章节顺序、课节目标或来源集合。
- 重新生成大纲产生新的 draft Course Version，旧 active version 保持不变。
- 激活采用事务和并发条件更新：新版本变为 active、旧版本变为 archived、Course 指针切换必须原子完成。
- 激活前至少有一个 Lesson Version 已发布，且全部来源和引用仍有效。

### 5.2 Lesson 与 Lesson Version

- Lesson 是大纲中的课节槽位，仅属于一个 Course Version，不能跨 Course Version 复用其身份。
- 每次成功的课节生成创建新的 draft Lesson Version，不覆盖旧草稿或已发布版本。
- 发布采用原子条件更新：目标 draft 变为 published，之前 published 变为 superseded，Lesson 指针同步切换。
- 课节发布后仍允许生成新草稿，但只有再次显式发布才改变 Reader 内容。
- Course Version 激活后仍可逐课节生成和发布；Course 的结构和来源快照不因此改变。

### 5.3 Course Reader

- Reader 默认只读取 Course 当前 active version。
- 对每个 Lesson，只读取 `current_published_version_id`；草稿不得混入正式阅读结果。
- 尚未发布的课节保留大纲槽位并显示状态，不伪造空正文。
- 历史 Course Version 和 Lesson Version 可通过管理 API 审阅，但不作为默认 Reader 内容。

## 6. 来源快照与有效性

### 6.1 建立快照

创建大纲 job 时，API 在同一事务中把用户选择的 document 身份解析为当时的 active/current/ready version，并写入 `course_generation_job_sources`。执行前 worker 再校验这些精确版本，不能重新解析为“最新版本”。大纲成功提交时，同一组记录原样形成 `course_version_sources`，不得在提交阶段重新选择版本。

每次重新生成大纲都建立新的快照。单课节生成继承所属 Course Version 的快照，不能临时增减来源；需要更换来源时必须生成新的 Course Version。

### 6.2 来源状态变化

以下任一情况使快照过期或课程降级：

- document 被软删除；
- snapshot version 不再是 active/current/ready；
- snapshot version 或其可引用 chunk 不再可读；
- workspace 所有权校验失败。

排队或运行中的 job 以 `source_snapshot_stale` 失败，不自动切换版本。已存在 Course Version 保留，但计算并公开 `source_degraded` 状态。

### 6.3 删除与影响提示

- 删除资料前，API 返回或计算受影响 Course 数量，Web 必须明确提示。
- 用户确认删除资料后，资料按 Stage 2 合同删除；课程不会被级联删除。
- 受影响的已发布内容仍可读，因为它是独立课程成果；引用入口显示“来源已不可用”，不得返回原文或假链接。
- 降级期间禁止新生成、发布和激活，以免把不可验证内容继续提升为正式内容。
- 恢复路径是基于有效资料创建新的 Course Version；不得修改旧版本的 source snapshot。
- 删除 Course 只影响课程及其派生内容，不删除任何来源资料。

## 7. 一致性与并发

- 创建 Course 与首个 generation job 使用同一数据库事务和 `Idempotency-Key`。
- artifact 校验、版本写入、citation 写入与 job 成功提交必须处于同一事务。
- job attempt 使用唯一约束或条件写入，重复投递不能创建重复 Course/Lesson Version。
- 激活和发布带期望版本或当前指针条件；并发冲突返回 409，不采用最后写入者静默获胜。
- worker 丢失租约后不得提交 artifact；Redis 丢失时由 Postgres job 状态和 reconciler 恢复。
- Course 软删除后立即从默认列表和 Reader 隐藏，排队 job 请求取消；迟到结果不得复活课程。

## 8. 引用合同

- 章节和课节引用只接受服务端检索阶段签发的临时 evidence ID。
- 持久化时由服务端将 evidence ID 解析为 Stage 2 的 document/version/chunk/位置元数据；模型不能自行提交可信主键。
- citation 必须属于当前 workspace 和 Course Version source snapshot。
- 发布和激活时重新校验 citation 可用性；越界、未知或已删除引用导致操作失败。
- Qdrant 只负责候选召回。最终引用有效性、展示和删除判断全部回到 Postgres。

## 9. 备选方案

### 方案 A：Course 保存一份可变大纲 JSON

拒绝。重生成、发布和并发写入会覆盖用户已审阅内容，无法稳定追踪历史来源，也会阻碍后续 Tutor/练习引用。

### 方案 B：Course 永远跟随 document 当前版本

拒绝。资料换版会在没有课程审阅和重新生成的情况下改变证据语义，历史 citation 也可能指向不同内容。

### 方案 C：删除任一来源时级联删除课程

拒绝。课程是用户投入生成成本并审阅后的独立成果；静默级联会造成不可接受的数据丢失。

### 方案 D：来源删除后继续允许生成和发布

拒绝。系统无法再验证证据，继续发布会把已知不完整的来源链包装为正式内容。

### 方案 E：只保留最新草稿，不保存 Lesson Version

拒绝。失败重生成和误发布无法恢复，Reader 内容也会受到草稿写入影响。

## 10. 影响

### 正向影响

- 已发布课程稳定，可追踪生成时的精确资料版本。
- 失败、重试和逐课节生成不会破坏 Reader。
- 删除影响可见，且课程成果与来源资料生命周期明确分离。
- 为 Tutor、练习和学习进度提供稳定身份。

### 成本与限制

- schema、事务和状态机比可变 JSON 更复杂。
- 来源换版后必须显式生成新 Course Version，不能原地“刷新”。
- 课程降级判断需要影响查询和针对删除/换版的回归测试。
- Slice 1 不提供任意富文本编辑，用户主要通过重生成、发布和版本切换控制内容。

## 11. 验证要求

- migration 覆盖外键、唯一性、状态约束和从 Stage 2 最新 migration 升级。
- 测试重复投递、并发激活、并发发布、失败生成、取消、课程删除后的迟到 worker。
- 测试来源换版、删除、非 ready、跨 workspace 和 citation 越界。
- 验证 Reader 刷新后只恢复 active/published 内容，草稿不泄漏。
- 人工验证删除来源前的影响提示、降级显示、不可用 citation 和基于新来源重建版本。

## 12. 人工 Gate

接受本 ADR 表示确认：

1. Course 与资料是不同生命周期的产品资源，删除资料不级联删除课程。
2. Course Version 和 Lesson Version 均不可原地改写，通过显式激活/发布切换正式内容。
3. Course Version 固定精确 document versions，不自动跟随资料当前版本。
4. 来源失效后课程保留但进入 `source_degraded`，已有内容可读、引用不可用，并禁止新生成/发布/激活。
5. 至少一个课节已发布且所有来源有效时，Course Version 才能激活。
