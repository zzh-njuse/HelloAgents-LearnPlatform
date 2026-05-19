"""LearningAgent — 智能学习伙伴

基于 ReActAgent 的 AI 学习助手，整合:
- RAG 知识检索 (RAGRetrievalTool)
- Skill 方法论加载 (SkillTool)
- MemoryManager — 4 种记忆类型（Working/Episodic/Semantic）
- UserModel — 掌握度追踪 + 间隔重复
- TodoWriteTool — 学习任务管理
"""

import os

from typing import Optional
from datetime import datetime

from hello_agents.agents.react_agent import ReActAgent
from hello_agents.core.llm import HelloAgentsLLM
from hello_agents.core.config import Config
from hello_agents.tools.registry import ToolRegistry
from hello_agents.tools.builtin.todowrite_tool import TodoWriteTool
from hello_agents.tools.builtin.skill_tool import SkillTool
from hello_agents.skills.loader import SkillLoader
from hello_agents.memory import MemoryManager

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

## 用户学习档案
{user_summary}

## 相关历史记忆
{memory_context}

当前时间: {current_time}
"""


class LearningAgent(ReActAgent):
    """智能学习伙伴 Agent

    继承 ReActAgent，预配置学习模式所需的所有工具和记忆系统。

    记忆架构:
      - UserModel: 主题掌握度 + 间隔重复（学习模式专属逻辑）
      - WorkingMemory: 当前会话活跃上下文（自动管理）
      - EpisodicMemory: 每次学习交互存为 episode（SQLite + Qdrant）
      - SemanticMemory: 知识点存为语义实体（Qdrant + Neo4j）

    使用示例:
        >>> from hello_agents import HelloAgentsLLM
        >>> llm = HelloAgentsLLM()
        >>> agent = LearningAgent("学习伙伴", llm)
        >>> result = agent.run("解释 TCP 三次握手")
    """

    def __init__(
        self,
        name: str,
        llm: HelloAgentsLLM,
        config: Optional[AcademicConfig] = None,
        max_steps: int = 8,
    ):
        self.academic_config = config or get_config()

        # 初始化 UserModel（掌握度 + 间隔重复）
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

        # 构建工具注册表
        tool_registry = ToolRegistry()

        # 1. RAG 检索工具 (核心)
        rag_tool = RAGRetrievalTool()
        tool_registry.register_tool(rag_tool)

        # 2. TodoWrite 任务管理
        todo_tool = TodoWriteTool(project_root=os.getcwd())
        tool_registry.register_tool(todo_tool)

        # 构建含用户状态 + 记忆上下文的系统提示词
        memory_context = self._build_memory_context()
        system_prompt = LEARNING_SYSTEM_PROMPT.format(
            user_summary=self.user_model.get_summary(),
            memory_context=memory_context,
            current_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )

        framework_config = Config(
            skills_enabled=False,
            todowrite_enabled=False,
            devlog_enabled=False,
            subagent_enabled=False,
        )

        super().__init__(
            name=name,
            llm=llm,
            tool_registry=tool_registry,
            system_prompt=system_prompt,
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

    def _build_memory_context(self) -> str:
        """从 MemoryManager 检索与当前会话相关的历史记忆"""
        try:
            recent = self.memory_manager.memory_types.get("working")
            if recent:
                context = recent.get_context_summary(max_length=300)
                if context and "No working memories" not in context:
                    return context
        except Exception:
            pass
        return "（暂无历史学习记忆）"

    def _record_learning(self, query: str, answer: str):
        """记录学习过程——双写 UserModel + MemoryManager

        未来可接入 LLM 精确评估掌握度。
        """
        # 简单关键词提取作为主题
        topic = query[:50].strip()
        if len(query) > 50:
            topic += "..."

        # 评分（占位逻辑——后续优化为 LLM 评估）
        base_score = min(70.0, 40.0 + len(answer) / 100.0)

        # 1. UserModel: 掌握度追踪
        self.user_model.update_mastery(
            topic=topic,
            score=base_score,
            notes=f"Query: {query}",
        )

        # 2. EpisodicMemory: 学习事件持久化
        try:
            self.memory_manager.add_memory(
                content=f"学习了 {topic}\n问题: {query}\n回答摘要: {answer[:200]}",
                memory_type="episodic",
                importance=0.5 + base_score / 200,  # 0.5~0.85
                metadata={
                    "topic": topic,
                    "mastery_score": base_score,
                    "session_id": f"learn-{datetime.now().strftime('%Y%m%d')}",
                },
            )
        except Exception:
            pass

        # 3. SemanticMemory: 知识点记录（核心概念存为语义实体）
        try:
            self.memory_manager.add_memory(
                content=f"知识点: {topic} (掌握度 {base_score:.0f}%)",
                memory_type="semantic",
                importance=0.5 + base_score / 200,
                metadata={"topic": topic, "mastery_score": base_score},
            )
        except Exception:
            pass

        # 4. 定期整合：高重要性 working → episodic
        try:
            self.memory_manager.consolidate_memories(
                from_type="working",
                to_type="episodic",
                importance_threshold=0.7,
            )
        except Exception:
            pass

    def get_learning_status(self) -> str:
        """获取学习状态摘要——UserModel + MemoryManager 合并视图"""
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
