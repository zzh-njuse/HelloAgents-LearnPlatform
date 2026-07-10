"""聊天 API — SSE 流式 + 非流式端点"""

import asyncio
import time
import traceback
from typing import Optional, Dict
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from hello_agents.core.llm import HelloAgentsLLM
from hello_agents.core.streaming import StreamEvent, StreamEventType

router = APIRouter()

# ── Session store (MVP: in-memory dict, 后续可换 Redis) ──
# 学习模式保持多轮上下文：key = session_id
_learning_sessions: Dict[str, "LearningAgent"] = {}
_research_sessions: Dict[str, "ResearchOrchestrator"] = {}


# ── Request model ──

class ChatRequest(BaseModel):
    mode: str = "learning"  # "learning" | "research"
    message: str
    session_id: str = "default"


# ── Streaming (SSE) ──

@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """SSE 流式端点

    学习模式: LearningAgent.arun_stream() → StreamEvent → SSE
    研究模式: ResearchOrchestrator.run_streaming() → StreamEvent → SSE
    """
    if request.mode not in ("learning", "research"):
        raise HTTPException(status_code=400, detail="mode 必须是 'learning' 或 'research'")

    async def event_generator():
        last_event_time = time.time()

        def _emit(event: StreamEvent):
            nonlocal last_event_time
            last_event_time = time.time()
            return event.to_sse()

        try:
            yield _emit(StreamEvent.create(
                StreamEventType.AGENT_START, "academic_companion",
                mode=request.mode, message=request.message,
            ))

            if request.mode == "learning":
                async for sse_str in _stream_learning(request.message, request.session_id):
                    yield sse_str
                    await asyncio.sleep(0.01)

            elif request.mode == "research":
                for sse_str in _stream_research(request.message):
                    yield sse_str
                    await asyncio.sleep(0.01)
                    # 心跳
                    if time.time() - last_event_time > 30:
                        yield ": heartbeat\n\n"
                        last_event_time = time.time()

            yield _emit(StreamEvent.create(
                StreamEventType.AGENT_FINISH, "academic_companion", status="complete",
            ))

        except Exception as e:
            yield _emit(StreamEvent.create(
                StreamEventType.ERROR, "academic_companion",
                error=str(e), traceback=traceback.format_exc()[-500:],
            ))

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream_learning(message: str, session_id: str):
    """学习模式流式 — 从 LearningAgent.arun_stream() 直接转发"""
    from academic_companion.agents.learning_agent import LearningAgent

    # 复用或创建 agent
    if session_id in _learning_sessions:
        agent = _learning_sessions[session_id]
    else:
        llm = HelloAgentsLLM(temperature=0.5)
        agent = LearningAgent("学习伙伴", llm, max_steps=8)
        _learning_sessions[session_id] = agent

    async for event in agent.arun_stream(message):
        yield event.to_sse()


def _stream_research(message: str):
    """研究模式流式 — 使用 ResearchOrchestrator.run_streaming()"""
    from academic_companion.agents.research.orchestrator import ResearchOrchestrator

    llm = HelloAgentsLLM(temperature=0.3)
    orchestrator = ResearchOrchestrator("研究协调员", llm)

    for event in orchestrator.run_streaming(message):
        yield event.to_sse()


# ── Non-Streaming Fallback ──

@router.post("/chat")
async def chat(request: ChatRequest):
    """非流式端点 — 返回完整响应 JSON"""
    if request.mode not in ("learning", "research"):
        raise HTTPException(status_code=400, detail="mode 必须是 'learning' 或 'research'")

    try:
        if request.mode == "learning":
            from academic_companion.agents.learning_agent import LearningAgent

            if request.session_id in _learning_sessions:
                agent = _learning_sessions[request.session_id]
            else:
                llm = HelloAgentsLLM(temperature=0.5)
                agent = LearningAgent("学习伙伴", llm, max_steps=8)
                _learning_sessions[request.session_id] = agent

            result = agent.run(request.message)
            return {"mode": "learning", "response": result, "session_id": request.session_id}

        elif request.mode == "research":
            from academic_companion.agents.research.orchestrator import ResearchOrchestrator

            llm = HelloAgentsLLM(temperature=0.3)
            orchestrator = ResearchOrchestrator("研究协调员", llm)
            result = orchestrator.run(request.message)
            return {"mode": "research", "response": result, "session_id": request.session_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
