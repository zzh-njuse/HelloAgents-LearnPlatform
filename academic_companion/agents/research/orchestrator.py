"""ResearchOrchestrator — 学术研究协调员

Plan: 使用 PlanSolveAgent 的 Planner 生成研究计划。
Execute: 用自己的 TaskTool 将每步委派给子 Agent，不再用框架 Executor。

流程:
  Plan → Step 1: Task("search") → Step 2: Task("filter") → Step 3: Task("analyze") → Step 4: Task("synthesize")
"""

import os
from typing import Optional, Dict, Any
from datetime import datetime

from hello_agents.agents.plan_solve_agent import PlanSolveAgent
from hello_agents.core.llm import HelloAgentsLLM
from hello_agents.core.config import Config
from hello_agents.core.agent import Agent
from hello_agents.tools.registry import ToolRegistry
from hello_agents.tools.builtin.task_tool import TaskTool
from hello_agents.tools.tool_filter import CustomFilter

# 研究子 Agent 权限:
# - 搜索/筛选/分析: 可调 MCP + RAG + Skill + 只读文件，禁止写文件和 Bash
# - 合成: 全权限（需 WriteTool 保存报告）
RESEARCH_READONLY = CustomFilter(
    mode="whitelist",
    allowed=[
        "ArxivSearch", "SemanticScholar", "RAGRetrieval",
        "Skill", "SkillTool",
        "Read", "ReadTool", "Glob", "Grep",
        "Thought", "Finish",
    ],
)
RESEARCH_FULL = CustomFilter(
    mode="blacklist",
    denied=["Bash", "BashTool", "Terminal", "TerminalTool", "Execute", "ExecuteTool"],
)

from academic_companion.config import get_config, AcademicConfig
from academic_companion.memory_extensions.research_notes import ResearchNotes


ORCHESTRATOR_SYSTEM_PROMPT = """你是一个学术研究协调员。收到研究主题后，请生成一份研究计划。
每一步必须以 [搜索]/[筛选]/[分析]/[综述] 其中之一开头。

标签含义:
- [搜索] 在学术数据库中检索论文
- [筛选] 根据标准精选论文
- [分析] 深度阅读和分析论文
- [综述] 汇总结果生成报告

示例:
  [搜索] 用关键词 XXX 在 arXiv 和 Semantic Scholar 搜索最新论文
  [筛选] 从结果中选 3 篇最相关的高引论文
  [分析] 深度分析第1篇论文的方法、实验和贡献
  [综述] 生成对比报告和 BibTeX

{research_summary}

当前时间: {current_time}
"""


def _research_agent_factory(
    agent_type: str,
    llm: HelloAgentsLLM,
    research_notes: ResearchNotes,
    academic_config: AcademicConfig,
) -> Optional[Agent]:
    """为 TaskTool 创建子 Agent 的工厂函数"""
    sub_name = f"subagent-{agent_type}"

    if agent_type == "search":
        from academic_companion.agents.research.search_agent import SearchAgent
        return SearchAgent(
            name=sub_name, llm=llm, config=academic_config,
            research_notes=research_notes,
            max_steps=academic_config.research.subagent_max_steps,
        )
    elif agent_type == "filter":
        from academic_companion.agents.research.filter_agent import FilterAgent
        return FilterAgent(
            name=sub_name, llm=llm, config=academic_config,
            max_steps=academic_config.research.subagent_max_steps,
        )
    elif agent_type == "analyze":
        from academic_companion.agents.research.analyze_agent import AnalyzeAgent
        return AnalyzeAgent(
            name=sub_name, llm=llm, config=academic_config, max_iterations=2,
        )
    elif agent_type == "synthesize":
        from academic_companion.agents.research.synthesize_agent import SynthesizeAgent
        return SynthesizeAgent(
            name=sub_name, llm=llm, config=academic_config,
        )
    return None


def _step_to_agent_type(step_text: str) -> str:
    """根据步骤文本确定子 Agent 类型。

    1. 优先解析 [...] 标签
    2. 否则按优先级做关键词包含匹配:
       synthesize > filter > analyze > search
    """
    import re

    # 1. [标签] 格式
    m = re.match(r'\[(搜索|筛选|分析|综述|search|filter|analyze|synthesize)\]', step_text)
    if m:
        tag = m.group(1)
        return {
            "搜索": "search", "search": "search",
            "筛选": "filter", "filter": "filter",
            "分析": "analyze", "analyze": "analyze",
            "综述": "synthesize", "synthesize": "synthesize",
        }.get(tag, "search")

    # 2. 关键词匹配 — 去掉数字前缀后，按优先级从高到低判断
    text = re.sub(r'^\d+[\.\)、]\s*', '', step_text)

    # synthesize: 汇总/综述/整理/总结/报告/对比表/BibTeX (最明确, 最高优先)
    if any(kw in text for kw in ["汇总", "综述", "对比", "BibTeX", "输出报告", "导出"]):
        return "synthesize"

    # analyze: 分析/精读/深入/评估/阅读 (在 filter 之前: "对筛选出的论文精读" → analyze)
    if any(kw in text for kw in ["分析", "精读", "深入", "评估", "剖析", "阅读", "提取", "理解"]):
        return "analyze"

    # filter: 筛选/精选/评分
    if any(kw in text for kw in ["筛选", "精选", "评分", "挑出", "选取"]):
        return "filter"

    # synthesize (更弱的关键词, 在 analyze/filter 之后判断)
    if any(kw in text for kw in ["整理", "总结", "报告", "输出", "导出", "生成"]):
        return "synthesize"

    # search: 搜索/检索/查找
    if any(kw in text for kw in ["搜索", "检索", "查找", "search", "关键词", "数据库"]):
        return "search"

    # 默认: 根据步骤在 plan 中的位置推断（不在此处处理，调用方处理）
    return "search"


class ResearchOrchestrator(PlanSolveAgent):
    """学术研究协调员

    Plan: 复用 PlanSolveAgent.Planner
    Execute: 用自己的 TaskTool 委派子 Agent（不用框架 Executor）
    """

    def __init__(
        self, name: str, llm: HelloAgentsLLM,
        config: Optional[AcademicConfig] = None,
    ):
        self.academic_config = config or get_config()
        self.research_notes = ResearchNotes(
            self.academic_config.research_notes.notes_file
        )
        self._llm = llm  # 保存引用，run() 中创建子 Agent 用

        tool_registry = ToolRegistry()

        def agent_factory(agent_type: str) -> Optional[Agent]:
            return _research_agent_factory(
                agent_type=agent_type, llm=self._llm,
                research_notes=self.research_notes,
                academic_config=self.academic_config,
            )

        self._agent_factory = agent_factory
        task_tool = TaskTool(
            agent_factory=agent_factory,
            tool_registry=tool_registry, config=Config(),
        )
        tool_registry.register_tool(task_tool)
        self._task_tool = task_tool

        system_prompt = ORCHESTRATOR_SYSTEM_PROMPT.format(
            research_summary=self.research_notes.get_summary(),
            current_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )

        framework_config = Config(
            skills_enabled=False, todowrite_enabled=False,
            devlog_enabled=False, subagent_enabled=False,
        )

        super().__init__(
            name=name, llm=llm, system_prompt=system_prompt,
            config=framework_config, tool_registry=tool_registry,
            enable_tool_calling=True, max_tool_iterations=3,
        )

    def run(self, input_text: str, **kwargs) -> str:
        """Plan → TaskTool 委派执行（不走框架 Executor）"""
        print(f"\n{'='*50}")
        print(f"  ResearchOrchestrator: {input_text[:80]}...")
        print(f"{'='*50}")

        # Phase 1: Plan
        plan = self.planner.plan(input_text, **kwargs)
        if not plan:
            return "无法生成研究计划，任务终止。"

        # Phase 2: Execute — 每步用 TaskTool 委派子 Agent
        step_results = []

        for i, step in enumerate(plan, 1):
            print(f"\n--- Step {i}/{len(plan)}: {step[:60]}... ---")

            agent_type = _step_to_agent_type(step)
            tool_filter = RESEARCH_FULL if agent_type == "synthesize" else RESEARCH_READONLY

            # 构建任务：带上前几步的结果作为上下文
            task = step
            if step_results:
                prev = "\n".join(
                    f"[Step {j}] {r[:500]}"
                    for j, r in enumerate(step_results, 1)
                )
                task = f"已有上下文:\n{prev}\n\n当前任务: {step}"

            try:
                sub = self._agent_factory(agent_type)
                if sub is None:
                    step_results.append(f"[{agent_type}] 无法创建子 Agent")
                    continue

                result = sub.run_as_subagent(
                    task=task,
                    tool_filter=tool_filter,
                    return_summary=True,
                    max_steps_override=self.academic_config.research.subagent_max_steps,
                )
                summary = result.get("summary", str(result))
                step_results.append(summary)
                print(f"  -> {agent_type} 完成 ({result.get('metadata', {}).get('steps', '?')} steps)")

            except Exception as e:
                step_results.append(f"[{agent_type}] 执行失败: {str(e)}")
                print(f"  -> 失败: {e}")

        # Phase 3: 汇总
        final = "\n\n".join(
            f"## Step {j+1} ({_step_to_agent_type(plan[j])})\n{r}"
            for j, r in enumerate(step_results)
        )
        return final

    async def arun(self, input_text: str, **kwargs) -> str:
        result = await super().arun(input_text, **kwargs)
        return result

    def get_research_status(self) -> str:
        return self.research_notes.get_summary()
