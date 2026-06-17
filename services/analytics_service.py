"""Business analytics — daily / monthly / yearly, dine-in vs parcel.

Computes metrics in Python over the orders in a time window. At a single
restaurant's scale this is cheap and avoids brittle SQL; revenue uses the bill
snapshot frozen on each order (``order.total``) so historical figures are stable,
falling back to a live computation for carts/legacy rows.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from db.models.order import Order
from services.billing import bill_for_order
from services.menu_service import MenuService
from services.order_lifecycle import DINE_IN

RESTAURANT_TZ = ZoneInfo("Asia/Kolkata")

# range key -> rolling window in days (None = all time; "today" = IST midnight).
RANGE_DAYS: dict[str, int | None] = {
    "today": 0,
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "year": 365,
    "all": None,
}

# Orders that don't count toward business done (still building / abandoned).
_EXCLUDED = {"cart", "cancelled"}


def range_start(range_key: str) -> datetime | None:
    """UTC-naive datetime from which orders count; None = no lower bound."""
    if range_key == "today":
        now_ist = datetime.now(RESTAURANT_TZ)
        midnight = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight.astimezone(timezone.utc).replace(tzinfo=None)
    days = RANGE_DAYS.get(range_key)
    if days is None:
        return None
    return datetime.utcnow() - timedelta(days=days)


def _ist(dt: datetime) -> datetime:
    """Treat a naive UTC timestamp as UTC and convert to IST."""
    return dt.replace(tzinfo=timezone.utc).astimezone(RESTAURANT_TZ)


class AnalyticsService:
    def __init__(self, db: Session):
        self.db = db

    def _orders(self, range_key: str) -> list[Order]:
        q = self.db.query(Order)
        start = range_start(range_key)
        if start is not None:
            q = q.filter(Order.created_at >= start)
        return q.all()

    @staticmethod
    def _revenue(order: Order) -> float:
        if order.total is not None:
            return float(order.total)
        return bill_for_order(order)["total"]

    @staticmethod
    def _subtotal(order: Order) -> float:
        from decimal import Decimal

        from services.money import money_float
        return money_float(
            sum((Decimal(str(i.price_at_order)) * i.quantity for i in order.items), Decimal(0))
        )

    # --- Headline overview ------------------------------------------------

    def overview(self, range_key: str) -> dict:
        orders = self._orders(range_key)
        billable = [o for o in orders if o.status not in _EXCLUDED]

        status_counts: dict[str, int] = defaultdict(int)
        for o in orders:
            status_counts[o.status] += 1

        revenue_total = sum(self._revenue(o) for o in billable)
        revenue_subtotal = sum(self._subtotal(o) for o in billable)

        # dine-in vs parcel split
        split: dict[str, dict] = {
            "dine_in": {"orders": 0, "revenue": 0.0},
            "parcel": {"orders": 0, "revenue": 0.0},
        }
        zones: dict[str, dict] = {}
        floors: dict[str, dict] = {}
        item_stats: dict[str, dict] = {}
        for o in billable:
            kind = "dine_in" if o.order_type == DINE_IN else "parcel"
            split[kind]["orders"] += 1
            split[kind]["revenue"] += self._revenue(o)
            if kind == "dine_in":
                zname = o.zone_name or "Unassigned"
                z = zones.setdefault(zname, {"zone": zname, "orders": 0, "revenue": 0.0})
                z["orders"] += 1
                z["revenue"] += self._revenue(o)
                fname = o.floor_name or "Unassigned"
                fl = floors.setdefault(fname, {"floor": fname, "orders": 0, "revenue": 0.0})
                fl["orders"] += 1
                fl["revenue"] += self._revenue(o)
            for oi in o.items:
                line = float(oi.price_at_order) * oi.quantity
                st = item_stats.setdefault(
                    oi.menu_item_id,
                    {"menu_item_id": oi.menu_item_id, "quantity": 0, "revenue": 0.0},
                )
                st["quantity"] += oi.quantity
                st["revenue"] += line

        # name the top items
        menu_service = MenuService(self.db)
        top_items = []
        for st in sorted(item_stats.values(), key=lambda s: -s["quantity"])[:8]:
            try:
                name = menu_service.get_item(st["menu_item_id"], include_unavailable=True).name
            except ValueError:
                name = st["menu_item_id"]
            top_items.append({**st, "name": name})

        # dine-in table sessions opened in the window (turnover)
        from db.models.restaurant_table import RestaurantTable
        from db.models.table_session import TableSession

        start = range_start(range_key)
        sq = self.db.query(TableSession)
        if start is not None:
            sq = sq.filter(TableSession.opened_at >= start)
        sessions = sq.count()
        tables_total = (
            self.db.query(RestaurantTable)
            .filter(RestaurantTable.active == True)  # noqa: E712
            .count()
        )

        from services.money import money_float

        # Round all money fields to paise so accumulated sums never show drift.
        for b in (*split.values(), *zones.values(), *floors.values(), *top_items):
            b["revenue"] = money_float(b["revenue"])

        n_billable = len(billable)
        return {
            "range": range_key,
            "range_start": (start or datetime(1970, 1, 1)),
            "total_orders": len(orders),
            "billable_orders": n_billable,
            "orders_by_status": dict(status_counts),
            "revenue_subtotal": money_float(revenue_subtotal),
            "revenue_total": money_float(revenue_total),
            "avg_ticket": money_float(revenue_total / n_billable) if n_billable else 0.0,
            "split": split,
            "by_zone": sorted(zones.values(), key=lambda z: -z["revenue"]),
            "by_floor": sorted(floors.values(), key=lambda f: -f["revenue"]),
            "top_items": top_items,
            "dine_in_sessions": sessions,
            "active_tables": tables_total,
            "table_turnover": round((sessions / tables_total), 3) if tables_total else 0.0,
        }

    # --- Time series (day / month / year) ---------------------------------

    def timeseries(self, range_key: str, granularity: str = "day") -> list[dict]:
        fmt = {"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}.get(granularity, "%Y-%m-%d")
        orders = [o for o in self._orders(range_key) if o.status not in _EXCLUDED]
        buckets: dict[str, dict] = {}
        for o in orders:
            key = _ist(o.created_at).strftime(fmt)
            b = buckets.setdefault(
                key,
                {"bucket": key, "orders": 0, "revenue": 0.0, "dine_in": 0.0, "parcel": 0.0},
            )
            rev = self._revenue(o)
            b["orders"] += 1
            b["revenue"] += rev
            b["dine_in" if o.order_type == DINE_IN else "parcel"] += rev
        return [buckets[k] for k in sorted(buckets)]

    # --- Peak hours (hour-of-day, IST) ------------------------------------

    def peak_hours(self, range_key: str) -> list[dict]:
        orders = [o for o in self._orders(range_key) if o.status not in _EXCLUDED]
        hours = {h: {"hour": h, "orders": 0, "revenue": 0.0} for h in range(24)}
        for o in orders:
            h = _ist(o.created_at).hour
            hours[h]["orders"] += 1
            hours[h]["revenue"] += self._revenue(o)
        return [hours[h] for h in range(24)]
