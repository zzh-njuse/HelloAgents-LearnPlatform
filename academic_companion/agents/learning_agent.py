"""LearningAgent — 智能学习伙伴

基于 ReActAgent 的 AI 学习助手，整合:
- RAG 知识检索 (RAGRetrievalTool)
- Skill 方法论加载 (SkillTool)
- 用户记忆追踪 (UserModel)
- 学习任务管理 (TodoWriteTool)
- 学习轨迹记录 (DevLogTool)
"""

import os

from typing import Optional, Dict, Any
from datetime import datetime

from hello_agents.agents.react_agent import ReActAgent
from hello_agents.core.llm import HelloAgentsLLM
from hello_agents.core.config import Config
from hello_agents.tools.registry import ToolRegistry
from hello_agents.tools.builtin.todowrite_tool import TodoWriteTool
from hello_agents.tools.builtin.devlog_tool import DevLogTool
from hello_agents.tools.builtin.skill_tool import SkillTool
from hello_agents.skills.loader import SkillLoader

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
5. 重要的学习发现记录到 DevLog

## 用户记忆
{user_summary}

当前时间: {current_time}
"""


class LearningAgent(ReActAgent):
    """智能学习伙伴 Agent

    继承 ReActAgent，预配置学习模式所需的所有工具和记忆系统。

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

        # 初始化 UserModel
        self.user_model = UserModel(
            filepath=self.academic_config.memory.user_model_file
        )

        # 构建工具注册表
        tool_registry = ToolRegistry()

        # 1. RAG 检索工具 (核心) — 可在 super() 前注册
        rag_tool = RAGRetrievalTool()
        tool_registry.register_tool(rag_tool)

        # 2. TodoWrite 任务管理 — 可在 super() 前注册
        todo_tool = TodoWriteTool(project_root=os.getcwd())
        tool_registry.register_tool(todo_tool)

        # 3. DevLog 学习轨迹 — 可在 super() 前注册
        devlog_tool = DevLogTool(
            session_id=f"learn-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            agent_name=name,
            project_root=os.getcwd(),
        )
        tool_registry.register_tool(devlog_tool)

        # 构建含用户状态的系统提示词
        system_prompt = LEARNING_SYSTEM_PROMPT.format(
            user_summary=self.user_model.get_summary(),
            current_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )

        # 框架 Config（禁用内置的 Skill/TodoWrite/DevLog 自动注册，
        # 因为我们手动注册了定制版本）
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

        # 初始化 SkillLoader + SkillTool（必须在 super().__init__ 之后，因为父类会把 skill_loader 置 None）
        from pathlib import Path as _Path
        import os as _os
        skills_base = _Path(_os.path.dirname(_os.path.dirname(__file__))) / "skills"
        self.skill_loader = SkillLoader(skills_base)
        skill_tool = SkillTool(skill_loader=self.skill_loader)
        tool_registry.register_tool(skill_tool)

    def run(self, input_text: str, **kwargs) -> str:
        """执行学习对话

        在 ReActAgent.run() 的基础上增加学习状态追踪。
        """
        # 记录学习主题（从 query 提取关键词）
        result_text = super().run(input_text, **kwargs)

        # 尝试提取主题和评估掌握度（简版: 根据回答是否成功来判断）
        # 后续可接入 LLM 评估
        self._record_learning(input_text, result_text)

        return result_text

    async def arun(self, input_text: str, **kwargs) -> str:
        """异步执行学习对话"""
        result_text = await super().arun(input_text, **kwargs)
        self._record_learning(input_text, result_text)
        return result_text

    def _record_learning(self, query: str, answer: str):
        """记录学习过程

        从 query 中简单提取可能的关键词作为 topic。
        生产环境可接入 LLM 提取精确主题和评分。
        """
        # 简单关键词提取（取 query 的前 50 字符作为主题描述）
        topic = query[:50].strip()
        if len(query) > 50:
            topic += "..."

        # 如果回答过长说明可能讲得比较深入，给个基础评分
        base_score = min(70.0, 40.0 + len(answer) / 100.0)

        self.user_model.update_mastery(
            topic=topic,
            score=base_score,
            notes=f"Query: {query}",
        )

    def get_learning_status(self) -> str:
        """获取当前学习状态摘要"""
        return self.user_model.get_summary()

    def get_weak_topics(self, n: int = 5):
        """获取薄弱主题列表"""
        return self.user_model.get_weak_topics(n)
