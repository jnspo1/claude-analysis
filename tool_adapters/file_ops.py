"""File operation tool adapters (Read, Write, Edit)."""

import os
from .base import ToolAdapter, ToolInvocation, ExtractionOptions


class ReadAdapter(ToolAdapter):
    """Adapter for Read tool invocations."""

    def extract(self, block: dict, base_metadata: dict, options: ExtractionOptions) -> ToolInvocation:
        """Extract Read-specific fields."""
        tool_input = block.get("input", {})

        return ToolInvocation(
            **base_metadata,
            tool_name="Read",
            tool_use_id=block.get("id"),
            read_file_path=tool_input.get("file_path"),
            read_offset=tool_input.get("offset"),
            read_limit=tool_input.get("limit"),
            read_pages=tool_input.get("pages"),
        )

    def get_primary_value(self, invocation: ToolInvocation) -> str:
        """Return the file path as primary value."""
        return invocation.read_file_path or ""

    def get_pattern_levels(self, invocation: ToolInvocation) -> tuple[str, str, str]:
        """
        Get 3-level path patterns.

        Level 1: Top directory (e.g., /home/pi/TP/)
        Level 2: Subdirectory (e.g., /home/pi/TP/workflows/)
        Level 3: File extension (e.g., .py)
        """
        path = invocation.read_file_path or ""
        if not path:
            return ("", "", "")

        # Level 1: Top-level directory (first 3 path components for absolute paths)
        parts = path.split("/")
        if path.startswith("/") and len(parts) >= 4:
            level1 = "/".join(parts[:4]) + "/"
        elif path.startswith("/") and len(parts) >= 3:
            level1 = "/".join(parts[:3]) + "/"
        else:
            level1 = parts[0] if parts else ""

        # Level 2: Subdirectory (first 4-5 components)
        if path.startswith("/") and len(parts) >= 5:
            level2 = "/".join(parts[:5]) + "/"
        elif path.startswith("/") and len(parts) >= 4:
            level2 = "/".join(parts[:4]) + "/"
        else:
            level2 = level1

        # Level 3: File extension
        _, ext = os.path.splitext(path)
        level3 = ext if ext else "(no extension)"

        return (level1, level2, level3)


class WriteAdapter(ToolAdapter):
    """Adapter for Write tool invocations."""

    def extract(self, block: dict, base_metadata: dict, options: ExtractionOptions) -> ToolInvocation:
        """Extract Write-specific fields."""
        tool_input = block.get("input", {})
        content = tool_input.get("content", "")

        preview = None
        if options.include_content_previews and content:
            preview = self.truncate_preview(content, options.preview_length)

        return ToolInvocation(
            **base_metadata,
            tool_name="Write",
            tool_use_id=block.get("id"),
            write_file_path=tool_input.get("file_path"),
            write_content_length=len(content) if content else 0,
            write_content_preview=preview,
        )

    def get_primary_value(self, invocation: ToolInvocation) -> str:
        """Return the file path as primary value."""
        return invocation.write_file_path or ""

    def get_pattern_levels(self, invocation: ToolInvocation) -> tuple[str, str, str]:
        """Get 3-level path patterns (same as Read)."""
        path = invocation.write_file_path or ""
        if not path:
            return ("", "", "")

        # Reuse same logic as ReadAdapter
        parts = path.split("/")
        if path.startswith("/") and len(parts) >= 4:
            level1 = "/".join(parts[:4]) + "/"
        elif path.startswith("/") and len(parts) >= 3:
            level1 = "/".join(parts[:3]) + "/"
        else:
            level1 = parts[0] if parts else ""

        if path.startswith("/") and len(parts) >= 5:
            level2 = "/".join(parts[:5]) + "/"
        elif path.startswith("/") and len(parts) >= 4:
            level2 = "/".join(parts[:4]) + "/"
        else:
            level2 = level1

        _, ext = os.path.splitext(path)
        level3 = ext if ext else "(no extension)"

        return (level1, level2, level3)


class EditAdapter(ToolAdapter):
    """Adapter for Edit tool invocations."""

    def extract(self, block: dict, base_metadata: dict, options: ExtractionOptions) -> ToolInvocation:
        """Extract Edit-specific fields."""
        tool_input = block.get("input", {})
        old_string = tool_input.get("old_string", "")
        new_string = tool_input.get("new_string", "")

        old_preview = None
        new_preview = None
        if options.include_content_previews:
            if old_string:
                old_preview = self.truncate_preview(old_string, options.preview_length)
            if new_string:
                new_preview = self.truncate_preview(new_string, options.preview_length)

        return ToolInvocation(
            **base_metadata,
            tool_name="Edit",
            tool_use_id=block.get("id"),
            edit_file_path=tool_input.get("file_path"),
            edit_old_string_preview=old_preview,
            edit_new_string_preview=new_preview,
            edit_replace_all=tool_input.get("replace_all"),
        )

    def get_primary_value(self, invocation: ToolInvocation) -> str:
        """Return the file path as primary value."""
        return invocation.edit_file_path or ""

    def get_pattern_levels(self, invocation: ToolInvocation) -> tuple[str, str, str]:
        """Get 3-level path patterns (same as Read)."""
        path = invocation.edit_file_path or ""
        if not path:
            return ("", "", "")

        parts = path.split("/")
        if path.startswith("/") and len(parts) >= 4:
            level1 = "/".join(parts[:4]) + "/"
        elif path.startswith("/") and len(parts) >= 3:
            level1 = "/".join(parts[:3]) + "/"
        else:
            level1 = parts[0] if parts else ""

        if path.startswith("/") and len(parts) >= 5:
            level2 = "/".join(parts[:5]) + "/"
        elif path.startswith("/") and len(parts) >= 4:
            level2 = "/".join(parts[:4]) + "/"
        else:
            level2 = level1

        _, ext = os.path.splitext(path)
        level3 = ext if ext else "(no extension)"

        return (level1, level2, level3)
