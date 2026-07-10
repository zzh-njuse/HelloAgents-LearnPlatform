"""ResearchOrchestrator — 学术研究协调员

Plan: 使用 PlanSolveAgent 的 Planner 生成研究计划。
Execute: 用自己的 TaskTool 将每步委派给子 Agent，不再用框架 Executor。

流程:
  Plan → Step 1: Task("search") → Step 2: Task("filter") → Step 3: Task("analyze") → Step 4: Task("synthesize")
"""

import json
import os
from typing import Optional, Dict, Any
from datetime import datetime

from hello_agents.agents.plan_solve_agent import PlanSolveAgent
from hello_agents.core.llm import HelloAgentsLLM
from hello_agents.core.config import Config
from hello_agents.core.agent import Agent
from hello_agents.core.streaming import StreamEvent, StreamEventType
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
from .pipeline_context import PipelineContext


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
            research_notes=research_notes,
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
        self.pipe_ctx = PipelineContext(max_tokens=6000)

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
        # structured_results: {step_name: parsed_dict}
        structured_results: Dict[str, dict] = {}
        step_summaries: list = []  # 用于 Phase 3 展示

        for i, step in enumerate(plan, 1):
            print(f"\n--- Step {i}/{len(plan)}: {step[:60]}... ---")

            agent_type = _step_to_agent_type(step)
            tool_filter = RESEARCH_FULL if agent_type == "synthesize" else RESEARCH_READONLY

            # 用 PipelineContext 组装结构化上下文（替代旧版 [:500] 截断）
            context = self.pipe_ctx.build(
                step_index=i - 1,
                step_type=agent_type,
                plan=plan,
                structured_results=structured_results,
            )
            task = f"{context}\n\n---\n当前任务: {step}"

            try:
                sub = self._agent_factory(agent_type)
                if sub is None:
                    step_summaries.append(f"[{agent_type}] 无法创建子 Agent")
                    continue

                result = sub.run_as_subagent(
                    task=task,
                    tool_filter=tool_filter,
                    return_summary=False,
                    max_steps_override=self.academic_config.research.subagent_max_steps,
                )
                raw_output = result.get("result", str(result))

                # 提取结构化 JSON
                parsed = self._parse_structured_output(raw_output, agent_type)
                structured_results[agent_type] = parsed
                step_summaries.append(raw_output)

                if parsed.get("parse_failed"):
                    print(f"  -> {agent_type} 完成 (JSON 解析失败，降级为原始文本)")
                else:
                    print(f"  -> {agent_type} 完成 (结构化输出 OK)")

            except Exception as e:
                err_msg = f"[{agent_type}] 执行失败: {str(e)}"
                step_summaries.append(err_msg)
                structured_results[agent_type] = {"raw": err_msg, "parse_failed": True}
                print(f"  -> 失败: {e}")

        # Phase 3: 汇总
        final = "\n\n".join(
            f"## Step {j+1} ({_step_to_agent_type(plan[j])})\n{r}"
            for j, r in enumerate(step_summaries)
        )
        return final

    def _parse_structured_output(self, raw_text: str, agent_type: str) -> dict:
        """从 Agent 回复中提取结构化 JSON 块

        降级策略: JSON 解析失败 → {"raw": raw_text, "parse_failed": True}
        """
        import re
        # 找最后一个 ```json ... ``` 块
        json_blocks = list(re.finditer(r'```json\s*\n(.*?)```', raw_text, re.DOTALL))
        if json_blocks:
            try:
                return json.loads(json_blocks[-1].group(1))
            except json.JSONDecodeError:
                pass
        # 尝试找裸 JSON 块 (以 { 开头 } 结尾)
        try:
            start = raw_text.rindex('{')
            end = raw_text.rindex('}') + 1
            return json.loads(raw_text[start:end])
        except (ValueError, json.JSONDecodeError):
            pass
        return {"raw": raw_text, "parse_failed": True}

    def run_streaming(self, input_text: str):
        """流式执行研究 pipeline，逐步产出 StreamEvent

        供 FastAPI SSE 端点调用。每个步骤前后发射事件。
        """
        yield StreamEvent.create(
            StreamEventType.AGENT_START, self.name,
            input_text=input_text,
        )

        # Phase 1: Plan
        yield StreamEvent.create(
            StreamEventType.THINKING, self.name,
            content=f"正在规划研究路径：{input_text[:80]}...",
        )

        plan = self.planner.plan(input_text)
        if not plan:
            yield StreamEvent.create(
                StreamEventType.ERROR, self.name,
                error="无法生成研究计划",
            )
            yield StreamEvent.create(
                StreamEventType.AGENT_FINISH, self.name,
                result="任务终止：无法生成研究计划。",
            )
            return

        yield StreamEvent.create(
            StreamEventType.THINKING, self.name,
            content=f"研究计划共 {len(plan)} 步：{' → '.join(_step_to_agent_type(s) for s in plan)}",
        )

        # Phase 2: Execute pipeline
        structured_results: dict = {}
        step_summaries: list = []

        for i, step in enumerate(plan, 1):
            agent_type = _step_to_agent_type(step)
            tool_filter = RESEARCH_FULL if agent_type == "synthesize" else RESEARCH_READONLY

            yield StreamEvent.create(
                StreamEventType.STEP_START, self.name,
                step=i, step_type=agent_type, description=step,
            )

            context = self.pipe_ctx.build(
                step_index=i - 1,
                step_type=agent_type,
                plan=plan,
                structured_results=structured_results,
            )
            task = f"{context}\n\n---\n当前任务: {step}"

            try:
                sub = self._agent_factory(agent_type)
                if sub is None:
                    step_summaries.append(f"[{agent_type}] 无法创建子 Agent")
                    yield StreamEvent.create(
                        StreamEventType.STEP_FINISH, self.name,
                        step=i, step_type=agent_type, status="failed",
                        error="无法创建子 Agent",
                    )
                    continue

                result = sub.run_as_subagent(
                    task=task,
                    tool_filter=tool_filter,
                    return_summary=False,
                    max_steps_override=self.academic_config.research.subagent_max_steps,
                )
                raw_output = result.get("result", str(result))
                parsed = self._parse_structured_output(raw_output, agent_type)
                structured_results[agent_type] = parsed
                step_summaries.append(raw_output)

                yield StreamEvent.create(
                    StreamEventType.STEP_FINISH, self.name,
                    step=i, step_type=agent_type, status="completed",
                    json_ok=not parsed.get("parse_failed", False),
                    summary=raw_output[:500],
                )

            except Exception as e:
                err_msg = f"[{agent_type}] 执行失败: {str(e)}"
                step_summaries.append(err_msg)
                structured_results[agent_type] = {"raw": err_msg, "parse_failed": True}
                yield StreamEvent.create(
                    StreamEventType.STEP_FINISH, self.name,
                    step=i, step_type=agent_type, status="failed",
                    error=str(e),
                )

        # Phase 3: Final result
        final = "\n\n".join(
            f"## Step {j+1} ({_step_to_agent_type(plan[j])})\n{r}"
            for j, r in enumerate(step_summaries)
        )

        yield StreamEvent.create(
            StreamEventType.AGENT_FINISH, self.name,
            result=final, steps=len(plan),
        )

    async def arun(self, input_text: str, **kwargs) -> str:
        result = await super().arun(input_text, **kwargs)
        return result

    def get_research_status(self) -> str:
        return self.research_notes.get_summary()
