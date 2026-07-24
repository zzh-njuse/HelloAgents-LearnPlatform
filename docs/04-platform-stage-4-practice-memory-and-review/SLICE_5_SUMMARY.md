# Stage 4 Slice 5 完成总结

归档日期：2026-07-24

状态：完成

## 目标与结论

Slice 5 是计划外的稳定性修复切片，不增加新的 Practice capability。它针对真实
人工 smoke 中 Python、Java、C++ 与科学题生成成功率低、修复放大、预算口径
冲突和工具状态误投影等问题，完成了事实诊断、版本化合同、有限修复、确定性
评分边界、Web 纠正与运行时 capability 隔离。

Java/C++ 的低成功率不是单一 wrapper 缺陷，而是非 canonical provider 输出、
整组修复、预算消耗和环境工具链不稳定叠加。最终实现拒绝 Java package，
specialized repair 只修失败 Item，并以最小 DTO 保护 hidden tests、题面和引用
等不可变字段。

## 实际完成

- Practice Job/Set/Item 固定 artifact contract v2；历史 v1 Set 保持可读、可评分，
  未完成 v1 generation Job 稳定拒绝。
- generation 使用独立 `PRACTICE_GENERATION_MODEL`，与 Tutor、课程和评分模型
  解耦。
- Python/Java/C++ canonical validation、版本化 harness dispatcher 和稳定错误
  分类。
- structure、specialized、novelty repair 分流；specialized repair 使用最小 DTO，
  只替换允许变化的 reference 字段。
- provider call、attempt step、search 和 wall time 使用统一预算；最终 commit 前
  再次检查 owner、lease、scope、source 与 wall budget。
- scientific grading 在证据不足或未授权时正式 `ungradable`，不生成数值分数或
  学习投影；基础设施失败走可重试失败。
- 有界 CJK-aware near-duplicate 预防与修复，避免只在最终阶段反复拒绝。
- Web 修复 Wolfram `not_used` 投影、Tutor 无效放大、编程专注模式、试运行结果
  隔离、starter code 提交和 capability 状态刷新。
- execution/science capability probe 独立调度，慢远端科学探测不再拖垮本地代码
  capability。

## 验证

- Slice 4/5 focused 回归：`198 passed, 8 skipped`。
- OCR 收尾 focused：`16 passed`。
- Stage 4 offline eval：`35/35 hard gates passed`，3 个 observational cases
  已记录。
- Web lint：0 errors，3 个既有 exhaustive-deps warnings。
- Web production build：通过。
- `git diff --check`：通过。
- 六块 OCR 均完整结束，无 token budget 截断；High 与高置信 Medium 已关闭。
- 2026-07-24 人工浏览器 smoke 完成，用户确认当前主路径无遗留问题。

8 个 skip 是宿主 Java/C++ compiler matrix 的环境阻塞结果，不冒充三语言全绿。
隔离 Postgres migration 测试仍需要显式 `SLICE5_PG_TEST_URL`，本轮未用产品库
代替隔离环境。

## 暂缓风险

- 当前 Docker test image 不包含稳定 Java/C++ compiler Gate；后续 CI 应提供
  带固定编译器版本且禁止 matrix skip 的 test stage。
- 真实 provider、Judge0 与 Wolfram 的成本和外部可用性仍属于人工 Gate，
  自动化不承诺外部服务永久可用。
- Stage 4 过程复盘已记录 slice 偏大、系统测试进入过晚和 source-inspection
  测试偏多的问题；项目最终复盘时继续处理，不在本次归档中扩大重构。

## 下一阶段输入

后续 Stage 应把 Slice 控制得更小，并在实现早期建立一条跨 Web、API、worker、
数据库和外部 adapter 的代表性系统测试。Stage 4 历史任务包只作归档依据，不得
继续追加实现。
