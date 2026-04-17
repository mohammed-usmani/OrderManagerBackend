"""Voice agent entry point.

FastAPI server with a single agent interface:
  - WS /ws → voice pipeline (STT → Pipecat LLM + tools → TTS)  (ticket required)

Auxiliary REST:
  - /auth, /menu, /orders for account + order management.
"""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask

from config import ADMIN_EMAIL, ADMIN_PASSWORD
from db.base import get_session
from pipeline.voice_pipeline import create_pipeline
from routers import auth, menu, orders
from services.auth_service import auth_service


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

# REST routers (no text chat)
app.include_router(auth.router)
app.include_router(menu.router)
app.include_router(orders.router)


# --- Voice WebSocket endpoint ---

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Voice chat: ticket auth, then audio + UI events over WS via Pipecat."""
    ticket = websocket.query_params.get("ticket")
    if not ticket:
        await websocket.close(code=4001)
        return

    payload = auth_service.consume_ws_ticket(ticket)
    if not payload:
        await websocket.close(code=4001)
        return

    user_id = payload["user_id"]
    user_timezone = payload.get("timezone")

    await websocket.accept()
    logger.info(
        f"Voice client connected: {websocket.client} user={user_id} tz={user_timezone}"
    )

    pipeline = create_pipeline(websocket, user_id=user_id, user_timezone=user_timezone)
    task = PipelineTask(pipeline)
    runner = PipelineRunner(handle_sigint=False)

    await runner.run(task)
    logger.info(f"Voice client disconnected: {websocket.client}")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level="info")
