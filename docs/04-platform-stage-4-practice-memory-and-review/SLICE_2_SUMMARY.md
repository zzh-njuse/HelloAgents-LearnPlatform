# Stage 4 Slice 2 完成总结

状态：完成；2026-07-18 人工接受

## 实际交付

- 将已评分 Attempt 投影为可重算的 Learning Event、Mastery Signal、Mastery State、Weakness 与 Review Item；掌握度只展示分档、证据数量和来源，不伪装成精确能力百分比。
- 采用抗单次污染规则：初次负向证据仅形成初步建议，确认薄弱点、解决状态与重新打开均要求独立证据并保留来源。
- 提供今日复习页面、推荐原因、回看课节或历史练习、完成复习、延期、不适用、重新验证与重算入口。
- confirmed Weakness 自动建立可管理的长期学习 Memory；支持编辑、暂停、重新确认、归档、删除和防旧事件复活水位。
- 在正式 Reader 内容末尾增加版本级“学习完毕”事实及撤销操作。课节完成不提高掌握度，也不冒充薄弱点 Memory。
- Tutor 仅在 Workspace 明确开启后，按当前 Course/Lesson 范围选择 active Memory 与课节完成摘要；不外发答案、rubric、feedback、evidence 正文或历史对话。
- Tutor UI 区分“当前范围可选数量”和“该范围最近一次实际使用数量”，避免 Session 中其他课节或课程范围的旧 Turn 造成误导。
- Postgres 保持事实权威；全量重算复用 practice queue 的 claim、lease、heartbeat、retry、cancel 与 reconciler 模式，Redis 只负责投递。

## 验证与评审

- 脱敏 full-file OCR 分四个风险块完成，覆盖 27 个文件；采纳了 suppression watermark、重算 FK、时间归一化、过期请求、轮询停止、空字段防护和 Tutor Memory 注入边界等问题。详情见 `reviews/2026-07-17-slice-2-ocr.md`。
- API 全量、Stage 4 offline eval、Web lint/build、Compose migration/ready/Web 200 均完成复验。
- 2026-07-18 Chrome 人工主路径验证覆盖练习投影、复习动作、Memory 自动建立与管理、课节完成、课节换版、历史练习提示、Tutor 范围筛选和 Memory 实际使用。
- 人工发现的乱码目标、笼统复习项、旧版本导航、Tutor 结构校验、范围计数和页面卡顿等问题已修正或明确收敛行为。

## 已接受的边界

- Memory 是确定性学习事实，不是对话摘要；当前仅自动建立 weakness Memory，课节完成事实独立保存。
- Tutor 使用 Memory 已证明链路可用，但回答质量上下限仍明显受问题表达和教学提示策略影响。Slice 2 只保证正确选择、受控外发和可观测使用，不宣称已形成稳定的个性化教学方法。
- 掌握度公式和阈值维持 Spec 002 / ADR 003 的确定性合同，本轮不因个别人工样例调整。
- Attempt 删除不提供专用 Web 按钮；API 与自动化删除覆盖保留。
- Course、Practice、Attempt、Memory 与 Workspace 的破坏性人工删除 smoke 统一延后到 Stage 4 最终 Gate，避免反复重建真实测试资料。

## Slice 3 可依赖事实

- 当前 Course/Lesson 范围内的已发布内容、引用、练习与反馈。
- 可解释的 mastery band、Weakness、Review Item 和用户管理后的 active Memory。
- 版本级 Lesson Completion；它只能说明用户明确完成过阅读，不能说明已经掌握。
- 每次 Tutor Turn 实际使用的 Memory/Completion 数量及现有预算、trace、失败和引用校验边界。

## 后续输入

Slice 3 应把一种教学方法产品化为可版本化、可选择、可评估的 Skill，并把 Tutor 教学质量优化列为核心目标之一。重点不是为固定问题硬编码答案，而是让 Tutor 根据问题、课程依据、掌握度、薄弱点和学习进度综合形成可执行的解释、诊断与下一步学习建议。
