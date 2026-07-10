"""Academic AI Companion — FastAPI 服务入口

启动方式:
    uvicorn academic_companion.api.server:app --reload --host 0.0.0.0 --port 8000

端点:
    GET  /api/health          — 健康检查
    POST /api/chat/stream     — SSE 流式聊天
    POST /api/chat            — 非流式聊天
    GET  /api/knowledge/status  — Qdrant 统计
    GET  /api/knowledge/chapters — CS-Base 章节列表
"""

import os
import sys

# 确保项目根在 sys.path 中（uvicorn 运行时需要）
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes_chat import router as chat_router
from .routes_knowledge import router as knowledge_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Academic AI Companion API",
        description="HelloAgents 学术 AI 伴侣 — 学习模式 + 研究模式",
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(chat_router, prefix="/api")
    app.include_router(knowledge_router, prefix="/api")

    @app.get("/api/health")
    async def health():
        return {
            "status": "ok",
            "version": "1.0.0",
            "modes": ["learning", "research"],
        }

    @app.get("/")
    async def root():
        return {
            "app": "Academic AI Companion API",
            "docs": "/docs",
            "health": "/api/health",
            "chat_stream": "/api/chat/stream",
            "chat": "/api/chat",
            "knowledge": "/api/knowledge/status",
            "chapters": "/api/knowledge/chapters",
        }

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
