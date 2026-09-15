import os

import pytest
from fastapi.testclient import TestClient

os.environ["APP_DEBUG"] = "false"
os.environ["DATABASE_URL"] = "postgresql://test:test@localhost:5432/test"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["CORS_ALLOWED_ORIGINS"] = '["http://localhost:5173"]'

from nexus.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
