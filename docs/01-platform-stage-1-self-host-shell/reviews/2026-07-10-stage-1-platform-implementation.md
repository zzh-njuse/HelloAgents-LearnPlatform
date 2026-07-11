# Stage 1 平台实现 Review 记录

日期：2026-07-10
状态：本地自审与 OCR preview 完成；付费 OCR 实审未运行

## 审查范围

- `apps/api` 产品 API、Alembic migration、测试与 Dockerfile。
- `apps/web` workspace 工作台、API client、响应式样式、Nginx 与 Dockerfile。
- 根 Compose、环境样例、storage ignore 规则与 Stage 1 运行文档。

最终 `ocr review --preview` 识别到 55 个变更文件，约 `+4869/-4`；其中 43 个代码/配置文件进入可审查范围，12 个 Markdown、requirements、Mako 或 Nginx 文件因扩展名不受支持而排除。

## OCR 决策

未运行会向 provider 发送代码并产生费用的真实 OCR review。原因是仓库规则要求用户明确批准付费实审，而本轮只获得了“开始开发”的实现 gate。OCR preview 已证明工具和审查范围正常；真实 OCR 仍需单独确认。

## 自审发现与处理

| 发现 | 处理 |
|---|---|
| 临时 `uv run` 意外改写根 `uv.lock` | 已恢复根锁文件；API 验证改为 `uv run --no-project --with-requirements`，保持 framework/product 依赖边界 |
| Web Docker context 首次包含本地 `node_modules`，约 111 MB | 增加 `apps/web/.dockerignore`；最终 context 降至增量级别，构建正常 |
| 本机 5432 被既有 Postgres 占用 | self-host 默认宿主端口改为 55432；容器内部仍使用 5432；本地 API 默认配置同步修改 |
| 基础设施端口默认暴露到所有网卡 | 增加 `BIND_ADDRESS=127.0.0.1`，五个服务默认仅本机可访问 |
| API healthcheck 造成重复、密集访问日志 | 结构化 middleware 跳过成功 `/health` 日志，并关闭 Uvicorn access log |
| 产品入口可能再次固化原型 chat | Stage 1 API 未挂载任何 prototype chat/knowledge router；Web 首屏仅提供 workspace 与状态工作流 |

## 验证结果

| 验证 | 结果 |
|---|---|
| Stage 1 API tests | `7 passed` |
| Framework 离线回归集 | `155 passed, 4 skipped`；20 个既有 deprecation warning |
| Alembic offline SQL | 生成 `alembic_version` 与 `workspaces` DDL 成功 |
| 实际 Postgres migration | `alembic_version=0001` |
| Web lint | 通过 |
| Web production build | 通过；JS 208.22 kB，gzip 65.20 kB |
| npm install audit | 0 vulnerabilities |
| Docker image build | API/Web 均通过 |
| Docker Compose | 五服务启动；API/Postgres/Redis healthy，Qdrant 可由 `/ready` 探测 |
| HTTP smoke | `/health=ok`、`/ready=ready`、Web HTTP 200 |
| 业务 smoke | API 与 Web 均成功创建 workspace；API 重启后数据仍存在 |
| 视觉 QA | 1440x900 与 390x844 均无横向溢出或控件重叠；浏览器 console 无 warning/error |
| Markdown 链接与 diff whitespace | 通过；无断链、无尾随空白 |

## 暂缓项与剩余风险

- Stage 1 为单用户 self-host，尚无认证与授权；默认仅绑定本机以降低暴露面。
- `.env.example` 使用开发默认密码，runbook 已要求局域网使用前修改；正式公网部署不在本 Stage。
- 未制造没有稳定资产接口的 `academic_companion` capability adapter；这不阻塞基础壳验收。
- Qdrant 容器未声明独立 Compose healthcheck，但产品 `/ready` 已实际验证其 `/readyz`。
- 真实 OCR review 等待用户明确批准 provider 成本。
