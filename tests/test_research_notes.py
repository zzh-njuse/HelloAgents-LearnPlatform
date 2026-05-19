"""ResearchNotes 单元测试"""

import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from dotenv import load_dotenv

load_dotenv()


class TestPaperEntry:
    """PaperEntry 数据模型测试"""

    def test_create_entry(self):
        from academic_companion.memory_extensions.research_notes import PaperEntry
        e = PaperEntry(
            arxiv_id="2501.01234",
            title="Test Paper",
            authors=["Alice", "Bob"],
            year=2025,
        )
        assert e.arxiv_id == "2501.01234"
        assert len(e.authors) == 2

    def test_make_key_priority(self):
        """ID 提取优先级: arxiv_id > doi > s2_id"""
        from academic_companion.memory_extensions.research_notes import PaperEntry
        e = PaperEntry(arxiv_id="123", doi="456", s2_id="789")
        assert e._make_key() == "123"

        e2 = PaperEntry(doi="456", s2_id="789")
        assert e2._make_key() == "456"

    def test_to_text(self):
        """序列化为可向量化文本"""
        from academic_companion.memory_extensions.research_notes import PaperEntry
        e = PaperEntry(title="Test", abstract="An abstract.", tags=["tag1"])
        text = e.to_text()
        assert "Test" in text
        assert "An abstract" in text
        assert "tag1" in text

    def test_to_dict_and_from_dict(self):
        """序列化往返"""
        from academic_companion.memory_extensions.research_notes import PaperEntry
        e = PaperEntry(
            arxiv_id="123",
            title="Test",
            authors=["A"],
            my_take={"rating": 4, "strengths": ["good"]},
        )
        d = e.to_dict()
        e2 = PaperEntry.from_dict(d)
        assert e2.arxiv_id == "123"
        assert e2.my_take["rating"] == 4


class TestResearchNotes:
    """ResearchNotes 核心功能测试"""

    @pytest.fixture
    def notes(self):
        from academic_companion.memory_extensions.research_notes import ResearchNotes
        path = "memory/research/pytest_notes.json"
        rn = ResearchNotes(path)
        rn.reset()
        yield rn
        rn.reset()

    def test_add_and_get(self, notes):
        """添加后精确查找"""
        from academic_companion.memory_extensions.research_notes import PaperEntry
        e = PaperEntry(arxiv_id="test-001", title="Test")
        notes.add_entry(e)
        found = notes.get_by_id("test-001")
        assert found is not None
        assert found.title == "Test"

    def test_dedup_by_arxiv_id(self, notes):
        """arXiv ID 去重"""
        from academic_companion.memory_extensions.research_notes import PaperEntry
        e = PaperEntry(arxiv_id="test-001", title="Test")
        notes.add_entry(e)

        papers = [
            {"arxiv_id": "test-001", "title": "Existing"},
            {"arxiv_id": "test-002", "title": "New"},
        ]
        new, seen = notes.dedup_candidates(papers)
        assert len(new) == 1
        assert len(seen) == 1
        assert new[0]["arxiv_id"] == "test-002"
        assert seen[0]["_seen"] is True

    def test_dedup_by_doi(self, notes):
        """DOI 去重"""
        from academic_companion.memory_extensions.research_notes import PaperEntry
        e = PaperEntry(doi="10.1234/test", title="Test")
        notes.add_entry(e)

        papers = [{"doi": "10.1234/test", "title": "Test"}]
        new, seen = notes.dedup_candidates(papers)
        assert len(new) == 0
        assert len(seen) == 1

    def test_list_by_status(self, notes):
        """状态筛选"""
        from academic_companion.memory_extensions.research_notes import PaperEntry
        notes.add_entry(PaperEntry(arxiv_id="1", status="candidate"))
        notes.add_entry(PaperEntry(arxiv_id="2", status="analyzed"))
        notes.add_entry(PaperEntry(arxiv_id="3", status="analyzed"))

        assert len(notes.list_by_status("candidate")) == 1
        assert len(notes.list_by_status("analyzed")) == 2
        assert len(notes.list_by_status("synthesized")) == 0

    def test_list_by_tag(self, notes):
        """标签筛选"""
        from academic_companion.memory_extensions.research_notes import PaperEntry
        notes.add_entry(PaperEntry(arxiv_id="1", tags=["APR", "LLM"]))
        notes.add_entry(PaperEntry(arxiv_id="2", tags=["APR", "DL"]))

        assert len(notes.list_by_tag("APR")) == 2
        assert len(notes.list_by_tag("LLM")) == 1
        assert len(notes.list_by_tag("NLP")) == 0

    def test_get_recent(self, notes):
        """最近条目"""
        from academic_companion.memory_extensions.research_notes import PaperEntry
        notes.add_entry(PaperEntry(arxiv_id="1", title="Paper 1"))
        notes.add_entry(PaperEntry(arxiv_id="2", title="Paper 2"))
        recent = notes.get_recent(5)
        assert len(recent) == 2

    def test_persistence(self, notes):
        """跨实例持久化"""
        from academic_companion.memory_extensions.research_notes import PaperEntry, ResearchNotes
        notes.add_entry(PaperEntry(arxiv_id="test-persist", title="Persist Test"))

        # 新建实例加载
        notes2 = ResearchNotes(str(notes.filepath))
        found = notes2.get_by_id("test-persist")
        assert found is not None
        assert found.title == "Persist Test"

    def test_merge_on_duplicate_key(self, notes):
        """同一 ID 再次 add 时合并而非重复"""
        from academic_companion.memory_extensions.research_notes import PaperEntry
        e1 = PaperEntry(arxiv_id="merge-test", title="Original", citations=10)
        notes.add_entry(e1)

        e2 = PaperEntry(arxiv_id="merge-test", title="Updated", citations=20, tags=["new"])
        notes.add_entry(e2)

        found = notes.get_by_id("merge-test")
        assert found is not None
        assert found.title == "Updated"
        assert found.citations == 20
        assert "new" in found.tags
        # 只有一个条目
        assert len(notes.entries) == 1

    def test_get_summary(self, notes):
        """生成摘要"""
        from academic_companion.memory_extensions.research_notes import PaperEntry
        summary = notes.get_summary()
        assert "尚未" in summary  # 空时提示

        notes.add_entry(PaperEntry(arxiv_id="1", title="Paper"))
        summary = notes.get_summary()
        assert "1 条" in summary
