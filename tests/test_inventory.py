from types import SimpleNamespace

from services.menu_service import effective_available


def _item(**kw):
    base = dict(available=True, is_86=False, track_stock=False, stock_qty=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_effective_available_rules():
    assert effective_available(_item()) is True
    assert effective_available(_item(available=False)) is False
    assert effective_available(_item(is_86=True)) is False
    # Stock-tracked: out of stock → unavailable; in stock → available.
    assert effective_available(_item(track_stock=True, stock_qty=0)) is False
    assert effective_available(_item(track_stock=True, stock_qty=3)) is True
    # Tracked but no count set is treated as out of stock.
    assert effective_available(_item(track_stock=True, stock_qty=None)) is False
    # Not tracked → stock is irrelevant.
    assert effective_available(_item(track_stock=False, stock_qty=0)) is True
