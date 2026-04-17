"""Voice pipeline factory: creates a Pipecat pipeline per WebSocket connection.

Voice-only. Each tool:
  1. Fetches structured data from the DB.
  2. Pushes a UI event (OutputTransportMessageUrgentFrame) to the client so
     the frontend can render cards.
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
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from agent.brain import SYSTEM_PROMPT, build_time_context_message
from config import GROQ_API_KEY, MISTRAL_API_KEY, VOICE_ID
from db.base import get_session
from db.repositories.menu_repo import MenuRepo
from pipeline.fallback_llm import FallbackLLMService
from pipeline.ui_events import (
    menu_item_to_card,
    order_to_card,
    push_ui_event,
)
from pipeline.voxtral_stt import VoxtralSTTService
from pipeline.voxtral_tts import VoxtralTTSService
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
        """Search the restaurant menu by dish name or item ID.

        Any matching dishes are rendered as cards on the customer's screen.
        In your spoken reply, just name the top 2-3 options and their prices —
        don't dump full descriptions since the UI shows that.

        Args:
            query: Dish name or ID to search for.
        """
        stop = _loop_guard("pc_search_menu", f"q={query}")
        if stop:
            await params.result_callback(stop)
            return

        with get_session() as db:
            service = MenuService(db)
            items: list = []
            try:
                items = [service.get_item(query.upper())]
            except ValueError:
                items = service.find_by_name(query)

            cards = [menu_item_to_card(i) for i in items]

        await push_ui_event(params.llm, "menu_results", {"title": f"Results for '{query}'", "items": cards})

        if not cards:
            msg = f"No matches for '{query}'."
        else:
            names = ", ".join(f"{c['name']} (₹{c['price']})" for c in cards[:3])
            more = f" and {len(cards) - 3} more" if len(cards) > 3 else ""
            msg = f"Showing {len(cards)} match(es) on screen: {names}{more}."
        await params.result_callback(msg)

    async def pc_get_menu_categories(params: FunctionCallParams) -> None:
        """Show an overview of the full menu grouped by category.

        The full menu is rendered on the customer's screen. In your spoken
        reply, just name the categories available — don't list every dish.
        """
        stop = _loop_guard("pc_get_menu_categories", "")
        if stop:
            await params.result_callback(stop)
            return

        with get_session() as db:
            items = MenuService(db).list_items(include_unavailable=False)
            cards = [menu_item_to_card(i) for i in items]

        await push_ui_event(params.llm, "menu_results", {"title": "Our Menu", "items": cards})

        categories = sorted({c["category"] for c in cards})
        msg = f"Full menu shown. Categories: {', '.join(categories)}."
        await params.result_callback(msg)

    # --- Cart tools -------------------------------------------------------

    async def pc_view_order(params: FunctionCallParams) -> None:
        """Show the customer's current in-progress cart.

        Renders the cart on screen. Your spoken reply should be a one-liner
        (item count + total) — the UI shows the breakdown.
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
            msg = f"Cart: {card['item_count']} item(s), total ₹{card['total']}."
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
        await params.result_callback(
            f"Order #{card['id'][:8]} confirmed — ₹{card['total']}. "
            "Kitchen has it."
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
            msg = f"Your order history is on screen. Summary: {summary}."
        await params.result_callback(msg)

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
        pc_get_menu_categories,
        pc_view_order,
        pc_add_to_order,
        pc_remove_from_order,
        pc_confirm_order,
        pc_cancel_order,
        pc_search_my_orders,
        pc_get_current_datetime,
    ]


# --- Pipeline factory ---------------------------------------------------


def create_pipeline(
    websocket: WebSocket,
    user_id: str = None,
    user_timezone: str | None = None,
):
    """Create a fresh voice pipeline for a single client connection."""
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            serializer=ProtobufFrameSerializer(),
        ),
    )

    stt = VoxtralSTTService(api_key=MISTRAL_API_KEY)

    system_instruction = (
        build_time_context_message(user_timezone) + "\n\n" + SYSTEM_PROMPT
    )

    llm = FallbackLLMService(
        api_key=MISTRAL_API_KEY,
        groq_api_key=GROQ_API_KEY,
        groq_model="llama-3.3-70b-versatile",
        settings=FallbackLLMService.Settings(
            model="mistral-large-latest",
            system_instruction=system_instruction,
        ),
    )

    tool_fns = _make_tool_wrappers(user_id or "", user_timezone)
    tool_schemas = []
    for tool_fn in tool_fns:
        llm.register_direct_function(tool_fn)
        wrapper = DirectFunctionWrapper(tool_fn)
        tool_schemas.append(wrapper.to_function_schema())

    tts = VoxtralTTSService(api_key=MISTRAL_API_KEY, voice_id=VOICE_ID)

    context = LLMContext()
    context.set_tools(ToolsSchema(standard_tools=tool_schemas))
    context_pair = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            context_pair.user(),
            llm,
            tts,
            transport.output(),
            context_pair.assistant(),
        ]
    )

    return pipeline
