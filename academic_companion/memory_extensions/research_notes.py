"""ResearchNotes — 研究笔记管理器

结构化文献笔记的跨会话持久化 + ID 去重 + Qdrant 语义检索。

参考 user_model.py 的 JSON 原子写入模式。

数据模型:
  PaperEntry — 单篇论文的结构化条目
    - 唯一标识: arxiv_id / doi / s2_id (用于去重)
    - 状态流转: candidate → filtered → analyzed → synthesized
    - 分析笔记: one_liner / contributions / method_summary / results_summary / my_take

检索策略:
  1. 精确匹配 (去重): get_by_id() — O(1) 哈希查找
  2. 语义检索: search() — Qdrant 向量搜索
  3. 结构化过滤: list_by_tag() / list_by_status()
"""

import json
import os
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path


@dataclass
class PaperEntry:
    """单篇论文的结构化条目"""

    # 唯一标识 (按优先级用于去重)
    arxiv_id: Optional[str] = None
    doi: Optional[str] = None
    s2_id: Optional[str] = None

    # 来源标识
    source: str = ""  # "arxiv" | "semantic_scholar"

    # 元数据
    title: str = ""
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    venue: str = ""
    citations: int = 0
    abstract: str = ""

    # 分析状态
    status: str = "candidate"  # candidate | filtered | analyzed | synthesized
    relevance_score: float = 0.0
    tags: List[str] = field(default_factory=list)

    # 用户笔记 (分析后逐步填充)
    one_liner: str = ""
    contributions: List[str] = field(default_factory=list)
    method_summary: str = ""
    results_summary: str = ""
    my_take: Dict[str, Any] = field(default_factory=dict)

    # 时间戳
    first_seen_at: str = ""   # ISO timestamp
    last_updated_at: str = ""
    analyzed_at: Optional[str] = None

    def to_text(self) -> str:
        """序列化为可向量化的文本 (用于 Qdrant embedding)"""
        parts = [self.title]
        if self.authors:
            parts.append("Authors: " + ", ".join(self.authors))
        if self.abstract:
            parts.append(self.abstract[:500])
        if self.one_liner:
            parts.append(self.one_liner)
        if self.tags:
            parts.append("Tags: " + ", ".join(self.tags))
        if self.venue:
            parts.append(f"Venue: {self.venue}")
        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "arxiv_id": self.arxiv_id,
            "doi": self.doi,
            "s2_id": self.s2_id,
            "source": self.source,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "venue": self.venue,
            "citations": self.citations,
            "abstract": self.abstract,
            "status": self.status,
            "relevance_score": self.relevance_score,
            "tags": self.tags,
            "one_liner": self.one_liner,
            "contributions": self.contributions,
            "method_summary": self.method_summary,
            "results_summary": self.results_summary,
            "my_take": self.my_take,
            "first_seen_at": self.first_seen_at,
            "last_updated_at": self.last_updated_at,
            "analyzed_at": self.analyzed_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PaperEntry":
        return cls(
            arxiv_id=d.get("arxiv_id"),
            doi=d.get("doi"),
            s2_id=d.get("s2_id"),
            source=d.get("source", ""),
            title=d.get("title", ""),
            authors=d.get("authors", []),
            year=d.get("year"),
            venue=d.get("venue", ""),
            citations=d.get("citations", 0),
            abstract=d.get("abstract", ""),
            status=d.get("status", "candidate"),
            relevance_score=d.get("relevance_score", 0.0),
            tags=d.get("tags", []),
            one_liner=d.get("one_liner", ""),
            contributions=d.get("contributions", []),
            method_summary=d.get("method_summary", ""),
            results_summary=d.get("results_summary", ""),
            my_take=d.get("my_take", {}),
            first_seen_at=d.get("first_seen_at", ""),
            last_updated_at=d.get("last_updated_at", ""),
            analyzed_at=d.get("analyzed_at"),
        )

    def _make_key(self) -> Optional[str]:
        """生成用于去重的唯一键，按优先级返回第一个非空 ID"""
        for val in [self.arxiv_id, self.doi, self.s2_id]:
            if val:
                return val
        return None


class ResearchNotes:
    """研究笔记管理器

    跨会话持久化 + 语义检索 + ID 去重。
    """

    def __init__(self, filepath: str = "memory/research/notes.json"):
        self.filepath = Path(filepath)
        self.entries: Dict[str, PaperEntry] = {}
        self._load()

    # === 核心操作 ===

    def dedup_candidates(
        self, papers: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """ID 去重，返回 (new_papers, seen_papers)。

        seen_papers 中每条附加上次记录的 status / relevance_score / first_seen_at。
        """
        new_papers = []
        seen_papers = []

        for paper in papers:
            paper_id = self._extract_id(paper)
            if paper_id and paper_id in self.entries:
                existing = self.entries[paper_id]
                paper["_seen"] = True
                paper["_previous_status"] = existing.status
                paper["_previous_score"] = existing.relevance_score
                paper["_first_seen_at"] = existing.first_seen_at
                paper["_previous_one_liner"] = existing.one_liner
                seen_papers.append(paper)
            else:
                paper["_seen"] = False
                new_papers.append(paper)

        return new_papers, seen_papers

    def add_entry(self, entry: PaperEntry):
        """添加/更新笔记。以 ID 为键，自动合并已有条目。

        已存在时：更新元数据字段但不覆盖用户手动填写的分析笔记。
        """
        now = datetime.now().isoformat()
        entry.last_updated_at = now

        key = entry._make_key()
        if not key:
            # 没有唯一 ID，用文件名形式的 key：title_hash
            key = f"unknown-{hash(entry.title) % 100000}"

        if key in self.entries:
            # 合并：保留已有的分析笔记
            existing = self.entries[key]
            # 更新元数据
            if entry.title:
                existing.title = entry.title
            if entry.authors:
                existing.authors = entry.authors
            if entry.year:
                existing.year = entry.year
            if entry.venue:
                existing.venue = entry.venue
            if entry.citations:
                existing.citations = entry.citations
            if entry.abstract:
                existing.abstract = entry.abstract
            if entry.tags:
                existing.tags = list(set(existing.tags + entry.tags))
            # 只有新状态比旧状态"进展"时才更新
            status_order = {"candidate": 0, "filtered": 1, "analyzed": 2, "synthesized": 3}
            if status_order.get(entry.status, 0) > status_order.get(existing.status, 0):
                existing.status = entry.status
            existing.last_updated_at = now
        else:
            if not entry.first_seen_at:
                entry.first_seen_at = now
            self.entries[key] = entry

        self._save()

        # 异步索引到 Qdrant (容错)
        try:
            self._index_to_qdrant(self.entries[key])
        except Exception:
            pass

    def get_by_id(self, paper_id: str) -> Optional[PaperEntry]:
        """通过 arxiv_id / doi / s2_id 精确查找。O(1) 哈希。"""
        return self.entries.get(paper_id)

    def search(self, query: str, top_k: int = 10) -> List[PaperEntry]:
        """语义搜索 (Qdrant 向量检索，降级为 JSON 关键词匹配)"""
        try:
            return self._search_qdrant(query, top_k)
        except Exception:
            return self._search_fallback(query, top_k)

    def list_by_tag(self, tag: str) -> List[PaperEntry]:
        """按标签筛选"""
        return [e for e in self.entries.values() if tag in e.tags]

    def list_by_status(self, status: str) -> List[PaperEntry]:
        """按状态筛选"""
        return [e for e in self.entries.values() if e.status == status]

    def get_recent(self, n: int = 20) -> List[PaperEntry]:
        """按 last_updated_at 降序返回最近条目"""
        sorted_entries = sorted(
            self.entries.values(),
            key=lambda e: e.last_updated_at or e.first_seen_at or "",
            reverse=True,
        )
        return sorted_entries[:n]

    def get_summary(self) -> str:
        """生成笔记摘要 (注入 Agent system prompt)"""
        if not self.entries:
            return "（尚未记录任何论文笔记）"

        total = len(self.entries)
        by_status = {}
        for e in self.entries.values():
            by_status[e.status] = by_status.get(e.status, 0) + 1

        recent = self.get_recent(5)
        analyzed = self.list_by_status("analyzed")
        synthesized = self.list_by_status("synthesized")

        lines = [f"研究笔记: 共 {total} 条记录"]
        if by_status:
            lines.append(" | ".join(f"{s}: {c}" for s, c in by_status.items()))

        if analyzed:
            lines.append(f"\n已分析 {len(analyzed)} 篇:")
            for e in analyzed[:5]:
                score_str = f" 评分{e.relevance_score:.0f}" if e.relevance_score else ""
                lines.append(f"  - {e.title[:80]}{score_str}")

        if synthesized:
            lines.append(f"\n已完成综述 {len(synthesized)} 篇")

        if recent:
            lines.append("\n最近记录的论文:")
            for e in recent[:5]:
                lines.append(f"  - {e.title[:80]} [{e.status}]")

        return "\n".join(lines)

    def remove_entry(self, paper_id: str):
        """删除一条笔记"""
        self.entries.pop(paper_id, None)
        self._save()

    def reset(self):
        """清空全部笔记 (调试用)"""
        self.entries.clear()
        if self.filepath.exists():
            self.filepath.unlink()

    # === 内部: 持久化 ===

    def _save(self):
        """原子写入 JSON（Windows 兼容：PermissionError 时降级为直接写入）"""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "updated_at": datetime.now().isoformat(),
            "count": len(self.entries),
            "entries": [e.to_dict() for e in self.entries.values()],
        }
        tmp = self.filepath.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        try:
            tmp.replace(self.filepath)
        except PermissionError:
            # Windows 文件锁 — 降级为直接写入
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            try:
                tmp.unlink()
            except Exception:
                pass

    def _load(self):
        """从 JSON 恢复"""
        if not self.filepath.exists():
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            for d in data.get("entries", []):
                entry = PaperEntry.from_dict(d)
                key = entry._make_key()
                if key:
                    self.entries[key] = entry
        except (json.JSONDecodeError, KeyError):
            pass

    # === 内部: ID 提取 ===

    def _extract_id(self, paper: Dict[str, Any]) -> Optional[str]:
        """从论文 dict 中提取第一个可用的唯一 ID"""
        for id_field in ["arxiv_id", "arxivId", "paperId", "doi", "DOI", "s2_id"]:
            val = paper.get(id_field)
            if val:
                return str(val)
        # 尝试 externalIds
        ext = paper.get("externalIds", {})
        if isinstance(ext, dict):
            for id_field in ["ArXiv", "DOI", "paperId"]:
                val = ext.get(id_field)
                if val:
                    return str(val)
        return None

    # === 内部: Qdrant 向量索引 ===

    def _index_to_qdrant(self, entry: PaperEntry):
        """将笔记文本向量化存入 Qdrant"""
        try:
            from hello_agents.embedding import get_text_embedder
            from hello_agents.storage.qdrant_store import QdrantVectorStore
            from academic_companion.config import get_config

            config = get_config()
            embedder = get_text_embedder()
            store = QdrantVectorStore()

            text = entry.to_text()
            if not text.strip():
                return
            vector = embedder.embed([text])[0]
            key = entry._make_key()
            if not key:
                return

            store.add_vectors(
                vectors=[vector],
                metadatas=[{"content": text, "key": key}],
                ids=[key],
                collection_name=config.research_notes.qdrant_collection,
            )
        except Exception:
            pass

    def _search_qdrant(self, query: str, top_k: int) -> List[PaperEntry]:
        """Qdrant 语义检索"""
        from hello_agents.embedding import get_text_embedder
        from hello_agents.storage.qdrant_store import QdrantVectorStore
        from academic_companion.config import get_config

        config = get_config()
        embedder = get_text_embedder()
        store = QdrantVectorStore()

        query_vector = embedder.embed([query])[0]
        hits = store.search_similar(
            query_vector=query_vector,
            top_k=top_k,
            score_threshold=config.research_notes.similarity_threshold,
            collection_name=config.research_notes.qdrant_collection,
        )

        results = []
        for h in hits:
            key = h.get("metadata", {}).get("key", "")
            if key and key in self.entries:
                results.append(self.entries[key])

        return results

    def _search_fallback(self, query: str, top_k: int) -> List[PaperEntry]:
        """降级：JSON 关键词匹配"""
        query_lower = query.lower()
        results = []
        for entry in self.entries.values():
            score = 0
            if query_lower in entry.title.lower():
                score += 3
            if query_lower in entry.abstract.lower():
                score += 2
            if query_lower in entry.one_liner.lower():
                score += 2
            if any(query_lower in tag.lower() for tag in entry.tags):
                score += 1
            if score > 0:
                results.append((score, entry))

        results.sort(key=lambda x: -x[0])
        return [entry for _, entry in results[:top_k]]
