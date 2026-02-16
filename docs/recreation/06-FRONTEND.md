# 06 - Frontend: dashboard_template.html

Complete reference for recreating the Claude Activity Dashboard frontend -- a single-file HTML/CSS/JS dashboard (985 lines) that renders all visualizations for the Claude Code Activity service.

**Source file**: `/home/pi/python/claude_analysis/dashboard_template.html`

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [HTML Head](#2-html-head)
3. [CSS Design System](#3-css-design-system)
4. [HTML Body Structure](#4-html-body-structure)
5. [JavaScript: Data Injection and State](#5-javascript-data-injection-and-state)
6. [JavaScript: Color Maps](#6-javascript-color-maps)
7. [JavaScript: Helper Functions](#7-javascript-helper-functions)
8. [JavaScript: Initialization](#8-javascript-initialization)
9. [JavaScript: Overview Tab](#9-javascript-overview-tab)
10. [JavaScript: Chart Rendering Functions](#10-javascript-chart-rendering-functions)
11. [JavaScript: Timeline and Range Switching](#11-javascript-timeline-and-range-switching)
12. [JavaScript: Task Explorer Tab](#12-javascript-task-explorer-tab)
13. [JavaScript: Action Log Tab](#13-javascript-action-log-tab)
14. [Data Contracts](#14-data-contracts)
15. [Chart.js Configuration Patterns](#15-chartjs-configuration-patterns)
16. [Complete Data Flow](#16-complete-data-flow)

---

## 1. Architecture Overview

The dashboard is a **single HTML file** containing all CSS and JavaScript inline. It follows a server-side template injection pattern:

```
app.py reads dashboard_template.html
  -> replaces `const DASHBOARD_DATA = {};` with actual JSON
  -> returns as HTMLResponse
```

The template is NOT a Jinja2 template. It uses simple string replacement in `app.py`:

```python
template = TEMPLATE_PATH.read_text(encoding="utf-8")
data_json = json.dumps(init_data, ensure_ascii=False, default=str)
data_json = data_json.replace("</", r"<\/")  # Prevent script injection via </script>
html = template.replace(
    "const DASHBOARD_DATA = {};",
    f"const DASHBOARD_DATA = {data_json};",
)
return HTMLResponse(content=html)
```

The injected `init_data` has this shape:

```python
{
    "overview": overview,          # Pre-computed global aggregates (~5KB)
    "sessions": sessions,          # Lightweight session summaries (~30-50KB)
    "rebuild_in_progress": bool,   # Whether background rebuild is active
}
```

Session detail data is NOT injected at page load. It is fetched lazily via `fetch()` when the user selects a session:

```
GET /api/session/{session_id}  ->  Full session JSON
```

**External dependency**: Chart.js 4.4.7 loaded from CDN.

---

## 2. HTML Head

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<!-- iPhone Home Screen icon -->
<link rel="apple-touch-icon" sizes="180x180"
      href="/claude_activity/app_icon.jpg?v=20260216">

<!-- Home Screen label (shows "Task Monitor" under icon) -->
<meta name="apple-mobile-web-app-title" content="Task Monitor">
<meta name="application-name" content="Task Monitor">

<!-- Standalone mode (no Safari chrome) -->
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">

<title>Claude Code Activity Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
```

Key details:
- The `apple-touch-icon` href doubles as the root path detector in JavaScript (see Section 5).
- The `?v=20260216` cache-busting parameter should be updated when the icon changes.
- PWA metas enable "Add to Home Screen" on iOS and Android with standalone (no browser chrome) display.

---

## 3. CSS Design System

### 3.1 CSS Variables (Dark Theme)

All colors are defined as CSS custom properties on `:root`:

```css
:root {
  --bg: #0f1117;        /* Page background - near-black with blue tint */
  --surface: #1a1d27;   /* Card/panel background */
  --surface2: #242836;  /* Nested surface (inputs, code blocks) */
  --border: #2e3347;    /* Border color for all containers */
  --text: #e1e4ed;      /* Primary text */
  --text-dim: #8b8fa3;  /* Secondary/muted text */
  --accent: #6c8cff;    /* Primary accent (blue) */
  --accent2: #a78bfa;   /* Secondary accent (purple) */
  --green: #4ade80;     /* Success/positive */
  --orange: #fb923c;    /* Warning/interrupts */
  --red: #f87171;       /* Error/danger */
  --cyan: #22d3ee;      /* Info/alternative */
  --pink: #f472b6;      /* Bash/terminal */
}
```

### 3.2 Reset and Base

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

### 3.3 Complete CSS Class Reference

#### Layout Classes

| Class | Element | Properties |
|-------|---------|------------|
| `.header` | `<div>` | `background: var(--surface); border-bottom: 1px solid var(--border); padding: 16px 24px; display: flex; align-items: center; justify-content: space-between;` |
| `.header h1` | `<h1>` | `font-size: 20px; font-weight: 600;` |
| `.header .meta` | `<div>` | `font-size: 13px; color: var(--text-dim);` |
| `.tabs` | `<div>` | `display: flex; gap: 0; background: var(--surface); border-bottom: 1px solid var(--border); padding: 0 24px;` |
| `.tab` | `<div>` | `padding: 12px 20px; cursor: pointer; font-size: 14px; font-weight: 500; color: var(--text-dim); border-bottom: 2px solid transparent; transition: all 0.2s;` |
| `.tab:hover` | hover state | `color: var(--text);` |
| `.tab.active` | active tab | `color: var(--accent); border-bottom-color: var(--accent);` |
| `.content` | `<div>` | `padding: 24px; max-width: 1400px; margin: 0 auto;` |
| `.tab-panel` | `<div>` | `display: none;` |
| `.tab-panel.active` | visible panel | `display: block;` |

#### Card Classes

| Class | Element | Properties |
|-------|---------|------------|
| `.cards` | grid container | `display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px;` |
| `.card` | card container | `background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 20px;` |
| `.card .label` | card heading | `font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-dim); margin-bottom: 4px;` |
| `.card .value` | large number | `font-size: 28px; font-weight: 700;` |
| `.card .sub` | subtitle | `font-size: 12px; color: var(--text-dim); margin-top: 4px;` |

#### Chart Classes

| Class | Element | Properties |
|-------|---------|------------|
| `.charts-grid` | 2-column grid | `display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px;` |
| `.chart-box` | chart wrapper | `background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 20px;` |
| `.chart-box h3` | chart title | `font-size: 14px; font-weight: 600; margin-bottom: 12px; color: var(--text-dim);` |
| `.chart-box canvas` | chart canvas | `max-height: 300px;` |

The "Trends Over Time" section overrides `.charts-grid` to 3 columns inline:
```html
<div class="charts-grid" style="grid-template-columns:1fr 1fr 1fr">
```

#### Explorer Classes

| Class | Element | Properties |
|-------|---------|------------|
| `.explorer-controls` | controls bar | `display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap;` |
| `.explorer-controls select` | dropdown | `background: var(--surface2); border: 1px solid var(--border); color: var(--text); padding: 8px 12px; border-radius: 6px; font-size: 14px; min-width: 200px;` |
| `.explorer-controls select:focus` | focus state | `outline: none; border-color: var(--accent);` |
| `select option` | option items | `background: var(--surface2); color: var(--text);` |

#### Session Summary Classes

| Class | Element | Properties |
|-------|---------|------------|
| `.session-summary` | summary card | `background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 20px; margin-bottom: 20px;` |
| `.session-summary h2` | session title | `font-size: 16px; margin-bottom: 12px;` |
| `.prompt-text` | prompt display | `background: var(--surface2); padding: 12px; border-radius: 6px; font-size: 13px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; max-height: 200px; overflow-y: auto; margin-bottom: 12px;` |
| `.meta-row` | metadata bar | `display: flex; gap: 20px; flex-wrap: wrap; font-size: 13px; color: var(--text-dim);` |
| `.meta-row span` | each item | `display: flex; align-items: center; gap: 4px;` |
| `.meta-row .badge` | action badge | `background: var(--accent); color: #fff; padding: 2px 8px; border-radius: 10px; font-size: 12px; font-weight: 600;` |

#### Detail Grid Classes

| Class | Element | Properties |
|-------|---------|------------|
| `.detail-grid` | 2-column grid | `display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px;` |

Responsive override at `max-width: 900px`:
```css
@media (max-width: 900px) {
  .detail-grid, .charts-grid { grid-template-columns: 1fr; }
}
```

#### Table Classes

| Class | Element | Properties |
|-------|---------|------------|
| `.table-box` | table wrapper | `background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; overflow-x: auto;` |
| `.table-box h3` | table title | `font-size: 14px; font-weight: 600; margin-bottom: 10px; color: var(--text-dim);` |
| `table` | table element | `width: 100%; border-collapse: collapse; font-size: 13px;` |
| `th` | header cell | `text-align: left; padding: 8px; border-bottom: 1px solid var(--border); color: var(--text-dim); font-weight: 500; font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;` |
| `td` | data cell | `padding: 6px 8px; border-bottom: 1px solid var(--border);` |
| `tr:last-child td` | last row | `border-bottom: none;` |
| `td.mono` | monospace cell | `font-family: 'SF Mono', 'Fira Code', monospace; font-size: 12px;` |

#### Tool Badge Classes

Base class plus per-tool color overrides:

```css
.tool-badge {
  display: inline-block; padding: 2px 8px;
  border-radius: 4px; font-size: 11px; font-weight: 600;
}
```

| Class | Background | Text Color |
|-------|-----------|------------|
| `.tool-badge.Read` | `#1e3a5f` | `#60a5fa` |
| `.tool-badge.Write` | `#1a3d2e` | `var(--green)` |
| `.tool-badge.Edit` | `#3d2e1a` | `var(--orange)` |
| `.tool-badge.Bash` | `#3d1a2e` | `var(--pink)` |
| `.tool-badge.Grep` | `#2e1a3d` | `var(--accent2)` |
| `.tool-badge.Glob` | `#1a2e3d` | `var(--cyan)` |
| `.tool-badge.Task`, `.TaskCreate`, `.TaskUpdate`, `.TaskList`, `.TaskGet`, `.TaskOutput` | `#2d2d1a` | `#facc15` |
| `.tool-badge.WebSearch`, `.WebFetch` | `#1a3d3d` | `#2dd4bf` |
| `.tool-badge.Skill` | `#3d3d1a` | `#fde047` |
| `.tool-badge.default` | `var(--surface2)` | `var(--text-dim)` |

The pattern for each tool badge is a dark, tinted background with a bright foreground of the same hue -- creating a "chip" look.

#### Subagent Card Classes

| Class | Element | Properties |
|-------|---------|------------|
| `.subagent-card` | card wrapper | `background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 12px;` |
| `.subagent-header` | clickable header | `padding: 12px 16px; cursor: pointer; display: flex; justify-content: space-between; align-items: center;` |
| `.subagent-header:hover` | hover | `background: rgba(108, 140, 255, 0.05);` |
| `.subagent-header .agent-label` | agent name | `font-size: 13px; font-weight: 600; color: var(--accent2);` |
| `.agent-type-badge` | type pill | `display: inline-block; background: var(--accent2); color: #fff; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; margin-right: 6px; vertical-align: middle;` |
| `.subagent-header .agent-meta` | tool count | `font-size: 12px; color: var(--text-dim);` |
| `.subagent-body` | collapsed body | `padding: 0 16px 16px; display: none;` |
| `.subagent-body.open` | expanded body | `display: block;` |
| `.subagent-desc` | task prompt | `font-size: 12px; color: var(--text-dim); margin-bottom: 8px; line-height: 1.5; background: var(--surface); padding: 8px 10px; border-radius: 4px; max-height: 120px; overflow-y: auto; white-space: pre-wrap; word-break: break-word;` |
| `.arrow` | expand arrow | `transition: transform 0.2s; display: inline-block;` |
| `.arrow.open` | rotated state | `transform: rotate(90deg);` |

#### Pagination Classes

| Class | Element | Properties |
|-------|---------|------------|
| `.pagination` | container | `display: flex; gap: 8px; align-items: center; justify-content: center; margin-top: 12px; font-size: 13px;` |
| `.pagination button` | nav button | `background: var(--surface2); border: 1px solid var(--border); color: var(--text); padding: 6px 12px; border-radius: 4px; cursor: pointer;` |
| `.pagination button:hover` | hover | `border-color: var(--accent);` |
| `.pagination button:disabled` | disabled | `opacity: 0.3; cursor: default;` |
| `.pagination .page-info` | page text | `color: var(--text-dim);` |

#### Filter Bar Classes

| Class | Element | Properties |
|-------|---------|------------|
| `.filter-bar` | container | `display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; align-items: center;` |
| `.filter-bar label` | checkbox label | `font-size: 12px; display: flex; align-items: center; gap: 4px; cursor: pointer; color: var(--text-dim);` |
| `.filter-bar label:hover` | hover | `color: var(--text);` |
| `.filter-bar input[type="checkbox"]` | checkbox | `accent-color: var(--accent);` |

#### Conversation Flow Classes

| Class | Element | Properties |
|-------|---------|------------|
| `.conversation-flow` | container | `margin-top: 12px;` |
| `.conversation-flow summary` | toggle | `cursor: pointer; font-size: 13px; color: var(--text-dim); padding: 6px 0; user-select: none;` |
| `.conversation-flow summary:hover` | hover | `color: var(--text);` |
| `.turn-list` | list | `list-style: none; padding: 8px 0 0 0; display: flex; flex-direction: column; gap: 6px;` |
| `.turn-item` | normal turn | `background: var(--surface2); border-left: 3px solid var(--accent); padding: 8px 12px; border-radius: 0 6px 6px 0; font-size: 13px; line-height: 1.4;` |
| `.turn-item.interrupt` | interrupted turn | `border-left-color: var(--orange); font-style: italic; color: var(--text-dim); background: rgba(251, 146, 60, 0.08);` |
| `.turn-number` | turn # prefix | `font-size: 11px; color: var(--text-dim); margin-right: 6px; font-weight: 600;` |
| `.turn-time` | timestamp | `font-size: 11px; color: var(--text-dim); float: right;` |

#### Miscellaneous Classes

| Class | Element | Properties |
|-------|---------|------------|
| `.badge-orange` | interrupt badge | `background: rgba(251, 146, 60, 0.2); color: var(--orange);` |
| `.category-pills` | pill container | `display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px;` |
| `.cat-pill` | filter pill | `display: inline-block; padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; cursor: pointer; border: 1px solid var(--border); background: var(--surface2); color: var(--text-dim); transition: all 0.15s; user-select: none;` |
| `.cat-pill:hover` | hover | `border-color: var(--accent); color: var(--text);` |
| `.cat-pill.active` | active pill | `background: var(--accent); color: #fff; border-color: var(--accent);` |
| `.cat-pill .cat-count` | count label | `opacity: 0.7; margin-left: 2px;` |
| `.empty-state` | placeholder | `text-align: center; padding: 60px 20px; color: var(--text-dim);` |
| `.empty-state h3` | heading | `margin-bottom: 8px; color: var(--text);` |
| `.loading-spinner` | spinner wrapper | `text-align: center; padding: 40px; color: var(--text-dim);` |
| `.loading-spinner::before` | spinner circle | `content: ''; display: inline-block; width: 24px; height: 24px; border: 3px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; margin-bottom: 12px;` |
| `.loading-spinner p` | text below | `margin-top: 8px; font-size: 13px;` |
| `.rebuild-banner` | banner | `background: var(--surface2); border: 1px solid var(--accent); border-radius: 8px; padding: 12px 20px; margin-bottom: 16px; font-size: 13px; color: var(--accent); display: flex; align-items: center; gap: 8px;` |
| `.rebuild-banner::before` | spinner | `content: ''; display: inline-block; width: 12px; height: 12px; border: 2px solid var(--accent); border-top-color: transparent; border-radius: 50%; animation: spin 0.8s linear infinite;` |

#### CSS Animation

```css
@keyframes spin { to { transform: rotate(360deg); } }
```

Used by both `.loading-spinner::before` and `.rebuild-banner::before`.

---

## 4. HTML Body Structure

### 4.1 Top-Level Layout

```
<body>
  <div class="header">
    <h1>Claude Code Activity Dashboard</h1>
    <div class="meta" id="headerMeta"></div>
  </div>

  <div class="tabs">
    <div class="tab active" data-tab="overview">Overview</div>
    <div class="tab" data-tab="explorer">Task Explorer</div>
    <div class="tab" data-tab="log">Action Log</div>
  </div>

  <div class="content">
    <div id="overview" class="tab-panel active">...</div>
    <div id="explorer" class="tab-panel">...</div>
    <div id="log" class="tab-panel">...</div>
  </div>
</body>
```

Tab switching uses `data-tab` attributes matched to panel `id`s. The JS toggles `.active` class on both the `.tab` and corresponding `.tab-panel`.

### 4.2 Overview Tab (`#overview`)

```html
<div id="overview" class="tab-panel active">
  <!-- Rebuild banner (hidden by default, shown when rebuild_in_progress) -->
  <div id="rebuildBanner" style="display:none;" class="rebuild-banner">
    Cache is being built in the background. Data will appear shortly.
  </div>

  <!-- 6 summary cards (populated by renderOverview()) -->
  <div class="cards" id="summaryCards"></div>

  <!-- "Activity by Time Range" section -->
  <div style="margin-bottom:24px">
    <div style="display:flex;justify-content:space-between;align-items:center;
                margin-bottom:12px;flex-wrap:wrap;gap:8px">
      <h3 style="margin:0;font-size:14px;font-weight:600;color:var(--text-dim)">
        Activity by Time Range</h3>
      <div class="category-pills" id="rangeChartPills" style="margin:0">
        <span class="cat-pill active" data-r="all"
              onclick="switchAllRanges('all')">All</span>
        <span class="cat-pill" data-r="1d"
              onclick="switchAllRanges('1d')">Day</span>
        <span class="cat-pill" data-r="7d"
              onclick="switchAllRanges('7d')">Week</span>
        <span class="cat-pill" data-r="30d"
              onclick="switchAllRanges('30d')">Month</span>
      </div>
    </div>
    <div class="charts-grid">  <!-- 2x2 grid -->
      <div class="chart-box">
        <h3>Tool Distribution</h3>
        <canvas id="toolPieChart"></canvas>
      </div>
      <div class="chart-box">
        <h3>Top Projects by Actions</h3>
        <canvas id="projectBarChart"></canvas>
      </div>
      <div class="chart-box">
        <h3>File Types Touched</h3>
        <canvas id="fileTypeChart"></canvas>
      </div>
      <div class="chart-box">
        <h3>Cost by Project</h3>
        <canvas id="costByProjectChart"></canvas>
      </div>
    </div>
  </div>

  <!-- "Trends Over Time" section -->
  <div style="margin-bottom:24px">
    <div style="display:flex;justify-content:space-between;align-items:center;
                margin-bottom:12px;flex-wrap:wrap;gap:8px">
      <h3 style="margin:0;font-size:14px;font-weight:600;color:var(--text-dim)">
        Trends Over Time</h3>
      <div class="category-pills" id="timelinePills" style="margin:0">
        <span class="cat-pill" data-g="daily"
              onclick="switchTimeline('daily')">Daily</span>
        <span class="cat-pill active" data-g="weekly"
              onclick="switchTimeline('weekly')">Weekly</span>
        <span class="cat-pill" data-g="monthly"
              onclick="switchTimeline('monthly')">Monthly</span>
      </div>
    </div>
    <div class="charts-grid"
         style="grid-template-columns:1fr 1fr 1fr">  <!-- 3-column -->
      <div class="chart-box">
        <h3>Sessions</h3><canvas id="timelineChart"></canvas>
      </div>
      <div class="chart-box">
        <h3>Actions</h3><canvas id="actionsTimelineChart"></canvas>
      </div>
      <div class="chart-box">
        <h3>Active Time</h3><canvas id="activeTimeChart"></canvas>
      </div>
    </div>
  </div>
</div>
```

The 6 summary cards rendered by `renderOverview()` are:

1. **Sessions** -- `ov.total_sessions`, sub: date range
2. **Total Active Time** -- `fmtDurationMs(ov.total_active_ms)`, sub: "Claude working time across all sessions"
3. **Total Actions** -- `ov.total_actions`, sub: direct + subagent breakdown
4. **Total Tokens** -- active + cached, sub: breakdown
5. **Estimated Cost** -- `~$X.XX`, sub: project count
6. **Subagents Spawned** -- `ov.subagent_count`

### 4.3 Task Explorer Tab (`#explorer`)

```html
<div id="explorer" class="tab-panel">
  <!-- Dropdowns -->
  <div class="explorer-controls">
    <select id="projectFilter">
      <option value="">All Projects</option>
    </select>
    <select id="sessionSelect">
      <option value="">Select a session...</option>
    </select>
  </div>

  <!-- Loading spinner (hidden until session fetch) -->
  <div id="sessionLoading" class="loading-spinner" style="display:none;">
    <p>Loading session detail...</p>
  </div>

  <!-- Session detail (hidden until loaded) -->
  <div id="sessionDetail" style="display:none;">
    <div class="session-summary">
      <h2 id="sessionTitle"></h2>
      <div class="prompt-text" id="promptText"></div>
      <div class="conversation-flow" id="conversationFlow"
           style="display:none;"></div>
      <div class="meta-row" id="sessionMeta"></div>
    </div>

    <div class="detail-grid">
      <div class="chart-box">
        <h3>Tool Breakdown</h3>
        <canvas id="sessionToolChart"></canvas>
      </div>
      <div class="table-box">
        <h3>File Operations</h3>
        <div id="fileOpsTable"></div>
      </div>
    </div>

    <div class="detail-grid" style="margin-bottom:20px;">
      <div class="chart-box" id="bashChartBox" style="display:none;">
        <h3>Bash Command Categories</h3>
        <canvas id="bashCatChart"></canvas>
      </div>
      <div class="table-box">
        <h3>Bash Commands</h3>
        <div id="bashTable"></div>
      </div>
    </div>

    <div id="subagentsSection"></div>
  </div>

  <!-- Empty state (visible by default) -->
  <div id="explorerEmpty" class="empty-state">
    <h3>Select a session to explore</h3>
    <p>Choose a project and session from the dropdowns above.</p>
  </div>
</div>
```

### 4.4 Action Log Tab (`#log`)

```html
<div id="log" class="tab-panel">
  <div id="logContent">
    <!-- No session selected state -->
    <div id="logNoSession" class="empty-state">
      <h3>No session selected</h3>
      <p>Select a session in the Task Explorer tab first,
         then come back here to see the full action log.</p>
    </div>

    <!-- Active log (hidden until session loaded) -->
    <div id="logActive" style="display:none;">
      <div class="filter-bar" id="toolFilters"></div>
      <div class="table-box">
        <table>
          <thead>
            <tr>
              <th>#</th><th>Time</th><th>Tool</th>
              <th>Detail</th><th>Source</th>
            </tr>
          </thead>
          <tbody id="logTableBody"></tbody>
        </table>
      </div>
      <div class="pagination" id="logPagination"></div>
    </div>
  </div>
</div>
```

---

## 5. JavaScript: Data Injection and State

### 5.1 Data Injection

```javascript
// Placeholder replaced by app.py with actual JSON at serve time
const DASHBOARD_DATA = {};
```

After injection, `DASHBOARD_DATA` has this shape:

```javascript
{
  overview: { /* global aggregates - see Section 14.1 */ },
  sessions: [ /* lightweight session summaries - see Section 14.2 */ ],
  rebuild_in_progress: false
}
```

### 5.2 Root Path Resolution

```javascript
const rootPath = document.querySelector('link[rel="apple-touch-icon"]')
  ?.href?.match(/(.*)\/app_icon/)?.[1] || '/claude_activity';
```

This extracts the base URL path from the apple-touch-icon `<link>` tag. The icon href is `/claude_activity/app_icon.jpg?v=...`, so the regex captures the full origin + path prefix (e.g., `http://100.99.217.84/claude_activity`). This makes API calls work regardless of whether the dashboard is served behind a reverse proxy prefix or at root. The fallback is `'/claude_activity'`.

### 5.3 State Variables

```javascript
let currentSession = null;          // Full session detail object (from API)
let sessionToolChart = null;        // Chart.js instance for session tool donut
let bashCatChart = null;            // Chart.js instance for bash category donut
let logPage = 1;                    // Current page in action log
const LOG_PAGE_SIZE = 50;           // Actions per page
let logToolFilters = new Set();     // Active tool type filters for action log
```

---

## 6. JavaScript: Color Maps

### 6.1 TOOL_COLORS (22 entries)

Maps tool names to hex colors. Used by chart datasets.

```javascript
const TOOL_COLORS = {
  Read: '#60a5fa',           // Blue
  Write: '#4ade80',          // Green
  Edit: '#fb923c',           // Orange
  Bash: '#f472b6',           // Pink
  Grep: '#a78bfa',           // Purple
  Glob: '#22d3ee',           // Cyan
  Task: '#facc15',           // Yellow (generic Task)
  TaskCreate: '#facc15',     // Yellow
  TaskUpdate: '#fbbf24',     // Amber
  TaskList: '#f59e0b',       // Darker amber
  TaskGet: '#d97706',        // Dark amber
  TaskOutput: '#b45309',     // Brown-amber
  WebSearch: '#2dd4bf',      // Teal
  WebFetch: '#14b8a6',       // Darker teal
  Skill: '#fde047',          // Light yellow
  AskUserQuestion: '#c084fc', // Light purple
  EnterPlanMode: '#7c3aed',  // Violet
  ExitPlanMode: '#6d28d9',   // Dark violet
  NotebookEdit: '#f0abfc',   // Light pink
  TaskStop: '#a3a3a3',       // Gray
  TodoWrite: '#a3e635',      // Lime green
};
```

Lookup function with fallback:

```javascript
function getToolColor(name) { return TOOL_COLORS[name] || '#8b8fa3'; }
```

### 6.2 BASH_CAT_COLORS (7 entries)

Maps bash command categories to colors. Used by the bash category donut chart.

```javascript
const BASH_CAT_COLORS = {
  'Version Control': '#6c8cff',      // Blue (accent)
  'Running Code': '#4ade80',         // Green
  'Searching & Reading': '#a78bfa',  // Purple
  'File Management': '#fb923c',      // Orange
  'Testing & Monitoring': '#22d3ee', // Cyan
  'Server & System': '#f472b6',      // Pink
  'Other': '#8b8fa3',               // Gray (text-dim)
};
```

### 6.3 BASH_CAT_DESCRIPTIONS (7 entries)

Plain-language descriptions used in chart tooltips (`afterLabel` callback):

```javascript
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

### 6.4 Tool Badge Class Resolver

```javascript
function getToolBadgeClass(name) {
  const known = ['Read','Write','Edit','Bash','Grep','Glob','Task',
    'TaskCreate','TaskUpdate','TaskList','TaskGet','TaskOutput',
    'WebSearch','WebFetch','Skill'];
  return known.includes(name) ? name : 'default';
}
```

Returns the tool name if it has a matching CSS class, otherwise `'default'`. Used to set the CSS class on `<span class="tool-badge ${class}">`.

---

## 7. JavaScript: Helper Functions

### 7.1 DOM Helpers

```javascript
// Set the inner HTML content of an element reference
function setHtml(el, html) { el.innerHTML = html; }

// Set the inner HTML content of an element by its ID
function setHtmlById(id, html) { document.getElementById(id).innerHTML = html; }
```

Note: The comment in the source states "All dynamic content uses esc() for HTML escaping. This dashboard is served on a Tailscale-only network with no external user input."

### 7.2 HTML Escaping

```javascript
function esc(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
```

Standard DOM-based HTML entity escaping. Creates a temporary `<div>`, sets `textContent`, reads back the escaped content. This ensures characters like `<`, `>`, `&`, and `"` are properly escaped.

### 7.3 Formatting Functions

#### `fmtDurationMs(ms)`

Formats milliseconds into human-readable duration:

```javascript
function fmtDurationMs(ms) {
  if (!ms || ms <= 0) return null;       // Returns null (not string)
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;      // "42s"
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ${secs % 60}s`;  // "5m 23s"
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ${mins % 60}m`;        // "2h 15m"
}
```

#### `fmtTokenCount(n)`

Formats token counts with K/M suffixes:

```javascript
function fmtTokenCount(n) {
  if (!n) return '0';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';  // "3.2M"
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';          // "45.7K"
  return n.toLocaleString();                                      // "123"
}
```

#### `fmtDate(ts)`

Formats ISO timestamp to "Mon DD" format:

```javascript
function fmtDate(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    // Example: "Jan 15"
  } catch(e) { return ts.slice(0,10); }
}
```

#### `fmtDateTime(ts)`

Formats ISO timestamp to "Mon DD, HH:MM" format:

```javascript
function fmtDateTime(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    return d.toLocaleString('en-US', {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'
    });
    // Example: "Jan 15, 2:30 PM"
  } catch(e) { return ts; }
}
```

#### `fmtTime(ts)`

Formats ISO timestamp to "HH:MM:SS" format:

```javascript
function fmtTime(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
    // Example: "02:30:45 PM"
  } catch(e) { return ts; }
}
```

#### `shortenPath(p)`

Truncates file paths longer than 4 segments:

```javascript
function shortenPath(p) {
  const parts = p.split('/');
  if (parts.length <= 4) return p;
  return '.../' + parts.slice(-3).join('/');
  // "/home/pi/python/claude_analysis/app.py" -> ".../python/claude_analysis/app.py"
}
```

#### `calcDuration(start, end)`

Calculates wall-clock duration between two ISO timestamps:

```javascript
function calcDuration(start, end) {
  try {
    const ms = new Date(end) - new Date(start);
    if (ms < 0) return null;
    const mins = Math.floor(ms / 60000);
    if (mins < 1) return '<1 min';
    if (mins < 60) return `${mins} min`;        // "42 min"
    const hrs = Math.floor(mins / 60);
    const rem = mins % 60;
    return `${hrs}h ${rem}m`;                    // "2h 15m"
  } catch(e) { return null; }
}
```

---

## 8. JavaScript: Initialization

The entire application bootstraps from a single `DOMContentLoaded` handler:

```javascript
document.addEventListener('DOMContentLoaded', () => {
  const d = DASHBOARD_DATA;

  // 1. Show rebuild banner if background build is running
  if (d.rebuild_in_progress) {
    document.getElementById('rebuildBanner').style.display = 'flex';
  }

  // 2. Handle empty/building state
  if (!d.overview && (!d.sessions || !d.sessions.length)) {
    // Show placeholder card spanning full grid (grid-column:1/-1)
    // with "Building Cache" / "Parsing session files..."
    // EARLY RETURN - no further rendering
    return;
  }

  // 3. Set header meta text
  const ov = d.overview || {};
  const sessCount = ov.total_sessions || (d.sessions ? d.sessions.length : 0);
  const projCount = ov.project_count || 0;
  const genAt = ov.generated_at
    ? new Date(ov.generated_at).toLocaleString() : 'N/A';
  document.getElementById('headerMeta').textContent =
    `Generated ${genAt} | ${sessCount} sessions | ${projCount} projects`;

  // 4. Wire tab click listeners
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t =>
        t.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p =>
        p.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById(tab.dataset.tab).classList.add('active');
    });
  });

  // 5. Render initial content
  renderOverview();
  setupExplorer();
});
```

**Startup behavior**:
- If `rebuild_in_progress` is true, the blue banner with spinning indicator is shown.
- If there is no overview and no sessions (cold start), a "Building Cache" placeholder card spans the full grid width (`grid-column:1/-1`) and the function returns early. User should refresh after a few seconds.
- Otherwise, the header text is populated, tabs are wired, and `renderOverview()` + `setupExplorer()` are called.

---

## 9. JavaScript: Overview Tab

### `renderOverview()`

This is the main function for the Overview tab. It:

1. Reads `DASHBOARD_DATA.overview`
2. Computes token breakdowns (active vs cached)
3. Renders 6 summary cards
4. Initializes 7 window-level chart instance variables (all set to `null`)
5. Calls all 7 chart rendering functions with initial data

```javascript
function renderOverview() {
  const ov = DASHBOARD_DATA.overview;
  if (!ov) return;

  // Token calculations
  const activeTokens = (ov.total_input_tokens || 0)
                     + (ov.total_output_tokens || 0);
  const cachedTokens = (ov.total_cache_creation_tokens || 0)
                     + (ov.total_cache_read_tokens || 0);
  const totalAllTokens = activeTokens + cachedTokens;
  const dateRange = (ov.date_range_start && ov.date_range_end)
    ? `${fmtDate(ov.date_range_start)} - ${fmtDate(ov.date_range_end)}`
    : 'N/A';

  // Render 6 summary cards
  // Card 1: Sessions (value: total_sessions, sub: dateRange)
  // Card 2: Total Active Time (value: fmtDurationMs(total_active_ms))
  // Card 3: Total Actions (value: total_actions, sub: direct + subagent)
  // Card 4: Total Tokens (value: fmtTokenCount(totalAllTokens))
  // Card 5: Estimated Cost (value: ~$total_cost)
  // Card 6: Subagents Spawned (value: subagent_count)
  setHtmlById('summaryCards', `...`);

  // Initialize chart instance holders on window
  window._toolPieInst = null;
  window._projectBarInst = null;
  window._timelineInst = null;
  window._fileTypeInst = null;
  window._costByProjectInst = null;
  window._actionsTimelineInst = null;
  window._activeTimeInst = null;

  // Render all 7 charts with default data
  renderToolPie(ov.tool_distribution || {});
  renderProjectBar(ov.projects_chart || {});
  renderTimeline(ov.weekly_timeline || {});          // Default: weekly
  renderFileTypes(ov.file_types_chart || {});
  renderCostByProject(ov.cost_by_project || {});
  renderActionsTimeline(ov.actions_weekly || {});     // Default: weekly
  renderActiveTime(ov.active_time_weekly || {});      // Default: weekly
}
```

The 7 chart instance variables stored on `window`:

| Variable | Canvas ID | Chart Type | Default Data Source |
|----------|----------|------------|------------|
| `_toolPieInst` | `toolPieChart` | doughnut | `tool_distribution` |
| `_projectBarInst` | `projectBarChart` | bar (horizontal) | `projects_chart` |
| `_timelineInst` | `timelineChart` | line | `weekly_timeline` |
| `_fileTypeInst` | `fileTypeChart` | bar (vertical) | `file_types_chart` |
| `_costByProjectInst` | `costByProjectChart` | bar (horizontal) | `cost_by_project` |
| `_actionsTimelineInst` | `actionsTimelineChart` | line (3 datasets) | `actions_weekly` |
| `_activeTimeInst` | `activeTimeChart` | line | `active_time_weekly` |

---

## 10. JavaScript: Chart Rendering Functions

Each chart function follows the same pattern:
1. Convert data object to sorted entries array
2. Destroy existing chart instance if present (`window._*Inst.destroy()`)
3. Return early if no entries
4. Create new `Chart` instance and store on `window._*Inst`

### 10.1 `renderToolPie(data)`

**Chart type**: Doughnut
**Canvas**: `#toolPieChart`
**Data shape input**: `{ "Read": 150, "Write": 42, ... }`

```javascript
function renderToolPie(data) {
  const entries = Object.entries(data).sort((a,b) => b[1]-a[1]);
  if (window._toolPieInst) window._toolPieInst.destroy();
  if (!entries.length) return;
  window._toolPieInst = new Chart(
    document.getElementById('toolPieChart'), {
    type: 'doughnut',
    data: {
      labels: entries.map(e => e[0]),
      datasets: [{
        data: entries.map(e => e[1]),
        backgroundColor: entries.map(e => getToolColor(e[0])),
        borderWidth: 0
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: {
          position: 'right',
          labels: { color: '#8b8fa3', font: { size: 11 } }
        }
      }
    }
  });
}
```

Key config: legend on right side, no border between segments.

### 10.2 `renderProjectBar(data)`

**Chart type**: Bar (horizontal)
**Canvas**: `#projectBarChart`
**Data shape input**: `{ "claude_analysis": 500, "admin_panel": 200, ... }`

```javascript
function renderProjectBar(data) {
  const entries = Object.entries(data)
    .sort((a,b) => b[1]-a[1]).slice(0, 10);
  // ... destroy existing, guard empty
  window._projectBarInst = new Chart(..., {
    type: 'bar',
    data: {
      labels: entries.map(e => e[0]),
      datasets: [{
        data: entries.map(e => e[1]),
        backgroundColor: '#6c8cff',    // accent color
        borderRadius: 4
      }]
    },
    options: {
      responsive: true,
      indexAxis: 'y',                   // horizontal bars
      plugins: { legend: { display: false } },
      scales: {
        x: {
          ticks: { color: '#8b8fa3' },
          grid: { color: '#2e3347' }
        },
        y: {
          ticks: { color: '#e1e4ed', font: { size: 11 } },
          grid: { display: false }
        }
      }
    }
  });
}
```

Key config: top 10 only, horizontal (`indexAxis: 'y'`), no legend, no y-grid.

### 10.3 `renderTimeline(data)`

**Chart type**: Line (with fill)
**Canvas**: `#timelineChart`
**Data shape input**: `{ "2026-02-03": 5, "2026-02-10": 8, ... }`

```javascript
function renderTimeline(data) {
  const entries = Object.entries(data)
    .sort((a,b) => a[0].localeCompare(b[0]));
  // ... destroy existing, guard empty
  window._timelineInst = new Chart(..., {
    type: 'line',
    data: {
      labels: entries.map(e => fmtDate(e[0])),
      datasets: [{
        data: entries.map(e => e[1]),
        borderColor: '#6c8cff',
        backgroundColor: 'rgba(108,140,255,0.1)',
        fill: true,
        tension: 0.3,
        pointRadius: 3
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          ticks: { color: '#8b8fa3', maxRotation: 45, font: { size: 10 } },
          grid: { color: '#2e3347' }
        },
        y: {
          ticks: { color: '#8b8fa3' },
          grid: { color: '#2e3347' },
          beginAtZero: true
        }
      }
    }
  });
}
```

Key config: sorted chronologically, area fill, smooth curve (tension 0.3), y starts at 0.

### 10.4 `renderFileTypes(data)`

**Chart type**: Bar (vertical)
**Canvas**: `#fileTypeChart`
**Data shape input**: `{ ".py": 200, ".html": 50, ".md": 30, ... }`

```javascript
// Top 12, vertical bars, color: #a78bfa (accent2)
// Scales: x grid hidden, y beginAtZero
```

Key config: top 12 only, vertical bars (default axis), no x-grid, purple color.

### 10.5 `renderCostByProject(data)`

**Chart type**: Bar (horizontal)
**Canvas**: `#costByProjectChart`
**Data shape input**: `{ "claude_analysis": 12.50, "admin_panel": 3.20, ... }`

```javascript
// Top 10, horizontal, color: #4ade80 (green)
// Special tooltip: '$' + ctx.parsed.x.toFixed(2)
// Special x-axis ticks: '$' + v.toFixed(0)
```

Key config: top 10, horizontal, green, dollar-formatted axis ticks and tooltips.

### 10.6 `renderActionsTimeline(data)`

**Chart type**: Line (3 datasets, no fill)
**Canvas**: `#actionsTimelineChart`
**Data shape input**: `{ "2026-02-03": { "total": 100, "direct": 80, "subagent": 20 }, ... }`

```javascript
datasets: [
  {
    label: 'Total',
    data: entries.map(e => e[1].total),
    borderColor: '#6c8cff',                    // accent
    backgroundColor: 'rgba(108,140,255,0.1)',
    fill: false,
    tension: 0.3,
    pointRadius: 3,
    borderWidth: 2.5                           // thicker primary
  },
  {
    label: 'Direct',
    data: entries.map(e => e[1].direct),
    borderColor: '#a78bfa',                    // accent2
    backgroundColor: 'rgba(167,139,250,0.1)',
    fill: false,
    tension: 0.3,
    pointRadius: 2,
    borderWidth: 1.5                           // thinner secondary
  },
  {
    label: 'Subagent',
    data: entries.map(e => e[1].subagent),
    borderColor: '#f59e0b',                    // amber
    backgroundColor: 'rgba(245,158,11,0.1)',
    fill: false,
    tension: 0.3,
    pointRadius: 2,
    borderWidth: 1.5
  }
]
```

Legend config:
```javascript
legend: {
  position: 'top',
  labels: {
    color: '#8b8fa3',
    font: { size: 11 },
    usePointStyle: true,
    pointStyle: 'line'       // line segments in legend
  }
}
```

Key config: 3 overlaid line series, legend at top with line-style point indicators, primary line (Total) is thicker (2.5px) with larger points (3px), secondary lines are thinner (1.5px) with smaller points (2px).

### 10.7 `renderActiveTime(data)`

**Chart type**: Line (with fill)
**Canvas**: `#activeTimeChart`
**Data shape input**: `{ "2026-02-03": 3600000, ... }` (values in milliseconds)

The function converts milliseconds to hours by dividing by 3,600,000.

```javascript
const hours = entries.map(e => e[1] / 3600000);  // ms -> hours
// borderColor: '#34d399' (emerald -- NOT the CSS var --green #4ade80)
// backgroundColor: 'rgba(52,211,153,0.1)'
// Tooltip: ctx.parsed.y.toFixed(1) + ' hours'
// Y-axis ticks: v.toFixed(0) + 'h'
```

Key config: uses `#34d399` (emerald) not the CSS variable `--green` (#4ade80), ms-to-hours conversion, "Xh" axis ticks, "X.X hours" tooltips.

---

## 11. JavaScript: Timeline and Range Switching

### 11.1 `switchTimeline(granularity)`

Controls the 3 "Trends Over Time" charts. Called by onclick handlers on timeline pills.

**Parameter**: `'daily'` | `'weekly'` | `'monthly'`

```javascript
function switchTimeline(granularity) {
  const ov = DASHBOARD_DATA.overview;
  if (!ov) return;

  // Map granularity to overview data keys
  const sessMap = {
    daily: ov.daily_timeline,
    weekly: ov.weekly_timeline,
    monthly: ov.monthly_timeline
  };
  const actMap = {
    daily: ov.actions_daily,
    weekly: ov.actions_weekly,
    monthly: ov.actions_monthly
  };
  const timeMap = {
    daily: ov.active_time_daily,
    weekly: ov.active_time_weekly,
    monthly: ov.active_time_monthly
  };

  // Re-render all 3 trend charts with new granularity
  renderTimeline(sessMap[granularity] || {});
  renderActionsTimeline(actMap[granularity] || {});
  renderActiveTime(timeMap[granularity] || {});

  // Update pill active states via data-g attribute
  document.querySelectorAll('#timelinePills .cat-pill').forEach(p => {
    p.classList.toggle('active', p.dataset.g === granularity);
  });
}
```

### 11.2 `switchAllRanges(range)`

Controls the 4 "Activity by Time Range" charts. Called by onclick handlers on range pills.

**Parameter**: `'all'` | `'1d'` | `'7d'` | `'30d'`

```javascript
function switchAllRanges(range) {
  const ov = DASHBOARD_DATA.overview;
  if (!ov) return;

  // Build suffix: 'all' -> '', '1d' -> '_1d', '7d' -> '_7d', '30d' -> '_30d'
  const suffix = range === 'all' ? '' : '_' + range;

  // Dynamic key lookup on overview object
  renderToolPie(ov['tool_distribution' + suffix] || {});
  renderProjectBar(ov['projects_chart' + suffix] || {});
  renderFileTypes(ov['file_types_chart' + suffix] || {});
  renderCostByProject(ov['cost_by_project' + suffix] || {});

  // Update pill active states via data-r attribute
  document.querySelectorAll('#rangeChartPills .cat-pill').forEach(p => {
    p.classList.toggle('active', p.dataset.r === range);
  });
}
```

The dynamic key pattern means the overview object must contain these keys:
- `tool_distribution` (all), `tool_distribution_1d`, `tool_distribution_7d`, `tool_distribution_30d`
- `projects_chart` (all), `projects_chart_1d`, `projects_chart_7d`, `projects_chart_30d`
- `file_types_chart` (all), `file_types_chart_1d`, `file_types_chart_7d`, `file_types_chart_30d`
- `cost_by_project` (all), `cost_by_project_1d`, `cost_by_project_7d`, `cost_by_project_30d`

---

## 12. JavaScript: Task Explorer Tab

### 12.1 `setupExplorer()`

Called once during initialization. Sets up the project/session dropdowns and their event handlers.

```javascript
function setupExplorer() {
  const projSelect = document.getElementById('projectFilter');
  const sessSelect = document.getElementById('sessionSelect');
  const sessions = DASHBOARD_DATA.sessions || [];

  // Build project list:
  // prefer overview.projects_list, fall back to deriving from sessions
  const projects =
    (DASHBOARD_DATA.overview && DASHBOARD_DATA.overview.projects_list)
    || [...new Set(sessions.map(s => s.project))].sort();

  // Populate project dropdown with DOM methods
  projects.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p; opt.textContent = p;
    projSelect.appendChild(opt);
  });

  // Inner function: populate session dropdown based on project filter
  function populateSessions(project) {
    sessSelect.textContent = '';  // Clear all options
    const defaultOpt = document.createElement('option');
    defaultOpt.value = '';
    defaultOpt.textContent = 'Select a session...';
    sessSelect.appendChild(defaultOpt);

    let filtered = sessions;
    if (project) filtered = filtered.filter(s => s.project === project);

    filtered.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s.session_id;
      const date = s.start_time ? fmtDate(s.start_time) : '?';
      const preview = s.prompt_preview || s.slug
                      || s.session_id.slice(0, 8);
      opt.textContent =
        `[${date}] ${preview} (${s.total_actions} actions)`;
      sessSelect.appendChild(opt);
    });
  }

  populateSessions('');  // Initial: all projects

  // Project change -> repopulate sessions, hide detail
  projSelect.addEventListener('change', () => {
    populateSessions(projSelect.value);
    hideSessionDetail();
  });

  // Session change -> async fetch detail from API
  sessSelect.addEventListener('change', async () => {
    const sid = sessSelect.value;
    if (!sid) { hideSessionDetail(); return; }

    // Show loading state
    document.getElementById('explorerEmpty').style.display = 'none';
    document.getElementById('sessionDetail').style.display = 'none';
    document.getElementById('sessionLoading').style.display = 'block';

    try {
      const resp = await fetch(`${rootPath}/api/session/${sid}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const session = await resp.json();
      document.getElementById('sessionLoading').style.display = 'none';
      showSessionDetail(session);
    } catch (err) {
      document.getElementById('sessionLoading').style.display = 'none';
      // Show error using safe DOM methods (createElement + textContent)
      const el = document.getElementById('explorerEmpty');
      el.style.display = 'block';
      el.textContent = '';
      const h3 = document.createElement('h3');
      h3.textContent = 'Failed to load session';
      const p = document.createElement('p');
      p.textContent = err.message;
      el.appendChild(h3);
      el.appendChild(p);
    }
  });
}
```

### 12.2 `hideSessionDetail()`

Resets the explorer to its default empty state:

```javascript
function hideSessionDetail() {
  document.getElementById('sessionDetail').style.display = 'none';
  document.getElementById('sessionLoading').style.display = 'none';
  const el = document.getElementById('explorerEmpty');
  el.style.display = 'block';
  el.textContent = '';
  const h3 = document.createElement('h3');
  h3.textContent = 'Select a session to explore';
  const p = document.createElement('p');
  p.textContent = 'Choose a project and session from the dropdowns above.';
  el.appendChild(h3);
  el.appendChild(p);
  currentSession = null;
}
```

### 12.3 `showSessionDetail(s)`

The largest function in the dashboard (~200 lines). Renders the full session detail view when a session is fetched from the API.

**Parameter**: Full session detail object (see Section 14.3)

**Rendering steps in order**:

#### Step 1: Title

```javascript
currentSession = s;
document.getElementById('explorerEmpty').style.display = 'none';
document.getElementById('sessionDetail').style.display = 'block';
const title = s.slug || s.session_id.slice(0, 12);
document.getElementById('sessionTitle').textContent = title;
```

#### Step 2: Prompt

```javascript
document.getElementById('promptText').textContent =
  s.first_prompt || '(no prompt captured)';
```

#### Step 3: Conversation Flow

Only shown if there are more than 1 user turns. Uses a native `<details>` element for collapsible display.

```javascript
const turns = s.user_turns || [];
if (turns.length > 1) {
  // Summary text: "Conversation Flow (N turns[, M interrupted])"
  // Each turn: <li class="turn-item [interrupt]">
  //   <span class="turn-number">#N</span>
  //   [<span class="turn-time">HH:MM:SS</span>]
  //   escaped turn text
  flowDiv.style.display = 'block';
} else {
  flowDiv.style.display = 'none';
}
```

Interrupted turns get the `.interrupt` class (orange left border, italic, dimmed background).

#### Step 4: Meta Row

Builds a series of `<span>` elements containing session metadata badges:

| Always shown | Conditionally shown |
|-------------|-------------------|
| Project | Model (if `s.model` present) |
| Date | Active time (if calculable, with wall clock in parentheses) |
| Turns (with tooltip) | Wall clock duration (if no active time but start+end exist) |
| Actions badge | Token breakdown (if `s.tokens` present, includes cache hit %) |
| | Cost estimate badge (if present, green tinted background `#1a3d2e`) |
| | Subagent count badge (if subagents exist, accent2 background) |
| | Thinking level badge (if present, purple tinted background `#2e1a3d`) |
| | Permission mode badge (if present, surface2 background) |
| | Error count badge (if > 0, red tinted background `#3d1a1a`) |
| | Interrupt count badge (if > 0, `.badge-orange`) |

The token display includes cache hit percentage calculation:
```javascript
const cachePct = inp > 0
  ? Math.round(cacheRead / (inp + cacheRead) * 100) : 0;
```

#### Step 5: Tool Donut Chart (Combined)

Merges parent session tool counts with all subagent tool counts into one combined object, then renders a doughnut chart:

```javascript
const combinedToolCounts = { ...s.tool_counts };
subagents.forEach(sa => {
  Object.entries(sa.tool_counts).forEach(([t, c]) => {
    combinedToolCounts[t] = (combinedToolCounts[t] || 0) + c;
  });
});
const tc = Object.entries(combinedToolCounts).sort((a,b) => b[1]-a[1]);
sessionToolChart = new Chart(...);  // doughnut, same config as overview tool pie
```

#### Step 6: File Operations Table

Groups files by extension, sorts extensions by file count (descending), sorts files within each extension by total operation count (descending). Shows top 30 files.

Table columns: **File** (mono, `shortenPath()`, full path in `title` tooltip) | **Read** | **Write** | **Edit**

If more than 30 files exist, appends: "...and N more files".
If no files touched, shows: "No file operations".

#### Step 7: Bash Category Chart and Commands Table

If `s.bash_commands` has entries:
1. Renders a doughnut chart of `s.bash_category_summary` using `BASH_CAT_COLORS`, with `BASH_CAT_DESCRIPTIONS` shown in tooltip `afterLabel` callback
2. If more than 1 category exists, renders clickable category pills with `filterBashCat()` onclick
3. Renders a commands table (top 25) with columns: **Command** (mono) | **Category** | **Count**
4. Each `<tr>` has `data-cat` attribute for category filtering
5. If more than 25 commands, appends overflow row

If no bash commands: hides chart box, shows "No bash commands".

#### Step 8: Subagent Cards

Each subagent renders as a collapsible card inside a `.table-box` wrapper:

Structure per subagent card:
- Header (clickable, calls `toggleSubagent(idx)`):
  - Agent type badge (if not generic "agent")
  - Agent label (task_description, or type, or "Agent {id}")
  - Meta text: "N actions | active time"
  - Right-pointing triangle arrow (Unicode `&#9654;`)
- Body (hidden by default, `.subagent-body`):
  - Task prompt in `.subagent-desc` (if `sa.description` present)
  - Tool summary text: "Read: 5, Write: 3, ..."
  - Tool calls table (max 30 rows): **#** (seq) | **Tool** (badge) | **Detail** (mono, truncated 120 chars)

#### Step 9: Trigger Action Log

```javascript
renderActionLog(s);
```

This populates the Action Log tab so the user can switch to it.

### 12.4 `toggleSubagent(idx)`

Toggles the visibility of a subagent's body and rotates the arrow:

```javascript
function toggleSubagent(idx) {
  document.getElementById('saBody' + idx).classList.toggle('open');
  document.getElementById('saArrow' + idx).classList.toggle('open');
}
```

### 12.5 `filterBashCat(cat)`

Filters bash command table rows by category:

```javascript
function filterBashCat(cat) {
  // Update pill active state
  document.querySelectorAll('#bashCatPills .cat-pill').forEach(p => {
    p.classList.toggle('active', p.dataset.cat === cat);
  });
  // Show/hide table rows based on data-cat attribute
  document.querySelectorAll('#bashTableBody tr').forEach(row => {
    if (cat === 'all') {
      row.style.display = '';
    } else {
      row.style.display = (row.dataset.cat === cat) ? '' : 'none';
    }
  });
}
```

---

## 13. JavaScript: Action Log Tab

### 13.1 `renderActionLog(s)`

Called from `showSessionDetail()`. Merges parent and subagent tool calls into a single chronological timeline.

```javascript
function renderActionLog(s) {
  document.getElementById('logNoSession').style.display = 'none';
  document.getElementById('logActive').style.display = 'block';

  // Merge all tool calls (parent + subagents)
  const allCalls = [...(s.tool_calls || [])];
  (s.subagents || []).forEach(sa => {
    (sa.tool_calls || []).forEach(tc => {
      allCalls.push({
        ...tc,
        is_subagent: true,
        agent_id: sa.agent_id
      });
    });
  });

  // Sort by time (string comparison of ISO timestamps)
  allCalls.sort((a, b) => {
    if (a.time && b.time) return a.time.localeCompare(b.time);
    return 0;
  });

  // Assign sequential numbers for display
  allCalls.forEach((c, i) => c._seq = i + 1);

  // Build filter checkboxes (one per unique tool type)
  const toolTypes = [...new Set(allCalls.map(c => c.tool))].sort();
  logToolFilters = new Set(toolTypes);  // All enabled by default

  // Populate filter bar using DOM methods (createElement)
  const filterDiv = document.getElementById('toolFilters');
  filterDiv.textContent = '';
  // Add "Filter:" label (bold, 12px, text-dim)
  // Add one checkbox per tool type, all checked
  // Each checkbox change -> add/remove from logToolFilters
  //                      -> reset logPage = 1
  //                      -> re-render via renderLogPage(allCalls)

  logPage = 1;
  renderLogPage(allCalls);
}
```

### 13.2 `renderLogPage(allCalls)`

Renders a single page of the action log table with pagination.

```javascript
function renderLogPage(allCalls) {
  // Filter by active tool types
  const filtered = allCalls.filter(c => logToolFilters.has(c.tool));
  const totalPages = Math.max(1,
    Math.ceil(filtered.length / LOG_PAGE_SIZE));
  if (logPage > totalPages) logPage = totalPages;

  // Slice current page (50 items)
  const start = (logPage - 1) * LOG_PAGE_SIZE;
  const page = filtered.slice(start, start + LOG_PAGE_SIZE);

  // Render rows using createElement + setHtml per row
  const tbody = document.getElementById('logTableBody');
  tbody.textContent = '';
  page.forEach(c => {
    const tr = document.createElement('tr');
    // Columns: _seq | fmtTime | tool badge | detail (150 chars) | source
    tbody.appendChild(tr);
  });

  // Render pagination: [Prev] Page X of Y (N actions) [Next]
  // Store allCalls on window for pagination navigation
  window._logAllCalls = allCalls;
}
```

Table columns:

| Column | Content | Style |
|--------|---------|-------|
| # | Sequential number (`_seq`) | Default |
| Time | `fmtTime(c.time)` | `td.mono` |
| Tool | Tool badge with colored chip | `.tool-badge` classes |
| Detail | `c.detail` truncated to 150 chars, full in `title` attribute | `td.mono`, max-width 500px, ellipsis overflow |
| Source | "main" (text-dim) or "agent-{id}" (accent2 purple) | Inline styled spans |

### 13.3 `logPageNav(delta)`

Simple page navigation:

```javascript
function logPageNav(delta) {
  logPage += delta;
  renderLogPage(window._logAllCalls);
}
```

---

## 14. Data Contracts

### 14.1 Overview Object (`DASHBOARD_DATA.overview`)

Injected at page load. All fields from `cache_db.get_overview_payload()`:

```javascript
{
  // Scalar aggregates
  generated_at: "2026-02-16T10:30:00",      // ISO timestamp
  total_sessions: 150,
  total_tools: 5000,                          // Direct tool calls only
  total_actions: 7000,                        // Direct + subagent
  total_cost: 45.67,                          // USD float
  total_input_tokens: 2000000,
  total_output_tokens: 500000,
  total_cache_read_tokens: 8000000,
  total_cache_creation_tokens: 1000000,
  total_active_ms: 86400000,                  // Milliseconds
  date_range_start: "2026-01-01T00:00:00",
  date_range_end: "2026-02-16T10:30:00",
  project_count: 8,
  subagent_count: 42,
  subagent_tools: 2000,

  // Chart data - "all" time range
  tool_distribution: { "Read": 1500, "Write": 300, ... },
  projects_chart: { "claude_analysis": 500, ... },
  file_types_chart: { ".py": 200, ".html": 50, ... },
  cost_by_project: { "claude_analysis": 12.50, ... },

  // Chart data - 1-day range
  tool_distribution_1d: { ... },
  projects_chart_1d: { ... },
  file_types_chart_1d: { ... },
  cost_by_project_1d: { ... },

  // Chart data - 7-day range
  tool_distribution_7d: { ... },
  projects_chart_7d: { ... },
  file_types_chart_7d: { ... },
  cost_by_project_7d: { ... },

  // Chart data - 30-day range
  tool_distribution_30d: { ... },
  projects_chart_30d: { ... },
  file_types_chart_30d: { ... },
  cost_by_project_30d: { ... },

  // Timeline data - session counts by date bucket
  daily_timeline: { "2026-02-15": 5, "2026-02-16": 3, ... },
  weekly_timeline: { "2026-02-10": 12, "2026-02-03": 8, ... },
  monthly_timeline: { "2026-02": 30, "2026-01": 45, ... },

  // Timeline data - actions breakdown by date bucket
  actions_daily: {
    "2026-02-15": { total: 100, direct: 80, subagent: 20 }, ...
  },
  actions_weekly: {
    "2026-02-10": { total: 500, direct: 400, subagent: 100 }, ...
  },
  actions_monthly: {
    "2026-02": { total: 2000, direct: 1500, subagent: 500 }, ...
  },

  // Timeline data - active time in milliseconds by date bucket
  active_time_daily: { "2026-02-15": 3600000, ... },
  active_time_weekly: { "2026-02-10": 18000000, ... },
  active_time_monthly: { "2026-02": 72000000, ... },

  // Project list for explorer dropdown
  projects_list: ["admin_panel", "claude_analysis", "fuel", ...]
}
```

### 14.2 Session Summaries (`DASHBOARD_DATA.sessions`)

Injected at page load. Array of lightweight objects from `cache_db.get_session_list()`:

```javascript
[
  {
    session_id: "abc123def456...",           // Full UUID-style ID
    project: "claude_analysis",
    slug: "add-cost-tracking",              // Human-readable label (nullable)
    prompt_preview: "Add cost tracking...", // First ~80 chars of prompt
    start_time: "2026-02-16T08:00:00",
    end_time: "2026-02-16T09:30:00",
    model: "claude-opus-4-6",
    total_tools: 50,                        // Direct tool calls
    total_actions: 65,                      // Direct + subagent
    turn_count: 3,
    subagent_count: 2,
    active_duration_ms: 1800000,
    total_active_duration_ms: 2400000,      // Including subagent active time
    cost_estimate: 1.23,
    permission_mode: "allowedTools",        // Or null
    interrupt_count: 0,
    thinking_level: "high",                 // Or null
    tool_errors: 0
  },
  // ... (sorted by start_time DESC)
]
```

### 14.3 Session Detail (Fetched via API)

Loaded lazily via `GET /api/session/{session_id}`. Full object from `single_pass_parser.parse_session_fast()`:

```javascript
{
  session_id: "abc123def456...",
  slug: "add-cost-tracking",
  project: "claude_analysis",
  first_prompt: "Please add cost tracking to the dashboard...",
  prompt_preview: "Please add cost tracking...",
  turn_count: 3,
  start_time: "2026-02-16T08:00:00",
  end_time: "2026-02-16T09:30:00",
  model: "claude-opus-4-6",
  total_tools: 50,

  // Tool usage counts (direct calls only)
  tool_counts: { "Read": 20, "Write": 5, "Edit": 10, "Bash": 15 },

  // File extension counts
  file_extensions: { ".py": 15, ".html": 5, ".md": 3 },

  // Per-file operation breakdown
  files_touched: {
    "/home/pi/python/claude_analysis/app.py": {
      "Read": 3, "Edit": 2
    },
    "/home/pi/python/claude_analysis/cache_db.py": {
      "Read": 2, "Write": 1
    },
    // ...
  },

  // Bash commands aggregated by command text
  bash_commands: [
    { command: "git status", category: "Version Control", count: 5 },
    { command: "python app.py", category: "Running Code", count: 2 },
    // ... sorted by count descending
  ],

  // Category totals for bash chart
  bash_category_summary: {
    "Version Control": 12,
    "Running Code": 5,
    "File Management": 3
  },

  // Chronological tool call log (direct calls)
  tool_calls: [
    {
      seq: 1,
      tool: "Read",
      detail: "/home/pi/.../app.py",
      time: "2026-02-16T08:01:00"
    },
    {
      seq: 2,
      tool: "Bash",
      detail: "git status",
      time: "2026-02-16T08:01:15"
    },
    // ...
  ],

  // User message turns in conversation
  user_turns: [
    {
      turn_number: 1,
      text: "Please add cost tracking...",
      timestamp: "2026-02-16T08:00:00",
      is_interrupt: false
    },
    {
      turn_number: 2,
      text: "Actually, also add token counts",
      timestamp: "2026-02-16T08:15:00",
      is_interrupt: true
    },
    // ...
  ],

  interrupt_count: 1,

  // Token usage breakdown
  tokens: {
    input: 50000,
    output: 15000,
    cache_creation: 10000,
    cache_read: 200000
  },

  active_duration_ms: 1800000,
  total_active_duration_ms: 2400000,  // Including subagent time
  permission_mode: "allowedTools",
  tool_errors: 0,
  tool_successes: 48,
  thinking_level: "high",
  models_used: ["claude-opus-4-6"],
  cost_estimate: 1.23,

  // Subagent data
  subagents: [
    {
      agent_id: "a1b2c3",
      subagent_type: "code-review",       // Or "agent" for generic
      task_description: "Review the changes",
      description: "Full task prompt text...",  // Truncated to 200 chars
      tool_count: 15,
      tool_counts: { "Read": 10, "Grep": 5 },
      tool_calls: [
        {
          seq: 1,
          tool: "Read",
          detail: "/path/to/file.py",
          time: "2026-02-16T08:20:00"
        },
        // ...
      ],
      active_duration_ms: 600000
    },
    // ...
  ]
}
```

---

## 15. Chart.js Configuration Patterns

### 15.1 Shared Theme Constants

All charts use these consistent values (repeated inline, not stored as variables):

| Property | Value | Used In |
|----------|-------|---------|
| Tick text color | `'#8b8fa3'` | All scale ticks |
| Grid line color | `'#2e3347'` | All grid lines |
| Y-axis label color (bar charts) | `'#e1e4ed'` | Project/cost/file type labels |
| Legend label color | `'#8b8fa3'` | All legends |
| Legend font size | `11` | All legends |
| X-axis font size | `10` (line) or `11` (bar) | Varies by chart type |
| Max X-axis rotation | `45` | Line charts only |
| Bar border radius | `4` | All bar charts |
| Line tension | `0.3` | All line charts |
| Primary point radius | `3` | Single-dataset lines |
| Secondary point radius | `2` | Multi-dataset secondary lines |
| Primary border width | `2.5` | Actions timeline "Total" |
| Secondary border width | `1.5` | Actions timeline "Direct"/"Subagent" |

### 15.2 Chart Type Summary

| Chart | Type | Axis | Legend | Fill | Color | Special |
|-------|------|------|--------|------|-------|---------|
| Tool Distribution | doughnut | N/A | right | N/A | Per-tool colors | borderWidth: 0 |
| Top Projects | bar | horizontal | hidden | N/A | `#6c8cff` | Top 10 |
| File Types | bar | vertical | hidden | N/A | `#a78bfa` | Top 12 |
| Cost by Project | bar | horizontal | hidden | N/A | `#4ade80` | Top 10, $ tooltip |
| Sessions Timeline | line | default | hidden | true | `#6c8cff` | Area fill |
| Actions Timeline | line | default | top | false | 3 colors | 3 datasets |
| Active Time | line | default | hidden | true | `#34d399` | ms->hours, "Xh" ticks |
| Session Tool Donut | doughnut | N/A | right | N/A | Per-tool colors | Combined counts |
| Bash Categories | doughnut | N/A | right | N/A | Per-category colors | afterLabel tooltip |

### 15.3 Destroy-Before-Create Pattern

Every chart rendering function checks for an existing instance and destroys it before creating a new one. This prevents Chart.js memory leaks and canvas conflicts:

```javascript
if (window._chartInst) window._chartInst.destroy();
if (!entries.length) return;  // Don't create empty chart
window._chartInst = new Chart(canvas, config);
```

### 15.4 Responsive Behavior

All charts set `responsive: true`. The `.chart-box canvas` element has `max-height: 300px` to prevent charts from growing too tall on wide screens.

At viewport widths below 900px, both `.detail-grid` and `.charts-grid` collapse from multi-column to single-column layout.

---

## 16. Complete Data Flow

### 16.1 Page Load

```
Browser requests GET /
  -> app.py reads dashboard_template.html from disk
  -> app.py queries SQLite for overview + session summaries
  -> app.py serializes to JSON, escapes "</" sequences
  -> app.py replaces "const DASHBOARD_DATA = {};" in template
  -> Browser receives ~149KB HTML (~33KB gzipped)
  -> Chart.js loads from CDN
  -> DOMContentLoaded fires
  -> Check rebuild_in_progress -> show banner if true
  -> Check for empty state -> show placeholder if no data, return early
  -> Set headerMeta text: "Generated {date} | {sessions} | {projects}"
  -> Wire tab click listeners (classList toggle on .tab + .tab-panel)
  -> renderOverview():
     -> Compute token breakdowns
     -> Render 6 summary cards
     -> Create 7 Chart.js instances on canvas elements
  -> setupExplorer():
     -> Populate project dropdown from overview.projects_list
     -> Populate session dropdown with all sessions
     -> Wire change event handlers
```

### 16.2 User Selects a Session

```
User picks session from #sessionSelect dropdown
  -> change event fires
  -> Show #sessionLoading spinner
  -> Hide #explorerEmpty and #sessionDetail
  -> fetch(`${rootPath}/api/session/${sid}`)
     -> app.py queries session_details table in SQLite
     -> Returns full session JSON (~5-50KB depending on session)
  -> On success:
     -> Hide spinner
     -> showSessionDetail(session):
        1. Set title (slug or truncated ID)
        2. Set prompt text
        3. Build conversation flow (if > 1 turn)
        4. Build meta row with conditional badges
        5. Merge parent + subagent tool counts
        6. Create session tool donut chart
        7. Render file operations table (grouped by ext, top 30)
        8. Create bash category donut + commands table
        9. Render subagent cards (collapsible)
       10. Call renderActionLog(session)
  -> On error:
     -> Hide spinner
     -> Show error message in #explorerEmpty
```

### 16.3 User Switches Time Range

```
User clicks "Week" pill in "Activity by Time Range" section
  -> onclick="switchAllRanges('7d')"
  -> Computes suffix '_7d'
  -> Destroys + recreates 4 charts with *_7d data from overview:
     tool_distribution_7d, projects_chart_7d,
     file_types_chart_7d, cost_by_project_7d
  -> Updates pill active states (toggle .active class via data-r attribute)
```

### 16.4 User Switches Timeline Granularity

```
User clicks "Monthly" pill in "Trends Over Time" section
  -> onclick="switchTimeline('monthly')"
  -> Looks up 3 data objects from overview:
     monthly_timeline, actions_monthly, active_time_monthly
  -> Destroys + recreates 3 charts with monthly data
  -> Updates pill active states (toggle .active class via data-g attribute)
```

### 16.5 Action Log Interaction

```
User unchecks "Read" in filter bar
  -> change event on checkbox
  -> logToolFilters.delete('Read')
  -> logPage = 1  (reset to first page)
  -> renderLogPage(allCalls)
     -> Filter allCalls by logToolFilters set
     -> Compute pagination
     -> Render current page of filtered results

User clicks "Next" page button
  -> logPageNav(1)
  -> logPage += 1
  -> renderLogPage(window._logAllCalls)
  -> Shows next 50 items from filtered set
```

### 16.6 Subagent Expand/Collapse

```
User clicks subagent header
  -> toggleSubagent(idx)
  -> #saBody{idx}.classList.toggle('open') -> display: none/block
  -> #saArrow{idx}.classList.toggle('open') -> rotate 0/90deg
```

### 16.7 Bash Category Filtering

```
User clicks category pill (e.g., "Version Control")
  -> filterBashCat('Version Control')
  -> Toggle .active class on all #bashCatPills pills
  -> Show/hide #bashTableBody rows based on data-cat attribute
  -> 'all' shows all rows, specific category hides non-matching
```

---

## Appendix A: Element ID Reference

Complete list of all elements accessed by JavaScript via `document.getElementById()`:

| ID | Element | Tab | Purpose |
|----|---------|-----|---------|
| `headerMeta` | div.meta | Header | "Generated ... \| N sessions \| N projects" |
| `rebuildBanner` | div.rebuild-banner | Overview | Cache building notification |
| `summaryCards` | div.cards | Overview | 6 metric cards container |
| `rangeChartPills` | div.category-pills | Overview | All/Day/Week/Month pills |
| `timelinePills` | div.category-pills | Overview | Daily/Weekly/Monthly pills |
| `toolPieChart` | canvas | Overview | Tool distribution doughnut |
| `projectBarChart` | canvas | Overview | Projects bar chart |
| `fileTypeChart` | canvas | Overview | File types bar chart |
| `costByProjectChart` | canvas | Overview | Cost bar chart |
| `timelineChart` | canvas | Overview | Sessions line chart |
| `actionsTimelineChart` | canvas | Overview | Actions line chart (3 datasets) |
| `activeTimeChart` | canvas | Overview | Active time line chart |
| `projectFilter` | select | Explorer | Project dropdown |
| `sessionSelect` | select | Explorer | Session dropdown |
| `sessionLoading` | div.loading-spinner | Explorer | Loading indicator |
| `sessionDetail` | div | Explorer | Session detail container |
| `sessionTitle` | h2 | Explorer | Session name |
| `promptText` | div.prompt-text | Explorer | First prompt display |
| `conversationFlow` | div.conversation-flow | Explorer | Turn-by-turn flow |
| `sessionMeta` | div.meta-row | Explorer | Metadata badges |
| `sessionToolChart` | canvas | Explorer | Session tool donut |
| `fileOpsTable` | div | Explorer | File operations table |
| `bashChartBox` | div.chart-box | Explorer | Bash chart container (hidden if empty) |
| `bashCatChart` | canvas | Explorer | Bash category donut |
| `bashTable` | div | Explorer | Bash commands table |
| `bashCatPills` | div.category-pills | Explorer | Bash category filter pills (dynamic) |
| `bashTableBody` | tbody | Explorer | Bash table body (for row filtering) |
| `subagentsSection` | div | Explorer | Subagent cards container |
| `explorerEmpty` | div.empty-state | Explorer | "Select a session" placeholder |
| `saBody{N}` | div.subagent-body | Explorer | Subagent N body (dynamic, 0-indexed) |
| `saArrow{N}` | span.arrow | Explorer | Subagent N expand arrow (dynamic, 0-indexed) |
| `logNoSession` | div.empty-state | Log | "No session selected" message |
| `logActive` | div | Log | Active log container |
| `toolFilters` | div.filter-bar | Log | Tool type checkboxes |
| `logTableBody` | tbody | Log | Action log table body |
| `logPagination` | div.pagination | Log | Page navigation controls |

---

## Appendix B: Window-Level Globals

Variables stored on `window` for cross-function access:

| Variable | Type | Purpose |
|----------|------|---------|
| `window._toolPieInst` | Chart \| null | Overview tool distribution chart |
| `window._projectBarInst` | Chart \| null | Overview projects bar chart |
| `window._timelineInst` | Chart \| null | Overview sessions timeline chart |
| `window._fileTypeInst` | Chart \| null | Overview file types chart |
| `window._costByProjectInst` | Chart \| null | Overview cost by project chart |
| `window._actionsTimelineInst` | Chart \| null | Overview actions timeline chart |
| `window._activeTimeInst` | Chart \| null | Overview active time chart |
| `window._logAllCalls` | Array | All merged tool calls for current session (pagination) |

---

## Appendix C: Function Index

All JavaScript functions in declaration order with source line numbers:

| Function | Line | Called By | Purpose |
|----------|------|-----------|---------|
| `getToolColor(name)` | 303 | Chart renderers | Lookup tool color, fallback gray |
| `getToolBadgeClass(name)` | 324-327 | `showSessionDetail`, `renderLogPage` | CSS class for tool badge |
| `setHtml(el, html)` | 332 | Multiple | Set element content |
| `setHtmlById(id, html)` | 333 | Multiple | Set element content by ID |
| `renderOverview()` | 372-407 | Init | Render overview cards + 7 charts |
| `renderToolPie(data)` | 409-421 | `renderOverview`, `switchAllRanges` | Doughnut chart of tools |
| `renderProjectBar(data)` | 423-435 | `renderOverview`, `switchAllRanges` | Horizontal bar of projects |
| `renderTimeline(data)` | 437-449 | `renderOverview`, `switchTimeline` | Sessions line chart |
| `renderFileTypes(data)` | 451-462 | `renderOverview`, `switchAllRanges` | Vertical bar of file types |
| `renderCostByProject(data)` | 465-484 | `renderOverview`, `switchAllRanges` | Horizontal bar of costs |
| `renderActionsTimeline(data)` | 486-509 | `renderOverview`, `switchTimeline` | 3-line actions chart |
| `renderActiveTime(data)` | 511-531 | `renderOverview`, `switchTimeline` | Active time line chart |
| `switchTimeline(granularity)` | 534-546 | onclick (timeline pills) | Switch daily/weekly/monthly trends |
| `switchAllRanges(range)` | 549-560 | onclick (range pills) | Switch all/1d/7d/30d range charts |
| `setupExplorer()` | 563-632 | Init | Wire project/session dropdowns |
| `hideSessionDetail()` | 634-647 | `setupExplorer` | Reset explorer to empty state |
| `showSessionDetail(s)` | 649-847 | `setupExplorer` (async) | Render full session detail |
| `toggleSubagent(idx)` | 849-854 | onclick (subagent headers) | Toggle subagent body visibility |
| `filterBashCat(cat)` | 856-867 | onclick (bash category pills) | Filter bash table rows |
| `renderActionLog(s)` | 870-912 | `showSessionDetail` | Merge + display action log |
| `renderLogPage(allCalls)` | 914-939 | `renderActionLog`, `logPageNav` | Render one page of log |
| `logPageNav(delta)` | 941-944 | onclick (pagination buttons) | Navigate log pages |
| `fmtDurationMs(ms)` | 947-955 | Multiple | Format ms to "Xh Ym" |
| `fmtTokenCount(n)` | 956-961 | `renderOverview`, `showSessionDetail` | Format tokens to "X.XK" |
| `esc(s)` | 962 | Multiple | HTML-escape a string |
| `fmtDate(ts)` | 963 | Chart renderers, `setupExplorer` | Format to "Mon DD" |
| `fmtDateTime(ts)` | 964 | `showSessionDetail` | Format to "Mon DD, HH:MM" |
| `fmtTime(ts)` | 965 | `showSessionDetail`, `renderLogPage` | Format to "HH:MM:SS" |
| `shortenPath(p)` | 966-970 | `showSessionDetail` | Truncate long file paths |
| `calcDuration(start, end)` | 971-982 | `showSessionDetail` | Wall-clock duration string |

---

## Appendix D: Recreation Notes

1. **Single file**: Everything goes in one HTML file. No external CSS or JS files.
2. **No template engine**: The HTML is a static file with one `const DASHBOARD_DATA = {};` placeholder. `app.py` does a string replacement -- not Jinja2.
3. **Chart.js version**: Must be 4.4.7 for API compatibility.
4. **Dark theme only**: No light mode toggle.
5. **Responsive**: Only one breakpoint at 900px (stacks 2-column grids to 1 column).
6. **No CDN fallback**: Chart.js is the only external dependency. If CDN is down, charts will not render.
7. **HTML escaping**: All dynamic content goes through `esc()`. The `setHtml()` / `setHtmlById()` functions are used for pre-escaped HTML strings.
8. **Session loading**: Session details are NOT in the initial payload. They are fetched lazily via `fetch()` when a user selects a session from the dropdown. This keeps the initial HTML payload small (~33KB gzipped).
9. **Root path detection**: The JavaScript extracts the base URL from the apple-touch-icon link tag, making the dashboard work behind any reverse proxy prefix.
