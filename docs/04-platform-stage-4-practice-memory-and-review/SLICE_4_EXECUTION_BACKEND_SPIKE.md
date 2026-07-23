# Stage 4 Slice 4 执行后端兼容性 Spike

状态：完成，2026-07-19

## 调查范围

对两个成熟自托管多语言执行引擎进行兼容性评估，判断其能否在不突破 ADR 006 安全边界的前提下作为代码实验室后端。

## Judge0 CE

- **版本**：1.13.0（最新稳定）
- **许可证**：GPLv3
- **运行依赖**：Docker（每个 submission 创建独立容器）、Redis（内部队列）
- **privileged / cgroup**：官方 `docker-compose.yml` 中 worker 使用 `privileged: true` 以支持 cgroup 资源限制；部分社区配置可在非 privileged 模式运行但失去 CPU/内存硬限制
- **Windows Docker Desktop 可行性**：可行，但 privileged 模式在 Windows Docker Desktop 下行为与 Linux 不同，cgroup 隔离不完整
- **网络**：默认无公网出口；容器间通过 Docker 内部网络通信
- **持久化**：无持久化；结果通过 API 返回后不保留
- **支持语言**：60+，包括 Python 3、Java (OpenJDK)、C++ (GCC)
- **API 合同**：REST POST `/submissions`，支持 `source_code`、`language_id`、`stdin`、`cpu_time_limit`、`memory_limit`、`wall_time_limit`
- **结论**：功能完整，但 `privileged: true` 与 ADR 006 §2.6 "不在 Product API/worker 内直接执行用户代码" 和 "不把 Judge0/Piston 官方 privileged Compose 直接并入主栈" 冲突。真实后端集成需要独立隔离主机/VM 和单独安全 Gate。**首版保留 adapter + fake contract，真实 backend smoke 标为 blocker。**

## Piston (Code-Runner)

- **版本**：0.12.4（最新稳定）
- **许可证**：MIT
- **运行依赖**：无需 Docker；使用 nsjail 隔离（Linux 专用）
- **privileged / cgroup**：nsjail 需要 CLONE_NEWPID / CLONE_NEWNET / CLONE_NEWNS，通常需要 `CAP_SYS_ADMIN` 或 root；部分配置可使用 user namespaces 降低权限
- **Windows Docker Desktop 可行性**：不可行；nsjail 是 Linux 专用，Windows 下无法运行
- **网络**：nsjail 默认禁用网络
- **持久化**：无持久化
- **支持语言**：50+，包括 Python 3、Java、C++
- **API 合同**：REST POST `/execute`，支持 `language`、`source`、`stdin`、`compile_timeout`、`run_timeout`
- **结论**：比 Judge0 更轻量，但 nsjail 依赖 Linux 内核特性，Windows Docker Desktop 下不可行。同样不能直接并入主 Compose。

## 决策

1. **首版不将真实 Judge0 或 Piston 并入主 `docker-compose.yml`**，符合 ADR 006 §2.6 和任务包 §3 禁止事项。
2. **产品 MCP adapter 使用固定 `run_code` Tool 合同**，后端 URL 由管理员配置；缺失时 readiness 为 unavailable。
3. **自动化测试使用 fake HTTP execution backend**，覆盖三语言映射、编译/运行错误、超时、输出截断、断连和非法返回。
4. **真实后端集成是明确 blocker**：需要管理员在独立隔离主机/VM 上部署执行引擎，通过独立安全 Gate 验证后配置 adapter URL。产品不自动拉取或启动 privileged 服务。
5. **Compose 中提供 `mcp-execution` adapter 服务**，它只连接管理员配置的执行后端 URL；不发布宿主端口，不挂载产品 storage 或网络。

## 语言映射

| 产品语言 | Judge0 language_id | Piston language |
|---------|-------------------|-----------------|
| python  | 71 (Python 3)    | python3         |
| java    | 62 (Java 11)     | java            |
| cpp     | 54 (C++ GCC 9.2) | c++             |

映射表固定在 adapter 中，不接受客户端指定 language_id 或 runtime。
