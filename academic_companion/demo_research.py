"""Phase 3 CLI Demo — 研究模式端到端验证

运行方式:
    python academic_companion/demo_research.py

前置条件:
    1. .env 已配置 LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_ID
    2. pip install arxiv-search-mcp-server semantic-scholar-mcp
    3. 可选: SEMANTIC_SCHOLAR_API_KEY 用于提升 rate limit

测试场景:
    1. MCP 工具独立测试 — ArxivSearch + SemanticScholar
    2. 论文搜索 — SearchAgent 搜索并返回结构化结果
    3. 去重验证 — ResearchNotes ID 去重
    4. 状态摘要 — 研究笔记统计
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from hello_agents.core.llm import HelloAgentsLLM
from academic_companion.mcp_extensions.arxiv_tool import ArxivSearchTool
from academic_companion.mcp_extensions.semantic_scholar_tool import SemanticScholarTool
from academic_companion.memory_extensions.research_notes import ResearchNotes, PaperEntry
from academic_companion.agents.research.search_agent import SearchAgent


def print_separator(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def main():
    print_separator("Academic AI Companion — 研究模式 Demo")
    print(f"LLM Model: {os.getenv('LLM_MODEL_ID', 'not set')}")

    # ============================================
    # 场景 1: MCP 工具独立测试
    # ============================================
    print_separator("场景 1: MCP 工具 — arXiv 搜索")

    arxiv_tool = ArxivSearchTool()
    s2_tool = SemanticScholarTool()

    mcp_ok = arxiv_tool._get_fastmcp_instance() is not None
    s2_ok = s2_tool._get_fastmcp_instance() is not None
    print(f"ArxivSearch MCP: {'OK' if mcp_ok else 'FAIL'}")
    print(f"SemanticScholar MCP: {'OK' if s2_ok else 'FAIL'}")

    if mcp_ok:
        result = arxiv_tool.run({"query": "LLM program repair", "max_results": 5})
        print(f"arXiv 搜索: {result.status.value} — 结果长度 {len(result.text)} chars")

    if s2_ok:
        result = s2_tool.run({"query": "LLM program repair", "max_results": 3})
        print(f"SemanticScholar 搜索: {result.status.value}")

    # ============================================
    # 场景 2: ResearchNotes 去重验证
    # ============================================
    print_separator("场景 2: ResearchNotes 去重验证")

    notes = ResearchNotes("memory/research/demo_notes.json")
    notes.reset()

    # 模拟添加一些论文
    e1 = PaperEntry(
        arxiv_id="2301.00001",
        title="Test Paper: LLM-based APR",
        authors=["Test Author"],
        year=2023,
        status="candidate",
        tags=["APR", "LLM"],
    )
    notes.add_entry(e1)

    # 模拟搜索结果中包含已有论文 + 新论文
    mock_results = [
        {"arxiv_id": "2301.00001", "title": "Test Paper: LLM-based APR"},  # 已有
        {"arxiv_id": "2301.00002", "title": "New Paper: Something Else"},  # 新
    ]
    new, seen = notes.dedup_candidates(mock_results)
    print(f"去重结果: 新论文 {len(new)} 篇, 已有记录 {len(seen)} 篇")
    if seen:
        print(f"  已有: {seen[0]['title']} (状态: {seen[0]['_previous_status']})")

    # 语义搜索测试 (Qdrant 不可用时降级)
    results = notes.search("LLM program repair")
    print(f"语义搜索 'LLM program repair': 命中 {len(results)} 条")

    print(notes.get_summary())
    notes.reset()

    # ============================================
    # 场景 3: SearchAgent (需要 LLM)
    # ============================================
    print_separator("场景 3: SearchAgent 论文搜索")

    if not os.getenv("LLM_API_KEY"):
        print("跳过 (未配置 LLM_API_KEY)")
    else:
        llm = HelloAgentsLLM()
        agent = SearchAgent("论文搜索", llm, research_notes=ResearchNotes())

        tools = agent.tool_registry.list_tools()
        print(f"已注册工具 ({len(tools)}): {', '.join(tools)}")

        result = agent.run(
            "搜索关于 LLM-based automated program repair 的最新论文 (2023-2026)，"
            "给我 5 篇最相关的"
        )
        print(f"\n回答:\n{result}")

    # ============================================
    # 场景 4: 多 Agent 编排 — ResearchOrchestrator
    # ============================================
    print_separator("场景 4: 多 Agent 编排 (Orchestrator)")

    if not os.getenv("LLM_API_KEY"):
        print("跳过 (未配置 LLM_API_KEY)")
    else:
        from academic_companion.agents.research.orchestrator import ResearchOrchestrator

        llm = HelloAgentsLLM()
        orchestrator = ResearchOrchestrator("研究协调员", llm)

        tools = orchestrator.tool_registry.list_tools()
        print(f"已注册工具 ({len(tools)}): {', '.join(tools)}")

        # 轻量任务: 搜索 + 筛选 + 分析 1 篇
        result = orchestrator.run(
            "调研关于 'LLM-based test case generation' 的论文。"
            "搜索 3 篇最新论文，筛选最相关的 2 篇，分析第 1 篇，"
            "然后生成一份简短的综述（包含方法对比和 BibTeX）。"
        )
        print(f"\n回答:\n{result}")
        print(f"\n研究笔记:\n{orchestrator.get_research_status()}")

    print_separator("Demo 完成")
    print("研究笔记: memory/research/")
    print("Trace 日志: memory/traces/")


if __name__ == "__main__":
    main()
