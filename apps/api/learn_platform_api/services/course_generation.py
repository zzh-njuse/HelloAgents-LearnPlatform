import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from academic_companion.course_agents import CourseAgentRequest, CourseOutlineArtifact, LessonCoveragePlan, LessonCoverageVerification, LessonDraftArtifact, LessonRepairArtifact, LessonUnitArtifact, build_generation_prompt, build_lesson_coverage_prompt, build_lesson_repair_prompt, build_lesson_unit_prompt, build_lesson_unit_repair_prompt, build_lesson_verification_prompt, build_search_prompt, validate_citations
from learn_platform_api.db.models import AgentRun, AgentToolCall, Course, CourseGenerationJob, CourseGenerationJobSource, CourseSection, CourseSectionCitation, CourseVersion, CourseVersionSource, Lesson, LessonCitation, LessonVersion, SourceDocument, DocumentChunk, DocumentVersion, Workspace
from learn_platform_api.services.retrieval import retrieve
from learn_platform_api.settings import Settings


def now() -> datetime:
    return datetime.now(timezone.utc)


def snapshot_rows(db: Session, job: CourseGenerationJob) -> list[tuple[CourseGenerationJobSource, SourceDocument, DocumentVersion]]:
    rows = list(db.execute(select(CourseGenerationJobSource, SourceDocument, DocumentVersion).join(SourceDocument, CourseGenerationJobSource.document_id == SourceDocument.id).join(DocumentVersion, CourseGenerationJobSource.document_version_id == DocumentVersion.id).where(CourseGenerationJobSource.course_generation_job_id == job.id, CourseGenerationJobSource.workspace_id == job.workspace_id)).all())
    if not rows or any(document.lifecycle_status != "active" or document.current_version_id != version.id or version.processing_status != "ready" for _, document, version in rows):
        raise ValueError("source_snapshot_stale")
    return rows


def evidence_search(db: Session, settings: Settings, job: CourseGenerationJob, query: str, top_k: int = 5) -> tuple[list[dict[str, str]], dict[str, DocumentChunk]]:
    rows = snapshot_rows(db, job)
    document_ids = [document.id for _, document, _ in rows]
    _, results = retrieve(db, settings, job.workspace_id, query, min(top_k, 5), document_ids=document_ids)
    evidence: list[dict[str, str]] = []
    chunks: dict[str, DocumentChunk] = {}
    token_total = 0
    for result in results:
        estimated = max(1, int(len(result.text) * 0.6))
        if token_total + estimated > settings.product_generation_max_evidence_tokens:
            break
        citation_id = f"e{len(evidence) + 1}"
        evidence.append({"citation_id": citation_id, "text": result.text})
        chunk = db.get(DocumentChunk, result.citation.chunk_id)
        if chunk:
            chunks[citation_id] = chunk
            token_total += estimated
    if not evidence:
        raise ValueError("insufficient_evidence")
    return evidence, chunks


def call_provider(settings: Settings, messages: list[dict[str, str]], max_output_tokens: int | None = None, timeout_seconds: float | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    if not settings.product_generation_api_key:
        raise ValueError("generation_provider_unconfigured")
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
        raise ValueError("generation_provider_unavailable") from exc


def _tool_call(db: Session, run: AgentRun, name: str, ordinal: int, query: str | None, count: int | None, started: float, status: str = "succeeded", error: str | None = None) -> None:
    db.add(AgentToolCall(agent_run_id=run.id, workspace_id=run.workspace_id, tool_name=name, ordinal=ordinal, status=status, input_hash=hashlib.sha256(query.encode()).hexdigest() if query else None, result_count=count, latency_ms=round((time.perf_counter() - started) * 1000), error_code=error))


def _sources_for_job(db: Session, job: CourseGenerationJob) -> dict[str, CourseGenerationJobSource]:
    return {
        source.document_version_id: source
        for source in db.scalars(
            select(CourseGenerationJobSource).where(CourseGenerationJobSource.course_generation_job_id == job.id)
        )
    }


def _source_for_chunk(sources: dict[str, CourseGenerationJobSource], chunk: DocumentChunk) -> CourseGenerationJobSource:
    source = sources.get(chunk.document_version_id)
    if not source:
        raise ValueError("unknown_citation")
    return source


def persist_outline(db: Session, job: CourseGenerationJob, artifact: CourseOutlineArtifact, chunks: dict[str, DocumentChunk]) -> CourseVersion:
    number = (db.scalar(select(func.max(CourseVersion.version_number)).where(CourseVersion.course_id == job.course_id)) or 0) + 1
    version = CourseVersion(course_id=job.course_id, workspace_id=job.workspace_id, version_number=number, status="draft", title=artifact.title, summary=artifact.summary)
    db.add(version); db.flush()
    sources = _sources_for_job(db, job)
    for source in sources.values():
        db.add(CourseVersionSource(course_version_id=version.id, workspace_id=job.workspace_id, document_id=source.document_id, document_version_id=source.document_version_id))
    for section_index, section_data in enumerate(artifact.sections):
        section = CourseSection(course_version_id=version.id, workspace_id=job.workspace_id, ordinal=section_index, title=section_data.title, objective=section_data.objective)
        db.add(section); db.flush()
        for citation_id in dict.fromkeys(section_data.citation_ids):
            chunk = chunks.get(citation_id)
            if not chunk:
                raise ValueError("unknown_citation")
            source = _source_for_chunk(sources, chunk)
            db.add(CourseSectionCitation(course_section_id=section.id, workspace_id=job.workspace_id, document_id=source.document_id, document_version_id=source.document_version_id, document_chunk_id=chunk.id))
        for lesson_index, lesson_data in enumerate(section_data.lessons):
            db.add(Lesson(course_version_id=version.id, course_section_id=section.id, workspace_id=job.workspace_id, ordinal=lesson_index, title=lesson_data.title, objective=lesson_data.objective))
    job.course_version_id = version.id
    return version


def persist_lesson(db: Session, job: CourseGenerationJob, artifact: LessonDraftArtifact, chunks: dict[str, DocumentChunk]) -> LessonVersion:
    lesson = db.get(Lesson, job.lesson_id)
    if not lesson or lesson.workspace_id != job.workspace_id or lesson.course_version_id != job.course_version_id:
        raise ValueError("lesson_not_found")
    number = (db.scalar(select(func.max(LessonVersion.version_number)).where(LessonVersion.lesson_id == lesson.id)) or 0) + 1
    version = LessonVersion(lesson_id=lesson.id, course_version_id=lesson.course_version_id, workspace_id=job.workspace_id, version_number=number, status="draft", title=artifact.title, learning_objectives=artifact.learning_objectives, blocks=[block.model_dump() for block in artifact.blocks])
    db.add(version); db.flush()
    sources = _sources_for_job(db, job)
    for block in artifact.blocks:
        for citation_id in dict.fromkeys(block.citation_ids):
            chunk = chunks.get(citation_id)
            if not chunk:
                raise ValueError("unknown_citation")
            source = _source_for_chunk(sources, chunk)
            db.add(LessonCitation(lesson_version_id=version.id, workspace_id=job.workspace_id, block_key=block.block_key, document_id=source.document_id, document_version_id=source.document_version_id, document_chunk_id=chunk.id))
    return version


def _lesson_job_active(db: Session, job: CourseGenerationJob, settings: Settings, started: float) -> None:
    db.refresh(job)
    if time.monotonic() - started > settings.lesson_generation_max_wall_seconds:
        raise ValueError("lesson_budget_exceeded")
    workspace = db.get(Workspace, job.workspace_id)
    if workspace is None or workspace.lifecycle_status != "active" or job.status != "running" or (job.lease_expires_at and job.lease_expires_at < now()):
        raise ValueError("generation_canceled")


def _lesson_evidence_search(db: Session, settings: Settings, job: CourseGenerationJob, query: str) -> list[DocumentChunk]:
    rows = snapshot_rows(db, job)
    document_ids = [document.id for _, document, _ in rows]
    _, results = retrieve(db, settings, job.workspace_id, query, 8, document_ids=document_ids)
    chunks: list[DocumentChunk] = []
    for result in results:
        chunk = db.get(DocumentChunk, result.citation.chunk_id)
        if chunk is not None:
            chunks.append(chunk)
    return chunks


def _execute_lesson_generation(db: Session, settings: Settings, job: CourseGenerationJob, request: CourseAgentRequest) -> None:
    run = AgentRun(course_generation_job_id=job.id, workspace_id=job.workspace_id, role="lesson_writer", attempt_number=job.attempt_count, status="running")
    db.add(run)
    db.flush()
    started = time.monotonic()
    ordinal = 0
    provider_calls = 0
    input_tokens = 0
    output_tokens = 0

    def provider_phase(name: str, messages: list[dict[str, str]]) -> dict[str, Any]:
        nonlocal ordinal, provider_calls, input_tokens, output_tokens
        _lesson_job_active(db, job, settings, started)
        if provider_calls >= settings.lesson_generation_max_provider_calls:
            raise ValueError("lesson_budget_exceeded")
        phase_started = time.perf_counter()
        generated, usage = call_provider(
            settings,
            messages,
            settings.lesson_generation_max_output_tokens_per_call,
            settings.lesson_generation_timeout_seconds,
        )
        provider_calls += 1
        _lesson_job_active(db, job, settings, started)
        ordinal += 1
        used_input = usage.get("input_tokens") or 0
        used_output = usage.get("output_tokens")
        if used_output is None:
            used_output = max(1, int(len(json.dumps(generated, ensure_ascii=False)) * 0.6))
        input_tokens += int(used_input)
        output_tokens += int(used_output)
        _tool_call(db, run, name, ordinal, None, 1, phase_started)
        if usage.get("finish_reason") == "length" or output_tokens > settings.lesson_generation_max_total_output_tokens:
            raise ValueError("lesson_budget_exceeded")
        return generated

    try:
        plan = LessonCoveragePlan.model_validate(provider_phase(
            "PlanLessonCoverage",
            build_lesson_coverage_prompt(request, settings.lesson_generation_max_coverage_units),
        ))
    except ValidationError as exc:
        raise ValueError("lesson_coverage_invalid") from exc
    if len(plan.units) > settings.lesson_generation_max_coverage_units:
        raise ValueError("lesson_coverage_invalid")

    evidence: list[dict[str, str]] = []
    chunks: dict[str, DocumentChunk] = {}
    evidence_by_unit: dict[str, list[dict[str, str]]] = {}
    seen_chunk_ids: set[str] = set()
    evidence_tokens = 0
    for unit in plan.units:
        _lesson_job_active(db, job, settings, started)
        search_started = time.perf_counter()
        found = _lesson_evidence_search(db, settings, job, unit.search_query)
        unit_evidence: list[dict[str, str]] = []
        for chunk in found:
            if chunk.id in seen_chunk_ids:
                existing = next((item for item in evidence if chunks[item["citation_id"]].id == chunk.id), None)
                if existing:
                    unit_evidence.append(existing)
                continue
            estimated = max(1, int(len(chunk.content) * 0.6))
            if evidence_tokens + estimated > settings.lesson_generation_max_evidence_tokens:
                continue
            citation_id = f"e{len(evidence) + 1}"
            item = {"citation_id": citation_id, "text": chunk.content}
            evidence.append(item)
            unit_evidence.append(item)
            chunks[citation_id] = chunk
            seen_chunk_ids.add(chunk.id)
            evidence_tokens += estimated
        ordinal += 1
        _tool_call(db, run, "CourseEvidenceSearch", ordinal, unit.search_query, len(unit_evidence), search_started)
        if not unit_evidence:
            if evidence_tokens >= settings.lesson_generation_max_evidence_tokens:
                raise ValueError("lesson_budget_exceeded")
            raise ValueError("lesson_evidence_insufficient")
        evidence_by_unit[unit.unit_key] = unit_evidence

    def validate_unit(unit, generated: dict[str, Any]) -> LessonUnitArtifact:
        candidate = dict(generated)
        candidate["unit_key"] = unit.unit_key
        artifact = LessonUnitArtifact.model_validate(candidate)
        validate_citations(
            LessonDraftArtifact(title=request.lesson_title or request.title, learning_objectives=plan.learning_objectives, blocks=artifact.blocks),
            {item["citation_id"] for item in evidence_by_unit[unit.unit_key]},
        )
        return artifact

    units: list[LessonUnitArtifact] = []
    for unit in plan.units:
        generated = provider_phase(
            "WriteLessonUnit",
            build_lesson_unit_prompt(request, unit, evidence_by_unit[unit.unit_key]),
        )
        try:
            artifact = validate_unit(unit, generated)
        except (ValidationError, ValueError) as exc:
            try:
                repaired = provider_phase(
                    "RepairLessonUnit",
                    build_lesson_unit_repair_prompt(request, unit, evidence_by_unit[unit.unit_key], generated),
                )
                artifact = validate_unit(unit, repaired)
            except (ValidationError, ValueError) as repair_exc:
                raise ValueError("invalid_agent_artifact") from repair_exc
        units.append(artifact)

    def verify() -> LessonCoverageVerification:
        try:
            return LessonCoverageVerification.model_validate(provider_phase(
                "VerifyLessonCoverage",
                build_lesson_verification_prompt(plan, units),
            ))
        except ValidationError as exc:
            raise ValueError("lesson_coverage_invalid") from exc

    verification = verify()
    if not verification.complete:
        requested = {revision.unit_key for revision in verification.revisions}
        if not requested.issubset({unit.unit_key for unit in units}):
            raise ValueError("lesson_coverage_invalid")
        try:
            repaired = LessonRepairArtifact.model_validate(provider_phase(
                "RepairLessonCoverage",
                build_lesson_repair_prompt(plan, units, verification.revisions, evidence_by_unit),
            ))
        except ValidationError as exc:
            raise ValueError("invalid_agent_artifact") from exc
        if {unit.unit_key for unit in repaired.units} != requested:
            raise ValueError("invalid_agent_artifact")
        replacements = {unit.unit_key: unit for unit in repaired.units}
        for repaired_unit in repaired.units:
            try:
                validate_citations(
                    LessonDraftArtifact(title=request.lesson_title or request.title, learning_objectives=plan.learning_objectives, blocks=repaired_unit.blocks),
                    {item["citation_id"] for item in evidence_by_unit[repaired_unit.unit_key]},
                )
            except (ValidationError, ValueError) as exc:
                raise ValueError("invalid_agent_artifact") from exc
        units = [replacements.get(unit.unit_key, unit) for unit in units]
        if not verify().complete:
            raise ValueError("lesson_coverage_incomplete")

    blocks = [block for unit in units for block in unit.blocks]
    try:
        artifact = LessonDraftArtifact(
            title=request.lesson_title or request.title,
            learning_objectives=plan.learning_objectives,
            blocks=blocks,
        )
        validate_citations(artifact, set(chunks))
    except (ValidationError, ValueError) as exc:
        raise ValueError("invalid_agent_artifact") from exc

    _lesson_job_active(db, job, settings, started)
    submit_started = time.perf_counter()
    persist_lesson(db, job, artifact, chunks)
    ordinal += 1
    _tool_call(db, run, "SubmitLessonDraft", ordinal, None, 1, submit_started)
    run.status = "succeeded"
    run.step_count = provider_calls
    run.input_tokens = input_tokens
    run.output_tokens = output_tokens
    run.completed_at = now()
    job.status = "succeeded"
    job.lease_expires_at = None
    job.error_code = None
    job.error_message = None


def execute_generation(db: Session, settings: Settings, job: CourseGenerationJob) -> None:
    course = db.get(Course, job.course_id)
    if not course or course.workspace_id != job.workspace_id or course.lifecycle_status != "active":
        raise ValueError("generation_canceled")
    role = "course_architect" if job.job_type == "course_outline" else "lesson_writer"
    lesson = db.get(Lesson, job.lesson_id) if job.lesson_id else None
    request = CourseAgentRequest(title=course.title, goal=course.goal, audience=course.audience, lesson_title=lesson.title if lesson else None, lesson_objective=lesson.objective if lesson else None, output_language=job.output_language)
    if role == "lesson_writer":
        if lesson is None:
            raise ValueError("lesson_not_found")
        _execute_lesson_generation(db, settings, job, request)
        return
    run = AgentRun(course_generation_job_id=job.id, workspace_id=job.workspace_id, role=role, attempt_number=job.attempt_count, status="running")
    db.add(run); db.flush()
    plan, plan_usage = call_provider(settings, build_search_prompt(role, request))
    maximum_searches = 5 if role == "course_architect" else 3
    queries = plan.get("queries") if isinstance(plan, dict) else None
    if not isinstance(queries, list) or not 1 <= len(queries) <= maximum_searches or any(not isinstance(query, str) or not query.strip() or len(query) > 300 for query in queries):
        raise ValueError("invalid_agent_artifact")
    queries = list(dict.fromkeys(query.strip() for query in queries))
    evidence: list[dict[str, str]] = []
    chunks: dict[str, DocumentChunk] = {}
    seen_chunk_ids: set[str] = set()
    evidence_tokens = 0
    for ordinal, query in enumerate(queries, 1):
        started = time.perf_counter()
        search_evidence, search_chunks = evidence_search(db, settings, job, query)
        added = 0
        for item in search_evidence:
            estimated = max(1, int(len(item["text"]) * 0.6))
            chunk = search_chunks[item["citation_id"]]
            if chunk.id in seen_chunk_ids or evidence_tokens + estimated > settings.product_generation_max_evidence_tokens:
                continue
            citation_id = f"e{len(evidence) + 1}"
            evidence.append({"citation_id": citation_id, "text": item["text"]})
            chunks[citation_id] = chunk
            seen_chunk_ids.add(chunk.id)
            evidence_tokens += estimated; added += 1
        _tool_call(db, run, "CourseEvidenceSearch", ordinal, query, added, started)
    if not evidence:
        raise ValueError("insufficient_evidence")
    messages = build_generation_prompt(role, request, evidence)
    generated, usage = call_provider(settings, messages)
    usage = {"input_tokens": (plan_usage["input_tokens"] or 0) + (usage["input_tokens"] or 0), "output_tokens": (plan_usage["output_tokens"] or 0) + (usage["output_tokens"] or 0)}
    submit_started = time.perf_counter()
    submit_ordinal = len(queries) + 1
    try:
        artifact = CourseOutlineArtifact.model_validate(generated) if role == "course_architect" else LessonDraftArtifact.model_validate(generated)
        validate_citations(artifact, set(chunks))
    except (ValidationError, ValueError) as exc:
        _tool_call(db, run, "SubmitCourseOutline" if role == "course_architect" else "SubmitLessonDraft", submit_ordinal, None, None, submit_started, "failed", "invalid_agent_artifact")
        maximum_steps = 6 if role == "course_architect" else 4
        if submit_ordinal + 1 > maximum_steps:
            raise ValueError("agent_step_budget_exceeded") from exc
        repair_messages = messages + [{"role": "assistant", "content": json.dumps(generated, ensure_ascii=False)}, {"role": "user", "content": f"Repair only the JSON structure and citations. Validation error: {type(exc).__name__}. Return JSON only."}]
        generated, repair_usage = call_provider(settings, repair_messages)
        usage = {"input_tokens": (usage["input_tokens"] or 0) + (repair_usage["input_tokens"] or 0), "output_tokens": (usage["output_tokens"] or 0) + (repair_usage["output_tokens"] or 0)}
        submit_ordinal += 1
        submit_started = time.perf_counter()
        try:
            artifact = CourseOutlineArtifact.model_validate(generated) if role == "course_architect" else LessonDraftArtifact.model_validate(generated)
            validate_citations(artifact, set(chunks))
        except (ValidationError, ValueError) as repair_exc:
            _tool_call(db, run, "SubmitCourseOutline" if role == "course_architect" else "SubmitLessonDraft", submit_ordinal, None, None, submit_started, "failed", "invalid_agent_artifact")
            raise ValueError("invalid_agent_artifact") from repair_exc
    workspace = db.scalar(select(Workspace).where(Workspace.id == job.workspace_id).with_for_update())
    db.refresh(job)
    if workspace is None or workspace.lifecycle_status != "active" or job.status != "running" or (job.lease_expires_at and job.lease_expires_at < now()):
        raise ValueError("generation_canceled")
    if role == "course_architect":
        persist_outline(db, job, artifact, chunks)
    else:
        persist_lesson(db, job, artifact, chunks)
    _tool_call(db, run, "SubmitCourseOutline" if role == "course_architect" else "SubmitLessonDraft", submit_ordinal, None, 1, submit_started)
    run.status = "succeeded"; run.step_count = submit_ordinal; run.input_tokens = usage["input_tokens"]; run.output_tokens = usage["output_tokens"]; run.completed_at = now()
    job.status = "succeeded"; job.lease_expires_at = None; job.error_code = None; job.error_message = None
