import pytest
from fastapi.testclient import TestClient
from db.base import get_db
from config import ADMIN_EMAIL, ADMIN_PASSWORD


@pytest.fixture
def client(db):
    from main import app
    from db.seeds.menu_seed import seed_menu, seed_admin
    seed_menu(db)
    seed_admin(db, ADMIN_EMAIL, ADMIN_PASSWORD)
    db.commit()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin_token(client):
    resp = client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    return client.cookies.get("saffron_session")


def test_list_menu_is_public(client):
    resp = client.get("/menu")
    assert resp.status_code == 200
    assert len(resp.json()) > 0


def test_create_item_requires_admin(client):
    resp = client.post("/menu", json={
        "id": "NEW01", "name": "New Item", "category": "starters", "price": 100.0
    })
    assert resp.status_code in (401, 403)


def test_create_item_as_admin(client, admin_token):
    resp = client.post(
        "/menu",
        json={"id": "NEW02", "name": "New Item", "category": "starters", "price": 100.0},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["id"] == "NEW02"


def test_patch_item_price(client, admin_token):
    resp = client.patch(
        "/menu/M01",
        json={"price": 999.0},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["price"] == 999.0


def test_delete_item_soft_disables(client, admin_token):
    client.delete("/menu/M02", headers={"Authorization": f"Bearer {admin_token}"})
    resp = client.get("/menu/M02")
    assert resp.status_code == 404


def test_upload_rejects_oversized_images(client, admin_token, monkeypatch):
    from routers import menu as menu_router

    monkeypatch.setattr(menu_router, "upload_enabled", lambda: True)
    monkeypatch.setattr(menu_router, "upload_image", lambda contents: "https://img.test/x.jpg")
    big = b"\x00" * (menu_router.MAX_IMAGE_BYTES + 1)
    headers = {"Authorization": f"Bearer {admin_token}"}
    r = client.post("/menu/upload-image", headers=headers,
                    files={"file": ("big.jpg", big, "image/jpeg")})
    assert r.status_code == 413
    ok = client.post("/menu/upload-image", headers=headers,
                     files={"file": ("small.jpg", b"\xff\xd8\xff", "image/jpeg")})
    assert ok.status_code == 200 and ok.json()["image_url"] == "https://img.test/x.jpg"
