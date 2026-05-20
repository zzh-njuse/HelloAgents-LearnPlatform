"""LearningSession — 会话管理器 + CLI 交互

管理学习会话生命周期:
  IDLE → SELECTING → LEARNING → ASSESSING → IDLE

职责:
  - 加载 chapters.json
  - 展示学习进度（对比 UserModel）
  - 管理章节选择
  - CLI 交互循环（拦截命令，转发学习对话）
"""

import io
import json
import logging
import sys
import contextlib
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime

from hello_agents.core.llm import HelloAgentsLLM
from academic_companion.agents.learning_agent import LearningAgent
from academic_companion.memory_extensions.user_model import UserModel

# 抑制框架内部 INFO 日志，只显示 WARNING 及以上
for _name in ("sentence_transformers", "hello_agents.memory", "hello_agents.storage",
              "hello_agents.rag", "httpx", "httpcore", "urllib3", "openai"):
    logging.getLogger(_name).setLevel(logging.WARNING)

import os as _os
_os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
_os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
_os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
_os.environ.setdefault("TQDM_DISABLE", "1")


HELP_TEXT = """可用命令:
  /select <mode>   — 选择学习模式 (cs_fundamentals | algorithm)
  /progress        — 查看学习进度
  /learn <id>      — 选择学习的章节
  /status          — 查看当前章节状态
  /stop            — 停止当前学习（触发评测 — 即将实现）
  /switch <mode>   — 切换模式
  /help            — 显示此帮助
  /quit            — 退出
"""


class LearningSession:
    """学习会话管理器

    使用示例:
        >>> session = LearningSession()
        >>> session.start()
    """

    def __init__(self):
        self.state = "IDLE"  # IDLE → SELECTING → LEARNING
        self.mode: str = ""  # "cs_fundamentals" | "algorithm"
        self.chapters: Dict[str, list] = {}  # 按 mode 分组
        self.selected_chapter: Optional[Dict] = None
        self.agent: Optional[LearningAgent] = None
        self.user_model = UserModel(filepath="memory/user_model.json")

        # 防止系统代理干扰本地 Qdrant 连接
        # httpx 会走系统 HTTP_PROXY 代理，而 Docker Desktop 的 localhost 不能走代理
        _os.environ["NO_PROXY"] = "localhost,127.0.0.1,.local"

        self._load_chapters()

    def _load_chapters(self):
        """加载 chapters.json"""
        chapters_path = Path("data/chapters.json")
        if not chapters_path.exists():
            print("[WARNING] data/chapters.json 不存在，请先运行 scripts/build_chapters.py")
            return

        with open(chapters_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.chapters = {
            "cs_fundamentals": data.get("cs_fundamentals", []),
            "algorithm": data.get("algorithm", []),
        }

    # ===================================================================
    # 命令：选择模式
    # ===================================================================

    def select_mode(self, mode: str):
        """选择学习模式"""
        if mode not in ("cs_fundamentals", "algorithm"):
            print(f"无效模式: {mode}。可选: cs_fundamentals | algorithm")
            return

        self.mode = mode
        self.state = "SELECTING"
        mode_label = "八股知识" if mode == "cs_fundamentals" else "算法专题"
        print(f"\n已选择模式: {mode_label}")

        # 初始化 Agent（首次选择模式时）
        if self.agent is None:
            print("正在初始化 LLM...")
            llm = HelloAgentsLLM()
            self.agent = LearningAgent("学习伙伴", llm)
            print("初始化完成")

        self.show_progress()

    # ===================================================================
    # 命令：查看进度
    # ===================================================================

    def show_progress(self):
        """展示学习进度"""
        if not self.mode:
            print("请先选择模式 /select <mode>")
            return

        chapters = self.chapters.get(self.mode, [])
        if not chapters:
            print("该模式暂无章节")
            return

        print(self.user_model.get_chapter_progress_summary(chapters, self.mode))

    # ===================================================================
    # 命令：选择章节
    # ===================================================================

    def select_chapter(self, chapter_id: str):
        """选择要学习的章节"""
        if self.state not in ("SELECTING", "LEARNING"):
            print(f"当前状态 {self.state} 不允许选择章节，请先 /select <mode>")
            return

        chapters = self.chapters.get(self.mode, [])
        matched = None
        for ch in chapters:
            if ch["id"] == chapter_id or chapter_id in ch["id"]:
                matched = ch
                break

        if matched is None:
            print(f"未找到章节: {chapter_id}")
            print("可用章节:")
            for ch in chapters:
                print(f"  {ch['id']:30s} {ch['name_zh']}")
            return

        self.selected_chapter = matched
        self.agent.chapter_context = matched
        self.state = "LEARNING"

        ch = matched
        mode_label = "八股" if ch["mode"] == "cs_fundamentals" else "算法"
        print(f"\n{'='*60}")
        print(f"开始学习: [{mode_label}] {ch['name_zh']}")
        print(f"  {ch.get('description', '')}")
        if "file_count" in ch:
            print(f"  包含 {ch['file_count']} 篇文章")
        if ch.get("article_titles"):
            for t in ch["article_titles"][:5]:
                print(f"    - {t}")
            if len(ch.get("article_titles", [])) > 5:
                print(f"    ... 还有 {len(ch['article_titles']) - 5} 篇")
        if "problem_count" in ch:
            diff = ch.get("difficulty_distribution", {})
            print(f"  题目数: {ch['problem_count']}  "
                  f"(E:{diff.get('Easy',0)} M:{diff.get('Medium',0)} H:{diff.get('Hard',0)})")
        print(f"\n输入 /stop 结束学习进入评测，/progress 查看进度，/help 查看命令")
        print(f"{'='*60}\n")

    # ===================================================================
    # 命令：停止学习 → 进入评测
    # ===================================================================

    def stop_learning(self):
        """停止当前学习，进入评测"""
        if self.state != "LEARNING":
            print("当前没有进行中的学习")
            return

        ch = self.selected_chapter
        self.state = "ASSESSING"

        if ch["mode"] == "cs_fundamentals":
            self._assess_cs(ch)
        else:
            self._assess_algorithm(ch)

        # 回到章节选择
        self.selected_chapter = None
        if self.agent:
            self.agent.chapter_context = None
        self.state = "SELECTING"

    def _assess_cs(self, chapter: dict):
        """八股评测：LLM 生成题目 → 用户作答 → LLM 评分"""
        from .assessor import CSAssessor

        print(f"\n{'='*60}")
        print(f"进入评测: {chapter['name_zh']}")
        print(f"{'='*60}")
        print("正在生成评测题目...")

        # 获取会话学习摘要
        session_ctx = ""
        if self.agent:
            try:
                wm = self.agent.memory_manager.memory_types.get("working")
                if wm:
                    session_ctx = wm.get_context_summary(max_length=800)
            except Exception:
                pass

        # 创建评测器（用低温度的专用 LLM）
        from hello_agents.core.llm import HelloAgentsLLM
        assessor_llm = HelloAgentsLLM(temperature=0.3)
        assessor = CSAssessor(assessor_llm)

        questions = assessor.generate_questions(
            chapter_name=chapter["name_zh"],
            description=chapter.get("description", ""),
            article_titles=chapter.get("article_titles", []),
            session_context=session_ctx,
        )

        if not questions:
            print("题目生成失败，评测跳过")
            return

        print(f"\n共 {len(questions)} 道题:\n")
        for i, q in enumerate(questions, 1):
            print(f"[{i}] {q.text}\n")

        # 逐题收答案
        for i, q in enumerate(questions, 1):
            print(f"--- 第{i}题 ---")
            try:
                answer = input("你的回答: ").strip()
            except (EOFError, KeyboardInterrupt):
                answer = ""
            q.user_answer = answer

        print(f"\n正在评分...")

        result = assessor.evaluate(
            chapter_name=chapter["name_zh"],
            questions=questions,
        )

        # 更新 UserModel
        self.user_model.update_chapter_progress(
            chapter_id=chapter["id"],
            name_zh=chapter["name_zh"],
            mode=chapter["mode"],
            mastery=result.total_score,
            articles=chapter.get("article_titles", []),
        )
        # 也更新 agent 侧的 UserModel（如果是同一实例）
        if self.agent:
            self.agent.user_model = self.user_model

        # 展示结果
        print(f"\n{'='*60}")
        print(f"评测完成: {chapter['name_zh']}")
        print(f"{'='*60}")
        for i, q in enumerate(result.questions, 1):
            bar = _score_bar(q.score)
            print(f"  [{i}] {bar} {q.score:.0f}分  {q.text[:50]}...")
        print(f"\n综合掌握度: {result.total_score:.0f}%")
        if result.weak_points:
            print(f"薄弱点: {', '.join(result.weak_points)}")
        if result.comment:
            print(f"评语: {result.comment}")
        print(f"{'='*60}")

    def _assess_algorithm(self, chapter: dict):
        """算法评测：匹配 LeetCode 题目 → 用户去 LeetCode 完成 → 回报结果"""
        from .assessor import AlgorithmAssessor

        print(f"\n{'='*60}")
        print(f"进入评测: {chapter['name_zh']}")
        print(f"{'='*60}")

        assessor = AlgorithmAssessor()
        problems = assessor.match_problems(
            topics=chapter.get("topics", []),
            count=3,
        )

        if not problems:
            print("未找到匹配的题目，评测跳过")
            return

        print(f"\n请在 LeetCode 上完成以下 {len(problems)} 道题:\n")
        for i, p in enumerate(problems, 1):
            print(f"  [{i}] [{p['difficulty']}] {p['title']}")
            print(f"      题号: {p['frontend_id']}")
            print(f"      链接: {p['url']}")
            print()

        print("完成后请回报通过情况 (y=通过 / n=未通过):\n")

        for i, p in enumerate(problems, 1):
            try:
                ans = input(f"  [{i}] {p['title']} — 通过了吗? (y/n): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            p["passed"] = ans in ("y", "yes", "通过", "是")

        result = assessor.evaluate(problems)

        # 更新 UserModel
        self.user_model.update_chapter_progress(
            chapter_id=chapter["id"],
            name_zh=chapter["name_zh"],
            mode=chapter["mode"],
            mastery=result.total_score,
        )
        if self.agent:
            self.agent.user_model = self.user_model

        print(f"\n{'='*60}")
        print(f"评测完成: {chapter['name_zh']}")
        print(f"{'='*60}")
        passed = sum(1 for p in problems if p.get("passed"))
        print(f"  通过: {passed}/{len(problems)} → 掌握度: {result.total_score:.0f}%")
        print(f"{'='*60}")

    # ===================================================================
    # CLI 交互循环
    # ===================================================================

    def start(self):
        """启动 CLI 交互循环"""
        print("\n" + "=" * 60)
        print("Academic AI Companion — 学习模式")
        print("=" * 60)
        print("输入 /help 查看命令")
        print()

        while True:
            try:
                if self.state == "LEARNING" and self.selected_chapter:
                    ch_name = self.selected_chapter["name_zh"]
                    prompt = f"\n[{ch_name}] > "
                else:
                    prompt = "\n> "

                user_input = input(prompt).strip()
                if not user_input:
                    continue

            except (EOFError, KeyboardInterrupt):
                print("\n再见！")
                break

            # 命令分发
            if user_input.startswith("/"):
                parts = user_input.split(maxsplit=1)
                cmd = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else ""

                if cmd == "/quit" or cmd == "/exit":
                    print("再见！")
                    break
                elif cmd == "/help":
                    print(HELP_TEXT)
                elif cmd == "/select":
                    self.select_mode(arg)
                elif cmd == "/progress":
                    self.show_progress()
                elif cmd == "/learn":
                    if not arg:
                        print("用法: /learn <chapter_id>")
                    else:
                        self.select_chapter(arg)
                elif cmd == "/stop":
                    self.stop_learning()
                elif cmd == "/status":
                    self._show_status()
                elif cmd == "/switch":
                    self.select_mode(arg)
                else:
                    print(f"未知命令: {cmd}。输入 /help 查看可用命令")
            else:
                # 转发到 Agent
                if self.state != "LEARNING":
                    print("请先选择章节 /learn <chapter_id>")
                    self.show_progress()
                    continue

                if not self.agent:
                    print("[ERROR] Agent 未初始化")
                    continue

                print("思考中...", end="\r")
                try:
                    # 捕获内部日志（ReAct 步骤等），只向用户展示最终回答
                    debug_buf = io.StringIO()
                    with contextlib.redirect_stdout(debug_buf), \
                         contextlib.redirect_stderr(debug_buf):
                        result = self.agent.run(user_input)

                    # 写入 debug 日志
                    debug_output = debug_buf.getvalue()
                    if debug_output.strip():
                        debug_log = Path("memory") / "debug" / "agent_trace.log"
                        debug_log.parent.mkdir(parents=True, exist_ok=True)
                        with open(debug_log, "a", encoding="utf-8") as f:
                            f.write(f"\n{'='*40} {datetime.now().isoformat()} {'='*40}\n")
                            f.write(debug_output)
                            f.write(f"\n--- RESULT ---\n{result}\n")

                    print(f"\r{' '*20}\r{result}")
                except Exception as e:
                    print(f"\r[ERROR] 学习对话失败: {e}")

    def _show_status(self):
        """显示当前状态"""
        print(f"状态: {self.state}")
        print(f"模式: {self.mode or '未选择'}")
        if self.selected_chapter:
            ch = self.selected_chapter
            mastery = self.user_model.get_chapter_mastery(ch["id"])
            print(f"章节: {ch['name_zh']} (掌握度: {mastery:.0f}%)")
        else:
            print("章节: 未选择")
        if self.agent:
            print(self.agent.get_learning_status())


def _score_bar(score: float, width: int = 8) -> str:
    """分数可视化条"""
    if score <= 0:
        return "[" + "·" * width + "]"
    filled = max(1, int(score / 100 * width))
    return "[" + "█" * filled + "·" * (width - filled) + "]"
