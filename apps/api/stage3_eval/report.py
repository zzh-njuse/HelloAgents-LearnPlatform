"""Report schema and writer for the Stage 3 eval.

The report only ever contains safe, non-sensitive fields: schema/version
metadata, per-case status with a stable error category, and observational metric
numbers. It must never include prompts, questions, answers, drafts, evidence,
source text, file paths, provider configuration or environment variables. On
failure the report records only the case id and a stable error category; the
underlying exception detail is not retained in the artifact.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

REPORT_SCHEMA_VERSION = "1.0"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LatencyMetrics(_StrictModel):
    total_ms: int | None = Field(default=None, ge=0)
    max_ms: int | None = Field(default=None, ge=0)


class UsageMetrics(_StrictModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    step_count: int | None = Field(default=None, ge=0)
    tool_call_count: int | None = Field(default=None, ge=0)
    latency: LatencyMetrics | None = None


class ObservationMetrics(_StrictModel):
    outline_section_coverage: float | None = Field(default=None, ge=0, le=1)
    block_citation_coverage: float | None = Field(default=None, ge=0, le=1)
    evidence_duplication_ratio: float | None = Field(default=None, ge=0, le=1)
    usage: UsageMetrics | None = None


class HumanRubric(_StrictModel):
    clarity: float | None = Field(default=None, ge=0, le=1)
    relevance: float | None = Field(default=None, ge=0, le=1)
    completeness: float | None = Field(default=None, ge=0, le=1)


class HardCaseResult(_StrictModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$", max_length=100)
    role: Literal["course_architect", "lesson_writer", "tutor", "cross"]
    gate: Literal["hard"]
    status: Literal["passed", "failed"]
    duration_ms: int = Field(ge=0)
    error_category: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$", max_length=100)


class PairedTutorUsage(_StrictModel):
    """Provider-call / token usage for the baseline-vs-skill pair (offline).

    Token counts come from the fake provider; offline mode never reads real
    provider configuration. Field names deliberately avoid the report's
    forbidden-key set (no ``input_hash``/``query``/``text`` etc.).
    """

    baseline_provider_calls: int | None = Field(default=None, ge=0)
    skill_provider_calls: int | None = Field(default=None, ge=0)
    baseline_input_tokens: int | None = Field(default=None, ge=0)
    skill_input_tokens: int | None = Field(default=None, ge=0)
    baseline_output_tokens: int | None = Field(default=None, ge=0)
    skill_output_tokens: int | None = Field(default=None, ge=0)


class PairedTutorRubric(_StrictModel):
    """Teaching-quality rubric retained for later real-provider pairing.

    All dimensions are ``None`` under the offline fake provider — the offline
    run only proves the orchestration/contract, never teaching quality.
    """

    responsiveness: float | None = Field(default=None, ge=0, le=1)
    evidence_fidelity: float | None = Field(default=None, ge=0, le=1)
    calibration: float | None = Field(default=None, ge=0, le=1)
    synthesis: float | None = Field(default=None, ge=0, le=1)
    priority: float | None = Field(default=None, ge=0, le=1)
    actionability: float | None = Field(default=None, ge=0, le=1)
    explanation_depth: float | None = Field(default=None, ge=0, le=1)
    uncertainty: float | None = Field(default=None, ge=0, le=1)


class PairedTutorCase(_StrictModel):
    """One baseline-vs-skill paired observation on identical fixtures."""

    case_id: str = Field(pattern=r"^[a-z0-9_]+$", max_length=100)
    intent: str = Field(pattern=r"^[a-z0-9_]+$", max_length=60)
    baseline_status: Literal["succeeded", "failed"]
    skill_status: Literal["succeeded", "failed"]
    gates: dict[str, bool]
    usage: PairedTutorUsage | None = None
    human_rubric: PairedTutorRubric


class ObservationalResult(_StrictModel):
    case_id: str = Field(pattern=r"^[a-z0-9_]+$", max_length=100)
    role: Literal["course_architect", "lesson_writer", "tutor"]
    status: Literal["passed", "failed"]
    error_category: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$", max_length=100)
    duration_ms: int = Field(ge=0)
    metrics: ObservationMetrics | None
    human_rubric: HumanRubric


class Totals(_StrictModel):
    hard_total: int = Field(ge=0)
    hard_passed: int = Field(ge=0)
    hard_failed: int = Field(ge=0)
    observational_total: int = Field(ge=0)
    status: Literal["passed", "failed"]


class EvalReport(_StrictModel):
    schema_version: Literal["1.0"]
    generated_at: str = Field(max_length=64)
    git_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    manifest_version: str = Field(pattern=r"^[A-Za-z0-9_.-]+$", max_length=100)
    manifest_schema_version: Literal["1.0"]
    mode: Literal["offline"]
    cases: list[HardCaseResult]
    observational: list[ObservationalResult]
    paired_tutor: list[PairedTutorCase] = Field(default_factory=list)
    totals: Totals


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_git_revision(repo_root: Path) -> str | None:
    """Best-effort current commit hash. Returns None if git is unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip()


def build_report(
    *,
    manifest_version: str,
    manifest_schema_version: str,
    mode: str,
    case_results: list[dict],
    observational: list[dict],
    paired_tutor: list[dict] | None = None,
    git_revision: str | None,
    generated_at: str,
) -> dict:
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
        "paired_tutor": paired_tutor or [],
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
