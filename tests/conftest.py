import pytest

from erp import create_app

ADMIN = {"username": "admin", "password": "admin123"}


@pytest.fixture(autouse=True)
def _clean_minierp_env(monkeypatch):
    """Make sure a developer's shell settings can't leak into the tests."""
    for name in ("MINIERP_SESSION_EXPIRY_ACTIONS", "MINIERP_DB_PATH", "MINIERP_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def make_app(tmp_path):
    """Build a MiniERP app backed by a fresh, seeded temp database."""

    def _make(**config):
        return create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db"), **config})

    return _make


@pytest.fixture
def client(make_app):
    return make_app().test_client()


@pytest.fixture
def logged_in_client(client):
    client.post("/login", data=ADMIN)
    return client
