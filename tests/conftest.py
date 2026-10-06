import socket
import threading

import pytest
from werkzeug.serving import make_server

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


@pytest.fixture
def erp_app(make_app):
    """A fresh, seeded MiniERP app (its own temp database)."""
    return make_app()


@pytest.fixture
def erp_url(erp_app):
    """URL of a real MiniERP server running on a random local port for the test's duration."""
    server = make_server("127.0.0.1", 0, erp_app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture
def dead_erp_url():
    """A URL where nothing is listening, to simulate MiniERP being down."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"
