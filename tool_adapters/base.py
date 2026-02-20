"""Base classes for tool adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ExtractionOptions:
    """Configuration options for tool extraction."""
    include_content_previews: bool = True
    preview_length: int = 100
    verbose: bool = False


@dataclass
class ToolInvocation:
    """Unified representation of any tool invocation."""
    # Common metadata (all tools)
    timestamp: str | None
    project: str
    tool_name: str
    tool_use_id: str | None
    jsonl_path: str
    lineno: int
    cwd: str | None
    session_id: str | None
    git_branch: str | None

    # Tool-specific inputs (Optional fields, populated based on tool_name)
    # Bash
    bash_command: str | None = None
    bash_description: str | None = None
    bash_timeout: int | None = None

    # Read
    read_file_path: str | None = None
    read_offset: int | None = None
    read_limit: int | None = None
    read_pages: str | None = None

    # Write
    write_file_path: str | None = None
    write_content_length: int | None = None
    write_content_preview: str | None = None

    # Edit
    edit_file_path: str | None = None
    edit_old_string_preview: str | None = None
    edit_new_string_preview: str | None = None
    edit_replace_all: bool | None = None

    # Grep
    grep_pattern: str | None = None
    grep_path: str | None = None
    grep_output_mode: str | None = None
    grep_flags: str | None = None
    grep_glob: str | None = None
    grep_type: str | None = None

    # Glob
    glob_pattern: str | None = None
    glob_path: str | None = None

    # Task tools
    task_subject: str | None = None
    task_description_preview: str | None = None
    task_id: str | None = None
    task_status: str | None = None
    task_operation: str | None = None  # create, update, list, get, output

    # TodoWrite
    todo_content_preview: str | None = None

    # Special tools
    skill_name: str | None = None
    websearch_query: str | None = None
    ask_question_preview: str | None = None

    # Generic fallback
    raw_input_json: str | None = None


class ToolAdapter(ABC):
    """Base class for tool-specific extraction logic."""

    @abstractmethod
    def extract(self, block: dict, base_metadata: dict, options: ExtractionOptions) -> ToolInvocation:
        """
        Extract tool-specific fields from tool_use block.

        Args:
            block: The tool_use content block
            base_metadata: Common metadata (timestamp, project, cwd, etc.)
            options: Extraction configuration

        Returns:
            ToolInvocation with tool-specific fields populated
        """
        pass

    @abstractmethod
    def get_primary_value(self, invocation: ToolInvocation) -> str:
        """
        Get the 'primary' value for pattern analysis.

        For Bash: command string
        For Read: file_path
        For Grep: pattern
        etc.

        Returns:
            Primary value string for pattern analysis
        """
        pass

    @abstractmethod
    def get_pattern_levels(self, invocation: ToolInvocation) -> tuple[str, str, str]:
        """
        Get 3-level pattern hierarchy for this tool.

        Returns:
            Tuple of (level1, level2, level3) pattern strings
        """
        pass

    def truncate_preview(self, text: str, length: int = 100) -> str:
        """Helper to truncate text to preview length."""
        if not text:
            return ""
        text = text.strip()
        if len(text) <= length:
            return text
        return text[:length] + "..."
