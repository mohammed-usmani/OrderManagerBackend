import pytest
from services.menu_service import MenuService


def _seed_item(db, item_id="MS01"):
    service = MenuService(db)
    return service.create_item(
        id=item_id, name="Test Item", category="starters",
        price=150.0, available=True
    )


def test_list_items_excludes_unavailable_by_default(db):
    service = MenuService(db)
    service.create_item(id="MS02", name="Avail", category="mains", price=200.0, available=True)
    service.create_item(id="MS03", name="Unavail", category="mains", price=200.0, available=False)

    items = service.list_items()
    ids = [i.id for i in items]
    assert "MS02" in ids
    assert "MS03" not in ids


def test_list_items_includes_unavailable_when_requested(db):
    service = MenuService(db)
    service.create_item(id="MS04", name="Hidden", category="mains", price=100.0, available=False)

    items = service.list_items(include_unavailable=True)
    assert any(i.id == "MS04" for i in items)


def test_get_item_not_found_raises(db):
    service = MenuService(db)
    with pytest.raises(ValueError, match="not found"):
        service.get_item("NONEXISTENT")


def test_update_item_price(db):
    item = _seed_item(db, "MS05")
    service = MenuService(db)
    updated = service.update_item("MS05", price=999.0)
    assert float(updated.price) == 999.0


def test_disable_item(db):
    item = _seed_item(db, "MS06")
    service = MenuService(db)
    service.disable_item("MS06")
    assert service.get_item("MS06", include_unavailable=True).available is False
