---
name: paper-reading
description: 三段式论文阅读法：快速浏览→批判性阅读→结构化总结，含论文笔记模板和文献管理技巧
---

# 三段式论文阅读法

## 第一遍：快速浏览（5-10 分钟）

### 目标
判断论文是否值得深入阅读。

### 阅读顺序
1. **标题 + 作者 + 发表年份/会议**
2. **Abstract** — 最重要，理解问题和贡献
3. **Introduction 最后一段** — 看贡献列表
4. **Conclusion** — 验证贡献是否达成
5. **图表扫读** — 看 Figures 和 Tables，获取直观感受

### 决策点
- ✅ 相关且有创新 → 进入第二遍
- ⚠️ 相关但可能不够深入 → 标记为"引用"，只读 Related Work
- ❌ 不相关或质量低 → 放弃

## 第二遍：批判性阅读（30-60 分钟）

### 目标
理解核心方法，能向同事复述论文做了什么。

### 阅读要点
1. **Problem Definition**: 作者到底在解决什么问题？问题定义是否清晰？
2. **Method**: 核心方法是什么？画一个流程图。
3. **Key Insight**: 这篇文章最关键的一个洞察是什么？
4. **Experiment**: 实验设置合理吗？baseline 选择是否公平？
5. **Limitations**: 作者坦诚的局限性有哪些？你发现的不合理的在哪？

### 批判性提问清单
- [ ] 问题是否重要？动机是否充分？
- [ ] 方法是否有理论支撑？
- [ ] 实验是否可复现？代码和数据是否开源？
- [ ] 对比的 baseline 是否是 SOTA？
- [ ] 结果提升是否显著（不只是统计显著，还要实际显著）？
- [ ] 泛化性：在其他数据集/场景下是否有效？

## 第三遍：结构化总结（15-30 分钟）

### 论文笔记模板
```yaml
title: ""
authors: ""
year: 2024
venue: ""  # CVPR/NeurIPS/ICML/ACL...
arxiv: ""

# 一句话总结
one_liner: ""

# 核心贡献 (2-3 条)
contributions:
  - ""
  - ""

# 方法
method:
  name: ""
  diagram: ""  # 方法流程图描述
  key_innovation: ""

# 实验结果
results:
  dataset: ""
  metric: ""
  sota_before: 0.0
  this_paper: 0.0
  improvement: ""

# 我的评价
my_take:
  rating: 3  # 1-5
  strengths: []
  weaknesses: []
  ideas_inspired: []  # 这篇论文启发了什么新想法

# 与我的研究的关系
relevance: "high"  # high/medium/low
citation_needed: true
```

## 文献管理技巧

1. **用 Zotero/Mendeley 管理 PDF**，自动提取元数据
2. **按项目建文件夹**，每个项目一个 collection
3. **阅读顺序**: Survey → 经典论文 → 最新 SOTA
4. **每周整理**: 每周日花 30 分钟回顾本周读的论文笔记
