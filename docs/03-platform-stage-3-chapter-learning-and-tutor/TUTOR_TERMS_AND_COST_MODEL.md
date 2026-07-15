# Tutor 名词与成本模型

日期：2026-07-15

状态：用于评审 Spec 002/ADR 003/004 的解释材料；价格是 2026-07-15 的外部事实，预算仍待人工 Gate。

## 1. 名词具体指代

### Tutor

Tutor 是“受控辅导角色和一次运行时能力”，不是数据库中的常驻机器人，也不是一直占用资源的后台进程。

用户提交一个问题后，worker 为该次 attempt 创建全新的 Tutor runtime，装入有限历史、当前课程/课节快照和两个允许工具，生成结果后销毁。Tutor 不拥有 workspace、session 或消息事实，也不自动记住用户。

### Session

Session 是一段连续辅导对话的 Postgres 容器。它固定一个 Course Version，保存用户可见的 Turn 历史和外部处理确认。

创建 Session 本身不调用模型，通常只有数据库成本。Session 不是长期 Memory：它不会跨课程推断偏好，不更新掌握度，也不会自动生成隐藏画像。

### Turn

Turn 是 Session 中“一次用户提问及其最终 Tutor 回答”的稳定业务记录。例如：

```text
用户：B+ 树为什么适合数据库索引？
Tutor：带引用回答……
```

这整体是一个 Turn。一个 Turn 可以经历多次 attempt，但最终最多只有一份正式成功回答。

### Attempt

Attempt 是执行某个 Turn 的一次尝试。provider 超时后显式重试，会产生新的 attempt 和新的 Agent Run，也会重新消耗模型与 embedding 成本。失败 attempt 已经发出的 provider 请求仍可能计费。

### Message 与 History

Message 是 Turn 中的用户问题或 Tutor 回答正文。History 是为理解“它”“刚才那个例子”等指代而装入当前 attempt 的最近成功 Turn。

History 会占输入 token，并在每轮重新发送，因此对话越长，单轮成本会增长，直到达到“最近 8 Turn / 6,000 tokens”上限后趋于稳定。

### Scope

- `lesson scope`：默认模式，问题聚焦当前课节，但证据仍只能来自固定 Course Version 的来源快照。
- `course scope`：用户显式选择，用于跨课节比较或总结；不会扩大到其他课程或 workspace。

Scope 由产品固定，不由模型自行改变。

### Evidence、Citation 与检索

Evidence 是当前 attempt 从资料 chunk 回读的临时正文，只在本次运行中供模型使用。Citation 是最终回答保存的可定位引用，指向 document version 和 chunk。

Evidence 会占模型输入 token；Citation 元数据本身很小。Qdrant 只返回候选，Postgres 回读后才有资格成为 evidence。

### Agent Step、Tool Call 与 Provider Call

三者不是同一个计费单位：

- Agent Step：产品的逻辑预算单位，例如一次检索或一次结构化提交。
- Tool Call：Tutor 调用产品工具；本地 Qdrant/Postgres 查询通常没有模型输出费用。
- Provider Call：真正发送到 DeepSeek 或 embedding provider 的网络调用，按 token 计费。

草案的 `5 step / 3 search` 推荐映射为：

| 阶段 | Agent step | DeepSeek 调用 | Embedding 调用 |
|---|---:|---:|---:|
| 查询规划 | 不单独占工具 step | 1 | 0 |
| 最多 3 次 Evidence Search | 1 至 3 | 0 | 1 至 3 |
| SubmitTutorAnswer | 1 | 1 | 0 |
| 校验失败后的修复提交 | 最多 1 | 最多 1 | 0 |

因此正常是 2 次 DeepSeek 调用，最坏 3 次；不是 5 次 DeepSeek 调用。完整开放式 ReAct 每 step 都重新请求模型，成本更难控制，本草案不采用。

### Run 与 Trace

Agent Run 是一个 attempt 的审计摘要；Tool Call Trace 是该 Run 的工具调用摘要。它们记录 token、延迟、状态、hash 和数量，不保存问题、回答、history、evidence 或 prompt 正文。

### SSE

SSE 是服务器向浏览器推送状态和已验证回答 block 的传输方式。保持连接、心跳和重连本身不消耗模型 token；它只消耗少量本机网络、Redis 和 API 资源。

## 2. 一次 Turn 的成本从哪里来

### 2.1 查询规划

输入通常包含系统规则、当前问题、课程/课节元数据和有限 history；输出是 1 至 3 条短检索 query。

这是一笔 DeepSeek 输入/输出 token 成本。History 越大，规划调用越贵。

### 2.2 Evidence Search

每条 query 调用 `text-embedding-v4` 生成查询向量，随后在本地 Qdrant 检索并由 Postgres 回读。

- embedding 按 query 输入 token 计费；
- self-host Qdrant/Postgres 没有外部按 token 费用，但占用本机 CPU、内存和磁盘；
- evidence chunk 不会重新 embedding，因为资料上传时已经完成。

### 2.3 回答生成

输入包含系统规则、问题、有限 history、课程/课节上下文和最多 8,000 evidence tokens；输出最多 2,000 tokens。

这通常是单 Turn 最大的成本来源，因为 evidence 与 history 都属于输入，而且回答输出单价高于输入。

### 2.4 修复

只有首次回答的 JSON、block 或 citation 校验失败时才调用。修复会重新发送大部分输入以及无效输出，因此接近再做一次回答生成。它不是免费 retry。

### 2.5 取消、失败和 retry

- 在 provider 请求前取消：几乎没有模型成本。
- provider 已开始后取消：已经生成的 token 仍可能计费，即使结果最终不提交。
- 资料不足：可能只产生规划和 embedding 成本；没有有效 evidence 时不调用回答生成。
- 显式 retry：重新执行完整 attempt，成本重新计算。
- SSE 断线：草案规定不自动取消，因此不会仅因刷新重复发起 provider 调用。

## 3. 当前价格与估算

仓库默认使用 `deepseek-v4-flash`、非思考模式。DeepSeek 官方在 2026-07-15 公布的人民币单价为：缓存未命中输入 `1 元/百万 tokens`、缓存命中输入 `0.02 元/百万 tokens`、输出 `2 元/百万 tokens`。价格会变化，正式成本面板必须以 provider 返回 usage 和当时价格表为准。

官方来源：[DeepSeek 模型与价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing)。

当前 `text-embedding-v4` 的中国内地区域参考价格为输入 `0.6 元/百万 tokens`，输出不计费。

官方来源：[阿里云 AI 中心计费](https://help.aliyun.com/zh/milvus/product-overview/ai-center-billing)。实际账单仍取决于当前 DashScope 账户和地域。

### 3.1 正常 Turn 示例

保守假设：

- 规划输入 7,200、输出 200 tokens；
- 回答输入 15,500、输出 2,000 tokens；
- 3 条 embedding query 合计 300 tokens；
- 全部 DeepSeek 输入按缓存未命中计算。

```text
DeepSeek 输入：(7,200 + 15,500) / 1,000,000 * 1 元 = 0.0227 元
DeepSeek 输出：(200 + 2,000) / 1,000,000 * 2 元 = 0.0044 元
Embedding：300 / 1,000,000 * 0.6 元 = 0.00018 元
合计约 0.0273 元/Turn
```

### 3.2 最坏且发生一次修复

再假设修复输入 17,500、输出 2,000 tokens：

```text
DeepSeek 输入：40,200 tokens = 0.0402 元
DeepSeek 输出：4,200 tokens = 0.0084 元
Embedding：约 0.00018 元
合计约 0.0488 元/Turn
```

这不是严格账单上限，因为 tokenizer 实际值、provider 附加字段和 retry 会变化；它是当前草案预算下的保守量级。缓存命中可能降低输入费用，但设计预算不依赖缓存命中。

### 3.3 Session 累计量级

| 使用量 | 按正常 Turn 估算 | 每 Turn 都触发修复的保守估算 |
|---:|---:|---:|
| 10 Turn | 约 0.27 元 | 约 0.49 元 |
| 100 Turn | 约 2.73 元 | 约 4.88 元 |

Session 创建、读取、SSE、Postgres 和 Redis 没有额外 provider token 费。随着 history 增长，前几轮成本逐渐上升；达到 history 上限后不再线性增长。

## 4. 哪些选择最影响成本

按影响从大到小通常是：

1. evidence 上限和回答输出上限；
2. history token 上限；
3. 是否发生修复或 retry；
4. 每 Turn 是否需要查询规划；
5. 检索次数本身。

Embedding query 很短，三次检索的直接 embedding 费用非常小；检索次数更主要影响延迟和最终装入多少 evidence。SSE 对 token 成本几乎没有影响。

## 5. 当前推荐

- 保留 `5 step / 3 search`，但明确实现为最多 3 次 DeepSeek 调用，而不是开放式 5 次 ReAct 调用。
- history 维持 6,000 token 上限，evidence 维持 8,000，输出维持 2,000。
- usage 以每个 attempt 单独记录；Web 至少显示本 Turn token，Stage 5 再做完整人民币成本治理。
- eval 同时记录正常、资料不足、修复和 retry 四类成本，不能只测成功平均值。
