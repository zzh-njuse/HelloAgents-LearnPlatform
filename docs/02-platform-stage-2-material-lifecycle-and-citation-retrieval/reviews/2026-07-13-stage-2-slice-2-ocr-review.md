# Stage 2 Slice 2 OCR 评审记录

状态：已完成代码修复与自动化复验

日期：2026-07-13

## 评审结论摘要

本次独立评审完整覆盖 Slice 2 的带引用回答、批量资料生命周期、worker、数据/部署配置与 Web。高置信的幂等、worker 所有权、外部副作用、检索资源释放、错误可观测性和 Web 异步状态问题已修复并通过回归测试。

不将本地单用户 self-host 原型误判为已经具备多用户授权、流式上传或生产容器加固；这些项已作为后续输入记录。用户明确决定不为当前非移动端项目新增移动导航。

## 审查执行与覆盖

真实 OCR 由用户在本地终端顺序执行，输出保存在本目录的 `raw/`。首次带 60K token 上限的尝试发生预算截断，随后以相同文件名、无 token 上限的命令重跑并覆盖原输出。最终覆盖如下：

| 风险边界 | 文件数 | 实际 token | 用时 | 原始输出 |
|---|---:|---:|---:|---|
| 回答/API 合同 | 4/4 | 157,465 | 8分30秒 | [answer-api](raw/slice-2-answer-api-ocr.txt) |
| 批量生命周期 | 5/5 | 328,648 | 13分32秒 | [batch-lifecycle](raw/slice-2-batch-lifecycle-ocr.txt) |
| 解析 worker | 1/1 | 64,836 | 4分23秒 | [worker](raw/slice-2-worker-ocr.txt) |
| 数据模型/迁移/部署 | 5/5 | 147,245 | 9分52秒 | [persistence-deploy](raw/slice-2-persistence-deploy-ocr.txt) |
| Web | 2/2 | 91,602 | 5分19秒 | [web](raw/slice-2-web-ocr.txt) |

总用量约 789,796 token。批量生命周期块超过后来确立的 10 分钟目标；它在该协作规则生效前启动，覆盖有效但不作为后续分块模板。后续 OCR 按 Playbook 的 10 分钟预计时长规则进一步拆分。

## 已采纳并修复

- 批量请求指纹纳入每个文件的 SHA-256，并在 `(workspace_id, idempotency_key)` 唯一约束竞争后回读胜出请求；历史 metadata-only 指纹仅用于兼容已存在的批次。
- worker 在心跳失败时设置租约丢失信号，并在关键副作用前再次确认所有权；按 workspace 锁定 claim 路径以串行化并发上限检查。
- 解析失败时尽力清理尚未提交的 parsed 文件和 Qdrant version points；Qdrant client 在入库、清理和检索路径中显式关闭；PDF 子进程增加 `kill()` 兜底。
- 原文件清理失败不再覆盖初始异常；入队和 reconciler 失败补充结构化日志。
- 回答检索失败会写入失败 trace；失败 trace 写入本身不会覆盖原始 provider 错误；查询和回答路由保留稳定的用户错误响应同时记录异常。
- Web 防止旧 workspace 的检索/回答结果回写，轮询错误会显示，异步操作使用计数而不是共享布尔 busy 状态；补齐关键输入焦点与 disabled 按钮反馈。

## 暂缓与不采纳

### 暂缓到后续 Stage/切片

- 多用户身份认证与 workspace 授权：当前没有身份模型，不能用临时依赖伪造授权边界。
- magic-byte/MIME 安全检测、病毒扫描与流式直写：属于 parser/storage 扩展；当前批量上限是 100 MiB，不是 OCR 所称的 500 MiB。
- 分页、N+1 优化、额外数据库 CHECK/index、容器 restart/healthcheck/non-root、生产 secret 强制注入：不阻塞 Slice 2 合同，留给运维与规模化切片。
- 移动端 workspace 导航：用户明确不处理，产品当前不是移动端项目。

### 不采纳

- `DocumentChunk.id` 缺少默认 UUID：worker 使用由 version/ordinal/content hash 派生的确定性 UUID。
- `current_version_id` 在创建时未立即设置：它只在版本成功入库后更新，避免失败版本进入可检索当前版本。
- 中文 token 估算 `0.6 * 字符数`：与当前 DeepSeek 约定一致。
- 批量路由“没有单文件上限”：单个文件由 `create_document` 拒绝为 batch item，符合已接受的部分成功语义。

## 复验

- `docker compose run --rm --build api-test`：40 passed。
- `npm.cmd run lint`：通过。
- `npm.cmd run build`：通过。
- `git diff --check`：通过。
- `docker compose up --build -d` 后，所有容器正常运行；`/ready` 与 Web 首页均返回 HTTP 200。
- 只读浏览器 smoke：workspace 列表和切换正常，四项依赖状态均为可用/可写，控制台未发现 warning 或 error。

仍需在阶段收尾前，以真实资料完成一次 post-fix 人工浏览器 smoke，重点核验批量幂等冲突提示、异步处理状态、重试/取消和带引用回答。这一步会创建资料与调用已配置的 provider，因此保留给用户在明确开始验收时执行。

## 追加人工验收反馈与增量修复（2026-07-13）

- 未点击上传前的多次选文件原先会互相覆盖，现在按 `name/size/lastModified` 去重累加到待上传列表，并允许在本地副本阶段逐个移除。切换 workspace 会清空未提交候选，避免跨 workspace 上传。
- 真实资料验收发现：纯 Qdrant Top-K 会将非相关关键词的低分候选当作证据，还会在候选次数不足时排除文件名完全匹配的资料。现在 `/rag/query` 和 `/rag/answer` 共用 `词面支持 OR 最低向量分数` 门禁，且默认先召回 `min(top_k*3, 50)` 个候选；无合格证据时回答不得调用 generation provider。
- 调试中发现一份已上传的测试资料含有 provider key 形式的敏感内容。未将其内容、密钥或绝对路径写入本记录。用户应在页面删除该资料并立即轮换对应 provider key。

### 增量复验

- `docker compose run --rm --build api-test`：42 passed。
- `npm.cmd run lint` 与 `npm.cmd run build`：通过。
- `docker compose up --build -d` 后，API `/ready` 返回 `ready`，本地容器均正常运行。
- 以 UTF-8 编码直连本地 API 的真实检索验证：“英雄联盟”返回 0 条；“搜广推”返回 5 条来自匹配文件名的资料。Windows PowerShell 默认请求编码会造成中文检查的假阴性，不作为产品结论。

### 收尾人工 Gate

用户完成了代表性浏览器核验：上传和异步状态显示正常，PDF 初次失败的修复在用户重试后成功，批量候选列表与显式清除检索状态的 Web 交互已经确认。已发现的包含 provider key 形式内容的测试资料不再用于真实 generation 复验；后续应先删除该资料并轮换 key，再以无敏感 fixture 进行 provider/eval smoke。

因此本评审在 Stage 2 范围内收尾；正式的阶段结论、暂缓风险和 Stage 3 输入见 [Stage 2 总结与 Stage 3 输入](../STAGE_2_SUMMARY_AND_STAGE_3_INPUTS.md)。
