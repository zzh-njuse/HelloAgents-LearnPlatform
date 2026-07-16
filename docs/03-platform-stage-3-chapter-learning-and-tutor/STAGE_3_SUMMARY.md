# Platform Stage 3 总结

状态：已完成并于 2026-07-16 通过人工 Gate

## 实际完成

Stage 3 建立了从 ready 学习资料到章节化课程、长课节正文、引用回读和受控 Tutor 的完整学习路径：

- Postgres 持有 Course、Course Version、Section、Lesson、Lesson Version、Tutor Session/Turn、异步 Job 和最小 Agent trace 的权威事实。
- Course 最多选择 20 份 ready 来源并固定到 Document Version，最多生成 15 个 Section；Course Architect 受 6 step / 5 次检索约束。
- Course 支持独立创建多个方案、版本化大纲、激活、删除和来源变化保护，用户可在左侧切换比较不同课程。
- Lesson Writer 采用 coverage plan、分单元检索与写作、结构修复、coverage verify 和原子提交；具备独立调用、输出、证据、时长预算以及任务队列。
- 课节支持中英文、多个草稿版本、发布与重新生成；Reader 与草稿提供紧凑预览和接近全屏的专注阅读。
- 引用按数字编号，优先展示文件名、章节路径和第 N-M 页；旧 PDF chunk 不猜测页码，新解析结果才提供可靠页跨度。
- Tutor 固定 Course Version；lesson scope 固定 Lesson Version。两种 scope 的会话历史隔离，Session 可删除，Turn 可取消和重试。
- Tutor 只从课程来源快照检索，使用 evidence ledger 校验引用；证据不足时明确 limitation，不伪造引用。
- Workspace 删除先阻止新写入，再异步清理资料、课程、Tutor、trace、Qdrant 索引和文件存储。
- Workspace 提供只读“运行记录”，按 Course、角色和状态筛选，展示任务身份、状态、attempt、token、耗时和脱敏阶段摘要。
- 固定离线 eval 覆盖 Course Architect、Lesson Writer、Tutor 和跨角色合同；本地报告严格限制为非敏感白名单字段。

Stage 3 未引入练习、掌握度、复习队列、长期 Memory、Skill、MCP、自主多 Agent、认证或 SaaS 多租户。

## 验证结果

- Slice 1、Slice 2 均完成分块 OCR、修复复验和 Chrome 人工 smoke。
- Slice 3 完成三块隐私隔离 OCR；High 和高置信 Medium 已修复，误报和暂缓项已记录。
- API 全套：`76 passed`。
- 固定离线 eval：`19/19` hard gates passed，3 个 observational case 已记录。
- Web ESLint 和 TypeScript project build 通过。
- Docker API、worker、reconciler、Web production build 通过。
- Compose 启动后 API healthy，`/ready` 返回 ready，Web 和运行摘要 API 返回 HTTP 200。
- 2026-07-16 Chrome 人工 Gate 确认运行记录入口、身份、筛选、详情、刷新、删除后的脱敏行为及 token 未报告语义没有功能性问题。
- `git diff --check` 通过。

详细审查记录见：

- [Slice 1 OCR](reviews/2026-07-14-slice-1-ocr-review.md)
- [Slice 2 OCR 与本地审查](reviews/2026-07-15-slice-2-ocr-and-local-review.md)
- [Slice 3 OCR 与本地审查](reviews/2026-07-16-slice-3-ocr-and-local-review.md)

## 已接受边界与暂缓风险

- 当前是单用户 self-host 产品，没有认证、membership 和多租户授权；workspace id 隔离不等于 SaaS 权限模型。
- Chrome 是当前人工 UI 基线；Edge 的局部显示问题和完整跨浏览器/移动端矩阵尚未建立。
- Tutor history 是可见、可删除的短期 Session context，不是长期 Memory。
- 旧 PDF chunk 没有可靠页码；不猜测页码，也不静默重解析或改写 Course source snapshot。
- token 缺失时显示“未报告”，不按文本或价格估算；金额成本治理留到后续独立范围。
- 运行记录列表最多 50 条，当前可能存在有限 N+1 查询；在形成真实性能证据前不增加复杂分页和聚合。
- Real-provider eval 必须另行确认脱敏样本、provider 和调用预算；它是观察基线，不替代离线 hard gate，也不会被默认命令触发。

## Review 结论

Stage 3 的预设目标已经完成：版本化课程、受控课程生成、章节阅读、可追溯引用、受控 Tutor、删除权威、最小 trace、固定 eval 和脱敏运行摘要均形成可重复交付闭环。现有剩余项不阻塞 Stage 4，也不得借收尾名义提前扩展为长期 Memory、Skill、MCP 或自主多 Agent。

## 下一阶段输入

Stage 4 从用户在 Reader/Tutor 中的真实学习行为出发，定义练习、作答、反馈、掌握度、薄弱点和复习队列的权威事实与可解释闭环。具体输入与待决问题见 [Stage 4 输入](../04-platform-stage-4-practice-memory-and-review/STAGE_4_INPUTS.md)。
