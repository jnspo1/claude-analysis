"""
FastAPI service for Claude Code Activity Dashboard.

Uses SQLite persistent cache with incremental rebuilds. Only new/changed
JSONL files are reparsed. Global aggregates are pre-computed server-side
so the HTML payload is ~50KB instead of 3MB.

Deployment: uvicorn app:app --host 127.0.0.1 --port 8202
"""

from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pi_shared.fastapi import make_standard_router

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

logger = logging.getLogger("claude-activity")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
JSONL_ROOT = Path.home() / ".claude/projects"
TEMPLATE_PATH = Path(__file__).parent / "dashboard_template.html"
CACHE_TTL_SECONDS = 300  # 5 minutes

# ---------------------------------------------------------------------------
# Background rebuild state
# ---------------------------------------------------------------------------
_rebuild_lock = threading.Lock()
_last_rebuild: float = 0.0
_rebuild_in_progress = False
_last_rebuild_stats: dict[str, Any] = {}


def _parse_stale_files(
    stale_files, adapters, options,
) -> tuple:
    """Parse stale JSONL files and upsert into the DB.

    Returns (parsed_count, error_count).
    """
    conn = get_connection()
    parsed = 0
    errors = 0
    try:
        for jsonl_path in stale_files:
            project_raw = derive_project_name(jsonl_path, JSONL_ROOT)
            project = make_project_readable(project_raw)

            try:
                session = parse_session_single_pass(
                    jsonl_path, project, adapters, options
                )
                if session:
                    stat = jsonl_path.stat()
                    upsert_session(conn, str(jsonl_path), session,
                                   stat.st_mtime, stat.st_size)
                    parsed += 1
            except Exception as e:
                logger.warning("Failed to parse %s: %s", jsonl_path.name, e)
                errors += 1
        conn.commit()
    finally:
        conn.close()
    return parsed, errors


def _incremental_rebuild() -> dict[str, Any]:
    """Parse only new/changed JSONL files, update SQLite, recompute aggregates."""
    global _last_rebuild, _rebuild_in_progress, _last_rebuild_stats

    acquired = _rebuild_lock.acquire(blocking=False)
    if not acquired:
        return {"status": "skipped", "reason": "rebuild already in progress"}

    try:
        _rebuild_in_progress = True
        t0 = time.monotonic()

        adapters = create_adapter_registry()
        options = ExtractionOptions(include_content_previews=True, preview_length=150)

        all_jsonl = find_jsonl_files(JSONL_ROOT)
        session_files = [p for p in all_jsonl if "subagents" not in p.parts]

        conn = get_connection()
        try:
            stale_files, current_paths = get_stale_files(conn, session_files)
        finally:
            conn.close()

        parsed, errors = _parse_stale_files(stale_files, adapters, options)

        conn = get_connection()
        try:
            removed = delete_removed_sessions(conn, current_paths)
            conn.commit()
            rebuild_global_aggregates(conn)
        finally:
            conn.close()

        elapsed = time.monotonic() - t0
        _last_rebuild = time.monotonic()

        stats = {
            "status": "completed",
            "elapsed_seconds": round(elapsed, 2),
            "total_files": len(session_files),
            "stale_files": len(stale_files),
            "parsed": parsed,
            "errors": errors,
            "removed": removed,
            "total_cached": get_session_count(get_connection()),
        }
        _last_rebuild_stats = stats
        logger.info(
            "Rebuild done: %d parsed, %d errors, %d removed in %.1fs",
            parsed, errors, removed, elapsed,
        )
        return stats

    finally:
        _rebuild_in_progress = False
        _rebuild_lock.release()


def _ensure_fresh() -> None:
    """Trigger background rebuild if stale. Never blocks the caller."""
    if (
        (time.monotonic() - _last_rebuild) > CACHE_TTL_SECONDS
        and not _rebuild_in_progress
    ):
        threading.Thread(target=_incremental_rebuild, daemon=True).start()


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB and trigger first rebuild on startup."""
    init_db()
    # Kick off initial rebuild in background so startup is instant
    threading.Thread(target=_incremental_rebuild, daemon=True).start()
    yield


app = FastAPI(
    title="Claude Activity Dashboard",
    lifespan=lifespan,
)

# Static files (CSS, JS, icon)
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Standard health + icon endpoints (from pi_shared)
ICON_PATH = STATIC_DIR / "app_icon.jpg"
app.include_router(make_standard_router(ICON_PATH))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def dashboard_html():
    """Serve the dashboard HTML with lightweight data injection."""
    if not TEMPLATE_PATH.exists():
        raise HTTPException(status_code=500, detail="Template not found")

    _ensure_fresh()

    conn = get_connection()
    try:
        overview = get_overview_payload(conn)
        sessions = get_session_list(conn)
    finally:
        conn.close()

    # Build lightweight init data (~50KB vs 3MB)
    init_data = {
        "overview": overview,
        "sessions": sessions,
        "rebuild_in_progress": _rebuild_in_progress,
    }

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    data_json = json.dumps(init_data, ensure_ascii=False, default=str)
    data_json = data_json.replace("</", r"<\/")
    html = template.replace(
        "const DASHBOARD_DATA = {};",
        f"const DASHBOARD_DATA = {data_json};",
    )
    return HTMLResponse(content=html)


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


@app.get("/api/sessions")
def api_sessions(project: str | None = Query(default=None)):
    """Lightweight session summaries from SQLite."""
    _ensure_fresh()
    conn = get_connection()
    try:
        return get_session_list(conn, project)
    finally:
        conn.close()


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


@app.get("/api/refresh")
def api_refresh():
    """Force a cache rebuild and return status."""
    stats = _incremental_rebuild()
    return stats


@app.get("/api/rebuild-status")
def api_rebuild_status():
    """Check if a rebuild is in progress."""
    return {
        "in_progress": _rebuild_in_progress,
        "last_rebuild_stats": _last_rebuild_stats,
        "seconds_since_rebuild": round(time.monotonic() - _last_rebuild, 1) if _last_rebuild else None,
    }
