"""Deterministic, non-sensitive metric functions for the Stage 3 eval.

Every function here is pure and operates on plain Python data (lists / dicts),
never on ORM rows, prompts, answers, evidence text, source content or paths.
Returned numbers feed the observational section of the report only; none of them
carry a universal threshold in Slice 3 (see Spec 005 / ADR 007).
"""

from __future__ import annotations

from typing import Iterable


def outline_section_coverage(sections: list[dict]) -> float:
    """Fraction of outline sections that carry at least one citation."""
    if not sections:
        return 0.0
    cited = sum(1 for section in sections if section.get("citation_ids"))
    return cited / len(sections)


def block_citation_coverage(blocks: Iterable[dict]) -> float:
    """Fraction of content blocks that carry at least one citation."""
    block_list = list(blocks)
    if not block_list:
        return 0.0
    cited = sum(1 for block in block_list if block.get("citation_ids"))
    return cited / len(block_list)


def evidence_duplication_ratio(texts: Iterable[str]) -> float:
    """Fraction of evidence entries that duplicate an earlier entry.

    0.0 means all evidence is distinct; higher means more repetition. Computed on
    exact text equality only (a deliberately coarse, content-free signal).
    """
    text_list = list(texts)
    if not text_list:
        return 0.0
    seen: set[str] = set()
    duplicates = 0
    for value in text_list:
        if value in seen:
            duplicates += 1
        else:
            seen.add(value)
    return duplicates / len(text_list)


def empty_human_rubric() -> dict[str, None]:
    """Placeholder slots for human-scored teaching quality.

    Slice 3 never fills these with an LLM judge; a human reviewer records a
    rubric during baseline acceptance. They remain null in the generated report.
    """
    return {"clarity": None, "relevance": None, "completeness": None}


def usage_summary(
    *,
    input_tokens: int | None,
    output_tokens: int | None,
    step_count: int | None,
    tool_call_count: int | None,
) -> dict[str, int | None]:
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "step_count": step_count,
        "tool_call_count": tool_call_count,
    }


def latency_summary(latencies_ms: Iterable[int | None]) -> dict[str, int | None]:
    values = [value for value in latencies_ms if value is not None]
    if not values:
        return {"total_ms": None, "max_ms": None}
    return {"total_ms": sum(values), "max_ms": max(values)}
