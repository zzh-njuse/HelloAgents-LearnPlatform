# Stage 3 Slice 2 Tutor 事实盘点

日期：2026-07-15

状态：当前正确仓库事实盘点；作为 Spec 002、ADR 003/004 的输入，不表示方案已经接受。

## 1. 盘点结论

Slice 2 可以复用 Stage 2 的检索、权威回读和引用校验，以及 Slice 1 的课程版本、来源快照和最小 Agent trace，但当前产品尚不存在 Tutor session、消息、turn、流式事件或 Tutor 专用 runtime。

现有 `academic_companion` 学习原型只能作为交互和教学策略参考，不能直接接入产品。它把进程内 session、内置资料 RAG、本地 Memory、UserModel、Skill、Todo 和学习进度副作用绑定在同一个 `LearningAgent` 中，会绕过 workspace、课程版本、来源删除和 Postgres 事实合同。

因此 Slice 2 需要新的产品 Tutor 合同和受控领域 adapter，而不是给 `/rag/answer` 增加 history，或把 prototype chat router 挂到产品 API。

## 2. 当前正确仓库已验证事实

### 2.1 课程与 Reader

- Course、Course Version、Section、Lesson、Lesson Version 和 citation 已由 Postgres 管理。
- Reader 只读取当前激活 Course Version，并展示其中已发布 Lesson Version。
- Course Version 固定来源 document version 快照；来源换版或删除后课程会降级，不静默改绑。
- Lesson citation 可以回读 document、version、chunk、heading 和字符偏移。

这使 Tutor 能绑定不可变 Course Version，并为每个 turn 固定 Lesson Version；它不应只绑定可变化的 `course.current_active_version_id` 或 `lesson.current_published_version_id`。

### 2.2 RAG 与单轮回答

- `/rag/query` 和 `/rag/answer` 已提供 workspace 过滤、Qdrant 候选召回、Postgres 权威回读、相关性门禁和资料不足拒答。
- `/rag/answer` 是单请求服务：不保存问题/回答正文，只保存 hash、citation ID、token、延迟和状态 trace。
- 当前 retrieval 可按 document ID 过滤，但 Tutor 必须新增精确 document version scope，不能只依赖当前 active version。
- 当前单轮回答的结构化 claim/citation 校验和一次修复模式可以复用为设计证据，但它没有 Agent 工具循环、session、取消或流式恢复合同。

### 2.3 Slice 1 Agent runtime

- Course Architect 和 Lesson Writer 使用产品绑定的证据工具、结构化提交、step/search 预算和 Postgres artifact。
- `agent_runs` 当前强制关联 `course_generation_job_id`；Tutor 若复用统一 trace，需要 migration 将 run owner 泛化为互斥的 course job 或 Tutor turn。
- `agent_tool_calls` 只保存 hash、数量、状态、延迟和错误码，不保存原始 query 或 evidence。
- Redis 是非权威投递层；Postgres job/turn 状态必须可恢复。

### 2.4 Product Web/API

- 产品 Web 已有 Workspace、资料、课程和 Reader 体验，但 Reader 目前没有 Tutor 区域。
- Product API 没有 SSE endpoint、Tutor queue、session CRUD 或消息删除合同。
- 当前 Web 的普通 `fetch` helper 只处理完整 JSON；流式读取需要独立、可取消的客户端实现。

## 3. Prototype 可参考与不可采用部分

### 3.1 可参考

- `academic_companion/api/routes_chat.py` 验证过 SSE、心跳和学习模式多轮交互的基本体验。
- `LearningAgent` 的章节上下文、解释、示例和追问风格可作为 Tutor prompt/eval 候选。
- `hello_agents` 提供 async streaming、ToolRegistry、ReAct step 和上下文管理基础能力。

### 3.2 不可直接采用

- prototype session 是进程内字典，重启丢失且没有 workspace 隔离、并发控制或删除语义。
- framework `SessionStore` 把完整 history 写入本地 JSON，并可能包含工具缓存；它不是产品 Postgres session。
- `LearningAgent` 默认接入原型 RAG、Working/Episodic/Semantic Memory、UserModel、Skill 和 TodoWrite，并产生学习进度副作用。
- prototype SSE 会直接转发 framework event，并把异常正文与 traceback 片段发送给客户端；产品不能暴露 thinking、原始工具参数、evidence 或 provider 错误。
- prototype history 与 memory 没有课程版本快照，无法处理激活版本变化和来源降级。

## 4. Slice 2 需要新增的产品能力

1. Postgres Tutor Session、Turn、Turn Citation 与删除生命周期。
2. Session 固定 Course Version；每个 Turn 固定 section/lesson/lesson version 和用户选择的 scope。
3. 新的受控 Tutor adapter，以及产品拥有的 `TutorEvidenceSearch`、结构化回答提交和引用校验。
4. 每个 Turn 的幂等、排队、取消、重试、超时、并发和最终提交合同。
5. 只传递安全事件的 SSE；最终回答和 citation 仍以 Postgres 为准。
6. Reader 内的 Tutor 面板、session 恢复、失败/取消/重试和来源降级提示。
7. 固定 eval 覆盖引用、章节 scope、历史污染、prompt injection、拒答、取消、重连、删除、成本和延迟。

## 5. 明确不是当前事实

- 当前没有多用户身份或授权系统，只有 workspace ID 隔离纪律。
- 当前没有产品长期 Memory、掌握度或复习队列。
- 当前没有已接受的 Tutor step/search/token、session retention 或 streaming 方案。
- 当前没有 Skill、MCP、网页搜索或 Tutor 自主委派权限。
- 当前没有证据证明 prototype 的四步教学法应成为所有课程的硬编码产品合同。

## 6. 对 Spec/ADR 的约束

- session history 是用户可见、可删除的短期对话事实，不得命名为长期 Memory。
- 对话历史只能帮助理解指代和教学连续性，不能替代当前 turn 的资料证据。
- 模型不能提供 workspace、course/source/version filter；scope 由产品请求和数据库关系固定。
- 任何 streaming delta 都是临时传输，不得成为唯一回答事实。
- 课程版本变化、来源降级、断线和重试不得静默改变原 turn 的上下文快照。
- 方案涉及 schema、queue、删除、敏感消息正文和 provider 外发，属于 L3，必须经过 Spec/ADR 人工 Gate。
