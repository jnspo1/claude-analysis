# 05 - API Server (`app.py`)

This document provides a complete specification of the FastAPI server that powers the Claude Activity Dashboard. It covers every import, constant, function, route, and design decision needed to recreate `app.py` from scratch.

**Source file**: `/home/pi/python/claude_analysis/app.py` (297 lines)

---

## Table of Contents

1. [Module Docstring](#module-docstring)
2. [Imports](#imports)
3. [Logger](#logger)
4. [Configuration Constants](#configuration-constants)
5. [Background Rebuild State](#background-rebuild-state)
6. [Core Functions](#core-functions)
   - [`_incremental_rebuild()`](#_incremental_rebuild---dictstr-any)
   - [`_ensure_fresh()`](#_ensure_fresh---none)
7. [Application Lifespan](#application-lifespan)
8. [FastAPI App Instance](#fastapi-app-instance)
9. [Routes](#routes)
   - [`GET /health` and `GET /healthz`](#get-health-and-get-healthz)
   - [`GET /app_icon.jpg`](#get-app_iconjpg)
   - [`GET /`](#get--dashboard-html)
   - [`GET /api/overview`](#get-apioverview)
   - [`GET /api/sessions`](#get-apisessions)
   - [`GET /api/session/{session_id}`](#get-apisessionsession_id)
   - [`GET /api/data`](#get-apidata-deprecated)
   - [`GET /api/refresh`](#get-apirefresh)
   - [`GET /api/rebuild-status`](#get-apirebuild-status)
10. [Key Design Decisions](#key-design-decisions)
11. [Dependency Contracts](#dependency-contracts)
12. [Error Handling Summary](#error-handling-summary)

---

## Module Docstring

```python
"""
FastAPI service for Claude Code Activity Dashboard.

Uses SQLite persistent cache with incremental rebuilds. Only new/changed
JSONL files are reparsed. Global aggregates are pre-computed server-side
so the HTML payload is ~50KB instead of 3MB.

Deployment: uvicorn app:app --host 127.0.0.1 --port 8202
"""
```

---

## Imports

### Standard Library

```python
from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
```

### Third-Party

```python
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
```

Note: `JSONResponse` is imported but not explicitly used in route return types -- FastAPI auto-serializes dicts as JSON responses.

### Internal Modules

```python
from extract_tool_usage import find_jsonl_files, derive_project_name
from session_parser import make_project_readable
from single_pass_parser import parse_session_single_pass
from tool_adapters import create_adapter_registry, ExtractionOptions
from cache_db import (
    init_db,
    get_connection,
    get_stale_files,
    upsert_session,
    delete_removed_sessions,
    rebuild_global_aggregates,
    get_overview_payload,
    get_session_list,
    get_session_detail,
    get_session_count,
)
```

Each imported function is documented in [Dependency Contracts](#dependency-contracts).

---

## Logger

```python
logger = logging.getLogger("claude-activity")
```

Named logger `"claude-activity"`. Used only in `_incremental_rebuild()` for:
- `logger.warning(...)` on individual file parse failures
- `logger.info(...)` on rebuild completion stats

---

## Configuration Constants

```python
JSONL_ROOT = Path.home() / ".claude/projects"
TEMPLATE_PATH = Path(__file__).parent / "dashboard_template.html"
CACHE_TTL_SECONDS = 300  # 5 minutes
```

| Constant | Type | Purpose |
|---|---|---|
| `JSONL_ROOT` | `Path` | Root directory to recursively scan for `*.jsonl` session log files. Resolves to `~/.claude/projects`. |
| `TEMPLATE_PATH` | `Path` | Absolute path to the Jinja-less HTML template file. Located adjacent to `app.py`. |
| `CACHE_TTL_SECONDS` | `int` | Seconds before the SQLite cache is considered stale and a background rebuild is triggered. Default: 300 (5 minutes). |

---

## Background Rebuild State

Four module-level globals manage the single-threaded rebuild lifecycle:

```python
_rebuild_lock = threading.Lock()
_last_rebuild: float = 0.0
_rebuild_in_progress = False
_last_rebuild_stats: Dict[str, Any] = {}
```

| Global | Type | Purpose |
|---|---|---|
| `_rebuild_lock` | `threading.Lock` | Prevents concurrent rebuilds. Acquired non-blocking at the start of `_incremental_rebuild()`. |
| `_last_rebuild` | `float` | `time.monotonic()` timestamp of last successful rebuild completion. Starts at `0.0` (forces immediate rebuild on first check). |
| `_rebuild_in_progress` | `bool` | Flag read by routes and `_ensure_fresh()` to avoid triggering duplicate rebuilds. |
| `_last_rebuild_stats` | `Dict[str, Any]` | Stats dict from the most recent rebuild, served by the `/api/rebuild-status` endpoint. |

---

## Core Functions

### `_incremental_rebuild() -> Dict[str, Any]`

The core rebuild algorithm. Parses only new/changed JSONL files, updates the SQLite cache, and recomputes global aggregates.

**Step-by-step logic:**

1. **Acquire lock (non-blocking)**. Call `_rebuild_lock.acquire(blocking=False)`. If lock not acquired, return immediately:
   ```python
   {"status": "skipped", "reason": "rebuild already in progress"}
   ```

2. **Set state**: `_rebuild_in_progress = True`, record start time with `time.monotonic()`.

3. **Create parsing infrastructure**:
   ```python
   adapters = create_adapter_registry()
   options = ExtractionOptions(include_content_previews=True, preview_length=150)
   ```

4. **Discover JSONL files**: Call `find_jsonl_files(JSONL_ROOT)` (returns sorted list of all `*.jsonl` under root). Filter out files with `"subagents"` in any path component:
   ```python
   session_files = [p for p in all_jsonl if "subagents" not in p.parts]
   ```

5. **Detect stale files**: Call `get_stale_files(conn, session_files)` which returns a tuple of `(stale_files: List[Path], current_paths: Set[str])`. Staleness is determined by comparing filesystem `mtime` and `size` against cached values in the `file_cache` table.

6. **Parse each stale file** in a loop:
   - Call `derive_project_name(jsonl_path, JSONL_ROOT)` to get a raw project name from path structure
   - Call `make_project_readable(project_raw)` to convert it to human-friendly form
   - Call `parse_session_single_pass(jsonl_path, project, adapters, options)` to parse the file
   - If a session dict is returned (non-None), call `upsert_session(conn, str(jsonl_path), session, stat.st_mtime, stat.st_size)`
   - Increment `parsed` counter on success
   - On any exception, log a warning and increment `errors` counter (does not abort the loop)

7. **Clean up removed files**: Call `delete_removed_sessions(conn, current_paths)` to remove cached sessions whose source JSONL files no longer exist on disk. Returns count of removed sessions.

8. **Commit**: `conn.commit()` -- all upserts and deletes are committed in one transaction.

9. **Recompute aggregates**: Call `rebuild_global_aggregates(conn)` to recalculate the overview statistics from all cached session summaries.

10. **Close connection**: `conn.close()` in a `finally` block.

11. **Record timing**: Update `_last_rebuild = time.monotonic()`.

12. **Build and store stats dict**:
    ```python
    {
        "status": "completed",
        "elapsed_seconds": round(elapsed, 2),
        "total_files": len(session_files),
        "stale_files": len(stale_files),
        "parsed": parsed,
        "errors": errors,
        "removed": removed,
        "total_cached": get_session_count(get_connection()),
    }
    ```
    Store in `_last_rebuild_stats` and log summary via `logger.info(...)`.

13. **Release lock**: In the outer `finally` block, set `_rebuild_in_progress = False` and call `_rebuild_lock.release()`.

**Important**: The `total_cached` count opens a new connection via `get_connection()` -- this is separate from the connection used for the rebuild.

---

### `_ensure_fresh() -> None`

Stale-while-revalidate trigger. Called by most read routes before serving data.

```python
def _ensure_fresh() -> None:
    """Trigger background rebuild if stale. Never blocks the caller."""
    if (
        (time.monotonic() - _last_rebuild) > CACHE_TTL_SECONDS
        and not _rebuild_in_progress
    ):
        threading.Thread(target=_incremental_rebuild, daemon=True).start()
```

**Behavior**:
- Checks two conditions: cache age exceeds `CACHE_TTL_SECONDS` AND no rebuild is currently running.
- If both true, spawns a **daemon thread** running `_incremental_rebuild`.
- **Never blocks** the calling request. The current request is served from whatever is in SQLite right now.
- If `_last_rebuild` is `0.0` (initial state), the check `(time.monotonic() - 0.0) > 300` is immediately true, which is why the lifespan already triggers the first rebuild explicitly.

---

## Application Lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB and trigger first rebuild on startup."""
    init_db()
    # Kick off initial rebuild in background so startup is instant
    threading.Thread(target=_incremental_rebuild, daemon=True).start()
    yield
```

**Startup sequence**:
1. `init_db()` -- creates the SQLite schema (tables + indexes) if they don't exist. Database path is `data/cache.db` relative to the project directory.
2. Spawns a daemon thread for the initial `_incremental_rebuild()` so the uvicorn process starts accepting requests immediately without waiting for the full parse.

**Shutdown**: No cleanup actions on shutdown (the `yield` has nothing after it). Daemon threads are killed automatically when the process exits.

---

## FastAPI App Instance

```python
app = FastAPI(
    title="Claude Activity Dashboard",
    root_path="/claude_activity",
    lifespan=lifespan,
)
```

| Parameter | Value | Why |
|---|---|---|
| `title` | `"Claude Activity Dashboard"` | Appears in the auto-generated OpenAPI docs at `/docs`. |
| `root_path` | `"/claude_activity"` | **Critical for nginx reverse proxy**. Nginx proxies requests from `http://<tailscale-ip>/claude_activity/` to `http://127.0.0.1:8202/`. Without `root_path`, generated URLs (redirects, OpenAPI docs) would be incorrect. All routes in the app use paths relative to this root (e.g., `GET /` is actually served at `/claude_activity/`). |
| `lifespan` | `lifespan` | The async context manager above. |

---

## Routes

The server exposes 10 route handlers across 9 URL patterns (two decorators share one handler).

### `GET /health` and `GET /healthz`

```python
@app.get("/health")
@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "cached_sessions": get_session_count(get_connection()),
        "rebuild_in_progress": _rebuild_in_progress,
    }
```

**Purpose**: Health check for monitoring and nginx upstream checks.

**Response**: `200 OK`
```json
{
    "status": "ok",
    "cached_sessions": 142,
    "rebuild_in_progress": false
}
```

**Notes**:
- Two decorators on the same function create two routes pointing to the same handler.
- Opens a new DB connection each call via `get_connection()` to get the live session count.
- Does NOT call `_ensure_fresh()` -- health checks should be lightweight and not trigger rebuilds.

---

### `GET /app_icon.jpg`

```python
@app.get("/app_icon.jpg")
async def app_icon():
    """Serve the app icon for iPhone Home Screen."""
    return FileResponse(
        Path(__file__).parent / "static" / "app_icon.jpg",
        media_type="image/jpeg",
        headers={"Cache-Control": "no-cache"},
    )
```

**Purpose**: Serves the PWA / home screen icon for iOS Safari "Add to Home Screen".

**Response**: JPEG binary with `Cache-Control: no-cache` header.

**File path**: `static/app_icon.jpg` relative to `app.py`.

**Note**: This is an `async def` handler (the only async route in the file), while all others are synchronous `def`. Both work fine in FastAPI -- sync handlers run in a thread pool.

---

### `GET /` (Dashboard HTML)

```python
@app.get("/", response_class=HTMLResponse)
def dashboard_html():
```

**Purpose**: The main dashboard page. Serves a complete HTML document with initial data pre-injected into a JavaScript variable.

**Step-by-step logic**:

1. **Template check**: If `TEMPLATE_PATH` does not exist, raise `HTTPException(status_code=500, detail="Template not found")`.

2. **Freshness check**: Call `_ensure_fresh()` to potentially trigger a background rebuild (non-blocking).

3. **Load data from SQLite**:
   ```python
   conn = get_connection()
   try:
       overview = get_overview_payload(conn)
       sessions = get_session_list(conn)
   finally:
       conn.close()
   ```

4. **Build initialization payload** (~50KB):
   ```python
   init_data = {
       "overview": overview,       # Pre-computed aggregates (charts, totals, etc.)
       "sessions": sessions,       # Lightweight session summaries (no detail)
       "rebuild_in_progress": _rebuild_in_progress,
   }
   ```

5. **Read template and serialize JSON**:
   ```python
   template = TEMPLATE_PATH.read_text(encoding="utf-8")
   data_json = json.dumps(init_data, ensure_ascii=False, default=str)
   ```
   - `ensure_ascii=False` preserves Unicode characters (e.g., emoji in project names).
   - `default=str` handles `datetime` objects and any other non-serializable types by calling `str()`.

6. **Sanitize for script tag safety** (CRITICAL):
   ```python
   data_json = data_json.replace("</", r"<\/")
   ```
   This prevents any `</script>` sequence inside the JSON from prematurely closing the `<script>` tag in the HTML. Without this, malicious or accidental content in session data could break the page or enable XSS.

7. **Inject into template via string replacement**:
   ```python
   html = template.replace(
       "const DASHBOARD_DATA = {};",
       f"const DASHBOARD_DATA = {data_json};",
   )
   ```
   The template contains a placeholder line `const DASHBOARD_DATA = {};` which gets replaced with the actual data. This is a simple string substitution -- no template engine (Jinja2, etc.) is used.

8. **Return**: `HTMLResponse(content=html)`

**Response**: `200 OK`, `Content-Type: text/html`

---

### `GET /api/overview`

```python
@app.get("/api/overview")
def api_overview():
    """Return pre-computed overview aggregates."""
    _ensure_fresh()
    conn = get_connection()
    try:
        overview = get_overview_payload(conn)
    finally:
        conn.close()
    if not overview:
        return {"status": "building", "message": "Cache is being built"}
    return overview
```

**Purpose**: Returns the pre-computed overview aggregates (total tokens, cost data, per-project stats, chart data, etc.).

**Response** (normal): The full overview dict from `global_aggregates` table.

**Response** (cache not ready):
```json
{"status": "building", "message": "Cache is being built"}
```

**Notes**:
- Calls `_ensure_fresh()` before serving.
- Returns the "building" fallback when `get_overview_payload()` returns `None` (e.g., first startup before the initial rebuild completes).

---

### `GET /api/sessions`

```python
@app.get("/api/sessions")
def api_sessions(project: Optional[str] = Query(default=None)):
    """Lightweight session summaries from SQLite."""
    _ensure_fresh()
    conn = get_connection()
    try:
        return get_session_list(conn, project)
    finally:
        conn.close()
```

**Purpose**: Returns a list of lightweight session summaries. Optionally filtered by project name.

**Query Parameters**:
| Parameter | Type | Default | Description |
|---|---|---|---|
| `project` | `Optional[str]` | `None` | If provided, filters sessions to only those matching this project name. |

**Response**: JSON array of session summary dicts (no full detail -- just metadata like session ID, project, timestamp, token counts, duration, etc.).

---

### `GET /api/session/{session_id}`

```python
@app.get("/api/session/{session_id}")
def api_session_detail(session_id: str):
    """Full detail for a single session (lazy loaded on demand)."""
    conn = get_connection()
    try:
        detail = get_session_detail(conn, session_id)
    finally:
        conn.close()
    if not detail:
        raise HTTPException(status_code=404, detail="Session not found")
    return detail
```

**Purpose**: Returns full session detail for a specific session. This is the lazy-loading endpoint -- the dashboard fetches this only when the user selects a session.

**Path Parameters**:
| Parameter | Type | Description |
|---|---|---|
| `session_id` | `str` | The unique session identifier (typically the JSONL filename stem). |

**Response** (found): Full session detail dict including tool calls, token breakdowns, timing, content previews, etc.

**Response** (not found): `404 Not Found` with `{"detail": "Session not found"}`

**Notes**:
- Does NOT call `_ensure_fresh()`. Session detail is a direct cache lookup; if the session exists in SQLite, serve it. If not, 404.

---

### `GET /api/data` (Deprecated)

```python
@app.get("/api/data")
def api_data():
    """Backward-compatible full payload (deprecated, reconstructs from SQLite)."""
    _ensure_fresh()
    conn = get_connection()
    try:
        overview = get_overview_payload(conn)
        sessions = get_session_list(conn)
    finally:
        conn.close()

    return {
        "generated_at": overview["generated_at"] if overview else datetime.now().isoformat(),
        "projects": overview["projects_list"] if overview else [],
        "sessions": sessions,
    }
```

**Purpose**: Backward-compatible endpoint that reconstructs the original monolithic payload format. Deprecated in favor of the tiered API (`/api/overview` + `/api/sessions` + `/api/session/{id}`).

**Response**:
```json
{
    "generated_at": "2026-02-16T12:00:00",
    "projects": ["project-a", "project-b"],
    "sessions": [...]
}
```

**Notes**:
- If `overview` is `None` (cache not yet built), falls back to `datetime.now().isoformat()` for `generated_at` and an empty list for `projects`.
- Accesses `overview["generated_at"]` and `overview["projects_list"]` -- these keys must exist in the overview payload.

---

### `GET /api/refresh`

```python
@app.get("/api/refresh")
def api_refresh():
    """Force a cache rebuild and return status."""
    stats = _incremental_rebuild()
    return stats
```

**Purpose**: Force a synchronous cache rebuild. Unlike `_ensure_fresh()`, this blocks until the rebuild completes and returns the stats.

**Response**: The stats dict from `_incremental_rebuild()`:
```json
{
    "status": "completed",
    "elapsed_seconds": 2.34,
    "total_files": 87,
    "stale_files": 3,
    "parsed": 3,
    "errors": 0,
    "removed": 0,
    "total_cached": 87
}
```

Or if another rebuild is already running:
```json
{"status": "skipped", "reason": "rebuild already in progress"}
```

**Notes**:
- This is a **blocking** call. The HTTP response is not sent until the rebuild finishes.
- Useful for manual cache invalidation or debugging.

---

### `GET /api/rebuild-status`

```python
@app.get("/api/rebuild-status")
def api_rebuild_status():
    """Check if a rebuild is in progress."""
    return {
        "in_progress": _rebuild_in_progress,
        "last_rebuild_stats": _last_rebuild_stats,
        "seconds_since_rebuild": round(time.monotonic() - _last_rebuild, 1) if _last_rebuild else None,
    }
```

**Purpose**: Non-blocking status check for rebuild progress.

**Response**:
```json
{
    "in_progress": false,
    "last_rebuild_stats": {
        "status": "completed",
        "elapsed_seconds": 1.87,
        "total_files": 87,
        "stale_files": 0,
        "parsed": 0,
        "errors": 0,
        "removed": 0,
        "total_cached": 87
    },
    "seconds_since_rebuild": 42.3
}
```

**Notes**:
- `seconds_since_rebuild` is `None` if no rebuild has ever completed (`_last_rebuild` is `0.0`, which is falsy).
- `last_rebuild_stats` is `{}` if no rebuild has completed yet.

---

## Key Design Decisions

### 1. Stale-While-Revalidate Caching

Requests are **never blocked** by a rebuild. The SQLite cache always has data (after the first successful rebuild), and routes serve whatever is currently cached. Background threads update the cache asynchronously. This eliminates the 504 Gateway Timeout errors that occurred when rebuilds ran synchronously in the request path.

### 2. Template Injection (No Template Engine)

The dashboard HTML is a static file with a single placeholder: `const DASHBOARD_DATA = {};`. The server does a simple `str.replace()` to inject JSON data. This avoids a Jinja2 dependency and keeps the template as a pure HTML/CSS/JS file that can be opened directly in a browser for development (with an empty data object).

### 3. Tiered Data Loading

Data is split into three tiers to minimize initial page load:
- **Tier 1 (injected in HTML)**: Overview aggregates + session summaries (~50KB). Loaded instantly with the page.
- **Tier 2 (lazy fetch)**: Full session detail, loaded via `fetch(/api/session/{id})` only when the user selects a specific session.
- This reduced the HTML payload from ~3MB to ~33KB gzipped.

### 4. Thread Safety

- `_rebuild_lock` is a non-blocking mutex. Only one rebuild runs at a time.
- The lock is acquired non-blocking (`blocking=False`) so that concurrent requests to `/api/refresh` or multiple `_ensure_fresh()` triggers don't pile up -- they return or skip immediately.
- All rebuild threads are daemon threads, so they don't prevent process shutdown.

### 5. root_path for Reverse Proxy

`root_path="/claude_activity"` tells FastAPI that it is mounted at a sub-path behind nginx. Without this:
- OpenAPI docs links would be wrong
- Redirect URLs would be wrong
- The interactive docs at `/docs` would fail to load resources

### 6. Connection Lifecycle

Each route opens and closes its own DB connection within a `try/finally` block. There is no connection pool or shared connection. This is safe because SQLite with WAL mode handles concurrent readers well, and the service is single-process with low concurrency.

### 7. Subagent Filtering

Files with `"subagents"` in their path components are excluded from parsing:
```python
session_files = [p for p in all_jsonl if "subagents" not in p.parts]
```
This filters out Claude Code subagent log files that are not independent sessions.

---

## Dependency Contracts

These are the function signatures and return types that `app.py` depends on from other modules.

### From `extract_tool_usage`

| Function | Signature | Returns |
|---|---|---|
| `find_jsonl_files` | `(root: Path) -> List[Path]` | Sorted list of all `*.jsonl` files found recursively under `root`. |
| `derive_project_name` | `(jsonl_path: Path, root: Path) -> str` | Raw project name derived from the JSONL file's path relative to `root`. |

### From `session_parser`

| Function | Signature | Returns |
|---|---|---|
| `make_project_readable` | `(raw: str) -> str` | Human-friendly project name (e.g., converts directory-style names to readable form). |

### From `single_pass_parser`

| Function | Signature | Returns |
|---|---|---|
| `parse_session_single_pass` | `(jsonl_path: Path, project: str, adapters: Dict, options: ExtractionOptions) -> Optional[Dict]` | Parsed session dict, or `None` if the file is empty/invalid. |

### From `tool_adapters`

| Symbol | Type | Description |
|---|---|---|
| `create_adapter_registry` | `() -> Dict[str, ToolAdapter]` | Creates a mapping of tool names to their adapter instances for extracting structured data from tool calls. |
| `ExtractionOptions` | Dataclass | Configuration for extraction: `include_content_previews: bool = True`, `preview_length: int = 100`, `verbose: bool = False`. App overrides `preview_length=150`. |

### From `cache_db`

| Function | Signature | Returns | Notes |
|---|---|---|---|
| `init_db` | `() -> sqlite3.Connection` | Connection (not used by app.py) | Creates schema if needed. |
| `get_connection` | `() -> sqlite3.Connection` | New SQLite connection with WAL mode and `Row` factory. | DB path: `data/cache.db`. |
| `get_stale_files` | `(conn, jsonl_files: List[Path]) -> Tuple[List[Path], Set[str]]` | `(stale_files, current_paths)` | Compares mtime+size against `file_cache` table. |
| `upsert_session` | `(conn, file_path: str, session: Dict, mtime: float, size: int) -> None` | None | Inserts/updates `file_cache`, `session_summaries`, and `session_details`. |
| `delete_removed_sessions` | `(conn, current_paths: Set[str]) -> int` | Count of removed sessions | Deletes cache entries for files no longer on disk. |
| `rebuild_global_aggregates` | `(conn) -> None` | None | Recomputes the `global_aggregates` table from all `session_summaries` rows. |
| `get_overview_payload` | `(conn) -> Optional[Dict[str, Any]]` | Overview dict or `None` | Reads from `global_aggregates` table. Returns `None` if table is empty. |
| `get_session_list` | `(conn, project: Optional[str] = None) -> List[Dict[str, Any]]` | List of session summary dicts | Optionally filtered by project name. |
| `get_session_detail` | `(conn, session_id: str) -> Optional[Dict[str, Any]]` | Full session dict or `None` | Reads from `session_details` table. |
| `get_session_count` | `(conn) -> int` | Total cached session count | `SELECT COUNT(*) FROM session_summaries`. |

---

## Error Handling Summary

| Scenario | Handling |
|---|---|
| Template file missing | `GET /` raises `HTTPException(500, "Template not found")` |
| Session not found | `GET /api/session/{id}` raises `HTTPException(404, "Session not found")` |
| Individual JSONL parse failure | Logged as warning, error counter incremented, rebuild continues with next file |
| Rebuild lock contention | `_incremental_rebuild()` returns `{"status": "skipped", ...}` immediately |
| Cache not yet built | `GET /api/overview` returns `{"status": "building", "message": "Cache is being built"}` |
| Cache not yet built (deprecated endpoint) | `GET /api/data` falls back to `datetime.now().isoformat()` and empty project list |
| SQLite connection | Opened/closed per request in `try/finally`. No connection leaks. |
| OS errors on file stat | `get_stale_files` catches `OSError` and skips the file (handled in `cache_db`, not `app.py`) |

---

## Complete Route Table

| Method | Path | Handler | Sync/Async | Calls `_ensure_fresh()` | Auth | Response Type |
|---|---|---|---|---|---|---|
| GET | `/health` | `healthz` | sync | No | None | JSON |
| GET | `/healthz` | `healthz` | sync | No | None | JSON |
| GET | `/app_icon.jpg` | `app_icon` | async | No | None | JPEG file |
| GET | `/` | `dashboard_html` | sync | Yes | None | HTML |
| GET | `/api/overview` | `api_overview` | sync | Yes | None | JSON |
| GET | `/api/sessions` | `api_sessions` | sync | Yes | None | JSON |
| GET | `/api/session/{session_id}` | `api_session_detail` | sync | No | None | JSON |
| GET | `/api/data` | `api_data` | sync | Yes | None | JSON |
| GET | `/api/refresh` | `api_refresh` | sync | No (calls rebuild directly) | None | JSON |
| GET | `/api/rebuild-status` | `api_rebuild_status` | sync | No | None | JSON |

All routes are unauthenticated -- security is provided by the Tailscale network trust model.
