# Stage 2 Slice 1 总结与 Slice 2 输入

状态：Slice 1 已完成
日期：2026-07-12

## 1. 已实现范围

- 建立 document、version、parse report、chunk、ingestion job 与 query trace 的 Postgres schema 和 `0002` 至 `0008` migration。
- 实现 PDF、Markdown、TXT 单文件上传、格式与大小校验、原始字节原子落盘、资料列表与详情。
- 实现 Redis/RQ worker、Postgres claim/lease/heartbeat、自动重试、显式重试、过期任务 reconciler 和脱敏错误合同。
- 实现确定性解析与切块、Markdown 标题路径、DashScope 文档/查询 embedding，且 provider 失败时不隐式降级。
- 实现 Qdrant collection 合同、稳定 point ID、workspace filter、Postgres 权威回读和 query trace。
- 实现权威软删除、后台 Qdrant/storage cleanup，以及从 Postgres 重建 Qdrant 的显式维护命令。
- Web 增加资料上传、状态刷新、失败重试、删除确认、检索片段和引用定位。
- Compose 增加 worker、scheduler、reconciler，并提供隔离的 `api-test` profile。

## 2. 合同落实

| Spec 合同 | 实现结果 |
|---|---|
| 上传请求不执行解析/embedding | API 持久化 document/version/job 后 enqueue，返回 202 |
| Postgres 为事实来源 | 正文、状态、归属、版本、job、trace 均在 Postgres |
| Redis 非权威 | enqueue 失败保留 `queue_failed`；reconciler 可恢复孤儿任务 |
| Qdrant 可重建 | payload 仅含定位元数据；维护命令从当前 ready chunk 重建 |
| workspace 隔离 | Qdrant 强制 filter，命中后再次回读 Postgres 验证 |
| 删除立即不可见 | 先提交 `deleted`；列表和检索均按权威状态过滤 |
| 删除与索引并发安全 | worker 最终写入与 delete 对 document 行加锁串行化 |
| 扫描 PDF | 无可用文本或只有零星字符时返回 `ocr_required` |
| 不生成自然语言答案 | `/rag/query` 仅返回片段、分数和 citation |
| embedding 不隐式降级 | 仅接受已配置 DashScope，失败进入明确任务错误/重试 |

## 3. 验证记录

- API focused tests：`docker compose run --rm --build api-test`，34 passed。
- Web lint 与 build：`npm.cmd run lint`、Docker 内 `npm run build` 通过。
- `docker compose config --quiet`：通过。
- 根 framework suite：本切片未修改 `hello_agents/`；本机 `.venv` 仍指向已不存在的 uv Python，因此 `python -m pytest -q` 无法启动。这是已有环境缺口，不将其视为通过，也不把重建 framework 开发环境混入 Slice 1 变更。
- 干净 migration：临时 Postgres 从 `0001` 升级至 `0008` 成功，确认 8 张预期表后删除临时数据库。
- Compose：API、worker、reconciler、Web 与三项基础设施均已构建并启动；`/ready` 全部通过，Web HTTP 200。
- 真实 synthetic E2E：使用仓库合成 Markdown，经真实 DashScope embedding 完成入库、citation 检索、维护命令重建索引、删除及后台 cleanup；删除后资料列表与检索结果均为空。
- 人工 PDF 回归：`pypdf` 提取文本中的 NUL 控制字符会导致 Postgres chunk 写入失败，已修复为规范化时移除不可写入的控制字符与 surrogate；同一 PDF 的隔离解析和切块验证通过，用户主动重试后确认 provider/Qdrant 全链路成功。
- 人工浏览器回归：上传成功后在 `await` 之后读取 React 合成事件的 `currentTarget` 可能已为 `null`，导致表单重置报错；已在异步前保存 form 引用并由用户复验。此类前端事件生命周期问题不会由 API tests、lint 或 OCR 自动覆盖。
- Qdrant compatibility：真实 E2E 发现 client `1.18` 与 server `1.12.5` 不兼容告警，已将 client 收敛为 `>=1.12.0,<1.13.0`，重建后再次 E2E 成功且日志无版本不兼容、错误或 traceback。
- `git diff --check`：通过。
- OCR：用户在本地终端完成核心 API、schema/deployment 与 Web 三块分段扫描；高置信 findings 已修复并通过复验。详见 [OCR 评审记录](reviews/2026-07-12-stage-2-slice-1-ocr-review.md)。

Slice 1 的实现、环境验证与 OCR gate 已收尾。根 framework suite 因既有 `.venv` 环境缺口未重建，该未执行项不影响本切片 API/Web 改动的 focused verification。

## 4. 运维入口

- API/Web/worker/reconciler：`docker compose up --build -d`
- API focused tests：`docker compose run --rm --build api-test`
- 索引重建：`docker compose run --rm api python -m learn_platform_api.maintenance`
- 状态检查：`docker compose ps`、`GET /ready`、Web HTTP 200。

索引重建会先清空目标 collection，再分批重新 embedding 和 upsert。Qdrant 本身不是事实来源，但操作中断会暂时形成不完整索引，因此应在维护窗口运行并在结束后做检索 smoke。

## 5. 暂缓风险

- Slice 1 不实现图片 OCR、Office、网页、Git、批量上传和自然语言回答；它们仍是后续 parser extension 或 Slice 2 的候选能力，并非永久排除。
- 当前仍是单用户 self-host 边界；多用户鉴权与更细权限不在本切片。
- local storage 是首个正式实现；object storage adapter 尚未实现。
- 重建使用当前 embedding provider 重新计算向量，会产生 provider 成本。
- 原文件大小上限不能约束 PDF 解压后的文本、切块数和 embedding 输入量；解析资源预算尚未成为产品合同。它必须在 Slice 2 批量导入设计前通过 Spec/ADR 明确，不能以静默截断作为临时处理。
- 为完成真实 E2E 创建的 `Slice 1 ... E2E` workspace 留在当前单用户数据库中；Stage 1 尚无 workspace 删除合同，未直接绕过产品 API 清理它们。

## 6. Slice 2 输入

Slice 2 应在新的 Spec/ADR 经人工确认后开始。它以现有 `document`、`version`、`job`、`chunk`、`citation` 合同为基础，不重新定义 Slice 1 已验证的单文件生命周期。

### 6.1 必须继承的实现边界

- Postgres 仍是资料、版本、任务、可见性、引用回读和删除状态的事实来源；Redis 仅负责投递，Qdrant 仍可从 ready chunk 重建。
- 批量操作必须保留逐文件的 `document/version/job` 身份、状态、错误码和重试记录，不能用一个总任务覆盖部分成功、部分失败或用户取消。
- 查询回答必须先取得已授权、可见且当前的检索证据；模型输出不得创造未由 citation 支撑的资料事实。无足够证据时要有明确且可观察的产品行为。
- Slice 2 的带引用回答是单轮生成服务，不是 Tutor Agent；Agent runtime、工具、memory、session 和课程上下文由 Stage 3 单独设计。
- DashScope 仍是默认 embedding provider。provider 不可用时显式失败，不以本地模型静默降级；任何生成或新的 provider 默认值都需单独确认。
- 已有八股/LeetCode 数据只可作为测试、eval 和演示材料，不反向决定产品数据模型。

### 6.2 解析与成本预算 Gate

“25 MiB 原文件”不足以限制 PDF 的解压文本量：一个原文件不大的 PDF 仍可能在解压、文本提取、切块或 embedding 阶段放大为大量 CPU、内存、队列时间和 provider 输入。因此 Slice 2 的批量上传设计前，必须在 Spec 中定义需求，并以 ADR 决定以下可配置预算及其执行位置：

1. 每份资料的页数、规范化文本字符数、chunk 数、预估 embedding token/调用数、解析墙钟时间，以及 worker 并发/内存边界。
2. parser/worker 的增量计数和提前终止方式；超过预算必须产生可诊断的失败或受控取消，**不得静默截断后把不完整资料标记为 ready**。
3. 用户可见的失败类别、重试资格和批量汇总语义，例如页数超限、解析文本超限、解析超时或 embedding 预算耗尽；名称和 HTTP/API 合同由 Spec 决定。
4. 批量级的并发、排队、公平性和成本上限，与单文件预算分开记录；真实 provider 的调用量必须可观测。

这不是把资源保护推迟到 Stage 5：Stage 5 处理部署级容量、告警和成本治理；Slice 2 需要先为产品工作流建立“单份资料不会无界放大”的合同。Slice 1 不追补此行为，以避免未审查地改变已验收的解析语义。

### 6.3 Slice 2 业务设计项

1. 批量上传的逐文件独立状态、限流、部分失败、取消和恢复语义。
2. 带引用回答的证据选择、prompt 边界、引用一致性、无证据行为和可追溯 query trace。
3. 用户可见的 provider 成本、超时、重试与取消反馈。
4. 资料生命周期与回答请求并发时的可见性、删除和幂等边界。

### 6.4 后续 parser extension 的位置

OCR、Office、网页和 Git 导入不是 Slice 1 遗漏项，也不被永久排除。它们应在批量/回答核心合同稳定后，按独立 parser extension 切片评估：输入所有权、隔离运行、资源预算、恶意文件防护、失败诊断与是否需要人工确认，均不得直接复用原型路径绕过产品合同。

### 6.5 测试与人工验收输入

- 扩展 parser fixture 矩阵：正常/空/损坏/加密或扫描 PDF、Markdown/TXT 编码边界，以及 NUL、其他不可写控制字符和 UTF-8 surrogate 等规范化边界。
- 增加预算超限的确定性测试，覆盖“失败而非 ready”、无静默截断、重试资格和批量部分失败。
- 对上传、轮询、失败重试和表单重置等异步 Web 流程，除 API 测试和 lint/build 外，保留真实浏览器 smoke；检查用户可见状态、控制台错误和网络错误路径。
- 在不提交私人资料原文的前提下，人工验收至少使用一份有代表性的真实 PDF；应记录可复现的脱敏特征（来源类别、页数、提取文本量、结果），发现问题后补入自动回归测试或明确记录无法自动化的原因。
- 真实 provider/OCR 的调用继续显式触发，并将命令、范围、成本风险、结果和采纳结论归档到当前 Stage 的 `reviews/`。

不得为了批量或回答功能绕过 Postgres 权威回读，也不得把 fixture 数据反向固化为产品 schema。
