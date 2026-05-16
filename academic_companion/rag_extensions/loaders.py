"""数据加载器 — 将 CS-Base Markdown 和 LeetCode JSON 转换为 RAG Pipeline chunks"""

import json
from pathlib import Path
from typing import List, Dict, Optional
from hello_agents.rag.pipeline import load_and_chunk_texts, index_chunks
from hello_agents.embedding import get_text_embedder
from academic_companion.config import get_config


def load_cs_fundamentals(data_dir: Optional[str] = None) -> List[Dict]:
    """加载 CS-Base Markdown 文件并生成 chunks

    遍历 data/cs_fundamentals/ 目录，将每个 .md 文件切分为语义块。
    使用框架 rag pipeline 的 load_and_chunk_texts()。

    Args:
        data_dir: CS 基础数据目录，默认从 config 推断

    Returns:
        chunk 列表，每个 chunk 含 id, content, metadata
    """
    if data_dir is None:
        data_dir = str(Path(__file__).resolve().parents[2] / "data" / "cs_fundamentals")

    base = Path(data_dir)
    if not base.exists():
        raise FileNotFoundError(f"CS data directory not found: {data_dir}")

    md_files = sorted(base.rglob("*.md"))
    if not md_files:
        raise FileNotFoundError(f"No .md files found in {data_dir}")

    paths = [str(f) for f in md_files]
    print(f"Found {len(paths)} markdown files in {data_dir}")

    config = get_config()
    chunks = load_and_chunk_texts(
        paths,
        chunk_size=800,
        chunk_overlap=100,
        namespace=config.rag.collection_cs,
        source_label="cs_fundamentals",
    )
    print(f"Generated {len(chunks)} chunks from {len(paths)} files")
    return chunks


def load_leetcode(data_dir: Optional[str] = None) -> List[Dict]:
    """加载 LeetCode 题库 JSON 并生成 chunks

    将每道题转换为一个独立的 chunk，
    内容 = title + description + difficulty + topics + solution hint

    Args:
        data_dir: LeetCode 数据目录

    Returns:
        chunk 列表
    """
    if data_dir is None:
        data_dir = str(Path(__file__).resolve().parents[2] / "data" / "leetcode")

    base = Path(data_dir)
    if not base.exists():
        raise FileNotFoundError(f"LeetCode data directory not found: {data_dir}")

    # 查找 JSON 文件
    json_files = list(base.rglob("*.json"))
    if not json_files:
        raise FileNotFoundError(f"No JSON files found in {data_dir}")

    all_chunks = []
    seen_ids = set()

    for jf in json_files:
        with open(jf, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 支持两种格式: 直接数组 或 {"problems": [...]}
        if isinstance(data, list):
            problems = data
        elif isinstance(data, dict):
            problems = data.get("problems", data.get("questions", []))
        else:
            continue

        for prob in problems:
            pid = str(prob.get("problem_id", prob.get("id", prob.get("questionId", ""))))
            title = prob.get("title", prob.get("titleSlug", ""))
            if pid in seen_ids or not title:
                continue
            seen_ids.add(pid)

            # 构建可检索文本
            difficulty = prob.get("difficulty", "Unknown")
            topics = prob.get("topics", prob.get("topicTags", []))
            if isinstance(topics, list) and topics and isinstance(topics[0], dict):
                topics = [t.get("name", t.get("slug", str(t))) for t in topics]

            description = prob.get("description", prob.get("content", ""))
            solution = prob.get("solution", prob.get("editorial", ""))
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
            chunk_id = f"lc-{pid}"

            all_chunks.append({
                "id": chunk_id,
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

    print(f"Loaded {len(all_chunks)} problems from {len(json_files)} JSON files")
    return all_chunks


def ingest_all(data_dir: Optional[str] = None):
    """摄入全部知识数据到 Qdrant

    包括 CS fundamentals 和 LeetCode 题库。
    使用框架 rag pipeline 的 index_chunks() 写入向量。

    Args:
        data_dir: data/ 目录的父路径，默认从项目根推断
    """
    config = get_config()
    embedder = get_text_embedder()
    print(f"Using embedder: {type(embedder).__name__}, dim={embedder.dimension}")

    # 延迟导入 Qdrant（允许在无 Qdrant 环境下仍可 import 此模块）
    from hello_agents.storage.qdrant_store import QdrantVectorStore

    store = QdrantVectorStore()

    # --- CS Fundamentals ---
    print("\n" + "=" * 60)
    print("Ingesting: CS Fundamentals")
    print("=" * 60)
    cs_chunks = load_cs_fundamentals(data_dir)
    if cs_chunks:
        index_chunks(
            store=store,
            chunks=cs_chunks,
            rag_namespace=config.rag.collection_cs,
        )
        stats = store.get_collection_stats(config.rag.collection_cs)
        print(f"CS collection stats: {stats}")

    # --- LeetCode ---
    print("\n" + "=" * 60)
    print("Ingesting: LeetCode Problems")
    print("=" * 60)
    lc_chunks = load_leetcode(data_dir)
    if lc_chunks:
        index_chunks(
            store=store,
            chunks=lc_chunks,
            rag_namespace=config.rag.collection_leetcode,
        )
        stats = store.get_collection_stats(config.rag.collection_leetcode)
        print(f"LeetCode collection stats: {stats}")

    print("\n" + "=" * 60)
    print("Ingestion complete!")
    print(f"  CS Fundamentals: {len(cs_chunks)} chunks")
    print(f"  LeetCode:        {len(lc_chunks)} chunks")
    print("=" * 60)


if __name__ == "__main__":
    ingest_all()
