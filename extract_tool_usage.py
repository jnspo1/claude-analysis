#!/usr/bin/env python3
"""
Extract all tool usage from Claude Code project JSONL logs.

Scans /home/pi/.claude/projects/**/*.jsonl files and extracts every tool
invocation (Bash, Read, Write, Edit, Grep, Glob, Task tools, etc.), producing:
  1. tool_events.csv - detailed CSV with all tool invocations and metadata
  2. tool_summary.txt - comprehensive summary with pattern analysis
  3. permissions_suggested.yaml - suggested permission rules

Usage:
    python extract_tool_usage.py [--root PATH] [--out-dir PATH] [--top N]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import yaml
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from collections.abc import Iterable
from typing import Any

# Import our adapters and analyzers
from tool_adapters import (
    create_adapter_registry,
    get_adapter,
    ExtractionOptions,
    ToolInvocation,
)
from analyzers import (
    extract_patterns,
    analyze_permissions,
    write_summary,
)


def iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any] | None]]:
    """
    Iterate over JSONL file line-by-line, yielding (lineno, parsed_object).

    Yields (lineno, None) for malformed JSON lines instead of crashing.
    """
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield lineno, json.loads(line)
            except json.JSONDecodeError:
                yield lineno, None


def extract_tools_from_file(
    jsonl_path: Path,
    project: str,
    adapters: dict[str, Any],
    options: ExtractionOptions
) -> tuple[list[ToolInvocation], int]:
    """
    Extract all tool invocations from a single JSONL file.

    Args:
        jsonl_path: Path to JSONL file
        project: Project identifier
        adapters: Adapter registry
        options: Extraction options

    Returns:
        (list of ToolInvocation objects, count of malformed JSON lines)
    """
    extracted: list[ToolInvocation] = []
    bad_lines = 0

    for lineno, obj in iter_jsonl(jsonl_path):
        if obj is None:
            bad_lines += 1
            continue

        # Extract message content
        msg = obj.get("message") or {}
        content = msg.get("content")

        if not isinstance(content, list):
            continue

        # Prepare base metadata (common to all tools)
        base_metadata = {
            "timestamp": obj.get("timestamp"),
            "project": project,
            "jsonl_path": str(jsonl_path),
            "lineno": lineno,
            "cwd": obj.get("cwd"),
            "session_id": obj.get("sessionId"),
            "git_branch": obj.get("gitBranch"),
        }

        # Scan for tool_use blocks
        for block in content:
            if not isinstance(block, dict):
                continue

            # Process any tool_use block
            if block.get("type") == "tool_use":
                tool_name = block.get("name")
                if not tool_name:
                    continue

                # Get appropriate adapter
                adapter = get_adapter(tool_name, adapters)

                # Extract tool-specific fields
                try:
                    invocation = adapter.extract(block, base_metadata, options)
                    extracted.append(invocation)
                except Exception as e:
                    if options.verbose:
                        print(f"Warning: Failed to extract {tool_name} at {jsonl_path}:{lineno}: {e}", file=sys.stderr)
                    continue

    return extracted, bad_lines


def find_jsonl_files(root: Path) -> list[Path]:
    """Find all JSONL files under root directory."""
    return sorted(root.rglob("*.jsonl"))


def derive_project_name(jsonl_path: Path, root: Path) -> str:
    """
    Derive project name from JSONL path.

    Example: /home/pi/.claude/projects/-home-pi-TP/session.jsonl -> -home-pi-TP
    """
    try:
        # Get relative path from root
        rel_path = jsonl_path.relative_to(root)
        # Project is the first directory component
        project = rel_path.parts[0] if rel_path.parts else "unknown"
        return project
    except ValueError:
        # If path is not relative to root, use parent directory name
        return jsonl_path.parent.name


def write_csv(invocations: list[ToolInvocation], output_path: Path):
    """Write tool invocations to CSV file."""
    if not invocations:
        print("No invocations to write", file=sys.stderr)
        return

    # Get all field names from dataclass
    fieldnames = list(asdict(invocations[0]).keys())

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for inv in invocations:
            writer.writerow(asdict(inv))

    print(f"CSV written to: {output_path}")
    print(f"  {len(invocations):,} tool invocations")


def write_permission_yaml(insights, output_path: Path):
    """Write suggested permissions to YAML file."""
    rules = []

    # Allow rules
    for pattern, reason, count in insights.suggested_allow:
        rules.append({
            "pattern": pattern,
            "action": "allow",
            "reason": f"{reason} ({count:,} occurrences)",
        })

    # Ask rules
    for pattern, reason, count in insights.suggested_ask:
        rules.append({
            "pattern": pattern,
            "action": "ask",
            "reason": f"{reason} ({count:,} occurrences)",
        })

    # Deny rules
    for pattern, reason in insights.suggested_deny:
        rules.append({
            "pattern": pattern,
            "action": "deny",
            "reason": reason,
        })

    # Create YAML structure
    yaml_data = {
        "# Generated permission suggestions for Claude Code": None,
        "# Review and customize before applying to ~/.claude/permissions.yaml": None,
        "# Generated": str(Path(output_path).stat().st_mtime) if output_path.exists() else "2026-02-11",
        "rules": rules,
        "statistics": {
            "total_invocations": insights.total_operations,
            "bash_commands": insights.tool_counts.get("Bash", 0),
            "file_operations": sum([
                insights.tool_counts.get("Read", 0),
                insights.tool_counts.get("Write", 0),
                insights.tool_counts.get("Edit", 0),
            ]),
            "search_operations": sum([
                insights.tool_counts.get("Grep", 0),
                insights.tool_counts.get("Glob", 0),
            ]),
        }
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        # Write header comments manually
        f.write("# Generated permission suggestions for Claude Code\n")
        f.write("# Review and customize before applying to ~/.claude/permissions.yaml\n")
        f.write("# Generated: 2026-02-11\n\n")

        # Write rules and statistics
        yaml.dump(
            {"rules": rules, "statistics": yaml_data["statistics"]},
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )

    print(f"Permission YAML written to: {output_path}")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Extract all tool usage from Claude Code JSONL logs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract all tools from default location
  python extract_tool_usage.py

  # Extract from custom root directory
  python extract_tool_usage.py --root /custom/path/.claude/projects

  # Save outputs to custom directory
  python extract_tool_usage.py --out-dir ./analysis_output

  # Show more patterns in summary
  python extract_tool_usage.py --top 50

  # Verbose mode
  python extract_tool_usage.py -v
        """
    )

    parser.add_argument(
        "--root",
        type=Path,
        default=Path.home() / ".claude/projects",
        help="Root directory to scan for JSONL files (default: ~/.claude/projects)",
    )

    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path.cwd(),
        help="Output directory for generated files (default: current directory)",
    )

    parser.add_argument(
        "--top",
        type=int,
        default=30,
        help="Number of top items to show in summary (default: 30)",
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    return parser.parse_args()


def _extract_all_files(
    root: Path, adapters, options, verbose: bool = False,
) -> tuple:
    """Extract tool invocations from all JSONL files under root.

    Returns (all_invocations, total_bad_lines).
    """
    jsonl_files = find_jsonl_files(root)
    print(f"Found {len(jsonl_files)} JSONL files\n")

    all_invocations: list[ToolInvocation] = []
    total_bad_lines = 0

    for jsonl_path in jsonl_files:
        project = derive_project_name(jsonl_path, root)
        invocations, bad_lines = extract_tools_from_file(
            jsonl_path, project, adapters, options
        )
        all_invocations.extend(invocations)
        total_bad_lines += bad_lines

        if verbose:
            print(f"  {len(invocations):4d} invocations from {jsonl_path.name}")

    print(f"Extracted {len(all_invocations):,} total tool invocations")
    if total_bad_lines > 0:
        print(f"  (skipped {total_bad_lines} malformed JSON lines)")
    print()

    return all_invocations, total_bad_lines


def _generate_outputs(
    all_invocations: list[ToolInvocation], adapters, out_dir: Path, top_n: int,
) -> None:
    """Analyze patterns/permissions and write CSV, summary, and YAML outputs."""
    print("Analyzing patterns...")
    patterns_by_tool = {}
    tool_counts = Counter(inv.tool_name for inv in all_invocations)

    for tool_name in tool_counts:
        adapter = get_adapter(tool_name, adapters)
        tool_invocations = [inv for inv in all_invocations if inv.tool_name == tool_name]
        patterns_by_tool[tool_name] = extract_patterns(tool_invocations, adapter)

    print("Analyzing permissions...")
    permission_insights = analyze_permissions(all_invocations)

    print("\nWriting outputs...")
    csv_path = out_dir / "tool_events.csv"
    write_csv(all_invocations, csv_path)

    summary_path = out_dir / "tool_summary.txt"
    write_summary(all_invocations, patterns_by_tool, permission_insights, summary_path, top_n)

    yaml_path = out_dir / "permissions_suggested.yaml"
    write_permission_yaml(permission_insights, yaml_path)

    print(f"\n{'=' * 70}\nDONE!\n{'=' * 70}")
    print(f"Total invocations analyzed: {len(all_invocations):,}")
    print(f"Unique tools found: {len(tool_counts)}\n")
    print(f"Output files:\n  1. {csv_path}\n  2. {summary_path}\n  3. {yaml_path}\n")


def main():
    """Main entry point."""
    args = parse_args()

    if not args.root.exists():
        print(f"Error: Root directory does not exist: {args.root}", file=sys.stderr)
        sys.exit(1)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    print(f"{'=' * 70}\nCLAUDE CODE TOOL USAGE EXTRACTOR\n{'=' * 70}")
    print(f"Scanning: {args.root}\nOutput:   {args.out_dir}\n")

    adapters = create_adapter_registry()
    options = ExtractionOptions(
        include_content_previews=True, preview_length=100, verbose=args.verbose,
    )

    all_invocations, _ = _extract_all_files(args.root, adapters, options, args.verbose)

    if not all_invocations:
        print("No tool invocations found. Nothing to analyze.", file=sys.stderr)
        sys.exit(0)

    _generate_outputs(all_invocations, adapters, args.out_dir, args.top)


if __name__ == "__main__":
    main()
