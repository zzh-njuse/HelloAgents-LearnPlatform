# Stage 1 Self-Host 运行手册

## 前置条件

- Docker Desktop，支持 Docker Compose v2。
- 本地开发 Web 时需要 Node.js 22+ 与 npm。
- 本地开发 API 时需要 Python 3.12，并安装 `apps/api/requirements-dev.txt`。

Stage 1 不需要 LLM API key。

默认只绑定 `127.0.0.1`。若确实需要局域网访问，可在 `.env` 中显式修改 `BIND_ADDRESS`；同时应先修改默认 Postgres 密码，并配置主机防火墙。Stage 1 尚不提供公网 HTTPS 或反向代理方案。

## Compose 启动

在仓库根目录执行：

```powershell
Copy-Item .env.example .env
docker compose config
docker compose up --build
```

默认入口：

- Web 工作台：`http://localhost:8080`
- API 文档：`http://localhost:8000/docs`
- 存活检查：`http://localhost:8000/health`
- 就绪检查：`http://localhost:8000/ready`

API 容器启动时先执行 `alembic upgrade head`，然后启动 Uvicorn。首次启动会创建 `workspaces` 表。

## 本地开发

API：

```powershell
docker compose up -d postgres qdrant redis
Set-Location apps/api
python -m pip install -r requirements-dev.txt
alembic upgrade head
uvicorn learn_platform_api.main:app --reload
```

Web：

```powershell
Set-Location apps/web
npm install
npm run dev
```

Vite 将 `/api`、`/health` 和 `/ready` 代理到 `http://localhost:8000`。

## 验证

```powershell
Set-Location apps/api
uv run --no-project --with-requirements requirements-dev.txt python -m pytest tests -q
Set-Location ../..
Set-Location apps/web
npm.cmd run lint
npm.cmd run build
Set-Location ../..
docker compose config
docker compose ps
```

业务 smoke：在 Web 创建一个 workspace，刷新页面后确认仍在列表中。

## 停止与数据

```powershell
docker compose down
```

该命令保留 Postgres、Qdrant 和 Redis named volume。只有明确需要清空本地平台数据时才使用 `docker compose down -v`。仓库内 `storage/` 是运行时文件根，内容默认不进入 Git。

## 故障定位

- `/health` 成功而 `/ready` 为 `degraded`：API 进程正常，但至少一个依赖不可用；查看 `checks` 中的脱敏状态。
- Web 无法读取 API：检查 `api` 容器状态及 Nginx `/api` proxy，确认端口未冲突。
- migration 失败：检查 Postgres health、`DATABASE_URL` 和现有 schema；不要通过删除 migration 绕过问题。
- 端口冲突：在 `.env` 中修改 `API_PORT`、`WEB_PORT`、`POSTGRES_PORT`、`QDRANT_PORT` 或 `REDIS_PORT`。
