"""Tests for cache_db.py — SQLite persistent cache."""

import json

import pytest

import cache_db


class TestInitDb:
    """Tests for init_db and schema creation."""

    def test_creates_tables(self, tmp_db):
        """init_db creates all required tables."""
        tables = [
            row[0]
            for row in tmp_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "file_cache" in tables
        assert "session_summaries" in tables
        assert "session_details" in tables
        assert "global_aggregates" in tables

    def test_wal_mode(self, tmp_db):
        """Database uses WAL journal mode."""
        mode = tmp_db.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_idempotent(self, tmp_db):
        """Calling init_db twice doesn't raise."""
        # tmp_db already called init_db; call again
        conn2 = cache_db.init_db()
        conn2.close()


class TestUpsertSession:
    """Tests for upsert_session round-trips."""

    def test_insert_and_read_back(self, tmp_db, sample_session_data):
        """Inserted session can be read back from all tables."""
        cache_db.upsert_session(
            tmp_db, "/test/path.jsonl", sample_session_data, 1000.0, 5000
        )
        tmp_db.commit()

        # Check file_cache
        row = tmp_db.execute(
            "SELECT * FROM file_cache WHERE file_path = ?", ("/test/path.jsonl",)
        ).fetchone()
        assert row is not None
        assert row["session_id"] == "test-session-001"

        # Check session_summaries
        row = tmp_db.execute(
            "SELECT * FROM session_summaries WHERE session_id = ?",
            ("test-session-001",),
        ).fetchone()
        assert row is not None
        assert row["project"] == "test-project"
        assert row["total_tools"] == 3
        assert row["cost_estimate"] == pytest.approx(0.0125)

        # Check session_details
        row = tmp_db.execute(
            "SELECT detail_json FROM session_details WHERE session_id = ?",
            ("test-session-001",),
        ).fetchone()
        assert row is not None
        detail = json.loads(row["detail_json"])
        assert detail["session_id"] == "test-session-001"

    def test_upsert_replaces_existing(self, tmp_db, sample_session_data):
        """Upserting same session_id replaces existing data."""
        cache_db.upsert_session(
            tmp_db, "/test/path.jsonl", sample_session_data, 1000.0, 5000
        )
        tmp_db.commit()

        # Update and re-upsert
        sample_session_data["total_tools"] = 99
        cache_db.upsert_session(
            tmp_db, "/test/path.jsonl", sample_session_data, 2000.0, 6000
        )
        tmp_db.commit()

        row = tmp_db.execute(
            "SELECT total_tools FROM session_summaries WHERE session_id = ?",
            ("test-session-001",),
        ).fetchone()
        assert row["total_tools"] == 99

    def test_computes_combined_tool_counts(self, tmp_db, sample_session_data):
        """Subagent tool counts are merged into combined tool_counts_json."""
        sample_session_data["subagents"] = [
            {"tool_count": 5, "tool_counts": {"Read": 3, "Grep": 2}},
        ]
        cache_db.upsert_session(
            tmp_db, "/test/path.jsonl", sample_session_data, 1000.0, 5000
        )
        tmp_db.commit()

        row = tmp_db.execute(
            "SELECT tool_counts_json, total_actions FROM session_summaries WHERE session_id = ?",
            ("test-session-001",),
        ).fetchone()
        tc = json.loads(row["tool_counts_json"])
        # Read: 1 (parent) + 3 (subagent) = 4
        assert tc["Read"] == 4
        assert tc["Grep"] == 2
        # total_actions = parent total_tools (3) + subagent tool_count (5)
        assert row["total_actions"] == 8


class TestGetStaleFiles:
    """Tests for staleness detection."""

    def test_new_file_is_stale(self, tmp_db, tmp_path):
        """A file not in cache is returned as stale."""
        jsonl = tmp_path / "new_session.jsonl"
        jsonl.write_text('{"type":"summary"}\n')

        stale, current = cache_db.get_stale_files(tmp_db, [jsonl])
        assert jsonl in stale
        assert str(jsonl) in current

    def test_cached_file_not_stale(self, tmp_db, tmp_path, sample_session_data):
        """A file already cached with same mtime/size is not stale."""
        jsonl = tmp_path / "cached.jsonl"
        jsonl.write_text('{"type":"summary"}\n')
        stat = jsonl.stat()

        # Pre-cache it
        cache_db.upsert_session(
            tmp_db, str(jsonl), sample_session_data, stat.st_mtime, stat.st_size
        )
        tmp_db.commit()

        stale, current = cache_db.get_stale_files(tmp_db, [jsonl])
        assert stale == []
        assert str(jsonl) in current

    def test_modified_file_is_stale(self, tmp_db, tmp_path, sample_session_data):
        """A file with changed mtime is returned as stale."""
        jsonl = tmp_path / "modified.jsonl"
        jsonl.write_text('{"type":"summary"}\n')

        # Cache with old mtime
        cache_db.upsert_session(
            tmp_db, str(jsonl), sample_session_data, 0.0, 0
        )
        tmp_db.commit()

        stale, _ = cache_db.get_stale_files(tmp_db, [jsonl])
        assert jsonl in stale


class TestDeleteRemovedSessions:
    """Tests for cleaning up sessions whose files are gone."""

    def test_removes_orphaned_sessions(self, tmp_db, sample_session_data):
        """Sessions whose JSONL files are gone get cleaned up."""
        cache_db.upsert_session(
            tmp_db, "/gone/file.jsonl", sample_session_data, 1000.0, 5000
        )
        tmp_db.commit()

        removed = cache_db.delete_removed_sessions(tmp_db, set())
        tmp_db.commit()
        assert removed == 1

        row = tmp_db.execute(
            "SELECT * FROM session_summaries WHERE session_id = ?",
            ("test-session-001",),
        ).fetchone()
        assert row is None

    def test_keeps_existing_files(self, tmp_db, sample_session_data):
        """Sessions whose files still exist are kept."""
        path = "/still/here.jsonl"
        cache_db.upsert_session(
            tmp_db, path, sample_session_data, 1000.0, 5000
        )
        tmp_db.commit()

        removed = cache_db.delete_removed_sessions(tmp_db, {path})
        assert removed == 0


class TestGlobalAggregates:
    """Tests for rebuild_global_aggregates."""

    def test_empty_db_clears_aggregates(self, tmp_db):
        """With no sessions, aggregates row is deleted."""
        cache_db.rebuild_global_aggregates(tmp_db)
        row = tmp_db.execute(
            "SELECT * FROM global_aggregates WHERE id = 1"
        ).fetchone()
        assert row is None

    def test_single_session_aggregates(self, tmp_db, sample_session_data):
        """Aggregates are computed correctly from a single session."""
        cache_db.upsert_session(
            tmp_db, "/test.jsonl", sample_session_data, 1000.0, 5000
        )
        tmp_db.commit()
        cache_db.rebuild_global_aggregates(tmp_db)

        row = tmp_db.execute(
            "SELECT * FROM global_aggregates WHERE id = 1"
        ).fetchone()
        assert row is not None
        assert row["total_sessions"] == 1
        assert row["total_tools"] == 3
        assert row["total_cost"] == pytest.approx(0.0125)

    def test_overview_payload_structure(self, tmp_db, sample_session_data):
        """get_overview_payload returns expected keys."""
        cache_db.upsert_session(
            tmp_db, "/test.jsonl", sample_session_data, 1000.0, 5000
        )
        tmp_db.commit()
        cache_db.rebuild_global_aggregates(tmp_db)

        payload = cache_db.get_overview_payload(tmp_db)
        assert payload is not None
        assert "total_sessions" in payload
        assert "tool_distribution" in payload
        assert "projects_chart" in payload
        assert "weekly_timeline" in payload
        assert "projects_list" in payload
        assert isinstance(payload["tool_distribution"], dict)
        assert isinstance(payload["projects_list"], list)


class TestQueryHelpers:
    """Tests for get_session_list, get_session_detail, etc."""

    def test_get_session_list(self, tmp_db, sample_session_data):
        """Session list returns inserted sessions."""
        cache_db.upsert_session(
            tmp_db, "/test.jsonl", sample_session_data, 1000.0, 5000
        )
        tmp_db.commit()

        sessions = cache_db.get_session_list(tmp_db)
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "test-session-001"

    def test_get_session_list_with_project_filter(self, tmp_db, sample_session_data):
        """Session list filters by project."""
        cache_db.upsert_session(
            tmp_db, "/test.jsonl", sample_session_data, 1000.0, 5000
        )
        tmp_db.commit()

        # Matching project
        sessions = cache_db.get_session_list(tmp_db, project="test-project")
        assert len(sessions) == 1

        # Non-matching project
        sessions = cache_db.get_session_list(tmp_db, project="other-project")
        assert len(sessions) == 0

    def test_get_session_detail(self, tmp_db, sample_session_data):
        """Session detail returns full JSON data."""
        cache_db.upsert_session(
            tmp_db, "/test.jsonl", sample_session_data, 1000.0, 5000
        )
        tmp_db.commit()

        detail = cache_db.get_session_detail(tmp_db, "test-session-001")
        assert detail is not None
        assert detail["session_id"] == "test-session-001"

    def test_get_session_detail_missing(self, tmp_db):
        """Non-existent session returns None."""
        detail = cache_db.get_session_detail(tmp_db, "nonexistent")
        assert detail is None

    def test_get_session_count(self, tmp_db, sample_session_data):
        """Session count reflects inserted sessions."""
        assert cache_db.get_session_count(tmp_db) == 0

        cache_db.upsert_session(
            tmp_db, "/test.jsonl", sample_session_data, 1000.0, 5000
        )
        tmp_db.commit()
        assert cache_db.get_session_count(tmp_db) == 1

    def test_get_projects_list(self, tmp_db, sample_session_data):
        """Projects list returns distinct projects."""
        cache_db.upsert_session(
            tmp_db, "/test.jsonl", sample_session_data, 1000.0, 5000
        )
        tmp_db.commit()

        projects = cache_db.get_projects_list(tmp_db)
        assert "test-project" in projects
