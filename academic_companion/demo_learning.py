"""Phase 2 CLI Demo — 学习模式端到端验证

运行方式:
    python academic_companion/demo_learning.py

前置条件:
    1. .env 已配置 LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_ID
    2. .env 已配置 QDRANT_URL, QDRANT_API_KEY (Qdrant Cloud)
    3. data/cs_fundamentals/ 下有 CS-Base 数据
    4. data/leetcode/ 下有 LeetCode 数据
    5. pip install sentence-transformers (bge 本地 embedding)

测试场景:
    1. 知识检索: "解释 TCP 拥塞控制的四种算法"
    2. 刷题辅导: "给我讲一道滑动窗口的中等难度题"
    3. 记忆回溯: 检查学习进度
"""

import sys
import os

# 确保项目根在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from hello_agents.core.llm import HelloAgentsLLM
from academic_companion.agents.learning_agent import LearningAgent


def print_separator(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def main():
    print_separator("Academic AI Companion — 学习模式 Demo")
    print(f"LLM Model: {os.getenv('LLM_MODEL_ID', 'not set')}")
    print(f"Qdrant URL: {os.getenv('QDRANT_URL', 'not set')}")

    # 初始化 LLM
    llm = HelloAgentsLLM()

    # 初始化 LearningAgent
    print("\n初始化 LearningAgent...")
    agent = LearningAgent("学习伙伴", llm)

    # 显示可用工具
    tools = agent.tool_registry.list_tools()
    print(f"已注册工具 ({len(tools)}): {', '.join(tools)}")

    # 显示已加载 Skills
    skills = agent.skill_loader.list_skills()
    print(f"已加载 Skills ({len(skills)}): {', '.join(skills)}")

    # 显示学习状态
    print("\n学习状态:")
    print(agent.get_learning_status())

    # --- 场景 1: 知识检索 ---
    print_separator("场景 1: CS 概念讲解 — TCP 拥塞控制")
    result1 = agent.run("请详细解释 TCP 拥塞控制的四种算法：慢启动、拥塞避免、快速重传、快速恢复")
    print(f"\n回答:\n{result1}")

    # --- 场景 2: 刷题辅导 ---
    print_separator("场景 2: 算法题辅导 — 滑动窗口")
    result2 = agent.run("给我讲一道滑动窗口的中等难度算法题，从思路到代码实现")
    print(f"\n回答:\n{result2}")

    # --- 场景 3: 记忆回溯 ---
    print_separator("场景 3: 学习状态检查")
    print(agent.get_learning_status())
    weak = agent.get_weak_topics(3)
    if weak:
        print(f"\n建议复习的主题:")
        for topic, score in weak:
            print(f"  - {topic}: {score:.0f}%")

    print_separator("Demo 完成")
    print(f"学习记录已保存到 memory/user_model.json")
    print(f"Trace 日志: memory/traces/")


if __name__ == "__main__":
    main()
