"""SynthesizeAgent — 学术综述撰写 Agent

基于 SimpleAgent，汇总多篇论文分析结果，
生成文献综述 + 方法对比表 + 研究空白分析 + BibTeX。
"""

import os
from typing import Optional

from hello_agents.agents.simple_agent import SimpleAgent
from hello_agents.core.llm import HelloAgentsLLM
from hello_agents.core.config import Config
from hello_agents.tools.registry import ToolRegistry
from hello_agents.tools.builtin.file_tools import WriteTool

from academic_companion.config import get_config, AcademicConfig


SYNTHESIZE_SYSTEM_PROMPT = """你是一个学术综述撰写专家。你会收到多篇论文的分析结果，汇总生成以下内容:

## 输出结构

### 1. 文献综述
按主题/方法分类，叙述当前研究脉络。

### 2. 方法对比表

| 论文 | 问题 | 方法 | 数据集 | 指标 | 优势 | 局限 |
|------|------|------|--------|------|------|------|
| ... | ... | ... | ... | ... | ... | ... |

### 3. 研究空白分析
- 当前方法的共性局限
- 未解决的问题
- 潜在的突破方向

### 4. 未来方向建议
- 短期可尝试的方向 (1-2年)
- 长期研究方向 (3-5年)

### 5. 参考文献 (BibTeX)
```bibtex
@article{...}
```

## 输出要求
- 综述部分 300-500 字
- 对比表覆盖所有分析过的论文
- BibTeX 格式规范 (可从 Semantic Scholar / arXiv 获取)
- 使用 Write 工具保存报告到 research_report.md
"""


class SynthesizeAgent(SimpleAgent):
    """学术综述撰写 Agent

    汇总论文分析结果，生成结构化调研报告并保存到文件。
    注册 WriteTool 用于文件输出。
    """

    def __init__(
        self,
        name: str,
        llm: HelloAgentsLLM,
        config: Optional[AcademicConfig] = None,
    ):
        self.academic_config = config or get_config()

        tool_registry = ToolRegistry()
        tool_registry.register_tool(WriteTool())

        framework_config = Config(
            skills_enabled=False,
            todowrite_enabled=False,
            devlog_enabled=False,
            subagent_enabled=False,
        )

        super().__init__(
            name=name,
            llm=llm,
            system_prompt=SYNTHESIZE_SYSTEM_PROMPT,
            config=framework_config,
            tool_registry=tool_registry,
            enable_tool_calling=True,
            max_tool_iterations=3,
        )
