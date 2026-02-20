"""Tests for app.py — FastAPI endpoints."""

import json

import pytest


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    def test_healthz_returns_200(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


class TestOverviewEndpoint:
    """Tests for GET /api/overview."""

    def test_returns_valid_json(self, client):
        resp = client.get("/api/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_sessions" in data
        assert "total_tools" in data
        assert "tool_distribution" in data

    def test_returns_aggregated_data(self, client):
        resp = client.get("/api/overview")
        data = resp.json()
        assert data["total_sessions"] == 1
        assert data["total_tools"] == 3


class TestSessionsEndpoint:
    """Tests for GET /api/sessions."""

    def test_returns_list(self, client):
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["session_id"] == "test-session-001"

    def test_filter_by_project(self, client):
        resp = client.get("/api/sessions?project=test-project")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

    def test_filter_nonexistent_project(self, client):
        resp = client.get("/api/sessions?project=nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 0


class TestSessionDetailEndpoint:
    """Tests for GET /api/session/{id}."""

    def test_valid_session(self, client):
        resp = client.get("/api/session/test-session-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "test-session-001"
        assert data["project"] == "test-project"

    def test_missing_session_404(self, client):
        resp = client.get("/api/session/nonexistent-id")
        assert resp.status_code == 404


class TestDashboardHtml:
    """Tests for GET / (HTML dashboard)."""

    def test_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_injects_data(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        # The template replacement injects DASHBOARD_DATA with real data
        assert "DASHBOARD_DATA" in resp.text
        # Should contain session data (not the empty placeholder)
        assert "test-session-001" in resp.text


class TestDataEndpoint:
    """Tests for GET /api/data (deprecated but must still work)."""

    def test_returns_backward_compatible_payload(self, client):
        resp = client.get("/api/data")
        assert resp.status_code == 200
        data = resp.json()
        assert "generated_at" in data
        assert "projects" in data
        assert "sessions" in data
        assert isinstance(data["sessions"], list)


class TestRebuildEndpoints:
    """Tests for rebuild-related endpoints."""

    def test_refresh_returns_status(self, client):
        resp = client.get("/api/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data

    def test_rebuild_status(self, client):
        resp = client.get("/api/rebuild-status")
        assert resp.status_code == 200
        data = resp.json()
        assert "in_progress" in data
