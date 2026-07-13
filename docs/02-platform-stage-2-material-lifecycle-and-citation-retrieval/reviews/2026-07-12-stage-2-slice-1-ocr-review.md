# Stage 2 Slice 1 OCR 评审记录

状态：已完成，修复与复验完成
日期：2026-07-12

## 评审背景

本次评审覆盖 Stage 2 Slice 1 的单文件上传、权威资料生命周期、Redis/RQ 任务恢复、DashScope embedding、Qdrant 派生索引、workspace 隔离检索、引用、删除和 Compose 部署。

## 预检与范围

- `ocr version`：`open-code-review dev windows/amd64`。
- `ocr scan --preview --path apps/api/learn_platform_api`：识别 28 个文件、约 1595 行代码。
- `ocr llm test`：2026-07-12 恢复网络授权后连接 DeepSeek 成功。
- Codex 执行环境拒绝了真实 scan，因为它不能代为向外部 provider 发送私有源码。
- 用户在本地终端主动运行三块 scan，并将完整输出保存至本目录的 `raw/`。这些输出是本次 gate 的原始归档。

## 实际执行分块

1. 核心生命周期：8 个文件、37 条 comments，原始输出：[core-api-ocr.txt](raw/core-api-ocr.txt)。
2. schema、API、migration、部署和测试：19 个文件、60 条 comments，原始输出：[schema-api-deploy-ocr.txt](raw/schema-api-deploy-ocr.txt)。
3. Web：3 个文件、11 条 comments，原始输出：[web-ocr.txt](raw/web-ocr.txt)。

每块使用 `ocr scan --audience human --concurrency 1 --timeout 5 --path ...`，由用户主动在本地执行；共覆盖 Slice 1 的业务实现、schema/migration、部署合同、测试与 Web。

## 采纳并修复

- 删除与 worker 最终索引之间增加 Postgres 行锁，避免 cleanup 先完成、旧 worker 后写入 Qdrant 的竞态。
- `current_version_id` ORM 外键补齐 `ON DELETE SET NULL`，与 migration 合同一致。
- 移除公开的 job reconcile 写端点，只保留内部 reconciler 服务，缩小无鉴权管理面。
- PDF 仅有零星字符时按 `ocr_required` 处理，并增加回归测试。
- 原子写入使用唯一临时文件，避免并发调用互相覆盖临时路径。
- cleanup 在删除 Qdrant/storage 前确认 worker lease；reconciler 对已恢复任务使用行锁，降低多实例重复 enqueue。
- worker 对每个文档只扫描一次 Markdown 标题，避免按 chunk 重复扫描全文；异常路径改为显式初始化 session/job。
- 索引重建改为流式分批读取 chunk，避免将完整索引正文一次性载入内存；检索改为批量 join 回读，去除每条结果的版本/document N+1 查询。
- 上传在读取 multipart 正文前确认 workspace 存在，降低无效 workspace 请求的内存占用。
- Web 修复 retry 后资料列表刷新、重复轮询、workspace 切换时取消资料请求、citation 稳定 key、侧栏滚动和键盘焦点/减少动态效果。

## 未采纳或暂缓

- collection rebuild 的蓝绿 alias 切换：结论暂缓。现有 ADR 明确这是受控、显式的维护命令，当前 collection 名称是既有直接物理 collection；引入 alias 会改变运行合同，留给后续运维切片。维护文档已明确重建中断会暂时造成索引不完整。
- 以 outbox 替代“Postgres commit 后 enqueue”的 crash window、自动重试 `queue_failed`、多 reconciler 高可用：暂缓。Slice 1 明确 Redis 非权威且 `queue_failed` 采用用户显式重试，单用户 Compose 只运行一个 reconciler；扩展为多实例时应以独立 ADR 引入 outbox/leader 选举。
- Docker 非 root、生产 secret 强制注入、完整多用户 workspace 授权：不在 Slice 1 边界。当前为 localhost 单用户 self-host 开发默认值；多用户鉴权在路线图后续阶段处理。
- “DocumentChunk 缺少 UUID 默认值”“retry 条件更新会让两个调用都成功”“空密码 PDF 必然是乱码”：未采纳。chunk ID 是由 version/ordinal/content hash 派生的稳定 ID；retry 的条件 UPDATE 只允许一个调用实际转换状态；允许空密码解密的 PDF 可正常读取。

## 复验与结论

- `docker compose run --rm --build api-test`：32 passed。
- `npm.cmd run lint` 与 `npm.cmd run build`：通过。
- Compose 重建后 `/ready` 为 ready，Web HTTP 200。
- 使用合成 Markdown 的 DashScope E2E：入库、引用检索、流式重建、删除与 cleanup 全部成功；删除后检索返回 0 条。

结论：OCR gate 已完成。高置信的正确性、并发、性能和可访问性问题已修复；其余项已按 Slice 1 合同记录为暂缓或不采纳，不存在未说明的 High finding。

## 人工 PDF 验证后的补充

人工上传 `icse2027-paper1606.pdf` 时，任务三次失败并显示通用 `ingestion_failed`。本地隔离诊断确认：该 PDF 的 12 页文本层可由 `pypdf` 读取，但解析文本含 7 个 NUL 控制字符；Postgres `TEXT` 不接受 NUL，因此在写入 chunk 时失败。

已修复：规范化解析文本时移除除换行和 Tab 之外的 C0 控制字符及 UTF-8 不可编码的 surrogate，并为 PDF 失败记录稳定错误码、处理阶段和异常类型（不记录正文）。相同防护覆盖 Markdown/TXT，文件名也拒绝数据库不接受的控制字符。上传表单另外修复了异步后访问 React `event.currentTarget` 可能为 `null` 的问题。回归测试为 34 passed；同一 PDF 在不调用 embedding/provider 的隔离解析中得到 72953 个字符、0 个 NUL、110 个 chunk。

受 Codex 执行环境的数据外发策略限制，不能由 Codex 代为再次把该 PDF 文本发送至 DashScope；用户已在 Web 主动点击“重试处理”并确认成功，完成 provider/Qdrant 人工 smoke。该限制不影响本地解析与数据库写入根因的复现和修复。
