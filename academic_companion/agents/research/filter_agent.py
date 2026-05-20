"""FilterAgent — 学术论文筛选评分 Agent

基于 ReActAgent，对论文列表进行四维评分，精选 Top 5-8 篇。
"""

import os
from typing import Optional
from datetime import datetime

from hello_agents.agents.react_agent import ReActAgent
from hello_agents.core.llm import HelloAgentsLLM
from hello_agents.core.config import Config
from hello_agents.tools.registry import ToolRegistry

from academic_companion.config import get_config, AcademicConfig
from academic_companion.rag_extensions.rag_tool import RAGRetrievalTool
from academic_companion.memory_extensions.research_notes import ResearchNotes


FILTER_SYSTEM_PROMPT = """你是一个学术论文筛选专家。你会收到一批候选论文，请对每篇进行四维评分和筛选。

## 评分维度 (每项 1-10)
1. **相关度**: 与用户需求的匹配程度
2. **新颖度**: 方法或思路是否有创新
3. **可靠性**: 实验是否扎实，结论是否可信
4. **可复现性**: 代码/数据是否开源

## 输出格式
对每篇论文给出评分和一句话入选理由，最终精选 Top 5-8 篇:

```
### 精选论文

[1] ★8.5 论文标题
   相关度:9 新颖度:8 可靠性:9 可复现性:8
   入选理由: (一句话)

[2] ★7.8 ...
...

### 未入选
- 论文X: 相关度不足，偏向XXX领域
- 论文Y: 方法陈旧，已被后续工作超越
```

## 评分标准
- 8-10: 必须深入阅读
- 6-7: 值得浏览
- 4-5: 备选
- 1-3: 不推荐

{research_summary}

## 结构化输出要求
在完成筛选后，你必须在回复末尾附加一个 JSON 块，以 `---` 分隔线开头:

```
---
```json
{{
  "selected": [
    {{
      "paper_title": "论文标题",
      "arxiv_id": "2301.xxx",
      "reason": "入选理由",
      "priority": 1
    }}
  ],
  "rejected": [
    {{
      "paper_title": "论文标题",
      "arxiv_id": "2310.xxx",
      "reason": "淘汰理由"
    }}
  ],
  "selection_criteria": ["引用数>50", "2023年以后"],
  "notes": "筛选说明"
}}
```
```

selected 最多 5 篇。

当前时间: {current_time}
"""


class FilterAgent(ReActAgent):
    """论文筛选 Agent

    对搜索结果进行四维评分，精选最值得深读的论文。
    可调用 RAGRetrieval 检查本地是否已有相关主题的知识。
    """

    def __init__(
        self,
        name: str,
        llm: HelloAgentsLLM,
        config: Optional[AcademicConfig] = None,
        research_notes: Optional[ResearchNotes] = None,
        max_steps: int = 5,
    ):
        self.academic_config = config or get_config()
        self.research_notes = research_notes or ResearchNotes()

        tool_registry = ToolRegistry()
        # 注册 RAG 检索工具 (检查本地知识库)
        tool_registry.register_tool(RAGRetrievalTool())

        system_prompt = FILTER_SYSTEM_PROMPT.format(
            research_summary=self.research_notes.get_summary(),
            current_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )

        framework_config = Config(
            skills_enabled=False,
            todowrite_enabled=False,
            devlog_enabled=False,
            subagent_enabled=False,
        )

        super().__init__(
            name=name,
            llm=llm,
            tool_registry=tool_registry,
            system_prompt=system_prompt,
            config=framework_config,
            max_steps=max_steps,
        )
