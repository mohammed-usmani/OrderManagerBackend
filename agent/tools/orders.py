"""Order management tools for the restaurant agent.

Tools use user_id from LangGraph configurable (injected via RunnableConfig).
DB operations go through OrderService and MenuService.
"""

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from db.base import get_session
from services.menu_service import MenuService
from services.order_service import OrderService


def _get_user_id(config: RunnableConfig) -> str:
    user_id = (config or {}).get("configurable", {}).get("user_id")
    if not user_id:
        raise ValueError("user_id not found in agent config — are you authenticated?")
    return user_id


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
def view_order(config: RunnableConfig = None) -> str:
    """View your current order."""
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
