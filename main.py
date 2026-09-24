"""Voice agent entry point.

FastAPI server with a single agent interface:
  - WS /ws → voice pipeline (STT → Pipecat LLM + tools → TTS)  (ticket required)

Auxiliary REST:
  - /auth, /menu, /orders for account + order management.
"""

import asyncio
import os
import uuid
from contextlib import asynccontextmanager

import uvicorn
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from pipecat.frames.frames import LLMRunFrame, OutputTransportMessageUrgentFrame
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask

from config import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    AUTH_COOKIE_NAME,
    CORS_ORIGINS,
    MAX_SESSION_SECONDS,
    REDIS_URL,
    SEED_ON_STARTUP,
    VOICE_IDLE_SECONDS,
)
from db.base import get_session
from pipeline.voice_pipeline import create_pipeline, load_call_context
from routers import (
    admin,
    analytics,
    auth,
    customers,
    floors,
    menu,
    orders,
    payments,
    service_areas,
    settings,
    staff,
    table_sessions,
    tables,
    zones,
)
from services.auth_service import auth_service
from services.ratelimit import acquire_slot, release_slot


def _client_ip(websocket: WebSocket) -> str:
    """Caller IP. Uvicorn resolves X-Forwarded-For only from trusted proxies
    (see server_config), so a client can't spoof it by sending the header."""
    return websocket.client.host if websocket.client else ""


def seed_database() -> None:
    with get_session() as db:
        from db.seeds.areas_seed import seed_service_areas
        from db.seeds.floor_seed import seed_floor
        from db.seeds.menu_seed import seed_admin, seed_menu
        seed_menu(db)
        seed_admin(db, email=ADMIN_EMAIL, password=ADMIN_PASSWORD)
        seed_service_areas(db)
        seed_floor(db)
    logger.info("Database seeded")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if SEED_ON_STARTUP:
        seed_database()

    # Seed the default bill charge policy + prime the billing cache so
    # compute_bill uses the admin-editable policy from the first request.
    with get_session() as db:
        from services.settings_service import SettingsService
        SettingsService(db).load_into_cache()

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
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,  # the browser sends the session cookie
    allow_methods=["*"],
    allow_headers=["*"],
)

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _request_origin(request: Request) -> str | None:
    origin = request.headers.get("origin")
    if origin:
        return origin.rstrip("/")
    referer = urlsplit(request.headers.get("referer", ""))
    return f"{referer.scheme}://{referer.netloc}" if referer.netloc else None


@app.middleware("http")
async def reject_cross_site_cookie_writes(request: Request, call_next):
    """CSRF guard for cookie-authenticated writes.

    SameSite=Lax doesn't cover sibling subdomains of the same site, so a write
    that rides on the session cookie must come from an allowed frontend origin.
    Bearer-token callers and cookie-less requests (guests, webhooks) are exempt:
    a cross-site page can't attach either credential by itself.
    """
    if (
        request.method in _UNSAFE_METHODS
        and AUTH_COOKIE_NAME in request.cookies
        and "authorization" not in request.headers
        and _request_origin(request) not in CORS_ORIGINS
    ):
        return JSONResponse(status_code=403, content={"detail": "Cross-site request blocked"})
    return await call_next(request)

# Lightweight health check — used by the frontend's "backend waking up"
# gate when we're on Render's free plan (cold-starts take ~50 s). No auth,
# no DB, no external calls — just confirms the process is serving.
@app.get("/health")
async def health():
    """Liveness: the process is up. Deliberately touches nothing else."""
    return {"status": "ok"}


def _ping_database() -> None:
    from sqlalchemy import text

    with get_session() as db:
        db.execute(text("SELECT 1"))


def _ping_redis() -> None:
    import redis

    redis.Redis.from_url(REDIS_URL, socket_timeout=2).ping()


@app.get("/ready")
async def ready():
    """Readiness: Postgres and Redis both answer. Route traffic only when 200."""
    status = {}
    for name, ping in (("database", _ping_database), ("redis", _ping_redis)):
        try:
            await asyncio.to_thread(ping)
            status[name] = "ok"
        except Exception as e:
            logger.warning(f"readiness: {name} unavailable: {e}")
            status[name] = "down"
    code = 200 if all(v == "ok" for v in status.values()) else 503
    return JSONResponse(status_code=code, content=status)


# REST routers (no text chat)
app.include_router(auth.router)
app.include_router(menu.router)
app.include_router(orders.router)
app.include_router(admin.router)
app.include_router(customers.router)
app.include_router(service_areas.router)
app.include_router(floors.router)
app.include_router(zones.router)
app.include_router(tables.router)
app.include_router(table_sessions.router)
app.include_router(settings.router)
app.include_router(analytics.router)
app.include_router(staff.router)
app.include_router(payments.router)


# --- Voice WebSocket endpoint ---

def _cancel_pipeline_on_disconnect(transport, task, ip: str) -> None:
    """Free the concurrency slot the instant the browser hangs up.

    Pipecat's FastAPI transport fires ``on_client_disconnected`` when the client
    closes the socket, but it does NOT inject an EndFrame — so ``runner.run(task)``
    would keep awaiting (the Gemini Live upstream socket is still open) until the
    session-cap watchdog cancels it ~15 min later. Until then the call still holds
    its slot, so stopping the mic mid-call leaked one slot per restart → after a
    few taps every line reads "busy" and new taps queue forever.

    Cancelling the task here makes ``runner.run`` return immediately, so the
    ``finally: release_slot`` in the endpoint runs right away. Extracted (and
    unit-tested) so the wiring can't silently regress.
    """

    @transport.event_handler("on_client_disconnected")
    async def _on_client_disconnected(_transport, _client):  # noqa: ANN001
        logger.info(f"Voice client hung up — cancelling pipeline to free slot: {ip}")
        await task.cancel()


def build_task(pipeline) -> PipelineTask:
    """A call's pipeline task, ended (with a notice to the client) once nobody
    has spoken for VOICE_IDLE_SECONDS."""
    task = PipelineTask(
        pipeline, idle_timeout_secs=VOICE_IDLE_SECONDS, cancel_on_idle_timeout=False
    )

    @task.event_handler("on_idle_timeout")
    async def _end_idle_call(task_):
        try:
            await task_.queue_frames([
                OutputTransportMessageUrgentFrame(message={
                    "kind": "ui_event",
                    "event": "session_end",
                    "data": {
                        "reason": "idle",
                        "message": "We didn't hear anything for a while, so we ended the call. "
                                   "Tap the mic to start again.",
                    },
                })
            ])
            await asyncio.sleep(0.6)  # let the notice reach the client first
        except Exception:
            pass
        await task_.cancel()

    return task


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Voice chat: ticket auth, then audio + UI events over WS via Pipecat."""
    # Browsers always send Origin on WebSockets; don't let other sites embed the
    # voice line and spend our Gemini quota on their visitors.
    origin = websocket.headers.get("origin")
    if origin and origin.rstrip("/") not in CORS_ORIGINS:
        await websocket.close(code=4001)
        return
    ticket = websocket.query_params.get("ticket")
    if not ticket:
        await websocket.close(code=4001)
        return

    # Consuming the ticket hits Redis — if Redis is down, close cleanly with the
    # auth code instead of letting the exception bubble (no socket close).
    try:
        payload = auth_service.consume_ws_ticket(ticket)
    except Exception as e:
        logger.warning(f"ws-ticket consume failed (redis?): {e}")
        await websocket.close(code=4001)
        return
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

    # Slot is held from here — wrap EVERYTHING that follows so a failure during
    # pipeline construction can't leak the concurrency slot.
    cap_task = None
    try:
        logger.info(
            f"Voice client connected (anonymous parcel line): {ip} tz={user_timezone}"
        )

        # Table/profile lookups run off the event loop (it serves every call's audio).
        call_context = await asyncio.to_thread(load_call_context, table_token)
        pipeline, transport = create_pipeline(
            websocket, user_timezone=user_timezone, table_token=table_token,
            call_context=call_context,
        )
        task = build_task(pipeline)

        # Hang-up → cancel the pipeline now so the slot is released immediately
        # (otherwise it leaks until the session cap; see helper docstring).
        _cancel_pipeline_on_disconnect(transport, task, ip)

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
        await runner.run(task)
    finally:
        if cap_task is not None:
            cap_task.cancel()
        release_slot(call_id)
    logger.info(f"Voice client disconnected: {ip}")


def server_config() -> dict:
    """Uvicorn settings. Behind a reverse proxy, set FORWARDED_ALLOW_IPS to the
    proxy's address/range so request.client.host is the real caller (per-IP
    rate limits depend on it); by default only a local proxy is trusted."""
    return {
        "host": "0.0.0.0",
        "port": int(os.environ.get("PORT", "8000")),
        "log_level": "info",
        "proxy_headers": True,
        "forwarded_allow_ips": os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    }


if __name__ == "__main__":
    uvicorn.run("main:app", **server_config())
