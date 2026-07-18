"""Batch A focused tests: learning target, item target and ORM round-trip."""

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from learn_platform_api.db.models import (
    Course, CourseSection, CourseVersion, CourseVersionSource, DocumentChunk, DocumentVersion,
    LearningEvent, LearningMemory, LearningMemoryPolicy, LearningMemorySource, LearningMemoryRevision,
    LearningTarget, MasterySignal, MasteryState, PracticeAttempt, PracticeFeedback, PracticeItem,
    PracticeItemTarget, PracticeSet, ReviewAction, ReviewItem, SourceDocument, Weakness, Workspace,
    Lesson, LessonVersion,
)


def _seed(db: Session):
    ws = Workspace(name="s2", slug="s2"); db.add(ws); db.flush()
    doc = SourceDocument(workspace_id=ws.id, display_name="g.md"); db.add(doc); db.flush()
    ver = DocumentVersion(document_id=doc.id, version_number=1, processing_status="ready", original_filename="g", mime_type="text/markdown", byte_size=1, sha256="a"*64, original_storage_uri="t"); db.add(ver); db.flush(); doc.current_version_id = ver.id
    chunk = DocumentChunk(id="d"*32+"1"*4, document_version_id=ver.id, ordinal=0, content="content", content_hash="b"*64, start_offset=0, end_offset=7)
    course = Course(workspace_id=ws.id, title="C", goal="g"); db.add_all([chunk, course]); db.flush()
    cv = CourseVersion(course_id=course.id, workspace_id=ws.id, version_number=1, status="active", title="C"); db.add(cv); db.flush(); course.current_active_version_id = cv.id
    db.add(CourseVersionSource(course_version_id=cv.id, workspace_id=ws.id, document_id=doc.id, document_version_id=ver.id))
    sec = CourseSection(course_version_id=cv.id, workspace_id=ws.id, ordinal=0, title="s", objective="o"); db.add(sec); db.flush()
    lesson = Lesson(course_version_id=cv.id, course_section_id=sec.id, workspace_id=ws.id, ordinal=0, title="L", objective="o"); db.add(lesson); db.flush()
    lv = LessonVersion(lesson_id=lesson.id, course_version_id=cv.id, workspace_id=ws.id, version_number=1, status="published", title="L", learning_objectives=["Explain X", "Apply Y"], blocks=[]); db.add(lv); db.flush(); lesson.current_published_version_id = lv.id
    db.commit()
    return ws, course, cv, lesson, lv, chunk, doc, ver


def test_learning_target_unique_per_version(db_session: Session) -> None:
    ws, course, cv, lesson, lv, *_ = _seed(db_session)
    t1 = LearningTarget(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, lesson_id=lesson.id, lesson_version_id=lv.id, target_key="objective_1", title="Explain X", kind="objective")
    db_session.add(t1); db_session.commit()
    dup = LearningTarget(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, lesson_id=lesson.id, lesson_version_id=lv.id, target_key="objective_1", title="dup", kind="objective")
    db_session.add(dup)
    with pytest.raises(Exception):
        db_session.commit()
    db_session.rollback()


def test_target_kinds(db_session: Session) -> None:
    ws, course, cv, lesson, lv, *_ = _seed(db_session)
    db_session.add(LearningTarget(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, lesson_id=lesson.id, lesson_version_id=lv.id, target_key="objective_1", title="X", kind="objective"))
    db_session.add(LearningTarget(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, lesson_id=lesson.id, lesson_version_id=lv.id, target_key="lesson_overall", title="Lesson", kind="lesson_overall"))
    db_session.commit()
    assert db_session.query(LearningTarget).filter_by(lesson_version_id=lv.id).count() == 2


def test_signal_event_target_unique(db_session: Session) -> None:
    ws, course, cv, lesson, lv, chunk, doc, ver = _seed(db_session)
    target = LearningTarget(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, lesson_id=lesson.id, lesson_version_id=lv.id, target_key="lesson_overall", title="L", kind="lesson_overall")
    db_session.add(target); db_session.flush()
    ps = PracticeSet(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, lesson_id=lesson.id, lesson_version_id=lv.id, output_language="zh-CN", difficulty="standard", item_count=1, generation_config={}, lifecycle_status="active")
    db_session.add(ps); db_session.flush()
    item = PracticeItem(practice_set_id=ps.id, workspace_id=ws.id, ordinal=0, item_type="single_choice", stem="s", options=[{"option_key":"a","text":"A"}], answer_spec={"correct_option_key":"a"})
    db_session.add(item); db_session.flush()
    att = PracticeAttempt(workspace_id=ws.id, practice_item_id=item.id, ordinal=1, item_type="single_choice", answer_payload={"option_key":"a"}, idempotency_key="k", status="succeeded")
    db_session.add(att); db_session.flush()
    fb = PracticeFeedback(practice_attempt_id=att.id, workspace_id=ws.id, verdict="correct", score=100, criterion_results=None, feedback_blocks=[], is_ai_graded=0)
    db_session.add(fb); db_session.flush()
    event = LearningEvent(workspace_id=ws.id, event_type="practice_result", practice_attempt_id=att.id, practice_feedback_id=fb.id, occurred_at=datetime.now(timezone.utc))
    db_session.add(event); db_session.flush()
    signal = MasterySignal(learning_event_id=event.id, learning_target_id=target.id, workspace_id=ws.id, practice_item_id=item.id, practice_set_id=ps.id, outcome="positive", value=1.0, weight=1.0, source_kind="single_choice", is_ai_derived=0)
    db_session.add(signal); db_session.commit()
    dup = MasterySignal(learning_event_id=event.id, learning_target_id=target.id, workspace_id=ws.id, practice_item_id=item.id, practice_set_id=ps.id, outcome="positive", value=1.0, weight=1.0, source_kind="single_choice", is_ai_derived=0)
    db_session.add(dup)
    with pytest.raises(Exception):
        db_session.commit()
    db_session.rollback()


def test_weakness_and_review_and_memory_round_trip(db_session: Session) -> None:
    ws, course, cv, lesson, lv, *_ = _seed(db_session)
    target = LearningTarget(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, lesson_id=lesson.id, lesson_version_id=lv.id, target_key="lesson_overall", title="L", kind="lesson_overall")
    db_session.add(target); db_session.flush()
    w = Weakness(learning_target_id=target.id, workspace_id=ws.id, status="confirmed", revision=1)
    db_session.add(w); db_session.flush()
    ri = ReviewItem(weakness_id=w.id, workspace_id=ws.id, status="due", reopen_count=0, reason_snapshot={"target": "L"})
    db_session.add(ri); db_session.flush()
    db_session.add(ReviewAction(review_item_id=ri.id, workspace_id=ws.id, action="reviewed"))
    mem = LearningMemory(workspace_id=ws.id, course_id=course.id, lesson_id=lesson.id, lesson_version_id=lv.id, learning_target_id=target.id, weakness_id=w.id, kind="weakness", status="active", display_text="test", confirmed_at=datetime.now(timezone.utc))
    db_session.add(mem); db_session.flush()
    db_session.add(LearningMemorySource(learning_memory_id=mem.id, learning_event_id=None, workspace_id=ws.id) if False else LearningMemoryRevision(learning_memory_id=mem.id, workspace_id=ws.id, revision=1, action="auto_created"))
    db_session.add(LearningMemoryPolicy(workspace_id=ws.id, tutor_use_enabled=0, policy_revision=1))
    db_session.commit()
    assert db_session.query(Weakness).filter_by(workspace_id=ws.id).count() == 1
    assert db_session.query(ReviewItem).filter_by(workspace_id=ws.id).count() == 1
    assert db_session.query(LearningMemory).filter_by(workspace_id=ws.id).count() == 1
    assert db_session.query(LearningMemoryPolicy).filter_by(workspace_id=ws.id).one().tutor_use_enabled == 0


def test_mastery_state_unique_per_target(db_session: Session) -> None:
    ws, course, cv, lesson, lv, *_ = _seed(db_session)
    target = LearningTarget(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, lesson_id=lesson.id, lesson_version_id=lv.id, target_key="lesson_overall", title="L", kind="lesson_overall")
    db_session.add(target); db_session.flush()
    db_session.add(MasteryState(learning_target_id=target.id, workspace_id=ws.id, band="insufficient", evidence_count=0, distinct_set_count=0, projection_score=0.5, revision=1, policy_version="001"))
    db_session.commit()
    db_session.add(MasteryState(learning_target_id=target.id, workspace_id=ws.id, band="secure", evidence_count=10, distinct_set_count=3, projection_score=0.9, revision=2, policy_version="001"))
    with pytest.raises(Exception):
        db_session.commit()
    db_session.rollback()


def test_only_one_current_memory_per_target(db_session: Session) -> None:
    ws, course, cv, lesson, lv, *_ = _seed(db_session)
    target = LearningTarget(workspace_id=ws.id, course_id=course.id, course_version_id=cv.id, lesson_id=lesson.id, lesson_version_id=lv.id, target_key="lesson_overall", title="L", kind="lesson_overall")
    db_session.add(target); db_session.flush()
    db_session.add(LearningMemory(workspace_id=ws.id, course_id=course.id, lesson_id=lesson.id, lesson_version_id=lv.id, learning_target_id=target.id, kind="weakness", status="active", display_text="one"))
    db_session.commit()
    db_session.add(LearningMemory(workspace_id=ws.id, course_id=course.id, lesson_id=lesson.id, lesson_version_id=lv.id, learning_target_id=target.id, kind="weakness", status="paused", display_text="two"))
    with pytest.raises(Exception):
        db_session.commit()
    db_session.rollback()
