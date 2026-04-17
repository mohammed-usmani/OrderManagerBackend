# Saffron & Smoke — Server

Voice-first restaurant ordering backend. One WebSocket carries audio + structured UI events between a customer and **Arjun**, the in-house AI manager. REST endpoints cover auth, menu, orders, and the admin back-office.

> Companion frontend lives in `../client/`.

---

## What it does

- **Voice pipeline** (Pipecat): STT → LLM (with restaurant tools) → TTS → back over the same WebSocket.
- **Tool-calling agent** places/reads orders, searches the menu, renders cards on the customer's screen, and ends the call when done.
- **Structured UI events** (`menu_results`, `cart_view`, `orders_list`, `order_confirmed`, `session_end`) travel over the same WS so the frontend renders a live "canvas" while you talk.
- **REST** for user registration / login (JWT), menu read/CRUD, order read/cancel, and an admin surface (`/admin/*`) for kitchen fulfilment, analytics, and menu management.

---

## Stack

| Layer | Choice |
|---|---|
| Language | Python 3.11 |
| HTTP | FastAPI + Uvicorn |
| Voice pipeline | [Pipecat](https://github.com/pipecat-ai/pipecat) |
| LLM | Mistral Large (primary) · Groq Llama 3.3 (fallback on rate limits) |
| STT / TTS | Voxtral (Mistral) |
| Database | PostgreSQL + SQLAlchemy 2 + Alembic |
| WS auth tickets | Redis (30 s single-use) |
| Auth | bcrypt + JWT (python-jose) |
| Package mgmt | [uv](https://docs.astral.sh/uv/) |

Alternative voice backend on the `feat/gemini-live-native-audio` branch: single **Gemini Live Native Audio** service replacing STT + LLM + TTS — see `docs/GEMINI_LIVE.md`.

---

## Project layout

```
server/
├── main.py                   FastAPI entrypoint + /ws voice endpoint
├── config.py                 env loading + shared constants (BILL_CHARGES…)
├── dependencies.py           get_current_user / require_admin
│
├── agent/
│   ├── brain.py              SYSTEM_PROMPT + build_time_context_message()
│   └── restaurant/menu.py    seed MENU + IMAGE_URLS
│
├── pipeline/
│   ├── voice_pipeline.py     Pipecat pipeline factory + tool wrappers
│   ├── ui_events.py          push_ui_event helper + compute_bill
│   ├── fallback_llm.py       Mistral → Groq fallback LLM service
│   ├── voxtral_stt.py        Mistral Voxtral STT adapter
│   └── voxtral_tts.py        Mistral Voxtral TTS adapter
│
├── routers/
│   ├── auth.py               /auth/register, /auth/login, /auth/ws-ticket
│   ├── menu.py               /menu (public read + admin CRUD)
│   ├── orders.py             /orders (read + cancel + tap-to-add)
│   └── admin.py              /admin/orders, /admin/menu, /admin/analytics
│
├── services/                 business logic (no HTTP concerns)
│   ├── auth_service.py       JWT + Redis tickets
│   ├── menu_service.py       menu search + filter + CRUD
│   ├── order_service.py      cart + order state machine
│   ├── chat_service.py       chat session persistence
│   └── user_service.py       register / login
│
├── db/
│   ├── base.py               engine + Session factory + get_session()
│   ├── models/               User, MenuItem, Order, OrderItem, ChatSession,
│   │                         ChatMessage (SQLAlchemy 2 mapped classes)
│   ├── repositories/         thin query helpers per model
│   └── seeds/menu_seed.py    seeds menu + admin user on startup
│
├── migrations/               Alembic
├── scripts/                  one-shot helpers (e.g. image downloader)
├── tests/                    pytest, hits a real test database
└── docs/                     design notes (GEMINI_LIVE.md, etc.)
```

### Layer rule

`router → service → repository → model`. Services own business rules. Routers do translation only. Agent tools call services directly (they're just another front-end).

---

## Prerequisites

- Python 3.11
- PostgreSQL (local or Docker)
- Redis
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- API keys: Mistral, Groq, NVIDIA NIM, a Voxtral `VOICE_ID`
- Optional (for the Gemini branch): Google AI Studio API key

---

## Setup

```bash
# 1. Install deps
uv sync

# 2. Create the database
createdb restaurant

# 3. Copy env template and fill in keys
cp .env.example .env
$EDITOR .env

# 4. Run migrations
uv run alembic upgrade head

# 5. Start the server
uv run uvicorn main:app --reload --port 8000
```

First startup seeds the menu and creates the admin user (`ADMIN_EMAIL` / `ADMIN_PASSWORD` from `.env`). Menu image URLs are also synced from `agent/restaurant/menu.py` on every restart.

---

## Environment variables

| Name | Required | Notes |
|---|:---:|---|
| `GROQ_API_KEY` | ✓ | Fallback LLM + voice-pipeline fallback |
| `MISTRAL_API_KEY` | ✓ | Primary LLM + STT + TTS |
| `NVIDIA_API_KEY` | ✓ | Reserved for secondary fallback |
| `VOICE_ID` | ✓ | Mistral Voxtral voice uuid |
| `DATABASE_URL` | ✓ | e.g. `postgresql://user:pass@localhost/restaurant` |
| `REDIS_URL` | · | defaults to `redis://localhost:6379` |
| `JWT_SECRET_KEY` | ✓ | 32+ random chars |
| `JWT_EXPIRE_DAYS` | · | defaults to `7` |
| `ADMIN_EMAIL` · `ADMIN_PASSWORD` | ✓ | seeded on first run |
| `GOOGLE_API_KEY` | · | only on the Gemini Live branch |
| `GEMINI_MODEL` · `GEMINI_VOICE` | · | override Gemini model / voice |

---

## Key endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/auth/register` · `/auth/login` | returns JWT |
| `POST` | `/auth/ws-ticket` | single-use Redis ticket (carries user timezone) |
| `WS` | `/ws?ticket=…` | voice pipeline — audio in + audio/UI events out |
| `GET` | `/menu` · `/menu/{id}` | public catalog |
| `POST` / `PATCH` / `DELETE` | `/menu` · `/menu/{id}` | admin CRUD |
| `GET` | `/orders` · `/orders/current` · `/orders/{id}` | customer orders |
| `POST` | `/orders/current/items` | tap-to-add fallback (no voice) |
| `DELETE` | `/orders/current/items/{id}` | tap-to-remove |
| `DELETE` | `/orders/{id}` | cancel |
| `GET` | `/admin/orders?status=active\|all\|…` | kitchen feed |
| `PATCH` | `/admin/orders/{id}/status` | transition `paid` / `cancelled` |
| `GET` | `/admin/menu` | full catalog incl. disabled |
| `GET` | `/admin/analytics/summary?range=today\|7d\|30d\|all` | dashboard data |

Full OpenAPI docs at `http://localhost:8000/docs`.

---

## Tool catalogue (voice agent)

Each tool is a Pipecat "direct function" registered on the LLM. Every tool that touches UI pushes a `ui_event` frame in addition to returning a short text summary for the LLM to narrate.

| Tool | UI event | What it does |
|---|---|---|
| `search_menu` | `menu_results` | smart keyword search (name, category, dietary, spice) |
| `filter_menu` | `menu_results` | AND-composable filter |
| `get_menu_categories` | `menu_results` | full catalog |
| `add_to_order` · `remove_from_order` | `cart_view` | cart mutations |
| `view_order` | `cart_view` | current cart |
| `confirm_order` | `order_confirmed` | send to kitchen |
| `cancel_order` | `cart_view` | cancel (pre-payment) |
| `search_my_orders` | `orders_list` | history + per-status counts |
| `end_conversation` | `session_end` | close WS after closing line |
| `get_current_datetime` | — | timezone-aware clock |

Every connection re-prepends a fresh `CURRENT TIME CONTEXT` block with both the restaurant's IST time and the customer's local timezone so the agent never quotes stale times.

---

## Running tests

```bash
uv run pytest -q
```

Tests hit a real PostgreSQL database (`restaurant_test` by default — see `tests/conftest.py`). Each test rolls back its own transaction.

---

## Common tasks

**Add a new menu item without a REST call.** Edit `agent/restaurant/menu.py`, optionally add an `IMAGE_URLS` entry, restart — the seeder reconciles.

**Change bill rates** (service charge, GST). Edit `BILL_CHARGES` in `config.py`. Everything — voice narration, UI cards, REST responses, printed bill — rebuilds off that single source.

**Swap the primary LLM.** Edit `pipeline/voice_pipeline.py` — the service is `FallbackLLMService(api_key=MISTRAL, groq_api_key=GROQ, …)`. Swap to a different backend there.

**Generate a migration.**
```bash
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```
