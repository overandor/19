"""Integration tests for the FastAPI backend."""
import json
import pytest
from fastapi.testclient import TestClient

from backend import app

client = TestClient(app, raise_server_exceptions=True)


def test_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "uptime_seconds" in body


def test_health_no_auth_needed():
    """Health endpoint must be reachable without an API key."""
    resp = client.get("/health")
    assert resp.status_code == 200


def test_signals_returns_json():
    resp = client.get("/signals")
    assert resp.status_code == 200
    body = resp.json()
    assert "signals" in body
    assert "generated_at" in body


def test_scan_no_persist():
    resp = client.post("/scan", json={"persist": False})
    assert resp.status_code == 200
    body = resp.json()
    assert "signals" in body


def test_scan_empty_body():
    resp = client.post("/scan")
    assert resp.status_code == 200


def test_focus_returns_targets():
    resp = client.post("/focus")
    assert resp.status_code == 200
    body = resp.json()
    assert "targets" in body
    assert "entropy" in body


def test_openapi_schema_available():
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert schema["info"]["title"] == "Autonomous Alpha Console"
