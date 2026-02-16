# 07 - CLI Extraction Scripts

## Overview

The Claude Activity Dashboard includes four standalone CLI scripts and a supporting `analyzers/` package for extracting, analyzing, and auditing tool usage from Claude Code JSONL logs. These scripts are **not required** by the web dashboard (which uses `single_pass_parser.py` and `cache_db.py` instead) but serve as independent analysis tools for CSV export, permission simulation, and command-pattern investigation.

### Script Inventory

| Script | Lines | Purpose |
|--------|-------|---------|
| `extract_tool_usage.py` | 392 | Extract all tool invocations to CSV + summary + permission YAML |
| `extract_bash_commands.py` | 352 | Extract Bash commands only, with heredoc cleaning |
| `analyze_commands.py` | 261 | Query helpers for post-hoc analysis of `bash_commands.csv` |
| `analyze_permissions.py` | 567 | Simulate permission rules against `tool_events.csv` |
| `test_heredoc_cleaning.py` | 104 | Demonstration script for the heredoc cleaning feature |

### Dependency Graph

```
extract_tool_usage.py
  --> tool_adapters/  (adapter registry, ToolInvocation dataclass)
  --> analyzers/      (patterns, permissions, summary)
  --> pyyaml

extract_bash_commands.py
  --> (self-contained, no internal imports)

analyze_commands.py
  --> bash_commands.csv  (output of extract_bash_commands.py --csv)

analyze_permissions.py
  --> tool_events.csv    (output of extract_tool_usage.py)
```

---

## extract_tool_usage.py -- Main CLI Tool Extractor

**Location:** `/home/pi/python/claude_analysis/extract_tool_usage.py`

The primary extraction script. Scans all JSONL files under a root directory, uses the `tool_adapters` adapter registry to extract every tool invocation (Bash, Read, Write, Edit, Grep, Glob, Task tools, etc.), then writes three output files.

### CLI Arguments

```
--root PATH      Root directory to scan (default: ~/.claude/projects)
--out-dir PATH   Output directory (default: current working directory)
--top N          Number of top items in summary (default: 30)
-v / --verbose   Print per-file extraction counts and adapter warnings
```

### Execution Flow

1. **Parse args, validate root exists.** Creates `out_dir` if missing.
2. **Initialize adapters.** Calls `create_adapter_registry()` from `tool_adapters` and builds `ExtractionOptions(include_content_previews=True, preview_length=100, verbose=args.verbose)`.
3. **Find JSONL files.** `find_jsonl_files(root)` returns `sorted(root.rglob("*.jsonl"))`.
4. **Extract all invocations.** For each file:
   - `derive_project_name(jsonl_path, root)` -- takes the first path component relative to root (e.g., `-home-pi-TP` from `/home/pi/.claude/projects/-home-pi-TP/session.jsonl`).
   - `extract_tools_from_file(jsonl_path, project, adapters, options)` -- iterates JSONL lines, finds `tool_use` blocks, delegates to the appropriate adapter via `get_adapter(tool_name, adapters)`.
5. **Analyze patterns per tool type.** Groups invocations by `tool_name`, calls `extract_patterns(tool_invocations, adapter)` from `analyzers.patterns` for each.
6. **Analyze permissions.** Calls `analyze_permissions(all_invocations)` from `analyzers.permissions`.
7. **Write outputs** (see below).

### Key Functions

#### `iter_jsonl(path: Path) -> Iterable[tuple[int, Optional[Dict]]]`

Shared JSONL reader. Opens file with UTF-8, yields `(lineno, parsed_dict)` for each non-empty line. Yields `(lineno, None)` for malformed JSON instead of raising.

#### `extract_tools_from_file(jsonl_path, project, adapters, options) -> tuple[List[ToolInvocation], int]`

For each line parsed by `iter_jsonl`:
- Extracts `message.content` (must be a list).
- Builds `base_metadata` dict with: `timestamp`, `project`, `jsonl_path`, `lineno`, `cwd`, `session_id`, `git_branch`.
- For each `tool_use` block in content, gets the adapter and calls `adapter.extract(block, base_metadata, options)`.
- Returns the list of `ToolInvocation` objects and a count of bad JSON lines.

#### `derive_project_name(jsonl_path, root) -> str`

Gets `jsonl_path.relative_to(root).parts[0]`. Falls back to `jsonl_path.parent.name` if the path is not relative to root.

#### `write_csv(invocations, output_path)`

Converts each `ToolInvocation` to a dict via `dataclasses.asdict()`, writes all fields as CSV columns using `csv.DictWriter`.

#### `write_permission_yaml(insights, output_path)`

Builds a list of rule dicts from `insights.suggested_allow`, `insights.suggested_ask`, and `insights.suggested_deny`. Each entry has `pattern`, `action`, and `reason` keys. Writes header comments manually, then uses `yaml.dump()` for the rules and statistics sections.

### Output Files

| File | Format | Contents |
|------|--------|----------|
| `tool_events.csv` | CSV | Every tool invocation with all `ToolInvocation` dataclass fields as columns |
| `tool_summary.txt` | Text | Distribution by tool/project, pattern analysis, permission recommendations |
| `permissions_suggested.yaml` | YAML | Machine-readable allow/ask/deny rules with occurrence counts |

---

## extract_bash_commands.py -- Bash Command Extractor

**Location:** `/home/pi/python/claude_analysis/extract_bash_commands.py`

Focused extractor that pulls only Bash tool invocations. Includes a heredoc-cleaning feature that collapses verbose `<<EOF...EOF` blocks for better pattern grouping.

### BashCmd Dataclass

```python
@dataclass
class BashCmd:
    timestamp: Optional[str]
    project: str
    cwd: Optional[str]
    command: str
    jsonl_path: str
    lineno: int
    tool_use_id: Optional[str]
    description: Optional[str]
```

### CLI Arguments

```
--root PATH          Root directory (default: /home/pi/.claude/projects)
--out-dir PATH       Output directory (default: current working directory)
--top N              Top commands in summary (default: 50)
--csv                Also output bash_commands.csv
--clean-heredocs     Replace heredoc blocks with placeholders
```

### Key Functions

#### `clean_heredoc(command: str) -> str`

Regex pattern: `r"<<'?(\w+)'?\s*\n.*?\n\1"` with `re.DOTALL`.

Replaces heredoc bodies with `<<'DELIMITER'...[heredoc]...DELIMITER`, then collapses all newlines into single spaces. This groups structurally identical commands (e.g., all `git commit -m "$(cat <<'EOF'...)"` variants) into a single pattern for frequency analysis.

**Before:**
```
git commit -m "$(cat <<'EOF'
Long commit message with multiple lines...
Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
EOF
)" && git push
```

**After:**
```
git commit -m "$(cat <<'EOF'...[heredoc]...EOF )" && git push
```

#### `extract_bash_from_file(jsonl_path, project, clean_heredocs=False) -> tuple[list[BashCmd], int]`

Has its own inline `iter_jsonl()` (duplicated from `extract_tool_usage.py`). Scans for `tool_use` blocks where `name == "Bash"`, extracts `input.command` and `input.description`, and optionally applies `clean_heredoc()`.

#### `extract_command_patterns(commands: list[str]) -> dict[str, Counter]`

Splits each command string by whitespace and counts patterns at three granularity levels:

| Key | Description | Example |
|-----|-------------|---------|
| `base` | First word only | `git`, `sudo`, `ls` |
| `level2` | First 2 words | `git status`, `sudo systemctl` |
| `level3` | First 3 words | `sudo systemctl restart` |

### Execution Flow

1. Parse args, validate root directory.
2. `rglob("*.jsonl")` to find all log files.
3. For each file: derive project name, call `extract_bash_from_file()`.
4. Accumulate per-command counts (`Counter`) and per-project totals.
5. Run `extract_command_patterns()` on all command strings.
6. Write outputs.

### Output Files

| File | Condition | Contents |
|------|-----------|----------|
| `bash_commands_all.txt` | Always | One raw command per line, chronological |
| `bash_commands_summary.txt` | Always | Pattern counts (base/2-word/3-word with count >= 3), top N specific commands, per-project totals |
| `bash_commands.csv` | `--csv` flag | Full `BashCmd` fields: timestamp, project, cwd, command, jsonl_path, lineno, tool_use_id, description |

---

## analyze_commands.py -- Query Helpers

**Location:** `/home/pi/python/claude_analysis/analyze_commands.py`

Post-processing script that reads `bash_commands.csv` (produced by `extract_bash_commands.py --csv`) and runs six targeted analyses. Prints results to stdout.

**Prerequisite:** Run `extract_bash_commands.py --csv` first to generate `bash_commands.csv`.

### Functions

#### `load_commands(csv_path="bash_commands.csv") -> List[Dict[str, str]]`

Reads CSV via `csv.DictReader`, returns list of row dicts.

#### `analyze_git_operations(commands)`

Filters commands starting with `"git "`. Extracts git subcommands (second word) and counts them. Also groups git usage by project.

**Output sections:** Top git operations (e.g., `git status`, `git add`), git usage by project.

#### `analyze_sudo_commands(commands)`

Filters commands starting with `"sudo "`. Extracts systemctl service names via regex `r'systemctl \w+ ([\w-]+)'`.

**Output sections:** Total sudo commands, systemctl services managed (service name + count).

#### `analyze_risky_commands(commands)`

Matches commands against five risk patterns:

| Pattern | Description |
|---------|-------------|
| `rm -rf` | Recursive force delete |
| `chmod 777` | Overly permissive chmod |
| `--force` | Force flag used |
| `pkill\|killall` | Process killing |
| `dd if=` | Direct disk operations |

Shows up to 3 examples per pattern with project and CWD context.

#### `analyze_package_management(commands)`

Counts commands containing `pip`, `npm`, `apt`, or `brew`.

#### `analyze_by_time(commands)`

Parses timestamps via `datetime.fromisoformat()`. Groups by date and by hour-of-day. Shows top 5 most active days and a simple bar chart of commands per hour (block character bars, 1 block = 10 commands).

#### `analyze_command_patterns(commands)`

Same 1/2/3-word pattern analysis as `extract_bash_commands.py` but includes percentage of total for each pattern. Shows top 10 base commands, top 15 two-word patterns, top 10 three-word patterns.

### `main()` Execution Order

```python
analyze_command_patterns(commands)
analyze_git_operations(commands)
analyze_sudo_commands(commands)
analyze_package_management(commands)
analyze_risky_commands(commands)
analyze_by_time(commands)
```

---

## analyze_permissions.py -- Permission Rule Simulator

**Location:** `/home/pi/python/claude_analysis/analyze_permissions.py`

Simulates a set of deny/ask/allow permission rules against every tool call in `tool_events.csv`. Reports what percentage would be allowed, asked, or denied, with detailed breakdowns of each category. This is used to tune permission rules before deploying them to `~/.claude/permissions.yaml`.

**Prerequisite:** Run `extract_tool_usage.py` first to generate `tool_events.csv`.

### PermissionAnalyzer Class

```python
class PermissionAnalyzer:
    def __init__(self, rules: Dict)
    # rules = {"deny": [...], "ask": [...], "allow": [...]}

    stats = {"allow": 0, "ask": 0, "deny": 0, "total": 0}
    ask_cases = []   # list of result dicts
    deny_cases = []  # list of result dicts
```

### Rule Format

Rules follow the pattern `"ToolName(glob_pattern)"`:

| Example | Meaning |
|---------|---------|
| `Bash(git *)` | Any Bash command starting with `git ` |
| `Read(**/.ssh/**)` | Read any path containing `.ssh/` |
| `Edit(//etc/**)` | Edit any path under `/etc/` (`//` = absolute `/`) |
| `Bash(sudo systemctl * ssh*)` | Any sudo systemctl command targeting ssh services |
| `Bash(curl *\|*)` | Any curl command piped to another program |

The `//` prefix is a convention: since patterns use `(...)` delimiters, a leading `//` is normalized to `/` to represent absolute paths.

### Key Methods

#### `parse_rule_pattern(rule: str) -> Tuple[str, str]`

Regex: `r'^(\w+)\((.*)\)$'` -- splits into tool name and pattern. Returns `(None, None)` on failure.

#### `normalize_path(path: str) -> str`

Converts `//` prefix to `/`. Leaves other paths unchanged.

#### `match_glob_pattern(pattern: str, value: str) -> bool`

Handles `**` glob matching that `fnmatch` does not natively support:

- If pattern is `**/suffix` -- matches if value ends with the suffix (using `fnmatch` with `*` prefix).
- If pattern is `prefix/**` -- matches if value starts with the prefix path.
- For mixed patterns like `**/middle/**` -- converts `**/` to `*/` and `/**` to `/*`, then uses `fnmatch`.
- Without `**` -- delegates directly to `fnmatch.fnmatch()`.

#### `match_bash_pattern(pattern: str, command: str) -> bool`

Normalizes whitespace in both pattern and command, then calls `fnmatch.fnmatch()`. The pipe character `|` is treated as literal (not regex alternation) because fnmatch does not interpret it.

#### `check_rule_match(tool_name, value, rules) -> Optional[str]`

Iterates through a rule list. For `Bash` tools, uses `match_bash_pattern()`. For `Read`/`Edit`/`Write`, uses `match_glob_pattern()`. Returns the first matched rule string, or `None`.

#### `categorize_call(tool_name, value) -> Tuple[str, Optional[str]]`

Applies the priority chain: **deny > ask > allow**. Checks deny rules first, then ask, then allow. If no rule matches, defaults to `"ask"`. Returns `(category, matched_rule)`.

#### `analyze_tool_call(row: Dict) -> Dict`

Extracts the relevant value from a CSV row based on `tool_name`:

| tool_name | CSV column used |
|-----------|----------------|
| `Bash` | `bash_command` |
| `Read` | `read_file_path` |
| `Edit` | `edit_file_path` |
| `Write` | `write_file_path` |
| Other | Empty string (auto-allowed) |

Returns a result dict with `category`, `matched_rule`, `tool_name`, `value`, `timestamp`, `project`.

#### `analyze_csv(csv_path: str)`

Reads all rows from `tool_events.csv`, calls `analyze_tool_call()` on each, updates `stats` counters, and accumulates `ask_cases` and `deny_cases`.

#### `generate_report() -> str`

Produces a structured text report with four sections:

1. **Summary Statistics** -- total/allow/ask/deny counts with percentages.
2. **Deny Cases** -- grouped by matched rule, up to 10 examples each showing tool, value, project, and timestamp.
3. **Ask Cases** -- grouped by tool type then by rule, showing unique values with counts (top 20 per rule).
4. **Breakdown by Tool Type** -- re-reads `tool_events.csv` and tabulates allow/ask/deny per tool name.

### Embedded Rules (in `main()`)

The script contains a comprehensive rule set organized into three tiers:

**Deny (39 rules):**
- SSH keys and related material (`Read/Edit/Write(**/.ssh/**)`, `**/id_rsa*`, etc.)
- Catastrophic disk operations (`Bash(dd *)`, `Bash(mkfs*)`, `Bash(shred *)`, etc.)
- System root deletion (`Bash(rm -rf /)`, `Bash(rm -rf /etc*)`, etc.)
- Network/access service management (`Bash(sudo systemctl * ssh*)`, `*tailscale*`, `*networking*`, etc.)

**Ask (24 rules):**
- Pipe-to-shell commands (`Bash(curl *|*)`, `Bash(wget *|*)`)
- Environment files (`Read/Edit/Write(**/.env)`, `**/.env.*`)
- System path edits/writes (`Edit/Write(//etc/**)`, `//usr/**`, `//var/**`, etc.)
- Permission changes (`Bash(chmod *)`, `Bash(chown *)`)
- System package management (`Bash(sudo apt *)`, `Bash(sudo dpkg *)`)

**Allow (39 rules):**
- Read everywhere (`Read(//**)`)
- Write/Edit under home directory (`Edit/Write(//home/pi/**)`)
- Temp files (`Read/Edit/Write(//tmp/**)`)
- Git fully autonomous (`Bash(git *)`)
- Service management except deny-listed (`Bash(sudo systemctl *)`, `Bash(sudo journalctl *)`)
- Local/Tailscale curl (`Bash(curl *127.0.0.1*)`, `*localhost*`, `*100.99.27.84*`)
- Trusted piped curl to local addresses (`Bash(curl *127.0.0.1*|*)`)
- Common dev commands (`ls`, `pwd`, `find`, `grep`, `cat`, `head`, `tail`, etc.)
- Python tooling (`python`, `pip`, `source`)
- Scoped rm under home (`Bash(rm * /home/pi/*)`)

### Output

Writes `permission_analysis_report.txt` and prints a quick summary to stdout with total/allow/ask/deny counts and percentages.

---

## analyzers/ Package

**Location:** `/home/pi/python/claude_analysis/analyzers/`

Three modules providing pattern extraction, permission analysis, and summary generation. Used by `extract_tool_usage.py` but not by the web dashboard.

### analyzers/__init__.py

Exports:
```python
from .patterns import extract_patterns, PatternStats
from .permissions import analyze_permissions, PermissionInsights
from .summary import generate_summary, write_summary
```

### analyzers/patterns.py (122 lines)

#### PatternStats Dataclass

```python
@dataclass
class PatternStats:
    tool_name: str
    total_count: int
    level1_patterns: Counter  # Most general (e.g., base command)
    level2_patterns: Counter  # Mid-level (e.g., 2-word pattern)
    level3_patterns: Counter  # Most specific (e.g., 3-word pattern)
    primary_values: Counter   # Raw values (full command, full path, etc.)
```

#### `extract_patterns(invocations, adapter) -> PatternStats`

For each invocation, calls `adapter.get_primary_value(inv)` for raw value counting and `adapter.get_pattern_levels(inv)` for the 3-level hierarchy. Returns populated `PatternStats`.

#### `format_pattern_section(stats, level, top_n=30, min_count=3) -> List[str]`

Formats a single pattern level as text lines. Filters patterns below `min_count`, sorts descending, truncates at `top_n`, and appends a "... N more" line if overflow.

### analyzers/permissions.py (289 lines)

#### PermissionInsights Dataclass

```python
@dataclass
class PermissionInsights:
    total_operations: int
    high_privilege_count: int
    sensitive_file_access: int
    external_access_count: int

    # High-risk operations detected
    sudo_commands: List[Tuple[str, int]]      # (command, count)
    rm_operations: List[Tuple[str, int]]
    chmod_operations: List[Tuple[str, int]]
    sensitive_paths: List[Tuple[str, int]]     # (path, count)

    # Recommendations
    suggested_allow: List[Tuple[str, str, int]]  # (pattern, reason, count)
    suggested_ask: List[Tuple[str, str, int]]
    suggested_deny: List[Tuple[str, str]]        # (pattern, reason) -- preventive

    # Statistics per tool
    tool_counts: Counter          # default_factory=Counter
    bash_command_types: Counter
    file_extensions: Counter
    directory_access: Counter
```

#### `analyze_permissions(invocations) -> PermissionInsights`

Orchestrates three sub-analyses then generates recommendations:

1. **`_analyze_bash_commands()`** -- Counts sudo commands (extracts what follows `sudo`), rm operations, chmod commands, git subcommands, and curl usage.
2. **`_analyze_file_operations()`** -- Checks file paths against sensitive patterns via regex: `/etc/`, `.ssh/`, `.env`, `credentials`, `secrets`, `password`, `/root/`, `/var/`. Also extracts file extensions and top-level directory access patterns.
3. **`_generate_recommendations()`** -- Threshold-based rule suggestions:
   - **Allow** if: read-only git >= 10, common file reads >= 50, Grep >= 10, Glob >= 5.
   - **Ask** if: git writes >= 5, Write >= 10, config edits >= 3, sudo >= 5.
   - **Deny** (always): system directory deletion, system file modification, SSH key modification, `chmod 777`, `dd if=/dev/`.

### analyzers/summary.py (440 lines)

#### `generate_summary(invocations, patterns_by_tool, insights, top_n=30) -> str`

Assembles the full `tool_summary.txt` by calling internal section generators:

| Section Generator | Report Section |
|-------------------|---------------|
| `_generate_header()` | Total invocations, unique tools, project count, time range |
| `_generate_distribution()` | Tool counts with percentages, project counts |
| `_generate_bash_section()` | Bash command patterns at 3 levels (count >= 3 filter) |
| `_generate_file_ops_section()` | Read/Write/Edit breakdown, top accessed paths, extensions, directories |
| `_generate_search_section()` | Grep/Glob totals, Grep output modes, most-used search patterns |
| `_generate_task_section()` | TaskCreate/TaskUpdate/TaskList/TaskGet/TaskOutput/TodoWrite counts |
| `_generate_permission_section()` | Sudo counts, rm/chmod operations, sensitive file access, external access, suggested allow/ask/deny rules, flagged operations |

#### `write_summary(invocations, patterns_by_tool, insights, output_path, top_n=30)`

Calls `generate_summary()` then writes the string to `output_path`.

---

## test_heredoc_cleaning.py -- Heredoc Cleaning Demo

**Location:** `/home/pi/python/claude_analysis/test_heredoc_cleaning.py`

A standalone demonstration script (not a pytest test). Contains its own copy of `clean_heredoc()` and three example commands:

1. **Git commit with push** -- multi-line commit message with `<<'EOF'...EOF` block.
2. **Git commit without push** -- similar heredoc structure.
3. **Python heredoc** -- `python3 << 'EOF'` with inline Python code.

Runs each through `clean_heredoc()` and prints before/after comparison. Also prints a summary of the statistical impact:

```
Without --clean-heredocs:
  Total commands: 1355, Unique: 1155

With --clean-heredocs:
  Total commands: 1363, Unique: 1131 (24 fewer)
  Similar commands grouped together:
    15x  git commit -m "$(cat <<'EOF'...[heredoc]...EOF)"
    12x  git commit -m "$(cat <<'EOF'...[heredoc]...EOF)" && git push
```

---

## Typical Workflow

A full analysis session using these CLI scripts:

```bash
cd ~/python/claude_analysis
source venv/bin/activate

# Step 1: Extract all tool invocations
python extract_tool_usage.py --top 50

# Step 2: Extract Bash commands with heredoc cleaning and CSV
python extract_bash_commands.py --csv --clean-heredocs

# Step 3: Run query helpers on the Bash CSV
python analyze_commands.py

# Step 4: Simulate permission rules against tool_events.csv
python analyze_permissions.py
```

**Generated files after a full run:**

```
tool_events.csv               # All tool calls (extract_tool_usage.py)
tool_summary.txt              # Aggregated analysis (extract_tool_usage.py)
permissions_suggested.yaml    # Auto-generated rules (extract_tool_usage.py)
bash_commands_all.txt         # Raw command list (extract_bash_commands.py)
bash_commands_summary.txt     # Command patterns (extract_bash_commands.py)
bash_commands.csv             # Detailed CSV (extract_bash_commands.py --csv)
permission_analysis_report.txt  # Rule simulation (analyze_permissions.py)
```

---

## Relationship to the Web Dashboard

The web dashboard (`app.py`) does **not** use any of these scripts or the `analyzers/` package. It has its own optimized pipeline:

| CLI Scripts | Web Dashboard |
|-------------|---------------|
| `extract_tool_usage.py` + `tool_adapters/` | `single_pass_parser.py` |
| `analyzers/` (patterns, permissions, summary) | `cache_db.py` (SQLite aggregates) |
| CSV / YAML / text file outputs | SQLite `data/cache.db` |
| Manual CLI invocation | Automatic background rebuilds |

The two extraction paths share the same JSONL input (`~/.claude/projects/**/*.jsonl`) but parse independently. The CLI scripts produce flat-file outputs for ad hoc analysis; the web dashboard maintains a persistent SQLite cache for real-time serving.

One shared dependency: `extract_tool_usage.py` imports `iter_jsonl()` from its own module, and `extract_bash_commands.py` has a duplicated copy of the same function. The `tool_adapters/` package is used only by `extract_tool_usage.py` and the CLI pipeline, not by the web dashboard.
