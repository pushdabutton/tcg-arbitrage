"""Tests for FastAPI routes."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Patch settings BEFORE importing anything that uses them
from config import Settings


@pytest.fixture(autouse=True)
def _patch_settings(tmp_path, monkeypatch):
    """Override DB path to use temp directory for all tests."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("config.settings.DB_PATH", db_path)
    monkeypatch.setattr("config.settings.BASE_DIR", Path(__file__).resolve().parent.parent)
    from engine.database import init_db
    init_db(db_path)


@pytest.fixture()
def client():
    """Create a test client."""
    from fastapi.testclient import TestClient
    from main import create_app
    app = create_app()
    return TestClient(app)


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


def test_alerts_empty(client):
    resp = client.get("/api/alerts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["alerts"] == []
    assert data["count"] == 0


def test_cards_empty(client):
    resp = client.get("/api/cards")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cards"] == []


def test_card_prices_404(client):
    resp = client.get("/api/cards/NonExistent/FakeSet/prices")
    assert resp.status_code == 404


def test_dismiss_nonexistent(client):
    resp = client.post("/api/alerts/99999/dismiss")
    assert resp.status_code == 404


def test_dashboard_loads(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "TCG" in resp.text
    assert "Arbitrage" in resp.text
