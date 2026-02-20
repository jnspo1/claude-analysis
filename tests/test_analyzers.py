"""Tests for analyzers/ — patterns, permissions, and summary."""

from collections import Counter

import pytest

from tool_adapters.base import ToolInvocation, ExtractionOptions
from tool_adapters.bash import BashAdapter
from tool_adapters.file_ops import ReadAdapter
from tool_adapters.search import GrepAdapter
from analyzers.patterns import extract_patterns, format_pattern_section, PatternStats
from analyzers.permissions import analyze_permissions, PermissionInsights


# Shared base metadata
BASE = {
    "timestamp": "2025-06-01T10:00:00Z",
    "project": "test",
    "jsonl_path": "/test.jsonl",
    "lineno": 1,
    "cwd": "/home/pi/test",
    "session_id": "s-001",
    "git_branch": "main",
}


def _make_bash_inv(command):
    return ToolInvocation(**BASE, tool_name="Bash", tool_use_id="t1",
                          bash_command=command)


def _make_read_inv(path):
    return ToolInvocation(**BASE, tool_name="Read", tool_use_id="t1",
                          read_file_path=path)


def _make_write_inv(path):
    return ToolInvocation(**BASE, tool_name="Write", tool_use_id="t1",
                          write_file_path=path)


def _make_grep_inv(pattern):
    return ToolInvocation(**BASE, tool_name="Grep", tool_use_id="t1",
                          grep_pattern=pattern, grep_output_mode="files_with_matches")


class TestExtractPatterns:
    """Tests for extract_patterns."""

    def test_empty_invocations(self):
        stats = extract_patterns([], BashAdapter())
        assert stats.total_count == 0
        assert stats.tool_name == ""

    def test_bash_patterns(self):
        invocations = [
            _make_bash_inv("git status"),
            _make_bash_inv("git diff"),
            _make_bash_inv("pytest tests/"),
        ]
        stats = extract_patterns(invocations, BashAdapter())
        assert stats.total_count == 3
        assert stats.tool_name == "Bash"
        assert stats.level1_patterns["git *"] == 2
        assert stats.level1_patterns["pytest *"] == 1

    def test_primary_values_counted(self):
        invocations = [
            _make_bash_inv("git status"),
            _make_bash_inv("git status"),
        ]
        stats = extract_patterns(invocations, BashAdapter())
        assert stats.primary_values["git status"] == 2

    def test_read_patterns(self):
        invocations = [
            _make_read_inv("/home/pi/python/project/app.py"),
            _make_read_inv("/home/pi/python/project/tests/test_app.py"),
        ]
        stats = extract_patterns(invocations, ReadAdapter())
        assert stats.total_count == 2
        # Level 3 is file extension
        assert stats.level3_patterns[".py"] == 2


class TestFormatPatternSection:
    """Tests for format_pattern_section."""

    def test_formats_level1(self):
        stats = PatternStats(
            tool_name="Bash",
            total_count=10,
            level1_patterns=Counter({"git *": 5, "python *": 3, "ls *": 2}),
            level2_patterns=Counter(),
            level3_patterns=Counter(),
            primary_values=Counter(),
        )
        lines = format_pattern_section(stats, level=1, min_count=1)
        assert any("git *" in l for l in lines)
        assert any("python *" in l for l in lines)

    def test_invalid_level(self):
        stats = PatternStats("X", 0, Counter(), Counter(), Counter(), Counter())
        assert format_pattern_section(stats, level=99) == []

    def test_respects_min_count(self):
        stats = PatternStats(
            tool_name="Bash",
            total_count=5,
            level1_patterns=Counter({"git *": 1, "python *": 5}),
            level2_patterns=Counter(),
            level3_patterns=Counter(),
            primary_values=Counter(),
        )
        lines = format_pattern_section(stats, level=1, min_count=3)
        text = "\n".join(lines)
        assert "python *" in text
        assert "git *" not in text


class TestAnalyzePermissions:
    """Tests for analyze_permissions."""

    def test_empty_invocations(self):
        insights = analyze_permissions([])
        assert insights.total_operations == 0
        assert insights.high_privilege_count == 0
        assert insights.sudo_commands == []

    def test_counts_tools(self):
        invocations = [
            _make_bash_inv("git status"),
            _make_bash_inv("ls"),
            _make_read_inv("/tmp/test.py"),
            _make_grep_inv("TODO"),
        ]
        insights = analyze_permissions(invocations)
        assert insights.total_operations == 4
        assert insights.tool_counts["Bash"] == 2
        assert insights.tool_counts["Read"] == 1
        assert insights.tool_counts["Grep"] == 1

    def test_detects_sudo(self):
        invocations = [
            _make_bash_inv("sudo systemctl restart nginx"),
            _make_bash_inv("sudo apt update"),
        ]
        insights = analyze_permissions(invocations)
        assert insights.high_privilege_count == 2
        assert len(insights.sudo_commands) > 0

    def test_detects_rm(self):
        invocations = [_make_bash_inv("rm -rf /tmp/junk")]
        insights = analyze_permissions(invocations)
        assert len(insights.rm_operations) > 0

    def test_detects_sensitive_paths(self):
        invocations = [
            _make_read_inv("/etc/passwd"),
            _make_read_inv("/home/pi/.ssh/id_rsa"),
        ]
        insights = analyze_permissions(invocations)
        assert insights.sensitive_file_access == 2
        assert len(insights.sensitive_paths) > 0

    def test_generates_deny_recommendations(self):
        invocations = [_make_bash_inv("ls")]
        insights = analyze_permissions(invocations)
        # Deny rules are always added (preventive)
        assert len(insights.suggested_deny) > 0
        deny_patterns = [p for p, _ in insights.suggested_deny]
        assert any("rm -rf" in p for p in deny_patterns)

    def test_allow_recommendations_for_high_frequency(self):
        # Create enough grep operations to trigger allow recommendation
        invocations = [_make_grep_inv(f"pattern_{i}") for i in range(15)]
        insights = analyze_permissions(invocations)
        allow_patterns = [p for p, _, _ in insights.suggested_allow]
        assert any("Grep" in p for p in allow_patterns)

    def test_tracks_file_extensions(self):
        invocations = [
            _make_read_inv("/home/pi/test.py"),
            _make_read_inv("/home/pi/test.md"),
            _make_write_inv("/home/pi/output.json"),
        ]
        insights = analyze_permissions(invocations)
        assert insights.file_extensions[".py"] >= 1
        assert insights.file_extensions[".md"] >= 1

    def test_tracks_directory_access(self):
        invocations = [
            _make_read_inv("/home/pi/python/project/main.py"),
        ]
        insights = analyze_permissions(invocations)
        assert len(insights.directory_access) > 0

    def test_external_access_counted(self):
        web_inv = ToolInvocation(
            **BASE, tool_name="WebSearch", tool_use_id="t1",
            websearch_query="python docs",
        )
        insights = analyze_permissions([web_inv])
        assert insights.external_access_count == 1
