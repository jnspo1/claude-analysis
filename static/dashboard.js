// State
let currentSession = null;
let sessionToolChart = null;
let bashCatChart = null;
let logPage = 1;
const LOG_PAGE_SIZE = 50;
let logToolFilters = new Set();

// Chart colors
const TOOL_COLORS = {
  Read: '#60a5fa', Write: '#4ade80', Edit: '#fb923c', Bash: '#f472b6',
  Grep: '#a78bfa', Glob: '#22d3ee', Task: '#facc15', TaskCreate: '#facc15',
  TaskUpdate: '#fbbf24', TaskList: '#f59e0b', TaskGet: '#d97706', TaskOutput: '#b45309',
  WebSearch: '#2dd4bf', WebFetch: '#14b8a6', Skill: '#fde047',
  AskUserQuestion: '#c084fc', EnterPlanMode: '#7c3aed', ExitPlanMode: '#6d28d9',
  NotebookEdit: '#f0abfc', TaskStop: '#a3a3a3', TodoWrite: '#a3e635',
};
/** @param {string} name - Tool name. @returns {string} Hex color. */
function getToolColor(name) { return TOOL_COLORS[name] || '#8b8fa3'; }

// Bash category colors and descriptions
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
/** @param {string} name - Tool name. @returns {string} CSS class for badge. */
function getToolBadgeClass(name) {
  const known = ['Read','Write','Edit','Bash','Grep','Glob','Task','TaskCreate','TaskUpdate','TaskList','TaskGet','TaskOutput','WebSearch','WebFetch','Skill'];
  return known.includes(name) ? name : 'default';
}

// ---- Safe DOM helpers ----
// SECURITY NOTE: All dynamic content uses esc() for HTML escaping before
// being set via innerHTML. This dashboard renders trusted server-side data
// only (no user input) and is served on a Tailscale-only private network.
// The setHtml/setHtmlById helpers centralize innerHTML usage so it can be
// audited in one place. All string interpolation passes through esc() first.
function setHtml(el, html) { el.innerHTML = html; }
function setHtmlById(id, html) { document.getElementById(id).innerHTML = html; }

// ---- INIT ----
document.addEventListener('DOMContentLoaded', () => {
  const d = DASHBOARD_DATA;

  // Show rebuild banner if building
  if (d.rebuild_in_progress) {
    document.getElementById('rebuildBanner').classList.remove('hidden');
  }

  // Handle empty/building state
  if (!d.overview && (!d.sessions || !d.sessions.length)) {
    setHtmlById('summaryCards', '<div class="card" style="grid-column:1/-1;text-align:center;"><div class="label">Building Cache</div><div class="value" style="font-size:18px;">Parsing session files...</div><div class="sub">Refresh in a few seconds to see data.</div></div>');
    return;
  }

  // Header
  const ov = d.overview || {};
  const sessCount = ov.total_sessions || (d.sessions ? d.sessions.length : 0);
  const projCount = ov.project_count || 0;
  const genAt = ov.generated_at ? new Date(ov.generated_at).toLocaleString() : 'N/A';
  document.getElementById('headerMeta').textContent = `Generated ${genAt} | ${sessCount} sessions | ${projCount} projects`;

  // Tabs
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => { t.classList.remove('active'); t.setAttribute('aria-selected', 'false'); });
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      tab.setAttribute('aria-selected', 'true');
      document.getElementById(tab.dataset.tab).classList.add('active');
    });
  });

  renderOverview();
  setupExplorer();
});

// ---- OVERVIEW (reads pre-computed aggregates) ----
/** Render overview cards and all overview charts from pre-computed aggregates. */
function renderOverview() {
  const ov = DASHBOARD_DATA.overview;
  if (!ov) return;

  const activeTokens = (ov.total_input_tokens || 0) + (ov.total_output_tokens || 0);
  const cachedTokens = (ov.total_cache_creation_tokens || 0) + (ov.total_cache_read_tokens || 0);
  const totalAllTokens = activeTokens + cachedTokens;
  const dateRange = (ov.date_range_start && ov.date_range_end) ? `${fmtDate(ov.date_range_start)} - ${fmtDate(ov.date_range_end)}` : 'N/A';

  setHtmlById('summaryCards', `
    <div class="card"><div class="label">Sessions</div><div class="value">${ov.total_sessions}</div><div class="sub">${dateRange}</div></div>
    <div class="card"><div class="label">Total Active Time</div><div class="value">${fmtDurationMs(ov.total_active_ms) || 'N/A'}</div><div class="sub">Claude working time across all sessions</div></div>
    <div class="card"><div class="label">Total Actions</div><div class="value">${ov.total_actions.toLocaleString()}</div><div class="sub">${ov.total_tools.toLocaleString()} direct + ${(ov.subagent_tools || 0).toLocaleString()} from ${ov.subagent_count || 0} subagents</div></div>
    <div class="card"><div class="label">Total Tokens</div><div class="value">${fmtTokenCount(totalAllTokens)}</div><div class="sub">${fmtTokenCount(activeTokens)} active + ${fmtTokenCount(cachedTokens)} cached</div></div>
    <div class="card"><div class="label">Estimated Cost</div><div class="value">~$${(ov.total_cost || 0).toFixed(2)}</div><div class="sub">${ov.project_count} projects</div></div>
    <div class="card"><div class="label">Subagents Spawned</div><div class="value">${ov.subagent_count || 0}</div></div>
  `);

  // Chart instances for dynamic updates
  window._toolPieInst = null;
  window._projectBarInst = null;
  window._timelineInst = null;
  window._fileTypeInst = null;
  window._costByProjectInst = null;
  window._actionsTimelineInst = null;
  window._activeTimeInst = null;

  // Render initial charts
  renderToolPie(ov.tool_distribution || {});
  renderProjectBar(ov.projects_chart || {});
  renderTimeline(ov.weekly_timeline || {});
  renderFileTypes(ov.file_types_chart || {});
  renderCostByProject(ov.cost_by_project || {});
  renderActionsTimeline(ov.actions_weekly || {});
  renderActiveTime(ov.active_time_weekly || {});
}

/** @param {Object<string,number>} data - Tool name to count mapping. */
function renderToolPie(data) {
  const entries = Object.entries(data).sort((a,b) => b[1]-a[1]);
  if (window._toolPieInst) window._toolPieInst.destroy();
  if (!entries.length) return;
  window._toolPieInst = new Chart(document.getElementById('toolPieChart'), {
    type: 'doughnut',
    data: {
      labels: entries.map(e => e[0]),
      datasets: [{ data: entries.map(e => e[1]), backgroundColor: entries.map(e => getToolColor(e[0])), borderWidth: 0 }]
    },
    options: { responsive: true, plugins: { legend: { position: 'right', labels: { color: '#8b8fa3', font: { size: 11 } } } } }
  });
}

/** @param {Object<string,number>} data - Project name to action count. */
function renderProjectBar(data) {
  const entries = Object.entries(data).sort((a,b) => b[1]-a[1]).slice(0, 10);
  if (window._projectBarInst) window._projectBarInst.destroy();
  if (!entries.length) return;
  window._projectBarInst = new Chart(document.getElementById('projectBarChart'), {
    type: 'bar',
    data: {
      labels: entries.map(e => e[0]),
      datasets: [{ data: entries.map(e => e[1]), backgroundColor: '#6c8cff', borderRadius: 4 }]
    },
    options: { responsive: true, indexAxis: 'y', plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#8b8fa3' }, grid: { color: '#2e3347' } }, y: { ticks: { color: '#e1e4ed', font: { size: 11 } }, grid: { display: false } } } }
  });
}

/** @param {Object<string,number>} data - Date string to session count. */
function renderTimeline(data) {
  const entries = Object.entries(data).sort((a,b) => a[0].localeCompare(b[0]));
  if (window._timelineInst) window._timelineInst.destroy();
  if (!entries.length) return;
  window._timelineInst = new Chart(document.getElementById('timelineChart'), {
    type: 'line',
    data: {
      labels: entries.map(e => fmtDate(e[0])),
      datasets: [{ data: entries.map(e => e[1]), borderColor: '#6c8cff', backgroundColor: 'rgba(108,140,255,0.1)', fill: true, tension: 0.3, pointRadius: 3 }]
    },
    options: { responsive: true, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#8b8fa3', maxRotation: 45, font: { size: 10 } }, grid: { color: '#2e3347' } }, y: { ticks: { color: '#8b8fa3' }, grid: { color: '#2e3347' }, beginAtZero: true } } }
  });
}

/** @param {Object<string,number>} data - File extension to count. */
function renderFileTypes(data) {
  const entries = Object.entries(data).sort((a,b) => b[1]-a[1]).slice(0, 12);
  if (window._fileTypeInst) window._fileTypeInst.destroy();
  if (!entries.length) return;
  window._fileTypeInst = new Chart(document.getElementById('fileTypeChart'), {
    type: 'bar',
    data: {
      labels: entries.map(e => e[0]),
      datasets: [{ data: entries.map(e => e[1]), backgroundColor: '#a78bfa', borderRadius: 4 }]
    },
    options: { responsive: true, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#e1e4ed', font: { size: 11 } }, grid: { display: false } }, y: { ticks: { color: '#8b8fa3' }, grid: { color: '#2e3347' }, beginAtZero: true } } }
  });
}

/** @param {Object<string,number>} data - Project name to cost in USD. */
function renderCostByProject(data) {
  const entries = Object.entries(data).sort((a,b) => b[1]-a[1]).slice(0, 10);
  if (window._costByProjectInst) window._costByProjectInst.destroy();
  if (!entries.length) return;
  window._costByProjectInst = new Chart(document.getElementById('costByProjectChart'), {
    type: 'bar',
    data: {
      labels: entries.map(e => e[0]),
      datasets: [{ data: entries.map(e => e[1]), backgroundColor: '#4ade80', borderRadius: 4 }]
    },
    options: {
      responsive: true, indexAxis: 'y',
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => '$' + ctx.parsed.x.toFixed(2) } } },
      scales: {
        x: { ticks: { color: '#8b8fa3', callback: v => '$' + v.toFixed(0) }, grid: { color: '#2e3347' } },
        y: { ticks: { color: '#e1e4ed', font: { size: 11 } }, grid: { display: false } }
      }
    }
  });
}

/** @param {Object<string,{total:number,direct:number,subagent:number}>} data - Date to action breakdown. */
function renderActionsTimeline(data) {
  const entries = Object.entries(data).sort((a,b) => a[0].localeCompare(b[0]));
  if (window._actionsTimelineInst) window._actionsTimelineInst.destroy();
  if (!entries.length) return;
  window._actionsTimelineInst = new Chart(document.getElementById('actionsTimelineChart'), {
    type: 'line',
    data: {
      labels: entries.map(e => fmtDate(e[0])),
      datasets: [
        { label: 'Total', data: entries.map(e => e[1].total), borderColor: '#6c8cff', backgroundColor: 'rgba(108,140,255,0.1)', fill: false, tension: 0.3, pointRadius: 3, borderWidth: 2.5 },
        { label: 'Direct', data: entries.map(e => e[1].direct), borderColor: '#a78bfa', backgroundColor: 'rgba(167,139,250,0.1)', fill: false, tension: 0.3, pointRadius: 2, borderWidth: 1.5 },
        { label: 'Subagent', data: entries.map(e => e[1].subagent), borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.1)', fill: false, tension: 0.3, pointRadius: 2, borderWidth: 1.5 }
      ]
    },
    options: {
      responsive: true,
      plugins: { legend: { position: 'top', labels: { color: '#8b8fa3', font: { size: 11 }, usePointStyle: true, pointStyle: 'line' } } },
      scales: {
        x: { ticks: { color: '#8b8fa3', maxRotation: 45, font: { size: 10 } }, grid: { color: '#2e3347' } },
        y: { ticks: { color: '#8b8fa3' }, grid: { color: '#2e3347' }, beginAtZero: true }
      }
    }
  });
}

/** @param {Object<string,number>} data - Date to active milliseconds. */
function renderActiveTime(data) {
  const entries = Object.entries(data).sort((a,b) => a[0].localeCompare(b[0]));
  if (window._activeTimeInst) window._activeTimeInst.destroy();
  if (!entries.length) return;
  const hours = entries.map(e => e[1] / 3600000);
  window._activeTimeInst = new Chart(document.getElementById('activeTimeChart'), {
    type: 'line',
    data: {
      labels: entries.map(e => fmtDate(e[0])),
      datasets: [{ data: hours, borderColor: '#34d399', backgroundColor: 'rgba(52,211,153,0.1)', fill: true, tension: 0.3, pointRadius: 3 }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ctx.parsed.y.toFixed(1) + ' hours' } } },
      scales: {
        x: { ticks: { color: '#8b8fa3', maxRotation: 45, font: { size: 10 } }, grid: { color: '#2e3347' } },
        y: { ticks: { color: '#8b8fa3', callback: v => v.toFixed(0) + 'h' }, grid: { color: '#2e3347' }, beginAtZero: true }
      }
    }
  });
}

// ---- TIMELINE GRANULARITY PILLS ----
/** @param {'daily'|'weekly'|'monthly'} granularity - Timeline resolution. */
function switchTimeline(granularity) {
  const ov = DASHBOARD_DATA.overview;
  if (!ov) return;
  const sessMap = { daily: ov.daily_timeline, weekly: ov.weekly_timeline, monthly: ov.monthly_timeline };
  const actMap = { daily: ov.actions_daily, weekly: ov.actions_weekly, monthly: ov.actions_monthly };
  const timeMap = { daily: ov.active_time_daily, weekly: ov.active_time_weekly, monthly: ov.active_time_monthly };
  renderTimeline(sessMap[granularity] || {});
  renderActionsTimeline(actMap[granularity] || {});
  renderActiveTime(timeMap[granularity] || {});
  document.querySelectorAll('#timelinePills .cat-pill').forEach(p => {
    p.classList.toggle('active', p.dataset.g === granularity);
  });
}

// ---- TIME-RANGE FILTER PILLS (Tool Dist, Projects, File Types) ----
/** @param {'all'|'1d'|'7d'|'30d'} range - Time range filter. */
function switchAllRanges(range) {
  const ov = DASHBOARD_DATA.overview;
  if (!ov) return;
  const suffix = range === 'all' ? '' : '_' + range;
  renderToolPie(ov['tool_distribution' + suffix] || {});
  renderProjectBar(ov['projects_chart' + suffix] || {});
  renderFileTypes(ov['file_types_chart' + suffix] || {});
  renderCostByProject(ov['cost_by_project' + suffix] || {});
  document.querySelectorAll('#rangeChartPills .cat-pill').forEach(p => {
    p.classList.toggle('active', p.dataset.r === range);
  });
}

// ---- EXPLORER ----
function setupExplorer() {
  const projSelect = document.getElementById('projectFilter');
  const sessSelect = document.getElementById('sessionSelect');
  const sessions = DASHBOARD_DATA.sessions || [];

  // Projects from overview or derive from sessions
  const projects = (DASHBOARD_DATA.overview && DASHBOARD_DATA.overview.projects_list) || [...new Set(sessions.map(s => s.project))].sort();
  projects.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p; opt.textContent = p;
    projSelect.appendChild(opt);
  });

  function populateSessions(project) {
    sessSelect.textContent = '';
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
      const preview = s.prompt_preview || s.slug || s.session_id.slice(0, 8);
      opt.textContent = `[${date}] ${preview} (${s.total_actions} actions)`;
      sessSelect.appendChild(opt);
    });
  }

  populateSessions('');

  projSelect.addEventListener('change', () => {
    populateSessions(projSelect.value);
    hideSessionDetail();
  });

  // Async lazy-load session detail on selection
  sessSelect.addEventListener('change', async () => {
    const sid = sessSelect.value;
    if (!sid) { hideSessionDetail(); return; }

    // Show loading state
    document.getElementById('explorerEmpty').classList.add('hidden');
    document.getElementById('sessionDetail').classList.add('hidden');
    document.getElementById('sessionLoading').classList.remove('hidden');

    try {
      const resp = await fetch(`${rootPath}/api/session/${sid}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const session = await resp.json();
      document.getElementById('sessionLoading').classList.add('hidden');
      showSessionDetail(session);
    } catch (err) {
      document.getElementById('sessionLoading').classList.add('hidden');
      const el = document.getElementById('explorerEmpty');
      el.classList.remove('hidden');
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

/** Reset explorer to empty state. */
function hideSessionDetail() {
  document.getElementById('sessionDetail').classList.add('hidden');
  document.getElementById('sessionLoading').classList.add('hidden');
  const el = document.getElementById('explorerEmpty');
  el.classList.remove('hidden');
  el.textContent = '';
  const h3 = document.createElement('h3');
  h3.textContent = 'Select a session to explore';
  const p = document.createElement('p');
  p.textContent = 'Choose a project and session from the dropdowns above.';
  el.appendChild(h3);
  el.appendChild(p);
  currentSession = null;
}

/**
 * Build the session meta-row HTML (project, date, model, tokens, badges).
 * @param {Object} s - Session detail object.
 * @param {Array} subagents - Subagent data array.
 * @returns {string} HTML string for the meta row.
 */
function buildSessionMeta(s, subagents) {
  const totalActions = s.total_tools + subagents.reduce((a, b) => a + b.tool_count, 0);
  const wallClock = (s.start_time && s.end_time) ? calcDuration(s.start_time, s.end_time) : null;
  const activeTime = fmtDurationMs(s.total_active_duration_ms);
  let h = `<span><strong>Project:</strong> ${esc(s.project)}</span>`;
  h += `<span><strong>Date:</strong> ${s.start_time ? esc(fmtDateTime(s.start_time)) : 'N/A'}</span>`;
  if (s.model) h += `<span><strong>Model:</strong> ${esc(s.model)}</span>`;
  h += `<span title="Number of user messages sent in this conversation"><strong>Turns:</strong> ${esc(String(s.turn_count))}</span>`;
  if (activeTime) {
    h += `<span title="Active working time (wall clock: ${esc(wallClock || 'N/A')})"><strong>Active:</strong> ${esc(activeTime)}${wallClock ? ' <span style="color:var(--text-dim);font-size:11px;">(wall: ' + esc(wallClock) + ')</span>' : ''}</span>`;
  } else if (wallClock) {
    h += `<span><strong>Duration:</strong> ${esc(wallClock)}</span>`;
  }
  if (s.tokens) {
    const inp = s.tokens.input || 0, out = s.tokens.output || 0, cacheRead = s.tokens.cache_read || 0;
    const cachePct = inp > 0 ? Math.round(cacheRead / (inp + cacheRead) * 100) : 0;
    const tokenTip = cachePct > 0 ? `Cache hit: ${cachePct}%` : '';
    h += `<span title="${esc(tokenTip)}"><strong>Tokens:</strong> ${esc(fmtTokenCount(inp))} in / ${esc(fmtTokenCount(out))} out${cachePct > 0 ? ' (' + cachePct + '% cached)' : ''}</span>`;
  }
  if (s.cost_estimate) h += `<span class="badge" style="background:#1a3d2e;color:var(--green)">~$${esc(s.cost_estimate.toFixed(2))}</span>`;
  h += `<span class="badge">${esc(String(totalActions))} actions</span>`;
  if (subagents.length) h += `<span class="badge" style="background:var(--accent2)">${esc(String(subagents.length))} subagent${subagents.length>1?'s':''}</span>`;
  if (s.thinking_level) h += `<span class="badge" style="background:#2e1a3d;color:var(--accent2)">thinking: ${esc(s.thinking_level)}</span>`;
  if (s.permission_mode) h += `<span class="badge" style="background:var(--surface2);color:var(--text-dim)">${esc(s.permission_mode)}</span>`;
  if (s.tool_errors > 0) h += `<span class="badge" style="background:#3d1a1a;color:var(--red)">${esc(String(s.tool_errors))} error${s.tool_errors>1?'s':''}</span>`;
  if (s.interrupt_count > 0) h += `<span class="badge badge-orange">${esc(String(s.interrupt_count))} interrupt${s.interrupt_count>1?'s':''}</span>`;
  return h;
}

/**
 * Render the file operations table for a session.
 * @param {Object} s - Session detail object with files_touched.
 */
function renderFileOpsTable(s) {
  const fileEntries = Object.entries(s.files_touched || {});
  if (!fileEntries.length) {
    setHtmlById('fileOpsTable', '<p style="color:var(--text-dim);font-size:13px;">No file operations</p>');
    return;
  }
  const byExt = {};
  fileEntries.forEach(([path, ops]) => {
    const ext = path.split('.').pop() || '(none)';
    if (!byExt[ext]) byExt[ext] = [];
    byExt[ext].push({ path, ops });
  });
  let html = '<table><thead><tr><th>File</th><th>Read</th><th>Write</th><th>Edit</th></tr></thead><tbody>';
  const sorted = Object.entries(byExt).sort((a,b) => b[1].length - a[1].length);
  let shown = 0;
  for (const [, files] of sorted) {
    files.sort((a,b) => {
      const aTotal = Object.values(a.ops).reduce((sum,v)=>sum+v,0);
      const bTotal = Object.values(b.ops).reduce((sum,v)=>sum+v,0);
      return bTotal - aTotal;
    });
    for (const f of files) {
      if (shown >= 30) break;
      const short = shortenPath(f.path);
      html += `<tr><td class="mono" title="${esc(f.path)}">${esc(short)}</td>`;
      html += `<td>${f.ops.Read||''}</td><td>${f.ops.Write||''}</td><td>${f.ops.Edit||''}</td></tr>`;
      shown++;
    }
  }
  if (fileEntries.length > 30) html += `<tr><td colspan="4" style="color:var(--text-dim)">...and ${fileEntries.length - 30} more files</td></tr>`;
  html += '</tbody></table>';
  setHtmlById('fileOpsTable', html);
}

/**
 * Render bash commands section: category chart, pills, and table.
 * @param {Object} s - Session detail object with bash_commands and bash_category_summary.
 */
function renderBashSection(s) {
  const bashCmds = s.bash_commands || [];
  if (!bashCmds.length) {
    setHtmlById('bashTable', '<p style="color:var(--text-dim);font-size:13px;">No bash commands</p>');
    document.getElementById('bashChartBox').classList.add('hidden');
    if (bashCatChart) { bashCatChart.destroy(); bashCatChart = null; }
    return;
  }
  const catSummary = s.bash_category_summary || {};
  if (bashCatChart) bashCatChart.destroy();
  const catEntries = Object.entries(catSummary).sort((a,b) => b[1]-a[1]);
  if (catEntries.length) {
    document.getElementById('bashChartBox').classList.remove('hidden');
    bashCatChart = new Chart(document.getElementById('bashCatChart'), {
      type: 'doughnut',
      data: {
        labels: catEntries.map(e => e[0]),
        datasets: [{ data: catEntries.map(e => e[1]), backgroundColor: catEntries.map(e => BASH_CAT_COLORS[e[0]] || '#8b8fa3'), borderWidth: 0 }]
      },
      options: {
        responsive: true,
        plugins: {
          legend: { position: 'right', labels: { color: '#8b8fa3', font: { size: 11 } } },
          tooltip: { callbacks: { afterLabel: function(ctx) { return BASH_CAT_DESCRIPTIONS[ctx.label] || ''; } } }
        }
      }
    });
  } else {
    document.getElementById('bashChartBox').classList.add('hidden');
  }
  let html = '';
  if (Object.keys(catSummary).length > 1) {
    html += '<div class="category-pills" id="bashCatPills">';
    html += `<span class="cat-pill active" data-cat="all" onclick="filterBashCat('all')">All<span class="cat-count">${bashCmds.reduce((a,c)=>a+c.count,0)}</span></span>`;
    Object.entries(catSummary).forEach(([cat, cnt]) => {
      const desc = BASH_CAT_DESCRIPTIONS[cat] || '';
      html += `<span class="cat-pill" data-cat="${esc(cat)}" title="${esc(desc)}" onclick="filterBashCat('${esc(cat)}')">${esc(cat)}<span class="cat-count"> ${cnt}</span></span>`;
    });
    html += '</div>';
  }
  html += '<table><thead><tr><th>Command</th><th>Category</th><th>Count</th></tr></thead><tbody id="bashTableBody">';
  bashCmds.slice(0, 25).forEach(c => {
    html += `<tr data-cat="${esc(c.category || 'Other')}"><td class="mono">${esc(c.command)}</td><td><span style="font-size:11px;color:var(--text-dim)">${esc(c.category || 'Other')}</span></td><td>${c.count}</td></tr>`;
  });
  if (bashCmds.length > 25) html += `<tr class="bash-overflow" data-cat="all"><td colspan="3" style="color:var(--text-dim)">...and ${bashCmds.length - 25} more</td></tr>`;
  html += '</tbody></table>';
  setHtmlById('bashTable', html);
}

/**
 * Render the subagents accordion section.
 * @param {Array} subagents - Array of subagent data objects.
 */
function renderSubagentsSection(subagents) {
  const saDiv = document.getElementById('subagentsSection');
  if (!subagents.length) { saDiv.textContent = ''; return; }
  let html = '<div class="table-box"><h3>Subagents (' + esc(String(subagents.length)) + ')</h3>';
  subagents.forEach((sa, idx) => {
    const toolSummary = Object.entries(sa.tool_counts).map(([t,c]) => `${t}: ${c}`).join(', ');
    const agentType = sa.subagent_type || 'agent';
    const taskDesc = sa.task_description || '';
    const typeLabel = agentType !== 'agent' ? `<span class="agent-type-badge">${esc(agentType)}</span> ` : '';
    const headerLabel = taskDesc ? taskDesc : (agentType !== 'agent' ? agentType : `Agent ${sa.agent_id}`);
    const saActive = fmtDurationMs(sa.active_duration_ms);
    html += `<div class="subagent-card">
      <div class="subagent-header" onclick="toggleSubagent(${idx})">
        <div>${typeLabel}<span class="agent-label">${esc(headerLabel)}</span> <span class="agent-meta">${esc(String(sa.tool_count))} actions${saActive ? ' | ' + esc(saActive) : ''}</span></div>
        <span class="arrow" id="saArrow${idx}">&#9654;</span>
      </div>
      <div class="subagent-body" id="saBody${idx}">
        ${sa.description ? `<div class="subagent-desc"><strong>Task prompt:</strong> ${esc(sa.description)}</div>` : ''}
        <div style="font-size:12px;color:var(--text-dim);margin-bottom:8px;">${esc(toolSummary)}</div>
        <table><thead><tr><th>#</th><th>Tool</th><th>Detail</th></tr></thead><tbody>`;
    (sa.tool_calls || []).slice(0, 30).forEach(tc => {
      html += `<tr><td>${tc.seq}</td><td><span class="tool-badge ${getToolBadgeClass(tc.tool)}">${esc(tc.tool)}</span></td><td class="mono">${esc(tc.detail.slice(0, 120))}</td></tr>`;
    });
    if ((sa.tool_calls || []).length > 30) html += `<tr><td colspan="3" style="color:var(--text-dim)">...and ${sa.tool_calls.length - 30} more</td></tr>`;
    html += '</tbody></table></div></div>';
  });
  html += '</div>';
  setHtml(saDiv, html);
}

/**
 * Show full session detail in the explorer panel.
 * @param {Object} s - Session detail object from the API.
 */
function showSessionDetail(s) {
  currentSession = s;
  document.getElementById('explorerEmpty').classList.add('hidden');
  document.getElementById('sessionDetail').classList.remove('hidden');

  // Title and prompt
  document.getElementById('sessionTitle').textContent = s.slug || s.session_id.slice(0, 12);
  document.getElementById('promptText').textContent = s.first_prompt || '(no prompt captured)';

  // Conversation flow
  const flowDiv = document.getElementById('conversationFlow');
  const turns = s.user_turns || [];
  if (turns.length > 1) {
    let flowHtml = `<details><summary>Conversation Flow (${esc(String(turns.length))} turns${s.interrupt_count ? ', ' + esc(String(s.interrupt_count)) + ' interrupted' : ''})</summary><ul class="turn-list">`;
    turns.forEach(t => {
      const cls = t.is_interrupt ? ' interrupt' : '';
      const timeStr = t.timestamp ? fmtTime(t.timestamp) : '';
      flowHtml += `<li class="turn-item${cls}"><span class="turn-number">#${esc(String(t.turn_number))}</span>${timeStr ? '<span class="turn-time">' + esc(timeStr) + '</span>' : ''}${esc(t.text)}</li>`;
    });
    flowHtml += '</ul></details>';
    setHtml(flowDiv, flowHtml);
    flowDiv.classList.remove('hidden');
  } else {
    flowDiv.classList.add('hidden');
  }

  // Meta row
  const subagents = s.subagents || [];
  setHtmlById('sessionMeta', buildSessionMeta(s, subagents));

  // Tool donut chart (combined: parent + subagent tools)
  if (sessionToolChart) sessionToolChart.destroy();
  const combinedToolCounts = { ...s.tool_counts };
  subagents.forEach(sa => {
    Object.entries(sa.tool_counts).forEach(([t, c]) => {
      combinedToolCounts[t] = (combinedToolCounts[t] || 0) + c;
    });
  });
  const tc = Object.entries(combinedToolCounts).sort((a,b) => b[1]-a[1]);
  sessionToolChart = new Chart(document.getElementById('sessionToolChart'), {
    type: 'doughnut',
    data: {
      labels: tc.map(e => e[0]),
      datasets: [{ data: tc.map(e => e[1]), backgroundColor: tc.map(e => getToolColor(e[0])), borderWidth: 0 }]
    },
    options: { responsive: true, plugins: { legend: { position: 'right', labels: { color: '#8b8fa3', font: { size: 11 } } } } }
  });

  // Delegated sections
  renderFileOpsTable(s);
  renderBashSection(s);
  renderSubagentsSection(subagents);
  renderActionLog(s);
}

function toggleSubagent(idx) {
  const body = document.getElementById('saBody' + idx);
  const arrow = document.getElementById('saArrow' + idx);
  body.classList.toggle('open');
  arrow.classList.toggle('open');
}

function filterBashCat(cat) {
  document.querySelectorAll('#bashCatPills .cat-pill').forEach(p => {
    p.classList.toggle('active', p.dataset.cat === cat);
  });
  document.querySelectorAll('#bashTableBody tr').forEach(row => {
    if (cat === 'all') {
      row.style.display = '';
    } else {
      row.style.display = (row.dataset.cat === cat) ? '' : 'none';
    }
  });
}

// ---- ACTION LOG ----
/**
 * Render the action log tab for a session.
 * @param {Object} s - Session detail object with tool_calls and subagents.
 */
function renderActionLog(s) {
  document.getElementById('logNoSession').classList.add('hidden');
  document.getElementById('logActive').classList.remove('hidden');

  const allCalls = [...(s.tool_calls || [])];
  (s.subagents || []).forEach(sa => {
    (sa.tool_calls || []).forEach(tc => {
      allCalls.push({ ...tc, is_subagent: true, agent_id: sa.agent_id });
    });
  });

  allCalls.sort((a, b) => {
    if (a.time && b.time) return a.time.localeCompare(b.time);
    return 0;
  });
  allCalls.forEach((c, i) => c._seq = i + 1);

  const toolTypes = [...new Set(allCalls.map(c => c.tool))].sort();
  logToolFilters = new Set(toolTypes);
  const filterDiv = document.getElementById('toolFilters');
  filterDiv.textContent = '';
  const filterLabel = document.createElement('strong');
  filterLabel.style.fontSize = '12px';
  filterLabel.style.color = 'var(--text-dim)';
  filterLabel.textContent = 'Filter:';
  filterDiv.appendChild(filterLabel);
  toolTypes.forEach(t => {
    const label = document.createElement('label');
    const cb = document.createElement('input');
    cb.type = 'checkbox'; cb.checked = true; cb.dataset.tool = t;
    cb.addEventListener('change', () => {
      if (cb.checked) logToolFilters.add(t); else logToolFilters.delete(t);
      logPage = 1;
      renderLogPage(allCalls);
    });
    label.appendChild(cb);
    label.appendChild(document.createTextNode(' ' + t));
    filterDiv.appendChild(label);
  });

  logPage = 1;
  renderLogPage(allCalls);
}

function renderLogPage(allCalls) {
  const filtered = allCalls.filter(c => logToolFilters.has(c.tool));
  const totalPages = Math.max(1, Math.ceil(filtered.length / LOG_PAGE_SIZE));
  if (logPage > totalPages) logPage = totalPages;

  const start = (logPage - 1) * LOG_PAGE_SIZE;
  const page = filtered.slice(start, start + LOG_PAGE_SIZE);

  const tbody = document.getElementById('logTableBody');
  tbody.textContent = '';
  page.forEach(c => {
    const tr = document.createElement('tr');
    const time = c.time ? fmtTime(c.time) : '';
    const source = c.is_subagent ? `<span style="color:var(--accent2);font-size:11px;">agent-${esc(c.agent_id || '?')}</span>` : '<span style="color:var(--text-dim);font-size:11px;">main</span>';
    setHtml(tr, `<td>${c._seq}</td><td class="mono">${esc(time)}</td><td><span class="tool-badge ${getToolBadgeClass(c.tool)}">${esc(c.tool)}</span></td><td class="mono detail-cell" title="${esc(c.detail)}">${esc(c.detail.slice(0, 150))}</td><td>${source}</td>`);
    tbody.appendChild(tr);
  });

  setHtmlById('logPagination', `
    <button onclick="logPageNav(-1)" ${logPage <= 1 ? 'disabled' : ''}>Prev</button>
    <span class="page-info">Page ${logPage} of ${totalPages} (${filtered.length} actions)</span>
    <button onclick="logPageNav(1)" ${logPage >= totalPages ? 'disabled' : ''}>Next</button>
  `);

  window._logAllCalls = allCalls;
}

function logPageNav(delta) {
  logPage += delta;
  renderLogPage(window._logAllCalls);
}

// ---- HELPERS ----
/** @param {number} ms - Duration in milliseconds. @returns {string|null} Human-readable duration. */
function fmtDurationMs(ms) {
  if (!ms || ms <= 0) return null;
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ${secs % 60}s`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ${mins % 60}m`;
}
/** @param {number} n - Token count. @returns {string} Formatted token count (e.g. "1.2M"). */
function fmtTokenCount(n) {
  if (!n) return '0';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return n.toLocaleString();
}
/** @param {string} s - Raw string. @returns {string} HTML-escaped string. */
function esc(s) { if (!s) return ''; const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function fmtDate(ts) { if (!ts) return ''; try { const d = new Date(ts); return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }); } catch(e) { return ts.slice(0,10); } }
function fmtDateTime(ts) { if (!ts) return ''; try { const d = new Date(ts); return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }); } catch(e) { return ts; } }
function fmtTime(ts) { if (!ts) return ''; try { const d = new Date(ts); return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' }); } catch(e) { return ts; } }
function shortenPath(p) {
  const parts = p.split('/');
  if (parts.length <= 4) return p;
  return '.../' + parts.slice(-3).join('/');
}
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
