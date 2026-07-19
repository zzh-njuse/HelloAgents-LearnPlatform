# Stage 4 Slice 3 完成总结

状态：完成，2026-07-19 人工接受

## 实际交付

- 将“证据引导的诊断式支架”固化为产品拥有、白名单控制且版本化的教学 Skill；当前发布版本为 v2，v1 保留用于历史 Turn 展示与重试。
- 每个新 Tutor Turn 固化 Skill ID、版本和完整文件 hash。客户端不能选择、伪造或覆盖 Skill；文件缺失、元数据不匹配或加载失败时显式失败，不静默降级为旧 Tutor。
- Tutor 通过受控 plan、课节范围检索和结构化 answer 两阶段执行，根据问题意图综合课程证据、授权的 active Memory 与 Lesson Completion，而不是逐条复述学习记录。
- 区分课程事实、学习诊断、下一步行动、自检问题和诚实降级；课程事实必须引用当前范围证据，学习诊断必须标注确定性且不得用课程引用冒充学习状态依据。
- Lesson scope 只检索当前已发布 Lesson Version 的引用片段；短期对话历史按 Session、course/lesson scope 和 Lesson Version 隔离。
- 保留受控 step、检索、token、AgentRun、ToolCall、claim/lease/heartbeat、取消、重试和最终权威重检，晚到结果不能提交。
- Tutor UI 显示当前教学方法及历史 Turn 的 Skill 版本，显示本次实际使用的 Memory/Completion 数量，并支持删除单条终态问答。删除后的问题、回答、引用与 trace 不再进入后续短期历史。
- 修复 Stage 3 eval 对新结构化回答的兼容方式，并增加配对候选与教学质量回归覆盖；没有增加针对 smoke 问句或固定答案的硬编码路径。

## 验证与评审

- GLM 完成主体实现及三轮修正任务包；Codex 对合同、权威边界、worker、API、eval 和 Web 进行了独立复核与后续可靠性修正。
- API 全量套件：`241 passed, 6 skipped`；其中容器 test target 未复制仓库根配置导致的 3 个环境性失败，在挂载完整仓库后均通过。OCR 最后一轮补丁回归：`3 passed`。
- Web lint 与生产构建通过；API、worker、Web 镜像重建成功。
- Compose 重启后 `/ready` 全部正常，Web 返回 HTTP 200。
- Chrome 人工 smoke 覆盖普通知识问答、学习诊断、跨 Turn 追问、Memory 实际使用、引用、失败重试和单 Turn 删除后的历史隔离。
- 脱敏 full-file OCR 覆盖 5 个风险分块、26 个普通源码文件，共产生 107 条意见；高置信问题已修复，其余误报、越界项及暂缓理由见 `reviews/2026-07-19-slice-3-ocr.md`。

## 已接受边界

- 默认只提供诊断式辅导，不再保留独立“普通问答”模式；诊断式辅导仍必须先直接回应用户的实际问题，不能为了展示教学结构而答非所问。
- Skill 决定“如何教”，不拥有新的事实来源，也不能修改 mastery、Weakness、Memory 或 Lesson Completion 权威事实。
- RAG 继续回答课程资料中有什么；Memory 只提供经授权的学习状态；Skill 负责综合、解释、诊断和学习动作。
- 用户删除一个 Turn 后，该 Turn 不再参与后续短期会话历史。Session ordinal 保持单调，不因删除重新编号。
- 当前仍是单用户 self-host 产品边界；认证、多租户和通用 Skill 市场不属于本 Slice。
- 不进行关键词式“输入映射固定输出”修复。所有行为修正必须落在通用合同、结构化验证、状态机或权威边界上。

## Slice 4 可依赖事实

- 已发布 Course/Lesson Version、引用 ledger、RAG 检索结果及其来源范围。
- Practice、Attempt、Feedback、mastery band、Weakness、Review Item、active Memory 与 Lesson Completion 的既有权威合同。
- 版本化教学 Skill 的 plan/answer、预算、失败、trace 和用户可见投影模式。
- Tutor Session/Turn 的 scope、短期历史、取消、重试、删除和晚到结果防护。
- AgentRun/AgentToolCall 可以作为受控外部工具调用 trace 的参考，但不能直接假设现有 provider 调用等同于 MCP。

## 后续输入

Slice 4 只研究一个具有明确学习价值、且不能由现有内部能力合理替代的 MCP 外部工具闭环。代码执行沙箱、数学工具和日历仍只是候选项；必须先完成事实盘点、风险比较、Spec/ADR 和人工 Gate，再决定是否实现及选择哪一个。

Stage 4 最终 Gate 仍需统一执行此前延后的破坏性删除人工 smoke，覆盖 Course、Practice、Attempt、Memory、Tutor Session/Turn、Workspace 及未来 Slice 4 工具 trace 的删除边界。
