# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

#### 2026-02-16: Chart Reorganization with Cost and Activity Aggregations
- **Added**: 10 new columns to global_aggregates schema (cost_by_project, actions_daily/weekly/monthly, active_time_daily/weekly/monthly with time-filtered variants) to support multi-timescale visualizations.
- **Added**: Migration support in cache_db.py for schema evolution with backward compatibility.
- **Added**: Aggregation logic to compute cost breakdown by project and action/activity timelines at daily/weekly/monthly granularity, enabling accurate trend analysis over different time windows.
- **Added**: New Chart.js visualizations: Cost by Project pie chart (Activity by Time Range group), Actions breakdown timeline (Trends Over Time group), and Active Time timeline with three render functions (renderCostByProject, renderActionsTimeline, renderActiveTime).
- **Changed**: Dashboard layout reorganized into two grouped sections with shared pill controls: "Activity by Time Range" (2x2 grid controlling Tool Distribution, Top Projects, File Types, Cost by Project) and "Trends Over Time" (3-column grid controlling Sessions, Actions, Active Time charts). Synchronized pill handlers allow users to apply time-range filters across multiple charts simultaneously.
- **Updated**: Overview payload now returns all 10 new aggregation fields for client-side visualization.

#### 2026-02-16: Token Display Fix and Time-Range Chart Filters
- **Fixed**: Token card now shows all 4 token types (input + output + cache_creation + cache_read) instead of just input + output. Display changed from misleading "3.2M" to accurate "812M" reflecting true token volume.
- **Fixed**: Cost estimation now includes cache_creation tokens charged at 125% of input rate, matching Anthropic's actual pricing for cache writes.
- **Changed**: Token card sub-label shows "active + cached" split instead of "in / out | cache hit %".
- **Added**: Timeline granularity pills (Daily/Weekly/Monthly) on the Sessions Over Time chart, with pre-computed data for each granularity.
- **Added**: Time-range filter pills (All/Day/Week/Month) controlling Tool Distribution, Top Projects, and File Types charts simultaneously, with server-side pre-computed filtered variants.
- **Changed**: Chart rendering refactored to use destroyable instances for dynamic pill-based switching without page reload.

#### 2026-02-16: PWA Home Screen Support
- **Added**: iPhone home screen icon support with apple-touch-icon link and app title meta tags ("Task Monitor") to enable adding dashboard to iOS home screen. Includes /app_icon.jpg FileResponse endpoint and standalone mode meta tags for fullscreen display without Safari chrome.

#### 2026-02-15: CLAUDE.md Quality Audit
- **Added**: Dev server command, architecture section with data flow diagram, and cache behavior documentation to CLAUDE.md


#### 2026-02-14: Bash Category Refactoring and Command Classification Improvements
- **Changed**: Replaced 8 technical bash categories (Git, Search, File Ops, Python, Node/NPM, Network, System, Editor) with 6 plain-language categories (Version Control, Running Code, Searching & Reading, File Management, Testing & Monitoring, Server & System) in session_parser.py for improved user understanding and task-oriented grouping.
- **Changed**: Rewrote `categorize_bash_command()` to robustly handle edge cases: chained commands with `&&` and `;`, `cd` prefix skipping, full-path commands like `./venv/bin/python`, and venv activation patterns (both `source` and dot-space variants).
- **Added**: Bash command category doughnut chart in dashboard_template.html alongside the existing bash commands table using the detail-grid two-column layout for balanced visualization.
- **Added**: Color map and plain-English description tooltips for each bash category (e.g., "Running Code" displays "Executing scripts and running programs" on hover in chart legend).
- **Changed**: Category filter pills now display description tooltips on hover to help users understand each category's purpose.

#### 2026-02-14: Conversation Flow and Bash Command Categorization
- **Added**: `_is_interrupt_message()` function to detect Claude Code tool-use interruption markers in session_parser.py.
- **Added**: `extract_user_turns()` function to extract all user messages with metadata (text, timestamp, is_interrupt flag, turn_number) for conversation flow visualization.
- **Added**: `BASH_CATEGORIES` and `categorize_bash_command()` to classify bash commands into Git, Search, File Ops, Python, Node/NPM, Network, System, and Editor categories.
- **Changed**: `extract_first_prompt()` now skips interrupt markers to find the actual first user prompt.
- **Changed**: `build_session_data()` now extracts user turns, counts interrupts, and categorizes bash commands. Each bash command in the list now includes a `category` field.
- **Changed**: `/api/sessions` lightweight endpoint in app.py now includes `interrupt_count` for each session.
- **Added**: Dashboard now displays collapsible conversation flow with all user turns styled by type (regular vs interrupt), timestamps, and turn numbers.
- **Added**: Interrupt badge in session metadata showing count of interrupted requests.
- **Added**: Interactive bash category pills allowing users to filter the command table by category. Each pill shows the command count for that category.
- **Added**: Category column in bash commands table and data attributes for row-level filtering.
- **Added**: CSS styling for conversation flow (turn list with interrupt styling), interrupt badge, and category pills with hover/active states.
- **Fixed**: HTML parser breaking when `</script>` tags appear in user turn text data. Added escaping of `</` sequences to `<\/` before injecting JSON into script block—prevents malformed HTML when turn content contains closing tags.

#### 2026-02-14: Session Parser Library and Dashboard Metadata Enhancement
- **Added**: `session_parser.py` - Extracted session parsing logic from dashboard generation into a reusable library module. Removes static generation code; now provides pure session data extraction with rich metadata.
- **Added**: Rich metadata extraction including active duration (from turn_duration system entries), cache tokens (creation and read from usage data), permission mode, tool success/error counts, thinking level, unique models used, and cost estimation based on model pricing.
- **Added**: Subagent active duration extraction to track actual working time for spawned agents.
- **Changed**: `app.py` imports updated to use `session_parser` module. Added new fields to `/api/sessions` endpoint: active_duration_ms, total_active_duration_ms, cost_estimate, permission_mode.
- **Changed**: `dashboard_template.html` enhanced with formatting helpers and new UI cards showing total active time, token counts with cache hit percentage, estimated cost, and session-level metrics for thinking level, permission mode, and error counts.
- **Changed**: Updated `CLAUDE.md` to document session_parser.py and removed references to generate_dashboard.py.
- **Removed**: Static `dashboard.html` generated artifact (no longer checked in).
- **Removed**: `generate_dashboard.py` - functionality migrated to session_parser.py library module.

#### 2026-02-14: Interactive Dashboard for Session Analysis
- **Added**: `generate_dashboard.py` - Python script that scans all Claude Code JSONL session logs and generates a self-contained HTML dashboard with 1.3MB file size. Extracts session metadata including prompts, tool calls, timestamps, models, token usage, and subagent activity.
- **Added**: `dashboard_template.html` - Interactive HTML/CSS/JS dashboard with three tabs: Overview (summary cards, charts, timeline), Task Explorer (project/session filters, detailed breakdown), and Action Log (chronological tool calls with filtering and pagination).
- **Added**: `app.py` - FastAPI service that serves the dashboard as a live web service on port 8202, with JSON API endpoints for programmatic access and cache refresh capability.
- **Added**: `claude-activity.service` - Systemd unit file for running the FastAPI service as a persistent background service with automatic restart on failure.
- **Added**: `requirements.txt` - Python dependencies for the FastAPI service (fastapi, uvicorn, pyyaml).
- **Changed**: Updated `CLAUDE.md` to document the new dashboard scripts, live service configuration, API endpoints, and service management for analyzing multi-project Claude Code activity across 149 session files and 102 subagent files.
- **Note**: `dashboard.html` is a generated artifact and should not be committed to version control.

#### 2026-02-14: Enhanced Subagent Information in Dashboard
- **Added**: `extract_subagent_info()` function in `generate_dashboard.py` that extracts subagent_type and task_description from parent session Task tool calls by scanning JSONL for tool_use blocks and progress records. Enables rich context about what each subagent was working on.
- **Changed**: `build_subagent_data()` now includes subagent_type and task_description fields to provide complete agent context.
- **Changed**: Overview "Total Actions" card combines parent and subagent action counts to show the complete picture of work performed across the entire session tree.
- **Changed**: Session detail donut chart now includes subagent tool call counts alongside parent totals for accurate action distribution visualization.
- **Changed**: Subagent cards display agent type badge and task description prominently to quickly identify agent role and assigned work.
- **Changed**: Task prompt display in subagent cards now includes styled formatting for better readability.

## Current State

The claude_analysis project now provides comprehensive analysis of Claude Code tool usage across 12 projects with:
- Session-level metadata extraction and visualization
- Interactive filtering by project, session, and tool type
- Chronological action log with pagination
- Subagent activity tracking and breakdown
- Self-contained HTML dashboard for easy sharing and offline analysis
- Conversation flow analysis with user turn tracking and interrupt detection
- Bash command categorization with interactive filtering by command type
