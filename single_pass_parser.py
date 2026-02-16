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
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def parse_session_single_pass(
    jsonl_path: Path,
    project: str,
    adapters: Dict,
    options: ExtractionOptions,
    max_file_size_mb: int = MAX_FILE_SIZE_MB,
) -> Optional[Dict]:
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

    # Accumulators for all data we extract in one pass
    invocations: List[ToolInvocation] = []

    # Metadata accumulators (from extract_session_metadata)
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

    # First prompt (from extract_first_prompt)
    first_prompt = None
    first_prompt_found = False

    # User turns (from extract_user_turns + count_turns)
    user_turns: List[Dict[str, Any]] = []
    turn_number = 0

    # Subagent info (from extract_subagent_info)
    task_calls: Dict[str, Dict[str, str]] = {}
    agent_mapping: Dict[str, str] = {}

    # --- Single pass over the file ---
    for lineno, obj in iter_jsonl(jsonl_path):
        if obj is None:
            continue

        # --- Slug (can appear on any record) ---
        if not slug and obj.get("slug"):
            slug = obj["slug"]

        # --- Timestamps ---
        ts = obj.get("timestamp")
        if ts:
            if first_ts is None:
                first_ts = ts
            last_ts = ts

        obj_type = obj.get("type")

        # --- Active duration from turn_duration entries ---
        if obj_type == "system" and obj.get("subtype") == "turn_duration":
            active_duration_ms += obj.get("durationMs", 0)

        # --- Permission mode ---
        if obj.get("permissionMode"):
            permission_mode = obj["permissionMode"]

        # --- Thinking level ---
        thinking_meta = obj.get("thinkingMetadata")
        if thinking_meta and "level" in thinking_meta:
            thinking_level = thinking_meta["level"]

        # --- Subagent progress records ---
        if obj_type == "progress":
            data = obj.get("data", {})
            agent_id = data.get("agentId")
            parent_tool_use_id = obj.get("parentToolUseID")
            if agent_id and parent_tool_use_id and parent_tool_use_id not in agent_mapping:
                agent_mapping[parent_tool_use_id] = agent_id

        # --- Message-level processing ---
        msg = obj.get("message") or {}
        role = msg.get("role")

        # --- Model and token usage (from assistant messages) ---
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

        content = msg.get("content")

        # --- User message processing (turns, first prompt) ---
        if role == "user":
            text = _extract_text_from_content(content)
            if text:
                stripped = text.strip()
                # Skip system/command messages
                if not (
                    stripped.startswith("<local-command")
                    or stripped.startswith("<command-")
                    or len(stripped) < 3
                ):
                    turn_number += 1
                    is_interrupt = _is_interrupt_message(stripped)

                    # First prompt extraction
                    if not first_prompt_found and not is_interrupt:
                        cleaned = re.sub(
                            r'^(<[^>]+>[\s\S]*?</[^>]+>\s*)+', '', stripped
                        ).strip()
                        if cleaned and len(cleaned) > 3:
                            first_prompt = cleaned
                            first_prompt_found = True
                        elif len(stripped) > 3:
                            first_prompt = stripped
                            first_prompt_found = True

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

                    user_turns.append({
                        "text": display_text,
                        "timestamp": ts,
                        "is_interrupt": is_interrupt,
                        "turn_number": turn_number,
                    })

        # --- Content block processing (tool_use, tool_result) ---
        if isinstance(content, list):
            # Base metadata for tool extraction
            base_metadata = {
                "timestamp": obj.get("timestamp"),
                "project": project,
                "jsonl_path": str(jsonl_path),
                "lineno": lineno,
                "cwd": obj.get("cwd"),
                "session_id": obj.get("sessionId"),
                "git_branch": obj.get("gitBranch"),
            }

            for block in content:
                if not isinstance(block, dict):
                    continue

                block_type = block.get("type")

                # Tool invocations
                if block_type == "tool_use":
                    tool_name = block.get("name")
                    if not tool_name:
                        continue

                    # Track Task tool calls for subagent mapping
                    if tool_name == "Task":
                        tool_use_id = block.get("id", "")
                        inp = block.get("input", {})
                        task_calls[tool_use_id] = {
                            "subagent_type": inp.get("subagent_type", ""),
                            "description": inp.get("description", ""),
                        }

                    # Extract via adapter
                    adapter = get_adapter(tool_name, adapters)
                    try:
                        invocation = adapter.extract(block, base_metadata, options)
                        invocations.append(invocation)
                    except Exception:
                        continue

                # Tool results (for error/success counts)
                elif block_type == "tool_result":
                    if block.get("is_error"):
                        tool_errors += 1
                    else:
                        tool_successes += 1

    # --- Post-processing ---

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
            files_touched[fpath][inv.tool_name] = (
                files_touched[fpath].get(inv.tool_name, 0) + 1
            )

    # Bash commands aggregation
    bash_cmds: Counter = Counter()
    for inv in invocations:
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

    # Tool calls chronological list
    tool_calls = build_tool_calls_list(invocations)

    # Prompt preview
    prompt_preview = None
    if first_prompt:
        prompt_preview = (
            first_prompt[:80] + "..." if len(first_prompt) > 80 else first_prompt
        )

    # Build subagent info mapping
    subagent_info: Dict[str, Dict[str, str]] = {}
    for tool_use_id, info in task_calls.items():
        agent_id = agent_mapping.get(tool_use_id)
        if agent_id:
            subagent_info[agent_id] = info

    # Process subagents (these are separate files, still multi-pass but small)
    subagents = []
    subagent_files = find_subagent_files(jsonl_path)
    for sa_path in subagent_files:
        sa_data = _build_subagent_data_fast(
            sa_path, project, adapters, options, subagent_info
        )
        if sa_data:
            subagents.append(sa_data)

    # Total active duration (parent + subagents)
    subagent_active_ms = sum(sa.get("active_duration_ms", 0) for sa in subagents)
    total_active_duration_ms = active_duration_ms + subagent_active_ms

    # Cost estimate
    cost_estimate = _estimate_cost(
        total_input_tokens, total_output_tokens, cache_read_tokens, model
    )

    return {
        "session_id": session_id,
        "slug": slug,
        "project": project,
        "first_prompt": first_prompt,
        "prompt_preview": prompt_preview,
        "turn_count": turn_number,
        "start_time": first_ts,
        "end_time": last_ts,
        "model": model,
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
            "input": total_input_tokens,
            "output": total_output_tokens,
            "cache_creation": cache_creation_tokens,
            "cache_read": cache_read_tokens,
        },
        "active_duration_ms": active_duration_ms,
        "total_active_duration_ms": total_active_duration_ms,
        "permission_mode": permission_mode,
        "tool_errors": tool_errors,
        "tool_successes": tool_successes,
        "thinking_level": thinking_level,
        "models_used": sorted(models_used),
        "cost_estimate": cost_estimate,
        "subagents": subagents,
    }


def _build_subagent_data_fast(
    sa_path: Path,
    project: str,
    adapters: Dict,
    options: ExtractionOptions,
    subagent_info: Dict[str, Dict[str, str]],
) -> Optional[Dict]:
    """Build subagent data. Subagent files are small, so two passes is fine."""
    invocations: List[ToolInvocation] = []
    description = None
    active_duration_ms = 0

    for lineno, obj in iter_jsonl(sa_path):
        if obj is None:
            continue

        # Active duration
        if obj.get("type") == "system" and obj.get("subtype") == "turn_duration":
            active_duration_ms += obj.get("durationMs", 0)

        msg = obj.get("message") or {}
        content = msg.get("content")

        # First prompt for description
        if description is None and msg.get("role") == "user":
            text = _extract_text_from_content(content)
            if text:
                stripped = text.strip()
                if (
                    not stripped.startswith("<local-command")
                    and not stripped.startswith("<command-")
                    and len(stripped) > 3
                    and not _is_interrupt_message(stripped)
                ):
                    cleaned = re.sub(
                        r'^(<[^>]+>[\s\S]*?</[^>]+>\s*)+', '', stripped
                    ).strip()
                    description = cleaned if cleaned and len(cleaned) > 3 else stripped

        # Tool invocations
        if isinstance(content, list):
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

    if not invocations:
        return None

    agent_id = sa_path.stem.replace("agent-", "")
    info = subagent_info.get(agent_id, {})
    subagent_type = info.get("subagent_type", "")
    task_description = info.get("description", "")

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
        "active_duration_ms": active_duration_ms,
    }
