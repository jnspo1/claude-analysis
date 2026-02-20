"""
SQLite persistent cache for the Claude Activity Dashboard.

Stores parsed session data so rebuilds only process new/changed JSONL files.
Pre-computes global aggregates for instant overview rendering.

DB location: data/cache.db (WAL mode for concurrent reads during writes).
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent / "data" / "cache.db"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
_SCHEMA = """
CREATE TABLE IF NOT EXISTS file_cache (
    file_path  TEXT PRIMARY KEY,
    file_mtime REAL NOT NULL,
    file_size  INTEGER NOT NULL,
    session_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_summaries (
    session_id               TEXT PRIMARY KEY,
    project                  TEXT NOT NULL,
    slug                     TEXT,
    prompt_preview           TEXT,
    start_time               TEXT,
    end_time                 TEXT,
    model                    TEXT,
    total_tools              INTEGER DEFAULT 0,
    total_actions            INTEGER DEFAULT 0,
    turn_count               INTEGER DEFAULT 0,
    subagent_count           INTEGER DEFAULT 0,
    active_duration_ms       INTEGER DEFAULT 0,
    total_active_duration_ms INTEGER DEFAULT 0,
    cost_estimate            REAL DEFAULT 0,
    permission_mode          TEXT,
    interrupt_count          INTEGER DEFAULT 0,
    thinking_level           TEXT,
    tool_errors              INTEGER DEFAULT 0,
    tool_counts_json         TEXT,
    file_extensions_json     TEXT,
    tokens_json              TEXT
);

CREATE TABLE IF NOT EXISTS session_details (
    session_id TEXT PRIMARY KEY,
    detail_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS global_aggregates (
    id                          INTEGER PRIMARY KEY CHECK (id = 1),
    generated_at                TEXT,
    total_sessions              INTEGER,
    total_tools                 INTEGER,
    total_actions               INTEGER,
    total_cost                  REAL,
    total_input_tokens          INTEGER,
    total_output_tokens         INTEGER,
    total_cache_read_tokens     INTEGER,
    total_cache_creation_tokens INTEGER,
    total_active_ms             INTEGER,
    date_range_start            TEXT,
    date_range_end              TEXT,
    project_count               INTEGER,
    subagent_count              INTEGER,
    subagent_tools              INTEGER,
    tool_distribution_json      TEXT,
    projects_chart_json         TEXT,
    weekly_timeline_json        TEXT,
    daily_timeline_json         TEXT,
    monthly_timeline_json       TEXT,
    file_types_chart_json       TEXT,
    projects_list_json          TEXT,
    tool_distribution_1d_json   TEXT,
    tool_distribution_7d_json   TEXT,
    tool_distribution_30d_json  TEXT,
    projects_chart_1d_json      TEXT,
    projects_chart_7d_json      TEXT,
    projects_chart_30d_json     TEXT,
    file_types_chart_1d_json    TEXT,
    file_types_chart_7d_json    TEXT,
    file_types_chart_30d_json   TEXT,
    cost_by_project_json        TEXT,
    cost_by_project_1d_json     TEXT,
    cost_by_project_7d_json     TEXT,
    cost_by_project_30d_json    TEXT,
    actions_daily_json          TEXT,
    actions_weekly_json         TEXT,
    actions_monthly_json        TEXT,
    active_time_daily_json      TEXT,
    active_time_weekly_json     TEXT,
    active_time_monthly_json    TEXT
);
"""


def get_connection() -> sqlite3.Connection:
    """Get a SQLite connection with WAL mode and row factory."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _migrate_global_aggregates(conn: sqlite3.Connection) -> None:
    """Add new columns to global_aggregates if they don't exist yet."""
    new_columns = [
        ("total_cache_creation_tokens", "INTEGER"),
        ("daily_timeline_json", "TEXT"),
        ("monthly_timeline_json", "TEXT"),
        ("tool_distribution_1d_json", "TEXT"),
        ("tool_distribution_7d_json", "TEXT"),
        ("tool_distribution_30d_json", "TEXT"),
        ("projects_chart_1d_json", "TEXT"),
        ("projects_chart_7d_json", "TEXT"),
        ("projects_chart_30d_json", "TEXT"),
        ("file_types_chart_1d_json", "TEXT"),
        ("file_types_chart_7d_json", "TEXT"),
        ("file_types_chart_30d_json", "TEXT"),
        ("cost_by_project_json", "TEXT"),
        ("cost_by_project_1d_json", "TEXT"),
        ("cost_by_project_7d_json", "TEXT"),
        ("cost_by_project_30d_json", "TEXT"),
        ("actions_daily_json", "TEXT"),
        ("actions_weekly_json", "TEXT"),
        ("actions_monthly_json", "TEXT"),
        ("active_time_daily_json", "TEXT"),
        ("active_time_weekly_json", "TEXT"),
        ("active_time_monthly_json", "TEXT"),
    ]
    for col_name, col_type in new_columns:
        try:
            conn.execute(
                f"ALTER TABLE global_aggregates ADD COLUMN {col_name} {col_type}"
            )
        except sqlite3.OperationalError:
            pass  # Column already exists
    conn.commit()


def init_db() -> sqlite3.Connection:
    """Create schema and return connection."""
    conn = get_connection()
    conn.executescript(_SCHEMA)
    _migrate_global_aggregates(conn)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Staleness detection
# ---------------------------------------------------------------------------
def get_stale_files(
    conn: sqlite3.Connection,
    jsonl_files: list[Path],
) -> tuple[list[Path], set[str]]:
    """Compare filesystem against file_cache, return files needing reparse.

    Returns:
        (stale_files, current_paths) - files to reparse and set of all current paths
    """
    current_paths: set[str] = set()
    stale: list[Path] = []

    # Build lookup of cached files
    cached = {}
    for row in conn.execute("SELECT file_path, file_mtime, file_size FROM file_cache"):
        cached[row["file_path"]] = (row["file_mtime"], row["file_size"])

    for path in jsonl_files:
        path_str = str(path)
        current_paths.add(path_str)

        try:
            stat = path.stat()
        except OSError:
            continue

        cache_entry = cached.get(path_str)
        if cache_entry is None:
            # New file
            stale.append(path)
        elif cache_entry[0] != stat.st_mtime or cache_entry[1] != stat.st_size:
            # Modified file
            stale.append(path)

    return stale, current_paths


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------
def upsert_session(
    conn: sqlite3.Connection,
    file_path: str,
    session_data: dict[str, Any],
    file_mtime: float,
    file_size: int,
) -> None:
    """Insert or replace a parsed session into all tables."""
    sid = session_data["session_id"]

    # Compute combined tool counts (parent + subagent)
    combined_tool_counts = dict(session_data.get("tool_counts", {}))
    subagent_tools = 0
    for sa in session_data.get("subagents", []):
        subagent_tools += sa.get("tool_count", 0)
        for tool, count in sa.get("tool_counts", {}).items():
            combined_tool_counts[tool] = combined_tool_counts.get(tool, 0) + count

    total_actions = session_data.get("total_tools", 0) + subagent_tools

    conn.execute(
        """INSERT OR REPLACE INTO file_cache (file_path, file_mtime, file_size, session_id)
           VALUES (?, ?, ?, ?)""",
        (file_path, file_mtime, file_size, sid),
    )

    tokens = session_data.get("tokens", {})
    conn.execute(
        """INSERT OR REPLACE INTO session_summaries (
            session_id, project, slug, prompt_preview, start_time, end_time,
            model, total_tools, total_actions, turn_count, subagent_count,
            active_duration_ms, total_active_duration_ms, cost_estimate,
            permission_mode, interrupt_count, thinking_level, tool_errors,
            tool_counts_json, file_extensions_json, tokens_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            sid,
            session_data.get("project", ""),
            session_data.get("slug"),
            session_data.get("prompt_preview"),
            session_data.get("start_time"),
            session_data.get("end_time"),
            session_data.get("model"),
            session_data.get("total_tools", 0),
            total_actions,
            session_data.get("turn_count", 0),
            len(session_data.get("subagents", [])),
            session_data.get("active_duration_ms", 0),
            session_data.get("total_active_duration_ms", 0),
            session_data.get("cost_estimate", 0),
            session_data.get("permission_mode"),
            session_data.get("interrupt_count", 0),
            session_data.get("thinking_level"),
            session_data.get("tool_errors", 0),
            json.dumps(combined_tool_counts),
            json.dumps(dict(session_data.get("file_extensions", {}))),
            json.dumps(tokens),
        ),
    )

    conn.execute(
        """INSERT OR REPLACE INTO session_details (session_id, detail_json)
           VALUES (?, ?)""",
        (sid, json.dumps(session_data, default=str)),
    )


def delete_removed_sessions(
    conn: sqlite3.Connection, current_paths: set[str]
) -> int:
    """Remove sessions whose JSONL files no longer exist. Returns count deleted."""
    cached_paths = [
        row[0] for row in conn.execute("SELECT file_path FROM file_cache").fetchall()
    ]
    removed = [p for p in cached_paths if p not in current_paths]

    if not removed:
        return 0

    for path in removed:
        row = conn.execute(
            "SELECT session_id FROM file_cache WHERE file_path = ?", (path,)
        ).fetchone()
        if row:
            sid = row[0]
            conn.execute("DELETE FROM session_summaries WHERE session_id = ?", (sid,))
            conn.execute("DELETE FROM session_details WHERE session_id = ?", (sid,))
        conn.execute("DELETE FROM file_cache WHERE file_path = ?", (path,))

    return len(removed)


# ---------------------------------------------------------------------------
# Global aggregates — helpers
# ---------------------------------------------------------------------------
def _parse_row_json(raw: str | None, default: str = "{}") -> dict[str, Any]:
    """Safely parse a JSON string from a DB column."""
    try:
        return json.loads(raw or default)
    except (json.JSONDecodeError, TypeError):
        return json.loads(default)


def _round_cost_counter(c: Counter, top_n: int = 15) -> dict[str, float]:
    """Round cost values and keep top N entries for cleaner JSON output."""
    return {k: round(v, 4) for k, v in c.most_common(top_n)}


def _accumulate_session_stats(rows: list) -> dict[str, Any]:
    """Loop over session rows and accumulate all counters.

    Returns a dict of accumulated stats ready for payload building.
    """
    now = datetime.now()
    totals = {
        "sessions": len(rows), "tools": 0, "actions": 0, "cost": 0.0,
        "input_tokens": 0, "output_tokens": 0, "cache_read": 0,
        "cache_creation": 0, "active_ms": 0, "subagents": 0, "subagent_tools": 0,
    }
    all_starts: list[str] = []
    all_ends: list[str] = []

    # All-time counters
    projects: Counter = Counter()
    tool_distribution: Counter = Counter()
    file_types: Counter = Counter()
    cost_by_project: Counter = Counter()

    # Timeline counters
    day_counts: Counter = Counter()
    week_counts: Counter = Counter()
    month_counts: Counter = Counter()

    # Time-range counters keyed by range name
    range_counters = {
        d: {"tools": Counter(), "projects": Counter(),
            "file_types": Counter(), "cost": Counter()}
        for d in (1, 7, 30)
    }

    # Actions and active time over time
    actions_buckets = {"daily": {}, "weekly": {}, "monthly": {}}
    active_time_buckets = {"daily": {}, "weekly": {}, "monthly": {}}

    for row in rows:
        totals["tools"] += row["total_tools"]
        totals["actions"] += row["total_actions"]
        totals["cost"] += row["cost_estimate"] or 0
        totals["subagents"] += row["subagent_count"] or 0
        totals["subagent_tools"] += (row["total_actions"] or 0) - (row["total_tools"] or 0)
        totals["active_ms"] += row["total_active_duration_ms"] or 0

        if row["start_time"]:
            all_starts.append(row["start_time"])
        if row["end_time"]:
            all_ends.append(row["end_time"])

        projects[row["project"]] += row["total_actions"] or 0
        cost_by_project[row["project"]] += row["cost_estimate"] or 0

        tc = _parse_row_json(row["tool_counts_json"])
        fe = _parse_row_json(row["file_extensions_json"])

        for tool, count in tc.items():
            tool_distribution[tool] += count
        for ext, count in fe.items():
            file_types[ext] += count

        tokens = _parse_row_json(row["tokens_json"])
        totals["input_tokens"] += tokens.get("input", 0)
        totals["output_tokens"] += tokens.get("output", 0)
        totals["cache_read"] += tokens.get("cache_read", 0)
        totals["cache_creation"] += tokens.get("cache_creation", 0)

        # Time-based accumulation
        if row["start_time"]:
            _accumulate_time_stats(
                row, tc, fe, now, day_counts, week_counts, month_counts,
                range_counters, actions_buckets, active_time_buckets,
            )

    return {
        "totals": totals,
        "all_starts": all_starts,
        "all_ends": all_ends,
        "projects": projects,
        "tool_distribution": tool_distribution,
        "file_types": file_types,
        "cost_by_project": cost_by_project,
        "day_counts": day_counts,
        "week_counts": week_counts,
        "month_counts": month_counts,
        "range_counters": range_counters,
        "actions_buckets": actions_buckets,
        "active_time_buckets": active_time_buckets,
        "projects_set": sorted(set(row["project"] for row in rows)),
    }


def _accumulate_time_stats(
    row: Any, tc: dict, fe: dict, now: datetime,
    day_counts: Counter, week_counts: Counter, month_counts: Counter,
    range_counters: dict, actions_buckets: dict, active_time_buckets: dict,
) -> None:
    """Accumulate timeline and time-range stats for a single row."""
    try:
        dt = datetime.fromisoformat(row["start_time"].replace("Z", "+00:00"))
        dt_naive = dt.replace(tzinfo=None)
    except (ValueError, TypeError):
        return

    day_key = dt.date().isoformat()
    day_counts[day_key] += 1

    week_start = dt.date() - timedelta(days=dt.weekday())
    week_key = week_start.isoformat()
    week_counts[week_key] += 1

    month_key = dt.strftime("%Y-%m")
    month_counts[month_key] += 1

    # Time-range filters
    age_days = (now - dt_naive).total_seconds() / 86400
    actions = row["total_actions"] or 0

    for days in (1, 7, 30):
        if age_days <= days:
            rc = range_counters[days]
            rc["projects"][row["project"]] += actions
            rc["cost"][row["project"]] += row["cost_estimate"] or 0
            for tool, count in tc.items():
                rc["tools"][tool] += count
            for ext, count in fe.items():
                rc["file_types"][ext] += count

    # Actions over time
    direct = row["total_tools"] or 0
    subagent = actions - direct
    for bucket_name, key in [("daily", day_key), ("weekly", week_key), ("monthly", month_key)]:
        bucket = actions_buckets[bucket_name]
        if key not in bucket:
            bucket[key] = {"direct": 0, "subagent": 0, "total": 0}
        bucket[key]["direct"] += direct
        bucket[key]["subagent"] += subagent
        bucket[key]["total"] += actions

    # Active time over time
    active_ms = row["total_active_duration_ms"] or 0
    for bucket_name, key in [("daily", day_key), ("weekly", week_key), ("monthly", month_key)]:
        bucket = active_time_buckets[bucket_name]
        bucket[key] = bucket.get(key, 0) + active_ms


def _build_aggregate_payload(stats: dict[str, Any]) -> dict[str, Any]:
    """Assemble the aggregate payload dict from accumulated stats."""
    t = stats["totals"]
    rc = stats["range_counters"]

    return {
        "generated_at": datetime.now().isoformat(),
        "total_sessions": t["sessions"],
        "total_tools": t["tools"],
        "total_actions": t["actions"],
        "total_cost": round(t["cost"], 4),
        "total_input_tokens": t["input_tokens"],
        "total_output_tokens": t["output_tokens"],
        "total_cache_read_tokens": t["cache_read"],
        "total_cache_creation_tokens": t["cache_creation"],
        "total_active_ms": t["active_ms"],
        "date_range_start": min(stats["all_starts"]) if stats["all_starts"] else None,
        "date_range_end": max(stats["all_ends"]) if stats["all_ends"] else None,
        "project_count": len(stats["projects_set"]),
        "subagent_count": t["subagents"],
        "subagent_tools": t["subagent_tools"],
        # All-time charts
        "tool_distribution": dict(stats["tool_distribution"].most_common()),
        "projects_chart": dict(stats["projects"].most_common(15)),
        "weekly_timeline": dict(sorted(stats["week_counts"].items())),
        "daily_timeline": dict(sorted(stats["day_counts"].items())),
        "monthly_timeline": dict(sorted(stats["month_counts"].items())),
        "file_types_chart": dict(stats["file_types"].most_common(15)),
        "projects_list": stats["projects_set"],
        # Time-range charts
        "tool_distribution_1d": dict(Counter(rc[1]["tools"]).most_common()),
        "tool_distribution_7d": dict(Counter(rc[7]["tools"]).most_common()),
        "tool_distribution_30d": dict(Counter(rc[30]["tools"]).most_common()),
        "projects_chart_1d": dict(rc[1]["projects"].most_common(15)),
        "projects_chart_7d": dict(rc[7]["projects"].most_common(15)),
        "projects_chart_30d": dict(rc[30]["projects"].most_common(15)),
        "file_types_chart_1d": dict(rc[1]["file_types"].most_common(15)),
        "file_types_chart_7d": dict(rc[7]["file_types"].most_common(15)),
        "file_types_chart_30d": dict(rc[30]["file_types"].most_common(15)),
        # Cost by project
        "cost_by_project": _round_cost_counter(stats["cost_by_project"]),
        "cost_by_project_1d": _round_cost_counter(rc[1]["cost"]),
        "cost_by_project_7d": _round_cost_counter(rc[7]["cost"]),
        "cost_by_project_30d": _round_cost_counter(rc[30]["cost"]),
        # Actions over time
        "actions_daily": dict(sorted(stats["actions_buckets"]["daily"].items())),
        "actions_weekly": dict(sorted(stats["actions_buckets"]["weekly"].items())),
        "actions_monthly": dict(sorted(stats["actions_buckets"]["monthly"].items())),
        # Active time over time
        "active_time_daily": dict(sorted(stats["active_time_buckets"]["daily"].items())),
        "active_time_weekly": dict(sorted(stats["active_time_buckets"]["weekly"].items())),
        "active_time_monthly": dict(sorted(stats["active_time_buckets"]["monthly"].items())),
    }


def _persist_aggregates(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    """Write the aggregate payload to the global_aggregates table."""
    conn.execute(
        """INSERT OR REPLACE INTO global_aggregates (
            id, generated_at, total_sessions, total_tools, total_actions,
            total_cost, total_input_tokens, total_output_tokens,
            total_cache_read_tokens, total_cache_creation_tokens, total_active_ms,
            date_range_start, date_range_end, project_count,
            subagent_count, subagent_tools,
            tool_distribution_json, projects_chart_json,
            weekly_timeline_json, daily_timeline_json, monthly_timeline_json,
            file_types_chart_json, projects_list_json,
            tool_distribution_1d_json, tool_distribution_7d_json, tool_distribution_30d_json,
            projects_chart_1d_json, projects_chart_7d_json, projects_chart_30d_json,
            file_types_chart_1d_json, file_types_chart_7d_json, file_types_chart_30d_json,
            cost_by_project_json, cost_by_project_1d_json, cost_by_project_7d_json, cost_by_project_30d_json,
            actions_daily_json, actions_weekly_json, actions_monthly_json,
            active_time_daily_json, active_time_weekly_json, active_time_monthly_json
        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            payload["generated_at"],
            payload["total_sessions"],
            payload["total_tools"],
            payload["total_actions"],
            payload["total_cost"],
            payload["total_input_tokens"],
            payload["total_output_tokens"],
            payload["total_cache_read_tokens"],
            payload["total_cache_creation_tokens"],
            payload["total_active_ms"],
            payload["date_range_start"],
            payload["date_range_end"],
            payload["project_count"],
            payload["subagent_count"],
            payload["subagent_tools"],
            json.dumps(payload["tool_distribution"]),
            json.dumps(payload["projects_chart"]),
            json.dumps(payload["weekly_timeline"]),
            json.dumps(payload["daily_timeline"]),
            json.dumps(payload["monthly_timeline"]),
            json.dumps(payload["file_types_chart"]),
            json.dumps(payload["projects_list"]),
            json.dumps(payload["tool_distribution_1d"]),
            json.dumps(payload["tool_distribution_7d"]),
            json.dumps(payload["tool_distribution_30d"]),
            json.dumps(payload["projects_chart_1d"]),
            json.dumps(payload["projects_chart_7d"]),
            json.dumps(payload["projects_chart_30d"]),
            json.dumps(payload["file_types_chart_1d"]),
            json.dumps(payload["file_types_chart_7d"]),
            json.dumps(payload["file_types_chart_30d"]),
            json.dumps(payload["cost_by_project"]),
            json.dumps(payload["cost_by_project_1d"]),
            json.dumps(payload["cost_by_project_7d"]),
            json.dumps(payload["cost_by_project_30d"]),
            json.dumps(payload["actions_daily"]),
            json.dumps(payload["actions_weekly"]),
            json.dumps(payload["actions_monthly"]),
            json.dumps(payload["active_time_daily"]),
            json.dumps(payload["active_time_weekly"]),
            json.dumps(payload["active_time_monthly"]),
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Global aggregates — main entry point
# ---------------------------------------------------------------------------
def rebuild_global_aggregates(conn: sqlite3.Connection) -> None:
    """Recompute overview aggregates from all session_summaries rows."""
    rows = conn.execute(
        """SELECT project, total_tools, total_actions, cost_estimate,
                  subagent_count, start_time, end_time,
                  active_duration_ms, total_active_duration_ms,
                  tool_counts_json, file_extensions_json, tokens_json
           FROM session_summaries"""
    ).fetchall()

    if not rows:
        conn.execute("DELETE FROM global_aggregates WHERE id = 1")
        conn.commit()
        return

    stats = _accumulate_session_stats(rows)
    payload = _build_aggregate_payload(stats)
    _persist_aggregates(conn, payload)


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------
def get_overview_payload(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Read pre-computed global aggregates for the overview tab."""
    row = conn.execute("SELECT * FROM global_aggregates WHERE id = 1").fetchone()
    if not row:
        return None

    return {
        "generated_at": row["generated_at"],
        "total_sessions": row["total_sessions"],
        "total_tools": row["total_tools"],
        "total_actions": row["total_actions"],
        "total_cost": row["total_cost"],
        "total_input_tokens": row["total_input_tokens"],
        "total_output_tokens": row["total_output_tokens"],
        "total_cache_read_tokens": row["total_cache_read_tokens"],
        "total_cache_creation_tokens": row["total_cache_creation_tokens"] or 0,
        "total_active_ms": row["total_active_ms"],
        "date_range_start": row["date_range_start"],
        "date_range_end": row["date_range_end"],
        "project_count": row["project_count"],
        "subagent_count": row["subagent_count"],
        "subagent_tools": row["subagent_tools"],
        "tool_distribution": json.loads(row["tool_distribution_json"] or "{}"),
        "projects_chart": json.loads(row["projects_chart_json"] or "{}"),
        "weekly_timeline": json.loads(row["weekly_timeline_json"] or "{}"),
        "daily_timeline": json.loads(row["daily_timeline_json"] or "{}"),
        "monthly_timeline": json.loads(row["monthly_timeline_json"] or "{}"),
        "file_types_chart": json.loads(row["file_types_chart_json"] or "{}"),
        "projects_list": json.loads(row["projects_list_json"] or "[]"),
        "tool_distribution_1d": json.loads(row["tool_distribution_1d_json"] or "{}"),
        "tool_distribution_7d": json.loads(row["tool_distribution_7d_json"] or "{}"),
        "tool_distribution_30d": json.loads(row["tool_distribution_30d_json"] or "{}"),
        "projects_chart_1d": json.loads(row["projects_chart_1d_json"] or "{}"),
        "projects_chart_7d": json.loads(row["projects_chart_7d_json"] or "{}"),
        "projects_chart_30d": json.loads(row["projects_chart_30d_json"] or "{}"),
        "file_types_chart_1d": json.loads(row["file_types_chart_1d_json"] or "{}"),
        "file_types_chart_7d": json.loads(row["file_types_chart_7d_json"] or "{}"),
        "file_types_chart_30d": json.loads(row["file_types_chart_30d_json"] or "{}"),
        "cost_by_project": json.loads(row["cost_by_project_json"] or "{}"),
        "cost_by_project_1d": json.loads(row["cost_by_project_1d_json"] or "{}"),
        "cost_by_project_7d": json.loads(row["cost_by_project_7d_json"] or "{}"),
        "cost_by_project_30d": json.loads(row["cost_by_project_30d_json"] or "{}"),
        "actions_daily": json.loads(row["actions_daily_json"] or "{}"),
        "actions_weekly": json.loads(row["actions_weekly_json"] or "{}"),
        "actions_monthly": json.loads(row["actions_monthly_json"] or "{}"),
        "active_time_daily": json.loads(row["active_time_daily_json"] or "{}"),
        "active_time_weekly": json.loads(row["active_time_weekly_json"] or "{}"),
        "active_time_monthly": json.loads(row["active_time_monthly_json"] or "{}"),
    }


def get_session_list(
    conn: sqlite3.Connection, project: str | None = None
) -> list[dict[str, Any]]:
    """Get lightweight session summaries for the dropdown/list."""
    if project:
        rows = conn.execute(
            """SELECT session_id, project, slug, prompt_preview, start_time, end_time,
                      model, total_tools, total_actions, turn_count, subagent_count,
                      active_duration_ms, total_active_duration_ms, cost_estimate,
                      permission_mode, interrupt_count, thinking_level, tool_errors
               FROM session_summaries
               WHERE project = ?
               ORDER BY start_time DESC""",
            (project,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT session_id, project, slug, prompt_preview, start_time, end_time,
                      model, total_tools, total_actions, turn_count, subagent_count,
                      active_duration_ms, total_active_duration_ms, cost_estimate,
                      permission_mode, interrupt_count, thinking_level, tool_errors
               FROM session_summaries
               ORDER BY start_time DESC"""
        ).fetchall()

    return [dict(row) for row in rows]


def get_session_detail(
    conn: sqlite3.Connection, session_id: str
) -> dict[str, Any] | None:
    """Load full session detail from SQLite."""
    row = conn.execute(
        "SELECT detail_json FROM session_details WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if not row:
        return None
    return json.loads(row["detail_json"])


def get_projects_list(conn: sqlite3.Connection) -> list[str]:
    """Return sorted list of all distinct project names."""
    rows = conn.execute(
        "SELECT DISTINCT project FROM session_summaries ORDER BY project"
    ).fetchall()
    return [row["project"] for row in rows]


def get_session_count(conn: sqlite3.Connection) -> int:
    """Return total number of cached sessions."""
    row = conn.execute("SELECT COUNT(*) as cnt FROM session_summaries").fetchone()
    return row["cnt"] if row else 0
