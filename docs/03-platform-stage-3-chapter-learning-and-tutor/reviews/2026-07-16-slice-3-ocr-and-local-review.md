# 2026-07-16 Slice 3 OCR 与本地审查记录

## 范围与隐私边界

本次 OCR 仅扫描用户允许公开的普通源码，并使用仓库外的一次性白名单副本。主动排除了 API key、`.env`、私有连接地址、内部域名、上传原文、敏感 prompt、日志、绝对路径和 provider 配置。

扫描分为三个风险块：

1. API 运行摘要：router、schema、service、注册入口和 focused tests，共 6 个文件。
2. Stage 3 eval：runner、manifest、metrics、report 和 tests，共 6 个文件。
3. Web 运行记录：panel、API client、入口和样式，共 4 个文件。

原始输出归档在 `reviews/raw/slice3-*.txt`。三个 scan 均完整结束，未发现残留 OCR 进程或截断提示。

## OCR 命令与耗时

每块先执行 `ocr scan --preview --path ...`，再使用：

```powershell
ocr scan --audience human --path <whitelist-block> --concurrency 1 --timeout 10 --background "Stage 3 Slice 3 context"
```

实际结果：

- API：6 files，20 comments，约 364,777 tokens，13m14s。
- Eval：6 files，19 comments，约 261,486 tokens，11m52s。
- Web：4 files，16 comments，约 186,622 tokens，11m36s。

三块均完成，但均超过 Playbook 偏好的 150K token 或 10 分钟边界。preview 未给出可靠 token 估算；后续同类 scan 应继续按函数或合同边界缩小，而不是延长 timeout。

## 采纳并修复

- Eval 离线模式不再调用 `get_settings()`，改为代码内构造的 fake-provider 设置，确保不读取 `.env` 或进程环境中的 provider 配置。
- Eval report 增加运行时严格白名单 schema，拒绝未批准的字段和任意 metrics，避免未来扩展意外写入内容、路径或配置。
- Observational probe 失败现在记录稳定 `status`、`error_category` 和耗时，但仍不阻断 hard gate；新增回归测试。
- 每个 eval probe 结束后关闭 Session 并 dispose 临时 SQLite engine，避免重复运行泄漏资源。
- Tutor history probe 现在实际覆盖 8-turn 上限，而不只检查一个不足上限的样本。
- Web 不再直接显示底层 `Error.message`，仅展示固定、脱敏的用户错误提示。
- Web 课程筛选加载失败不再静默；运行记录仍可独立查看。
- Web running 状态轮询增加 AbortController 与 in-flight guard，避免重叠请求和卸载后的旧响应。
- Web detail error 按 run id 隔离，避免快速切换展开项时错误显示到另一条记录。
- 修正文档注释：运行摘要会返回已记录的 input/output token 数，而不是所谓“usage 永不返回”。

## 排除、暂缓与理由

- “router import 全部损坏”是白名单副本缺少既有 router 上下文导致的误报；完整 API 测试和 Docker 启动均通过。
- CORS、全局异常、日志、settings、旧 `/ready` 和既有 Web request helper 等评论不属于 Slice 3 diff，且部分依赖被隐私边界主动排除；不借 OCR 扩大范围。
- API 列表无 offset pagination：Spec 005 明确约束为最近记录、`limit <= 50`，不是本切片缺陷。
- API identity 查询存在有限 N+1 可能：单次最多 50 条，当前优先保持删除语义和显式 workspace 校验；作为后续性能观察项，不在收尾切片引入复杂 join。
- 未统一把 role/status/tool name 改为数据库 enum：当前写入路径和 response schema 已受控，属于低风险一致性改进。
- Real-provider eval 仍 fail-closed：没有显式确认和预算时不会读取配置或发起外部调用；真实 provider 观察不冒充离线硬门禁通过。实际观察留给人工明确授权后的独立动作。
- Web modal、旧页面布局、移动端完整矩阵等评论属于既有界面或 Spec 005 明确不做项；不扩大到 Stage 4 或跨浏览器重构。

## 复验

- Focused API/eval tests：`17 passed`。
- API 全套：`76 passed`。
- Offline eval：`19/19` hard gates passed，3 observational cases recorded。
- Web ESLint：通过。
- TypeScript project build：通过。
- 本机 Vite build：受 Codex sandbox 上层目录读取限制而失败；同一源码在 Docker Web production build 中成功，1583 modules transformed。
- `docker compose build`：API、worker、reconciler、Web 全部成功。
- `docker compose up -d` / `docker compose ps`：API healthy，其余服务运行。
- `/ready`：ready；Web：HTTP 200；现有 Workspace 的运行摘要 API：HTTP 200。
- `git diff --check`：通过。

## 人工 Gate 与收尾

- 2026-07-16，用户在 Chrome 中确认 Workspace 的“学习 / 运行记录”切换、身份、筛选、展开详情、刷新、删除后的脱敏行为和 token 未报告语义没有功能性问题，Slice 3 人工 UI Gate 通过。
- 若未来决定执行真实 provider 观察，仍必须另行确认脱敏 fixture、provider、最大 case 数和最大调用数；它只形成观察基线，不替代离线 hard gate。
