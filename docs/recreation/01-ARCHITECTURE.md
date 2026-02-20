# 01 — Architecture: Data Flow, Components, and Design Decisions

## System Overview

```
 ┌─────────────────────────────────────────────────────────────────────┐
 │  ~/.claude/projects/**/*.jsonl    (Claude Code session logs)        │
 └───────────────────────┬─────────────────────────────────────────────┘
                         │
                         ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │  single_pass_parser.py                                              │
 │  ┌──────────────┐   ┌──────────────────┐   ┌────────────────────┐  │
 │  │ iter_jsonl() │──▶│ parse_session_   │──▶│ _build_subagent_   │  │
 │  │ (from        │   │ single_pass()    │   │ data_fast()        │  │
 │  │  extract_    │   │                  │   │                    │  │
 │  │  tool_usage) │   │ Uses adapters    │   │ (for each subagent │  │
 │  └──────────────┘   │ from tool_       │   │  JSONL file)       │  │
 │                     │ adapters/        │   └────────────────────┘  │
 │                     └──────────────────┘                           │
 └───────────────────────┬─────────────────────────────────────────────┘
                         │ Returns Dict (session data)
                         ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │  cache_db.py  (SQLite — data/cache.db, WAL mode)                   │
 │                                                                     │
 │  ┌──────────┐  ┌──────────────────┐  ┌────────────────────┐       │
 │  │file_cache│  │session_summaries │  │global_aggregates   │       │
 │  │(staleness│  │(lightweight list)│  │(pre-computed charts│       │
 │  │detection)│  │                  │  │ + time-filtered    │       │
 │  └──────────┘  └──────────────────┘  │ variants)          │       │
 │                ┌──────────────────┐  └────────────────────┘       │
 │                │session_details   │                                │
 │                │(full JSON blobs) │                                │
 │                └──────────────────┘                                │
 └───────────────────────┬─────────────────────────────────────────────┘
                         │
                         ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │  app.py  (FastAPI — port 8202)                                      │
 │                                                                     │
 │  ┌──────────────────┐   ┌──────────────────────────────────────┐   │
 │  │ Background       │   │ Routes                               │   │
 │  │ rebuild thread   │   │                                      │   │
 │  │                  │   │ GET /          → HTML with injected  │   │
 │  │ _incremental_    │   │                  overview + sessions │   │
 │  │ rebuild()        │   │ GET /api/session/{id} → full detail  │   │
 │  │                  │   │ GET /api/overview     → aggregates   │   │
 │  │ Runs every 5min  │   │ GET /api/sessions     → summaries   │   │
 │  │ or on startup    │   │ GET /api/refresh      → force build │   │
 │  └──────────────────┘   └──────────────────────────────────────┘   │
 └───────────────────────┬─────────────────────────────────────────────┘
                         │ HTML with embedded JSON
                         ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │  dashboard_template.html  (Chart.js 4.4.7)                         │
 │                                                                     │
 │  ┌──────────┐  ┌────────────────┐  ┌────────────────┐             │
 │  │ Overview │  │ Task Explorer  │  │ Action Log     │             │
 │  │ (7 charts│  │ (async session │  │ (paginated     │             │
 │  │  + cards)│  │  loading)      │  │  tool calls)   │             │
 │  └──────────┘  └────────────────┘  └────────────────┘             │
 └─────────────────────────────────────────────────────────────────────┘
```

## Component Relationships (Imports)

```
app.py
├── extract_tool_usage.py     (find_jsonl_files, derive_project_name)
├── session_parser.py         (make_project_readable)
├── single_pass_parser.py     (parse_session_single_pass)
├── tool_adapters/            (create_adapter_registry, ExtractionOptions)
└── cache_db.py               (init_db, get_connection, get_stale_files, ...)

single_pass_parser.py
├── extract_tool_usage.py     (iter_jsonl, derive_project_name)
├── session_parser.py         (_extract_text_from_content, _is_interrupt_message,
│                               _get_tool_detail, _get_file_path, _estimate_cost,
│                               build_tool_calls_list, categorize_bash_command,
│                               find_subagent_files, extract_active_duration,
│                               make_project_readable)
└── tool_adapters/            (create_adapter_registry, get_adapter,
                               ExtractionOptions, ToolInvocation)

session_parser.py
├── extract_tool_usage.py     (iter_jsonl, find_jsonl_files,
│                               derive_project_name, extract_tools_from_file)
└── tool_adapters/            (create_adapter_registry, ExtractionOptions,
                               ToolInvocation)

extract_tool_usage.py
├── tool_adapters/            (create_adapter_registry, get_adapter,
│                               ExtractionOptions, ToolInvocation)
└── analyzers/                (extract_patterns, analyze_permissions, write_summary)

cache_db.py
└── (stdlib only — json, sqlite3, collections, datetime, pathlib)
```

## Caching Strategy: Stale-While-Revalidate

The dashboard uses a 3-tier caching approach to achieve sub-second response times:

### Tier 1: File Staleness Detection
- `file_cache` table stores `(file_path, file_mtime, file_size)` for each JSONL file
- On rebuild, compare filesystem mtime+size against cached values
- Only reparse files that are new or changed
- **Cold rebuild** (all files): ~8-12s on Raspberry Pi 4B
- **Warm rebuild** (incremental): <1s

### Tier 2: Pre-computed Aggregates
- `global_aggregates` table (singleton row) stores all overview chart data as JSON columns
- 42 columns including time-filtered variants (1d, 7d, 30d)
- Recomputed after every session upsert/delete cycle
- The overview tab reads ONLY from this table (~5KB payload)

### Tier 3: Stale-While-Revalidate Pattern
```
Request arrives
    │
    ├── Serve instantly from SQLite cache (never blocks)
    │
    └── Is cache older than 5 minutes?
         ├── No  → done
         └── Yes → spawn background daemon thread → _incremental_rebuild()
                   (next request will get fresh data)
```

### Startup Behavior
1. `lifespan()` calls `init_db()` (creates schema if needed)
2. Spawns background thread for `_incremental_rebuild()`
3. First request served from existing SQLite data (may be stale from last run)
4. Background rebuild finishes within seconds, subsequent requests are fresh

## Session Data Shape

This is THE critical data structure that flows through the entire system. Produced by `parse_session_single_pass()` and stored in `session_details.detail_json`.

```python
{
    # Identity
    "session_id": "abc123-def456",           # JSONL filename stem
    "slug": "my-session",                     # Optional human-readable name
    "project": "admin-panel",                 # Readable project name

    # Prompt
    "first_prompt": "Add a logout button...", # First real user message (full)
    "prompt_preview": "Add a logout bu...",   # Truncated to 80 chars

    # Timing
    "start_time": "2026-02-15T10:30:00Z",    # First timestamp in file
    "end_time": "2026-02-15T11:45:00Z",      # Last timestamp in file
    "active_duration_ms": 450000,             # Sum of turn_duration entries (parent only)
    "total_active_duration_ms": 600000,       # Parent + all subagents

    # Model
    "model": "claude-sonnet-4-5-20250929",    # First model seen
    "models_used": ["claude-sonnet-4-5-..."], # All models seen (sorted)
    "thinking_level": "high",                 # From thinkingMetadata.level
    "permission_mode": "default",             # From permissionMode field

    # Counts
    "turn_count": 5,                          # Number of user messages
    "total_tools": 42,                        # Parent tool invocations only
    "interrupt_count": 1,                     # User interrupts
    "tool_errors": 2,                         # tool_result is_error count
    "tool_successes": 40,                     # tool_result non-error count

    # Tool breakdown
    "tool_counts": {"Read": 15, "Edit": 10, "Bash": 8, ...},
    "file_extensions": {".py": 12, ".md": 3, ...},
    "files_touched": {                        # path -> {tool: count}
        "/home/pi/app.py": {"Read": 3, "Edit": 2},
        ...
    },

    # Bash analysis
    "bash_commands": [                        # Top 50 by count
        {"command": "git status", "base": "git", "count": 5, "category": "Version Control"},
        ...
    ],
    "bash_category_summary": {"Version Control": 15, "Running Code": 8, ...},

    # Chronological action log
    "tool_calls": [                           # All tool invocations in order
        {"seq": 1, "time": "2026-02-15T10:30:05Z", "tool": "Read", "detail": "/home/pi/app.py", "is_subagent": false},
        ...
    ],

    # Conversation flow
    "user_turns": [
        {"text": "Add a logout button...", "timestamp": "...", "is_interrupt": false, "turn_number": 1},
        ...
    ],

    # Tokens and cost
    "tokens": {
        "input": 150000,
        "output": 25000,
        "cache_creation": 50000,
        "cache_read": 100000
    },
    "cost_estimate": 1.2345,                  # USD, 4 decimal places

    # Subagents
    "subagents": [
        {
            "agent_id": "ad7c5cf",
            "subagent_type": "code-reviewer",
            "task_description": "Review auth code",
            "description": "Review the authentication...", # First prompt (max 200 chars)
            "tool_count": 8,
            "tool_counts": {"Read": 5, "Grep": 3},
            "tool_calls": [{"seq": 1, ...}],
            "active_duration_ms": 15000
        },
        ...
    ]
}
```

## Cost Estimation Formula

```python
# Rates per million tokens
if "opus" in model:     input_rate, output_rate = 15.0, 75.0
elif "haiku" in model:  input_rate, output_rate = 0.80, 4.0
else:                   input_rate, output_rate = 3.0, 15.0  # sonnet default

cache_creation_rate = input_rate * 1.25  # 125% of input (write premium)
cache_read_rate = input_rate * 0.10      # 10% of input

cost = (input * input_rate + output * output_rate
      + cache_creation * cache_creation_rate
      + cache_read * cache_read_rate) / 1_000_000
```

## Bash Command Categorization

Commands are classified into 6 categories + "Other" using regex patterns:

| Category | Regex Pattern |
|----------|--------------|
| Version Control | `^(git\|gh)\b` |
| Running Code | `^(python\|python3\|pip\|pip3\|node\|npm\|npx\|yarn\|pytest\|uvicorn\|mypy\|ruff\|black\|isort\|flake8\|pylint)\b` |
| Searching & Reading | `^(grep\|rg\|find\|fd\|ag\|ack\|ls\|cat\|head\|tail\|wc\|tree\|sort\|uniq\|tee\|stat\|du\|df)\b` |
| File Management | `^(mkdir\|rmdir\|rm\|mv\|cp\|chmod\|chown\|ln\|touch\|tar\|zip\|unzip\|gzip)\b` |
| Testing & Monitoring | `^(curl\|wget\|ssh\|scp\|rsync\|ping\|nc\|netstat\|ss\|ps\|kill\|pkill\|top\|htop\|lsof\|which\|whereis)\b` |
| Server & System | `^(systemctl\|journalctl\|service\|docker\|docker-compose\|nginx\|hostname\|uname\|date\|whoami\|env\|export\|echo\|printf\|sleep\|sed\|awk\|sqlite3)\b` |

**Preprocessing before matching:**
1. Split on `&&` and `;` (handle chained commands)
2. Take first command in pipe (`|`)
3. Strip `sudo` prefix
4. Strip env var prefixes (`FOO=bar`)
5. Skip `cd` segments
6. Handle `source`/`. ` (venv activation → "Running Code")
7. Extract basename from paths (`./venv/bin/python` → `python`)

## Data Tiering (HTML Payload Optimization)

The original approach embedded ALL session data in the HTML (~3MB). The current approach tiers data delivery:

| Tier | What | Size | When loaded |
|------|------|------|-------------|
| Overview aggregates | Summary cards + chart data | ~5KB | Injected in HTML at page load |
| Session summaries | Dropdown list with previews | ~30-50KB | Injected in HTML at page load |
| Session details | Full tool calls, files, turns | ~5-50KB each | Lazy-loaded via `fetch()` on selection |

**Total initial HTML payload:** ~149KB uncompressed, ~33KB gzipped (down from ~3MB).

## Template Injection Mechanism

The HTML template contains a placeholder:
```javascript
const DASHBOARD_DATA = {};
```

app.py replaces this via string substitution:
```python
data_json = json.dumps(init_data, ensure_ascii=False, default=str)
data_json = data_json.replace("</", r"<\/")  # Prevent script injection
html = template.replace(
    "const DASHBOARD_DATA = {};",
    f"const DASHBOARD_DATA = {data_json};",
)
```

The `</` → `<\/` replacement prevents `</script>` in JSON data from prematurely closing the script tag.

## JSONL File Structure

Claude Code writes one JSON object per line. Relevant object types:

```jsonl
{"type": "system", "subtype": "turn_duration", "durationMs": 5000, "timestamp": "..."}
{"message": {"role": "user", "content": [{"type": "text", "text": "..."}]}, "timestamp": "...", "permissionMode": "default"}
{"message": {"role": "assistant", "model": "claude-...", "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "..."}, "id": "..."}], "usage": {"input_tokens": 1000, "output_tokens": 500}}, "timestamp": "..."}
{"type": "progress", "data": {"agentId": "abc123"}, "parentToolUseID": "tooluse_xyz"}
```

Key fields extracted:
- `obj.timestamp` — ISO 8601 timestamp
- `obj.slug` — optional session name
- `obj.type` / `obj.subtype` — system events (turn_duration, progress)
- `obj.permissionMode` — permission mode setting
- `obj.thinkingMetadata.level` — thinking level (if extended thinking)
- `obj.message.role` — "user" or "assistant"
- `obj.message.model` — model identifier
- `obj.message.usage` — token counts
- `obj.message.content` — list of content blocks (text, tool_use, tool_result)

## Subagent File Discovery

```
Session file: <project>/<session-uuid>.jsonl
Subagents:    <project>/<session-uuid>/subagents/agent-*.jsonl
```

Parent session tracks the mapping:
1. `Task` tool_use block has `id` (tool_use_id) and `input.subagent_type` + `input.description`
2. `progress` records link `parentToolUseID` to `data.agentId`
3. Combined: `agent_id` → `{subagent_type, description}`

## Performance Characteristics

| Metric | Value |
|--------|-------|
| Cold rebuild (all files) | ~8-12s (Raspberry Pi 4B) |
| Warm rebuild (incremental) | <1s |
| HTML payload (gzipped) | ~33KB |
| Overview API response | <10ms |
| Session list API response | <50ms |
| Session detail API response | <20ms |
| SQLite DB size | ~5-20MB (depends on session count) |
| Max JSONL file size | 100MB (configurable) |
