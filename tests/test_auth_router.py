import pytest
from fastapi.testclient import TestClient
from db.base import get_db
from config import ADMIN_EMAIL, ADMIN_PASSWORD


@pytest.fixture
def client(db):
    from main import app
    from db.seeds.menu_seed import seed_admin
    seed_admin(db, ADMIN_EMAIL, ADMIN_PASSWORD)
    db.commit()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


def test_register(client):
    resp = client.post("/auth/register", json={
        "email": "r1@test.com", "password": "pass123", "name": "R1"
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_register_duplicate_email(client):
    client.post("/auth/register", json={"email": "dup@test.com", "password": "p", "name": "D"})
    resp = client.post("/auth/register", json={"email": "dup@test.com", "password": "p", "name": "D"})
    assert resp.status_code == 400


def test_login_success(client):
    client.post("/auth/register", json={"email": "login@test.com", "password": "secret", "name": "L"})
    resp = client.post("/auth/login", json={"email": "login@test.com", "password": "secret"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_wrong_password(client):
    client.post("/auth/register", json={"email": "wp@test.com", "password": "correct", "name": "W"})
    resp = client.post("/auth/login", json={"email": "wp@test.com", "password": "wrong"})
    assert resp.status_code == 401


def test_ws_ticket_is_public(client):
    # The voice line is public — anyone can get a ticket without logging in.
    resp = client.post("/auth/ws-ticket")
    assert resp.status_code == 200
    assert "ticket" in resp.json()


def test_ws_ticket_accepts_timezone(client):
    resp = client.post("/auth/ws-ticket", json={"timezone": "Asia/Kolkata"})
    assert resp.status_code == 200
    assert "ticket" in resp.json()
