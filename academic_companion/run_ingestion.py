"""数据摄入脚本 — 将 CS-Base + LeetCode 分批导入本地 Qdrant

Usage:
    python academic_companion/run_ingestion.py

Embedding 模型由 .env 的 EMBED_RAG_MODEL 控制，默认 bge-large-zh-v1.5。
分批次处理以避免 OOM。
"""

import os
import sys
import gc
import json
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from hello_agents.embedding import get_text_embedder, get_dimension
from hello_agents.rag.pipeline import load_and_chunk_texts, index_chunks
from hello_agents.storage.qdrant_store import QdrantVectorStore


def main():
    print("=" * 60)
    print("Phase 2: RAG Data Ingestion (batched)")
    print("=" * 60)

    embedder = get_text_embedder("rag")
    print(f"Embedding Model: {embedder.model_name}")
    print(f"Vector Dimension: {embedder.dimension}")
    store = QdrantVectorStore()
    print(f"Qdrant: {os.getenv('QDRANT_URL', '')[:50]}...")

    # ================================================================
    # CS-Base — 按 subject 分批
    # ================================================================
    cs_base = Path("data/cs_fundamentals/CS-Base")
    subjects = ["mysql", "network", "os", "redis"]

    total_cs_chunks = 0
    for subject in subjects:
        subject_dir = cs_base / subject
        if not subject_dir.is_dir():
            continue

        md_files = sorted(subject_dir.rglob("*.md"))
        if not md_files:
            continue

        print(f"\n{'─'*40}")
        print(f"CS-Base / {subject}: {len(md_files)} files")
        print(f"{'─'*40}")

        paths = [str(f) for f in md_files]
        chunks = load_and_chunk_texts(
            paths, chunk_size=800, chunk_overlap=100,
            namespace="cs_fundamentals", source_label="cs_fundamentals",
        )
        print(f"  Chunks: {len(chunks)}")

        index_chunks(store=store, chunks=chunks, rag_namespace="cs_fundamentals")

        total_cs_chunks += len(chunks)
        print(f"  Done. CS total so far: {total_cs_chunks} chunks")

        # 释放内存
        del chunks
        del paths
        gc.collect()

    # ================================================================
    # LeetCode — 按 500 题一批
    # ================================================================
    print(f"\n{'─'*40}")
    print("LeetCode: Loading problems...")
    print(f"{'─'*40}")

    lc_path = "data/leetcode/leetcode-problems/merged_problems.json"
    with open(lc_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    problems = data.get("questions", [])

    BATCH_SIZE = 500
    total_lc_chunks = 0

    for batch_start in range(0, len(problems), BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, len(problems))
        batch = problems[batch_start:batch_end]
        print(f"\n  LeetCode batch {batch_start+1}-{batch_end} ({len(batch)} problems)...")

        lc_chunks = []
        for prob in batch:
            pid = str(prob.get("problem_id", ""))
            title = prob.get("title", "")
            difficulty = prob.get("difficulty", "Unknown")
            topics = prob.get("topics", [])
            description = prob.get("description", "")
            solution = prob.get("solution", "")
            examples = prob.get("examples", [])

            text_parts = [
                f"# {title} (LeetCode {pid})",
                f"Difficulty: {difficulty}",
            ]
            if topics:
                text_parts.append(f"Topics: {', '.join(topics)}")
            text_parts.append(f"\n{description}")

            if examples:
                text_parts.append(f"\n## Examples\n{str(examples)[:500]}")
            if solution:
                text_parts.append(f"\n## Solution\n{solution[:800]}")

            content = "\n".join(p for p in text_parts if p)
            lc_chunks.append({
                "id": f"lc-{pid}",
                "content": content,
                "metadata": {
                    "source": "leetcode",
                    "problem_id": pid,
                    "title": title,
                    "difficulty": difficulty,
                    "topics": topics,
                    "has_solution": bool(solution),
                },
            })

        index_chunks(store=store, chunks=lc_chunks, rag_namespace="leetcode")

        total_lc_chunks += len(lc_chunks)
        del lc_chunks
        gc.collect()
        print(f"  Done. LC total so far: {total_lc_chunks} chunks")

    # ================================================================
    # Done
    # ================================================================
    print("\n" + "=" * 60)
    print("Ingestion Complete!")
    print(f"  CS Fundamentals: {total_cs_chunks} chunks")
    print(f"  LeetCode:        {total_lc_chunks} chunks")
    print("=" * 60)


if __name__ == "__main__":
    main()
