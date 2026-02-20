"""
Single-pass JSONL session parser for the Claude Activity Dashboard.

Merges the 5-7 separate file passes from session_parser.py into a single
iter_jsonl() loop per file. Extracts tools, metadata, first prompt, turns,
subagent info, and timing all at once.

Used exclusively by app.py for dashboard builds. The original session_parser.py
remains unchanged for CLI scripts.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from extract_tool_usage import iter_jsonl, derive_project_name
from session_parser import (
    _extract_text_from_content,
    _is_interrupt_message,
    _get_tool_detail,
    _get_file_path,
    _estimate_cost,
    build_tool_calls_list,
    categorize_bash_command,
    find_subagent_files,
    extract_active_duration,
    make_project_readable,
)
from tool_adapters import (
    create_adapter_registry,
    get_adapter,
    ExtractionOptions,
    ToolInvocation,
)

# Maximum file size to parse (skip outliers to avoid memory issues on Pi)
MAX_FILE_SIZE_MB = 100


# ---------------------------------------------------------------------------
# Session state accumulator
# ---------------------------------------------------------------------------
@dataclass
class _SessionState:
    """Mutable accumulator holding all data collected during the single pass."""

    project: str
    jsonl_path: Path
    adapters: Dict
    options: ExtractionOptions

    # Tool invocations
    invocations: list[ToolInvocation] = field(default_factory=list)

    # Metadata
    slug: str | None = None
    model: str | None = None
    first_ts: str | None = None
    last_ts: str | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    active_duration_ms: int = 0
    permission_mode: str | None = None
    tool_errors: int = 0
    tool_successes: int = 0
    thinking_level: str | None = None
    models_used: set = field(default_factory=set)

    # First prompt
    first_prompt: str | None = None
    first_prompt_found: bool = False

    # User turns
    user_turns: list[dict[str, Any]] = field(default_factory=list)
    turn_number: int = 0

    # Subagent info
    task_calls: dict[str, dict[str, str]] = field(default_factory=dict)
    agent_mapping: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Phase functions
# ---------------------------------------------------------------------------
def _process_message(obj: dict, lineno: int, state: _SessionState) -> None:
    """Process a single JSONL record, updating state in place."""
    # Slug
    if not state.slug and obj.get("slug"):
        state.slug = obj["slug"]

    # Timestamps
    ts = obj.get("timestamp")
    if ts:
        if state.first_ts is None:
            state.first_ts = ts
        state.last_ts = ts

    obj_type = obj.get("type")

    # Active duration
    if obj_type == "system" and obj.get("subtype") == "turn_duration":
        state.active_duration_ms += obj.get("durationMs", 0)

    # Permission mode
    if obj.get("permissionMode"):
        state.permission_mode = obj["permissionMode"]

    # Thinking level
    thinking_meta = obj.get("thinkingMetadata")
    if thinking_meta and "level" in thinking_meta:
        state.thinking_level = thinking_meta["level"]

    # Subagent progress records
    if obj_type == "progress":
        data = obj.get("data", {})
        agent_id = data.get("agentId")
        parent_id = obj.get("parentToolUseID")
        if agent_id and parent_id and parent_id not in state.agent_mapping:
            state.agent_mapping[parent_id] = agent_id

    # Message-level processing
    msg = obj.get("message") or {}
    role = msg.get("role")

    # Model and token usage
    if msg.get("model"):
        state.models_used.add(msg["model"])
        if not state.model:
            state.model = msg["model"]

    usage = msg.get("usage")
    if usage:
        state.total_input_tokens += usage.get("input_tokens", 0)
        state.total_output_tokens += usage.get("output_tokens", 0)
        state.cache_creation_tokens += usage.get("cache_creation_input_tokens", 0)
        state.cache_read_tokens += usage.get("cache_read_input_tokens", 0)

    content = msg.get("content")

    # User message processing
    if role == "user":
        _process_user_message(content, ts, state)

    # Content block processing (tool_use, tool_result)
    if isinstance(content, list):
        _extract_tool_invocations(obj, content, lineno, state)


def _process_user_message(
    content: Any, ts: str | None, state: _SessionState
) -> None:
    """Handle a user message — extract turns and first prompt."""
    text = _extract_text_from_content(content)
    if not text:
        return

    stripped = text.strip()
    if (
        stripped.startswith("<local-command")
        or stripped.startswith("<command-")
        or len(stripped) < 3
    ):
        return

    state.turn_number += 1
    is_interrupt = _is_interrupt_message(stripped)

    # First prompt extraction
    if not state.first_prompt_found and not is_interrupt:
        cleaned = re.sub(
            r'^(<[^>]+>[\s\S]*?</[^>]+>\s*)+', '', stripped
        ).strip()
        if cleaned and len(cleaned) > 3:
            state.first_prompt = cleaned
            state.first_prompt_found = True
        elif len(stripped) > 3:
            state.first_prompt = stripped
            state.first_prompt_found = True

    # User turn for conversation flow
    display_text = stripped
    if not is_interrupt:
        cleaned = re.sub(
            r'^(<[^>]+>[\s\S]*?</[^>]+>\s*)+', '', stripped
        ).strip()
        if cleaned and len(cleaned) > 3:
            display_text = cleaned
    if len(display_text) > 300:
        display_text = display_text[:300] + "..."

    state.user_turns.append({
        "text": display_text,
        "timestamp": ts,
        "is_interrupt": is_interrupt,
        "turn_number": state.turn_number,
    })


def _extract_tool_invocations(
    obj: dict, content: list, lineno: int, state: _SessionState
) -> None:
    """Pull tool_use and tool_result blocks from content, updating state."""
    base_metadata = {
        "timestamp": obj.get("timestamp"),
        "project": state.project,
        "jsonl_path": str(state.jsonl_path),
        "lineno": lineno,
        "cwd": obj.get("cwd"),
        "session_id": obj.get("sessionId"),
        "git_branch": obj.get("gitBranch"),
    }

    for block in content:
        if not isinstance(block, dict):
            continue

        block_type = block.get("type")

        if block_type == "tool_use":
            tool_name = block.get("name")
            if not tool_name:
                continue

            # Track Task calls for subagent mapping
            if tool_name == "Task":
                tool_use_id = block.get("id", "")
                inp = block.get("input", {})
                state.task_calls[tool_use_id] = {
                    "subagent_type": inp.get("subagent_type", ""),
                    "description": inp.get("description", ""),
                }

            adapter = get_adapter(tool_name, state.adapters)
            try:
                invocation = adapter.extract(block, base_metadata, state.options)
                state.invocations.append(invocation)
            except Exception:
                continue

        elif block_type == "tool_result":
            if block.get("is_error"):
                state.tool_errors += 1
            else:
                state.tool_successes += 1


def _build_session_result(state: _SessionState) -> dict | None:
    """Assemble the final session dict from accumulated state."""
    interrupt_count = sum(1 for t in state.user_turns if t["is_interrupt"])

    if not state.invocations and not state.first_prompt:
        return None

    session_id = state.jsonl_path.stem
    tool_counter = Counter(inv.tool_name for inv in state.invocations)

    # File extensions and files touched
    file_extensions: Counter = Counter()
    files_touched: dict[str, dict[str, int]] = {}
    for inv in state.invocations:
        fpath = _get_file_path(inv)
        if fpath:
            ext = Path(fpath).suffix or "(no ext)"
            file_extensions[ext] += 1
            if fpath not in files_touched:
                files_touched[fpath] = {}
            files_touched[fpath][inv.tool_name] = (
                files_touched[fpath].get(inv.tool_name, 0) + 1
            )

    # Bash commands aggregation
    bash_cmds: Counter = Counter()
    for inv in state.invocations:
        if inv.tool_name == "Bash" and inv.bash_command:
            bash_cmds[inv.bash_command.strip()] += 1

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

    tool_calls = build_tool_calls_list(state.invocations)

    prompt_preview = None
    if state.first_prompt:
        prompt_preview = (
            state.first_prompt[:80] + "..."
            if len(state.first_prompt) > 80
            else state.first_prompt
        )

    # Build subagent info mapping
    subagent_info: dict[str, dict[str, str]] = {}
    for tool_use_id, info in state.task_calls.items():
        agent_id = state.agent_mapping.get(tool_use_id)
        if agent_id:
            subagent_info[agent_id] = info

    # Process subagents
    subagents = _build_subagents(state, subagent_info)

    # Total active duration
    subagent_active_ms = sum(sa.get("active_duration_ms", 0) for sa in subagents)
    total_active_duration_ms = state.active_duration_ms + subagent_active_ms

    cost_estimate = _estimate_cost(
        state.total_input_tokens, state.total_output_tokens,
        state.cache_read_tokens, state.model,
        cache_creation_tokens=state.cache_creation_tokens,
    )

    return {
        "session_id": session_id,
        "slug": state.slug,
        "project": state.project,
        "first_prompt": state.first_prompt,
        "prompt_preview": prompt_preview,
        "turn_count": state.turn_number,
        "start_time": state.first_ts,
        "end_time": state.last_ts,
        "model": state.model,
        "total_tools": len(state.invocations),
        "tool_counts": dict(tool_counter.most_common()),
        "file_extensions": dict(file_extensions.most_common()),
        "files_touched": files_touched,
        "bash_commands": bash_commands_list,
        "bash_category_summary": bash_category_summary,
        "tool_calls": tool_calls,
        "user_turns": state.user_turns,
        "interrupt_count": interrupt_count,
        "tokens": {
            "input": state.total_input_tokens,
            "output": state.total_output_tokens,
            "cache_creation": state.cache_creation_tokens,
            "cache_read": state.cache_read_tokens,
        },
        "active_duration_ms": state.active_duration_ms,
        "total_active_duration_ms": total_active_duration_ms,
        "permission_mode": state.permission_mode,
        "tool_errors": state.tool_errors,
        "tool_successes": state.tool_successes,
        "thinking_level": state.thinking_level,
        "models_used": sorted(state.models_used),
        "cost_estimate": cost_estimate,
        "subagents": subagents,
    }


def _build_subagents(
    state: _SessionState, subagent_info: dict[str, dict[str, str]]
) -> list[dict]:
    """Find and parse subagent files for this session."""
    subagents = []
    subagent_files = find_subagent_files(state.jsonl_path)
    for sa_path in subagent_files:
        sa_data = _build_subagent_data_fast(
            sa_path, state.project, state.adapters, state.options, subagent_info
        )
        if sa_data:
            subagents.append(sa_data)
    return subagents


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def parse_session_single_pass(
    jsonl_path: Path,
    project: str,
    adapters: Dict,
    options: ExtractionOptions,
    max_file_size_mb: int = MAX_FILE_SIZE_MB,
) -> dict | None:
    """Parse a single JSONL session file in one pass.

    Extracts everything that build_session_data() does, but reads
    each line only once instead of 5-7 times.

    Returns the same dict shape as session_parser.build_session_data().
    Returns None for empty/skipped sessions.
    """
    # Skip oversized files
    try:
        file_size = jsonl_path.stat().st_size
        if file_size > max_file_size_mb * 1_048_576:
            return None
    except OSError:
        return None

    state = _SessionState(
        project=project,
        jsonl_path=jsonl_path,
        adapters=adapters,
        options=options,
    )

    for lineno, obj in iter_jsonl(jsonl_path):
        if obj is None:
            continue
        _process_message(obj, lineno, state)

    return _build_session_result(state)


# ---------------------------------------------------------------------------
# Subagent parsing
# ---------------------------------------------------------------------------
def _build_subagent_data_fast(
    sa_path: Path,
    project: str,
    adapters: Dict,
    options: ExtractionOptions,
    subagent_info: dict[str, dict[str, str]],
) -> dict | None:
    """Build subagent data from a subagent JSONL file."""
    invocations: list[ToolInvocation] = []
    description = None
    active_duration_ms = 0

    for lineno, obj in iter_jsonl(sa_path):
        if obj is None:
            continue

        if obj.get("type") == "system" and obj.get("subtype") == "turn_duration":
            active_duration_ms += obj.get("durationMs", 0)

        msg = obj.get("message") or {}
        content = msg.get("content")

        if description is None and msg.get("role") == "user":
            description = _extract_subagent_description(content)

        if isinstance(content, list):
            _collect_subagent_tools(
                obj, content, lineno, sa_path, project, adapters, options,
                invocations,
            )

    if not invocations:
        return None

    return _assemble_subagent_result(
        sa_path, invocations, description, active_duration_ms, subagent_info
    )


def _extract_subagent_description(content: Any) -> str | None:
    """Extract the first user prompt from subagent content as description."""
    text = _extract_text_from_content(content)
    if not text:
        return None

    stripped = text.strip()
    if (
        stripped.startswith("<local-command")
        or stripped.startswith("<command-")
        or len(stripped) <= 3
        or _is_interrupt_message(stripped)
    ):
        return None

    cleaned = re.sub(
        r'^(<[^>]+>[\s\S]*?</[^>]+>\s*)+', '', stripped
    ).strip()
    return cleaned if cleaned and len(cleaned) > 3 else stripped


def _collect_subagent_tools(
    obj: dict, content: list, lineno: int, sa_path: Path,
    project: str, adapters: Dict, options: ExtractionOptions,
    invocations: list[ToolInvocation],
) -> None:
    """Extract tool invocations from subagent content blocks."""
    base_metadata = {
        "timestamp": obj.get("timestamp"),
        "project": project,
        "jsonl_path": str(sa_path),
        "lineno": lineno,
        "cwd": obj.get("cwd"),
        "session_id": obj.get("sessionId"),
        "git_branch": obj.get("gitBranch"),
    }
    for block in content:
        if (
            isinstance(block, dict)
            and block.get("type") == "tool_use"
            and block.get("name")
        ):
            adapter = get_adapter(block["name"], adapters)
            try:
                invocation = adapter.extract(block, base_metadata, options)
                invocations.append(invocation)
            except Exception:
                continue


def _assemble_subagent_result(
    sa_path: Path,
    invocations: list[ToolInvocation],
    description: str | None,
    active_duration_ms: int,
    subagent_info: dict[str, dict[str, str]],
) -> Dict:
    """Assemble the subagent data dict from collected data."""
    agent_id = sa_path.stem.replace("agent-", "")
    info = subagent_info.get(agent_id, {})

    if description and len(description) > 200:
        description = description[:200] + "..."

    tool_counter = Counter(inv.tool_name for inv in invocations)

    return {
        "agent_id": agent_id,
        "subagent_type": info.get("subagent_type", ""),
        "task_description": info.get("description", ""),
        "description": description,
        "tool_count": len(invocations),
        "tool_counts": dict(tool_counter.most_common()),
        "tool_calls": build_tool_calls_list(invocations, is_subagent=True),
        "active_duration_ms": active_duration_ms,
    }
