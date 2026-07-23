"""Batch B focused tests: ORM models, schema validation, and migration contract.

Uses SQLite in-memory for ORM model validation (no Postgres needed).
The AgentRun 4-way XOR constraint uses Postgres-specific ::int cast,
so SQLite tests use a filtered subset of tables. The migration itself
is tested separately via Alembic upgrade/downgrade against Postgres.
"""

import pytest
from uuid import uuid4

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from learn_platform_api.db.base import Base
from learn_platform_api.db.models import (
    AgentRun,
    CodeLabJob,
    CodeLabRun,
    TutorTurnCodeRun,
    TutorTurnToolAuthorization,
    Workspace,
    WorkspaceMcpPolicy,
)
from learn_platform_api.schemas.mcp import (
    CodeRunCreate,
    CodeRunSafeSummary,
    McpPolicyPatch,
    ScienceToolAuthorizationRead,
)
from learn_platform_api.schemas.tutor import TutorTurnCreate


# ---------------------------------------------------------------------------
# SQLite in-memory fixture — only create Slice 4 tables (avoid AgentRun
# Postgres-specific constraint)
# ---------------------------------------------------------------------------

_SLICE4_TABLES = [
    "workspaces",
    "source_documents",
    "document_versions",
    "document_chunks",
    "document_parse_reports",
    "ingestion_jobs",
    "ingestion_batches",
    "ingestion_batch_items",
    "rag_query_traces",
    "rag_answer_traces",
    "courses",
    "course_versions",
    "course_version_sources",
    "course_sections",
    "course_section_citations",
    "lessons",
    "lesson_versions",
    "lesson_citations",
    "course_generation_jobs",
    "course_generation_job_sources",
    "tutor_sessions",
    "tutor_turns",
    "tutor_turn_citations",
    "practice_jobs",
    "practice_job_sources",
    "practice_sets",
    "practice_items",
    "practice_item_citations",
    "practice_attempts",
    "practice_feedback",
    "learning_targets",
    "practice_item_targets",
    "learning_events",
    "mastery_signals",
    "mastery_states",
    "weaknesses",
    "review_items",
    "review_actions",
    "learning_projection_jobs",
    "learning_memories",
    "learning_memory_sources",
    "learning_memory_revisions",
    "learning_memory_policies",
    "lesson_completions",
    "workspace_mcp_policies",
    "code_lab_runs",
    "code_lab_jobs",
    "tutor_turn_tool_authorizations",
    "tutor_turn_code_runs",
]


@pytest.fixture
def db():
    engine = create_engine("sqlite://", echo=False)

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    tables_to_create = [t for t in Base.metadata.sorted_tables if t.name in _SLICE4_TABLES]
    Base.metadata.create_all(engine, tables=tables_to_create)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _uuid() -> str:
    return str(uuid4())


# ---------------------------------------------------------------------------
# ORM Model Tests
# ---------------------------------------------------------------------------


class TestWorkspaceMcpPolicyModel:
    def test_create_and_read(self, db):
        ws_id = _uuid()
        ws = Workspace(id=ws_id, name="test", slug="test", lifecycle_status="active")
        db.add(ws)
        db.flush()

        policy = WorkspaceMcpPolicy(workspace_id=ws_id, code_execution_enabled=0)
        db.add(policy)
        db.flush()
        db.refresh(policy)

        assert policy.workspace_id == ws_id
        assert policy.code_execution_enabled == 0
        assert policy.revision == 1

    def test_default_code_execution_disabled(self, db):
        ws_id = _uuid()
        ws = Workspace(id=ws_id, name="test2", slug="test2", lifecycle_status="active")
        db.add(ws)
        db.flush()

        policy = WorkspaceMcpPolicy(workspace_id=ws_id)
        db.add(policy)
        db.flush()
        assert policy.code_execution_enabled == 0


class TestCodeLabRunModel:
    def test_create_minimal(self, db):
        ws_id = _uuid()
        ws = Workspace(id=ws_id, name="test", slug="test", lifecycle_status="active")
        db.add(ws)
        db.flush()

        run = CodeLabRun(
            id=_uuid(),
            workspace_id=ws_id,
            language="python",
            source_code="print('hello')",
            stdin="",
            status="queued",
        )
        db.add(run)
        db.flush()
        db.refresh(run)

        assert run.language == "python"
        assert run.status == "queued"
        assert run.course_id is None
        assert run.stdout_truncated == 0
        assert run.stderr_truncated == 0

    def test_create_with_navigation(self, db):
        ws_id = _uuid()
        ws = Workspace(id=ws_id, name="test", slug="test", lifecycle_status="active")
        db.add(ws)
        db.flush()

        run = CodeLabRun(
            id=_uuid(),
            workspace_id=ws_id,
            language="java",
            source_code="class Main {}",
            stdin="",
            status="queued",
        )
        db.add(run)
        db.flush()
        assert run.language == "java"


class TestCodeLabJobModel:
    def test_create_and_read(self, db):
        ws_id = _uuid()
        ws = Workspace(id=ws_id, name="test", slug="test", lifecycle_status="active")
        db.add(ws)
        db.flush()

        run = CodeLabRun(
            id=_uuid(),
            workspace_id=ws_id,
            language="cpp",
            source_code="int main() {}",
            stdin="",
            status="queued",
        )
        db.add(run)
        db.flush()

        job = CodeLabJob(
            id=_uuid(),
            workspace_id=ws_id,
            run_id=run.id,
            idempotency_key="ik-001",
            request_hash="abc123",
            status="queued",
        )
        db.add(job)
        db.flush()
        db.refresh(job)

        assert job.run_id == run.id
        assert job.status == "queued"
        assert job.attempt_count == 0


class TestTutorTurnToolAuthorizationModel:
    def test_model_construction(self):
        auth = TutorTurnToolAuthorization(
            id=_uuid(),
            turn_id=_uuid(),
            workspace_id=_uuid(),
            capability_id="science_computation",
            max_calls=3,
            used_calls=0,
        )
        assert auth.capability_id == "science_computation"
        assert auth.max_calls == 3
        assert auth.used_calls == 0


class TestTutorTurnCodeRunModel:
    def test_model_construction(self):
        tcr = TutorTurnCodeRun(
            id=_uuid(),
            turn_id=_uuid(),
            code_lab_run_id=_uuid(),
            workspace_id=_uuid(),
        )
        assert tcr.turn_id is not None
        assert tcr.code_lab_run_id is not None


# ---------------------------------------------------------------------------
# Schema Validation Tests
# ---------------------------------------------------------------------------


class TestCodeRunCreateSchema:
    def test_valid_python(self):
        req = CodeRunCreate(language="python", source_code="print('hi')")
        assert req.language == "python"
        assert req.stdin == ""

    def test_valid_java(self):
        req = CodeRunCreate(language="java", source_code="class Main {}")
        assert req.language == "java"

    def test_valid_cpp(self):
        req = CodeRunCreate(language="cpp", source_code="int main() {}")
        assert req.language == "cpp"

    def test_invalid_language_rejected(self):
        with pytest.raises(Exception):
            CodeRunCreate(language="javascript", source_code="console.log('hi')")

    def test_extra_field_forbidden(self):
        with pytest.raises(Exception):
            CodeRunCreate(language="python", source_code="x", timeout=30)

    def test_source_code_too_long(self):
        with pytest.raises(Exception):
            CodeRunCreate(language="python", source_code="x" * 20001)

    def test_stdin_too_long(self):
        with pytest.raises(Exception):
            CodeRunCreate(language="python", source_code="x", stdin="y" * 8001)


class TestMcpPolicyPatchSchema:
    def test_valid_patch(self):
        patch = McpPolicyPatch(code_execution_enabled=True)
        assert patch.code_execution_enabled is True

    def test_extra_field_forbidden(self):
        with pytest.raises(Exception):
            McpPolicyPatch(code_execution_enabled=True, custom_field="x")


class TestScienceToolAuthorizationReadSchema:
    def test_valid(self):
        auth = ScienceToolAuthorizationRead(
            capability_id="science_computation",
            max_calls=3,
            used_calls=0,
            authorized=True,
        )
        assert auth.capability_id == "science_computation"
        assert auth.max_calls == 3


class TestTutorTurnCreateScienceTool:
    def test_default_false(self):
        req = TutorTurnCreate(question="What is 2+2?", scope="course")
        assert req.science_tool_authorized is False

    def test_explicit_true(self):
        req = TutorTurnCreate(
            question="Solve x^2 - 4 = 0",
            scope="course",
            science_tool_authorized=True,
        )
        assert req.science_tool_authorized is True

    def test_extra_field_still_forbidden(self):
        with pytest.raises(Exception):
            TutorTurnCreate(
                question="test",
                scope="course",
                science_tool_authorized=True,
                custom_server_url="http://evil.com",
            )


class TestCodeRunSafeSummary:
    def test_no_private_io(self):
        summary = CodeRunSafeSummary(
            id="run-1",
            language="python",
            status="completed",
            exit_code=0,
            duration_ms=100,
            runtime="judge0-lang-71",
        )
        data = summary.model_dump()
        assert "source_code" not in data
        assert "stdout" not in data
        assert "stderr" not in data
        assert "compile_output" not in data


# ---------------------------------------------------------------------------
# AgentRun 4-way owner constraint (model-level)
# ---------------------------------------------------------------------------


class TestAgentRunFourWayOwner:
    def test_code_lab_job_id_column_exists(self):
        assert hasattr(AgentRun, "code_lab_job_id")

    def test_all_four_owner_columns_exist(self):
        assert hasattr(AgentRun, "course_generation_job_id")
        assert hasattr(AgentRun, "tutor_turn_id")
        assert hasattr(AgentRun, "practice_job_id")
        assert hasattr(AgentRun, "code_lab_job_id")

    def test_check_constraint_exists(self):
        constraints = AgentRun.__table_args__
        has_constraint = any(
            getattr(c, "name", None) == "ck_agent_runs_one_owner"
            for c in (constraints or ())
        )
        assert has_constraint, "ck_agent_runs_one_owner check constraint must exist on AgentRun"
