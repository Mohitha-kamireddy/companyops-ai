import importlib

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    "package",
    ["agent", "tools", "policy", "recovery", "verification", "memory", "database", "api", "workers"],
)
def test_subpackages_importable(package):
    importlib.import_module(f"backend.app.{package}")
