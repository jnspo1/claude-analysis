# CLAUDE.md

## Project Overview

Extracts and analyzes tool usage from Claude Code project JSONL logs. Used for permission configuration, security auditing, and understanding Claude Code workflow patterns.

## Live Service

The dashboard runs as a FastAPI service: `claude-activity` on port **8202**.

- Systemd unit: `claude-activity.service`
- Nginx proxy: `/claude_activity/` on Tailscale IP
- After code changes: `sudo systemctl restart claude-activity`
- App entry point: `app.py`

### API Endpoints

| Route | Description |
|---|---|
| `GET /` | Full HTML dashboard (~33KB gzipped) |
| `GET /api/overview` | Pre-computed overview aggregates |
| `GET /api/sessions?project=X` | Lightweight session summaries |
| `GET /api/session/{id}` | Full session detail (lazy loaded) |
| `GET /api/data` | Backward-compatible full payload (deprecated) |
| `GET /api/refresh` | Force incremental cache rebuild |
| `GET /api/rebuild-status` | Check rebuild progress |
| `GET /healthz` | Health check with cache status |

## Commands

```bash
# Development server (with auto-reload)
source venv/bin/activate
uvicorn app:app --host 127.0.0.1 --port 8202 --reload

# Restart production service
sudo systemctl restart claude-activity

# Extract tool usage data (CLI scripts, not used by dashboard)
python extract_tool_usage.py
python extract_bash_commands.py
python analyze_permissions.py
```

## Architecture

**Data flow**: `~/.claude/projects/**/*.jsonl` → `single_pass_parser.py` (single-pass extraction) → `cache_db.py` (SQLite persistent cache) → `app.py` (serve via FastAPI) → `dashboard_template.html` (Chart.js UI)

### Caching Strategy

- **SQLite persistent cache** at `data/cache.db` (WAL mode) stores parsed sessions and pre-computed aggregates
- **Incremental rebuilds**: Only new/changed JSONL files are reparsed (checked by mtime+size)
- **Stale-while-revalidate**: Requests are served instantly from SQLite; background thread rebuilds if cache is >5min old
- **Startup prewarm**: Background rebuild triggers on service start; first request served from existing SQLite data
- **Cold rebuild**: ~8-12s for all files (single-pass). **Warm rebuild**: <1s (incremental)

### Data Shape

- **Overview tab**: Pre-computed aggregates from `global_aggregates` table (~5KB)
- **Session dropdown**: Lightweight summaries from `session_summaries` table (~30-50KB)
- **Session detail**: Full data from `session_details` table, loaded on demand via `fetch()`
- **HTML payload**: ~149KB uncompressed, ~33KB gzipped (was 3MB before optimization)

## Key Scripts

- **app.py** - FastAPI service with SQLite backend, background rebuilds, tiered data injection
- **single_pass_parser.py** - Single-pass JSONL parser (merges 5-7 passes into one loop)
- **cache_db.py** - SQLite schema, CRUD, incremental staleness detection, aggregate computation
- **session_parser.py** - Original multi-pass parser (still used by CLI scripts)
- **dashboard_template.html** - HTML/CSS/JS dashboard template (Chart.js, async session loading)
- **extract_tool_usage.py** - CLI tool extraction to CSV/summary (provides `iter_jsonl()` used by parsers)
- **extract_bash_commands.py** - CLI bash command extraction with classification
- **analyze_commands.py** - Query helpers for analyzing extracted command data
- **analyze_permissions.py** - Simulates permission rules against historical tool calls

## Input

`~/.claude/projects/**/*.jsonl` - Claude Code's project log files

## Output

- `data/cache.db` - SQLite persistent cache (gitignored)
- `tool_events.csv` - All tool calls with timestamps, parameters, project context
- `tool_summary.txt` - Aggregated tool usage statistics
- `bash_commands.csv`, `bash_commands_all.txt` - Extracted Bash commands
- `bash_commands_summary.txt` - Command frequency analysis
- `permissions_suggested.yaml` - Suggested permission rules based on usage patterns
- `permission_analysis_report.txt` - Simulation results for permission rules

## Usage

```bash
source venv/bin/activate
python extract_tool_usage.py       # Extract all tool calls
python extract_bash_commands.py    # Extract Bash commands
python analyze_permissions.py      # Simulate permission rules
```

## UI Design System

Theme: **blue** (`<html data-theme="blue">`). Shared CSS: `/shared/pi-design.css`. Skill: `~/.claude/skills/fastapi-ui-design-system.md`.
