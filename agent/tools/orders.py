"""Order management tools for the restaurant agent.

Tools use user_id from LangGraph configurable (injected via RunnableConfig).
DB operations go through OrderService and MenuService.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from db.base import get_session
from services.menu_service import MenuService
from services.order_service import OrderService

RESTAURANT_TZ = ZoneInfo("Asia/Kolkata")


def _get_user_id(config: RunnableConfig) -> str:
    user_id = (config or {}).get("configurable", {}).get("user_id")
    if not user_id:
        raise ValueError("user_id not found in agent config — are you authenticated?")
    return user_id


def _get_display_tz(config: RunnableConfig) -> ZoneInfo:
    """Return the customer's timezone if known, otherwise restaurant IST."""
    name = (config or {}).get("configurable", {}).get("user_timezone")
    if name:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return RESTAURANT_TZ


def _format_dt(dt: datetime | None, tz: ZoneInfo) -> str:
    """Render a naive-UTC datetime from the DB in the given timezone."""
    if dt is None:
        return "unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(tz)
    return local.strftime("%b %d, %I:%M %p %Z")


@tool
def search_menu(query: str, config: RunnableConfig = None) -> str:
    """Search the restaurant menu by dish name or item ID.

    Args:
        query: The dish name or ID to search for (e.g. 'butter chicken', 'M01', 'biryani').
    """
    with get_session() as db:
        service = MenuService(db)
        # Try exact ID match first
        try:
            item = service.get_item(query.upper())
            items = [item]
        except ValueError:
            items = service.find_by_name(query)

        if not items:
            return f"No dishes found matching '{query}'. Try a different search term."

        lines = []
        for item in items:
            lines.append(f"[{item.id}] {item.name} — ₹{float(item.price)} ({item.serving})")
            if item.description:
                lines.append(f"  {item.description}")
            if item.taste_profile:
                lines.append(f"  Taste: {item.taste_profile}")
            if item.how_its_made:
                lines.append(f"  Preparation: {item.how_its_made}")
            if item.popularity:
                lines.append(f"  Rating: {item.popularity}/5 — {item.popularity_note or ''}")
            if item.spice_level:
                lines.append(f"  Spice level: {item.spice_level}")
            if item.dietary:
                lines.append(f"  Dietary: {', '.join(item.dietary)}")
            lines.append(f"  Status: {'Available' if item.available else 'Currently unavailable'}")
            lines.append("")
        result = "\n".join(lines)
    return result


@tool
def get_menu_categories(config: RunnableConfig = None) -> str:
    """Get an overview of all menu categories and their items with prices."""
    with get_session() as db:
        items = MenuService(db).list_items(include_unavailable=True)

        by_category: dict[str, list] = {}
        for item in items:
            by_category.setdefault(item.category, []).append(item)

        lines = []
        for category, cat_items in by_category.items():
            lines.append(f"\n— {category.upper()} —")
            for item in cat_items:
                avail = "" if item.available else " [UNAVAILABLE]"
                lines.append(f"  [{item.id}] {item.name} — ₹{float(item.price)} ({item.serving}){avail}")
        result = "\n".join(lines)
    return result


@tool
def add_to_order(
    item_id: str,
    quantity: int = 1,
    special_instructions: str = "",
    config: RunnableConfig = None,
) -> str:
    """Add an item to the current user's order.

    Args:
        item_id: The menu item ID (e.g. 'M01', 'S02', 'B03').
        quantity: Number of this item to add.
        special_instructions: Any special requests (e.g. 'extra spicy', 'no onion').
    """
    user_id = _get_user_id(config)
    with get_session() as db:
        service = OrderService(db)
        cart = service.get_or_create_cart(user_id)
        try:
            oi = service.add_item(cart.id, item_id, quantity, special_instructions)
            db.refresh(cart)
            price_each = float(oi.price_at_order)
            total = sum(float(i.price_at_order) * i.quantity for i in cart.items)
            from db.repositories.menu_repo import MenuRepo
            mi = MenuRepo(db).get_by_id(item_id)
            name = mi.name if mi else item_id
        except ValueError as e:
            return str(e)

    return (
        f"Added {quantity}x {name} (₹{price_each} each) to your order."
        f"{' Note: ' + special_instructions if special_instructions else ''}"
        f"\nCurrent order total: ₹{total}"
    )


@tool
def search_my_orders(
    status: str = "",
    limit: int = 5,
    config: RunnableConfig = None,
) -> str:
    """Search the customer's past orders, optionally filtered by status.

    Use this when the customer asks about their order history, past orders,
    or wants to know e.g. "how many confirmed orders do I have?". For the
    CURRENT in-progress cart only, use view_order instead.

    Args:
        status: Optional status filter. One of: "cart", "confirmed",
            "awaiting_payment", "paid", "cancelled". Leave empty to count
            across all statuses and return a summary.
        limit: Maximum number of matching orders to return details for
            (default 5). Counts are always returned in full.
    """
    user_id = _get_user_id(config)
    tz = _get_display_tz(config)
    status = (status or "").strip().lower()
    valid = {"cart", "confirmed", "awaiting_payment", "paid", "cancelled"}
    if status and status not in valid:
        return f"Unknown status '{status}'. Valid: {', '.join(sorted(valid))}."

    with get_session() as db:
        service = OrderService(db)
        all_orders = service.get_orders(user_id)
        if not all_orders:
            return "You don't have any orders yet."

        # Build status counts once — cheap and useful context for the LLM.
        counts: dict[str, int] = {}
        for o in all_orders:
            counts[o.status] = counts.get(o.status, 0) + 1
        summary = ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))

        matches = [o for o in all_orders if not status or o.status == status]
        if not matches:
            return f"Summary: {summary}. No orders with status '{status}'."

        header = (
            f"Summary across all orders: {summary}.\n"
            f"Showing {min(limit, len(matches))} of {len(matches)} "
            f"{status or 'total'} order(s):"
        )
        lines = [header]
        for o in matches[:limit]:
            short = o.id[:8]
            item_count = sum(i.quantity for i in o.items)
            total = sum(float(i.price_at_order) * i.quantity for i in o.items)
            created = _format_dt(o.created_at, tz)
            lines.append(
                f"  • #{short} — {o.status} — {item_count} item(s) — ₹{total} — placed {created}"
            )
    return "\n".join(lines)


@tool
def view_order(config: RunnableConfig = None) -> str:
    """View your current in-progress cart (items not yet confirmed).

    For historical orders (past / confirmed / cancelled), use list_my_orders instead.
    """
    user_id = _get_user_id(config)
    with get_session() as db:
        service = OrderService(db)
        cart = service.get_or_create_cart(user_id)
        if not cart.items:
            return "Your order is empty."

        from db.repositories.menu_repo import MenuRepo
        menu_repo = MenuRepo(db)

        lines = [f"Your order (#{cart.id[:8]}) — Status: {cart.status}"]
        lines.append("-" * 40)
        for i, item in enumerate(cart.items, 1):
            mi = menu_repo.get_by_id(item.menu_item_id)
            name = mi.name if mi else item.menu_item_id
            total_price = float(item.price_at_order) * item.quantity
            line = f"  {i}. {item.quantity}x {name} — ₹{total_price}"
            if item.special_instructions:
                line += f" ({item.special_instructions})"
            lines.append(line)

        total = sum(float(i.price_at_order) * i.quantity for i in cart.items)
        lines.append("-" * 40)
        lines.append(f"  TOTAL: ₹{total}")
    return "\n".join(lines)


@tool
def remove_from_order(item_id: str, config: RunnableConfig = None) -> str:
    """Remove an item from your order by item ID.

    Args:
        item_id: The menu item ID to remove (e.g. 'M01').
    """
    user_id = _get_user_id(config)
    with get_session() as db:
        service = OrderService(db)
        cart = service.get_or_create_cart(user_id)
        from db.repositories.menu_repo import MenuRepo
        mi = MenuRepo(db).get_by_id(item_id)
        name = mi.name if mi else item_id
        try:
            service.remove_item(cart.id, item_id)
            db.refresh(cart)
            total = sum(float(i.price_at_order) * i.quantity for i in cart.items)
        except ValueError as e:
            return str(e)

    return f"Removed {name} from your order. New total: ₹{total}"


@tool
def confirm_order(config: RunnableConfig = None) -> str:
    """Confirm and send your order to the kitchen."""
    user_id = _get_user_id(config)
    with get_session() as db:
        service = OrderService(db)
        cart = service.get_or_create_cart(user_id)
        try:
            order = service.confirm_order(cart.id)
            total = sum(float(i.price_at_order) * i.quantity for i in order.items)
            item_count = sum(i.quantity for i in order.items)
            order_id_short = order.id[:8]
        except ValueError as e:
            return str(e)

    return (
        f"Order #{order_id_short} confirmed and sent to the kitchen!"
        f"\n{item_count} items, total: ₹{total}"
        f"\nEstimated preparation time: 20-25 minutes."
    )


@tool
def cancel_order(config: RunnableConfig = None) -> str:
    """Cancel your current order."""
    user_id = _get_user_id(config)
    with get_session() as db:
        service = OrderService(db)
        cart = service.get_or_create_cart(user_id)
        if cart.status == "confirmed":
            return (
                "Your order has already been sent to the kitchen. "
                "Please speak to the manager for cancellations after confirmation."
            )
        try:
            service.cancel_order(cart.id)
        except ValueError as e:
            return str(e)

    return "Your order has been cancelled."
