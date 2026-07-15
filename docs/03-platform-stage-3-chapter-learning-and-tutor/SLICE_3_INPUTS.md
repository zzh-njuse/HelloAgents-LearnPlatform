# Stage 3 Slice 3 输入

状态：事实输入；尚未形成 Slice 3 Spec/ADR

日期：2026-07-15

## 已完成且可继承的事实

- Workspace、资料、Course/Course Version、Lesson/Lesson Version、Tutor Session/Turn 和异步 Job 均由 Postgres 持有权威状态。
- 课程来源固定到 ready Document Version；课程正文与 Tutor 回答均通过 chunk citation 回读，不允许模型自由生成引用。
- Course Architect、Lesson Writer 和 Tutor 是由 product orchestrator 控制的有界角色；Redis/RQ 只负责投递，worker lease、取消、重试和 reconciler 已形成公共运行模式。
- Course 支持独立创建、版本化大纲、单课节多草稿、发布/激活、中文/英文生成、任务队列和来源变化保护。
- Lesson Writer 已采用 coverage plan、逐单元检索/写作、结构修复、coverage verify 和原子提交，并有独立调用、输出、证据和时长预算。
- Reader 提供紧凑预览和专注阅读；引用按顺序编号，位置优先显示文件名、章节路径和页码。
- Tutor Session 固定 Course Version；lesson scope 固定 Lesson Version，course scope 与 lesson scope 历史分开；Session 可删除，Turn 可取消/重试。
- Workspace 删除会先阻止新写入，再异步清理资料、课程、Tutor、trace、索引和文件存储。

## 已接受的兼容边界

- 只有新版 PDF 解析产生可靠页跨度；旧 chunk 不猜测页码，需重新上传/解析。
- 当前是单用户 self-host 产品，没有认证、membership 或多租户权限系统。
- Tutor history 是用户可见、可删除的短期上下文，不是长期 Memory。
- Chrome 是本轮人工 UI 验收基准；Edge/其他浏览器的完整兼容矩阵尚未建立。

## Slice 3 范围分析必须回答

1. Stage 3 是否还需要一个以质量 eval、可观测性和跨浏览器/移动端验收为主的收尾 Slice，还是直接结束 Stage 3、进入 Stage 4 Spec。
2. 若继续 Stage 3，Course Architect、Lesson Writer、Tutor 各自使用哪些公开/脱敏 eval 样本和可重复质量指标；哪些指标只观察，哪些成为发布 Gate。
3. 用户是否需要任务/成本明细、失败诊断或 run trace 的产品界面；若需要，公开到何种粒度且如何避免泄漏 prompt、provider 配置和原文。
4. 真实 provider 的覆盖率、引用率、重复率、语言一致性、拒答和预算耗尽如何形成稳定回归，而不是依赖单次人工观感。
5. 是否需要为旧资料提供显式“重新解析”产品流程；不得通过猜测页码或静默改写 Course source snapshot 解决。

## 默认建议与非目标

默认建议是把可能的 Slice 3 限定为 Stage 3 既有 Course/Tutor 能力的 eval、可观测性和交付收尾；先做事实盘点和 Spec/ADR，再决定是否实现。以下能力仍属于 Stage 4 或需要独立路线调整，不因命名为 Slice 3 自动进入：

- 练习、作答、掌握度、错题和复习队列。
- 可查看/纠正/删除的长期 Memory 或学习画像。
- Skill 产品化、MCP、网页搜索和自主多 Agent。
- 认证、多用户 membership、云端 SaaS 权限与计费。

## 开始条件

- 四份产品方向文档的当前状态已同步到 Slice 1/2 完成；后续范围变化继续保持同步。
- 完成 Slice 3 事实盘点，明确它是 Stage 3 收尾还是 Stage 4 前置。
- 非平凡实现先形成 Spec；eval/trace/schema/预算/权限/重新解析等跨模块决策先形成 ADR。
- Spec/ADR 经人工接受后才能开始对应实现。
