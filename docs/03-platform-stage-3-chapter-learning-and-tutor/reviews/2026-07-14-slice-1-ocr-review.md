# Stage 3 Slice 1 分块 OCR Review

日期：2026-07-14
结论：完成分块独立审查；High 和高置信 Medium 已修复并复验，合同外或缺乏运行依据的建议已明确拒绝或暂缓。

## 背景与范围

本次审查覆盖 Slice 1 的课程事实、受控生成、worker、API、schema/migration、部署和 Web 主路径。真实 OCR 使用已配置的 DeepSeek provider；用户已知情同意发送普通源码，`.env`、API key、上传资料、数据库内容、日志和运行数据均未纳入。

统一参数为 `--audience human --concurrency 1 --timeout 10`，不设置 token 上限。候选路径先执行 `ocr scan --preview --path ...`，真实扫描逐块串行运行。完整原始输出保存在 [raw/](raw/)；早期未归档但成功返回的 `docker-compose.yml`、`CoursePanel.tsx` 和首次 `course_generation.py` 结果在本记录中保留结论。一次 API 目录扫描和一次 `courses.py` 早期扫描超时，均未计为通过，且已确认无残留 OCR 进程。

成功扫描包括：

- `services/course_generation.py` 首审与一次修复后复审；复审单文件实际约 250.8K token、4 分 19 秒，作为 preview 未提供 token 估算时的单文件例外记录。
- `services/courses.py`、`course_workers.py`、`routers/courses.py`、`academic_companion/course_agents.py`。
- ORM models、迁移 `0010`/`0011`、Slice 1 focused tests。
- `docker-compose.yml` 与 `CoursePanel.tsx`。

## 采纳与修复

High / 高置信 Medium：

- worker 增加非预期异常收敛，避免 job 永久停留在 `running`；清除 lease，保存不含异常正文的内部错误状态，并补充取消提示和 heartbeat 清理时间。
- 生成执行增加 Course 与 job 的显式 workspace 归属校验。
- 课程、outline 和 lesson job 的幂等唯一约束竞争改为回滚后读取既有请求，避免并发唯一冲突直接变成 500。
- 发布和激活请求增加期望当前指针；服务在行锁内比较，指针变化返回 409，避免最后写入者静默覆盖。
- prompt 将课程元数据和 evidence 作为明确的非可信 JSON 数据传递，强化 system 边界；citation artifact 类型和持久化 lookup 增加防御校验。
- citation source 查询改为单次预载，修复 repair submit latency 统计，并缓存 chunk ID 去重集合。
- Reader 对缺失 active version、空 blocks/objectives 做受控处理。
- Web job polling 改为串行 `setTimeout`，避免请求重叠和旧响应覆盖；workspace 切换清理 source selection。
- 增加幂等 replay、workspace 隔离、期望指针冲突、Reader citation 与来源降级断言。

## 拒绝或暂缓

- **缺少认证/授权**：Slice 1 Spec 明确不包含多用户权限和公开分享；当前 self-host workspace ID 隔离仍按既有平台合同执行。不得借 OCR 扩大为认证系统，后续权限 Stage 需单独 Spec/ADR。
- **Reader 泄露 chunk/version/offset**：这些字段正是 Spec 9 和引用合同要求的定位数据，不是误暴露；Reader 不返回上传原文。
- **Course 硬删除**：实现为 lifecycle soft delete，同时取消或请求取消 generation job；OCR 将其识别为硬删除属于误报。
- **客户端 external processing ack 可绕过**：Spec 明确要求每次请求携带确认字段；它是当次披露确认，不是身份或持久法律同意记录。
- **课程列表分页、N+1 优化**：属于规模优化，不是当前最多 15 Section 的 Slice 1 正确性阻断；保留为后续性能输入。
- **所有 FK 使用级联删除**：与 Postgres 权威历史、来源删除不级联课程和软删除决策冲突，拒绝。
- **迁移 `0011` 清理既有重复值**：`0010` 与 `0011` 在同一未发布 Slice 中连续建立新表和约束，升级前不存在历史生产数据；干净升级和 0011 降级/再升级已验证。
- **timestamp server default、DocumentChunk UUID default、旧 ingestion idempotency scope**：不是 Slice 1 新合同，ORM 已负责时间戳，DocumentChunk ID 由现有 ingestion/index 合同签发；不混入无关 schema 改动。
- **失败 tool trace 独立提交**：当前失败 attempt 保留最小 `AgentRun`，artifact/tool 写入与 job 成功仍保持单事务。更细的失败 tool trace 需要重新设计跨事务审计边界，暂缓并记录为后续输入。
- **provider 调用内重试**：产品 orchestrator 已按 job attempt 重试，provider 内隐式重试会模糊成本和 attempt 事实，拒绝。

## 复验结果

- API focused tests：`47 passed`。
- 根 framework baseline `python -m pytest -q` 未完成：当前全局 Python 环境缺少 `tiktoken`，在 collection 阶段停止；同时缺少 `pytest-asyncio` marker 注册。这不是测试通过，需在完整 framework 开发环境中补跑。
- Web：`npm.cmd run lint` 通过；`tsc -b` 通过。
- Web production build：Docker build 通过；本机裸 Vite build 因 Windows 沙箱无法读取上级目录而失败，不冒充通过。
- Docker：API、worker、reconciler、Web 镜像构建通过；Compose 服务全部运行，API/Postgres/Redis healthy。
- Migration：主数据库为 `0011 (head)`；此前已完成干净升级以及 `0011 -> 0010 -> 0011`。
- Runtime：`/ready` 返回 `ready`，Web HTTP 200。
- `git diff --check` 通过。

## 人工 Gate 结果

应用内浏览器控制插件初始化仍报 `Cannot redefine property: process`，因此自动浏览器 smoke 无法执行。用户随后完成了人工浏览器验收，确认 workspace 上传、课程大纲、单课节生成、草稿查看、发布、激活和 Reader 主路径没有功能性问题。期间发现并修复 Nginx 上传 `HTTP 413`、任务状态位置不直观、草稿不可见以及课程区布局密度问题；Edge 的部分显示异常属于浏览器侧表现，后续人工检查优先使用 Chrome。真实 generation provider 的调用范围与成本未在本记录中单独留存，因此不将其冒充为可重复的自动化 provider smoke。
