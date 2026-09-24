"""/health says the process is up; /ready says it can serve (DB + Redis)."""

from fastapi.testclient import TestClient


def test_ready_when_database_and_redis_answer():
    from main import app

    with TestClient(app) as c:
        r = c.get("/ready")
    assert r.status_code == 200 and r.json() == {"database": "ok", "redis": "ok"}


def test_not_ready_when_redis_is_down(monkeypatch):
    import main

    def down():
        raise ConnectionError("redis unreachable")

    monkeypatch.setattr(main, "_ping_redis", down)
    with TestClient(main.app) as c:
        r = c.get("/ready")
    assert r.status_code == 503 and r.json()["redis"] == "down"
