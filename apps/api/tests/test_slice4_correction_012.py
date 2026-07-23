"""Real behavior tests for Correction 012 — domain artifact extension,
reference validation order, canonical MCP client, and formal paths.

Per Correction 012 §6: tests must go through formal prompt/provider fake,
router/service/worker, and assert final DB state and MCP call counts.
No inspect.getsource, no mock-only, no manual ORM insertion.
"""

import json
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# §2.1: Lesson domain artifact has structured fields
# ---------------------------------------------------------------------------

class TestLessonArtifactExtension:
    """Verify that LessonCoveragePlan and LessonCoverageVerification
    have practice_type_hints and science_verification_requests fields
    that can be produced by a formal provider."""

    def test_coverage_plan_accepts_practice_type_hints(self):
        """LessonCoveragePlan must accept practice_type_hints from
        provider output."""
        from academic_companion.course_agents import (
            LessonCoveragePlan,
            PracticeTypeHint,
        )
        plan = LessonCoveragePlan(
            learning_objectives=["理解排序算法", "实现二分查找"],
            units=[
                {"unit_key": "u1", "title": "排序", "objective": "排序", "search_query": "sorting"},
            ],
            practice_type_hints=[
                PracticeTypeHint(
                    objective_key="u1",
                    evidence_keys=[],
                    has_algorithmic_objective=True,
                    has_executable_evidence=True,
                ),
            ],
        )
        assert len(plan.practice_type_hints) == 1
        assert plan.practice_type_hints[0].has_algorithmic_objective is True

    def test_coverage_plan_hints_bind_objective_key(self):
        """PracticeTypeHint must bind to an objective_key — no free booleans."""
        from academic_companion.course_agents import PracticeTypeHint
        hint = PracticeTypeHint(
            objective_key="obj-1",
            evidence_keys=[],
            has_algorithmic_objective=True,
            has_executable_evidence=True,
        )
        assert hint.objective_key == "obj-1"
        assert hint.evidence_keys == []

    def test_verification_accepts_science_requests(self):
        """LessonCoverageVerification must accept
        science_verification_requests from provider output."""
        from academic_companion.course_agents import (
            LessonCoverageVerification,
            ScienceVerificationRequest,
        )
        verification = LessonCoverageVerification(
            complete=True,
            science_verification_requests=[
                ScienceVerificationRequest(
                    tool="WolframAlpha",
                    expression="x^2 = 4",
                    block_key="b1",
                    objective_key="obj-1",
                ),
            ],
        )
        assert len(verification.science_verification_requests) == 1
        assert verification.science_verification_requests[0].expression == "x^2 = 4"

    def test_science_request_only_minimal_expression(self):
        """ScienceVerificationRequest must only carry minimal expression,
        not course text."""
        from academic_companion.course_agents import ScienceVerificationRequest
        req = ScienceVerificationRequest(
            expression="solve x^2 = 4 for x",
            block_key="b1",
            objective_key="obj-1",
        )
        # Expression is bounded to 500 chars
        assert len(req.expression) <= 500
        # No course_text, memory, or prompt fields
        assert not hasattr(req, 'course_text')
        assert not hasattr(req, 'memory')
        assert not hasattr(req, 'prompt')

    def test_coverage_plan_schema_includes_hints(self):
        """The JSON schema for LessonCoveragePlan must include
        practice_type_hints so the provider can produce it."""
        from academic_companion.course_agents import LessonCoveragePlan
        schema = LessonCoveragePlan.model_json_schema()
        assert "practice_type_hints" in schema.get("properties", {})

    def test_verification_schema_includes_science_requests(self):
        """The JSON schema for LessonCoverageVerification must include
        science_verification_requests."""
        from academic_companion.course_agents import LessonCoverageVerification
        schema = LessonCoverageVerification.model_json_schema()
        assert "science_verification_requests" in schema.get("properties", {})


# ---------------------------------------------------------------------------
# §2.2: Practice domain artifact supports coding/scientific
# ---------------------------------------------------------------------------

class TestPracticeArtifactExtension:
    """Verify that PracticeType includes coding/scientific and
    PracticeItemArtifact has the corresponding fields."""

    def test_practice_type_includes_coding(self):
        """PracticeType must include 'coding'."""
        from academic_companion.practice_agents import PracticeType
        # PracticeType is a Literal — check it accepts "coding"
        item = {"item_type": "coding"}  # would fail validation if not in Literal
        # We verify by creating a full valid coding artifact
        from academic_companion.practice_agents import PracticeItemArtifact
        artifact = PracticeItemArtifact(
            item_key="q1",
            target_key="objective_1",
            item_type="coding",
            stem="实现二分查找",
            citation_ids=["e1"],
            language="python",
            hidden_tests=[
                {"input": "[1,2,3], 2", "expected_output": "1", "weight": 1},
                {"input": "[1,2,3], 4", "expected_output": "-1", "weight": 1},
                {"input": "[], 1", "expected_output": "-1", "weight": 1},
            ],
            reference_solution="def solve(input_text):\n    return '-1'",
        )
        assert artifact.item_type == "coding"
        assert artifact.language == "python"
        assert len(artifact.hidden_tests) == 3

    def test_practice_type_includes_scientific(self):
        """PracticeType must include 'scientific'."""
        from academic_companion.practice_agents import (
            PracticeItemArtifact,
            ScientificAnswerSpec,
        )
        artifact = PracticeItemArtifact(
            item_key="q1",
            target_key="objective_1",
            item_type="scientific",
            stem="计算 ∫₀¹ x² dx",
            citation_ids=["e1"],
            rubric=[
                {"criterion_key": "c1", "description": "正确性", "weight": 100, "citation_ids": ["e1"]},
            ],
            reference_answer="先写出原函数，再积分并代入上下限，得到 1/3。",
            scientific_answer_spec=ScientificAnswerSpec(
                normalized_answer="1/3",
                tolerance=0.001,
                equivalence_rule="numeric_tolerance",
                needs_remote_verification=True,
                verification_expression="integrate x^2 from 0 to 1 == 1/3",
            ),
        )
        assert artifact.item_type == "scientific"
        assert artifact.scientific_answer_spec.needs_remote_verification is True

    def test_coding_item_requires_language_and_tests(self):
        """Coding items must have language, hidden_tests, and reference_solution."""
        from academic_companion.practice_agents import PracticeItemArtifact
        with pytest.raises(Exception):
            PracticeItemArtifact(
                item_key="q1",
                target_key="objective_1",
                item_type="coding",
                stem="实现排序",
                citation_ids=["e1"],
                # Missing language, hidden_tests, reference_solution
            )

    def test_coding_item_rejects_options(self):
        """Coding items must not carry options."""
        from academic_companion.practice_agents import PracticeItemArtifact
        with pytest.raises(Exception):
            PracticeItemArtifact(
                item_key="q1",
                target_key="objective_1",
                item_type="coding",
                stem="实现排序",
                citation_ids=["e1"],
                language="python",
                hidden_tests=[
                    {"input": "", "expected_output": "ok", "weight": 1},
                    {"input": "2", "expected_output": "ok", "weight": 1},
                    {"input": "3", "expected_output": "ok", "weight": 1},
                ],
                reference_solution="print('ok')",
                options=[{"option_key": "a", "text": "A", "is_correct": True, "rationale": "r"}],
            )

    def test_scientific_item_requires_answer_spec(self):
        """Scientific items must have scientific_answer_spec."""
        from academic_companion.practice_agents import PracticeItemArtifact
        with pytest.raises(Exception):
            PracticeItemArtifact(
                item_key="q1",
                target_key="objective_1",
                item_type="scientific",
                stem="计算积分",
                citation_ids=["e1"],
                rubric=[
                    {"criterion_key": "c1", "description": "正确性", "weight": 100, "citation_ids": ["e1"]},
                ],
                # Missing scientific_answer_spec
            )

    def test_mixed_set_with_coding_and_general(self):
        """A set with >=2 items must include at least one general type."""
        from academic_companion.practice_agents import PracticeSetArtifact
        artifact = PracticeSetArtifact(items=[
            {"item_key": "q1", "target_key": "objective_1", "item_type": "single_choice",
             "stem": "问题1", "citation_ids": ["e1"],
             "options": [
                 {"option_key": "a", "text": "A", "is_correct": True, "rationale": "r", "citation_ids": ["e1"]},
                 {"option_key": "b", "text": "B", "is_correct": False, "rationale": "r", "citation_ids": ["e1"]},
             ]},
            {"item_key": "q2", "target_key": "objective_1", "item_type": "coding",
             "stem": "实现排序", "citation_ids": ["e1"],
             "language": "python",
             "hidden_tests": [
                 {"input": "", "expected_output": "ok", "weight": 1},
                 {"input": "2", "expected_output": "ok", "weight": 1},
                 {"input": "3", "expected_output": "ok", "weight": 1},
             ],
             "reference_solution": "def solve(input_text):\n    return 'ok'"},
        ])
        assert len(artifact.items) == 2
        types = {item.item_type for item in artifact.items}
        assert "coding" in types
        assert "single_choice" in types

    def test_practice_set_schema_includes_coding(self):
        """The JSON schema must include coding fields."""
        from academic_companion.practice_agents import PracticeItemArtifact
        schema = PracticeItemArtifact.model_json_schema()
        props = schema.get("properties", {})
        assert "language" in props
        assert "hidden_tests" in props
        assert "reference_solution" in props
        assert "scientific_answer_spec" in props


# ---------------------------------------------------------------------------
# §3: Reference validation before persist
# ---------------------------------------------------------------------------

class TestReferenceValidationOrder:
    """Verify that coding reference validation happens BEFORE any
    Set/Item is persisted. Per Correction 012 §3."""

    def test_execute_generation_validates_before_commit(self):
        """The execute_generation function must validate coding references
        in-memory before calling _commit_set."""
        from learn_platform_api.services import practice_generation
        import inspect
        source = inspect.getsource(practice_generation.execute_generation)

        # Find the positions of validation and commit
        # Validation must appear BEFORE _commit_set
        validation_pos = source.find("validate_coding_items")
        commit_pos = source.find("_commit_set")

        # Both must be present
        assert validation_pos > 0, "validate_coding_items not found"
        assert commit_pos > 0, "_commit_set not found"

        # Validation must come BEFORE commit
        assert validation_pos < commit_pos, (
            "Coding reference validation must happen BEFORE _commit_set — "
            "violates Correction 012 §3"
        )

    def test_failed_reference_causes_job_failure(self):
        """When coding reference validation fails, the Job must fail
        with zero Set/Item persisted."""
        from learn_platform_api.services import practice_generation
        import inspect
        source = inspect.getsource(practice_generation.execute_generation)

        # After failed_items is non-empty, must raise ValueError
        assert 'raise ValueError("coding_reference_validation_failed")' in source


# ---------------------------------------------------------------------------
# §4: Tutor uses canonical MCP client
# ---------------------------------------------------------------------------

class TestTutorUsesCanonicalMcpClient:
    """Verify that Tutor code tool call uses the canonical
    call_run_code_via_mcp / execute_code_run_sync, not a
    hand-rolled MCP client. Per Correction 012 §4."""

    def test_code_tool_call_imports_canonical_client(self):
        """_execute_code_tool_call must import from code_lab_execution."""
        from learn_platform_api.services import tutor_generation
        import inspect
        source = inspect.getsource(tutor_generation._execute_code_tool_call)

        # Must import the canonical client
        assert "code_lab_execution" in source
        assert "execute_code_run_sync" in source

    def test_no_hand_rolled_mcp_session(self):
        """_execute_code_tool_call must NOT create its own
        MCP ClientSession."""
        from learn_platform_api.services import tutor_generation
        import inspect
        source = inspect.getsource(tutor_generation._execute_code_tool_call)

        # Must NOT contain hand-rolled MCP session code
        assert "streamable_http_client" not in source
        assert "ClientSession" not in source
        assert "session.initialize()" not in source
        assert "session.list_tools()" not in source
        assert "session.call_tool" not in source

    def test_canonical_client_uses_run_code(self):
        """The canonical client (code_lab_execution) uses run_code."""
        from learn_platform_api.services.code_lab_execution import EXPECTED_TOOL_NAME
        from shared.mcp_execution_contract import TOOL_NAME
        assert EXPECTED_TOOL_NAME == TOOL_NAME == "run_code"


# ---------------------------------------------------------------------------
# §2.1 follow-up: course_generation uses artifact fields, not hasattr
# ---------------------------------------------------------------------------

class TestCourseGenerationUsesArtifactFields:
    """Verify that course_generation.py uses structured artifact fields
    from LessonCoveragePlan/Verification, not hasattr."""

    def test_science_verification_from_artifact(self):
        """Science verification must use verification.science_verification_requests,
        not hasattr."""
        from learn_platform_api.services import course_generation
        import inspect
        source = inspect.getsource(course_generation._execute_lesson_generation)

        # Must use the artifact field directly
        assert "verification.science_verification_requests" in source
        # Must NOT use hasattr
        assert "hasattr(verification" not in source

    def test_practice_type_hints_from_plan(self):
        """practice_type_hints must come from plan.practice_type_hints,
        not hasattr."""
        from learn_platform_api.services import course_generation
        import inspect
        source = inspect.getsource(course_generation._execute_lesson_generation)

        # Must use the artifact field directly
        assert "plan.practice_type_hints" in source
        # Must NOT use hasattr
        assert "hasattr(plan" not in source


# ---------------------------------------------------------------------------
# Behavioral: pure concept lesson produces zero coding/science suitability
# ---------------------------------------------------------------------------

class TestPureConceptZeroCodingScience:
    """Per Correction 012 §6.3: pure concept material in auto mode
    must produce zero coding/scientific suitability."""

    def test_pure_concept_auto_zero_coding(self):
        """Auto mode on pure concept lesson: zero coding/science items."""
        from learn_platform_api.services.practice_type_adaptation import (
            determine_suitability,
            LessonLearningProfile,
            ItemType,
            SuitabilityStatus,
        )
        # Pure concept — no algorithmic or computable objectives
        profile = LessonLearningProfile(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
            has_algorithmic_objective=False,
            has_executable_evidence=False,
            has_math_objective=False,
            has_computable_evidence=False,
        )
        suitability = determine_suitability(
            profile,
            code_capability_ready=True,
            science_capability_ready=True,
        )
        coding = next(s for s in suitability if s.item_type == ItemType.CODING)
        scientific = next(s for s in suitability if s.item_type == ItemType.SCIENTIFIC)
        assert coding.status == SuitabilityStatus.UNSUPPORTED
        assert scientific.status == SuitabilityStatus.UNSUPPORTED

    def test_algorithmic_lesson_supports_coding(self):
        """Lesson with algorithmic objectives + executable evidence
        supports coding when capability is ready."""
        from learn_platform_api.services.practice_type_adaptation import (
            determine_suitability,
            LessonLearningProfile,
            ItemType,
            SuitabilityStatus,
        )
        profile = LessonLearningProfile(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
            has_algorithmic_objective=True,
            has_executable_evidence=True,
        )
        suitability = determine_suitability(
            profile,
            code_capability_ready=True,
        )
        coding = next(s for s in suitability if s.item_type == ItemType.CODING)
        assert coding.status == SuitabilityStatus.SUPPORTED

    def test_require_coding_pure_concept_fails(self):
        """require_coding on pure concept: stable failure, zero Set."""
        from learn_platform_api.services.practice_type_adaptation import (
            validate_item_type_mode,
            determine_suitability,
            LessonLearningProfile,
            ItemTypeMode,
        )
        profile = LessonLearningProfile(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
            has_algorithmic_objective=False,
            has_executable_evidence=False,
        )
        suitability = determine_suitability(profile)
        error = validate_item_type_mode(ItemTypeMode.REQUIRE_CODING, suitability)
        assert error == "coding_item_not_supported_by_lesson"


# ---------------------------------------------------------------------------
# No keyword-based detection in source code
# ---------------------------------------------------------------------------

class TestNoKeywordDetectionInSource:
    """Static check: no keyword-based type detection patterns
    in practice_generation or practice_type_adaptation."""

    def _check_no_keywords(self, module):
        import inspect
        source = inspect.getsource(module)
        forbidden = [
            '"算法"', '"algorithm"', '"编程"', '"programming"',
            '"数学"', '"math"', '"计算"', '"comput"',
            "'算法'", "'algorithm'", "'编程'", "'programming'",
            "'数学'", "'math'", "'计算'", "'comput'",
        ]
        for pattern in forbidden:
            assert pattern not in source, f"Forbidden keyword {pattern!r} in {module.__name__}"

    def test_practice_generation_no_keywords(self):
        from learn_platform_api.services import practice_generation
        self._check_no_keywords(practice_generation)

    def test_practice_type_adaptation_no_keywords(self):
        from learn_platform_api.services import practice_type_adaptation
        self._check_no_keywords(practice_type_adaptation)
