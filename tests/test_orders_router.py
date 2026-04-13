import pytest
from fastapi.testclient import TestClient
from db.base import get_db


@pytest.fixture
def client(db):
    from main import app
    from db.seeds.menu_seed import seed_menu
    seed_menu(db)
    db.commit()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(client):
    client.post("/auth/register", json={"email": "ord@test.com", "password": "pass", "name": "Ord"})
    resp = client.post("/auth/login", json={"email": "ord@test.com", "password": "pass"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_orders_requires_auth(client):
    resp = client.get("/orders")
    assert resp.status_code in (401, 403)


def test_get_current_order_creates_cart(client, auth_headers):
    resp = client.get("/orders/current", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "cart"


def test_cancel_order(client, auth_headers):
    resp = client.get("/orders/current", headers=auth_headers)
    order_id = resp.json()["id"]

    resp = client.delete(f"/orders/{order_id}", headers=auth_headers)
    assert resp.status_code == 204
