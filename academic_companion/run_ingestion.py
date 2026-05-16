"""数据摄入脚本 — 将 CS-Base + LeetCode 导入 Qdrant Cloud

Usage:
    python academic_companion/run_ingestion.py

使用 HF 镜像加速 + MiniLM 轻量模型，适合国内网络。
后续可改模型名为 "BAAI/bge-large-zh-v1.5" 重跑以获得更好中文效果。
"""

import os
import sys
import json
from pathlib import Path

# HF 镜像加速（国内必须）
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

# 通过 ModelScope 下载的本地 bge 模型
MODEL_NAME = "C:/Users/Admin/.cache/modelscope/hub/models/BAAI/bge-large-zh-v1___5"

from hello_agents.embedding import get_text_embedder
from hello_agents.rag.pipeline import load_and_chunk_texts, index_chunks
from hello_agents.storage.qdrant_store import QdrantVectorStore

# 强制重建全局 embedder（使用 MiniLM）
from hello_agents.embedding.factory import _global_embedder
from hello_agents.embedding.local import LocalTransformerEmbedding
import hello_agents.embedding.factory as fmod
fmod._global_embedder = None


def get_embedder():
    return LocalTransformerEmbedding(MODEL_NAME, device="cpu")


def main():
    print("=" * 60)
    print("Phase 2: RAG Data Ingestion")
    print("=" * 60)

    # 初始化 embedder
    embedder = get_embedder()
    print(f"Embedding Model: {MODEL_NAME}")
    print(f"Vector Dimension: {embedder.dimension}")

    # 替换全局 embedder
    fmod._global_embedder = embedder

    store = QdrantVectorStore()
    print(f"Qdrant: {os.getenv('QDRANT_URL', '')[:50]}...")

    # --- CS-Base ---
    print("\n" + "-" * 40)
    print("CS-Base: Loading 123 markdown files...")
    cs_files = sorted(Path("data/cs_fundamentals/CS-Base").rglob("*.md"))
    cs_paths = [str(f) for f in cs_files]
    print(f"  Files: {len(cs_paths)}")

    cs_chunks = load_and_chunk_texts(
        cs_paths, chunk_size=800, chunk_overlap=100,
        namespace="cs_fundamentals", source_label="cs_fundamentals",
    )
    print(f"  Chunks: {len(cs_chunks)}")

    print("  Embedding & Uploading...")
    index_chunks(store=store, chunks=cs_chunks, rag_namespace="cs_fundamentals")
    stats = store.get_collection_stats("cs_fundamentals")
    print(f"  CS Collection: {stats}")

    # --- LeetCode (first 300) ---
    print("\n" + "-" * 40)
    print("LeetCode: Loading problems...")

    lc_path = "data/leetcode/leetcode-problems/merged_problems.json"
    with open(lc_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    problems = data.get("questions", [])[:300]

    lc_chunks = []
    for prob in problems:
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
            f"Topics: {', '.join(topics)}" if topics else "",
            f"\n{description}",
        ]
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

    print(f"  Problems loaded: {len(lc_chunks)}")

    print("  Embedding & Uploading...")
    index_chunks(store=store, chunks=lc_chunks, rag_namespace="leetcode")
    stats = store.get_collection_stats("leetcode")
    print(f"  LeetCode Collection: {stats}")

    # --- Done ---
    print("\n" + "=" * 60)
    print("Ingestion Complete!")
    print(f"  CS Fundamentals: {len(cs_chunks)} chunks")
    print(f"  LeetCode:        {len(lc_chunks)} chunks")
    print("=" * 60)


if __name__ == "__main__":
    main()
