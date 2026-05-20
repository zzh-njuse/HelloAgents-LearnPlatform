"""Academic AI Companion — 学习模式演示入口

启动会话式学习 CLI。

Usage:
    conda run --no-capture-output -n helloagents python academic_companion/session_demo.py
"""

import os
import sys

# 确保项目根在 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from academic_companion.agents.learning_session import LearningSession


def main():
    # 检查 chapters.json
    if not os.path.exists("data/chapters.json"):
        print("=" * 60)
        print("首次运行：章节数据尚未生成")
        print("正在运行 scripts/build_chapters.py ...")
        print("=" * 60)
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import subprocess
        subprocess.run([sys.executable, "scripts/build_chapters.py"])

    session = LearningSession()

    # 快速开始：直接选八股模式
    print('\n快速开始: /select cs_fundamentals  (八股) 或 /select algorithm (算法)')

    session.start()


if __name__ == "__main__":
    main()
