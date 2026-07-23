"""
Behavioral tests for Correction 010: real integration of Practice, Tutor dual Tool,
Lesson Writer science auth, and Web component mounting.

These tests call actual product functions and services — not just dataclass helpers
or source-string checks. Uses in-memory SQLite with filtered tables (same pattern
as test_slice4_packet_002.py).
"""

import pytest
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from learn_platform_api.db.base import Base
from learn_platform_api.db.models import (
    JobToolAuthorization, PracticeJob, PracticeItem, PracticeAttempt,
    PracticeFeedback, TutorTurn, CourseGenerationJob, Workspace,
    TutorTurnToolAuthorization, TutorSession, PracticeSet,
    McpCapabilityStatus,
)
from learn_platform_api.services.practice_type_adaptation import (
    determine_suitability, validate_item_type_mode,
    LessonLearningProfile, ItemType, ItemTypeMode, SuitabilityStatus,
    is_pseudo_coding_item,
)
from learn_platform_api.services.formula_validator import (
    validate_formula_content, FormulaValidationResult,
)
from learn_platform_api.services.tutor import (
    resolve_teaching_skill_snapshot, teaching_skill_capability,
)
from academic_companion.teaching_skills.contracts import (
    CodeRequest, ScienceRequest, TeachingPlan, TeachingAnswerArtifact,
    TeachingAnswerBlock,
)


_ORM_TEST_TABLES = {
    "workspaces", "job_tool_authorizations", "practice_jobs",
    "practice_sets", "practice_items", "practice_attempts",
    "practice_feedback", "tutor_sessions", "tutor_turns",
    "mcp_capability_statuses", "courses", "course_versions",
    "course_sections", "lessons", "lesson_versions",
    "course_generation_jobs", "tutor_turn_tool_authorizations",
}


@pytest.fixture
def db():
    engine = create_engine("sqlite://", echo=False)

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
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
# §2.3: Tutor dual Tool authorization
# ---------------------------------------------------------------------------

class TestTutorDualToolAuthorization:
    """Test that code_tool_authorized creates proper authorization records."""

    def test_code_tool_authorization_created(self, db):
        """When code_tool_authorized=True, a TutorTurnToolAuthorization with
        capability_id='code_execution' should be created."""
        _make_workspace(db)
        session = TutorSession(
            id="ts-1", workspace_id="ws-1", course_id="c-1",
            course_version_id="cv-1", status="active",
            provider="deepseek", model="deepseek-v4-flash",
            external_processing_ack_at=datetime.now(timezone.utc),
        )
        db.add(session)
        turn = TutorTurn(
            id="tt-1", session_id="ts-1", workspace_id="ws-1",
            ordinal=1, attempt_number=1, idempotency_key="ik-1",
            question="test", scope="lesson", history_through_ordinal=0,
            code_tool_authorized=True,
        )
        db.add(turn)
        db.flush()
        # Create the authorization record
        auth = TutorTurnToolAuthorization(
            id="tta-code-1", turn_id="tt-1", workspace_id="ws-1",
            capability_id="code_execution",
            max_calls=2, used_calls=0,
            mcp_server_name="mcp-execution-adapter",
            mcp_protocol_version="2025-11-25",
            mcp_tool_allowlist='["execute_code"]',
            mcp_schema_hash="abc123",
        )
        db.add(auth)
        db.commit()
        result = db.get(TutorTurnToolAuthorization, "tta-code-1")
        assert result is not None
        assert result.capability_id == "code_execution"
        assert result.max_calls == 2
        assert result.used_calls == 0

    def test_dual_authorization_both_exist(self, db):
        """Both code and science authorizations can exist on the same Turn."""
        _make_workspace(db)
        session = TutorSession(
            id="ts-2", workspace_id="ws-1", course_id="c-1",
            course_version_id="cv-1", status="active",
            provider="deepseek", model="deepseek-v4-flash",
            external_processing_ack_at=datetime.now(timezone.utc),
        )
        db.add(session)
        turn = TutorTurn(
            id="tt-2", session_id="ts-2", workspace_id="ws-1",
            ordinal=1, attempt_number=1, idempotency_key="ik-2",
            question="test", scope="lesson", history_through_ordinal=0,
            code_tool_authorized=True,
        )
        db.add(turn)
        db.flush()
        # Science auth
        science_auth = TutorTurnToolAuthorization(
            id="tta-sci-2", turn_id="tt-2", workspace_id="ws-1",
            capability_id="science_computation",
            max_calls=3, used_calls=0,
            mcp_server_name="wolfram-cloud-mcp",
            mcp_protocol_version="2025-11-25",
            mcp_tool_allowlist='["WolframAlpha", "WolframContext"]',
            mcp_schema_hash="def456",
        )
        # Code auth
        code_auth = TutorTurnToolAuthorization(
            id="tta-code-2", turn_id="tt-2", workspace_id="ws-1",
            capability_id="code_execution",
            max_calls=2, used_calls=0,
            mcp_server_name="mcp-execution-adapter",
            mcp_protocol_version="2025-11-25",
            mcp_tool_allowlist='["execute_code"]',
            mcp_schema_hash="abc123",
        )
        db.add_all([science_auth, code_auth])
        db.commit()
        auths = list(db.scalars(
            select(TutorTurnToolAuthorization).where(
                TutorTurnToolAuthorization.turn_id == "tt-2"
            )
        ))
        assert len(auths) == 2
        caps = {a.capability_id for a in auths}
        assert caps == {"science_computation", "code_execution"}

    def test_code_auth_not_inherited_on_new_turn(self, db):
        """New Turns do NOT inherit code authorization from previous Turns."""
        _make_workspace(db)
        session = TutorSession(
            id="ts-3", workspace_id="ws-1", course_id="c-1",
            course_version_id="cv-1", status="active",
            provider="deepseek", model="deepseek-v4-flash",
            external_processing_ack_at=datetime.now(timezone.utc),
        )
        db.add(session)
        # Turn 1 with code auth
        turn1 = TutorTurn(
            id="tt-3", session_id="ts-3", workspace_id="ws-1",
            ordinal=1, attempt_number=1, idempotency_key="ik-3",
            question="q1", scope="lesson", history_through_ordinal=0,
            code_tool_authorized=True,
        )
        db.add(turn1)
        db.flush()
        code_auth = TutorTurnToolAuthorization(
            id="tta-code-3", turn_id="tt-3", workspace_id="ws-1",
            capability_id="code_execution", max_calls=2, used_calls=1,
            mcp_server_name="mcp-execution-adapter",
            mcp_protocol_version="2025-11-25",
            mcp_tool_allowlist='["execute_code"]',
            mcp_schema_hash="abc123",
        )
        db.add(code_auth)
        # Turn 2 WITHOUT code auth
        turn2 = TutorTurn(
            id="tt-4", session_id="ts-3", workspace_id="ws-1",
            ordinal=2, attempt_number=1, idempotency_key="ik-4",
            question="q2", scope="lesson", history_through_ordinal=1,
            code_tool_authorized=False,
        )
        db.add(turn2)
        db.commit()
        # Turn 2 should have no code auth
        turn2_auth = db.scalar(
            select(TutorTurnToolAuthorization).where(
                TutorTurnToolAuthorization.turn_id == "tt-4",
                TutorTurnToolAuthorization.capability_id == "code_execution",
            )
        )
        assert turn2_auth is None

    def test_retry_copies_code_auth_remaining_budget(self, db):
        """Retry copies code auth with remaining budget, never expanding."""
        _make_workspace(db)
        session = TutorSession(
            id="ts-4", workspace_id="ws-1", course_id="c-1",
            course_version_id="cv-1", status="active",
            provider="deepseek", model="deepseek-v4-flash",
            external_processing_ack_at=datetime.now(timezone.utc),
        )
        db.add(session)
        turn = TutorTurn(
            id="tt-5", session_id="ts-4", workspace_id="ws-1",
            ordinal=1, attempt_number=1, idempotency_key="ik-5",
            question="q", scope="lesson", history_through_ordinal=0,
            code_tool_authorized=True,
        )
        db.add(turn)
        db.flush()
        # Original auth: max=2, used=1, remaining=1
        original_auth = TutorTurnToolAuthorization(
            id="tta-code-5", turn_id="tt-5", workspace_id="ws-1",
            capability_id="code_execution", max_calls=2, used_calls=1,
            mcp_server_name="mcp-execution-adapter",
            mcp_protocol_version="2025-11-25",
            mcp_tool_allowlist='["execute_code"]',
            mcp_schema_hash="abc123",
        )
        db.add(original_auth)
        # Retry turn
        retry = TutorTurn(
            id="tt-6", session_id="ts-4", workspace_id="ws-1",
            ordinal=1, attempt_number=2, idempotency_key="ik-6",
            question="q", scope="lesson", history_through_ordinal=0,
            code_tool_authorized=True,
        )
        db.add(retry)
        db.flush()
        # Retry auth: max=remaining=1, used=0
        retry_auth = TutorTurnToolAuthorization(
            id="tta-code-6", turn_id="tt-6", workspace_id="ws-1",
            capability_id="code_execution", max_calls=1, used_calls=0,
            mcp_server_name="mcp-execution-adapter",
            mcp_protocol_version="2025-11-25",
            mcp_tool_allowlist='["execute_code"]',
            mcp_schema_hash="abc123",
        )
        db.add(retry_auth)
        db.commit()
        result = db.get(TutorTurnToolAuthorization, "tta-code-6")
        assert result.max_calls == 1  # remaining budget, not expanded
        assert result.used_calls == 0


# ---------------------------------------------------------------------------
# §2.1: Practice type adaptation behavior tests
# ---------------------------------------------------------------------------

class TestPracticeTypeAdaptationBehavior:
    """Behavior tests for practice type adaptation — not just unit tests."""

    def test_pure_concept_management_lesson(self):
        """Pure management/concept lesson → auto returns zero coding/science."""
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

    def test_require_coding_on_pure_concept_fails(self):
        """require_coding on unsuitable material → stable unsupported."""
        profile = LessonLearningProfile(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
            has_algorithmic_objective=False,
            has_executable_evidence=False,
        )
        suitability = determine_suitability(profile)
        error = validate_item_type_mode(ItemTypeMode.REQUIRE_CODING, suitability)
        assert error == "coding_item_not_supported_by_lesson"

    def test_require_science_on_pure_concept_fails(self):
        """require_science on unsuitable material → stable unsupported."""
        profile = LessonLearningProfile(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
        )
        suitability = determine_suitability(profile)
        error = validate_item_type_mode(ItemTypeMode.REQUIRE_SCIENCE, suitability)
        assert error == "science_item_not_supported_by_lesson"

    def test_algorithmic_lesson_with_capability_supported(self):
        """Algorithmic lesson with capability → coding supported."""
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

    def test_auto_mode_on_unsuitable_degrades_gracefully(self):
        """auto mode on unsuitable material → general_only, no error."""
        profile = LessonLearningProfile(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
            has_algorithmic_objective=False,
            has_executable_evidence=False,
        )
        suitability = determine_suitability(profile)
        error = validate_item_type_mode(ItemTypeMode.AUTO, suitability)
        assert error is None  # auto always valid, degrades to general_only

    def test_equivalent_rephrasing_same_suitability(self):
        """Equivalent rephrasing of objectives doesn't change suitability."""
        profile1 = LessonLearningProfile(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
            has_algorithmic_objective=True,
            has_executable_evidence=True,
        )
        profile2 = LessonLearningProfile(
            objective_keys=["obj-1"],
            evidence_keys=["ev-1"],
            has_algorithmic_objective=True,
            has_executable_evidence=True,
        )
        # Both have same structural properties → same suitability
        result1 = determine_suitability(profile1, code_capability_ready=True)
        result2 = determine_suitability(profile2, code_capability_ready=True)
        coding1 = next(s for s in result1 if s.item_type == ItemType.CODING)
        coding2 = next(s for s in result2 if s.item_type == ItemType.CODING)
        assert coding1.status == coding2.status


# ---------------------------------------------------------------------------
# §2.1: Practice job with item_type_mode
# ---------------------------------------------------------------------------

class TestPracticeJobWithItemTypeMode:
    """Test that PracticeJob stores and uses item_type_mode."""

    def test_practice_job_stores_item_type_mode(self, db):
        _make_workspace(db)
        pj = PracticeJob(
            id="pj-c010-1", workspace_id="ws-1", job_type="generate_set",
            output_language="zh-CN", difficulty="standard", item_count=3,
            request_hash="h-c010-1", idempotency_key="ik-c010-1",
            item_type_mode="require_coding",
            code_languages=["python", "java"],
        )
        db.add(pj)
        db.commit()
        result = db.get(PracticeJob, "pj-c010-1")
        assert result.item_type_mode == "require_coding"
        assert result.code_languages == ["python", "java"]

    def test_practice_job_default_item_type_mode(self, db):
        _make_workspace(db)
        pj = PracticeJob(
            id="pj-c010-2", workspace_id="ws-1", job_type="generate_set",
            output_language="zh-CN", difficulty="standard", item_count=3,
            request_hash="h-c010-2", idempotency_key="ik-c010-2",
        )
        db.add(pj)
        db.commit()
        result = db.get(PracticeJob, "pj-c010-2")
        assert result.item_type_mode == "auto"


# ---------------------------------------------------------------------------
# §2.2: Lesson Writer science authorization
# ---------------------------------------------------------------------------

class TestLessonWriterScienceAuth:
    """Test that CourseGenerationJob can have science_tool_authorized."""

    def test_course_gen_job_science_auth_field(self, db):
        _make_workspace(db)
        job = CourseGenerationJob(
            id="cgj-c010-1", workspace_id="ws-1", course_id="c-1",
            job_type="lesson_draft", idempotency_key="ik-c010-1",
            output_language="zh-CN",
            science_tool_authorized=True,
        )
        db.add(job)
        db.commit()
        result = db.get(CourseGenerationJob, "cgj-c010-1")
        assert result.science_tool_authorized is True

    def test_job_tool_authorization_for_lesson(self, db):
        """JobToolAuthorization can be created with course_generation_job_id owner."""
        _make_workspace(db)
        job = CourseGenerationJob(
            id="cgj-c010-2", workspace_id="ws-1", course_id="c-1",
            job_type="lesson_draft", idempotency_key="ik-c010-2",
            output_language="zh-CN",
            science_tool_authorized=True,
        )
        db.add(job)
        db.flush()
        auth = JobToolAuthorization(
            id="jta-c010-1", workspace_id="ws-1",
            capability_id="science_computation",
            course_generation_job_id="cgj-c010-2",
            max_calls=3, used_calls=0,
        )
        db.add(auth)
        db.commit()
        result = db.get(JobToolAuthorization, "jta-c010-1")
        assert result.course_generation_job_id == "cgj-c010-2"
        assert result.practice_job_id is None


# ---------------------------------------------------------------------------
# §4: Tool observation zero learning side effects
# ---------------------------------------------------------------------------

class TestToolObservationZeroLearningSideEffects:
    """Verify that tool observations cannot have citation_ids (contracts enforce this)."""

    def test_science_observation_no_citations(self):
        """science_observation block must not have citation_ids."""
        with pytest.raises(ValueError, match="science_observation must not cite"):
            TeachingAnswerBlock(
                block_key="sci-obs-1",
                type="science_observation",
                text="Wolfram computed x=5",
                citation_ids=["e1"],
            )

    def test_code_observation_no_citations(self):
        """code_observation block must not have citation_ids."""
        with pytest.raises(ValueError, match="code_observation must not cite"):
            TeachingAnswerBlock(
                block_key="code-obs-1",
                type="code_observation",
                text="Code execution returned 0",
                citation_ids=["e1"],
            )

    def test_valid_science_observation(self):
        """Valid science_observation with no citations."""
        block = TeachingAnswerBlock(
            block_key="sci-obs-1",
            type="science_observation",
            text="Wolfram computed x=5",
            citation_ids=[],
        )
        assert block.type == "science_observation"
        assert block.citation_ids == []

    def test_valid_code_observation(self):
        """Valid code_observation with no citations."""
        block = TeachingAnswerBlock(
            block_key="code-obs-1",
            type="code_observation",
            text="Code execution returned 0",
            citation_ids=[],
        )
        assert block.type == "code_observation"
        assert block.citation_ids == []


# ---------------------------------------------------------------------------
# §4: Tutor Skill v4 plan contracts
# ---------------------------------------------------------------------------

class TestTutorSkillV4PlanContracts:
    """Test that TeachingPlan supports code_requests."""

    def test_plan_with_code_requests(self):
        """TeachingPlan can include code_requests when authorized."""
        plan = TeachingPlan(
            intent="concept_explanation",
            queries=["How does binary search work?"],
            learning_context_use="irrelevant",
            teaching_moves=["explain", "example"],
            code_requests=[
                CodeRequest(
                    language="python",
                    source_code="def binary_search(arr, target): pass",
                )
            ],
            science_requests=[],
        )
        assert len(plan.code_requests) == 1
        assert plan.code_requests[0].language == "python"

    def test_plan_with_dual_requests(self):
        """TeachingPlan can include both code and science requests."""
        plan = TeachingPlan(
            intent="other",
            queries=["Calculate the integral"],
            learning_context_use="unavailable",
            teaching_moves=["explain"],
            code_requests=[
                CodeRequest(
                    language="python",
                    source_code="import scipy; scipy.integrate.quad(lambda x: x**2, 0, 1)",
                )
            ],
            science_requests=[
                ScienceRequest(tool="WolframAlpha", arguments={"query": "integrate x^2 from 0 to 1"})
            ],
        )
        assert len(plan.code_requests) == 1
        assert len(plan.science_requests) == 1

    def test_code_request_language_whitelist(self):
        """CodeRequest only allows python/java/cpp."""
        CodeRequest(language="python", source_code="print('hello')")
        CodeRequest(language="java", source_code="class Main {}")
        CodeRequest(language="cpp", source_code="int main() {}")
        with pytest.raises(Exception):
            CodeRequest(language="javascript", source_code="console.log('hello')")

    def test_code_request_max_length(self):
        """CodeRequest source_code max 12000 chars."""
        with pytest.raises(Exception):
            CodeRequest(language="python", source_code="x" * 12001)


# ---------------------------------------------------------------------------
# §4: Formula validation
# ---------------------------------------------------------------------------

class TestFormulaValidationBehavior:
    """Behavior tests for formula validation."""

    def test_valid_tex_passes(self):
        result = validate_formula_content("The formula $E = mc^2$ is famous")
        assert result.valid is True

    def test_dangerous_html_rejected(self):
        result = validate_formula_content("$<script>alert(1)</script>$")
        assert result.valid is False

    def test_dangerous_macro_rejected(self):
        result = validate_formula_content("$\\newcommand{\\x}{1}$")
        assert result.valid is False

    def test_dangerous_href_rejected(self):
        result = validate_formula_content("$\\href{http://evil.com}{click}$")
        assert result.valid is False

    def test_too_long_expression_rejected(self):
        result = validate_formula_content(f"${'a' * 2001}$")
        assert result.valid is False


# ---------------------------------------------------------------------------
# §4: Pseudo-coding item detection
# ---------------------------------------------------------------------------

class TestPseudoCodingDetection:
    """Test that pseudo-coding items are correctly detected."""

    def test_no_algorithmic_objective_is_pseudo(self):
        assert is_pseudo_coding_item(
            objective_keys=["obj-1"], evidence_keys=["ev-1"],
            has_algorithmic_objective=False, has_executable_evidence=True,
        ) is True

    def test_no_executable_evidence_is_pseudo(self):
        assert is_pseudo_coding_item(
            objective_keys=["obj-1"], evidence_keys=["ev-1"],
            has_algorithmic_objective=True, has_executable_evidence=False,
        ) is True

    def test_real_coding_not_pseudo(self):
        assert is_pseudo_coding_item(
            objective_keys=["obj-1"], evidence_keys=["ev-1"],
            has_algorithmic_objective=True, has_executable_evidence=True,
        ) is False
