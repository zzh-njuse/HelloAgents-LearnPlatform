# ADR 006：Parser 资源预算、隔离与超限语义

状态：已接受
接受日期：2026-07-13
日期：2026-07-13
适用阶段：Platform Stage 2 Slice 2

## 1. 决策摘要

不以单一原文件大小作为资源保护。采用“请求准入 + parser 子进程隔离 + 增量页/字符预算 + chunk/token 预检 + provider 分批 + worker 并发”分层预算。超过任何硬预算时明确失败，不静默截断，不把部分产物标记为 ready。

## 2. 背景

Slice 1 的 25 MiB 上限只能约束上传字节，不能约束 PDF 解压后的对象数、页数、提取文本、chunk 数、embedding token、CPU 时间或内存。一个原文件很小的 PDF 仍可能造成明显资源放大。进入批量上传后，同一风险会乘以文件数和并发数，因此不能等到 Stage 5 才处理。

纯粹设置更小的“死上限”也不充分：它只能拒绝部分大输入，无法终止卡住的 parser、限制批量并发或阻止 embedding 成本放大。

这里明确覆盖 Slice 1 收尾时提出的“原文件不大，但解析后膨胀”问题，防护分为四层：

| 放大位置 | 例子 | Slice 2 控制 |
|---|---|---|
| 上传批次 | 很多小文件合计占满磁盘/请求 | 单文件 25 MiB、单批 100 MiB、最多 20 文件 |
| PDF 解析 | 压缩对象、超多页、parser 卡住或内存增长 | 独立子进程、500 页、10 分钟、并发 1；跨平台内存 hard limit 仍是剩余风险 |
| 解析文本与切块 | 小 PDF 提取出极大文本并产生大量数据库行 | 1,000,000 字符、2,000 chunks，提交前失败 |
| Embedding/provider | 大量 chunk 形成高额 token 和外部调用 | 约 1,500,000 token 预检、provider 分批、workspace 并发 3 |

## 3. 决策

### 3.1 初始可配置预算

以下是 self-host 默认建议值，均使用产品命名空间配置，并在实现前通过人工 gate 确认：

| 预算 | 默认建议 | 执行阶段 |
|---|---:|---|
| 单文件原始字节 | 25 MiB | API 准入与实际流式计数 |
| 单批文件数 | 20 | API 准入 |
| 单批原始字节 | 100 MiB | API 准入与实际计数 |
| PDF 页数 | 500 页 | parser preflight/逐页检查 |
| 规范化文本 | 1,000,000 Unicode 字符 | parser 增量累计 |
| 单资料 chunk | 2,000 | chunk 生成前后 |
| 单资料 embedding 输入估算 | 1,500,000 tokens | provider 调用前累计 |
| 单资料 parser 墙钟时间 | 10 分钟 | 父 worker 监督子进程 |
| 同一 worker parser 子进程 | 1 | worker 并发边界 |
| 同一 workspace 活跃 ingestion | 3 | Postgres claim/调度边界 |

这些值不是产品永恒常量。修改部署配置不会改变已 ready version；若重新处理资料，新的预算和处理配置进入新的 generation/parse report。

`25 MiB` 与 `100 MiB` 不是二选一：前者限制每个文件，后者限制同一批所有文件相加。文件数上限、单文件字节和批次总字节三项都必须通过。

### 3.2 Parser 子进程隔离

- PDF parser 在独立子进程中运行，父 worker 只传入服务端 storage URI 和预算，不传正文到 Redis。
- 子进程逐页提取、规范化并在受限结果通道返回文本、计数、warning 和状态；父 worker 在成功后原子写入 parsed artifact。受限文本预算避免 IPC 结果无限增长。
- 父 worker监督墙钟时间；超时后终止并回收子进程，清理临时 artifact。
- 子进程异常退出映射为稳定错误，不把 traceback 或原文写入 API。
- Slice 2 至少实现时间隔离和单进程并发边界。操作系统级内存 hard limit 若在当前跨平台开发环境无法一致实现，必须记录为 Stage 5 部署加固项；不能宣称已有完整沙箱。

TXT/Markdown 可保留进程内增量读取，但使用相同字符、时间和取消检查合同。

### 3.3 增量检查

- PDF 先读取页数元数据；超过页数预算时在正文提取前失败。
- 每页提取后规范化文本并累计字符数；达到上限立即停止并失败。
- 解析完成后，chunker 在提交数据库前累计 chunk 数和 token 估算。
- embedding adapter 在任何 provider 调用前检查总估算预算，再按 provider 单批限制执行。
- provider 已产生部分向量但后续失败时 version 不 ready；retry 使用稳定 chunk/point ID 覆盖，并在最终提交前核对完整计数。

### 3.4 超限错误

建议稳定错误码：

- `file_too_large`
- `batch_too_large`
- `pdf_page_limit_exceeded`
- `parsed_text_limit_exceeded`
- `chunk_limit_exceeded`
- `embedding_input_limit_exceeded`
- `parser_timeout`
- `parser_process_failed`

错误消息说明哪个预算被触发、当前部署上限和可行动建议，但不返回宿主机路径、原文或 parser traceback。资源超限默认不可自动重试；管理员提高配置或用户换文件后可显式重新处理。

### 3.5 不允许静默截断

任何超限资料必须保持 failed，parse report 记录已观察计数和错误码。不得保存前 N 页或前 N 个 chunk 后标记 ready，因为：

- 用户无法知道哪些内容缺失；
- citation 会把不完整语料伪装成完整资料；
- 后续 Tutor/课程可能基于缺失内容给出错误判断。

未来若产品需要“用户明确选择部分导入”，必须作为新的可见模式设计，保存选择范围并在资料详情和 citation 中持续标识。

### 3.6 批量公平性与成本

- batch 不直接占有一个大 worker job；逐 item job 按现有队列调度。
- 同一 workspace 活跃 ingestion 默认最多 3 个，其余保持 queued，避免单批占满部署。
- generation answer 与 ingestion 使用不同逻辑并发/超时配置；不得让长 PDF 批量阻塞所有回答。
- 记录解析计数、chunk/token 估算、provider 实际 usage 和延迟，为 Stage 5 容量与成本治理提供事实。

## 4. 影响

### 正向

- 同时控制上传、解析、数据库、Qdrant 和 provider 成本放大。
- 卡住的 PDF parser 可以被父进程终止。
- 超限行为清晰可测试，不产生看似成功的不完整资料。
- 批量上传不会无限提高并发。

### 成本

- parser 子进程、临时 artifact 和结果通道增加实现复杂度。
- 默认预算可能拒绝合法的大型教材，需要部署者显式调整。
- 跨平台一致的内存 hard limit 暂不承诺，仍存在解析库层面的剩余风险。
- token 估算与 provider 实际计费可能不同，必须分别记录。

## 5. 未采用方案

### 只保留 25 MiB 文件上限

不采用。无法限制解压文本、CPU、内存、chunk 和 provider 输入。

### 只设置文本字符死上限

不采用为完整方案。无法终止 parser 卡死、限制页对象或控制批量并发。

### 超限后截断并继续 ready

不采用。破坏资料完整性和 citation 可信度。

### 直接在现有 RQ worker 进程解析所有 PDF

不采用。解析超时或异常可能长期占用甚至终止 worker，批量时影响扩大。

### 立即引入完整容器级恶意文件沙箱

暂不采用。超出 Slice 2 self-host 开发范围；先建立子进程、预算和并发边界，Stage 5 再评估只读容器、seccomp、内存/CPU quota 和独立 parser service。

## 6. 待人工确认

1. 默认页数、字符、chunk、token 与 10 分钟超时是否适合目标资料。
2. 是否接受 Slice 2 只保证 parser 子进程时间隔离，不宣称跨平台内存 hard limit。
3. 同一 workspace 最多 3 个活跃 ingestion 是否适合单机 self-host。
4. 超限一律失败、不提供静默或自动部分导入是否接受。

## 7. 生效条件

与 Spec 002 一并接受后生效。实现必须包含每一预算的边界测试、parser timeout 终止与清理测试、无 silent truncate 测试，以及批量并发不超过配置的集成测试。
