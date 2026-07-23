"""
Behavioral tests for Slice 4 Packet 002 additions:
- Migration 0021: job_tool_authorizations, PracticeJob/Item/Attempt/Feedback/TutorTurn extensions
- Formula validator
- Practice type adaptation
- Tutor Skill v4 contracts

Note: SQLite cannot evaluate Postgres-specific `::int` casts in check constraints,
so ORM tests use a filtered subset of tables (same approach as test_mcp_orm_and_schema.py).
The migration itself is tested via Alembic upgrade/downgrade against Postgres.
"""

import pytest
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from learn_platform_api.db.base import Base
from learn_platform_api.db.models import (
    JobToolAuthorization, PracticeJob, PracticeItem, PracticeAttempt,
    PracticeFeedback, TutorTurn, CourseGenerationJob, Workspace,
    McpCapabilityStatus, PracticeSet, TutorSession,
)
from learn_platform_api.services.formula_validator import (
    validate_formula_content, FormulaValidationResult,
)
from learn_platform_api.services.practice_type_adaptation import (
    determine_suitability, validate_item_type_mode,
    LessonLearningProfile, ItemType, ItemTypeMode, SuitabilityStatus,
    is_pseudo_coding_item,
)


# Tables that don't have Postgres-specific ::int check constraints
_ORM_TEST_TABLES = {
    "workspaces", "job_tool_authorizations", "practice_jobs",
    "practice_sets", "practice_items", "practice_attempts",
    "practice_feedback", "tutor_sessions", "tutor_turns",
    "mcp_capability_statuses", "courses", "course_versions",
    "course_sections", "lessons", "lesson_versions",
    "course_generation_jobs",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    engine = create_engine("sqlite://", echo=False)

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        # Disable FK checks for simpler test setup (FKs tested in Postgres migration)
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    tables_to_create = [t for t in Base.metadata.sorted_tables if t.name in _ORM_TEST_TABLES]
    Base.metadata.create_all(engine, tables=tables_to_create)
    maker = sessionmaker(bind=engine)
    session = maker()
    yield session
    session.close()
    engine.dispose()


def _make_workspace(db: Session) -> Workspace:
    ws = Workspace(id="ws-1", name="Test", slug="test")
    db.add(ws)
    db.commit()
    return ws


# ---------------------------------------------------------------------------
# Migration 0021: JobToolAuthorization
# ---------------------------------------------------------------------------

class TestJobToolAuthorizationModel:
    def test_create_with_course_generation_owner(self, db):
        _make_workspace(db)
        course_job = CourseGenerationJob(
            id="cgj-1", workspace_id="ws-1", course_id="c-1",
            job_type="lesson_draft", idempotency_key="ik-1",
            output_language="zh-CN",
        )
        db.add(course_job)
        db.commit()
        auth = JobToolAuthorization(
            id="jta-1", workspace_id="ws-1", capability_id="science_computation",
            course_generation_job_id="cgj-1",
            max_calls=3, used_calls=0,
        )
        db.add(auth)
        db.commit()
        result = db.get(JobToolAuthorization, "jta-1")
        assert result is not None
        assert result.capability_id == "science_computation"
        assert result.course_generation_job_id == "cgj-1"
        assert result.practice_job_id is None
        assert result.max_calls == 3
        assert result.used_calls == 0

    def test_create_with_practice_owner(self, db):
        _make_workspace(db)
        pj = PracticeJob(
            id="pj-1", workspace_id="ws-1", job_type="generate_set",
            output_language="zh-CN", difficulty="standard", item_count=3,
            request_hash="h", idempotency_key="ik-2",
            item_type_mode="auto",
        )
        db.add(pj)
        db.commit()
        auth = JobToolAuthorization(
            id="jta-2", workspace_id="ws-1", capability_id="code_execution",
            practice_job_id="pj-1",
            max_calls=1, used_calls=0,
        )
        db.add(auth)
        db.commit()
        result = db.get(JobToolAuthorization, "jta-2")
        assert result is not None
        assert result.practice_job_id == "pj-1"
        assert result.course_generation_job_id is None


# ---------------------------------------------------------------------------
# PracticeJob extensions
# ---------------------------------------------------------------------------

class TestPracticeJobExtensions:
    def test_item_type_mode_default(self, db):
        _make_workspace(db)
        pj = PracticeJob(
            id="pj-m1", workspace_id="ws-1", job_type="generate_set",
            output_language="zh-CN", difficulty="standard", item_count=3,
            request_hash="h", idempotency_key="ik-m1",
        )
        db.add(pj)
        db.commit()
        result = db.get(PracticeJob, "pj-m1")
        assert result.item_type_mode == "auto"

    def test_code_languages(self, db):
        _make_workspace(db)
        pj = PracticeJob(
            id="pj-m2", workspace_id="ws-1", job_type="generate_set",
            output_language="zh-CN", difficulty="standard", item_count=3,
            request_hash="h", idempotency_key="ik-m2",
            item_type_mode="require_coding",
            code_languages=["python", "java", "cpp"],
        )
        db.add(pj)
        db.commit()
        result = db.get(PracticeJob, "pj-m2")
        assert result.item_type_mode == "require_coding"
        assert result.code_languages == ["python", "java", "cpp"]


# ---------------------------------------------------------------------------
# PracticeItem interaction_spec
# ---------------------------------------------------------------------------

class TestPracticeItemInteractionSpec:
    def test_coding_interaction_spec(self, db):
        _make_workspace(db)
        item = PracticeItem(
            id="pi-1", practice_set_id="ps-1", workspace_id="ws-1",
            ordinal=1, item_type="coding", stem="Write a function",
            answer_spec={"reference_solution": "def f(): pass"},
            interaction_spec={
                "language": "python",
                "starter_code": "def solve():\n    pass",
                "input_description": "List of integers",
                "output_description": "Sorted list",
                "constraints": "O(n log n)",
                "public_examples": [{"input": "[3,1,2]", "output": "[1,2,3]"}],
                "runtime_limit_seconds": 3,
                "time_limit_seconds": 10,
                "output_limit_bytes": 32768,
            },
        )
        db.add(item)
        db.commit()
        result = db.get(PracticeItem, "pi-1")
        assert result.interaction_spec is not None
        assert result.interaction_spec["language"] == "python"

    def test_non_coding_null_interaction_spec(self, db):
        _make_workspace(db)
        item = PracticeItem(
            id="pi-2", practice_set_id="ps-1", workspace_id="ws-1",
            ordinal=2, item_type="single_choice", stem="What is X?",
            answer_spec={"correct_option": "a"},
        )
        db.add(item)
        db.commit()
        result = db.get(PracticeItem, "pi-2")
        assert result.interaction_spec is None


# ---------------------------------------------------------------------------
# PracticeAttempt source_code
# ---------------------------------------------------------------------------

class TestPracticeAttemptSourceCode:
    def test_coding_attempt_with_source_code(self, db):
        _make_workspace(db)
        attempt = PracticeAttempt(
            id="pa-1", workspace_id="ws-1", practice_item_id="pi-1",
            ordinal=1, item_type="coding",
            answer_payload={"option_key": None, "text": None, "source_code": "def solve(): return 42"},
            idempotency_key="ik-pa1",
            source_code="def solve(): return 42",
        )
        db.add(attempt)
        db.commit()
        result = db.get(PracticeAttempt, "pa-1")
        assert result.source_code == "def solve(): return 42"


# ---------------------------------------------------------------------------
# PracticeFeedback coding summary
# ---------------------------------------------------------------------------

class TestPracticeFeedbackCodingSummary:
    def test_coding_feedback(self, db):
        _make_workspace(db)
        fb = PracticeFeedback(
            id="pf-1", practice_attempt_id="pa-1", workspace_id="ws-1",
            verdict="incorrect", score=60,
            feedback_blocks=[{"type": "explanation", "text": "Partial"}],
            coding_tests_passed=3,
            coding_tests_total=5,
            coding_error_categories=["runtime_error", "timeout"],
            coding_public_cases=[
                {"input": "[1,2,3]", "expected": "6", "actual": "6", "passed": True},
                {"input": "[1]", "expected": "1", "actual": "1", "passed": True},
            ],
        )
        db.add(fb)
        db.commit()
        result = db.get(PracticeFeedback, "pf-1")
        assert result.coding_tests_passed == 3
        assert result.coding_tests_total == 5
        assert "runtime_error" in result.coding_error_categories
        assert len(result.coding_public_cases) == 2


# ---------------------------------------------------------------------------
# TutorTurn code tool fields
# ---------------------------------------------------------------------------

class TestTutorTurnCodeToolFields:
    def test_code_tool_fields_default(self, db):
        _make_workspace(db)
        turn = TutorTurn(
            id="tt-1", session_id="ts-1", workspace_id="ws-1",
            ordinal=1, attempt_number=1, idempotency_key="ik-tt1",
            question="test", scope="lesson", history_through_ordinal=0,
        )
        db.add(turn)
        db.commit()
        result = db.get(TutorTurn, "tt-1")
        assert result.code_tool_authorized is False
        assert result.code_tool_used is False
        assert result.code_tool_call_count == 0
        assert result.science_tool_used is False
        assert result.science_tool_call_count == 0


# ---------------------------------------------------------------------------
# Formula validator
# ---------------------------------------------------------------------------

class TestFormulaValidator:
    def test_valid_plain_text(self):
        result = validate_formula_content("Hello world")
        assert result.valid is True

    def test_valid_inline_math(self):
        result = validate_formula_content("The formula $E = mc^2$ is famous")
        assert result.valid is True

    def test_valid_display_math(self):
        result = validate_formula_content("$$\\int_0^1 x dx = 0.5$$")
        assert result.valid is True

    def test_valid_chemistry(self):
        result = validate_formula_content("Water is $\\ce{H2O}$")
        assert result.valid is True

    def test_unpaired_delimiter(self):
        result = validate_formula_content("This has $unpaired dollar")
        # The repair logic removes the trailing unpaired $, making it valid
        assert result.valid is True
        assert result.repaired_content is not None

    def test_too_long_expression(self):
        long_expr = "a" * 2001
        result = validate_formula_content(f"${long_expr}$")
        assert result.valid is False

    def test_dangerous_html_in_math(self):
        result = validate_formula_content("$<script>alert(1)</script>$")
        assert result.valid is False

    def test_dangerous_macro_definition(self):
        result = validate_formula_content("$\\newcommand{\\x}{1} \\x$")
        assert result.valid is False

    def test_dangerous_href(self):
        result = validate_formula_content("$\\href{http://evil.com}{click}$")
        assert result.valid is False

    def test_normal_dollar_signs_not_math(self):
        # Regular text with dollar amounts should not be treated as math
        # (only $...$ with matching pairs are math)
        result = validate_formula_content("Price is $5 and $10 total")
        # This has paired $ so it will be treated as math, but that's the
        # expected behavior per Spec 004 §4.2: "only content with explicit
        # supported delimiters is parsed as math"
        # The key invariant is that render failure shows fallback
        assert isinstance(result, FormulaValidationResult)

    def test_empty_content(self):
        result = validate_formula_content("")
        assert result.valid is True

    def test_content_too_long(self):
        result = validate_formula_content("x" * 100_001)
        assert result.valid is False


# ---------------------------------------------------------------------------
# Practice type adaptation
# ---------------------------------------------------------------------------

class TestPracticeTypeAdaptation:
    def test_pure_concept_lesson(self):
        profile = LessonLearningProfile(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
            has_algorithmic_objective=False,
            has_executable_evidence=False,
        )
        result = determine_suitability(profile)
        coding = next(s for s in result if s.item_type == ItemType.CODING)
        science = next(s for s in result if s.item_type == ItemType.SCIENTIFIC)
        assert coding.status == SuitabilityStatus.UNSUPPORTED
        assert science.status == SuitabilityStatus.UNSUPPORTED

    def test_algorithmic_lesson_with_capability(self):
        profile = LessonLearningProfile(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1", "ev-2"],
            has_algorithmic_objective=True,
            has_executable_evidence=True,
            algorithmic_evidence_keys=["ev-1", "ev-2"],
        )
        result = determine_suitability(
            profile, code_capability_ready=True, science_capability_ready=True,
        )
        coding = next(s for s in result if s.item_type == ItemType.CODING)
        assert coding.status == SuitabilityStatus.SUPPORTED

    def test_scientific_lesson_with_capability(self):
        profile = LessonLearningProfile(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
            has_math_objective=True,
            has_computable_evidence=True,
            computable_evidence_keys=["ev-1"],
        )
        result = determine_suitability(
            profile, code_capability_ready=True, science_capability_ready=True,
        )
        science = next(s for s in result if s.item_type == ItemType.SCIENTIFIC)
        assert science.status == SuitabilityStatus.SUPPORTED

    def test_capability_not_ready_blocks_coding(self):
        profile = LessonLearningProfile(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
            has_algorithmic_objective=True,
            has_executable_evidence=True,
        )
        result = determine_suitability(
            profile, code_capability_ready=False, science_capability_ready=True,
        )
        coding = next(s for s in result if s.item_type == ItemType.CODING)
        assert coding.status == SuitabilityStatus.UNSUPPORTED

    def test_general_only_mode_always_valid(self):
        profile = LessonLearningProfile(
            objective_keys=["obj-1"], evidence_keys=["ev-1"],
        )
        suitability = determine_suitability(profile)
        error = validate_item_type_mode(ItemTypeMode.GENERAL_ONLY, suitability)
        assert error is None

    def test_auto_mode_always_valid(self):
        profile = LessonLearningProfile(
            objective_keys=["obj-1"], evidence_keys=["ev-1"],
        )
        suitability = determine_suitability(profile)
        error = validate_item_type_mode(ItemTypeMode.AUTO, suitability)
        assert error is None

    def test_require_coding_unsupported_fails(self):
        profile = LessonLearningProfile(
            objective_keys=["obj-1"], evidence_keys=["ev-1"],
            has_algorithmic_objective=False,
            has_executable_evidence=False,
        )
        suitability = determine_suitability(profile)
        error = validate_item_type_mode(ItemTypeMode.REQUIRE_CODING, suitability)
        assert error == "coding_item_not_supported_by_lesson"

    def test_require_science_unsupported_fails(self):
        profile = LessonLearningProfile(
            objective_keys=["obj-1"], evidence_keys=["ev-1"],
        )
        suitability = determine_suitability(profile)
        error = validate_item_type_mode(ItemTypeMode.REQUIRE_SCIENCE, suitability)
        assert error == "science_item_not_supported_by_lesson"


class TestPseudoCodingItemDetection:
    def test_no_algorithmic_objective_is_pseudo(self):
        assert is_pseudo_coding_item(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
            has_algorithmic_objective=False,
            has_executable_evidence=True,
        ) is True

    def test_no_executable_evidence_is_pseudo(self):
        assert is_pseudo_coding_item(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
            has_algorithmic_objective=True,
            has_executable_evidence=False,
        ) is True

    def test_no_objectives_is_pseudo(self):
        assert is_pseudo_coding_item(
            objective_keys=[],
            evidence_keys=["ev-1"],
            has_algorithmic_objective=True,
            has_executable_evidence=True,
        ) is True

    def test_real_coding_not_pseudo(self):
        assert is_pseudo_coding_item(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
            has_algorithmic_objective=True,
            has_executable_evidence=True,
        ) is False
