"""
Parse Claude Code JSONL session logs into structured data.

Extracts session metadata, tool calls, subagent data, and timing
information from ~/.claude/projects/**/*.jsonl files. Used by the
FastAPI dashboard (app.py).
"""

from __future__ import annotations

import json
import os
import re
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


def _is_interrupt_message(text: str) -> bool:
    """Check if a message is a Claude Code tool-use interruption marker."""
    stripped = text.strip()
    return stripped in (
        "[Request interrupted by user]",
        "[Request interrupted by user for tool use]",
    )


def extract_first_prompt(jsonl_path: Path) -> Optional[str]:
    """Find the first real user message (not a system/command/interrupt message)."""
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
        # Skip interrupt markers
        if _is_interrupt_message(stripped):
            continue

        # Strip leading XML tags (system-reminder, etc.) to find actual user text
        cleaned = re.sub(r'^(<[^>]+>[\s\S]*?</[^>]+>\s*)+', '', stripped).strip()
        if cleaned and len(cleaned) > 3:
            return cleaned
        if len(stripped) > 3:
            return stripped

    return None


def extract_user_turns(jsonl_path: Path) -> List[Dict[str, Any]]:
    """Extract all user messages with metadata for conversation flow display.

    Returns list of dicts with: text, timestamp, is_interrupt, turn_number.
    System/command messages are excluded.
    """
    turns: List[Dict[str, Any]] = []
    turn_number = 0

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

        stripped = text.strip()
        # Skip system-generated messages and commands
        if stripped.startswith("<local-command") or stripped.startswith("<command-"):
            continue
        if len(stripped) < 3:
            continue

        turn_number += 1
        is_interrupt = _is_interrupt_message(stripped)

        # Clean XML tags from non-interrupt messages for display
        display_text = stripped
        if not is_interrupt:
            cleaned = re.sub(r'^(<[^>]+>[\s\S]*?</[^>]+>\s*)+', '', stripped).strip()
            if cleaned and len(cleaned) > 3:
                display_text = cleaned

        # Truncate long messages for display
        if len(display_text) > 300:
            display_text = display_text[:300] + "..."

        turns.append({
            "text": display_text,
            "timestamp": obj.get("timestamp"),
            "is_interrupt": is_interrupt,
            "turn_number": turn_number,
        })

    return turns


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


# -- Bash command categorization --
BASH_CATEGORIES = {
    "Git": re.compile(r'^(git|gh)\b'),
    "Search": re.compile(r'^(grep|rg|find|fd|ag|ack)\b'),
    "File Ops": re.compile(r'^(ls|cp|mv|rm|mkdir|rmdir|chmod|chown|ln|touch|stat|du|df|cat|head|tail|wc|sort|uniq|tee|tar|zip|unzip|gzip)\b'),
    "Python": re.compile(r'^(python|python3|pip|pip3|pytest|mypy|ruff|black|isort|flake8|pylint|uvicorn)\b'),
    "Node/NPM": re.compile(r'^(node|npm|npx|yarn|pnpm|bun|deno|tsx|tsc)\b'),
    "Network": re.compile(r'^(curl|wget|ssh|scp|rsync|ping|nc|netstat|ss|nmap|dig|nslookup|traceroute)\b'),
    "System": re.compile(r'^(sudo|systemctl|journalctl|service|kill|pkill|ps|top|htop|which|whereis|whoami|hostname|uname|date|env|export|source|echo|printf|sleep|docker|docker-compose)\b'),
    "Editor": re.compile(r'^(sed|awk|vim|vi|nano|code|subl)\b'),
}


def categorize_bash_command(command: str) -> str:
    """Categorize a bash command string into a high-level group."""
    cmd = command.strip()
    # Handle piped commands — categorize by the first command
    base_cmd = cmd.split("|")[0].strip()
    # Handle sudo prefix
    if base_cmd.startswith("sudo "):
        base_cmd = base_cmd[5:].strip()
    # Handle env vars like FOO=bar command
    while "=" in base_cmd.split()[0] if base_cmd.split() else False:
        base_cmd = " ".join(base_cmd.split()[1:])

    # Check if the piped chain contains grep/rg (search pattern)
    if "|" in cmd:
        pipe_parts = cmd.split("|")
        for part in pipe_parts[1:]:
            part_base = part.strip().split()[0] if part.strip().split() else ""
            if part_base in ("grep", "rg", "awk", "sed"):
                # If the first command is also search-like, categorize as Search
                pass

    for category, pattern in BASH_CATEGORIES.items():
        if pattern.search(base_cmd):
            return category

    return "Other"


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
    """Extract slug, model, timestamps, token usage, and rich metadata."""
    slug = None
    model = None
    first_ts = None
    last_ts = None
    total_input_tokens = 0
    total_output_tokens = 0
    cache_creation_tokens = 0
    cache_read_tokens = 0
    active_duration_ms = 0
    permission_mode = None
    tool_errors = 0
    tool_successes = 0
    thinking_level = None
    models_used: set = set()

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

        obj_type = obj.get("type")

        # Active duration from turn_duration system entries
        if obj_type == "system" and obj.get("subtype") == "turn_duration":
            active_duration_ms += obj.get("durationMs", 0)

        # Permission mode from user entries (keep last seen)
        if obj.get("permissionMode"):
            permission_mode = obj["permissionMode"]

        # Thinking level from user entries (keep last seen)
        thinking_meta = obj.get("thinkingMetadata")
        if thinking_meta and "level" in thinking_meta:
            thinking_level = thinking_meta["level"]

        # Model, usage, and cache tokens from assistant messages
        msg = obj.get("message") or {}

        if msg.get("model"):
            models_used.add(msg["model"])
            if not model:
                model = msg["model"]

        usage = msg.get("usage")
        if usage:
            total_input_tokens += usage.get("input_tokens", 0)
            total_output_tokens += usage.get("output_tokens", 0)
            cache_creation_tokens += usage.get("cache_creation_input_tokens", 0)
            cache_read_tokens += usage.get("cache_read_input_tokens", 0)

        # Tool errors and successes from tool_result content blocks
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    if block.get("is_error"):
                        tool_errors += 1
                    else:
                        tool_successes += 1

    return {
        "slug": slug,
        "model": model,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "cache_creation_tokens": cache_creation_tokens,
        "cache_read_tokens": cache_read_tokens,
        "active_duration_ms": active_duration_ms,
        "permission_mode": permission_mode,
        "tool_errors": tool_errors,
        "tool_successes": tool_successes,
        "thinking_level": thinking_level,
        "models_used": sorted(models_used),
    }


def extract_active_duration(jsonl_path: Path) -> int:
    """Extract total active duration (ms) from turn_duration entries."""
    total = 0
    for _lineno, obj in iter_jsonl(jsonl_path):
        if obj is None:
            continue
        if obj.get("type") == "system" and obj.get("subtype") == "turn_duration":
            total += obj.get("durationMs", 0)
    return total


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


def _estimate_cost(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    model: Optional[str],
) -> float:
    """Estimate cost in USD based on token counts and model pricing.

    Rates per million tokens (approximate):
      opus:   $15 input, $75 output
      sonnet: $3 input, $15 output
      haiku:  $0.80 input, $4 output
    Cache reads charged at 10% of input price.
    """
    if not model:
        model = ""
    m = model.lower()
    if "opus" in m:
        input_rate, output_rate = 15.0, 75.0
    elif "haiku" in m:
        input_rate, output_rate = 0.80, 4.0
    else:
        # Default to sonnet pricing
        input_rate, output_rate = 3.0, 15.0

    cache_read_rate = input_rate * 0.10

    cost = (
        input_tokens * input_rate
        + output_tokens * output_rate
        + cache_read_tokens * cache_read_rate
    ) / 1_000_000

    return round(cost, 4)


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
    user_turns = extract_user_turns(jsonl_path)
    interrupt_count = sum(1 for t in user_turns if t["is_interrupt"])

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
    bash_category_counter: Counter = Counter()
    for cmd, cnt in bash_cmds.most_common(50):
        base = cmd.split()[0] if cmd.split() else cmd
        category = categorize_bash_command(cmd)
        bash_category_counter[category] += cnt
        bash_commands_list.append({
            "command": cmd[:200],
            "base": base,
            "count": cnt,
            "category": category,
        })
    bash_category_summary = dict(bash_category_counter.most_common())

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

    # Calculate total active duration (parent + subagents)
    subagent_active_ms = sum(sa.get("active_duration_ms", 0) for sa in subagents)
    total_active_duration_ms = meta["active_duration_ms"] + subagent_active_ms

    # Cost estimate
    cost_estimate = _estimate_cost(
        meta["total_input_tokens"],
        meta["total_output_tokens"],
        meta["cache_read_tokens"],
        meta["model"],
    )

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
        "bash_category_summary": bash_category_summary,
        "tool_calls": tool_calls,
        "user_turns": user_turns,
        "interrupt_count": interrupt_count,
        "tokens": {
            "input": meta["total_input_tokens"],
            "output": meta["total_output_tokens"],
            "cache_creation": meta["cache_creation_tokens"],
            "cache_read": meta["cache_read_tokens"],
        },
        "active_duration_ms": meta["active_duration_ms"],
        "total_active_duration_ms": total_active_duration_ms,
        "permission_mode": meta["permission_mode"],
        "tool_errors": meta["tool_errors"],
        "tool_successes": meta["tool_successes"],
        "thinking_level": meta["thinking_level"],
        "models_used": meta["models_used"],
        "cost_estimate": cost_estimate,
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

    # Active duration from subagent's own turn_duration entries
    active_duration_ms = extract_active_duration(sa_path)

    return {
        "agent_id": agent_id,
        "subagent_type": subagent_type,
        "task_description": task_description,
        "description": description,
        "tool_count": len(invocations),
        "tool_counts": dict(tool_counter.most_common()),
        "tool_calls": build_tool_calls_list(invocations, is_subagent=True),
        "active_duration_ms": active_duration_ms,
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
