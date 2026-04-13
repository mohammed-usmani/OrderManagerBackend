"""Voice agent entry point.

FastAPI server with two interfaces to the same LangGraph agent:
  - POST /chat       → text in, text out
  - WS   /ws         → voice pipeline (STT → Agent → TTS)
"""

from uuid import uuid4

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pydantic import BaseModel

from agent.graph import create_agent, create_fallback_agent, invoke_agent
from pipeline.voice_pipeline import create_pipeline

app = FastAPI(title="Culinary Oracle API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared agents — created once, reused across requests
_agent = None
_fallback_agent = None


def get_agents():
    global _agent, _fallback_agent
    if _agent is None:
        _agent = create_agent()
        _fallback_agent = create_fallback_agent()
    return _agent, _fallback_agent


# --- Text chat endpoint ---

class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    thread_id: str


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    """Text chat: message in, text response out. No voice."""
    agent, fallback = get_agents()
    thread_id = req.thread_id or str(uuid4())

    response_text = await invoke_agent(agent, fallback, req.message, thread_id)

    return ChatResponse(response=response_text, thread_id=thread_id)


# --- Voice WebSocket endpoint ---

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Voice chat: audio in/out via Pipecat pipeline, backed by same agent."""
    await websocket.accept()
    logger.info(f"Voice client connected: {websocket.client}")

    pipeline = create_pipeline(websocket)
    task = PipelineTask(pipeline)
    runner = PipelineRunner(handle_sigint=False)

    await runner.run(task)

    logger.info(f"Voice client disconnected: {websocket.client}")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8765, log_level="info")
