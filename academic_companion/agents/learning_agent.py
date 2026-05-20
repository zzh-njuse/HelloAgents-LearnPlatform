"""LearningAgent — 智能学习伙伴 (GSSC 上下文管线版)

基于 ReActAgent，集成:
- RAG 知识检索 (RAGRetrievalTool)
- Skill 方法论加载 (SkillTool)
- MemoryManager — 3 种记忆类型（Working/Episodic/Semantic）
- UserModel — 掌握度追踪 + 章节进度 + 间隔重复
- ContextBuilder — GSSC 上下文组装 (Gather-Select-Structure-Compress)
- TodoWriteTool — 学习任务管理
"""

import os
from typing import Optional, Dict, Any
from datetime import datetime

from hello_agents.agents.react_agent import ReActAgent
from hello_agents.core.llm import HelloAgentsLLM
from hello_agents.core.config import Config
from hello_agents.core.message import Message
from hello_agents.tools.registry import ToolRegistry
from hello_agents.tools.builtin.todowrite_tool import TodoWriteTool
from hello_agents.tools.builtin.skill_tool import SkillTool
from hello_agents.skills.loader import SkillLoader
from hello_agents.memory import MemoryManager
from hello_agents.context.builder import ContextBuilder, ContextConfig, ContextPacket

from academic_companion.config import get_config, AcademicConfig
from academic_companion.rag_extensions.rag_tool import RAGRetrievalTool
from academic_companion.memory_extensions.user_model import UserModel


LEARNING_SYSTEM_PROMPT = """你是一个 AI 学习伙伴，帮助用户准备技术面试和学术研究。你的能力包括：

1. **知识检索**: 从 CS 八股知识库和 LeetCode 题库中检索相关概念和题解
2. **方法论指导**: 加载面试备考方法论和算法解题模式指导
3. **自适应教学**: 根据用户的学习进度和薄弱点调整讲解深度
4. **学习追踪**: 记录每次学习的主题、掌握度和薄弱点

## 教学原则

- 使用 **四步教学法**: 概念定义 → 工作原理 → 实例演示 → 练习题
- 发现用户的薄弱点后，主动追问相关概念
- 用通俗的类比解释复杂概念
- 对算法题，先讲思路再写代码，最后分析复杂度

## 工作流程

1. 用户提问后，先用 **RAGRetrieval** 检索知识库
2. 若涉及面试技巧/算法模式，用 **Skill** 加载方法论
3. 基于检索结果和用户水平组织回答
4. 回答后更新 TodoWrite 记录本次学习

当前时间: {current_time}
"""


class LearningAgent(ReActAgent):
    """智能学习伙伴 Agent

    继承 ReActAgent，集成 GSSC 上下文管线：
    - 每次 run() 动态组装 system prompt（注入 Memory + RAG 上下文）
    - 跨轮对话连续性（HistoryManager 历史注入）
    - WorkingMemory 写入（供下次检索）

    记忆架构:
      - WorkingMemory: 当前会话活跃上下文（每次学习后写入）
      - EpisodicMemory: 每次学习交互存为 episode（SQLite + Qdrant）
      - SemanticMemory: 知识点存为语义实体（Qdrant + Neo4j）
      - UserModel: 主题掌握度 + 章节进度 + 间隔重复

    使用示例:
        >>> from hello_agents import HelloAgentsLLM
        >>> llm = HelloAgentsLLM()
        >>> agent = LearningAgent("学习伙伴", llm)
        >>> agent.chapter_context = {"id": "mysql-index", "source_dir": "mysql/index", ...}
        >>> result = agent.run("解释什么是 B+ 树索引")
    """

    def __init__(
        self,
        name: str,
        llm: HelloAgentsLLM,
        config: Optional[AcademicConfig] = None,
        max_steps: int = 8,
    ):
        self.academic_config = config or get_config()

        # 章节上下文（由 LearningSession 设置）
        self.chapter_context: Optional[Dict[str, Any]] = None

        # 初始化 UserModel（掌握度 + 章节进度 + 间隔重复）
        self.user_model = UserModel(
            filepath=self.academic_config.memory.user_model_file
        )

        # 初始化 MemoryManager（三种记忆类型，perceptual 暂不开）
        self.memory_manager = MemoryManager(
            enable_working=True,
            enable_episodic=True,
            enable_semantic=True,
            enable_perceptual=False,
        )

        # 初始化 GSSC 上下文构建器
        self.context_builder = ContextBuilder(
            config=ContextConfig(
                max_tokens=6000,
                enable_compression=True,
            )
        )

        # 构建工具注册表
        tool_registry = ToolRegistry()

        # 1. RAG 检索工具 (核心)
        rag_tool = RAGRetrievalTool()
        tool_registry.register_tool(rag_tool)

        # 2. TodoWrite 任务管理
        todo_tool = TodoWriteTool(project_root=os.getcwd())
        tool_registry.register_tool(todo_tool)

        framework_config = Config(
            skills_enabled=False,
            todowrite_enabled=False,
            devlog_enabled=False,
            subagent_enabled=False,
        )

        # 初始 system prompt（每次 run 会被 _build_messages 覆盖为动态版本）
        initial_prompt = LEARNING_SYSTEM_PROMPT.format(
            current_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )

        super().__init__(
            name=name,
            llm=llm,
            tool_registry=tool_registry,
            system_prompt=initial_prompt,
            config=framework_config,
            max_steps=max_steps,
        )

        # 初始化 SkillLoader + SkillTool（必须在 super().__init__ 之后）
        from pathlib import Path as _Path
        import os as _os
        skills_base = _Path(_os.path.dirname(_os.path.dirname(__file__))) / "skills"
        self.skill_loader = SkillLoader(skills_base)
        skill_tool = SkillTool(skill_loader=self.skill_loader)
        tool_registry.register_tool(skill_tool)

    # ===================================================================
    # 核心：GSSC 上下文构建（覆盖 _build_messages）
    # ===================================================================

    def _build_messages(self, input_text: str):
        """构建消息列表 —— 动态 system prompt + 历史 + 当前输入

        每次 run() 调用此方法，重新生成 system prompt，
        注入最新的 Memory + RAG 上下文。
        """
        # 1. 构建动态 system prompt
        system_prompt = self._build_dynamic_prompt(input_text)

        # 2. 消息序列：system + history + user
        messages = [Message(system_prompt, role="system")]

        # 注入对话历史（跨轮连续）
        if self.history_manager:
            history_msgs = self.history_manager.get_history()
            messages.extend(history_msgs)

        messages.append(Message(input_text, role="user"))
        return messages

    def _build_dynamic_prompt(self, query: str) -> str:
        """每次 run 动态生成 system prompt

        = 基础教学指令 + 用户状态 + GSSC 上下文（Memory + RAG）
        """
        parts = []

        # 1. 基础教学指令
        parts.append(LEARNING_SYSTEM_PROMPT.format(
            current_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
        ))

        # 2. 用户学习状态
        user_summary = self.user_model.get_summary()
        if user_summary and "暂无" not in user_summary:
            parts.append(f"\n## 用户学习档案\n{user_summary}")

        # 3. 当前章节上下文
        if self.chapter_context:
            ch = self.chapter_context
            parts.append(f"\n## 当前学习章节\n"
                         f"- 章节: {ch.get('name_zh', '未知')} "
                         f"({ch.get('subject_zh', ch.get('subject', ''))})\n"
                         f"- 主题: {ch.get('description', '')}\n"
                         f"- 涉及文章: {', '.join(ch.get('article_titles', [])[:8])}")

        # 4. GSSC 上下文（Memory + RAG）
        gssc_context = self._build_context(query)
        if gssc_context:
            parts.append(gssc_context)

        return "\n".join(parts)

    def _build_context(self, query: str) -> str:
        """GSSC 管线：收集 Memory → ContextBuilder 组装

        每次 run 从多源收集上下文：
        1. WorkingMemory — 当前会话近期学习摘要
        2. EpisodicMemory — 相关章节的历史学习事件
        3. SemanticMemory — 知识图谱概念关联
        4. RAG 检索 — 章节范围的知识库内容
        """
        packets = []

        # 来源1: WorkingMemory 上下文（当前会话摘要）
        try:
            wm = self.memory_manager.memory_types.get("working")
            if wm:
                summary = wm.get_context_summary(max_length=500)
                if summary and "No working memories" not in summary:
                    packets.append(ContextPacket(
                        content=summary,
                        metadata={"type": "task_state"},
                    ))
        except Exception:
            pass

        # 来源2: EpisodicMemory 检索（同一章节的历史学习）
        if self.chapter_context:
            try:
                ch_name = self.chapter_context.get("name_zh", "")
                past = self.memory_manager.retrieve_memories(
                    query=f"{ch_name} {query}",
                    memory_types=["episodic"],
                    limit=3,
                )
                for m in past[:2]:  # 只取 top-2，省 token
                    packets.append(ContextPacket(
                        content=f"[历史学习] {m.content[:300]}",
                        metadata={"type": "related_memory"},
                    ))
            except Exception:
                pass

        # 来源3: SemanticMemory — 知识图谱检索（概念关联）
        try:
            concepts = self.memory_manager.retrieve_memories(
                query=query,
                memory_types=["semantic"],
                limit=3,
            )
            for m in concepts[:2]:
                packets.append(ContextPacket(
                    content=f"[已学概念] {m.content[:200]}",
                    metadata={"type": "related_memory"},
                ))
        except Exception:
            pass

        # 来源4: RAG 检索（按章节 scope）
        if self.chapter_context and hasattr(self, 'tool_registry'):
            try:
                rag_tool = None
                for tool in self.tool_registry.get_all_tools():
                    if tool.name == "RAGRetrieval":
                        rag_tool = tool
                        break

                if rag_tool:
                    source_dir = self.chapter_context.get("source_dir", "")
                    params = {
                        "query": query,
                        "top_k": 5,
                    }
                    if source_dir:
                        params["source_dir"] = source_dir

                    # 同步调用 RAG tool
                    result = rag_tool.run(params)
                    if result and hasattr(result, 'text') and result.text:
                        packets.append(ContextPacket(
                            content=result.text[:800],
                            metadata={"type": "retrieval"},
                        ))
            except Exception:
                pass

        if not packets:
            return ""

        # ContextBuilder: Gather → Select → Structure → Compress
        try:
            return self.context_builder.build(
                user_query=query,
                system_instructions="",
                conversation_history=[],
                additional_packets=packets,
            )
        except Exception:
            # 降级：直接拼接
            return "\n\n".join(p.content[:300] for p in packets)

    # ===================================================================
    # 核心：run() 覆盖（学习记录 + WorkingMemory 写入）
    # ===================================================================

    def run(self, input_text: str, **kwargs) -> str:
        """执行学习对话，完成后记录学习轨迹"""
        result_text = super().run(input_text, **kwargs)
        self._record_learning(input_text, result_text)
        return result_text

    async def arun(self, input_text: str, **kwargs) -> str:
        """异步执行学习对话"""
        result_text = await super().arun(input_text, **kwargs)
        self._record_learning(input_text, result_text)
        return result_text

    def _record_learning(self, query: str, answer: str):
        """记录学习过程 —— 多写 Memory + UserModel

        1. WorkingMemory: 当前会话上下文（供下次 run GSSC 管线读取）
        2. UserModel: 章节进度 + 主题掌握度
        3. EpisodicMemory: 学习事件持久化
        4. SemanticMemory: 知识点记录
        """
        topic = query[:50].strip()
        if len(query) > 50:
            topic += "..."

        # 占位评分（第3层将改为 LLM 评估）
        base_score = min(70.0, 40.0 + len(answer) / 100.0)

        # 1. WorkingMemory: 写入当前会话上下文
        try:
            self.memory_manager.add_memory(
                content=f"[刚学完] {topic}\n要点: {answer[:200]}",
                memory_type="working",
                importance=0.7,
            )
        except Exception:
            pass

        # 2. UserModel: 主题掌握度 + 章节进度
        self.user_model.update_mastery(
            topic=topic,
            score=base_score,
            notes=f"Query: {query}",
        )
        if self.chapter_context:
            self.user_model.update_chapter_progress(
                chapter_id=self.chapter_context["id"],
                name_zh=self.chapter_context.get("name_zh", ""),
                mode=self.chapter_context.get("mode", "cs_fundamentals"),
                mastery=base_score,
                articles=[topic],
            )

        # 3. EpisodicMemory: 学习事件持久化
        try:
            self.memory_manager.add_memory(
                content=f"学习了 {topic}\n问题: {query}\n回答摘要: {answer[:200]}",
                memory_type="episodic",
                importance=0.5 + base_score / 200,
                metadata={
                    "topic": topic,
                    "mastery_score": base_score,
                    "chapter_id": self.chapter_context.get("id", "") if self.chapter_context else "",
                    "session_id": f"learn-{datetime.now().strftime('%Y%m%d')}",
                },
            )
        except Exception:
            pass

        # 4. SemanticMemory: 知识点记录
        try:
            self.memory_manager.add_memory(
                content=f"知识点: {topic} (掌握度 {base_score:.0f}%)",
                memory_type="semantic",
                importance=0.5 + base_score / 200,
                metadata={
                    "topic": topic,
                    "mastery_score": base_score,
                    "chapter_id": self.chapter_context.get("id", "") if self.chapter_context else "",
                },
            )
        except Exception:
            pass

        # 5. 定期整合：最高重要性 working → episodic（阈值 0.85，避免每次 Q&A 都搬空）
        try:
            self.memory_manager.consolidate_memories(
                from_type="working",
                to_type="episodic",
                importance_threshold=0.85,
            )
        except Exception:
            pass

    # ===================================================================
    # 辅助方法
    # ===================================================================

    def get_learning_status(self) -> str:
        """获取学习状态摘要 —— UserModel + Memory 合并视图"""
        user_summary = self.user_model.get_summary()
        try:
            stats = self.memory_manager.get_memory_stats()
            mem_info = f"记忆: {stats['total_memories']} 条 ({list(stats['memories_by_type'].keys())})"
            return f"{user_summary}\n{mem_info}"
        except Exception:
            return user_summary

    def get_weak_topics(self, n: int = 5):
        """获取薄弱主题列表"""
        return self.user_model.get_weak_topics(n)

    def get_chapter_progress_summary(self, all_chapters: list, mode: str) -> str:
        """获取章节进度可视化"""
        return self.user_model.get_chapter_progress_summary(all_chapters, mode)
