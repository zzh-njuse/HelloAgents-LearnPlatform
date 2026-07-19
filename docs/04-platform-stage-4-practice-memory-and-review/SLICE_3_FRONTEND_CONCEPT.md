# Stage 4 Slice 3 Tutor 教学 Skill 前端概念

状态：已接受（2026-07-18 人工 Gate）

日期：2026-07-18

## 1. 目标

不新增独立页面。教学 Skill 继续位于 Course Reader 右侧 Tutor 面板。所有新 Tutor Turn 自动使用当前已发布的诊断式教学 Skill；用户无需在“辅导”和“普通问答”之间做无意义选择，但能够看见当前方法和历史 Turn 实际采用的 Skill/version。

## 2. 信息架构

Tutor 面板自上而下保持：

1. 标题、固定课程版本、provider/model 与 Memory 管理入口。
2. Session 选择。
3. 当前课节/整门课程 scope 与课节选择。
4. 一行紧凑状态：`教学方法：诊断式支架 v1`，并说明是否有可用的个性化学习状态。
5. 当前 scope 的历史 Turn；Slice 3 新回答显示 `诊断式支架 v1`，升级后继续显示各自实际版本。Slice 3 前的历史回答可显示 `基础 Tutor（历史）`。
6. 问题输入、发送、运行/取消/重试状态。

不显示 Skill prompt、内部 intent enum、Memory ID、evidence ID 或模型思考。

## 3. 概念图

```text
┌ Tutor：课程问答 ─────────────────────┐
│ 课程版本 2       provider / model    │
│ Session [2026/07/18 16:20        ▾]  │
│ [当前课节] [整门课程]  [课节选择 ▾]  │
│ 教学方法：诊断式支架 v1              │
│ 已授权学习状态 3 条；课节完成 2 条   │
├──────────────────────────────────────┤
│ 你：我接下来该学什么？               │
│ 诊断式支架 v1                        │
│ 先学习……，因为……                    │
│ 依据：[1]                            │
│ 下一步：回看……并完成一次……          │
├──────────────────────────────────────┤
│ [输入问题……                       ]  │
│                              [发送]  │
└──────────────────────────────────────┘
```

## 4. 交互合同

- 所有 Slice 3 新 Turn 由服务端自动固定当前发布的 Skill ID/version/hash；客户端不能请求普通模式、任意 Skill 或任意版本。
- retry 必须沿用原 Turn 的 Skill ID/version/hash、scope 和 history boundary，不静默升级到新版本。
- Skill 新版本部署后，只影响之后新建的 Turn；旧回答继续显示原版本。
- Memory 未授权或当前范围没有可用学习状态时，诊断式辅导仍可基于课程证据工作，但状态行明确显示“本次没有可用的个性化学习状态”。
- 资料不足、Skill 不可用、预算耗尽和 provider 失败沿用 Turn 错误区域与重试动作，不自动回退为旧基础 Tutor。
- Slice 3 前的历史 Turn 与新 Skill Turn 可以出现在同一 Session；历史筛选仍只按现有 course/lesson scope。

## 5. 状态矩阵

| 状态 | Skill 状态 | 历史 | 输入与动作 |
|---|---|---|---|
| 无 Session | 显示当前发布版本 | 空态 | 首次发送沿用现有外部处理确认 |
| idle | 显示当前发布版本 | 显示每 Turn 实际版本 | 可发送 |
| queued/running | 显示本 Turn 固定版本 | 保留并显示运行身份 | 取消可用 |
| succeeded | 显示本 Turn 固定版本 | 显示 Skill/version 与引用 | 可继续提问 |
| failed/canceled | retry 使用原版本 | 显示稳定错误 | 重试或发起新 Turn |
| Memory disabled | Skill 仍工作 | 不显示伪个性化结论 | 状态说明不使用学习记忆 |
| Skill unavailable | 明确不可用，不静默降级 | 失败 Turn 可见 | 配置修复后重试 |
| 旧 Skill version | 新 Turn 不再选择旧版 | 历史继续显示旧版 | 只读/原版本 retry |

## 6. 响应式

- 桌面端维持现有三栏 Reader；Skill 状态使用一行紧凑元信息，不扩大右栏最低宽度。
- 窄视口沿用 Tutor 位于正文后的布局，不增加新的操作行。
- 长 Skill 名称在 UI 使用短标签，完整名称/version 通过回答元信息和 tooltip 提供。
- 切换正文/练习/Tutor 或 scope 时不得重建整个 Tutor 面板，避免丢失输入草稿与滚动。

## 7. 人工 UI Gate

1. 当前教学方法在提问前清楚可见，但不增加一次选择操作。
2. 用户不需要理解 framework SkillTool，也不会遇到“普通问答/诊断式辅导”的重复选择。
3. Turn 运行中、成功、失败和 retry 均显示正确 Skill/version；历史基础 Tutor 标识清楚。
4. Memory 开关关闭、无 Memory、有多条 Memory 和只有 Completion 时，状态文案不误导。
5. Chrome 桌面、窄视口、长问题、长回答和混合历史下无重叠、跳动或草稿丢失。
