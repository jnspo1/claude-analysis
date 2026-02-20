"""Permission analysis and recommendations."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from tool_adapters.base import ToolInvocation


@dataclass
class PermissionInsights:
    """Insights and recommendations for permission configuration."""
    total_operations: int
    high_privilege_count: int
    sensitive_file_access: int
    external_access_count: int

    # High-risk operations detected
    sudo_commands: list[tuple[str, int]]  # (command, count)
    rm_operations: list[tuple[str, int]]
    chmod_operations: list[tuple[str, int]]
    sensitive_paths: list[tuple[str, int]]  # (path, count)

    # Recommendations
    suggested_allow: list[tuple[str, str, int]]  # (pattern, reason, count)
    suggested_ask: list[tuple[str, str, int]]
    suggested_deny: list[tuple[str, str]]  # (pattern, reason) - preventive, no count

    # Statistics per tool
    tool_counts: Counter = field(default_factory=Counter)
    bash_command_types: Counter = field(default_factory=Counter)
    file_extensions: Counter = field(default_factory=Counter)
    directory_access: Counter = field(default_factory=Counter)


def analyze_permissions(invocations: list[ToolInvocation]) -> PermissionInsights:
    """
    Analyze tool invocations and generate permission recommendations.

    Args:
        invocations: All tool invocations

    Returns:
        PermissionInsights with recommendations
    """
    insights = PermissionInsights(
        total_operations=len(invocations),
        high_privilege_count=0,
        sensitive_file_access=0,
        external_access_count=0,
        sudo_commands=[],
        rm_operations=[],
        chmod_operations=[],
        sensitive_paths=[],
        suggested_allow=[],
        suggested_ask=[],
        suggested_deny=[],
    )

    # Count by tool type
    for inv in invocations:
        insights.tool_counts[inv.tool_name] += 1

    # Analyze Bash commands
    bash_invocations = [inv for inv in invocations if inv.tool_name == "Bash"]
    _analyze_bash_commands(bash_invocations, insights)

    # Analyze file operations
    file_invocations = [inv for inv in invocations if inv.tool_name in ("Read", "Write", "Edit")]
    _analyze_file_operations(file_invocations, insights)

    # Analyze external access
    web_invocations = [inv for inv in invocations if inv.tool_name in ("WebSearch", "WebFetch")]
    insights.external_access_count = len(web_invocations)

    # Generate recommendations
    _generate_recommendations(invocations, insights)

    return insights


def _analyze_bash_commands(bash_invocations: list[ToolInvocation], insights: PermissionInsights):
    """Analyze Bash commands for security patterns."""
    sudo_cmds = Counter()
    rm_cmds = Counter()
    chmod_cmds = Counter()
    git_cmds = Counter()
    curl_cmds = 0

    for inv in bash_invocations:
        cmd = inv.bash_command or ""
        if not cmd:
            continue

        # Extract base command
        parts = cmd.split()
        if not parts:
            continue

        base_cmd = parts[0]
        insights.bash_command_types[base_cmd] += 1

        # Check for high-privilege operations
        if cmd.startswith("sudo "):
            insights.high_privilege_count += 1
            # Extract sudo command (what comes after sudo)
            sudo_parts = cmd[5:].strip().split()
            if sudo_parts:
                sudo_cmd = sudo_parts[0]
                sudo_cmds[sudo_cmd] += 1

        # Check for file deletion
        if base_cmd == "rm" or "rm " in cmd:
            rm_cmds[cmd] += 1

        # Check for permission changes
        if base_cmd == "chmod":
            chmod_cmds[cmd] += 1

        # Track git commands
        if base_cmd == "git" and len(parts) >= 2:
            git_cmds[parts[1]] += 1

        # Track curl (external access)
        if base_cmd == "curl":
            curl_cmds += 1

    # Store top operations
    insights.sudo_commands = sudo_cmds.most_common(10)
    insights.rm_operations = rm_cmds.most_common(10)
    insights.chmod_operations = chmod_cmds.most_common(10)

    # Store git command counts for recommendations
    insights._git_cmds = git_cmds  # Internal use
    insights._curl_count = curl_cmds


def _analyze_file_operations(file_invocations: list[ToolInvocation], insights: PermissionInsights):
    """Analyze file operations for sensitive path access."""
    sensitive_patterns = [
        r"^/etc/",
        r"\.ssh/",
        r"\.env$",
        r"\.env\.",
        r"credentials",
        r"secrets",
        r"password",
        r"^/root/",
        r"^/var/",
    ]

    sensitive_paths = Counter()
    extensions = Counter()
    directories = Counter()

    for inv in file_invocations:
        # Get file path
        path = None
        if inv.tool_name == "Read":
            path = inv.read_file_path
        elif inv.tool_name == "Write":
            path = inv.write_file_path
        elif inv.tool_name == "Edit":
            path = inv.edit_file_path

        if not path:
            continue

        # Check for sensitive paths
        for pattern in sensitive_patterns:
            if re.search(pattern, path, re.IGNORECASE):
                sensitive_paths[path] += 1
                insights.sensitive_file_access += 1
                break

        # Extract extension
        if "." in path:
            ext = "." + path.rsplit(".", 1)[1]
            extensions[ext] += 1

        # Extract top-level directory
        if path.startswith("/"):
            parts = path.split("/")
            if len(parts) >= 4:
                top_dir = "/".join(parts[:4]) + "/"
                directories[top_dir] += 1

    insights.sensitive_paths = sensitive_paths.most_common(10)
    insights.file_extensions = extensions
    insights.directory_access = directories


def _generate_recommendations(invocations: list[ToolInvocation], insights: PermissionInsights):
    """Generate allow/ask/deny recommendations based on usage patterns."""

    # SUGGESTED ALLOW RULES (high-frequency, low-risk)
    # Read-only git commands
    git_cmds = getattr(insights, '_git_cmds', Counter())
    read_only_git = sum([
        git_cmds.get('status', 0),
        git_cmds.get('diff', 0),
        git_cmds.get('log', 0),
        git_cmds.get('show', 0),
    ])
    if read_only_git >= 10:
        insights.suggested_allow.append((
            "Bash:git (status|diff|log|show)",
            "Read-only git operations",
            read_only_git
        ))

    # File reads in common extensions
    read_count = insights.tool_counts.get("Read", 0)
    common_exts = [".py", ".md", ".json", ".html", ".txt"]
    common_read_count = sum(insights.file_extensions.get(ext, 0) for ext in common_exts)
    if common_read_count >= 50:
        insights.suggested_allow.append((
            "Read:.*\\.(py|md|json|html|txt)$",
            "Reading common code/doc files",
            common_read_count
        ))

    # Grep operations (generally safe)
    grep_count = insights.tool_counts.get("Grep", 0)
    if grep_count >= 10:
        insights.suggested_allow.append((
            "Grep:.*",
            "Code search operations",
            grep_count
        ))

    # Glob operations (generally safe)
    glob_count = insights.tool_counts.get("Glob", 0)
    if glob_count >= 5:
        insights.suggested_allow.append((
            "Glob:.*",
            "File pattern matching",
            glob_count
        ))

    # SUGGESTED ASK RULES (infrequent or moderate-risk)
    # Git write operations
    git_write = sum([
        git_cmds.get('push', 0),
        git_cmds.get('commit', 0),
        git_cmds.get('add', 0),
    ])
    if git_write >= 5:
        insights.suggested_ask.append((
            "Bash:git (push|commit|add)",
            "Version control writes",
            git_write
        ))

    # File creation
    write_count = insights.tool_counts.get("Write", 0)
    if write_count >= 10:
        insights.suggested_ask.append((
            "Write:.*",
            "File creation",
            write_count
        ))

    # Config file edits
    config_exts = [".env", ".toml", ".yaml", ".yml", ".config", ".ini"]
    config_edit_count = sum(insights.file_extensions.get(ext, 0) for ext in config_exts)
    if config_edit_count >= 3:
        insights.suggested_ask.append((
            "Edit:.*\\.(env|toml|yaml|yml|config|ini)$",
            "Configuration file edits",
            config_edit_count
        ))

    # Sudo commands
    if insights.high_privilege_count >= 5:
        insights.suggested_ask.append((
            "Bash:sudo.*",
            "Privileged operations",
            insights.high_privilege_count
        ))

    # SUGGESTED DENY RULES (high-risk patterns - preventive)
    insights.suggested_deny.extend([
        ("Bash:rm -rf /(etc|usr|var|boot|sys)", "System directory deletion (preventive)"),
        ("Write:/(etc|usr|sys)/.*", "System file modification (preventive)"),
        ("Write:~/.ssh/.*", "SSH key modification (preventive)"),
        ("Bash:chmod 777", "Overly permissive chmod (preventive)"),
        ("Bash:dd if=/dev/.*", "Dangerous disk operations (preventive)"),
    ])
