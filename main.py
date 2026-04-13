"""Voice agent entry point.

FastAPI server with two interfaces to the same LangGraph agent:
  - POST /chat       → text in, text out  (JWT required)
  - WS   /ws         → voice pipeline (STT → Agent → TTS)  (ticket required)
"""

from contextlib import asynccontextmanager
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pydantic import BaseModel

from agent.graph import create_agent, create_fallback_agent, invoke_agent
from config import ADMIN_EMAIL, ADMIN_PASSWORD
from db.base import get_session
from pipeline.voice_pipeline import create_pipeline
from routers import auth, chat, menu, orders
from services.auth_service import auth_service
from services.chat_service import ChatService
from services.order_service import OrderService


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Seed data on startup
    with get_session() as db:
        from db.seeds.menu_seed import seed_admin, seed_menu
        seed_menu(db)
        seed_admin(db, email=ADMIN_EMAIL, password=ADMIN_PASSWORD)
        logger.info("Database seeded")

    yield


app = FastAPI(title="Culinary Oracle API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(auth.router)
app.include_router(menu.router)
app.include_router(orders.router)
app.include_router(chat.router)

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


_bearer = HTTPBearer()


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    req: ChatRequest,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
):
    """Text chat: message in, text response out. JWT required."""
    # Auth
    try:
        payload = auth_service.decode_token(credentials.credentials)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = payload["sub"]

    # Get or create session and load history
    with get_session() as db:
        order_service = OrderService(db)
        chat_service = ChatService(db)

        cart = order_service.get_or_create_cart(user_id)
        session = chat_service.get_active_session(user_id)
        session_id = session.id if session else str(uuid4())
        prior_messages = chat_service.get_history_as_langchain_messages(session_id) if session else []

    thread_id = session_id

    agent, fallback = get_agents()
    response_text = await invoke_agent(
        agent, fallback, req.message, thread_id,
        user_id=user_id, prior_messages=prior_messages
    )

    # Persist messages
    with get_session() as db:
        chat_service = ChatService(db)
        chat_service.save_message(session_id, "user", req.message)
        chat_service.save_message(session_id, "assistant", response_text)

    return ChatResponse(response=response_text, thread_id=thread_id)


# --- Voice WebSocket endpoint ---

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Voice chat: ticket auth, then audio in/out via Pipecat."""
    ticket = websocket.query_params.get("ticket")
    if not ticket:
        await websocket.close(code=4001)
        return

    user_id = auth_service.consume_ws_ticket(ticket)
    if not user_id:
        await websocket.close(code=4001)
        return

    await websocket.accept()
    logger.info(f"Voice client connected: {websocket.client} user={user_id}")

    pipeline = create_pipeline(websocket, user_id=user_id)
    task = PipelineTask(pipeline)
    runner = PipelineRunner(handle_sigint=False)

    await runner.run(task)
    logger.info(f"Voice client disconnected: {websocket.client}")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8765, log_level="info")
