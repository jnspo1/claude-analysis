# 00 — Master Index: Claude Activity Dashboard Recreation Guide

## What This Is

The **Claude Activity Dashboard** is a FastAPI web app that parses Claude Code's JSONL session logs and presents an interactive analytics dashboard. It shows tool usage, session timelines, cost estimates, subagent activity, and bash command patterns across all Claude Code projects.

**Tech stack:** Python 3.11+ / FastAPI / SQLite (WAL) / Jinja-free HTML template / Chart.js 4.4.7 / systemd + nginx

## File Tree

```
claude_analysis/                      # Project root
├── app.py                    (297)   # FastAPI server — routes, background rebuild, template injection
├── cache_db.py               (676)   # SQLite schema, CRUD, staleness detection, aggregate computation
├── single_pass_parser.py     (454)   # Optimized JSONL parser (one pass per file) — used by dashboard
├── session_parser.py         (675)   # Multi-pass JSONL parser — used by CLI scripts
├── extract_tool_usage.py     (392)   # CLI: extract all tool calls to CSV + summary. Provides iter_jsonl()
├── extract_bash_commands.py  (352)   # CLI: extract bash commands with heredoc cleaning
├── analyze_commands.py       (261)   # CLI: query helpers for bash command analysis
├── analyze_permissions.py    (567)   # CLI: simulate permission rules against historical calls
├── dashboard_template.html   (985)   # Single-file HTML/CSS/JS dashboard (Chart.js)
├── requirements.txt            (3)   # fastapi, uvicorn, pyyaml
├── claude-activity.service    (18)   # systemd unit file
├── .gitignore                 (17)   # Excludes data/, venv/, *.csv, *.txt
├── test_heredoc_cleaning.py  (104)   # Demo script for heredoc cleaning
├── CLAUDE.md                         # Project instructions for Claude Code
├── CHANGELOG.md                      # Change history
│
├── tool_adapters/                    # Adapter pattern for tool-specific extraction
│   ├── __init__.py            (27)   # Re-exports all public names
│   ├── base.py               (134)   # ExtractionOptions, ToolInvocation, ToolAdapter ABC
│   ├── bash.py                (62)   # BashAdapter
│   ├── file_ops.py           (172)   # ReadAdapter, WriteAdapter, EditAdapter
│   ├── search.py             (115)   # GrepAdapter, GlobAdapter
│   ├── tasks.py              (116)   # TaskAdapter, TodoWriteAdapter
│   ├── special.py            (112)   # SpecialToolAdapter, GenericAdapter
│   └── registry.py            (73)   # create_adapter_registry(), get_adapter()
│
├── analyzers/                        # Analysis modules for CLI scripts
│   ├── __init__.py            (14)   # Re-exports
│   ├── patterns.py           (121)   # Pattern extraction (3-level hierarchy)
│   ├── permissions.py        (289)   # Permission analysis + recommendations
│   └── summary.py            (440)   # Summary text generation
│
├── static/
│   └── app_icon.jpg                  # PWA icon (133KB JPEG)
│
└── data/                             # Runtime — gitignored
    └── cache.db                      # SQLite persistent cache (created by init_db())
```

Numbers in parentheses are line counts. **Total: ~6,400 lines** across 20+ source files.

## Recommended Build Order

Build bottom-up — each layer depends only on layers below it.

```
Step  What to build              Doc    Depends on
─────────────────────────────────────────────────────────
 1    tool_adapters/ package     04     (nothing)
 2    extract_tool_usage.py      03     tool_adapters
      (only iter_jsonl + helpers)
 3    session_parser.py          03     extract_tool_usage, tool_adapters
 4    single_pass_parser.py      03     extract_tool_usage, session_parser, tool_adapters
 5    cache_db.py                02     (nothing — pure SQLite)
 6    app.py                     05     cache_db, single_pass_parser, session_parser,
                                        extract_tool_usage, tool_adapters
 7    dashboard_template.html    06     (standalone HTML — consumes app.py's JSON)
 8    CLI scripts (optional)     07     extract_tool_usage, tool_adapters, analyzers
 9    Deploy                     08     All above
```

**Minimum viable dashboard (steps 1-7):** You need `tool_adapters/`, `extract_tool_usage.py` (for `iter_jsonl`), `session_parser.py`, `single_pass_parser.py`, `cache_db.py`, `app.py`, and `dashboard_template.html`.

The CLI scripts (step 8) are independent analysis tools — not required for the web dashboard.

## Key Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| fastapi | >=0.115.0 | Web framework |
| uvicorn | >=0.34.0 | ASGI server |
| pyyaml | >=6.0 | YAML output (CLI scripts only) |
| chart.js | 4.4.7 | Charts (loaded via CDN in HTML) |

Python stdlib heavily used: `sqlite3`, `json`, `threading`, `collections.Counter`, `dataclasses`, `pathlib`, `re`, `csv`, `fnmatch`.

## Documentation Map

| Doc | File | Purpose | When to use with Copilot |
|-----|------|---------|--------------------------|
| **00** | This file | Orientation | Always open — the roadmap |
| **01** | [01-ARCHITECTURE.md](01-ARCHITECTURE.md) | Data flow, caching, session shape | Before starting anything |
| **02** | [02-DATA-LAYER.md](02-DATA-LAYER.md) | SQLite schema + cache_db.py | Building cache_db.py |
| **03** | [03-PARSER.md](03-PARSER.md) | JSONL parsing engine | Building parsers + iter_jsonl |
| **04** | [04-TOOL-ADAPTERS.md](04-TOOL-ADAPTERS.md) | Adapter pattern + all adapters | Building tool_adapters/ |
| **05** | [05-API-SERVER.md](05-API-SERVER.md) | FastAPI app + routes | Building app.py |
| **06** | [06-FRONTEND.md](06-FRONTEND.md) | Full HTML/CSS/JS dashboard | Building dashboard_template.html |
| **07** | [07-CLI-SCRIPTS.md](07-CLI-SCRIPTS.md) | CLI extraction tools | Building CLI tools (optional) |
| **08** | [08-DEPLOYMENT.md](08-DEPLOYMENT.md) | systemd, nginx, verification | Final deployment step |

## Quick Start (for the impatient)

1. Read **01-ARCHITECTURE** for the big picture
2. Build **tool_adapters/** using doc **04** (no dependencies)
3. Build **cache_db.py** using doc **02** (no dependencies)
4. Build parsers using doc **03** (needs tool_adapters + iter_jsonl)
5. Build **app.py** using doc **05** (needs everything above)
6. Build **dashboard_template.html** using doc **06** (standalone)
7. Deploy using doc **08**

## Input Data

The dashboard reads Claude Code's JSONL logs from `~/.claude/projects/`. Each project directory contains session `.jsonl` files and optional `subagents/` subdirectories. Without these files, the dashboard will show an empty state.
