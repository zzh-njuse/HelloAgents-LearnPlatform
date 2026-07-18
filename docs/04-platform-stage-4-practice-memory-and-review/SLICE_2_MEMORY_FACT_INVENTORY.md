# Stage 4 Slice 2 掌握度、复习与 Memory 事实盘点

状态：分析输入；不构成实现批准

日期：2026-07-17

## 当前产品事实

- `apps/api` 尚无 Learning Event、Mastery、Weakness、Review Item 或长期 Memory 产品表。
- Slice 1 的 Practice Attempt 与 Feedback 已由 Postgres 持有，并固定到 Practice Item、Lesson Version、Course Version 和来源快照。
- 单选 Feedback 是服务端确定性结果；简答 Feedback 带 `is_ai_graded`、0-100 score、rubric criterion result 和引用。
- 未答题不会创建 Attempt；查看反馈、跳过页面和 Tutor 对话也不会创建学习事件。
- Lesson Version 已保存 `learning_objectives` JSON，但目标没有独立稳定 ID；Practice Item/rubric 也未映射到目标。
- Practice Set/Attempt/Course/Workspace 删除已有权威路径；新增派生学习事实必须加入同一删除图。
- 当前没有认证用户或 membership；所有学习状态只能先以 Workspace 为隔离边界，不能声称是跨账号用户画像。

## Prototype 能力与限制

### `academic_companion.memory_extensions.UserModel`

可参考：

- topic/chapter mastery、weak points、last reviewed、review count 的概念；
- 简单的弱项排序和复习到期视图。

禁止直接继承：

- `memory/user_model.json` 文件权威；
- topic 使用截断问题文本，没有 Course/Lesson/Version 身份；
- 第一次分数直接成为 mastery，后续固定 `70% 历史 + 30% 本次`；
- 固定 `<70`、`<80` 和 3 天间隔，没有证据强度、纠正、删除或重算；
- weak points/notes 自由字符串，无来源和冲突合同。

### `LearningAgent` / `LearningSession`

可参考：

- episodic event、semantic summary、review schedule 是不同职责；
- 学习状态可以进入后续上下文。

禁止直接继承：

- 按回答长度产生占位 mastery；
- CLI assessor 单次总分直接覆盖 chapter mastery；
- 同一行为同时写 Working/Episodic/Semantic/UserModel，失败被静默吞掉；
- 学习问答全文或答案摘要自动进入长期记忆；
- SQLite/Qdrant/Neo4j 混合作为隐式产品权威。

### `hello_agents.memory`

可参考：

- working、episodic、semantic 的能力分类；
- add/retrieve/update/remove 和 importance/forgetting 的抽象。

禁止直接作为 Slice 2 schema：

- `MemoryItem.content + metadata` 通用袋式结构；
- 本地 SQLite/document store 为正式 self-host 权威；
- Qdrant 记忆 payload 存正文；
- 默认启用 Neo4j 或依赖图数据库；
- 关键词/文本长度 importance 和自动分类决定长期学习事实。

## Slice 1 的合同缺口

Slice 2 若要按知识目标累计证据，必须补充稳定目标映射：

- Lesson Version 的每个 learning objective 需要稳定 `target_key`；
- Practice Item 需要声明覆盖哪些 target；
- 简答 rubric criterion 需要声明对应 target；
- 旧 Practice Item 没有映射，只能迁移到该 Lesson Version 的 `lesson_overall` 合成目标，不能事后用 LLM 猜测。

## 可以确定性复用的信号

| 来源 | 可用信号 | 可信边界 |
|---|---|---|
| 单选 Feedback | correct / incorrect | 确定性，但一次题目可能有歧义或猜测 |
| 简答 criterion | full / partial / none | AI 评估，必须折扣权重并保留 AI 标记 |
| ungradable/failed/canceled | 无 mastery signal | 不得转换为 0 分 |
| 未答题 | 无 mastery signal | 不得推断不会 |
| 查看反馈 | 不创建 Learning Event | 不提高 mastery |
| 标记已复习 | Review Action | 不提高 mastery，等待新 Attempt 验证 |
| skip/snooze | Review Action | 不改变 mastery |
| Tutor Turn | Slice 2 排除 | 短期对话不是稳定学习证据 |

## 结论

Slice 2 应由确定性投影服务完成，不需要新的 LLM Agent。Postgres 保存事件、信号、投影、复习项和由 confirmed Weakness 自动建立、用户可管理的 Memory；Qdrant、Neo4j、本地 JSON 和模型自由摘要均不进入第一版权威路径。
