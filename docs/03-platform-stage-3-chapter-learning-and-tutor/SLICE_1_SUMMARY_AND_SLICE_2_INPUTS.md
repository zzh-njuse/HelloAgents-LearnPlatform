# Stage 3 Slice 1 总结与 Slice 2 输入

日期：2026-07-14
状态：Slice 1 已完成实现、独立 review、复验与人工验收；Slice 2 尚未进入实现。

## 1. Slice 1 实际完成

- Postgres 建立 Course、Course Version、Section、Lesson、Lesson Version、来源快照、citation、generation job 和最小 Agent run/tool trace 事实模型，并完成 `0010`、`0011` migration。
- Course Architect 遵守 6 step / 5 次检索 / 最多 15 Section；Lesson Writer 遵守 4 step / 3 次检索。两者只通过产品证据工具和 Postgres artifact 交接。
- 完成课程创建、列表、详情、软删除、大纲重生成、逐课节生成、发布、课程版本激活、取消、重试和 queue recovery。
- Course Reader 展示已发布课节、学习目标、正文和可用性明确的引用定位；来源换版或删除不会静默改绑。
- Web 显示置顶任务状态、可折叠版本与课节草稿、引用详情和紧凑响应式布局；Nginx 上传限制与产品 100 MiB 合同对齐。

Slice 1 没有引入 Tutor、聊天 session、长期 memory、Skill、MCP、练习系统或自主多 Agent。

## 2. 验证事实

| 门禁 | 结果 |
|---|---|
| API focused tests | 47 passed |
| Web | ESLint、TypeScript、production build 通过 |
| Migration | 干净升级及 `0011 -> 0010 -> 0011` 通过 |
| Compose | API、worker、reconciler、Web 与依赖服务运行；`/ready` 正常，Web HTTP 200 |
| 独立 review | 分块 OCR 完成；High 与高置信 Medium 已修复并复验 |
| 人工 smoke | 用户确认上传与 Slice 1 课程主路径无功能性问题 |
| 根 pytest | 未完成；全局 Python 缺少 `tiktoken`，collection 阶段停止，不视为通过 |

应用内浏览器插件仍因 `Cannot redefine property: process` 无法用于自动 smoke。人工验收期间发现的 413、任务反馈位置、草稿可见性和布局问题均已修复；后续浏览器人工检查优先使用 Chrome，Edge 表现作为兼容性观察项。

## 3. 保留风险与技术输入

- 当前 self-host 合同只有 workspace ID 隔离，没有多用户认证和授权；Slice 2 不得把它误写成已具备用户权限。
- generation job 的失败 attempt 只保留最小 AgentRun；失败 tool trace 的跨事务持久化仍未设计。
- 课程列表尚未分页，详情读取存在后续规模优化空间；当前受 15 Section 上限约束，不是 Slice 1 阻断项。
- 根 framework 的完整依赖基线仍需恢复后补跑 `python -m pytest -q`。
- 真实 provider smoke 缺少可重复的固定 fixture、成本和结果记录；Slice 2 eval 设计应补齐，而不是依赖聊天或人工印象。

## 4. Slice 2 必须继承的事实

1. Postgres 继续拥有 workspace、课程、版本、课节、citation、job 和 trace 事实；Tutor 不得建立旁路 JSON/session 事实源。
2. Tutor 的证据必须从 Stage 2 权威 citation 回读和 Slice 1 固定课程/课节上下文进入；模型不能自行指定 workspace 或扩大 source snapshot。
3. 已发布 Lesson Version 是 Tutor 当前章节内容的稳定输入。来源降级、citation 不可用和资料不足必须产生明确拒答或降级行为。
4. 产品 orchestrator 继续拥有预算、超时、取消、重试和持久化；`academic_companion` 只提供可复用领域能力，保持 `apps -> academic_companion -> hello_agents`。
5. 现有 `AgentRun`/`ToolCall` 可以扩展，但是否记录消息、失败工具结果和成本明细必须在 ADR 中明确数据边界、敏感信息和保留策略。

## 5. Slice 2 Spec/ADR 待决问题

- Tutor 是单请求问答还是持久 session；刷新恢复、并发请求、取消和重试各自如何定义。
- 当前上下文精确绑定 workspace、course version、section、lesson version 的哪一级，课程版本切换后旧 session 如何处理。
- 短期对话上下文保存什么、保存多久、谁可删除；不得提前引入 Stage 4 长期 memory 或掌握度。
- Tutor 可调用哪些只读工具、每轮 step/search/token 预算、停止条件与无证据拒答合同。
- 回答和 citation 的持久化、敏感 prompt/资料正文隔离、外部 provider 确认和日志脱敏。
- streaming 是否属于 Slice 2 必需体验；若采用，需定义断线、部分输出和最终事实提交。
- 最小 eval corpus 如何覆盖章节约束、引用有效性、prompt injection、来源降级、拒答、取消、成本与延迟。
- Web 入口应位于 Reader 内还是独立 Tutor 视图，并保持课程阅读为主体验，不把聊天框变成无上下文首屏。

## 6. Slice 2 开始门禁

先基于上述输入完成 Tutor 事实盘点和小范围 Spec/ADR，明确 session/memory/trace/tool 权限与失败矩阵，经人工接受后才开始 schema、API、worker 或 Web 实现。Skill、MCP、自主多 Agent、长期 memory 和练习系统继续排除在 Slice 2 默认范围之外，除非另行提出并通过 Gate。
