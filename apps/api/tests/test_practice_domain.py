from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from academic_companion.practice_agents import (
    PracticeFeedbackArtifact,
    PracticeItemArtifact,
    PracticeSetArtifact,
    feedback_citation_ids,
    item_citation_ids,
    validate_feedback_citations,
    validate_practice_citations,
)
from learn_platform_api.db.models import (
    PracticeAttempt,
    PracticeFeedback,
    PracticeItem,
    PracticeItemCitation,
    PracticeJob,
    PracticeJobSource,
    PracticeSet,
    Workspace,
)


def _single_choice(item_key="q1", citation="e1", correct="a"):
    return {
        "item_key": item_key,
        "item_type": "single_choice",
        "stem": "Which option is correct?",
        "citation_ids": [citation],
        "options": [
            {"option_key": "a", "text": "Alpha", "is_correct": correct == "a", "rationale": "alpha holds", "citation_ids": [citation]},
            {"option_key": "b", "text": "Beta", "is_correct": correct == "b", "rationale": "beta fails", "citation_ids": [citation]},
        ],
    }


def _short_answer(item_key="q2", citation="e1"):
    return {
        "item_key": item_key,
        "item_type": "short_answer",
        "stem": "Explain the mechanism.",
        "citation_ids": [citation],
        "rubric": [
            {"criterion_key": "c1", "description": "names the mechanism", "weight": 60, "citation_ids": [citation]},
            {"criterion_key": "c2", "description": "gives an example", "weight": 40, "citation_ids": [citation]},
        ],
        "reference_answer": "The mechanism halves the interval.",
    }


def test_practice_set_artifact_accepts_mixed_types() -> None:
    artifact = PracticeSetArtifact.model_validate({"items": [_single_choice(), _short_answer()]})
    assert {item.item_type for item in artifact.items} == {"single_choice", "short_answer"}
    validate_practice_citations(artifact, {"e1"})


def test_practice_set_with_two_items_requires_both_types() -> None:
    with pytest.raises(ValidationError):
        PracticeSetArtifact.model_validate({"items": [_single_choice("q1"), _single_choice("q2")]})


def test_single_choice_requires_exactly_one_correct() -> None:
    bad = _single_choice()
    bad["options"][0]["is_correct"] = True
    bad["options"][1]["is_correct"] = True
    with pytest.raises(ValidationError):
        PracticeItemArtifact.model_validate(bad)


def test_rubric_weights_must_sum_to_100() -> None:
    bad = _short_answer()
    bad["rubric"][0]["weight"] = 50
    with pytest.raises(ValidationError):
        PracticeItemArtifact.model_validate(bad)


def test_unknown_citation_rejected() -> None:
    artifact = PracticeSetArtifact.model_validate({"items": [_single_choice()]})
    with pytest.raises(ValueError, match="unknown_citation"):
        validate_practice_citations(artifact, {"other"})


def test_feedback_ungradable_forbids_score() -> None:
    with pytest.raises(ValidationError):
        PracticeFeedbackArtifact.model_validate({
            "verdict": "ungradable",
            "score": 50,
            "blocks": [{"block_key": "b1", "type": "limitation", "text": "cannot judge", "citation_ids": []}],
        })


def test_feedback_requires_score_for_graded_verdict() -> None:
    with pytest.raises(ValidationError):
        PracticeFeedbackArtifact.model_validate({
            "verdict": "correct",
            "score": None,
            "blocks": [{"block_key": "b1", "type": "explanation", "text": "ok", "citation_ids": []}],
        })


def test_perfect_score_requires_all_rubric_criteria_fully_met() -> None:
    with pytest.raises(ValidationError):
        PracticeFeedbackArtifact.model_validate({
            "verdict": "correct",
            "score": 100,
            "criterion_results": [{"criterion_key": "c1", "met": "partial", "note": "missing detail", "citation_ids": []}],
            "blocks": [{"block_key": "b1", "type": "improvement", "text": "add detail", "citation_ids": []}],
        })


def test_feedback_citation_validation_matches_rubric_keys() -> None:
    feedback = PracticeFeedbackArtifact.model_validate({
        "verdict": "partially_correct",
        "score": 60,
        "criterion_results": [{"criterion_key": "c1", "met": "full", "note": "good", "citation_ids": []}],
        "blocks": [{"block_key": "b1", "type": "improvement", "text": "add example", "citation_ids": []}],
    })
    # rubric keys must match criterion results exactly
    with pytest.raises(ValueError, match="invalid_rubric"):
        validate_feedback_citations(feedback, set(), {"c1", "c2"})
    validate_feedback_citations(feedback, set(), {"c1"})


def test_item_citation_ids_aggregate_across_options_and_rubric() -> None:
    single = PracticeItemArtifact.model_validate(_single_choice(citation="e1"))
    assert item_citation_ids(single) == {"e1"}
    short = PracticeItemArtifact.model_validate(_short_answer(citation="e2"))
    assert item_citation_ids(short) == {"e2"}
    assert feedback_citation_ids(PracticeFeedbackArtifact.model_validate({
        "verdict": "correct", "score": 99,
        "blocks": [{"block_key": "b1", "type": "explanation", "text": "ok", "citation_ids": ["e1", "e2"]}],
    })) == {"e1", "e2"}


def test_practice_orm_round_trip(db_session: Session) -> None:
    workspace = Workspace(name="practice", slug="practice")
    db_session.add(workspace)
    db_session.flush()
    now = datetime.now(timezone.utc)

    job = PracticeJob(
        workspace_id=workspace.id, job_type="generate_set", output_language="zh-CN",
        difficulty="standard", item_count=2, request_hash="0" * 64, status="succeeded",
        idempotency_key="job-1", attempt_count=1, external_processing_ack_at=now,
        created_at=now, updated_at=now,
    )
    db_session.add(job)
    db_session.flush()
    db_session.add(PracticeJobSource(practice_job_id=job.id, workspace_id=workspace.id, document_id="d1", document_version_id="v1"))

    practice_set = PracticeSet(
        workspace_id=workspace.id, course_id="c1", course_version_id="cv1", lesson_id="l1", lesson_version_id="lv1",
        practice_job_id=job.id, output_language="zh-CN", difficulty="standard", item_count=2,
        generation_config={"item_count": 2}, lifecycle_status="active", created_at=now,
    )
    db_session.add(practice_set)
    db_session.flush()
    job.practice_set_id = practice_set.id

    item = PracticeItem(
        practice_set_id=practice_set.id, workspace_id=workspace.id, ordinal=0, item_type="single_choice",
        stem="Pick one", options=[{"option_key": "a", "text": "Alpha"}],
        answer_spec={"correct_option_key": "a"}, created_at=now,
    )
    db_session.add(item)
    db_session.flush()
    db_session.add(PracticeItemCitation(
        practice_item_id=item.id, workspace_id=workspace.id, citation_key="e1",
        document_id="d1", document_version_id="v1", document_chunk_id="k1",
    ))

    attempt = PracticeAttempt(
        workspace_id=workspace.id, practice_item_id=item.id, ordinal=1, item_type="single_choice",
        answer_payload={"option_key": "a"}, idempotency_key="att-1", status="succeeded", created_at=now, updated_at=now,
    )
    db_session.add(attempt)
    db_session.flush()
    feedback = PracticeFeedback(
        practice_attempt_id=attempt.id, workspace_id=workspace.id, verdict="correct", score=100,
        feedback_blocks=[{"block_key": "b1", "type": "explanation", "text": "right", "citation_ids": ["e1"]}],
        is_ai_graded=0, created_at=now,
    )
    db_session.add(feedback)
    db_session.commit()

    assert db_session.get(PracticeSet, practice_set.id).item_count == 2
    assert db_session.get(PracticeItem, item.id).stem == "Pick one"
    # Unique: one feedback per attempt.
    db_session.add(PracticeFeedback(practice_attempt_id=attempt.id, workspace_id=workspace.id, verdict="incorrect", score=0, feedback_blocks=[], is_ai_graded=0, created_at=now))
    with pytest.raises(Exception):
        db_session.commit()
    db_session.rollback()


def test_agent_run_supports_practice_job_owner(db_session: Session) -> None:
    from learn_platform_api.db.models import AgentRun
    workspace = Workspace(name="owner", slug="owner")
    db_session.add(workspace)
    db_session.flush()
    job = PracticeJob(workspace_id=workspace.id, job_type="grade_attempt", output_language="zh-CN", difficulty="standard", item_count=1, request_hash="0" * 64, status="succeeded", idempotency_key="j", attempt_count=1, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    db_session.add(job)
    db_session.flush()
    run = AgentRun(practice_job_id=job.id, workspace_id=workspace.id, role="exercise_author", attempt_number=1, status="succeeded")
    db_session.add(run)
    db_session.commit()
    assert db_session.get(AgentRun, run.id).practice_job_id == job.id
