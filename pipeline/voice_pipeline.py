"""Voice pipeline factory: creates a Pipecat pipeline per WebSocket connection.

Gemini Live Native Audio variant: Gemini handles STT + LLM + TTS natively, so
the pipeline is just `transport.input -> user -> gemini -> transport.output
-> assistant`.

Each tool:
  1. Fetches structured data from the DB.
  2. Pushes a UI event (OutputTransportMessageUrgentFrame) to the client so
     the frontend can render cards. Gemini's FrameProcessor forwards unknown
     frames downstream, so this still reaches the transport unchanged.
  3. Returns a short text summary for the LLM to narrate.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import WebSocket

from pipecat.adapters.schemas.direct_function import DirectFunctionWrapper
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.services.google.gemini_live import GeminiLiveLLMService
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMSettings
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from agent.brain import SYSTEM_PROMPT, build_time_context_message
from config import GEMINI_MODEL, GEMINI_VOICE, GOOGLE_API_KEY
from db.base import get_session
from db.repositories.menu_repo import MenuRepo
from pipeline.ui_events import (
    menu_item_to_card,
    order_to_card,
    push_ui_event,
)
from services.menu_service import MenuService
from services.order_service import OrderService

RESTAURANT_TZ = ZoneInfo("Asia/Kolkata")


def _resolve_tz(name: str | None) -> ZoneInfo:
    if name:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return RESTAURANT_TZ


def _format_when(dt: datetime | None, tz: ZoneInfo) -> str:
    if dt is None:
        return "unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%b %d, %I:%M %p %Z")


def _make_tool_wrappers(user_id: str, user_timezone: str | None = None):
    """Create Pipecat tool wrappers scoped to one WebSocket connection.

    Each wrapper:
      - does its DB work,
      - pushes a UI event for the frontend,
      - returns a short text summary that the LLM reads (and narrates).
    """
    tz = _resolve_tz(user_timezone)

    # Loop guard: protects against LLMs that get stuck calling the same tool
    # repeatedly instead of replying.
    MAX_REPEATS = 2
    recent_calls: dict[str, list[str]] = {}

    def _loop_guard(name: str, signature: str) -> str | None:
        history = recent_calls.setdefault(name, [])
        history.append(signature)
        if len(history) > MAX_REPEATS + 1:
            history.pop(0)
        if len(history) > MAX_REPEATS and all(a == signature for a in history):
            recent_calls[name] = []
            return (
                f"STOP LOOPING. You have already called {name} with these "
                f"arguments {MAX_REPEATS + 1} times in a row. Use the data "
                "you already have and respond to the user with plain text."
            )
        return None

    # --- Menu tools -------------------------------------------------------

    async def pc_search_menu(params: FunctionCallParams, query: str) -> None:
        """Search the menu with freeform keywords.

        Matches tokens in the query against dish name, description, taste
        profile, preparation notes, category, spice level, and dietary tags.
        Ranks by how many tokens hit.

        Use for fuzzy or intent-style queries like "spicy", "paneer vegan",
        "something creamy". For structured filters (e.g. "starters under
        ₹400") use filter_menu instead.

        Dishes show on the customer's screen — speak only the top 2-3 names
        and their prices.

        Args:
            query: Freeform search terms (e.g. "chicken tikka", "spicy",
                "vegan dessert").
        """
        stop = _loop_guard("pc_search_menu", f"q={query}")
        if stop:
            await params.result_callback(stop)
            return

        with get_session() as db:
            service = MenuService(db)
            items: list = []
            # Exact ID hit first (e.g. "M01").
            try:
                items = [service.get_item(query.strip().upper())]
            except ValueError:
                items = service.search(query)

            cards = [menu_item_to_card(i) for i in items]

        await push_ui_event(
            params.llm,
            "menu_results",
            {"title": f"Results for '{query}'", "items": cards},
        )

        if not cards:
            msg = f"No matches for '{query}'."
        else:
            # Include every item's ID so the LLM has the exact IDs it needs
            # to call add_to_order next. Rendering is handled by the UI card;
            # the spoken reply should still be short (system prompt enforces).
            lines = [f"{len(cards)} match(es) for '{query}':"]
            for c in cards:
                lines.append(
                    f"  - {c['name']} [id={c['id']}] — ₹{c['price']} ({c['category']})"
                )
            msg = "\n".join(lines)
        await params.result_callback(msg)

    async def pc_filter_menu(
        params: FunctionCallParams,
        category: str = "",
        dietary: str = "",
        spice_level: str = "",
        max_price: float = 0,
        keyword: str = "",
    ) -> None:
        """Filter the menu by one or more structured criteria (AND).

        Use when the customer combines constraints like "vegan mains under
        ₹400" or "mild starters". For a single freeform word like "spicy"
        or dish name, prefer search_menu.

        Matching dishes render as cards on screen.

        Args:
            category: One of: starters, mains, breads, rice, desserts, beverages.
                Empty = any category.
            dietary: Comma-separated tags like "vegan", "gluten-free",
                "vegetarian". All listed tags must match.
            spice_level: e.g. "mild", "medium", "spicy". Empty = any.
            max_price: Upper price bound in rupees. 0 = no limit.
            keyword: Additional freeform terms to narrow the filter further.
        """
        sig = f"c={category}|d={dietary}|s={spice_level}|p={max_price}|k={keyword}"
        stop = _loop_guard("pc_filter_menu", sig)
        if stop:
            await params.result_callback(stop)
            return

        dietary_list = [t.strip() for t in dietary.split(",") if t.strip()]
        max_price_val = float(max_price) if max_price and max_price > 0 else None

        with get_session() as db:
            service = MenuService(db)
            items = service.filter(
                category=category or None,
                dietary=dietary_list or None,
                spice_level=spice_level or None,
                max_price=max_price_val,
                keyword=keyword or None,
            )
            cards = [menu_item_to_card(i) for i in items]

        parts = []
        if category:
            parts.append(category)
        if dietary_list:
            parts.append(" ".join(dietary_list))
        if spice_level:
            parts.append(spice_level)
        if max_price_val:
            parts.append(f"under ₹{int(max_price_val)}")
        if keyword:
            parts.append(f'"{keyword}"')
        title = "Menu filter: " + (", ".join(parts) if parts else "all")

        await push_ui_event(
            params.llm,
            "menu_results",
            {"title": title, "items": cards},
        )

        if not cards:
            msg = "No dishes match those filters."
        else:
            lines = [f"{len(cards)} match(es) for filter {title}:"]
            for c in cards:
                lines.append(
                    f"  - {c['name']} [id={c['id']}] — ₹{c['price']} ({c['category']})"
                )
            msg = "\n".join(lines)
        await params.result_callback(msg)

    async def pc_get_menu_categories(params: FunctionCallParams) -> None:
        """Show an overview of the full menu grouped by category.

        The full menu is rendered on the customer's screen. In your spoken
        reply, just name the categories available — don't list every dish.
        The text response (LLM-only) includes every item's ID so you can
        resolve any dish the customer mentions without a second search.
        """
        stop = _loop_guard("pc_get_menu_categories", "")
        if stop:
            await params.result_callback(stop)
            return

        with get_session() as db:
            items = MenuService(db).list_items(include_unavailable=False)
            cards = [menu_item_to_card(i) for i in items]

        await push_ui_event(params.llm, "menu_results", {"title": "Our Menu", "items": cards})

        # Group by category with full id,name,price list so the LLM can map
        # any spoken dish name to its exact id without another tool call.
        by_cat: dict[str, list[dict]] = {}
        for c in cards:
            by_cat.setdefault(c["category"], []).append(c)
        lines = ["Full menu:"]
        for cat in sorted(by_cat.keys()):
            lines.append(f"  {cat}:")
            for c in by_cat[cat]:
                lines.append(f"    - {c['name']} [id={c['id']}] — ₹{c['price']}")
        msg = "\n".join(lines)
        await params.result_callback(msg)

    # --- Cart tools -------------------------------------------------------

    async def pc_view_order(params: FunctionCallParams) -> None:
        """Show the customer's current in-progress cart.

        Renders the full cart on screen. The text response includes the
        menu_item_id of every line so you can reference them when the
        customer asks to remove something. Your spoken reply should still
        be a one-liner (count + total); the UI shows the breakdown.
        """
        stop = _loop_guard("pc_view_order", "")
        if stop:
            await params.result_callback(stop)
            return

        with get_session() as db:
            service = OrderService(db)
            cart = service.get_or_create_cart(user_id)
            menu_repo = MenuRepo(db)
            card = order_to_card(cart, menu_repo)

        await push_ui_event(params.llm, "cart_view", card)

        if not card["items"]:
            msg = "Your cart is empty."
        else:
            # Full breakdown so the LLM knows every item_id and can act on
            # pre-existing items across conversation / process restarts.
            lines = [
                f"Cart (#{card['id'][:8]}) — {card['item_count']} item(s):"
            ]
            for it in card["items"]:
                note = f" ({it['special_instructions']})" if it["special_instructions"] else ""
                lines.append(
                    f"  - {it['quantity']}× {it['name']} [id={it['menu_item_id']}] — ₹{it['line_total']}{note}"
                )
            lines.append(f"Subtotal: ₹{card['subtotal']:.2f}")
            for ch in card["charges"]:
                lines.append(f"  + {ch['label']}: ₹{ch['amount']:.2f}")
            lines.append(f"Total (incl. charges): ₹{card['total']:.2f}")
            msg = "\n".join(lines)
        await params.result_callback(msg)

    async def pc_add_to_order(
        params: FunctionCallParams,
        item_id: str,
        quantity: int = 1,
        special_instructions: str = "",
    ) -> None:
        """Add an item to the customer's cart.

        Only call after verifying the item_id via search_menu/get_menu_categories.

        Args:
            item_id: The menu item ID (e.g. 'M01').
            quantity: Number of this item.
            special_instructions: Special requests (optional).
        """
        sig = f"{item_id}|{quantity}|{special_instructions}"
        stop = _loop_guard("pc_add_to_order", sig)
        if stop:
            await params.result_callback(stop)
            return

        with get_session() as db:
            service = OrderService(db)
            menu_repo = MenuRepo(db)
            cart = service.get_or_create_cart(user_id)
            try:
                service.add_item(cart.id, item_id, quantity, special_instructions)
            except ValueError as e:
                await params.result_callback(str(e))
                return
            db.refresh(cart)
            card = order_to_card(cart, menu_repo)
            added = menu_repo.get_by_id(item_id)
            added_name = added.name if added else item_id

        await push_ui_event(params.llm, "cart_view", card)

        msg = (
            f"Added {quantity}× {added_name} to the cart. "
            f"Cart total is now ₹{card['total']}."
        )
        await params.result_callback(msg)

    async def pc_remove_from_order(params: FunctionCallParams, item_id: str) -> None:
        """Remove an item from the cart.

        Args:
            item_id: The menu item ID to remove.
        """
        stop = _loop_guard("pc_remove_from_order", item_id)
        if stop:
            await params.result_callback(stop)
            return

        with get_session() as db:
            service = OrderService(db)
            menu_repo = MenuRepo(db)
            cart = service.get_or_create_cart(user_id)
            removed = menu_repo.get_by_id(item_id)
            removed_name = removed.name if removed else item_id
            try:
                service.remove_item(cart.id, item_id)
            except ValueError as e:
                await params.result_callback(str(e))
                return
            db.refresh(cart)
            card = order_to_card(cart, menu_repo)

        await push_ui_event(params.llm, "cart_view", card)
        await params.result_callback(
            f"Removed {removed_name}. Cart total is ₹{card['total']}."
        )

    async def pc_confirm_order(params: FunctionCallParams) -> None:
        """Confirm the cart and send it to the kitchen.

        Only call when the user has explicitly said they're done.
        """
        stop = _loop_guard("pc_confirm_order", "")
        if stop:
            await params.result_callback(stop)
            return

        with get_session() as db:
            service = OrderService(db)
            menu_repo = MenuRepo(db)
            cart = service.get_or_create_cart(user_id)
            try:
                order = service.confirm_order(cart.id)
            except ValueError as e:
                await params.result_callback(str(e))
                return
            db.refresh(order)
            card = order_to_card(order, menu_repo)

        await push_ui_event(params.llm, "order_confirmed", card)
        charges_str = ", ".join(
            f"{c['label'].lower()} ₹{c['amount']:.2f}" for c in card["charges"]
        )
        await params.result_callback(
            f"Order #{card['id'][:8]} confirmed. Subtotal ₹{card['subtotal']:.2f}; "
            f"{charges_str}; grand total ₹{card['total']:.2f}. Kitchen has it."
        )

    async def pc_cancel_order(params: FunctionCallParams) -> None:
        """Cancel the cart (only works before payment)."""
        stop = _loop_guard("pc_cancel_order", "")
        if stop:
            await params.result_callback(stop)
            return

        with get_session() as db:
            service = OrderService(db)
            menu_repo = MenuRepo(db)
            cart = service.get_or_create_cart(user_id)
            if cart.status == "confirmed":
                await params.result_callback(
                    "Already confirmed — please speak to the manager."
                )
                return
            try:
                service.cancel_order(cart.id)
            except ValueError as e:
                await params.result_callback(str(e))
                return
            new_cart = service.get_or_create_cart(user_id)
            card = order_to_card(new_cart, menu_repo)

        await push_ui_event(params.llm, "cart_view", card)
        await params.result_callback("Cart cancelled.")

    # --- Order history ----------------------------------------------------

    async def pc_search_my_orders(
        params: FunctionCallParams,
        status: str = "",
        limit: int = 5,
    ) -> None:
        """Search the customer's past orders, optionally filtered by status.

        Orders are rendered as cards on screen. Your spoken reply is a summary
        ("You have 3 confirmed and 1 cancelled") — the UI shows the details.

        Args:
            status: Optional filter: cart | confirmed | awaiting_payment | paid | cancelled.
            limit: Max cards to render (default 5).
        """
        stop = _loop_guard("pc_search_my_orders", f"s={status}|l={limit}")
        if stop:
            await params.result_callback(stop)
            return

        status = (status or "").strip().lower()
        valid = {"cart", "confirmed", "awaiting_payment", "paid", "cancelled"}
        if status and status not in valid:
            await params.result_callback(
                f"Unknown status. Valid: {', '.join(sorted(valid))}."
            )
            return

        with get_session() as db:
            service = OrderService(db)
            menu_repo = MenuRepo(db)
            all_orders = service.get_orders(user_id)
            counts: dict[str, int] = {}
            for o in all_orders:
                counts[o.status] = counts.get(o.status, 0) + 1
            matches = [o for o in all_orders if not status or o.status == status]
            cards = [order_to_card(o, menu_repo) for o in matches[:limit]]

        title = f"Orders ({status})" if status else "Your Orders"
        await push_ui_event(
            params.llm,
            "orders_list",
            {"title": title, "orders": cards, "counts": counts},
        )

        if not all_orders:
            msg = "You don't have any orders yet."
        elif not matches:
            msg = f"No orders with status '{status}'."
        else:
            summary = ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))
            lines = [f"Order history — {summary}:"]
            for c in cards:
                lines.append(
                    f"  - #{c['id'][:8]} {c['status']} — {c['item_count']} item(s) — ₹{c['total']}"
                )
            msg = "\n".join(lines)
        await params.result_callback(msg)

    # --- Session control --------------------------------------------------

    async def pc_end_conversation(
        params: FunctionCallParams,
        reason: str = "goodbye",
    ) -> None:
        """End the voice conversation.

        Call this ONLY when the customer clearly wants to stop (says
        goodbye / thanks that's all / see you / bye), OR after confirm_order
        succeeds AND the customer doesn't have follow-up questions.

        Your spoken reply right before this tool should be a short, warm
        closing ("Enjoy your meal, see you soon!"). The client waits for
        your audio to finish playing before it disconnects, so do NOT call
        another tool after this one — the session is ending.

        Args:
            reason: Short label for logs — "goodbye", "after_payment",
                "user_hangup", etc.
        """
        await push_ui_event(params.llm, "session_end", {"reason": reason})
        await params.result_callback(
            "Session ending — the mic will close after your closing line "
            "finishes playing. Do not call any more tools."
        )

    # --- Datetime (no UI; just text) -------------------------------------

    async def pc_get_current_datetime(params: FunctionCallParams) -> None:
        """Current date/time in restaurant (IST) and customer timezones."""
        stop = _loop_guard("pc_get_current_datetime", "")
        if stop:
            await params.result_callback(stop)
            return

        now = datetime.now(RESTAURANT_TZ)
        rest = now.strftime("%A, %B %d, %Y at %I:%M %p %Z")
        if tz != RESTAURANT_TZ:
            user = now.astimezone(tz).strftime("%A, %B %d, %Y at %I:%M %p %Z")
            msg = f"Restaurant (IST): {rest} | Customer ({user_timezone}): {user}"
        else:
            msg = f"Restaurant (IST): {rest}"
        await params.result_callback(msg)

    return [
        pc_search_menu,
        pc_filter_menu,
        pc_get_menu_categories,
        pc_view_order,
        pc_add_to_order,
        pc_remove_from_order,
        pc_confirm_order,
        pc_cancel_order,
        pc_search_my_orders,
        pc_end_conversation,
        pc_get_current_datetime,
    ]


# --- Pipeline factory ---------------------------------------------------


def create_pipeline(
    websocket: WebSocket,
    user_id: str = None,
    user_timezone: str | None = None,
):
    """Create a fresh Gemini Live Native Audio pipeline per connection."""
    if not GOOGLE_API_KEY:
        raise RuntimeError(
            "GOOGLE_API_KEY not set — required for Gemini Live Native Audio. "
            "Get a key from https://aistudio.google.com/ and put it in .env."
        )

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_out_sample_rate=24000,  # Gemini Live emits 24 kHz mono PCM16
            audio_out_channels=1,
            serializer=ProtobufFrameSerializer(),
        ),
    )

    # Fresh per-connection time context prepended to the base prompt.
    system_instruction = (
        build_time_context_message(user_timezone) + "\n\n" + SYSTEM_PROMPT
    )

    # Collect tool schemas up front. Pass tools at init time ONLY — if we also
    # put them on the LLMContext, Pipecat treats that as a change-at-runtime
    # and forces a reconnect (during which audio is dropped).
    tool_fns = _make_tool_wrappers(user_id or "", user_timezone)
    tool_schemas = [DirectFunctionWrapper(f).to_function_schema() for f in tool_fns]
    tools = ToolsSchema(standard_tools=tool_schemas)

    llm = GeminiLiveLLMService(
        api_key=GOOGLE_API_KEY,
        system_instruction=system_instruction,
        tools=tools,
        settings=GeminiLiveLLMSettings(
            model=GEMINI_MODEL,
            voice=GEMINI_VOICE,
            language="en-US",
        ),
    )

    for tool_fn in tool_fns:
        llm.register_direct_function(tool_fn)

    # Universal context + aggregator (new API; the service's
    # create_context_aggregator helper is deprecated in 0.0.108).
    # VAD lives on the user aggregator per Pipecat's new convention.
    # NOTE: don't set tools on the context — init-time tools are already
    # active, and adding them here would trigger an unnecessary reconnect.
    context = LLMContext()
    agg = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            agg.user(),
            llm,
            transport.output(),
            agg.assistant(),
        ]
    )

    return pipeline
