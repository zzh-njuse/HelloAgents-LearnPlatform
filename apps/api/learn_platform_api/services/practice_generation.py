"""Controlled practice generation and grading (Platform Stage 4 Slice 1).

The Exercise Author is a bounded agent: it can only run ``PracticeEvidenceSearch``
against the job's frozen source snapshot and submit one validated artifact. The
Answer Grader is retrieval-free and grades a single attempt against the item's
frozen rubric/evidence. Neither saves half-finished work, fallback questions or
fixed scores, and neither logs prompts, answers, evidence or provider errors.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from academic_companion.practice_agents import (
    PracticeAuthorRequest,
    PracticeFeedbackArtifact,
    PracticeGraderRequest,
    PracticeRubricCriterion,
    PracticeSetArtifact,
    build_grading_prompt,
    build_grading_repair_prompt,
    build_practice_generation_prompt,
    build_practice_repair_prompt,
    build_practice_search_prompt,
    feedback_citation_ids,
    item_citation_ids,
    validate_feedback_citations,
    validate_practice_citations,
)
from learn_platform_api.db.models import (
    AgentRun,
    AgentToolCall,
    Course,
    CourseVersionSource,
    DocumentChunk,
    Lesson,
    LessonVersion,
    PracticeAttempt,
    PracticeFeedback,
    PracticeItem,
    PracticeItemCitation,
    PracticeJob,
    PracticeJobSource,
    PracticeSet,
    SourceDocument,
    DocumentVersion,
    Workspace,
)
from learn_platform_api.services.retrieval import retrieve
from learn_platform_api.settings import Settings


def now() -> datetime:
    return datetime.now(timezone.utc)


def _sources(db: Session, job: PracticeJob) -> list[tuple[PracticeJobSource, SourceDocument, DocumentVersion]]:
    rows = list(
        db.execute(
            select(PracticeJobSource, SourceDocument, DocumentVersion)
            .join(SourceDocument, PracticeJobSource.document_id == SourceDocument.id)
            .join(DocumentVersion, PracticeJobSource.document_version_id == DocumentVersion.id)
            .where(PracticeJobSource.practice_job_id == job.id, PracticeJobSource.workspace_id == job.workspace_id)
        ).all()
    )
    if not rows or any(
        document.lifecycle_status != "active"
        or document.current_version_id != version.id
        or version.processing_status != "ready"
        for _, document, version in rows
    ):
        raise ValueError("source_snapshot_stale")
    return rows


def call_provider(settings: Settings, messages: list[dict[str, str]], max_output_tokens: int | None = None, timeout_seconds: float | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    if not settings.product_generation_api_key:
        raise ValueError("provider_unconfigured")
    try:
        response = httpx.post(
            f"{settings.product_generation_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.product_generation_api_key}"},
            json={"model": settings.product_generation_model, "messages": messages, "response_format": {"type": "json_object"}, "max_tokens": max_output_tokens or settings.product_generation_max_output_tokens, "temperature": 0.2},
            timeout=timeout_seconds or settings.product_generation_timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        return json.loads(content), {"input_tokens": body.get("usage", {}).get("prompt_tokens"), "output_tokens": body.get("usage", {}).get("completion_tokens"), "finish_reason": body["choices"][0].get("finish_reason")}
    except (httpx.HTTPError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("provider_unavailable") from exc


def _check_active(db: Session, job: PracticeJob, expected_worker_id: str, *, started: float, wall_limit: int, lease_lost=None, check_wall: bool = True) -> None:
    """Per-call authority + ownership + lease gate.

    A worker may only keep working while it still owns the job (status running,
    same worker_id, lease not expired) and its heartbeat has not reported the
    lease lost. Reconciler resets or a new owner must stop this worker cold.
    """
    db.refresh(job)
    if check_wall and time.monotonic() - started > wall_limit:
        raise ValueError("practice_budget_exceeded" if job.job_type == "generate_set" else "grading_budget_exceeded")
    if lease_lost is not None and lease_lost.is_set():
        raise ValueError("practice_canceled")
    if job.status != "running" or job.worker_id != expected_worker_id:
        raise ValueError("practice_canceled")
    if job.lease_expires_at is None:
        raise ValueError("practice_canceled")
    # SQLite returns naive datetimes; Postgres returns aware. Normalise to UTC.
    _lease = job.lease_expires_at
    if _lease.tzinfo is None:
        _lease = _lease.replace(tzinfo=timezone.utc)
    if _lease <= now():
        raise ValueError("practice_canceled")
    workspace = db.get(Workspace, job.workspace_id)
    if workspace is None or workspace.lifecycle_status != "active":
        raise ValueError("practice_canceled")
    if job.job_type == "generate_set":
        course = db.get(Course, job.course_id)
        if course is None or course.lifecycle_status != "active" or course.current_active_version_id != job.course_version_id:
            raise ValueError("practice_canceled")


def _tool_call(db: Session, run: AgentRun, name: str, ordinal: int, query: str | None, count: int | None, started: float, status: str = "succeeded", error: str | None = None) -> None:
    db.add(AgentToolCall(agent_run_id=run.id, workspace_id=run.workspace_id, tool_name=name, ordinal=ordinal, status=status, input_hash=hashlib.sha256(query.encode()).hexdigest() if query else None, result_count=count, latency_ms=round((time.perf_counter() - started) * 1000), error_code=error))


def _course_version_degraded(db: Session, course_version_id: str) -> bool:
    rows = list(db.scalars(select(CourseVersionSource).where(CourseVersionSource.course_version_id == course_version_id)))
    if not rows:
        return True
    for source in rows:
        document = db.get(SourceDocument, source.document_id)
        version = db.get(DocumentVersion, source.document_version_id)
        if document is None or version is None or document.lifecycle_status != "active" or document.current_version_id != version.id or version.processing_status != "ready":
            return True
    return False


def _assert_generation_authority(db: Session, job: PracticeJob, expected_worker_id: str, lease_lost) -> None:
    """Re-validate every authoritative precondition in the final transaction.

    A late worker whose workspace/course/lesson/source/owner/lease state changed
    after the provider returned must drop its result rather than commit.
    """
    _check_active(db, job, expected_worker_id, started=0.0, wall_limit=0, lease_lost=lease_lost, check_wall=False)
    lesson = db.get(Lesson, job.lesson_id)
    lesson_version = db.get(LessonVersion, job.lesson_version_id)
    if (
        lesson is None or lesson_version is None
        or lesson.workspace_id != job.workspace_id
        or lesson.course_version_id != job.course_version_id
        or lesson_version.lesson_id != lesson.id
        or lesson_version.course_version_id != job.course_version_id
        or lesson_version.status != "published"
        or lesson.current_published_version_id != lesson_version.id
    ):
        raise ValueError("practice_canceled")
    # practice_job_sources must still resolve to an active/ready snapshot.
    _sources(db, job)


def _assert_grading_authority(db: Session, job: PracticeJob, attempt: PracticeAttempt, item: PracticeItem, expected_worker_id: str, lease_lost) -> None:
    _check_active(db, job, expected_worker_id, started=0.0, wall_limit=0, lease_lost=lease_lost, check_wall=False)
    db.refresh(attempt)
    if attempt.workspace_id != job.workspace_id or attempt.practice_job_id != job.id or attempt.practice_item_id != item.id:
        raise ValueError("practice_canceled")
    if attempt.status not in {"grading", "retry_wait"}:
        raise ValueError("practice_canceled")
    practice_set = db.get(PracticeSet, item.practice_set_id)
    if practice_set is None or practice_set.workspace_id != job.workspace_id or practice_set.lifecycle_status != "active":
        raise ValueError("practice_canceled")
    if _course_version_degraded(db, practice_set.course_version_id):
        raise ValueError("source_snapshot_stale")
    if db.scalar(select(PracticeFeedback).where(PracticeFeedback.practice_attempt_id == attempt.id)) is not None:
        raise ValueError("practice_canceled")


def execute_generation(db: Session, settings: Settings, job: PracticeJob, *, worker_id: str, lease_lost=None) -> None:
    lesson = db.get(Lesson, job.lesson_id)
    lesson_version = db.get(LessonVersion, job.lesson_version_id)
    if lesson is None or lesson_version is None or lesson.workspace_id != job.workspace_id or lesson_version.lesson_id != lesson.id or lesson_version.status != "published" or lesson.current_published_version_id != lesson_version.id:
        raise ValueError("practice_canceled")
    request = PracticeAuthorRequest(
        lesson_title=lesson.title,
        lesson_objective=lesson.objective,
        learning_objectives=tuple(lesson_version.learning_objectives),
        output_language=job.output_language,
        difficulty=job.difficulty,
        item_count=job.item_count,
    )
    run = AgentRun(practice_job_id=job.id, workspace_id=job.workspace_id, role="exercise_author", attempt_number=job.attempt_count, status="running")
    db.add(run)
    db.flush()
    started = time.monotonic()
    ordinal = 0
    provider_calls = 0
    searches = 0
    input_total = 0
    output_total = 0
    input_missing = False
    output_missing = False
    estimated_output = 0      # separate hard-budget estimate; never reported as provider usage

    def provider_step(messages: list[dict[str, str]], max_tokens: int) -> tuple[dict[str, Any], float]:
        """Counted provider call (step + usage). Does NOT write a tool call: plan
        is an internal step, and submit tool traces are written by the submit
        logic with the correct succeeded/failed status.

        The step is counted BEFORE the provider call so a failed attempt (e.g.
        provider_unavailable) is still reflected in run.step_count."""
        nonlocal ordinal, provider_calls, input_total, output_total, input_missing, output_missing, estimated_output
        _check_active(db, job, worker_id, started=started, wall_limit=settings.practice_generation_max_wall_seconds, lease_lost=lease_lost)
        if (provider_calls + searches) >= settings.practice_generation_max_steps or provider_calls >= settings.practice_generation_max_provider_calls:
            raise ValueError("practice_budget_exceeded")
        phase_started = time.perf_counter()
        provider_calls += 1
        ordinal += 1
        run.step_count = ordinal  # count the attempt before it runs
        generated, usage = call_provider(settings, messages, max_tokens, settings.practice_generation_timeout_seconds)
        reported_in = usage.get("input_tokens")
        reported_out = usage.get("output_tokens")
        if reported_in is None:
            input_missing = True
        else:
            input_total += int(reported_in)
        if reported_out is None:
            output_missing = True
            estimated_output += max(1, int(len(json.dumps(generated, ensure_ascii=False)) * 0.6))
        else:
            output_total += int(reported_out)
            estimated_output += int(reported_out)
        if usage.get("finish_reason") == "length" or estimated_output > settings.practice_generation_max_output_tokens:
            raise ValueError("practice_budget_exceeded")
        _check_active(db, job, worker_id, started=started, wall_limit=settings.practice_generation_max_wall_seconds, lease_lost=lease_lost)
        return generated, phase_started

    # Search plan is a counted provider step (step + usage) but NOT a tool call.
    planned, _ = provider_step(build_practice_search_prompt(request), settings.product_generation_max_output_tokens)
    queries = planned.get("queries") if isinstance(planned, dict) else None
    if not isinstance(queries, list) or not 1 <= len(queries) <= settings.practice_generation_max_searches or any(not isinstance(q, str) or not q.strip() or len(q) > 300 for q in queries):
        raise ValueError("invalid_practice_artifact")
    queries = list(dict.fromkeys(q.strip() for q in queries))

    # One job-wide evidence ledger: monotonic, unique citation keys; identical
    # chunks keep their first key; the evidence-token budget spans the whole job.
    rows = _sources(db, job)
    by_version = {source.document_version_id: source for source, _, _ in rows}
    document_ids = [document.id for _, document, _ in rows]
    evidence: list[dict[str, str]] = []
    chunks: dict[str, DocumentChunk] = {}
    sources: dict[str, PracticeJobSource] = {}
    seen_chunk_ids: set[str] = set()
    evidence_tokens = 0
    for query in queries:
        if (provider_calls + searches) >= settings.practice_generation_max_steps or searches >= settings.practice_generation_max_searches:
            break
        _check_active(db, job, worker_id, started=started, wall_limit=settings.practice_generation_max_wall_seconds, lease_lost=lease_lost)
        searches += 1
        ordinal += 1
        run.step_count = ordinal  # count the search attempt before it runs
        search_started = time.perf_counter()
        _, results = retrieve(db, settings, job.workspace_id, query, settings.practice_generation_search_top_k, document_ids=document_ids)
        added = 0
        for result in results:
            chunk = db.get(DocumentChunk, result.citation.chunk_id)
            if chunk is None or chunk.document_version_id not in by_version or chunk.id in seen_chunk_ids:
                continue
            estimated = max(1, int(len(result.text) * 0.6))
            if evidence_tokens + estimated > settings.practice_generation_max_evidence_tokens:
                continue
            citation_id = f"e{len(evidence) + 1}"
            evidence.append({"citation_id": citation_id, "text": result.text})
            chunks[citation_id] = chunk
            sources[citation_id] = by_version[chunk.document_version_id]
            seen_chunk_ids.add(chunk.id)
            evidence_tokens += estimated
            added += 1
        _tool_call(db, run, "PracticeEvidenceSearch", ordinal, query, added, search_started)
    if not evidence:
        raise ValueError("insufficient_evidence")

    def submit_attempt(messages: list[dict[str, str]]) -> tuple[Any, float]:
        return provider_step(messages, settings.practice_generation_max_output_tokens)

    generated, submit_started = submit_attempt(build_practice_generation_prompt(request, evidence))
    try:
        artifact = PracticeSetArtifact.model_validate(generated)
        validate_practice_citations(artifact, set(chunks))
    except (ValidationError, ValueError) as exc:
        _tool_call(db, run, "SubmitPracticeSet", ordinal, None, None, submit_started, "failed", "invalid_practice_artifact")
        if provider_calls >= settings.practice_generation_max_provider_calls or (provider_calls + searches) >= settings.practice_generation_max_steps:
            raise ValueError("invalid_practice_artifact") from exc
        repaired, repair_started = submit_attempt(build_practice_repair_prompt(request, evidence, generated))
        try:
            artifact = PracticeSetArtifact.model_validate(repaired)
            validate_practice_citations(artifact, set(chunks))
        except (ValidationError, ValueError) as repair_exc:
            _tool_call(db, run, "SubmitPracticeSet", ordinal, None, None, repair_started, "failed", "invalid_practice_artifact")
            raise ValueError("invalid_practice_artifact") from repair_exc
        else:
            _tool_call(db, run, "SubmitPracticeSet", ordinal, None, len(artifact.items), repair_started, "succeeded")
    else:
        _tool_call(db, run, "SubmitPracticeSet", ordinal, None, len(artifact.items), submit_started, "succeeded")

    # Final authoritative re-check (owner + lease + scope + sources) before commit.
    _assert_generation_authority(db, job, worker_id, lease_lost)
    practice_set = _commit_set(db, job, artifact, chunks, sources)
    run.status = "succeeded"
    run.step_count = provider_calls + searches  # plan + searches + submit calls; always <= max_steps
    run.input_tokens = None if input_missing else (input_total or None)
    run.output_tokens = None if output_missing else (output_total or None)
    run.completed_at = now()
    job.practice_set_id = practice_set.id
    job.status = "succeeded"
    job.input_tokens = run.input_tokens
    job.output_tokens = run.output_tokens
    job.lease_expires_at = None
    job.worker_id = None
    job.error_code = None
    job.error_message = None
    job.completed_at = now()


def _commit_set(db: Session, job: PracticeJob, artifact: PracticeSetArtifact, chunks: dict[str, DocumentChunk], sources: dict[str, PracticeJobSource]) -> PracticeSet:
    practice_set = PracticeSet(
        workspace_id=job.workspace_id, course_id=job.course_id, course_version_id=job.course_version_id,
        lesson_id=job.lesson_id, lesson_version_id=job.lesson_version_id, practice_job_id=job.id,
        output_language=job.output_language, difficulty=job.difficulty, item_count=len(artifact.items),
        generation_config={"item_count": job.item_count, "difficulty": job.difficulty, "output_language": job.output_language},
        lifecycle_status="active", created_at=now(),
    )
    db.add(practice_set)
    db.flush()
    for index, item in enumerate(artifact.items):
        answer_spec = _answer_spec(item)
        practice_item = PracticeItem(
            practice_set_id=practice_set.id, workspace_id=job.workspace_id, ordinal=index, item_type=item.item_type,
            stem=item.stem, options=[{"option_key": option.option_key, "text": option.text} for option in item.options] if item.options else None,
            answer_spec=answer_spec, created_at=now(),
        )
        db.add(practice_item)
        db.flush()
        for citation_id in sorted(item_citation_ids(item)):
            chunk = chunks.get(citation_id)
            if chunk is None:
                raise ValueError("unknown_citation")
            source = sources[citation_id]
            db.add(PracticeItemCitation(
                practice_item_id=practice_item.id, workspace_id=job.workspace_id, citation_key=citation_id,
                document_id=source.document_id, document_version_id=source.document_version_id, document_chunk_id=chunk.id,
            ))
    return practice_set


def _answer_spec(item) -> dict[str, Any]:
    if item.item_type == "single_choice":
        return {
            "correct_option_key": next(option.option_key for option in item.options if option.is_correct),
            "option_rationales": {option.option_key: {"rationale": option.rationale, "citation_ids": option.citation_ids} for option in item.options},
            "citation_ids": list(item.citation_ids),
        }
    return {
        "reference_answer": item.reference_answer,
        "rubric": [criterion.model_dump() for criterion in item.rubric],
        "citation_ids": list(item.citation_ids),
    }


def execute_grading(db: Session, settings: Settings, job: PracticeJob, *, worker_id: str, lease_lost=None) -> None:
    attempt = db.get(PracticeAttempt, job.practice_attempt_id)
    if attempt is None or attempt.workspace_id != job.workspace_id or attempt.practice_job_id != job.id:
        raise ValueError("practice_canceled")
    item = db.scalar(select(PracticeItem).where(PracticeItem.id == attempt.practice_item_id, PracticeItem.workspace_id == job.workspace_id))
    if item is None or item.item_type != "short_answer":
        raise ValueError("practice_canceled")
    db.refresh(attempt)
    if attempt.status not in {"grading", "retry_wait"}:
        raise ValueError("practice_canceled")
    answer_spec = item.answer_spec
    rubric = tuple(PracticeRubricCriterion.model_validate(criterion) for criterion in answer_spec.get("rubric", []))
    evidence = _item_evidence(db, settings, item)
    request = PracticeGraderRequest(
        item_type="short_answer", stem=item.stem, reference_answer=answer_spec.get("reference_answer", ""),
        rubric=rubric, evidence=tuple(evidence), answer=str(attempt.answer_payload.get("text", "")), output_language=job.output_language,
    )
    run = AgentRun(practice_job_id=job.id, workspace_id=job.workspace_id, role="answer_grader", attempt_number=job.attempt_count, status="running")
    db.add(run)
    db.flush()
    started = time.monotonic()
    ordinal = 0
    provider_calls = 0
    input_total = 0
    output_total = 0
    input_missing = False
    output_missing = False
    estimated_output = 0

    def provider_step(messages: list[dict[str, str]]) -> tuple[dict[str, Any], float]:
        nonlocal ordinal, provider_calls, input_total, output_total, input_missing, output_missing, estimated_output
        _check_active(db, job, worker_id, started=started, wall_limit=settings.practice_grading_max_wall_seconds, lease_lost=lease_lost)
        if provider_calls >= settings.practice_grading_max_provider_calls:
            raise ValueError("grading_budget_exceeded")
        phase_started = time.perf_counter()
        provider_calls += 1
        ordinal += 1
        run.step_count = ordinal  # count the attempt before it runs
        generated, usage = call_provider(settings, messages, settings.practice_grading_max_output_tokens, settings.practice_grading_timeout_seconds)
        reported_in = usage.get("input_tokens")
        reported_out = usage.get("output_tokens")
        if reported_in is None:
            input_missing = True
        else:
            input_total += int(reported_in)
        if reported_out is None:
            output_missing = True
            estimated_output += max(1, int(len(json.dumps(generated, ensure_ascii=False)) * 0.6))
        else:
            output_total += int(reported_out)
            estimated_output += int(reported_out)
        if usage.get("finish_reason") == "length" or estimated_output > settings.practice_grading_max_output_tokens:
            raise ValueError("grading_budget_exceeded")
        _check_active(db, job, worker_id, started=started, wall_limit=settings.practice_grading_max_wall_seconds, lease_lost=lease_lost)
        return generated, phase_started

    allowed_citations = {citation.citation_key for citation in db.scalars(select(PracticeItemCitation).where(PracticeItemCitation.practice_item_id == item.id))}
    rubric_keys = {criterion.criterion_key for criterion in rubric}
    generated, submit_started = provider_step(build_grading_prompt(request))
    try:
        feedback = PracticeFeedbackArtifact.model_validate(generated)
        validate_feedback_citations(feedback, allowed_citations, rubric_keys)
    except (ValidationError, ValueError) as exc:
        _tool_call(db, run, "SubmitPracticeFeedback", ordinal, None, None, submit_started, "failed", "invalid_practice_artifact")
        if provider_calls >= settings.practice_grading_max_provider_calls:
            raise ValueError("invalid_practice_artifact") from exc
        repaired, repair_started = provider_step(build_grading_repair_prompt(request, generated))
        try:
            feedback = PracticeFeedbackArtifact.model_validate(repaired)
            validate_feedback_citations(feedback, allowed_citations, rubric_keys)
        except (ValidationError, ValueError) as repair_exc:
            _tool_call(db, run, "SubmitPracticeFeedback", ordinal, None, None, repair_started, "failed", "invalid_practice_artifact")
            raise ValueError("invalid_practice_artifact") from repair_exc
        else:
            _tool_call(db, run, "SubmitPracticeFeedback", ordinal, None, 1, repair_started, "succeeded")
    else:
        _tool_call(db, run, "SubmitPracticeFeedback", ordinal, None, 1, submit_started, "succeeded")

    # Final authoritative re-check (owner + lease + scope + no prior feedback).
    _assert_grading_authority(db, job, attempt, item, worker_id, lease_lost)
    record = PracticeFeedback(
        practice_attempt_id=attempt.id, workspace_id=job.workspace_id, verdict=feedback.verdict, score=feedback.score,
        criterion_results=[result.model_dump() for result in feedback.criterion_results] or None,
        feedback_blocks=[{**block.model_dump(), "option_key": None} for block in feedback.blocks],
        is_ai_graded=1, created_at=now(),
    )
    db.add(record)
    run.status = "succeeded"
    run.step_count = provider_calls  # = submit attempts (1 first success, 2 repair)
    run.input_tokens = None if input_missing else (input_total or None)
    run.output_tokens = None if output_missing else (output_total or None)
    run.completed_at = now()
    attempt.status = "succeeded"
    attempt.completed_at = now()
    attempt.error_code = None
    attempt.error_message = None
    job.status = "succeeded"
    job.input_tokens = run.input_tokens
    job.output_tokens = run.output_tokens
    job.lease_expires_at = None
    job.worker_id = None
    job.error_code = None
    job.error_message = None
    job.completed_at = now()


def _item_evidence(db: Session, settings: Settings, item: PracticeItem) -> list[dict[str, str]]:
    rows = list(db.execute(
        select(PracticeItemCitation, DocumentChunk)
        .join(DocumentChunk, PracticeItemCitation.document_chunk_id == DocumentChunk.id)
        .where(PracticeItemCitation.practice_item_id == item.id)
    ).all())
    evidence: list[dict[str, str]] = []
    token_total = 0
    for citation, chunk in rows:
        estimated = max(1, int(len(chunk.content) * 0.6))
        if token_total + estimated > settings.practice_grading_max_evidence_tokens:
            break
        evidence.append({"citation_id": citation.citation_key, "text": chunk.content})
        token_total += estimated
    return evidence
