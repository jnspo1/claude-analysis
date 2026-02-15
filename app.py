"""
FastAPI service for Claude Code Activity Dashboard.

Serves the live dashboard via HTTP with cached JSONL scanning
(5-minute TTL) to avoid re-parsing on every request.

Deployment: uvicorn app:app --host 127.0.0.1 --port 8202
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from extract_tool_usage import find_jsonl_files, derive_project_name
from session_parser import build_session_data, make_project_readable
from tool_adapters import create_adapter_registry, ExtractionOptions

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
JSONL_ROOT = Path.home() / ".claude/projects"
TEMPLATE_PATH = Path(__file__).parent / "dashboard_template.html"
CACHE_TTL_SECONDS = 300  # 5 minutes

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Claude Activity Dashboard",
    root_path="/claude_activity",
)

# ---------------------------------------------------------------------------
# Thread-safe cache
# ---------------------------------------------------------------------------
_cache_lock = threading.Lock()
_cache: Dict[str, Any] = {
    "data": None,
    "built_at": 0.0,
}


def _build_dashboard_data() -> Dict[str, Any]:
    """Scan JSONL files and build the full dashboard payload."""
    adapters = create_adapter_registry()
    options = ExtractionOptions(
        include_content_previews=True,
        preview_length=150,
    )

    all_jsonl = find_jsonl_files(JSONL_ROOT)
    session_files = [p for p in all_jsonl if "subagents" not in p.parts]

    sessions: List[Dict] = []
    projects_seen: set[str] = set()

    for jsonl_path in session_files:
        project_raw = derive_project_name(jsonl_path, JSONL_ROOT)
        project = make_project_readable(project_raw)
        projects_seen.add(project)

        try:
            session = build_session_data(jsonl_path, project, adapters, options)
            if session:
                sessions.append(session)
        except Exception:
            continue

    sessions.sort(key=lambda s: s.get("start_time") or "", reverse=True)

    return {
        "generated_at": datetime.now().isoformat(),
        "projects": sorted(projects_seen),
        "sessions": sessions,
    }


def _get_cached_data(force_refresh: bool = False) -> Dict[str, Any]:
    """Return cached dashboard data, rebuilding if stale or forced."""
    now = time.monotonic()
    with _cache_lock:
        if (
            not force_refresh
            and _cache["data"] is not None
            and (now - _cache["built_at"]) < CACHE_TTL_SECONDS
        ):
            return _cache["data"]

    # Build outside the lock (expensive, don't block other readers)
    data = _build_dashboard_data()

    with _cache_lock:
        _cache["data"] = data
        _cache["built_at"] = time.monotonic()

    return data


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/app_icon.jpg")
async def app_icon():
    """Serve the app icon for iPhone Home Screen"""
    return FileResponse(
        Path(__file__).parent / "static" / "app_icon.jpg",
        media_type="image/jpeg",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/", response_class=HTMLResponse)
def dashboard_html():
    """Serve the full dashboard HTML with injected data."""
    if not TEMPLATE_PATH.exists():
        raise HTTPException(status_code=500, detail="Template not found")

    data = _get_cached_data()
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    data_json = json.dumps(data, ensure_ascii=False)
    # Escape </ sequences to prevent </script> in data from breaking HTML parser
    data_json = data_json.replace("</", r"<\/")
    html = template.replace(
        "const DASHBOARD_DATA = {};",
        f"const DASHBOARD_DATA = {data_json};",
    )
    return HTMLResponse(content=html)


@app.get("/api/data")
def api_data():
    """Return the full dashboard JSON payload."""
    return _get_cached_data()


@app.get("/api/refresh")
def api_refresh():
    """Force a cache rebuild and return fresh data."""
    data = _get_cached_data(force_refresh=True)
    return {
        "status": "refreshed",
        "generated_at": data["generated_at"],
        "session_count": len(data["sessions"]),
        "project_count": len(data["projects"]),
    }


@app.get("/api/sessions")
def api_sessions(project: Optional[str] = Query(default=None)):
    """Lightweight session summaries, optionally filtered by project."""
    data = _get_cached_data()
    sessions = data["sessions"]
    if project:
        sessions = [s for s in sessions if s["project"] == project]

    return [
        {
            "session_id": s["session_id"],
            "project": s["project"],
            "slug": s.get("slug"),
            "prompt_preview": s.get("prompt_preview"),
            "start_time": s.get("start_time"),
            "end_time": s.get("end_time"),
            "model": s.get("model"),
            "total_tools": s["total_tools"],
            "turn_count": s.get("turn_count", 0),
            "subagent_count": len(s.get("subagents", [])),
            "active_duration_ms": s.get("active_duration_ms"),
            "total_active_duration_ms": s.get("total_active_duration_ms"),
            "cost_estimate": s.get("cost_estimate"),
            "permission_mode": s.get("permission_mode"),
            "interrupt_count": s.get("interrupt_count", 0),
        }
        for s in sessions
    ]


@app.get("/api/session/{session_id}")
def api_session_detail(session_id: str):
    """Full detail for a single session."""
    data = _get_cached_data()
    for s in data["sessions"]:
        if s["session_id"] == session_id:
            return s
    raise HTTPException(status_code=404, detail="Session not found")
