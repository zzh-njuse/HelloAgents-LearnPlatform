# 2026-07-15 Slice 2 OCR 与本地审查记录

## 范围与隐私边界

用户最终确认：主动排除 API key、`.env`、私有连接地址、内部域名、上传原文、敏感 prompt、日志、绝对路径和 provider 配置；普通 API 实现、schema、migration、worker、测试和脱敏部署配置允许 OCR。

公开 OCR 范围：

- `apps/web/src/app/App.tsx`
- `apps/web/src/app/CoursePanel.tsx`
- `apps/web/src/app/TutorPanel.tsx`
- `apps/web/src/styles.css`
- `apps/web/src/lib/api.ts`
- ORM models、API schemas、routers、`0012`/`0013` migrations。
- Tutor service、Workspace 删除 service、jobs/reconciler。
- Course/Tutor/Workspace 删除 workers 与 queue。
- Course/Tutor/Workspace API tests。

后端 OCR 使用一次性白名单隔离副本。副本完整提供允许源码作为跨文件上下文，但不包含 `.git`、`settings.py`、`.env`、原始 `docker-compose.yml`、generation/provider 配置、上传原文处理、敏感 prompt 或日志文件。副本不进入仓库和 Git。

早期一次直接扫描 routers 目录时，OCR 自主 `file_read settings.py`，证明 `--path` 不能作为隐私隔离边界。发现后立即停止直接仓库扫描、检查并终止残留进程，后续全部改用白名单隔离副本。该次越界读取未被隐瞒。

## 命令策略

- 每块先运行 `ocr scan --preview --path ...`。
- 真实扫描使用 `--audience human --concurrency 1 --timeout 10`。
- 大块按 models、schemas、migration、routers、Tutor、删除、jobs、workers、tests 风险边界拆分；worker 聚合块超时后保持 10 分钟上限并缩小为两个功能块。
- provider 连接测试通过；记录不保存 provider 配置或凭据。

## OCR Findings 处理

采纳并修复：

- `App.tsx`：Workspace 切换期间上传、批次、重试等异步结果可能污染新 Workspace。
- `CoursePanel.tsx`：打开课程缺少错误反馈；生成命令未设置 busy；切换课程残留旧 sources/job。
- `TutorPanel.tsx`：Session 删除失败缺少反馈；异步结果改为服务端重新读取；SSE 使用稳定 Turn id/status。
- `styles.css`：Tutor panel 在短视口可能裁切；缺少部分 focus-visible；移动端隐藏 Workspace 导航且无替代；`100vh` 动态视口问题。
- `api.ts`：Slice 2 Workspace 删除和 Tutor Turn 在网络失败后需要复用稳定 Idempotency-Key。
- OCR 后的本地检查发现根 `lib/` ignore 规则误伤 `apps/web/src/lib/api.ts`，已改为 `/lib/`，使浏览器 API 客户端正式进入版本控制。

未采纳：

- “`session?.turns[...]` 初始 mount 必然崩溃”：可选链会短路该成员访问，且 TypeScript/生产构建通过。
- API 合同中必需的 `citations`/`citation_ids` 可能任意缺失：客户端类型和服务端 response model 已规定该合同。
- React 18 下所有异步 handler 都必须增加 mounted ref/AbortController：作为 Low 改进，不是本 Slice 的已证实故障；已有 Workspace 身份 guard 和 effect cleanup。
- 中文 fallback error 应改英文：当前产品界面语言为中文，不构成安全或功能缺陷。
- `request()` 缺少泛型导致 `Promise<unknown>`：TypeScript 根据函数返回类型完成推断，`tsc --noEmit` 通过。
- magic number 抽常量：Low，不影响合同或行为。

## 后端 OCR 与本地合同审查

重点检查并修复：

- Workspace 删除与 Tutor 最终提交使用 Workspace 权威状态，避免删除后继续写入。
- Session/Course Version 和 Turn/Lesson Version 的 workspace/course/version 关系。
- 同一 Session 单 active Turn、完整请求幂等比较、重试后 queue failure 状态。
- Tutor 5 step/3 search、evidence/output/history 上限、一次 repair 和 citation ledger。
- provider/cancel/lease 边界不提交部分正式回答。
- SSE 白名单、heartbeat、无 prompt/evidence/provider raw error 泄漏。
- Session deleting 的清理重投递、AgentToolCall/AgentRun/TurnCitation 删除顺序。
- Workspace 删除对 Tutor Session/Turn/trace 的级联和 Qdrant/存储/DB 顺序。
- reconciler 只投递一次各类任务，修复原有 course job 仅在存在 deletion job 时才重投递的问题。
- `0013` downgrade 在存在 Tutor AgentRun 时先删除 Tutor tool/run trace，再恢复 legacy 非空 owner 约束，避免 rollback 失败。
- Tutor lesson scope 拒绝空白 ID；cancel 使用行锁；retry 在 Session 内再次执行单 active turn guard。
- Course/Tutor/Workspace deletion reconciler 刷新 `updated_at`；Tutor Session cleanup 使用 `FOR UPDATE SKIP LOCKED`，避免重复投递。
- Workspace 删除初次/重试 enqueue 失败明确落为 `queue_failed`；retry 再校验 Workspace 仍处于 `deleting`。
- Workspace 删除 worker 增加持续 heartbeat/lease 续期，降低长清理期间重复执行风险。
- Tutor 取消的 AgentRun 正确记录为 canceled；unexpected failure 也保留 AgentRun trace。

未采纳或暂缓：

- WorkspaceDeletionJob 不设 Workspace FK：删除 job 是 Workspace 主记录删除后的权威回执，不能随 Workspace 一起级联删除。
- ORM 非空字段无 server default：当前 ORM/服务显式赋值且 migration/测试通过，不把 raw SQL 写入扩展为本 Slice 合同。
- 缺认证/多租户 membership：当前 accepted self-host Slice 未引入身份系统；workspace ID 隔离仍由服务查询约束，认证属于后续独立 Spec/ADR。
- response model、router import、软删除索引、统一 enum/timestamp、N+1、测试拆分等 Low/设计建议，不在本次高置信修复中盲改。
- Course worker/queue 的部分结论属于既有 Slice 1 路径或依赖未纳入 OCR 的 generation/provider 上下文；仅记录，不扩大 Slice 2。

## 复验

- API focused：15 passed；API 全套：55 passed。
- Web lint：通过。
- TypeScript：通过。
- Docker Web production build：通过。
- API、worker、reconciler 镜像重建：通过。
- Compose：服务运行，API healthy；`/ready` 返回 ready。
- Alembic：在临时真实 Postgres 数据库完成全量 upgrade、`0013 -> 0012 -> 0013`，最终 `0013 (head)`；未破坏现有开发数据。
- `git diff --check`：通过。

## 剩余 Gate

本节记录 OCR 当时的剩余 Gate：当时人工 Chrome smoke 尚未执行，Codex 应用内浏览器也因本地运行时错误不可用，因此没有冒充 UI smoke 通过。

## OCR 后收尾

- 后续人工 Chrome smoke 已于 2026-07-15 接受 Slice 2。
- 人工发现的任务身份、任务队列、课节结构失败、取消收敛、课程对比、长课节质量、引用位置、输出语言和长文阅读问题已修复；这些后续改动由 Codex self-review、回归测试和人工 smoke 覆盖，没有冒充为上述 OCR 扫描范围。
- 最终 API 全套为 59 passed；Web lint、TypeScript、Docker production build、Compose readiness、`0015 (head)` 和 `git diff --check` 通过。
- 迁移前旧 PDF chunk 不猜测页码；新解析资料产生可靠页跨度。该兼容边界已由人工接受并进入 Slice 3 输入。
