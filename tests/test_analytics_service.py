"""Analytics time-series + peak-hours logic (no DB — _orders is stubbed)."""

from datetime import datetime

from services.analytics_service import AnalyticsService, range_start


class _Item:
    def __init__(self, price, qty):
        self.price_at_order = price
        self.quantity = qty


class _Order:
    def __init__(self, total, status, order_type, created_at, zone_name=None, items=None):
        self.total = total
        self.status = status
        self.order_type = order_type
        self.created_at = created_at  # naive UTC
        self.zone_name = zone_name
        self.is_ac = False
        self.items = items or []


def _orders():
    # 16:30 UTC = 22:00 IST; 17:00 UTC = 22:30 IST → both hour 22.
    return [
        _Order(600.0, "confirmed", "dine_in", datetime(2026, 6, 12, 16, 30), "AC Hall", [_Item(500, 1)]),
        _Order(1150.0, "paid", "parcel", datetime(2026, 6, 12, 17, 0), None, [_Item(500, 2)]),
        _Order(0.0, "cart", "parcel", datetime(2026, 6, 12, 17, 0)),       # excluded
        _Order(300.0, "cancelled", "parcel", datetime(2026, 6, 12, 17, 0)),  # excluded
    ]


class _Svc(AnalyticsService):
    def _orders(self, range_key):  # noqa: D401 - test stub
        return _orders()


def test_range_start():
    assert range_start("all") is None
    assert isinstance(range_start("30d"), datetime)
    assert range_start("30d") < datetime.utcnow()
    assert range_start("today") <= datetime.utcnow()


def test_timeseries_buckets_and_split():
    ts = _Svc(None).timeseries("all", "day")
    assert len(ts) == 1  # carts/cancelled excluded; both billable on same IST day
    b = ts[0]
    assert b["bucket"] == "2026-06-12"
    assert b["orders"] == 2
    assert b["revenue"] == 1750.0
    assert b["dine_in"] == 600.0
    assert b["parcel"] == 1150.0


def test_timeseries_month_granularity():
    ts = _Svc(None).timeseries("all", "month")
    assert ts[0]["bucket"] == "2026-06"


def test_peak_hours_ist_conversion():
    ph = _Svc(None).peak_hours("all")
    assert len(ph) == 24
    assert ph[22]["orders"] == 2  # both orders fall in the 22:00 IST hour
    assert ph[22]["revenue"] == 1750.0
    assert sum(h["orders"] for h in ph) == 2  # excluded orders don't count
