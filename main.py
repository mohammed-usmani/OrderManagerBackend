"""Voice agent entry point.

FastAPI server with a single agent interface:
  - WS /ws → voice pipeline (STT → Pipecat LLM + tools → TTS)  (ticket required)

Auxiliary REST:
  - /auth, /menu, /orders for account + order management.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pipecat.frames.frames import LLMRunFrame, OutputTransportMessageUrgentFrame
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask

from config import ADMIN_EMAIL, ADMIN_PASSWORD, MAX_SESSION_SECONDS
from db.base import get_session
from pipeline.voice_pipeline import create_pipeline
from routers import (
    admin,
    analytics,
    auth,
    customers,
    menu,
    orders,
    service_areas,
    settings,
    table_sessions,
    tables,
    zones,
)
from services.auth_service import auth_service
from services.ratelimit import acquire_slot, release_slot


def _client_ip(websocket: WebSocket) -> str:
    """Real client IP behind Cloud Run's proxy (first X-Forwarded-For hop)."""
    fwd = websocket.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return websocket.client.host if websocket.client else ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Seed data on startup
    with get_session() as db:
        from db.seeds.areas_seed import seed_service_areas
        from db.seeds.floor_seed import seed_floor
        from db.seeds.menu_seed import seed_admin, seed_menu
        seed_menu(db)
        seed_admin(db, email=ADMIN_EMAIL, password=ADMIN_PASSWORD)
        seed_service_areas(db)
        seed_floor(db)
        # Seed the default bill charge policy + prime the billing cache so
        # compute_bill uses the admin-editable policy from the first request.
        from services.settings_service import SettingsService
        SettingsService(db).load_into_cache()
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
app.include_router(zones.router)
app.include_router(tables.router)
app.include_router(table_sessions.router)
app.include_router(settings.router)
app.include_router(analytics.router)


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
    table_token = payload.get("table_token")
    ip = _client_ip(websocket)
    call_id = uuid.uuid4().hex

    await websocket.accept()

    # Global concurrency cap (Gemini free tier ≈ 3 Live sessions). We accept
    # first so the browser gets a proper close code + reason to show/retry on.
    allowed, reason = acquire_slot(call_id)
    if not allowed:
        logger.info(f"Voice connect turned away (lines busy) ip={ip}: {reason}")
        # A WebSocket close reason is capped at 123 bytes by the protocol —
        # truncate so a long message can't raise "control frame too long".
        safe_reason = reason.encode("utf-8")[:120].decode("utf-8", "ignore")
        try:
            await websocket.close(code=4003, reason=safe_reason)
        except Exception as e:
            logger.warning(f"close after rate-limit failed: {e}")
        return

    logger.info(
        f"Voice client connected (anonymous parcel line): {ip} tz={user_timezone}"
    )

    pipeline = create_pipeline(
        websocket, user_timezone=user_timezone, table_token=table_token
    )
    task = PipelineTask(pipeline)

    # Kick Gemini Live into a ready state. The service only becomes ready for
    # realtime audio after its _handle_context runs, which only fires on a
    # context frame. The user aggregator pushes a context frame when it
    # receives an LLMRunFrame, so we emit one right as the pipeline starts.
    @task.event_handler("on_pipeline_started")
    async def _kickstart(_task, _frame):
        await _task.queue_frames([LLMRunFrame()])

    runner = PipelineRunner(handle_sigint=False)

    # Hard cap on call length: a watchdog tells the client WHY the call is
    # ending (so it's clearly a demo limit, not a crash), then gracefully ends
    # the pipeline so no one can hold a call (and CPU) open indefinitely.
    async def _session_cap():
        warn = 60  # seconds of heads-up before the hard cut
        try:
            if MAX_SESSION_SECONDS > warn:
                await asyncio.sleep(MAX_SESSION_SECONDS - warn)
                try:
                    await task.queue_frames([
                        OutputTransportMessageUrgentFrame(message={
                            "kind": "ui_event",
                            "event": "time_warning",
                            "data": {"seconds_left": warn},
                        })
                    ])
                except Exception:
                    pass
                await asyncio.sleep(warn)
            else:
                await asyncio.sleep(MAX_SESSION_SECONDS)
            mins = MAX_SESSION_SECONDS // 60
            logger.info(f"Voice session hit the {MAX_SESSION_SECONDS}s cap — ending: {ip}")
            try:
                await task.queue_frames([
                    OutputTransportMessageUrgentFrame(message={
                        "kind": "ui_event",
                        "event": "session_end",
                        "data": {
                            "reason": "time_limit",
                            "message": (
                                f"We cap each call at {mins} minutes on this demo so the "
                                "shared kitchen CPU stays free for everyone. Tap the mic "
                                "to start a fresh call whenever you like."
                            ),
                        },
                    })
                ])
                await asyncio.sleep(0.6)  # let the notice reach the client first
            except Exception:
                pass
            await task.cancel()
        except asyncio.CancelledError:
            pass  # call ended normally before the cap

    cap_task = asyncio.create_task(_session_cap())
    try:
        await runner.run(task)
    finally:
        cap_task.cancel()
        release_slot(call_id)
    logger.info(f"Voice client disconnected: {ip}")


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
