"""Deterministic, non-sensitive practice metric functions for the Stage 4 eval.

Pure functions over plain Python data. They never receive prompts, stems,
options, answers, rubrics, feedback or evidence text — only counts and citation
key sets. None carries a universal threshold in Slice 1.
"""

from __future__ import annotations

from typing import Iterable


def item_type_counts(items: list[dict]) -> dict[str, int]:
    single = sum(1 for item in items if item.get("item_type") == "single_choice")
    short = sum(1 for item in items if item.get("item_type") == "short_answer")
    return {"single_choice_count": single, "short_answer_count": short}


def citation_coverage(citation_key_sets: Iterable[set[str]]) -> float:
    """Fraction of items/blocks that carry at least one citation key."""
    sets = list(citation_key_sets)
    if not sets:
        return 0.0
    cited = sum(1 for keys in sets if keys)
    return cited / len(sets)


def empty_human_rubric() -> dict[str, None]:
    return {
        "answerability": None, "ambiguity": None, "difficulty_match": None,
        "distractor_quality": None, "rubric_coverage": None, "feedback_clarity": None,
    }


def usage_summary(*, input_tokens: int | None, output_tokens: int | None, provider_calls: int | None, latencies_ms: Iterable[int | None] | None = None) -> dict:
    values = [value for value in (latencies_ms or []) if value is not None]
    latency = {"total_ms": sum(values), "max_ms": max(values)} if values else {"total_ms": None, "max_ms": None}
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "provider_calls": provider_calls,
        "latency": latency,
    }
