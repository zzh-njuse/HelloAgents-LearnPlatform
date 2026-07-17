# Stage 4 Slice 1 完成总结

状态：完成；2026-07-17 人工接受

## 实际交付

- Reader 内按已发布 Lesson Version 生成独立 Practice Set，支持题数、难度和中英文。
- 单选题由服务端确定性评分；简答题由固定 rubric/evidence 约束的独立 practice worker 异步评分。
- Practice Set、Item、Citation、Attempt、Feedback 和 Job 由 Postgres 持有权威事实。
- 生成与评分具备幂等、预算、step/token trace、独立队列、claim/lease、取消、重试、reconciler 和晚到结果权威重检。
- 提交前使用显式白名单投影隐藏正确答案、rationale、reference answer、rubric 和 evidence 正文。
- Web 支持整份交卷、未答题确认、一次外部评分确认、练习集切换、历史反馈、引用、答案遮挡和新建多套练习。
- `source_degraded` 历史集合保持可读但完全只读；健康来源仍可生成新集合。
- Set、Attempt、Course 和 Workspace 删除图进入自动化覆盖；Attempt 删除保留 API，不提供 Slice 1 专用 Web 按钮。

## Review 与验证

- GLM 主实现后完成三轮 Codex 修正任务包与独立复核。
- 五块脱敏 full-file OCR 已完成，结论见 `reviews/2026-07-16-slice-1-ocr.md`。
- API 全量：138 passed（OCR 收尾基线）；后续 UX/保守评分 focused：36 passed，评分领域：12 passed。
- Stage 4 offline eval：27/27 hard gates passed，2 个 observational case。
- Web lint、Docker production build、Compose migration/ready/Web 200 和独立 practice-worker smoke 通过。
- 2026-07-17 Chrome 人工主路径验收通过；交互中发现的问题已完成修正。

## 人工验收后的产品调整

- 练习改为最后一题统一交卷，未答题按 1 起始页面题号提示。
- 简答题外部处理确认合并为交卷时一次确认；生成确认改为通俗的外部 AI 描述。
- 简答评分采用诊断性保守标准；100 分要求全部 rubric 完全满足且答案全面、准确、无实质遗漏。
- 已提交题目默认不重复提交；可一键遮挡或显示整套答案与反馈以便自测。
- 已有集合时提供明确“新建练习”入口；练习记录下拉框直接显示实际集合。
- 课程生成任务区域只显示运行中任务和极少量最近记录，避免挤占课程内容。

## 延后项与风险

- 删除 Course、Practice Set、Attempt 和 Workspace 的人工破坏性 smoke 统一延后到 Stage 4 最终 Gate，避免每个 Slice 重建真实测试资料；自动化删除测试不得移除。
- Attempt 删除没有 Web 按钮是接受的 Slice 1 产品取舍，后续归档不得把按钮缺失写成回归。
- 简答评分质量仍需在后续 Slice 使用更多真实题型做 observational eval；不得将单次 AI 分数直接升级为掌握度或长期 Memory。
- 当前产品没有认证或 membership；Slice 2 不得把 workspace ID 误当成已认证用户身份。

## Slice 2 可依赖事实

- 每个 Attempt 固定到不可变 Practice Item、Lesson Version、Course Version 和来源快照。
- Feedback 的 verdict、score、rubric criterion result、AI 标记和引用可作为候选学习事件输入。
- 单选 0/100 与简答 AI score 的可信度不同，Slice 2 必须区分信号类型和证据强度。
- Attempt/Feedback 可删除且来源可能 degraded；掌握度、复习项和 Memory 必须支持撤回、重算和解释。
