"""Pattern extraction and analysis for tool invocations."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from tool_adapters.base import ToolAdapter, ToolInvocation


@dataclass
class PatternStats:
    """Statistics for a tool's usage patterns."""
    tool_name: str
    total_count: int
    level1_patterns: Counter  # Most general patterns
    level2_patterns: Counter  # Mid-level patterns
    level3_patterns: Counter  # Most specific patterns
    primary_values: Counter   # Raw primary values (commands, paths, etc.)


def extract_patterns(invocations: list[ToolInvocation], adapter: ToolAdapter) -> PatternStats:
    """
    Extract 3-level pattern hierarchy from invocations using tool-specific adapter.

    Args:
        invocations: List of tool invocations for a single tool type
        adapter: Tool adapter for pattern extraction

    Returns:
        PatternStats with pattern counters
    """
    if not invocations:
        return PatternStats(
            tool_name="",
            total_count=0,
            level1_patterns=Counter(),
            level2_patterns=Counter(),
            level3_patterns=Counter(),
            primary_values=Counter(),
        )

    tool_name = invocations[0].tool_name
    level1 = Counter()
    level2 = Counter()
    level3 = Counter()
    primary = Counter()

    for inv in invocations:
        # Get primary value for direct counting
        pv = adapter.get_primary_value(inv)
        if pv:
            primary[pv] += 1

        # Get 3-level patterns
        l1, l2, l3 = adapter.get_pattern_levels(inv)
        if l1:
            level1[l1] += 1
        if l2:
            level2[l2] += 1
        if l3:
            level3[l3] += 1

    return PatternStats(
        tool_name=tool_name,
        total_count=len(invocations),
        level1_patterns=level1,
        level2_patterns=level2,
        level3_patterns=level3,
        primary_values=primary,
    )


def format_pattern_section(
    stats: PatternStats,
    level: int,
    top_n: int = 30,
    min_count: int = 3
) -> list[str]:
    """
    Format a pattern level section for summary output.

    Args:
        stats: Pattern statistics
        level: Which level to format (1, 2, or 3)
        top_n: Show top N patterns
        min_count: Minimum count to include

    Returns:
        List of formatted lines
    """
    if level == 1:
        patterns = stats.level1_patterns
        title = "Level 1 patterns (most general)"
    elif level == 2:
        patterns = stats.level2_patterns
        title = "Level 2 patterns (mid-level)"
    elif level == 3:
        patterns = stats.level3_patterns
        title = "Level 3 patterns (most specific)"
    else:
        return []

    lines = [f"\n{title}:"]

    # Filter and sort
    filtered = [(count, pattern) for pattern, count in patterns.items() if count >= min_count]
    filtered.sort(reverse=True)

    if not filtered:
        lines.append("  (no patterns with count >= {})".format(min_count))
        return lines

    # Format top N
    for count, pattern in filtered[:top_n]:
        lines.append(f"  {count:4d}  {pattern}")

    if len(filtered) > top_n:
        remaining = len(filtered) - top_n
        total_remaining = sum(count for count, _ in filtered[top_n:])
        lines.append(f"  ... {remaining} more patterns ({total_remaining} total occurrences)")

    return lines
