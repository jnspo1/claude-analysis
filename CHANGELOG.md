# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

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
