"""Report schema and writer for the Stage 4 practice eval.

Only safe, non-sensitive fields are ever emitted: schema/version metadata,
per-case status with a stable error category, and observational metric numbers.
It must never include prompts, question stems, options, user answers, correct
answers, rubric text, feedback, evidence, source text, file paths, provider
configuration or environment variables.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

REPORT_SCHEMA_VERSION = "1.0"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LatencyMetrics(_Strict):
    total_ms: int | None = Field(default=None, ge=0)
    max_ms: int | None = Field(default=None, ge=0)


class UsageMetrics(_Strict):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    provider_calls: int | None = Field(default=None, ge=0)
    latency: LatencyMetrics | None = None


class PracticeObservation(_Strict):
    items: int | None = Field(default=None, ge=0)
    single_choice_count: int | None = Field(default=None, ge=0)
    short_answer_count: int | None = Field(default=None, ge=0)
    citation_coverage: float | None = Field(default=None, ge=0, le=1)
    evidence_count: int | None = Field(default=None, ge=0)
    signal_count: int | None = Field(default=None, ge=0)
    negative_count: int | None = Field(default=None, ge=0)
    usage: UsageMetrics | None = None


class HumanRubric(_Strict):
    answerability: float | None = Field(default=None, ge=0, le=1)
    ambiguity: float | None = Field(default=None, ge=0, le=1)
    difficulty_match: float | None = Field(default=None, ge=0, le=1)
    distractor_quality: float | None = Field(default=None, ge=0, le=1)
    rubric_coverage: float | None = Field(default=None, ge=0, le=1)
    feedback_clarity: float | None = Field(default=None, ge=0, le=1)


class HardCaseResult(_Strict):
    id: str = Field(pattern=r"^[a-z0-9_]+$", max_length=100)
    role: Literal["exercise_author", "answer_grader", "practice", "cross"]
    gate: Literal["hard"]
    status: Literal["passed", "failed"]
    duration_ms: int = Field(ge=0)
    error_category: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$", max_length=100)


class ObservationalResult(_Strict):
    case_id: str = Field(pattern=r"^[a-z0-9_]+$", max_length=100)
    role: Literal["exercise_author", "answer_grader", "practice"]
    status: Literal["passed", "failed"]
    error_category: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$", max_length=100)
    duration_ms: int = Field(ge=0)
    metrics: PracticeObservation | None
    human_rubric: HumanRubric


class Totals(_Strict):
    hard_total: int = Field(ge=0)
    hard_passed: int = Field(ge=0)
    hard_failed: int = Field(ge=0)
    observational_total: int = Field(ge=0)
    status: Literal["passed", "failed"]


class EvalReport(_Strict):
    schema_version: Literal["1.0"]
    generated_at: str = Field(max_length=64)
    git_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    manifest_version: str = Field(pattern=r"^[A-Za-z0-9_.-]+$", max_length=100)
    manifest_schema_version: Literal["1.0"]
    mode: Literal["offline"]
    cases: list[HardCaseResult]
    observational: list[ObservationalResult]
    totals: Totals


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_git_revision(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo_root), capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip()


def build_report(*, manifest_version: str, manifest_schema_version: str, mode: str, case_results: list[dict], observational: list[dict], git_revision: str | None, generated_at: str) -> dict:
    hard = [entry for entry in case_results if entry.get("gate") == "hard"]
    hard_passed = [entry for entry in hard if entry.get("status") == "passed"]
    hard_failed = [entry for entry in hard if entry.get("status") != "passed"]
    data = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated_at,
        "git_revision": git_revision,
        "manifest_version": manifest_version,
        "manifest_schema_version": manifest_schema_version,
        "mode": mode,
        "cases": case_results,
        "observational": observational,
        "totals": {
            "hard_total": len(hard),
            "hard_passed": len(hard_passed),
            "hard_failed": len(hard_failed),
            "observational_total": len(observational),
            "status": "passed" if not hard_failed else "failed",
        },
    }
    return EvalReport.model_validate(data).model_dump(mode="json")


def write_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
