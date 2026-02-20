"""Task management tool adapters."""

from .base import ToolAdapter, ToolInvocation, ExtractionOptions


class TaskAdapter(ToolAdapter):
    """Adapter for Task tool invocations (TaskCreate, TaskUpdate, TaskList, TaskGet, TaskOutput)."""

    def extract(self, block: dict, base_metadata: dict, options: ExtractionOptions) -> ToolInvocation:
        """Extract Task-specific fields."""
        tool_input = block.get("input", {})
        tool_name = block.get("name", "Task")

        # Determine operation type from tool name
        operation = None
        if tool_name == "TaskCreate":
            operation = "create"
        elif tool_name == "TaskUpdate":
            operation = "update"
        elif tool_name == "TaskList":
            operation = "list"
        elif tool_name == "TaskGet":
            operation = "get"
        elif tool_name == "TaskOutput":
            operation = "output"

        subject = tool_input.get("subject")
        description = tool_input.get("description", "")
        description_preview = None
        if options.include_content_previews and description:
            description_preview = self.truncate_preview(description, options.preview_length)

        return ToolInvocation(
            **base_metadata,
            tool_name=tool_name,
            tool_use_id=block.get("id"),
            task_subject=subject,
            task_description_preview=description_preview,
            task_id=tool_input.get("taskId"),
            task_status=tool_input.get("status"),
            task_operation=operation,
        )

    def get_primary_value(self, invocation: ToolInvocation) -> str:
        """Return the task subject or operation as primary value."""
        if invocation.task_subject:
            return invocation.task_subject
        return invocation.task_operation or ""

    def get_pattern_levels(self, invocation: ToolInvocation) -> tuple[str, str, str]:
        """
        Get 3-level task patterns.

        Level 1: Operation type (create, update, list, get)
        Level 2: Status (if applicable)
        Level 3: Subject category (extracted from subject text)
        """
        operation = invocation.task_operation or "unknown"
        status = invocation.task_status or "(no status)"

        # Extract subject category (first 2 words)
        subject = invocation.task_subject or ""
        if subject:
            words = subject.split()
            category = " ".join(words[:2]) if len(words) >= 2 else subject
        else:
            category = "(no subject)"

        return (operation, status, category)


class TodoWriteAdapter(ToolAdapter):
    """Adapter for TodoWrite tool invocations."""

    def extract(self, block: dict, base_metadata: dict, options: ExtractionOptions) -> ToolInvocation:
        """Extract TodoWrite-specific fields."""
        tool_input = block.get("input", {})
        content = tool_input.get("content", "")

        preview = None
        if options.include_content_previews and content:
            preview = self.truncate_preview(content, options.preview_length)

        return ToolInvocation(
            **base_metadata,
            tool_name="TodoWrite",
            tool_use_id=block.get("id"),
            todo_content_preview=preview,
        )

    def get_primary_value(self, invocation: ToolInvocation) -> str:
        """Return the todo content preview as primary value."""
        return invocation.todo_content_preview or ""

    def get_pattern_levels(self, invocation: ToolInvocation) -> tuple[str, str, str]:
        """
        Get 3-level todo patterns.

        Since todos are freeform, we extract:
        Level 1: First word (usually action verb)
        Level 2: First two words
        Level 3: First line
        """
        content = invocation.todo_content_preview or ""
        if not content:
            return ("", "", "")

        lines = content.split("\n")
        first_line = lines[0] if lines else ""

        words = first_line.split()
        level1 = words[0] if words else ""
        level2 = " ".join(words[:2]) if len(words) >= 2 else first_line
        level3 = first_line

        return (level1, level2, level3)
