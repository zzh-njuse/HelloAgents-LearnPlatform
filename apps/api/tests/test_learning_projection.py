"""Focused tests for the deterministic learning projection pipeline."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from learn_platform_api.db.models import (
    Course, CourseSection, CourseVersion, CourseVersionSource, DocumentChunk, DocumentVersion,
    LearningEvent, LearningMemory, LearningTarget, MasterySignal, MasteryState,
    PracticeAttempt, PracticeFeedback, PracticeItem, PracticeItemTarget, PracticeSet,
    ReviewItem, SourceDocument, Weakness, Workspace, Lesson, LessonVersion,
)
from learn_platform_api.services.learning_projection import (
    project_attempt_feedback, delete_attempt_learning_facts, _recompute_target,
)
from learn_platform_api.settings import get_settings


def _seed(db: Session):
    ws = Workspace(name="lp", slug="lp"); db.add(ws); db.flush()
    doc = SourceDocument(workspace_id=ws.id, display_name="g.md"); db.add(doc); db.flush()
    ver = DocumentVersion(document_id=doc.id, version_number=1, processing_status="ready", original_filename="g", mime_type="text/markdown", byte_size=1, sha256="a"*64, original_storage_uri="t"); db.add(ver); db.flush(); doc.current_version_id = ver.id
    chunk = DocumentChunk(id="f"*32+"1"*4, document_version_id=ver.id, ordinal=0, content="c", content_hash="b"*64, start_offset=0, end_offset=1)
    course = Course(workspace_id=ws.id, title="C", goal="g"); db.add_all([chunk, course]); db.flush()
    cv = CourseVersion(course_id=course.id, workspace_id=ws.id, version_number=1, status="active", title="C"); db.add(cv); db.flush(); course.current_active_version_id = cv.id
    db.add(CourseVersionSource(course_version_id=cv.id, workspace_id=ws.id, document_id=doc.id, document_version_id=ver.id))
    sec = CourseSection(course_version_id=cv.id, workspace_id=ws.id, ordinal=0, title="s", objective="o"); db.add(sec); db.flush()
    lesson = Lesson(course_version_id=cv.id, course_section_id=sec.id, workspace_id=ws.id, ordinal=0, title="L", objective="o"); db.add(lesson); db.flush()
    lv = LessonVersion(lesson_id=lesson.id, course_version_id=cv.id, workspace_id=ws.id, version_number=1, status="published", title="L", learning_objectives=["Explain X"], blocks=[]); db.add(lv); db.flush(); lesson.current_published_version_id = lv.id
    target = LearningTarget(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, lesson_id=lesson.id, lesson_version_id=lv.id, target_key="lesson_overall", title="Lesson L", kind="lesson_overall")
    db.add(target); db.flush()
    ps = PracticeSet(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, lesson_id=lesson.id, lesson_version_id=lv.id, output_language="zh-CN", difficulty="standard", item_count=2, generation_config={}, lifecycle_status="active")
    db.add(ps); db.flush()
    db.commit()
    return ws, course, cv, lesson, lv, target, ps, doc, ver


def _make_attempt(db, ws, ps, target, item_ordinal, option_key, correct, idem):
    """Seed an item, target mapping, attempt + feedback, and project."""
    item = PracticeItem(practice_set_id=ps.id, workspace_id=ws.id, ordinal=item_ordinal, item_type="single_choice", stem="q", options=[{"option_key":"a","text":"A"},{"option_key":"b","text":"B"}], answer_spec={"correct_option_key":"a" if correct else "b"})
    db.add(item); db.flush()
    db.add(PracticeItemTarget(practice_item_id=item.id, learning_target_id=target.id, workspace_id=ws.id, criterion_key=None))
    att = PracticeAttempt(workspace_id=ws.id, practice_item_id=item.id, ordinal=1, item_type="single_choice", answer_payload={"option_key": option_key}, idempotency_key=idem, status="succeeded", completed_at=datetime.now(timezone.utc))
    db.add(att); db.flush()
    verdict = "correct" if option_key == ("a" if correct else "b") else "incorrect"
    fb = PracticeFeedback(practice_attempt_id=att.id, workspace_id=ws.id, verdict=verdict, score=100 if verdict=="correct" else 0, criterion_results=None, feedback_blocks=[], is_ai_graded=0)
    db.add(fb); db.flush(); db.commit()
    project_attempt_feedback(db, ws.id, att, fb)
    db.commit()
    return att, fb


def test_one_incorrect_creates_provisional_weakness_no_memory(db_session: Session) -> None:
    ws, course, cv, lesson, lv, target, ps, *_ = _seed(db_session)
    _make_attempt(db_session, ws, ps, target, 0, "b", correct_key_is_a=True, idem="a1")
    weakness = db_session.query(Weakness).filter_by(learning_target_id=target.id).one()
    assert weakness.status == "provisional"
    assert db_session.query(LearningMemory).filter_by(learning_target_id=target.id).count() == 0


def test_two_different_items_confirm_weakness_and_create_memory(db_session: Session) -> None:
    ws, course, cv, lesson, lv, target, ps, *_ = _seed(db_session)
    _make_attempt(db_session, ws, ps, target, 0, "b", correct_key_is_a=True, idem="a1")
    _make_attempt(db_session, ws, ps, target, 1, "b", correct_key_is_a=True, idem="a2")
    weakness = db_session.query(Weakness).filter_by(learning_target_id=target.id).one()
    assert weakness.status == "confirmed"
    mems = db_session.query(LearningMemory).filter_by(learning_target_id=target.id).count()
    assert mems == 1, f"expected exactly 1 auto memory, got {mems}"


def test_idempotent_replay_no_duplicates(db_session: Session) -> None:
    ws, *_ = _seed(db_session)
    target = db_session.query(LearningTarget).first()
    ps = db_session.query(PracticeSet).first()
    att, fb = _make_attempt(db_session, ws, ps, target, 0, "b", correct_key_is_a=True, idem="a1")
    events_before = db_session.query(LearningEvent).count()
    signals_before = db_session.query(MasterySignal).count()
    # Replay the same feedback.
    project_attempt_feedback(db_session, ws.id, att, fb)
    db_session.commit()
    assert db_session.query(LearningEvent).count() == events_before
    assert db_session.query(MasterySignal).count() == signals_before


def test_delete_attempt_removes_facts_and_recomputes(db_session: Session) -> None:
    ws, *_ = _seed(db_session)
    target = db_session.query(LearningTarget).first()
    ps = db_session.query(PracticeSet).first()
    att, fb = _make_attempt(db_session, ws, ps, target, 0, "b", correct_key_is_a=True, idem="a1")
    affected = delete_attempt_learning_facts(db_session, ws.id, att.id, fb.id)
    for tid in affected:
        _recompute_target(db_session, tid, ws.id)
    db_session.commit()
    assert db_session.query(LearningEvent).filter_by(workspace_id=ws.id).count() == 0
    assert db_session.query(MasterySignal).filter_by(workspace_id=ws.id).count() == 0
    # Weakness with no signals should be cleaned up.
    assert db_session.query(Weakness).filter_by(workspace_id=ws.id).count() == 0


def test_correct_answer_no_weakness(db_session: Session) -> None:
    ws, *_ = _seed(db_session)
    target = db_session.query(LearningTarget).first()
    ps = db_session.query(PracticeSet).first()
    _make_attempt(db_session, ws, ps, target, 0, "a", correct_key_is_a=True, idem="ok1")
    assert db_session.query(Weakness).filter_by(workspace_id=ws.id).count() == 0
    state = db_session.query(MasteryState).filter_by(learning_target_id=target.id).one()
    assert state.band in ("insufficient", "developing")  # 1 correct answer, <2 distinct attempts


# Helper alias to make the test signatures cleaner
def _make_attempt(db, ws, ps, target, item_ordinal, option_key, correct_key_is_a, idem):
    correct = correct_key_is_a
    item = PracticeItem(practice_set_id=ps.id, workspace_id=ws.id, ordinal=item_ordinal, item_type="single_choice", stem="q", options=[{"option_key":"a","text":"A"},{"option_key":"b","text":"B"}], answer_spec={"correct_option_key":"a" if correct else "b"})
    db.add(item); db.flush()
    db.add(PracticeItemTarget(practice_item_id=item.id, learning_target_id=target.id, workspace_id=ws.id, criterion_key=None))
    att = PracticeAttempt(workspace_id=ws.id, practice_item_id=item.id, ordinal=1, item_type="single_choice", answer_payload={"option_key": option_key}, idempotency_key=idem, status="succeeded", completed_at=datetime.now(timezone.utc))
    db.add(att); db.flush()
    is_correct = option_key == ("a" if correct else "b")
    verdict = "correct" if is_correct else "incorrect"
    fb = PracticeFeedback(practice_attempt_id=att.id, workspace_id=ws.id, verdict=verdict, score=100 if is_correct else 0, criterion_results=None, feedback_blocks=[], is_ai_graded=0)
    db.add(fb); db.flush(); db.commit()
    project_attempt_feedback(db, ws.id, att, fb)
    db.commit()
    return att, fb
