import time
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import ValidationError

from academic_companion.tutor_agents import TutorAnswerArtifact, answer_prompt, search_prompt
from learn_platform_api.db.models import AgentRun, AgentToolCall, CourseVersionSource, DocumentChunk, DocumentVersion, Lesson, LessonVersion, SourceDocument, TutorSession, TutorTurn, TutorTurnCitation, Workspace
from learn_platform_api.services.course_generation import call_provider
from learn_platform_api.services.retrieval import retrieve
from learn_platform_api.settings import Settings


def _lesson_context(db: Session, turn: TutorTurn) -> dict | None:
    if turn.scope != "lesson": return None
    lesson = db.get(Lesson, turn.lesson_id); version = db.get(LessonVersion, turn.lesson_version_id)
    return {"title": lesson.title, "objective": lesson.objective, "published_blocks": version.blocks} if lesson and version else None


def _history(db: Session, turn: TutorTurn) -> list[dict]:
    rows = list(db.scalars(select(TutorTurn).where(TutorTurn.session_id == turn.session_id, TutorTurn.status == "succeeded", TutorTurn.ordinal <= turn.history_through_ordinal).order_by(TutorTurn.ordinal.desc()).limit(8)))
    result = []; token_budget = 6000
    for item in reversed(rows):
        entry = {"question": item.question, "answer_blocks": item.answer_blocks or []}; estimate = max(1, len(str(entry)) // 2)
        if estimate <= token_budget: result.append(entry); token_budget -= estimate
    return result


def _search(db: Session, settings: Settings, session: TutorSession, query: str, seen: set[str], token_total: list[int]):
    sources = list(db.scalars(select(CourseVersionSource).where(CourseVersionSource.course_version_id == session.course_version_id)))
    for source in sources:
        document = db.get(SourceDocument, source.document_id); version = db.get(DocumentVersion, source.document_version_id)
        if not document or not version or document.lifecycle_status != "active" or document.current_version_id != version.id or version.processing_status != "ready": raise ValueError("source_snapshot_stale")
    _, results = retrieve(db, settings, session.workspace_id, query, 5, document_ids=[source.document_id for source in sources])
    by_version = {source.document_version_id: source for source in sources}; evidence = []; ledger = {}
    for result in results:
        chunk = db.get(DocumentChunk, result.citation.chunk_id)
        if not chunk or chunk.id in seen or chunk.document_version_id not in by_version: continue
        estimate = max(1, len(result.text) // 2)
        if token_total[0] + estimate > settings.tutor_max_evidence_tokens: continue
        citation_id = f"e{len(seen) + 1}"; seen.add(chunk.id); token_total[0] += estimate
        evidence.append({"citation_id": citation_id, "text": result.text}); ledger[citation_id] = (chunk, by_version[chunk.document_version_id])
    return evidence, ledger


def execute_tutor_turn(db: Session, settings: Settings, turn: TutorTurn) -> None:
    session = db.get(TutorSession, turn.session_id)
    if not session or session.status != "active": raise ValueError("generation_canceled")
    run = AgentRun(tutor_turn_id=turn.id, workspace_id=turn.workspace_id, role="tutor", attempt_number=turn.attempt_number, status="running")
    db.add(run); db.flush(); context = _lesson_context(db, turn)
    planned, plan_usage = call_provider(settings, search_prompt(turn.question, turn.scope, context), settings.tutor_max_output_tokens); queries = planned.get("queries") if isinstance(planned, dict) else None
    if not isinstance(queries, list) or not 1 <= len(queries) <= 3 or any(not isinstance(value, str) or not value.strip() or len(value) > 300 for value in queries): raise ValueError("invalid_agent_artifact")
    queries = list(dict.fromkeys(value.strip() for value in queries)); evidence = []; ledger = {}; seen = set(); token_total = [0]
    for ordinal, query in enumerate(queries, 1):
        started = time.perf_counter(); items, chunks = _search(db, settings, session, query, seen, token_total); evidence.extend(items); ledger.update(chunks)
        db.add(AgentToolCall(agent_run_id=run.id, workspace_id=turn.workspace_id, tool_name="TutorEvidenceSearch", ordinal=ordinal, status="succeeded", result_count=len(items), latency_ms=round((time.perf_counter() - started) * 1000)))
    if not evidence:
        completed = datetime.now(timezone.utc); turn.answer_blocks = [{"block_key": "insufficient", "type": "limitation", "text": "当前课程资料不足以可靠回答这个问题。请缩小问题范围或补充资料。", "citation_ids": []}]; turn.status = "succeeded"; turn.completed_at = completed; run.status = "succeeded"; run.step_count = len(queries); run.completed_at = completed; return
    messages = answer_prompt(turn.question, turn.scope, context, _history(db, turn), evidence); generated, usage = call_provider(settings, messages, settings.tutor_max_output_tokens); submit_ordinal = len(queries) + 1
    try:
        artifact = TutorAnswerArtifact.model_validate(generated)
        if not {cid for block in artifact.blocks for cid in block.citation_ids}.issubset(ledger): raise ValueError("unknown_citation")
    except (ValidationError, ValueError) as exc:
        if submit_ordinal + 1 > 5: raise ValueError("agent_step_budget_exceeded") from exc
        repaired, repair_usage = call_provider(settings, messages + [{"role": "assistant", "content": str(generated)}, {"role": "user", "content": "Repair JSON structure and citation IDs only. Return JSON."}], settings.tutor_max_output_tokens); submit_ordinal += 1
        usage = {"input_tokens": (usage["input_tokens"] or 0) + (repair_usage["input_tokens"] or 0), "output_tokens": (usage["output_tokens"] or 0) + (repair_usage["output_tokens"] or 0)}
        try:
            artifact = TutorAnswerArtifact.model_validate(repaired)
            if not {cid for block in artifact.blocks for cid in block.citation_ids}.issubset(ledger): raise ValueError("invalid_agent_artifact")
        except (ValidationError, ValueError) as repair_exc:
            raise ValueError("invalid_agent_artifact") from repair_exc
    workspace = db.scalar(select(Workspace).where(Workspace.id == turn.workspace_id).with_for_update())
    db.refresh(turn); db.refresh(session)
    if not workspace or workspace.lifecycle_status != "active" or turn.status != "running" or session.status != "active": raise ValueError("generation_canceled")
    turn.answer_blocks = [block.model_dump() for block in artifact.blocks]; cited = set()
    for block in artifact.blocks:
        for citation_id in block.citation_ids:
            if citation_id in cited: continue
            cited.add(citation_id); chunk, source = ledger[citation_id]
            db.add(TutorTurnCitation(turn_id=turn.id, workspace_id=turn.workspace_id, block_key=block.block_key, citation_id=citation_id, document_id=source.document_id, document_version_id=source.document_version_id, document_chunk_id=chunk.id))
    completed = datetime.now(timezone.utc); turn.status = "succeeded"; turn.input_tokens = (plan_usage["input_tokens"] or 0) + (usage["input_tokens"] or 0); turn.output_tokens = (plan_usage["output_tokens"] or 0) + (usage["output_tokens"] or 0); turn.completed_at = completed; turn.lease_expires_at = None
    run.status = "succeeded"; run.step_count = submit_ordinal; run.input_tokens = turn.input_tokens; run.output_tokens = turn.output_tokens; run.completed_at = completed
