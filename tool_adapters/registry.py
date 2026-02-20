"""Tool adapter registry and factory."""

from __future__ import annotations

from .base import ToolAdapter
from .bash import BashAdapter
from .file_ops import ReadAdapter, WriteAdapter, EditAdapter
from .search import GrepAdapter, GlobAdapter
from .tasks import TaskAdapter, TodoWriteAdapter
from .special import SpecialToolAdapter, GenericAdapter


def create_adapter_registry() -> dict[str, ToolAdapter]:
    """
    Create and return the tool adapter registry.

    Maps tool names to their adapter instances.
    """
    registry = {}

    # File operations
    registry["Bash"] = BashAdapter()
    registry["Read"] = ReadAdapter()
    registry["Write"] = WriteAdapter()
    registry["Edit"] = EditAdapter()

    # Search
    registry["Grep"] = GrepAdapter()
    registry["Glob"] = GlobAdapter()

    # Task management
    registry["TaskCreate"] = TaskAdapter()
    registry["TaskUpdate"] = TaskAdapter()
    registry["TaskList"] = TaskAdapter()
    registry["TaskGet"] = TaskAdapter()
    registry["TaskOutput"] = TaskAdapter()
    registry["TodoWrite"] = TodoWriteAdapter()

    # Special tools
    registry["Skill"] = SpecialToolAdapter()
    registry["WebSearch"] = SpecialToolAdapter()
    registry["WebFetch"] = SpecialToolAdapter()
    registry["AskUserQuestion"] = SpecialToolAdapter()
    registry["EnterPlanMode"] = SpecialToolAdapter()
    registry["ExitPlanMode"] = SpecialToolAdapter()

    # NotebookEdit
    registry["NotebookEdit"] = SpecialToolAdapter()

    # Task tool (main Task invocation)
    registry["Task"] = SpecialToolAdapter()

    # TaskStop
    registry["TaskStop"] = SpecialToolAdapter()

    return registry


def get_adapter(tool_name: str, registry: dict[str, ToolAdapter]) -> ToolAdapter:
    """
    Get adapter for a tool name, falling back to GenericAdapter for unknown tools.

    Args:
        tool_name: Name of the tool
        registry: Adapter registry

    Returns:
        ToolAdapter instance for the tool
    """
    if tool_name in registry:
        return registry[tool_name]

    # Fallback to generic adapter
    return GenericAdapter()
