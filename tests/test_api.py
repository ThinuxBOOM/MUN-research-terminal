"""Smoke tests for the web app (no LLM call required)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_home_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "MUN" in resp.text


def test_ask_page_renders(client):
    resp = client.get("/ask")
    assert resp.status_code == 200
    assert "Evidence" in resp.text


def test_library_page_renders(client):
    resp = client.get("/library")
    assert resp.status_code == 200


def test_settings_warns_when_model_missing(client):
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "Ollama endpoint" in resp.text
