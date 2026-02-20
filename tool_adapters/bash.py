"""Bash tool adapter."""

from __future__ import annotations

import json

from .base import ExtractionOptions, ToolAdapter, ToolInvocation


class BashAdapter(ToolAdapter):
    """Adapter for Bash tool invocations."""

    def extract(self, block: dict, base_metadata: dict, options: ExtractionOptions) -> ToolInvocation:
        """Extract Bash-specific fields."""
        tool_input = block.get("input", {})

        return ToolInvocation(
            **base_metadata,
            tool_name="Bash",
            tool_use_id=block.get("id"),
            bash_command=tool_input.get("command"),
            bash_description=tool_input.get("description"),
            bash_timeout=tool_input.get("timeout"),
        )

    def get_primary_value(self, invocation: ToolInvocation) -> str:
        """Return the bash command as primary value."""
        return invocation.bash_command or ""

    def get_pattern_levels(self, invocation: ToolInvocation) -> tuple[str, str, str]:
        """
        Get 3-level command patterns.

        Level 1: Base command (first word)
        Level 2: Command + first arg/flag (first 2 words)
        Level 3: Command + first 2 args/flags (first 3 words)
        """
        cmd = invocation.bash_command or ""
        if not cmd:
            return ("", "", "")

        # Preserve single quotes in command
        parts = cmd.split()
        if not parts:
            return ("", "", "")

        # Level 1: Base command
        level1 = parts[0] + " *"

        # Level 2: Command + first arg (2 words)
        if len(parts) >= 2:
            level2 = " ".join(parts[:2]) + " *"
        else:
            level2 = cmd

        # Level 3: Command + first 2 args (3 words)
        if len(parts) >= 3:
            level3 = " ".join(parts[:3]) + " *"
        elif len(parts) == 2:
            level3 = cmd
        else:
            level3 = cmd

        return (level1, level2, level3)
