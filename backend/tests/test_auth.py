from app.config import get_settings
from tests.conftest import PASSWORD


def test_login_flow(client):
    assert client.get("/api/auth/status").json()["authenticated"] is False
    assert client.get("/api/dashboard").status_code == 401
    r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401
    r = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert r.status_code == 200
    assert "dm_session" in r.cookies
    assert client.get("/api/auth/me").json() == {"username": "admin"}
    client.post("/api/auth/logout")
    client.cookies.clear()
    assert client.get("/api/auth/me").status_code == 401


def test_csrf_header_required(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD},
                    headers={"X-Requested-With": "other"})
    assert r.status_code == 403


def test_rate_limit(client):
    for _ in range(5):
        assert client.post("/api/auth/login", json={"username": "admin", "password": "x"}).status_code == 401
    r = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_password_change_invalidates_session(auth, monkeypatch):
    assert auth.get("/api/auth/me").status_code == 200
    monkeypatch.setenv("APP_PASSWORD", "new-password")
    get_settings.cache_clear()
    assert auth.get("/api/auth/me").status_code == 401


def test_health_is_public(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_api_never_exposes_keys(auth):
    body = auth.get("/api/settings").text
    assert "sk-or-test" not in body
