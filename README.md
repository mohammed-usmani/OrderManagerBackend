# Saffron & Smoke — Server

Backend for a voice-first Indian restaurant. Guests talk to **Arjun**, the AI host, over one WebSocket that carries audio both ways plus structured UI events; staff run the restaurant from a role-based back-office (kitchen display, floor and tables, billing, menu, analytics).

> Companion frontend: [OrderManagerFrontend](https://github.com/mohammed-usmani/OrderManagerFrontend). The hosted backend is paused to save cost; run it locally with the steps below.

---

## What it does

- **Voice ordering** — a Pipecat pipeline around **Gemini Live native audio**: the caller's speech goes straight into one realtime model that listens, calls restaurant tools, and answers in speech. No separate STT or TTS.
- **Two call modes**
  - **Parcel** (takeaway/delivery): a returning customer is verified with their 4-digit code or phone **plus** the name and delivery pincode on the account (new ones register), then the delivery area is checked and the order taken.
  - **Dine-in**: the guest scans the table's QR code, so the call is already bound to that table; they can order and ask for the bill.
- **Live UI canvas** — tools push `ui_event` frames over the same socket (menu results, cart, customer card, delivery check, order confirmation, bill, order history) so the screen follows the conversation.
- **Back-office** — role-based access for owner, manager, cashier, waiter and chef: a real-time kitchen feed (Redis pub/sub → SSE), order edits/voids/refunds, table transfer and merge, floors/zones/tables with QR codes, 86-ing dishes, customers, staff, restaurant profile, charge policy and analytics.
- **Billing & payments** — context-aware charges (service, AC for dine-in AC zones, GST split into CGST/SGST), cash settlement, and Razorpay checkout (test mode) including pay-from-phone for dine-in tabs.

---

## Architecture

```
 Browser (Next.js client)                           Server (FastAPI)
 ────────────────────────                           ─────────────────────────────────────────
 POST /auth/ws-ticket ───────────────────────────▶  30 s single-use ticket in Redis
 WS /ws?ticket=…  ◀── audio (16 kHz in / 24 kHz out) + ui_event JSON ──▶
                                                    Pipecat pipeline
                                                      transport.input()
                                                      → user context aggregator (Silero VAD)
                                                      → GeminiLiveLLMService  ⇄ tools → services → Postgres
                                                      → transport.output()
                                                      → assistant context aggregator
 Admin pages ── REST (JWT) ─────────────────────▶  routers → services → repositories → models
 Kitchen display ── SSE /admin/orders/stream ◀───  Redis pub/sub "orders:events"
```

**Voice call lifecycle** (`main.py`, `/ws`)

1. The client gets a ticket from `POST /auth/ws-ticket` (no login needed — the voice line is anonymous). The ticket carries the caller's timezone and, for dine-in, the table's QR token.
2. `/ws` consumes the ticket (Redis `GETDEL`), then takes one of `MAX_CONCURRENT_CALLS` global slots (a Redis sorted set). When all lines are busy it closes with code `4003` and the client retries.
3. The pipeline starts with a fresh system prompt: the restaurant's current time, opening hours and the caller's mode (parcel or dine-in table).
4. A watchdog ends the call after `MAX_SESSION_SECONDS`, warning the client 60 s before (`time_warning`, then `session_end`).
5. When the caller hangs up, the disconnect handler cancels the pipeline so the slot is freed immediately.

**Layer rule:** `router → service → repository → model`. Services own business rules, routers only translate HTTP, and the voice agent's tools call services directly — they're just another front-end.

---

## Stack

| Layer | Choice |
|---|---|
| Language | Python 3.11 |
| HTTP | FastAPI + Uvicorn |
| Voice | [Pipecat](https://github.com/pipecat-ai/pipecat) + **Gemini Live native audio** (`gemini-3.1-flash-live-preview`, voice Charon) · Silero VAD |
| Database | PostgreSQL + **pgvector** · SQLAlchemy 2 · Alembic |
| Menu search | Mistral `mistral-embed` embeddings (semantic), falling back to keyword search |
| Realtime | Redis — WS tickets, call slots, JWT deny-list, order-event pub/sub |
| Auth | bcrypt + JWT (python-jose) in an httpOnly session cookie, roles: owner · manager · cashier · waiter · chef |
| Payments | Razorpay (test mode) + cash |
| Images | Cloudinary (optional) |
| Package mgmt | [uv](https://docs.astral.sh/uv/) |

---

## Project layout

```
server/
├── main.py                   FastAPI app, lifespan seeding, /health, /ws voice endpoint
├── config.py                 env loading + defaults (CHARGE_POLICY, call limits, …)
├── dependencies.py           current user, admin/staff/cashier guards
│
├── agent/
│   ├── brain.py              system prompt + time-context message
│   ├── session_state.py      per-call state (mode, table, customer, cart)
│   └── restaurant/menu.py    seed menu + image URLs
│
├── pipeline/
│   ├── voice_pipeline.py     Pipecat pipeline factory + the agent's tools
│   └── ui_events.py          push_ui_event helper
│
├── routers/                  auth, menu, orders, admin, analytics, customers,
│                             floors, zones, tables, table_sessions, service_areas,
│                             settings, staff, payments
├── services/                 business logic — orders & lifecycle, billing, payments,
│                             tables & floors, events (pub/sub), embeddings, roles,
│                             ratelimit, audit, settings, …
├── db/
│   ├── models/               users, menu, orders, customers, floors, dining zones,
│   │                         tables, table sessions, service areas, payments,
│   │                         audit log, app settings, chat
│   ├── repositories/         thin query helpers
│   └── seeds/                menu, admin, service areas, floor (+ manual demo seed)
│
├── migrations/               Alembic
├── tests/                    pytest against a real Postgres test database
├── docs/GEMINI_LIVE.md       notes on the Gemini Live voice engine
├── Dockerfile · docker-entrypoint.sh · docker-compose.yml
└── deploy.sh · DEPLOY.md     Cloud Run deployment
```

---

## Getting started

**Prerequisites:** Python 3.11, [uv](https://docs.astral.sh/uv/getting-started/installation/), PostgreSQL with the `vector` extension, Redis, and a [Google AI Studio](https://aistudio.google.com/) key.

The quickest way to get Postgres (with pgvector) and Redis is Docker:

```bash
docker compose up -d db redis        # Postgres on :5433, Redis on :6380
```

Then:

```bash
uv sync
cp .env.example .env                 # fill in keys; point DATABASE_URL/REDIS_URL at the ports above
uv run alembic upgrade head
uv run uvicorn main:app --reload --port 8000
```

Or run everything, API included: `docker compose up` (migrations run on boot).

On startup the server seeds the menu (only into an empty table; afterwards it just syncs image URLs), the admin user (`ADMIN_EMAIL` / `ADMIN_PASSWORD`), service areas and a default floor, loads settings into cache, and embeds any menu items that are missing vectors. `python -m db.seeds.demo_seed` adds demo data on request.

---

## Environment variables

| Name | Required | Default / notes |
|---|:---:|---|
| `DATABASE_URL` | ✓ | e.g. `postgresql://user:pass@localhost:5433/restaurant` |
| `JWT_SECRET_KEY` | ✓ | 32+ random characters |
| `ADMIN_EMAIL` · `ADMIN_PASSWORD` | ✓ | seeded owner account |
| `GOOGLE_API_KEY` | ✓ for voice | Google AI Studio key for Gemini Live |
| `GEMINI_MODEL` · `GEMINI_VOICE` | · | `models/gemini-3.1-flash-live-preview` · `Charon` |
| `REDIS_URL` | · | `redis://localhost:6379` |
| `JWT_EXPIRE_DAYS` | · | `7` |
| `CORS_ORIGINS` | ✓ in prod | comma-separated frontend origins allowed to use the session cookie; `http://localhost:3000` by default. Production: `https://order-manager.mohammedusmani.me` |
| `AUTH_COOKIE_SECURE` | · | `true`; set `false` only for local plain-http development |
| `SEED_ON_STARTUP` | · | `true`; seeds only empty tables. Set `false` once a deployment is set up |
| `MAX_CONCURRENT_CALLS` | · | `3` (Gemini free tier allows about 3 live sessions) |
| `MAX_SESSION_SECONDS` | · | `900` |
| `VOICE_IDLE_SECONDS` | · | `90`; a call where nobody speaks for this long is ended (with a notice) |
| `MISTRAL_API_KEY` | · | semantic menu search; keyword search without it |
| `MISTRAL_EMBED_MODEL` · `EMBEDDING_DIM` | · | `mistral-embed` · `1024` |
| `RAZORPAY_KEY_ID` · `RAZORPAY_KEY_SECRET` · `RAZORPAY_WEBHOOK_SECRET` | · | cash-only when unset |
| `CLOUDINARY_URL` | · | menu photo uploads; admins paste image URLs without it |
| `PORT` | · | `8000` (`8080` in the container) |
| `FORWARDED_ALLOW_IPS` | ✓ behind a proxy | proxy address/range whose `X-Forwarded-For` is trusted (default `127.0.0.1`). Without it every caller looks like the proxy and the per-IP rate limits become global |
| `RUN_MIGRATIONS` | · | container only; `false` skips `alembic upgrade head` on boot |

---

## API overview

Full OpenAPI docs at `http://localhost:8000/docs`. Access levels: **public**, **user** (any login), **staff** (any staff role), **cashier** (owner/manager/cashier), **admin** (owner/manager).

| Prefix | What | Access |
|---|---|---|
| `/auth` | register, login (set the session cookie), `me`, logout (revokes + clears it), `ws-ticket` | public |
| `WS /ws?ticket=…` | voice call | ticket |
| `/menu` | catalog read · CRUD, image upload, re-embed | public · admin |
| `/orders` | a customer's orders and cart | user |
| `/admin/orders` · `/admin/orders/stream` (SSE) | kitchen feed, status changes, cancel | staff |
| `/admin` edits · voids · refunds | order corrections (audited) | cashier |
| `/admin/analytics` | overview, time series, peak hours | admin |
| `/tables` | QR resolve, guest tab, call waiter · floor view · CRUD | public · staff · admin |
| `/table-sessions` | view · settle, transfer, merge | staff · cashier |
| `/floors` · `/zones` · `/service-areas` | layout and delivery areas | admin |
| `/customers` | customer records | admin |
| `/staff` | staff accounts and roles | owner/manager |
| `/settings` | restaurant profile (public read) · charge policy | public · admin |
| `/payments` | quote, Razorpay order/verify/webhook · cash | public · cashier |
| `/health` · `/ready` | liveness · readiness (Postgres + Redis, 503 if either is down) | public |

---

## Voice agent tools

Each tool is a Pipecat direct function (exposed to the model with a `pc_` prefix). Tools that change what's on screen also push a `ui_event`.

| Tool | Mode | UI event | What it does |
|---|---|---|---|
| `search_menu` | both | `menu_results` | semantic + keyword search |
| `filter_menu` | both | `menu_results` | filter by category, dietary, spice, price, keyword |
| `get_menu_categories` | both | `menu_results` | menu overview |
| `add_to_order` · `update_quantity` · `remove_from_order` · `view_order` | both | `cart_view` | cart |
| `confirm_order` | both | `order_confirmed` | send to the kitchen |
| `cancel_order` | both | `cart_view` | cancel before payment |
| `end_conversation` | both | `session_end` | hang up after the closing line |
| `get_current_datetime` | both | — | restaurant time + caller's timezone |
| `lookup_customer` · `register_customer` · `update_customer` | parcel | `customer_card` | verify (code/phone + name + pincode, 3 tries per call), register (never an existing phone), edit |
| `check_delivery_area` | parcel | `delivery_check` | area/pincode allowlist |
| `search_my_orders` | parcel | `orders_list` | order history |
| `request_bill` | dine-in | `bill_requested` | ask for the bill |

The server itself also sends `time_warning` and `session_end` when a call reaches its time limit.

---

## Orders and billing

- **Order lifecycle** (`services/order_lifecycle.py`)
  - dine-in: `cart → confirmed → cooking → served → paid`
  - parcel: `cart → confirmed → cooking → ready → delivered → paid`
  - either can be `cancelled`
- **Charges** come from `CHARGE_POLICY` in `config.py` (service 10 %, AC 5 % for dine-in in AC zones, GST 5 % shown as CGST + SGST). Admins can override it at runtime from **Pricing** (`/settings/charge-policy`); the override is stored in `app_settings`. Voice narration, UI cards, REST responses and printed bills all use the same calculation.
- Voids, refunds, settlements, transfers and merges are written to the audit log.

---

## Tests

```bash
uv run pytest -q
```

Tests run against a real PostgreSQL database and Redis — the docker-compose ones by default:

```bash
docker compose up -d db redis
docker compose exec db psql -U postgres -c "CREATE DATABASE restaurant_test;"   # once
```

Override with `TEST_DATABASE_URL` / `TEST_REDIS_URL` (the tests use Redis index 15 and clear it per test). Each test runs in a transaction that is rolled back, and the app is pointed at the test database, so nothing touches the `.env` database. Importing `config` still needs the required env vars, so keep a `.env` in place.

---

## Deployment

The backend ships as a Docker image that runs as an unprivileged user and listens on `$PORT`; the frontend is on **Vercel** at `order-manager.mohammedusmani.me`, with the API at `backend-saffron.mohammedusmani.me` (same site, so the session cookie works). The container runs `alembic upgrade head` on boot — several instances can boot at once, since migrations take a Postgres advisory lock — then starts the app. Point the host's health check at `/ready`. [`DEPLOY.md`](DEPLOY.md) still describes the earlier Cloud Run setup.

---

## Common tasks

**Add a menu item.** Use the admin Menu page, or `POST /menu`. Editing `agent/restaurant/menu.py` only seeds a fresh, empty database; on an existing one it just syncs image URLs.

**Change charges.** Edit them on the admin Pricing page. `CHARGE_POLICY` in `config.py` is only the default.

**Change the voice or model.** Set `GEMINI_VOICE` / `GEMINI_MODEL`.

**Generate a migration.**
```bash
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```
