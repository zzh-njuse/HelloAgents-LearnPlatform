"""Stage 4 Slice 5 — worker/grading authority tests (Phases B/E/F).

Covers the v2 behavior the Slice 5 packet targets, at the service/worker
altitude (no real provider/MCP/Wolfram): artifact-contract version pinning,
the bounded near-duplicate policy, and the science grading hard boundary that
prevents an LLM from producing a numeric score when deterministic verification
is missing. Secret/provider/MCP inputs are monkeypatched; nothing reads ``.env``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from academic_companion.practice_agents import (
    ARTIFACT_CONTRACT_V2,
    HARNESS_V2,
    PracticeItemArtifact,
    ScientificAnswerSpec,
)
from learn_platform_api.db.models import (
    AgentRun, PracticeAttempt, PracticeFeedback, PracticeItem, PracticeJob, PracticeSet,
)
from learn_platform_api.services import practice_generation
from learn_platform_api.services.practice_generation import (
    _char3grams, _jaccard, _task_tokens, _validate_practice_novelty,
)
from learn_platform_api.settings import get_settings
from types import SimpleNamespace


# ---------------------------------------------------------------------------
# Phase B: artifact contract version is pinned on the Job
# ---------------------------------------------------------------------------

def test_v2_generation_job_pins_artifact_contract_v2(db_session, monkeypatch) -> None:
    from learn_platform_api.services import practice
    from test_practice_worker import _reader

    ws, course, cv, lesson, lv, chunk, doc, ver = _reader(db_session)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    payload = type("P", (), {
        "item_count": 1, "difficulty": "standard", "output_language": "zh-CN",
        "item_type_mode": "auto", "code_languages": None,
        "code_tool_authorized": False, "science_tool_authorized": False,
    })()
    job = practice.create_generation_job(db_session, get_settings(), ws.id, course.id, cv.id, lesson.id, lv.id, payload, "v2-pin")
    assert job.artifact_contract_version == ARTIFACT_CONTRACT_V2


# ---------------------------------------------------------------------------
# Phase F: bounded near-duplicate (Spec 005 §9)
# ---------------------------------------------------------------------------

def _ns_item(item_key: str, target: str, item_type: str, stem: str) -> SimpleNamespace:
    return SimpleNamespace(item_key=item_key, target_key=target, item_type=item_type, stem=stem)


def test_v2_near_duplicate_rejects_same_task_high_overlap() -> None:
    """Same target/type/task signature with char 3-gram Jaccard >= 0.90 is a
    hard reject. Both EN and ZH stems are exercised."""
    prior = (("objective_1", "short_answer", "Explain how binary search halves a sorted interval."),)
    near_dup = _ns_item("q1", "objective_1", "short_answer",
                        "Explain how binary search halves a sorted interval?")
    with pytest.raises(ValueError, match="duplicate_practice_item"):
        _validate_practice_novelty(SimpleNamespace(items=[near_dup]), prior)

    prior_zh = (("objective_1", "short_answer", "请解释二分查找如何在有序区间内折半。"),)
    near_dup_zh = _ns_item("q1", "objective_1", "short_answer",
                           "请 解释 二分查找，如何在有序区间内折半？")
    with pytest.raises(ValueError, match="duplicate_practice_item"):
        _validate_practice_novelty(SimpleNamespace(items=[near_dup_zh]), prior_zh)


def test_v2_near_duplicate_keeps_same_objective_different_angle() -> None:
    """The same objective assessed from a materially different angle must NOT be
    hard-rejected (Spec 005 §9: don't over-kill related questions)."""
    prior = (("objective_1", "short_answer", "Explain how binary search halves a sorted interval."),)
    different_angle = _ns_item("q1", "objective_1", "short_answer",
                               "What invariant does binary search maintain about the target's position?")
    # Must not raise.
    _validate_practice_novelty(SimpleNamespace(items=[different_angle]), prior)
    # A different item type on the same stem is also not an exact duplicate.
    other_type = _ns_item("q2", "objective_1", "single_choice", "Explain how binary search halves a sorted interval.")
    _validate_practice_novelty(SimpleNamespace(items=[other_type]), prior)


def test_v2_novelty_thresholds_are_bounded_and_explainable() -> None:
    """The threshold/policy constants are pinned (Spec 005 §9 / ADR 007 §3.8)."""
    from learn_platform_api.services.practice_generation import (
        NOVELTY_HARD_THRESHOLD, NOVELTY_SOFT_THRESHOLD, NOVELTY_POLICY_VERSION,
    )
    assert NOVELTY_POLICY_VERSION == "char3gram_jaccard_v1"
    assert NOVELTY_HARD_THRESHOLD == 0.90
    assert NOVELTY_SOFT_THRESHOLD == 0.75
    # Gram helper folds non-alphanumerics before slicing.
    assert _char3grams("a  b") == frozenset({"ab"})
    assert _jaccard(_task_tokens("alpha beta"), _task_tokens("alpha beta")) == 1.0
    assert _jaccard(frozenset(), frozenset({"a"})) == 0.0


# ---------------------------------------------------------------------------
# Phase E: science grading hard boundary (Spec 005 §10.2 / ADR 007 §3.5)
# ---------------------------------------------------------------------------

def _science_grading_fixture(db_session, *, science_authorized: bool):
    """Build a minimal published scientific item + grading attempt + job."""
    from learn_platform_api.db.models import (
        Course, CourseSection, CourseVersion, CourseVersionSource, DocumentChunk,
        DocumentVersion, Lesson, LessonVersion, SourceDocument, Workspace,
    )
    now = datetime.now(timezone.utc)
    db = db_session
    ws = Workspace(name="w", slug="wsci"); db.add(ws); db.flush()
    doc = SourceDocument(workspace_id=ws.id, display_name="s.md"); db.add(doc); db.flush()
    ver = DocumentVersion(document_id=doc.id, version_number=1, processing_status="ready",
                          original_filename="s", mime_type="text/markdown", byte_size=1,
                          sha256="a" * 64, original_storage_uri="t"); db.add(ver); db.flush()
    doc.current_version_id = ver.id
    chunk = DocumentChunk(id=("c" * 32)[:36], document_version_id=ver.id, ordinal=0,
                          content="Newton's second law relates force, mass and acceleration.",
                          content_hash="b" * 64, start_offset=0, end_offset=52, page_start=1, page_end=1)
    course = Course(workspace_id=ws.id, title="C", goal="g"); db.add_all([chunk, course]); db.flush()
    cv = CourseVersion(course_id=course.id, workspace_id=ws.id, version_number=1, status="active", title="C"); db.add(cv); db.flush()
    course.current_active_version_id = cv.id
    db.add(CourseVersionSource(course_version_id=cv.id, workspace_id=ws.id, document_id=doc.id, document_version_id=ver.id))
    section = CourseSection(course_version_id=cv.id, workspace_id=ws.id, ordinal=0, title="s", objective="o"); db.add(section); db.flush()
    lesson = Lesson(course_version_id=cv.id, course_section_id=section.id, workspace_id=ws.id, ordinal=0, title="L", objective="o"); db.add(lesson); db.flush()
    lv = LessonVersion(lesson_id=lesson.id, course_version_id=cv.id, workspace_id=ws.id, version_number=1,
                       status="published", title="L", learning_objectives=["o"], blocks=[]); db.add(lv); db.flush()
    lesson.current_published_version_id = lv.id
    practice_set = PracticeSet(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id,
                               lesson_id=lesson.id, lesson_version_id=lv.id, output_language="zh-CN",
                               difficulty="standard", item_count=1,
                               generation_config={"artifact_contract_version": "practice_artifact_v2"},
                               lifecycle_status="active", created_at=now); db.add(practice_set); db.flush()
    spec = {
        "scientific_answer_spec": {
            "normalized_answer": "F = m*a", "unit": "N", "equivalence_rule": "symbolic",
            "needs_remote_verification": True, "verification_expression": "F == m*a",
        },
        "rubric": [{"criterion_key": "c1", "description": "derivation", "weight": 100, "citation_ids": ["e1"]}],
        "reference_answer": "F = m a with units Newtons.", "citation_ids": [],
    }
    item = PracticeItem(practice_set_id=practice_set.id, workspace_id=ws.id, ordinal=0,
                        item_type="scientific", stem="Derive the relation between force, mass and acceleration.",
                        options=None, answer_spec=spec,
                        interaction_spec={"unit": "N", "equivalence_rule": "symbolic"},
                        created_at=now); db.add(item); db.flush()
    attempt = PracticeAttempt(workspace_id=ws.id, practice_item_id=item.id, ordinal=1, item_type="scientific",
                              answer_payload={"text": "F=ma", "science_tool_authorized": science_authorized},
                              idempotency_key="k1", status="grading", external_processing_ack_at=now); db.add(attempt); db.flush()
    job = PracticeJob(workspace_id=ws.id, job_type="grade_attempt", practice_attempt_id=attempt.id,
                      output_language="zh-CN", difficulty="standard", item_count=1,
                      request_hash="h", status="running", idempotency_key="grade-k1",
                      attempt_count=1, worker_id="w1", external_processing_ack_at=now,
                      lease_expires_at=now + timedelta(minutes=2),
                      artifact_contract_version="practice_artifact_v2"); db.add(job); db.flush()
    attempt.practice_job_id = job.id
    db.commit()
    return ws, item, attempt, job


def test_v2_science_unauthorized_is_ungradable_with_no_score(db_session, monkeypatch) -> None:
    """A symbolic scientific item that needs remote verification but was not
    authorized yields a formal ``ungradable`` Feedback with score null and a
    limitation — never an LLM numeric score. No provider call is made."""
    ws, item, attempt, job = _science_grading_fixture(db_session, science_authorized=False)

    provider_calls = []
    monkeypatch.setattr(practice_generation, "call_provider",
                        lambda *_a, **_k: provider_calls.append(1) or pytest.fail("LLM must not be called for unauthorized science"))

    practice_generation.execute_grading(db_session, get_settings(), job, worker_id="w1")
    db_session.commit()

    assert provider_calls == []  # no LLM grading
    feedback = db_session.query(PracticeFeedback).filter_by(practice_attempt_id=attempt.id).one()
    assert feedback.verdict == "ungradable"
    assert feedback.score is None
    refreshed_attempt = db_session.get(PracticeAttempt, attempt.id)
    assert refreshed_attempt.status == "succeeded"
    assert db_session.get(PracticeJob, job.id).status == "succeeded"


def test_v2_science_local_rule_decided_does_not_call_remote(db_session, monkeypatch) -> None:
    """An exact/numeric science item decidable by local rules must not invoke
    the remote tool and proceeds to LLM rubric grading with the deterministic
    signal as bounded evidence."""
    ws, item, attempt, job = _science_grading_fixture(db_session, science_authorized=True)
    # Make the item locally decidable (exact rule).
    item.answer_spec["scientific_answer_spec"]["equivalence_rule"] = "exact"
    item.answer_spec["scientific_answer_spec"]["needs_remote_verification"] = False
    db_session.flush()

    science_calls = []
    import learn_platform_api.services.science_tool_service as science_tool_service
    monkeypatch.setattr(science_tool_service, "execute_science_verification",
                        lambda *_a, **_k: science_calls.append(1) or pytest.fail("remote science must not run for local-rule item"))

    plan = iter([({"verdict": "partially_correct", "score": 60,
                   "criterion_results": [{"criterion_key": "c1", "met": "partial", "note": "n", "citation_ids": []}],
                   "blocks": [{"block_key": "b1", "type": "explanation", "text": "ok", "citation_ids": []}]}, {})])
    monkeypatch.setattr(practice_generation, "call_provider", lambda *_a, **_k: next(plan))

    practice_generation.execute_grading(db_session, get_settings(), job, worker_id="w1")
    db_session.commit()
    assert science_calls == []
    feedback = db_session.query(PracticeFeedback).filter_by(practice_attempt_id=attempt.id).one()
    assert feedback.score == 60
