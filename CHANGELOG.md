# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

#### 2026-02-14: Interactive Dashboard for Session Analysis
- **Added**: `generate_dashboard.py` - Python script that scans all Claude Code JSONL session logs and generates a self-contained HTML dashboard with 1.3MB file size. Extracts session metadata including prompts, tool calls, timestamps, models, token usage, and subagent activity.
- **Added**: `dashboard_template.html` - Interactive HTML/CSS/JS dashboard with three tabs: Overview (summary cards, charts, timeline), Task Explorer (project/session filters, detailed breakdown), and Action Log (chronological tool calls with filtering and pagination).
- **Changed**: Updated `CLAUDE.md` to document the new dashboard scripts and their capabilities for analyzing multi-project Claude Code activity across 149 session files and 102 subagent files.
- **Note**: `dashboard.html` is a generated artifact and should not be committed to version control.

## Current State

The claude_analysis project now provides comprehensive analysis of Claude Code tool usage across 12 projects with:
- Session-level metadata extraction and visualization
- Interactive filtering by project, session, and tool type
- Chronological action log with pagination
- Subagent activity tracking and breakdown
- Self-contained HTML dashboard for easy sharing and offline analysis
