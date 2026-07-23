from __future__ import annotations

import pytest
from pydantic import ValidationError

from learn_platform_api.schemas.tutor import TutorTurnCreate
from learn_platform_api.services.practice_type_adaptation import (
    ItemType,
    LessonLearningProfile,
    SuitabilityStatus,
    determine_suitability,
)
from shared.mcp_execution_contract import OUTPUT_MAX_BYTES, RunCodeOutput


def test_execution_output_contract_rejects_oversized_fields() -> None:
    with pytest.raises(ValidationError):
        RunCodeOutput(
            status="completed",
            exit_code=0,
            compile_output="",
            stdout="x" * (OUTPUT_MAX_BYTES + 1),
            stderr="",
            duration_ms=1,
            runtime="python",
            stdout_truncated=False,
            stderr_truncated=False,
        )


def test_science_suitability_requires_an_objective_key() -> None:
    profile = LessonLearningProfile(
        objective_keys=[],
        evidence_keys=["e1"],
        has_math_objective=True,
        has_computable_evidence=True,
    )

    result = determine_suitability(profile, science_capability_ready=True)
    science = next(item for item in result if item.item_type == ItemType.SCIENTIFIC)

    assert science.status == SuitabilityStatus.UNSUPPORTED


@pytest.mark.parametrize("question", ["", "   ", "\t\r\n"])
def test_tutor_question_rejects_blank_input(question: str) -> None:
    with pytest.raises(ValidationError):
        TutorTurnCreate(question=question, scope="course")


def test_tutor_question_is_trimmed() -> None:
    payload = TutorTurnCreate(question="  explain this  ", scope="course")
    assert payload.question == "explain this"


def test_tutor_code_run_id_rejects_blank_input() -> None:
    with pytest.raises(ValidationError):
        TutorTurnCreate(question="explain", scope="course", code_run_id="  ")
