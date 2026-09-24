"""Browser auth is an httpOnly session cookie: JS never sees the token, writes
must come from the app's own origin, and abuse-prone endpoints are rate-limited
per IP."""

import uuid

import pytest
from fastapi.testclient import TestClient

from db.base import get_db
from services.auth_service import auth_service
from services.user_service import UserService

APP_ORIGIN = {"Origin": "http://localhost:3000"}
EVIL_ORIGIN = {"Origin": "https://evil.mohammedusmani.me"}


@pytest.fixture
def client(db):
    from main import app

    def override():
        yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _user(db, role="none", password="password1"):
    email = f"{uuid.uuid4().hex[:8]}@t.com"
    UserService(db).register(email, password, "Test User", role=role)
    return email, password


def _login(client, db, role="none"):
    email, password = _user(db, role)
    return client.post("/auth/login", json={"email": email, "password": password}, headers=APP_ORIGIN)


def test_login_sets_an_httponly_cookie_and_returns_no_token(client, db):
    r = _login(client, db)
    assert r.status_code == 200
    assert "access_token" not in r.json()
    assert r.json()["user"]["email"]
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_me_reflects_the_session_cookie(client, db):
    assert client.get("/auth/me").status_code == 401
    _login(client, db)
    r = client.get("/auth/me")
    assert r.status_code == 200 and r.json()["user"]["role"] == "none"


def test_logout_revokes_and_clears_the_cookie(client, db):
    _login(client, db)
    token = client.cookies.get("saffron_session")
    assert client.post("/auth/logout", headers=APP_ORIGIN).status_code == 204
    assert client.get("/auth/me").status_code == 401
    # the old token stays dead even if someone kept a copy
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_cookie_writes_from_another_origin_are_blocked(client, db):
    _login(client, db)
    assert client.post("/auth/logout", headers=EVIL_ORIGIN).status_code == 403
    assert client.post("/auth/logout", headers={}).status_code == 403  # no Origin at all


def test_bearer_header_still_works_without_origin(client, db):
    email, _ = _user(db)
    user = UserService(db).repo.get_by_email(email)
    token = auth_service.create_access_token(user.id, user.email, user.is_admin, user.role)
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_cors_only_allows_the_app_origin_with_credentials(client):
    ok = client.options("/auth/me", headers={**APP_ORIGIN, "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert ok.headers.get("access-control-allow-credentials") == "true"
    bad = client.options("/auth/me", headers={**EVIL_ORIGIN, "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


def test_order_stream_needs_a_staff_session(client, db):
    assert client.get("/admin/orders/stream").status_code == 401
    _login(client, db, role="none")
    assert client.get("/admin/orders/stream").status_code == 403


def test_order_stream_rejects_a_deleted_users_token(client, db):
    email, _ = _user(db, role="chef")
    user = UserService(db).repo.get_by_email(email)
    token = auth_service.create_access_token(user.id, user.email, user.is_admin, user.role)
    db.delete(user)
    db.flush()
    r = client.get("/admin/orders/stream", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_login_is_rate_limited_per_ip(client, db):
    codes = [
        client.post("/auth/login", json={"email": f"x{i}@t.com", "password": "nope1234"},
                    headers=APP_ORIGIN).status_code
        for i in range(12)
    ]
    assert codes[0] == 401 and codes[-1] == 429


def test_voice_tickets_are_rate_limited_per_ip(client):
    codes = [client.post("/auth/ws-ticket", headers=APP_ORIGIN).status_code for _ in range(25)]
    assert codes[0] == 200 and codes[-1] == 429
