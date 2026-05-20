"""PipelineContext — 研究流水线上下文组装器

不依赖 GSSC 的 Select（关键词检索），而是按步骤类型**选择性格式化**前序结果。
Orchestrator 掌握全部数据，不需要"搜索"——需要的是结构化展示。
"""

from typing import Dict, List, Any, Optional
from hello_agents.context.builder import count_tokens


# 各步骤输出 Schema（供 Agent system prompt 引用和 JSON 解析验证）
EXPECTED_SCHEMAS = {
    "search": {
        "papers": list,      # [{title, arxiv_id, authors, year, citations, abstract, url}]
        "search_queries": list,
        "total_found": int,
        "search_strategy": str,
    },
    "filter": {
        "selected": list,    # [{paper_title, arxiv_id, reason, priority}]
        "rejected": list,    # [{paper_title, arxiv_id, reason}]
        "selection_criteria": list,
        "notes": str,
    },
    "analyze": {
        "paper_title": str,
        "arxiv_id": str,
        "analysis": dict,    # {method, experiments, contributions, limitations, key_insight}
        "relevance_rating": int,
        "reproducibility": str,
        "novelty": str,
    },
    "synthesize": {
        "report_markdown": str,
        "comparison_table": str,
        "bibtex": list,
        "key_findings": list,
        "research_gaps": list,
    },
}


class PipelineContext:
    """研究流水线上下文组装器

    按当前步骤类型，从前序结构化结果中提取最相关的字段，
    格式化为 Markdown 表格/列表，注入子 Agent。
    """

    def __init__(self, max_tokens: int = 6000):
        self.max_tokens = max_tokens

    def build(
        self,
        step_index: int,
        step_type: str,
        plan: List[str],
        structured_results: Dict[str, dict],
    ) -> str:
        """为当前步骤组装上下文"""
        sections = [self._plan_section(plan, step_index)]

        if step_type == "search":
            pass  # 第一步，无前序结果

        elif step_type == "filter":
            sr = structured_results.get("search", {})
            if sr:
                sections.append(self._paper_table(sr))

        elif step_type == "analyze":
            sr = structured_results.get("search", {})
            fr = structured_results.get("filter", {})
            if fr:
                sections.append(self._selected_table(fr))
                sections.append(self._paper_detail(sr, fr))

        elif step_type == "synthesize":
            for sname, result in structured_results.items():
                sections.append(self._step_card(sname, result))

        return self._trim(sections)

    # ==================================================================
    # Section builders
    # ==================================================================

    def _plan_section(self, plan: List[str], current: int) -> str:
        lines = ["## 研究计划"]
        for i, step in enumerate(plan):
            mark = " ← 当前" if i == current else (" ✓" if i < current else "")
            lines.append(f"  Step {i+1}: {step}{mark}")
        lines.append(f"\n  进度: {current+1}/{len(plan)}")
        return "\n".join(lines)

    def _paper_table(self, search_result: dict) -> str:
        papers = search_result.get("papers", [])
        total = search_result.get("total_found", len(papers))

        if not papers:
            return "## 搜索结果\n(无论文数据)"

        lines = [
            f"## 搜索结果 (Step 1 — 搜索)",
            f"共 {total} 篇，以下 {len(papers)} 篇:",
            "",
            "| # | 标题 | 作者 | 年份 | 引用 |",
            "|---|------|------|------|------|",
        ]
        max_rows = 10
        for i, p in enumerate(papers[:max_rows], 1):
            lines.append(
                f"| {i} | {p.get('title','?')[:50]} | {p.get('authors','?')[:20]} "
                f"| {p.get('year','?')} | {p.get('citations','?')} |"
            )
        if len(papers) > max_rows:
            lines.append(f"| ... | (还有 {len(papers)-max_rows} 篇) | | | |")
        return "\n".join(lines)

    def _selected_table(self, filter_result: dict) -> str:
        selected = filter_result.get("selected", [])
        criteria = filter_result.get("selection_criteria", [])

        lines = ["## 筛选决策 (Step 2 — 筛选)"]
        if criteria:
            lines.append(f"标准: {', '.join(criteria)}")
        lines.extend(["", "| 优先级 | 标题 | 理由 |", "|--------|------|------|"])

        for s in selected[:5]:
            lines.append(
                f"| {s.get('priority','?')} | {s.get('paper_title','?')[:50]} "
                f"| {s.get('reason','?')[:80]} |"
            )
        return "\n".join(lines)

    def _paper_detail(self, search_result: dict, filter_result: dict) -> str:
        """只展示被选中的论文详情（摘要）"""
        selected_titles = {s.get("paper_title", "") for s in filter_result.get("selected", [])}
        papers = search_result.get("papers", [])

        lines = ["## 论文详情"]
        shown = 0
        for p in papers:
            if p.get("title", "") in selected_titles:
                shown += 1
                lines.append(
                    f"\n### {p.get('title','?')}\n"
                    f"- 作者: {p.get('authors','?')}, {p.get('year','?')}\n"
                    f"- arXiv: {p.get('arxiv_id','?')}  引用: {p.get('citations','?')}\n"
                    f"- 摘要: {p.get('abstract','(无)')[:400]}"
                )
                if shown >= 5:
                    break
        if shown == 0:
            lines.append("(未找到匹配的论文详情)")
        return "\n".join(lines)

    def _step_card(self, step_name: str, result: dict) -> str:
        """生成步骤摘要卡片"""
        if result.get("parse_failed"):
            return f"## {step_name} (原始输出)\n{result.get('raw','')[:500]}"

        cards = {
            "search": lambda r: (
                f"## Step: 搜索\n"
                f"查询: {', '.join(r.get('search_queries',['?']))}; "
                f"找到 {r.get('total_found','?')} 篇, 记录 {len(r.get('papers',[]))} 篇"
            ),
            "filter": lambda r: (
                f"## Step: 筛选\n"
                f"选定 {len(r.get('selected',[]))} 篇: "
                + ", ".join(s.get('paper_title','?')[:30] for s in r.get('selected',[])[:3])
            ),
            "analyze": lambda r: (
                f"## Step: 分析\n"
                f"论文: {r.get('paper_title','?')}\n"
                f"核心洞察: {r.get('analysis',{}).get('key_insight','(无)')[:200]}"
            ),
            "synthesize": lambda r: (
                f"## Step: 综述\n"
                f"核心发现: {'; '.join(r.get('key_findings',[])[:3])}"
            ),
        }
        fn = cards.get(step_name, lambda r: f"## {step_name}\n{r.get('raw','?')[:300]}")
        return fn(result)

    # ==================================================================
    # Token budget
    # ==================================================================

    def _trim(self, sections: List[str]) -> str:
        context = "\n\n".join(sections)
        tokens = count_tokens(context)
        if tokens <= self.max_tokens:
            return context
        # 按优先级裁剪：先缩论文详情，再缩表格，再缩 Plan
        # 简单实现：从后往前删 section
        while count_tokens("\n\n".join(sections)) > self.max_tokens and len(sections) > 1:
            sections.pop(-2)  # 保留 Plan (第一个) 和最后有用的
        return "\n\n".join(sections)
