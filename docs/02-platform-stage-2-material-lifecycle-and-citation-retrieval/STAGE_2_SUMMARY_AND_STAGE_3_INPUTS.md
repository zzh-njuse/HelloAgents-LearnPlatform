# Platform Stage 2 总结与 Stage 3 输入

日期：2026-07-13

状态：Stage 2 已完成并收尾；本文件是 Stage 3 文档工作的唯一阶段输入，不授权开始 Stage 3 业务实现。

## 1. 阶段结论

Stage 2 已将 Stage 1 的 workspace-first 平台壳扩展为资料驱动的产品链路：用户可以上传 PDF、Markdown 或 TXT，查看逐文件的异步处理状态，检索可定位的资料片段，并获得受引用证据约束的单轮回答。

本阶段仍不是 chat-first 应用，也没有引入 Tutor Agent、课程、练习、学习记忆或多用户鉴权。现有 `academic_companion` 能力与八股/LeetCode 数据仍是可复用资产、fixture 或 eval 候选，不是产品事实模型。

## 2. 实际完成

### 2.1 资料生命周期与存储边界

- 建立 `source_documents`、`document_versions`、`document_parse_reports`、`document_chunks`、`ingestion_jobs`、batch/item、query trace 和 answer trace 的 Alembic 合同。
- 单文件和批量上传均保留每个文件独立的 document/version/job 身份、错误、重试和部分成功语义；批量取消不会删除已成功的资料。
- Postgres 是资料、版本、状态、可见性与引用的事实来源；原始字节和派生文本进入 storage；Qdrant 仅保存可重建索引；Redis 仅负责非权威投递和协调。
- 删除先在 Postgres 提交不可见状态，再做 Qdrant/storage 清理；维护命令可由 ready chunk 重建 Qdrant。

### 2.2 解析、队列与资源保护

- PDF、Markdown、TXT 经过受控 parser、规范化、切块、DashScope embedding 和 Qdrant 写入；DashScope 不可用时明确失败，不静默降级到本地 embedding。
- worker 使用 Postgres claim/lease/heartbeat、显式 retry、reconciler 和 workspace 并发上限；心跳丢失后不继续关键外部副作用。
- PDF 采用受监督子进程；默认页数、解析文本、chunk、embedding token、时间和并发预算分别受配置约束。超限显式失败，不把不完整资料标记为 ready。

### 2.3 检索、引用与回答

- `/rag/query` 强制 workspace filter，随后由 Postgres 权威回读当前 ready version；citation 可定位 document、version、chunk、标题路径与字符偏移。
- `/rag/answer` 使用独立 `PRODUCT_GENERATION_*` 配置和 DeepSeek Flash 的结构化 claim/citation 合同；模型不能自行声明资料身份，越界 citation 不能成为成功回答。
- 最终检索门禁为“词面支持 OR 最低向量分数”；默认 `top_k=5`、先召回 `candidate_k=min(top_k*3, 50)`。无合格证据时返回 `insufficient_evidence`，不调用 generation provider。
- Web 支持待上传文件的累加、去重、移除；搜索词变化不会自动清掉旧结果，用户可通过搜索框旁的叉号显式清除检索与回答。

## 3. 验证与评审结论

| 类别 | 结果 |
|---|---|
| API focused tests | `docker compose run --rm --build api-test`：42 passed |
| Web | `npm.cmd run lint`、`npm.cmd run build`：通过 |
| Compose | `docker compose up --build -d` 后 API `/ready=ready`、Web HTTP 200 |
| 真实检索 | UTF-8 请求下，“英雄联盟”返回 0 条；“搜广推”返回 5 条匹配资料 |
| 人工浏览器 | 用户核验上传、处理状态、重试、PDF 回归和 Web 交互；PDF 初次失败修复后已由用户重试成功 |
| 独立审查 | 用户完成 5 个风险块的 OCR 扫描；高置信 finding 已修复，详见 `reviews/` |

Stage 2 OCR 原始输出、采纳/暂缓决定和增量人工验收反馈均已归档在 [reviews/](reviews/README.md)。本次实际测试资料中发现过 provider key 形式的敏感内容；其值、正文和路径未进入 Git 或审查记录。该资料必须从 workspace 删除，相关 provider key 必须轮换。

## 4. 暂缓风险和明确非目标

- OCR、Office、网页和 Git 导入是独立 parser extension 候选，不是永久排除项；还需评估 MIME/magic-byte、病毒扫描、流式直写、隔离和所有权合同。
- 当前仅是单用户 self-host；尚无多用户身份、workspace 授权、对象存储、生产 secret 注入、Redis/Qdrant 鉴权、反向代理或容器加固。
- 相关性门禁是保守的产品安全基线，不是已完成的 RAG 质量结论；尚未建立固定 corpus 上的 recall、citation correctness、拒答率和成本 eval。
- 后修复的“无证据即资料不足”路径有 focused test 覆盖。为避免把已发现的敏感测试资料发给外部 generation provider，未再次以该 workspace 做 post-fix 真实回答调用；Stage 3 应以无敏感、可提交描述的 fixture 完成 provider/eval smoke。
- 当前不建设移动端 workspace 导航，用户已明确该产品不以移动端为目标。

## 5. Stage 3 必须继承的边界

1. Course、lesson、Tutor 和任何 Agent 输出不能绕过 Stage 2 的 workspace、document/version/chunk/citation 权威链路。
2. 新生成内容必须有自己的事实、版本、发布和删除合同；不能把模型输出或 Qdrant payload 当作唯一事实来源。
3. `CitedAnswerService` 是可复用的受控检索/引用基础，不等于 Tutor Agent。session、memory、tool、run trace 和对话保留策略尚未被批准。
4. DashScope embedding 与 DeepSeek generation 分属不同配置边界；不实现自动 provider/model fallback，不向日志、trace 或公开 API 写入 key、上传正文、完整 prompt 或内部 URL。
5. 课程或 Tutor 的生成应先对固定、无敏感 fixture 做 eval，再使用真实用户资料进行显式人工 smoke。
6. 八股/LeetCode 仅可作为 Stage 3 的 fixture/eval/演示材料，不得反向定义 course、lesson 或 concept schema。

## 6. Stage 3 文档 Gate

在写业务代码或 migration 前，必须完成并经人工接受：

1. Stage 3 事实盘点：Stage 2 API/数据合同、现有 `academic_companion` 的 LearningAgent/Skill/research 能力，以及可复用与禁止复用的边界。
2. Spec：首条“资料 -> 章节 -> 阅读 -> 当前上下文辅导”的用户路径、页面信息架构、失败模式、引用规则、发布/重生成和验收。
3. ADR：至少覆盖 course/section/lesson 的事实与版本模型；Tutor runtime、session/memory/tool 权限与 run trace；生成任务、引用与 eval 的持久化/删除/成本边界。
4. 实现计划：先小范围建立 schema 与最小 Course Reader，再在已接受合同内接入受控 Tutor；不得把 Stage 4 的练习或长期记忆挤入首个 Stage 3 切片。

## 7. 文档入口

- [Stage 2 README](README.md)
- [Slice 1 总结与 Slice 2 输入](SLICE_1_SUMMARY_AND_SLICE_2_INPUTS.md)
- [Slice 2 OCR 评审](reviews/2026-07-13-stage-2-slice-2-ocr-review.md)
- [Stage 3 文档入口](../03-platform-stage-3-chapter-learning-and-tutor/README.md)
