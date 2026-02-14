#!/usr/bin/env python3
"""
Generate a self-contained HTML dashboard showing Claude Code activity.

Scans ~/.claude/projects/**/*.jsonl files, extracts session metadata,
tool calls, and subagent data, then embeds everything as JSON inside
a single HTML file that can be opened in any browser.

Usage:
    python generate_dashboard.py                    # Default: dashboard.html
    python generate_dashboard.py -o my_report.html  # Custom output
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Reuse existing extraction infrastructure
from extract_tool_usage import (
    iter_jsonl,
    find_jsonl_files,
    derive_project_name,
    extract_tools_from_file,
)
from tool_adapters import create_adapter_registry, ExtractionOptions, ToolInvocation


def extract_first_prompt(jsonl_path: Path) -> Optional[str]:
    """Find the first real user message (not a system/command message)."""
    for _lineno, obj in iter_jsonl(jsonl_path):
        if obj is None:
            continue
        msg = obj.get("message") or {}
        if msg.get("role") != "user":
            continue

        content = msg.get("content", "")
        text = _extract_text_from_content(content)
        if not text:
            continue

        # Skip system-generated messages and commands
        stripped = text.strip()
        if stripped.startswith("<local-command") or stripped.startswith("<command-"):
            continue
        if len(stripped) < 3:
            continue

        # Strip leading XML tags (system-reminder, etc.) to find actual user text
        cleaned = re.sub(r'^(<[^>]+>[\s\S]*?</[^>]+>\s*)+', '', stripped).strip()
        if cleaned and len(cleaned) > 3:
            return cleaned
        if len(stripped) > 3:
            return stripped

    return None


def _extract_text_from_content(content) -> Optional[str]:
    """Extract text from message content (handles string and list-of-blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts) if parts else None
    return None


def count_turns(jsonl_path: Path) -> int:
    """Count user messages (turns) in a session."""
    count = 0
    for _lineno, obj in iter_jsonl(jsonl_path):
        if obj is None:
            continue
        msg = obj.get("message") or {}
        if msg.get("role") == "user":
            count += 1
    return count


def extract_session_metadata(jsonl_path: Path) -> Dict[str, Any]:
    """Extract slug, model, timestamps, and token usage from a session."""
    slug = None
    model = None
    first_ts = None
    last_ts = None
    total_input_tokens = 0
    total_output_tokens = 0

    for _lineno, obj in iter_jsonl(jsonl_path):
        if obj is None:
            continue

        # Slug can appear on any record
        if not slug and obj.get("slug"):
            slug = obj["slug"]

        # Track timestamps
        ts = obj.get("timestamp")
        if ts:
            if first_ts is None:
                first_ts = ts
            last_ts = ts

        # Model and usage from assistant messages
        msg = obj.get("message") or {}
        if msg.get("model") and not model:
            model = msg["model"]

        usage = msg.get("usage")
        if usage:
            total_input_tokens += usage.get("input_tokens", 0)
            total_output_tokens += usage.get("output_tokens", 0)

    return {
        "slug": slug,
        "model": model,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
    }


def find_subagent_files(jsonl_path: Path) -> List[Path]:
    """Find subagent JSONL files for a session.

    Session file: <project>/<session-uuid>.jsonl
    Subagents dir: <project>/<session-uuid>/subagents/agent-*.jsonl
    """
    session_dir = jsonl_path.parent / jsonl_path.stem
    subagents_dir = session_dir / "subagents"
    if not subagents_dir.is_dir():
        return []
    return sorted(subagents_dir.glob("*.jsonl"))


def extract_subagent_info(jsonl_path: Path) -> Dict[str, Dict[str, str]]:
    """Extract subagent type and description from parent session's Task tool calls.

    Scans the parent JSONL for:
    1. Task tool_use blocks -> tool_use_id to {subagent_type, description}
    2. Progress records -> parentToolUseID to agentId

    Returns:
        {agent_id: {"subagent_type": str, "description": str}}
    """
    # Map tool_use_id -> {subagent_type, description} from Task invocations
    task_calls: Dict[str, Dict[str, str]] = {}
    # Map parentToolUseID -> agentId from progress records
    agent_mapping: Dict[str, str] = {}

    for _lineno, obj in iter_jsonl(jsonl_path):
        if obj is None:
            continue

        # Look for Task tool_use blocks in assistant messages
        msg = obj.get("message") or {}
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if (isinstance(block, dict)
                        and block.get("type") == "tool_use"
                        and block.get("name") == "Task"):
                    tool_use_id = block.get("id", "")
                    inp = block.get("input", {})
                    task_calls[tool_use_id] = {
                        "subagent_type": inp.get("subagent_type", ""),
                        "description": inp.get("description", ""),
                    }

        # Look for progress records with agentId
        if obj.get("type") == "progress":
            data = obj.get("data", {})
            agent_id = data.get("agentId")
            parent_tool_use_id = obj.get("parentToolUseID")
            if agent_id and parent_tool_use_id and parent_tool_use_id not in agent_mapping:
                agent_mapping[parent_tool_use_id] = agent_id

    # Combine: agent_id -> {subagent_type, description}
    result: Dict[str, Dict[str, str]] = {}
    for tool_use_id, info in task_calls.items():
        agent_id = agent_mapping.get(tool_use_id)
        if agent_id:
            result[agent_id] = info

    return result


def _get_tool_detail(inv: ToolInvocation) -> str:
    """Get a human-readable detail string for a tool invocation."""
    name = inv.tool_name
    if name == "Bash":
        cmd = inv.bash_command or ""
        return cmd[:200] if len(cmd) > 200 else cmd
    elif name == "Read":
        return inv.read_file_path or ""
    elif name == "Write":
        return inv.write_file_path or ""
    elif name == "Edit":
        return inv.edit_file_path or ""
    elif name == "Grep":
        path = inv.grep_path or ""
        pattern = inv.grep_pattern or ""
        return f"{pattern} in {path}" if path else pattern
    elif name == "Glob":
        return inv.glob_pattern or ""
    elif name == "Task":
        return inv.task_description_preview or inv.task_subject or ""
    elif name in ("TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "TaskOutput"):
        return inv.task_subject or inv.task_operation or ""
    elif name == "WebSearch":
        return inv.websearch_query or ""
    elif name == "Skill":
        return inv.skill_name or ""
    elif name == "AskUserQuestion":
        return inv.ask_question_preview or ""
    else:
        return inv.raw_input_json[:150] if inv.raw_input_json else ""


def _get_file_path(inv: ToolInvocation) -> Optional[str]:
    """Get the file path from a file operation invocation."""
    if inv.tool_name == "Read":
        return inv.read_file_path
    elif inv.tool_name == "Write":
        return inv.write_file_path
    elif inv.tool_name == "Edit":
        return inv.edit_file_path
    return None


def build_tool_calls_list(
    invocations: List[ToolInvocation], is_subagent: bool = False
) -> List[Dict]:
    """Convert ToolInvocation list to serializable dicts for the dashboard."""
    calls = []
    for i, inv in enumerate(invocations):
        calls.append({
            "seq": i + 1,
            "time": inv.timestamp or "",
            "tool": inv.tool_name,
            "detail": _get_tool_detail(inv),
            "is_subagent": is_subagent,
        })
    return calls


def build_session_data(
    jsonl_path: Path,
    project: str,
    adapters: Dict,
    options: ExtractionOptions,
) -> Optional[Dict]:
    """Build complete session data dict for one JSONL file."""
    # Extract tool invocations using existing infrastructure
    invocations, _ = extract_tools_from_file(jsonl_path, project, adapters, options)

    # Extract session metadata
    meta = extract_session_metadata(jsonl_path)
    first_prompt = extract_first_prompt(jsonl_path)
    turn_count = count_turns(jsonl_path)

    # Skip sessions with no tools and no meaningful content
    if not invocations and not first_prompt:
        return None

    session_id = jsonl_path.stem

    # Tool counts
    tool_counter = Counter(inv.tool_name for inv in invocations)

    # File extensions and files touched
    file_extensions: Counter = Counter()
    files_touched: Dict[str, Dict[str, int]] = {}
    for inv in invocations:
        fpath = _get_file_path(inv)
        if fpath:
            ext = Path(fpath).suffix or "(no ext)"
            file_extensions[ext] += 1
            if fpath not in files_touched:
                files_touched[fpath] = {}
            files_touched[fpath][inv.tool_name] = files_touched[fpath].get(inv.tool_name, 0) + 1

    # Bash commands aggregation
    bash_cmds: Counter = Counter()
    bash_bases: Counter = Counter()
    for inv in invocations:
        if inv.tool_name == "Bash" and inv.bash_command:
            cmd = inv.bash_command.strip()
            bash_cmds[cmd] += 1
            base = cmd.split()[0] if cmd.split() else cmd
            bash_bases[base] += 1

    bash_commands_list = []
    for cmd, cnt in bash_cmds.most_common(50):
        base = cmd.split()[0] if cmd.split() else cmd
        bash_commands_list.append({
            "command": cmd[:200],
            "base": base,
            "count": cnt,
        })

    # Tool calls chronological list
    tool_calls = build_tool_calls_list(invocations)

    # Prompt preview (truncated for dropdown display)
    prompt_preview = None
    if first_prompt:
        prompt_preview = first_prompt[:80] + "..." if len(first_prompt) > 80 else first_prompt

    # Process subagents
    subagents = []
    subagent_files = find_subagent_files(jsonl_path)
    subagent_info = extract_subagent_info(jsonl_path) if subagent_files else {}
    for sa_path in subagent_files:
        sa_data = build_subagent_data(sa_path, project, adapters, options, subagent_info)
        if sa_data:
            subagents.append(sa_data)

    return {
        "session_id": session_id,
        "slug": meta["slug"],
        "project": project,
        "first_prompt": first_prompt,
        "prompt_preview": prompt_preview,
        "turn_count": turn_count,
        "start_time": meta["first_ts"],
        "end_time": meta["last_ts"],
        "model": meta["model"],
        "total_tools": len(invocations),
        "tool_counts": dict(tool_counter.most_common()),
        "file_extensions": dict(file_extensions.most_common()),
        "files_touched": files_touched,
        "bash_commands": bash_commands_list,
        "tool_calls": tool_calls,
        "tokens": {
            "input": meta["total_input_tokens"],
            "output": meta["total_output_tokens"],
        },
        "subagents": subagents,
    }


def build_subagent_data(
    sa_path: Path,
    project: str,
    adapters: Dict,
    options: ExtractionOptions,
    subagent_info: Optional[Dict[str, Dict[str, str]]] = None,
) -> Optional[Dict]:
    """Build data dict for a single subagent JSONL file."""
    invocations, _ = extract_tools_from_file(sa_path, project, adapters, options)
    if not invocations:
        return None

    # Agent ID from filename (agent-ad7c5cf.jsonl -> ad7c5cf)
    agent_id = sa_path.stem.replace("agent-", "")

    # Get subagent type and task description from parent's Task tool call
    info = (subagent_info or {}).get(agent_id, {})
    subagent_type = info.get("subagent_type", "")
    task_description = info.get("description", "")

    # Fall back to extracting from the subagent's own first prompt
    description = extract_first_prompt(sa_path)
    if description and len(description) > 200:
        description = description[:200] + "..."

    tool_counter = Counter(inv.tool_name for inv in invocations)

    return {
        "agent_id": agent_id,
        "subagent_type": subagent_type,
        "task_description": task_description,
        "description": description,
        "tool_count": len(invocations),
        "tool_counts": dict(tool_counter.most_common()),
        "tool_calls": build_tool_calls_list(invocations, is_subagent=True),
    }


def make_project_readable(raw: str) -> str:
    """Convert raw project dir name to readable form.

    Example: '-home-pi-python-admin-panel' -> 'admin-panel'
    """
    # Strip common prefix patterns (longest first)
    name = raw
    for prefix in ["-home-pi-python-", "-home-pi-TP--", "-home-pi-TP-", "-home-pi-"]:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break

    # Handle special cases
    if name == "-home-pi":
        return "home (misc)"
    if name == "TP" or name == "-home-pi-TP":
        return "TP"

    return name or raw


def generate_dashboard(
    root: Path,
    template_path: Path,
    output_path: Path,
    verbose: bool = False,
):
    """Main entry: scan JSONL files, build data, generate HTML."""
    print("=" * 60)
    print("CLAUDE CODE ACTIVITY DASHBOARD GENERATOR")
    print("=" * 60)
    print(f"Scanning: {root}")
    print()

    adapters = create_adapter_registry()
    options = ExtractionOptions(
        include_content_previews=True,
        preview_length=150,
        verbose=verbose,
    )

    # Find only top-level session JSONL files (not subagent files)
    all_jsonl = find_jsonl_files(root)
    # Filter out subagent files (they live under */subagents/)
    session_files = [
        p for p in all_jsonl
        if "subagents" not in p.parts
    ]

    print(f"Found {len(session_files)} session files "
          f"({len(all_jsonl) - len(session_files)} subagent files)")

    sessions = []
    projects_seen = set()

    for i, jsonl_path in enumerate(session_files):
        project_raw = derive_project_name(jsonl_path, root)
        project = make_project_readable(project_raw)
        projects_seen.add(project)

        if verbose:
            print(f"  [{i+1}/{len(session_files)}] {project}/{jsonl_path.name}")

        try:
            session = build_session_data(jsonl_path, project, adapters, options)
            if session:
                sessions.append(session)
        except Exception as e:
            print(f"  Warning: Failed to process {jsonl_path.name}: {e}",
                  file=sys.stderr)

    # Sort sessions by start_time descending (newest first)
    sessions.sort(key=lambda s: s.get("start_time") or "", reverse=True)

    print(f"\nProcessed {len(sessions)} sessions across {len(projects_seen)} projects")

    # Build the dashboard data payload
    dashboard_data = {
        "generated_at": datetime.now().isoformat(),
        "projects": sorted(projects_seen),
        "sessions": sessions,
    }

    # Read template and inject data
    if not template_path.exists():
        print(f"Error: Template not found: {template_path}", file=sys.stderr)
        sys.exit(1)

    template_html = template_path.read_text(encoding="utf-8")

    # Inject data as JSON - replace the placeholder in the template
    data_json = json.dumps(dashboard_data, ensure_ascii=False)
    output_html = template_html.replace(
        "const DASHBOARD_DATA = {};",
        f"const DASHBOARD_DATA = {data_json};",
    )

    output_path.write_text(output_html, encoding="utf-8")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"\nDashboard written to: {output_path}")
    print(f"  Size: {size_mb:.1f} MB")
    print(f"  Sessions: {len(sessions)}")
    print(f"  Projects: {len(projects_seen)}")

    total_tools = sum(s["total_tools"] for s in sessions)
    total_subagents = sum(len(s["subagents"]) for s in sessions)
    print(f"  Total tool calls: {total_tools:,}")
    print(f"  Total subagents: {total_subagents}")
    print(f"\nOpen in a browser: file://{output_path.resolve()}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a self-contained HTML dashboard of Claude Code activity"
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=Path("dashboard.html"),
        help="Output HTML file path (default: dashboard.html)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.home() / ".claude/projects",
        help="Root directory to scan for JSONL files",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=Path(__file__).parent / "dashboard_template.html",
        help="Path to HTML template file",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.root.exists():
        print(f"Error: Root directory does not exist: {args.root}", file=sys.stderr)
        sys.exit(1)
    generate_dashboard(args.root, args.template, args.output, args.verbose)


if __name__ == "__main__":
    main()
