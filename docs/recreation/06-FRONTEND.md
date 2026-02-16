# 06 — Frontend: Dashboard Template (HTML/CSS/JS)

The entire frontend lives in a single file: `dashboard_template.html` (~985 lines). It uses **no build tools, no bundler, no framework** — just vanilla HTML, CSS, and JavaScript with Chart.js loaded from CDN.

---

## HTML Structure

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <!-- PWA meta tags -->
  <!-- Chart.js CDN -->
  <style>/* All CSS inline */</style>
</head>
<body>
  <div class="header">...</div>
  <div class="tabs">...</div>
  <div class="content">
    <div id="overview" class="tab-panel active">...</div>
    <div id="explorer" class="tab-panel">...</div>
    <div id="log" class="tab-panel">...</div>
  </div>
  <script>/* All JS inline */</script>
</body>
</html>
```

### PWA Meta Tags (Head)

```html
<!-- iPhone Home Screen icon -->
<link rel="apple-touch-icon" sizes="180x180" href="/claude_activity/app_icon.jpg?v=20260216">

<!-- Home Screen label -->
<meta name="apple-mobile-web-app-title" content="Task Monitor">
<meta name="application-name" content="Task Monitor">

<!-- Standalone mode (no Safari chrome) -->
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
```

The `?v=` cache buster on the icon can be any date string.

### Chart.js CDN

```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
```

Version **4.4.7** specifically. Loaded synchronously in `<head>` (before body renders).

---

## CSS Design System

### CSS Custom Properties

```css
:root {
  --bg: #0f1117;         /* Page background (near-black blue) */
  --surface: #1a1d27;    /* Card/panel backgrounds */
  --surface2: #242836;   /* Nested surface (inputs, code blocks) */
  --border: #2e3347;     /* All borders */
  --text: #e1e4ed;       /* Primary text */
  --text-dim: #8b8fa3;   /* Secondary/muted text */
  --accent: #6c8cff;     /* Primary accent (blue) */
  --accent2: #a78bfa;    /* Secondary accent (purple — subagents) */
  --green: #4ade80;      /* Success/write operations */
  --orange: #fb923c;     /* Warnings/edit operations */
  --red: #f87171;        /* Errors */
  --cyan: #22d3ee;       /* Info/glob operations */
  --pink: #f472b6;       /* Bash operations */
}
```

### Global Reset and Base

```css
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
}
a { color: var(--accent); }
```

### Layout Components

**Header** (top bar):
```css
.header {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 16px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.header h1 { font-size: 20px; font-weight: 600; }
.header .meta { font-size: 13px; color: var(--text-dim); }
```

**Tabs** (navigation bar):
```css
.tabs {
  display: flex;
  gap: 0;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 0 24px;
}
.tab {
  padding: 12px 20px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-dim);
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
}
.tab:hover { color: var(--text); }
.tab.active { color: var(--accent); border-bottom-color: var(--accent); }
```

**Content area**:
```css
.content { padding: 24px; max-width: 1400px; margin: 0 auto; }
.tab-panel { display: none; }
.tab-panel.active { display: block; }
```

### Card Grid

```css
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 20px;
}
.card .label {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-dim);
  margin-bottom: 4px;
}
.card .value { font-size: 28px; font-weight: 700; }
.card .sub { font-size: 12px; color: var(--text-dim); margin-top: 4px; }
```

### Charts Grid

```css
.charts-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 24px;
}
.chart-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 20px;
}
.chart-box h3 {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
  color: var(--text-dim);
}
.chart-box canvas { max-height: 300px; }
```

The "Trends Over Time" section uses a 3-column grid:
```css
/* Inline style on the element: */
grid-template-columns: 1fr 1fr 1fr;
```

### Explorer Controls

```css
.explorer-controls {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}
.explorer-controls select, .explorer-controls input {
  background: var(--surface2);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 14px;
  min-width: 200px;
}
.explorer-controls select:focus, .explorer-controls input:focus {
  outline: none;
  border-color: var(--accent);
}
select option { background: var(--surface2); color: var(--text); }
```

### Session Summary

```css
.session-summary {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 20px;
  margin-bottom: 20px;
}
.session-summary h2 { font-size: 16px; margin-bottom: 12px; }
.session-summary .prompt-text {
  background: var(--surface2);
  padding: 12px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
  margin-bottom: 12px;
}
.meta-row {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
  font-size: 13px;
  color: var(--text-dim);
}
.meta-row span { display: flex; align-items: center; gap: 4px; }
.meta-row .badge {
  background: var(--accent);
  color: #fff;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 600;
}
```

### Detail Grid

```css
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 20px;
}
@media (max-width: 900px) {
  .detail-grid, .charts-grid { grid-template-columns: 1fr; }
}
```

### Tables

```css
.table-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
  overflow-x: auto;
}
.table-box h3 {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 10px;
  color: var(--text-dim);
}
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th {
  text-align: left;
  padding: 8px;
  border-bottom: 1px solid var(--border);
  color: var(--text-dim);
  font-weight: 500;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
td { padding: 6px 8px; border-bottom: 1px solid var(--border); }
tr:last-child td { border-bottom: none; }
td.mono { font-family: 'SF Mono', 'Fira Code', monospace; font-size: 12px; }
```

### Tool Badges

Each tool gets a colored badge. CSS classes match tool names:

```css
.tool-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}
.tool-badge.Read { background: #1e3a5f; color: #60a5fa; }
.tool-badge.Write { background: #1a3d2e; color: var(--green); }
.tool-badge.Edit { background: #3d2e1a; color: var(--orange); }
.tool-badge.Bash { background: #3d1a2e; color: var(--pink); }
.tool-badge.Grep { background: #2e1a3d; color: var(--accent2); }
.tool-badge.Glob { background: #1a2e3d; color: var(--cyan); }
.tool-badge.Task, .tool-badge.TaskCreate, .tool-badge.TaskUpdate,
.tool-badge.TaskList, .tool-badge.TaskGet, .tool-badge.TaskOutput {
  background: #2d2d1a;
  color: #facc15;
}
.tool-badge.WebSearch, .tool-badge.WebFetch { background: #1a3d3d; color: #2dd4bf; }
.tool-badge.Skill { background: #3d3d1a; color: #fde047; }
.tool-badge.default { background: var(--surface2); color: var(--text-dim); }
```

### Subagent Cards

```css
.subagent-card {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 12px;
}
.subagent-header {
  padding: 12px 16px;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.subagent-header:hover { background: rgba(108, 140, 255, 0.05); }
.subagent-header .agent-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--accent2);
}
.agent-type-badge {
  display: inline-block;
  background: var(--accent2);
  color: #fff;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  margin-right: 6px;
  vertical-align: middle;
}
.subagent-header .agent-meta { font-size: 12px; color: var(--text-dim); }
.subagent-body { padding: 0 16px 16px; display: none; }
.subagent-body.open { display: block; }
.subagent-desc {
  font-size: 12px;
  color: var(--text-dim);
  margin-bottom: 8px;
  line-height: 1.5;
  background: var(--surface);
  padding: 8px 10px;
  border-radius: 4px;
  max-height: 120px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
.arrow { transition: transform 0.2s; display: inline-block; }
.arrow.open { transform: rotate(90deg); }
```

### Pagination

```css
.pagination {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: center;
  margin-top: 12px;
  font-size: 13px;
}
.pagination button {
  background: var(--surface2);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 6px 12px;
  border-radius: 4px;
  cursor: pointer;
}
.pagination button:hover { border-color: var(--accent); }
.pagination button:disabled { opacity: 0.3; cursor: default; }
.pagination .page-info { color: var(--text-dim); }
```

### Filter Bar (Action Log tool checkboxes)

```css
.filter-bar {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
  align-items: center;
}
.filter-bar label {
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  color: var(--text-dim);
}
.filter-bar label:hover { color: var(--text); }
.filter-bar input[type="checkbox"] { accent-color: var(--accent); }
```

### Conversation Flow

```css
.conversation-flow { margin-top: 12px; }
.conversation-flow summary {
  cursor: pointer;
  font-size: 13px;
  color: var(--text-dim);
  padding: 6px 0;
  user-select: none;
}
.conversation-flow summary:hover { color: var(--text); }
.turn-list {
  list-style: none;
  padding: 8px 0 0 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.turn-item {
  background: var(--surface2);
  border-left: 3px solid var(--accent);
  padding: 8px 12px;
  border-radius: 0 6px 6px 0;
  font-size: 13px;
  line-height: 1.4;
}
.turn-item.interrupt {
  border-left-color: var(--orange);
  font-style: italic;
  color: var(--text-dim);
  background: rgba(251, 146, 60, 0.08);
}
.turn-number {
  font-size: 11px;
  color: var(--text-dim);
  margin-right: 6px;
  font-weight: 600;
}
.turn-time { font-size: 11px; color: var(--text-dim); float: right; }
```

### Category Pills (Bash filter + Timeline granularity)

```css
.category-pills { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
.cat-pill {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid var(--border);
  background: var(--surface2);
  color: var(--text-dim);
  transition: all 0.15s;
  user-select: none;
}
.cat-pill:hover { border-color: var(--accent); color: var(--text); }
.cat-pill.active { background: var(--accent); color: #fff; border-color: var(--accent); }
.cat-pill .cat-count { opacity: 0.7; margin-left: 2px; }
```

### Misc

```css
.badge-orange { background: rgba(251, 146, 60, 0.2); color: var(--orange); }

.empty-state { text-align: center; padding: 60px 20px; color: var(--text-dim); }
.empty-state h3 { margin-bottom: 8px; color: var(--text); }

/* Loading spinner */
.loading-spinner { text-align: center; padding: 40px; color: var(--text-dim); }
.loading-spinner::before {
  content: '';
  display: inline-block;
  width: 24px; height: 24px;
  border: 3px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-bottom: 12px;
}
@keyframes spin { to { transform: rotate(360deg); } }
.loading-spinner p { margin-top: 8px; font-size: 13px; }

/* Rebuild banner */
.rebuild-banner {
  background: var(--surface2);
  border: 1px solid var(--accent);
  border-radius: 8px;
  padding: 12px 20px;
  margin-bottom: 16px;
  font-size: 13px;
  color: var(--accent);
  display: flex;
  align-items: center;
  gap: 8px;
}
.rebuild-banner::before {
  content: '';
  display: inline-block;
  width: 12px; height: 12px;
  border: 2px solid var(--accent);
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
```

---

## HTML Body Structure

### Header

```html
<div class="header">
  <h1>Claude Code Activity Dashboard</h1>
  <div class="meta" id="headerMeta"></div>
</div>
```

`headerMeta` is populated by JS with: `Generated {date} | {N} sessions | {N} projects`

### Tabs

```html
<div class="tabs">
  <div class="tab active" data-tab="overview">Overview</div>
  <div class="tab" data-tab="explorer">Task Explorer</div>
  <div class="tab" data-tab="log">Action Log</div>
</div>
```

Tab switching uses `data-tab` attribute to match panel `id`.

### Overview Tab

```html
<div id="overview" class="tab-panel active">
  <!-- Rebuild banner (hidden by default) -->
  <div id="rebuildBanner" style="display:none;" class="rebuild-banner">
    Cache is being built in the background. Data will appear shortly.
  </div>

  <!-- Summary cards row -->
  <div class="cards" id="summaryCards"></div>

  <!-- Activity by Time Range section -->
  <div>
    <h3>Activity by Time Range</h3>
    <div class="category-pills" id="rangeChartPills">
      <span class="cat-pill active" data-r="all" onclick="switchAllRanges('all')">All</span>
      <span class="cat-pill" data-r="1d" onclick="switchAllRanges('1d')">Day</span>
      <span class="cat-pill" data-r="7d" onclick="switchAllRanges('7d')">Week</span>
      <span class="cat-pill" data-r="30d" onclick="switchAllRanges('30d')">Month</span>
    </div>
    <div class="charts-grid">
      <div class="chart-box"><h3>Tool Distribution</h3><canvas id="toolPieChart"></canvas></div>
      <div class="chart-box"><h3>Top Projects by Actions</h3><canvas id="projectBarChart"></canvas></div>
      <div class="chart-box"><h3>File Types Touched</h3><canvas id="fileTypeChart"></canvas></div>
      <div class="chart-box"><h3>Cost by Project</h3><canvas id="costByProjectChart"></canvas></div>
    </div>
  </div>

  <!-- Trends Over Time section -->
  <div>
    <h3>Trends Over Time</h3>
    <div class="category-pills" id="timelinePills">
      <span class="cat-pill" data-g="daily" onclick="switchTimeline('daily')">Daily</span>
      <span class="cat-pill active" data-g="weekly" onclick="switchTimeline('weekly')">Weekly</span>
      <span class="cat-pill" data-g="monthly" onclick="switchTimeline('monthly')">Monthly</span>
    </div>
    <div class="charts-grid" style="grid-template-columns:1fr 1fr 1fr">
      <div class="chart-box"><h3>Sessions</h3><canvas id="timelineChart"></canvas></div>
      <div class="chart-box"><h3>Actions</h3><canvas id="actionsTimelineChart"></canvas></div>
      <div class="chart-box"><h3>Active Time</h3><canvas id="activeTimeChart"></canvas></div>
    </div>
  </div>
</div>
```

### Task Explorer Tab

```html
<div id="explorer" class="tab-panel">
  <!-- Controls: project filter + session selector -->
  <div class="explorer-controls">
    <select id="projectFilter"><option value="">All Projects</option></select>
    <select id="sessionSelect"><option value="">Select a session...</option></select>
  </div>

  <!-- Loading spinner (hidden) -->
  <div id="sessionLoading" class="loading-spinner" style="display:none;">
    <p>Loading session detail...</p>
  </div>

  <!-- Session detail container (hidden until loaded) -->
  <div id="sessionDetail" style="display:none;">
    <div class="session-summary">
      <h2 id="sessionTitle"></h2>
      <div class="prompt-text" id="promptText"></div>
      <div class="conversation-flow" id="conversationFlow" style="display:none;"></div>
      <div class="meta-row" id="sessionMeta"></div>
    </div>

    <div class="detail-grid">
      <div class="chart-box"><h3>Tool Breakdown</h3><canvas id="sessionToolChart"></canvas></div>
      <div class="table-box"><h3>File Operations</h3><div id="fileOpsTable"></div></div>
    </div>

    <div class="detail-grid">
      <div class="chart-box" id="bashChartBox" style="display:none;">
        <h3>Bash Command Categories</h3><canvas id="bashCatChart"></canvas>
      </div>
      <div class="table-box"><h3>Bash Commands</h3><div id="bashTable"></div></div>
    </div>

    <div id="subagentsSection"></div>
  </div>

  <!-- Empty state (shown when no session selected) -->
  <div id="explorerEmpty" class="empty-state">
    <h3>Select a session to explore</h3>
    <p>Choose a project and session from the dropdowns above.</p>
  </div>
</div>
```

### Action Log Tab

```html
<div id="log" class="tab-panel">
  <div id="logContent">
    <!-- No-session state -->
    <div id="logNoSession" class="empty-state">
      <h3>No session selected</h3>
      <p>Select a session in the Task Explorer tab first, then come back here to see the full action log.</p>
    </div>

    <!-- Active log (hidden until session loaded) -->
    <div id="logActive" style="display:none;">
      <div class="filter-bar" id="toolFilters"></div>
      <div class="table-box">
        <table>
          <thead><tr><th>#</th><th>Time</th><th>Tool</th><th>Detail</th><th>Source</th></tr></thead>
          <tbody id="logTableBody"></tbody>
        </table>
      </div>
      <div class="pagination" id="logPagination"></div>
    </div>
  </div>
</div>
```

---

## JavaScript Architecture

### Data Injection Point

```javascript
const DASHBOARD_DATA = {};
```

This **exact** line is replaced by `app.py` via string substitution (see doc 05). The injected object has shape:

```javascript
{
  overview: {                      // From global_aggregates table
    total_sessions: 150,
    total_actions: 12000,
    total_tools: 8000,
    total_cost: 45.67,
    project_count: 12,
    subagent_count: 200,
    subagent_tools: 4000,
    total_active_ms: 5400000,
    total_input_tokens: 5000000,
    total_output_tokens: 800000,
    total_cache_creation_tokens: 2000000,
    total_cache_read_tokens: 3000000,
    date_range_start: "2025-12-01T...",
    date_range_end: "2026-02-16T...",
    generated_at: "2026-02-16T12:00:00",
    projects_list: ["admin-panel", "claude-analysis", ...],

    // Chart data (all-time)
    tool_distribution: {"Read": 500, "Edit": 300, ...},
    projects_chart: {"admin-panel": 1200, ...},
    file_types_chart: {".py": 400, ".md": 200, ...},
    cost_by_project: {"admin-panel": 12.50, ...},

    // Time-filtered variants (1d/7d/30d)
    tool_distribution_1d: {...}, tool_distribution_7d: {...}, tool_distribution_30d: {...},
    projects_chart_1d: {...},    projects_chart_7d: {...},    projects_chart_30d: {...},
    file_types_chart_1d: {...},  file_types_chart_7d: {...},  file_types_chart_30d: {...},
    cost_by_project_1d: {...},   cost_by_project_7d: {...},   cost_by_project_30d: {...},

    // Timeline data (daily/weekly/monthly)
    daily_timeline: {"2026-02-14": 5, "2026-02-15": 8, ...},
    weekly_timeline: {"2026-02-10": 25, ...},
    monthly_timeline: {"2026-01": 100, ...},

    // Actions timeline (has .total, .direct, .subagent per bucket)
    actions_daily: {"2026-02-14": {total: 50, direct: 30, subagent: 20}, ...},
    actions_weekly: {...},
    actions_monthly: {...},

    // Active time timeline (milliseconds per bucket)
    active_time_daily: {"2026-02-14": 3600000, ...},
    active_time_weekly: {...},
    active_time_monthly: {...},
  },

  sessions: [                      // From session_summaries table
    {
      session_id: "abc123-def456",
      project: "admin-panel",
      slug: "add-logout",
      prompt_preview: "Add a logout button...",
      start_time: "2026-02-15T10:30:00Z",
      total_actions: 42,
      model: "claude-sonnet-4-5-...",
      cost_estimate: 1.23,
    },
    ...
  ],

  rebuild_in_progress: false       // True during initial cache build
}
```

### Root Path Resolution

```javascript
const rootPath = document.querySelector('link[rel="apple-touch-icon"]')
  ?.href?.match(/(.*)\/app_icon/)?.[1] || '/claude_activity';
```

This extracts the path prefix from the PWA icon URL. Used for all `fetch()` API calls. Falls back to `/claude_activity`.

### Global State Variables

```javascript
let currentSession = null;         // Full session detail object (after lazy load)
let sessionToolChart = null;       // Chart.js instance (explorer tool donut)
let bashCatChart = null;           // Chart.js instance (explorer bash categories)
let logPage = 1;                   // Current page in action log
const LOG_PAGE_SIZE = 50;          // Rows per page in action log
let logToolFilters = new Set();    // Active tool type filters in action log
```

### Color Maps

**Tool Colors** (for Chart.js datasets):
```javascript
const TOOL_COLORS = {
  Read: '#60a5fa',           // Blue
  Write: '#4ade80',          // Green
  Edit: '#fb923c',           // Orange
  Bash: '#f472b6',           // Pink
  Grep: '#a78bfa',           // Purple
  Glob: '#22d3ee',           // Cyan
  Task: '#facc15',           // Yellow
  TaskCreate: '#facc15',     // Yellow
  TaskUpdate: '#fbbf24',     // Amber
  TaskList: '#f59e0b',       // Amber (darker)
  TaskGet: '#d97706',        // Amber (darker)
  TaskOutput: '#b45309',     // Amber (darkest)
  WebSearch: '#2dd4bf',      // Teal
  WebFetch: '#14b8a6',       // Teal (darker)
  Skill: '#fde047',          // Yellow-green
  AskUserQuestion: '#c084fc', // Violet
  EnterPlanMode: '#7c3aed',  // Indigo
  ExitPlanMode: '#6d28d9',   // Indigo (darker)
  NotebookEdit: '#f0abfc',   // Pink-violet
  TaskStop: '#a3a3a3',       // Gray
  TodoWrite: '#a3e635',      // Lime
};

function getToolColor(name) { return TOOL_COLORS[name] || '#8b8fa3'; }
```

**Bash Category Colors and Descriptions**:
```javascript
const BASH_CAT_COLORS = {
  'Version Control': '#6c8cff',
  'Running Code': '#4ade80',
  'Searching & Reading': '#a78bfa',
  'File Management': '#fb923c',
  'Testing & Monitoring': '#22d3ee',
  'Server & System': '#f472b6',
  'Other': '#8b8fa3',
};

const BASH_CAT_DESCRIPTIONS = {
  'Version Control': 'Saving and tracking code changes',
  'Running Code': 'Executing scripts and running programs',
  'Searching & Reading': 'Finding files and reading content',
  'File Management': 'Creating, moving, and organizing files',
  'Testing & Monitoring': 'Checking connections and monitoring processes',
  'Server & System': 'Managing services and system configuration',
  'Other': 'Miscellaneous commands',
};
```

**Tool Badge Class Resolution**:
```javascript
function getToolBadgeClass(name) {
  const known = ['Read','Write','Edit','Bash','Grep','Glob','Task','TaskCreate',
    'TaskUpdate','TaskList','TaskGet','TaskOutput','WebSearch','WebFetch','Skill'];
  return known.includes(name) ? name : 'default';
}
```

---

## JavaScript Functions — Complete Reference

### DOM Helpers

```javascript
function setHtml(el, html) { el.innerHTML = html; }
function setHtmlById(id, html) { document.getElementById(id).innerHTML = html; }
```

All dynamic content uses `esc()` for HTML escaping. Comment in source: "This dashboard is served on a Tailscale-only network with no external user input."

### Initialization (`DOMContentLoaded`)

```javascript
document.addEventListener('DOMContentLoaded', () => {
  const d = DASHBOARD_DATA;

  // 1. Show rebuild banner if building
  if (d.rebuild_in_progress) {
    document.getElementById('rebuildBanner').style.display = 'flex';
  }

  // 2. Handle empty/building state
  if (!d.overview && (!d.sessions || !d.sessions.length)) {
    // Show "Building Cache" card instead of empty page
    setHtmlById('summaryCards', '...');
    return;
  }

  // 3. Populate header with metadata
  document.getElementById('headerMeta').textContent =
    `Generated ${genAt} | ${sessCount} sessions | ${projCount} projects`;

  // 4. Set up tab switching
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      // Remove active from all tabs/panels, add to clicked
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById(tab.dataset.tab).classList.add('active');
    });
  });

  // 5. Render overview and set up explorer
  renderOverview();
  setupExplorer();
});
```

### Overview Tab Functions

#### `renderOverview()`

Reads `DASHBOARD_DATA.overview` and renders:

1. **Summary cards** (6 cards):
   - Sessions (with date range)
   - Total Active Time (formatted via `fmtDurationMs`)
   - Total Actions (direct + subagent breakdown)
   - Total Tokens (active + cached breakdown)
   - Estimated Cost (with project count)
   - Subagents Spawned

2. **Chart instances** (stored on `window` for later updates):
   - `window._toolPieInst` — Tool Distribution doughnut
   - `window._projectBarInst` — Top Projects horizontal bar
   - `window._timelineInst` — Sessions line chart
   - `window._fileTypeInst` — File Types vertical bar
   - `window._costByProjectInst` — Cost by Project horizontal bar
   - `window._actionsTimelineInst` — Actions multi-line chart
   - `window._activeTimeInst` — Active Time area chart

#### `renderToolPie(data)`

**Type:** Doughnut chart
**Canvas ID:** `toolPieChart`
**Data:** `{tool_name: count, ...}` sorted desc by count
**Colors:** `getToolColor(tool_name)` for each segment
**Options:**
```javascript
{
  responsive: true,
  plugins: {
    legend: { position: 'right', labels: { color: '#8b8fa3', font: { size: 11 } } }
  }
}
```

#### `renderProjectBar(data)`

**Type:** Horizontal bar chart
**Canvas ID:** `projectBarChart`
**Data:** `{project: count, ...}` sorted desc, top 10
**Color:** `#6c8cff` (accent blue)
**Options:**
```javascript
{
  responsive: true,
  indexAxis: 'y',
  plugins: { legend: { display: false } },
  scales: {
    x: { ticks: { color: '#8b8fa3' }, grid: { color: '#2e3347' } },
    y: { ticks: { color: '#e1e4ed', font: { size: 11 } }, grid: { display: false } }
  }
}
```

#### `renderTimeline(data)`

**Type:** Line chart (filled area)
**Canvas ID:** `timelineChart`
**Data:** `{date_bucket: session_count, ...}` sorted asc by key
**Labels:** Formatted via `fmtDate()`
**Dataset:**
```javascript
{
  data: [...],
  borderColor: '#6c8cff',
  backgroundColor: 'rgba(108,140,255,0.1)',
  fill: true,
  tension: 0.3,
  pointRadius: 3
}
```
**Options:**
```javascript
{
  responsive: true,
  plugins: { legend: { display: false } },
  scales: {
    x: { ticks: { color: '#8b8fa3', maxRotation: 45, font: { size: 10 } }, grid: { color: '#2e3347' } },
    y: { ticks: { color: '#8b8fa3' }, grid: { color: '#2e3347' }, beginAtZero: true }
  }
}
```

#### `renderFileTypes(data)`

**Type:** Vertical bar chart
**Canvas ID:** `fileTypeChart`
**Data:** `{extension: count, ...}` sorted desc, top 12
**Color:** `#a78bfa` (purple)
**Options:** Same pattern as projectBar but vertical (no `indexAxis: 'y'`).

#### `renderCostByProject(data)`

**Type:** Horizontal bar chart
**Canvas ID:** `costByProjectChart`
**Data:** `{project: cost_usd, ...}` sorted desc, top 10
**Color:** `#4ade80` (green)
**Special:** Tooltip callback formats as `$X.XX`, x-axis ticks format as `$X`
```javascript
plugins: {
  legend: { display: false },
  tooltip: { callbacks: { label: ctx => '$' + ctx.parsed.x.toFixed(2) } }
},
scales: {
  x: { ticks: { color: '#8b8fa3', callback: v => '$' + v.toFixed(0) }, grid: { color: '#2e3347' } },
  y: { ticks: { color: '#e1e4ed', font: { size: 11 } }, grid: { display: false } }
}
```

#### `renderActionsTimeline(data)`

**Type:** Multi-line chart (3 datasets)
**Canvas ID:** `actionsTimelineChart`
**Data:** `{date_bucket: {total: N, direct: N, subagent: N}, ...}`
**Datasets:**
```javascript
[
  { label: 'Total',    borderColor: '#6c8cff', borderWidth: 2.5, pointRadius: 3 },
  { label: 'Direct',   borderColor: '#a78bfa', borderWidth: 1.5, pointRadius: 2 },
  { label: 'Subagent', borderColor: '#f59e0b', borderWidth: 1.5, pointRadius: 2 }
]
```
**Legend:** Top position, point style `'line'`, color `#8b8fa3`.

#### `renderActiveTime(data)`

**Type:** Line chart (filled area)
**Canvas ID:** `activeTimeChart`
**Data:** `{date_bucket: milliseconds, ...}` — converted to hours (`ms / 3600000`)
**Colors:** Border `#34d399` (emerald), fill `rgba(52,211,153,0.1)`
**Special:** Tooltip shows `X.X hours`, y-axis ticks show `Xh`.

#### `switchTimeline(granularity)`

Switches the 3 "Trends Over Time" charts between daily/weekly/monthly.

```javascript
function switchTimeline(granularity) {
  // granularity: 'daily' | 'weekly' | 'monthly'
  const ov = DASHBOARD_DATA.overview;
  const sessMap  = { daily: ov.daily_timeline,    weekly: ov.weekly_timeline,    monthly: ov.monthly_timeline };
  const actMap   = { daily: ov.actions_daily,     weekly: ov.actions_weekly,     monthly: ov.actions_monthly };
  const timeMap  = { daily: ov.active_time_daily, weekly: ov.active_time_weekly, monthly: ov.active_time_monthly };

  renderTimeline(sessMap[granularity] || {});
  renderActionsTimeline(actMap[granularity] || {});
  renderActiveTime(timeMap[granularity] || {});

  // Update pill active state
  document.querySelectorAll('#timelinePills .cat-pill').forEach(p => {
    p.classList.toggle('active', p.dataset.g === granularity);
  });
}
```

#### `switchAllRanges(range)`

Switches the 4 "Activity by Time Range" charts between all/1d/7d/30d.

```javascript
function switchAllRanges(range) {
  // range: 'all' | '1d' | '7d' | '30d'
  const ov = DASHBOARD_DATA.overview;
  const suffix = range === 'all' ? '' : '_' + range;

  renderToolPie(ov['tool_distribution' + suffix] || {});
  renderProjectBar(ov['projects_chart' + suffix] || {});
  renderFileTypes(ov['file_types_chart' + suffix] || {});
  renderCostByProject(ov['cost_by_project' + suffix] || {});

  // Update pill active state
  document.querySelectorAll('#rangeChartPills .cat-pill').forEach(p => {
    p.classList.toggle('active', p.dataset.r === range);
  });
}
```

### Explorer Tab Functions

#### `setupExplorer()`

Called once on init. Sets up:

1. **Project dropdown**: Populated from `DASHBOARD_DATA.overview.projects_list` or derived from sessions via `Set`.

2. **Session dropdown**: Populated by `populateSessions(project)` — filters sessions by project, formats each option as:
   ```
   [{date}] {preview} ({total_actions} actions)
   ```

3. **Event listeners**:
   - Project change → repopulate sessions, hide detail
   - Session change → async fetch detail from API

4. **Async session loading**:
   ```javascript
   sessSelect.addEventListener('change', async () => {
     const sid = sessSelect.value;
     if (!sid) { hideSessionDetail(); return; }

     // Show loading spinner
     document.getElementById('sessionLoading').style.display = 'block';

     try {
       const resp = await fetch(`${rootPath}/api/session/${sid}`);
       const session = await resp.json();
       showSessionDetail(session);
     } catch (err) {
       // Show error in empty state div
     }
   });
   ```

#### `hideSessionDetail()`

Hides session detail panel, shows empty state, clears `currentSession`.

#### `showSessionDetail(s)`

The main session rendering function. Takes a full session detail object (from `/api/session/{id}`) and renders:

1. **Title**: `s.slug || s.session_id.slice(0, 12)`

2. **Prompt text**: `s.first_prompt` in a `.prompt-text` div

3. **Conversation flow**: If `s.user_turns.length > 1`, renders a `<details>` accordion with all turns. Each turn has:
   - Turn number badge
   - Timestamp (right-aligned)
   - Text content (HTML-escaped)
   - `.interrupt` class for interrupted turns

4. **Meta row**: Badges for project, date, model, turns, active time (with wall clock), tokens (with cache %), cost, action count, subagent count, thinking level, permission mode, error count, interrupt count

5. **Tool donut chart**: Combines parent `s.tool_counts` + all subagent `sa.tool_counts` into one merged object

6. **File operations table**: Groups files by extension, sorts by operation count, shows Read/Write/Edit columns, max 30 rows with overflow message. Uses `shortenPath()` for long paths.

7. **Bash commands**: If any exist:
   - Bash category donut chart (with tooltip descriptions from `BASH_CAT_DESCRIPTIONS`)
   - Category filter pills (clickable)
   - Bash commands table (max 25 rows): command, category, count

8. **Subagents section**: Collapsible cards, each with:
   - Type badge (`agent-type-badge`)
   - Task description or agent type as header
   - Tool count and active time
   - Expandable body with: task prompt, tool summary, tool calls table (max 30 rows)

9. **Action log update**: Calls `renderActionLog(s)` to prepare the Log tab

#### `toggleSubagent(idx)`

Toggles `.open` class on subagent body and arrow elements.

#### `filterBashCat(cat)`

Filters bash command table rows by category. `cat='all'` shows all.
```javascript
document.querySelectorAll('#bashTableBody tr').forEach(row => {
  row.style.display = (cat === 'all' || row.dataset.cat === cat) ? '' : 'none';
});
```

### Action Log Tab Functions

#### `renderActionLog(s)`

Prepares the action log from a session:

1. **Merge all tool calls**: Combines `s.tool_calls` (parent) with all subagent tool calls, adding `is_subagent: true` and `agent_id` to subagent entries.

2. **Sort by time**: `a.time.localeCompare(b.time)`

3. **Assign sequential numbers**: `c._seq = i + 1`

4. **Build tool filter checkboxes**: One checkbox per unique tool type, all checked by default.

5. **Render first page**: Calls `renderLogPage(allCalls)`

#### `renderLogPage(allCalls)`

Paginated rendering:

```javascript
const filtered = allCalls.filter(c => logToolFilters.has(c.tool));
const totalPages = Math.ceil(filtered.length / LOG_PAGE_SIZE);  // 50 per page
const page = filtered.slice(start, start + LOG_PAGE_SIZE);
```

Each row:
| Column | Content |
|--------|---------|
| # | Sequential number |
| Time | `fmtTime(c.time)` (HH:MM:SS) |
| Tool | Tool badge with colored class |
| Detail | `c.detail.slice(0, 150)`, full text in `title` attr |
| Source | "main" or "agent-{id}" (colored purple for subagents) |

Pagination buttons call `logPageNav(delta)`.

Stores `allCalls` on `window._logAllCalls` for pagination navigation.

#### `logPageNav(delta)`

```javascript
function logPageNav(delta) {
  logPage += delta;
  renderLogPage(window._logAllCalls);
}
```

### Helper Functions

#### `fmtDurationMs(ms)` — Format milliseconds to human-readable

```javascript
function fmtDurationMs(ms) {
  if (!ms || ms <= 0) return null;
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ${secs % 60}s`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ${mins % 60}m`;
}
```

Returns `null` for zero/negative values (callers check for `null`).

#### `fmtTokenCount(n)` — Format token counts with K/M suffixes

```javascript
function fmtTokenCount(n) {
  if (!n) return '0';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return n.toLocaleString();
}
```

#### `esc(s)` — HTML escape

```javascript
function esc(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
```

Uses DOM-based escaping (creates a div, sets `textContent`, reads `innerHTML`).

#### `fmtDate(ts)` — Short date format

```javascript
function fmtDate(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  } catch(e) { return ts.slice(0,10); }
}
```
Output: `"Feb 15"`, `"Jan 3"`, etc.

#### `fmtDateTime(ts)` — Date + time format

```javascript
function fmtDateTime(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  } catch(e) { return ts; }
}
```
Output: `"Feb 15, 10:30 AM"`

#### `fmtTime(ts)` — Time only

```javascript
function fmtTime(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch(e) { return ts; }
}
```
Output: `"10:30:05 AM"`

#### `shortenPath(p)` — Truncate long file paths

```javascript
function shortenPath(p) {
  const parts = p.split('/');
  if (parts.length <= 4) return p;
  return '.../' + parts.slice(-3).join('/');
}
```
Example: `/home/pi/python/claude_analysis/app.py` → `.../claude_analysis/app.py`

#### `calcDuration(start, end)` — Wall-clock duration

```javascript
function calcDuration(start, end) {
  try {
    const ms = new Date(end) - new Date(start);
    if (ms < 0) return null;
    const mins = Math.floor(ms / 60000);
    if (mins < 1) return '<1 min';
    if (mins < 60) return `${mins} min`;
    const hrs = Math.floor(mins / 60);
    const rem = mins % 60;
    return `${hrs}h ${rem}m`;
  } catch(e) { return null; }
}
```

---

## Chart Summary (All 7 Overview + 2 Explorer Charts)

### Overview Charts (7)

| Chart | Canvas ID | Type | Data Key | Time-filtered? | Granularity? |
|-------|-----------|------|----------|---------------|-------------|
| Tool Distribution | `toolPieChart` | doughnut | `tool_distribution` | Yes (1d/7d/30d) | No |
| Top Projects | `projectBarChart` | bar (horizontal) | `projects_chart` | Yes (1d/7d/30d) | No |
| File Types | `fileTypeChart` | bar (vertical) | `file_types_chart` | Yes (1d/7d/30d) | No |
| Cost by Project | `costByProjectChart` | bar (horizontal) | `cost_by_project` | Yes (1d/7d/30d) | No |
| Sessions Timeline | `timelineChart` | line (filled) | `weekly_timeline` | No | Yes (daily/weekly/monthly) |
| Actions Timeline | `actionsTimelineChart` | line (3 series) | `actions_weekly` | No | Yes (daily/weekly/monthly) |
| Active Time | `activeTimeChart` | line (filled) | `active_time_weekly` | No | Yes (daily/weekly/monthly) |

### Explorer Charts (2)

| Chart | Canvas ID | Type | Data Source |
|-------|-----------|------|-------------|
| Session Tool Breakdown | `sessionToolChart` | doughnut | Combined `tool_counts` (parent + subagents) |
| Bash Categories | `bashCatChart` | doughnut | `bash_category_summary` from session |

### Chart.js Common Patterns

- **All doughnut charts**: `borderWidth: 0` (no segment borders)
- **All bar charts**: `borderRadius: 4` (rounded corners)
- **All line charts**: `tension: 0.3` (smooth curves), `pointRadius: 2-3`
- **Legend colors**: Always `#8b8fa3` (text-dim)
- **Grid colors**: Always `#2e3347` (border color)
- **Tick colors**: `#8b8fa3` for axes, `#e1e4ed` for category labels
- **Chart instances**: Stored on `window._*Inst` (overview) or module-level vars (explorer), destroyed before re-creating

---

## Data Flow Summary

```
Page Load
    │
    ├── DASHBOARD_DATA injected (overview + session summaries)
    │
    ├── renderOverview() → 7 overview charts
    │
    └── setupExplorer() → project/session dropdowns
                              │
                              └── User selects session
                                    │
                                    ├── fetch(`${rootPath}/api/session/${sid}`)
                                    │
                                    └── showSessionDetail(session)
                                          ├── Session summary + meta badges
                                          ├── Tool donut + file ops table
                                          ├── Bash chart + commands table
                                          ├── Subagent cards
                                          └── renderActionLog() → paginated log
```

---

## Recreation Notes

1. **Single file**: Everything goes in one HTML file. No external CSS or JS files.
2. **No template engine**: The HTML is a static file with one `const DASHBOARD_DATA = {};` placeholder. app.py does a string replacement.
3. **Chart.js version**: Must be 4.4.7 for API compatibility.
4. **Dark theme only**: No light mode toggle.
5. **Responsive**: Only one breakpoint at 900px (stacks 2-column grids to 1 column).
6. **No CDN fallback**: Chart.js is the only external dependency. If CDN is down, charts won't render.
7. **HTML escaping**: All dynamic content goes through `esc()`. The `setHtml()` function is used for pre-escaped HTML strings.
8. **Session loading**: Session details are NOT in the initial payload. They're fetched via `fetch()` when a user selects a session from the dropdown. This keeps the initial HTML payload small (~33KB gzipped).
