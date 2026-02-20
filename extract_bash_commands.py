#!/usr/bin/env python3
"""
Extract all Bash commands from Claude Code project JSONL logs.

Scans /home/pi/.claude/projects/**/*.jsonl files and extracts every Bash tool
invocation, producing:
  1. bash_commands_all.txt - flat list of all commands chronologically
  2. bash_commands_summary.txt - summary with counts and statistics
  3. bash_commands.csv - detailed CSV with metadata for analysis

Usage:
    python extract_bash_commands.py [--root PATH] [--out-dir PATH] [--top N]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from collections.abc import Iterable
from typing import Any


@dataclass
class BashCmd:
    """Represents a single Bash command invocation with metadata."""
    timestamp: str | None
    project: str
    cwd: str | None
    command: str
    jsonl_path: str
    lineno: int
    tool_use_id: str | None
    description: str | None


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
            except json.JSONDecodeError as e:
                # Silently skip malformed lines but track them
                yield lineno, None


def clean_heredoc(command: str) -> str:
    """
    Remove verbose heredoc content from commands, keeping structure.

    Transforms:
        git commit -m "$(cat <<'EOF'
        Long commit message...
        EOF
        )"

    Into:
        git commit -m "$(cat <<'EOF'...[heredoc]...EOF)"

    This simplifies git commits and other commands that use heredocs.
    """
    # Pattern to match heredoc blocks: <<'DELIMITER' or <<DELIMITER
    # Captures delimiter, then matches everything until that delimiter appears alone
    # Use DOTALL to match across newlines
    pattern = r"<<'?(\w+)'?\s*\n.*?\n\1"

    def replacer(match):
        delimiter = match.group(1)
        return f"<<'{delimiter}'...[heredoc]...{delimiter}"

    cleaned = re.sub(pattern, replacer, command, flags=re.DOTALL)

    # Also collapse multiple newlines into single space for readability
    cleaned = re.sub(r'\s*\n\s*', ' ', cleaned)

    return cleaned


def extract_bash_from_file(jsonl_path: Path, project: str, clean_heredocs: bool = False) -> tuple[list[BashCmd], int]:
    """
    Extract all Bash commands from a single JSONL file.

    Returns:
        (list of BashCmd objects, count of malformed JSON lines)
    """
    extracted: list[BashCmd] = []
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

        # Scan for tool_use blocks
        for block in content:
            if not isinstance(block, dict):
                continue

            # Only process Bash tool invocations
            if block.get("type") == "tool_use" and block.get("name") == "Bash":
                inp = block.get("input") or {}
                cmd = inp.get("command")

                # Validate command is a string
                if not isinstance(cmd, str):
                    continue

                # Clean heredocs if requested
                if clean_heredocs:
                    cmd = clean_heredoc(cmd)

                extracted.append(BashCmd(
                    timestamp=obj.get("timestamp"),
                    project=project,
                    cwd=obj.get("cwd"),
                    command=cmd,
                    jsonl_path=str(jsonl_path),
                    lineno=lineno,
                    tool_use_id=block.get("id"),
                    description=inp.get("description"),
                ))

    return extracted, bad_lines


def extract_command_patterns(commands: list[str]) -> dict[str, Counter]:
    """
    Extract command patterns at different levels of granularity.

    Returns:
        Dictionary with pattern levels:
        - 'base': First word (e.g., 'git', 'ls', 'sudo')
        - 'level2': First 2 words (e.g., 'git status', 'sudo systemctl')
        - 'level3': First 3 words (e.g., 'sudo systemctl restart')
    """
    patterns = {
        'base': Counter(),
        'level2': Counter(),
        'level3': Counter(),
    }

    for cmd in commands:
        # Split command but handle pipes, redirects, etc.
        # For pattern matching, just look at the start of the command
        parts = cmd.split()
        if not parts:
            continue

        # Level 1: Base command (first word)
        patterns['base'][parts[0]] += 1

        # Level 2: First 2 words
        if len(parts) >= 2:
            patterns['level2'][' '.join(parts[:2])] += 1

        # Level 3: First 3 words
        if len(parts) >= 3:
            patterns['level3'][' '.join(parts[:3])] += 1

    return patterns


def _find_and_extract(
    root: Path, clean_heredocs: bool,
) -> tuple:
    """Scan root for JSONL files and extract all bash commands.

    Returns (all_cmds, counts, per_project, bad_lines_total, file_count).
    """
    print(f"Scanning for JSONL files in: {root}")
    jsonl_files = sorted(root.rglob("*.jsonl"))
    print(f"Found {len(jsonl_files)} JSONL files")

    all_cmds: list[BashCmd] = []
    counts: Counter = Counter()
    per_project: Counter = Counter()
    bad_lines_total = 0

    for idx, p in enumerate(jsonl_files, 1):
        if idx % 10 == 0 or idx == len(jsonl_files):
            print(f"  Processing {idx}/{len(jsonl_files)} files...", end="\r")

        try:
            project = p.relative_to(root).parts[0]
        except (ValueError, IndexError):
            project = "<unknown>"

        extracted, bad_lines = extract_bash_from_file(p, project, clean_heredocs)
        bad_lines_total += bad_lines

        for item in extracted:
            all_cmds.append(item)
            counts[item.command] += 1
            per_project[item.project] += 1

    print()
    print(f"Extracted {len(all_cmds)} Bash commands from {len(jsonl_files)} files")
    return all_cmds, counts, per_project, bad_lines_total, len(jsonl_files)


def _write_outputs(
    all_cmds: list, counts: Counter, per_project: Counter,
    bad_lines_total: int, out_dir: Path, top_n: int, write_csv: bool,
) -> None:
    """Write summary, all-commands, and optional CSV output files."""
    patterns = extract_command_patterns([item.command for item in all_cmds])

    # All commands (one per line)
    out_all = out_dir / "bash_commands_all.txt"
    with out_all.open("w", encoding="utf-8") as f:
        for item in all_cmds:
            f.write(item.command + "\n")
    print(f"Wrote: {out_all}")

    # Summary with counts
    out_summary = out_dir / "bash_commands_summary.txt"
    with out_summary.open("w", encoding="utf-8") as f:
        f.write(f"Total Bash tool calls: {sum(counts.values())}\n")
        f.write(f"Unique commands: {len(counts)}\n")
        f.write(f"Bad JSON lines skipped: {bad_lines_total}\n")
        f.write(f"Projects scanned: {len(per_project)}\n\n")

        f.write("=" * 70 + "\n")
        f.write("COMMAND PATTERNS (High-Level Overview)\n")
        f.write("=" * 70 + "\n\n")

        for label, key in [("Base commands", "base"),
                           ("Command patterns - 2 words", "level2"),
                           ("Command patterns - 3 words", "level3")]:
            f.write(f"{label} (count >= 3):\n")
            for cmd, n in patterns[key].most_common():
                if n >= 3:
                    f.write(f"{n:6d}  {cmd} *\n")
            f.write("\n")

        f.write("=" * 70 + "\n")
        f.write("SPECIFIC COMMANDS\n")
        f.write("=" * 70 + "\n\n")

        f.write(f"Top {min(top_n, len(counts))} commands:\n")
        for cmd, n in counts.most_common(top_n):
            display_cmd = cmd if len(cmd) <= 100 else cmd[:97] + "..."
            f.write(f"{n:6d}  {display_cmd}\n")

        f.write("\nPer-project totals:\n")
        for proj, n in per_project.most_common():
            f.write(f"{n:6d}  {proj}\n")
    print(f"Wrote: {out_summary}")

    # Optional CSV
    if write_csv:
        out_csv = out_dir / "bash_commands.csv"
        with out_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "project", "cwd", "command",
                "jsonl_path", "lineno", "tool_use_id", "description"
            ])
            for item in all_cmds:
                writer.writerow([
                    item.timestamp, item.project, item.cwd, item.command,
                    item.jsonl_path, item.lineno, item.tool_use_id, item.description,
                ])
        print(f"Wrote: {out_csv}")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Extract Bash commands from Claude Code project logs"
    )
    parser.add_argument("--root", type=Path, default=Path("/home/pi/.claude/projects"),
                        help="Root directory containing project logs")
    parser.add_argument("--out-dir", type=Path, default=Path.cwd(),
                        help="Output directory for results")
    parser.add_argument("--top", type=int, default=50,
                        help="Number of top commands to show in summary")
    parser.add_argument("--csv", action="store_true",
                        help="Also output detailed CSV file")
    parser.add_argument("--clean-heredocs", action="store_true",
                        help="Remove verbose heredoc content")
    args = parser.parse_args()

    if not args.root.exists() or not args.root.is_dir():
        print(f"Error: Invalid root directory: {args.root}", file=sys.stderr)
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)

    result = _find_and_extract(args.root, args.clean_heredocs)
    all_cmds, counts, per_project, bad_lines_total, file_count = result

    if not all_cmds:
        print("Warning: No Bash commands found", file=sys.stderr)
        return 0

    _write_outputs(all_cmds, counts, per_project, bad_lines_total,
                   args.out_dir, args.top, args.csv)

    print("\nDone!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
