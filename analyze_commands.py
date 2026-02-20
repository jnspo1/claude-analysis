#!/usr/bin/env python3
"""
Quick analysis helpers for extracted Bash commands.

Provides common queries and insights from the extracted command data.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


def load_commands(csv_path: str = "bash_commands.csv") -> list[dict[str, str]]:
    """Load commands from CSV file."""
    commands = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            commands.append(row)
    return commands


def analyze_git_operations(commands: list[dict[str, str]]) -> None:
    """Analyze git command patterns."""
    git_commands = [cmd for cmd in commands if cmd["command"].startswith("git ")]

    if not git_commands:
        print("No git commands found")
        return

    print(f"\n{'='*60}")
    print("GIT OPERATIONS ANALYSIS")
    print(f"{'='*60}")
    print(f"Total git commands: {len(git_commands)}")

    # Extract git subcommands
    git_ops = Counter()
    for cmd in git_commands:
        parts = cmd["command"].split()
        if len(parts) >= 2:
            git_ops[parts[1]] += 1

    print("\nTop git operations:")
    for op, count in git_ops.most_common(10):
        print(f"  {count:4d}  git {op}")

    # Git by project
    git_by_project = Counter()
    for cmd in git_commands:
        git_by_project[cmd["project"]] += 1

    print("\nGit usage by project:")
    for proj, count in git_by_project.most_common():
        print(f"  {count:4d}  {proj}")


def analyze_sudo_commands(commands: list[dict[str, str]]) -> None:
    """Analyze sudo/privileged operations."""
    sudo_commands = [cmd for cmd in commands if cmd["command"].startswith("sudo ")]

    if not sudo_commands:
        print("\nNo sudo commands found")
        return

    print(f"\n{'='*60}")
    print("PRIVILEGED OPERATIONS (sudo)")
    print(f"{'='*60}")
    print(f"Total sudo commands: {len(sudo_commands)}")

    # Group by service
    systemctl_ops = Counter()
    for cmd in sudo_commands:
        if "systemctl" in cmd["command"]:
            # Extract service name
            match = re.search(r'systemctl \w+ ([\w-]+)', cmd["command"])
            if match:
                systemctl_ops[match.group(1)] += 1

    if systemctl_ops:
        print("\nSystemctl services managed:")
        for service, count in systemctl_ops.most_common():
            print(f"  {count:4d}  {service}")


def analyze_risky_commands(commands: list[dict[str, str]]) -> None:
    """Identify potentially risky commands."""
    risky_patterns = [
        (r"rm -rf", "Recursive force delete"),
        (r"chmod 777", "Overly permissive chmod"),
        (r"--force", "Force flag used"),
        (r"pkill|killall", "Process killing"),
        (r"dd if=", "Direct disk operations"),
    ]

    risky = defaultdict(list)
    for cmd in commands:
        for pattern, desc in risky_patterns:
            if re.search(pattern, cmd["command"]):
                risky[desc].append(cmd)

    if not risky:
        print("\nNo risky command patterns detected")
        return

    print(f"\n{'='*60}")
    print("POTENTIALLY RISKY COMMANDS")
    print(f"{'='*60}")

    for desc, cmds in risky.items():
        print(f"\n{desc}: {len(cmds)} occurrences")
        for cmd in cmds[:3]:  # Show first 3 examples
            display_cmd = cmd["command"]
            if len(display_cmd) > 80:
                display_cmd = display_cmd[:77] + "..."
            print(f"  → {display_cmd}")
            print(f"    Project: {cmd['project']}, CWD: {cmd['cwd']}")


def analyze_package_management(commands: list[dict[str, str]]) -> None:
    """Analyze package installation/management."""
    pkg_commands = [
        cmd for cmd in commands
        if any(x in cmd["command"] for x in ["pip", "npm", "apt", "brew"])
    ]

    if not pkg_commands:
        print("\nNo package management commands found")
        return

    print(f"\n{'='*60}")
    print("PACKAGE MANAGEMENT")
    print(f"{'='*60}")

    pkg_mgrs = Counter()
    for cmd in pkg_commands:
        if "pip" in cmd["command"]:
            pkg_mgrs["pip"] += 1
        elif "npm" in cmd["command"]:
            pkg_mgrs["npm"] += 1
        elif "apt" in cmd["command"]:
            pkg_mgrs["apt"] += 1
        elif "brew" in cmd["command"]:
            pkg_mgrs["brew"] += 1

    print("\nPackage manager usage:")
    for mgr, count in pkg_mgrs.most_common():
        print(f"  {count:4d}  {mgr}")


def analyze_by_time(commands: list[dict[str, str]]) -> None:
    """Analyze command patterns over time."""
    from datetime import datetime

    # Group by date
    by_date = defaultdict(int)
    by_hour = Counter()

    for cmd in commands:
        ts = cmd.get("timestamp")
        if not ts:
            continue

        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            by_date[dt.date()] += 1
            by_hour[dt.hour] += 1
        except (ValueError, AttributeError):
            continue

    if not by_date:
        print("\nNo timestamp data available")
        return

    print(f"\n{'='*60}")
    print("TEMPORAL ANALYSIS")
    print(f"{'='*60}")

    print(f"\nCommands span {len(by_date)} days")
    print(f"Date range: {min(by_date.keys())} to {max(by_date.keys())}")

    print("\nTop 5 most active days:")
    for date in sorted(by_date, key=by_date.get, reverse=True)[:5]:
        print(f"  {date}: {by_date[date]} commands")

    print("\nCommands by hour of day:")
    for hour in sorted(by_hour.keys()):
        bar = "█" * (by_hour[hour] // 10)
        print(f"  {hour:02d}:00  {by_hour[hour]:4d}  {bar}")


def analyze_command_patterns(commands: list[dict[str, str]]) -> None:
    """Analyze high-level command patterns."""
    print(f"\n{'='*60}")
    print("COMMAND PATTERN OVERVIEW")
    print(f"{'='*60}")

    # Extract patterns
    base_cmds = Counter()
    two_word = Counter()
    three_word = Counter()

    for cmd in commands:
        parts = cmd["command"].split()
        if not parts:
            continue

        base_cmds[parts[0]] += 1

        if len(parts) >= 2:
            two_word[' '.join(parts[:2])] += 1

        if len(parts) >= 3:
            three_word[' '.join(parts[:3])] += 1

    print("\nTop 10 base commands:")
    for cmd, count in base_cmds.most_common(10):
        pct = (count / len(commands)) * 100
        print(f"  {count:4d} ({pct:4.1f}%)  {cmd} *")

    print("\nTop 15 command patterns (2 words):")
    for cmd, count in two_word.most_common(15):
        pct = (count / len(commands)) * 100
        print(f"  {count:4d} ({pct:4.1f}%)  {cmd} *")

    print("\nTop 10 command patterns (3 words):")
    for cmd, count in three_word.most_common(10):
        pct = (count / len(commands)) * 100
        print(f"  {count:4d} ({pct:4.1f}%)  {cmd} *")


def main():
    """Run all analyses."""
    csv_path = "bash_commands.csv"

    if not Path(csv_path).exists():
        print(f"Error: {csv_path} not found")
        print("Run extract_bash_commands.py with --csv flag first")
        sys.exit(1)

    print("Loading command data...")
    commands = load_commands(csv_path)
    print(f"Loaded {len(commands)} commands\n")

    # Run analyses
    analyze_command_patterns(commands)
    analyze_git_operations(commands)
    analyze_sudo_commands(commands)
    analyze_package_management(commands)
    analyze_risky_commands(commands)
    analyze_by_time(commands)

    print(f"\n{'='*60}")
    print("Analysis complete!")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
