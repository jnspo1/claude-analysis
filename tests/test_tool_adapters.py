"""Tests for tool_adapters — extraction, primary values, and pattern levels."""

import pytest

from tool_adapters.base import ExtractionOptions, ToolInvocation
from tool_adapters.bash import BashAdapter
from tool_adapters.file_ops import ReadAdapter, WriteAdapter, EditAdapter
from tool_adapters.search import GrepAdapter, GlobAdapter
from tool_adapters.tasks import TaskAdapter, TodoWriteAdapter
from tool_adapters.special import SpecialToolAdapter, GenericAdapter
from tool_adapters.registry import create_adapter_registry, get_adapter


# Shared base metadata for all adapter tests
BASE_META = {
    "timestamp": "2025-06-01T10:00:00Z",
    "project": "test-project",
    "jsonl_path": "/test/session.jsonl",
    "lineno": 1,
    "cwd": "/home/pi/test",
    "session_id": "test-001",
    "git_branch": "main",
}

OPTIONS = ExtractionOptions(include_content_previews=True, preview_length=50)


class TestBashAdapter:
    """Tests for BashAdapter."""

    def test_extract(self):
        block = {
            "id": "tu_001",
            "name": "Bash",
            "input": {
                "command": "git status",
                "description": "Check git status",
                "timeout": 5000,
            },
        }
        inv = BashAdapter().extract(block, BASE_META, OPTIONS)
        assert inv.tool_name == "Bash"
        assert inv.bash_command == "git status"
        assert inv.bash_description == "Check git status"
        assert inv.bash_timeout == 5000

    def test_primary_value(self):
        inv = ToolInvocation(**BASE_META, tool_name="Bash", tool_use_id="t1",
                             bash_command="pytest tests/")
        assert BashAdapter().get_primary_value(inv) == "pytest tests/"

    def test_primary_value_empty(self):
        inv = ToolInvocation(**BASE_META, tool_name="Bash", tool_use_id="t1")
        assert BashAdapter().get_primary_value(inv) == ""

    def test_pattern_levels(self):
        inv = ToolInvocation(**BASE_META, tool_name="Bash", tool_use_id="t1",
                             bash_command="git commit -m 'fix'")
        l1, l2, l3 = BashAdapter().get_pattern_levels(inv)
        assert l1 == "git *"
        assert l2 == "git commit *"
        assert l3 == "git commit -m *"

    def test_pattern_levels_single_word(self):
        inv = ToolInvocation(**BASE_META, tool_name="Bash", tool_use_id="t1",
                             bash_command="ls")
        l1, l2, l3 = BashAdapter().get_pattern_levels(inv)
        assert l1 == "ls *"
        assert l2 == "ls"
        assert l3 == "ls"

    def test_empty_command_patterns(self):
        inv = ToolInvocation(**BASE_META, tool_name="Bash", tool_use_id="t1",
                             bash_command="")
        assert BashAdapter().get_pattern_levels(inv) == ("", "", "")


class TestReadAdapter:
    """Tests for ReadAdapter."""

    def test_extract(self):
        block = {
            "id": "tu_002",
            "name": "Read",
            "input": {"file_path": "/home/pi/test.py", "offset": 10, "limit": 50},
        }
        inv = ReadAdapter().extract(block, BASE_META, OPTIONS)
        assert inv.tool_name == "Read"
        assert inv.read_file_path == "/home/pi/test.py"
        assert inv.read_offset == 10
        assert inv.read_limit == 50

    def test_pattern_levels_deep_path(self):
        inv = ToolInvocation(**BASE_META, tool_name="Read", tool_use_id="t1",
                             read_file_path="/home/pi/python/project/src/main.py")
        l1, l2, l3 = ReadAdapter().get_pattern_levels(inv)
        assert l1 == "/home/pi/python/"
        assert l2 == "/home/pi/python/project/"
        assert l3 == ".py"

    def test_pattern_levels_no_extension(self):
        inv = ToolInvocation(**BASE_META, tool_name="Read", tool_use_id="t1",
                             read_file_path="/home/pi/Makefile")
        _, _, l3 = ReadAdapter().get_pattern_levels(inv)
        assert l3 == "(no extension)"


class TestWriteAdapter:
    """Tests for WriteAdapter."""

    def test_extract_with_preview(self):
        block = {
            "id": "tu_003",
            "name": "Write",
            "input": {
                "file_path": "/tmp/output.txt",
                "content": "Hello world!\nSecond line\n",
            },
        }
        inv = WriteAdapter().extract(block, BASE_META, OPTIONS)
        assert inv.tool_name == "Write"
        assert inv.write_file_path == "/tmp/output.txt"
        assert inv.write_content_length == 25
        assert inv.write_content_preview is not None

    def test_extract_no_preview(self):
        opts = ExtractionOptions(include_content_previews=False)
        block = {
            "id": "tu_003",
            "name": "Write",
            "input": {"file_path": "/tmp/out.txt", "content": "data"},
        }
        inv = WriteAdapter().extract(block, BASE_META, opts)
        assert inv.write_content_preview is None


class TestEditAdapter:
    """Tests for EditAdapter."""

    def test_extract(self):
        block = {
            "id": "tu_004",
            "name": "Edit",
            "input": {
                "file_path": "/home/pi/app.py",
                "old_string": "def old():",
                "new_string": "def new():",
                "replace_all": True,
            },
        }
        inv = EditAdapter().extract(block, BASE_META, OPTIONS)
        assert inv.tool_name == "Edit"
        assert inv.edit_file_path == "/home/pi/app.py"
        assert inv.edit_replace_all is True
        assert inv.edit_old_string_preview is not None

    def test_missing_input(self):
        block = {"id": "tu_004", "name": "Edit", "input": {}}
        inv = EditAdapter().extract(block, BASE_META, OPTIONS)
        assert inv.edit_file_path is None
        assert inv.edit_old_string_preview is None


class TestGrepAdapter:
    """Tests for GrepAdapter."""

    def test_extract_with_flags(self):
        block = {
            "id": "tu_005",
            "name": "Grep",
            "input": {
                "pattern": "def test_.*",
                "path": "/home/pi/project",
                "-i": True,
                "-C": 3,
                "output_mode": "content",
            },
        }
        inv = GrepAdapter().extract(block, BASE_META, OPTIONS)
        assert inv.grep_pattern == "def test_.*"
        assert inv.grep_path == "/home/pi/project"
        assert "-i" in inv.grep_flags
        assert "-C 3" in inv.grep_flags
        assert inv.grep_output_mode == "content"

    def test_pattern_levels_regex(self):
        inv = ToolInvocation(**BASE_META, tool_name="Grep", tool_use_id="t1",
                             grep_pattern="class\\s+\\w+", grep_path="/src",
                             grep_output_mode="content")
        l1, l2, l3 = GrepAdapter().get_pattern_levels(inv)
        assert l1 == "content"
        assert l2 == "/src"
        assert l3 == "regex"

    def test_pattern_levels_literal(self):
        inv = ToolInvocation(**BASE_META, tool_name="Grep", tool_use_id="t1",
                             grep_pattern="TODO", grep_output_mode="files_with_matches")
        l1, _, l3 = GrepAdapter().get_pattern_levels(inv)
        assert l1 == "files_with_matches"
        assert l3 == "literal"


class TestGlobAdapter:
    """Tests for GlobAdapter."""

    def test_extract(self):
        block = {
            "id": "tu_006",
            "name": "Glob",
            "input": {"pattern": "**/*.py", "path": "/home/pi/project"},
        }
        inv = GlobAdapter().extract(block, BASE_META, OPTIONS)
        assert inv.glob_pattern == "**/*.py"
        assert inv.glob_path == "/home/pi/project"

    def test_pattern_levels_recursive(self):
        inv = ToolInvocation(**BASE_META, tool_name="Glob", tool_use_id="t1",
                             glob_pattern="**/*.py", glob_path="/src")
        l1, l2, l3 = GlobAdapter().get_pattern_levels(inv)
        assert l1 == "recursive"
        assert l2 == ".py"
        assert l3 == "/src"


class TestTaskAdapter:
    """Tests for TaskAdapter."""

    def test_extract_create(self):
        block = {
            "id": "tu_007",
            "name": "TaskCreate",
            "input": {
                "subject": "Fix bug",
                "description": "Fix the login bug in auth.py",
            },
        }
        inv = TaskAdapter().extract(block, BASE_META, OPTIONS)
        assert inv.tool_name == "TaskCreate"
        assert inv.task_subject == "Fix bug"
        assert inv.task_operation == "create"

    def test_extract_update(self):
        block = {
            "id": "tu_008",
            "name": "TaskUpdate",
            "input": {"taskId": "5", "status": "completed"},
        }
        inv = TaskAdapter().extract(block, BASE_META, OPTIONS)
        assert inv.task_id == "5"
        assert inv.task_status == "completed"
        assert inv.task_operation == "update"


class TestSpecialToolAdapter:
    """Tests for SpecialToolAdapter."""

    def test_extract_skill(self):
        block = {
            "id": "tu_009",
            "name": "Skill",
            "input": {"skill": "brainstorming"},
        }
        inv = SpecialToolAdapter().extract(block, BASE_META, OPTIONS)
        assert inv.skill_name == "brainstorming"

    def test_extract_websearch(self):
        block = {
            "id": "tu_010",
            "name": "WebSearch",
            "input": {"query": "python fastapi tutorial"},
        }
        inv = SpecialToolAdapter().extract(block, BASE_META, OPTIONS)
        assert inv.websearch_query == "python fastapi tutorial"


class TestGenericAdapter:
    """Tests for GenericAdapter fallback."""

    def test_extract_unknown_tool(self):
        block = {
            "id": "tu_011",
            "name": "UnknownTool",
            "input": {"foo": "bar", "baz": 42},
        }
        inv = GenericAdapter().extract(block, BASE_META, OPTIONS)
        assert inv.tool_name == "UnknownTool"
        assert inv.raw_input_json is not None
        assert "foo" in inv.raw_input_json

    def test_primary_value_returns_tool_name(self):
        """GenericAdapter returns tool_name as the primary value."""
        inv = ToolInvocation(**BASE_META, tool_name="X", tool_use_id="t1")
        assert GenericAdapter().get_primary_value(inv) == "X"

    def test_pattern_levels_all_tool_name(self):
        """GenericAdapter uses tool_name at all 3 pattern levels."""
        inv = ToolInvocation(**BASE_META, tool_name="X", tool_use_id="t1")
        assert GenericAdapter().get_pattern_levels(inv) == ("X", "X", "X")


class TestRegistry:
    """Tests for adapter registry."""

    def test_creates_all_known_adapters(self):
        registry = create_adapter_registry()
        assert "Bash" in registry
        assert "Read" in registry
        assert "Write" in registry
        assert "Edit" in registry
        assert "Grep" in registry
        assert "Glob" in registry
        assert "Skill" in registry
        assert len(registry) >= 20

    def test_get_adapter_known(self):
        registry = create_adapter_registry()
        adapter = get_adapter("Bash", registry)
        assert isinstance(adapter, BashAdapter)

    def test_get_adapter_unknown_falls_back(self):
        registry = create_adapter_registry()
        adapter = get_adapter("MadeUpTool", registry)
        assert isinstance(adapter, GenericAdapter)


class TestTruncatePreview:
    """Tests for ToolAdapter.truncate_preview helper."""

    def test_short_text_unchanged(self):
        result = BashAdapter().truncate_preview("hello", 100)
        assert result == "hello"

    def test_long_text_truncated(self):
        result = BashAdapter().truncate_preview("a" * 200, 50)
        assert len(result) == 53  # 50 + "..."
        assert result.endswith("...")

    def test_empty_text(self):
        result = BashAdapter().truncate_preview("", 100)
        assert result == ""

    def test_strips_whitespace(self):
        result = BashAdapter().truncate_preview("  hello  ", 100)
        assert result == "hello"
