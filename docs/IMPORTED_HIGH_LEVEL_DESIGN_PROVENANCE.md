# 高层设计文档导入说明

日期：2026-07-10

## 来源

以下文档从误用仓库的 `main@ddf9a20` 原样导入：

- `LEARNING_AGENT_BLUEPRINT.md`
- `SELF_HOST_DEVELOPMENT_ROADMAP.md`
- `DATABASE_AND_DEPLOYMENT_PLAN.md`
- `AGENT_COLLABORATION_PLAYBOOK.md`

源仓库路径：

```text
C:\Users\Admin\Desktop\HelloAgents-learn_version\HelloAgents-learn_version
```

正确目标仓库：

```text
C:\Users\Admin\Desktop\HelloAgents-LearnPlatform
```

## 使用方式

这些文件用于保留误用仓库已经形成的产品运作模式、self-host 方向、数据与部署原则、阶段路线及协作方法。

导入不表示其中关于“当前仓库状态”、代码路径、已完成功能、阶段编号或技术接口的描述已经在正确仓库中成立。后续分析必须同时读取正确仓库当前代码与 Git 基线，并把文档内容分为：

- 产品目标与运作原则；
- 可继续采用的架构决策；
- 需要依据正确仓库重新验证的事实描述；
- 与现有 `academic_companion`、API/Web、数据和 dirty 历史冲突的旧假设。

在新的基线分析和人工确认完成前，不应据此直接迁移阶段 1 骨架或开始阶段 2 实现。
