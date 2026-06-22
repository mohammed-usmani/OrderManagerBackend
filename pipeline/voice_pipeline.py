"""Voice pipeline factory: creates a Pipecat pipeline per WebSocket connection.

Gemini Live Native Audio variant: Gemini handles STT + LLM + TTS natively, so
the pipeline is just `transport.input -> user -> gemini -> transport.output
-> assistant`.

The line is PUBLIC and anonymous — there is no logged-in user. A caller is
tied to a customer record only once the agent identifies them mid-call (via
lookup_customer / register_customer); that identity lives in a per-connection
CallSession the cart/order tools read from.

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

from agent.brain import build_system_prompt, build_time_context_message
from agent.session_state import CallSession
from services.order_lifecycle import OrderType
from config import GEMINI_MODEL, GEMINI_VOICE, GOOGLE_API_KEY
from db.base import get_session
from db.repositories.customer_repo import CustomerRepo
from db.repositories.menu_repo import MenuRepo
from pipeline.ui_events import (
    customer_to_card,
    menu_item_to_card,
    order_to_card,
    push_ui_event,
)
from loguru import logger

from services.customer_service import CustomerService
from services.menu_service import MenuService
from services.order_service import OrderService
from services.service_area_service import ServiceAreaService
from services.table_service import TableService

RESTAURANT_TZ = ZoneInfo("Asia/Kolkata")

# Returned by cart/order tools when the agent hasn't identified the caller yet.
_NEED_CUSTOMER = (
    "No customer is identified for this call yet. First ask whether they're a "
    "returning customer (then call lookup_customer with their code or phone) or "
    "new (collect name, phone, and full delivery address, then call "
    "register_customer). Do not build an order until a customer is identified."
)


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


def _make_tool_wrappers(session: CallSession, user_timezone: str | None = None):
    """Create Pipecat tool wrappers scoped to one WebSocket connection.

    Tools share a mutable `session`; once the caller is identified, the
    cart/order tools operate on that customer's cart.
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

    def _cart(service: OrderService):
        """The active cart for this call — table tab (dine-in) or customer (parcel)."""
        if session.is_dine_in:
            cart = service.get_or_create_cart_for_table(
                session.table_id,
                zone_name=session.zone_name,
                is_ac=session.is_ac,
                floor_name=session.floor_name,
            )
            session.table_session_id = cart.table_session_id
            return cart
        return service.get_or_create_cart_for_customer(session.customer_id)

    def _need_msg() -> str:
        """Why an order tool refused — depends on the call mode."""
        if session.is_dine_in:
            return (
                "I don't know which table this is yet. Ask the guest for their "
                "table number or the code on the QR card, then call set_table."
            )
        return _NEED_CUSTOMER

    # --- Menu tools -------------------------------------------------------

    async def pc_search_menu(params: FunctionCallParams, query: str) -> None:
        """Search the menu with freeform keywords or intent.

        Matches the query against dish name, description, taste profile,
        preparation notes, category, spice level, and dietary tags, and also
        ranks by semantic similarity, so vague requests like "comfort food for
        a rainy day" or "something creamy and mild" work as well as exact terms
        like "paneer" or an item ID like "M01".

        Dishes show on the customer's screen — speak only the top 2-3 names
        and their prices.

        Args:
            query: Freeform search terms (e.g. "chicken tikka", "spicy",
                "vegan dessert", "comfort food").
        """
        stop = _loop_guard("pc_search_menu", f"q={query}")
        if stop:
            await params.result_callback(stop)
            return

        with get_session() as db:
            service = MenuService(db)
            items: list = []
            # Exact ID hit first (e.g. "M01"). Include unavailable so an exact
            # ID for a temporarily-unavailable dish surfaces it (the card shows
            # the unavailable state) rather than falling through to fuzzy search.
            try:
                items = [service.get_item(query.strip().upper(), include_unavailable=True)]
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
            lines = [f"{len(cards)} match(es) for '{query}':"]
            for c in cards:
                lines.append(
                    f"  - {c['name']} [id={c['id']}] — Rs {c['price']} ({c['category']})"
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
        Rs 400" or "mild starters". For a single freeform word like "spicy"
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
            parts.append(f"under Rs {int(max_price_val)}")
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
                    f"  - {c['name']} [id={c['id']}] — Rs {c['price']} ({c['category']})"
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

        by_cat: dict[str, list[dict]] = {}
        for c in cards:
            by_cat.setdefault(c["category"], []).append(c)
        lines = ["Full menu:"]
        for cat in sorted(by_cat.keys()):
            lines.append(f"  {cat}:")
            for c in by_cat[cat]:
                lines.append(f"    - {c['name']} [id={c['id']}] — Rs {c['price']}")
        msg = "\n".join(lines)
        await params.result_callback(msg)

    # --- Customer identity tools -----------------------------------------

    async def pc_lookup_customer(
        params: FunctionCallParams, code_or_phone: str
    ) -> None:
        """Look up a RETURNING customer by their 4-digit code or phone number.

        On a match, the rest of the call is tied to that customer and you get
        back their name, delivery address, preferences and allergies — greet
        them by name and confirm the address on file before ordering. On no
        match, offer to register them as a new customer.

        Args:
            code_or_phone: The 4-digit code they quote (e.g. "4821") or their
                phone number.
        """
        stop = _loop_guard("pc_lookup_customer", code_or_phone)
        if stop:
            await params.result_callback(stop)
            return

        with get_session() as db:
            cust = CustomerService(db).lookup(code_or_phone)
            if not cust:
                await params.result_callback(
                    f"No customer found for '{code_or_phone}'. Ask if they'd like "
                    "to register as new — collect name, phone, and full address."
                )
                return
            session.identify(cust)
            card = customer_to_card(cust)

        await push_ui_event(params.llm, "customer_card", card)
        bits = [f"Welcome back {card['name'] or 'customer'} (code {card['code']})."]
        if card["address_line"]:
            addr = card["address_line"]
            if card["area"]:
                addr += f", {card['area']}"
            if card["pincode"]:
                addr += f" {card['pincode']}"
            bits.append(f"Address on file: {addr}.")
        if card["preferences"]:
            bits.append(f"Preferences: {card['preferences']}.")
        if card["allergies"]:
            bits.append(f"Avoid (allergies): {card['allergies']}.")
        bits.append(
            "Greet them by name, confirm delivery to the address on file "
            "(or ask if it changed), then take their order."
        )
        await params.result_callback(" ".join(bits))

    async def pc_register_customer(
        params: FunctionCallParams,
        name: str,
        phone: str,
        address: str,
        area: str = "",
        pincode: str = "",
        landmark: str = "",
        preferences: str = "",
        allergies: str = "",
    ) -> None:
        """Register a NEW customer after collecting their details.

        IMPORTANT: this checks the delivery area first. If the area/pincode is
        outside our delivery zone, registration is REFUSED — apologize and do
        not take an order. On success, a 4-digit code is assigned; read it back
        digit by digit and tell them to keep it for next time.

        Args:
            name: Customer's name.
            phone: Phone number.
            address: Full delivery address (flat/building/street).
            area: Locality/neighbourhood (e.g. "Pali Hill", "Khar West").
            pincode: 6-digit pincode if known.
            landmark: Optional nearby landmark.
            preferences: Optional food preferences (e.g. "loves extra spicy").
            allergies: Optional allergies / dishes to avoid (e.g. "no peanuts").
        """
        sig = f"{name}|{phone}|{area}|{pincode}"
        stop = _loop_guard("pc_register_customer", sig)
        if stop:
            await params.result_callback(stop)
            return

        # Don't run a delivery-area check on an empty locality — that would push
        # a confusing blank delivery_check card and a false "outside area" refusal.
        if not (area or "").strip() and not (pincode or "").strip():
            await params.result_callback(
                "I still need their delivery area or pincode before I can register "
                "them — ask for the locality (and pincode if they know it)."
            )
            return

        with get_session() as db:
            ok, matched = ServiceAreaService(db).is_serviceable(pincode or area)
            matched_name = matched.name if matched else None
            matched_pincode = matched.pincode if matched else None
            if not ok:
                await push_ui_event(
                    params.llm,
                    "delivery_check",
                    {"query": area or pincode, "serviceable": False, "matched": None},
                )
                await params.result_callback(
                    f"'{area or pincode}' is OUTSIDE our delivery area. Apologize "
                    "warmly, explain we can't deliver there, and do NOT register "
                    "or take an order."
                )
                return

            cust = CustomerService(db).create_customer(
                name=name,
                phone=phone,
                address_line=address,
                area=area or matched_name,
                pincode=pincode or matched_pincode,
                landmark=landmark,
                preferences=preferences,
                allergies=allergies,
            )
            session.identify(cust)
            card = customer_to_card(cust)

        await push_ui_event(params.llm, "customer_card", card)
        spaced = " ".join(list(card["code"]))
        await params.result_callback(
            f"Registered {card['name'] or 'customer'}. Their code is {card['code']} "
            f"(read it back slowly as: {spaced}) — tell them to keep it for next "
            "time so you can pull up their details instantly. Now take their order."
        )

    async def pc_update_customer(
        params: FunctionCallParams,
        preferences: str = "",
        allergies: str = "",
        address: str = "",
        area: str = "",
        pincode: str = "",
        landmark: str = "",
        name: str = "",
        phone: str = "",
    ) -> None:
        """Amend the identified customer's saved details.

        Use when a returning customer's address changed, or to record new
        preferences/allergies they mention. Only the fields you pass are
        updated. Requires a customer to be identified first.

        Args:
            preferences: New/updated food preferences.
            allergies: New/updated allergies or dishes to avoid.
            address: Updated full delivery address.
            area: Updated locality.
            pincode: Updated pincode.
            landmark: Updated landmark.
            name: Corrected name.
            phone: Corrected phone.
        """
        if not session.can_order:
            await params.result_callback(_need_msg())
            return

        fields: dict = {}
        if preferences:
            fields["preferences"] = preferences
        if allergies:
            fields["allergies"] = allergies
        if address:
            fields["address_line"] = address
        if area:
            fields["area"] = area
        if pincode:
            fields["pincode"] = pincode
        if landmark:
            fields["landmark"] = landmark
        if name:
            fields["name"] = name
        if phone:
            fields["phone"] = phone
        if not fields:
            await params.result_callback("Nothing to update — no fields provided.")
            return

        with get_session() as db:
            cust = CustomerService(db).update_customer(session.customer_id, **fields)
            session.identify(cust)
            card = customer_to_card(cust)

        await push_ui_event(params.llm, "customer_card", card)
        await params.result_callback(
            f"Updated {card['name'] or 'the customer'}'s details. Confirm the change briefly."
        )

    async def pc_check_delivery_area(
        params: FunctionCallParams, area_or_pincode: str
    ) -> None:
        """Check whether an area or pincode is within our delivery zone.

        Use this BEFORE registering a new customer or before agreeing to
        deliver, whenever a customer states where they are. If it returns
        out-of-area, apologize and do not take a delivery order.

        Args:
            area_or_pincode: The locality name or 6-digit pincode to check.
        """
        stop = _loop_guard("pc_check_delivery_area", area_or_pincode)
        if stop:
            await params.result_callback(stop)
            return

        with get_session() as db:
            ok, matched = ServiceAreaService(db).is_serviceable(area_or_pincode)
            matched_name = matched.name if matched else None

        await push_ui_event(
            params.llm,
            "delivery_check",
            {"query": area_or_pincode, "serviceable": ok, "matched": matched_name},
        )
        if ok:
            await params.result_callback(
                f"'{area_or_pincode}' IS within our delivery area "
                f"(matched {matched_name}). Go ahead and take the order."
            )
        else:
            await params.result_callback(
                f"'{area_or_pincode}' is OUTSIDE our delivery area. Politely "
                "apologize and explain we can't deliver there — do not take a "
                "delivery order for this address."
            )

    # --- Cart tools (require an identified customer) ----------------------

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
        if not session.can_order:
            await params.result_callback(_need_msg())
            return

        with get_session() as db:
            service = OrderService(db)
            cart = _cart(service)
            menu_repo = MenuRepo(db)
            card = order_to_card(cart, menu_repo)

        await push_ui_event(params.llm, "cart_view", card)

        if not card["items"]:
            msg = (
                "The cart is empty. NOTE: if they just confirmed an order, it's "
                "already placed and with the kitchen — do not tell them they have "
                "no order; use search_my_orders to show it."
            )
        else:
            lines = [
                f"Cart (#{card['id'][:8]}) — {card['item_count']} item(s):"
            ]
            for it in card["items"]:
                note = f" ({it['special_instructions']})" if it["special_instructions"] else ""
                lines.append(
                    f"  - {it['quantity']}× {it['name']} [id={it['menu_item_id']}] — Rs {it['line_total']}{note}"
                )
            lines.append(f"Subtotal: Rs {card['subtotal']:.2f}")
            for ch in card["charges"]:
                lines.append(f"  + {ch['label']}: Rs {ch['amount']:.2f}")
            lines.append(f"Total (incl. charges): Rs {card['total']:.2f}")
            msg = "\n".join(lines)
        await params.result_callback(msg)

    async def pc_add_to_order(
        params: FunctionCallParams,
        item_id: str,
        quantity: int = 1,
        special_instructions: str = "",
    ) -> None:
        """Add an item to the customer's cart.

        Only call after verifying the item_id via search_menu/get_menu_categories,
        and after a customer has been identified.

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
        if not session.can_order:
            await params.result_callback(_need_msg())
            return

        with get_session() as db:
            service = OrderService(db)
            menu_repo = MenuRepo(db)
            cart = _cart(service)
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
            f"Added {quantity}× {added_name}. New grand total (incl. charges) is "
            f"{card['total']:.2f} rupees — say this exact figure in rupees, "
            "do not add it up yourself and never say dollars."
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
        if not session.can_order:
            await params.result_callback(_need_msg())
            return

        with get_session() as db:
            service = OrderService(db)
            menu_repo = MenuRepo(db)
            cart = _cart(service)
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
            f"Removed {removed_name}. New grand total (incl. charges) is "
            f"{card['total']:.2f} rupees — say this exact figure in rupees, "
            "do not add it up yourself and never say dollars."
        )

    async def pc_update_quantity(
        params: FunctionCallParams,
        item_id: str,
        quantity: int,
    ) -> None:
        """Set the ABSOLUTE quantity of an item already in (or being added to)
        the cart. Use this whenever the customer says how many they want in
        total — "make it two", "change it to three", "actually just one".

        For "add another / one more", use add_to_order instead (that adds on
        top). Setting quantity to 0 removes the item.

        Args:
            item_id: The menu item ID (e.g. 'M02').
            quantity: The new TOTAL quantity for this item.
        """
        sig = f"{item_id}|{quantity}"
        stop = _loop_guard("pc_update_quantity", sig)
        if stop:
            await params.result_callback(stop)
            return
        if not session.can_order:
            await params.result_callback(_need_msg())
            return

        with get_session() as db:
            service = OrderService(db)
            menu_repo = MenuRepo(db)
            cart = _cart(service)
            named = menu_repo.get_by_id(item_id)
            item_name = named.name if named else item_id
            try:
                service.set_item_quantity(cart.id, item_id, quantity)
            except ValueError as e:
                await params.result_callback(str(e))
                return
            db.refresh(cart)
            card = order_to_card(cart, menu_repo)

        await push_ui_event(params.llm, "cart_view", card)
        if quantity <= 0:
            await params.result_callback(
                f"Removed {item_name}. New grand total (incl. charges) is "
                f"{card['total']:.2f} rupees — say this exact figure in rupees."
            )
        else:
            await params.result_callback(
                f"Set {item_name} to {quantity}. New grand total (incl. charges) is "
                f"{card['total']:.2f} rupees — say this exact figure in rupees, "
                "do not add it up yourself and never say dollars."
            )

    async def pc_confirm_order(params: FunctionCallParams) -> None:
        """Send the current order to the kitchen.

        Only call when the customer has explicitly said they're done. For
        parcel, confirm the delivery address first (this freezes it onto the
        order). For dine-in this fires the round to the kitchen; the guest can
        order more rounds afterward and pays at the end.
        """
        stop = _loop_guard("pc_confirm_order", "")
        if stop:
            await params.result_callback(stop)
            return
        if not session.can_order:
            await params.result_callback(_need_msg())
            return

        dine_in = session.is_dine_in
        with get_session() as db:
            service = OrderService(db)
            menu_repo = MenuRepo(db)
            cust = None if dine_in else CustomerRepo(db).get_by_id(session.customer_id)
            cart = _cart(service)
            try:
                order = service.confirm_order(cart.id, customer=cust)
            except ValueError as e:
                await params.result_callback(str(e))
                return
            db.refresh(order)
            card = order_to_card(order, menu_repo)
            deliver_to = order.delivery_address or "the address on file"

        await push_ui_event(params.llm, "order_confirmed", card)
        charges_str = ", ".join(
            f"{c['label'].lower()} Rs {c['amount']:.2f}" for c in card["charges"]
        )
        if dine_in:
            await params.result_callback(
                f"Round for Table {session.table_label} SENT to the kitchen. "
                f"Subtotal Rs {card['subtotal']:.2f}; {charges_str}; grand total so far "
                f"Rs {card['total']:.2f}. The kitchen is on it. Tell the guest it's "
                "being prepared and ask if they'd like anything else — they pay at the "
                "end (use request_bill when they're ready). The cart is empty by design now."
            )
        else:
            await params.result_callback(
                f"Order #{card['id'][:8]} CONFIRMED and placed for delivery to {deliver_to}. "
                f"Subtotal Rs {card['subtotal']:.2f}; {charges_str}; grand total "
                f"Rs {card['total']:.2f}. Kitchen has it. The order is now placed — do NOT "
                "call view_order or say there's no order afterward; the cart is empty by design."
            )

    async def pc_cancel_order(params: FunctionCallParams) -> None:
        """Cancel the cart (only works before payment)."""
        stop = _loop_guard("pc_cancel_order", "")
        if stop:
            await params.result_callback(stop)
            return
        if not session.can_order:
            await params.result_callback(_need_msg())
            return

        with get_session() as db:
            service = OrderService(db)
            menu_repo = MenuRepo(db)
            cart = _cart(service)
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
            new_cart = _cart(service)
            card = order_to_card(new_cart, menu_repo)

        await push_ui_event(params.llm, "cart_view", card)
        await params.result_callback("Cart cancelled.")

    # --- Dine-in tools ----------------------------------------------------

    async def pc_set_table(params: FunctionCallParams, table: str) -> None:
        """Bind this dine-in call to a table by its number (voice fallback).

        Only needed when the guest did NOT scan the table's QR — ask them for
        their table number (or the number printed on the QR tent card) and pass
        it here. Once set, you can take their order.

        Args:
            table: The table number/label the guest gives (e.g. "5", "table 7").
        """
        stop = _loop_guard("pc_set_table", table)
        if stop:
            await params.result_callback(stop)
            return

        raw = table.strip()
        cand = raw[5:].strip() if raw.lower().startswith("table") else raw
        with get_session() as db:
            from db.repositories.floor_repo import FloorRepo
            from db.repositories.table_repo import TableRepo
            from db.repositories.zone_repo import ZoneRepo

            trepo = TableRepo(db)
            t = (
                trepo.get_by_qr_token(raw)
                or trepo.get_by_label(cand)
                or trepo.get_by_label(raw)
            )
            if not t or not t.active:
                await params.result_callback(
                    f"No table '{table}' found here. Ask the guest to read the "
                    "number on their table again, slowly."
                )
                return
            zone = ZoneRepo(db).get_by_id(t.zone_id)
            floor = FloorRepo(db).get_by_id(zone.floor_id) if zone and zone.floor_id else None
            label = t.label
            zone_name = zone.name if zone else None
            is_ac = bool(zone.is_ac) if zone else False
            floor_name = floor.name if floor else None
            session.seat(
                table_id=t.id, table_label=label, zone_name=zone_name,
                is_ac=is_ac, floor_name=floor_name,
            )

        await params.result_callback(
            f"Got it — Table {label} in {zone_name or 'the dining room'}. "
            "You can take their order now."
        )

    async def pc_request_bill(params: FunctionCallParams) -> None:
        """Signal staff to bring the bill and settle the table.

        Call when a dine-in guest is finished and wants to pay.
        """
        stop = _loop_guard("pc_request_bill", "")
        if stop:
            await params.result_callback(stop)
            return
        if not session.is_dine_in or not session.is_seated:
            await params.result_callback("There's no table to bill on this call.")
            return
        if not session.table_session_id:
            await params.result_callback(
                "Nothing's been ordered yet, so there's no bill. Would they like to order?"
            )
            return

        with get_session() as db:
            service = OrderService(db)
            try:
                service.request_bill(session.table_session_id)
            except ValueError as e:
                await params.result_callback(str(e))
                return

        await push_ui_event(
            params.llm, "bill_requested", {"table_label": session.table_label}
        )
        await params.result_callback(
            "Bill requested — staff have been notified. Tell the guest someone "
            "will be right over with the bill to settle up, and thank them warmly."
        )

    # --- Order history ----------------------------------------------------

    async def pc_search_my_orders(
        params: FunctionCallParams,
        status: str = "",
        limit: int = 5,
    ) -> None:
        """Search the identified customer's past orders, optionally by status.

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
        if not session.can_order:
            await params.result_callback(_need_msg())
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
            all_orders = service.get_orders_for_customer(session.customer_id)
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
                    f"  - #{c['id'][:8]} {c['status']} — {c['item_count']} item(s) — Rs {c['total']}"
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

    shared_menu = [pc_search_menu, pc_filter_menu, pc_get_menu_categories]
    shared_cart = [
        pc_view_order,
        pc_add_to_order,
        pc_update_quantity,
        pc_remove_from_order,
        pc_confirm_order,
        pc_cancel_order,
    ]
    tail = [pc_end_conversation, pc_get_current_datetime]

    if session.is_dine_in:
        # Dine-in: no customer identification or delivery; seat + bill instead.
        return shared_menu + [pc_set_table] + shared_cart + [pc_request_bill] + tail

    # Parcel (default): customer identity + delivery-area + order history.
    return (
        shared_menu
        + [
            pc_lookup_customer,
            pc_register_customer,
            pc_update_customer,
            pc_check_delivery_area,
        ]
        + shared_cart
        + [pc_search_my_orders]
        + tail
    )


# --- Pipeline factory ---------------------------------------------------


def create_pipeline(
    websocket: WebSocket,
    user_timezone: str | None = None,
    table_token: str | None = None,
):
    """Create a fresh Gemini Live Native Audio pipeline per connection.

    Parcel calls start anonymous; the agent identifies the caller mid-call.
    Dine-in calls arrive with a ``table_token`` (the guest scanned the table's
    QR) — we resolve it and seat the session up front so the agent skips
    identification/delivery and builds the table's tab. The shared CallSession
    carries this to the cart/order tools.
    """
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

    # One mutable session shared by all tool wrappers for this connection.
    session = CallSession()
    if table_token:
        # Dine-in: bind to the scanned table. Stay in dine-in mode even if the
        # token doesn't resolve — the agent will ask for the table via set_table.
        session.order_type = OrderType.DINE_IN
        try:
            with get_session() as db:
                info = TableService(db).resolve_qr(table_token)
            session.seat(
                table_id=info["table_id"],
                table_label=info["label"],
                zone_name=info["zone_name"],
                is_ac=info["is_ac"],
                floor_name=info.get("floor_name"),
            )
            logger.info(
                f"Dine-in call seated at Table {info['label']} ({info['zone_name']}, "
                f"AC={info['is_ac']})"
            )
        except ValueError:
            logger.warning("Dine-in table_token didn't resolve — agent will ask for the table")

    # Load the editable restaurant profile so "are we open" tracks admin hours.
    _profile_hours, _profile_tz = None, None
    try:
        with get_session() as db:
            from services.settings_service import SettingsService
            _profile = SettingsService(db).get_restaurant_profile()
            _profile_hours, _profile_tz = _profile.get("hours"), _profile.get("timezone")
    except Exception:
        pass  # fall back to the legacy hardcoded schedule

    # Fresh per-connection time context prepended to the mode-appropriate prompt.
    system_instruction = (
        build_time_context_message(user_timezone, hours=_profile_hours, timezone=_profile_tz)
        + "\n\n"
        + build_system_prompt(session)
    )

    # Collect tool schemas up front. Pass tools at init time ONLY — if we also
    # put them on the LLMContext, Pipecat treats that as a change-at-runtime
    # and forces a reconnect (during which audio is dropped).
    tool_fns = _make_tool_wrappers(session, user_timezone)
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
