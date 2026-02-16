# 02 - Data Layer: SQLite Schema and cache_db.py

This document provides everything needed to recreate `cache_db.py` from scratch -- the
persistent SQLite caching layer that sits between the JSONL parser (`single_pass_parser.py`)
and the FastAPI application (`app.py`). It covers the database schema, every public and
private function, the migration system, and the exact data contracts between components.

---

## Table of Contents

1. [Purpose and Architecture](#1-purpose-and-architecture)
2. [File Location and Imports](#2-file-location-and-imports)
3. [Database Path](#3-database-path)
4. [Schema (4 Tables)](#4-schema-4-tables)
5. [Connection Management](#5-connection-management)
6. [Migration System](#6-migration-system)
7. [Initialization](#7-initialization)
8. [Staleness Detection](#8-staleness-detection)
9. [Session CRUD](#9-session-crud)
10. [Global Aggregates Computation](#10-global-aggregates-computation)
11. [Query Helpers](#11-query-helpers)
12. [Data Contracts](#12-data-contracts)
13. [Integration Points](#13-integration-points)
14. [Operational Notes](#14-operational-notes)

---

## 1. Purpose and Architecture

`cache_db.py` is a pure data-access module with no FastAPI or HTTP awareness. It provides:

- **Persistent caching** of parsed JSONL session data in SQLite so that only new or changed
  files need reparsing on each rebuild cycle.
- **Pre-computed global aggregates** (totals, charts, timelines) stored as a single row so
  the overview endpoint returns instantly without scanning all sessions.
- **Incremental staleness detection** by comparing filesystem mtime+size against cached
  values.
- **Cleanup** of sessions whose source JSONL files have been deleted.

**Data flow position:**

```
JSONL files on disk
       |
       v
single_pass_parser.py  (parses one file -> session dict)
       |
       v
cache_db.py            (stores in SQLite, computes aggregates)
       |
       v
app.py                 (reads from SQLite, serves via FastAPI)
```

The module is stateless -- it has no global mutable state. All functions accept a
`sqlite3.Connection` parameter (except `init_db()` and `get_connection()` which create
connections).

---

## 2. File Location and Imports

**File:** `/home/pi/python/claude_analysis/cache_db.py`

```python
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
```

No third-party dependencies. Standard library only.

---

## 3. Database Path

```python
DB_PATH = Path(__file__).parent / "data" / "cache.db"
```

This resolves to `<project_root>/data/cache.db`. The `data/` directory is created
automatically by `get_connection()` if it does not exist. The database file is gitignored.

---

## 4. Schema (4 Tables)

The schema is defined as a single SQL string (`_SCHEMA`) executed via `executescript()`.
All tables use `CREATE TABLE IF NOT EXISTS` so the schema is idempotent.

### 4.1 `file_cache` -- Staleness Tracking

Tracks which JSONL files have been parsed and their filesystem metadata at parse time.
Used to detect which files need reparsing.

```sql
CREATE TABLE IF NOT EXISTS file_cache (
    file_path  TEXT PRIMARY KEY,   -- Absolute path to the JSONL file
    file_mtime REAL NOT NULL,      -- os.stat().st_mtime at parse time
    file_size  INTEGER NOT NULL,   -- os.stat().st_size at parse time
    session_id TEXT NOT NULL       -- Links to session_summaries/session_details
);
```

**Key points:**
- Primary key is the absolute file path string.
- One JSONL file maps to exactly one session.
- `file_mtime` is a float (Unix timestamp with fractional seconds).
- When a file is re-parsed, the row is replaced via `INSERT OR REPLACE`.

### 4.2 `session_summaries` -- Lightweight Session List

Stores denormalized scalar fields for each session. The frontend session dropdown loads
these rows (without the heavy detail blob) for fast rendering.

```sql
CREATE TABLE IF NOT EXISTS session_summaries (
    session_id               TEXT PRIMARY KEY,  -- JSONL filename stem (UUID)
    project                  TEXT NOT NULL,      -- Human-readable project name
    slug                     TEXT,               -- Claude session slug (if any)
    prompt_preview           TEXT,               -- First 80 chars of first prompt
    start_time               TEXT,               -- ISO 8601 timestamp string
    end_time                 TEXT,               -- ISO 8601 timestamp string
    model                    TEXT,               -- e.g. "claude-sonnet-4-20250514"
    total_tools              INTEGER DEFAULT 0,  -- Parent session tool count only
    total_actions            INTEGER DEFAULT 0,  -- Parent tools + subagent tools
    turn_count               INTEGER DEFAULT 0,  -- Number of user turns
    subagent_count           INTEGER DEFAULT 0,  -- Number of subagent files found
    active_duration_ms       INTEGER DEFAULT 0,  -- Parent-only active time
    total_active_duration_ms INTEGER DEFAULT 0,  -- Parent + subagent active time
    cost_estimate            REAL DEFAULT 0,     -- Estimated USD cost
    permission_mode          TEXT,               -- e.g. "default", "plan"
    interrupt_count          INTEGER DEFAULT 0,  -- User interrupts during session
    thinking_level           TEXT,               -- e.g. "medium", "high"
    tool_errors              INTEGER DEFAULT 0,  -- Count of is_error tool results
    tool_counts_json         TEXT,               -- JSON: {"Bash": 5, "Read": 3, ...}
    file_extensions_json     TEXT,               -- JSON: {".py": 12, ".md": 3, ...}
    tokens_json              TEXT                -- JSON: {"input": N, "output": N, ...}
);
```

**Key points:**
- `total_tools` is the parent session's tool count only (direct invocations).
- `total_actions` = `total_tools` + sum of all subagent tool counts. This is computed
  during `upsert_session`, not stored in the parser output.
- `tool_counts_json` stores **combined** parent + subagent tool counts (merged during upsert).
- `tokens_json` has four keys: `input`, `output`, `cache_read`, `cache_creation`.
- Timestamps are ISO 8601 strings, not Unix timestamps.

### 4.3 `session_details` -- Full Session Blob

Stores the complete session data dict as a single JSON blob. Loaded on demand when the
user clicks into a specific session.

```sql
CREATE TABLE IF NOT EXISTS session_details (
    session_id TEXT PRIMARY KEY,  -- Same key as session_summaries
    detail_json TEXT NOT NULL     -- json.dumps(session_data, default=str)
);
```

**Key points:**
- `default=str` in `json.dumps()` handles any non-serializable values (Path objects, etc).
- This blob contains everything: tool_calls list, user_turns, bash_commands, subagents,
  files_touched, etc.
- Typical size: 5-50KB per session depending on tool count.

### 4.4 `global_aggregates` -- Pre-computed Overview Data

A singleton row (enforced by `CHECK (id = 1)`) holding all pre-computed aggregates for the
overview tab. Rebuilt in full every time `rebuild_global_aggregates()` is called.

```sql
CREATE TABLE IF NOT EXISTS global_aggregates (
    id                          INTEGER PRIMARY KEY CHECK (id = 1),
    generated_at                TEXT,

    -- Scalar totals
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

    -- All-time chart data (JSON)
    tool_distribution_json      TEXT,    -- {"Bash": 500, "Read": 400, ...}
    projects_chart_json         TEXT,    -- {"project_a": 150, ...} (top 15 by actions)
    weekly_timeline_json        TEXT,    -- {"2025-01-06": 5, ...} (Monday starts)
    daily_timeline_json         TEXT,    -- {"2025-01-15": 3, ...}
    monthly_timeline_json       TEXT,    -- {"2025-01": 40, ...}
    file_types_chart_json       TEXT,    -- {".py": 300, ".md": 50, ...} (top 15)
    projects_list_json          TEXT,    -- ["project_a", "project_b", ...] (sorted)

    -- Time-filtered chart data: 1 day, 7 days, 30 days
    tool_distribution_1d_json   TEXT,
    tool_distribution_7d_json   TEXT,
    tool_distribution_30d_json  TEXT,
    projects_chart_1d_json      TEXT,
    projects_chart_7d_json      TEXT,
    projects_chart_30d_json     TEXT,
    file_types_chart_1d_json    TEXT,
    file_types_chart_7d_json    TEXT,
    file_types_chart_30d_json   TEXT,

    -- Cost by project (top 15, rounded to 4 decimal places)
    cost_by_project_json        TEXT,    -- {"project_a": 1.2345, ...}
    cost_by_project_1d_json     TEXT,
    cost_by_project_7d_json     TEXT,
    cost_by_project_30d_json    TEXT,

    -- Actions over time (direct vs subagent breakdown)
    actions_daily_json          TEXT,    -- {"2025-01-15": {"direct": 10, "subagent": 3, "total": 13}}
    actions_weekly_json         TEXT,
    actions_monthly_json        TEXT,

    -- Active time over time (milliseconds)
    active_time_daily_json      TEXT,    -- {"2025-01-15": 45000}
    active_time_weekly_json     TEXT,
    active_time_monthly_json    TEXT
);
```

**Total columns: 42** (1 id + 41 data columns).

**Key points:**
- The `CHECK (id = 1)` constraint ensures only one row can ever exist.
- All JSON columns use `json.dumps()` for serialization.
- Chart data columns store `{label: count}` dicts, already sorted/truncated.
- Timeline columns store `{date_key: count}` dicts, sorted by date key.
- Time-filtered columns (1d/7d/30d) contain the same structure as all-time but only
  include sessions within that age threshold.

---

## 5. Connection Management

### `get_connection() -> sqlite3.Connection`

Creates a new SQLite connection configured for dashboard workloads.

```python
def get_connection() -> sqlite3.Connection:
    """Get a SQLite connection with WAL mode and row factory."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn
```

**Behavior:**
1. Creates `data/` directory if it does not exist (`parents=True, exist_ok=True`).
2. Opens connection with 10-second busy timeout (handles concurrent access from background
   rebuild thread and request handlers).
3. Sets `row_factory = sqlite3.Row` so rows behave like dicts (`row["column_name"]`).
4. Enables **WAL (Write-Ahead Logging)** mode for concurrent read/write access. This is
   critical because the background rebuild thread writes while request handlers read.
5. Sets `synchronous=NORMAL` (instead of default FULL) for better write performance.
   Safe with WAL mode -- only risks losing the last transaction on OS crash, not corruption.

**Returns:** A configured `sqlite3.Connection` object.

**Called by:** `init_db()`, and directly by `app.py` for per-request connections.

---

## 6. Migration System

### `_migrate_global_aggregates(conn: sqlite3.Connection) -> None`

Adds columns to `global_aggregates` that were not in the original schema. This handles
upgrading existing databases when new chart types or aggregates are added.

```python
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
```

**Behavior:**
- Iterates over 22 column definitions.
- For each, attempts `ALTER TABLE ... ADD COLUMN`.
- Catches `sqlite3.OperationalError` silently if the column already exists (SQLite raises
  "duplicate column name" as OperationalError).
- Commits once at the end.

**Why this pattern:** SQLite does not support `ADD COLUMN IF NOT EXISTS`. The try/except
approach is the standard workaround. The migration list is append-only -- new columns are
added to the end of the list and never removed.

**Note:** This is a **private function** (leading underscore). Only called by `init_db()`.

---

## 7. Initialization

### `init_db() -> sqlite3.Connection`

One-time setup called at application startup. Creates all tables and runs migrations.

```python
def init_db() -> sqlite3.Connection:
    """Create schema and return connection."""
    conn = get_connection()
    conn.executescript(_SCHEMA)
    _migrate_global_aggregates(conn)
    conn.commit()
    return conn
```

**Behavior:**
1. Gets a WAL-mode connection via `get_connection()`.
2. Runs the full `_SCHEMA` string via `executescript()`. Since all tables use
   `CREATE TABLE IF NOT EXISTS`, this is safe to run on an existing database.
3. Runs migrations to add any columns not in the original schema.
4. Commits and returns the connection.

**Called by:** `app.py` in the FastAPI lifespan handler at startup.

**Returns:** The initialized `sqlite3.Connection`.

---

## 8. Staleness Detection

### `get_stale_files(conn, jsonl_files: List[Path]) -> Tuple[List[Path], Set[str]]`

Compares the current filesystem state against the `file_cache` table to determine which
JSONL files need reparsing.

```python
def get_stale_files(
    conn: sqlite3.Connection,
    jsonl_files: List[Path],
) -> Tuple[List[Path], Set[str]]:
```

**Parameters:**
- `conn` -- Active SQLite connection.
- `jsonl_files` -- List of `Path` objects for all JSONL session files currently on disk.

**Returns:** A 2-tuple:
- `stale_files` (`List[Path]`) -- Files that need reparsing (new or modified).
- `current_paths` (`Set[str]`) -- Set of all current file path strings. Used later by
  `delete_removed_sessions()` to find files that no longer exist.

**Algorithm:**

```
1. Load all rows from file_cache into a dict: {path_str: (mtime, size)}
2. For each path in jsonl_files:
   a. Add str(path) to current_paths set
   b. Call path.stat() -- skip on OSError (file deleted between discovery and check)
   c. Look up path in cached dict:
      - Not found -> NEW file, add to stale list
      - Found but mtime OR size differs -> MODIFIED file, add to stale list
      - Found and mtime+size match -> FRESH, skip
3. Return (stale_files, current_paths)
```

**Key details:**
- Both `mtime` and `size` must match for a file to be considered fresh. This catches
  edge cases where mtime is preserved but content changes (rare but possible with some
  copy tools).
- Files that fail `stat()` are silently skipped (not added to stale or current_paths).
- The lookup dict is built once, not queried per-file, for performance.

---

## 9. Session CRUD

### 9.1 `upsert_session(conn, file_path, session_data, file_mtime, file_size)`

Inserts or replaces a parsed session into all three data tables atomically.

```python
def upsert_session(
    conn: sqlite3.Connection,
    file_path: str,
    session_data: Dict[str, Any],
    file_mtime: float,
    file_size: int,
) -> None:
```

**Parameters:**
- `conn` -- Active SQLite connection (caller is responsible for committing).
- `file_path` -- Absolute path to the JSONL file (string, not Path).
- `session_data` -- The dict returned by `parse_session_single_pass()`. See
  [Section 12.1](#121-session_data-dict-from-parser) for the full shape.
- `file_mtime` -- `os.stat().st_mtime` of the JSONL file.
- `file_size` -- `os.stat().st_size` of the JSONL file.

**Behavior:**

1. **Extract session ID:**
   ```python
   sid = session_data["session_id"]
   ```

2. **Compute combined tool counts** (parent + all subagents):
   ```python
   combined_tool_counts = dict(session_data.get("tool_counts", {}))
   subagent_tools = 0
   for sa in session_data.get("subagents", []):
       subagent_tools += sa.get("tool_count", 0)
       for tool, count in sa.get("tool_counts", {}).items():
           combined_tool_counts[tool] = combined_tool_counts.get(tool, 0) + count
   ```
   This merges the parent session's tool counts with every subagent's tool counts into a
   single dict. For example, if the parent has `{"Bash": 5}` and a subagent has
   `{"Bash": 2, "Read": 3}`, the combined result is `{"Bash": 7, "Read": 3}`.

3. **Compute total_actions:**
   ```python
   total_actions = session_data.get("total_tools", 0) + subagent_tools
   ```
   This is parent tool count + sum of all subagent tool counts.

4. **INSERT OR REPLACE into `file_cache`:**
   ```python
   conn.execute(
       """INSERT OR REPLACE INTO file_cache (file_path, file_mtime, file_size, session_id)
          VALUES (?, ?, ?, ?)""",
       (file_path, file_mtime, file_size, sid),
   )
   ```

5. **INSERT OR REPLACE into `session_summaries`:**
   - Extracts `tokens` dict from `session_data.get("tokens", {})`.
   - Maps 21 columns from `session_data` fields.
   - Serializes `combined_tool_counts`, `file_extensions`, and `tokens` as JSON.
   - `subagent_count` = `len(session_data.get("subagents", []))`.
   - Uses `.get()` with defaults for all optional fields.

6. **INSERT OR REPLACE into `session_details`:**
   ```python
   conn.execute(
       """INSERT OR REPLACE INTO session_details (session_id, detail_json)
          VALUES (?, ?)""",
       (sid, json.dumps(session_data, default=str)),
   )
   ```

**Important:** This function does NOT commit. The caller (`_incremental_rebuild` in
`app.py`) calls `conn.commit()` once after processing all stale files, making the entire
batch atomic.

### 9.2 `delete_removed_sessions(conn, current_paths: Set[str]) -> int`

Removes sessions from all tables when their source JSONL file no longer exists on disk.

```python
def delete_removed_sessions(
    conn: sqlite3.Connection, current_paths: Set[str]
) -> int:
```

**Parameters:**
- `conn` -- Active SQLite connection.
- `current_paths` -- The set of path strings returned by `get_stale_files()`.

**Returns:** Number of sessions deleted.

**Algorithm:**
```
1. SELECT all file_path values from file_cache
2. Find paths in file_cache that are NOT in current_paths -> "removed" list
3. If none removed, return 0
4. For each removed path:
   a. Look up its session_id in file_cache
   b. DELETE from session_summaries WHERE session_id = ?
   c. DELETE from session_details WHERE session_id = ?
   d. DELETE from file_cache WHERE file_path = ?
5. Return count of removed paths
```

**Important:** This function also does NOT commit. The caller commits after this runs.

---

## 10. Global Aggregates Computation

### `rebuild_global_aggregates(conn: sqlite3.Connection) -> None`

The most substantial function in the module. Reads ALL `session_summaries` rows and
computes every aggregate value for the overview tab, writing the result as a single row
in `global_aggregates`.

```python
def rebuild_global_aggregates(conn: sqlite3.Connection) -> None:
```

**Parameters:**
- `conn` -- Active SQLite connection.

**Returns:** None. Writes directly to the database and commits.

**High-level flow:**

```
1. SELECT all rows from session_summaries (12 columns needed)
2. If no rows: DELETE the singleton aggregate row and commit, then return
3. Initialize scalar accumulators and Counter objects
4. Single loop over all rows, accumulating:
   - Scalar totals
   - Date range (min/max)
   - Tool distribution, project counts, file types, cost by project (all-time)
   - Same four metrics for 1d/7d/30d time windows
   - Timeline data (daily/weekly/monthly session counts)
   - Actions over time (daily/weekly/monthly, broken down by direct/subagent)
   - Active time over time (daily/weekly/monthly)
5. Post-process: sort, truncate to top 15, round costs
6. INSERT OR REPLACE the singleton row with 42 column values
7. Commit
```

#### 10.1 Columns Selected from session_summaries

```sql
SELECT project, total_tools, total_actions, cost_estimate,
       subagent_count, start_time, end_time,
       active_duration_ms, total_active_duration_ms,
       tool_counts_json, file_extensions_json, tokens_json
FROM session_summaries
```

#### 10.2 Scalar Accumulators

Initialized to zero, accumulated per-row:

| Variable | Source | Notes |
|---|---|---|
| `total_sessions` | `len(rows)` | Set once, not accumulated |
| `total_tools` | `row["total_tools"]` | Parent-only tool count |
| `total_actions` | `row["total_actions"]` | Parent + subagent tools |
| `total_cost` | `row["cost_estimate"] or 0` | Handles None |
| `total_input_tokens` | `tokens["input"]` | From parsed tokens_json |
| `total_output_tokens` | `tokens["output"]` | From parsed tokens_json |
| `total_cache_read` | `tokens["cache_read"]` | From parsed tokens_json |
| `total_cache_creation` | `tokens["cache_creation"]` | From parsed tokens_json |
| `total_active_ms` | `row["total_active_duration_ms"] or 0` | Parent + subagent |
| `total_subagents` | `row["subagent_count"] or 0` | Sum across all sessions |
| `total_subagent_tools` | `(total_actions or 0) - (total_tools or 0)` | Derived per-row |

#### 10.3 Counter Objects

All are `collections.Counter` instances:

| Counter | Accumulation | Final Output |
|---|---|---|
| `projects` | `[project] += total_actions` | `.most_common(15)` -> dict |
| `tool_distribution` | Per tool from `tool_counts_json` | `.most_common()` -> dict (all) |
| `file_types` | Per ext from `file_extensions_json` | `.most_common(15)` -> dict |
| `week_counts` | `[week_start_iso] += 1` | sorted by key |
| `day_counts` | `[date_iso] += 1` | sorted by key |
| `month_counts` | `[YYYY-MM] += 1` | sorted by key |
| `tool_dist_1d/7d/30d` | Same as tool_distribution, filtered by age | `.most_common()` -> dict |
| `projects_1d/7d/30d` | Same as projects, filtered by age | `.most_common(15)` -> dict |
| `file_types_1d/7d/30d` | Same as file_types, filtered by age | `.most_common(15)` -> dict |
| `cost_by_project` | `[project] += cost_estimate` | `_round_cost_counter()` (top 15, 4 decimals) |
| `cost_by_project_1d/7d/30d` | Same, filtered by age | `_round_cost_counter()` |

#### 10.4 Time Filtering Logic

The age of a session is calculated from `start_time`:

```python
dt = datetime.fromisoformat(row["start_time"].replace("Z", "+00:00"))
dt_naive = dt.replace(tzinfo=None)
age_days = (now - dt_naive).total_seconds() / 86400
```

Where `now = datetime.now()` (called once before the loop).

**Critical detail:** The timezone is stripped from the parsed datetime before comparison
with `datetime.now()`. This means the age calculation assumes local time. The `.replace("Z", "+00:00")`
handles UTC timestamps from Claude's JSONL format, then `dt.replace(tzinfo=None)` drops
the timezone for subtraction against the naive `now`.

Time window thresholds use `<=` (inclusive):
- `age_days <= 1` for 1d window
- `age_days <= 7` for 7d window
- `age_days <= 30` for 30d window

**These are NOT exclusive windows.** A 6-hour-old session appears in all three (1d, 7d, 30d).

#### 10.5 Week Start Calculation

ISO week start (Monday) is computed as:

```python
week_start = dt.date()
week_start = week_start.replace(day=week_start.day - week_start.weekday())
```

`weekday()` returns 0 for Monday, so for a Monday this is a no-op. For a Wednesday
(weekday=2), it subtracts 2 days to get the previous Monday.

**Edge case:** This can produce invalid dates when the subtraction crosses a month boundary
(e.g., March 2 is a Wednesday -- `day=2, weekday=2` produces `day=0` which raises
ValueError). In practice this has not been an issue because sessions span continuous
calendar periods, but it is a latent bug. A more robust approach would use
`timedelta(days=weekday)`.

#### 10.6 Actions Over Time

Three dicts with identical structure at different granularities:

```python
actions_daily: Dict[str, Dict[str, int]] = {}
actions_weekly: Dict[str, Dict[str, int]] = {}
actions_monthly: Dict[str, Dict[str, int]] = {}
```

Per-session computation:
```python
direct = row["total_tools"] or 0
subagent = actions - direct   # where actions = row["total_actions"] or 0

for bucket, key in [
    (actions_daily, day_key),
    (actions_weekly, week_key),
    (actions_monthly, month_key),
]:
    if key not in bucket:
        bucket[key] = {"direct": 0, "subagent": 0, "total": 0}
    bucket[key]["direct"] += direct
    bucket[key]["subagent"] += subagent
    bucket[key]["total"] += actions
```

Output shape (after sorting by key):
```json
{
    "2025-01-06": {"direct": 45, "subagent": 12, "total": 57},
    "2025-01-13": {"direct": 32, "subagent": 5, "total": 37}
}
```

#### 10.7 Active Time Over Time

Three dicts mapping date keys to total milliseconds:

```python
active_time_daily: Dict[str, int] = {}
active_time_weekly: Dict[str, int] = {}
active_time_monthly: Dict[str, int] = {}
```

Per-session:
```python
active_ms = row["total_active_duration_ms"] or 0
for bucket, key in [
    (active_time_daily, day_key),
    (active_time_weekly, week_key),
    (active_time_monthly, month_key),
]:
    bucket[key] = bucket.get(key, 0) + active_ms
```

Output shape:
```json
{"2025-01-15": 345000, "2025-01-16": 128000}
```

#### 10.8 Post-Processing and Output

After the main loop:

```python
# Date range
date_range_start = min(all_starts) if all_starts else None
date_range_end = max(all_ends) if all_ends else None

# Sorted project list for dropdown
projects_set = sorted(set(row["project"] for row in rows))

# Chart data: truncated to top 15 and/or sorted by date
projects_chart = dict(projects.most_common(15))
weekly_timeline = dict(sorted(week_counts.items()))
daily_timeline = dict(sorted(day_counts.items()))
monthly_timeline = dict(sorted(month_counts.items()))
file_types_chart = dict(Counter(file_types).most_common(15))
tool_dist = dict(tool_distribution.most_common())  # ALL tools, not truncated

# Actions and active time: sorted by date key
actions_daily_sorted = dict(sorted(actions_daily.items()))
# ... (same for weekly, monthly, active_time variants)
```

#### 10.9 Cost Rounding Helper

Defined as a local function inside `rebuild_global_aggregates`:

```python
def _round_cost_counter(c: Counter) -> dict:
    return {k: round(v, 4) for k, v in c.most_common(15)}
```

Takes a Counter of `{project_name: cost_float}`, returns the top 15 projects with costs
rounded to 4 decimal places.

#### 10.10 Final INSERT

All 42 columns are written in a single `INSERT OR REPLACE` with `id=1`:

```python
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
        cost_by_project_json, cost_by_project_1d_json, cost_by_project_7d_json,
        cost_by_project_30d_json,
        actions_daily_json, actions_weekly_json, actions_monthly_json,
        active_time_daily_json, active_time_weekly_json, active_time_monthly_json
    ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
    (
        datetime.now().isoformat(),     # generated_at
        total_sessions,                  # total_sessions
        total_tools,                     # total_tools (parent only)
        total_actions,                   # total_actions (parent + subagent)
        round(total_cost, 4),           # total_cost (rounded)
        total_input_tokens,
        total_output_tokens,
        total_cache_read,
        total_cache_creation,
        total_active_ms,
        date_range_start,               # min of all start_times (string compare)
        date_range_end,                 # max of all end_times (string compare)
        len(projects_set),              # project_count
        total_subagents,                # subagent_count (total across all sessions)
        total_subagent_tools,           # subagent_tools (total)
        json.dumps(tool_dist),          # tool_distribution_json (ALL tools)
        json.dumps(projects_chart),     # projects_chart_json (top 15)
        json.dumps(weekly_timeline),    # weekly_timeline_json (sorted)
        json.dumps(daily_timeline),     # daily_timeline_json (sorted)
        json.dumps(monthly_timeline),   # monthly_timeline_json (sorted)
        json.dumps(file_types_chart),   # file_types_chart_json (top 15)
        json.dumps(projects_set),       # projects_list_json (sorted list)
        json.dumps(dict(Counter(tool_dist_1d).most_common())),    # 1d tools (all)
        json.dumps(dict(Counter(tool_dist_7d).most_common())),    # 7d tools (all)
        json.dumps(dict(Counter(tool_dist_30d).most_common())),   # 30d tools (all)
        json.dumps(dict(projects_1d.most_common(15))),            # 1d projects (top 15)
        json.dumps(dict(projects_7d.most_common(15))),            # 7d projects (top 15)
        json.dumps(dict(projects_30d.most_common(15))),           # 30d projects (top 15)
        json.dumps(dict(Counter(file_types_1d).most_common(15))), # 1d file types (top 15)
        json.dumps(dict(Counter(file_types_7d).most_common(15))), # 7d file types (top 15)
        json.dumps(dict(Counter(file_types_30d).most_common(15))),# 30d file types (top 15)
        json.dumps(_round_cost_counter(cost_by_project)),         # cost all-time
        json.dumps(_round_cost_counter(cost_by_project_1d)),      # cost 1d
        json.dumps(_round_cost_counter(cost_by_project_7d)),      # cost 7d
        json.dumps(_round_cost_counter(cost_by_project_30d)),     # cost 30d
        json.dumps(actions_daily_sorted),
        json.dumps(actions_weekly_sorted),
        json.dumps(actions_monthly_sorted),
        json.dumps(active_time_daily_sorted),
        json.dumps(active_time_weekly_sorted),
        json.dumps(active_time_monthly_sorted),
    ),
)
conn.commit()
```

**Important:** This function calls `conn.commit()` itself (unlike `upsert_session` and
`delete_removed_sessions`).

---

## 11. Query Helpers

### 11.1 `get_overview_payload(conn) -> Optional[Dict]`

Reads the singleton `global_aggregates` row and deserializes all JSON columns.

```python
def get_overview_payload(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
```

**Returns:** A dict with 35 keys (scalar values as-is, JSON columns deserialized via
`json.loads()`), or `None` if no aggregates exist yet.

**Key deserialization pattern:**
```python
row = conn.execute("SELECT * FROM global_aggregates WHERE id = 1").fetchone()
if not row:
    return None

return {
    "generated_at": row["generated_at"],
    "total_sessions": row["total_sessions"],
    # ... scalar fields passed through directly ...
    "total_cache_creation_tokens": row["total_cache_creation_tokens"] or 0,  # Note: None -> 0
    # ... JSON fields deserialized with fallback ...
    "tool_distribution": json.loads(row["tool_distribution_json"] or "{}"),
    "projects_list": json.loads(row["projects_list_json"] or "[]"),
    # ... etc for all 26 JSON columns ...
}
```

**Fallback pattern:** Every JSON column uses `row["col"] or "{}"` (or `"[]"` for list
columns) to handle NULL values in the database. Only `projects_list_json` uses `"[]"` as
fallback -- all others use `"{}"`.

**Output key naming:** The `_json` suffix is stripped from column names in the returned
dict. For example, `tool_distribution_json` becomes the key `tool_distribution`.

### 11.2 `get_session_list(conn, project=None) -> List[Dict]`

Returns lightweight session summaries for the dropdown/list, optionally filtered by project.

```python
def get_session_list(
    conn: sqlite3.Connection, project: Optional[str] = None
) -> List[Dict[str, Any]]:
```

**Parameters:**
- `conn` -- Active SQLite connection.
- `project` -- If provided, only return sessions for this project name (exact match).

**Returns:** List of dicts, each containing 18 scalar fields from `session_summaries`.
Ordered by `start_time DESC` (most recent first).

**Selected columns** (JSON columns `tool_counts_json`, `file_extensions_json`, `tokens_json`
are NOT included -- this is deliberate to keep the payload lightweight):

```
session_id, project, slug, prompt_preview, start_time, end_time,
model, total_tools, total_actions, turn_count, subagent_count,
active_duration_ms, total_active_duration_ms, cost_estimate,
permission_mode, interrupt_count, thinking_level, tool_errors
```

**Implementation note:** Uses two separate SQL queries (one with `WHERE project = ?`, one
without) rather than dynamically building the query. Each row is converted via `dict(row)`.

### 11.3 `get_session_detail(conn, session_id) -> Optional[Dict]`

Loads the full session data blob for a specific session.

```python
def get_session_detail(
    conn: sqlite3.Connection, session_id: str
) -> Optional[Dict[str, Any]]:
```

**Parameters:**
- `conn` -- Active SQLite connection.
- `session_id` -- The JSONL filename stem (UUID format).

**Returns:** The full session data dict (deserialized from `detail_json`), or `None` if
not found.

```python
row = conn.execute(
    "SELECT detail_json FROM session_details WHERE session_id = ?",
    (session_id,),
).fetchone()
if not row:
    return None
return json.loads(row["detail_json"])
```

### 11.4 `get_projects_list(conn) -> List[str]`

Returns a sorted list of all distinct project names.

```python
def get_projects_list(conn: sqlite3.Connection) -> List[str]:
```

**Returns:** `["admin_panel", "claude_analysis", "fuel", ...]` -- sorted alphabetically
via `ORDER BY project`.

```python
rows = conn.execute(
    "SELECT DISTINCT project FROM session_summaries ORDER BY project"
).fetchall()
return [row["project"] for row in rows]
```

### 11.5 `get_session_count(conn) -> int`

Returns the total number of cached sessions.

```python
def get_session_count(conn: sqlite3.Connection) -> int:
```

**Returns:** Integer count.

```python
row = conn.execute("SELECT COUNT(*) as cnt FROM session_summaries").fetchone()
return row["cnt"] if row else 0
```

---

## 12. Data Contracts

### 12.1 `session_data` Dict from Parser

The dict returned by `single_pass_parser.parse_session_single_pass()` and consumed by
`upsert_session()`. Every key listed here:

```python
{
    "session_id": str,           # JSONL filename stem (UUID)
    "slug": Optional[str],       # Claude session slug
    "project": str,              # Human-readable project name
    "first_prompt": Optional[str],  # Full text of first user prompt
    "prompt_preview": Optional[str], # First 80 chars + "..." if truncated
    "turn_count": int,           # Number of user turns
    "start_time": Optional[str], # ISO 8601 timestamp (first record)
    "end_time": Optional[str],   # ISO 8601 timestamp (last record)
    "model": Optional[str],      # Primary model used
    "total_tools": int,          # Parent session tool invocation count
    "tool_counts": dict,         # {"Bash": 5, "Read": 3, ...} parent only
    "file_extensions": dict,     # {".py": 12, ".md": 3, ...}
    "files_touched": dict,       # {"/path/file.py": {"Read": 2, "Edit": 1}}
    "bash_commands": list,       # [{command, base, count, category}, ...]
    "bash_category_summary": dict, # {"git": 5, "file_ops": 3, ...}
    "tool_calls": list,          # Chronological list of tool call dicts
    "user_turns": list,          # [{text, timestamp, is_interrupt, turn_number}]
    "interrupt_count": int,
    "tokens": {
        "input": int,
        "output": int,
        "cache_creation": int,
        "cache_read": int,
    },
    "active_duration_ms": int,          # Parent-only active time
    "total_active_duration_ms": int,    # Parent + subagent active time
    "permission_mode": Optional[str],
    "tool_errors": int,
    "tool_successes": int,
    "thinking_level": Optional[str],
    "models_used": List[str],           # Sorted list of all models seen
    "cost_estimate": float,
    "subagents": [                      # List of subagent dicts
        {
            "agent_id": str,
            "subagent_type": str,
            "task_description": str,
            "description": Optional[str],
            "tool_count": int,
            "tool_counts": dict,        # {"Read": 2, "Grep": 1}
            "tool_calls": list,
            "active_duration_ms": int,
        },
    ],
}
```

### 12.2 Overview Payload (from `get_overview_payload`)

The dict served by `GET /api/overview`. Contains 35 keys:

**Scalar fields:**
```
generated_at, total_sessions, total_tools, total_actions, total_cost,
total_input_tokens, total_output_tokens, total_cache_read_tokens,
total_cache_creation_tokens, total_active_ms, date_range_start,
date_range_end, project_count, subagent_count, subagent_tools
```

**All-time chart data (deserialized dicts):**
```
tool_distribution, projects_chart, weekly_timeline, daily_timeline,
monthly_timeline, file_types_chart, projects_list
```

**Time-filtered chart data:**
```
tool_distribution_1d, tool_distribution_7d, tool_distribution_30d,
projects_chart_1d, projects_chart_7d, projects_chart_30d,
file_types_chart_1d, file_types_chart_7d, file_types_chart_30d,
cost_by_project, cost_by_project_1d, cost_by_project_7d, cost_by_project_30d
```

**Temporal aggregates:**
```
actions_daily, actions_weekly, actions_monthly,
active_time_daily, active_time_weekly, active_time_monthly
```

### 12.3 Session List Item (from `get_session_list`)

Each item in the returned list:

```python
{
    "session_id": str,
    "project": str,
    "slug": Optional[str],
    "prompt_preview": Optional[str],
    "start_time": Optional[str],
    "end_time": Optional[str],
    "model": Optional[str],
    "total_tools": int,
    "total_actions": int,
    "turn_count": int,
    "subagent_count": int,
    "active_duration_ms": int,
    "total_active_duration_ms": int,
    "cost_estimate": float,
    "permission_mode": Optional[str],
    "interrupt_count": int,
    "thinking_level": Optional[str],
    "tool_errors": int,
}
```

---

## 13. Integration Points

### 13.1 Called by `app.py`

| Function | Where Called | Purpose |
|---|---|---|
| `init_db()` | Lifespan startup handler | Create schema on app start |
| `get_connection()` | Per-request and rebuild thread | Get fresh connection |
| `get_stale_files()` | `_incremental_rebuild()` | Determine what to reparse |
| `upsert_session()` | `_incremental_rebuild()` loop | Store parsed session |
| `delete_removed_sessions()` | `_incremental_rebuild()` | Clean up deleted files |
| `rebuild_global_aggregates()` | `_incremental_rebuild()` | Recompute overview data |
| `get_overview_payload()` | `GET /api/overview` | Serve overview tab |
| `get_session_list()` | `GET /api/sessions` | Serve session dropdown |
| `get_session_detail()` | `GET /api/session/{id}` | Serve session detail |
| `get_session_count()` | `_incremental_rebuild()` | Report cache stats |

### 13.2 Rebuild Flow (Caller Sequence)

The typical sequence called by `app.py._incremental_rebuild()`:

```python
conn = get_connection()
try:
    # 1. Find what needs updating
    stale_files, current_paths = get_stale_files(conn, session_files)

    # 2. Parse and upsert each stale file
    for jsonl_path in stale_files:
        session = parse_session_single_pass(jsonl_path, project, adapters, options)
        if session:
            upsert_session(conn, str(jsonl_path), session, stat.st_mtime, stat.st_size)

    # 3. Remove stale entries
    removed = delete_removed_sessions(conn, current_paths)

    # 4. Commit all changes as one transaction
    conn.commit()

    # 5. Recompute aggregates (commits internally)
    rebuild_global_aggregates(conn)
finally:
    conn.close()
```

### 13.3 Concurrency Model

- `app.py` uses a `threading.Lock` to ensure only one rebuild runs at a time.
- Request handlers create their own connections via `get_connection()` (short-lived).
- WAL mode allows readers to proceed without blocking during writes.
- The `timeout=10` on connections prevents indefinite blocking if the lock is held.

---

## 14. Operational Notes

### 14.1 Database Location

The database file lives at `<project_root>/data/cache.db` and is gitignored. Deleting it
triggers a full cold rebuild on next request (takes 8-12 seconds for all JSONL files).

### 14.2 WAL Files

SQLite WAL mode creates two additional files: `cache.db-wal` and `cache.db-shm`. These
are normal and should also be gitignored. They are automatically cleaned up when all
connections close cleanly.

### 14.3 Memory Considerations

On the Raspberry Pi 5 (4GB RAM), `rebuild_global_aggregates` loads all session summaries
into memory at once. With hundreds of sessions, each row is small (the JSON blobs in
summaries are compact), so this is not a concern. The heavy `session_details` blobs are
never loaded during aggregation.

### 14.4 Transaction Safety

- `upsert_session` and `delete_removed_sessions` do NOT commit -- the caller batches
  them into a single transaction for atomicity.
- `rebuild_global_aggregates` DOES commit internally because it runs after the session
  CRUD transaction is complete.
- If a rebuild crashes mid-way, the database remains consistent because uncommitted
  changes from the CRUD phase are rolled back.

### 14.5 Adding New Aggregate Columns

To add a new chart or metric to the overview:

1. Add the column to the `_SCHEMA` string (for fresh databases).
2. Add it to `_migrate_global_aggregates`'s `new_columns` list (for existing databases).
3. Add an accumulator in `rebuild_global_aggregates`.
4. Add it to the INSERT statement in `rebuild_global_aggregates` (both column list and
   values tuple -- these MUST match in order and count).
5. Add it to `get_overview_payload`'s return dict with `json.loads()` deserialization.
6. The dashboard template can then access it in the overview payload.

### 14.6 JSON Column Conventions

| Data Type | Serialization | Deserialization Fallback |
|---|---|---|
| Dict (chart data) | `json.dumps(dict)` | `json.loads(col or "{}")` |
| List (projects list) | `json.dumps(list)` | `json.loads(col or "[]")` |
| Counter (truncated) | `json.dumps(dict(c.most_common(15)))` | `json.loads(col or "{}")` |
| Cost Counter | `json.dumps(_round_cost_counter(c))` | `json.loads(col or "{}")` |

### 14.7 Known Limitations

1. **Week start calculation** uses `date.replace(day=day - weekday)` which can produce
   invalid dates when crossing month boundaries. A `timedelta`-based approach would be
   safer.
2. **Time filtering** compares naive datetimes, assuming the server's local timezone
   matches the JSONL timestamps (which are UTC). On this Pi deployment this works because
   the system timezone is set accordingly, but it would be a bug on a server in a
   different timezone.
3. **No index on `start_time`** in `session_summaries`. The full table scan in
   `rebuild_global_aggregates` is fast enough for hundreds of sessions but would benefit
   from an index at thousands.
4. **`total_cost` rounding** happens at the global level (`round(total_cost, 4)`) but
   individual session costs are stored at full float precision.
