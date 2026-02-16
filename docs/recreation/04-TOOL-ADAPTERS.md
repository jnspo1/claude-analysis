# 04 - Tool Adapters Package

Comprehensive documentation of the `tool_adapters/` package -- the adapter layer that
normalizes heterogeneous Claude Code tool invocations into a single `ToolInvocation`
dataclass. This document contains everything needed to recreate the package from scratch.

---

## Table of Contents

1. [Purpose and Design](#1-purpose-and-design)
2. [Package Structure](#2-package-structure)
3. [Data Flow and Integration](#3-data-flow-and-integration)
4. [base.py -- Foundation Types](#4-basepy----foundation-types)
5. [bash.py -- BashAdapter](#5-bashpy----bashadapter)
6. [file_ops.py -- ReadAdapter, WriteAdapter, EditAdapter](#6-file_opspy----readadapter-writeadapter-editadapter)
7. [search.py -- GrepAdapter, GlobAdapter](#7-searchpy----grepadapter-globadapter)
8. [tasks.py -- TaskAdapter, TodoWriteAdapter](#8-taskspy----taskadapter-todowriteadapter)
9. [special.py -- SpecialToolAdapter, GenericAdapter](#9-specialpy----specialtooladapter-genericadapter)
10. [registry.py -- Factory and Lookup](#10-registrypy----factory-and-lookup)
11. [__init__.py -- Public API](#11-__init__py----public-api)
12. [Pattern Levels Reference](#12-pattern-levels-reference)
13. [Recreation Checklist](#13-recreation-checklist)

---

## 1. Purpose and Design

### Problem

Claude Code JSONL logs contain `tool_use` blocks for many different tools (Bash, Read, Write,
Edit, Grep, Glob, Task variants, WebSearch, Skill, etc.). Each tool has a completely
different `input` schema. Without an adapter layer, every parser must contain a sprawling
`if/elif` tree that understands every tool's schema -- duplicated in each parser.

### Solution: Adapter Pattern

The `tool_adapters` package applies the **Adapter pattern** (also called the Strategy
pattern in this context):

1. A single `ToolInvocation` dataclass serves as the **universal output type** with
   optional fields for every tool.
2. A `ToolAdapter` abstract base class defines three operations every tool must support.
3. Concrete adapter classes (one per tool family) implement tool-specific extraction logic.
4. A `registry` maps tool names to adapter instances, with a `GenericAdapter` fallback for
   unknown tools.

Consumers (parsers, analyzers) never inspect raw `tool_use` blocks directly. They call
`get_adapter(tool_name, registry)` and delegate extraction.

### Key Benefits

- **Single Responsibility**: Each adapter knows only its own tool's schema.
- **Open/Closed**: Adding a new tool requires only a new adapter class and a registry entry.
- **Testability**: Each adapter can be unit-tested with a mock `block` dict.
- **Pattern Analysis**: The 3-level pattern hierarchy enables frequency analysis,
  permission simulation, and dashboard visualizations without tool-specific code.

---

## 2. Package Structure

```
tool_adapters/
    __init__.py       (27 lines)  -- re-exports all public names
    base.py           (134 lines) -- ExtractionOptions, ToolInvocation, ToolAdapter ABC
    bash.py           (62 lines)  -- BashAdapter
    file_ops.py       (172 lines) -- ReadAdapter, WriteAdapter, EditAdapter
    search.py         (115 lines) -- GrepAdapter, GlobAdapter
    tasks.py          (116 lines) -- TaskAdapter, TodoWriteAdapter
    special.py        (112 lines) -- SpecialToolAdapter, GenericAdapter
    registry.py       (73 lines)  -- create_adapter_registry(), get_adapter()
```

**No external dependencies.** The entire package uses only the Python standard library
(`abc`, `dataclasses`, `typing`, `json`, `os`).

---

## 3. Data Flow and Integration

### Where Adapters Sit in the Pipeline

```
JSONL files
    |
    v
Parser (single_pass_parser.py or extract_tool_usage.py)
    |  for each tool_use block:
    |    1. Extract base_metadata (timestamp, project, cwd, session_id, etc.)
    |    2. adapter = get_adapter(block["name"], registry)
    |    3. invocation = adapter.extract(block, base_metadata, options)
    |
    v
List[ToolInvocation]
    |
    v
Analyzers (patterns.py, permissions.py, summary.py)
    |  for each invocation:
    |    adapter.get_primary_value(invocation)
    |    adapter.get_pattern_levels(invocation)
    |
    v
Aggregated results (dashboards, CSV exports, permission configs)
```

### Consumers

| Consumer | What it does with adapters |
|---|---|
| `single_pass_parser.py` | Creates registry once, calls `get_adapter()` + `extract()` for every tool_use block found during single-pass JSONL scan |
| `extract_tool_usage.py` | Same pattern, used by CLI extraction scripts; also iterates invocations for CSV output |
| `session_parser.py` | Creates registry, passes `ExtractionOptions` to extraction loop |
| `app.py` | Creates registry at startup for the FastAPI service |
| `analyzers/patterns.py` | Calls `get_primary_value()` and `get_pattern_levels()` on invocations to build `PatternStats` |
| `analyzers/permissions.py` | Reads `ToolInvocation` fields for permission rule simulation |
| `analyzers/summary.py` | Reads `ToolInvocation` fields for summary statistics |

### Typical Calling Code

```python
from tool_adapters import create_adapter_registry, get_adapter, ExtractionOptions

adapters = create_adapter_registry()
options = ExtractionOptions(include_content_previews=True, preview_length=100)

# Inside a JSONL line-scanning loop:
for block in content:
    if block.get("type") == "tool_use":
        tool_name = block.get("name")
        if not tool_name:
            continue

        base_metadata = {
            "timestamp": timestamp,
            "project": project,
            "jsonl_path": str(jsonl_path),
            "lineno": lineno,
            "cwd": cwd,
            "session_id": session_id,
            "git_branch": git_branch,
        }

        adapter = get_adapter(tool_name, adapters)
        invocation = adapter.extract(block, base_metadata, options)
        # invocation is now a fully-populated ToolInvocation
```

---

## 4. base.py -- Foundation Types

This file defines the three foundational types that the entire package builds on. It
imports only `abc`, `dataclasses`, and `typing`.

### ExtractionOptions Dataclass

Controls how much detail adapters extract from tool_use blocks.

```python
from dataclasses import dataclass

@dataclass
class ExtractionOptions:
    """Configuration options for tool extraction."""
    include_content_previews: bool = True   # Whether to extract content snippets
    preview_length: int = 100               # Max chars for content previews
    verbose: bool = False                   # Print warnings to stderr on failures
```

**Usage notes:**
- `include_content_previews=False` suppresses all content truncation, making extraction
  faster and output smaller (useful for count-only analysis).
- `preview_length` controls the truncation point for `truncate_preview()`. Content longer
  than this gets `"..."` appended.
- `verbose=True` is used by CLI scripts; the FastAPI service runs with `verbose=False`.

### ToolInvocation Dataclass

The universal output type. Every tool invocation in the entire system is represented as
one of these. Fields are divided into two groups:

1. **Common metadata** (9 required fields) -- populated by the parser, passed to the
   adapter via `base_metadata`.
2. **Tool-specific fields** (30+ optional fields) -- populated by the adapter based on the
   tool type. Only the relevant fields are set; all others remain `None`.

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class ToolInvocation:
    """Unified representation of any tool invocation."""

    # ---- Common metadata (all tools) ----
    # These are positional (required) because every invocation has them.
    timestamp: Optional[str]       # ISO timestamp from JSONL line, or None
    project: str                   # Project name derived from JSONL path
    tool_name: str                 # Tool name (e.g., "Bash", "Read", "Grep")
    tool_use_id: Optional[str]     # Unique block ID from Claude API
    jsonl_path: str                # Absolute path to source JSONL file
    lineno: int                    # Line number within JSONL file
    cwd: Optional[str]            # Working directory at time of invocation
    session_id: Optional[str]     # Session identifier
    git_branch: Optional[str]     # Git branch if detectable

    # ---- Tool-specific fields (all Optional, default None) ----

    # Bash
    bash_command: Optional[str] = None         # The shell command string
    bash_description: Optional[str] = None     # Human description of command
    bash_timeout: Optional[int] = None         # Timeout in milliseconds

    # Read
    read_file_path: Optional[str] = None       # Absolute path to file being read
    read_offset: Optional[int] = None          # Line offset (for partial reads)
    read_limit: Optional[int] = None           # Line limit (for partial reads)
    read_pages: Optional[str] = None           # Page range for PDF files

    # Write
    write_file_path: Optional[str] = None      # Absolute path to file being written
    write_content_length: Optional[int] = None # Length of content in chars
    write_content_preview: Optional[str] = None # Truncated content preview

    # Edit
    edit_file_path: Optional[str] = None           # Absolute path to file being edited
    edit_old_string_preview: Optional[str] = None  # Preview of string being replaced
    edit_new_string_preview: Optional[str] = None  # Preview of replacement string
    edit_replace_all: Optional[bool] = None        # Whether replace_all flag is set

    # Grep
    grep_pattern: Optional[str] = None         # Regex search pattern
    grep_path: Optional[str] = None            # Directory/file to search
    grep_output_mode: Optional[str] = None     # files_with_matches, content, count
    grep_flags: Optional[str] = None           # Combined flag string (e.g., "-i -A 3")
    grep_glob: Optional[str] = None            # File glob filter (e.g., "*.py")
    grep_type: Optional[str] = None            # File type filter (e.g., "py")

    # Glob
    glob_pattern: Optional[str] = None         # Glob pattern (e.g., "**/*.ts")
    glob_path: Optional[str] = None            # Base directory for glob

    # Task tools (TaskCreate, TaskUpdate, TaskList, TaskGet, TaskOutput)
    task_subject: Optional[str] = None              # Task subject line
    task_description_preview: Optional[str] = None  # Truncated task description
    task_id: Optional[str] = None                   # Task identifier (taskId)
    task_status: Optional[str] = None               # Task status value
    task_operation: Optional[str] = None            # create, update, list, get, output

    # TodoWrite
    todo_content_preview: Optional[str] = None      # Truncated todo content

    # Special tools
    skill_name: Optional[str] = None                # Skill tool: skill identifier
    websearch_query: Optional[str] = None           # WebSearch: query; WebFetch: URL
    ask_question_preview: Optional[str] = None      # AskUserQuestion: first question text

    # Generic fallback
    raw_input_json: Optional[str] = None            # JSON string of raw input (for unknowns)
```

**Design decisions:**
- Common metadata fields are positional (not keyword-only) so that `**base_metadata`
  unpacking works cleanly when combined with `tool_name=` and tool-specific kwargs.
- All tool-specific fields default to `None` so each adapter only needs to set its
  relevant fields.
- `websearch_query` is intentionally reused for both WebSearch (query text) and WebFetch
  (URL) to avoid adding a one-off field.

### ToolAdapter Abstract Base Class

The contract that every adapter must fulfill.

```python
from abc import ABC, abstractmethod

class ToolAdapter(ABC):
    """Base class for tool-specific extraction logic."""

    @abstractmethod
    def extract(self, block: dict, base_metadata: dict, options: ExtractionOptions) -> ToolInvocation:
        """
        Extract tool-specific fields from a tool_use content block.

        Args:
            block: The raw tool_use content block dict from JSONL. Contains at minimum
                   "type": "tool_use", "name": str, "id": str, "input": dict.
            base_metadata: Pre-built dict of common metadata fields (timestamp, project,
                           jsonl_path, lineno, cwd, session_id, git_branch). Does NOT
                           include tool_name or tool_use_id -- those are set by the adapter.
            options: ExtractionOptions controlling preview behavior.

        Returns:
            A fully populated ToolInvocation.
        """
        pass

    @abstractmethod
    def get_primary_value(self, invocation: ToolInvocation) -> str:
        """
        Return the single most important value for pattern analysis.

        Examples:
            Bash  -> the command string
            Read  -> the file path
            Grep  -> the search pattern
            Skill -> the skill name

        Returns:
            String suitable for frequency counting.
        """
        pass

    @abstractmethod
    def get_pattern_levels(self, invocation: ToolInvocation) -> tuple[str, str, str]:
        """
        Return a 3-level pattern hierarchy for this invocation.

        Level 1 is the broadest grouping, Level 3 is the most specific.
        The exact semantics depend on the tool type (see per-adapter docs below).

        Returns:
            Tuple of (level1, level2, level3) strings.
        """
        pass

    def truncate_preview(self, text: str, length: int = 100) -> str:
        """
        Helper to truncate text to a preview length.

        Strips leading/trailing whitespace first. If the stripped text is
        longer than `length`, truncates and appends "...".

        Returns empty string if text is falsy.
        """
        if not text:
            return ""
        text = text.strip()
        if len(text) <= length:
            return text
        return text[:length] + "..."
```

**Important implementation detail:** `truncate_preview` is a concrete (non-abstract)
method on the base class. All adapters inherit it and use it for content preview fields.
The `length` parameter defaults to 100, which matches `ExtractionOptions.preview_length`.
Callers pass `options.preview_length` explicitly.

---

## 5. bash.py -- BashAdapter

Handles Bash tool invocations. Imports `json` (though it does not use it in the current
implementation -- a leftover from development) and the base types.

### Extraction

Reads three fields from `block["input"]`:

| Input Field | ToolInvocation Field | Type | Notes |
|---|---|---|---|
| `command` | `bash_command` | `str` | The shell command string |
| `description` | `bash_description` | `str` | Human-readable description |
| `timeout` | `bash_timeout` | `int` | Timeout in milliseconds |

```python
class BashAdapter(ToolAdapter):
    def extract(self, block: dict, base_metadata: dict, options: ExtractionOptions) -> ToolInvocation:
        tool_input = block.get("input", {})
        return ToolInvocation(
            **base_metadata,
            tool_name="Bash",
            tool_use_id=block.get("id"),
            bash_command=tool_input.get("command"),
            bash_description=tool_input.get("description"),
            bash_timeout=tool_input.get("timeout"),
        )
```

### Primary Value

Returns `bash_command` (the full command string), or empty string if None.

### Pattern Levels

Splits the command on whitespace and builds progressively wider prefixes:

| Level | Description | Example for `git commit -m "fix"` |
|---|---|---|
| Level 1 | First word + ` *` | `git *` |
| Level 2 | First 2 words + ` *` | `git commit *` |
| Level 3 | First 3 words + ` *` | `git commit -m *` |

**Edge cases:**
- Empty or None command: returns `("", "", "")`.
- Single-word command (e.g., `ls`): Level 2 and Level 3 both equal the full command
  (no ` *` suffix).
- Two-word command (e.g., `git status`): Level 3 equals the full command.

```python
def get_pattern_levels(self, invocation: ToolInvocation) -> tuple[str, str, str]:
    cmd = invocation.bash_command or ""
    if not cmd:
        return ("", "", "")

    parts = cmd.split()
    if not parts:
        return ("", "", "")

    level1 = parts[0] + " *"

    if len(parts) >= 2:
        level2 = " ".join(parts[:2]) + " *"
    else:
        level2 = cmd

    if len(parts) >= 3:
        level3 = " ".join(parts[:3]) + " *"
    elif len(parts) == 2:
        level3 = cmd
    else:
        level3 = cmd

    return (level1, level2, level3)
```

---

## 6. file_ops.py -- ReadAdapter, WriteAdapter, EditAdapter

All three file operation adapters share the same `get_pattern_levels` logic for path-based
pattern analysis, but differ in what they extract.

### Shared Path Pattern Logic

Used identically by ReadAdapter, WriteAdapter, and EditAdapter (the code is duplicated in
each class rather than extracted to a helper -- a deliberate simplicity choice).

Given a file path like `/home/pi/python/claude_analysis/tool_adapters/base.py`:

| Level | Logic | Example |
|---|---|---|
| Level 1 | First 4 components of absolute path + `/` | `/home/pi/python/` |
| Level 2 | First 5 components of absolute path + `/` | `/home/pi/python/claude_analysis/` |
| Level 3 | File extension via `os.path.splitext()` | `.py` |

**Boundary behavior for absolute paths:**
- 4+ components: Level 1 = first 4, Level 2 = first 5 (or first 4 if only 4 total).
- 3 components: Level 1 = first 3, Level 2 = same as Level 1.
- Fewer: Level 1 = first component or empty.

**For relative paths:** Level 1 = first component string; Level 2 = same as Level 1.

**Extension:** If no extension, Level 3 = `"(no extension)"`.

```python
# Shared logic (shown once, duplicated in all three adapters):
def get_pattern_levels(self, invocation: ToolInvocation) -> tuple[str, str, str]:
    path = invocation.read_file_path or ""  # or write_file_path / edit_file_path
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
```

### ReadAdapter

Extracts file read operations.

| Input Field | ToolInvocation Field | Type | Notes |
|---|---|---|---|
| `file_path` | `read_file_path` | `str` | Absolute path to file |
| `offset` | `read_offset` | `int` | Starting line number |
| `limit` | `read_limit` | `int` | Number of lines to read |
| `pages` | `read_pages` | `str` | PDF page range (e.g., "1-5") |

```python
class ReadAdapter(ToolAdapter):
    def extract(self, block: dict, base_metadata: dict, options: ExtractionOptions) -> ToolInvocation:
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
        return invocation.read_file_path or ""
```

**No content preview:** Read operations do not include content previews because the Read
tool's input is just metadata (path, offset, limit). The file content appears in the
tool_result block, which adapters do not process.

### WriteAdapter

Extracts file write operations. This is the first adapter that uses content previews.

| Input Field | ToolInvocation Field | Type | Notes |
|---|---|---|---|
| `file_path` | `write_file_path` | `str` | Absolute path to file |
| `content` | `write_content_length` | `int` | `len(content)` |
| `content` | `write_content_preview` | `str` | Truncated to `preview_length` |

```python
class WriteAdapter(ToolAdapter):
    def extract(self, block: dict, base_metadata: dict, options: ExtractionOptions) -> ToolInvocation:
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
        return invocation.write_file_path or ""
```

**Preview gating:** The content preview is only computed when
`options.include_content_previews` is `True` AND `content` is truthy. Otherwise
`write_content_preview` remains `None`. The `write_content_length` is always computed
(it is cheap and useful for analysis).

### EditAdapter

Extracts file edit (search-and-replace) operations. Has two content preview fields.

| Input Field | ToolInvocation Field | Type | Notes |
|---|---|---|---|
| `file_path` | `edit_file_path` | `str` | Absolute path to file |
| `old_string` | `edit_old_string_preview` | `str` | Truncated text being replaced |
| `new_string` | `edit_new_string_preview` | `str` | Truncated replacement text |
| `replace_all` | `edit_replace_all` | `bool` | Whether to replace all occurrences |

```python
class EditAdapter(ToolAdapter):
    def extract(self, block: dict, base_metadata: dict, options: ExtractionOptions) -> ToolInvocation:
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
        return invocation.edit_file_path or ""
```

**Note:** Both `old_string` and `new_string` are previewed independently. If
`include_content_previews` is False, both remain `None`.

---

## 7. search.py -- GrepAdapter, GlobAdapter

Search tool adapters. These have the most complex extraction (Grep) and the most
interesting pattern level classification.

### GrepAdapter

Extracts ripgrep-based search operations. The main complexity is combining multiple
boolean/numeric flags into a single `grep_flags` string.

| Input Field | ToolInvocation Field | Type | Notes |
|---|---|---|---|
| `pattern` | `grep_pattern` | `str` | Regex search pattern |
| `path` | `grep_path` | `str` | Search directory/file |
| `output_mode` | `grep_output_mode` | `str` | Default: `"files_with_matches"` |
| (computed) | `grep_flags` | `str` | Combined flag string or None |
| `glob` | `grep_glob` | `str` | File glob filter |
| `type` | `grep_type` | `str` | File type filter |

#### Flag Combination Logic

The adapter inspects six boolean/numeric input fields and combines them into a single
space-separated string:

```python
flags = []
if tool_input.get("-i"):                        # Case insensitive
    flags.append("-i")
if tool_input.get("-A"):                        # Lines after match
    flags.append(f"-A {tool_input['-A']}")
if tool_input.get("-B"):                        # Lines before match
    flags.append(f"-B {tool_input['-B']}")
if tool_input.get("-C"):                        # Context lines (alias)
    flags.append(f"-C {tool_input['-C']}")
if tool_input.get("context"):                   # Context lines (named param)
    flags.append(f"-C {tool_input['context']}")
if tool_input.get("multiline"):                 # Multiline mode
    flags.append("-U")

flags_str = " ".join(flags) if flags else None
```

**Important:** Both `-C` and `context` map to `-C` in the output string. If both are
present, both appear (this mirrors ripgrep accepting both forms). The `multiline` boolean
maps to `-U` (ripgrep's multiline flag).

If no flags are set, `grep_flags` is `None` (not an empty string).

#### Pattern Levels

| Level | Description | Example |
|---|---|---|
| Level 1 | `output_mode` | `"files_with_matches"` |
| Level 2 | `grep_path` (or `"(cwd)"` if None) | `"/home/pi/python/"` |
| Level 3 | Pattern complexity classification | `"regex"` or `"literal"` or `"empty"` |

**Complexity classification:**
- `"empty"` -- pattern is falsy.
- `"regex"` -- pattern contains any of: `. * + ? [ ] { } ( ) | \ ^ $`
- `"literal"` -- all other non-empty patterns.

```python
def get_pattern_levels(self, invocation: ToolInvocation) -> tuple[str, str, str]:
    output_mode = invocation.grep_output_mode or "files_with_matches"
    path = invocation.grep_path or "(cwd)"
    pattern = invocation.grep_pattern or ""

    if not pattern:
        complexity = "empty"
    elif any(c in pattern for c in r".*+?[]{}()|\^$"):
        complexity = "regex"
    else:
        complexity = "literal"

    return (output_mode, path, complexity)
```

### GlobAdapter

Extracts file pattern matching operations. Simple extraction, interesting pattern levels.

| Input Field | ToolInvocation Field | Type | Notes |
|---|---|---|---|
| `pattern` | `glob_pattern` | `str` | Glob pattern (e.g., `"**/*.py"`) |
| `path` | `glob_path` | `str` | Base directory for search |

#### Pattern Levels

| Level | Description | Example |
|---|---|---|
| Level 1 | Pattern type | `"recursive"`, `"simple"`, or `"literal"` |
| Level 2 | File extension extracted from pattern | `".py"`, `".ts"`, `"(no extension)"` |
| Level 3 | `glob_path` (or `"(cwd)"` if None) | `"/home/pi/python/"` |

**Pattern type classification:**
- `"recursive"` -- pattern contains `**`
- `"simple"` -- pattern contains `*` but not `**`
- `"literal"` -- no wildcards

**Extension extraction:**
Splits the pattern on `"."`, takes the last segment, and strips trailing `*` and `}`
characters. For example:
- `"**/*.py"` -> splits to `["**/*", "py"]` -> `".py"`
- `"**/*.{ts,tsx}"` -> splits to `["**/*", "{ts,tsx}"]` -> `".{ts,tsx"` (strips `}`) -> `".{ts,tsx"`
- `"Makefile"` -> no `"."` -> `"(no extension)"`

```python
def get_pattern_levels(self, invocation: ToolInvocation) -> tuple[str, str, str]:
    pattern = invocation.glob_pattern or ""
    path = invocation.glob_path or "(cwd)"

    if "**" in pattern:
        pattern_type = "recursive"
    elif "*" in pattern:
        pattern_type = "simple"
    else:
        pattern_type = "literal"

    if "." in pattern:
        parts = pattern.split(".")
        extension = "." + parts[-1].rstrip("*}")
    else:
        extension = "(no extension)"

    return (pattern_type, extension, path)
```

---

## 8. tasks.py -- TaskAdapter, TodoWriteAdapter

Adapters for Claude Code's task management tools (subagent tasks and todo lists).

### TaskAdapter

Handles five tool names with a single adapter class: `TaskCreate`, `TaskUpdate`,
`TaskList`, `TaskGet`, `TaskOutput`. The operation type is derived from the tool name.

| Input Field | ToolInvocation Field | Type | Notes |
|---|---|---|---|
| (from tool name) | `task_operation` | `str` | `"create"`, `"update"`, `"list"`, `"get"`, `"output"` |
| `subject` | `task_subject` | `str` | Task subject line |
| `description` | `task_description_preview` | `str` | Truncated description |
| `taskId` | `task_id` | `str` | Task identifier |
| `status` | `task_status` | `str` | Task status |

**Operation mapping:**

```python
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
```

**Critical detail:** The adapter preserves the original `tool_name` (e.g., `"TaskCreate"`)
in `ToolInvocation.tool_name`, not a normalized name. The `task_operation` field holds the
normalized lowercase operation.

#### Primary Value

Returns `task_subject` if available, otherwise `task_operation`, otherwise empty string.

#### Pattern Levels

| Level | Description | Example |
|---|---|---|
| Level 1 | Operation type | `"create"` |
| Level 2 | Status (or `"(no status)"`) | `"completed"` |
| Level 3 | First 2 words of subject (or `"(no subject)"`) | `"Implement error"` |

```python
def get_pattern_levels(self, invocation: ToolInvocation) -> tuple[str, str, str]:
    operation = invocation.task_operation or "unknown"
    status = invocation.task_status or "(no status)"

    subject = invocation.task_subject or ""
    if subject:
        words = subject.split()
        category = " ".join(words[:2]) if len(words) >= 2 else subject
    else:
        category = "(no subject)"

    return (operation, status, category)
```

### TodoWriteAdapter

Handles the `TodoWrite` tool for writing todo list content.

| Input Field | ToolInvocation Field | Type | Notes |
|---|---|---|---|
| `content` | `todo_content_preview` | `str` | Truncated content preview |

```python
class TodoWriteAdapter(ToolAdapter):
    def extract(self, block: dict, base_metadata: dict, options: ExtractionOptions) -> ToolInvocation:
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
```

#### Primary Value

Returns `todo_content_preview` or empty string.

#### Pattern Levels

Since todo content is freeform text, patterns are extracted from words:

| Level | Description | Example for `"Fix the broken login flow"` |
|---|---|---|
| Level 1 | First word | `"Fix"` |
| Level 2 | First two words | `"Fix the"` |
| Level 3 | Entire first line | `"Fix the broken login flow"` |

```python
def get_pattern_levels(self, invocation: ToolInvocation) -> tuple[str, str, str]:
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
```

---

## 9. special.py -- SpecialToolAdapter, GenericAdapter

### SpecialToolAdapter

A single adapter class that handles a collection of workflow/meta tools. It uses the
tool name from the block to decide which fields to extract.

**Handled tool names:** `Skill`, `WebSearch`, `WebFetch`, `AskUserQuestion`,
`EnterPlanMode`, `ExitPlanMode`, `NotebookEdit`, `Task`, `TaskStop`.

#### Tool-Specific Extraction Logic

```python
def extract(self, block: dict, base_metadata: dict, options: ExtractionOptions) -> ToolInvocation:
    tool_input = block.get("input", {})
    tool_name = block.get("name", "Unknown")

    skill_name = None
    websearch_query = None
    ask_question_preview = None

    if tool_name == "Skill":
        skill_name = tool_input.get("skill")

    elif tool_name == "WebSearch":
        websearch_query = tool_input.get("query")

    elif tool_name == "WebFetch":
        websearch_query = tool_input.get("url")  # Reuses websearch_query field

    elif tool_name == "AskUserQuestion":
        questions = tool_input.get("questions", [])
        if questions and options.include_content_previews:
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
```

| Tool Name | Field Populated | Source |
|---|---|---|
| `Skill` | `skill_name` | `input.skill` |
| `WebSearch` | `websearch_query` | `input.query` |
| `WebFetch` | `websearch_query` | `input.url` (reuses field) |
| `AskUserQuestion` | `ask_question_preview` | `input.questions[0].question` (truncated) |
| `EnterPlanMode` | (none) | No tool-specific fields |
| `ExitPlanMode` | (none) | No tool-specific fields |
| `NotebookEdit` | (none) | No tool-specific fields |
| `Task` | (none) | No tool-specific fields (distinct from TaskCreate et al.) |
| `TaskStop` | (none) | No tool-specific fields |

**AskUserQuestion detail:** The input contains a `questions` array of objects. The adapter
extracts only the first question's `question` field and truncates it.

#### Primary Value

Returns the first non-None of: `skill_name`, `websearch_query`, `ask_question_preview`.
Falls back to `tool_name` if none are set.

#### Pattern Levels

| Level | Description | Example for Skill "commit" |
|---|---|---|
| Level 1 | Tool name | `"Skill"` |
| Level 2 | First word of primary value | `"commit"` |
| Level 3 | First 2 words of primary value | `"commit"` |

```python
def get_pattern_levels(self, invocation: ToolInvocation) -> tuple[str, str, str]:
    tool_name = invocation.tool_name
    primary = self.get_primary_value(invocation)

    words = primary.split()
    level2 = words[0] if words else primary
    level3 = " ".join(words[:2]) if len(words) >= 2 else primary

    return (tool_name, level2, level3)
```

### GenericAdapter

The fallback for any tool name not found in the registry. Stores the raw input as a
compact JSON string.

```python
class GenericAdapter(ToolAdapter):
    def extract(self, block: dict, base_metadata: dict, options: ExtractionOptions) -> ToolInvocation:
        tool_input = block.get("input", {})
        tool_name = block.get("name", "Unknown")

        raw_input = json.dumps(tool_input, separators=(',', ':'))
        if options.include_content_previews:
            raw_input = self.truncate_preview(raw_input, options.preview_length * 2)

        return ToolInvocation(
            **base_metadata,
            tool_name=tool_name,
            tool_use_id=block.get("id"),
            raw_input_json=raw_input,
        )
```

**Key detail:** The JSON string is serialized with compact separators (`(',', ':')`) to
minimize size, then truncated to `preview_length * 2` (200 chars by default) -- double
the normal preview length because JSON structure takes more space.

#### Primary Value

Returns `tool_name` (since there is no structured data to pick from).

#### Pattern Levels

All three levels return `tool_name`. Since the tool structure is unknown, no meaningful
hierarchy can be derived.

```python
def get_pattern_levels(self, invocation: ToolInvocation) -> tuple[str, str, str]:
    tool_name = invocation.tool_name
    return (tool_name, tool_name, tool_name)
```

---

## 10. registry.py -- Factory and Lookup

Two functions that wire everything together.

### create_adapter_registry()

Returns a `Dict[str, ToolAdapter]` mapping every known tool name to an adapter instance.
Each tool name gets its own instance (even when multiple names map to the same adapter
class, each gets a separate instance).

```python
from typing import Dict
from .base import ToolAdapter
from .bash import BashAdapter
from .file_ops import ReadAdapter, WriteAdapter, EditAdapter
from .search import GrepAdapter, GlobAdapter
from .tasks import TaskAdapter, TodoWriteAdapter
from .special import SpecialToolAdapter, GenericAdapter

def create_adapter_registry() -> Dict[str, ToolAdapter]:
    registry = {}

    # File operations
    registry["Bash"] = BashAdapter()
    registry["Read"] = ReadAdapter()
    registry["Write"] = WriteAdapter()
    registry["Edit"] = EditAdapter()

    # Search
    registry["Grep"] = GrepAdapter()
    registry["Glob"] = GlobAdapter()

    # Task management (5 separate TaskAdapter instances)
    registry["TaskCreate"] = TaskAdapter()
    registry["TaskUpdate"] = TaskAdapter()
    registry["TaskList"] = TaskAdapter()
    registry["TaskGet"] = TaskAdapter()
    registry["TaskOutput"] = TaskAdapter()
    registry["TodoWrite"] = TodoWriteAdapter()

    # Special tools (each gets its own SpecialToolAdapter instance)
    registry["Skill"] = SpecialToolAdapter()
    registry["WebSearch"] = SpecialToolAdapter()
    registry["WebFetch"] = SpecialToolAdapter()
    registry["AskUserQuestion"] = SpecialToolAdapter()
    registry["EnterPlanMode"] = SpecialToolAdapter()
    registry["ExitPlanMode"] = SpecialToolAdapter()
    registry["NotebookEdit"] = SpecialToolAdapter()
    registry["Task"] = SpecialToolAdapter()
    registry["TaskStop"] = SpecialToolAdapter()

    return registry
```

**Complete tool name list (21 entries):**
1. `Bash`
2. `Read`
3. `Write`
4. `Edit`
5. `Grep`
6. `Glob`
7. `TaskCreate`
8. `TaskUpdate`
9. `TaskList`
10. `TaskGet`
11. `TaskOutput`
12. `TodoWrite`
13. `Skill`
14. `WebSearch`
15. `WebFetch`
16. `AskUserQuestion`
17. `EnterPlanMode`
18. `ExitPlanMode`
19. `NotebookEdit`
20. `Task`
21. `TaskStop`

### get_adapter()

Simple lookup with GenericAdapter fallback.

```python
def get_adapter(tool_name: str, registry: Dict[str, ToolAdapter]) -> ToolAdapter:
    if tool_name in registry:
        return registry[tool_name]
    return GenericAdapter()
```

**Important:** `GenericAdapter()` is instantiated fresh on every miss. Since the adapter is
stateless this has no correctness impact, but it means high-frequency unknown tools create
many short-lived objects. In practice, unknown tools are rare.

---

## 11. __init__.py -- Public API

Re-exports all public names so consumers can write `from tool_adapters import ...` without
knowing the internal module structure.

```python
"""Tool adapter modules for extracting tool-specific fields from JSONL data."""

from .base import ToolAdapter, ExtractionOptions, ToolInvocation
from .bash import BashAdapter
from .file_ops import ReadAdapter, WriteAdapter, EditAdapter
from .search import GrepAdapter, GlobAdapter
from .tasks import TaskAdapter, TodoWriteAdapter
from .special import SpecialToolAdapter, GenericAdapter
from .registry import create_adapter_registry, get_adapter

__all__ = [
    'ToolAdapter',
    'ExtractionOptions',
    'ToolInvocation',
    'BashAdapter',
    'ReadAdapter',
    'WriteAdapter',
    'EditAdapter',
    'GrepAdapter',
    'GlobAdapter',
    'TaskAdapter',
    'TodoWriteAdapter',
    'SpecialToolAdapter',
    'GenericAdapter',
    'create_adapter_registry',
    'get_adapter',
]
```

**14 public names total:** 3 base types + 9 adapter classes + 2 registry functions.

---

## 12. Pattern Levels Reference

Quick-reference table of what each level means for every adapter:

| Adapter | Level 1 | Level 2 | Level 3 |
|---|---|---|---|
| BashAdapter | First word + ` *` | First 2 words + ` *` | First 3 words + ` *` |
| ReadAdapter | Top directory (`/a/b/c/`) | Subdirectory (`/a/b/c/d/`) | File extension (`.py`) |
| WriteAdapter | Top directory | Subdirectory | File extension |
| EditAdapter | Top directory | Subdirectory | File extension |
| GrepAdapter | Output mode | Search path | Complexity (regex/literal/empty) |
| GlobAdapter | Pattern type (recursive/simple/literal) | Extension | Search path |
| TaskAdapter | Operation (create/update/list/get/output) | Status | Subject first 2 words |
| TodoWriteAdapter | First word | First 2 words | Full first line |
| SpecialToolAdapter | Tool name | First word of primary value | First 2 words of primary value |
| GenericAdapter | Tool name | Tool name | Tool name |

---

## 13. Recreation Checklist

Follow this order to recreate the package from scratch:

1. **Create `tool_adapters/` directory** and an empty `__init__.py`.

2. **Write `base.py` first.** It has zero internal dependencies.
   - Define `ExtractionOptions` dataclass (3 fields with defaults).
   - Define `ToolInvocation` dataclass (9 positional common fields + 30 optional tool fields).
   - Define `ToolAdapter` ABC with 3 abstract methods + 1 concrete helper.

3. **Write `bash.py`.** Imports only from `base`.
   - Single class: `BashAdapter`.
   - `extract()`: reads `command`, `description`, `timeout` from input.
   - `get_pattern_levels()`: word-based splitting with ` *` suffixes.

4. **Write `file_ops.py`.** Imports `os` and `base`.
   - Three classes: `ReadAdapter`, `WriteAdapter`, `EditAdapter`.
   - All share identical path-based `get_pattern_levels()` logic (duplicated, not shared).
   - `WriteAdapter` and `EditAdapter` use `truncate_preview()` for content fields.

5. **Write `search.py`.** Imports only from `base`.
   - `GrepAdapter`: flag combination logic, regex complexity classification.
   - `GlobAdapter`: pattern type classification, extension extraction.

6. **Write `tasks.py`.** Imports only from `base`.
   - `TaskAdapter`: operation derived from tool name, handles 5 tool names.
   - `TodoWriteAdapter`: simple content preview extraction.

7. **Write `special.py`.** Imports `json` and `base`.
   - `SpecialToolAdapter`: branching on tool name for Skill/WebSearch/WebFetch/AskUserQuestion.
   - `GenericAdapter`: stores raw JSON input truncated to 2x preview length.

8. **Write `registry.py`.** Imports all adapter classes.
   - `create_adapter_registry()`: 21 entries mapping tool names to instances.
   - `get_adapter()`: dict lookup with GenericAdapter fallback.

9. **Update `__init__.py`.** Re-export all 14 public names.

10. **Verify integration.** The package is used by:
    - `single_pass_parser.py` -- calls `create_adapter_registry()` once, then
      `get_adapter()` + `adapter.extract()` per tool_use block.
    - `extract_tool_usage.py` -- same pattern for CLI extraction.
    - `analyzers/patterns.py` -- calls `get_primary_value()` and `get_pattern_levels()`
      to build `PatternStats`.

### Test Strategy

Each adapter can be tested independently with a mock block dict:

```python
from tool_adapters import BashAdapter, ExtractionOptions

adapter = BashAdapter()
options = ExtractionOptions()

block = {
    "type": "tool_use",
    "name": "Bash",
    "id": "test-123",
    "input": {
        "command": "git status",
        "description": "Check working tree",
        "timeout": 30000,
    },
}
base_metadata = {
    "timestamp": "2026-01-15T10:00:00Z",
    "project": "test-project",
    "jsonl_path": "/tmp/test.jsonl",
    "lineno": 42,
    "cwd": "/home/pi",
    "session_id": "sess-abc",
    "git_branch": "main",
}

invocation = adapter.extract(block, base_metadata, options)
assert invocation.bash_command == "git status"
assert invocation.bash_description == "Check working tree"
assert invocation.bash_timeout == 30000
assert adapter.get_primary_value(invocation) == "git status"
assert adapter.get_pattern_levels(invocation) == ("git *", "git status", "git status")
```
