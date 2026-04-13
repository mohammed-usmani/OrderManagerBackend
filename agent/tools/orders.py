"""Order management tools for the restaurant agent."""

import json
import os
from datetime import datetime
from typing import Optional
from uuid import uuid4

from langchain_core.tools import tool

from agent.restaurant.menu import MENU, find_dish

ORDERS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "orders.json")


def _load_orders() -> dict:
    if not os.path.exists(ORDERS_FILE):
        return {}
    with open(ORDERS_FILE) as f:
        return json.load(f)


def _save_orders(orders: dict) -> None:
    os.makedirs(os.path.dirname(ORDERS_FILE), exist_ok=True)
    with open(ORDERS_FILE, "w") as f:
        json.dump(orders, f, indent=2)


@tool
def search_menu(query: str) -> str:
    """Search the restaurant menu by dish name or item ID.

    Args:
        query: The dish name or ID to search for (e.g. 'butter chicken', 'M01', 'biryani').
    """
    results = find_dish(query)
    if not results:
        return f"No dishes found matching '{query}'. Try a different search term."

    lines = []
    for item in results:
        lines.append(f"[{item['id']}] {item['name']} — ₹{item['price']} ({item['serving']})")
        if "description" in item:
            lines.append(f"  {item['description']}")
        if "taste_profile" in item:
            lines.append(f"  Taste: {item['taste_profile']}")
        if "how_its_made" in item:
            lines.append(f"  Preparation: {item['how_its_made']}")
        if "popularity" in item:
            lines.append(f"  Rating: {item['popularity']}/5 — {item.get('popularity_note', '')}")
        if "spice_level" in item:
            lines.append(f"  Spice level: {item['spice_level']}")
        if "dietary" in item:
            lines.append(f"  Dietary: {', '.join(item['dietary'])}")
        avail = "Available" if item.get("available", True) else "Currently unavailable"
        lines.append(f"  Status: {avail}")
        lines.append("")
    return "\n".join(lines)


@tool
def get_menu_categories() -> str:
    """Get an overview of all menu categories and their items with prices."""
    lines = []
    for category, items in MENU.items():
        lines.append(f"\n— {category.upper()} —")
        for item in items:
            avail = "" if item.get("available", True) else " [UNAVAILABLE]"
            lines.append(f"  [{item['id']}] {item['name']} — ₹{item['price']} ({item['serving']}){avail}")
    return "\n".join(lines)


@tool
def add_to_order(
    table_id: str,
    item_id: str,
    quantity: int = 1,
    special_instructions: str = "",
) -> str:
    """Add an item to a table's order.

    Args:
        table_id: The table number or customer name.
        item_id: The menu item ID (e.g. 'M01', 'S02', 'B03').
        quantity: Number of this item to add.
        special_instructions: Any special requests (e.g. 'extra spicy', 'no onion').
    """
    # Find the dish
    results = find_dish(item_id)
    if not results:
        return f"Item '{item_id}' not found on the menu. Use get_menu_categories to see available items."

    dish = results[0]
    if not dish.get("available", True):
        return f"Sorry, {dish['name']} is currently unavailable."

    orders = _load_orders()

    if table_id not in orders:
        orders[table_id] = {
            "order_id": str(uuid4())[:8],
            "table": table_id,
            "items": [],
            "status": "open",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

    order_item = {
        "item_id": dish["id"],
        "name": dish["name"],
        "quantity": quantity,
        "price_each": dish["price"],
        "total": dish["price"] * quantity,
        "special_instructions": special_instructions,
    }

    orders[table_id]["items"].append(order_item)
    orders[table_id]["updated_at"] = datetime.now().isoformat()
    _save_orders(orders)

    total = sum(i["total"] for i in orders[table_id]["items"])
    return (
        f"Added {quantity}x {dish['name']} (₹{dish['price']} each) to {table_id}'s order."
        f"{' Note: ' + special_instructions if special_instructions else ''}"
        f"\nCurrent order total: ₹{total}"
    )


@tool
def view_order(table_id: str) -> str:
    """View the current order for a table.

    Args:
        table_id: The table number or customer name.
    """
    orders = _load_orders()
    if table_id not in orders:
        return f"No order found for {table_id}."

    order = orders[table_id]
    if not order["items"]:
        return f"Order for {table_id} is empty."

    lines = [f"Order for {table_id} (#{order['order_id']}) — Status: {order['status']}"]
    lines.append("-" * 40)

    for i, item in enumerate(order["items"], 1):
        line = f"  {i}. {item['quantity']}x {item['name']} — ₹{item['total']}"
        if item.get("special_instructions"):
            line += f" ({item['special_instructions']})"
        lines.append(line)

    total = sum(i["total"] for i in order["items"])
    lines.append("-" * 40)
    lines.append(f"  TOTAL: ₹{total}")

    return "\n".join(lines)


@tool
def remove_from_order(table_id: str, item_name: str) -> str:
    """Remove an item from a table's order by dish name.

    Args:
        table_id: The table number or customer name.
        item_name: The name of the dish to remove (or part of it).
    """
    orders = _load_orders()
    if table_id not in orders:
        return f"No order found for {table_id}."

    order = orders[table_id]
    name_lower = item_name.lower()
    removed = None

    for i, item in enumerate(order["items"]):
        if name_lower in item["name"].lower():
            removed = order["items"].pop(i)
            break

    if not removed:
        return f"'{item_name}' not found in {table_id}'s order."

    orders[table_id]["updated_at"] = datetime.now().isoformat()
    _save_orders(orders)

    total = sum(i["total"] for i in order["items"])
    return f"Removed {removed['quantity']}x {removed['name']} from {table_id}'s order. New total: ₹{total}"


@tool
def confirm_order(table_id: str) -> str:
    """Confirm and send a table's order to the kitchen.

    Args:
        table_id: The table number or customer name.
    """
    orders = _load_orders()
    if table_id not in orders:
        return f"No order found for {table_id}."

    order = orders[table_id]
    if not order["items"]:
        return f"Cannot confirm an empty order for {table_id}."

    if order["status"] != "open":
        return f"Order for {table_id} is already {order['status']}."

    order["status"] = "confirmed"
    order["confirmed_at"] = datetime.now().isoformat()
    _save_orders(orders)

    total = sum(i["total"] for i in order["items"])
    item_count = sum(i["quantity"] for i in order["items"])
    return (
        f"Order #{order['order_id']} for {table_id} confirmed and sent to kitchen!"
        f"\n{item_count} items, total: ₹{total}"
        f"\nEstimated preparation time: 20-25 minutes."
    )


@tool
def cancel_order(table_id: str) -> str:
    """Cancel a table's entire order.

    Args:
        table_id: The table number or customer name.
    """
    orders = _load_orders()
    if table_id not in orders:
        return f"No order found for {table_id}."

    order = orders[table_id]
    if order["status"] == "confirmed":
        return (
            f"Order for {table_id} has already been sent to the kitchen. "
            f"Please speak to the manager for cancellations after confirmation."
        )

    del orders[table_id]
    _save_orders(orders)
    return f"Order for {table_id} has been cancelled."
