"""AnalyzeAgent — 学术论文深度分析 Agent

基于 ReflectionAgent，使用三段式论文阅读法 (paper-reading Skill)
对单篇论文进行 浏览→批判性阅读→结构化总结 的深度分析。
"""

import os
from typing import Optional
from pathlib import Path
from datetime import datetime

from hello_agents.agents.reflection_agent import ReflectionAgent
from hello_agents.core.llm import HelloAgentsLLM
from hello_agents.core.config import Config
from hello_agents.tools.registry import ToolRegistry
from hello_agents.tools.builtin.skill_tool import SkillTool
from hello_agents.skills.loader import SkillLoader

from academic_companion.config import get_config, AcademicConfig
from academic_companion.mcp_extensions.arxiv_tool import ArxivSearchTool
from academic_companion.mcp_extensions.semantic_scholar_tool import SemanticScholarTool


ANALYZE_SYSTEM_PROMPT = """你是一个学术论文深度分析专家，使用 **三段式论文阅读法** 进行系统分析。

## 分析流程

### 第一遍: 快速浏览
- 标题/作者/年份/会议
- Abstract — 理解问题和贡献
- Introduction 最后一段 — 看贡献列表
- Conclusion — 验证贡献是否达成

### 第二遍: 批判性阅读
- **Problem Definition**: 解决什么问题？定义清晰吗？
- **Method**: 核心方法是什么？画出流程
- **Key Insight**: 最关键的一个洞察是什么？
- **Experiment**: 实验设置合理吗？baseline 公平吗？
- **Limitations**: 作者的局限性？你发现的还有哪些？

### 第三遍: 结构化总结
按以下模板输出分析卡片:

```yaml
title: ""
authors: ""
year: 2024
venue: ""

# 一句话总结
one_liner: ""

# 核心贡献 (2-3条)
contributions:
  - ""
  - ""

# 方法
method:
  name: ""
  key_innovation: ""

# 实验结果
results:
  dataset: ""
  metric: ""
  improvement: ""

# 我的评价
my_take:
  rating: 3  # 1-5
  strengths: []
  weaknesses: []
  ideas_inspired: []

# 与我的研究的关系
relevance: "high/medium/low"
```

## 批判性提问清单
- [ ] 问题重要吗？动机充分吗？
- [ ] 方法有理论支撑吗？
- [ ] 实验可复现吗？代码/数据开源吗？
- [ ] 对比的 baseline 是 SOTA 吗？
- [ ] 结果提升是否显著？
- [ ] 泛化性：其他场景下是否有效？

使用 paper-reading Skill 获取更详细的方法论指导。
必要时使用 ArxivSearch / SemanticScholar 查找论文全文或引用信息。

## 结构化输出要求
在完成分析后，你必须在回复末尾附加一个 JSON 块，以 `---` 分隔线开头:

```
---
```json
{{
  "paper_title": "论文标题",
  "arxiv_id": "2301.xxx",
  "analysis": {{
    "method": "核心方法的简要归纳",
    "experiments": "实验设置与主要结果",
    "contributions": "1-3条核心贡献",
    "limitations": "方法的局限性",
    "key_insight": "最重要的一个洞察"
  }},
  "relevance_rating": 8,
  "reproducibility": "中",
  "novelty": "方法创新/综述/应用创新"
}}
```
```

每个 analysis 字段 ≤500 字。
"""


class AnalyzeAgent(ReflectionAgent):
    """论文深度分析 Agent

    使用 ReflectionAgent 的反思循环提升分析质量:
    初始分析 → 反思质疑 → 改进分析 → 最终输出

    加载 paper-reading Skill。
    """

    def __init__(
        self,
        name: str,
        llm: HelloAgentsLLM,
        config: Optional[AcademicConfig] = None,
        max_iterations: int = 2,
    ):
        self.academic_config = config or get_config()

        tool_registry = ToolRegistry()
        tool_registry.register_tool(ArxivSearchTool())
        tool_registry.register_tool(SemanticScholarTool())

        framework_config = Config(
            skills_enabled=False,
            todowrite_enabled=False,
            devlog_enabled=False,
            subagent_enabled=False,
        )

        super().__init__(
            name=name,
            llm=llm,
            system_prompt=ANALYZE_SYSTEM_PROMPT,
            config=framework_config,
            max_iterations=max_iterations,
            tool_registry=tool_registry,
            enable_tool_calling=True,
            max_tool_iterations=3,
        )

        # 加载 paper-reading Skill (必须在 super().__init__ 之后)
        skills_path = Path(__file__).resolve().parents[2] / "skills"
        self.skill_loader = SkillLoader(skills_path)
        skill_tool = SkillTool(skill_loader=self.skill_loader)
        tool_registry.register_tool(skill_tool)
