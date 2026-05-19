"""SearchAgent — 学术论文搜索 Agent

基于 ReActAgent，注册 ArxivSearch + SemanticScholar 两个 MCP Tool，
负责根据用户需求搜索和初步整理论文列表。
"""

import os
from typing import Optional
from datetime import datetime

from hello_agents.agents.react_agent import ReActAgent
from hello_agents.core.llm import HelloAgentsLLM
from hello_agents.core.config import Config
from hello_agents.tools.registry import ToolRegistry

from academic_companion.config import get_config, AcademicConfig
from academic_companion.mcp_extensions.arxiv_tool import ArxivSearchTool
from academic_companion.mcp_extensions.semantic_scholar_tool import SemanticScholarTool
from academic_companion.memory_extensions.research_notes import ResearchNotes


SEARCH_SYSTEM_PROMPT = """你是一个学术论文搜索专家。你的任务是：

1. **制定搜索策略**: 根据用户需求拆分关键词、覆盖同义词
2. **双路搜索**: 使用 ArxivSearch (arXiv 预印本) + SemanticScholar (全领域含 IEEE/ACM)
3. **整理结果**: 合并去重，按以下结构化格式输出每篇论文:

```
[编号] 论文标题
  作者: ...
  年份: ... | 出处: ... (arXiv/会议/期刊)
  引用数: ... | arXiv ID: ... | DOI: ...
  摘要: (2-3 句)
```

## 工作原则
- 优先使用 ArxivSearch 获取最新预印本
- 用 SemanticScholar 补充引用数据和补充来源
- 控制总输出在 15 篇以内，优先返回最相关的
- 搜索策略要在输出开头简要说明

{research_summary}

当前时间: {current_time}
"""


class SearchAgent(ReActAgent):
    """论文搜索 Agent

    注册 ArxivSearchTool + SemanticScholarTool，
    将搜索结果整理为结构化论文列表。
    """

    def __init__(
        self,
        name: str,
        llm: HelloAgentsLLM,
        config: Optional[AcademicConfig] = None,
        research_notes: Optional[ResearchNotes] = None,
        max_steps: int = 6,
    ):
        self.academic_config = config or get_config()
        self.research_notes = research_notes or ResearchNotes()

        tool_registry = ToolRegistry()
        tool_registry.register_tool(ArxivSearchTool())
        tool_registry.register_tool(SemanticScholarTool())

        system_prompt = SEARCH_SYSTEM_PROMPT.format(
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
