# 08 - Deployment and Infrastructure

This document covers everything needed to deploy the Claude Activity Dashboard as a
production service on a Raspberry Pi 4B -- from Python dependencies and virtual environments
through systemd service management, nginx reverse proxying, and operational verification.
It also documents the PWA configuration, input data requirements, performance characteristics,
and a troubleshooting reference.

**Target environment**: Raspberry Pi 4B (4GB RAM, ARM64), Debian-based OS, Tailscale VPN for
network access. No public internet exposure.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Directory Structure](#2-directory-structure)
3. [Python Environment](#3-python-environment)
4. [Configuration Files](#4-configuration-files)
5. [systemd Service](#5-systemd-service)
6. [nginx Reverse Proxy](#6-nginx-reverse-proxy)
7. [root_path and Path Routing](#7-root_path-and-path-routing)
8. [PWA and Home Screen Support](#8-pwa-and-home-screen-support)
9. [Input Data Requirements](#9-input-data-requirements)
10. [Runtime Data Directory](#10-runtime-data-directory)
11. [Development Server](#11-development-server)
12. [Verification Checklist](#12-verification-checklist)
13. [Performance Characteristics](#13-performance-characteristics)
14. [Troubleshooting Reference](#14-troubleshooting-reference)
15. [Service Lifecycle Operations](#15-service-lifecycle-operations)
16. [Security Model](#16-security-model)
17. [Recreation Checklist](#17-recreation-checklist)

---

## 1. Prerequisites

### System Requirements

| Component | Requirement |
|---|---|
| Hardware | Raspberry Pi 4B (4GB+ RAM) or any Linux host |
| OS | Debian-based (Raspberry Pi OS, Ubuntu) |
| Python | 3.11+ (system Python on Pi OS Bookworm) |
| nginx | Any recent version (reverse proxy) |
| Tailscale | Installed and configured (provides network access) |
| systemd | Present (standard on all modern Debian systems) |

### Software Dependencies

The dashboard has only three Python dependencies, all declared in `requirements.txt`:

```
fastapi>=0.115.0
uvicorn>=0.34.0
pyyaml>=6.0
```

Everything else is Python standard library. No database drivers needed -- the `sqlite3` module
is built into Python.

PyYAML is used only by the CLI analysis scripts (`analyze_permissions.py`), not by the web
dashboard itself. However, it is included in the shared `requirements.txt` for completeness.

---

## 2. Directory Structure

The complete project layout with deployment-relevant files highlighted:

```
~/python/claude_analysis/           <-- WorkingDirectory for systemd
├── app.py                          <-- FastAPI entry point (uvicorn app:app)
├── cache_db.py                     <-- SQLite cache layer
├── single_pass_parser.py           <-- JSONL parser
├── session_parser.py               <-- Original multi-pass parser (used by CLI)
├── extract_tool_usage.py           <-- CLI extraction + shared utilities
├── extract_bash_commands.py        <-- CLI bash command extraction
├── analyze_commands.py             <-- CLI query helpers
├── analyze_permissions.py          <-- CLI permission simulation
├── dashboard_template.html         <-- HTML template served by app.py
├── requirements.txt                <-- Python dependencies (3 packages)
├── claude-activity.service         <-- systemd unit file (copied to /etc/systemd/system/)
├── .gitignore                      <-- Excludes data/, venv/, *.csv, *.txt
├── test_heredoc_cleaning.py        <-- Tests
├── CLAUDE.md                       <-- Project instructions
├── CHANGELOG.md                    <-- Change history
├── tool_adapters/                  <-- Adapter package
│   ├── __init__.py
│   ├── base.py
│   ├── bash.py
│   ├── file_ops.py
│   ├── search.py
│   ├── tasks.py
│   ├── special.py
│   └── registry.py
├── analyzers/                      <-- Analysis modules
│   ├── __init__.py
│   ├── patterns.py
│   ├── permissions.py
│   └── summary.py
├── static/                         <-- Static assets
│   └── app_icon.jpg                <-- PWA icon (133KB JPEG, 180x180)
├── venv/                           <-- Python virtual environment (gitignored)
│   └── ...
├── data/                           <-- Created at runtime (gitignored)
│   └── cache.db                    <-- SQLite persistent cache
└── docs/
    └── recreation/
        └── (this documentation)
```

**Key paths referenced in code:**

| Path | Referenced By | Purpose |
|---|---|---|
| `~/.claude/projects/` | `app.py` (`JSONL_ROOT`) | Input JSONL log files |
| `data/cache.db` | `cache_db.py` (`DB_PATH`) | SQLite persistent cache |
| `dashboard_template.html` | `app.py` (`TEMPLATE_PATH`) | HTML template (same dir as app.py) |
| `static/app_icon.jpg` | `app.py` (`app_icon()` route) | PWA home screen icon |

---

## 3. Python Environment

### Initial Setup

```bash
cd ~/python/claude_analysis
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Verifying the Environment

```bash
source venv/bin/activate
python -c "import fastapi; print(fastapi.__version__)"
python -c "import uvicorn; print(uvicorn.__version__)"
python -c "import yaml; print(yaml.__version__)"
```

### Why a Virtual Environment

The systemd unit file uses `Environment="PATH=.../venv/bin"` to make the venv's Python
and uvicorn available without activation. This means the venv must exist at the exact path
`/home/pi/python/claude_analysis/venv/` for the service to start. The `ExecStart` also
uses the full path to the venv's uvicorn binary.

### requirements.txt (Exact Content)

```
fastapi>=0.115.0
uvicorn>=0.34.0
pyyaml>=6.0
```

Three packages with minimum version pins. No upper bounds, no extras. FastAPI pulls in
`starlette`, `pydantic`, and `anyio` as transitive dependencies. Uvicorn pulls in
`click` and `h11`.

---

## 4. Configuration Files

### .gitignore (Exact Content)

```gitignore
# Generated artifacts
dashboard.html
*.csv
*.txt

# OS files
.DS_Store
.claude/

# Python
__pycache__/
*.pyc
*.pyo
venv/

# SQLite cache
data/
```

**Why these entries:**

| Pattern | Reason |
|---|---|
| `dashboard.html` | CLI scripts can generate a standalone HTML file; not tracked |
| `*.csv`, `*.txt` | CLI extraction outputs (`tool_events.csv`, `bash_commands.csv`, etc.) |
| `.claude/` | Claude Code local project config |
| `venv/` | Virtual environment, machine-specific |
| `data/` | SQLite cache directory, regenerated from source JSONL files |

### Application Constants (in app.py)

```python
JSONL_ROOT = Path.home() / ".claude/projects"
TEMPLATE_PATH = Path(__file__).parent / "dashboard_template.html"
CACHE_TTL_SECONDS = 300  # 5 minutes
```

These are not configurable via environment variables or config files. To change them,
edit `app.py` directly. `CACHE_TTL_SECONDS` controls how long the SQLite cache is
considered fresh before a background rebuild triggers.

### Parser Constant (in single_pass_parser.py)

```python
MAX_FILE_SIZE_MB = 100
```

Files larger than 100MB are skipped during parsing to prevent out-of-memory conditions
on the 4GB Raspberry Pi. This is especially important for the first cold rebuild where
all files are parsed.

---

## 5. systemd Service

### Unit File: `claude-activity.service`

```ini
[Unit]
Description=Claude Activity Dashboard
After=network.target

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=/home/pi/python/claude_analysis
Environment="PATH=/home/pi/python/claude_analysis/venv/bin"
ExecStart=/home/pi/python/claude_analysis/venv/bin/uvicorn app:app --host 127.0.0.1 --port 8202
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### Line-by-Line Explanation

| Directive | Purpose |
|---|---|
| `After=network.target` | Ensures the network is up before starting (needed for Tailscale access) |
| `Type=simple` | uvicorn runs in the foreground; systemd tracks the main process directly |
| `User=pi` / `Group=pi` | Runs as the `pi` user who owns the JSONL files in `~/.claude/projects/` |
| `WorkingDirectory` | Sets cwd so Python module imports (`from cache_db import ...`) resolve correctly |
| `Environment="PATH=..."` | Puts the venv's `bin/` on PATH so uvicorn finds the correct Python |
| `ExecStart` | Full path to venv's uvicorn, binding to localhost only (nginx fronts it) |
| `--host 127.0.0.1` | Listen only on loopback; not directly accessible from the network |
| `--port 8202` | The port nginx proxies to |
| `Restart=always` | Auto-restart on crash, OOM kill, or any non-zero exit |
| `RestartSec=3` | Wait 3 seconds between restart attempts (prevents tight restart loops) |
| `StandardOutput/Error=journal` | All logs go to journald (viewable via `journalctl`) |
| `WantedBy=multi-user.target` | Start on boot (when enabled) |

### Installation Steps

```bash
# 1. Copy unit file to systemd directory
sudo cp ~/python/claude_analysis/claude-activity.service /etc/systemd/system/

# 2. Reload systemd to pick up the new file
sudo systemctl daemon-reload

# 3. Enable to start on boot
sudo systemctl enable claude-activity

# 4. Start the service
sudo systemctl start claude-activity

# 5. Verify it is running
sudo systemctl status claude-activity
```

### After Code Changes

Any change to Python files requires a service restart:

```bash
sudo systemctl restart claude-activity
```

The restart is fast (~1-2 seconds). The service starts, initializes the SQLite database
schema if needed, and begins a background cache rebuild. Existing cached data in
`data/cache.db` is served immediately while the rebuild runs.

### Viewing Logs

```bash
# Follow live logs
sudo journalctl -u claude-activity -f

# Last 50 lines
sudo journalctl -u claude-activity -n 50

# Logs since last boot
sudo journalctl -u claude-activity -b

# Logs from the last hour
sudo journalctl -u claude-activity --since "1 hour ago"
```

---

## 6. nginx Reverse Proxy

### Location Block

The service is exposed through nginx as part of a multi-service reverse proxy
configuration. The relevant location blocks from `/etc/nginx/conf.d/tailnet.conf`:

```nginx
# claude_activity
location /claude_activity/ {
    proxy_pass http://127.0.0.1:8202/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location = /claude_activity/healthz {
    proxy_pass http://127.0.0.1:8202/healthz;
}
```

### How the Proxy Works

**Path stripping via trailing slash:** The trailing `/` on `proxy_pass http://127.0.0.1:8202/;`
is critical. When nginx matches `location /claude_activity/`, it strips the `/claude_activity/`
prefix and forwards the remainder to the upstream. For example:

| Client Requests | nginx Forwards To |
|---|---|
| `GET /claude_activity/` | `GET /` on port 8202 |
| `GET /claude_activity/api/overview` | `GET /api/overview` on port 8202 |
| `GET /claude_activity/api/session/abc123` | `GET /api/session/abc123` on port 8202 |

**Health check shortcut:** The `location = /claude_activity/healthz` is an exact-match rule
that bypasses the general proxy block. This provides slightly faster health check routing
and is used by the Pi Apps launcher for service status monitoring.

### Server Block Context

The nginx config listens only on the Tailscale interface:

```nginx
server {
    listen 100.99.217.84:80;
    server_name _;
    client_max_body_size 100M;

    # ... other services ...

    # claude_activity
    location /claude_activity/ {
        proxy_pass http://127.0.0.1:8202/;
        # ... headers ...
    }
}
```

The `listen 100.99.217.84:80` directive binds to the Tailscale IP only, making
the service inaccessible from the local LAN or the public internet.

### Adding to nginx

If recreating from scratch:

```bash
# 1. Add the location block to your nginx config
sudo nano /etc/nginx/conf.d/tailnet.conf

# 2. Test the configuration
sudo nginx -t

# 3. Reload nginx (graceful, no downtime)
sudo systemctl reload nginx
```

### Timeout Considerations

The default `proxy_read_timeout` in nginx is 60 seconds. The first cold rebuild of the
cache takes 8-12 seconds on a Raspberry Pi 4B, which is well within this limit. If you
have significantly more JSONL data, consider adding:

```nginx
location /claude_activity/ {
    proxy_pass http://127.0.0.1:8202/;
    proxy_read_timeout 120s;    # Only needed if cold rebuild exceeds 60s
    # ... headers ...
}
```

However, the stale-while-revalidate caching pattern means requests never wait for rebuilds.
The only scenario where a timeout could occur is the very first request to an empty cache,
which forces a synchronous rebuild. After that, all rebuilds happen in background threads.

---

## 7. root_path and Path Routing

### The Problem

When a FastAPI app is served behind a reverse proxy at a sub-path (`/claude_activity/`),
the app itself does not know about that prefix. Without configuration:

- Generated URLs in OpenAPI docs would point to `/docs` instead of `/claude_activity/docs`
- Redirect responses would use wrong paths
- The interactive Swagger UI would fail to load its JavaScript resources

### The Solution

The FastAPI app declares its mount point:

```python
app = FastAPI(
    title="Claude Activity Dashboard",
    root_path="/claude_activity",
    lifespan=lifespan,
)
```

`root_path="/claude_activity"` tells FastAPI (via ASGI) that every URL it generates
should be prefixed with `/claude_activity`. This works in conjunction with nginx stripping
the prefix on the way in -- FastAPI adds it back on the way out for any generated URLs.

### How Routes See Requests

From the perspective of route handlers in `app.py`, all paths are relative to the app
root. A route decorated with `@app.get("/api/overview")` handles requests that arrive at:

- `http://127.0.0.1:8202/api/overview` (direct, for development)
- `http://100.99.217.84/claude_activity/api/overview` (through nginx)

The handler code is identical in both cases. The `root_path` only affects outbound URL
generation, not inbound request matching.

### How the Frontend Uses root_path

The dashboard HTML resolves the root path dynamically from a known element:

```javascript
const rootPath = document.querySelector('link[rel="apple-touch-icon"]')
    ?.href?.match(/(.*)\/app_icon/)?.[1] || '/claude_activity';
```

This extracts the base URL from the `apple-touch-icon` link's fully-qualified `href`
attribute (which the browser resolves relative to the current page URL). All `fetch()`
calls in the dashboard use this `rootPath` prefix to build API URLs.

---

## 8. PWA and Home Screen Support

The dashboard supports "Add to Home Screen" on iOS devices, creating an app-like
experience without the Safari address bar.

### HTML Meta Tags (in dashboard_template.html)

```html
<!-- iPhone Home Screen icon -->
<link rel="apple-touch-icon" sizes="180x180"
      href="/claude_activity/app_icon.jpg?v=20260216">

<!-- Home Screen label -->
<meta name="apple-mobile-web-app-title" content="Task Monitor">
<meta name="application-name" content="Task Monitor">

<!-- Standalone mode (no Safari chrome) -->
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
```

### Icon Serving Route (in app.py)

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

The icon is served from `static/app_icon.jpg` (133KB JPEG). The route is at `/app_icon.jpg`
(not under `/static/`) because the `apple-touch-icon` link uses the `root_path`-prefixed
URL `/claude_activity/app_icon.jpg`, which nginx strips to `/app_icon.jpg` before forwarding.

**Cache-Control: no-cache** ensures the icon is always fresh when the home screen
shortcut is created, at the cost of a small re-fetch on each page load. The icon file
is only 133KB so this is negligible.

---

## 9. Input Data Requirements

### Source Data

The dashboard reads from Claude Code's session log files:

```
~/.claude/projects/
├── -home-pi-python-admin-panel/
│   ├── session-uuid-1.jsonl
│   ├── session-uuid-1/
│   │   └── subagents/
│   │       └── agent-abc123.jsonl    <-- excluded (subagent)
│   └── session-uuid-2.jsonl
├── -home-pi-TP/
│   └── ...
└── ...
```

**Key details:**

| Aspect | Details |
|---|---|
| Location | `~/.claude/projects/` (hardcoded in `app.py` as `JSONL_ROOT`) |
| Format | One JSON object per line (JSONL) |
| Discovery | `find_jsonl_files()` recursively finds all `*.jsonl` files |
| Filtering | Files with `"subagents"` in any path component are excluded |
| Ownership | Must be readable by the `pi` user (the systemd `User=`) |

### What Happens with No Data

If `~/.claude/projects/` does not exist or contains no JSONL files:

1. The service starts normally
2. The cache rebuild completes instantly with zero files
3. The dashboard renders with empty charts and "No sessions found"
4. The `/healthz` endpoint still returns healthy

The dashboard degrades gracefully -- it never crashes due to missing input data.

### JSONL File Format

Each line is a JSON object representing a Claude Code event. The parser looks for specific
fields (see `02-DATA-LAYER.md` and `03-SINGLE-PASS-PARSER.md` for full details), but the
relevant top-level shape is:

```json
{"type": "assistant", "message": {"content": [...]}, "costUSD": 0.05, ...}
{"type": "human", "message": {"content": "..."}, ...}
{"type": "system_init", "cwd": "/home/pi/project", ...}
```

The parser is resilient to malformed lines (skips them with a warning) and unknown event
types (ignores them).

---

## 10. Runtime Data Directory

### Automatic Creation

The `data/` directory and `data/cache.db` SQLite database are created automatically by
`cache_db.init_db()` on first run:

```python
DB_PATH = Path(__file__).parent / "data" / "cache.db"
```

`init_db()` calls `DB_PATH.parent.mkdir(parents=True, exist_ok=True)` before opening the
database, so no manual directory creation is needed.

### SQLite Configuration

The database is opened with WAL (Write-Ahead Logging) mode, which enables:

- Concurrent readers during writes (background rebuild does not block API reads)
- Better write performance for single-writer workloads
- Crash recovery without corruption

WAL mode is set on every connection via `PRAGMA journal_mode=WAL`.

### Cache Lifecycle

```
Service starts
    |
    v
init_db()              <-- Creates data/ dir and cache.db if needed
    |                       Sets up schema (4 tables)
    v
Background rebuild     <-- Triggered by app lifespan startup
    |                       Runs _incremental_rebuild() in a daemon thread
    v
Cache ready            <-- Requests served from SQLite
    |
    v
Every 5 minutes        <-- _ensure_fresh() checks CACHE_TTL_SECONDS
    |                       If stale, triggers another background rebuild
    v
Service restart        <-- Existing cache.db is preserved
                            Only stale files are reparsed (incremental)
```

### Gitignore

The `data/` directory is gitignored because:

1. The SQLite cache is regenerated from source JSONL files
2. The cache file size varies (typically 5-50MB depending on session count)
3. SQLite WAL files (`cache.db-wal`, `cache.db-shm`) should never be committed

---

## 11. Development Server

For development with auto-reload on code changes:

```bash
cd ~/python/claude_analysis
source venv/bin/activate
uvicorn app:app --host 127.0.0.1 --port 8202 --reload
```

**Notes:**

- `--reload` watches for file changes and restarts automatically (uses `watchfiles` if
  installed, falls back to polling)
- The dev server binds to `127.0.0.1` like production; access through nginx at
  `http://100.99.217.84/claude_activity/` or directly at `http://127.0.0.1:8202/`
- Stop the systemd service first to avoid port conflicts:
  `sudo systemctl stop claude-activity`
- The dev server uses the same `data/cache.db` as the production service. There is no
  separate dev database.

### Running Without nginx

For local-only testing, you can bind to all interfaces:

```bash
uvicorn app:app --host 0.0.0.0 --port 8202 --reload
```

This makes the dashboard accessible at `http://<pi-ip>:8202/` directly, bypassing nginx.
Note that `root_path="/claude_activity"` will still be set, so auto-generated docs URLs
will include the prefix, but route matching still works on the bare paths.

---

## 12. Verification Checklist

After deploying, run these commands in order to verify everything is working:

### Step 1: Service Status

```bash
sudo systemctl status claude-activity
```

Expected: `active (running)`. If not, check logs with `journalctl -u claude-activity -n 50`.

### Step 2: Port Binding

```bash
ss -tlnp | grep 8202
```

Expected: A line showing `127.0.0.1:8202` in the `LISTEN` state. If nothing appears,
the service is not running or crashed on startup.

### Step 3: Health Check (Direct)

```bash
curl -s http://127.0.0.1:8202/healthz | python3 -m json.tool
```

Expected response:

```json
{
    "status": "healthy",
    "cached_sessions": 87,
    "cache_db": "data/cache.db"
}
```

`cached_sessions` will be `0` on a fresh deployment until the first rebuild completes.

### Step 4: Health Check (Through nginx)

```bash
curl -s http://100.99.217.84/claude_activity/healthz | python3 -m json.tool
```

Expected: Same response as Step 3. If this fails but Step 3 succeeds, the issue is
in the nginx configuration.

### Step 5: Dashboard Load

Open `http://100.99.217.84/claude_activity/` in a browser. Expected: The full
dashboard with charts and session data. On first load after a fresh deployment, the
dashboard may show partial data while the background rebuild completes.

### Step 6: Force Cache Rebuild

```bash
curl -s http://127.0.0.1:8202/api/refresh | python3 -m json.tool
```

Expected response:

```json
{
    "status": "completed",
    "elapsed_seconds": 8.5,
    "total_files": 87,
    "stale_files": 87,
    "parsed": 87,
    "errors": 0,
    "removed": 0,
    "total_cached": 87
}
```

On a warm rebuild (no changes), `stale_files` and `parsed` will be `0`.

### Step 7: Check Rebuild Status

```bash
curl -s http://127.0.0.1:8202/api/rebuild-status | python3 -m json.tool
```

Confirms no rebuild is stuck in progress and shows time since last successful rebuild.

---

## 13. Performance Characteristics

### Rebuild Times (Raspberry Pi 4B, 4GB RAM)

| Scenario | Time | Description |
|---|---|---|
| Cold rebuild (all files) | 8-12s | Every JSONL file parsed from scratch |
| Warm rebuild (no changes) | <1s | Only staleness check, no parsing |
| Incremental rebuild (few changes) | 1-3s | Only new/modified files parsed |

### Memory Usage

| Component | Approximate Usage |
|---|---|
| uvicorn + FastAPI | ~30-40MB base |
| During cold rebuild | +50-100MB (temporary, parsing all files) |
| Steady state | ~40-60MB |
| SQLite cache (on disk) | 5-50MB (varies with session count) |

The `MAX_FILE_SIZE_MB = 100` limit in `single_pass_parser.py` prevents out-of-memory
conditions from a single oversized JSONL file.

### Response Times

| Endpoint | Typical Response Time |
|---|---|
| `/healthz` | <5ms |
| `/` (dashboard HTML) | <50ms (reads template + injects data) |
| `/api/overview` | <10ms (reads pre-computed aggregates) |
| `/api/sessions` | <20ms (reads session summaries) |
| `/api/session/{id}` | <10ms (single row lookup) |
| `/api/refresh` | 1-12s (blocks until rebuild completes) |

### HTML Payload Size

| Metric | Size |
|---|---|
| Uncompressed HTML | ~149KB |
| Gzipped (as served by nginx) | ~33KB |
| Before optimization (monolithic) | ~3MB |

The 50x reduction came from the tiered data loading architecture: overview aggregates
and session summaries are injected into the HTML (~50KB of JSON), while full session
details are lazy-loaded via `fetch()` only when selected.

---

## 14. Troubleshooting Reference

### Service Won't Start

**Symptoms:** `systemctl status claude-activity` shows `failed` or `inactive`.

**Common causes and fixes:**

| Cause | Diagnosis | Fix |
|---|---|---|
| Missing venv | `journalctl` shows "No such file or directory" for uvicorn | `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt` |
| Missing packages | `journalctl` shows `ModuleNotFoundError` | `source venv/bin/activate && pip install -r requirements.txt` |
| Wrong WorkingDirectory | `journalctl` shows `ModuleNotFoundError: No module named 'cache_db'` | Check `WorkingDirectory=` in the unit file matches the actual project path |
| Port already in use | `journalctl` shows "Address already in use" | Stop the dev server or kill the conflicting process: `ss -tlnp \| grep 8202` |
| File permissions | `journalctl` shows `PermissionError` | Ensure files are owned by `pi:pi`: `chown -R pi:pi ~/python/claude_analysis` |

### 502 Bad Gateway from nginx

**Meaning:** nginx cannot connect to the upstream (port 8202).

**Diagnosis:**
```bash
# Is the service running?
sudo systemctl status claude-activity

# Is anything listening on 8202?
ss -tlnp | grep 8202

# Are there recent crashes?
sudo journalctl -u claude-activity -n 20
```

**Common causes:**
- Service not started: `sudo systemctl start claude-activity`
- Service crashed and `Restart=always` hasn't kicked in yet (wait 3 seconds)
- Wrong port in nginx config (should be `proxy_pass http://127.0.0.1:8202/;`)

### 504 Gateway Timeout from nginx

**Meaning:** The upstream took too long to respond.

**When this happens:** Typically only during the very first request to a fresh deployment,
when the cache is empty and a synchronous rebuild is triggered.

**Fixes:**
1. Wait and retry -- the background rebuild will complete and subsequent requests will
   be fast
2. Trigger a rebuild manually: `curl http://127.0.0.1:8202/api/refresh` (bypass nginx)
3. If persistent, increase nginx timeout:
   ```nginx
   location /claude_activity/ {
       proxy_pass http://127.0.0.1:8202/;
       proxy_read_timeout 120s;
       # ... other headers ...
   }
   ```

### Empty Dashboard (No Data)

**Symptoms:** Dashboard loads but shows empty charts, zero sessions.

**Diagnosis:**
```bash
# Check if JSONL files exist
find ~/.claude/projects -name '*.jsonl' 2>/dev/null | wc -l

# Check cache status
curl -s http://127.0.0.1:8202/healthz | python3 -m json.tool

# Check rebuild status (might still be building)
curl -s http://127.0.0.1:8202/api/rebuild-status | python3 -m json.tool
```

**Common causes:**
- Cache still building after service restart (wait 10 seconds and refresh)
- No JSONL files exist yet (use Claude Code to generate some)
- JSONL files not readable by `pi` user
- `JSONL_ROOT` path wrong (check `app.py`, should be `Path.home() / ".claude/projects"`)

### Missing App Icon

**Symptoms:** PWA home screen shortcut shows a generic icon.

**Fix:** Ensure `static/app_icon.jpg` exists in the project directory:
```bash
ls -la ~/python/claude_analysis/static/app_icon.jpg
```

The file must be a JPEG image. The route `GET /app_icon.jpg` serves it from
`Path(__file__).parent / "static" / "app_icon.jpg"`.

### SQLite Database Corruption

**Symptoms:** Errors mentioning `database disk image is malformed`.

**Fix:** Delete the cache and let it rebuild:
```bash
rm -rf ~/python/claude_analysis/data/
sudo systemctl restart claude-activity
```

The cache is fully regenerable from the source JSONL files. No data is lost.

---

## 15. Service Lifecycle Operations

### Start, Stop, Restart

```bash
sudo systemctl start claude-activity     # Start
sudo systemctl stop claude-activity      # Stop
sudo systemctl restart claude-activity   # Restart (after code changes)
sudo systemctl status claude-activity    # Check status
```

### Enable/Disable Auto-Start

```bash
sudo systemctl enable claude-activity    # Start on boot
sudo systemctl disable claude-activity   # Do not start on boot
```

### Full Redeployment

If the project directory has been moved or recreated:

```bash
# 1. Recreate the venv
cd ~/python/claude_analysis
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Update the unit file if paths changed
sudo cp claude-activity.service /etc/systemd/system/
sudo systemctl daemon-reload

# 3. Restart
sudo systemctl restart claude-activity

# 4. Force a fresh cache build
curl -s http://127.0.0.1:8202/api/refresh | python3 -m json.tool
```

### Clearing the Cache

To force a complete rebuild from scratch:

```bash
rm -rf ~/python/claude_analysis/data/
sudo systemctl restart claude-activity
```

The `data/` directory and `cache.db` will be recreated automatically on next startup.

---

## 16. Security Model

### No Authentication

The service has no authentication layer. Every endpoint is publicly accessible to anyone
who can reach it. Security is provided entirely by the Tailscale network:

- nginx listens only on the Tailscale IP (`100.99.217.84:80`)
- uvicorn listens only on localhost (`127.0.0.1:8202`)
- Only devices on the Tailscale network can access the dashboard

### Attack Surface

| Vector | Mitigation |
|---|---|
| Network access | Tailscale VPN (no public exposure) |
| Direct port access | uvicorn bound to `127.0.0.1` only |
| File system access | Runs as unprivileged `pi` user |
| Input injection | JSONL files are read-only (dashboard never writes to them) |
| SQL injection | SQLite queries use parameterized statements |
| XSS | Dashboard data is JSON-encoded, not raw HTML interpolation |

### Data Sensitivity

The JSONL files contain Claude Code conversation logs, which may include:
- Code snippets from projects
- File paths on the host system
- Tool call parameters (bash commands, file contents)
- Cost and token usage data

This data is only accessible to Tailscale network members. There is no data exfiltration
path from the dashboard.

---

## 17. Recreation Checklist

Ordered steps to deploy the Claude Activity Dashboard from scratch on a fresh system:

1. **Install system prerequisites**
   - Python 3.11+, nginx, Tailscale

2. **Create project directory**
   ```bash
   mkdir -p ~/python/claude_analysis
   ```

3. **Copy all source files** (see [Directory Structure](#2-directory-structure))
   - All `.py` files, `dashboard_template.html`, `requirements.txt`, `.gitignore`
   - `tool_adapters/` package (8 files)
   - `analyzers/` package (4 files)
   - `static/app_icon.jpg`
   - `claude-activity.service`

4. **Set up Python environment**
   ```bash
   cd ~/python/claude_analysis
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

5. **Test locally**
   ```bash
   uvicorn app:app --host 127.0.0.1 --port 8202
   curl -s http://127.0.0.1:8202/healthz
   ```

6. **Install systemd service**
   ```bash
   sudo cp claude-activity.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable claude-activity
   sudo systemctl start claude-activity
   ```

7. **Configure nginx**
   - Add the `location /claude_activity/` block to your nginx config
   - Add the `location = /claude_activity/healthz` exact-match block
   - `sudo nginx -t && sudo systemctl reload nginx`

8. **Verify deployment** (follow [Verification Checklist](#12-verification-checklist))

9. **Trigger initial cache build**
   ```bash
   curl -s http://127.0.0.1:8202/api/refresh | python3 -m json.tool
   ```

10. **Access the dashboard**
    - `http://<tailscale-ip>/claude_activity/`

---

## Cross-References

- **02-DATA-LAYER.md**: SQLite schema, `cache_db.py` functions, migration system
- **04-TOOL-ADAPTERS.md**: The adapter package that normalizes tool calls during parsing
- **05-API-SERVER.md**: Complete `app.py` specification including all routes and dependency contracts
