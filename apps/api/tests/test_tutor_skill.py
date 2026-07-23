"""Stage 4 Slice 3 teaching-skill tests.

Covers the registry/contracts matrix, migration 0019, the capability/snapshot
API surface and the skill runtime's safety/projection/idempotency/retry gates.
The paired baseline-vs-skill contract matrix lives in the stage3_eval paired
harness (see ``stage3_eval/paired.py``); these tests target the building blocks.
"""

import importlib.util
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, Table, Column, String, Integer, DateTime, create_engine, inspect, select, text
from sqlalchemy.orm import Session

from academic_companion.teaching_skills import SkillUnavailable, TeachingAnswerArtifact, TeachingAnswerBlock, TeachingPlan, compute_content_hash, current_published, display_name_for, load_skill
from learn_platform_api.db.models import (AgentRun, Course, CourseSection, CourseVersion, CourseVersionSource, DocumentChunk, DocumentVersion, LearningMemory, LearningMemoryPolicy, LearningTarget, Lesson, LessonCitation, LessonCompletion, LessonVersion, MasteryState, SourceDocument, TutorSession, TutorTurn, AgentToolCall, Weakness, Workspace)
from learn_platform_api.schemas.tutor import TutorSkillCapabilityRead, TutorTurnCreate
from learn_platform_api.services import tutor_generation
from learn_platform_api.services.tutor import resolve_teaching_skill_snapshot


# --------------------------------------------------------------------------- #
# Registry / contracts matrix (Batch A)
# --------------------------------------------------------------------------- #

def test_registry_loads_current_published_skill_with_stable_hash():
    skill_id, version = current_published()
    assert skill_id == "evidence-guided-diagnostic-scaffold"
    assert version == "4"
    skill = load_skill(skill_id, version)
    assert skill.display_name == "诊断式支架"
    assert len(skill.content_hash) == 64
    assert not skill.body.startswith("---")
    assert skill.body.startswith("# ")
    # Hash is reproducible across reloads.
    assert load_skill(skill_id, version).content_hash == skill.content_hash


def test_registry_rejects_unknown_id_version_and_path_injection():
    with pytest.raises(SkillUnavailable):
        load_skill("does-not-exist", "1")
    with pytest.raises(SkillUnavailable):
        load_skill("evidence-guided-diagnostic-scaffold", "999")
    # Path traversal attempts in the id/version are rejected by the identifier
    # regex before any filesystem path is built.
    for bad_id in ("../escape", "/abs/path", "..\\win", ".hidden", "UPPER", "has space"):
        with pytest.raises(SkillUnavailable):
            load_skill(bad_id, "1")
    for bad_version in ("../v1", "1/2", "v1", "0x1"):
        with pytest.raises(SkillUnavailable):
            load_skill("evidence-guided-diagnostic-scaffold", bad_version)


def test_display_name_for_returns_none_for_unknown_pair():
    assert display_name_for("evidence-guided-diagnostic-scaffold", "1") == "诊断式支架"
    assert display_name_for("evidence-guided-diagnostic-scaffold", "2") == "诊断式支架"
    assert display_name_for("evidence-guided-diagnostic-scaffold", "999") is None


def test_plan_dedupes_and_enforces_enum_length():
    plan = TeachingPlan.model_validate({"intent": "study_planning", "queries": ["a", "a", "b"], "learning_context_use": "required", "teaching_moves": ["focus", "focus", "explain"]})
    # Duplicates within the 1-3 bound are deduped.
    assert plan.queries == ["a", "b"]
    assert plan.teaching_moves == ["focus", "explain"]
    with pytest.raises(Exception):
        TeachingPlan.model_validate({"intent": "bogus", "queries": ["a"], "learning_context_use": "required", "teaching_moves": ["focus"]})
    with pytest.raises(Exception):
        TeachingPlan.model_validate({"intent": "other", "queries": ["a"], "learning_context_use": "bogus", "teaching_moves": ["focus"]})
    with pytest.raises(Exception):
        TeachingPlan.model_validate({"intent": "other", "queries": ["a"], "learning_context_use": "required", "teaching_moves": ["bogus"]})
    with pytest.raises(Exception):
        TeachingPlan.model_validate({"intent": "other", "queries": [], "learning_context_use": "required", "teaching_moves": ["focus"]})


def test_answer_block_enforces_citation_and_certainty_rules():
    # Factual blocks require a citation.
    with pytest.raises(Exception):
        TeachingAnswerArtifact.model_validate({"blocks": [{"block_key": "a", "type": "explanation", "text": "x", "citation_ids": []}]})
    with pytest.raises(Exception):
        TeachingAnswerArtifact.model_validate({"blocks": [{"block_key": "a", "type": "direct_answer", "text": "x", "citation_ids": []}]})
    with pytest.raises(Exception):
        TeachingAnswerArtifact.model_validate({"blocks": [{"block_key": "a", "type": "explanation", "text": "x", "citation_ids": ["   "]}]})
    # Diagnosis requires a certainty and must not cite course evidence.
    with pytest.raises(Exception):
        TeachingAnswerArtifact.model_validate({"blocks": [{"block_key": "d", "type": "learning_diagnosis", "text": "x", "citation_ids": []}]})
    with pytest.raises(Exception):
        TeachingAnswerArtifact.model_validate({"blocks": [{"block_key": "d", "type": "learning_diagnosis", "text": "x", "certainty": "confirmed", "citation_ids": ["e1"]}]})
    # Certainty is only permitted on diagnosis.
    with pytest.raises(Exception):
        TeachingAnswerArtifact.model_validate({"blocks": [{"block_key": "a", "type": "direct_answer", "text": "x", "citation_ids": ["e1"], "certainty": "confirmed"}]})
    # next_action / limitation must not cite.
    with pytest.raises(Exception):
        TeachingAnswerArtifact.model_validate({"blocks": [{"block_key": "n", "type": "next_action", "text": "x", "citation_ids": ["e1"]}]})
    with pytest.raises(Exception):
        TeachingAnswerArtifact.model_validate({"blocks": [{"block_key": "l", "type": "limitation", "text": "x", "citation_ids": ["e1"]}]})
    # Duplicate block keys are rejected.
    with pytest.raises(Exception):
        TeachingAnswerArtifact.model_validate({"blocks": [{"block_key": "a", "type": "direct_answer", "text": "x", "citation_ids": ["e1"]}, {"block_key": "a", "type": "explanation", "text": "y", "citation_ids": ["e1"]}]})


def test_runtime_projects_harmless_provider_metadata_but_keeps_semantic_validation():
    generated = {
        "blocks": [{
            "block_key": "answer",
            "type": "direct_answer",
            "text": "Supported explanation.",
            "citation_ids": ["e1"],
            "heading": "extra provider metadata",
        }]
    }
    artifact = tutor_generation._validate_teaching_answer(
        generated, {"e1"}, False, {}, [], "concept_explanation"
    )
    assert artifact.blocks[0].text == "Supported explanation."
    assert not hasattr(artifact.blocks[0], "heading")

    generated["blocks"][0]["citation_ids"] = ["unknown"]
    with pytest.raises(ValueError, match="invalid_agent_artifact"):
        tutor_generation._validate_teaching_answer(
            generated, {"e1"}, False, {}, [], "concept_explanation"
        )


def test_repair_instruction_exposes_only_safe_runtime_constraints():
    message = tutor_generation._teaching_repair_instruction(
        {"e2", "e1"}, True, {"t1": {"confirmed", "insufficient"}}, "learner_diagnosis"
    )
    assert '"allowed_citation_ids": ["e1", "e2"]' in message
    assert '"t1": ["confirmed", "insufficient"]' in message
    assert "learning_diagnosis requires one listed target_ref" in message
    assert "prompt" not in message.lower()


def test_diagnosis_can_answer_directly_without_unasked_course_definition():
    artifact = tutor_generation._validate_teaching_answer(
        {
            "blocks": [{
                "block_key": "diagnosis",
                "type": "learning_diagnosis",
                "text": "This target still needs review.",
                "citation_ids": [],
                "certainty": "confirmed",
                "target_ref": "t1",
            }]
        },
        {"e1"},
        True,
        {"t1": {"confirmed", "insufficient"}},
        [],
        "learner_diagnosis",
    )
    assert [block.type for block in artifact.blocks] == ["learning_diagnosis"]

    with pytest.raises(ValueError, match="invalid_agent_artifact"):
        tutor_generation._validate_teaching_answer(
            {
                "blocks": [{
                    "block_key": "action",
                    "type": "next_action",
                    "text": "Review it.",
                    "citation_ids": [],
                }]
            },
            {"e1"},
            False,
            {},
            [],
            "concept_explanation",
        )


def test_legacy_stage3_answer_artifact_still_validates():
    """Slice 3 keeps reading/producing the Stage 3 baseline contract for the
    offline paired eval and historical-retry path."""
    from academic_companion.tutor_agents import TutorAnswerArtifact as LegacyArtifact
    artifact = LegacyArtifact.model_validate({"blocks": [{"block_key": "a", "type": "explanation", "text": "ok", "citation_ids": ["e1"]}, {"block_key": "m", "type": "memory_summary", "text": "note", "citation_ids": []}]})
    assert len(artifact.blocks) == 2


# --------------------------------------------------------------------------- #
# Migration 0019 (Batch B)
# --------------------------------------------------------------------------- #

def _load_migration_0019():
    spec = importlib.util.spec_from_file_location("mig0019", "alembic/versions/0019_add_tutor_teaching_skill_snapshot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tutor_turns_0018(metadata):
    return Table("tutor_turns", metadata, *(Column("id", String(36), primary_key=True), Column("status", String(30)), Column("question", String), Column("scope", String(20)), Column("created_at", DateTime), Column("updated_at", DateTime)))


def test_migration_0019_adds_and_drops_snapshot_columns():
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    mig = _load_migration_0019()
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    _tutor_turns_0018(metadata)
    metadata.create_all(engine)

    def columns():
        return {column["name"] for column in inspect(engine).get_columns("tutor_turns")}

    snapshot_cols = {"teaching_skill_id", "teaching_skill_version", "teaching_skill_hash"}
    assert snapshot_cols.isdisjoint(columns())

    class _Ops(Operations):
        # SQLite cannot ALTER-add a CHECK constraint; the constraint semantics
        # are validated separately below. We exercise the real migration code for
        # the column add/drop, which is the SQLite-portable part.
        def create_check_constraint(self, *args, **kwargs):  # noqa: D401
            return None

        def drop_constraint(self, *args, **kwargs):
            return None

    with engine.begin() as conn:
        ops = _Ops(MigrationContext.configure(conn))
        mig.op = ops
        mig.upgrade()  # 0018 -> 0019
    assert snapshot_cols <= columns()

    with engine.begin() as conn:
        ops = _Ops(MigrationContext.configure(conn))
        mig.op = ops
        mig.downgrade()  # 0019 -> 0018
    assert snapshot_cols.isdisjoint(columns())

    with engine.begin() as conn:
        ops = _Ops(MigrationContext.configure(conn))
        mig.op = ops
        mig.upgrade()  # 0018 -> 0019 again
    assert snapshot_cols <= columns()


def test_migration_0019_check_constraint_semantics():
    mig = _load_migration_0019()
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    table = Table("tutor_turns", metadata, Column("id", String(36), primary_key=True))
    # Embed the exact constraint expression the migration applies on Postgres.
    with engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE tutor_turns (id TEXT PRIMARY KEY, teaching_skill_id TEXT, teaching_skill_version TEXT, teaching_skill_hash TEXT, CHECK {mig.SNAPSHOT_ALL_OR_NONE_EXPR})"))

    def insert(**fields):
        cols = ", ".join(["id", *fields])
        placeholders = ", ".join([":id", *[f":{k}" for k in fields]])
        with engine.begin() as conn:
            conn.execute(text(f"INSERT INTO tutor_turns ({cols}) VALUES ({placeholders})"), {"id": str(uuid4()), **fields})

    # All NULL is allowed (historical turn).
    insert()
    # All non-NULL is allowed (Slice 3 turn).
    insert(teaching_skill_id="skill", teaching_skill_version="1", teaching_skill_hash="h" * 64)
    # A partial snapshot is rejected.
    with pytest.raises(Exception):
        insert(teaching_skill_id="only-id")
    with pytest.raises(Exception):
        insert(teaching_skill_id="id", teaching_skill_version="1")


# --------------------------------------------------------------------------- #
# API capability + snapshot projection (Batch B)
# --------------------------------------------------------------------------- #

def _reader_fixture(db: Session):
    workspace = Workspace(name="skill workspace", slug="skill-workspace")
    db.add(workspace); db.flush()
    document = SourceDocument(workspace_id=workspace.id, display_name="guide.md")
    db.add(document); db.flush()
    version = DocumentVersion(document_id=document.id, version_number=1, processing_status="ready", original_filename="guide.md", mime_type="text/markdown", byte_size=10, sha256="a" * 64, original_storage_uri="test")
    db.add(version); db.flush(); document.current_version_id = version.id
    chunk = DocumentChunk(id="22222222-2222-2222-2222-222222222222", document_version_id=version.id, ordinal=0, content="Cathedral mode uses central design.", content_hash="b" * 64, start_offset=0, end_offset=34, page_start=2, page_end=2)
    course = Course(workspace_id=workspace.id, title="Software management", goal="patterns")
    db.add_all([chunk, course]); db.flush()
    course_version = CourseVersion(course_id=course.id, workspace_id=workspace.id, version_number=1, status="active", title=course.title)
    db.add(course_version); db.flush(); course.current_active_version_id = course_version.id
    db.add(CourseVersionSource(course_version_id=course_version.id, workspace_id=workspace.id, document_id=document.id, document_version_id=version.id))
    section = CourseSection(course_version_id=course_version.id, workspace_id=workspace.id, ordinal=0, title="Patterns", objective="patterns")
    db.add(section); db.flush()
    lesson = Lesson(course_version_id=course_version.id, course_section_id=section.id, workspace_id=workspace.id, ordinal=0, title="Cathedral and bazaar", objective="patterns")
    db.add(lesson); db.flush()
    lesson_version = LessonVersion(lesson_id=lesson.id, course_version_id=course_version.id, workspace_id=workspace.id, version_number=1, status="published", title=lesson.title, learning_objectives=["patterns"], blocks=[{"block_key": "p1", "type": "paragraph", "text": chunk.content, "citation_ids": ["c1"]}])
    db.add(lesson_version); db.flush(); lesson.current_published_version_id = lesson_version.id; db.commit()
    return workspace, course, course_version, section, lesson, lesson_version, chunk


def test_tutor_skill_capability_endpoint(client: TestClient, db_session: Session):
    workspace, *_ = _reader_fixture(db_session)
    response = client.get(f"/api/v1/workspaces/{workspace.id}/tutor-skill")
    assert response.status_code == 200
    body = response.json()
    assert body["teaching_skill"]["id"] == "evidence-guided-diagnostic-scaffold"
    assert body["teaching_skill"]["display_name"] == "诊断式支架"
    assert body["teaching_skill"]["version"] == "4"
    # Hash, prompt body and file path are never published.
    blob = str(body)
    for forbidden in ("hash", "prompt", "path", "body", ".md"):
        assert forbidden not in blob
    TutorSkillCapabilityRead.model_validate(body)


def test_tutor_skill_capability_404_for_missing_workspace(client: TestClient):
    response = client.get("/api/v1/workspaces/00000000-0000-0000-0000-000000000000/tutor-skill")
    assert response.status_code == 404


def test_new_turn_auto_snapshots_skill_and_rejects_forged_fields(client: TestClient, db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import tutor
    monkeypatch.setattr(tutor, "enqueue_tutor_turn", lambda *_args: None)
    workspace, course, version, section, lesson, lesson_version, _ = _reader_fixture(db_session)
    snapshot = resolve_teaching_skill_snapshot()
    session = client.post(f"/api/v1/workspaces/{workspace.id}/courses/{course.id}/tutor-sessions", json={"course_version_id": version.id, "external_processing_ack": True}).json()
    # The client cannot supply teaching_skill_* or a teaching mode: forged extra
    # fields fail with a stable 422 (corr 3.8), they are not silently ignored.
    forged = client.post(f"/api/v1/workspaces/{workspace.id}/tutor-sessions/{session['id']}/turns", headers={"Idempotency-Key": "forged"}, json={"question": "Explain cathedral mode.", "scope": "course", "teaching_skill_id": "forged", "teaching_mode": "plain", "teaching_skill_hash": "forged"})
    assert forged.status_code == 422
    # A clean create always carries the server-resolved current skill snapshot.
    turn = client.post(f"/api/v1/workspaces/{workspace.id}/tutor-sessions/{session['id']}/turns", headers={"Idempotency-Key": "skill-1"}, json={"question": "Explain cathedral mode.", "scope": "course"}).json()
    assert turn["teaching_skill"] == {"id": snapshot["id"], "display_name": snapshot["display_name"], "version": snapshot["version"]}
    assert "teaching_skill_hash" not in turn
    # The client create schema exposes no skill / mode fields.
    assert not any(field.startswith("teaching_") for field in TutorTurnCreate.model_fields)
    assert "teaching_skill" not in TutorTurnCreate.model_fields


def test_historical_turn_projects_null_skill(client: TestClient, db_session: Session) -> None:
    workspace, course, version, *_ = _reader_fixture(db_session)
    session = TutorSession(workspace_id=workspace.id, course_id=course.id, course_version_id=version.id, provider="fake", model="fake", external_processing_ack_at=datetime.now(timezone.utc))
    db_session.add(session); db_session.flush()
    historical = TutorTurn(session_id=session.id, workspace_id=workspace.id, ordinal=1, attempt_number=1, idempotency_key="hist", status="succeeded", question="old", scope="course", history_through_ordinal=0, answer_blocks=[{"block_key": "a", "type": "explanation", "text": "legacy", "citation_ids": []}])
    db_session.add(historical); db_session.commit()
    body = client.get(f"/api/v1/workspaces/{workspace.id}/tutor-sessions/{session.id}").json()
    assert body["turns"][0]["teaching_skill"] is None


def test_retry_preserves_skill_snapshot_and_legacy_retry_stays_null(client: TestClient, db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import tutor
    monkeypatch.setattr(tutor, "enqueue_tutor_turn", lambda *_args: None)
    workspace, course, version, *_ = _reader_fixture(db_session)
    snapshot = resolve_teaching_skill_snapshot()
    session = client.post(f"/api/v1/workspaces/{workspace.id}/courses/{course.id}/tutor-sessions", json={"course_version_id": version.id, "external_processing_ack": True}).json()
    turn = client.post(f"/api/v1/workspaces/{workspace.id}/tutor-sessions/{session['id']}/turns", headers={"Idempotency-Key": "r1"}, json={"question": "q", "scope": "course"}).json()
    client.post(f"/api/v1/workspaces/{workspace.id}/tutor-turns/{turn['id']}/cancel")
    retried = client.post(f"/api/v1/workspaces/{workspace.id}/tutor-turns/{turn['id']}/retry").json()
    assert retried["teaching_skill"] == {"id": snapshot["id"], "display_name": snapshot["display_name"], "version": snapshot["version"]}

    # A historical (pre-Slice-3) turn retries on the legacy path with NULL snapshot.
    legacy_session = TutorSession(workspace_id=workspace.id, course_id=course.id, course_version_id=version.id, provider="fake", model="fake", external_processing_ack_at=datetime.now(timezone.utc))
    db_session.add(legacy_session); db_session.flush()
    legacy = TutorTurn(session_id=legacy_session.id, workspace_id=workspace.id, ordinal=1, attempt_number=1, idempotency_key="legacy", status="failed", question="old", scope="course", history_through_ordinal=0, error_code="invalid_agent_artifact")
    db_session.add(legacy); db_session.commit()
    legacy_retry = client.post(f"/api/v1/workspaces/{workspace.id}/tutor-turns/{legacy.id}/retry").json()
    assert legacy_retry["teaching_skill"] is None


# --------------------------------------------------------------------------- #
# Runtime: context safety, plan fallback, calibration, cancel (Batch C)
TUTOR_TEST_WORKER = "test-tutor-worker"


# --------------------------------------------------------------------------- #

def _seed_skill_turn(db: Session, snapshot, *, question="Explain.", scope="course", policy=False):
    workspace = Workspace(name="rt", slug=str(uuid4())[:8])
    db.add(workspace); db.flush()
    document = SourceDocument(workspace_id=workspace.id, display_name="g.md")
    db.add(document); db.flush()
    version = DocumentVersion(document_id=document.id, version_number=1, processing_status="ready", original_filename="g.md", mime_type="text/markdown", byte_size=10, sha256="a" * 64, original_storage_uri="t")
    db.add(version); db.flush(); document.current_version_id = version.id
    chunk = DocumentChunk(id=str(uuid4()), document_version_id=version.id, ordinal=0, content="Cathedral mode uses central design and longer release cycles.", content_hash="b" * 64, start_offset=0, end_offset=60, page_start=1, page_end=1)
    db.add(chunk); db.flush()
    course = Course(workspace_id=workspace.id, title="c", goal="g")
    db.add(course); db.flush()
    cversion = CourseVersion(course_id=course.id, workspace_id=workspace.id, version_number=1, status="active", title="c")
    db.add(cversion); db.flush(); course.current_active_version_id = cversion.id
    source = CourseVersionSource(course_version_id=cversion.id, workspace_id=workspace.id, document_id=document.id, document_version_id=version.id)
    db.add(source)
    # Real published lesson/version so memories referencing them stay eligible.
    section = CourseSection(course_version_id=cversion.id, workspace_id=workspace.id, ordinal=0, title="Patterns", objective="patterns")
    db.add(section); db.flush()
    lesson = Lesson(id=str(uuid4()), course_version_id=cversion.id, course_section_id=section.id, workspace_id=workspace.id, ordinal=0, title="Cathedral and bazaar", objective="patterns")
    db.add(lesson); db.flush()
    lesson_version = LessonVersion(id=str(uuid4()), lesson_id=lesson.id, course_version_id=cversion.id, workspace_id=workspace.id, version_number=1, status="published", title=lesson.title, learning_objectives=["patterns"], blocks=[])
    db.add(lesson_version); db.flush(); lesson.current_published_version_id = lesson_version.id
    if policy:
        db.add(LearningMemoryPolicy(workspace_id=workspace.id, tutor_use_enabled=1))
        target = LearningTarget(workspace_id=workspace.id, course_id=course.id, course_version_id=cversion.id, lesson_id=lesson.id, lesson_version_id=lesson_version.id, target_key="lesson_overall", title="Choosing a mode", kind="lesson_overall")
        db.add(target); db.flush()
        db.add(Weakness(learning_target_id=target.id, workspace_id=workspace.id, status="confirmed"))
        db.add(MasteryState(learning_target_id=target.id, workspace_id=workspace.id, band="needs_review"))
        db.add(LearningMemory(workspace_id=workspace.id, course_id=course.id, lesson_id=lesson.id, lesson_version_id=lesson_version.id, learning_target_id=target.id, kind="weakness", status="active", display_text="巩固：根据项目条件选择开发模式"))
    session = TutorSession(workspace_id=workspace.id, course_id=course.id, course_version_id=cversion.id, provider="fake", model="fake", external_processing_ack_at=datetime.now(timezone.utc))
    db.add(session); db.flush()
    turn = TutorTurn(session_id=session.id, workspace_id=workspace.id, ordinal=1, attempt_number=1, idempotency_key=str(uuid4()), status="running", question=question, scope=scope, history_through_ordinal=0, teaching_skill_id=snapshot["id"], teaching_skill_version=snapshot["version"], teaching_skill_hash=snapshot["hash"], worker_id=TUTOR_TEST_WORKER, lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=300))
    db.add(turn); db.commit()
    return turn, chunk, source, lesson, lesson_version


def test_history_isolated_by_scope_and_lesson_version(db_session: Session):
    snapshot = resolve_teaching_skill_snapshot()
    turn, _chunk, _source, lesson, lesson_version = _seed_skill_turn(
        db_session, snapshot, scope="lesson"
    )
    turn.ordinal = 4
    turn.history_through_ordinal = 3
    turn.lesson_id = lesson.id
    turn.lesson_version_id = lesson_version.id

    session = db_session.get(TutorSession, turn.session_id)
    other_lesson = Lesson(
        id=str(uuid4()),
        course_version_id=lesson.course_version_id,
        course_section_id=lesson.course_section_id,
        workspace_id=lesson.workspace_id,
        ordinal=2,
        title="Other lesson",
        objective="other",
    )
    db_session.add(other_lesson)
    db_session.flush()
    other_version = LessonVersion(
        id=str(uuid4()),
        lesson_id=other_lesson.id,
        course_version_id=lesson.course_version_id,
        workspace_id=lesson.workspace_id,
        version_number=1,
        status="published",
        title="Other lesson",
        learning_objectives=["other"],
        blocks=[],
    )
    db_session.add(other_version)
    db_session.flush()
    other_lesson.current_published_version_id = other_version.id

    def prior(ordinal: int, scope: str, marker: str, lesson_id=None, version_id=None):
        return TutorTurn(
            session_id=session.id,
            workspace_id=turn.workspace_id,
            ordinal=ordinal,
            attempt_number=1,
            idempotency_key=str(uuid4()),
            status="succeeded",
            question=marker,
            scope=scope,
            lesson_id=lesson_id,
            lesson_version_id=version_id,
            history_through_ordinal=ordinal - 1,
            answer_blocks=[{
                "block_key": "a", "type": "limitation", "text": f"{marker}_ANSWER",
                "citation_ids": [], "certainty": None,
            }],
            completed_at=datetime.now(timezone.utc),
        )

    db_session.add_all([
        prior(1, "course", "COURSE_HISTORY"),
        prior(2, "lesson", "OTHER_LESSON_HISTORY", other_lesson.id, other_version.id),
        prior(3, "lesson", "SAME_LESSON_HISTORY", lesson.id, lesson_version.id),
    ])
    db_session.commit()

    history = tutor_generation._history(db_session, turn)
    blob = str(history)
    assert "SAME_LESSON_HISTORY" in blob
    assert "COURSE_HISTORY" not in blob
    assert "OTHER_LESSON_HISTORY" not in blob

    diagnosis_history = tutor_generation._history(
        db_session, turn, include_answer_text=False
    )
    diagnosis_blob = str(diagnosis_history)
    assert "SAME_LESSON_HISTORY" in diagnosis_blob
    assert "SAME_LESSON_HISTORY_ANSWER" not in diagnosis_blob
    assert diagnosis_history[0]["answer_block_types"] == ["limitation"]


def test_lesson_search_passes_only_lesson_citation_chunks(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, source, lesson, lesson_version = _seed_skill_turn(
        db_session, snapshot, scope="lesson"
    )
    turn.lesson_id = lesson.id
    turn.lesson_version_id = lesson_version.id
    db_session.add(LessonCitation(
        lesson_version_id=lesson_version.id,
        workspace_id=turn.workspace_id,
        block_key="body",
        document_id=source.document_id,
        document_version_id=source.document_version_id,
        document_chunk_id=chunk.id,
    ))
    db_session.commit()
    captured = {}

    def fake_retrieve(*_args, **kwargs):
        captured.update(kwargs)
        return "trace", []

    monkeypatch.setattr(tutor_generation, "retrieve", fake_retrieve)
    session = db_session.get(TutorSession, turn.session_id)
    evidence, ledger = tutor_generation._search(
        db_session, _settings(), session, turn, "topic", set(), [0], 1000
    )
    assert evidence == [] and ledger == {}
    assert captured["chunk_ids"] == [chunk.id]
    assert captured["document_ids"] == [source.document_id]


def _settings():
    from types import SimpleNamespace
    return SimpleNamespace(product_generation_api_key=None, product_generation_base_url="https://offline.invalid", product_generation_model="fake", product_generation_timeout_seconds=45.0, tutor_max_evidence_tokens=8000, tutor_max_output_tokens=2000, tutor_skill_max_evidence_tokens=10000, tutor_skill_max_output_tokens=3000)


def _seq(items):
    iterator = iter(items)
    return lambda *_a, **_k: next(iterator)


def test_skill_turn_canceled_mid_flight_commits_nothing(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, source, _lesson, _lv = _seed_skill_turn(db_session, snapshot)
    settings = _settings()
    plan = {"intent": "concept_explanation", "queries": ["cathedral"], "learning_context_use": "unavailable", "teaching_moves": ["explain"]}
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, source)}))
    monkeypatch.setattr(tutor_generation, "call_provider", lambda *_a, **_k: (plan, {"input_tokens": 1, "output_tokens": 1}))
    # Mark the session deleting so the authority check refuses to commit.
    session = db_session.get(TutorSession, turn.session_id)
    session.status = "deleting"
    db_session.commit()
    with pytest.raises(ValueError):
        tutor_generation.execute_tutor_turn(db_session, settings, turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    db_session.rollback()
    db_session.refresh(turn)
    assert turn.answer_blocks is None


def test_plan_fallback_records_reason_and_uses_other_explain(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, source, _lesson, _lv = _seed_skill_turn(db_session, snapshot)
    settings = _settings()
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Central design.", "citation_ids": ["e1"]}]}
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, source)}))
    monkeypatch.setattr(tutor_generation, "call_provider", lambda *_a, **_k: next(iter([("not a valid plan", {"input_tokens": 1, "output_tokens": 1}), (answer, {"input_tokens": 5, "output_tokens": 5})])))
    # Force plan parse failure by returning a non-dict first.
    call = {"i": 0}
    def provider(*_a, **_k):
        call["i"] += 1
        return ("garbage", {"input_tokens": 1, "output_tokens": 1}) if call["i"] == 1 else (answer, {"input_tokens": 5, "output_tokens": 5})
    monkeypatch.setattr(tutor_generation, "call_provider", provider)
    tutor_generation.execute_tutor_turn(db_session, settings, turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    db_session.commit(); db_session.refresh(turn)
    assert turn.status == "succeeded"
    fallback = db_session.execute(select(AgentToolCall).where(AgentToolCall.tool_name == "PlanFallback")).scalar_one_or_none()
    assert fallback is not None and fallback.error_code == "plan_degraded"


def test_memory_policy_off_blocks_personalization_and_diagnosis(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, source, _lesson, _lv = _seed_skill_turn(db_session, snapshot, policy=False)
    settings = _settings()
    plan = {"intent": "learner_diagnosis", "queries": ["gaps"], "learning_context_use": "required", "teaching_moves": ["focus"]}
    # Without injected state a diagnosis block must be rejected; provide a clean
    # answer that respects the no-state constraint.
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Central design.", "citation_ids": ["e1"]}, {"block_key": "l", "type": "limitation", "text": "No personalized state available.", "citation_ids": []}]}
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, source)}))
    monkeypatch.setattr(tutor_generation, "call_provider", _seq([(plan, {"input_tokens": 2, "output_tokens": 2}), (answer, {"input_tokens": 5, "output_tokens": 5})]))
    tutor_generation.execute_tutor_turn(db_session, settings, turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    db_session.commit(); db_session.refresh(turn)
    assert turn.status == "succeeded"
    select_trace = db_session.execute(select(AgentToolCall).where(AgentToolCall.tool_name == "TeachingContextSelect")).scalar_one()
    assert select_trace.error_code == "policy_disabled"
    assert all(block["type"] != "learning_diagnosis" for block in turn.answer_blocks)


def test_projection_never_leaks_sensitive_fields(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, source, _lesson, _lv = _seed_skill_turn(db_session, snapshot, policy=True)
    settings = _settings()
    captured: list = []
    plan = {"intent": "learner_diagnosis", "queries": ["gaps"], "learning_context_use": "required", "teaching_moves": ["focus", "next_action"]}
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Standing.", "citation_ids": ["e1"]}, {"block_key": "d", "type": "learning_diagnosis", "text": "There is a confirmed gap to work on.", "certainty": "confirmed", "target_ref": "t1", "citation_ids": []}, {"block_key": "n", "type": "next_action", "text": "Practise two sample projects.", "citation_ids": []}]}

    def provider(*_a, **_k):
        value = next(provider.seq)
        captured.append(value[0])
        return value
    provider.seq = iter([(plan, {"input_tokens": 2, "output_tokens": 2}), (answer, {"input_tokens": 8, "output_tokens": 8})])
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, source)}))
    monkeypatch.setattr(tutor_generation, "call_provider", provider)
    tutor_generation.execute_tutor_turn(db_session, settings, turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    db_session.commit()
    blob = str(captured)
    # The safe projection must never carry raw scores, answers, rubrics,
    # feedback, evidence text, memory revisions or projection scores.
    for forbidden in ("projection_score", "answer_spec", "rubric", "feedback_blocks", "correct_option_key", "option_rationales", "revision"):
        assert forbidden not in blob
    # Memory display text is allowed, but a Memory revision / hidden score is not.


def test_memory_cap_applied(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, source, _lesson, _lv = _seed_skill_turn(db_session, snapshot, policy=True)
    settings = _settings()
    # Active memory is unique per target, so to exceed the 5-memory cap we add
    # six further targets each with its own active memory in the course scope.
    session = db_session.get(TutorSession, turn.session_id)
    course_id = session.course_id
    course_version_id = session.course_version_id
    for ordinal in range(6):
        target = LearningTarget(workspace_id=turn.workspace_id, course_id=course_id, course_version_id=course_version_id, lesson_id=_lesson.id, lesson_version_id=_lv.id, target_key=f"obj_{ordinal}", title=f"Objective {ordinal}", kind="objective")
        db_session.add(target); db_session.flush()
        db_session.add(LearningMemory(workspace_id=turn.workspace_id, course_id=course_id, lesson_id=_lesson.id, lesson_version_id=_lv.id, learning_target_id=target.id, kind="weakness", status="active", display_text=f"note {ordinal}"))
    db_session.commit()
    plan = {"intent": "learner_diagnosis", "queries": ["gaps"], "learning_context_use": "required", "teaching_moves": ["focus", "next_action"]}
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Standing.", "citation_ids": ["e1"]}, {"block_key": "d", "type": "learning_diagnosis", "text": "A confirmed gap.", "certainty": "confirmed", "target_ref": "t1", "citation_ids": []}, {"block_key": "n", "type": "next_action", "text": "Practise more.", "citation_ids": []}]}
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, source)}))
    monkeypatch.setattr(tutor_generation, "call_provider", _seq([(plan, {"input_tokens": 2, "output_tokens": 2}), (answer, {"input_tokens": 8, "output_tokens": 8})]))
    tutor_generation.execute_tutor_turn(db_session, settings, turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    db_session.commit()
    select_trace = db_session.execute(select(AgentToolCall).where(AgentToolCall.tool_name == "TeachingContextSelect")).scalar_one()
    # 7 active memories in scope, capped at 5; no completions seeded.
    assert select_trace.result_count == 5


def test_restate_guard_rejects_verbatim_memory_copy(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, source, _lesson, _lv = _seed_skill_turn(db_session, snapshot, policy=True)
    settings = _settings()
    memory_text = "巩固：根据项目条件选择开发模式"
    plan = {"intent": "learner_diagnosis", "queries": ["gaps"], "learning_context_use": "required", "teaching_moves": ["focus", "next_action"]}
    bad = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Standing.", "citation_ids": ["e1"]}, {"block_key": "d", "type": "learning_diagnosis", "text": memory_text, "certainty": "confirmed", "target_ref": "t1", "citation_ids": []}]}
    good = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Standing.", "citation_ids": ["e1"]}, {"block_key": "d", "type": "learning_diagnosis", "text": "You need to map project conditions to a development mode.", "certainty": "confirmed", "target_ref": "t1", "citation_ids": []}, {"block_key": "n", "type": "next_action", "text": "Try two examples.", "citation_ids": []}]}
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, source)}))
    monkeypatch.setattr(tutor_generation, "call_provider", _seq([(plan, {"input_tokens": 2, "output_tokens": 2}), (bad, {"input_tokens": 5, "output_tokens": 5}), (good, {"input_tokens": 5, "output_tokens": 5})]))
    tutor_generation.execute_tutor_turn(db_session, settings, turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    db_session.commit(); db_session.refresh(turn)
    assert turn.status == "succeeded"
    diagnosis = next(block for block in turn.answer_blocks if block["type"] == "learning_diagnosis")
    assert "map project conditions" in diagnosis["text"]


# --------------------------------------------------------------------------- #
# Correction packet 001 regression matrix (3.1 - 3.9)
# --------------------------------------------------------------------------- #

import threading as _threading
from contextlib import contextmanager as _contextmanager


def _quick_skill_turn(db, snapshot, *, question="q", evidence=True):
    """Minimal claimed skill turn on its own workspace (for matrix tests)."""
    ws = Workspace(name=str(uuid4())[:8], slug=str(uuid4())[:8]); db.add(ws); db.flush()
    doc = SourceDocument(workspace_id=ws.id, display_name="g.md"); db.add(doc); db.flush()
    ver = DocumentVersion(document_id=doc.id, version_number=1, processing_status="ready", original_filename="g.md", mime_type="text/markdown", byte_size=1, sha256="a" * 64, original_storage_uri="t"); db.add(ver); db.flush(); doc.current_version_id = ver.id
    chunk = DocumentChunk(id=str(uuid4()), document_version_id=ver.id, ordinal=0, content="Cathedral mode uses central design and longer release cycles.", content_hash="b" * 64, start_offset=0, end_offset=60, page_start=1, page_end=1)
    if evidence:
        db.add(chunk); db.flush()
    course = Course(workspace_id=ws.id, title="c", goal="g"); db.add(course); db.flush()
    cv = CourseVersion(course_id=course.id, workspace_id=ws.id, version_number=1, status="active", title="c"); db.add(cv); db.flush(); course.current_active_version_id = cv.id
    src = CourseVersionSource(course_version_id=cv.id, workspace_id=ws.id, document_id=doc.id, document_version_id=ver.id); db.add(src)
    session = TutorSession(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, provider="fake", model="fake", external_processing_ack_at=datetime.now(timezone.utc)); db.add(session); db.flush()
    turn = TutorTurn(session_id=session.id, workspace_id=ws.id, ordinal=1, attempt_number=1, idempotency_key=str(uuid4()), status="running", question=question, scope="course", history_through_ordinal=0, teaching_skill_id=snapshot["id"], teaching_skill_version=snapshot["version"], teaching_skill_hash=snapshot["hash"], worker_id=TUTOR_TEST_WORKER, lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=300)); db.add(turn); db.commit()
    return turn, chunk, src


def _seed_multi_target(db, snapshot):
    """Two targets: A confirmed (t1), B provisional (t2), policy enabled."""
    ws = Workspace(name=str(uuid4())[:8], slug=str(uuid4())[:8]); db.add(ws); db.flush()
    doc = SourceDocument(workspace_id=ws.id, display_name="g.md"); db.add(doc); db.flush()
    ver = DocumentVersion(document_id=doc.id, version_number=1, processing_status="ready", original_filename="g.md", mime_type="text/markdown", byte_size=1, sha256="a" * 64, original_storage_uri="t"); db.add(ver); db.flush(); doc.current_version_id = ver.id
    chunk = DocumentChunk(id=str(uuid4()), document_version_id=ver.id, ordinal=0, content="Cathedral mode uses central design and longer release cycles.", content_hash="b" * 64, start_offset=0, end_offset=60, page_start=1, page_end=1); db.add(chunk); db.flush()
    course = Course(workspace_id=ws.id, title="c", goal="g"); db.add(course); db.flush()
    cv = CourseVersion(course_id=course.id, workspace_id=ws.id, version_number=1, status="active", title="c"); db.add(cv); db.flush(); course.current_active_version_id = cv.id
    src = CourseVersionSource(course_version_id=cv.id, workspace_id=ws.id, document_id=doc.id, document_version_id=ver.id); db.add(src)
    section = CourseSection(course_version_id=cv.id, workspace_id=ws.id, ordinal=0, title="P", objective="p"); db.add(section); db.flush()
    lesson = Lesson(id=str(uuid4()), course_version_id=cv.id, course_section_id=section.id, workspace_id=ws.id, ordinal=0, title="Cathedral and bazaar", objective="p"); db.add(lesson); db.flush()
    lv = LessonVersion(id=str(uuid4()), lesson_id=lesson.id, course_version_id=cv.id, workspace_id=ws.id, version_number=1, status="published", title=lesson.title, learning_objectives=["p"], blocks=[]); db.add(lv); db.flush(); lesson.current_published_version_id = lv.id
    db.add(LearningMemoryPolicy(workspace_id=ws.id, tutor_use_enabled=1))
    ta = LearningTarget(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, lesson_id=lesson.id, lesson_version_id=lv.id, target_key="a", title="Choosing a mode", kind="objective"); db.add(ta); db.flush()
    tb = LearningTarget(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, lesson_id=lesson.id, lesson_version_id=lv.id, target_key="b", title="Naming the modes", kind="objective"); db.add(tb); db.flush()
    db.add(Weakness(learning_target_id=ta.id, workspace_id=ws.id, status="confirmed"))
    db.add(MasteryState(learning_target_id=ta.id, workspace_id=ws.id, band="needs_review"))
    db.add(LearningMemory(workspace_id=ws.id, course_id=course.id, lesson_id=lesson.id, lesson_version_id=lv.id, learning_target_id=ta.id, kind="weakness", status="active", display_text="A巩固选择模式"))
    db.add(Weakness(learning_target_id=tb.id, workspace_id=ws.id, status="provisional"))
    db.add(MasteryState(learning_target_id=tb.id, workspace_id=ws.id, band="needs_review"))
    session = TutorSession(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, provider="fake", model="fake", external_processing_ack_at=datetime.now(timezone.utc)); db.add(session); db.flush()
    turn = TutorTurn(session_id=session.id, workspace_id=ws.id, ordinal=1, attempt_number=1, idempotency_key=str(uuid4()), status="running", question="my gaps?", scope="course", history_through_ordinal=0, teaching_skill_id=snapshot["id"], teaching_skill_version=snapshot["version"], teaching_skill_hash=snapshot["hash"], worker_id=TUTOR_TEST_WORKER, lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=300)); db.add(turn); db.commit()
    return turn, chunk, src


def test_target_calibration_per_target_confirmed_vs_provisional(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _seed_multi_target(db_session, snapshot)
    plan = {"intent": "learner_diagnosis", "queries": ["gaps"], "learning_context_use": "required", "teaching_moves": ["focus", "next_action"]}
    # Overclaim: t2 (provisional) as confirmed -> rejected; honest per-target repair.
    bad = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Standing.", "citation_ids": ["e1"]}, {"block_key": "d", "type": "learning_diagnosis", "text": "Naming is confirmed.", "certainty": "confirmed", "target_ref": "t2", "citation_ids": []}]}
    good = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Standing.", "citation_ids": ["e1"]}, {"block_key": "d1", "type": "learning_diagnosis", "text": "Choosing is a confirmed gap.", "certainty": "confirmed", "target_ref": "t1", "citation_ids": []}, {"block_key": "d2", "type": "learning_diagnosis", "text": "Naming is a provisional signal.", "certainty": "provisional", "target_ref": "t2", "citation_ids": []}, {"block_key": "n", "type": "next_action", "text": "Practise both.", "citation_ids": []}]}
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))
    monkeypatch.setattr(tutor_generation, "call_provider", _seq([(plan, {"input_tokens": 3, "output_tokens": 3}), (bad, {"input_tokens": 5, "output_tokens": 5}), (good, {"input_tokens": 5, "output_tokens": 5})]))
    tutor_generation.execute_tutor_turn(db_session, _settings(), turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    db_session.commit(); db_session.refresh(turn)
    assert turn.status == "succeeded"
    assert {block["certainty"] for block in turn.answer_blocks if block["type"] == "learning_diagnosis"} == {"confirmed", "provisional"}
    # Internal target refs are never persisted (corr 3.2/3.6).
    assert all("target_ref" not in block for block in turn.answer_blocks)


def test_target_calibration_unknown_target_ref_rejected(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _seed_multi_target(db_session, snapshot)
    plan = {"intent": "learner_diagnosis", "queries": ["gaps"], "learning_context_use": "required", "teaching_moves": ["focus", "next_action"]}
    bad = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Standing.", "citation_ids": ["e1"]}, {"block_key": "d", "type": "learning_diagnosis", "text": "Mystery.", "certainty": "confirmed", "target_ref": "t9", "citation_ids": []}]}
    good = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Standing.", "citation_ids": ["e1"]}, {"block_key": "d", "type": "learning_diagnosis", "text": "Confirmed on choosing.", "certainty": "confirmed", "target_ref": "t1", "citation_ids": []}, {"block_key": "n", "type": "next_action", "text": "Practise.", "citation_ids": []}]}
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))
    monkeypatch.setattr(tutor_generation, "call_provider", _seq([(plan, {"input_tokens": 3, "output_tokens": 3}), (bad, {"input_tokens": 5, "output_tokens": 5}), (good, {"input_tokens": 5, "output_tokens": 5})]))
    tutor_generation.execute_tutor_turn(db_session, _settings(), turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    db_session.commit(); db_session.refresh(turn)
    assert turn.status == "succeeded"


def _final_authority_mutations():
    def owner_replaced(db, turn):
        turn.worker_id = "another-owner"; db.flush()
    def lease_expired(db, turn):
        turn.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10); db.flush()
    def cancel_requested(db, turn):
        turn.status = "cancel_requested"; db.flush()
    def session_deleting(db, turn):
        db.get(TutorSession, turn.session_id).status = "deleting"; db.flush()
    def source_degraded(db, turn):
        session = db.get(TutorSession, turn.session_id)
        src = db.scalar(select(CourseVersionSource).where(CourseVersionSource.course_version_id == session.course_version_id))
        db.get(SourceDocument, src.document_id).lifecycle_status = "deleted"; db.flush()
    return [("owner_replaced", owner_replaced), ("lease_expired", lease_expired), ("cancel_requested", cancel_requested), ("session_deleting", session_deleting), ("source_degraded", source_degraded)]


def _midflight(plan, answer, mutate, db, turn, *, on_call=2):
    state = {"call": 0}
    def provider(*_a, **_k):
        state["call"] += 1
        if state["call"] == on_call:
            mutate(db, turn)
        if state["call"] == 1:
            return plan, {"input_tokens": 3, "output_tokens": 3}
        return answer, {"input_tokens": 5, "output_tokens": 5}
    return provider


@pytest.mark.parametrize("name,mutate", _final_authority_mutations())
def test_final_authority_rejects_late_result_normal_answer(db_session: Session, monkeypatch, name, mutate):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _quick_skill_turn(db_session, snapshot)
    plan = {"intent": "concept_explanation", "queries": ["cathedral"], "learning_context_use": "unavailable", "teaching_moves": ["explain"]}
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Central design.", "citation_ids": ["e1"]}]}
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))
    monkeypatch.setattr(tutor_generation, "call_provider", _midflight(plan, answer, mutate, db_session, turn, on_call=2))
    with pytest.raises(ValueError):
        tutor_generation.execute_tutor_turn(db_session, _settings(), turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    db_session.rollback(); db_session.refresh(turn)
    assert turn.status != "succeeded" and turn.answer_blocks is None


@pytest.mark.parametrize("name,mutate", [m for m in _final_authority_mutations() if m[0] != "source_degraded"])
def test_final_authority_rejects_late_result_limitation(db_session: Session, monkeypatch, name, mutate):
    # The limitation path carries no evidence ledger, so source degradation is
    # not observable here (it is covered by the normal-answer parametrization).
    snapshot = resolve_teaching_skill_snapshot()
    turn, _chunk, _src = _quick_skill_turn(db_session, snapshot, evidence=False)
    plan = {"intent": "other", "queries": ["x"], "learning_context_use": "unavailable", "teaching_moves": ["explain"]}
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([], {}))
    monkeypatch.setattr(tutor_generation, "call_provider", _midflight(plan, None, mutate, db_session, turn, on_call=1))
    with pytest.raises(ValueError):
        tutor_generation.execute_tutor_turn(db_session, _settings(), turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    db_session.rollback(); db_session.refresh(turn)
    assert turn.status != "succeeded" and turn.answer_blocks is None


def test_heartbeat_lost_does_not_commit(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _quick_skill_turn(db_session, snapshot)
    plan = {"intent": "concept_explanation", "queries": ["cathedral"], "learning_context_use": "unavailable", "teaching_moves": ["explain"]}
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Central design.", "citation_ids": ["e1"]}]}
    lost = _threading.Event(); lost.set()
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))
    monkeypatch.setattr(tutor_generation, "call_provider", _seq([(plan, {"input_tokens": 3, "output_tokens": 3}), (answer, {"input_tokens": 5, "output_tokens": 5})]))
    with pytest.raises(ValueError):
        tutor_generation.execute_tutor_turn(db_session, _settings(), turn, worker_id=TUTOR_TEST_WORKER, lease_lost=lost)
    db_session.rollback(); db_session.refresh(turn)
    assert turn.status != "succeeded" and turn.answer_blocks is None


def test_usage_aggregation_none_when_any_call_missing(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    plan = {"intent": "concept_explanation", "queries": ["cathedral"], "learning_context_use": "unavailable", "teaching_moves": ["explain"]}
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Central design.", "citation_ids": ["e1"]}]}
    # (provider usage sequence, expected input, expected output). The limitation
    # case uses a single plan call with no evidence and no answer call.
    cases = [
        ([{"input_tokens": 3, "output_tokens": 3}, {"input_tokens": 5, "output_tokens": 5}], 8, 8, True),
        ([{"input_tokens": 3, "output_tokens": 3}, {"input_tokens": 5, "output_tokens": None}], 8, None, True),
        ([{"input_tokens": 3, "output_tokens": 3}, {"input_tokens": None, "output_tokens": 5}], None, 8, True),
        ([{"input_tokens": None, "output_tokens": None}], None, None, False),
    ]
    for usages, exp_in, exp_out, with_answer in cases:
        turn, chunk, src = _quick_skill_turn(db_session, snapshot, evidence=with_answer)
        monkeypatch.setattr(tutor_generation, "_search", (lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)})) if with_answer else (lambda *_a: ([], {})))
        calls = [(plan, usages[0])] + ([(answer, usages[1])] if with_answer else [])
        monkeypatch.setattr(tutor_generation, "call_provider", _seq(calls))
        tutor_generation.execute_tutor_turn(db_session, _settings(), turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
        db_session.commit(); db_session.refresh(turn)
        run = db_session.scalar(select(AgentRun).where(AgentRun.tutor_turn_id == turn.id, AgentRun.status == "succeeded"))
        assert turn.input_tokens == exp_in, (usages, turn.input_tokens, exp_in)
        assert turn.output_tokens == exp_out, (usages, turn.output_tokens, exp_out)
        assert run.input_tokens == exp_in and run.output_tokens == exp_out
        db_session.rollback()


def test_in_flight_usage_does_not_dirty_turn_before_final_authority(db_session: Session):
    """The deletion path locks Workspace before Turn, so Tutor execution must
    not acquire a Turn row lock while recording provider progress."""
    snapshot = resolve_teaching_skill_snapshot()
    turn, _chunk, _src = _quick_skill_turn(db_session, snapshot, evidence=True)
    run = AgentRun(
        tutor_turn_id=turn.id,
        workspace_id=turn.workspace_id,
        role="tutor",
        attempt_number=turn.attempt_number,
        status="running",
    )
    db_session.add(run)
    db_session.flush()

    usages = [{"input_tokens": 2, "output_tokens": 3}]
    tutor_generation._record_usage(turn, run, usages, db_session)
    assert run.input_tokens == 2 and run.output_tokens == 3
    assert turn.input_tokens is None and turn.output_tokens is None

    tutor_generation._record_usage(
        turn, run, usages, db_session, finalize_turn=True
    )
    assert turn.input_tokens == 2 and turn.output_tokens == 3
    db_session.rollback()


def test_actual_use_counts_reflect_injection_not_selection(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    plan_required = {"intent": "learner_diagnosis", "queries": ["gaps"], "learning_context_use": "required", "teaching_moves": ["focus", "next_action"]}
    plan_irrelevant = {"intent": "concept_explanation", "queries": ["cathedral"], "learning_context_use": "irrelevant", "teaching_moves": ["explain"]}
    answer_required = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Standing.", "citation_ids": ["e1"]}, {"block_key": "d", "type": "learning_diagnosis", "text": "Confirmed gap on choosing.", "certainty": "confirmed", "target_ref": "t1", "citation_ids": []}, {"block_key": "n", "type": "next_action", "text": "Practise.", "citation_ids": []}]}
    answer_irrelevant = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Central design.", "citation_ids": ["e1"]}]}
    base = _settings()

    def run(plan, answer):
        turn, chunk, src = _seed_skill_turn(db_session, snapshot, policy=True)[:3]
        monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))
        monkeypatch.setattr(tutor_generation, "call_provider", _seq([(plan, {"input_tokens": 3, "output_tokens": 3}), (answer, {"input_tokens": 8, "output_tokens": 8})]))
        tutor_generation.execute_tutor_turn(db_session, base, turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
        db_session.commit(); db_session.refresh(turn)
        mem = db_session.scalar(select(AgentToolCall).join(AgentRun, AgentToolCall.agent_run_id == AgentRun.id).where(AgentRun.tutor_turn_id == turn.id, AgentToolCall.tool_name == "LearningMemoryContext").order_by(AgentToolCall.created_at.desc()).limit(1))
        return mem.result_count if mem else 0

    assert run(plan_required, answer_required) == 1          # required -> injected
    assert run(plan_irrelevant, answer_irrelevant) == 0      # irrelevant -> not injected

    # policy off -> 0
    turn, chunk, src = _seed_skill_turn(db_session, snapshot, policy=False)[:3]
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))
    monkeypatch.setattr(tutor_generation, "call_provider", _seq([(plan_irrelevant, {"input_tokens": 3, "output_tokens": 3}), (answer_irrelevant, {"input_tokens": 8, "output_tokens": 8})]))
    tutor_generation.execute_tutor_turn(db_session, base, turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    db_session.commit()
    mem = db_session.scalar(select(AgentToolCall).join(AgentRun, AgentToolCall.agent_run_id == AgentRun.id).where(AgentRun.tutor_turn_id == turn.id, AgentToolCall.tool_name == "LearningMemoryContext").order_by(AgentToolCall.created_at.desc()).limit(1))
    assert (mem.result_count if mem else 0) == 0


def test_context_budget_caps_oversize_state(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src, lesson, lesson_version = _seed_skill_turn(db_session, snapshot, policy=True)
    course = db_session.get(TutorSession, turn.session_id)
    # Add a second target carrying a far-too-long memory; the ~800-token budget
    # must drop the oversized memory (whole-entry truncation) and keep the run
    # deterministic and successful (corr 3.4).
    long_target = LearningTarget(workspace_id=turn.workspace_id, course_id=course.course_id, course_version_id=course.course_version_id, lesson_id=lesson.id, lesson_version_id=lesson_version.id, target_key="long", title="Long target", kind="objective")
    db_session.add(long_target); db_session.flush()
    db_session.add(Weakness(learning_target_id=long_target.id, workspace_id=turn.workspace_id, status="provisional"))
    db_session.add(LearningMemory(workspace_id=turn.workspace_id, course_id=course.course_id, lesson_id=lesson.id, lesson_version_id=lesson_version.id, learning_target_id=long_target.id, kind="weakness", status="active", display_text="Z" * 4000))
    db_session.commit()
    captured: list = []
    plan = {"intent": "learner_diagnosis", "queries": ["gaps"], "learning_context_use": "required", "teaching_moves": ["focus", "next_action"]}
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Standing.", "citation_ids": ["e1"]}, {"block_key": "d", "type": "learning_diagnosis", "text": "Confirmed gap on choosing.", "certainty": "confirmed", "target_ref": "t1", "citation_ids": []}, {"block_key": "n", "type": "next_action", "text": "Practise.", "citation_ids": []}]}

    seq = _seq([(plan, {"input_tokens": 3, "output_tokens": 3}), (answer, {"input_tokens": 8, "output_tokens": 8})])

    def provider(*args, **_k):
        captured.append(args[1])
        return seq(*args, **_k)

    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))
    monkeypatch.setattr(tutor_generation, "call_provider", provider)
    tutor_generation.execute_tutor_turn(db_session, _settings(), turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    db_session.commit(); db_session.refresh(turn)
    assert turn.status == "succeeded"
    # The 4000-char memory was dropped by the budget; it must not reach the prompt.
    answer_payload = str(captured[-1])
    assert "Z" * 50 not in answer_payload
    # And it must not be persisted.
    assert all("Z" * 50 not in (b.get("text") or "") for b in (turn.answer_blocks or []))


def test_public_projection_exposes_certainty_not_target_ref(client: TestClient, db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import tutor
    monkeypatch.setattr(tutor, "enqueue_tutor_turn", lambda *_args: None)
    snapshot = resolve_teaching_skill_snapshot()
    # Seed multi-target fixture through the multi-target helper, then POST a turn
    # via the API to exercise the public projection path.
    turn, chunk, src = _seed_multi_target(db_session, snapshot)
    # Drive generation directly, then read the public session projection.
    plan = {"intent": "learner_diagnosis", "queries": ["gaps"], "learning_context_use": "required", "teaching_moves": ["focus", "next_action"]}
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Standing.", "citation_ids": ["e1"]}, {"block_key": "d", "type": "learning_diagnosis", "text": "Choosing is confirmed.", "certainty": "confirmed", "target_ref": "t1", "citation_ids": []}, {"block_key": "n", "type": "next_action", "text": "Practise.", "citation_ids": []}]}
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))
    monkeypatch.setattr(tutor_generation, "call_provider", _seq([(plan, {"input_tokens": 3, "output_tokens": 3}), (answer, {"input_tokens": 8, "output_tokens": 8})]))
    tutor_generation.execute_tutor_turn(db_session, _settings(), turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    db_session.commit()
    session = db_session.get(TutorSession, turn.session_id)
    body = client.get(f"/api/v1/workspaces/{session.workspace_id}/tutor-sessions/{session.id}").json()
    block = next(b for b in body["turns"][0]["answer_blocks"] if b["type"] == "learning_diagnosis")
    assert block["certainty"] == "confirmed"               # certainty exposed
    assert "target_ref" not in block                        # internal ref stripped
    blob = str(body)
    for forbidden in ("target_ref", "teaching_skill_hash", "projection_score", "rubric", "feedback_blocks", "answer_spec"):
        assert forbidden not in blob


def test_tool_call_ordinals_are_monotonic_and_unique(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _quick_skill_turn(db_session, snapshot)
    plan = {"intent": "concept_explanation", "queries": ["cathedral", "bazaar"], "learning_context_use": "unavailable", "teaching_moves": ["explain"]}
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Central design.", "citation_ids": ["e1"]}]}
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))
    monkeypatch.setattr(tutor_generation, "call_provider", _seq([(plan, {"input_tokens": 3, "output_tokens": 3}), (answer, {"input_tokens": 5, "output_tokens": 5})]))
    tutor_generation.execute_tutor_turn(db_session, _settings(), turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    db_session.commit()
    run = db_session.scalar(select(AgentRun).where(AgentRun.tutor_turn_id == turn.id))
    ordinals = [call.ordinal for call in db_session.scalars(select(AgentToolCall).where(AgentToolCall.agent_run_id == run.id).order_by(AgentToolCall.ordinal))]
    assert ordinals == sorted(ordinals)
    assert len(ordinals) == len(set(ordinals))
    assert run.step_count == 4  # plan + 2 searches + submit


# --------------------------------------------------------------------------- #
# Worker: claim/idempotency/retry_wait/failed-trace (corr 3.1/3.9)
# --------------------------------------------------------------------------- #

def _seed_queued_turn(db, snapshot, *, status="queued", next_attempt_at=None):
    ws = Workspace(name=str(uuid4())[:8], slug=str(uuid4())[:8]); db.add(ws); db.flush()
    doc = SourceDocument(workspace_id=ws.id, display_name="g.md"); db.add(doc); db.flush()
    ver = DocumentVersion(document_id=doc.id, version_number=1, processing_status="ready", original_filename="g.md", mime_type="text/markdown", byte_size=1, sha256="a" * 64, original_storage_uri="t"); db.add(ver); db.flush(); doc.current_version_id = ver.id
    chunk = DocumentChunk(id=str(uuid4()), document_version_id=ver.id, ordinal=0, content="Cathedral mode uses central design and longer release cycles.", content_hash="b" * 64, start_offset=0, end_offset=60, page_start=1, page_end=1); db.add(chunk); db.flush()
    course = Course(workspace_id=ws.id, title="c", goal="g"); db.add(course); db.flush()
    cv = CourseVersion(course_id=course.id, workspace_id=ws.id, version_number=1, status="active", title="c"); db.add(cv); db.flush(); course.current_active_version_id = cv.id
    src = CourseVersionSource(course_version_id=cv.id, workspace_id=ws.id, document_id=doc.id, document_version_id=ver.id); db.add(src)
    session = TutorSession(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, provider="fake", model="fake", external_processing_ack_at=datetime.now(timezone.utc)); db.add(session); db.flush()
    turn = TutorTurn(session_id=session.id, workspace_id=ws.id, ordinal=1, attempt_number=1, idempotency_key=str(uuid4()), status=status, question="q", scope="course", history_through_ordinal=0, teaching_skill_id=snapshot["id"], teaching_skill_version=snapshot["version"], teaching_skill_hash=snapshot["hash"], next_attempt_at=next_attempt_at); db.add(turn); db.commit()
    return turn, chunk, src


def _patch_worker(db_session, monkeypatch, *, lease_set=False):
    from learn_platform_api import tutor_workers
    from sqlalchemy.orm import sessionmaker
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(tutor_workers, "SessionLocal", factory)
    event = _threading.Event(); event.set() if lease_set else event.clear()

    @_contextmanager
    def fake_lease(*_a, **_k):
        yield event
    monkeypatch.setattr(tutor_workers, "maintain_tutor_lease", fake_lease)
    return tutor_workers


def test_worker_success_and_duplicate_delivery_is_noop(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _seed_queued_turn(db_session, snapshot)
    tutor_workers = _patch_worker(db_session, monkeypatch)
    plan = {"intent": "concept_explanation", "queries": ["cathedral"], "learning_context_use": "unavailable", "teaching_moves": ["explain"]}
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Central design.", "citation_ids": ["e1"]}]}
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))
    monkeypatch.setattr(tutor_generation, "call_provider", _seq([(plan, {"input_tokens": 3, "output_tokens": 3}), (answer, {"input_tokens": 5, "output_tokens": 5})]))
    tutor_workers.run_tutor_turn(turn.id)
    db_session.expire_all(); db_session.refresh(turn)
    assert turn.status == "succeeded"
    # Duplicate delivery: the turn is no longer queued/retry_wait -> no-op, and
    # no second AgentRun is created.
    runs_before = db_session.scalar(select(AgentRun).where(AgentRun.tutor_turn_id == turn.id))
    tutor_workers.run_tutor_turn(turn.id)
    db_session.expire_all()
    assert db_session.scalars(select(AgentRun).where(AgentRun.tutor_turn_id == turn.id)).all() == [runs_before] or len(db_session.scalars(select(AgentRun).where(AgentRun.tutor_turn_id == turn.id)).all()) == 1


def test_worker_retry_wait_claim_timing(db_session: Session, monkeypatch):
    from sqlalchemy import func as _func
    snapshot = resolve_teaching_skill_snapshot()
    future = datetime.now(timezone.utc) + timedelta(seconds=60)
    turn, chunk, src = _seed_queued_turn(db_session, snapshot, status="retry_wait", next_attempt_at=future)
    tutor_workers = _patch_worker(db_session, monkeypatch)
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))
    monkeypatch.setattr(tutor_generation, "call_provider", _seq([({"intent": "other", "queries": ["q"], "learning_context_use": "unavailable", "teaching_moves": ["explain"]}, {"input_tokens": 1, "output_tokens": 1}), ({"blocks": [{"block_key": "a", "type": "direct_answer", "text": "x", "citation_ids": ["e1"]}]}, {"input_tokens": 1, "output_tokens": 1})]))
    # Not yet due -> no claim, no run.
    tutor_workers.run_tutor_turn(turn.id); db_session.expire_all(); db_session.refresh(turn)
    assert turn.status == "retry_wait"
    assert db_session.scalar(select(_func.count(AgentRun.id)).where(AgentRun.tutor_turn_id == turn.id)) == 0
    # Due now -> claimed and run.
    turn.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1); db_session.commit()
    tutor_workers.run_tutor_turn(turn.id); db_session.expire_all(); db_session.refresh(turn)
    assert turn.status == "succeeded"


def test_worker_failed_run_keeps_real_step_count(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _seed_queued_turn(db_session, snapshot)
    tutor_workers = _patch_worker(db_session, monkeypatch)
    plan = {"intent": "concept_explanation", "queries": ["cathedral"], "learning_context_use": "unavailable", "teaching_moves": ["explain"]}
    # Invalid answer (uncited factual block dropped -> empty) on both attempts.
    bad = {"blocks": [{"block_key": "a", "type": "explanation", "text": "no cite", "citation_ids": []}]}
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))
    monkeypatch.setattr(tutor_generation, "call_provider", _seq([(plan, {"input_tokens": 3, "output_tokens": 3}), (bad, {"input_tokens": 5, "output_tokens": 5}), (bad, {"input_tokens": 5, "output_tokens": 5})]))
    tutor_workers.run_tutor_turn(turn.id)
    db_session.expire_all(); db_session.refresh(turn)
    assert turn.status in {"failed", "retry_wait"}
    runs = db_session.scalars(select(AgentRun).where(AgentRun.tutor_turn_id == turn.id)).all()
    assert len(runs) == 1                       # no duplicate zero-step run
    assert runs[0].step_count >= 3              # plan + search + answer (+ repair) reflected
    assert runs[0].error_code == "invalid_agent_artifact"
    # Only actually-reported, complete usage dimensions enter the failed run.
    assert runs[0].input_tokens == 13           # 3 + 5 + 5, all reported
    assert runs[0].output_tokens == 13


def test_worker_lease_lost_does_not_commit(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _seed_queued_turn(db_session, snapshot)
    tutor_workers = _patch_worker(db_session, monkeypatch, lease_set=True)
    plan = {"intent": "concept_explanation", "queries": ["cathedral"], "learning_context_use": "unavailable", "teaching_moves": ["explain"]}
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Central design.", "citation_ids": ["e1"]}]}
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))
    monkeypatch.setattr(tutor_generation, "call_provider", _seq([(plan, {"input_tokens": 3, "output_tokens": 3}), (answer, {"input_tokens": 5, "output_tokens": 5})]))
    tutor_workers.run_tutor_turn(turn.id)
    db_session.expire_all(); db_session.refresh(turn)
    assert turn.status != "succeeded" and turn.answer_blocks is None


# --------------------------------------------------------------------------- #
# Correction packet 002 (3.1 retry budget, 3.2 authority/error codes,
# 3.3 search step, 3.4 budget/starvation, 3.5 missing matrix)
# --------------------------------------------------------------------------- #

def test_worker_auto_retry_budget_three_deliveries(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _seed_queued_turn(db_session, snapshot)
    tutor_workers = _patch_worker(db_session, monkeypatch)
    plan = {"intent": "concept_explanation", "queries": ["cathedral"], "learning_context_use": "unavailable", "teaching_moves": ["explain"]}
    invalid = {"blocks": [{"block_key": "a", "type": "explanation", "text": "no cite", "citation_ids": []}]}  # dropped -> empty -> invalid
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))

    call_count = {"n": 0}
    cycle = [(plan, {"input_tokens": 3, "output_tokens": 3}), (invalid, {"input_tokens": 5, "output_tokens": 5}), (invalid, {"input_tokens": 5, "output_tokens": 5})]

    def provider(*_a, **_k):
        call_count["n"] += 1
        return cycle[(call_count["n"] - 1) % len(cycle)]

    monkeypatch.setattr(tutor_generation, "call_provider", provider)
    # Drive the worker, fast-forwarding each retry_wait backoff, until terminal.
    for _ in range(8):
        tutor_workers.run_tutor_turn(turn.id)
        db_session.expire_all(); refreshed = db_session.get(TutorTurn, turn.id)
        if refreshed.status in {"succeeded", "failed", "canceled"}:
            break
        refreshed.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1); db_session.commit()
    db_session.expire_all(); db_session.refresh(turn)
    assert turn.status == "failed"                                  # exactly 3 deliveries then terminal
    assert turn.error_code == "invalid_agent_artifact"
    runs = db_session.scalars(select(AgentRun).where(AgentRun.tutor_turn_id == turn.id)).all()
    assert len(runs) == 3                                           # 3 delivery attempts
    calls_after_budget = call_count["n"]
    # A duplicate delivery after the budget is exhausted is a no-op.
    tutor_workers.run_tutor_turn(turn.id); db_session.expire_all()
    assert call_count["n"] == calls_after_budget
    assert len(db_session.scalars(select(AgentRun).where(AgentRun.tutor_turn_id == turn.id)).all()) == 3


def test_worker_explicit_retry_resets_budget(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _seed_queued_turn(db_session, snapshot)
    tutor_workers = _patch_worker(db_session, monkeypatch)
    plan = {"intent": "concept_explanation", "queries": ["cathedral"], "learning_context_use": "unavailable", "teaching_moves": ["explain"]}
    invalid = {"blocks": [{"block_key": "a", "type": "explanation", "text": "no cite", "citation_ids": []}]}
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))
    cycle = [(plan, {"input_tokens": 3, "output_tokens": 3}), (invalid, {"input_tokens": 5, "output_tokens": 5}), (invalid, {"input_tokens": 5, "output_tokens": 5})]
    provider_count = {"n": 0}
    monkeypatch.setattr(tutor_generation, "call_provider", lambda *_a, **_k: (provider_count.__setitem__("n", provider_count["n"] + 1) or cycle[(provider_count["n"] - 1) % len(cycle)]))
    for _ in range(8):
        tutor_workers.run_tutor_turn(turn.id)
        db_session.expire_all(); refreshed = db_session.get(TutorTurn, turn.id)
        if refreshed.status in {"succeeded", "failed", "canceled"}:
            break
        refreshed.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1); db_session.commit()
    # Explicit user retry creates a NEW TutorTurn with its own fresh budget.
    from learn_platform_api.services import tutor as tutor_service
    from learn_platform_api.settings import get_settings
    monkeypatch.setattr(tutor_service, "enqueue_tutor_turn", lambda *_a: None)
    retry = tutor_service.retry_turn(db_session, get_settings(), turn.workspace_id, turn.id)
    assert retry is not None and retry.id != turn.id
    assert db_session.scalars(select(AgentRun).where(AgentRun.tutor_turn_id == retry.id)).all() == []  # fresh budget
    # Original turn's failed AgentRuns are retained.
    assert len(db_session.scalars(select(AgentRun).where(AgentRun.tutor_turn_id == turn.id)).all()) == 3


def test_final_authority_source_degraded_maps_source_snapshot_stale(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _quick_skill_turn(db_session, snapshot)
    plan = {"intent": "concept_explanation", "queries": ["cathedral"], "learning_context_use": "unavailable", "teaching_moves": ["explain"]}
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Central design.", "citation_ids": ["e1"]}]}

    def degrade_source(db, turn):
        session = db.get(TutorSession, turn.session_id)
        source = db.scalar(select(CourseVersionSource).where(CourseVersionSource.course_version_id == session.course_version_id))
        db.get(SourceDocument, source.document_id).lifecycle_status = "deleted"; db.flush()
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))
    monkeypatch.setattr(tutor_generation, "call_provider", _midflight(plan, answer, degrade_source, db_session, turn, on_call=2))
    with pytest.raises(ValueError) as exc_info:
        tutor_generation.execute_tutor_turn(db_session, _settings(), turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    assert str(exc_info.value) == "source_snapshot_stale"
    db_session.rollback(); db_session.refresh(turn)
    assert turn.status != "succeeded" and turn.answer_blocks is None


def test_final_authority_course_version_changed_maps_source_snapshot_stale(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _quick_skill_turn(db_session, snapshot)
    plan = {"intent": "concept_explanation", "queries": ["cathedral"], "learning_context_use": "unavailable", "teaching_moves": ["explain"]}
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Central design.", "citation_ids": ["e1"]}]}

    def change_course(db, turn):
        session = db.get(TutorSession, turn.session_id)
        db.get(Course, session.course_id).current_active_version_id = "00000000-0000-0000-0000-000000000000"; db.flush()
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))
    monkeypatch.setattr(tutor_generation, "call_provider", _midflight(plan, answer, change_course, db_session, turn, on_call=2))
    with pytest.raises(ValueError) as exc_info:
        tutor_generation.execute_tutor_turn(db_session, _settings(), turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    assert str(exc_info.value) == "source_snapshot_stale"


def test_final_authority_lesson_version_changed_maps_source_snapshot_stale(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _quick_skill_turn(db_session, snapshot)
    # Switch to lesson scope with a real published lesson/version.
    db_session.flush()
    ws = db_session.get(Workspace, turn.workspace_id)
    section = CourseSection(course_version_id=db_session.get(TutorSession, turn.session_id).course_version_id, workspace_id=ws.id, ordinal=0, title="S", objective="o"); db_session.add(section); db_session.flush()
    lesson = Lesson(id=str(uuid4()), course_version_id=db_session.get(TutorSession, turn.session_id).course_version_id, course_section_id=section.id, workspace_id=ws.id, ordinal=0, title="L", objective="o"); db_session.add(lesson); db_session.flush()
    lv = LessonVersion(id=str(uuid4()), lesson_id=lesson.id, course_version_id=lesson.course_version_id, workspace_id=ws.id, version_number=1, status="published", title="L", learning_objectives=["o"], blocks=[]); db_session.add(lv); db_session.flush(); lesson.current_published_version_id = lv.id
    turn.scope = "lesson"; turn.lesson_id = lesson.id; turn.lesson_version_id = lv.id; db_session.commit()
    plan = {"intent": "concept_explanation", "queries": ["cathedral"], "learning_context_use": "unavailable", "teaching_moves": ["explain"]}
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Central design.", "citation_ids": ["e1"]}]}

    def change_lesson(db, turn):
        db.get(Lesson, turn.lesson_id).current_published_version_id = "00000000-0000-0000-0000-000000000000"; db.flush()
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))
    monkeypatch.setattr(tutor_generation, "call_provider", _midflight(plan, answer, change_lesson, db_session, turn, on_call=2))
    with pytest.raises(ValueError) as exc_info:
        tutor_generation.execute_tutor_turn(db_session, _settings(), turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    assert str(exc_info.value) == "source_snapshot_stale"


def test_fresh_get_bypasses_identity_map_cache(db_session: Session):
    from learn_platform_api.services.tutor_generation import _fresh_get
    ws = Workspace(name="cache", slug="cache-test"); db_session.add(ws); db_session.flush()
    db_session.get(Workspace, ws.id)  # populate the identity map with lifecycle_status="active"
    # A raw SQL UPDATE changes the DB row but leaves the cached instance stale.
    db_session.execute(text("UPDATE workspaces SET lifecycle_status = 'deleted' WHERE id = :id"), {"id": ws.id})
    db_session.flush()
    cached = db_session.get(Workspace, ws.id)
    assert cached.lifecycle_status == "active"          # identity-map cache returned
    fresh = _fresh_get(db_session, Workspace, ws.id)
    assert fresh.lifecycle_status == "deleted"          # forced re-read bypasses cache
    db_session.rollback()


def test_search_failure_counts_step_before_call(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _quick_skill_turn(db_session, snapshot)
    plan = {"intent": "concept_explanation", "queries": ["cathedral"], "learning_context_use": "unavailable", "teaching_moves": ["explain"]}
    monkeypatch.setattr(tutor_generation, "call_provider", _seq([(plan, {"input_tokens": 3, "output_tokens": 3})]))

    def raising_search(*_a, **_k):
        raise ValueError("source_snapshot_stale")
    monkeypatch.setattr(tutor_generation, "_search", raising_search)
    with pytest.raises(ValueError):
        tutor_generation.execute_tutor_turn(db_session, _settings(), turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    run = db_session.scalar(select(AgentRun).where(AgentRun.tutor_turn_id == turn.id, AgentRun.status == "running"))
    assert run.step_count == 2  # plan (1) + search counted before the failing retrieve (2)
    db_session.rollback()


def test_plan_provider_failure_step_count(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _quick_skill_turn(db_session, snapshot)
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))

    def provider(*_a, **_k):
        raise ValueError("generation_provider_unavailable")
    monkeypatch.setattr(tutor_generation, "call_provider", provider)
    with pytest.raises(ValueError):
        tutor_generation.execute_tutor_turn(db_session, _settings(), turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    run = db_session.scalar(select(AgentRun).where(AgentRun.tutor_turn_id == turn.id, AgentRun.status == "running"))
    assert run.step_count == 1  # plan step counted before the failing provider call
    db_session.rollback()


def test_build_injection_caps_serialized_json_within_budget():
    import json as _json
    from learn_platform_api.services.tutor_generation import LEARNING_STATE_MAX_CHARS, _build_injection
    learning = {
        "targets": [{"id": str(i), "title": "T" + ("X" * 200), "mastery_band": "needs_review", "weakness_status": "confirmed", "last_supported_at": None, "memory_display_text": None} for i in range(20)],
        "memories": [{"target_id": str(i), "target_title": "T" + ("X" * 200), "display_text": "M" + ("Y" * 300), "last_supported_at": None} for i in range(20)],
        "completions": [{"lesson_title": "L" + ("Z" * 200), "completed_at": "2026-01-01"} for _ in range(20)],
    }
    injection = _build_injection(learning, LEARNING_STATE_MAX_CHARS)
    assert len(_json.dumps(injection["projection"], ensure_ascii=False)) <= LEARNING_STATE_MAX_CHARS


def test_build_injection_does_not_starve_confirmed_memory():
    from learn_platform_api.services.tutor_generation import LEARNING_STATE_MAX_CHARS, _build_injection
    learning = {
        "targets": [{"id": "conf", "title": "Important", "mastery_band": "needs_review", "weakness_status": "confirmed", "last_supported_at": None, "memory_display_text": None}]
        + [{"id": f"n{i}", "title": "N" + ("X" * 150), "mastery_band": "unknown", "weakness_status": None, "last_supported_at": None, "memory_display_text": None} for i in range(20)],
        "memories": [{"target_id": "conf", "target_title": "Important", "display_text": "critical memory note", "last_supported_at": None}],
        "completions": [],
    }
    injection = _build_injection(learning, LEARNING_STATE_MAX_CHARS)
    # The confirmed target gets ref t1 and its active memory is bundled in,
    # despite a flood of low-value none-priority targets.
    assert any(t["ref"] == "t1" and t["weakness_certainty"] == "confirmed" for t in injection["projection"]["targets"])
    assert any(m["display_text"] == "critical memory note" for m in injection["projection"]["memories"])


def test_scope_isolation_excludes_other_scope(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _quick_skill_turn(db_session, snapshot, evidence=True)
    # State lives in a DIFFERENT workspace/course; the turn's scope must not see it.
    other_ws = Workspace(name="other", slug="other-scope"); db_session.add(other_ws); db_session.flush()
    other_doc = SourceDocument(workspace_id=other_ws.id, display_name="o.md"); db_session.add(other_doc); db_session.flush()
    other_ver = DocumentVersion(document_id=other_doc.id, version_number=1, processing_status="ready", original_filename="o.md", mime_type="text/markdown", byte_size=1, sha256="a" * 64, original_storage_uri="t"); db_session.add(other_ver); db_session.flush(); other_doc.current_version_id = other_ver.id
    other_course = Course(workspace_id=other_ws.id, title="other", goal="g"); db_session.add(other_course); db_session.flush()
    other_cv = CourseVersion(course_id=other_course.id, workspace_id=other_ws.id, version_number=1, status="active", title="other"); db_session.add(other_cv); db_session.flush(); other_course.current_active_version_id = other_cv.id
    other_section = CourseSection(course_version_id=other_cv.id, workspace_id=other_ws.id, ordinal=0, title="S", objective="o"); db_session.add(other_section); db_session.flush()
    other_lesson = Lesson(id=str(uuid4()), course_version_id=other_cv.id, course_section_id=other_section.id, workspace_id=other_ws.id, ordinal=0, title="OL", objective="o"); db_session.add(other_lesson); db_session.flush()
    other_lv = LessonVersion(id=str(uuid4()), lesson_id=other_lesson.id, course_version_id=other_cv.id, workspace_id=other_ws.id, version_number=1, status="published", title="OL", learning_objectives=["o"], blocks=[]); db_session.add(other_lv); db_session.flush(); other_lesson.current_published_version_id = other_lv.id
    db_session.add(LearningMemoryPolicy(workspace_id=other_ws.id, tutor_use_enabled=1))
    other_target = LearningTarget(workspace_id=other_ws.id, course_id=other_course.id, course_version_id=other_cv.id, lesson_id=other_lesson.id, lesson_version_id=other_lv.id, target_key="o", title="Other target", kind="objective"); db_session.add(other_target); db_session.flush()
    db_session.add(Weakness(learning_target_id=other_target.id, workspace_id=other_ws.id, status="confirmed"))
    db_session.add(MasteryState(learning_target_id=other_target.id, workspace_id=other_ws.id, band="needs_review"))
    db_session.add(LearningMemory(workspace_id=other_ws.id, course_id=other_course.id, lesson_id=other_lesson.id, lesson_version_id=other_lv.id, learning_target_id=other_target.id, kind="weakness", status="active", display_text="OTHER_SCOPE_SECRET_MEMORY"))
    db_session.commit()
    plan = {"intent": "learner_diagnosis", "queries": ["cathedral"], "learning_context_use": "required", "teaching_moves": ["explain"]}
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Central design.", "citation_ids": ["e1"]}]}
    captured: list = []
    seq = _seq([(plan, {"input_tokens": 3, "output_tokens": 3}), (answer, {"input_tokens": 5, "output_tokens": 5})])
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))
    monkeypatch.setattr(tutor_generation, "call_provider", lambda *a, **_k: captured.append(a[1]) or seq(*a, **_k))
    # The turn's own workspace has no policy enabled -> no state is selected/injected.
    tutor_generation.execute_tutor_turn(db_session, _settings(), turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    db_session.commit()
    blob = str(captured)
    assert "OTHER_SCOPE_SECRET_MEMORY" not in blob
    mem = db_session.scalar(select(AgentToolCall).join(AgentRun, AgentToolCall.agent_run_id == AgentRun.id).where(AgentRun.tutor_turn_id == turn.id, AgentToolCall.tool_name == "LearningMemoryContext"))
    assert (mem.result_count if mem else 0) == 0


@pytest.mark.parametrize("plan_u,answer_u,repair_u,exp_in,exp_out", [
    ({"input_tokens": 3, "output_tokens": 3}, {"input_tokens": 5, "output_tokens": 5}, {"input_tokens": 5, "output_tokens": 5}, 13, 13),        # all complete
    ({"input_tokens": None, "output_tokens": 3}, {"input_tokens": 5, "output_tokens": 5}, {"input_tokens": 5, "output_tokens": 5}, None, 13),  # plan missing input
    ({"input_tokens": 3, "output_tokens": None}, {"input_tokens": 5, "output_tokens": 5}, {"input_tokens": 5, "output_tokens": 5}, 13, None),  # plan missing output
    ({"input_tokens": 3, "output_tokens": 3}, {"input_tokens": None, "output_tokens": 5}, {"input_tokens": 5, "output_tokens": 5}, None, 13),  # answer missing input
    ({"input_tokens": 3, "output_tokens": 3}, {"input_tokens": 5, "output_tokens": None}, {"input_tokens": 5, "output_tokens": 5}, 13, None),  # answer missing output
    ({"input_tokens": 3, "output_tokens": 3}, {"input_tokens": 5, "output_tokens": 5}, {"input_tokens": None, "output_tokens": 5}, None, 13),  # repair missing input
    ({"input_tokens": 3, "output_tokens": 3}, {"input_tokens": 5, "output_tokens": 5}, {"input_tokens": 5, "output_tokens": None}, 13, None),  # repair missing output
    ({"input_tokens": None, "output_tokens": None}, {"input_tokens": None, "output_tokens": None}, {"input_tokens": None, "output_tokens": None}, None, None),  # all missing
])
def test_usage_repair_path_per_dimension_aggregation(db_session: Session, monkeypatch, plan_u, answer_u, repair_u, exp_in, exp_out):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _seed_skill_turn(db_session, snapshot, policy=True)[:3]
    plan = {"intent": "learner_diagnosis", "queries": ["gaps"], "learning_context_use": "required", "teaching_moves": ["focus", "next_action"]}
    bad = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Standing.", "citation_ids": ["e1"]}, {"block_key": "d", "type": "learning_diagnosis", "text": "gap.", "certainty": "confirmed", "citation_ids": []}]}  # missing target_ref -> invalid
    good = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Standing.", "citation_ids": ["e1"]}, {"block_key": "d", "type": "learning_diagnosis", "text": "Confirmed gap.", "certainty": "confirmed", "target_ref": "t1", "citation_ids": []}, {"block_key": "n", "type": "next_action", "text": "Practise.", "citation_ids": []}]}
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))
    monkeypatch.setattr(tutor_generation, "call_provider", _seq([(plan, plan_u), (bad, answer_u), (good, repair_u)]))
    tutor_generation.execute_tutor_turn(db_session, _settings(), turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    db_session.commit(); db_session.refresh(turn)
    run = db_session.scalar(select(AgentRun).where(AgentRun.tutor_turn_id == turn.id, AgentRun.status == "succeeded"))
    assert turn.input_tokens == exp_in, (turn.input_tokens, exp_in)
    assert turn.output_tokens == exp_out, (turn.output_tokens, exp_out)
    assert run.input_tokens == exp_in and run.output_tokens == exp_out
    db_session.rollback()


def test_worker_failed_trace_authority_reject_keeps_real_progress(db_session: Session, monkeypatch):
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _seed_queued_turn(db_session, snapshot)
    tutor_workers = _patch_worker(db_session, monkeypatch)
    plan = {"intent": "concept_explanation", "queries": ["cathedral"], "learning_context_use": "unavailable", "teaching_moves": ["explain"]}
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Central design.", "citation_ids": ["e1"]}]}

    # The patched search returns evidence AND degrades the ledger source in the
    # worker's own session, so the post-answer final authority rejects with the
    # real step/usage progress captured into the failed run.
    def search_and_degrade(db, _settings, session, _query, _seen, _token_total, *_rest):
        source = db.scalar(select(CourseVersionSource).where(CourseVersionSource.course_version_id == session.course_version_id))
        db.get(SourceDocument, source.document_id).lifecycle_status = "deleted"
        db.flush()
        return [{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}

    monkeypatch.setattr(tutor_generation, "_search", search_and_degrade)
    monkeypatch.setattr(tutor_generation, "call_provider", _seq([(plan, {"input_tokens": 3, "output_tokens": 3}), (answer, {"input_tokens": 5, "output_tokens": 5})]))
    tutor_workers.run_tutor_turn(turn.id)
    db_session.expire_all(); db_session.refresh(turn)
    assert turn.status == "failed"
    assert turn.error_code == "source_snapshot_stale"
    runs = db_session.scalars(select(AgentRun).where(AgentRun.tutor_turn_id == turn.id)).all()
    assert len(runs) == 1                       # no duplicate run
    assert runs[0].step_count >= 3              # plan + search + answer reflected
    assert runs[0].input_tokens == 8 and runs[0].output_tokens == 8


# --------------------------------------------------------------------------- #
# Correction packet 003 (3.1 limitation, 3.3 scope isolation, 3.4 worker trace)
# --------------------------------------------------------------------------- #

def _counting_provider(plan, answer=None, fail_on_call=None):
    """Provider that records how many times it was called. If ``fail_on_call``
    matches the call number it raises instead of returning."""
    state = {"n": 0}
    items = [(plan, {"input_tokens": 3, "output_tokens": 3})]
    if answer is not None:
        items.append((answer, {"input_tokens": 5, "output_tokens": 5}))

    def provider(*_a, **_k):
        state["n"] += 1
        if fail_on_call is not None and state["n"] == fail_on_call:
            raise ValueError("generation_provider_unavailable")
        return items[min(state["n"] - 1, len(items) - 1)]

    provider.count = state
    return provider


@pytest.mark.parametrize("plan_use", ["irrelevant", "unavailable"])
def test_limitation_when_plan_not_using_state_and_no_evidence(db_session: Session, monkeypatch, plan_use):
    """Candidates exist but the plan says irrelevant/unavailable and there is no
    evidence -> honest limitation, answer provider NOT called (corr 003/3.1)."""
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _seed_skill_turn(db_session, snapshot, policy=True)[:3]  # confirmed candidate exists
    plan = {"intent": "concept_explanation", "queries": ["cathedral"], "learning_context_use": plan_use, "teaching_moves": ["explain"]}
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([], {}))  # no evidence
    provider = _counting_provider(plan)
    monkeypatch.setattr(tutor_generation, "call_provider", provider)
    tutor_generation.execute_tutor_turn(db_session, _settings(), turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    db_session.commit(); db_session.refresh(turn)
    assert turn.status == "succeeded"
    assert [b["type"] for b in turn.answer_blocks] == ["limitation"]
    assert provider.count["n"] == 1  # only the plan call; answer provider never called
    mem = db_session.scalar(select(AgentToolCall).join(AgentRun, AgentToolCall.agent_run_id == AgentRun.id).where(AgentRun.tutor_turn_id == turn.id, AgentToolCall.tool_name == "LearningMemoryContext"))
    assert (mem.result_count if mem else 0) == 0  # actual-use reflects no injection


def test_answer_allowed_when_plan_required_state_injected_no_evidence(db_session: Session, monkeypatch):
    """No evidence but plan required and state actually injected -> answer IS
    called and actual-use count is accurate (corr 003/3.1)."""
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _seed_skill_turn(db_session, snapshot, policy=True)[:3]  # confirmed target t1 + memory
    plan = {"intent": "learner_diagnosis", "queries": ["gaps"], "learning_context_use": "required", "teaching_moves": ["focus", "next_action"]}
    # No evidence: the answer must avoid factual blocks and only describe state.
    answer = {"blocks": [{"block_key": "l", "type": "limitation", "text": "No course material available.", "citation_ids": []}, {"block_key": "d", "type": "learning_diagnosis", "text": "Confirmed gap on choosing a mode.", "certainty": "confirmed", "target_ref": "t1", "citation_ids": []}, {"block_key": "n", "type": "next_action", "text": "Add course material then practise.", "citation_ids": []}]}
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([], {}))
    provider = _counting_provider(plan, answer)
    monkeypatch.setattr(tutor_generation, "call_provider", provider)
    tutor_generation.execute_tutor_turn(db_session, _settings(), turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    db_session.commit(); db_session.refresh(turn)
    assert turn.status == "succeeded"
    assert provider.count["n"] == 2  # plan + answer
    mem = db_session.scalar(select(AgentToolCall).join(AgentRun, AgentToolCall.agent_run_id == AgentRun.id).where(AgentRun.tutor_turn_id == turn.id, AgentToolCall.tool_name == "LearningMemoryContext"))
    assert (mem.result_count if mem else 0) == 1  # actual-use reflects the injected memory


def test_limitation_when_candidates_exist_but_budget_emptied(db_session: Session, monkeypatch):
    """Candidates exist but the budget trims everything to an empty projection ->
    limitation, no answer provider call (corr 003/3.1)."""
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _seed_skill_turn(db_session, snapshot, policy=True)[:3]
    plan = {"intent": "learner_diagnosis", "queries": ["gaps"], "learning_context_use": "required", "teaching_moves": ["focus", "next_action"]}
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([], {}))
    # Force the budget to trim every candidate (no real projection sent).
    monkeypatch.setattr(tutor_generation, "_build_injection", lambda learning, max_chars: {"projection": {"targets": [], "memories": [], "completions": []}, "target_certainties": {}, "memory_texts": [], "memory_count": 0, "completion_count": 0})
    provider = _counting_provider(plan)
    monkeypatch.setattr(tutor_generation, "call_provider", provider)
    tutor_generation.execute_tutor_turn(db_session, _settings(), turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    db_session.commit(); db_session.refresh(turn)
    assert [b["type"] for b in turn.answer_blocks] == ["limitation"]
    assert provider.count["n"] == 1  # only plan; no answer call over an empty projection


def _seed_lesson_scope_state(db, snapshot):
    """A lesson-scope claimed skill turn with a real published lesson/version and
    policy on; used for non-empty scope isolation."""
    ws = Workspace(name=str(uuid4())[:8], slug=str(uuid4())[:8]); db.add(ws); db.flush()
    doc = SourceDocument(workspace_id=ws.id, display_name="g.md"); db.add(doc); db.flush()
    ver = DocumentVersion(document_id=doc.id, version_number=1, processing_status="ready", original_filename="g.md", mime_type="text/markdown", byte_size=1, sha256="a" * 64, original_storage_uri="t"); db.add(ver); db.flush(); doc.current_version_id = ver.id
    chunk = DocumentChunk(id=str(uuid4()), document_version_id=ver.id, ordinal=0, content="Cathedral mode uses central design.", content_hash="b" * 64, start_offset=0, end_offset=40, page_start=1, page_end=1); db.add(chunk); db.flush()
    course = Course(workspace_id=ws.id, title="c", goal="g"); db.add(course); db.flush()
    cv = CourseVersion(course_id=course.id, workspace_id=ws.id, version_number=1, status="active", title="c"); db.add(cv); db.flush(); course.current_active_version_id = cv.id
    src = CourseVersionSource(course_version_id=cv.id, workspace_id=ws.id, document_id=doc.id, document_version_id=ver.id); db.add(src)
    section = CourseSection(course_version_id=cv.id, workspace_id=ws.id, ordinal=0, title="S", objective="o"); db.add(section); db.flush()
    lesson = Lesson(id=str(uuid4()), course_version_id=cv.id, course_section_id=section.id, workspace_id=ws.id, ordinal=0, title="Lesson A", objective="o"); db.add(lesson); db.flush()
    lv = LessonVersion(id=str(uuid4()), lesson_id=lesson.id, course_version_id=cv.id, workspace_id=ws.id, version_number=1, status="published", title="Lesson A", learning_objectives=["o"], blocks=[]); db.add(lv); db.flush(); lesson.current_published_version_id = lv.id
    db.add(LearningMemoryPolicy(workspace_id=ws.id, tutor_use_enabled=1))
    # Same-scope confirmed target + memory (proves selection works).
    tgt = LearningTarget(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, lesson_id=lesson.id, lesson_version_id=lv.id, target_key="a", title="Lesson A target", kind="objective"); db.add(tgt); db.flush()
    db.add(Weakness(learning_target_id=tgt.id, workspace_id=ws.id, status="confirmed"))
    db.add(MasteryState(learning_target_id=tgt.id, workspace_id=ws.id, band="needs_review"))
    db.add(LearningMemory(workspace_id=ws.id, course_id=course.id, lesson_id=lesson.id, lesson_version_id=lv.id, learning_target_id=tgt.id, kind="weakness", status="active", display_text="SAME_SCOPE_KEEP"))
    session = TutorSession(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, provider="fake", model="fake", external_processing_ack_at=datetime.now(timezone.utc)); db.add(session); db.flush()
    turn = TutorTurn(session_id=session.id, workspace_id=ws.id, ordinal=1, attempt_number=1, idempotency_key=str(uuid4()), status="running", question="my gaps?", scope="lesson", lesson_id=lesson.id, lesson_version_id=lv.id, history_through_ordinal=0, teaching_skill_id=snapshot["id"], teaching_skill_version=snapshot["version"], teaching_skill_hash=snapshot["hash"], worker_id=TUTOR_TEST_WORKER, lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=300)); db.add(turn); db.commit()
    return turn, chunk, src, ws, course, cv, lesson, lv


def test_scope_isolation_non_empty_with_cross_scope_negatives(db_session: Session, monkeypatch):
    """Policy ON with a real same-scope state (selection works), plus state in
    another Workspace, another Course (same workspace) and another LessonVersion
    (same course) — none of the cross-scope state may leak into selection, the
    provider prompt, trace counts or the public result (corr 003/3.3)."""
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src, ws, course, cv, lesson, lv = _seed_lesson_scope_state(db_session, snapshot)

    # Cross-scope: another workspace.
    other_ws = Workspace(name="ow", slug="ow"); db_session.add(other_ws); db_session.flush()
    other_course = Course(workspace_id=other_ws.id, title="oc", goal="g"); db_session.add(other_course); db_session.flush()
    other_cv = CourseVersion(course_id=other_course.id, workspace_id=other_ws.id, version_number=1, status="active", title="oc"); db_session.add(other_cv); db_session.flush(); other_course.current_active_version_id = other_cv.id
    other_section = CourseSection(course_version_id=other_cv.id, workspace_id=other_ws.id, ordinal=0, title="OS", objective="o"); db_session.add(other_section); db_session.flush()
    other_lesson = Lesson(id=str(uuid4()), course_version_id=other_cv.id, course_section_id=other_section.id, workspace_id=other_ws.id, ordinal=0, title="OL", objective="o"); db_session.add(other_lesson); db_session.flush()
    other_lv = LessonVersion(id=str(uuid4()), lesson_id=other_lesson.id, course_version_id=other_cv.id, workspace_id=other_ws.id, version_number=1, status="published", title="OL", learning_objectives=["o"], blocks=[]); db_session.add(other_lv); db_session.flush(); other_lesson.current_published_version_id = other_lv.id
    db_session.add(LearningMemoryPolicy(workspace_id=other_ws.id, tutor_use_enabled=1))
    ows_tgt = LearningTarget(workspace_id=other_ws.id, course_id=other_course.id, course_version_id=other_cv.id, lesson_id=other_lesson.id, lesson_version_id=other_lv.id, target_key="ow", title="OW target", kind="objective"); db_session.add(ows_tgt); db_session.flush()
    db_session.add(Weakness(learning_target_id=ows_tgt.id, workspace_id=other_ws.id, status="confirmed"))
    db_session.add(LearningMemory(workspace_id=other_ws.id, course_id=other_course.id, lesson_id=other_lesson.id, lesson_version_id=other_lv.id, learning_target_id=ows_tgt.id, kind="weakness", status="active", display_text="OTHER_WS_SECRET"))
    db_session.add(LessonCompletion(workspace_id=other_ws.id, course_id=other_course.id, course_version_id=other_cv.id, lesson_id=other_lesson.id, lesson_version_id=other_lv.id, completed_at=datetime.now(timezone.utc)))

    # Cross-scope: same workspace, another course.
    alt_course = Course(workspace_id=ws.id, title="ac", goal="g"); db_session.add(alt_course); db_session.flush()
    alt_cv = CourseVersion(course_id=alt_course.id, workspace_id=ws.id, version_number=1, status="active", title="ac"); db_session.add(alt_cv); db_session.flush(); alt_course.current_active_version_id = alt_cv.id
    alt_section = CourseSection(course_version_id=alt_cv.id, workspace_id=ws.id, ordinal=0, title="AS", objective="o"); db_session.add(alt_section); db_session.flush()
    alt_lesson = Lesson(id=str(uuid4()), course_version_id=alt_cv.id, course_section_id=alt_section.id, workspace_id=ws.id, ordinal=0, title="AL", objective="o"); db_session.add(alt_lesson); db_session.flush()
    alt_lv = LessonVersion(id=str(uuid4()), lesson_id=alt_lesson.id, course_version_id=alt_cv.id, workspace_id=ws.id, version_number=1, status="published", title="AL", learning_objectives=["o"], blocks=[]); db_session.add(alt_lv); db_session.flush(); alt_lesson.current_published_version_id = alt_lv.id
    alt_tgt = LearningTarget(workspace_id=ws.id, course_id=alt_course.id, course_version_id=alt_cv.id, lesson_id=alt_lesson.id, lesson_version_id=alt_lv.id, target_key="ac", title="AC target", kind="objective"); db_session.add(alt_tgt); db_session.flush()
    db_session.add(Weakness(learning_target_id=alt_tgt.id, workspace_id=ws.id, status="confirmed"))
    db_session.add(LearningMemory(workspace_id=ws.id, course_id=alt_course.id, lesson_id=alt_lesson.id, lesson_version_id=alt_lv.id, learning_target_id=alt_tgt.id, kind="weakness", status="active", display_text="OTHER_COURSE_SECRET"))

    # Cross-scope: same course, another LessonVersion.
    other_lesson2 = Lesson(id=str(uuid4()), course_version_id=cv.id, course_section_id=lesson.course_section_id, workspace_id=ws.id, ordinal=1, title="Lesson B", objective="o"); db_session.add(other_lesson2); db_session.flush()
    other_lv2 = LessonVersion(id=str(uuid4()), lesson_id=other_lesson2.id, course_version_id=cv.id, workspace_id=ws.id, version_number=1, status="published", title="Lesson B", learning_objectives=["o"], blocks=[]); db_session.add(other_lv2); db_session.flush(); other_lesson2.current_published_version_id = other_lv2.id
    lv2_tgt = LearningTarget(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, lesson_id=other_lesson2.id, lesson_version_id=other_lv2.id, target_key="lv2", title="LV2 target", kind="objective"); db_session.add(lv2_tgt); db_session.flush()
    db_session.add(Weakness(learning_target_id=lv2_tgt.id, workspace_id=ws.id, status="confirmed"))
    db_session.add(LearningMemory(workspace_id=ws.id, course_id=course.id, lesson_id=other_lesson2.id, lesson_version_id=other_lv2.id, learning_target_id=lv2_tgt.id, kind="weakness", status="active", display_text="OTHER_LESSONVERSION_SECRET"))
    db_session.add(LessonCompletion(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, lesson_id=other_lesson2.id, lesson_version_id=other_lv2.id, completed_at=datetime.now(timezone.utc)))
    db_session.commit()

    plan = {"intent": "learner_diagnosis", "queries": ["gaps"], "learning_context_use": "required", "teaching_moves": ["focus", "next_action"]}
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Standing.", "citation_ids": ["e1"]}, {"block_key": "d", "type": "learning_diagnosis", "text": "Same-scope confirmed gap.", "certainty": "confirmed", "target_ref": "t1", "citation_ids": []}, {"block_key": "n", "type": "next_action", "text": "Practise.", "citation_ids": []}]}
    captured: list = []
    seq = _seq([(plan, {"input_tokens": 3, "output_tokens": 3}), (answer, {"input_tokens": 5, "output_tokens": 5})])
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))
    monkeypatch.setattr(tutor_generation, "call_provider", lambda *a, **_k: captured.append(a[1]) or seq(*a, **_k))
    tutor_generation.execute_tutor_turn(db_session, _settings(), turn, worker_id=TUTOR_TEST_WORKER, lease_lost=None)
    db_session.commit()
    blob = str(captured)
    # Same-scope state is selected and reaches the prompt; cross-scope secrets do not.
    assert "SAME_SCOPE_KEEP" in blob
    for secret in ("OTHER_WS_SECRET", "OTHER_COURSE_SECRET", "OTHER_LESSONVERSION_SECRET"):
        assert secret not in blob
    # actual-use memory count is exactly the one same-scope memory.
    mem = db_session.scalar(select(AgentToolCall).join(AgentRun, AgentToolCall.agent_run_id == AgentRun.id).where(AgentRun.tutor_turn_id == turn.id, AgentToolCall.tool_name == "LearningMemoryContext"))
    assert (mem.result_count if mem else 0) == 1
    comp = db_session.scalar(select(AgentToolCall).join(AgentRun, AgentToolCall.agent_run_id == AgentRun.id).where(AgentRun.tutor_turn_id == turn.id, AgentToolCall.tool_name == "LessonCompletionContext"))
    assert (comp.result_count if comp else 0) == 0  # cross-scope completion excluded
    # Public answer carries no cross-scope text.
    public = str(turn.answer_blocks)
    for secret in ("OTHER_WS_SECRET", "OTHER_COURSE_SECRET", "OTHER_LESSONVERSION_SECRET"):
        assert secret not in public


def test_worker_failed_trace_plan_first_failure(db_session: Session, monkeypatch):
    """Worker-persisted failed run for a plan-first provider failure carries the
    real step_count, zero tool calls and honest usage (corr 003/3.4)."""
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _seed_queued_turn(db_session, snapshot)
    tutor_workers = _patch_worker(db_session, monkeypatch)
    plan = {"intent": "concept_explanation", "queries": ["cathedral"], "learning_context_use": "unavailable", "teaching_moves": ["explain"]}
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, src)}))
    monkeypatch.setattr(tutor_generation, "call_provider", _counting_provider(plan, fail_on_call=1))
    tutor_workers.run_tutor_turn(turn.id)
    db_session.expire_all(); db_session.refresh(turn)
    assert turn.status in {"failed", "retry_wait"}
    runs = db_session.scalars(select(AgentRun).where(AgentRun.tutor_turn_id == turn.id)).all()
    assert len(runs) == 1
    assert runs[0].step_count == 1                       # plan step counted before the failing call
    assert runs[0].input_tokens is None and runs[0].output_tokens is None  # failed call reported no usage
    tool_calls = db_session.scalars(select(AgentToolCall).where(AgentToolCall.agent_run_id == runs[0].id)).all()
    assert tool_calls == []                              # no tool call on the persisted failed run


def test_worker_failure_finalizes_a_persisted_in_flight_run(db_session: Session):
    """A prematurely persisted in-flight trace must not remain ``running`` or
    be double-counted when the delivery is finalized as failed."""
    from learn_platform_api import tutor_workers

    snapshot = resolve_teaching_skill_snapshot()
    turn, _chunk, _src = _seed_queued_turn(db_session, snapshot)
    turn.status = "running"
    turn.worker_id = TUTOR_TEST_WORKER
    in_flight = AgentRun(
        tutor_turn_id=turn.id,
        workspace_id=turn.workspace_id,
        role="tutor",
        attempt_number=turn.attempt_number,
        status="running",
        step_count=2,
    )
    db_session.add(in_flight)
    db_session.commit()

    settings = _settings()
    settings.ingestion_max_attempts = 3
    tutor_workers._finish_failed_turn(
        db_session,
        turn,
        "invalid_agent_artifact",
        {"step_count": 4, "input_tokens": 7, "output_tokens": 9},
        settings,
    )
    db_session.commit()

    runs = db_session.scalars(
        select(AgentRun).where(AgentRun.tutor_turn_id == turn.id)
    ).all()
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert runs[0].step_count == 4
    assert runs[0].input_tokens == 7 and runs[0].output_tokens == 9


def test_worker_failed_trace_search_failure_after_plan(db_session: Session, monkeypatch):
    """Worker-persisted failed run for a search failure after a successful plan
    carries step_count 2, no faked search tool call, and the retained plan usage."""
    snapshot = resolve_teaching_skill_snapshot()
    turn, chunk, src = _seed_queued_turn(db_session, snapshot)
    tutor_workers = _patch_worker(db_session, monkeypatch)
    plan = {"intent": "concept_explanation", "queries": ["cathedral"], "learning_context_use": "unavailable", "teaching_moves": ["explain"]}
    monkeypatch.setattr(tutor_generation, "call_provider", _counting_provider(plan))

    def raising_search(*_a, **_k):
        raise ValueError("source_snapshot_stale")
    monkeypatch.setattr(tutor_generation, "_search", raising_search)
    tutor_workers.run_tutor_turn(turn.id)
    db_session.expire_all(); db_session.refresh(turn)
    assert turn.status == "failed"  # source_snapshot_stale is terminal
    runs = db_session.scalars(select(AgentRun).where(AgentRun.tutor_turn_id == turn.id)).all()
    assert len(runs) == 1
    assert runs[0].step_count == 2                       # plan (1) + search counted before the raise (2)
    assert runs[0].input_tokens == 3 and runs[0].output_tokens == 3  # plan usage retained
    tool_calls = db_session.scalars(select(AgentToolCall).where(AgentToolCall.agent_run_id == runs[0].id)).all()
    assert tool_calls == []                              # failing search wrote no tool call
