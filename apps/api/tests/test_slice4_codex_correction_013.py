from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from academic_companion.practice_agents import (
    PracticeAuthorRequest,
    PracticeGraderRequest,
    PracticeItemArtifact,
    PracticeRubricCriterion,
    ScientificAnswerSpec,
    build_grading_prompt,
    build_practice_repair_prompt,
)
from learn_platform_api.schemas.practice import PracticeSetCreate
from learn_platform_api.services.formula_validator import validate_formula_content
from learn_platform_api.services.practice_generation import (
    _build_coding_harness,
    _build_lesson_learning_profile,
    _build_coding_feedback_prompt,
    _validate_practice_novelty,
    execute_coding_grading,
)
from learn_platform_api.services import course_generation
from academic_companion.course_agents import (
    CourseAgentRequest,
    build_generation_prompt,
    build_lesson_coverage_prompt,
    build_search_prompt,
)
from learn_platform_api.services.science_tool_service import (
    normalize_science_arguments,
    parse_science_text_content,
)
from learn_platform_api.practice_workers import ERROR_MESSAGES as PRACTICE_ERROR_MESSAGES
from learn_platform_api.practice_workers import RETRYABLE_CODES
from learn_platform_api.settings import Settings


def test_wolfram_legacy_input_alias_normalizes_to_query() -> None:
    assert normalize_science_arguments("WolframAlpha", {"input": "1+1"}) == {"query": "1+1"}
    assert normalize_science_arguments("WolframContext", {"query": "x"}) == {"query": "x"}


def test_wolfram_text_error_is_not_accepted_as_observation() -> None:
    assert parse_science_text_content('[Error] Missing required parameter "query"') == {
        "error": "tool_call_error"
    }
    assert parse_science_text_content("2") == {"value": 2}
    assert parse_science_text_content("plain result") == {"text": "plain result"}


def test_practice_type_rejection_has_actionable_public_message() -> None:
    assert "编程题" in PRACTICE_ERROR_MESSAGES["coding_item_not_supported_by_lesson"]
    assert "自动选择或普通题" in PRACTICE_ERROR_MESSAGES["coding_item_not_supported_by_lesson"]
    assert "科学计算题" in PRACTICE_ERROR_MESSAGES["science_item_not_supported_by_lesson"]


def test_integrated_practice_uses_unified_step_budget() -> None:
    """Slice 5 (Spec 005 §7.2 / ADR 007 §3.6) collapses the old dual denomination
    (eval 6-step vs runtime 20-step) and the dead per-item ref-call setting into
    one authoritative budget: 4 provider calls, 3 searches, 12 attempt steps."""
    settings = Settings()
    assert settings.practice_generation_max_provider_calls == 4
    assert settings.practice_generation_max_searches == 3
    assert settings.practice_generation_max_attempt_steps == 12
    assert not hasattr(settings, "practice_generation_max_steps")
    assert not hasattr(settings, "practice_coding_max_ref_calls")


def test_invalid_artifact_is_not_retried_with_the_same_inputs() -> None:
    assert "invalid_practice_artifact" not in RETRYABLE_CODES


def test_coding_feedback_receives_acknowledged_source_without_hidden_tests() -> None:
    prompt = _build_coding_feedback_prompt(
        stem="Implement solve",
        source_code="def solve(input_text): return input_text",
        score=50,
        verdict="partially_correct",
        execution_summary={"tests_passed": 2, "tests_total": 4, "error_categories": []},
        evidence=[],
        output_language="en",
    )
    rendered = str(prompt)
    assert "def solve(input_text)" in rendered
    assert "hidden_tests" not in rendered
    assert "reference_solution" not in rendered


def test_practice_repair_prompt_preserves_science_contract() -> None:
    request = PracticeAuthorRequest(
        lesson_title="Thermochemistry",
        lesson_objective="Calculate enthalpy",
        learning_objectives=("Use standard enthalpies",),
        item_count=3,
        allowed_item_types=("single_choice", "short_answer", "scientific"),
    )
    rendered = str(build_practice_repair_prompt(request, [{"citation_id": "e1", "text": "evidence"}], {}, ["items.0: missing"]))
    assert "requires_general_item" in rendered
    assert "scientific_answer_spec" in rendered
    assert "objective_1" in rendered


def test_coding_grading_runs_public_and_hidden_cases_without_exposing_inputs(monkeypatch) -> None:
    from learn_platform_api.services import practice_generation

    monkeypatch.setattr(
        practice_generation,
        "execute_code_run_sync",
        lambda **_kwargs: (SimpleNamespace(status="completed", stdout='{"passed":2,"passed_weight":2,"total_weight":3,"errors":["mismatch"],"results":[true,false,true]}'), None),
    )
    result = execute_coding_grading(
        "def solve(input_text): return input_text",
        {
            "language": "python",
            "public_tests": [{"input": "public", "expected_output": "public", "weight": 1, "is_public": True}],
            "hidden_tests": [
                {"input": "secret-a", "expected_output": "x", "weight": 1, "is_public": False},
                {"input": "secret-b", "expected_output": "secret-b", "weight": 1, "is_public": False},
            ],
        },
        Settings(),
    )
    assert result.score == 67
    assert result.execution_summary["tests_total"] == 3
    assert result.execution_summary["public_cases"] == [{"test_index": 0, "passed": True}]
    assert "secret-a" not in str(result.execution_summary)


def test_course_outline_does_not_fail_when_one_search_has_no_evidence(monkeypatch) -> None:
    monkeypatch.setattr(course_generation, "snapshot_rows", lambda *_args: [(None, SimpleNamespace(id="doc-1"), None)])
    monkeypatch.setattr(course_generation, "retrieve", lambda *_args, **_kwargs: ("trace", []))
    evidence, chunks = course_generation.evidence_search(
        SimpleNamespace(),
        SimpleNamespace(product_generation_max_evidence_tokens=1000),
        SimpleNamespace(workspace_id="workspace-1"),
        "one narrow query",
    )
    assert evidence == []
    assert chunks == {}


def test_course_search_plan_receives_only_safe_source_name_hints() -> None:
    messages = build_search_prompt(
        "course_architect",
        CourseAgentRequest(
            title="算法学习",
            goal="学习基础算法",
            source_names=("01_sorting_algorithms.pdf", "02_dijkstra_shortest_path.pdf"),
        ),
    )
    rendered = "\n".join(message["content"] for message in messages)
    assert "01_sorting_algorithms.pdf" in rendered
    assert "02_dijkstra_shortest_path.pdf" in rendered
    assert "topic and terminology hints" in rendered


def test_outline_and_lesson_plans_prefer_fewer_supported_units() -> None:
    request = CourseAgentRequest(
        title="算法学习",
        goal="学习基础算法",
        lesson_title="排序算法",
        lesson_objective="解释 sorting algorithms",
        source_names=("01_sorting_algorithms.pdf",),
    )
    outline = "\n".join(
        item["content"] for item in build_generation_prompt(
            "course_architect", request, [{"citation_id": "e1", "text": "Sorting evidence"}]
        )
    )
    coverage = "\n".join(item["content"] for item in build_lesson_coverage_prompt(request, 4))
    assert "Prefer fewer, broader lessons over thin lessons" in outline
    assert "give every lesson its own relevant citation IDs" in outline
    assert "01_sorting_algorithms.pdf" in coverage
    assert "prefer fewer supported units" in coverage


def test_migration_0022_allows_integrated_practice_item_types() -> None:
    from pathlib import Path

    migration = Path("alembic/versions/0022_expand_practice_item_types.py").read_text(encoding="utf-8")
    assert "'single_choice', 'short_answer', 'coding', 'scientific'" in migration
    assert 'down_revision = "0021"' in migration


def test_required_coding_mode_requires_explicit_tool_authorization_and_language() -> None:
    with pytest.raises(ValidationError):
        PracticeSetCreate(
            external_processing_ack=True,
            item_type_mode="require_coding",
            code_languages=["python"],
        )
    with pytest.raises(ValidationError):
        PracticeSetCreate(
            external_processing_ack=True,
            item_type_mode="require_coding",
            code_tool_authorized=True,
            code_languages=[],
        )
    payload = PracticeSetCreate(
        external_processing_ack=True,
        item_type_mode="require_coding",
        code_tool_authorized=True,
        code_languages=["java"],
    )
    assert payload.code_languages == ["java"]


def test_required_science_mode_requires_explicit_tool_authorization() -> None:
    with pytest.raises(ValidationError):
        PracticeSetCreate(external_processing_ack=True, item_type_mode="require_science")
    assert PracticeSetCreate(
        external_processing_ack=True,
        item_type_mode="require_science",
        science_tool_authorized=True,
    ).science_tool_authorized


def test_published_per_objective_hints_drive_capabilities_without_keywords() -> None:
    lesson = SimpleNamespace(
        learning_objectives=["Objective A"],
        practice_type_hints=[{
            "objective_key": "u1",
            "evidence_keys": ["e7"],
            "has_algorithmic_objective": True,
            "has_executable_evidence": True,
            "has_math_objective": False,
            "has_physics_objective": False,
            "has_chemistry_objective": False,
            "has_computable_evidence": False,
        }],
    )
    profile = _build_lesson_learning_profile(lesson, SimpleNamespace())
    assert profile.has_algorithmic_objective
    assert profile.has_executable_evidence
    assert profile.algorithmic_evidence_keys == ["e7"]
    assert not profile.has_computable_evidence


def test_legacy_aggregate_hint_remains_readable() -> None:
    lesson = SimpleNamespace(
        learning_objectives=["Objective A"],
        practice_type_hints={
            "has_algorithmic_objective": True,
            "has_executable_evidence": True,
            "has_math_objective": False,
            "has_computable_evidence": False,
        },
    )
    profile = _build_lesson_learning_profile(lesson, SimpleNamespace())
    assert profile.has_executable_evidence


def test_remote_scientific_answer_requires_bounded_verification_expression() -> None:
    with pytest.raises(ValidationError):
        ScientificAnswerSpec(normalized_answer="2", needs_remote_verification=True)
    spec = ScientificAnswerSpec(
        normalized_answer="2",
        needs_remote_verification=True,
        verification_expression="1 + 1 == 2",
    )
    assert spec.verification_expression == "1 + 1 == 2"

    normalized = ScientificAnswerSpec(
        normalized_answer="-285.8",
        unit="kJ/mol",
        needs_remote_verification=False,
        verification_expression="standard enthalpy of formation of H2O(l)",
    )
    assert normalized.needs_remote_verification is True


def test_scientific_item_requires_worked_reference_answer() -> None:
    with pytest.raises(ValidationError):
        PracticeItemArtifact(
            item_key="q1",
            target_key="objective_1",
            item_type="scientific",
            stem="Calculate the result and show the derivation.",
            citation_ids=["e1"],
            rubric=[{"criterion_key": "steps", "description": "Derivation", "weight": 100, "citation_ids": ["e1"]}],
            scientific_answer_spec=ScientificAnswerSpec(normalized_answer="2"),
        )


def test_scientific_grader_treats_final_value_as_only_one_signal() -> None:
    request = PracticeGraderRequest(
        item_type="scientific",
        stem="Derive the result.",
        reference_answer="Start from the governing equation, substitute values with units, then conclude 2 J.",
        rubric=(PracticeRubricCriterion(criterion_key="steps", description="Complete derivation", weight=100, citation_ids=["e1"]),),
        evidence=({"citation_id": "e1", "text": "Approved source"},),
        answer="2 J",
        deterministic_verification={"final_result_equivalent": True},
    )
    rendered = "\n".join(message["content"] for message in build_grading_prompt(request))
    assert "not a complete solution" in rendered
    assert "first incorrect or missing step" in rendered
    assert "final_result_equivalent" in rendered


@pytest.mark.parametrize(
    ("language", "reference_solution"),
    [
        ("java", "class Main { public static void main(String[] args) {} }"),
        ("cpp", "std::string solve(const std::string& input) { return input; }\nint main() {}"),
    ],
)
def test_coding_artifact_rejects_entry_points_that_conflict_with_harness(language: str, reference_solution: str) -> None:
    with pytest.raises(ValidationError):
        PracticeItemArtifact(
            item_key="q1",
            target_key="objective_1",
            item_type="coding",
            stem="Implement the task.",
            citation_ids=["e1"],
            language=language,
            hidden_tests=[
                {"input": "a", "expected_output": "a", "weight": 1},
                {"input": "b", "expected_output": "b", "weight": 1},
                {"input": "c", "expected_output": "c", "weight": 1},
            ],
            reference_solution=reference_solution,
        )


def test_java_public_solution_is_accepted_and_normalized_by_harness() -> None:
    item = PracticeItemArtifact(
        item_key="q1",
        target_key="objective_1",
        item_type="coding",
        stem="Implement the task.",
        citation_ids=["e1"],
        language="java",
        hidden_tests=[
            {"input": "a", "expected_output": "a", "weight": 1},
            {"input": "b", "expected_output": "b", "weight": 1},
            {"input": "c", "expected_output": "c", "weight": 1},
        ],
        reference_solution="public class Solution { static String solve(String input) { return input; } }",
    )
    harness = _build_coding_harness(item.reference_solution or "", [test.model_dump() for test in item.hidden_tests or []], "java")
    assert "public class Solution" not in harness
    assert "class Solution" in harness


def test_practice_novelty_rejects_spacing_and_punctuation_repeat() -> None:
    item = PracticeItemArtifact(
        item_key="q1",
        target_key="objective_1",
        item_type="single_choice",
        stem="What is Dijkstra's invariant?",
        citation_ids=["e1"],
        options=[
            {"option_key": "a", "text": "A", "is_correct": True, "rationale": "R", "citation_ids": ["e1"]},
            {"option_key": "b", "text": "B", "is_correct": False, "rationale": "R", "citation_ids": ["e1"]},
        ],
    )
    with pytest.raises(ValueError, match="duplicate_practice_item"):
        # Slice 5: novelty now takes (target_key, item_type, stem) prior tuples
        # so near-duplicate detection can be scoped by target/type/task signature.
        _validate_practice_novelty(SimpleNamespace(items=[item]), (("objective_1", "single_choice", "What is Dijkstra’s invariant"),))


@pytest.mark.parametrize(
    ("language", "source", "contract_marker"),
    [
        ("python", "def solve(input_text):\n    return input_text", "solve(_value)"),
        ("java", "class Solution { static String solve(String input) { return input; } }", "Solution.solve(inputs[i])"),
        ("cpp", "string solve(const string& input) { return input; }", "solve(inputs[i])"),
    ],
)
def test_coding_harness_uses_one_fixed_contract_for_all_languages(
    language: str, source: str, contract_marker: str
) -> None:
    harness = _build_coding_harness(
        source,
        [{"input": "hello", "expected_output": "hello", "weight": 1}],
        language,
    )
    assert source in harness
    assert contract_marker in harness
    assert '"total_weight"' in harness or "total_weight" in harness


def test_coding_artifact_rejects_solution_leak_and_duplicate_cases() -> None:
    base = {
        "item_key": "q1", "target_key": "objective_1", "item_type": "coding",
        "stem": "Implement solve.", "citation_ids": ["e1"], "language": "python",
        "reference_solution": "def solve(input_text): return input_text",
        "hidden_tests": [
            {"input": "a", "expected_output": "a"},
            {"input": "b", "expected_output": "b"},
            {"input": "c", "expected_output": "c"},
        ],
    }
    with pytest.raises(ValidationError, match="starter_code must not reveal"):
        PracticeItemArtifact.model_validate({**base, "starter_code": base["reference_solution"]})
    with pytest.raises(ValidationError, match="inputs must be unique"):
        PracticeItemArtifact.model_validate({**base, "hidden_tests": [
            {"input": "a", "expected_output": "a"},
            {"input": "a", "expected_output": "a"},
            {"input": "c", "expected_output": "c"},
        ]})


def test_numeric_tolerance_is_encoded_in_all_language_harnesses() -> None:
    case = [{"input": "x", "expected_output": "3.14", "weight": 1, "comparator": "numeric_tolerance", "tolerance": 0.01}]
    for language, source in [
        ("python", "def solve(input_text): return '3.141'"),
        ("java", "class Solution { static String solve(String input) { return \"3.141\"; } }"),
        ("cpp", "string solve(const string& input) { return \"3.141\"; }"),
    ]:
        harness = _build_coding_harness(source, case, language)
        assert "numeric_tolerance" in harness
        assert "0.01" in harness


def test_formula_validator_accepts_learning_math_and_rejects_active_content() -> None:
    assert validate_formula_content(r"The result is $x^2 + y^2$.").valid
    assert validate_formula_content(r"$$\frac{-b \pm \sqrt{b^2-4ac}}{2a}$$ and $\ce{H2O}$").valid
    assert not validate_formula_content(r"$\href{javascript:alert(1)}{x}$").valid
    assert not validate_formula_content(r"$\unknowncommand{x}$").valid
    assert not validate_formula_content("<script>alert(1)</script>").valid


def test_failed_coding_reference_never_persists_a_set(db_session, monkeypatch) -> None:
    from learn_platform_api.db.models import McpCapabilityStatus, PracticeSet
    from learn_platform_api.schemas.documents import CitationRead, RetrievalResult
    from learn_platform_api.services import practice, practice_generation
    from learn_platform_api.services.practice_generation import CodingReferenceValidationResult
    from learn_platform_api.settings import get_settings
    from test_practice_worker import _reader

    workspace, course, course_version, lesson, lesson_version, chunk, document, document_version = _reader(db_session)
    lesson_version.practice_type_hints = [{
        "objective_key": "u1",
        "evidence_keys": ["e1"],
        "has_algorithmic_objective": True,
        "has_executable_evidence": True,
        "has_math_objective": False,
        "has_physics_objective": False,
        "has_chemistry_objective": False,
        "has_computable_evidence": False,
    }]
    db_session.add(McpCapabilityStatus(
        capability_id="code_execution",
        status="ready",
        detail="ready",
        verified_schema_hash="a" * 16,
        checked_at=datetime.now(timezone.utc),
        ttl_seconds=300,
    ))
    db_session.commit()
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_args: None)
    payload = SimpleNamespace(
        item_count=2,
        difficulty="standard",
        output_language="zh-CN",
        item_type_mode="require_coding",
        code_languages=["python"],
        code_tool_authorized=True,
        science_tool_authorized=False,
    )
    job = practice.create_generation_job(
        db_session,
        get_settings(),
        workspace.id,
        course.id,
        course_version.id,
        lesson.id,
        lesson_version.id,
        payload,
        "coding-reference-failure",
    )
    job.status = "running"
    job.worker_id = "worker-1"
    job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=2)
    job.attempt_count = 1
    db_session.commit()

    monkeypatch.setattr(practice_generation, "retrieve", lambda *_args, **_kwargs: (
        "trace",
        [RetrievalResult(
            score=0.9,
            text=chunk.content,
            citation=CitationRead(
                document_id=document.id,
                document_version_id=document_version.id,
                chunk_id=chunk.id,
                document_name=document.display_name,
                heading_path=[],
                start_offset=0,
                end_offset=len(chunk.content),
            ),
        )],
    ))
    coding_item = {
        "item_key": "q-code",
        "target_key": "objective_1",
        "item_type": "coding",
        "stem": "Implement the specified transformation.",
        "citation_ids": ["e1"],
        "language": "python",
        "hidden_tests": [
            {"input": "a", "expected_output": "a", "weight": 1},
            {"input": "b", "expected_output": "b", "weight": 1},
            {"input": "c", "expected_output": "c", "weight": 1},
        ],
        "reference_solution": "def solve(input_text):\n    return 'wrong'",
    }
    choice_item = {
        "item_key": "q-choice",
        "target_key": "objective_1",
        "item_type": "single_choice",
        "stem": "Choose the supported statement.",
        "citation_ids": ["e1"],
        "options": [
            {"option_key": "a", "text": "A", "is_correct": True, "rationale": "Supported.", "citation_ids": ["e1"]},
            {"option_key": "b", "text": "B", "is_correct": False, "rationale": "Unsupported.", "citation_ids": ["e1"]},
        ],
    }
    artifact = {"items": [choice_item, coding_item]}
    provider_results = iter([
        ({"queries": ["objective evidence", "implementation evidence", "test evidence"]}, {}),
        (artifact, {}),
        (artifact, {}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_args, **_kwargs: next(provider_results))
    monkeypatch.setattr(
        practice_generation,
        "_validate_coding_reference_via_mcp",
        lambda *_args, **_kwargs: CodingReferenceValidationResult(
            passed=False,
            tests_passed=0,
            tests_total=3,
            error_categories=["reference_failed_tests"],
            infrastructure_failure=False,
        ),
    )

    # Per Correction 002 §D: when the repair also fails (either the DTO is
    # malformed or re-validation fails), the stable error code is
    # coding_repair_artifact_invalid or coding_repair_revalidation_failed,
    # NOT coding_reference_test_failed. The key invariant (zero Set/Item
    # persisted) still holds.
    with pytest.raises(ValueError, match="coding_repair_artifact_invalid|coding_repair_revalidation_failed|coding_reference_test_failed"):
        practice_generation.execute_generation(
            db_session,
            get_settings(),
            job,
            worker_id="worker-1",
        )
    assert db_session.query(PracticeSet).filter_by(practice_job_id=job.id).count() == 0
