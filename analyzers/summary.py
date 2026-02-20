"""Summary generation for tool usage analysis."""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

from tool_adapters.base import ToolInvocation
from .patterns import PatternStats, format_pattern_section
from .permissions import PermissionInsights


def generate_summary(
    invocations: list[ToolInvocation],
    patterns_by_tool: dict[str, PatternStats],
    insights: PermissionInsights,
    top_n: int = 30
) -> str:
    """
    Generate comprehensive summary text.

    Args:
        invocations: All tool invocations
        patterns_by_tool: Pattern statistics by tool type
        insights: Permission analysis insights
        top_n: Number of top items to show in each section

    Returns:
        Formatted summary text
    """
    lines = []

    # Header
    lines.extend(_generate_header(invocations, insights))

    # Overall distribution
    lines.extend(_generate_distribution(invocations, insights, top_n))

    # Tool-specific sections
    if "Bash" in patterns_by_tool:
        lines.extend(_generate_bash_section(patterns_by_tool["Bash"], insights, top_n))

    # File operations section
    file_tools = ["Read", "Write", "Edit"]
    file_patterns = {name: patterns_by_tool[name] for name in file_tools if name in patterns_by_tool}
    if file_patterns:
        lines.extend(_generate_file_ops_section(file_patterns, insights, top_n))

    # Search section
    search_tools = ["Grep", "Glob"]
    search_patterns = {name: patterns_by_tool[name] for name in search_tools if name in patterns_by_tool}
    if search_patterns:
        lines.extend(_generate_search_section(search_patterns, insights, top_n))

    # Task tools section
    task_tools = ["TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "TaskOutput", "TodoWrite"]
    task_patterns = {name: patterns_by_tool[name] for name in task_tools if name in patterns_by_tool}
    if task_patterns:
        lines.extend(_generate_task_section(task_patterns, insights, top_n))

    # Permission insights
    lines.extend(_generate_permission_section(insights, top_n))

    return "\n".join(lines)


def _generate_header(invocations: list[ToolInvocation], insights: PermissionInsights) -> list[str]:
    """Generate summary header."""
    # Count unique projects
    projects = set(inv.project for inv in invocations)
    unique_tools = len(insights.tool_counts)

    # Time range
    timestamps = [inv.timestamp for inv in invocations if inv.timestamp]
    if timestamps:
        timestamps.sort()
        time_range = f"{timestamps[0]} to {timestamps[-1]}"
    else:
        time_range = "Unknown"

    return [
        "=" * 70,
        "CLAUDE CODE TOOL USAGE ANALYSIS",
        "=" * 70,
        "",
        f"Total tool invocations: {len(invocations):,}",
        f"Unique tool types: {unique_tools}",
        f"Projects analyzed: {len(projects)}",
        f"Time range: {time_range}",
        "",
    ]


def _generate_distribution(invocations: list[ToolInvocation], insights: PermissionInsights, top_n: int) -> list[str]:
    """Generate overall distribution section."""
    lines = [
        "=" * 70,
        "TOOL USAGE DISTRIBUTION",
        "=" * 70,
        "",
        "By tool type:",
    ]

    # Sort by count descending
    sorted_tools = insights.tool_counts.most_common(top_n)
    total = sum(insights.tool_counts.values())

    for tool, count in sorted_tools:
        pct = (count / total * 100) if total > 0 else 0
        lines.append(f"  {count:5d} ({pct:5.1f}%)  {tool}")

    # Count by project
    project_counts = Counter(inv.project for inv in invocations)
    lines.extend([
        "",
        "By project:",
    ])

    for project, count in project_counts.most_common(top_n):
        lines.append(f"  {count:5d}  {project}")

    lines.append("")
    return lines


def _generate_bash_section(stats: PatternStats, insights: PermissionInsights, top_n: int) -> list[str]:
    """Generate Bash tool analysis section."""
    lines = [
        "=" * 70,
        "BASH TOOL ANALYSIS",
        "=" * 70,
        "",
        f"Total Bash commands: {stats.total_count:,}",
        "",
    ]

    # Base commands (level 1)
    lines.append("Base commands (count >= 3):")
    filtered = [(count, pattern) for pattern, count in stats.level1_patterns.items() if count >= 3]
    filtered.sort(reverse=True)
    for count, pattern in filtered[:top_n]:
        lines.append(f"  {count:5d}  {pattern}")

    if len(filtered) > top_n:
        lines.append(f"  ... {len(filtered) - top_n} more")

    # Command patterns - 2 words (level 2)
    lines.append("")
    lines.append("Command patterns - 2 words (count >= 3):")
    filtered = [(count, pattern) for pattern, count in stats.level2_patterns.items() if count >= 3]
    filtered.sort(reverse=True)
    for count, pattern in filtered[:top_n]:
        lines.append(f"  {count:5d}  {pattern}")

    if len(filtered) > top_n:
        lines.append(f"  ... {len(filtered) - top_n} more")

    # Command patterns - 3 words (level 3)
    lines.append("")
    lines.append("Command patterns - 3 words (count >= 3):")
    filtered = [(count, pattern) for pattern, count in stats.level3_patterns.items() if count >= 3]
    filtered.sort(reverse=True)
    for count, pattern in filtered[:top_n]:
        lines.append(f"  {count:5d}  {pattern}")

    if len(filtered) > top_n:
        lines.append(f"  ... {len(filtered) - top_n} more")

    lines.append("")
    return lines


def _generate_file_ops_section(patterns: dict[str, PatternStats], insights: PermissionInsights, top_n: int) -> list[str]:
    """Generate file operations analysis section."""
    total_ops = sum(p.total_count for p in patterns.values())

    lines = [
        "=" * 70,
        "FILE OPERATIONS ANALYSIS (Read/Write/Edit)",
        "=" * 70,
        "",
        f"Total file operations: {total_ops:,}",
    ]

    # Breakdown by operation type
    for name, stats in patterns.items():
        pct = (stats.total_count / total_ops * 100) if total_ops > 0 else 0
        lines.append(f"  {name}:  {stats.total_count:5d} ({pct:5.1f}%)")

    lines.append("")

    # Most accessed paths (combine all file ops)
    all_paths = Counter()
    for stats in patterns.values():
        all_paths.update(stats.primary_values)

    lines.append(f"Most accessed paths (top {top_n}):")
    for path, count in all_paths.most_common(top_n):
        lines.append(f"  {count:5d}  {path}")

    # File extensions
    lines.append("")
    lines.append(f"Top file extensions (top {top_n}):")
    for ext, count in insights.file_extensions.most_common(top_n):
        lines.append(f"  {count:5d}  {ext}")

    # Directory access patterns
    lines.append("")
    lines.append(f"Directory access patterns (top {top_n}):")
    for dir_path, count in insights.directory_access.most_common(top_n):
        lines.append(f"  {count:5d}  {dir_path}")

    lines.append("")
    return lines


def _generate_search_section(patterns: dict[str, PatternStats], insights: PermissionInsights, top_n: int) -> list[str]:
    """Generate search tools analysis section."""
    total_searches = sum(p.total_count for p in patterns.values())

    lines = [
        "=" * 70,
        "GREP/GLOB SEARCH ANALYSIS",
        "=" * 70,
        "",
        f"Total searches: {total_searches:,}",
    ]

    for name, stats in patterns.items():
        pct = (stats.total_count / total_searches * 100) if total_searches > 0 else 0
        lines.append(f"  {name}:  {stats.total_count:5d} ({pct:5.1f}%)")

    lines.append("")

    # Grep output modes (if Grep exists)
    if "Grep" in patterns:
        grep_stats = patterns["Grep"]
        output_modes = Counter()
        for pattern in grep_stats.level1_patterns:
            output_modes[pattern] += grep_stats.level1_patterns[pattern]

        if output_modes:
            lines.append("Grep output modes:")
            for mode, count in output_modes.most_common():
                lines.append(f"  {count:5d}  {mode}")
            lines.append("")

    # Most searched patterns (Grep)
    if "Grep" in patterns:
        grep_stats = patterns["Grep"]
        lines.append(f"Most used Grep patterns (top {min(15, top_n)}):")
        for pattern, count in grep_stats.primary_values.most_common(15):
            # Truncate long patterns
            display_pattern = pattern[:60] + "..." if len(pattern) > 60 else pattern
            lines.append(f"  {count:5d}  {display_pattern}")
        lines.append("")

    # Most used Glob patterns
    if "Glob" in patterns:
        glob_stats = patterns["Glob"]
        lines.append(f"Most used Glob patterns (top {min(15, top_n)}):")
        for pattern, count in glob_stats.primary_values.most_common(15):
            lines.append(f"  {count:5d}  {pattern}")
        lines.append("")

    lines.append("")
    return lines


def _generate_task_section(patterns: dict[str, PatternStats], insights: PermissionInsights, top_n: int) -> list[str]:
    """Generate task tools analysis section."""
    total_tasks = sum(p.total_count for p in patterns.values())

    lines = [
        "=" * 70,
        "TASK TOOL USAGE",
        "=" * 70,
        "",
        f"Total task operations: {total_tasks:,}",
    ]

    for name, stats in patterns.items():
        lines.append(f"  {name}:  {stats.total_count:5d}")

    lines.append("")
    return lines


def _generate_permission_section(insights: PermissionInsights, top_n: int) -> list[str]:
    """Generate permission insights and recommendations section."""
    lines = [
        "=" * 70,
        "PERMISSION INSIGHTS & RECOMMENDATIONS",
        "=" * 70,
        "",
    ]

    _perm_high_risk_ops(insights, lines)
    _perm_sensitive_and_external(insights, lines)
    _perm_recommendations(insights, lines)
    _perm_flagged_summary(insights, lines)

    lines.append("")
    return lines


def _perm_high_risk_ops(insights: PermissionInsights, lines: list[str]) -> None:
    """Append high-risk operation details to lines."""
    if insights.high_privilege_count > 0:
        pct = insights.high_privilege_count / insights.total_operations * 100
        lines.append("High-privilege operations detected:")
        lines.append(f"  {insights.high_privilege_count:5d}  sudo commands ({pct:.1f}% of all operations)")

        if insights.sudo_commands:
            lines.append("")
            lines.append("  Top sudo operations:")
            for cmd, count in insights.sudo_commands[:10]:
                lines.append(f"    {count:5d}  sudo {cmd}")

    if insights.rm_operations:
        lines.append("")
        rm_count = sum(count for _, count in insights.rm_operations)
        lines.append(f"  {rm_count:5d}  rm operations ({rm_count / insights.total_operations * 100:.1f}%)")

    if insights.chmod_operations:
        lines.append("")
        chmod_count = sum(count for _, count in insights.chmod_operations)
        lines.append(f"  {chmod_count:5d}  chmod operations ({chmod_count / insights.total_operations * 100:.1f}%)")


def _perm_sensitive_and_external(insights: PermissionInsights, lines: list[str]) -> None:
    """Append sensitive file access and external access sections."""
    lines.append("")
    lines.append("Sensitive file access:")
    if insights.sensitive_file_access > 0:
        lines.append(f"  {insights.sensitive_file_access:5d}  operations on sensitive files")
        if insights.sensitive_paths:
            lines.append("")
            lines.append("  Sensitive paths accessed:")
            for path, count in insights.sensitive_paths[:10]:
                lines.append(f"    {count:5d}  {path}")
    else:
        lines.append("  None detected (✓ safe)")

    lines.append("")
    lines.append("External access:")
    if insights.external_access_count > 0:
        lines.append(f"  {insights.external_access_count:5d}  WebSearch/WebFetch queries")

    curl_count = getattr(insights, '_curl_count', 0)
    if curl_count > 0:
        lines.append(f"  {curl_count:5d}  curl commands (HTTP requests)")

    if insights.external_access_count == 0 and curl_count == 0:
        lines.append("  None detected")


def _perm_recommendations(insights: PermissionInsights, lines: list[str]) -> None:
    """Append allow/ask/deny recommendation sections."""
    lines.extend(["", "-" * 70, "SUGGESTED ALLOW RULES (high-frequency, low-risk):", "-" * 70])
    if insights.suggested_allow:
        for pattern, reason, count in insights.suggested_allow:
            lines.extend([f"  ✓ {pattern}", f"    {reason} ({count:,} occurrences)", ""])
    else:
        lines.extend(["  (no high-frequency patterns detected)", ""])

    lines.extend(["-" * 70, "SUGGESTED ASK RULES (moderate-risk or infrequent):", "-" * 70])
    if insights.suggested_ask:
        for pattern, reason, count in insights.suggested_ask:
            lines.extend([f"  ? {pattern}", f"    {reason} ({count:,} occurrences)", ""])
    else:
        lines.extend(["  (no moderate-risk patterns detected)", ""])

    lines.extend(["-" * 70, "SUGGESTED DENY RULES (high-risk - preventive):", "-" * 70])
    for pattern, reason in insights.suggested_deny:
        lines.extend([f"  ✗ {pattern}", f"    {reason}", ""])


def _perm_flagged_summary(insights: PermissionInsights, lines: list[str]) -> None:
    """Append flagged operations summary."""
    lines.extend(["-" * 70, "FLAGGED OPERATIONS (review recommended):", "-" * 70])

    flagged = []
    if insights.high_privilege_count > 0:
        pct = insights.high_privilege_count / insights.total_operations * 100
        flagged.append(f"  ⚠ {insights.high_privilege_count} sudo commands ({pct:.1f}% of operations)")
    if insights.rm_operations:
        rm_total = sum(count for _, count in insights.rm_operations)
        flagged.append(f"  ⚠ {rm_total} file deletion operations (rm commands)")
    if insights.chmod_operations:
        chmod_total = sum(count for _, count in insights.chmod_operations)
        flagged.append(f"  ⚠ {chmod_total} permission changes (chmod commands)")
    if insights.sensitive_file_access > 0:
        flagged.append(f"  ⚠ {insights.sensitive_file_access} sensitive file accesses")

    if flagged:
        lines.extend(flagged)
    else:
        lines.append("  ✓ No high-risk operations detected")


def write_summary(
    invocations: list[ToolInvocation],
    patterns_by_tool: dict[str, PatternStats],
    insights: PermissionInsights,
    output_path: Path,
    top_n: int = 30
):
    """
    Generate and write summary to file.

    Args:
        invocations: All tool invocations
        patterns_by_tool: Pattern statistics by tool type
        insights: Permission analysis insights
        output_path: Path to write summary
        top_n: Number of top items to show
    """
    summary = generate_summary(invocations, patterns_by_tool, insights, top_n)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(summary)

    print(f"Summary written to: {output_path}")
