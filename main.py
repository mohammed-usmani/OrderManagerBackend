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
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask

from config import ADMIN_EMAIL, ADMIN_PASSWORD
from db.base import get_session
from pipeline.voice_pipeline import create_pipeline
from routers import admin, auth, customers, menu, orders, service_areas
from services.auth_service import auth_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Seed data on startup
    with get_session() as db:
        from db.seeds.areas_seed import seed_service_areas
        from db.seeds.menu_seed import seed_admin, seed_menu
        seed_menu(db)
        seed_admin(db, email=ADMIN_EMAIL, password=ADMIN_PASSWORD)
        seed_service_areas(db)
        logger.info("Database seeded")

    # Backfill semantic-search embeddings for any menu items missing them.
    # Best-effort: never block startup if embeddings or the vector column are
    # unavailable.
    try:
        with get_session() as db:
            from services.menu_service import MenuService
            embedded = MenuService(db).reembed_all(only_missing=True)
            if embedded:
                logger.info(f"Embedded {embedded} menu item(s) for semantic search")
    except Exception as e:
        logger.warning(f"Skipped embedding backfill: {e}")

    yield


app = FastAPI(title="Culinary Oracle API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lightweight health check — used by the frontend's "backend waking up"
# gate when we're on Render's free plan (cold-starts take ~50 s). No auth,
# no DB, no external calls — just confirms the process is serving.
@app.get("/health")
async def health():
    return {"status": "ok"}


# REST routers (no text chat)
app.include_router(auth.router)
app.include_router(menu.router)
app.include_router(orders.router)
app.include_router(admin.router)
app.include_router(customers.router)
app.include_router(service_areas.router)


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

    user_timezone = payload.get("timezone")

    await websocket.accept()
    logger.info(
        f"Voice client connected (anonymous parcel line): {websocket.client} tz={user_timezone}"
    )

    pipeline = create_pipeline(websocket, user_timezone=user_timezone)
    task = PipelineTask(pipeline)

    # Kick Gemini Live into a ready state. The service only becomes ready for
    # realtime audio after its _handle_context runs, which only fires on a
    # context frame. The user aggregator pushes a context frame when it
    # receives an LLMRunFrame, so we emit one right as the pipeline starts.
    @task.event_handler("on_pipeline_started")
    async def _kickstart(_task, _frame):
        await _task.queue_frames([LLMRunFrame()])

    runner = PipelineRunner(handle_sigint=False)

    await runner.run(task)
    logger.info(f"Voice client disconnected: {websocket.client}")


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
