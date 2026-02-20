"""Shared fixtures for claude_analysis tests."""

import json
import sqlite3
from pathlib import Path

import pytest

import cache_db


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Provide an isolated SQLite DB in tmp_path.

    Monkeypatches cache_db.DB_PATH so all cache_db functions
    use the temporary database instead of the real one.
    """
    db_dir = tmp_path / "data"
    db_dir.mkdir()
    db_path = db_dir / "cache.db"
    monkeypatch.setattr(cache_db, "DB_PATH", db_path)
    conn = cache_db.init_db()
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Sample JSONL fixtures
# ---------------------------------------------------------------------------
MINIMAL_SESSION_MESSAGES = [
    {
        "type": "summary",
        "session_id": "test-session-001",
        "timestamp": "2025-06-01T10:00:00Z",
        "summary": {
            "model": "claude-sonnet-4-20250514",
            "input_tokens": 1000,
            "output_tokens": 500,
            "cache_read_input_tokens": 200,
            "cache_creation_input_tokens": 100,
        },
    },
    {
        "type": "message",
        "message": {
            "role": "user",
            "content": "Implement a hello world function",
        },
        "timestamp": "2025-06-01T10:00:01Z",
    },
    {
        "type": "message",
        "message": {
            "role": "assistant",
            "model": "claude-sonnet-4-20250514",
            "usage": {
                "input_tokens": 800,
                "output_tokens": 300,
                "cache_read_input_tokens": 150,
                "cache_creation_input_tokens": 50,
            },
            "content": [
                {"type": "text", "text": "I'll create that for you."},
                {
                    "type": "tool_use",
                    "id": "tu_001",
                    "name": "Write",
                    "input": {
                        "file_path": "/tmp/hello.py",
                        "content": "def hello():\n    return 'Hello, World!'\n",
                    },
                },
            ],
        },
        "timestamp": "2025-06-01T10:00:05Z",
    },
    {
        "type": "message",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me also read the file."},
                {
                    "type": "tool_use",
                    "id": "tu_002",
                    "name": "Read",
                    "input": {"file_path": "/tmp/hello.py"},
                },
            ],
        },
        "timestamp": "2025-06-01T10:00:10Z",
    },
    {
        "type": "message",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Running tests."},
                {
                    "type": "tool_use",
                    "id": "tu_003",
                    "name": "Bash",
                    "input": {
                        "command": "cd /tmp && python -c \"from hello import hello; print(hello())\"",
                        "description": "Run hello function",
                    },
                },
            ],
        },
        "timestamp": "2025-06-01T10:00:15Z",
    },
]


@pytest.fixture()
def sample_jsonl(tmp_path):
    """Write a minimal valid JSONL session file to tmp_path.

    Returns the Path to the JSONL file.
    """
    jsonl_file = tmp_path / "session.jsonl"
    lines = [json.dumps(msg) for msg in MINIMAL_SESSION_MESSAGES]
    jsonl_file.write_text("\n".join(lines) + "\n")
    return jsonl_file


@pytest.fixture()
def empty_jsonl(tmp_path):
    """An empty JSONL file."""
    jsonl_file = tmp_path / "empty.jsonl"
    jsonl_file.write_text("")
    return jsonl_file


@pytest.fixture()
def malformed_jsonl(tmp_path):
    """JSONL file with some malformed lines."""
    jsonl_file = tmp_path / "malformed.jsonl"
    lines = [
        '{"type": "summary", "session_id": "test-bad"}',
        "NOT VALID JSON {{{",
        '{"type": "message", "message": {"role": "user", "content": "hello"}}',
        "",
        '{"type": "message", "message": {"role": "assistant", "content": "hi"}}',
    ]
    jsonl_file.write_text("\n".join(lines) + "\n")
    return jsonl_file


# ---------------------------------------------------------------------------
# Sample session data (already-parsed, for cache_db tests)
# ---------------------------------------------------------------------------
SAMPLE_SESSION_DATA = {
    "session_id": "test-session-001",
    "project": "test-project",
    "slug": "test-session",
    "prompt_preview": "Implement a hello world function",
    "start_time": "2025-06-01T10:00:00Z",
    "end_time": "2025-06-01T10:00:15Z",
    "model": "claude-sonnet-4-20250514",
    "total_tools": 3,
    "turn_count": 1,
    "active_duration_ms": 15000,
    "total_active_duration_ms": 15000,
    "cost_estimate": 0.0125,
    "permission_mode": "default",
    "interrupt_count": 0,
    "thinking_level": "normal",
    "tool_errors": 0,
    "tool_counts": {"Write": 1, "Read": 1, "Bash": 1},
    "file_extensions": {".py": 2},
    "tokens": {
        "input": 1000,
        "output": 500,
        "cache_read": 200,
        "cache_creation": 100,
    },
    "subagents": [],
}


@pytest.fixture()
def sample_session_data():
    """Return a copy of sample parsed session data dict."""
    return dict(SAMPLE_SESSION_DATA)


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------
@pytest.fixture()
def client(tmp_path, monkeypatch):
    """FastAPI TestClient with monkeypatched DB and template.

    Patches DB_PATH and skips the background rebuild thread so tests
    are deterministic and don't touch real JSONL files.
    """
    from fastapi.testclient import TestClient

    # Patch DB to tmp
    db_dir = tmp_path / "data"
    db_dir.mkdir()
    db_path = db_dir / "cache.db"
    monkeypatch.setattr(cache_db, "DB_PATH", db_path)

    # Initialize DB with schema
    conn = cache_db.init_db()

    # Insert sample data so endpoints have something to return
    cache_db.upsert_session(
        conn,
        "/fake/path/session.jsonl",
        SAMPLE_SESSION_DATA,
        1000000.0,
        5000,
    )
    cache_db.rebuild_global_aggregates(conn)
    conn.close()

    # Patch the background rebuild to be a no-op in tests
    import app as app_module

    monkeypatch.setattr(app_module, "_incremental_rebuild", lambda: {"status": "skipped"})
    monkeypatch.setattr(app_module, "_ensure_fresh", lambda: None)
    monkeypatch.setattr(app_module, "_last_rebuild", 9999999999.0)

    # Ensure the template exists (use real template)
    template_path = Path(__file__).parent.parent / "dashboard_template.html"
    monkeypatch.setattr(app_module, "TEMPLATE_PATH", template_path)

    with TestClient(app_module.app, raise_server_exceptions=False) as tc:
        yield tc
