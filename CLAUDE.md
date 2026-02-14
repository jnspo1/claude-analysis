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
| `GET /` | Full HTML dashboard |
| `GET /api/data` | Raw dashboard JSON |
| `GET /api/refresh` | Force cache rebuild |
| `GET /api/sessions?project=X` | Lightweight session list |
| `GET /api/session/{id}` | Full session detail |
| `GET /healthz` | Health check |

## Key Scripts

- **app.py** - FastAPI service serving the live dashboard (port 8202)
- **session_parser.py** - JSONL session parsing: metadata extraction, tool calls, subagent data, timing, cost estimation
- **extract_tool_usage.py** - Extracts all tool calls from `~/.claude/projects/**/*.jsonl` into CSV/summary
- **extract_bash_commands.py** - Extracts Bash commands specifically, with classification
- **analyze_commands.py** - Query helpers for analyzing extracted command data
- **analyze_permissions.py** - Simulates permission rules against historical tool calls (allow/ask/deny)
- **test_heredoc_cleaning.py** - Tests for HEREDOC command cleaning logic
- **dashboard_template.html** - HTML/CSS/JS template for the dashboard (Chart.js, vanilla JS)

## Input

`~/.claude/projects/**/*.jsonl` - Claude Code's project log files

## Output

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
