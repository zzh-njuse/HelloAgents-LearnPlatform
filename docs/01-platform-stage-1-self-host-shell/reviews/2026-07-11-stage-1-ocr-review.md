# Stage 1 OCR 代码评审与处置记录

日期：2026-07-11
状态：已完成真实 OCR 评审、三项修复与复验

## 背景与范围

本次审查的对象是 Stage 1 self-host 平台骨架的当前未提交 diff：Compose 基础设施、FastAPI API、Alembic migration、workspace CRUD、React/Vite Web 控制台及其运行配置。

命令：

```powershell
ocr llm test
ocr review --audience agent --background "Stage 1 of a self-hosted learning-platform shell..."
```

OCR 使用已配置的 DeepSeek provider（`deepseek-v4-pro`）。实际审阅 42 个代码/配置文件，耗时约 6 分 34 秒；工具报告约 1,104,411 tokens。Markdown、requirements、Mako 与 Nginx 等 12 个不受支持扩展名文件未纳入 OCR 源码审查。

## 采纳并修复

| 发现 | 处置 |
|---|---|
| Redis URL 异常会在 `Redis.from_url()` 处逃逸，使 `/ready` 返回 500 | `check_redis()` 将 client 创建纳入 `try`，并仅在 client 已创建时关闭；新增 malformed URL 测试 |
| API Docker 容器的 shell 不会将关闭信号交给 Uvicorn | 启动命令改为 `alembic upgrade head && exec uvicorn ...` |
| 未处理异常没有完成请求日志，也无法返回 `X-Request-ID` | middleware 捕获未处理异常，写入 `request_failed` 日志，返回标准 500 JSON 并保留请求 ID；新增回归测试 |

## 记录但暂缓

| 发现 | 决策与理由 |
|---|---|
| Postgres 使用开发默认口令 | 当前服务默认仅绑定 `127.0.0.1`，且 Stage 1 runbook 已明确 LAN/公网使用前必须修改；归入部署加固工作 |
| 非 Docker 启动时 `storage_root` 依赖当前工作目录 | 当前 Stage 1 的支持主路径为 Compose；在 Stage 2 引入资料存储工作流前统一处理本地开发路径策略 |
| readiness 检查吞掉底层异常但没有写日志 | 有运维价值，但不是当前可用性阻塞项；后续 observability 强化时合并处理 |
| Qdrant 缺少 Compose service healthcheck | API 尚未在启动期依赖 Qdrant 执行业务；`/ready` 已实际检查 `/readyz`，暂不扩大 Compose 配置 |

## 不采纳

| OCR 建议 | 不采纳理由 |
|---|---|
| Alembic online migration 会使用 `localhost:55432` | `env.py` 的 `config.set_main_option("sqlalchemy.url", get_settings().database_url)` 已覆盖 Alembic 配置；OCR 未正确识别该路径 |
| workspace slug 应从 `-1` 而不是 `-2` | 现有行为与测试一致，属于命名策略而非正确性缺陷 |
| storage readiness 创建目录必然掩盖 bind mount 缺失 | 当前检查的合同是“存储根是否可写”，而非判别挂载来源；该建议不足以证明存在当前缺陷 |
| Web 初始状态显示降级 | 首次健康探测前的短暂 UI 呈现不是 Stage 1 阻塞问题，留待 Web 体验迭代 |

## 复验

| 验证 | 结果 |
|---|---|
| API focused pytest | 未能在沙箱中运行：`uv` 缓存与受管 Python 目录权限受限，系统 Python 未安装 FastAPI；已改用容器内等价回归检查 |
| Redis malformed URL 回归 | 容器内 mock `Redis.from_url()` 抛出 `ValueError` 后，`check_redis()` 正确返回 `{"ok": false}` |
| 未处理异常回归 | 容器内 TestClient 触发 500；响应保留 `X-Request-ID: failed-request`，同时记录 `request_failed` 与 `request_completed` |
| Docker API rebuild | 通过；API 容器重建后 healthy，启动命令采用 `exec uvicorn` |
| `/ready` smoke | 通过；Postgres、Qdrant、Redis、storage 均为 `ok: true`，整体状态 `ready` |
| `/health` request ID | 通过；`X-Request-ID: ocr-followup` 原样返回 |
| Web lint | 通过 |
| Web production build | 通过；初次在沙箱因 Vite/esbuild 上级目录读取受限失败，非沙箱复验成功 |

## 人工 Web 核验跟进

人工浏览器核验发现创建 workspace 的名称输入框与描述文本框缺少 `id` 和 `name`，浏览器因此发出 autofill 可用性告警。已分别补充 `workspace-name` / `workspaceName` 与 `workspace-description` / `workspaceDescription`；Web lint 与 production build 均已复验通过。
