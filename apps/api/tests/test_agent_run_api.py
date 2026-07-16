from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from learn_platform_api.db.models import (
    AgentRun,
    AgentToolCall,
    Course,
    CourseGenerationJob,
    CourseSection,
    CourseVersion,
    Lesson,
    TutorSession,
    TutorTurn,
    Workspace,
)

# Keys that must never appear in a safe run summary projection. The assertion is
# on the full (recursively collected) JSON key set, not just null values: a
# forbidden field must be entirely absent.
FORBIDDEN_KEYS = {
    "prompt", "system_prompt", "system", "messages", "question", "answer", "answer_blocks",
    "draft", "blocks", "coverage", "coverage_plan", "evidence", "chunk", "content", "text",
    "original_storage_uri", "parsed_storage_uri", "path", "file_path", "absolute_path",
    "input_hash", "tool_input", "input", "provider", "model", "base_url", "api_key",
    "url", "connection", "connection_string", "log", "logs", "raw", "raw_response",
    "query", "queries", "question_hash", "answer_hash", "sha256", "byte_size",
    "environment", "env", "idempotency_key", "worker_id", "lease_expires_at",
    "external_processing_ack_at", "key", "secret", "token",
}


def _collect_keys(obj, into=None):
    into = set() if into is None else into
    if isinstance(obj, dict):
        into.update(obj.keys())
        for value in obj.values():
            _collect_keys(value, into)
    elif isinstance(obj, list):
        for value in obj:
            _collect_keys(value, into)
    return into


def _seed_course(db: Session, *, name: str = "Runs workspace", slug: str = "runs-workspace", title: str = "Algorithms"):
    workspace = Workspace(name=name, slug=slug)
    db.add(workspace); db.flush()
    course = Course(workspace_id=workspace.id, title=title, goal="Learn")
    db.add(course); db.flush()
    version = CourseVersion(course_id=course.id, workspace_id=workspace.id, version_number=1, status="active", title=course.title)
    db.add(version); db.flush()
    course.current_active_version_id = version.id
    section = CourseSection(course_version_id=version.id, workspace_id=workspace.id, ordinal=0, title="Search", objective="Understand search")
    db.add(section); db.flush()
    lesson = Lesson(course_version_id=version.id, course_section_id=section.id, workspace_id=workspace.id, ordinal=0, title="Binary search", objective="Explain halving")
    db.add(lesson); db.flush()
    db.commit()
    return workspace, course, version, lesson


def _course_run(db: Session, workspace: Workspace, course: Course, *, role: str, job_type: str = "course_outline", lesson: Lesson | None = None, status: str = "succeeded", tokens: tuple[int | None, int | None] = (10, 20), with_tools: bool = True, age_seconds: int = 100):
    job = CourseGenerationJob(
        workspace_id=workspace.id, course_id=course.id, course_version_id=None,
        lesson_id=lesson.id if lesson else None, job_type=job_type, output_language="zh-CN",
        status="succeeded", idempotency_key=f"key-{course.id}-{job_type}-{role}-{age_seconds}",
    )
    db.add(job); db.flush()
    created = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    completed = created + timedelta(seconds=5) if status != "running" else None
    run = AgentRun(
        course_generation_job_id=job.id, workspace_id=workspace.id, role=role, attempt_number=1,
        status=status, step_count=2, input_tokens=tokens[0], output_tokens=tokens[1],
        created_at=created, completed_at=completed,
    )
    db.add(run); db.flush()
    if with_tools:
        for ordinal, name, count, latency in [(2, "EvidenceSearch", 5, 30), (1, "Plan", 3, 12), (3, "Generate", None, 40)]:
            db.add(AgentToolCall(
                agent_run_id=run.id, workspace_id=workspace.id, tool_name=name, ordinal=ordinal,
                status="succeeded", result_count=count, latency_ms=latency, error_code=None,
            ))
    db.commit()
    return run


def _tutor_run(db: Session, workspace: Workspace, course: Course, *, scope: str = "lesson", lesson: Lesson | None = None, status: str = "succeeded", tokens: tuple[int | None, int | None] = (5, 7), age_seconds: int = 50):
    session = TutorSession(
        workspace_id=workspace.id, course_id=course.id, course_version_id=course.current_active_version_id,
        provider="provider-secret", model="model-secret", external_processing_ack_at=datetime.now(timezone.utc),
    )
    db.add(session); db.flush()
    turn = TutorTurn(
        session_id=session.id, workspace_id=workspace.id, ordinal=1, attempt_number=1, idempotency_key="turn-key",
        status="succeeded", question="secret-question-text", scope=scope, lesson_id=lesson.id if lesson else None,
        history_through_ordinal=0,
    )
    db.add(turn); db.flush()
    created = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    completed = created + timedelta(seconds=2) if status != "running" else None
    run = AgentRun(
        tutor_turn_id=turn.id, workspace_id=workspace.id, role="tutor", attempt_number=1, status=status,
        step_count=1, input_tokens=tokens[0], output_tokens=tokens[1], created_at=created, completed_at=completed,
    )
    db.add(run); db.flush()
    db.commit()
    return run


def test_list_and_detail_cover_three_roles_and_tool_order(client: TestClient, db_session: Session) -> None:
    workspace, course, _, lesson = _seed_course(db_session)
    architect = _course_run(db_session, workspace, course, role="course_architect", job_type="course_outline", age_seconds=100)
    writer = _course_run(db_session, workspace, course, role="lesson_writer", job_type="lesson_draft", lesson=lesson, age_seconds=80)
    tutor = _tutor_run(db_session, workspace, course, scope="lesson", lesson=lesson, age_seconds=60)

    body = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs").json()
    roles = {item["role"] for item in body}
    assert roles == {"course_architect", "lesson_writer", "tutor"}
    # List items do not carry tool calls.
    assert all("tool_calls" not in item for item in body)
    # Ordering is most recent first.
    assert [item["created_at"] for item in body] == sorted((item["created_at"] for item in body), reverse=True)

    detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{architect.id}").json()
    assert detail["role"] == "course_architect"
    assert detail["status"] == "succeeded"
    assert detail["attempt_number"] == 1
    assert detail["step_count"] == 2
    assert detail["input_tokens"] == 10
    assert detail["output_tokens"] == 20
    assert detail["duration_seconds"] == 5.0
    assert detail["identity"]["kind"] == "course_generation"
    assert detail["identity"]["job_type"] == "course_outline"
    assert detail["identity"]["course_title"] == "Algorithms"
    assert detail["identity"]["course_deleted"] is False
    # Tool calls ordered by ordinal even though inserted out of order.
    assert [call["ordinal"] for call in detail["tool_calls"]] == [1, 2, 3]
    assert [call["tool_name"] for call in detail["tool_calls"]] == ["Plan", "EvidenceSearch", "Generate"]

    writer_detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{writer.id}").json()
    assert writer_detail["identity"]["job_type"] == "lesson_draft"
    assert writer_detail["identity"]["lesson_title"] == "Binary search"

    tutor_detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{tutor.id}").json()
    assert tutor_detail["identity"]["kind"] == "tutor"
    assert tutor_detail["identity"]["tutor_scope"] == "lesson"
    assert tutor_detail["identity"]["course_title"] == "Algorithms"
    assert tutor_detail["identity"]["lesson_title"] == "Binary search"


def test_workspace_isolation_and_unknown_run_404(client: TestClient, db_session: Session) -> None:
    workspace_a, course_a, _, _ = _seed_course(db_session, name="A", slug="a", title="Course A")
    workspace_b, _, _, _ = _seed_course(db_session, name="B", slug="b", title="Course B")
    run = _course_run(db_session, workspace_a, course_a, role="course_architect")

    # Cross-workspace access: empty list and 404 detail.
    assert client.get(f"/api/v1/workspaces/{workspace_b.id}/agent-runs").json() == []
    assert client.get(f"/api/v1/workspaces/{workspace_b.id}/agent-runs/{run.id}").status_code == 404
    # Unknown run within the owning workspace.
    assert client.get(f"/api/v1/workspaces/{workspace_a.id}/agent-runs/00000000-0000-0000-0000-000000000000").status_code == 404
    # Unknown workspace id.
    assert client.get(f"/api/v1/workspaces/00000000-0000-0000-0000-000000000000/agent-runs").status_code == 404


def test_filters_and_limit(client: TestClient, db_session: Session) -> None:
    workspace, course, _, lesson = _seed_course(db_session)
    _course_run(db_session, workspace, course, role="course_architect", status="succeeded", age_seconds=100)
    _course_run(db_session, workspace, course, role="lesson_writer", lesson=lesson, status="failed", age_seconds=80)
    _tutor_run(db_session, workspace, course, scope="course", age_seconds=60)

    by_role = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs", params={"role": "course_architect"}).json()
    assert [item["role"] for item in by_role] == ["course_architect"]

    by_status = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs", params={"status": "failed"}).json()
    assert [item["role"] for item in by_status] == ["lesson_writer"]

    by_course = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs", params={"course_id": course.id}).json()
    # All three runs belong to the same course (course jobs + tutor session course).
    assert len(by_course) == 3
    assert client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs", params={"course_id": "00000000-0000-0000-0000-000000000000"}).json() == []

    limited = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs", params={"limit": 2}).json()
    assert len(limited) == 2


def test_invalid_filters_return_422(client: TestClient, db_session: Session) -> None:
    workspace, _, _, _ = _seed_course(db_session)
    base = f"/api/v1/workspaces/{workspace.id}/agent-runs"
    assert client.get(base, params={"role": "bogus"}).status_code == 422
    assert client.get(base, params={"status": "bogus"}).status_code == 422
    assert client.get(base, params={"limit": 0}).status_code == 422
    assert client.get(base, params={"limit": 51}).status_code == 422
    assert client.get(base, params={"limit": "abc"}).status_code == 422


def test_running_completed_and_missing_usage(client: TestClient, db_session: Session) -> None:
    workspace, course, _, _ = _seed_course(db_session)
    running = _course_run(db_session, workspace, course, role="course_architect", status="running", tokens=(None, None))
    missing_usage = _course_run(db_session, workspace, course, role="lesson_writer", status="succeeded", tokens=(None, None), with_tools=False, age_seconds=70)

    running_detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{running.id}").json()
    assert running_detail["status"] == "running"
    assert running_detail["completed_at"] is None
    assert running_detail["duration_seconds"] is None
    assert running_detail["input_tokens"] is None

    missing_detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{missing_usage.id}").json()
    assert missing_detail["status"] == "succeeded"
    assert missing_detail["completed_at"] is not None
    assert missing_detail["duration_seconds"] is not None
    # Usage unreported by provider must surface as null, never an estimate.
    assert missing_detail["input_tokens"] is None
    assert missing_detail["output_tokens"] is None
    assert missing_detail["tool_calls"] == []


def test_deleted_association_shows_safe_identity(client: TestClient, db_session: Session) -> None:
    workspace, course, _, _ = _seed_course(db_session)
    run = _course_run(db_session, workspace, course, role="course_architect")
    # Simulate a soft-deleted course: the association can no longer be read back
    # as an active course, so the view must not revive content.
    course.lifecycle_status = "deleted"
    db_session.commit()

    detail = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{run.id}").json()
    assert detail["identity"]["course_deleted"] is True
    assert detail["identity"]["course_title"] is None
    assert detail["role"] == "course_architect"
    assert detail["status"] == "succeeded"


def test_response_excludes_forbidden_fields(client: TestClient, db_session: Session) -> None:
    workspace, course, _, lesson = _seed_course(db_session)
    architect = _course_run(db_session, workspace, course, role="course_architect")
    tutor = _tutor_run(db_session, workspace, course, scope="lesson", lesson=lesson)

    list_body = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs").json()
    detail_architect = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{architect.id}").json()
    detail_tutor = client.get(f"/api/v1/workspaces/{workspace.id}/agent-runs/{tutor.id}").json()

    for payload in [list_body, detail_architect, detail_tutor]:
        keys = _collect_keys(payload)
        leaked = keys & FORBIDDEN_KEYS
        assert not leaked, f"forbidden fields leaked: {leaked}"

    # Tool call projections specifically must omit the persisted input_hash and
    # any tool input, despite the ORM column existing.
    for call in detail_architect["tool_calls"]:
        assert set(call.keys()) == {"tool_name", "ordinal", "status", "result_count", "latency_ms", "error_code", "created_at"}

    # Provider/model must not be exposed on the generic run summary.
    for payload in [list_body, detail_architect, detail_tutor]:
        assert "provider" not in _collect_keys(payload)
        assert "model" not in _collect_keys(payload)
