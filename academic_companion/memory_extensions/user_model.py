"""UserModel — 用户知识图谱

整合框架 4 种 Memory 机制:
1. HistoryManager (短期) — 当前对话上下文
2. SessionStore (长期) — 跨天学习进度持久化
3. Smart Summary — 压缩长对话保留关键信息
4. 知识状态图 — 主题掌握度 + 薄弱点追踪 + 间隔重复

持久化到 memory/user_model.json
"""

import json
import os
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from pathlib import Path


@dataclass
class TopicState:
    """单个知识主题的状态"""
    mastery: float = 0.0          # 掌握度 0-100
    last_reviewed: str = ""       # 最后复习日期 ISO
    review_count: int = 0         # 复习次数
    weak_points: List[str] = field(default_factory=list)  # 薄弱点列表
    notes: str = ""               # 学习笔记


@dataclass
class ChapterProgress:
    """单个章节的学习进度"""
    chapter_id: str = ""
    name_zh: str = ""
    mode: str = ""                # "cs_fundamentals" | "algorithm"
    mastery: float = 0.0          # 综合掌握度 0-100
    articles_covered: List[str] = field(default_factory=list)  # 已覆盖的文章/子主题
    study_count: int = 0          # 学习次数
    last_studied: str = ""        # 最后学习日期 ISO


class UserModel:
    """用户知识状态模型

    追踪所有学习过的主题和章节的掌握度和薄弱点。
    提供间隔重复复习建议。

    使用示例:
        >>> model = UserModel()
        >>> model.update_mastery("TCP三次握手", 75, ["为什么不是两次?"])
        >>> model.get_weak_topics(3)
        [("TCP三次握手", 75), ...]
        >>> model.update_chapter_progress("mysql-index", "索引篇", "cs_fundamentals",
        ...     articles=["索引常见面试题"], mastery=60)
    """

    def __init__(self, filepath: str = "memory/user_model.json"):
        self.filepath = Path(filepath)
        self.topics: Dict[str, TopicState] = {}
        self.chapters: Dict[str, ChapterProgress] = {}
        self._load()

    # --- 核心操作 ---

    def update_mastery(
        self,
        topic: str,
        score: float,
        weak_points: Optional[List[str]] = None,
        notes: str = "",
    ):
        """更新某主题的掌握度

        Args:
            topic: 主题名
            score: 新的掌握度评分 0-100
            weak_points: 本次发现的薄弱点
            notes: 学习笔记
        """
        score = max(0.0, min(100.0, float(score)))

        if topic not in self.topics:
            self.topics[topic] = TopicState()

        state = self.topics[topic]
        # 加权平均：70% 历史 + 30% 本次（避免单次大幅波动）
        if state.review_count > 0:
            state.mastery = round(state.mastery * 0.7 + score * 0.3, 1)
        else:
            state.mastery = score

        state.last_reviewed = datetime.now().isoformat()
        state.review_count += 1

        if weak_points:
            state.weak_points = list(set(state.weak_points + weak_points))

        if notes:
            state.notes = notes

        self._save()

    def get_mastery(self, topic: str) -> float:
        """获取某主题掌握度，未学过返回 0"""
        state = self.topics.get(topic)
        return state.mastery if state else 0.0

    def get_weak_topics(self, n: int = 5) -> List[Tuple[str, float]]:
        """获取掌握度最低的 n 个主题

        Returns:
            [(topic, mastery), ...] 按掌握度升序
        """
        weak = [(t, s.mastery) for t, s in self.topics.items() if s.mastery < 70]
        weak.sort(key=lambda x: x[1])
        return weak[:n]

    def get_strong_topics(self, n: int = 5) -> List[Tuple[str, float]]:
        """获取掌握度最高的 n 个主题"""
        strong = [(t, s.mastery) for t, s in self.topics.items()]
        strong.sort(key=lambda x: -x[1])
        return strong[:n]

    def get_review_schedule(
        self, interval_days: int = 3, n: int = 5
    ) -> List[Tuple[str, float]]:
        """获取本周应复习的主题（间隔重复）

        条件: 掌握度 < 80 且距上次复习超过 interval_days 天

        Returns:
            [(topic, mastery), ...]
        """
        today = date.today()
        due = []
        for topic, state in self.topics.items():
            if state.mastery >= 80:
                continue
            if state.last_reviewed:
                last = datetime.fromisoformat(state.last_reviewed).date()
                if (today - last).days < interval_days:
                    continue
            due.append((topic, state.mastery))
        due.sort(key=lambda x: x[1])  # 最不会的排最前
        return due[:n]

    def get_all_topics(self) -> Dict[str, float]:
        """获取全部主题 -> 掌握度映射"""
        return {t: s.mastery for t, s in self.topics.items()}

    def get_summary(self) -> str:
        """生成用户学习状态摘要（注入到 Agent system prompt）"""
        parts = []
        # 章节进度
        if self.chapters:
            total_ch = len(self.chapters)
            studied = sum(1 for c in self.chapters.values() if c.study_count > 0)
            parts.append(f"已学习 {studied}/{total_ch} 个章节")

        if not self.topics and not self.chapters:
            return "（尚未学习任何主题）"

        if self.topics:
            total = len(self.topics)
            avg = sum(s.mastery for s in self.topics.values()) / total
            weak = self.get_weak_topics(3)
            strong = self.get_strong_topics(3)
            due = self.get_review_schedule(3)

            parts.append(f"已学习 {total} 个主题，平均掌握度 {avg:.0f}%")
            if strong:
                parts.append("掌握较好的: " + ", ".join(f"{t}({m:.0f}%)" for t, m in strong))
            if weak:
                parts.append("需要加强的: " + ", ".join(f"{t}({m:.0f}%)" for t, m in weak))
            if due:
                parts.append("建议复习: " + ", ".join(t for t, _ in due))

        return "\n".join(parts)

    # --- 章节进度 ---

    def update_chapter_progress(
        self,
        chapter_id: str,
        name_zh: str,
        mode: str,
        *,
        mastery: float = 0.0,
        articles: Optional[List[str]] = None,
    ):
        """更新某章节的学习进度

        Args:
            chapter_id: 章节 ID (如 "mysql-index")
            name_zh: 中文章节名
            mode: "cs_fundamentals" | "algorithm"
            mastery: 最新掌握度评分 0-100
            articles: 本次覆盖的文章/子主题
        """
        if chapter_id not in self.chapters:
            self.chapters[chapter_id] = ChapterProgress(
                chapter_id=chapter_id,
                name_zh=name_zh,
                mode=mode,
            )

        cp = self.chapters[chapter_id]
        if cp.study_count > 0:
            cp.mastery = round(cp.mastery * 0.6 + mastery * 0.4, 1)
        else:
            cp.mastery = mastery

        if articles:
            for a in articles:
                if a not in cp.articles_covered:
                    cp.articles_covered.append(a)

        cp.study_count += 1
        cp.last_studied = datetime.now().isoformat()
        self._save()

    def get_chapter_mastery(self, chapter_id: str) -> float:
        """获取某章节掌握度，未学过返回 0"""
        cp = self.chapters.get(chapter_id)
        return cp.mastery if cp else 0.0

    def get_chapters_by_mode(self, mode: str) -> Dict[str, ChapterProgress]:
        """获取某模式下所有已学章节"""
        return {
            cid: cp for cid, cp in self.chapters.items()
            if cp.mode == mode
        }

    def get_chapter_progress_summary(self, all_chapters: list[dict], mode: str) -> str:
        """对比全部章节列表，输出已学/未学/掌握度

        Args:
            all_chapters: 从 chapters.json 加载的某模式全部章节
            mode: "cs_fundamentals" | "algorithm"

        Returns:
            格式化的进度字符串，供 CLI 展示
        """
        subject_chapters = [c for c in all_chapters if c["mode"] == mode]
        if not subject_chapters:
            return "该模式暂无章节"

        mode_label = "八股知识" if mode == "cs_fundamentals" else "算法专题"
        lines = [f"\n=== {mode_label} 学习进度 ==="]

        # 按 subject 分组
        by_subject: Dict[str, list] = {}
        for ch in subject_chapters:
            subj = ch.get("subject_zh", ch["subject"])
            by_subject.setdefault(subj, []).append(ch)

        for subj, chapters in by_subject.items():
            studied = 0
            total = len(chapters)
            lines.append(f"\n  [{subj}]")
            for ch in chapters:
                cid = ch["id"]
                cp = self.chapters.get(cid)
                if cp and cp.study_count > 0:
                    studied += 1
                    bar = _mastery_bar(cp.mastery)
                    lines.append(f"    {bar} {ch['name_zh']:12s} {cp.mastery:5.0f}%  "
                                 f"({len(cp.articles_covered)}/{ch['file_count']} 篇)")
                else:
                    lines.append(f"    [      ] {ch['name_zh']:12s}  未开始")
            lines.append(f"    --- {studied}/{total} 章已开始 ---")

        return "\n".join(lines)

    # --- 持久化 ---

    def _save(self):
        """保存到 JSON 文件（原子写入）"""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "updated_at": datetime.now().isoformat(),
            "topics": {
                t: {
                    "mastery": s.mastery,
                    "last_reviewed": s.last_reviewed,
                    "review_count": s.review_count,
                    "weak_points": s.weak_points,
                    "notes": s.notes,
                }
                for t, s in self.topics.items()
            },
            "chapters": {
                cid: {
                    "chapter_id": cp.chapter_id,
                    "name_zh": cp.name_zh,
                    "mode": cp.mode,
                    "mastery": cp.mastery,
                    "articles_covered": cp.articles_covered,
                    "study_count": cp.study_count,
                    "last_studied": cp.last_studied,
                }
                for cid, cp in self.chapters.items()
            },
        }
        # 原子写入
        tmp = self.filepath.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(self.filepath)

    def _load(self):
        """从 JSON 文件加载"""
        if not self.filepath.exists():
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            for topic, s in data.get("topics", {}).items():
                self.topics[topic] = TopicState(
                    mastery=s.get("mastery", 0),
                    last_reviewed=s.get("last_reviewed", ""),
                    review_count=s.get("review_count", 0),
                    weak_points=s.get("weak_points", []),
                    notes=s.get("notes", ""),
                )
            for cid, c in data.get("chapters", {}).items():
                self.chapters[cid] = ChapterProgress(
                    chapter_id=c.get("chapter_id", cid),
                    name_zh=c.get("name_zh", ""),
                    mode=c.get("mode", ""),
                    mastery=c.get("mastery", 0),
                    articles_covered=c.get("articles_covered", []),
                    study_count=c.get("study_count", 0),
                    last_studied=c.get("last_studied", ""),
                )
        except (json.JSONDecodeError, KeyError):
            pass

    def reset(self):
        """重置全部知识状态"""
        self.topics.clear()
        self.chapters.clear()
        if self.filepath.exists():
            self.filepath.unlink()


def _mastery_bar(mastery: float, width: int = 6) -> str:
    """掌握度可视化条，如 [███░░░]"""
    if mastery <= 0:
        return "[" + "░" * width + "]"
    filled = max(1, int(mastery / 100 * width))
    return "[" + "█" * filled + "░" * (width - filled) + "]"
