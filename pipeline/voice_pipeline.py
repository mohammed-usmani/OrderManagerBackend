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

import asyncio
from datetime import datetime
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
    verified_customer_card,
)
from loguru import logger

from services.customer_service import CustomerService, normalize_phone
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


# Wrong code/phone + name + pincode combinations allowed per call before lookups stop.
MAX_FAILED_LOOKUPS = 3


async def _in_db(work):
    """Run ``work(db)`` on a worker thread with its own session and return its
    result. One event loop streams audio for every live call, so database
    round-trips must never run on it. ``work`` should return plain data (cards,
    strings, flags), not ORM rows, since the session closes when it returns."""
    def run():
        with get_session() as db:
            return work(db)

    return await asyncio.to_thread(run)

def _resolve_tz(name: str | None) -> ZoneInfo:
    if name:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return RESTAURANT_TZ


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
                "This call isn't linked to a table. Ask the guest to scan the QR "
                "code on their table to order — you can't take a dine-in order "
                "without it."
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

        def search(db):
            service = MenuService(db)
            # Exact ID hit first (e.g. "M01"). Include unavailable so an exact
            # ID for a temporarily-unavailable dish surfaces it (the card shows
            # the unavailable state) rather than falling through to fuzzy search.
            try:
                items = [service.get_item(query.strip().upper(), include_unavailable=True)]
            except ValueError:
                items = service.search(query)
            return [menu_item_to_card(i) for i in items]

        cards = await _in_db(search)

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

        def filtered(db):
            items = MenuService(db).filter(
                category=category or None,
                dietary=dietary_list or None,
                spice_level=spice_level or None,
                max_price=max_price_val,
                keyword=keyword or None,
            )
            return [menu_item_to_card(i) for i in items]

        cards = await _in_db(filtered)

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

        cards = await _in_db(
            lambda db: [menu_item_to_card(i) for i in MenuService(db).list_items(include_unavailable=False)]
        )

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
        params: FunctionCallParams, code_or_phone: str, name: str, pincode_or_area: str
    ) -> None:
        """Look up a RETURNING customer. They must prove it's their account:
        besides their 4-digit code or phone number, ask for the NAME on the
        account and their delivery PINCODE (or area). All three must match.

        On success the rest of the call is tied to that customer. On failure,
        don't say whether the number or code exists — ask them to double-check,
        or offer to register them as a new customer.

        Args:
            code_or_phone: The 4-digit code they quote (e.g. "4821") or their
                phone number.
            name: The name on the account, as the caller says it.
            pincode_or_area: Their delivery pincode (or area if they don't know it).
        """
        if session.failed_lookups >= MAX_FAILED_LOOKUPS:
            await params.result_callback(
                "Too many unsuccessful attempts — you can't look up an account on "
                "this call any more. Apologise, and offer to register them as a new "
                "customer or suggest calling back."
            )
            return
        if not (name or "").strip() or not (pincode_or_area or "").strip():
            await params.result_callback(
                "Before pulling up their account, ask for the name on the account "
                "and their delivery pincode (or area). Then call this again with all three."
            )
            return
        stop = _loop_guard("pc_lookup_customer", f"{code_or_phone}|{name}|{pincode_or_area}")
        if stop:
            await params.result_callback(stop)
            return

        def verify(db):
            cust = CustomerService(db).verify(code_or_phone, name=name, place=pincode_or_area)
            if not cust:
                return None
            session.identify(cust)
            first_name = (cust.name or "").split()[0] if cust.name else "there"
            return verified_customer_card(cust), first_name, cust.area, cust.preferences, cust.allergies

        found = await _in_db(verify)
        if found is None:
            session.failed_lookups += 1
            await params.result_callback(
                "Those details don't match an account. Don't say whether the "
                "number or code exists. Ask them to check the details, or offer "
                "to register them as a new customer."
            )
            return
        card, first_name, area, preferences, allergies = found

        await push_ui_event(params.llm, "customer_card", card)
        bits = [f"Verified: {first_name} (code {card['code']})."]
        if area:
            bits.append(
                f"They usually get delivery in {area}. Ask if that's where it's going "
                "today — never read out their street address or phone number."
            )
        if preferences:
            bits.append(f"For you, don't read aloud — preferences: {preferences}.")
        if allergies:
            bits.append(f"For you, don't read aloud — must avoid (allergies): {allergies}.")
        bits.append("Greet them by first name, then take their order.")
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

        def register(db):
            existing_phone = normalize_phone(phone)
            if existing_phone and CustomerRepo(db).get_by_phone(existing_phone):
                return "taken", None
            ok, matched = ServiceAreaService(db).is_serviceable(pincode or area)
            if not ok:
                return "outside", None
            cust = CustomerService(db).create_customer(
                name=name,
                phone=phone,
                address_line=address,
                area=area or (matched.name if matched else None),
                pincode=pincode or (matched.pincode if matched else None),
                landmark=landmark,
                preferences=preferences,
                allergies=allergies,
            )
            session.identify(cust)
            return "ok", customer_to_card(cust)

        outcome, card = await _in_db(register)
        if outcome == "taken":
            await params.result_callback(
                "That phone number is already registered. Don't reveal anything "
                "about that account — ask for their 4-digit code or look them up "
                "with lookup_customer (name and delivery pincode needed)."
            )
            return
        if outcome == "outside":
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

        def update(db):
            cust = CustomerService(db).update_customer(session.customer_id, **fields)
            session.identify(cust)
            return verified_customer_card(cust)

        card = await _in_db(update)

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

        def check(db):
            ok, matched = ServiceAreaService(db).is_serviceable(area_or_pincode)
            return ok, (matched.name if matched else None)

        ok, matched_name = await _in_db(check)

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

        card = await _in_db(lambda db: order_to_card(_cart(OrderService(db)), MenuRepo(db)))

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

        def add(db):
            service, menu_repo = OrderService(db), MenuRepo(db)
            cart = _cart(service)
            service.add_item(cart.id, item_id, quantity, special_instructions)
            db.refresh(cart)
            added = menu_repo.get_by_id(item_id)
            return order_to_card(cart, menu_repo), (added.name if added else item_id)

        try:
            card, added_name = await _in_db(add)
        except ValueError as e:
            await params.result_callback(str(e))
            return

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

        def remove(db):
            service, menu_repo = OrderService(db), MenuRepo(db)
            cart = _cart(service)
            removed = menu_repo.get_by_id(item_id)
            service.remove_item(cart.id, item_id)
            db.refresh(cart)
            return order_to_card(cart, menu_repo), (removed.name if removed else item_id)

        try:
            card, removed_name = await _in_db(remove)
        except ValueError as e:
            await params.result_callback(str(e))
            return

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

        def set_quantity(db):
            service, menu_repo = OrderService(db), MenuRepo(db)
            cart = _cart(service)
            named = menu_repo.get_by_id(item_id)
            service.set_item_quantity(cart.id, item_id, quantity)
            db.refresh(cart)
            return order_to_card(cart, menu_repo), (named.name if named else item_id)

        try:
            card, item_name = await _in_db(set_quantity)
        except ValueError as e:
            await params.result_callback(str(e))
            return

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
        def confirm(db):
            service, menu_repo = OrderService(db), MenuRepo(db)
            cust = None if dine_in else CustomerRepo(db).get_by_id(session.customer_id)
            order = service.confirm_order(_cart(service).id, customer=cust)
            db.refresh(order)
            return order_to_card(order, menu_repo), (order.delivery_address or "the address on file")

        try:
            card, deliver_to = await _in_db(confirm)
        except ValueError as e:
            await params.result_callback(str(e))
            return

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

        def cancel(db):
            service, menu_repo = OrderService(db), MenuRepo(db)
            cart = _cart(service)
            if cart.status == "confirmed":
                raise ValueError("Already confirmed — please speak to the manager.")
            service.cancel_order(cart.id)
            return order_to_card(_cart(service), menu_repo)

        try:
            card = await _in_db(cancel)
        except ValueError as e:
            await params.result_callback(str(e))
            return

        await push_ui_event(params.llm, "cart_view", card)
        await params.result_callback("Cart cancelled.")

    # --- Dine-in tools ----------------------------------------------------

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

        try:
            await _in_db(lambda db: OrderService(db).request_bill(session.table_session_id))
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

        def history(db):
            menu_repo = MenuRepo(db)
            all_orders = OrderService(db).get_orders_for_customer(session.customer_id)
            counts: dict[str, int] = {}
            for o in all_orders:
                counts[o.status] = counts.get(o.status, 0) + 1
            matches = [o for o in all_orders if not status or o.status == status]
            cards = [order_to_card(o, menu_repo) for o in matches[:limit]]
            return cards, counts, bool(all_orders), bool(matches)

        cards, counts, has_orders, has_matches = await _in_db(history)

        title = f"Orders ({status})" if status else "Your Orders"
        await push_ui_event(
            params.llm,
            "orders_list",
            {"title": title, "orders": cards, "counts": counts},
        )

        if not has_orders:
            msg = "You don't have any orders yet."
        elif not has_matches:
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
        return shared_menu + shared_cart + [pc_request_bill] + tail

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


def load_call_context(table_token: str | None) -> dict:
    """Database lookups a new call needs, done once before the pipeline is built.
    Synchronous: the WebSocket endpoint runs it on a worker thread.

    ``table`` is the scanned table (None for parcel calls or an unknown QR) and
    ``hours``/``timezone`` come from the editable restaurant profile, so "are we
    open" tracks the admin's hours (None falls back to the built-in schedule).
    """
    context = {"table": None, "hours": None, "timezone": None}
    if table_token:
        try:
            with get_session() as db:
                context["table"] = TableService(db).resolve_qr(table_token)
        except ValueError:
            pass  # unknown QR — the call stays dine-in and asks for a rescan
    try:
        with get_session() as db:
            from services.settings_service import SettingsService

            profile = SettingsService(db).get_restaurant_profile()
            context["hours"], context["timezone"] = profile.get("hours"), profile.get("timezone")
    except Exception:
        pass  # fall back to the legacy hardcoded schedule
    return context


def create_pipeline(
    websocket: WebSocket,
    user_timezone: str | None = None,
    table_token: str | None = None,
    call_context: dict | None = None,
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
    call_context = call_context or {"table": None, "hours": None, "timezone": None}
    if table_token:
        # Dine-in: bind to the scanned table. Stay in dine-in mode even if the
        # token doesn't resolve — the agent asks the guest to scan the QR again.
        session.order_type = OrderType.DINE_IN
        info = call_context["table"]
        if info:
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
        else:
            logger.warning("Dine-in table_token didn't resolve — agent will ask for a QR scan")
    _profile_hours, _profile_tz = call_context["hours"], call_context["timezone"]
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

    # Return the transport too: the caller wires an on_client_disconnected
    # handler to it so a browser hang-up cancels the pipeline (and frees the
    # concurrency slot) immediately, instead of hanging until the session cap.
    return pipeline, transport
