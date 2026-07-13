from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from sqlalchemy import select
from sqlalchemy.orm import Session

from learn_platform_api.db.models import DocumentChunk, DocumentVersion, SourceDocument
from learn_platform_api.db.session import SessionLocal
from learn_platform_api.settings import Settings
from learn_platform_api.workers import embed_texts, ensure_collection


def rebuild_index(db: Session, settings: Settings) -> int:
    client = QdrantClient(url=settings.qdrant_url)
    if client.collection_exists(settings.product_collection_name):
        client.delete_collection(settings.product_collection_name)
    ensure_collection(client, settings)
    rows = db.execute(
        select(DocumentChunk, DocumentVersion, SourceDocument)
        .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
        .join(SourceDocument, DocumentVersion.document_id == SourceDocument.id)
        .where(SourceDocument.lifecycle_status == "active", DocumentVersion.processing_status == "ready", SourceDocument.current_version_id == DocumentVersion.id)
        .order_by(DocumentChunk.id)
        .execution_options(yield_per=100)
    )
    count = 0
    for batch in rows.partitions(100):
        vectors = embed_texts(settings, [chunk.content for chunk, _, _ in batch], "document")
        client.upsert(settings.product_collection_name, [
            PointStruct(id=chunk.id, vector=vector, payload={"workspace_id": document.workspace_id, "document_id": document.id, "document_version_id": version.id, "chunk_id": chunk.id, "heading_path": chunk.heading_path, "content_hash": chunk.content_hash, "schema_version": 1})
            for (chunk, version, document), vector in zip(batch, vectors)
        ], wait=True)
        count += len(batch)
    return count


def main() -> None:
    from learn_platform_api.settings import get_settings

    with SessionLocal() as db:
        count = rebuild_index(db, get_settings())
    print(f"indexed_chunks={count}")


if __name__ == "__main__":
    main()
