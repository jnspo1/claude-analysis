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
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

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
    file_types_chart_30d_json   TEXT
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
    jsonl_files: List[Path],
) -> Tuple[List[Path], Set[str]]:
    """Compare filesystem against file_cache, return files needing reparse.

    Returns:
        (stale_files, current_paths) - files to reparse and set of all current paths
    """
    current_paths: Set[str] = set()
    stale: List[Path] = []

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
    session_data: Dict[str, Any],
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
    conn: sqlite3.Connection, current_paths: Set[str]
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
# Global aggregates
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

    now = datetime.now()

    total_sessions = len(rows)
    total_tools = 0
    total_actions = 0
    total_cost = 0.0
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_read = 0
    total_cache_creation = 0
    total_active_ms = 0
    total_subagents = 0
    total_subagent_tools = 0

    all_starts = []
    all_ends = []
    projects: Counter = Counter()
    tool_distribution: Counter = Counter()
    file_types: Counter = Counter()
    week_counts: Counter = Counter()
    day_counts: Counter = Counter()
    month_counts: Counter = Counter()

    # Time-filtered counters (1d, 7d, 30d)
    tool_dist_1d: Counter = Counter()
    tool_dist_7d: Counter = Counter()
    tool_dist_30d: Counter = Counter()
    projects_1d: Counter = Counter()
    projects_7d: Counter = Counter()
    projects_30d: Counter = Counter()
    file_types_1d: Counter = Counter()
    file_types_7d: Counter = Counter()
    file_types_30d: Counter = Counter()

    for row in rows:
        total_tools += row["total_tools"]
        total_actions += row["total_actions"]
        total_cost += row["cost_estimate"] or 0
        total_subagents += row["subagent_count"] or 0
        total_subagent_tools += (row["total_actions"] or 0) - (row["total_tools"] or 0)
        total_active_ms += row["total_active_duration_ms"] or 0

        if row["start_time"]:
            all_starts.append(row["start_time"])
        if row["end_time"]:
            all_ends.append(row["end_time"])

        # Project actions
        projects[row["project"]] += row["total_actions"] or 0

        # Parse tool counts and file extensions for this session
        try:
            tc = json.loads(row["tool_counts_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            tc = {}
        try:
            fe = json.loads(row["file_extensions_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            fe = {}

        # Tool distribution (combined parent+subagent from summary)
        for tool, count in tc.items():
            tool_distribution[tool] += count

        # File types
        for ext, count in fe.items():
            file_types[ext] += count

        # Tokens
        try:
            tokens = json.loads(row["tokens_json"] or "{}")
            total_input_tokens += tokens.get("input", 0)
            total_output_tokens += tokens.get("output", 0)
            total_cache_read += tokens.get("cache_read", 0)
            total_cache_creation += tokens.get("cache_creation", 0)
        except (json.JSONDecodeError, TypeError):
            pass

        # Timeline and time-range filters
        if row["start_time"]:
            try:
                dt = datetime.fromisoformat(row["start_time"].replace("Z", "+00:00"))
                dt_naive = dt.replace(tzinfo=None)

                # Daily timeline
                day_counts[dt.date().isoformat()] += 1

                # Weekly timeline (ISO week start = Monday)
                week_start = dt.date()
                week_start = week_start.replace(
                    day=week_start.day - week_start.weekday()
                )
                week_counts[week_start.isoformat()] += 1

                # Monthly timeline
                month_counts[dt.strftime("%Y-%m")] += 1

                # Time-range filters: check session age
                age_days = (now - dt_naive).total_seconds() / 86400
                actions = row["total_actions"] or 0

                if age_days <= 1:
                    projects_1d[row["project"]] += actions
                    for tool, count in tc.items():
                        tool_dist_1d[tool] += count
                    for ext, count in fe.items():
                        file_types_1d[ext] += count

                if age_days <= 7:
                    projects_7d[row["project"]] += actions
                    for tool, count in tc.items():
                        tool_dist_7d[tool] += count
                    for ext, count in fe.items():
                        file_types_7d[ext] += count

                if age_days <= 30:
                    projects_30d[row["project"]] += actions
                    for tool, count in tc.items():
                        tool_dist_30d[tool] += count
                    for ext, count in fe.items():
                        file_types_30d[ext] += count

            except (ValueError, TypeError):
                pass

    date_range_start = min(all_starts) if all_starts else None
    date_range_end = max(all_ends) if all_ends else None
    projects_set = sorted(set(row["project"] for row in rows))

    # Sort charts
    projects_chart = dict(projects.most_common(15))
    weekly_timeline = dict(sorted(week_counts.items()))
    daily_timeline = dict(sorted(day_counts.items()))
    monthly_timeline = dict(sorted(month_counts.items()))
    file_types_chart = dict(Counter(file_types).most_common(15))
    tool_dist = dict(tool_distribution.most_common())

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
            file_types_chart_1d_json, file_types_chart_7d_json, file_types_chart_30d_json
        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now().isoformat(),
            total_sessions,
            total_tools,
            total_actions,
            round(total_cost, 4),
            total_input_tokens,
            total_output_tokens,
            total_cache_read,
            total_cache_creation,
            total_active_ms,
            date_range_start,
            date_range_end,
            len(projects_set),
            total_subagents,
            total_subagent_tools,
            json.dumps(tool_dist),
            json.dumps(projects_chart),
            json.dumps(weekly_timeline),
            json.dumps(daily_timeline),
            json.dumps(monthly_timeline),
            json.dumps(file_types_chart),
            json.dumps(projects_set),
            json.dumps(dict(Counter(tool_dist_1d).most_common())),
            json.dumps(dict(Counter(tool_dist_7d).most_common())),
            json.dumps(dict(Counter(tool_dist_30d).most_common())),
            json.dumps(dict(projects_1d.most_common(15))),
            json.dumps(dict(projects_7d.most_common(15))),
            json.dumps(dict(projects_30d.most_common(15))),
            json.dumps(dict(Counter(file_types_1d).most_common(15))),
            json.dumps(dict(Counter(file_types_7d).most_common(15))),
            json.dumps(dict(Counter(file_types_30d).most_common(15))),
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------
def get_overview_payload(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
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
    }


def get_session_list(
    conn: sqlite3.Connection, project: Optional[str] = None
) -> List[Dict[str, Any]]:
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
) -> Optional[Dict[str, Any]]:
    """Load full session detail from SQLite."""
    row = conn.execute(
        "SELECT detail_json FROM session_details WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if not row:
        return None
    return json.loads(row["detail_json"])


def get_projects_list(conn: sqlite3.Connection) -> List[str]:
    """Get sorted list of all projects."""
    rows = conn.execute(
        "SELECT DISTINCT project FROM session_summaries ORDER BY project"
    ).fetchall()
    return [row["project"] for row in rows]


def get_session_count(conn: sqlite3.Connection) -> int:
    """Get total number of cached sessions."""
    row = conn.execute("SELECT COUNT(*) as cnt FROM session_summaries").fetchone()
    return row["cnt"] if row else 0
