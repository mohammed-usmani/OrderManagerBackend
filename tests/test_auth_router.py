import pytest
from fastapi.testclient import TestClient
from db.base import get_db
from config import ADMIN_EMAIL, ADMIN_PASSWORD

APP = {"Origin": "http://localhost:3000"}  # browsers send the page origin


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
    resp = client.post("/auth/register", headers=APP, json={
        "email": "r1@test.com", "password": "pass1234", "name": "R1"
    })
    assert resp.status_code == 200
    assert resp.json()["user"]["email"]
    assert "saffron_session" in resp.cookies


def test_register_rejects_short_password(client):
    resp = client.post("/auth/register", headers=APP, json={
        "email": "shorty@test.com", "password": "short", "name": "S"
    })
    assert resp.status_code == 400


def test_register_duplicate_email(client):
    client.post("/auth/register", headers=APP, json={"email": "dup@test.com", "password": "password1", "name": "D"})
    resp = client.post("/auth/register", headers=APP, json={"email": "dup@test.com", "password": "password1", "name": "D"})
    assert resp.status_code == 400


def test_login_success(client):
    client.post("/auth/register", headers=APP, json={"email": "login@test.com", "password": "secret12", "name": "L"})
    resp = client.post("/auth/login", headers=APP, json={"email": "login@test.com", "password": "secret12"})
    assert resp.status_code == 200
    assert resp.json()["user"]["email"]
    assert "saffron_session" in resp.cookies


def test_login_wrong_password(client):
    client.post("/auth/register", headers=APP, json={"email": "wp@test.com", "password": "correct1", "name": "W"})
    resp = client.post("/auth/login", headers=APP, json={"email": "wp@test.com", "password": "wrongpass"})
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
