"""Special and generic tool adapters."""

import json
from .base import ToolAdapter, ToolInvocation, ExtractionOptions


class SpecialToolAdapter(ToolAdapter):
    """
    Adapter for special workflow tools.

    Handles: Skill, WebSearch, WebFetch, AskUserQuestion, EnterPlanMode, ExitPlanMode, etc.
    """

    def extract(self, block: dict, base_metadata: dict, options: ExtractionOptions) -> ToolInvocation:
        """Extract special tool fields."""
        tool_input = block.get("input", {})
        tool_name = block.get("name", "Unknown")

        # Extract tool-specific fields
        skill_name = None
        websearch_query = None
        ask_question_preview = None

        if tool_name == "Skill":
            skill_name = tool_input.get("skill")
        elif tool_name == "WebSearch":
            websearch_query = tool_input.get("query")
        elif tool_name == "WebFetch":
            websearch_query = tool_input.get("url")  # Reuse field
        elif tool_name == "AskUserQuestion":
            questions = tool_input.get("questions", [])
            if questions and options.include_content_previews:
                # Extract first question
                first_q = questions[0].get("question", "") if questions else ""
                ask_question_preview = self.truncate_preview(first_q, options.preview_length)

        return ToolInvocation(
            **base_metadata,
            tool_name=tool_name,
            tool_use_id=block.get("id"),
            skill_name=skill_name,
            websearch_query=websearch_query,
            ask_question_preview=ask_question_preview,
        )

    def get_primary_value(self, invocation: ToolInvocation) -> str:
        """Return tool-specific primary value."""
        if invocation.skill_name:
            return invocation.skill_name
        if invocation.websearch_query:
            return invocation.websearch_query
        if invocation.ask_question_preview:
            return invocation.ask_question_preview
        return invocation.tool_name

    def get_pattern_levels(self, invocation: ToolInvocation) -> tuple[str, str, str]:
        """
        Get 3-level patterns for special tools.

        Level 1: Tool name
        Level 2: Operation type or primary value
        Level 3: Subtype or category
        """
        tool_name = invocation.tool_name
        primary = self.get_primary_value(invocation)

        # Level 2: Extract first word or category
        words = primary.split()
        level2 = words[0] if words else primary

        # Level 3: More specific
        level3 = " ".join(words[:2]) if len(words) >= 2 else primary

        return (tool_name, level2, level3)


class GenericAdapter(ToolAdapter):
    """
    Fallback adapter for unknown or future tool types.

    Stores raw input JSON for analysis.
    """

    def extract(self, block: dict, base_metadata: dict, options: ExtractionOptions) -> ToolInvocation:
        """Extract generic tool fields, storing raw input."""
        tool_input = block.get("input", {})
        tool_name = block.get("name", "Unknown")

        # Store raw input as JSON string
        raw_input = json.dumps(tool_input, separators=(',', ':'))
        if options.include_content_previews:
            raw_input = self.truncate_preview(raw_input, options.preview_length * 2)  # Longer for JSON

        return ToolInvocation(
            **base_metadata,
            tool_name=tool_name,
            tool_use_id=block.get("id"),
            raw_input_json=raw_input,
        )

    def get_primary_value(self, invocation: ToolInvocation) -> str:
        """Return tool name for generic tools."""
        return invocation.tool_name

    def get_pattern_levels(self, invocation: ToolInvocation) -> tuple[str, str, str]:
        """
        Get 3-level patterns for generic tools.

        Just use tool name at all levels since we don't know structure.
        """
        tool_name = invocation.tool_name
        return (tool_name, tool_name, tool_name)
