import hashlib
import time
from uuid import uuid4

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue
from sqlalchemy import select
from sqlalchemy.orm import Session

from learn_platform_api.db.models import DocumentChunk, DocumentVersion, RagQueryTrace, SourceDocument
from learn_platform_api.schemas.documents import CitationRead, RetrievalResult
from learn_platform_api.settings import Settings
from learn_platform_api.workers import embed_texts


QUESTION_MARKERS = ("?", "?", "什么", "怎么", "如何", "为何", "为什么", "是否", "哪些", "哪个", "多少", "几", "请问")


def _normalized_text(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _is_short_keyword(query: str) -> bool:
    normalized = _normalized_text(query)
    return 2 <= len(normalized) <= 20 and not any(marker in query for marker in QUESTION_MARKERS)


def _query_terms(query: str) -> set[str]:
    normalized = _normalized_text(query)
    for marker in QUESTION_MARKERS[2:]:
        normalized = normalized.replace(marker, "")
    if len(normalized) < 2:
        return set()
    terms = {normalized}
    maximum = min(6, len(normalized))
    for size in range(2, maximum + 1):
        terms.update(normalized[index:index + size] for index in range(len(normalized) - size + 1))
    return terms


def _has_lexical_support(query: str, document: SourceDocument, chunk: DocumentChunk) -> bool:
    searchable = _normalized_text(" ".join((document.display_name, chunk.heading_path or "", chunk.content)))
    if _is_short_keyword(query):
        return _normalized_text(query) in searchable
    matched = [term for term in _query_terms(query) if term in searchable]
    return any(len(term) >= 3 for term in matched) or sum(len(term) == 2 for term in matched) >= 2


def _passes_relevance_gate(query: str, score: float, document: SourceDocument, chunk: DocumentChunk, settings: Settings) -> bool:
    if _has_lexical_support(query, document, chunk):
        return True
    # A missing legacy environment value must not silently restore Top-K-as-evidence.
    minimum_score = settings.product_rag_min_score if settings.product_rag_min_score is not None else 0.50
    return score >= minimum_score


def _close_client(client) -> None:
    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            # Query results remain authoritative only after the Postgres
            # back-read; closing a best-effort client must not replace them.
            pass


def retrieve(
    db: Session,
    settings: Settings,
    workspace_id: str,
    query: str,
    top_k: int,
    candidate_limit: int | None = None,
    document_ids: list[str] | None = None,
) -> tuple[str, list[RetrievalResult]]:
    started = time.perf_counter()
    # The query endpoint also needs enough candidates for lifecycle and
    # relevance filtering; otherwise a valid lexical match can be hidden by
    # the first semantic Top-K alone.
    if candidate_limit is None:
        candidate_limit = min(
            top_k * settings.product_rag_candidate_multiplier,
            settings.product_rag_candidate_cap,
        )
    vector = embed_texts(settings, [query], "query")[0]
    client = QdrantClient(url=settings.qdrant_url)
    try:
        filters = [FieldCondition(key="workspace_id", match=MatchValue(value=workspace_id))]
        if document_ids:
            filters.append(FieldCondition(key="document_id", match=MatchAny(any=document_ids)))
        response = client.query_points(
            collection_name=settings.product_collection_name,
            query=vector,
            query_filter=Filter(must=filters),
            limit=candidate_limit,
        )
        candidate_ids = [str(point.payload.get("chunk_id")) for point in response.points if point.payload and point.payload.get("chunk_id")]
        rows = db.execute(
            select(DocumentChunk, DocumentVersion, SourceDocument)
            .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
            .join(SourceDocument, DocumentVersion.document_id == SourceDocument.id)
            .where(DocumentChunk.id.in_(candidate_ids))
        ).all() if candidate_ids else []
        chunks = {chunk.id: (chunk, version, document) for chunk, version, document in rows}
        results: list[RetrievalResult] = []
        for point in response.points:
            payload = point.payload or {}
            row = chunks.get(str(payload.get("chunk_id")))
            if row is None:
                continue
            chunk, version, document = row
            if (
                document is None
                or version is None
                or document.workspace_id != workspace_id
                or document.lifecycle_status != "active"
                or document.current_version_id != version.id
                or version.processing_status != "ready"
                or (document_ids is not None and document.id not in document_ids)
            ):
                continue
            score = float(point.score)
            if not _passes_relevance_gate(query, score, document, chunk, settings):
                continue
            results.append(
                RetrievalResult(
                    score=score,
                    text=chunk.content,
                    citation=CitationRead(
                        document_id=document.id,
                        document_version_id=version.id,
                        chunk_id=chunk.id,
                        document_name=document.display_name,
                        heading_path=chunk.heading_path.split(" / ") if chunk.heading_path else [],
                        start_offset=chunk.start_offset,
                        end_offset=chunk.end_offset,
                    ),
                )
            )
        trace = RagQueryTrace(
            id=str(uuid4()),
            workspace_id=workspace_id,
            query_hash=hashlib.sha256(query.encode("utf-8")).hexdigest(),
            top_k=top_k,
            filter_summary={
                "workspace_id": workspace_id,
                "document_ids": ",".join(document_ids or []),
                "relevance_policy": "lexical_or_min_score",
                "minimum_score": settings.product_rag_min_score if settings.product_rag_min_score is not None else 0.50,
            },
            collection_name=settings.product_collection_name,
            embedding_model=settings.product_embedding_model,
            candidate_count=len(candidate_ids),
            result_count=len(results),
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
        db.add(trace)
        db.commit()
        return trace.id, results[:top_k]
    finally:
        _close_client(client)
