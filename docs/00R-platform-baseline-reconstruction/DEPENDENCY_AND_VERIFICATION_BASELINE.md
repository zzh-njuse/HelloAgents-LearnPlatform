# 0R-A：依赖与验证基线

状态：完成
日期：2026-07-10
基线提交：`4b81f92461ff05c3d78f4bc6cf54cd07a01ba753`

## 目的

本记录在创建产品应用前固化可复现的起点。它将现有代码划分为三个独立运行通道，而不把它们误认为同一个可安装应用。

| 通道 | 当前权威来源 | 结果 | 0R 结论 |
|---|---|---|---|
| `hello_agents/` framework | 根目录 `pyproject.toml`、`requirements.txt`、`uv.lock` | 核心依赖可由 `uv --frozen` 解析；根测试工具未声明 | 保持为可复用 framework 通道 |
| `academic_companion/` 原型 API | 仅源码 import | 使用了 FastAPI、Uvicorn、Qdrant client，但没有独立依赖清单 | 作为参考原型，不作为可运行的产品入口 |
| `academic_companion/webui/` 原型 Web | `package.json`、`package-lock.json` | lint 和生产构建通过 | 作为 UI/SSE 合约参考，不作为 Stage 1 Web |

## 观察到的环境

- Windows 主机；默认 `python` 为 Anaconda Python 3.13.5。
- `uv` 为冻结的 framework 通道创建了被忽略的本地 `.venv`，解释器为 CPython 3.12.13。
- Node.js 为 24.14.0，npm 为 11.9.0。
- 本次审计无需 Docker；Compose 验收属于 Stage 1。

默认 Anaconda 环境缺少已声明的 `tiktoken`，因此根测试无法完成收集。它不是本仓库的验收环境。

## 命令与结果

| 命令 | 结果 | 说明 |
|---|---|---|
| `python -m pip check` | 通过 | 默认环境中没有破损的包关系，但该环境与项目无关 |
| `python -m pytest -q` | 在收集阶段阻塞 | `ModuleNotFoundError: tiktoken` |
| `uv run --locked python -m pytest -q` | 执行前阻塞 | `uv.lock` 相对 `pyproject.toml` 已漂移 |
| 带临时 `pytest`、`pytest-asyncio` 的 `uv run --frozen python -m pytest --collect-only -q` | 通过 | CPython 3.12.13 共收集 231 个测试 |
| 聚焦的离线 framework 测试集 | 通过 | 3.81 秒内 `155 passed, 4 skipped` |
| 在 `academic_companion/webui` 执行 `npm.cmd run lint` | 通过 | 既有 Web 原型 lint 基线 |
| 在 `academic_companion/webui` 执行 `npm.cmd run build` | 通过，有警告 | 最大 JS chunk 为 620.56 kB，超过 Vite 500 kB 警告阈值 |

聚焦测试集使用 `uv run --frozen --with pytest --with pytest-asyncio`，覆盖 lifecycle、circuit-breaker、custom-tool、file-tool、LLM function-calling、observability、research-note、session-persistence、skills、subagent、todo、tool-filter 与 tool-response 测试。

被跳过的用例需要真实 LLM 配置。`tests/test_all_agents.py`、真实 provider 用例和可选 MCP/外部工具用例不属于可确定复现的本地验收集，必须与产品 Stage 1 验收分开记录。

## 依赖发现

1. 根包声明了 `tiktoken`，但默认主机 Python 未安装它；`uv --frozen` 可以解析声明的 framework runtime。
2. 根测试依赖是隐式的。测试集需要 `pytest` 和 `pytest-asyncio`，但二者既不在项目 dependency group 中，也不在锁文件中。
3. 锁文件未与根项目元数据同步。`--frozen` 可使用已有锁，`--locked` 正确地拒绝执行。
4. `hello_agents/storage/qdrant_store.py` 对 Qdrant 为延迟 import；FastMCP 同样为可选能力。不能只因原型可能使用它们，就把它们加入 framework 强制依赖。
5. 原型 API import 了 `fastapi`、`uvicorn` 和 `qdrant_client`，但没有应用级依赖清单声明它们，当前不存在可靠的 API 启动命令。
6. 原型 Web 有有效 npm lockfile，但构建输出提示未来需评估 bundle 拆分；这不是 Stage 0R 阻塞项。

## 基线决策

- 重建阶段不改写根锁文件。必须先决定 framework 测试工具是否属于 dev dependency group，再在独立、可评审的变更中重建锁文件。
- 不把原型 API 包加入 framework 包。Stage 1 通过独立的 `apps/api/requirements.txt` 管理应用依赖，相关决定见其 ADR 草案。
- 在依赖策略实施前，使用 `uv run --frozen --with pytest --with pytest-asyncio` 作为临时 framework 验证通道。
- 将聚焦测试集作为当前确定性的 framework gate；真实 provider 与外部工具测试仅在显式 runtime 配置下运行，并单独记录结果。

## 已满足的退出条件

- 已识别 framework、原型 API 与原型 Web 的安装边界。
- 已记录可复现的 framework 收集命令和离线通过的测试子集。
- 已在创建产品应用前确认原型 API 的未声明 runtime 依赖。
