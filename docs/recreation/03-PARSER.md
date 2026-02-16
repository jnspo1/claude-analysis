# Part 3: JSONL Parsing System

The parsing system converts raw Claude Code JSONL log files into structured session data for the dashboard. It is implemented across three files with distinct roles:

| File | Lines | Role | Used By |
|------|-------|------|---------|
| `extract_tool_usage.py` | 392 | Core JSONL iterator, file discovery, tool extraction | All parsers, CLI scripts |
| `single_pass_parser.py` | 454 | Optimized single-pass session parser | `app.py` (dashboard) |
| `session_parser.py` | 675 | Multi-pass parser with individual extraction functions | CLI scripts |

The single-pass parser is the production parser. It reads each JSONL file exactly once, extracting everything in a single loop. The multi-pass parser (`session_parser.py`) performs 5-7 separate passes per file but provides decomposed functions that the single-pass parser imports and reuses for helper logic.

---

## Table of Contents

1. [extract_tool_usage.py -- Core Utilities](#extract_tool_usagepy----core-utilities)
2. [single_pass_parser.py -- Dashboard Parser](#single_pass_parserpy----dashboard-parser)
3. [session_parser.py -- Multi-Pass Parser](#session_parserpy----multi-pass-parser)
4. [Shared Data Structures](#shared-data-structures)
5. [Dependency Graph](#dependency-graph)
6. [Algorithm Details](#algorithm-details)

---

## extract_tool_usage.py -- Core Utilities

**Path:** `/home/pi/python/claude_analysis/extract_tool_usage.py`

This file provides the foundational JSONL iteration and tool extraction primitives used by every parser in the system. It also serves as a standalone CLI tool for extracting tool usage to CSV.

### Imports

```python
from tool_adapters import (
    create_adapter_registry,
    get_adapter,
    ExtractionOptions,
    ToolInvocation,
)
from analyzers import (
    extract_patterns,
    analyze_permissions,
    write_summary,
)
```

### iter_jsonl(path: Path) -> Iterable[tuple[int, Optional[Dict[str, Any]]]]

The foundational JSONL iterator used by **all** parsers in the system.

```python
def iter_jsonl(path: Path) -> Iterable[tuple[int, Optional[Dict[str, Any]]]]:
```

**Behavior:**
1. Opens the file with UTF-8 encoding.
2. Enumerates lines starting at 1 (`enumerate(f, start=1)`).
3. Strips whitespace from each line; skips empty lines entirely.
4. Calls `json.loads()` on each non-empty line.
5. Yields `(lineno, parsed_dict)` on success.
6. Yields `(lineno, None)` for malformed JSON lines (catches `json.JSONDecodeError`).
7. Never crashes on bad input -- callers check for `None`.

**Used by:**
- `single_pass_parser.parse_session_single_pass()`
- `single_pass_parser._build_subagent_data_fast()`
- `session_parser.extract_first_prompt()`
- `session_parser.extract_user_turns()`
- `session_parser.count_turns()`
- `session_parser.extract_session_metadata()`
- `session_parser.extract_active_duration()`
- `session_parser.extract_subagent_info()`
- `extract_tool_usage.extract_tools_from_file()`

### find_jsonl_files(root: Path) -> List[Path]

```python
def find_jsonl_files(root: Path) -> List[Path]:
    return sorted(root.rglob("*.jsonl"))
```

Recursively finds all `.jsonl` files under `root` and returns them in sorted order. The default root is `~/.claude/projects`.

### derive_project_name(jsonl_path: Path, root: Path) -> str

```python
def derive_project_name(jsonl_path: Path, root: Path) -> str:
```

Derives the project identifier from a JSONL file's path relative to the root directory.

**Algorithm:**
1. Compute `jsonl_path.relative_to(root)`.
2. Return the first directory component (`rel_path.parts[0]`).
3. On `ValueError` (path not relative to root), fall back to `jsonl_path.parent.name`.

**Example:**
```
/home/pi/.claude/projects/-home-pi-TP/abc123.jsonl
  relative to /home/pi/.claude/projects/
  -> parts[0] = "-home-pi-TP"
```

The raw project name like `-home-pi-TP` is later converted to a readable form by `make_project_readable()` in session_parser.py.

### extract_tools_from_file(jsonl_path, project, adapters, options) -> tuple[List[ToolInvocation], int]

```python
def extract_tools_from_file(
    jsonl_path: Path,
    project: str,
    adapters: Dict[str, Any],
    options: ExtractionOptions
) -> tuple[List[ToolInvocation], int]:
```

Extracts all tool invocations from a single JSONL file.

**Parameters:**
- `jsonl_path` -- Path to the JSONL file
- `project` -- Project identifier string
- `adapters` -- Adapter registry from `create_adapter_registry()`
- `options` -- `ExtractionOptions` controlling preview length, verbosity, etc.

**Returns:** Tuple of `(invocations_list, bad_lines_count)`.

**Algorithm:**
1. Iterate with `iter_jsonl()`, skip `None` (increment `bad_lines`).
2. For each object, extract `obj["message"]["content"]`.
3. Skip if `content` is not a `list`.
4. Build `base_metadata` dict:
   ```python
   {
       "timestamp": obj.get("timestamp"),
       "project": project,
       "jsonl_path": str(jsonl_path),
       "lineno": lineno,
       "cwd": obj.get("cwd"),
       "session_id": obj.get("sessionId"),
       "git_branch": obj.get("gitBranch"),
   }
   ```
5. For each block in content where `block["type"] == "tool_use"`:
   - Get `tool_name` from `block["name"]` (skip if missing).
   - Look up the adapter via `get_adapter(tool_name, adapters)`.
   - Call `adapter.extract(block, base_metadata, options)`.
   - Append the resulting `ToolInvocation` to the list.
   - On exception: print warning if verbose, skip the block.

### CLI Output Functions

These are used only when `extract_tool_usage.py` runs as a CLI script:

- **`write_csv(invocations, output_path)`** -- Serializes `ToolInvocation` dataclass instances to CSV via `dataclasses.asdict()`.
- **`write_permission_yaml(insights, output_path)`** -- Writes suggested permission rules (allow/ask/deny) to YAML.
- **`parse_args()`** -- Argparse setup with `--root`, `--out-dir`, `--top`, `-v` flags.
- **`main()`** -- Orchestrates: find files, extract tools, analyze patterns, analyze permissions, write CSV + summary + YAML.

---

## single_pass_parser.py -- Dashboard Parser

**Path:** `/home/pi/python/claude_analysis/single_pass_parser.py`

The optimized parser used exclusively by `app.py` for dashboard builds. Reads each JSONL file exactly once, extracting tools, metadata, prompts, turns, subagent info, and timing in a single loop. This replaced the multi-pass approach which read each file 5-7 times.

### Imports from Other Modules

```python
from extract_tool_usage import iter_jsonl, derive_project_name
from session_parser import (
    _extract_text_from_content,
    _is_interrupt_message,
    _get_tool_detail,
    _get_file_path,
    _estimate_cost,
    build_tool_calls_list,
    categorize_bash_command,
    find_subagent_files,
    extract_active_duration,
    make_project_readable,
)
from tool_adapters import (
    create_adapter_registry,
    get_adapter,
    ExtractionOptions,
    ToolInvocation,
)
```

### Constants

```python
MAX_FILE_SIZE_MB = 100
```

Files exceeding this size (in MB) are skipped entirely to avoid memory issues on the Raspberry Pi (4GB RAM).

### parse_session_single_pass(jsonl_path, project, adapters, options, max_file_size_mb=100) -> Optional[Dict]

```python
def parse_session_single_pass(
    jsonl_path: Path,
    project: str,
    adapters: Dict,
    options: ExtractionOptions,
    max_file_size_mb: int = MAX_FILE_SIZE_MB,
) -> Optional[Dict]:
```

The main entry point for parsing a session. Returns `None` for empty, skipped, or oversized sessions.

**Parameters:**
- `jsonl_path` -- Path to the session JSONL file
- `project` -- Project identifier
- `adapters` -- Tool adapter registry
- `options` -- `ExtractionOptions` instance
- `max_file_size_mb` -- Skip files larger than this (default 100MB)

#### Phase 1: Size Check

```python
file_size = jsonl_path.stat().st_size
if file_size > max_file_size_mb * 1_048_576:
    return None
```

Returns `None` for files exceeding the size limit. Also returns `None` on `OSError` (file inaccessible).

#### Phase 2: Accumulator Initialization

All accumulators are initialized before the single-pass loop:

```python
# Tool invocations
invocations: List[ToolInvocation] = []

# Session metadata
slug, model, first_ts, last_ts = None, None, None, None
total_input_tokens = 0
total_output_tokens = 0
cache_creation_tokens = 0
cache_read_tokens = 0
active_duration_ms = 0
permission_mode = None
tool_errors = 0
tool_successes = 0
thinking_level = None
models_used: set = set()

# First prompt extraction
first_prompt = None
first_prompt_found = False

# User turns
user_turns: List[Dict[str, Any]] = []
turn_number = 0

# Subagent tracking
task_calls: Dict[str, Dict[str, str]] = {}    # tool_use_id -> {subagent_type, description}
agent_mapping: Dict[str, str] = {}              # parentToolUseID -> agentId
```

#### Phase 3: Single-Pass Loop

```python
for lineno, obj in iter_jsonl(jsonl_path):
```

Each JSONL record is processed for multiple data types in a single iteration. The extraction order within each iteration:

**1. Slug extraction:**
```python
if not slug and obj.get("slug"):
    slug = obj["slug"]
```
Takes the first non-None slug encountered. The slug is Claude Code's human-readable session identifier.

**2. Timestamp tracking:**
```python
ts = obj.get("timestamp")
if ts:
    if first_ts is None:
        first_ts = ts
    last_ts = ts
```
Tracks earliest and latest timestamps for session duration. Timestamps are ISO 8601 strings.

**3. Active duration:**
```python
if obj_type == "system" and obj.get("subtype") == "turn_duration":
    active_duration_ms += obj.get("durationMs", 0)
```
Claude Code emits `turn_duration` system records after each turn. The sum gives total active processing time (excludes user think time and idle periods).

**4. Permission mode:**
```python
if obj.get("permissionMode"):
    permission_mode = obj["permissionMode"]
```
Keeps the last-seen value. Common values: `"default"`, `"plan"`, `"bypasstool"`.

**5. Thinking level:**
```python
thinking_meta = obj.get("thinkingMetadata")
if thinking_meta and "level" in thinking_meta:
    thinking_level = thinking_meta["level"]
```
Keeps the last-seen value. Represents the thinking/reasoning level configured for the session.

**6. Subagent progress records:**
```python
if obj_type == "progress":
    data = obj.get("data", {})
    agent_id = data.get("agentId")
    parent_tool_use_id = obj.get("parentToolUseID")
    if agent_id and parent_tool_use_id and parent_tool_use_id not in agent_mapping:
        agent_mapping[parent_tool_use_id] = agent_id
```
Maps a Task tool's `parentToolUseID` to the spawned `agentId`. This is used later to associate subagent JSONL files with their parent Task invocations. Only the first mapping per `parentToolUseID` is kept.

**7. Model and token usage:**
```python
if msg.get("model"):
    models_used.add(msg["model"])
    if not model:
        model = msg["model"]

usage = msg.get("usage")
if usage:
    total_input_tokens += usage.get("input_tokens", 0)
    total_output_tokens += usage.get("output_tokens", 0)
    cache_creation_tokens += usage.get("cache_creation_input_tokens", 0)
    cache_read_tokens += usage.get("cache_read_input_tokens", 0)
```
The `model` field takes the first model seen; `models_used` tracks all unique models. Token counts are summed across all assistant messages.

**8. User message processing (role == "user"):**

This block handles both first-prompt extraction and user-turn tracking.

```python
text = _extract_text_from_content(content)
```

Messages are **skipped** if:
- `text` is falsy
- Text starts with `"<local-command"` (system-generated)
- Text starts with `"<command-"` (system-generated)
- Text length < 3 characters

For non-skipped messages:
- `turn_number` is incremented
- `_is_interrupt_message()` checks for interrupt markers
- **First prompt logic**: Strips leading XML tags using regex `r'^(<[^>]+>[\s\S]*?</[^>]+>\s*)+'`. If the cleaned text has length > 3, it becomes the first prompt. Falls back to the unstripped text if cleaning removes everything meaningful.
- **User turn recording**: Each turn is stored as:
  ```python
  {
      "text": display_text,       # max 300 chars, XML-stripped for non-interrupts
      "timestamp": ts,
      "is_interrupt": bool,
      "turn_number": int,
  }
  ```

**9. Content block processing (tool_use and tool_result):**

```python
if isinstance(content, list):
    base_metadata = {
        "timestamp": obj.get("timestamp"),
        "project": project,
        "jsonl_path": str(jsonl_path),
        "lineno": lineno,
        "cwd": obj.get("cwd"),
        "session_id": obj.get("sessionId"),
        "git_branch": obj.get("gitBranch"),
    }

    for block in content:
        if block_type == "tool_use":
            # Track Task tool calls for subagent mapping
            if tool_name == "Task":
                task_calls[tool_use_id] = {
                    "subagent_type": inp.get("subagent_type", ""),
                    "description": inp.get("description", ""),
                }
            # Extract via adapter
            adapter = get_adapter(tool_name, adapters)
            invocation = adapter.extract(block, base_metadata, options)
            invocations.append(invocation)

        elif block_type == "tool_result":
            if block.get("is_error"):
                tool_errors += 1
            else:
                tool_successes += 1
```

Task tool calls are tracked separately to build the subagent mapping. Tool results are counted for error/success statistics.

#### Phase 4: Post-Processing

After the loop completes, the accumulated data is transformed into the final return dict.

**Interrupt count:**
```python
interrupt_count = sum(1 for t in user_turns if t["is_interrupt"])
```

**Skip check:**
```python
if not invocations and not first_prompt:
    return None
```
Sessions with no tool calls and no user prompt are considered empty.

**Session ID:**
```python
session_id = jsonl_path.stem
```
The JSONL filename without extension (a UUID).

**Tool counts:**
```python
tool_counter = Counter(inv.tool_name for inv in invocations)
```

**File extensions and files touched:**
```python
file_extensions: Counter = Counter()
files_touched: Dict[str, Dict[str, int]] = {}
for inv in invocations:
    fpath = _get_file_path(inv)    # Returns path for Read/Write/Edit, None otherwise
    if fpath:
        ext = Path(fpath).suffix or "(no ext)"
        file_extensions[ext] += 1
        files_touched[fpath][inv.tool_name] += 1
```

**Bash command aggregation:**
```python
bash_cmds: Counter = Counter()
for inv in invocations:
    if inv.tool_name == "Bash" and inv.bash_command:
        bash_cmds[inv.bash_command.strip()] += 1
```

Top 50 commands are categorized via `categorize_bash_command()` and stored as:
```python
{
    "command": str,     # truncated to 200 chars
    "base": str,        # first word of command
    "count": int,
    "category": str,    # e.g. "Version Control", "Running Code"
}
```

**Tool calls list:**
```python
tool_calls = build_tool_calls_list(invocations)
```
Returns chronological list of `{seq, time, tool, detail, is_subagent}`.

**Prompt preview:**
```python
prompt_preview = first_prompt[:80] + "..." if len(first_prompt) > 80 else first_prompt
```

**Subagent info mapping:**
```python
subagent_info: Dict[str, Dict[str, str]] = {}
for tool_use_id, info in task_calls.items():
    agent_id = agent_mapping.get(tool_use_id)
    if agent_id:
        subagent_info[agent_id] = info
```
Combines Task tool call data with progress record mappings to associate agent IDs with their task descriptions and types.

**Subagent file processing:**
```python
subagent_files = find_subagent_files(jsonl_path)
for sa_path in subagent_files:
    sa_data = _build_subagent_data_fast(sa_path, project, adapters, options, subagent_info)
    if sa_data:
        subagents.append(sa_data)
```

**Total active duration:**
```python
total_active_duration_ms = active_duration_ms + sum(sa.get("active_duration_ms", 0) for sa in subagents)
```
Parent session active time plus all subagent active times.

**Cost estimation:**
```python
cost_estimate = _estimate_cost(
    total_input_tokens, total_output_tokens, cache_read_tokens, model,
    cache_creation_tokens=cache_creation_tokens,
)
```

#### Return Value

The function returns a dict with 26 keys. This is **the** critical data structure that flows through the entire system -- from parser to SQLite cache to API to dashboard.

```python
{
    "session_id": str,                    # JSONL filename stem (UUID)
    "slug": Optional[str],               # Human-readable session name from Claude Code
    "project": str,                       # Raw project directory name
    "first_prompt": Optional[str],        # Full text of first user message
    "prompt_preview": Optional[str],      # first_prompt[:80] + "..."
    "turn_count": int,                    # Number of user turns
    "start_time": Optional[str],          # ISO 8601 timestamp of first record
    "end_time": Optional[str],            # ISO 8601 timestamp of last record
    "model": Optional[str],              # First model used (e.g. "claude-sonnet-4-20250514")
    "total_tools": int,                   # len(invocations)
    "tool_counts": Dict[str, int],        # {"Bash": 42, "Read": 31, ...}
    "file_extensions": Dict[str, int],    # {".py": 15, ".md": 3, ...}
    "files_touched": Dict[str, Dict[str, int]],  # {"/path/file.py": {"Read": 2, "Edit": 1}}
    "bash_commands": List[Dict],          # [{command, base, count, category}], top 50
    "bash_category_summary": Dict[str, int],  # {"Version Control": 20, ...}
    "tool_calls": List[Dict],            # [{seq, time, tool, detail, is_subagent}]
    "user_turns": List[Dict],            # [{text, timestamp, is_interrupt, turn_number}]
    "interrupt_count": int,               # Count of user interruptions
    "tokens": {                           # Token usage totals
        "input": int,
        "output": int,
        "cache_creation": int,
        "cache_read": int,
    },
    "active_duration_ms": int,            # Parent session active time only
    "total_active_duration_ms": int,      # Parent + all subagent active time
    "permission_mode": Optional[str],     # Last-seen permission mode
    "tool_errors": int,                   # Count of tool_result with is_error=True
    "tool_successes": int,                # Count of tool_result with is_error=False
    "thinking_level": Optional[str],      # Reasoning level (e.g. "medium")
    "models_used": List[str],             # Sorted list of all model strings seen
    "cost_estimate": float,               # Estimated cost in USD
    "subagents": List[Dict],              # List of subagent data dicts
}
```

### _build_subagent_data_fast(sa_path, project, adapters, options, subagent_info) -> Optional[Dict]

```python
def _build_subagent_data_fast(
    sa_path: Path,
    project: str,
    adapters: Dict,
    options: ExtractionOptions,
    subagent_info: Dict[str, Dict[str, str]],
) -> Optional[Dict]:
```

Parses a single subagent JSONL file. Subagent files are small (typically a few hundred lines), so the overhead is minimal.

**Algorithm:**
1. Single pass over the subagent file with `iter_jsonl()`.
2. Extracts `active_duration_ms` from `turn_duration` system entries.
3. Finds the first real user message (skipping system/command/interrupt messages) as the description. Strips leading XML tags.
4. Extracts tool invocations from `tool_use` content blocks.
5. Returns `None` if no tool invocations were found.

**Agent ID derivation:**
```python
agent_id = sa_path.stem.replace("agent-", "")
```
For example, `agent-ad7c5cf.jsonl` yields agent ID `ad7c5cf`.

**Return value:**
```python
{
    "agent_id": str,                # Derived from filename
    "subagent_type": str,           # From parent's Task tool call (e.g. "code-fix")
    "task_description": str,        # From parent's Task tool description parameter
    "description": str,             # First user prompt in subagent file (max 200 chars)
    "tool_count": int,              # Total tool invocations
    "tool_counts": Dict[str, int],  # {"Bash": 5, "Edit": 3, ...}
    "tool_calls": List[Dict],       # [{seq, time, tool, detail, is_subagent=True}]
    "active_duration_ms": int,      # Subagent's own active processing time
}
```

---

## session_parser.py -- Multi-Pass Parser

**Path:** `/home/pi/python/claude_analysis/session_parser.py`

The original parser that makes 5-7 separate passes per file. Each function reads the entire JSONL independently. Still used by CLI scripts (`extract_tool_usage.py`, `extract_bash_commands.py`) and provides helper functions imported by `single_pass_parser.py`.

### Imports

```python
from extract_tool_usage import (
    iter_jsonl,
    find_jsonl_files,
    derive_project_name,
    extract_tools_from_file,
)
from tool_adapters import create_adapter_registry, ExtractionOptions, ToolInvocation
```

### _is_interrupt_message(text: str) -> bool

```python
def _is_interrupt_message(text: str) -> bool:
```

Checks if a message is a Claude Code interruption marker.

**Matches exactly:**
- `"[Request interrupted by user]"`
- `"[Request interrupted by user for tool use]"`

Strips whitespace before comparison.

### _extract_text_from_content(content) -> Optional[str]

```python
def _extract_text_from_content(content) -> Optional[str]:
```

Extracts plain text from message content, handling two formats:

1. **String content:** Returns directly.
2. **List-of-blocks content:** Collects text from string elements and from `{"type": "text", "text": "..."}` blocks. Joins with `"\n"`.
3. **Other types:** Returns `None`.

### extract_first_prompt(jsonl_path: Path) -> Optional[str]

```python
def extract_first_prompt(jsonl_path: Path) -> Optional[str]:
```

Finds the first real user message in a session file. This is one full pass over the file.

**Skip criteria (in order):**
1. `obj` is `None` (malformed JSON)
2. `msg.role != "user"`
3. No extractable text
4. Text starts with `"<local-command"` (system-generated messages)
5. Text starts with `"<command-"` (system-generated messages)
6. Text length < 3 characters
7. Message is an interrupt marker

**XML stripping:**
```python
cleaned = re.sub(r'^(<[^>]+>[\s\S]*?</[^>]+>\s*)+', '', stripped).strip()
```
This regex removes leading XML tag pairs like `<system-reminder>...</system-reminder>` that Claude Code prepends to user messages. If the cleaned text has length > 3, it is returned. Otherwise the original (unstripped) text is returned if it has length > 3.

Returns `None` if no qualifying message is found.

### extract_user_turns(jsonl_path: Path) -> List[Dict[str, Any]]

```python
def extract_user_turns(jsonl_path: Path) -> List[Dict[str, Any]]:
```

Extracts all user messages with metadata. One full pass over the file.

**Skip criteria:** Same as `extract_first_prompt()` (except interrupt messages are included, not skipped).

**For each qualifying message:**
1. Increment `turn_number`.
2. Check `_is_interrupt_message()`.
3. For non-interrupt messages, strip leading XML tags for display.
4. Truncate display text to 300 characters.

**Returns:**
```python
[
    {
        "text": str,            # Display text (max 300 chars, XML-stripped)
        "timestamp": Optional[str],
        "is_interrupt": bool,
        "turn_number": int,     # Sequential, starting at 1
    },
    ...
]
```

### count_turns(jsonl_path: Path) -> int

```python
def count_turns(jsonl_path: Path) -> int:
```

Counts all user messages (where `msg.role == "user"`). One full pass. This counts raw user messages without the filtering applied by `extract_user_turns()`.

### extract_session_metadata(jsonl_path: Path) -> Dict[str, Any]

```python
def extract_session_metadata(jsonl_path: Path) -> Dict[str, Any]:
```

Extracts session-level metadata in one full pass. Tracks:

- **slug**: First non-None `obj["slug"]`
- **model**: First `msg["model"]` seen
- **models_used**: Set of all unique model strings
- **first_ts / last_ts**: Earliest and latest timestamps
- **Token counts**: Summed from `msg["usage"]` dicts (`input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`)
- **active_duration_ms**: Sum of `durationMs` from `turn_duration` system entries
- **permission_mode**: Last-seen `obj["permissionMode"]`
- **thinking_level**: Last-seen `obj["thinkingMetadata"]["level"]`
- **tool_errors / tool_successes**: Counted from `tool_result` content blocks

**Returns:**
```python
{
    "slug": Optional[str],
    "model": Optional[str],
    "first_ts": Optional[str],
    "last_ts": Optional[str],
    "total_input_tokens": int,
    "total_output_tokens": int,
    "cache_creation_tokens": int,
    "cache_read_tokens": int,
    "active_duration_ms": int,
    "permission_mode": Optional[str],
    "tool_errors": int,
    "tool_successes": int,
    "thinking_level": Optional[str],
    "models_used": List[str],        # sorted
}
```

### extract_active_duration(jsonl_path: Path) -> int

```python
def extract_active_duration(jsonl_path: Path) -> int:
```

Sums `durationMs` from all `turn_duration` system entries. One full pass. Returns total milliseconds.

### find_subagent_files(jsonl_path: Path) -> List[Path]

```python
def find_subagent_files(jsonl_path: Path) -> List[Path]:
```

Locates subagent JSONL files for a session based on the directory convention:

```
<project_dir>/<session-uuid>.jsonl          (parent session)
<project_dir>/<session-uuid>/subagents/     (subagent directory)
  agent-<agent-id>.jsonl                    (subagent files)
```

**Algorithm:**
1. `session_dir = jsonl_path.parent / jsonl_path.stem`
2. `subagents_dir = session_dir / "subagents"`
3. If `subagents_dir` is not a directory, return `[]`.
4. Return `sorted(subagents_dir.glob("*.jsonl"))`.

### extract_subagent_info(jsonl_path: Path) -> Dict[str, Dict[str, str]]

```python
def extract_subagent_info(jsonl_path: Path) -> Dict[str, Dict[str, str]]:
```

Scans the **parent** session JSONL to build a mapping from agent IDs to their Task tool call metadata. One full pass.

**Two-phase extraction:**
1. **Task tool_use blocks** in assistant messages: Maps `tool_use_id` to `{subagent_type, description}` from the Task tool's input parameters.
2. **Progress records** (`obj.type == "progress"`): Maps `parentToolUseID` to `agentId` from `obj.data`. Only first mapping per `parentToolUseID` is kept.

**Combination:** Joins the two maps via `tool_use_id` / `parentToolUseID` to produce the final result.

**Returns:**
```python
{
    "agent-id-string": {
        "subagent_type": str,     # e.g. "code-fix", "session-reviewer"
        "description": str,        # Task description from parent
    },
    ...
}
```

### categorize_bash_command(command: str) -> str

```python
def categorize_bash_command(command: str) -> str:
```

Categorizes a bash command string into one of seven human-readable groups.

**Categories and their regex patterns:**

| Category | Pattern |
|----------|---------|
| Version Control | `^(git\|gh)\b` |
| Running Code | `^(python\|python3\|pip\|pip3\|node\|npm\|npx\|yarn\|pytest\|uvicorn\|mypy\|ruff\|black\|isort\|flake8\|pylint)\b` |
| Searching & Reading | `^(grep\|rg\|find\|fd\|ag\|ack\|ls\|cat\|head\|tail\|wc\|tree\|sort\|uniq\|tee\|stat\|du\|df)\b` |
| File Management | `^(mkdir\|rmdir\|rm\|mv\|cp\|chmod\|chown\|ln\|touch\|tar\|zip\|unzip\|gzip)\b` |
| Testing & Monitoring | `^(curl\|wget\|ssh\|scp\|rsync\|ping\|nc\|netstat\|ss\|ps\|kill\|pkill\|top\|htop\|lsof\|which\|whereis)\b` |
| Server & System | `^(systemctl\|journalctl\|service\|docker\|docker-compose\|nginx\|hostname\|uname\|date\|whoami\|env\|export\|echo\|printf\|sleep\|sed\|awk\|sqlite3)\b` |
| Other | (default fallback) |

**Algorithm for chained/complex commands:**

1. **Split on `&&` and `;`** to handle chained commands.
2. For each segment:
   a. **Handle pipes**: Take the first command in a pipe chain (`split("|")[0]`).
   b. **Strip `sudo`**: Remove `"sudo "` prefix.
   c. **Strip environment variables**: Remove leading `FOO=bar` assignments.
   d. **Skip `cd`**: Pure directory changes are skipped; move to next segment.
   e. **Handle `source` / `. `**: If the argument contains `"venv"` or `"activate"`, return `"Running Code"`. Otherwise return `"Server & System"`.
   f. **Extract basename from paths**: `./venv/bin/python` becomes `python` (via `rsplit("/", 1)[-1]`).
   g. **Match regex**: Test the extracted command against each category pattern.
   h. **Return first match** or `"Other"` if none match.

3. If all segments are `cd` or empty, return `"Other"`.

**Examples:**
```
"cd /foo && git status"         -> "Version Control" (cd skipped, git matched)
"sudo systemctl restart nginx"  -> "Server & System" (sudo stripped)
"FOO=bar python test.py"        -> "Running Code" (env var stripped)
"source venv/bin/activate"      -> "Running Code" (venv detected)
"./venv/bin/python script.py"   -> "Running Code" (path basename extracted)
"cat foo | grep bar"            -> "Searching & Reading" (first in pipe)
```

### _estimate_cost(input_tokens, output_tokens, cache_read_tokens, model, cache_creation_tokens=0) -> float

```python
def _estimate_cost(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    model: Optional[str],
    cache_creation_tokens: int = 0,
) -> float:
```

Estimates session cost in USD based on token usage and model pricing.

**Per-million-token rates:**

| Model | Input | Output | Cache Creation | Cache Read |
|-------|-------|--------|----------------|------------|
| Opus | $15.00 | $75.00 | $18.75 (125%) | $1.50 (10%) |
| Haiku | $0.80 | $4.00 | $1.00 (125%) | $0.08 (10%) |
| Sonnet (default) | $3.00 | $15.00 | $3.75 (125%) | $0.30 (10%) |

**Model detection:** Case-insensitive substring match on the model string. If `"opus"` is in the model name, use Opus rates. If `"haiku"`, use Haiku rates. Otherwise default to Sonnet.

**Formula:**
```
cost = (input * input_rate + output * output_rate
        + cache_creation * input_rate * 1.25
        + cache_read * input_rate * 0.10) / 1_000_000
```

Returns the cost rounded to 4 decimal places.

### _get_tool_detail(inv: ToolInvocation) -> str

```python
def _get_tool_detail(inv: ToolInvocation) -> str:
```

Returns a human-readable detail string for a tool invocation, used in the `tool_calls` list displayed in the dashboard.

| Tool Name | Detail Source | Truncation |
|-----------|-------------|------------|
| Bash | `inv.bash_command` | 200 chars |
| Read | `inv.read_file_path` | None |
| Write | `inv.write_file_path` | None |
| Edit | `inv.edit_file_path` | None |
| Grep | `"{pattern} in {path}"` or just pattern | None |
| Glob | `inv.glob_pattern` | None |
| Task | `inv.task_description_preview` or `inv.task_subject` | None |
| TaskCreate/TaskUpdate/TaskList/TaskGet/TaskOutput | `inv.task_subject` or `inv.task_operation` | None |
| WebSearch | `inv.websearch_query` | None |
| Skill | `inv.skill_name` | None |
| AskUserQuestion | `inv.ask_question_preview` | None |
| (other) | `inv.raw_input_json` | 150 chars |

### _get_file_path(inv: ToolInvocation) -> Optional[str]

```python
def _get_file_path(inv: ToolInvocation) -> Optional[str]:
```

Returns the file path for file-operation tools:

| Tool | Field |
|------|-------|
| Read | `inv.read_file_path` |
| Write | `inv.write_file_path` |
| Edit | `inv.edit_file_path` |
| (other) | `None` |

### build_tool_calls_list(invocations, is_subagent=False) -> List[Dict]

```python
def build_tool_calls_list(
    invocations: List[ToolInvocation], is_subagent: bool = False
) -> List[Dict]:
```

Converts a list of `ToolInvocation` objects into serializable dicts for the dashboard.

**Returns:**
```python
[
    {
        "seq": int,               # 1-based sequence number
        "time": str,              # Timestamp or ""
        "tool": str,              # Tool name
        "detail": str,            # From _get_tool_detail()
        "is_subagent": bool,      # True if from a subagent file
    },
    ...
]
```

### build_session_data(jsonl_path, project, adapters, options) -> Optional[Dict]

```python
def build_session_data(
    jsonl_path: Path,
    project: str,
    adapters: Dict,
    options: ExtractionOptions,
) -> Optional[Dict]:
```

The multi-pass equivalent of `parse_session_single_pass()`. Makes 5-7 separate passes over the file:

1. `extract_tools_from_file()` -- tool invocations (pass 1)
2. `extract_session_metadata()` -- slug, model, tokens, timing (pass 2)
3. `extract_first_prompt()` -- first user message (pass 3)
4. `count_turns()` -- turn count (pass 4)
5. `extract_user_turns()` -- all user messages (pass 5)
6. `extract_subagent_info()` -- subagent mapping (pass 6, if subagent files exist)
7. For each subagent: `extract_tools_from_file()` + `extract_first_prompt()` + `extract_active_duration()` (passes 7+)

Returns the **same dict shape** as `parse_session_single_pass()`. This ensures both parsers are interchangeable from the perspective of `cache_db.py` and `app.py`.

### build_subagent_data(sa_path, project, adapters, options, subagent_info) -> Optional[Dict]

```python
def build_subagent_data(
    sa_path: Path,
    project: str,
    adapters: Dict,
    options: ExtractionOptions,
    subagent_info: Optional[Dict[str, Dict[str, str]]] = None,
) -> Optional[Dict]:
```

Multi-pass subagent parser. Makes 3 passes per subagent file:
1. `extract_tools_from_file()` -- tool invocations
2. `extract_first_prompt()` -- description
3. `extract_active_duration()` -- active time

Returns the same shape as `_build_subagent_data_fast()`.

### make_project_readable(raw: str) -> str

```python
def make_project_readable(raw: str) -> str:
```

Converts raw Claude Code project directory names (which encode the filesystem path) into human-readable names.

**Prefix stripping (tried in order, longest first):**

| Prefix | Example Input | Result |
|--------|--------------|--------|
| `-home-pi-python-` | `-home-pi-python-admin-panel` | `admin-panel` |
| `-home-pi-TP--` | `-home-pi-TP--some-branch` | `some-branch` |
| `-home-pi-TP-` | `-home-pi-TP-subdir` | `subdir` |
| `-home-pi-` | `-home-pi-dotfiles` | `dotfiles` |

**Special cases:**
- `"-home-pi"` returns `"home (misc)"`
- `"TP"` or `"-home-pi-TP"` returns `"TP"`
- Empty result after stripping falls back to the original raw string.

---

## Shared Data Structures

### ToolInvocation (dataclass)

Defined in `/home/pi/python/claude_analysis/tool_adapters/base.py`. The unified representation for any tool call extracted from JSONL.

```python
@dataclass
class ToolInvocation:
    # Common metadata (all tools)
    timestamp: Optional[str]
    project: str
    tool_name: str
    tool_use_id: Optional[str]
    jsonl_path: str
    lineno: int
    cwd: Optional[str]
    session_id: Optional[str]
    git_branch: Optional[str]

    # Bash
    bash_command: Optional[str] = None
    bash_description: Optional[str] = None
    bash_timeout: Optional[int] = None

    # Read
    read_file_path: Optional[str] = None
    read_offset: Optional[int] = None
    read_limit: Optional[int] = None
    read_pages: Optional[str] = None

    # Write
    write_file_path: Optional[str] = None
    write_content_length: Optional[int] = None
    write_content_preview: Optional[str] = None

    # Edit
    edit_file_path: Optional[str] = None
    edit_old_string_preview: Optional[str] = None
    edit_new_string_preview: Optional[str] = None
    edit_replace_all: Optional[bool] = None

    # Grep
    grep_pattern: Optional[str] = None
    grep_path: Optional[str] = None
    grep_output_mode: Optional[str] = None
    grep_flags: Optional[str] = None
    grep_glob: Optional[str] = None
    grep_type: Optional[str] = None

    # Glob
    glob_pattern: Optional[str] = None
    glob_path: Optional[str] = None

    # Task tools
    task_subject: Optional[str] = None
    task_description_preview: Optional[str] = None
    task_id: Optional[str] = None
    task_status: Optional[str] = None
    task_operation: Optional[str] = None

    # TodoWrite
    todo_content_preview: Optional[str] = None

    # Special tools
    skill_name: Optional[str] = None
    websearch_query: Optional[str] = None
    ask_question_preview: Optional[str] = None

    # Generic fallback
    raw_input_json: Optional[str] = None
```

Only the fields relevant to a specific tool are populated; the rest remain `None`.

### ExtractionOptions (dataclass)

```python
@dataclass
class ExtractionOptions:
    include_content_previews: bool = True
    preview_length: int = 100
    verbose: bool = False
```

Controls whether content previews (e.g., write content, edit strings) are included and their maximum length.

### ToolAdapter (abstract base class)

```python
class ToolAdapter(ABC):
    @abstractmethod
    def extract(self, block: dict, base_metadata: dict, options: ExtractionOptions) -> ToolInvocation: ...

    @abstractmethod
    def get_primary_value(self, invocation: ToolInvocation) -> str: ...

    @abstractmethod
    def get_pattern_levels(self, invocation: ToolInvocation) -> tuple[str, str, str]: ...

    def truncate_preview(self, text: str, length: int = 100) -> str: ...
```

Each tool type has a concrete adapter (BashAdapter, ReadAdapter, etc.) that implements `extract()` to parse `block["input"]` into the appropriate `ToolInvocation` fields.

---

## Dependency Graph

```
extract_tool_usage.py
  |-- iter_jsonl()          <-- used by everything
  |-- find_jsonl_files()
  |-- derive_project_name()
  |-- extract_tools_from_file()
  |
  v
session_parser.py
  |-- imports: iter_jsonl, find_jsonl_files, derive_project_name, extract_tools_from_file
  |-- _is_interrupt_message()
  |-- _extract_text_from_content()
  |-- _get_tool_detail()
  |-- _get_file_path()
  |-- _estimate_cost()
  |-- build_tool_calls_list()
  |-- categorize_bash_command()
  |-- find_subagent_files()
  |-- extract_active_duration()
  |-- make_project_readable()
  |-- extract_first_prompt()
  |-- extract_user_turns()
  |-- count_turns()
  |-- extract_session_metadata()
  |-- extract_subagent_info()
  |-- build_session_data()         <-- multi-pass entry point (CLI)
  |-- build_subagent_data()
  |
  v
single_pass_parser.py
  |-- imports from extract_tool_usage: iter_jsonl, derive_project_name
  |-- imports from session_parser: 10 helper functions (listed above)
  |-- parse_session_single_pass()  <-- single-pass entry point (dashboard)
  |-- _build_subagent_data_fast()
  |
  v
app.py (calls parse_session_single_pass)
```

---

## Algorithm Details

### JSONL Record Format

Each line in a Claude Code JSONL file is a JSON object. Key fields vary by record type:

```json
// Top-level fields present on most records:
{
    "type": "system" | "progress" | ...,
    "subtype": "turn_duration" | ...,
    "timestamp": "2026-02-16T10:30:00.000Z",
    "slug": "fix-login-bug",
    "sessionId": "abc123",
    "cwd": "/home/pi/project",
    "gitBranch": "main",
    "permissionMode": "default",
    "thinkingMetadata": {"level": "medium"},

    // For message records:
    "message": {
        "role": "user" | "assistant",
        "model": "claude-sonnet-4-20250514",
        "usage": {
            "input_tokens": 1234,
            "output_tokens": 567,
            "cache_creation_input_tokens": 100,
            "cache_read_input_tokens": 800
        },
        "content": "string" | [
            {"type": "text", "text": "..."},
            {"type": "tool_use", "id": "toolu_xxx", "name": "Bash", "input": {...}},
            {"type": "tool_result", "tool_use_id": "toolu_xxx", "is_error": false, "content": "..."}
        ]
    },

    // For progress records (subagent tracking):
    "parentToolUseID": "toolu_xxx",
    "data": {"agentId": "ad7c5cf"}
}
```

### Single-Pass vs Multi-Pass Performance

The single-pass parser was introduced to eliminate repeated file I/O on the Raspberry Pi:

| Approach | Passes per File | Cold Build Time | Warm Build Time |
|----------|----------------|-----------------|-----------------|
| Multi-pass (`build_session_data`) | 5-7 | ~30-40s | N/A |
| Single-pass (`parse_session_single_pass`) | 1 | ~8-12s | <1s (incremental) |

The single-pass parser achieves this by maintaining all accumulators simultaneously and classifying each JSONL record into the appropriate buckets as it streams through the file. The trade-off is increased code complexity within the single function versus the cleaner decomposition of the multi-pass approach.

### User Message Filtering Pipeline

Both parsers apply the same filtering logic to user messages:

```
Raw user message
  |
  +--> Skip if text is None/empty
  +--> Skip if starts with "<local-command"
  +--> Skip if starts with "<command-"
  +--> Skip if len < 3
  |
  v
Qualifying user message
  |
  +--> Check _is_interrupt_message()
  |     "[Request interrupted by user]" -> is_interrupt = True
  |     "[Request interrupted by user for tool use]" -> is_interrupt = True
  |
  +--> Strip leading XML tags (for display / first_prompt)
  |     regex: r'^(<[^>]+>[\s\S]*?</[^>]+>\s*)+'
  |     Falls back to original if cleaned result is too short
  |
  +--> Truncate to 300 chars (for user_turns display)
  +--> Truncate to 80 chars (for prompt_preview)
```

### Subagent Resolution Pipeline

Subagent data requires correlating three sources of information:

```
1. Parent session: Task tool_use blocks
   tool_use_id -> {subagent_type, description}

2. Parent session: Progress records
   parentToolUseID -> agentId

3. Subagent directory: Separate JSONL files
   agent-<agentId>.jsonl

Resolution:
  tool_use_id ---[progress records]---> agentId ---[filename match]---> subagent JSONL
                                              |
                                              +--> {subagent_type, description} from Task input
```

### Cost Estimation Pipeline

```
Token counts (from msg.usage)
  |
  +--> Model detection (substring match: opus/haiku/sonnet)
  |
  +--> Rate lookup
  |     input_rate, output_rate
  |     cache_creation_rate = input_rate * 1.25
  |     cache_read_rate = input_rate * 0.10
  |
  +--> Formula:
        cost = (input * input_rate
              + output * output_rate
              + cache_creation * cache_creation_rate
              + cache_read * cache_read_rate) / 1_000_000
  |
  +--> round(cost, 4) -> float (USD)
```
