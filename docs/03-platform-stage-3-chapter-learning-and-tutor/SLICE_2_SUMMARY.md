# Stage 3 Slice 2 总结

状态：已完成；自动化验证、白名单隔离 OCR、OCR 修复复验和人工 Chrome smoke 均已通过。

日期：2026-07-15

## 实际完成

- Workspace 删除：影响摘要、精确名称确认、立即隐藏/拒绝写入、任务取消、Qdrant/存储/Postgres 异步清理、失败重试和 Web 状态反馈。
- Tutor Session：固定 Workspace、Course 和 Course Version，并记录 provider/model 与外部处理确认。
- Tutor Turn：lesson/course scope、已发布 Lesson Version 校验、Session 内幂等、单 active turn、取消、重试和旧版本拒绝新 Turn。
- 受控 Tutor：最多 5 step、3 次检索、8,000 evidence tokens、2,000 output tokens；正常两次 provider 调用，最多一次结构修复。
- 上下文：最多最近 8 个成功 Turn/6,000 estimated tokens；history 仅用于对话连续性，不作为当前事实证据。
- 证据：只检索 Session Course Version 的来源快照；Qdrant 候选必须经 Postgres 精确回读；事实 block 必须引用当前 Turn evidence ledger。
- 运行时：Postgres 权威状态、Redis/RQ 队列、lease/heartbeat/reconciliation、SSE 安全事件和 GET Turn 最终事实回退。
- 删除：Session 立即进入 deleting，取消 active Turn，异步删除正文、citation 和 Tutor run/tool trace；Workspace 删除级联覆盖 Tutor。
- 2026-07-15 人工 smoke 修正：生成状态明确显示课程大纲或具体课节与尝试次数；Reader/Tutor 引用改用顺序编号和“文件名 > 章节路径 > 页码”；Tutor 历史按当前 `lesson_version_id` 与 course scope 分开展示。
- PDF 页码来自新解析 chunk 的可空页跨度；迁移前资料不会猜测页码，需重新上传/处理后才会补齐。
- Course 对比：左侧始终可新建独立 Course；同一 Course 的动作明确为“生成新大纲版本”，不再要求删除旧课程。
- 完整课节：Lesson Writer 改为 coverage plan、最多 8 个单元检索/分段撰写、coverage verify/受控补写和原子提交；独立默认护栏为 48k evidence、32k 累计输出、12 次 provider 调用和 20 分钟。
- Lesson Version：已有草稿仍可重新生成，保留并切换历史草稿/已发布版本，发布明确作用于当前选中版本；同一课节只允许一个 active generation job。
- 长文体验：草稿和 Reader 均提供接近全 viewport 的专注内容页、稳定返回/Escape；Reader 支持上一课/下一课，Tutor 状态不因进入专注阅读而改写。
- Reader Web：Session 创建/恢复/切换、lesson/course scope、连续提问、SSE 更新、引用、取消、重试和删除。
- 未引入长期 Memory、Skill、MCP、练习系统或自主多 Agent。

## 验证结果

- API focused：`python -m pytest -q apps/api/tests`，59 passed。
- Web：`npm.cmd run lint` 通过；TypeScript `--noEmit` 通过。
- Web production build：Docker 内 `npm run build` 通过。
- Compose：API、worker、reconciler、Web、Postgres、Redis 和 Qdrant 正常运行；API healthy，`/ready` 为 ready。
- Migration：此前临时真实 Postgres 数据库完成全量 upgrade 和 `0013 -> 0012 -> 0013`；当前 Compose 已升级到 `0015 (head)`。
- Workspace 删除 smoke：真实 API 创建临时 Workspace 后异步删除成功，最终不再出现在列表。
- Tutor focused/eval：Session/Turn 幂等、scope 隔离、取消/重试/删除、引用提交、未引用事实拒绝和 prompt-injection 输入边界均有测试。
- `git diff --check` 通过。

## Review 结论

- OCR 仅扫描用户批准的普通源码。后端通过一次性白名单隔离副本提供跨文件上下文，明确排除 key、`.env`、私有地址、内部域名、上传原文、敏感 prompt、日志、绝对路径、provider 配置和原始 Compose。
- OCR 高置信项已修复：Web 异步状态/交互问题；`0013` downgrade；Tutor retry/cancel 并发与 trace 状态；reconciler 重复入队；Workspace 删除 queue failure、retry lifecycle 和长任务 heartbeat。
- 一次早期 routers 扫描证明 `--path` 不能阻止 OCR 自主读取仓库其他文件；发现后停止直接扫描并切换隔离副本，详细经过已写入 review 记录。
- OCR 关于 React 18 卸载后 setState、Tutor 初始 mount 必崩、必需响应字段可能缺失和中文产品不应使用中文错误提示等结论被判为误报或 Low，未盲改。
- 详细记录见 [Slice 2 OCR 与本地审查记录](reviews/2026-07-15-slice-2-ocr-and-local-review.md)。

## 人工验收结论

- 2026-07-15 人工 Chrome smoke 接受 Slice 2：Workspace/Course 操作、课节生成与任务队列、草稿版本/发布、Reader 专注阅读、引用、Tutor scope/history 和主要布局可用。
- 人工 smoke 发现并修复：任务身份与多任务可见性、课节结构修复、取消收敛、独立 Course、完整长课节、引用可读位置、语言选择、长文专注页和常规页紧凑预览。
- 新解析 PDF 的引用可显示页码；迁移前旧 chunk 没有页跨度，不猜测页码。旧资料需要重新上传/解析才获得页码，这是已接受的兼容边界。
- Edge 的部分布局表现被确认含浏览器因素；当前人工验收以 Chrome 为基准，跨浏览器扩展不冒充已完成。

## 下一阶段输入

- 下一步从 [Slice 3 输入](SLICE_3_INPUTS.md)开始分析并另行通过 Spec/ADR Gate；不得从本 Slice 自动扩大到长期 Memory、Skill、MCP、练习或自主多 Agent。
