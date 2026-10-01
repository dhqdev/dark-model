from __future__ import annotations

import os

import httpx
import pytest
from fastapi.testclient import TestClient

from app import security
from app.api import usage as usage_api
from app.config import get_settings
from app.db import Base, init_engine
from app.providers import registry
from tests.fake_openrouter import FakeOpenRouter

PASSWORD = "s3cret-pass"


@pytest.fixture()
def fake(tmp_path, monkeypatch) -> FakeOpenRouter:
    monkeypatch.setenv("APP_USERNAME", "admin")
    monkeypatch.setenv("APP_PASSWORD", PASSWORD)
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key-0123456789-abcdefghijklmnop")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://fake.openrouter.test/api/v1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    # TEST_DATABASE_URL=postgresql://... roda a suíte no PostgreSQL (o CI usa SQLite e PostgreSQL)
    monkeypatch.setenv("DATABASE_URL", os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("EMBEDDED_WORKER", "false")
    monkeypatch.setenv("MOTION_SIZE", "320x180")
    monkeypatch.setenv("MOTION_FPS", "10")
    monkeypatch.setenv("FX_AUTO", "false")  # sem cotação ao vivo nos testes
    monkeypatch.setenv("USD_BRL", "5.0")
    monkeypatch.delenv("OPENROUTER_MANAGEMENT_KEY", raising=False)
    get_settings.cache_clear()
    engine = init_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    fake = FakeOpenRouter()
    registry.configure_for_tests(httpx.MockTransport(fake.handler))
    security._failures.clear()
    usage_api._balance_cache.clear()
    yield fake
    registry.configure_for_tests(None, video_poll_seconds=None, sleep=None)
    get_settings.cache_clear()


@pytest.fixture()
def client(fake):
    from app.main import create_app

    with TestClient(create_app(background=False)) as c:
        c.headers.update({"X-Requested-With": "dark-model"})
        yield c


@pytest.fixture()
def auth(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert r.status_code == 200, r.text
    return client
