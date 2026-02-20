"""Search tool adapters (Grep, Glob)."""

from .base import ToolAdapter, ToolInvocation, ExtractionOptions


class GrepAdapter(ToolAdapter):
    """Adapter for Grep tool invocations."""

    def extract(self, block: dict, base_metadata: dict, options: ExtractionOptions) -> ToolInvocation:
        """Extract Grep-specific fields."""
        tool_input = block.get("input", {})

        # Combine context flags into single string
        flags = []
        if tool_input.get("-i"):
            flags.append("-i")
        if tool_input.get("-A"):
            flags.append(f"-A {tool_input['-A']}")
        if tool_input.get("-B"):
            flags.append(f"-B {tool_input['-B']}")
        if tool_input.get("-C"):
            flags.append(f"-C {tool_input['-C']}")
        if tool_input.get("context"):
            flags.append(f"-C {tool_input['context']}")
        if tool_input.get("multiline"):
            flags.append("-U")

        flags_str = " ".join(flags) if flags else None

        return ToolInvocation(
            **base_metadata,
            tool_name="Grep",
            tool_use_id=block.get("id"),
            grep_pattern=tool_input.get("pattern"),
            grep_path=tool_input.get("path"),
            grep_output_mode=tool_input.get("output_mode", "files_with_matches"),
            grep_flags=flags_str,
            grep_glob=tool_input.get("glob"),
            grep_type=tool_input.get("type"),
        )

    def get_primary_value(self, invocation: ToolInvocation) -> str:
        """Return the grep pattern as primary value."""
        return invocation.grep_pattern or ""

    def get_pattern_levels(self, invocation: ToolInvocation) -> tuple[str, str, str]:
        """
        Get 3-level grep patterns.

        Level 1: Output mode
        Level 2: Search path (directory)
        Level 3: Pattern complexity (simple vs regex)
        """
        output_mode = invocation.grep_output_mode or "files_with_matches"
        path = invocation.grep_path or "(cwd)"
        pattern = invocation.grep_pattern or ""

        # Classify pattern complexity
        if not pattern:
            complexity = "empty"
        elif any(c in pattern for c in r".*+?[]{}()|\^$"):
            complexity = "regex"
        else:
            complexity = "literal"

        return (output_mode, path, complexity)


class GlobAdapter(ToolAdapter):
    """Adapter for Glob tool invocations."""

    def extract(self, block: dict, base_metadata: dict, options: ExtractionOptions) -> ToolInvocation:
        """Extract Glob-specific fields."""
        tool_input = block.get("input", {})

        return ToolInvocation(
            **base_metadata,
            tool_name="Glob",
            tool_use_id=block.get("id"),
            glob_pattern=tool_input.get("pattern"),
            glob_path=tool_input.get("path"),
        )

    def get_primary_value(self, invocation: ToolInvocation) -> str:
        """Return the glob pattern as primary value."""
        return invocation.glob_pattern or ""

    def get_pattern_levels(self, invocation: ToolInvocation) -> tuple[str, str, str]:
        """
        Get 3-level glob patterns.

        Level 1: Pattern type (recursive vs simple)
        Level 2: Extension or file type
        Level 3: Search path
        """
        pattern = invocation.glob_pattern or ""
        path = invocation.glob_path or "(cwd)"

        # Classify pattern type
        if "**" in pattern:
            pattern_type = "recursive"
        elif "*" in pattern:
            pattern_type = "simple"
        else:
            pattern_type = "literal"

        # Extract extension if present
        if "." in pattern:
            # Get last extension-like part
            parts = pattern.split(".")
            extension = "." + parts[-1].rstrip("*}")
        else:
            extension = "(no extension)"

        return (pattern_type, extension, path)
