from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from reportlab.pdfgen import canvas
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from learn_platform_api.db.base import Base
from learn_platform_api.db.models import DocumentChunk, DocumentParseReport, DocumentVersion, IngestionJob, RagAnswerTrace, RagQueryTrace, SourceDocument, Workspace
from learn_platform_api.schemas.documents import CitationRead, RetrievalResult
from learn_platform_api.services.retrieval import retrieve
from learn_platform_api.services.jobs import reconcile_jobs
from learn_platform_api.maintenance import rebuild_index
from learn_platform_api.services.documents import safe_display_name
from learn_platform_api.services.storage import remove_tree, write_original
from learn_platform_api.settings import get_settings
from learn_platform_api.workers import claim_job, chunk_text, heading_path_at, heartbeat_job, normalize_text, parse_document, run_cleanup_job, run_ingestion_job


def create_workspace(client: TestClient) -> str:
    response = client.post("/api/v1/workspaces", json={"name": "资料测试"})
    assert response.status_code == 201
    return response.json()["id"]


def test_document_list_requires_existing_workspace(client: TestClient) -> None:
    response = client.get("/api/v1/workspaces/00000000-0000-0000-0000-000000000000/documents")

    assert response.status_code == 404
    assert response.json()["detail"] == "Workspace 不存在"


def test_empty_upload_is_rejected_without_creating_a_document(client: TestClient) -> None:
    workspace_id = create_workspace(client)
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/documents",
        files={"file": ("empty.md", b"", "text/markdown")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "文件不能为空"
    assert client.get(f"/api/v1/workspaces/{workspace_id}/documents").json() == []


def test_retrieval_reports_unavailable_embedding_provider(client: TestClient, monkeypatch) -> None:
    from learn_platform_api.routers import documents
    from learn_platform_api.settings import get_settings

    monkeypatch.setattr(
        documents,
        "get_settings",
        lambda: get_settings().model_copy(update={"product_embedding_api_key": None}),
    )
    workspace_id = create_workspace(client)
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/rag/query",
        json={"query": "测试检索"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "检索服务暂不可用"


def test_retrieval_requires_existing_workspace(client: TestClient) -> None:
    response = client.post(
        "/api/v1/workspaces/00000000-0000-0000-0000-000000000000/rag/query",
        json={"query": "test"},
    )

    assert response.status_code == 404


def test_batch_upload_keeps_partial_failure_and_idempotency(client: TestClient, monkeypatch, tmp_path) -> None:
    from learn_platform_api.routers import documents as document_router
    from learn_platform_api.services import documents as document_service

    queued: list[str] = []
    settings = get_settings().model_copy(update={"storage_root": tmp_path})
    monkeypatch.setattr(document_router, "get_settings", lambda: settings)
    monkeypatch.setattr(document_service, "enqueue_ingestion_job", lambda _settings, job_id: queued.append(job_id))
    workspace_id = create_workspace(client)
    headers = {"Idempotency-Key": "batch-1"}
    files = [
        ("files", ("good.md", b"# Title\n\nBody", "text/markdown")),
        ("files", ("bad.exe", b"not supported", "application/octet-stream")),
    ]

    first = client.post(f"/api/v1/workspaces/{workspace_id}/document-batches", files=files, headers=headers)
    assert first.status_code == 202
    payload = first.json()
    assert payload["item_count"] == 2
    assert [item["status"] for item in payload["items"]] == ["queued", "rejected"]
    assert len(queued) == 1

    replay = client.post(f"/api/v1/workspaces/{workspace_id}/document-batches", files=files, headers=headers)
    assert replay.status_code == 202
    assert replay.json()["id"] == payload["id"]
    assert len(queued) == 1

    changed_same_size = [
        ("files", ("good.md", b"# Other\n\nBody", "text/markdown")),
        ("files", ("bad.exe", b"not supported", "application/octet-stream")),
    ]
    conflict = client.post(f"/api/v1/workspaces/{workspace_id}/document-batches", files=changed_same_size, headers=headers)
    assert conflict.status_code == 409


def test_batch_upload_enforces_aggregate_limit(client: TestClient, monkeypatch) -> None:
    from learn_platform_api.routers import documents as document_router

    settings = get_settings().model_copy(update={"batch_max_bytes": 10})
    monkeypatch.setattr(document_router, "get_settings", lambda: settings)
    workspace_id = create_workspace(client)
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/document-batches",
        headers={"Idempotency-Key": "too-large"},
        files=[("files", ("one.txt", b"12345678901", "text/plain"))],
    )

    assert response.status_code == 413


def test_resource_limits_fail_before_ready() -> None:
    settings = get_settings().model_copy(update={"parsed_text_max_chars": 10, "document_max_chunks": 1})
    with pytest.raises(ValueError, match="parsed_text_limit_exceeded"):
        parse_document("notes.txt", b"x" * 20, settings)
    with pytest.raises(ValueError, match="chunk_limit_exceeded"):
        chunk_text("x" * 2000, max_chunks=1)


def test_cited_answer_validates_model_citations(db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import answers

    workspace = Workspace(name="Answer", slug="answer")
    db_session.add(workspace)
    db_session.commit()
    result = RetrievalResult(
        score=0.9,
        text="重复 job 会覆盖结果。",
        citation=CitationRead(document_id="doc", document_version_id="version", chunk_id="chunk", document_name="资料.md", heading_path=["幂等"], start_offset=0, end_offset=12),
    )
    monkeypatch.setattr(answers, "retrieve", lambda *_args, **_kwargs: (None, [result]))
    monkeypatch.setattr(answers, "_generate", lambda *_args, **_kwargs: ({"claims": [{"text": "重复执行不会追加副本。", "citation_ids": ["c1"]}], "limitations": []}, {"input_tokens": 10, "output_tokens": 5}, 1))
    settings = get_settings().model_copy(update={"product_generation_api_key": "test-key"})

    response = answers.answer_question(db_session, settings, workspace.id, "什么是幂等？", 5, None)

    assert response["status"] == "succeeded"
    assert response["claims"][0].citation_ids == ["c1"]
    trace = db_session.scalar(select(RagAnswerTrace))
    assert trace.status == "succeeded"

    monkeypatch.setattr(answers, "_generate", lambda *_args, **_kwargs: ({"claims": [{"text": "无效", "citation_ids": ["unknown"]}]}, {}, 1))
    with pytest.raises(ValueError, match="invalid_model_output"):
        answers.answer_question(db_session, settings, workspace.id, "再问一次", 5, None)


def test_cited_answer_requires_generation_configuration_only_after_evidence(db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import answers

    workspace = Workspace(name="No provider", slug="no-provider")
    db_session.add(workspace)
    db_session.commit()
    result = RetrievalResult(
        score=0.9,
        text="有效证据",
        citation=CitationRead(document_id="doc", document_version_id="version", chunk_id="chunk", document_name="资料.md", heading_path=[], start_offset=0, end_offset=4),
    )
    monkeypatch.setattr(answers, "retrieve", lambda *_args, **_kwargs: ("query-trace", [result]))

    with pytest.raises(ValueError, match="generation_provider_unconfigured"):
        answers.answer_question(db_session, get_settings().model_copy(update={"product_generation_api_key": None}), workspace.id, "问题", 5, None)


def test_cited_answer_does_not_call_generation_without_qualified_evidence(db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import answers

    workspace = Workspace(name="No evidence", slug="no-evidence")
    db_session.add(workspace)
    db_session.commit()
    monkeypatch.setattr(answers, "retrieve", lambda *_args, **_kwargs: ("query-trace", []))
    monkeypatch.setattr(answers, "_generate", lambda *_args, **_kwargs: pytest.fail("不应为无关候选调用生成模型"))

    response = answers.answer_question(
        db_session,
        get_settings().model_copy(update={"product_generation_api_key": None}),
        workspace.id,
        "英雄联盟",
        5,
        None,
    )

    assert response["status"] == "insufficient_evidence"
    assert response["claims"] == []


def test_cited_answer_records_retrieval_failure(db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import answers

    workspace = Workspace(name="Retrieval failure", slug="retrieval-failure")
    db_session.add(workspace)
    db_session.commit()
    monkeypatch.setattr(answers, "retrieve", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("qdrant unavailable")))

    with pytest.raises(RuntimeError, match="retrieval_unavailable"):
        answers.answer_question(
            db_session,
            get_settings().model_copy(update={"product_generation_api_key": "test-key"}),
            workspace.id,
            "问题",
            5,
            None,
        )

    trace = db_session.scalar(select(RagAnswerTrace).where(RagAnswerTrace.workspace_id == workspace.id))
    assert trace is not None
    assert trace.status == "failed"
    assert trace.error_code == "retrieval_unavailable"


def test_text_parser_and_chunker_are_deterministic() -> None:
    text, parser_key, page_count, warnings = parse_document("notes.md", b"# Title\r\n\r\n\x00" + b"content " * 300)

    first = chunk_text(text)
    second = chunk_text(text)

    assert parser_key == "text"
    assert page_count is None
    assert warnings == []
    assert "\x00" not in text
    assert first == second
    assert first[0][1] == 0
    assert all(start < end for _, start, end in first)
    assert heading_path_at(text, text.index("content")) == "Title"


def test_normalize_text_removes_database_unsafe_control_characters() -> None:
    normalized = normalize_text("safe\x00 text\x1f\ud800\nnext")

    assert "\x00" not in normalized
    assert "\x1f" not in normalized
    assert not any(0xD800 <= ord(character) <= 0xDFFF for character in normalized)


def test_display_name_rejects_database_unsafe_characters() -> None:
    with pytest.raises(ValueError, match="invalid_filename"):
        safe_display_name("unsafe\x00.txt")


def test_scanned_pdf_requires_ocr() -> None:
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(buffer)

    with pytest.raises(ValueError, match="ocr_required"):
        parse_document("scan.pdf", buffer.getvalue())


def test_pdf_with_only_incidental_text_requires_ocr() -> None:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(72, 720, "x")
    pdf.save()

    with pytest.raises(ValueError, match="ocr_required"):
        parse_document("scan-with-page-number.pdf", buffer.getvalue())


def test_text_pdf_is_parsed_with_page_count() -> None:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(72, 720, "Hello learning platform")
    pdf.save()

    text, parser_key, page_count, warnings = parse_document(
        "notes.pdf",
        buffer.getvalue(),
        get_settings().model_copy(update={"parser_timeout_seconds": 20}),
    )

    assert "Hello learning platform" in text
    assert parser_key == "pypdf"
    assert page_count == 1
    assert warnings == []


def test_encrypted_pdf_has_stable_error() -> None:
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret")
    writer.write(buffer)

    with pytest.raises(ValueError, match="encrypted_pdf"):
        parse_document("secret.pdf", buffer.getvalue())


def test_upload_lists_summary_and_soft_deletes_pending_document(
    client: TestClient, db_session: Session, monkeypatch, tmp_path
) -> None:
    from learn_platform_api.routers import documents as document_router
    from learn_platform_api.services import documents as document_service

    queued: list[str] = []
    settings = get_settings().model_copy(update={"storage_root": tmp_path})
    monkeypatch.setattr(document_router, "get_settings", lambda: settings)
    monkeypatch.setattr(document_service, "enqueue_ingestion_job", lambda _settings, job_id: queued.append(job_id))
    workspace_id = create_workspace(client)

    uploaded = client.post(
        f"/api/v1/workspaces/{workspace_id}/documents",
        files={"file": ("notes.md", b"# Heading\n\nBody", "text/markdown")},
    )

    assert uploaded.status_code == 202
    payload = uploaded.json()
    assert queued == [payload["job"]["id"]]
    listed = client.get(f"/api/v1/workspaces/{workspace_id}/documents").json()
    assert listed[0]["current_version"]["processing_status"] == "queued"
    assert listed[0]["latest_job"]["status"] == "queued"

    deleted = client.delete(f"/api/v1/workspaces/{workspace_id}/documents/{payload['document']['id']}")

    assert deleted.status_code == 202
    assert deleted.json()["document_version_id"] == payload["version"]["id"]
    assert client.get(f"/api/v1/workspaces/{workspace_id}/documents").json() == []
    assert db_session.get(SourceDocument, payload["document"]["id"]).lifecycle_status == "deleted"


def test_enqueue_failure_is_authoritative_and_retryable(client: TestClient, monkeypatch, tmp_path) -> None:
    from learn_platform_api.routers import documents as document_router
    from learn_platform_api.services import documents as document_service

    settings = get_settings().model_copy(update={"storage_root": tmp_path})
    monkeypatch.setattr(document_router, "get_settings", lambda: settings)
    calls = 0

    def enqueue(_settings, _job_id):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("redis unavailable")

    monkeypatch.setattr(document_service, "enqueue_ingestion_job", enqueue)
    workspace_id = create_workspace(client)
    uploaded = client.post(
        f"/api/v1/workspaces/{workspace_id}/documents",
        files={"file": ("notes.txt", b"text", "text/plain")},
    )

    assert uploaded.status_code == 202
    assert uploaded.json()["job"]["status"] == "queue_failed"
    retried = client.post(
        f"/api/v1/workspaces/{workspace_id}/ingestion-jobs/{uploaded.json()['job']['id']}/retry"
    )
    assert retried.status_code == 202
    assert retried.json()["status"] == "queued"
    assert calls == 2


@pytest.mark.parametrize(
    ("filename", "content", "content_type"),
    [
        ("fake.pdf", b"not a pdf", "application/pdf"),
        ("bad.txt", b"\xff\xfe", "text/plain"),
        ("notes.exe", b"text", "application/octet-stream"),
    ],
)
def test_invalid_upload_content_is_rejected(
    client: TestClient, filename: str, content: bytes, content_type: str
) -> None:
    workspace_id = create_workspace(client)
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/documents",
        files={"file": (filename, content, content_type)},
    )

    assert response.status_code == 422
    assert client.get(f"/api/v1/workspaces/{workspace_id}/documents").json() == []


def test_upload_size_limit_is_enforced_before_persistence(client: TestClient, monkeypatch) -> None:
    from learn_platform_api.routers import documents as document_router

    settings = get_settings().model_copy(update={"document_max_bytes": 3})
    monkeypatch.setattr(document_router, "get_settings", lambda: settings)
    workspace_id = create_workspace(client)

    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/documents",
        files={"file": ("notes.txt", b"four", "text/plain")},
    )

    assert response.status_code == 422
    assert client.get(f"/api/v1/workspaces/{workspace_id}/documents").json() == []


def test_reconcile_requeues_expired_lease(db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import jobs as job_service

    # Foreign keys are not enforced by the SQLite fixture, keeping this test focused on state recovery.
    job = IngestionJob(
        workspace_id="workspace",
        job_type="ingest_document_version",
        status="running",
        idempotency_key="reconcile:test:1",
        lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db_session.add(job)
    db_session.commit()
    queued: list[str] = []
    monkeypatch.setattr(job_service, "enqueue_ingestion_job", lambda _settings, job_id: queued.append(job_id))

    count = reconcile_jobs(db_session, get_settings())

    db_session.refresh(job)
    assert count == 1
    assert job.status == "queued"
    assert queued == [job.id]


def test_job_claim_is_idempotent(db_session: Session) -> None:
    workspace = Workspace(name="Claim", slug="claim")
    db_session.add(workspace)
    db_session.flush()
    job = IngestionJob(
        workspace_id=workspace.id,
        job_type="ingest_document_version",
        status="queued",
        idempotency_key="claim:test:1",
    )
    db_session.add(job)
    db_session.commit()

    first = claim_job(db_session, job.id, "worker-1", get_settings())
    second = claim_job(db_session, job.id, "worker-2", get_settings())

    assert first is not None
    assert second is None
    db_session.refresh(job)
    assert job.worker_id == "worker-1"
    assert job.attempt_count == 1


def test_heartbeat_only_extends_owned_running_job(db_session: Session, monkeypatch) -> None:
    from learn_platform_api import workers

    job = IngestionJob(workspace_id="workspace", job_type="ingest_document_version", status="running", worker_id="worker-1", idempotency_key="heartbeat:test:1")
    db_session.add(job)
    db_session.commit()
    factory = lambda: db_session
    monkeypatch.setattr(workers, "SessionLocal", factory)

    assert heartbeat_job(job.id, "worker-1", get_settings())
    assert not heartbeat_job(job.id, "worker-2", get_settings())


def test_storage_rejects_escape_and_removes_document_tree(tmp_path) -> None:
    write_original(tmp_path, "workspaces/w/documents/d/original.txt", b"content")
    remove_tree(tmp_path, "workspaces/w/documents/d")
    assert not (tmp_path / "workspaces/w/documents/d").exists()

    with pytest.raises(ValueError, match="invalid_storage_uri"):
        write_original(tmp_path, "../escape.txt", b"content")


def test_cleanup_job_removes_qdrant_and_storage(db_session: Session, tmp_path, monkeypatch) -> None:
    from learn_platform_api import workers

    workspace = Workspace(name="Cleanup", slug="cleanup")
    db_session.add(workspace)
    db_session.flush()
    document = SourceDocument(workspace_id=workspace.id, display_name="notes.md", lifecycle_status="deleted")
    db_session.add(document)
    db_session.flush()
    version = DocumentVersion(document_id=document.id, version_number=1, processing_status="ready", original_filename="notes.md", mime_type="text/markdown", byte_size=4, sha256="0" * 64, original_storage_uri="original")
    db_session.add(version)
    db_session.flush()
    job = IngestionJob(workspace_id=workspace.id, document_version_id=version.id, job_type="cleanup_document", status="queued", idempotency_key=f"cleanup:{document.id}")
    db_session.add(job)
    db_session.commit()
    settings = get_settings().model_copy(update={"storage_root": tmp_path, "ingestion_heartbeat_seconds": 60})
    relative = f"workspaces/{workspace.id}/documents/{document.id}/original.md"
    write_original(tmp_path, relative, b"body")

    class FakeQdrant:
        deleted = False
        def __init__(self, **_kwargs): pass
        def collection_exists(self, _name): return True
        def delete(self, *_args, **_kwargs): self.__class__.deleted = True

    monkeypatch.setattr(workers, "QdrantClient", FakeQdrant)
    run_cleanup_job(db_session, settings, job)

    db_session.refresh(job)
    assert job.status == "succeeded"
    assert FakeQdrant.deleted
    assert not (tmp_path / f"workspaces/{workspace.id}/documents/{document.id}").exists()


def test_worker_processes_markdown_and_writes_citable_chunks(tmp_path, monkeypatch) -> None:
    from learn_platform_api import workers

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'worker.db'}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    settings = get_settings().model_copy(update={
        "storage_root": tmp_path / "storage",
        "product_embedding_api_key": "test-key",
        "product_embedding_dimension": 3,
        "ingestion_heartbeat_seconds": 60,
    })
    with session_factory() as db:
        workspace = Workspace(name="Test", slug="test")
        db.add(workspace)
        db.flush()
        document = SourceDocument(workspace_id=workspace.id, display_name="notes.md")
        db.add(document)
        db.flush()
        version = DocumentVersion(
            document_id=document.id,
            version_number=1,
            processing_status="queued",
            original_filename="notes.md",
            mime_type="text/markdown",
            byte_size=31,
            sha256="0" * 64,
            original_storage_uri=f"workspaces/{workspace.id}/documents/{document.id}/versions/version/original.md",
        )
        db.add(version)
        db.flush()
        job = IngestionJob(
            workspace_id=workspace.id,
            document_version_id=version.id,
            job_type="ingest_document_version",
            status="queued",
            idempotency_key=f"ingest:{version.id}:1",
        )
        db.add(job)
        db.commit()
        job_id = job.id
        document_id = document.id
        version_id = version.id
        write_original(settings.storage_root, version.original_storage_uri, b"# Chapter\n\n## Topic\n\nBody text")

    class FakeQdrant:
        points = []
        closed = False

        def __init__(self, **_kwargs): pass
        def collection_exists(self, _name): return False
        def create_collection(self, *_args, **_kwargs): return None
        def upsert(self, _name, points, **_kwargs): self.points.extend(points)
        def close(self): self.__class__.closed = True

    monkeypatch.setattr(workers, "SessionLocal", session_factory)
    monkeypatch.setattr(workers, "get_settings", lambda: settings)
    monkeypatch.setattr(workers, "QdrantClient", FakeQdrant)
    monkeypatch.setattr(workers, "embed_texts", lambda _settings, texts, _type: [[0.1, 0.2, 0.3] for _ in texts])

    run_ingestion_job(job_id)

    with session_factory() as db:
        job = db.get(IngestionJob, job_id)
        version = db.get(DocumentVersion, version_id)
        document = db.get(SourceDocument, document_id)
        chunks = list(db.execute(select(DocumentChunk)).scalars())
        report = db.scalar(select(DocumentParseReport))
        assert job.status == "succeeded"
        assert version.processing_status == "ready"
        assert document.current_version_id == version.id
        assert chunks[0].heading_path == "Chapter / Topic"
        assert report.character_count == len("# Chapter\n\n## Topic\n\nBody text")
        assert len(FakeQdrant.points) == len(chunks)
        assert FakeQdrant.closed
    engine.dispose()


def test_retrieval_backreads_postgres_and_filters_stale_candidates(db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import retrieval

    workspace = Workspace(name="One", slug="one")
    other_workspace = Workspace(name="Two", slug="two")
    db_session.add_all([workspace, other_workspace])
    db_session.flush()
    document = SourceDocument(workspace_id=workspace.id, display_name="notes.md")
    other_document = SourceDocument(workspace_id=other_workspace.id, display_name="other.md")
    db_session.add_all([document, other_document])
    db_session.flush()
    version = DocumentVersion(document_id=document.id, version_number=1, processing_status="ready", original_filename="notes.md", mime_type="text/markdown", byte_size=4, sha256="0" * 64, original_storage_uri="one")
    other_version = DocumentVersion(document_id=other_document.id, version_number=1, processing_status="ready", original_filename="other.md", mime_type="text/markdown", byte_size=5, sha256="1" * 64, original_storage_uri="two")
    db_session.add_all([version, other_version])
    db_session.flush()
    document.current_version_id = version.id
    other_document.current_version_id = other_version.id
    chunk = DocumentChunk(id="11111111-1111-1111-1111-111111111111", document_version_id=version.id, ordinal=0, content="Body", content_hash="a" * 64, heading_path="Chapter", start_offset=0, end_offset=4)
    other_chunk = DocumentChunk(id="22222222-2222-2222-2222-222222222222", document_version_id=other_version.id, ordinal=0, content="Other", content_hash="b" * 64, start_offset=0, end_offset=5)
    db_session.add_all([chunk, other_chunk])
    db_session.commit()

    points = [
        SimpleNamespace(payload={"chunk_id": chunk.id}, score=0.9),
        SimpleNamespace(payload={"chunk_id": other_chunk.id}, score=0.8),
    ]

    class FakeQdrant:
        query_filter = None
        query_limit = None
        closed = False
        def __init__(self, **_kwargs): pass
        def query_points(self, **kwargs):
            self.__class__.query_filter = kwargs["query_filter"]
            self.__class__.query_limit = kwargs["limit"]
            return SimpleNamespace(points=points)
        def close(self): self.__class__.closed = True

    monkeypatch.setattr(retrieval, "embed_texts", lambda *_args: [[0.1, 0.2, 0.3]])
    monkeypatch.setattr(retrieval, "QdrantClient", FakeQdrant)

    trace_id, results = retrieve(db_session, get_settings(), workspace.id, "question", 5)

    assert [result.text for result in results] == ["Body"]
    assert results[0].citation.heading_path == ["Chapter"]
    assert FakeQdrant.query_filter is not None
    assert FakeQdrant.query_limit == 15
    assert FakeQdrant.closed
    trace = db_session.get(RagQueryTrace, trace_id)
    assert trace.result_count == 1
    assert trace.query_hash != "question"


def test_retrieval_requires_qualified_evidence_before_returning_or_answering(db_session: Session, monkeypatch) -> None:
    from learn_platform_api.services import retrieval

    workspace = Workspace(name="Retrieval gate", slug="retrieval-gate")
    db_session.add(workspace)
    db_session.flush()
    matching_document = SourceDocument(workspace_id=workspace.id, display_name="搜广推.md")
    unrelated_document = SourceDocument(workspace_id=workspace.id, display_name="工程说明.md")
    db_session.add_all([matching_document, unrelated_document])
    db_session.flush()
    matching_version = DocumentVersion(document_id=matching_document.id, version_number=1, processing_status="ready", original_filename="搜广推.md", mime_type="text/markdown", byte_size=12, sha256="2" * 64, original_storage_uri="matching")
    unrelated_version = DocumentVersion(document_id=unrelated_document.id, version_number=1, processing_status="ready", original_filename="工程说明.md", mime_type="text/markdown", byte_size=12, sha256="3" * 64, original_storage_uri="unrelated")
    db_session.add_all([matching_version, unrelated_version])
    db_session.flush()
    matching_document.current_version_id = matching_version.id
    unrelated_document.current_version_id = unrelated_version.id
    matching_chunk = DocumentChunk(id="55555555-5555-5555-5555-555555555555", document_version_id=matching_version.id, ordinal=0, content="广告召回与排序", content_hash="d" * 64, start_offset=0, end_offset=7)
    unrelated_chunk = DocumentChunk(id="66666666-6666-6666-6666-666666666666", document_version_id=unrelated_version.id, ordinal=0, content="工程设计说明", content_hash="e" * 64, start_offset=0, end_offset=6)
    db_session.add_all([matching_chunk, unrelated_chunk])
    db_session.commit()

    points = [
        SimpleNamespace(payload={"chunk_id": unrelated_chunk.id}, score=0.414),
        SimpleNamespace(payload={"chunk_id": matching_chunk.id}, score=0.327),
    ]

    class FakeQdrant:
        def __init__(self, **_kwargs): pass
        def query_points(self, **_kwargs): return SimpleNamespace(points=points)
        def close(self): return None

    monkeypatch.setattr(retrieval, "embed_texts", lambda *_args: [[0.1, 0.2, 0.3]])
    monkeypatch.setattr(retrieval, "QdrantClient", FakeQdrant)
    settings = get_settings().model_copy(update={"product_rag_min_score": 0.50})

    _, unrelated_results = retrieve(db_session, settings, workspace.id, "英雄联盟", 5)
    _, matching_results = retrieve(db_session, settings, workspace.id, "搜广推", 5)

    assert unrelated_results == []
    assert [result.text for result in matching_results] == ["广告召回与排序"]


def test_explicit_rebuild_uses_only_active_current_ready_chunks(db_session: Session, monkeypatch) -> None:
    from learn_platform_api import maintenance

    workspace = Workspace(name="Rebuild", slug="rebuild")
    db_session.add(workspace)
    db_session.flush()
    document = SourceDocument(workspace_id=workspace.id, display_name="ready.md")
    deleted = SourceDocument(workspace_id=workspace.id, display_name="deleted.md", lifecycle_status="deleted")
    db_session.add_all([document, deleted])
    db_session.flush()
    version = DocumentVersion(document_id=document.id, version_number=1, processing_status="ready", original_filename="ready.md", mime_type="text/markdown", byte_size=4, sha256="0" * 64, original_storage_uri="one")
    deleted_version = DocumentVersion(document_id=deleted.id, version_number=1, processing_status="ready", original_filename="deleted.md", mime_type="text/markdown", byte_size=7, sha256="1" * 64, original_storage_uri="two")
    db_session.add_all([version, deleted_version])
    db_session.flush()
    document.current_version_id = version.id
    deleted.current_version_id = deleted_version.id
    db_session.add_all([
        DocumentChunk(id="33333333-3333-3333-3333-333333333333", document_version_id=version.id, ordinal=0, content="Keep", content_hash="c" * 64, start_offset=0, end_offset=4),
        DocumentChunk(id="44444444-4444-4444-4444-444444444444", document_version_id=deleted_version.id, ordinal=0, content="Exclude", content_hash="d" * 64, start_offset=0, end_offset=7),
    ])
    db_session.commit()

    class FakeQdrant:
        points = []
        deleted_collection = False
        def __init__(self, **_kwargs): pass
        def collection_exists(self, _name): return not self.__class__.deleted_collection
        def delete_collection(self, _name): self.__class__.deleted_collection = True
        def create_collection(self, *_args, **_kwargs): return None
        def upsert(self, _name, points, **_kwargs): self.__class__.points.extend(points)

    monkeypatch.setattr(maintenance, "QdrantClient", FakeQdrant)
    monkeypatch.setattr(maintenance, "embed_texts", lambda _settings, texts, _type: [[0.1, 0.2, 0.3] for _ in texts])
    settings = get_settings().model_copy(update={"product_embedding_dimension": 3})

    count = rebuild_index(db_session, settings)

    assert count == 1
    assert FakeQdrant.deleted_collection
    assert len(FakeQdrant.points) == 1
