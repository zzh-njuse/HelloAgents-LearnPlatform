"""研究模式 Agent — 多 Agent 协作完成论文调研

SearchAgent → FilterAgent → AnalyzeAgent → SynthesizeAgent
         ↑ Orchestrator (PlanSolveAgent + TaskTool) ↑
"""

from academic_companion.agents.research.search_agent import SearchAgent
from academic_companion.agents.research.filter_agent import FilterAgent
from academic_companion.agents.research.analyze_agent import AnalyzeAgent
from academic_companion.agents.research.synthesize_agent import SynthesizeAgent
from academic_companion.agents.research.orchestrator import ResearchOrchestrator

__all__ = [
    "SearchAgent",
    "FilterAgent",
    "AnalyzeAgent",
    "SynthesizeAgent",
    "ResearchOrchestrator",
]
