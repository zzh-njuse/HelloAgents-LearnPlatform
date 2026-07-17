# Stage 4 Slice 1 练习与评分事实盘点

状态：事实输入，不是已接受的产品合同

日期：2026-07-16

## 1. 当前产品事实

- Product API/Web 尚无 Exercise、Attempt、Rubric、Feedback 或 Practice Job schema、API 和界面。
- Reader 已能确定当前 Workspace、Course、Course Version、Lesson 和 Lesson Version；新练习可以复用该稳定上下文，不需要重新发明章节身份。
- Course Version 固定精确的 Document Version 来源快照；Lesson Citation 已把正文块映射到该快照内的 Document Chunk。
- Course Architect、Lesson Writer 和 Tutor 已建立 Postgres 权威任务、Redis/RQ 投递、lease、heartbeat、retry、cancel、reconciler、citation ledger、原子提交和最小 AgentRun/AgentToolCall trace 模式。
- 来源被删除或换版时，已有课程内容保留但进入 `source_degraded`；不得静默切换到新来源继续生成。
- Workspace/Course/Tutor 删除已经具备“先隐藏和阻止新写入，再异步清理事实与 trace”的权威顺序。
- Stage 3 离线 eval 已覆盖 schema、citation、scope、拒答、取消、预算和语言一致性，可扩展为练习硬门禁。

## 2. `academic_companion` 练习原型

### 2.1 `CSAssessor`

`academic_companion/agents/assessor.py` 提供：

- 根据 prototype chapter 元数据和 session summary 生成 3 道开放简答题；
- 保存题目、参考答案、用户答案和 0-100 分；
- 把全部问答和参考答案发送给 LLM，返回总分、薄弱点和评语；
- LLM 失败时生成标题型 fallback 题，评分失败时返回固定 50 分。

可参考的概念只有“题目生成”和“作答评估”应分开。以下行为禁止继承：

- 没有 Workspace、Course/Lesson Version、来源快照或 citation ledger；
- dataclass 只存在于进程内，没有 Postgres、版本、幂等、删除或历史；
- 直接解析未验证的 LLM JSON；
- 评分失败仍返回看似有效的固定分数；
- generic rubric 没有成为版本化事实；
- prompt、答案和 provider 错误可能直接进入输出或终端；
- fallback 题没有可靠证据却被当作正式练习。

### 2.2 `AlgorithmAssessor`

该原型从 `data/leetcode` 随机选择题目，跳转外部 LeetCode，再根据用户自报是否通过计算百分比。它可作为公开 eval fixture 参考，但不能定义通用学习平台的 Exercise schema、外部链接合同或评分权威。

### 2.3 `LearningSession` 与 `LearningAgent`

- `LearningSession` 是 CLI 状态机，Assessment 结束后直接更新本地 UserModel。
- `LearningAgent` 曾按回答长度生成占位 mastery，并把问答摘要写入本地 Working/Episodic/Semantic Memory。
- `UserModel` 使用 `memory/user_model.json`，以固定加权平均更新掌握度，并按阈值和日期推荐复习。

这些都是 Stage 4 Slice 2 的反例或算法候选，不属于 Slice 1 产品事实。尤其不能在 Slice 1 因一次作答直接写入 mastery、weakness、review queue 或长期 Memory。

## 3. Framework 资产边界

- `hello_agents` 提供 LLM、Agent/Tool、context、memory 和 MCP 抽象，但不拥有 Workspace、Exercise、Attempt、Feedback 或删除语义。
- framework memory 的 SQLite/本地文件/Neo4j 适配器不是正式 self-host 产品事实来源。
- Slice 1 可以通过 `academic_companion` 增加纯 artifact、prompt builder 和 validator，但所有 HTTP、Postgres、队列、权限和生命周期仍属于 `apps`。
- 不直接复用 `hello_agents.rag.pipeline` 或 prototype `RAGRetrievalTool`；练习证据必须经过 Stage 2/3 产品 retrieval 与 Postgres 回读。

## 4. 对 Slice 1 的约束结论

1. 第一条路径应绑定 Reader 中的当前激活 Course Version 与当前发布 Lesson Version，先做 lesson scope，不提前做 course-wide practice。
2. 每次生成形成独立、不可原地改写的 Practice Set；重新生成创建新集合，历史 Attempt 继续指向原集合。
3. 第一版只覆盖单选题和受控简答题，避免多选、代码执行、数学工具和外部判题提前进入 MCP 范围。
4. 单选题由服务端确定性评分；简答题使用版本化 rubric 和受控 LLM 评估，并明确标注“AI 反馈”。
5. 正确答案、参考答案和 rubric 在提交前不能通过普通读取 API 泄露。
6. 用户答案是敏感产品事实：允许保存历史和删除，不进入日志、运行摘要、原始 prompt 归档或 eval artifact。
7. 生成或评分失败不得产生 fallback 题、固定分数、伪成功 Feedback 或掌握度写入。
8. Slice 1 只记录 Exercise/Attempt/Feedback，不建立 Learning Event、Mastery、Review Item 或 Memory；Slice 2 再从可信历史形成这些事实。

## 5. 需要 Spec/ADR 决定

- Practice Set 的用户路径、数量、题型、难度、语言和重新生成行为；
- 单选确定性评分与简答 AI 反馈的呈现方式；
- 练习集合、题目、引用、作答、反馈和 Job 的 Postgres 权威与版本语义；
- 生成/评分的队列、预算、幂等、取消、晚到结果和 trace；
- 外部 provider 对课程片段及用户答案的披露和确认；
- 删除 Practice Set、单次 Attempt、Course 和 Workspace 时的清理顺序；
- 固定离线 eval、真实 provider 观察和 Chrome 人工验收范围。
