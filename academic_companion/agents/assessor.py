"""Assessor — 掌握度评测模块

两种评测模式:
1. CS 八股 → LLM 生成知识题，用户回答后 LLM 评分
2. 算法 → RAG 检索 LeetCode 题目，用户去 LeetCode 完成并反馈
"""

import json
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


# ====================================================================
# 数据结构
# ====================================================================

@dataclass
class AssessmentQuestion:
    """评测题目"""
    text: str
    reference_answer: str = ""  # 参考答案（LLM 评分用）
    user_answer: str = ""
    score: float = 0.0          # 0-100

@dataclass
class AssessmentResult:
    """评测结果"""
    mode: str                              # "cs_fundamentals" | "algorithm"
    chapter_id: str
    chapter_name: str
    total_score: float = 0.0               # 0-100
    questions: List[AssessmentQuestion] = field(default_factory=list)
    weak_points: List[str] = field(default_factory=list)
    comment: str = ""


# ====================================================================
# CS 八股评测器
# ====================================================================

CS_QUESTION_PROMPT = """你是技术面试考官。根据以下章节的学习内容，生成 3 道简答题来检验学生的掌握程度。

## 章节信息
- 章节名: {chapter_name}
- 描述: {description}
- 涉及主题: {article_titles}

## 本章学习摘要
{session_context}

## 要求
1. 题目应覆盖章节中的关键知识点，由浅入深
2. 题目应为开放式简答题（非选择题），考察理解而非记忆
3. 每道题应能用 2-5 句话回答
4. 同时给出每道题的参考答案要点

## 输出格式（严格 JSON）
```json
{{
  "questions": [
    {{
      "text": "题目内容",
      "reference": "参考答案要点"
    }}
  ]
}}
```

请生成题目:"""


CS_SCORE_PROMPT = """你是技术面试考官。根据学生的回答，评估其对章节内容的掌握程度。

## 章节: {chapter_name}

## 题目与学生回答
{qa_pairs}

## 评分标准
- 每个题目 0-100 分
- 概念理解 (40%): 核心概念是否准确
- 思路表达 (30%): 是否有逻辑地组织答案
- 深度与细节 (30%): 是否展示了深入理解

## 输出格式（严格 JSON）
```json
{{
  "scores": [85, 70, 90],
  "total_score": 82,
  "weak_points": ["对 xxx 的理解不够准确"],
  "comment": "总体评价..."
}}
```

请评分:"""


class CSAssessor:
    """CS 八股评测器 —— LLM 生成题目 + 评分"""

    def __init__(self, llm):
        self.llm = llm

    def generate_questions(
        self,
        chapter_name: str,
        description: str,
        article_titles: List[str],
        session_context: str = "",
    ) -> List[AssessmentQuestion]:
        """生成评测题目

        Args:
            chapter_name: 章节名
            description: 章节描述
            article_titles: 文章标题列表
            session_context: 会话学习摘要（来自 WorkingMemory）
        """
        prompt = CS_QUESTION_PROMPT.format(
            chapter_name=chapter_name,
            description=description or "（无描述）",
            article_titles=", ".join(article_titles[:10]),
            session_context=session_context or "（无会话摘要）",
        )

        try:
            response = self.llm.invoke(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=1500,
            )
            raw = response.content
            # 清理 JSON 包裹
            json_str = _extract_json(raw)
            data = json.loads(json_str)
            return [
                AssessmentQuestion(text=q["text"], reference_answer=q.get("reference", ""))
                for q in data.get("questions", [])
            ]
        except Exception as e:
            print(f"[WARNING] 题目生成失败: {e}")
            # fallback: 用文章标题生成简单题
            return _fallback_questions(article_titles)

    def evaluate(
        self,
        chapter_name: str,
        questions: List[AssessmentQuestion],
    ) -> AssessmentResult:
        """评估用户回答，返回掌握度

        Args:
            chapter_name: 章节名
            questions: 已作答的题目列表（含 user_answer）
        """
        qa_pairs = []
        for i, q in enumerate(questions, 1):
            qa_pairs.append(
                f"第{i}题: {q.text}\n"
                f"参考答案: {q.reference_answer}\n"
                f"学生回答: {q.user_answer or '(未回答)'}\n"
            )

        prompt = CS_SCORE_PROMPT.format(
            chapter_name=chapter_name,
            qa_pairs="\n---\n".join(qa_pairs),
        )

        try:
            response = self.llm.invoke(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=800,
            )
            raw = response.content
            json_str = _extract_json(raw)
            data = json.loads(json_str)

            scores = data.get("scores", [0] * len(questions))
            for i, s in enumerate(scores):
                if i < len(questions):
                    questions[i].score = s

            return AssessmentResult(
                mode="cs_fundamentals",
                chapter_id="",
                chapter_name=chapter_name,
                total_score=float(data.get("total_score", sum(scores) / max(len(scores), 1))),
                questions=questions,
                weak_points=data.get("weak_points", []),
                comment=data.get("comment", ""),
            )
        except Exception as e:
            print(f"[WARNING] LLM 评分失败: {e}")
            # fallback: 还是长度占位（比原来好一点，至少比 40+len/100 合理）
            return AssessmentResult(
                mode="cs_fundamentals",
                chapter_id="",
                chapter_name=chapter_name,
                total_score=50.0,
                questions=questions,
                comment=f"评分出错: {e}",
            )


def _extract_json(text: str) -> str:
    """从 LLM 输出中提取 JSON 块"""
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        return text[start:end].strip()
    if "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        return text[start:end].strip()
    # 直接找 { }
    if "{" in text:
        start = text.index("{")
        end = text.rindex("}") + 1
        return text[start:end]
    return text


def _fallback_questions(titles: List[str]) -> List[AssessmentQuestion]:
    """降级题目（无需 LLM）"""
    qs = []
    for title in titles[:3]:
        qs.append(AssessmentQuestion(
            text=f"请解释: {title}",
            reference_answer=f"需要准确解释 {title} 的核心概念和原理",
        ))
    if not qs:
        qs.append(AssessmentQuestion(
            text="请总结本章的核心知识点",
            reference_answer="应涵盖本章的主要概念和它们之间的关系",
        ))
    return qs


# ====================================================================
# 算法评测器
# ====================================================================

class AlgorithmAssessor:
    """算法评测器 —— LeetCode 题目匹配 + 用户反馈评分"""

    def __init__(self):
        self._problems_cache: Optional[List[Dict]] = None

    @property
    def problems(self) -> List[Dict]:
        """懒加载 LeetCode 题目数据"""
        if self._problems_cache is None:
            lc_path = Path("data/leetcode/leetcode-problems/merged_problems.json")
            if lc_path.exists():
                with open(lc_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._problems_cache = data.get("questions", [])
            else:
                self._problems_cache = []
        return self._problems_cache

    def match_problems(
        self,
        topics: List[str],
        count: int = 3,
        difficulty: Optional[str] = None,
    ) -> List[Dict]:
        """为算法章节检索匹配的 LeetCode 题目

        Args:
            topics: 章节涵盖的 LeetCode tag 列表
            count: 返回题目数
            difficulty: 限定难度 ("Easy"/"Medium"/"Hard")，None 则混合

        Returns:
            匹配的题目列表，含 title, frontend_id, difficulty, slug
        """
        candidates = []
        topic_set = set(topics)

        for p in self.problems:
            p_topics = set(p.get("topics", []))
            # 至少匹配一个 topic
            if p_topics & topic_set:
                diff = p.get("difficulty", "Unknown")
                if difficulty and diff != difficulty:
                    continue
                candidates.append(p)

        if not candidates:
            return []

        # 优先有 solution 的 + 随机采样避免总是一样的题
        with_solution = [p for p in candidates if p.get("solution")]
        without_solution = [p for p in candidates if not p.get("solution")]

        selected = []
        # 60% 来自有题解的
        n_solution = min(int(count * 0.6), len(with_solution))
        if n_solution > 0:
            selected.extend(random.sample(with_solution, n_solution))
        # 其余来自无题解但匹配的
        remaining = count - len(selected)
        if remaining > 0 and without_solution:
            n_extra = min(remaining, len(without_solution))
            selected.extend(random.sample(without_solution, n_extra))
        # 如果还不够
        if len(selected) < count:
            extras = [p for p in candidates if p not in selected]
            n_extra = min(count - len(selected), len(extras))
            if n_extra > 0:
                selected.extend(random.sample(extras, n_extra))

        result = []
        for p in selected[:count]:
            fid = p.get("frontend_id", p.get("problem_id", "?"))
            result.append({
                "title": p.get("title", ""),
                "frontend_id": fid,
                "difficulty": p.get("difficulty", "Unknown"),
                "slug": p.get("problem_slug", ""),
                "topics": p.get("topics", []),
                "url": f"https://leetcode.cn/problems/{p.get('problem_slug', '')}/",
            })

        return result

    def evaluate(self, results: List[Dict]) -> AssessmentResult:
        """根据用户反馈的通过情况评分

        Args:
            results: match_problems 的返回值 + "passed": True/False

        Returns:
            AssessmentResult with score = (passed / total) * 100
        """
        if not results:
            return AssessmentResult(
                mode="algorithm",
                chapter_id="",
                chapter_name="",
                total_score=0,
                comment="无题目可供评测",
            )

        passed = sum(1 for r in results if r.get("passed", False))
        total = len(results)
        score = (passed / total) * 100 if total > 0 else 0

        return AssessmentResult(
            mode="algorithm",
            chapter_id="",
            chapter_name="",
            total_score=score,
            comment=f"完成了 {total} 道题，通过 {passed} 道 ({score:.0f}%)",
        )
