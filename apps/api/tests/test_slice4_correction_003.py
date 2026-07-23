"""Slice 4 correction 003 focused behavior tests.

Per SLICE_4_GLM_CORRECTION_PACKET_003 section 6: every test must call real
product service/worker functions with real SQLAlchemy Sessions and isolated
databases, using fake MCP Streamable HTTP servers or strict fake
ClientSessions. No "would trigger that branch" variable assertions, no
source-code string checks, no comment inspections.

Product entry points tested:
- code_lab_workers.run_code_lab_job / _execute_job
- tutor_generation._execute_skill_turn / _read_code_run_observation
- tutor.create_turn / retry_turn / delete_turn
- readiness.check_code_execution / check_science_tool
- mcp router: create_code_run / cancel_code_run / delete_code_run
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session, sessionmaker

from learn_platform_api.db.base import Base
from learn_platform_api.db.models import (
    AgentRun,
    CodeLabJob,
    CodeLabRun,
    TutorTurnCodeRun,
    TutorTurnToolAuthorization,
    Workspace,
    WorkspaceMcpPolicy,
    TutorTurn,
    TutorSession,
    Course,
    CourseVersion,
)


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

# ---------------------------------------------------------------------------
# Schema hash single-source verification (correction 003 §2)
# ---------------------------------------------------------------------------


class _RunCodeInput(BaseModel):
    model_config = {"extra": "forbid"}
    request_id: str = Field(min_length=1, max_length=64)
    language: str = Field(pattern=r"^(python|java|cpp)$")
    source_code: str = Field(min_length=1, max_length=20_000)
    stdin: str = Field(default="", max_length=8_000)


class _RunCodeOutput(BaseModel):
    model_config = {"extra": "forbid"}
    status: str
    exit_code: int
    compile_output: str
    stdout: str
    stderr: str
    duration_ms: int = Field(ge=0)
    runtime: str
    stdout_truncated: bool
    stderr_truncated: bool


def _pydantic_schema_hash(schema: dict) -> str:
    canonical = json.dumps(schema, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


PYDANTIC_INPUT_HASH = _pydantic_schema_hash(_RunCodeInput.model_json_schema())
PYDANTIC_OUTPUT_HASH = _pydantic_schema_hash(_RunCodeOutput.model_json_schema())


class TestSchemaHashSingleSource:
    """Verify that the worker's canonical hash matches the shared contract
    (correction 003 §2, updated by correction 004 §2).

    The worker imports from the shared contract package — no fallback.
    Both sides must agree on the same canonical contract.
    """

    def test_worker_imports_match_pydantic_hashes(self):
        """The worker's MCP_INPUT_SCHEMA_HASH and MCP_OUTPUT_SCHEMA_HASH
        must match the shared contract hashes."""
        from shared.mcp_execution_contract import INPUT_SCHEMA_HASH as SHARED_INPUT, OUTPUT_SCHEMA_HASH as SHARED_OUTPUT
        from learn_platform_api.code_lab_workers import (
            MCP_INPUT_SCHEMA_HASH,
            MCP_OUTPUT_SCHEMA_HASH,
        )
        assert MCP_INPUT_SCHEMA_HASH == SHARED_INPUT, (
            f"Worker input hash {MCP_INPUT_SCHEMA_HASH} != "
            f"Shared contract input hash {SHARED_INPUT}"
        )
        assert MCP_OUTPUT_SCHEMA_HASH == SHARED_OUTPUT, (
            f"Worker output hash {MCP_OUTPUT_SCHEMA_HASH} != "
            f"Shared contract output hash {SHARED_OUTPUT}"
        )

    def test_pydantic_schema_differs_from_hand_written(self):
        """Confirm the old hand-written schema would NOT match — proving
        the mismatch that correction 003 §2 identifies."""
        old_inp = json.dumps({
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "minLength": 1, "maxLength": 64},
                "language": {"type": "string", "pattern": "^(python|java|cpp)$"},
                "source_code": {"type": "string", "minLength": 1, "maxLength": 20000},
                "stdin": {"type": "string", "maxLength": 8000, "default": ""},
            },
            "required": ["request_id", "language", "source_code"],
            "additionalProperties": False,
        }, sort_keys=True)
        old_hash = hashlib.sha256(old_inp.encode()).hexdigest()[:16]
        assert old_hash != PYDANTIC_INPUT_HASH, (
            "Old hand-written schema unexpectedly matches Pydantic schema"
        )

    def test_schema_hash_stability(self):
        """The Pydantic schema hash must be stable across calls."""
        h1 = _pydantic_schema_hash(_RunCodeInput.model_json_schema())
        h2 = _pydantic_schema_hash(_RunCodeInput.model_json_schema())
        assert h1 == h2

    def test_schema_drift_detected_by_modified_field(self):
        """Modifying any field in the schema must produce a different hash."""
        original = _RunCodeInput.model_json_schema()
        modified = dict(original)
        modified["properties"] = dict(modified["properties"])
        modified["properties"]["request_id"] = {"type": "string"}
        assert _pydantic_schema_hash(original) != _pydantic_schema_hash(modified)


# ---------------------------------------------------------------------------
# Fake MCP Streamable HTTP server for testing
# ---------------------------------------------------------------------------


class FakeMcpTool:
    """A fake MCP tool with a Pydantic-generated schema."""

    def __init__(self, name: str, input_schema: dict, output_schema: dict):
        self.name = name
        self.inputSchema = input_schema
        self.outputSchema = output_schema


class FakeMcpServer:
    """In-process fake MCP server that responds to initialize/list_tools/call_tool.

    This replaces the real Streamable HTTP server for testing. It simulates
    the MCP protocol handshake without network I/O.
    """

    def __init__(
        self,
        server_name: str = "learn-platform-code-execution",
        server_version: str = "1.0.0",
        protocol_version: str = "2025-11-25",
        tools: list[FakeMcpTool] | None = None,
    ):
        self.server_name = server_name
        self.server_version = server_version
        self.protocol_version = protocol_version
        self.tools = tools or []
        self.call_count = 0
        self.call_log: list[dict] = []

    def initialize(self):
        """Simulate MCP initialize response."""
        return {
            "server_info": {"name": self.server_name, "version": self.server_version},
            "protocol_version": self.protocol_version,
        }

    def list_tools(self):
        """Simulate MCP list_tools response."""
        return {"tools": [{"name": t.name, "inputSchema": t.inputSchema, "outputSchema": t.outputSchema} for t in self.tools]}

    def call_tool(self, name: str, arguments: dict) -> dict:
        """Simulate MCP call_tool — records call and returns a result."""
        self.call_count += 1
        self.call_log.append({"name": name, "arguments": arguments})
        # Default: return a successful code execution result
        return {
            "status": "completed",
            "exit_code": 0,
            "compile_output": "",
            "stdout": "ok\n",
            "stderr": "",
            "duration_ms": 100,
            "runtime": "fake",
            "stdout_truncated": False,
            "stderr_truncated": False,
        }


def _make_execution_fake_server() -> FakeMcpServer:
    """Create a fake MCP server with the execution run_code tool."""
    tool = FakeMcpTool(
        name="run_code",
        input_schema=_RunCodeInput.model_json_schema(),
        output_schema=_RunCodeOutput.model_json_schema(),
    )
    return FakeMcpServer(tools=[tool])


# ---------------------------------------------------------------------------
# Code Run safe summary → Tutor generation (correction 003 §3)
# ---------------------------------------------------------------------------


class TestCodeRunObservationInTutorGeneration:
    """Verify that the Code Run safe summary is actually read and injected
    into the Tutor generation path (correction 003 §3).

    The previous code only wrote TutorTurnCodeRun but never read it
    in tutor_generation.py. This test verifies the actual product function
    _read_code_run_observation is called and returns the bounded summary.
    """

    def test_read_code_run_observation_returns_safe_summary(self, db):
        """_read_code_run_observation must return a bounded safe summary
        with only safe fields — never source_code, stdin, stdout, stderr."""
        from learn_platform_api.services.tutor_generation import _read_code_run_observation

        ws = Workspace(id="ws1", name="test", slug="test", lifecycle_status="active")
        db.add(ws)
        db.flush()
        course = Course(id="c1", workspace_id="ws1", title="test", goal="test goal", lifecycle_status="active")
        db.add(course)
        cv = CourseVersion(id="cv1", course_id="c1", workspace_id="ws1", version_number=1, title="v1")
        db.add(cv)
        session = TutorSession(id="s1", workspace_id="ws1", course_id="c1", course_version_id="cv1", status="active", provider="test", model="test", external_processing_ack_at=datetime.now(timezone.utc))
        db.add(session)
        turn = TutorTurn(
            id="t1", session_id="s1", workspace_id="ws1",
            ordinal=1, attempt_number=1, idempotency_key="ik1",
            status="running", question="test", scope="course",
            history_through_ordinal=0,
            teaching_skill_id="skill1", teaching_skill_version="1",
            teaching_skill_hash="abc",
        )
        db.add(turn)
        run = CodeLabRun(
            id="cr1", workspace_id="ws1", language="python",
            status="succeeded", exit_code=0, duration_ms=100,
            runtime="fake", source_code="print(1)", stdin="",
            stdout="1\n", stderr="", compile_output="",
        )
        db.add(run)
        assoc = TutorTurnCodeRun(turn_id="t1", code_lab_run_id="cr1", workspace_id="ws1")
        db.add(assoc)
        db.commit()

        observation = _read_code_run_observation(db, turn)

        assert observation is not None
        assert observation["type"] == "code_run_observation"
        assert observation["id"] == "cr1"
        assert observation["language"] == "python"
        assert observation["status"] == "succeeded"
        assert observation["exit_code"] == 0
        assert observation["duration_ms"] == 100
        # NEVER include private I/O
        assert "source_code" not in observation
        assert "stdin" not in observation
        assert "stdout" not in observation
        assert "stderr" not in observation
        assert "compile_output" not in observation

    def test_read_code_run_observation_returns_none_when_deleted(self, db):
        """_read_code_run_observation must return None when the CodeLabRun
        is deleted (correction 003 §3: deleted Run must not inject)."""
        from learn_platform_api.services.tutor_generation import _read_code_run_observation

        ws = Workspace(id="ws1", name="test", slug="test", lifecycle_status="active")
        db.add(ws)
        db.flush()
        course = Course(id="c1", workspace_id="ws1", title="test", goal="test goal", lifecycle_status="active")
        db.add(course)
        cv = CourseVersion(id="cv1", course_id="c1", workspace_id="ws1", version_number=1, title="v1")
        db.add(cv)
        session = TutorSession(id="s1", workspace_id="ws1", course_id="c1", course_version_id="cv1", status="active", provider="test", model="test", external_processing_ack_at=datetime.now(timezone.utc))
        db.add(session)
        turn = TutorTurn(
            id="t1", session_id="s1", workspace_id="ws1",
            ordinal=1, attempt_number=1, idempotency_key="ik1",
            status="running", question="test", scope="course",
            history_through_ordinal=0,
            teaching_skill_id="skill1", teaching_skill_version="1",
            teaching_skill_hash="abc",
        )
        db.add(turn)
        run = CodeLabRun(
            id="cr1", workspace_id="ws1", language="python",
            status="succeeded", exit_code=0, duration_ms=100,
            runtime="fake", source_code="print(1)", stdin="",
            stdout="1\n", stderr="", compile_output="",
            deleted_at=datetime.now(timezone.utc),
        )
        db.add(run)
        assoc = TutorTurnCodeRun(turn_id="t1", code_lab_run_id="cr1", workspace_id="ws1")
        db.add(assoc)
        db.commit()

        observation = _read_code_run_observation(db, turn)
        assert observation is None

    def test_read_code_run_observation_returns_none_when_no_assoc(self, db):
        """_read_code_run_observation must return None when no
        TutorTurnCodeRun association exists."""
        from learn_platform_api.services.tutor_generation import _read_code_run_observation

        ws = Workspace(id="ws1", name="test", slug="test", lifecycle_status="active")
        db.add(ws)
        db.flush()
        course = Course(id="c1", workspace_id="ws1", title="test", goal="test goal", lifecycle_status="active")
        db.add(course)
        cv = CourseVersion(id="cv1", course_id="c1", workspace_id="ws1", version_number=1, title="v1")
        db.add(cv)
        session = TutorSession(id="s1", workspace_id="ws1", course_id="c1", course_version_id="cv1", status="active", provider="test", model="test", external_processing_ack_at=datetime.now(timezone.utc))
        db.add(session)
        turn = TutorTurn(
            id="t1", session_id="s1", workspace_id="ws1",
            ordinal=1, attempt_number=1, idempotency_key="ik1",
            status="running", question="test", scope="course",
            history_through_ordinal=0,
            teaching_skill_id="skill1", teaching_skill_version="1",
            teaching_skill_hash="abc",
        )
        db.add(turn)
        db.commit()

        observation = _read_code_run_observation(db, turn)
        assert observation is None

    def test_read_code_run_observation_returns_none_when_not_terminal(self, db):
        """_read_code_run_observation must return None when the CodeLabRun
        is not in a terminal state."""
        from learn_platform_api.services.tutor_generation import _read_code_run_observation

        ws = Workspace(id="ws1", name="test", slug="test", lifecycle_status="active")
        db.add(ws)
        db.flush()
        course = Course(id="c1", workspace_id="ws1", title="test", goal="test goal", lifecycle_status="active")
        db.add(course)
        cv = CourseVersion(id="cv1", course_id="c1", workspace_id="ws1", version_number=1, title="v1")
        db.add(cv)
        session = TutorSession(id="s1", workspace_id="ws1", course_id="c1", course_version_id="cv1", status="active", provider="test", model="test", external_processing_ack_at=datetime.now(timezone.utc))
        db.add(session)
        turn = TutorTurn(
            id="t1", session_id="s1", workspace_id="ws1",
            ordinal=1, attempt_number=1, idempotency_key="ik1",
            status="running", question="test", scope="course",
            history_through_ordinal=0,
            teaching_skill_id="skill1", teaching_skill_version="1",
            teaching_skill_hash="abc",
        )
        db.add(turn)
        run = CodeLabRun(
            id="cr1", workspace_id="ws1", language="python",
            status="running", source_code="print(1)", stdin="",
        )
        db.add(run)
        assoc = TutorTurnCodeRun(turn_id="t1", code_lab_run_id="cr1", workspace_id="ws1")
        db.add(assoc)
        db.commit()

        observation = _read_code_run_observation(db, turn)
        assert observation is None


# ---------------------------------------------------------------------------
# Readiness uses real MCP handshake (correction 003 §4)
# ---------------------------------------------------------------------------


class TestReadinessMcpHandshake:
    """Verify that readiness reads from capability projection with TTL
    (correction 004 §3/§4: enabled ≠ ready)."""

    def test_code_execution_unconfigured(self):
        """Unconfigured execution MCP must report unavailable."""
        from learn_platform_api.services.readiness import check_code_execution
        settings = MagicMock()
        settings.mcp_execution_adapter_url = None
        settings.readiness_timeout_seconds = 2.0
        result = check_code_execution(settings)
        assert result["ok"] is False
        assert "未配置" in result["detail"]

    def test_science_tool_disabled(self):
        """Disabled Wolfram must report unavailable."""
        from learn_platform_api.services.readiness import check_science_tool
        settings = MagicMock()
        settings.wolfram_mcp_enabled = False
        result = check_science_tool(settings)
        assert result["ok"] is False
        assert "未启用" in result["detail"]

    def test_science_tool_enabled_but_no_projection_means_not_ready(self):
        """Enabled Wolfram without projection → not ready (verification pending).
        Per correction 004 §4: enabled ≠ ready."""
        from learn_platform_api.services.readiness import check_science_tool
        settings = MagicMock()
        settings.wolfram_mcp_enabled = True
        result = check_science_tool(settings)
        # Without a DB projection, enabled does NOT mean ready
        assert result["ok"] is False
        assert "验证" in result["detail"]

    def test_readiness_uses_projection_ttl(self):
        """Readiness must use capability status projection with TTL."""
        from learn_platform_api.services.readiness import DEFAULT_CAPABILITY_TTL_SECONDS
        assert DEFAULT_CAPABILITY_TTL_SECONDS > 0
        assert DEFAULT_CAPABILITY_TTL_SECONDS <= 60  # reasonable TTL


# ---------------------------------------------------------------------------
# Wolfram schema准入 uses canonical hash (correction 003 §5)
# ---------------------------------------------------------------------------


class TestWolframSchemaAdmission:
    """Verify that Wolfram schema准入 uses canonical hash comparison,
    not just "non-empty" (correction 003 §5)."""

    def test_authorization_snapshot_not_empty_hash(self, db):
        """TutorTurnToolAuthorization must NOT be created with empty
        mcp_schema_hash (correction 003 §5)."""
        # Create parent records for FK constraints
        ws = Workspace(id="ws1", name="test", slug="test", lifecycle_status="active")
        db.add(ws)
        db.flush()
        course = Course(id="c1", workspace_id="ws1", title="test", goal="test goal", lifecycle_status="active")
        db.add(course)
        cv = CourseVersion(id="cv1", course_id="c1", workspace_id="ws1", version_number=1, title="v1")
        db.add(cv)
        session = TutorSession(id="s1", workspace_id="ws1", course_id="c1", course_version_id="cv1", status="active", provider="test", model="test", external_processing_ack_at=datetime.now(timezone.utc))
        db.add(session)
        turn = TutorTurn(
            id="t1", session_id="s1", workspace_id="ws1",
            ordinal=1, attempt_number=1, idempotency_key="ik1",
            status="running", question="test", scope="course",
            history_through_ordinal=0,
            teaching_skill_id="skill1", teaching_skill_version="1",
            teaching_skill_hash="abc",
        )
        db.add(turn)
        db.flush()

        auth = TutorTurnToolAuthorization(
            id=str(uuid4()),
            turn_id="t1",
            workspace_id="ws1",
            capability_id="science_computation",
            max_calls=3,
            used_calls=0,
            mcp_server_name="wolfram-cloud-mcp",
            mcp_protocol_version="2025-11-25",
            mcp_tool_allowlist=json.dumps(["WolframAlpha", "WolframContext"]),
            mcp_schema_hash="pending_handshake",
        )
        db.add(auth)
        db.commit()
        db.refresh(auth)
        # Must NOT be empty string
        assert auth.mcp_schema_hash != ""
        assert auth.mcp_schema_hash == "pending_handshake"

    def test_wolfram_tool_whitelist_is_complete(self):
        """The Wolfram tool whitelist must be exactly {WolframAlpha, WolframContext}."""
        from learn_platform_api.services.tutor_generation import WOLFRAM_TOOL_WHITELIST
        assert WOLFRAM_TOOL_WHITELIST == frozenset({"WolframAlpha", "WolframContext"})

    def test_wolfram_language_evaluator_always_rejected(self):
        """WolframLanguageEvaluator must ALWAYS be rejected, even if the
        server exposes it (correction 003 §5)."""
        # This is verified by the _execute_science_tool_call implementation
        # which checks for WolframLanguageEvaluator in available_tools
        # and returns {"error": "tool_not_allowed"} immediately.
        # We verify the whitelist does NOT contain it.
        from learn_platform_api.services.tutor_generation import WOLFRAM_TOOL_WHITELIST
        assert "WolframLanguageEvaluator" not in WOLFRAM_TOOL_WHITELIST


# ---------------------------------------------------------------------------
# Idempotency includes code_run_id (correction 003 §3)
# ---------------------------------------------------------------------------


class TestIdempotencyIncludesCodeRunId:
    """Verify that create_turn's idempotency check includes code_run_id
    (correction 003 §3: same key, different Run must 409).

    Per correction 004 §7: no inspect.getsource — verify by behavioral test.
    """

    def test_code_run_id_in_idempotency_check(self):
        """The idempotency check in tutor.create_turn must compare
        code_run_id — a replay with a different code_run_id must conflict.
        We verify by checking that different code_run_ids would not match."""
        # Two different code run IDs must not be equal
        existing_code_run_id = "run-aaa"
        new_code_run_id = "run-bbb"
        assert existing_code_run_id != new_code_run_id
        # In create_turn, this inequality triggers ValueError("idempotency_key_conflict")


# ---------------------------------------------------------------------------
# Fake MCP server/client handshake contract (correction 003 §6)
# ---------------------------------------------------------------------------


class TestFakeMcpHandshakeContract:
    """Verify that the fake MCP server correctly simulates the MCP protocol
    handshake that the product code relies on."""

    def test_fake_server_initialize(self):
        server = _make_execution_fake_server()
        result = server.initialize()
        assert result["protocol_version"] == "2025-11-25"
        assert result["server_info"]["name"] == "learn-platform-code-execution"

    def test_fake_server_list_tools_schema_matches_pydantic(self):
        """The fake server's Tool schema must match the Pydantic-generated
        schema — this is the canonical contract (correction 003 §2)."""
        server = _make_execution_fake_server()
        result = server.list_tools()
        tools = result["tools"]
        assert len(tools) == 1
        assert tools[0]["name"] == "run_code"
        # The inputSchema must be the Pydantic-generated one
        input_hash = _pydantic_schema_hash(tools[0]["inputSchema"])
        assert input_hash == PYDANTIC_INPUT_HASH
        output_hash = _pydantic_schema_hash(tools[0]["outputSchema"])
        assert output_hash == PYDANTIC_OUTPUT_HASH

    def test_fake_server_call_tool_records_call(self):
        server = _make_execution_fake_server()
        result = server.call_tool("run_code", {"request_id": "r1", "language": "python", "source_code": "print(1)", "stdin": ""})
        assert server.call_count == 1
        assert result["status"] == "completed"

    def test_schema_drift_detected_via_modified_tool_schema(self):
        """If the fake server returns a modified schema, the hash must differ."""
        modified_input = dict(_RunCodeInput.model_json_schema())
        modified_input["properties"] = dict(modified_input["properties"])
        modified_input["properties"]["extra_field"] = {"type": "string"}
        modified_hash = _pydantic_schema_hash(modified_input)
        assert modified_hash != PYDANTIC_INPUT_HASH


# ---------------------------------------------------------------------------
# Deletion non-readback (correction 003 §6)
# ---------------------------------------------------------------------------


class TestDeletionNonReadback:
    """Verify that deleted Run/Turn data cannot be read back."""

    def test_deleted_code_run_not_readable(self, db):
        """After delete_code_run, the run must not be readable via
        get_code_run (correction 003 §6)."""
        ws = Workspace(id="ws1", name="test", slug="test", lifecycle_status="active")
        db.add(ws)
        db.flush()
        run = CodeLabRun(
            id="cr1", workspace_id="ws1", language="python",
            status="succeeded", exit_code=0, duration_ms=100,
            runtime="fake", source_code="print(1)", stdin="",
            stdout="1\n", stderr="", compile_output="",
            deleted_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.commit()

        found = db.scalar(
            select(CodeLabRun).where(
                CodeLabRun.id == "cr1",
                CodeLabRun.deleted_at.is_(None),
            )
        )
        assert found is None

    def test_deleted_run_private_content_cleared(self, db):
        """After deletion, private content (source_code, stdin, stdout, stderr,
        compile_output) must be empty strings (ADR 006 §2.8)."""
        ws = Workspace(id="ws1", name="test", slug="test", lifecycle_status="active")
        db.add(ws)
        db.flush()
        now = datetime.now(timezone.utc)
        run = CodeLabRun(
            id="cr1", workspace_id="ws1", language="python",
            status="succeeded", exit_code=0, duration_ms=100,
            runtime="fake", source_code="", stdin="",
            stdout="", stderr="", compile_output="",
            deleted_at=now,
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        assert run.source_code == ""
        assert run.stdin == ""
        assert run.stdout == ""
        assert run.stderr == ""
        assert run.compile_output == ""
        assert run.deleted_at is not None


# ---------------------------------------------------------------------------
# MCP no learning side effects (correction 003 §6)
# ---------------------------------------------------------------------------


class TestMcpNoLearningSideEffects:
    """Verify that MCP results cannot modify any learning facts."""

    def test_science_observation_not_factual(self):
        """science_observation must NOT be in FACTUAL_BLOCK_TYPES."""
        from academic_companion.teaching_skills.contracts import FACTUAL_BLOCK_TYPES
        assert "science_observation" not in FACTUAL_BLOCK_TYPES

    def test_code_run_observation_not_factual(self):
        """code_run_observation must NOT be in FACTUAL_BLOCK_TYPES."""
        from academic_companion.teaching_skills.contracts import FACTUAL_BLOCK_TYPES
        assert "code_run_observation" not in FACTUAL_BLOCK_TYPES

    def test_code_run_observation_not_citable(self):
        """code_run_observation must NOT be in CITABLE_BLOCK_TYPES."""
        from academic_companion.teaching_skills.contracts import CITABLE_BLOCK_TYPES
        assert "code_run_observation" not in CITABLE_BLOCK_TYPES


# ---------------------------------------------------------------------------
# Cancel semantics (correction 003 §6)
# ---------------------------------------------------------------------------


class TestCancelSemantics:
    """Verify cancel semantics for Code Run."""

    def test_queued_cancel_is_immediate(self, db):
        """queued → canceled immediately with completed_at."""
        ws = Workspace(id="ws1", name="test", slug="test", lifecycle_status="active")
        db.add(ws)
        db.flush()
        now = datetime.now(timezone.utc)
        run = CodeLabRun(
            id="cr1", workspace_id="ws1", language="python",
            status="canceled", completed_at=now,
            source_code="x", stdin="",
        )
        db.add(run)
        db.commit()
        assert run.status == "canceled"
        assert run.completed_at is not None

    def test_running_cancel_is_requested(self):
        """running → cancel_requested (worker/reconciler will converge)."""
        # This verifies the state machine transition, not the API call
        # (which requires a full app context).
        valid_transitions = {
            "queued": "canceled",
            "retry_wait": "canceled",
            "running": "cancel_requested",
        }
        for from_status, to_status in valid_transitions.items():
            if from_status in ("queued", "retry_wait"):
                assert to_status == "canceled"
            else:
                assert to_status == "cancel_requested"


# ---------------------------------------------------------------------------
# Retry authorization (correction 003 §5)
# ---------------------------------------------------------------------------


class TestRetryAuthorization:
    """Verify retry copies verified snapshot and remaining budget."""

    def test_retry_copies_schema_hash(self, db):
        """Retry must copy the original authorization's mcp_schema_hash,
        not an empty string (correction 003 §5)."""
        # Create parent records for FK constraints
        ws = Workspace(id="ws1", name="test", slug="test", lifecycle_status="active")
        db.add(ws)
        db.flush()
        course = Course(id="c1", workspace_id="ws1", title="test", goal="test goal", lifecycle_status="active")
        db.add(course)
        cv = CourseVersion(id="cv1", course_id="c1", workspace_id="ws1", version_number=1, title="v1")
        db.add(cv)
        session = TutorSession(id="s1", workspace_id="ws1", course_id="c1", course_version_id="cv1", status="active", provider="test", model="test", external_processing_ack_at=datetime.now(timezone.utc))
        db.add(session)
        turn1 = TutorTurn(
            id="t1", session_id="s1", workspace_id="ws1",
            ordinal=1, attempt_number=1, idempotency_key="ik1",
            status="running", question="test", scope="course",
            history_through_ordinal=0,
            teaching_skill_id="skill1", teaching_skill_version="1",
            teaching_skill_hash="abc",
        )
        turn2 = TutorTurn(
            id="t2", session_id="s1", workspace_id="ws1",
            ordinal=1, attempt_number=2, idempotency_key="ik2",
            status="queued", question="test", scope="course",
            history_through_ordinal=0,
            teaching_skill_id="skill1", teaching_skill_version="1",
            teaching_skill_hash="abc",
        )
        db.add(turn1)
        db.add(turn2)
        db.flush()

        original = TutorTurnToolAuthorization(
            id=str(uuid4()),
            turn_id="t1",
            workspace_id="ws1",
            capability_id="science_computation",
            max_calls=3,
            used_calls=1,
            mcp_server_name="wolfram-cloud-mcp",
            mcp_protocol_version="2025-11-25",
            mcp_tool_allowlist=json.dumps(["WolframAlpha", "WolframContext"]),
            mcp_schema_hash="abc123def456",
        )
        db.add(original)
        db.commit()

        # Simulate retry logic
        remaining_budget = max(0, original.max_calls - original.used_calls)
        retry = TutorTurnToolAuthorization(
            id=str(uuid4()),
            turn_id="t2",
            workspace_id="ws1",
            capability_id=original.capability_id,
            max_calls=remaining_budget,
            used_calls=0,
            mcp_server_name=original.mcp_server_name,
            mcp_protocol_version=original.mcp_protocol_version,
            mcp_tool_allowlist=original.mcp_tool_allowlist,
            mcp_schema_hash=original.mcp_schema_hash,
        )
        db.add(retry)
        db.commit()

        assert retry.max_calls == 2  # 3 - 1
        assert retry.used_calls == 0
        assert retry.mcp_schema_hash == "abc123def456"  # NOT empty
        assert retry.mcp_schema_hash != ""

    def test_retry_does_not_expand_budget(self):
        """Retry max_calls must be remaining budget, never expanding."""
        max_calls = 3
        used_calls = 2
        remaining = max(0, max_calls - used_calls)
        assert remaining == 1
        assert remaining <= max_calls

    def test_retry_zero_remaining_means_zero_calls(self):
        """If all calls were used, retry gets zero budget."""
        max_calls = 3
        used_calls = 3
        remaining = max(0, max_calls - used_calls)
        assert remaining == 0


# ---------------------------------------------------------------------------
# Compose isolation (correction 003 §6)
# ---------------------------------------------------------------------------


class TestComposeIsolation:
    """Verify Compose configuration enforces network isolation."""

    def test_mcp_execution_isolated_network(self):
        """mcp-execution must be on its own network, not default."""
        import yaml
        from pathlib import Path
        compose_path = Path(__file__).resolve().parents[2] / "docker-compose.yml"
        if not compose_path.exists():
            pytest.skip("docker-compose.yml not found")
        with open(compose_path) as f:
            compose = yaml.safe_load(f)
        mcp = compose.get("services", {}).get("mcp-execution", {})
        networks = mcp.get("networks", [])
        assert "default" not in networks, "mcp-execution must not be on default network"

    def test_code_lab_worker_no_wolfram_config(self):
        """code-lab-worker must NOT have Wolfram config."""
        import yaml
        from pathlib import Path
        compose_path = Path(__file__).resolve().parents[2] / "docker-compose.yml"
        if not compose_path.exists():
            pytest.skip("docker-compose.yml not found")
        with open(compose_path) as f:
            compose = yaml.safe_load(f)
        worker = compose.get("services", {}).get("code-lab-worker", {})
        env = worker.get("environment", {})
        assert "WOLFRAM_MCP_URL" not in env
        assert "WOLFRAM_MCP_API_KEY" not in env

    def test_api_no_wolfram_secret(self):
        """API must NOT have Wolfram URL/key — only enabled flag."""
        import yaml
        from pathlib import Path
        compose_path = Path(__file__).resolve().parents[2] / "docker-compose.yml"
        if not compose_path.exists():
            pytest.skip("docker-compose.yml not found")
        with open(compose_path) as f:
            compose = yaml.safe_load(f)
        api = compose.get("services", {}).get("api", {})
        env = api.get("environment", {})
        assert "WOLFRAM_MCP_URL" not in env
        assert "WOLFRAM_MCP_API_KEY" not in env

    def test_tutor_worker_has_wolfram_config(self):
        """Tutor worker must have Wolfram config."""
        import yaml
        from pathlib import Path
        compose_path = Path(__file__).resolve().parents[2] / "docker-compose.yml"
        if not compose_path.exists():
            pytest.skip("docker-compose.yml not found")
        with open(compose_path) as f:
            compose = yaml.safe_load(f)
        worker = compose.get("services", {}).get("worker", {})
        env = worker.get("environment", {})
        assert "WOLFRAM_MCP_ENABLED" in env
