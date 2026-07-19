"""Stage 4 Slice 3 paired baseline-vs-skill Tutor eval (offline).

Drives the real Stage 3 baseline Tutor and the Slice 3 diagnostic-scaffold skill
on IDENTICAL fixtures with an injected fake provider. Offline mode never contacts
an external model and never reads provider configuration; it proves the
orchestration and contract gates, NOT teaching quality.

Each case runs both paths on the same workspace/course/evidence/history/learning
state. The baseline path is reachable ONLY through this harness (and the legacy
historical-retry path); it is never a production user option (Spec 003 §2).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from learn_platform_api.db.base import Base
from learn_platform_api.db.models import (
    AgentRun, AgentToolCall, Course, CourseSection, CourseVersion, CourseVersionSource,
    DocumentChunk, DocumentVersion, Lesson, LearningMemory, LearningMemoryPolicy,
    LearningTarget, LessonCompletion, LessonVersion, MasteryState, SourceDocument,
    TutorSession, TutorTurn, TutorTurnCitation, Weakness, Workspace,
)
from learn_platform_api.services import tutor_generation
from learn_platform_api.services.tutor import resolve_teaching_skill_snapshot

#: Offline settings carry NO provider configuration. The fake provider patches
#: every model call, so these values are never sent anywhere.
SETTINGS = SimpleNamespace(
    product_generation_api_key=None,
    product_generation_base_url="https://offline.invalid",
    product_generation_model="offline-fake",
    product_generation_timeout_seconds=45.0,
    tutor_max_evidence_tokens=8_000,
    tutor_max_output_tokens=2_000,
    tutor_skill_max_evidence_tokens=10_000,
    tutor_skill_max_output_tokens=3_000,
)

CHUNK_ID = ("c" * 32)[:32]
LESSON_ID = ("l" * 32)[:32]
LESSON_VERSION_ID = ("v" * 32)[:32]


class PairedFailure(Exception):
    def __init__(self, gate: str, message: str = "") -> None:
        super().__init__(message or gate)
        self.gate = gate


def expect(condition: bool, gate: str, message: str = "") -> None:
    if not condition:
        raise PairedFailure(gate, message)


def fresh_db():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _seq(items):
    iterator = iter(items)
    return lambda *_a, **_k: next(iterator)


def _add(db, obj):
    db.add(obj); db.flush(); return obj


def _seed(db, *, evidence=True, policy=False, confirmed=False, provisional=False, completion=False, secure=False):
    """Seed an identical fixture + optional authorized learning state.

    Learning state never carries answers, rubrics, feedback or evidence text —
    only titles/display text and calibrated certainty, exactly as the production
    projection allows (Spec 003 §6, ADR 005 §3.5).
    """
    ws = _add(db, Workspace(name="paired", slug="paired"))
    doc = _add(db, SourceDocument(workspace_id=ws.id, display_name="guide.md"))
    version = _add(db, DocumentVersion(document_id=doc.id, version_number=1, processing_status="ready", original_filename="guide.md", mime_type="text/markdown", byte_size=10, sha256="a" * 64, original_storage_uri="eval"))
    doc.current_version_id = version.id
    chunk = None
    if evidence:
        chunk = _add(db, DocumentChunk(id=CHUNK_ID, document_version_id=version.id, ordinal=0, content="Cathedral mode emphasises central design and longer release cycles.", content_hash="b" * 64, start_offset=0, end_offset=64, page_start=1, page_end=1))
    course = _add(db, Course(workspace_id=ws.id, title="Software management", goal="patterns"))
    cversion = _add(db, CourseVersion(course_id=course.id, workspace_id=ws.id, version_number=1, status="active", title="Software management"))
    course.current_active_version_id = cversion.id
    source = _add(db, CourseVersionSource(course_version_id=cversion.id, workspace_id=ws.id, document_id=doc.id, document_version_id=version.id))
    # A real published lesson/version referenced by the target keeps memories
    # eligible (refresh_memory_eligibility archives memories whose lesson version
    # is superseded), so the injected memory text is genuine exercise material
    # for the no-restate and projection gates.
    section = _add(db, CourseSection(course_version_id=cversion.id, workspace_id=ws.id, ordinal=0, title="Patterns", objective="patterns"))
    lesson = _add(db, Lesson(id=LESSON_ID, course_version_id=cversion.id, course_section_id=section.id, workspace_id=ws.id, ordinal=0, title="Cathedral and bazaar", objective="patterns"))
    lesson_version = _add(db, LessonVersion(id=LESSON_VERSION_ID, lesson_id=lesson.id, course_version_id=cversion.id, workspace_id=ws.id, version_number=1, status="published", title=lesson.title, learning_objectives=["patterns"], blocks=[]))
    lesson.current_published_version_id = lesson_version.id
    if policy:
        _add(db, LearningMemoryPolicy(workspace_id=ws.id, tutor_use_enabled=1))
    if confirmed or provisional or secure:
        target = _add(db, LearningTarget(workspace_id=ws.id, course_id=course.id, course_version_id=cversion.id, lesson_id=LESSON_ID, lesson_version_id=LESSON_VERSION_ID, target_key="lesson_overall", title="Choosing a development mode", kind="lesson_overall"))
        if confirmed:
            _add(db, Weakness(learning_target_id=target.id, workspace_id=ws.id, status="confirmed"))
        if provisional:
            _add(db, Weakness(learning_target_id=target.id, workspace_id=ws.id, status="provisional"))
        if secure:
            _add(db, Weakness(learning_target_id=target.id, workspace_id=ws.id, status="resolved"))
        _add(db, MasteryState(learning_target_id=target.id, workspace_id=ws.id, band="secure" if secure else "needs_review"))
        if confirmed:
            _add(db, LearningMemory(workspace_id=ws.id, course_id=course.id, lesson_id=LESSON_ID, lesson_version_id=LESSON_VERSION_ID, learning_target_id=target.id, kind="weakness", status="active", display_text="需要继续巩固：根据项目条件选择开发模式"))
    if completion:
        _add(db, LessonCompletion(workspace_id=ws.id, course_id=course.id, course_version_id=cversion.id, lesson_id=lesson.id, lesson_version_id=LESSON_VERSION_ID, completed_at=datetime.now(timezone.utc)))
    db.commit()
    return ws, course, cversion, chunk, source


TUTOR_EVAL_WORKER = "eval-tutor-worker"


def _claim(turn):
    turn.status = "running"
    turn.worker_id = TUTOR_EVAL_WORKER
    turn.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=300)


def _make_turn(db, ws, course, cversion, snapshot, *, question):
    session = _add(db, TutorSession(workspace_id=ws.id, course_id=course.id, course_version_id=cversion.id, provider="fake", model="fake", external_processing_ack_at=datetime.now(timezone.utc)))
    turn = TutorTurn(session_id=session.id, workspace_id=ws.id, ordinal=1, attempt_number=1, idempotency_key=f"pair-{uuid4()}", status="running", question=question, scope="course", history_through_ordinal=0,
                     teaching_skill_id=snapshot["id"] if snapshot else None, teaching_skill_version=snapshot["version"] if snapshot else None, teaching_skill_hash=snapshot["hash"] if snapshot else None)
    _claim(turn)
    _add(db, turn); db.commit()
    return session, turn


def _run_pair(db, ws, course, cversion, snapshot, *, question, evidence_fn, baseline_provider, skill_provider):
    _, base_turn = _make_turn(db, ws, course, cversion, None, question=question)
    with _patch((tutor_generation, "_search", evidence_fn), (tutor_generation, "call_provider", baseline_provider)):
        tutor_generation.execute_tutor_turn(db, SETTINGS, base_turn, worker_id=TUTOR_EVAL_WORKER, lease_lost=None); db.commit()
    _, skill_turn = _make_turn(db, ws, course, cversion, snapshot, question=question)
    with _patch((tutor_generation, "_search", evidence_fn), (tutor_generation, "call_provider", skill_provider)):
        tutor_generation.execute_tutor_turn(db, SETTINGS, skill_turn, worker_id=TUTOR_EVAL_WORKER, lease_lost=None); db.commit()
    return base_turn, skill_turn


def _types(turn):
    return [block["type"] for block in (turn.answer_blocks or [])]


def _run_with_evidence(chunk, source):
    return lambda *_a: ([{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, source)})


def _run_usage(db, turn):
    run = db.execute(select(AgentRun).where(AgentRun.tutor_turn_id == turn.id)).scalar_one_or_none()
    if run is None:
        return 0, 0
    return run.input_tokens or 0, run.output_tokens or 0


class _patch:
    """Tiny context manager swapping (obj, attr, value) tuples and restoring."""

    def __init__(self, *targets):
        self.targets = targets
        self.saved = []

    def __enter__(self):
        self.saved = [(obj, attr, getattr(obj, attr)) for obj, attr, _ in self.targets]
        for obj, attr, value in self.targets:
            setattr(obj, attr, value)
        return self

    def __exit__(self, *_exc):
        for obj, attr, original in self.saved:
            setattr(obj, attr, original)
        return False


def _common_gates(db, base_turn, skill_turn, snapshot):
    expect(bool(skill_turn.teaching_skill_id) and bool(skill_turn.teaching_skill_version) and bool(skill_turn.teaching_skill_hash), "skill_snapshot_set")
    expect(base_turn.teaching_skill_id is None and base_turn.teaching_skill_hash is None, "baseline_snapshot_null")
    expect(skill_turn.teaching_skill_hash == snapshot["hash"], "skill_snapshot_hash_matches")
    chunk_ids = {row[0] for row in db.execute(select(TutorTurnCitation.document_chunk_id).where(TutorTurnCitation.turn_id == skill_turn.id)).all()}
    expect(chunk_ids <= {CHUNK_ID}, "citations_in_ledger")
    loads = list(db.execute(select(AgentToolCall).where(AgentToolCall.tool_name == "TeachingSkillLoad")).scalars().all())
    expect(bool(loads) and all(call.input_hash == snapshot["hash"] for call in loads), "skill_load_trace_hash")
    trace_blob = str([(call.tool_name, call.error_code, call.input_hash) for call in db.execute(select(AgentToolCall)).scalars().all()])
    expect(skill_turn.question not in trace_blob, "no_question_in_trace")


# --------------------------------------------------------------------------- #
# Cases
# --------------------------------------------------------------------------- #

def _concept_explanation(db, snapshot, question):
    ws, course, cversion, chunk, source = _seed(db, evidence=True, policy=True, confirmed=True)
    ev = _run_with_evidence(chunk, source)
    plan = {"intent": "concept_explanation", "queries": ["cathedral release cycle"], "learning_context_use": "irrelevant", "teaching_moves": ["explain"]}
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Cathedral mode uses central design and longer cycles.", "citation_ids": ["e1"]}, {"block_key": "n", "type": "next_action", "text": "Read the bazaar section next.", "citation_ids": []}]}
    base_turn, skill_turn = _run_pair(db, ws, course, cversion, snapshot, question=question, evidence_fn=ev,
        baseline_provider=_seq([({"queries": ["cathedral"]}, {"input_tokens": 2, "output_tokens": 2}), ({"blocks": [{"block_key": "a", "type": "explanation", "text": "Central design.", "citation_ids": ["e1"]}]}, {"input_tokens": 6, "output_tokens": 6})]),
        skill_provider=_seq([(plan, {"input_tokens": 3, "output_tokens": 3}), (answer, {"input_tokens": 10, "output_tokens": 10})]))
    _common_gates(db, base_turn, skill_turn, snapshot)
    expect(base_turn.status == "succeeded" and skill_turn.status == "succeeded", "both_succeeded")
    expect("learning_diagnosis" not in _types(skill_turn), "no_diagnosis_when_irrelevant")
    expect("direct_answer" in _types(skill_turn), "answers_actual_question")
    return base_turn, skill_turn


def _learner_diagnosis(db, snapshot, question):
    ws, course, cversion, chunk, source = _seed(db, evidence=True, policy=True, confirmed=True)
    ev = _run_with_evidence(chunk, source)
    plan = {"intent": "learner_diagnosis", "queries": ["development mode choice"], "learning_context_use": "required", "teaching_moves": ["focus", "next_action"]}
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Here is where you stand.", "citation_ids": ["e1"]}, {"block_key": "d", "type": "learning_diagnosis", "text": "You have a confirmed gap in mapping project conditions to a mode, plus a provisional signal on basic differences.", "certainty": "confirmed", "target_ref": "t1", "citation_ids": []}, {"block_key": "n", "type": "next_action", "text": "Practise choosing a mode for two sample projects.", "citation_ids": []}]}
    base_turn, skill_turn = _run_pair(db, ws, course, cversion, snapshot, question=question, evidence_fn=ev,
        baseline_provider=_seq([({"queries": ["weakness"]}, {"input_tokens": 2, "output_tokens": 2}), ({"blocks": [{"block_key": "m", "type": "memory_summary", "text": "review mode choice", "citation_ids": []}]}, {"input_tokens": 6, "output_tokens": 6})]),
        skill_provider=_seq([(plan, {"input_tokens": 3, "output_tokens": 3}), (answer, {"input_tokens": 12, "output_tokens": 12})]))
    _common_gates(db, base_turn, skill_turn, snapshot)
    expect(base_turn.status == "succeeded" and skill_turn.status == "succeeded", "both_succeeded")
    diagnosis = next((block for block in skill_turn.answer_blocks if block["type"] == "learning_diagnosis"), None)
    expect(diagnosis is not None and diagnosis["certainty"] in {"confirmed", "provisional", "insufficient"}, "diagnosis_calibrated")
    expect(any(t in {"learning_diagnosis", "next_action"} for t in _types(skill_turn)), "has_synthesized_action")
    return base_turn, skill_turn


def _study_planning(db, snapshot, question):
    ws, course, cversion, chunk, source = _seed(db, evidence=True, policy=True, confirmed=True)
    ev = _run_with_evidence(chunk, source)
    plan = {"intent": "study_planning", "queries": ["next study step mode"], "learning_context_use": "required", "teaching_moves": ["focus", "explain", "next_action"]}
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Prioritise mode selection.", "citation_ids": ["e1"]}, {"block_key": "d", "type": "learning_diagnosis", "text": "Your main gap is applying conditions to choose a mode.", "certainty": "confirmed", "target_ref": "t1", "citation_ids": []}, {"block_key": "n", "type": "next_action", "text": "Write one reason for each of two sample projects.", "citation_ids": []}]}
    base_turn, skill_turn = _run_pair(db, ws, course, cversion, snapshot, question=question, evidence_fn=ev,
        baseline_provider=_seq([({"queries": ["plan"]}, {"input_tokens": 2, "output_tokens": 2}), ({"blocks": [{"block_key": "m", "type": "memory_summary", "text": "continue mode choice", "citation_ids": []}]}, {"input_tokens": 6, "output_tokens": 6})]),
        skill_provider=_seq([(plan, {"input_tokens": 3, "output_tokens": 3}), (answer, {"input_tokens": 12, "output_tokens": 12})]))
    _common_gates(db, base_turn, skill_turn, snapshot)
    expect(base_turn.status == "succeeded" and skill_turn.status == "succeeded", "both_succeeded")
    expect(any(t in {"learning_diagnosis", "next_action"} for t in _types(skill_turn)), "has_synthesized_action")
    memory_text = "需要继续巩固：根据项目条件选择开发模式"
    actions = [block["text"] for block in skill_turn.answer_blocks if block["type"] == "next_action"]
    expect(all(not tutor_generation._restates_memory(action, [memory_text]) for action in actions), "no_restate")
    return base_turn, skill_turn


def _self_check(db, snapshot, question):
    ws, course, cversion, chunk, source = _seed(db, evidence=True, policy=False)
    ev = _run_with_evidence(chunk, source)
    plan = {"intent": "self_check", "queries": ["cathedral mode check"], "learning_context_use": "unavailable", "teaching_moves": ["check"]}
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Here is a self-check.", "citation_ids": ["e1"]}, {"block_key": "c", "type": "check_question", "text": "Which project suits the bazaar mode and why?", "citation_ids": []}]}
    base_turn, skill_turn = _run_pair(db, ws, course, cversion, snapshot, question=question, evidence_fn=ev,
        baseline_provider=_seq([({"queries": ["check"]}, {"input_tokens": 2, "output_tokens": 2}), ({"blocks": [{"block_key": "a", "type": "explanation", "text": "central", "citation_ids": ["e1"]}]}, {"input_tokens": 6, "output_tokens": 6})]),
        skill_provider=_seq([(plan, {"input_tokens": 3, "output_tokens": 3}), (answer, {"input_tokens": 10, "output_tokens": 10})]))
    _common_gates(db, base_turn, skill_turn, snapshot)
    expect(base_turn.status == "succeeded" and skill_turn.status == "succeeded", "both_succeeded")
    expect("check_question" in _types(skill_turn), "has_check_question")
    return base_turn, skill_turn


def _neg_memory_irrelevant(db, snapshot, question):
    ws, course, cversion, chunk, source = _seed(db, evidence=True, policy=True, confirmed=True)
    ev = _run_with_evidence(chunk, source)
    plan = {"intent": "concept_explanation", "queries": ["cathedral definition"], "learning_context_use": "irrelevant", "teaching_moves": ["explain"]}
    answer = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Cathedral mode is central design.", "citation_ids": ["e1"]}]}
    base_turn, skill_turn = _run_pair(db, ws, course, cversion, snapshot, question=question, evidence_fn=ev,
        baseline_provider=_seq([({"queries": ["cathedral"]}, {"input_tokens": 2, "output_tokens": 2}), ({"blocks": [{"block_key": "a", "type": "explanation", "text": "central", "citation_ids": ["e1"]}]}, {"input_tokens": 6, "output_tokens": 6})]),
        skill_provider=_seq([(plan, {"input_tokens": 3, "output_tokens": 3}), (answer, {"input_tokens": 8, "output_tokens": 8})]))
    _common_gates(db, base_turn, skill_turn, snapshot)
    expect("learning_diagnosis" not in _types(skill_turn), "no_forced_personalization")
    expect("direct_answer" in _types(skill_turn), "answers_fact_directly")
    return base_turn, skill_turn


def _neg_no_evidence_no_state(db, snapshot, question):
    ws, course, cversion, _chunk, _source = _seed(db, evidence=False, policy=False)
    ev = lambda *_a: ([], {})
    base_turn, skill_turn = _run_pair(db, ws, course, cversion, snapshot, question=question, evidence_fn=ev,
        baseline_provider=_seq([({"queries": ["x"]}, {"input_tokens": 1, "output_tokens": 1})]),
        skill_provider=_seq([({"intent": "concept_explanation", "queries": ["x"], "learning_context_use": "unavailable", "teaching_moves": ["explain"]}, {"input_tokens": 1, "output_tokens": 1})]))
    _common_gates(db, base_turn, skill_turn, snapshot)
    expect(base_turn.status == "succeeded" and skill_turn.status == "succeeded", "both_succeeded")
    expect(_types(skill_turn) == ["limitation"], "honest_limitation")
    expect(_types(base_turn) == ["limitation"], "baseline_also_honest")
    return base_turn, skill_turn


def _neg_only_provisional(db, snapshot, question):
    ws, course, cversion, chunk, source = _seed(db, evidence=True, policy=True, provisional=True)
    ev = _run_with_evidence(chunk, source)
    plan = {"intent": "learner_diagnosis", "queries": ["gaps"], "learning_context_use": "required", "teaching_moves": ["focus", "next_action"]}
    bad = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Standing.", "citation_ids": ["e1"]}, {"block_key": "d", "type": "learning_diagnosis", "text": "You have a confirmed weakness here.", "certainty": "confirmed", "target_ref": "t1", "citation_ids": []}]}
    good = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Standing.", "citation_ids": ["e1"]}, {"block_key": "d", "type": "learning_diagnosis", "text": "There is a provisional signal worth checking.", "certainty": "provisional", "target_ref": "t1", "citation_ids": []}, {"block_key": "n", "type": "next_action", "text": "Verify with one more exercise.", "citation_ids": []}]}
    base_turn, skill_turn = _run_pair(db, ws, course, cversion, snapshot, question=question, evidence_fn=ev,
        baseline_provider=_seq([({"queries": ["gaps"]}, {"input_tokens": 2, "output_tokens": 2}), ({"blocks": [{"block_key": "a", "type": "explanation", "text": "central", "citation_ids": ["e1"]}]}, {"input_tokens": 6, "output_tokens": 6})]),
        skill_provider=_seq([(plan, {"input_tokens": 3, "output_tokens": 3}), (bad, {"input_tokens": 5, "output_tokens": 5}), (good, {"input_tokens": 5, "output_tokens": 5})]))
    _common_gates(db, base_turn, skill_turn, snapshot)
    expect(skill_turn.status == "succeeded", "repaired_after_overclaim")
    diagnosis = next((block for block in skill_turn.answer_blocks if block["type"] == "learning_diagnosis"), None)
    expect(diagnosis is not None and diagnosis["certainty"] != "confirmed", "provisional_not_confirmed")
    return base_turn, skill_turn


def _neg_only_completion(db, snapshot, question):
    ws, course, cversion, chunk, source = _seed(db, evidence=True, policy=True, completion=True)
    ev = _run_with_evidence(chunk, source)
    plan = {"intent": "learner_diagnosis", "queries": ["progress"], "learning_context_use": "required", "teaching_moves": ["focus", "next_action"]}
    bad = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Progress.", "citation_ids": ["e1"]}, {"block_key": "d", "type": "learning_diagnosis", "text": "You have mastered this lesson.", "certainty": "confirmed", "target_ref": "t1", "citation_ids": []}]}
    good = {"blocks": [{"block_key": "a", "type": "direct_answer", "text": "Progress.", "citation_ids": ["e1"]}, {"block_key": "l", "type": "limitation", "text": "Completion records reading only; mastery is not established from exercises yet.", "citation_ids": []}, {"block_key": "n", "type": "next_action", "text": "Complete a practice set to establish evidence.", "citation_ids": []}]}
    base_turn, skill_turn = _run_pair(db, ws, course, cversion, snapshot, question=question, evidence_fn=ev,
        baseline_provider=_seq([({"queries": ["progress"]}, {"input_tokens": 2, "output_tokens": 2}), ({"blocks": [{"block_key": "a", "type": "explanation", "text": "central", "citation_ids": ["e1"]}]}, {"input_tokens": 6, "output_tokens": 6})]),
        skill_provider=_seq([(plan, {"input_tokens": 3, "output_tokens": 3}), (bad, {"input_tokens": 5, "output_tokens": 5}), (good, {"input_tokens": 5, "output_tokens": 5})]))
    _common_gates(db, base_turn, skill_turn, snapshot)
    expect(skill_turn.status == "succeeded", "repaired_after_mastery_claim")
    # Completion cannot support a mastery diagnosis; the repaired answer must not
    # carry a learning_diagnosis, only an honest limitation + next action.
    expect(not any(block["type"] == "learning_diagnosis" for block in skill_turn.answer_blocks), "completion_not_mastery")
    expect(any(block["type"] == "next_action" for block in skill_turn.answer_blocks), "completion_not_mastery")
    return base_turn, skill_turn


#: Each intent has three distinct surface phrasings. They share identical
#: fixtures and identical fake-provider plans/answers, so any product branching
#: on surface keywords would diverge and fail the gates — the no-keyword-
#: hardcoding proof (Spec 003 §5.8, §14.1).
_INTENT_PHRASINGS = {
    "concept_explanation": ("解释一下大教堂模式的发布节奏", "大教堂模式的发布周期是怎样的", "说明大教堂模式如何发布"),
    "learner_diagnosis": ("我的薄弱点是什么", "我哪里掌握得不好", "哪些地方还需要巩固"),
    "study_planning": ("接下来学什么", "下一步该怎么安排", "现在最应该补哪块"),
    "self_check": ("出个题考考我", "给我一个自测问题", "怎么检验我学会了没"),
}
_INTENT_RUNNERS = {
    "concept_explanation": _concept_explanation,
    "learner_diagnosis": _learner_diagnosis,
    "study_planning": _study_planning,
    "self_check": _self_check,
}


def _build_paired_cases() -> list[dict]:
    cases: list[dict] = []
    for intent, phrases in _INTENT_PHRASINGS.items():
        for index, phrase in enumerate(phrases, start=1):
            cases.append({"id": f"paired_{intent}_v{index}", "intent": intent, "phrase": phrase, "runner": _INTENT_RUNNERS[intent]})
    cases.append({"id": "paired_neg_memory_irrelevant", "intent": "neg_memory_irrelevant", "phrase": "大教堂模式强调集中设计吗", "runner": _neg_memory_irrelevant})
    cases.append({"id": "paired_neg_no_evidence_no_state", "intent": "neg_no_evidence", "phrase": "资料里完全没有相关内容吗", "runner": _neg_no_evidence_no_state})
    cases.append({"id": "paired_neg_only_provisional", "intent": "neg_only_provisional", "phrase": "我的薄弱点是什么", "runner": _neg_only_provisional})
    cases.append({"id": "paired_neg_only_completion", "intent": "neg_only_completion", "phrase": "我学得怎么样了", "runner": _neg_only_completion})
    return cases


PAIRED_CASES = _build_paired_cases()


def empty_paired_rubric() -> dict:
    return {name: None for name in ("responsiveness", "evidence_fidelity", "calibration", "synthesis", "priority", "actionability", "explanation_depth", "uncertainty")}


def run_paired_case(spec: dict) -> dict:
    """Run one baseline-vs-skill pair and return a rich result dict.

    Never raises on a gate miss — records ``skill_status="failed"`` and the gate
    name so the caller can fold the failure into the hard-gate totals.
    """
    start = time.perf_counter()
    snapshot = resolve_teaching_skill_snapshot()
    try:
        db = fresh_db()
        spec["runner"](db, snapshot, spec["phrase"])
        skill_turn = db.execute(select(TutorTurn).where(TutorTurn.teaching_skill_id.is_not(None)).order_by(TutorTurn.created_at.desc()).limit(1)).scalar_one()
        base_turn = db.execute(select(TutorTurn).where(TutorTurn.teaching_skill_id.is_(None)).order_by(TutorTurn.created_at.desc()).limit(1)).scalar_one()
        b_in, b_out = _run_usage(db, base_turn)
        s_in, s_out = _run_usage(db, skill_turn)
        baseline_status = "succeeded" if base_turn.status == "succeeded" else "failed"
        skill_status = "succeeded" if skill_turn.status == "succeeded" else "failed"
        gates = {"all_gates_passed": skill_status == "succeeded" and baseline_status == "succeeded"}
        error_gate = None if skill_status == "succeeded" else "skill_gate_missed"
    except PairedFailure as exc:
        baseline_status = "failed"; skill_status = "failed"
        gates = {exc.gate: False}; error_gate = exc.gate
        b_in = b_out = s_in = s_out = 0
    return {
        "case_id": spec["id"], "intent": spec["intent"],
        "baseline_status": baseline_status, "skill_status": skill_status,
        "gates": gates, "error_gate": error_gate,
        "duration_ms": int(round((time.perf_counter() - start) * 1000)),
        "usage": {"baseline_input_tokens": b_in, "baseline_output_tokens": b_out, "skill_input_tokens": s_in, "skill_output_tokens": s_out},
        "human_rubric": empty_paired_rubric(),
    }
