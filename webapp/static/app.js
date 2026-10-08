// ============================================================
// State
// ============================================================
let projectId = null;
let questions = [];
let agentMeta = [];

// Conversational discovery flow state
let dfAnswers = {};       // question_id -> answer text
let dfSkipped = {};       // question_id -> true, for questions explicitly skipped
let dfIndex = 0;          // index of the question currently on screen
let dfShowingReview = false;
let dfReturnToReview = false; // true when we jumped here via "Edit" from the review screen
const OTHER_LABEL = 'Something else';
const ADDITIONAL_INFO_ID = 'additional_information';

// Agent-run state. runState drives the "Run AI Agents" button so it can never be
// double-clicked: idle -> running -> done, or running -> error (re-enabled to retry).
let runState = 'idle';          // 'idle' | 'running' | 'done' | 'error' | 'paused' (waiting after a RETHINK feasibility verdict)
let nextAgentIndex = 0;         // where a retry after an error resumes
let hasGeneratedBefore = false; // this project already has a generated package (reopened / re-run)
let lastHandoffStatus = null;
let lastNotesCount = 0;

const NODE_X_START = 70;
const NODE_X_GAP = 150;
const NODE_Y = 70;
const NODE_R = 26;

// ============================================================
// Helpers
// ============================================================
function $(sel) { return document.querySelector(sel); }
function el(tag, attrs = {}, children = []) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'text') e.textContent = v;
    else if (k === 'html') e.innerHTML = v;
    else e.setAttribute(k, v);
  }
  for (const c of children) e.appendChild(c);
  return e;
}
function unlock(panelId) { $(panelId).classList.remove('is-locked'); }

async function api(path, opts = {}) {
  const data = await rawApi(path, opts);
  // Live-mode steps run as background jobs (they make many LLM calls and can
  // take minutes): the POST answers with a job id and we poll until it's done,
  // then hand back exactly what the synchronous endpoint would have returned.
  if (data && data.job_id) return pollJob(data.job_id);
  return data;
}

function showJobProgress(lines) {
  const log = $('#agent-log');
  let box = $('#job-progress');
  if (!lines) { if (box) box.remove(); return; }
  if (!box) box = log.appendChild(el('div', { id: 'job-progress', class: 'log-progress' }));
  box.textContent = lines.slice(-3).map((l) => '   ⋯ ' + l).join('\n');
  box.style.whiteSpace = 'pre-wrap';
  log.scrollTop = log.scrollHeight;
}

async function pollJob(jobId) {
  const started = Date.now();
  let failures = 0;
  try {
    while (Date.now() - started < 30 * 60 * 1000) {
      await new Promise((r) => setTimeout(r, 2000));
      let snap;
      try {
        snap = await rawApi(`/api/job/${jobId}`);
        failures = 0;
      } catch (e) {
        if (/unknown or expired job/.test(e.message)) {
          throw new Error('The server restarted while generating — please try again.');
        }
        if (++failures >= 5) throw e;   // tolerate a few network blips
        continue;
      }
      if (snap.status === 'error') throw new Error(snap.error || 'generation failed');
      if (snap.status === 'done') return snap.result;
      showJobProgress(snap.progress && snap.progress.length ? snap.progress : ['working…']);
    }
    throw new Error('Generation is taking unusually long (over 30 minutes) — please try again.');
  } finally {
    showJobProgress(null);
  }
}

async function rawApi(path, opts = {}) {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  let data;
  try {
    data = await res.json();
  } catch (parseErr) {
    // The response wasn't JSON at all — almost always means a proxy/host
    // timed the request out (or crashed) and served its own HTML error
    // page before our Flask app's JSON error handler ever got to run.
    // Surface something actionable instead of the raw parse error.
    throw new Error(
      res.ok
        ? 'The server sent back an unexpected response. It may have timed out — please try again.'
        : `Request failed (HTTP ${res.status}). The server may have timed out — please try again.`
    );
  }
  if (!res.ok) throw new Error(data.error || 'request failed');
  return data;
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// downloadMarkdown / downloadBlob / ZIP writer / Word (.docx) export live in export.js

// Status strings like "READY FOR DESIGN AGENT" have spaces, which can't
// be used directly as CSS classes — slugify for styling, keep the raw
// text for display.
function statusSlug(status) {
  if (!status) return 'unknown';
  const s = status.toUpperCase();
  if (s.includes('NOT READY')) return 'status-not-ready';
  if (s.includes('WARNING')) return 'status-warnings';
  if (s.includes('READY')) return 'status-ready';
  return 'status-unknown';
}

// ============================================================
// Title block
// ============================================================
function setTitleBlock({ projectId, domain }) {
  $('#tb-project').textContent = projectId ? projectId.slice(0, 8) : '—';
  $('#tb-domain').textContent = domain || '—';
  $('#tb-date').textContent = new Date().toISOString().slice(0, 10);
  updateProjectHeader();
}

async function refreshDomainCount() {
  try {
    const data = await api('/api/knowledge/domains');
    $('#tb-domains').textContent = `${data.domains.length} domains`;
    $('#dash-kb').textContent = `${data.domains.length} domains in knowledge base`;
  } catch (e) { /* non-critical */ }
}

async function checkMode() {
  const elm = $('#tb-mode');
  try {
    const data = await api('/api/mode');
    const label = data.mode === 'live' ? `LIVE · ${data.provider.toUpperCase()}` : 'MOCK · offline';
    elm.textContent = label;
    $('#dash-mode-text').textContent = label;
    $('#dash-mode').classList.toggle('is-live', data.mode === 'live');
    $('#tb-mode').closest('.sys-pill').classList.toggle('is-live', data.mode === 'live');
  } catch (e) {
    elm.textContent = 'unknown';
    $('#dash-mode-text').textContent = 'unknown';
  }
}
checkMode();

// ============================================================
// View switching: dashboard <-> pipeline
// ============================================================
$('#btn-go-dashboard').addEventListener('click', goToDashboard);
$('#btn-pipeline-back').addEventListener('click', goToDashboard);
function startNewProject() {
  sessionStorage.setItem('poc_view', 'pipeline');
  history.replaceState(null, '', location.pathname);
  location.reload();
}
$('#btn-open-new-project').addEventListener('click', startNewProject);
$('#btn-empty-new').addEventListener('click', startNewProject);

function goToDashboard() {
  if (runState === 'running' &&
      !confirm('The AI agents are still running. If you leave now this run is lost (your answers stay saved as a draft). Leave anyway?')) return;
  runState = 'idle';   // let the unload guard below stand down
  sessionStorage.removeItem('poc_view');
  history.replaceState(null, '', location.pathname);
  location.reload();
}

// Guards against closing the tab in the middle of an agent run. Answers are autosaved
// server-side after every question, so nothing else is ever lost by closing the tab.
window.addEventListener('beforeunload', (e) => {
  if (runState === 'running') { e.preventDefault(); e.returnValue = ''; }
});

function showPipelineView() {
  $('#dashboard-view').hidden = true;
  $('#pipeline-view').hidden = false;
  $('#title-block').hidden = false;      // project context header only makes sense inside a project
}

function showDashboardList() {
  $('#pipeline-view').hidden = true;
  $('#title-block').hidden = true;
  $('#dashboard-view').hidden = false;
  loadDashboard();
}

function openProject(id) {
  location.hash = 'project=' + id;
  location.reload();
}

// ============================================================
// Dashboard — summary cards, insights, and a filterable project list
// ============================================================
const DASH_TOTAL_DOCS = 6;   // the full handoff package is 6 documents
const DASH_CATS = {
  ready:    { label: 'Design-ready',        short: 'READY',     cls: 'c-ready' },
  warn:     { label: 'Ready with warnings', short: 'WARNINGS',  cls: 'c-warn' },
  notready: { label: 'Not ready',           short: 'NOT READY', cls: 'c-notready' },
  draft:    { label: 'In progress',         short: 'DRAFT',     cls: 'c-draft' },
  unknown:  { label: 'Unknown',             short: 'UNKNOWN',   cls: 'c-unknown' },
};
let dashProjects = [];
const dashFilter = { status: 'all', domain: 'all', q: '', sort: 'updated' };

function dashCat(p) {
  if (p.status === 'draft') return 'draft';
  const s = statusSlug(p.handoff_status);
  if (s === 'status-ready') return 'ready';
  if (s === 'status-warnings') return 'warn';
  if (s === 'status-not-ready') return 'notready';
  return 'unknown';
}
function dashDomainLabel(d) { return d ? d.replace(/^e_commerce/, 'e-commerce').replace(/_/g, ' ') : 'unclassified'; }
function dashStamp(p) { const t = Date.parse(p.updated_at || p.created_at || ''); return isNaN(t) ? 0 : t; }
function relTime(ts) {
  if (!ts) return 'unknown';
  const diff = Math.max(0, Date.now() - ts), m = Math.round(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} hr ago`;
  const d = Math.round(h / 24);
  if (d < 30) return `${d} day${d === 1 ? '' : 's'} ago`;
  return new Date(ts).toLocaleDateString();
}

async function loadDashboard() {
  $('#dash-loading-msg').hidden = false;
  $('#dash-loading-msg').textContent = 'Loading projects…';
  $('#dash-empty-msg').hidden = true;
  $('#dash-content').hidden = true;
  refreshDomainCount();
  try {
    const data = await api('/api/history');
    dashProjects = data.projects || [];
    renderDashboard();
  } catch (e) {
    $('#dash-loading-msg').textContent = 'Could not load projects: ' + e.message;
  }
}

function renderDashboard() {
  $('#dash-loading-msg').hidden = true;
  if (!dashProjects.length) {
    $('#dash-empty-msg').hidden = false; $('#dash-content').hidden = true; return;
  }
  $('#dash-empty-msg').hidden = true; $('#dash-content').hidden = false;
  renderKpis();
  renderInsights();
  renderFilters();
  renderDashTable();
}

function dashCounts() {
  const c = { ready: 0, warn: 0, notready: 0, draft: 0, unknown: 0 };
  dashProjects.forEach(p => { c[dashCat(p)]++; });
  return c;
}

function setDashStatus(status) {
  dashFilter.status = (dashFilter.status === status) ? 'all' : status;
  renderFilters(); renderDashTable(); renderKpis();
  $('#dash-list-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderKpis() {
  const c = dashCounts(), total = dashProjects.length, done = total - c.draft;
  const pct = n => (total ? Math.round(n / total * 100) : 0) + '% of all';
  const cards = [
    { key: 'all',      n: total,      label: 'Total projects',      sub: `${done} complete · ${c.draft} in progress`, cls: 'c-all' },
    { key: 'ready',    n: c.ready,    label: 'Design-ready',        sub: pct(c.ready) },
    { key: 'warn',     n: c.warn,     label: 'Ready with warnings', sub: pct(c.warn) },
    { key: 'notready', n: c.notready, label: 'Not ready',           sub: pct(c.notready) },
    { key: 'draft',    n: c.draft,    label: 'In progress',         sub: c.draft ? 'resume where you left off' : 'no unfinished drafts' },
  ];
  const row = $('#kpi-row');
  row.innerHTML = '';
  cards.forEach(k => {
    const cls = k.key === 'all' ? 'c-all' : DASH_CATS[k.key].cls;
    const active = (dashFilter.status === k.key) || (k.key === 'all' && dashFilter.status === 'all');
    const card = el('button', { type: 'button', class: `kpi ${cls}${active && k.key !== 'all' ? ' is-active' : ''}`, 'aria-pressed': String(active && k.key !== 'all') }, [
      el('span', { class: 'kpi-num', text: String(k.n) }),
      el('span', { class: 'kpi-label', text: k.label }),
      el('span', { class: 'kpi-sub', text: k.sub }),
    ]);
    card.addEventListener('click', () => {
      if (k.key === 'all') { dashFilter.status = 'all'; renderFilters(); renderDashTable(); renderKpis(); }
      else setDashStatus(k.key);
    });
    row.appendChild(card);
  });
}

function renderInsights() {
  const c = dashCounts(), total = dashProjects.length, done = total - c.draft;

  // --- Handoff readiness: stacked bar over completed projects + legend ---
  const rb = $('#ins-readiness-body'); rb.innerHTML = '';
  const readyPct = done ? Math.round(c.ready / done * 100) : 0;
  const okPct = done ? Math.round((c.ready + c.warn) / done * 100) : 0;
  $('#ins-readiness-meta').textContent = `${done} completed`;
  if (!done) {
    rb.appendChild(el('div', { class: 'ins-empty', text: 'No completed projects yet.' }));
  } else {
    rb.appendChild(el('div', { class: 'ready-big' }, [
      el('span', { class: 'ready-big-num', text: okPct + '%' }),
      el('span', { class: 'ready-big-label', text: `can go to design now (${readyPct}% clean, ${okPct - readyPct}% with warnings)` }),
    ]));
    const bar = el('div', { class: 'stack-bar', role: 'img', 'aria-label': 'Handoff readiness breakdown' });
    ['ready', 'warn', 'notready', 'unknown'].forEach(k => {
      if (!c[k]) return;
      const seg = el('span', { class: `stack-seg ${DASH_CATS[k].cls}`, title: `${DASH_CATS[k].label}: ${c[k]}` });
      seg.style.flexGrow = String(c[k]);
      bar.appendChild(seg);
    });
    rb.appendChild(bar);
    const legend = el('div', { class: 'legend' });
    ['ready', 'warn', 'notready'].forEach(k => {
      const item = el('button', { type: 'button', class: 'legend-item' }, [
        el('span', { class: `legend-dot ${DASH_CATS[k].cls}` }),
        el('span', { class: 'legend-label', text: DASH_CATS[k].label }),
        el('span', { class: 'legend-n', text: String(c[k]) }),
      ]);
      item.addEventListener('click', () => setDashStatus(k));
      legend.appendChild(item);
    });
    rb.appendChild(legend);
  }

  // --- Domains: horizontal bars ---
  const db = $('#ins-domains-body'); db.innerHTML = '';
  const byDomain = {};
  dashProjects.forEach(p => { const d = p.domain || 'unclassified'; byDomain[d] = (byDomain[d] || 0) + 1; });
  const doms = Object.entries(byDomain).sort((a, b) => b[1] - a[1]);
  $('#ins-domains-meta').textContent = `${doms.length} domain${doms.length === 1 ? '' : 's'}`;
  const max = doms.length ? doms[0][1] : 1, topN = 6;
  doms.slice(0, topN).forEach(([d, n]) => {
    const row = el('button', { type: 'button', class: `bar-row${dashFilter.domain === d ? ' is-active' : ''}` }, [
      el('span', { class: 'bar-label', text: dashDomainLabel(d), title: dashDomainLabel(d) }),
      el('span', { class: 'bar-track' }, [el('span', { class: 'bar-fill', style: `width:${Math.max(6, n / max * 100)}%` })]),
      el('span', { class: 'bar-n', text: String(n) }),
    ]);
    row.addEventListener('click', () => {
      dashFilter.domain = (dashFilter.domain === d) ? 'all' : d;
      renderFilters(); renderDashTable(); renderInsights();
      $('#dash-list-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    db.appendChild(row);
  });
  if (doms.length > topN) db.appendChild(el('div', { class: 'ins-more', text: `+ ${doms.length - topN} more — use the domain filter below` }));

  // --- Needs attention: not-ready first, then drafts, newest first ---
  const ab = $('#ins-attention-body'); ab.innerHTML = '';
  const attn = dashProjects
    .filter(p => ['notready', 'draft'].includes(dashCat(p)))
    .sort((a, b) => (dashCat(a) === dashCat(b) ? dashStamp(b) - dashStamp(a) : (dashCat(a) === 'notready' ? -1 : 1)));
  $('#ins-attention-meta').textContent = attn.length ? `${attn.length} item${attn.length === 1 ? '' : 's'}` : '';
  if (!attn.length) {
    ab.appendChild(el('div', { class: 'ins-empty ok', text: '✓ Nothing blocking — every project is ready or has only warnings.' }));
  } else {
    attn.slice(0, 4).forEach(p => {
      const cat = dashCat(p);
      const item = el('button', { type: 'button', class: 'attn-item' }, [
        el('span', { class: `attn-tag ${DASH_CATS[cat].cls}`, text: DASH_CATS[cat].short }),
        el('span', { class: 'attn-idea', text: p.business_idea, title: p.business_idea }),
        el('span', { class: 'attn-go', text: cat === 'draft' ? 'Resume →' : 'Review →' }),
      ]);
      item.addEventListener('click', () => openProject(p.id));
      ab.appendChild(item);
    });
    if (attn.length > 4) {
      const more = el('button', { type: 'button', class: 'ins-more link-btn', text: `View all ${attn.length} →` });
      more.addEventListener('click', () => setDashStatus(attn.some(p => dashCat(p) === 'notready') ? 'notready' : 'draft'));
      ab.appendChild(more);
    }
  }
}

function renderFilters() {
  const c = dashCounts(), total = dashProjects.length;
  const seg = $('#dash-status-filter'); seg.innerHTML = '';
  [['all', 'All', total], ['ready', 'Ready', c.ready], ['warn', 'Warnings', c.warn], ['notready', 'Not ready', c.notready], ['draft', 'Drafts', c.draft]]
    .forEach(([key, label, n]) => {
      const b = el('button', { type: 'button', class: `seg-btn${dashFilter.status === key ? ' is-active' : ''}`, 'aria-pressed': String(dashFilter.status === key) }, [
        el('span', { text: label }), el('span', { class: 'seg-n', text: String(n) }),
      ]);
      b.addEventListener('click', () => { dashFilter.status = key; renderFilters(); renderDashTable(); renderKpis(); });
      seg.appendChild(b);
    });

  const sel = $('#dash-domain-filter');
  const domains = [...new Set(dashProjects.map(p => p.domain || 'unclassified'))].sort();
  if (dashFilter.domain !== 'all' && !domains.includes(dashFilter.domain)) dashFilter.domain = 'all';
  sel.innerHTML = '';
  sel.appendChild(el('option', { value: 'all', text: 'All domains' }));
  domains.forEach(d => sel.appendChild(el('option', { value: d, text: dashDomainLabel(d) })));
  sel.value = dashFilter.domain;
}

function filteredDashProjects() {
  const q = dashFilter.q.trim().toLowerCase();
  const rank = { notready: 0, draft: 1, warn: 2, unknown: 3, ready: 4 };
  const list = dashProjects.filter(p => {
    if (dashFilter.status !== 'all' && dashCat(p) !== dashFilter.status) return false;
    if (dashFilter.domain !== 'all' && (p.domain || 'unclassified') !== dashFilter.domain) return false;
    if (q && !(`${p.business_idea} ${dashDomainLabel(p.domain)}`.toLowerCase().includes(q))) return false;
    return true;
  });
  const by = {
    updated: (a, b) => dashStamp(b) - dashStamp(a),
    oldest:  (a, b) => dashStamp(a) - dashStamp(b),
    risk:    (a, b) => rank[dashCat(a)] - rank[dashCat(b)] || dashStamp(b) - dashStamp(a),
    ready:   (a, b) => rank[dashCat(b)] - rank[dashCat(a)] || dashStamp(b) - dashStamp(a),
    name:    (a, b) => (a.business_idea || '').localeCompare(b.business_idea || ''),
  }[dashFilter.sort];
  return list.sort(by);
}

function renderDashTable() {
  const body = $('#dash-table-body');
  body.innerHTML = '';
  const rows = filteredDashProjects();
  $('#dash-count').textContent = rows.length === dashProjects.length
    ? `${rows.length} project${rows.length === 1 ? '' : 's'}`
    : `showing ${rows.length} of ${dashProjects.length}`;
  $('#dash-table').hidden = !rows.length;
  $('#dash-nomatch').hidden = !!rows.length;

  rows.forEach(p => {
    const isDraft = p.status === 'draft';
    const cat = dashCat(p);
    const ts = dashStamp(p);

    const statusBadge = isDraft
      ? el('span', { class: 'history-badge status-draft', text: p.question_count ? `DRAFT · ${p.answered_count}/${p.question_count}` : 'DRAFT' })
      : el('span', { class: 'history-badge status-ready', text: 'COMPLETE' });
    const handoff = isDraft
      ? el('span', { class: 'dash-muted', text: '—' })
      : el('span', { class: `history-badge ${statusSlug(p.handoff_status)}`, text: p.handoff_status || 'unknown' });

    // documents meter: one segment per document in the full package
    const docs = Math.min(p.artefact_count || 0, DASH_TOTAL_DOCS);
    const meter = el('span', { class: 'doc-meter', title: `${p.artefact_count || 0} of ${DASH_TOTAL_DOCS} documents generated` });
    for (let i = 0; i < DASH_TOTAL_DOCS; i++) meter.appendChild(el('i', { class: i < docs ? 'on' : '' }));
    const docCell = el('td', {}, [el('div', { class: 'doc-cell' }, [meter, el('span', { class: 'doc-n', text: `${p.artefact_count || 0}/${DASH_TOTAL_DOCS}` })])]);

    const actionsBox = el('div', { class: 'dash-actions' });
    const actions = el('td', { class: 'dash-actions-cell' }, [actionsBox]);
    const openBtn = el('button', { type: 'button', class: 'btn btn-small', text: isDraft ? 'Resume →' : 'Open →' });
    openBtn.addEventListener('click', (ev) => { ev.stopPropagation(); openProject(p.id); });
    const delBtn = el('button', { type: 'button', class: 'btn btn-small btn-icon btn-icon-danger', title: 'Delete project', 'aria-label': 'Delete project: ' + clip(p.business_idea || 'untitled', 60) });
    delBtn.innerHTML = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.2c0 .5.4.8.8.8h4.2c.4 0 .8-.3.8-.8l.6-8.2M6.7 7v4M9.3 7v4" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    delBtn.addEventListener('click', (ev) => { ev.stopPropagation(); confirmDeleteProject(p, delBtn); });
    actionsBox.append(openBtn, delBtn);

    const row = el('tr', { class: `row-${cat}` }, [
      el('td', { class: 'dash-idea-cell', title: p.business_idea }, [el('span', { class: 'idea-text', text: p.business_idea })]),
      el('td', {}, [el('span', { class: 'domain-pill', text: dashDomainLabel(p.domain), title: dashDomainLabel(p.domain) })]),
      el('td', {}, [statusBadge]),
      docCell,
      el('td', {}, [handoff]),
      el('td', { class: 'dash-date-cell', title: ts ? new Date(ts).toLocaleString() : '' }, [document.createTextNode(relTime(ts))]),
      actions,
    ]);
    row.addEventListener('click', () => openProject(p.id));
    body.appendChild(row);
  });
}

// ---- Delete a project (draft or completed) with an in-app confirmation ----
let delPending = null, delReturnFocus = null;
function confirmDeleteProject(p, returnFocusEl) {
  delPending = p; delReturnFocus = returnFocusEl || null;
  const isDraft = p.status === 'draft';
  $('#del-modal-title').textContent = isDraft ? 'Delete this draft?' : 'Delete this project?';
  const lead = $('#del-modal-lead'); lead.innerHTML = '';
  lead.append(el('b', { text: clip(p.business_idea || 'Untitled project', 140) }),
    document.createElement('br'),
    document.createTextNode(isDraft
      ? 'Your answers will be removed. This cannot be undone.'
      : `The feasibility assessment, all ${p.artefact_count || DASH_TOTAL_DOCS} generated documents and your discovery answers will be removed. This cannot be undone.`));
  const err = $('#del-modal-error'); if (err) err.remove();
  $('#del-modal-confirm').disabled = false; $('#del-modal-confirm').textContent = 'Delete permanently';
  $('#del-modal').hidden = false;
  $('#del-modal-cancel').focus();
}
function closeDeleteModal() {
  $('#del-modal').hidden = true; delPending = null;
  if (delReturnFocus && document.contains(delReturnFocus)) delReturnFocus.focus();
  delReturnFocus = null;
}
(function wireDeleteModal() {
  $('#del-modal-cancel').addEventListener('click', closeDeleteModal);
  $('#del-modal-close').addEventListener('click', closeDeleteModal);
  $('#del-modal').addEventListener('click', (e) => { if (e.target.id === 'del-modal') closeDeleteModal(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('#del-modal').hidden) closeDeleteModal(); });
  $('#del-modal-confirm').addEventListener('click', async () => {
    if (!delPending) return;
    const btn = $('#del-modal-confirm'), id = delPending.id;
    btn.disabled = true; btn.textContent = 'Deleting…';
    try {
      await api(`/api/project/${id}`, { method: 'DELETE' });
      dashProjects = dashProjects.filter(x => x.id !== id);
      delReturnFocus = null; closeDeleteModal();
      renderDashboard();
    } catch (e) {
      btn.disabled = false; btn.textContent = 'Delete permanently';
      const old = $('#del-modal-error'); if (old) old.remove();
      $('#del-modal-lead').after(el('p', { id: 'del-modal-error', class: 'modal-error', text: 'Could not delete: ' + e.message }));
    }
  });
})();

(function wireDashboardControls() {
  $('#dash-search').addEventListener('input', (e) => { dashFilter.q = e.target.value; renderDashTable(); });
  $('#dash-domain-filter').addEventListener('change', (e) => { dashFilter.domain = e.target.value; renderDashTable(); renderInsights(); });
  $('#dash-sort').addEventListener('change', (e) => { dashFilter.sort = e.target.value; renderDashTable(); });
  $('#dash-clear').addEventListener('click', () => {
    dashFilter.status = 'all'; dashFilter.domain = 'all'; dashFilter.q = '';
    $('#dash-search').value = '';
    renderFilters(); renderDashTable(); renderKpis(); renderInsights();
  });
})();

// Turns ```mermaid code blocks into rendered diagrams, each on its own light "canvas" card with a
// small notation legend so separate diagrams are easy to tell apart. Purely progressive: if the
// mermaid library didn't load or a diagram is invalid, the readable source stays.
const DIAGRAM_LEGEND = '<span class="lg lg-term"></span>Start / End<span class="lg lg-proc"></span>Process step<span class="lg lg-dec"></span>Decision';

function renderMermaidBlocks(viewer) {
  if (!window.mermaid) return;
  try {
    const blocks = viewer.querySelectorAll('pre > code.language-mermaid');
    blocks.forEach((code) => {
      const src = code.textContent;
      const card = document.createElement('div');
      card.className = 'diagram-card';
      if (/^\s*(flowchart|graph)/i.test(src)) {
        const legend = document.createElement('div');
        legend.className = 'diagram-legend';
        legend.innerHTML = DIAGRAM_LEGEND;
        card.appendChild(legend);
      }
      const div = document.createElement('div');
      div.className = 'mermaid';
      div.textContent = src;
      card.appendChild(div);
      code.parentElement.replaceWith(card);
    });
    if (blocks.length) {
      window.mermaid.run({ nodes: viewer.querySelectorAll('.mermaid'), suppressErrors: true })
        .then(() => viewer.querySelectorAll('.diagram-card svg').forEach(routeFlowchart))
        .catch(() => {});
    }
  } catch (e) { /* keep the source visible */ }
}

// ------------------------------------------------------------------------------------------
// Standard flowchart connector routing.
// Mermaid clips every connector to the slanted edge of a diamond, so lines appear to start
// mid-side and arrowheads float off the borders. After rendering, each connector is re-drawn
// from the node geometry using the usual flowchart conventions:
//   - only horizontal / vertical segments (right angles), one arrowhead at the target
//   - a decision leaves from its left, right or bottom corner point
//   - other shapes leave from the bottom centre and enter the target's top centre
//   - a line that goes back up (a retry loop) leaves from the side and re-enters from the side
// Any edge that cannot be routed cleanly (it would cross another shape) keeps Mermaid's own line.
// ------------------------------------------------------------------------------------------
function routeFlowchart(svg) {
  try {
    const nodeEls = [...svg.querySelectorAll('g.node')];
    const paths = [...svg.querySelectorAll('path.flowchart-link')];
    if (!nodeEls.length || !paths.length) return;

    const boxes = {};
    nodeEls.forEach((g) => {
      const m = /flowchart-(.+)-\d+$/.exec(g.id || '');
      if (!m) return;
      const t = /translate\(\s*([-\d.]+)[ ,]+([-\d.]+)/.exec(g.getAttribute('transform') || '');
      if (!t) return;
      const b = g.getBBox();                       // whole node, in the node's own (centred) coordinates
      const w = b.width, h = b.height, cx = +t[1] + b.x + w / 2, cy = +t[2] + b.y + h / 2;
      const isDecision = g.querySelector('polygon') !== null;
      boxes[m[1]] = { id: m[1], cx, cy, w, h, l: cx - w / 2, r: cx + w / 2, t: cy - h / 2, b: cy + h / 2, dec: isDecision };
    });

    const labels = [...svg.querySelectorAll('g.edgeLabels > g.edgeLabel')];
    const used = {};                               // decision exits already taken: id -> {left,right,bottom}
    const routed = [];
    const channels = [];                           // x positions already used by loop-back lines

    const hits = (pts, skip) => {
      for (let i = 0; i < pts.length - 1; i++) {
        const [x1, y1] = pts[i], [x2, y2] = pts[i + 1];
        const minx = Math.min(x1, x2), maxx = Math.max(x1, x2), miny = Math.min(y1, y2), maxy = Math.max(y1, y2);
        for (const k in boxes) {
          if (skip.includes(k)) continue;
          const n = boxes[k];
          if (maxx > n.l + 1 && minx < n.r - 1 && maxy > n.t + 1 && miny < n.b - 1) return true;
        }
      }
      return false;
    };

    // Distance the arrow tip sits beyond the path end, so the tip can touch the shape border.
    let tip = 4;
    const mk = svg.querySelector('marker');
    if (mk) {
      const vb = (mk.getAttribute('viewBox') || '0 0 10 10').split(/[ ,]+/).map(Number);
      const refX = parseFloat(mk.getAttribute('refX') || '5'), mw = parseFloat(mk.getAttribute('markerWidth') || vb[2]);
      if (vb[2] > 0 && mw > 0 && !isNaN(refX)) tip = Math.max(0, (vb[2] - refX) * (mw / vb[2]));
    }

    const edges = [];
    paths.forEach((path, idx) => {
      // which shapes does this line join? Newer Mermaid puts it in the id (L_A_B_0 / L-A-B-0),
      // older versions also add LS-A / LE-B classes.
      const cls = path.getAttribute('class') || '';
      let s = (/LS-(\S+)/.exec(cls) || [])[1], e = (/LE-(\S+)/.exec(cls) || [])[1];
      if (!s || !e) {
        const ids = Object.keys(boxes), esc = (x) => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        outer: for (const a of ids) for (const b of ids) {
          if (new RegExp('(^|[-_])L[-_]' + esc(a) + '[-_]' + esc(b) + '[-_]\\d+$').test(path.id || '')) { s = a; e = b; break outer; }
        }
      }
      const S = boxes[s], T = boxes[e];
      if (S && T && S !== T) edges.push({ path, idx, S, T });
    });
    // loop-back lines first, so they reserve their corner points before forward lines choose theirs
    const isBack = (E) => !(E.T.t > E.S.b + 6);
    edges.sort((x, y) => (isBack(y) ? 1 : 0) - (isBack(x) ? 1 : 0));

    edges.forEach(({ path, idx, S, T }) => {
      const dx = T.cx - S.cx;
      const usedS = (used[S.id] = used[S.id] || {}), usedT = (used[T.id] = used[T.id] || {});
      const cands = [];                                           // candidate routes, best first

      if (T.t > S.b + 6) {                                         // forward: target is below
        const side = dx < 0 ? 'left' : 'right', sideX = dx < 0 ? S.l : S.r;
        const sideRoute = () => [[sideX, S.cy], [T.cx, S.cy], [T.cx, T.t]];
        const zRoute = (f) => { const my = S.b + (T.t - S.b) * f; return [[S.cx, S.b], [S.cx, my], [T.cx, my], [T.cx, T.t]]; };
        // leave the side, run past the target, come back into the target's facing side
        const wrapRoute = () => {
          const inX = dx < 0 ? T.r : T.l, x = dx < 0 ? T.r + 26 : T.l - 26;
          return [[sideX, S.cy], [x, S.cy], [x, T.cy], [inX, T.cy]];
        };
        const canSide = Math.abs(dx) > S.w / 2 + 8 && !usedS[side];
        const nb = usedS.bottomCount || 0;                          // lines already forking off the bottom point
        const canBottom = nb < 3;
        if (Math.abs(dx) < 3 && nb === 0) {
          const x = (S.cx + T.cx) / 2;                             // centres differ only by rounding
          cands.push({ pts: [[x, S.b], [x, T.t]], exit: 'bottom' });
        } else {
          const fr = [[0.5, 0.3, 0.7], [0.75, 0.25, 0.88], [0.9, 0.12, 0.6]][nb] || [];   // each fork gets its own level
          const z = canBottom ? fr.map((f) => ({ pts: zRoute(f), exit: 'bottom', seg: S.dec ? 1 : 0 })) : [];
          if (S.dec) {
            if (canSide) cands.push({ pts: sideRoute(), exit: side });
            cands.push(...z);
          } else {
            cands.push(...z);
            if (canSide) cands.push({ pts: sideRoute(), exit: side });
          }
          const enter = dx < 0 ? 'right' : 'left';
          if (canSide && !usedT[enter]) cands.push({ pts: wrapRoute(), exit: side, enter });
        }
      } else {                                                      // backward / same level: loop round a side
        const first = T.cx <= S.cx ? 'left' : 'right';
        [first, first === 'left' ? 'right' : 'left'].forEach((sd) => {
          if (usedS[sd] || usedT[sd]) return;
          let out = sd === 'left' ? Math.min(S.l, T.l) - 34 : Math.max(S.r, T.r) + 34;
          while (channels.some((c) => Math.abs(c - out) < 14)) out += sd === 'left' ? -16 : 16;   // keep loops apart
          cands.push({ pts: [[sd === 'left' ? S.l : S.r, S.cy], [out, S.cy], [out, T.cy], [sd === 'left' ? T.l : T.r, T.cy]], exit: sd, enter: sd, channel: out });
        });
      }
      const pick = cands.find((c) => !hits(c.pts, [S.id, T.id]));
      if (!pick) return;                                           // keep Mermaid's own line
      usedS[pick.exit] = true;
      if (pick.exit === 'bottom') usedS.bottomCount = (usedS.bottomCount || 0) + 1;
      if (pick.enter) usedT[pick.enter] = true;                    // a corner point carries one line only
      if (pick.channel !== undefined) channels.push(pick.channel);
      const pts = pick.pts, labelSeg = pick.seg || 0;

      // pull the last point back so the arrow TIP (not its base) lands on the border
      const n = pts.length, [px, py] = pts[n - 2], last = pts[n - 1];
      const len = Math.hypot(last[0] - px, last[1] - py) || 1;
      pts[n - 1] = [last[0] - ((last[0] - px) / len) * tip, last[1] - ((last[1] - py) / len) * tip];

      path.setAttribute('d', 'M' + pts.map((p) => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' L'));
      routed.push({ idx, pts, labelSeg });
    });

    // put each label on the first segment leaving its decision, on a white plate over the line
    routed.forEach(({ idx, pts, labelSeg }) => {
      const lab = labels[idx];
      if (!lab || !(lab.textContent || '').trim()) return;
      let a = pts[labelSeg], b = pts[labelSeg + 1];
      if (Math.hypot(b[0] - a[0], b[1] - a[1]) < 34 && pts[labelSeg + 2]) { a = pts[labelSeg + 1]; b = pts[labelSeg + 2]; }
      lab.setAttribute('transform', `translate(${((a[0] + b[0]) / 2).toFixed(1)}, ${((a[1] + b[1]) / 2).toFixed(1)})`);
    });

    // loop-back lines can run outside the box Mermaid measured — widen the drawing to include them
    const bb = svg.querySelector('g').getBBox();
    const pad = 12, vb = [bb.x - pad, bb.y - pad, bb.width + pad * 2, bb.height + pad * 2];
    svg.setAttribute('viewBox', vb.map((v) => v.toFixed(1)).join(' '));
    svg.style.maxWidth = vb[2].toFixed(0) + 'px';
  } catch (err) { /* leave Mermaid's own rendering untouched */ }
}

// Puts every table in a horizontally scrollable wrapper so wide tables use the full width
// available and scroll inside themselves instead of squeezing or overflowing the page.
function wrapTables(viewer) {
  viewer.querySelectorAll('table').forEach((t) => {
    if (t.parentElement && t.parentElement.classList.contains('table-wrap')) return;
    const wrap = document.createElement('div');
    wrap.className = 'table-wrap';
    t.replaceWith(wrap);
    wrap.appendChild(t);
  });
}

// ============================================================
// SHEET 01 — Intake
// ============================================================
const IDEA_DRAFT_KEY = 'poc_idea_draft';

// The idea text is kept locally as it's typed, so a closed tab before "Run discovery" loses nothing.
function restoreIdeaDraft() {
  try {
    const saved = localStorage.getItem(IDEA_DRAFT_KEY);
    if (saved && !$('#idea-input').value) $('#idea-input').value = saved;
  } catch (e) { /* storage unavailable */ }
  syncIdeaButton();
}
$('#idea-input').addEventListener('input', () => {
  try { localStorage.setItem(IDEA_DRAFT_KEY, $('#idea-input').value); } catch (e) { /* ignore */ }
  syncIdeaButton();
});
function syncIdeaButton() {
  const b = $('#btn-submit-idea');
  if (b.textContent.trim() === 'Run discovery →') b.disabled = !$('#idea-input').value.trim();
}

document.querySelectorAll('.chip').forEach(chip => {
  chip.addEventListener('click', () => {
    $('#idea-input').value = chip.dataset.idea;
    try { localStorage.setItem(IDEA_DRAFT_KEY, chip.dataset.idea); } catch (e) { /* ignore */ }
    syncIdeaButton();
    $('#idea-input').focus();
  });
});

$('#btn-submit-idea').addEventListener('click', async () => {
  const idea = $('#idea-input').value.trim();
  if (!idea) return;
  const btn = $('#btn-submit-idea');
  btn.disabled = true; btn.textContent = 'Running discovery…';

  try {
    const data = await api('/api/project', { method: 'POST', body: JSON.stringify({ idea }) });
    projectId = data.project_id;
    questions = data.questions;
    history.replaceState(null, '', '#project=' + projectId);   // refresh / reopened tab resumes this project
    try { localStorage.removeItem(IDEA_DRAFT_KEY); } catch (e) { /* ignore */ }
    setTitleBlock({ projectId, domain: `${data.domain} (${Math.round(data.confidence * 100)}%)` });
    await refreshDomainCount();
    if (data.learned_new_domain) $('#learned-banner').hidden = false;
    lockIntake();

    dfAnswers = {};
    dfSkipped = {};
    dfIndex = 0;
    dfShowingReview = false;
    dfReturnToReview = false;
    unlock('#panel-discovery');
    showDiscoveryQuestion(0);
  } catch (e) {
    alert('Something went wrong: ' + e.message);
    btn.disabled = false; btn.textContent = 'Run discovery →';
  }
});

// Once a project exists its idea is fixed (changing it would mean a different project).
function lockIntake() {
  $('#idea-input').readOnly = true;
  document.querySelector('.idea-examples').hidden = true;
  $('#btn-submit-idea').hidden = true;
  document.querySelector('.intake-actions').hidden = true;
  document.querySelector('.intake-tip').hidden = true;
  document.querySelector('.intake-aside').hidden = true;
  document.querySelector('.intake-grid').classList.add('is-single');
  $('#idea-input').setAttribute('rows', '2');
  $('#draft-note').hidden = false;
}

// ============================================================
// SHEET 02 — Discovery: sequential, conversational question flow
// ============================================================
const DF_MICROCOPY = {
  first: "Let's shape your idea into a plan.",
  penultimate: 'A few more details.',
  last: 'Almost there — last question.',
};

function microcopyFor(i, total) {
  if (total <= 1) return DF_MICROCOPY.first;
  if (i === 0) return DF_MICROCOPY.first;
  if (i === total - 1) return DF_MICROCOPY.last;
  if (i === total - 2) return DF_MICROCOPY.penultimate;
  if (i > 0 && i % 3 === 0) return "Let's narrow this down.";
  return '';
}

function humanizeCategory(cat) {
  return (cat || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function updateDiscoveryStatus() {
  const answeredCount = questions.filter(q => dfAnswers[q.id]).length;
  const skippedCount = questions.filter(q => dfSkipped[q.id]).length;
  const doneCount = answeredCount + skippedCount;
  if (dfShowingReview) { $('#discovery-status').textContent = 'reviewing'; return; }
  if (doneCount >= questions.length) {
    $('#discovery-status').textContent = skippedCount > 0 ? `complete (${skippedCount} skipped)` : 'complete';
  } else {
    $('#discovery-status').textContent = skippedCount > 0
      ? `${answeredCount} answered, ${skippedCount} skipped / ${questions.length}`
      : `${answeredCount} / ${questions.length} answered`;
  }
}

function showDiscoveryQuestion(index) {
  setCollapsed('#panel-discovery', false);
  dfIndex = Math.max(0, Math.min(index, questions.length - 1));
  dfShowingReview = false;
  $('#discovery-review').hidden = true;
  $('#discovery-flow').hidden = false;
  renderCurrentQuestion();
  updateDiscoveryStatus();
}

// Jump to a specific question from the review screen. Continuing from here
// returns straight to the review instead of marching through every
// remaining question, and answering it doesn't touch any other answer.
function editFromReview(index) {
  dfReturnToReview = true;
  showDiscoveryQuestion(index);
}

function renderCurrentQuestion() {
  const q = questions[dfIndex];
  const total = questions.length;

  // Progress
  $('#df-progress-fill').style.width = `${((dfIndex) / total) * 100 + (100 / total) * 0.15}%`;
  $('#df-progress-label').textContent = `Question ${dfIndex + 1} of ${total}`;

  // Copy
  const microcopyEl = $('#df-microcopy');
  const microcopyText = microcopyFor(dfIndex, total);
  microcopyEl.textContent = microcopyText;
  microcopyEl.hidden = !microcopyText;
  $('#df-category').textContent = humanizeCategory(q.category);
  $('#df-select-hint').hidden = !q.multi_select;
  $('#df-question').textContent = q.text;
  $('#df-skipped-note').hidden = !dfSkipped[q.id];

  // Nav
  $('#df-btn-back').hidden = dfIndex === 0;
  $('#df-btn-to-review').hidden = !dfReturnToReview;
  $('#df-btn-continue').textContent = dfReturnToReview ? 'Save & return to review →' : 'Continue →';

  const isExtra = q.id === ADDITIONAL_INFO_ID;
  $('#df-btn-skip').textContent = isExtra ? 'Nothing more to add — skip →' : 'Not sure / skip this question →';
  $('#df-freetext-input').placeholder = isExtra
    ? 'Optional — e.g. specific requirements, constraints, integrations, reference apps, data you already have…'
    : 'Type your answer…';
  $('#df-freetext-input').rows = isExtra ? 6 : 3;

  const existingAnswer = dfAnswers[q.id] || '';
  const optionsWrap = $('#df-options');
  const freetextWrap = $('#df-freetext');
  const freetextInput = $('#df-freetext-input');
  const otherWrap = $('#df-other-wrap');
  const otherInput = $('#df-other-input');
  const continueBtn = $('#df-btn-continue');

  optionsWrap.innerHTML = '';
  optionsWrap.setAttribute('role', q.multi_select ? 'group' : 'radiogroup');
  otherWrap.hidden = true;
  otherInput.value = '';

  if (q.options && q.options.length) {
    freetextWrap.hidden = true;

    if (q.multi_select) {
      // ---- Checkbox mode: several options may apply at once ----
      const parts = existingAnswer ? existingAnswer.split(' | ').map(p => p.trim()).filter(Boolean) : [];
      const selected = new Set(parts.filter(p => q.options.includes(p)));
      const otherText = parts.find(p => !q.options.includes(p)) || '';
      if (otherText) selected.add(OTHER_LABEL);

      const allOptions = q.options.includes(OTHER_LABEL) ? q.options : [...q.options, OTHER_LABEL];
      allOptions.forEach(opt => {
        const isSelected = selected.has(opt);
        const card = buildOptionCard(opt, isSelected, 'checkbox', opt === OTHER_LABEL);
        card.addEventListener('click', () => toggleMultiOption(q, opt, card));
        optionsWrap.appendChild(card);
      });

      if (selected.has(OTHER_LABEL)) {
        otherWrap.hidden = false;
        otherInput.value = otherText;
      }

      continueBtn.hidden = selected.size === 0;
      continueBtn.disabled = selected.has(OTHER_LABEL) && !otherInput.value.trim();
    } else {
      // ---- Radio mode: exactly one option applies ----
      const allOptions = q.options.includes(OTHER_LABEL) ? q.options : [...q.options, OTHER_LABEL];
      const matchedOption = allOptions.includes(existingAnswer) ? existingAnswer : (existingAnswer ? OTHER_LABEL : '');

      allOptions.forEach(opt => {
        const card = buildOptionCard(opt, opt === matchedOption, 'radio', opt === OTHER_LABEL);
        card.addEventListener('click', () => selectSingleOption(q, opt, card));
        optionsWrap.appendChild(card);
      });

      if (matchedOption === OTHER_LABEL) {
        otherWrap.hidden = false;
        otherInput.value = existingAnswer;
      }

      // Continue is only shown when landing on an already-answered question
      // (i.e. via Back / Edit) so the user can confirm without re-tapping.
      // A fresh tap always advances straight away — see selectSingleOption.
      continueBtn.hidden = !matchedOption;
      continueBtn.disabled = matchedOption === OTHER_LABEL && !existingAnswer.trim();
    }
  } else {
    freetextWrap.hidden = false;
    freetextInput.value = existingAnswer;
    continueBtn.hidden = false;
    continueBtn.disabled = !existingAnswer.trim();
    setTimeout(() => freetextInput.focus(), 50);
  }

  otherInput.oninput = () => {
    continueBtn.hidden = false;
    continueBtn.disabled = !otherInput.value.trim();
  };
  freetextInput.oninput = () => {
    continueBtn.disabled = !freetextInput.value.trim();
  };
}

// Builds one tappable choice card with a radio dot or checkbox indicator.
function buildOptionCard(label, isSelected, kind, isOther) {
  const card = el('button', {
    type: 'button',
    class: 'df-option' + (isSelected ? ' selected' : ''),
    role: kind,
    'aria-checked': isSelected ? 'true' : 'false',
  }, [
    el('span', { class: `df-option-indicator df-option-indicator-${kind}` }),
    el('span', { class: 'df-option-text' }, [
      el('span', { class: 'df-option-label', text: label }),
      ...(isOther ? [el('span', { class: 'df-option-hint', text: 'Write your own answer' })] : []),
    ]),
  ]);
  return card;
}

async function selectSingleOption(q, optionLabel, cardEl) {
  document.querySelectorAll('#df-options .df-option').forEach(c => {
    c.classList.remove('selected'); c.setAttribute('aria-checked', 'false');
  });
  cardEl.classList.add('selected');
  cardEl.setAttribute('aria-checked', 'true');

  const continueBtn = $('#df-btn-continue');
  const otherWrap = $('#df-other-wrap');
  const otherInput = $('#df-other-input');

  if (optionLabel === OTHER_LABEL) {
    otherWrap.hidden = false;
    otherInput.value = dfAnswers[q.id] && !q.options.includes(dfAnswers[q.id]) ? dfAnswers[q.id] : '';
    continueBtn.hidden = false;
    continueBtn.disabled = !otherInput.value.trim();
    otherInput.focus();
    return;
  }

  // A direct tap always advances on its own — no intermediate Continue flash.
  otherWrap.hidden = true;
  continueBtn.hidden = true;
  await saveAnswer(q.id, optionLabel);
  setTimeout(() => { if (dfAnswers[q.id] === optionLabel) goToNextQuestion(); }, 320);
}

function toggleMultiOption(q, optionLabel, cardEl) {
  const isSelected = cardEl.classList.toggle('selected');
  cardEl.setAttribute('aria-checked', isSelected ? 'true' : 'false');

  const otherWrap = $('#df-other-wrap');
  const otherInput = $('#df-other-input');
  const continueBtn = $('#df-btn-continue');

  if (optionLabel === OTHER_LABEL) {
    otherWrap.hidden = !isSelected;
    if (isSelected) otherInput.focus(); else otherInput.value = '';
  }

  const anySelected = document.querySelectorAll('#df-options .df-option.selected').length > 0;
  continueBtn.hidden = !anySelected;
  continueBtn.disabled = !otherWrap.hidden && !otherInput.value.trim();
}

async function saveAnswer(questionId, answerText) {
  answerText = (answerText || '').trim();
  if (!answerText) return;
  dfAnswers[questionId] = answerText;
  delete dfSkipped[questionId];
  updateDiscoveryStatus();
  onAnswersChanged();
  try {
    await api(`/api/project/${projectId}/answer`, { method: 'POST', body: JSON.stringify({ question_id: questionId, answer: answerText }) });
  } catch (e) {
    alert('Could not save answer: ' + e.message);
  }
}

async function skipCurrentQuestion() {
  const q = questions[dfIndex];
  delete dfAnswers[q.id];
  dfSkipped[q.id] = true;
  updateDiscoveryStatus();
  onAnswersChanged();
  try {
    await api(`/api/project/${projectId}/skip`, { method: 'POST', body: JSON.stringify({ question_id: q.id }) });
  } catch (e) {
    alert('Could not skip question: ' + e.message);
    return;
  }
  goToNextQuestion();
}

async function confirmCurrentAnswerAndAdvance() {
  const q = questions[dfIndex];
  if (q.options && q.options.length) {
    if (q.multi_select) {
      const selectedCards = [...document.querySelectorAll('#df-options .df-option.selected')];
      if (!selectedCards.length) return;
      const otherWrap = $('#df-other-wrap');
      const parts = [];
      selectedCards.forEach(card => {
        const label = card.querySelector('.df-option-label').textContent;
        if (label === OTHER_LABEL) {
          const val = $('#df-other-input').value.trim();
          if (val) parts.push(val);
        } else {
          parts.push(label);
        }
      });
      if (!parts.length) return;
      await saveAnswer(q.id, parts.join(' | '));
    } else {
      const otherWrap = $('#df-other-wrap');
      if (!otherWrap.hidden) {
        const val = $('#df-other-input').value.trim();
        if (!val) return;
        await saveAnswer(q.id, val);
      } else if (!dfAnswers[q.id]) {
        return; // nothing selected yet
      }
    }
  } else {
    const val = $('#df-freetext-input').value.trim();
    if (!val) return;
    await saveAnswer(q.id, val);
  }
  goToNextQuestion();
}

function goToNextQuestion() {
  if (dfReturnToReview) {
    dfReturnToReview = false;
    showDiscoveryReview();
    return;
  }
  if (dfIndex < questions.length - 1) {
    showDiscoveryQuestion(dfIndex + 1);
  } else {
    showDiscoveryReview();
  }
}

$('#df-btn-continue').addEventListener('click', confirmCurrentAnswerAndAdvance);
$('#df-freetext-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) confirmCurrentAnswerAndAdvance();
});
$('#df-other-input').addEventListener('keydown', e => { if (e.key === 'Enter') confirmCurrentAnswerAndAdvance(); });
$('#df-btn-back').addEventListener('click', () => {
  if (dfIndex > 0) showDiscoveryQuestion(dfIndex - 1);
});
$('#df-btn-to-review').addEventListener('click', () => {
  dfReturnToReview = false;
  showDiscoveryReview();
});
$('#df-btn-skip').addEventListener('click', skipCurrentQuestion);

// ---- Review / confirmation screen ----
function showDiscoveryReview() {
  setCollapsed('#panel-discovery', false);
  dfShowingReview = true;
  dfReturnToReview = false;
  $('#discovery-flow').hidden = true;
  $('#discovery-review').hidden = false;
  $('#reopen-note').hidden = !hasGeneratedBefore;
  updateDiscoveryStatus();
  renderReview();
  updateRunButton();
}

function renderReview() {
  const container = $('#df-review-groups');
  container.innerHTML = '';

  const seenCategories = [];
  const byCategory = {};
  questions.forEach(q => {
    if (!byCategory[q.category]) { byCategory[q.category] = []; seenCategories.push(q.category); }
    byCategory[q.category].push(q);
  });

  seenCategories.forEach(cat => {
    const section = el('div', { class: 'df-review-section' }, [
      el('div', { class: 'df-review-section-title', text: humanizeCategory(cat) }),
    ]);
    byCategory[cat].forEach(q => {
      const idx = questions.indexOf(q);
      const isSkipped = !!dfSkipped[q.id];
      const rawAnswer = dfAnswers[q.id] || (isSkipped ? (q.id === ADDITIONAL_INFO_ID ? 'Nothing added' : 'Skipped') : '(not answered)');
      const answer = rawAnswer.includes(' | ') ? rawAnswer.split(' | ').join(', ') : rawAnswer;
      const editBtn = el('button', { type: 'button', class: 'df-review-edit', text: isSkipped ? 'Answer' : 'Edit' });
      editBtn.addEventListener('click', () => editFromReview(idx));
      section.appendChild(el('div', { class: 'df-review-item' }, [
        el('div', { class: 'df-review-item-body' }, [
          el('p', { class: 'df-review-q', text: q.text }),
          el('p', { class: 'df-review-a' + (isSkipped ? ' df-review-a-skipped' : ''), text: answer }),
        ]),
        editBtn,
      ]));
    });
    container.appendChild(section);
  });

  const total = questions.length;
  const skipped = questions.filter(q => dfSkipped[q.id]).length;
  const answered = questions.filter(q => dfAnswers[q.id]).length;
  const open = total - answered - skipped;
  const stats = $('#review-stats');
  stats.innerHTML = '';
  [[`${total}`, 'questions', ''], [`${answered}`, 'answered', 'ok'], [`${skipped}`, 'skipped', skipped ? 'warn' : ''], [`${open}`, 'unanswered', open ? 'bad' : '']]
    .forEach(([n, l, c]) => stats.appendChild(el('span', { class: `rs-pill ${c}` }, [el('b', { text: n }), document.createTextNode(' ' + l)])));
  updateSummary(); updateStepper(); updatePanelSummaries();
}

$('#df-btn-review-back').addEventListener('click', () => showDiscoveryQuestion(questions.length - 1));

// ============================================================
// Run AI Agents — the button locks the moment it is clicked (no double runs) and only
// unlocks again if the agent process fails, so the person can retry.
// ============================================================
const RUN_LABELS = {
  idle: () => (hasGeneratedBefore ? 'Re-run AI Agents →' : 'Run AI Agents →'),
  running: () => 'Running AI Agents…',
  done: () => 'AI Agents completed ✓',
  error: () => 'Retry AI Agents →',
  paused: () => 'Continue anyway →',
  external: () => 'AI Agents running on the server…',
};
let pipelineRanThisSession = false;   // agent outputs exist in server memory -> resolve/export are possible

function updateRunButton() {
  const btn = $('#btn-run-agents');
  btn.textContent = RUN_LABELS[runState]();
  btn.disabled = runState === 'running' || runState === 'done' || runState === 'external';
  // while agents work, the answers must not change underneath them
  $('#discovery-review').classList.toggle('is-busy', runState === 'running' || runState === 'external');
  $('#df-btn-review-back').disabled = runState === 'running' || runState === 'external';
}

// Any change to an answer means the last package no longer matches -> allow a fresh run.
function onAnswersChanged() {
  nextAgentIndex = 0;
  if (runState === 'done' || runState === 'error' || runState === 'paused') runState = 'idle';
  updateRunButton();
}

function resetAgentPanel() {
  $('#agent-log').innerHTML = '';
  $('#qa-verdict').hidden = true;
  $('#feasibility-verdict').hidden = true;
  $('#agent-note').hidden = true;
  $('#btn-export').hidden = true;
  lastHandoffStatus = null;
  updateResolveButton();
}

$('#btn-run-agents').addEventListener('click', async () => {
  if (runState === 'running' || runState === 'external') return;   // hard guard against multi-click
  const allHandled = questions.every(q => dfAnswers[q.id] || dfSkipped[q.id]);
  if (!allHandled) { alert('A few questions still need an answer or a skip.'); return; }

  const wasPaused = runState === 'paused';   // captured before the state changes below
  runState = 'running';
  updateRunButton();                 // disabled synchronously, before any await
  let result = null;
  try {
    unlock('#panel-agents');
    if (!agentMeta.length) await loadAgentMeta();
    if (nextAgentIndex === 0) {
      resetAgentPanel();
      drawSchematic();
    } else if (wasPaused) {
      logLine(`▶ Continuing with ${agentMeta[nextAgentIndex].label}…`);
    } else {
      logLine(`↻ Retrying from ${agentMeta[nextAgentIndex].label}…`);
    }
    result = await runAgentPipeline(nextAgentIndex);
    if (result === true) hasGeneratedBefore = true;
    runState = result === true ? 'done' : result === 'paused' ? 'paused' : result === 'rerun' ? 'idle' : 'error';
    if (result === 'rerun') nextAgentIndex = 0;
  } catch (e) {
    logLine(`✗ Agent run failed: ${e.message}`);
    $('#agents-status').textContent = 'error';
    runState = 'error';
  }
  updateRunButton();
  updateResolveButton();   // the run has fully finished (incl. auto-resolution) — only now may Resolve show
  // The person edited answers in the feasibility popup and asked to re-run: start a fresh run now.
  if (result === 'rerun') setTimeout(() => $('#btn-run-agents').click(), 0);
});

// ============================================================
// SHEET 03 — Agent assembly (schematic)
// ============================================================
async function loadAgentMeta() {
  const data = await api(`/api/project/${projectId}/agents`);
  agentMeta = data.agents;
}

function nodeX(i) { return NODE_X_START + i * NODE_X_GAP; }

// Process-flow notation: nodes are joined by straight, single-direction, right-angle (horizontal)
// connectors with arrowheads.
function drawSchematic() {
  const svg = $('#schematic');
  svg.innerHTML = '';
  const ns = 'http://www.w3.org/2000/svg';

  const totalWidth = NODE_X_START * 2 + Math.max(0, agentMeta.length - 1) * NODE_X_GAP;
  svg.setAttribute('viewBox', `0 0 ${totalWidth} 160`);

  for (let i = 0; i < agentMeta.length - 1; i++) {
    const x1 = nodeX(i) + NODE_R, x2 = nodeX(i + 1) - NODE_R;
    const line = document.createElementNS(ns, 'line');
    line.setAttribute('x1', x1);
    line.setAttribute('y1', NODE_Y);
    line.setAttribute('x2', x2 - 9);
    line.setAttribute('y2', NODE_Y);
    line.setAttribute('class', 'trace-line');
    line.setAttribute('id', `trace-${i}`);
    svg.appendChild(line);

    const arrow = document.createElementNS(ns, 'polygon');
    arrow.setAttribute('points', `${x2},${NODE_Y} ${x2 - 10},${NODE_Y - 5} ${x2 - 10},${NODE_Y + 5}`);
    arrow.setAttribute('class', 'trace-arrow');
    arrow.setAttribute('id', `arrow-${i}`);
    svg.appendChild(arrow);
  }

  agentMeta.forEach((agent, i) => {
    const g = document.createElementNS(ns, 'g');
    const circle = document.createElementNS(ns, 'circle');
    circle.setAttribute('cx', nodeX(i)); circle.setAttribute('cy', NODE_Y); circle.setAttribute('r', NODE_R);
    circle.setAttribute('class', 'node-circle'); circle.setAttribute('id', `node-${i}`);
    g.appendChild(circle);

    const check = document.createElementNS(ns, 'text');
    check.setAttribute('x', nodeX(i)); check.setAttribute('y', NODE_Y + 6);
    check.setAttribute('text-anchor', 'middle'); check.setAttribute('class', 'node-check'); check.setAttribute('id', `check-${i}`);
    check.textContent = '✓';
    g.appendChild(check);

    const idx = document.createElementNS(ns, 'text');
    idx.setAttribute('x', nodeX(i)); idx.setAttribute('y', NODE_Y + 5);
    idx.setAttribute('text-anchor', 'middle'); idx.setAttribute('id', `idx-${i}`);
    idx.setAttribute('class', 'node-index');
    idx.textContent = `0${i + 1}`;
    g.appendChild(idx);

    const label1 = document.createElementNS(ns, 'text');
    label1.setAttribute('x', nodeX(i)); label1.setAttribute('y', NODE_Y + NODE_R + 22);
    label1.setAttribute('text-anchor', 'middle'); label1.setAttribute('class', 'node-label'); label1.setAttribute('id', `label-${i}`);
    label1.textContent = agent.label;
    g.appendChild(label1);

    const label2 = document.createElementNS(ns, 'text');
    label2.setAttribute('x', nodeX(i)); label2.setAttribute('y', NODE_Y + NODE_R + 36);
    label2.setAttribute('text-anchor', 'middle'); label2.setAttribute('class', 'node-label node-sublabel');
    label2.textContent = agent.note;
    g.appendChild(label2);

    svg.appendChild(g);
  });
}

function setNodeState(i, state) {
  const circle = $(`#node-${i}`), label = $(`#label-${i}`), check = $(`#check-${i}`), idx = $(`#idx-${i}`);
  if (!circle) return;
  circle.classList.remove('active', 'done', 'error'); label.classList.remove('active', 'done', 'error');
  if (state === 'active') {
    circle.classList.add('active'); label.classList.add('active');
  } else if (state === 'error') {
    circle.classList.add('error'); label.classList.add('error');
  } else if (state === 'done') {
    circle.classList.add('done'); label.classList.add('done'); check.classList.add('show');
    idx.style.display = 'none';
    const trace = $(`#trace-${i}`), arrow = $(`#arrow-${i}`);
    if (trace) trace.classList.add('charged');
    if (arrow) arrow.classList.add('charged');
  }
}

function logLine(text, done = false) {
  const log = $('#agent-log');
  log.appendChild(el('div', { text, class: done ? 'log-done' : '' }));
  log.scrollTop = log.scrollHeight;
}

// Returns true when all agents ran; false if one failed (the run button then re-enables to retry
// from the agent that failed, without redoing the ones that already succeeded).
async function runAgentPipeline(startIndex = 0) {
  $('#agents-status').textContent = 'running…';
  $('#btn-resolve-issues').hidden = true;

  for (let i = startIndex; i < agentMeta.length; i++) {
    // Before the BRD is drafted, put the still-open questions to the person (they are not listed in the BRD).
    if (agentMeta[i].role === 'business_analyst') {
      try {
        const r = await askClarifications();
        if (r === 'pause') {
          logLine('⏸ Paused before drafting the BRD — your clarifying questions are waiting. Click "Continue" to answer them.');
          $('#agents-status').textContent = 'paused';
          nextAgentIndex = i;
          return 'paused';
        }
        const res = clarLastResult || {};
        if (r === 'saved' || r === 'skipped') {
          const parts = [];
          if (res.answered) parts.push(`${res.answered} answered by you`);
          if (res.ai_chosen) parts.push(`${res.ai_chosen} chosen by the AI`);
          if (res.skipped) parts.push(`${res.skipped} left to planning defaults`);
          logLine(`✓ Clarifying questions settled (${parts.join(', ') || 'none'}) — written into the BRD; AI-chosen items are labelled "please confirm".`, true);
        }
      } catch (e) {
        logLine(`⚠ Could not load clarifying questions (${e.message}) — continuing with planning defaults.`);
      }
    }
    setNodeState(i, 'active');
    logLine(`⏳ ${agentMeta[i].label} reading project context…`);
    try {
      const data = await api(`/api/project/${projectId}/agent/${i}`, { method: 'POST' });
      setNodeState(i, 'done');
      logLine(`✓ ${agentMeta[i].label} — ${data.summary}`, true);
      // The validator's first verdict is NOT final: the automatic gap-correction rounds below usually change it.
      // Showing "NOT READY" now would announce a status the run is still working on — show a pending state instead
      // and the real status once validation has completely finished.
      if (agentMeta[i].role === 'ai_handoff_validation') { pendingQa = data; showQaPending(); }
      if (agentMeta[i].role === 'feasibility_assessment' && data.feasibility) {
        showFeasibility(data.feasibility);
        // An early check is only useful if it can stop wasted work: on a RETHINK verdict stop and let the person
        // resolve every serious flaw — fix it, or knowingly accept the risk. It never silently carries on while a
        // serious flaw is still undecided, and it cannot loop: an accepted flaw stays accepted until its answers change.
        const fz = data.feasibility;
        const open = (fz.rethink || {}).open || 0;
        if (fz.verdict === 'RETHINK' && startIndex === 0) {
          if (open > 0) {
            const choice = await openRethinkModal(fz, 'gate');
            if (choice === 'rerun') {
              logLine('↻ Answers updated — re-running the feasibility check…');
              return 'rerun';
            }
            if (choice === 'pause') {
              logLine('⏸ Paused after the feasibility check. Reopen "Rethink & resolve" from the red box when you are ready, or click Continue.');
              $('#agents-status').textContent = 'paused';
              nextAgentIndex = i + 1;
              return 'paused';
            }
            logLine('▶ Continuing — the risks you accepted are recorded in the BRD risk register.');
          } else {
            logLine(`ℹ Feasibility is still RETHINK, but you accepted all ${(fz.rethink || {}).accepted || 0} remaining risk(s). They are recorded in the BRD risk register — continuing.`);
          }
        }
      }
    } catch (e) {
      setNodeState(i, 'error');
      logLine(`✗ ${agentMeta[i].label} failed: ${e.message}`);
      $('#agents-status').textContent = 'error';
      nextAgentIndex = i;
      return false;
    }
  }
  nextAgentIndex = 0;
  pipelineRanThisSession = true;

  // The documents existing isn't the same as the package being complete — automatically
  // run a short chain of "resolve" passes (each its own quick request, so no single call
  // risks a host/proxy timeout) until validation comes back clean or a small round cap is
  // hit. This never requires the person to notice a gap and click anything.
  const finalQa = await autoResolveGaps(pendingQa);
  pendingQa = null;
  if (finalQa) showQaVerdict(finalQa);

  $('#agents-status').textContent = `complete — ${agentMeta.length}/${agentMeta.length}`;
  $('#btn-export').hidden = false;
  // Only now that auto-resolution has finished can the manual "Resolve issues" fallback appear.
  updateResolveButton();
  return true;
}

const MAX_AUTO_RESOLVE_ROUNDS = 4;

// Returns the LATEST validation result ({output, consistency_notes}) once the rounds are over, so the caller can
// show the handoff status a single time, when it is final — not after every intermediate round.
async function autoResolveGaps(initial) {
  let latest = initial || null;
  for (let round = 1; round <= MAX_AUTO_RESOLVE_ROUNDS; round++) {
    let data;
    try {
      data = await api(`/api/project/${projectId}/resolve`, { method: 'POST' });
    } catch (e) {
      logLine(`⚠ Auto-resolve round ${round} failed: ${e.message} — you can retry with "Resolve issues" below.`);
      return latest;
    }
    if (!data.resolved) {
      // Nothing left to fix (or nothing was flagged in the first place).
      return latest;
    }
    logLine(`↻ Auto-resolve round ${round}: fixed ${data.issues_addressed} issue(s) — re-ran: ${data.agents_rerun.join(', ')}`, true);
    latest = { output: data.validation_output, consistency_notes: data.consistency_notes };
    if (data.artefacts && data.artefacts.length) {
      unlock('#panel-artefacts');
      renderArtefacts(data.artefacts);
    }
    const status = data.validation_output && data.validation_output.final_handoff_status;
    const clean = status === 'READY FOR DESIGN AGENT'
      && !(data.validation_output.conflicts_found || []).length
      && !(data.validation_output.missing_information || []).length;
    if (clean) return latest;
  }
  logLine(`⚠ Reached the auto-resolve round limit (${MAX_AUTO_RESOLVE_ROUNDS}) with some items still flagged — review below, or click "Resolve issues" to try another round.`);
  return latest;
}

let lastFeasibility = null;

function showFeasibility(f) {
  lastFeasibility = f;
  setTimeout(() => { updateProjectHeader(); updateSummary(); }, 0);
  const box = $('#feasibility-verdict');
  const slug = f.verdict === 'GO' ? 'go' : f.verdict === 'RETHINK' ? 'rethink' : 'changes';
  box.hidden = false;
  box.className = `feas-verdict ${slug}`;
  const c = f.counts || {};
  const flaws = (f.headline_flaws || []).length
    ? '<ul>' + f.headline_flaws.map(x => `<li>${escapeHtml(x)}</li>`).join('') + '</ul>' : '';
  box.innerHTML = `<strong>FEASIBILITY: ${escapeHtml(f.verdict || 'n/a')}</strong>` +
    `<span class="feas-counts"> — ${c.critical || 0} critical · ${c.major || 0} major · ${c.minor || 0} minor flaw(s)</span>` +
    `<div class="feas-why">${escapeHtml(f.rationale || '')}</div>${flaws}` +
    `<div class="feas-foot">Full analysis (competitors, differentiators, flaws, recommended changes) is in the first document below once exported.</div>`;
  const rc = f.rethink || {};
  if ((rc.serious || 0) > 0) {
    const label = rc.open ? `↻ Rethink & resolve ${rc.open} flaw${rc.open === 1 ? '' : 's'}` : `✎ Review the ${rc.accepted} accepted risk${rc.accepted === 1 ? '' : 's'}`;
    const btn = el('button', { type: 'button', class: 'btn btn-ghost feas-actions', id: 'btn-feas-review', text: label });
    btn.addEventListener('click', () => {
      if (runState === 'running' || runState === 'external') { alert('Please wait until the agents have finished.'); return; }
      openRethinkModal(lastFeasibility, runState === 'paused' ? 'paused' : 'review').then(handleFeasChoice);
    });
    box.appendChild(btn);
  }
}

// What to do after the popup is used outside the pipeline (box button): re-run with the new answers, or continue.
function handleFeasChoice(choice) {
  if (choice === 'rerun' || choice === 'continue') {
    if (runState === 'running' || runState === 'external') return;
    $('#btn-run-agents').click();
  }
}

// ---- Rethink & resolve popup ---------------------------------------------------------------
// One card per serious feasibility flaw: why it matters, the recommended change, the AI's proposed answer for each
// answer behind it, and a choice — change the answer(s), or knowingly keep the plan and ACCEPT the risk.
// Resolves 'rerun' (answers changed -> re-check), 'continue' (everything decided, nothing changed) or 'pause'.
//   mode 'gate'   — opened automatically on a RETHINK verdict, mid-run
//   mode 'paused' — reopened after pausing
//   mode 'review' — opened from the red box later
let rtFlaws = [];
let rtDraft = {};            // question id -> new answer
let rtAccept = new Set();    // flaw keys the person is keeping
let rtResolve = null;
let rtReturnFocus = null;
const rtEditors = {};        // question id -> editor api

const rtDecided = (f) => rtAccept.has(f.key) || f.questions.some(q => q.id in rtDraft);

function updateRethinkFooter() {
  const open = rtFlaws.filter(f => !rtDecided(f));
  const changes = Object.keys(rtDraft).length;
  const apply = $('#rethink-apply');
  apply.disabled = open.length > 0;
  apply.textContent = open.length ? `Decide ${open.length} more to continue` : (changes ? `Apply ${changes} change${changes === 1 ? '' : 's'} & re-check →` : 'Continue with accepted risks →');
  $('#rethink-progress').textContent = `${rtFlaws.length - open.length} of ${rtFlaws.length} decided`;
  rtFlaws.forEach(f => {
    const card = document.getElementById(rtCardId(f.key));
    if (card) card.classList.toggle('decided', rtDecided(f));
  });
}
const rtCardId = (key) => 'rt-' + String(key).replace(/[^\w-]/g, '_');

function buildRethinkQuestion(f, q, firstTime) {
  const wrap = el('div', { class: 'rt-q' });
  wrap.appendChild(el('div', { class: 'fm-q', text: q.text }));
  wrap.appendChild(el('div', { class: 'fm-current', text: 'Current answer: ' + (q.current ? q.current.split(' | ').join(', ') : '(skipped)') }));
  if (!firstTime) {
    wrap.appendChild(el('div', { class: 'fm-shared', text: 'This answer is also behind an earlier problem on this list — change it there.' }));
    return wrap;
  }
  const sugBox = el('div', { class: 'clar-sug' });
  const ed = buildAnswerEditor(q, (v) => {
    if (v && v !== q.current) rtDraft[q.id] = v; else delete rtDraft[q.id];
    if (q.id in rtDraft) rtAccept.delete(f.key);
    renderRtSuggestion(q, sugBox); syncRtAccept(f); updateRethinkFooter();
  }, 'Type your answer…');
  rtEditors[q.id] = ed.api;
  if (q.suggestion) { wrap.appendChild(sugBox); renderRtSuggestion(q, sugBox); }
  wrap.appendChild(ed.el);
  return wrap;
}

function renderRtSuggestion(q, box) {
  box.innerHTML = '';
  rtEditors[q.id] && rtEditors[q.id].markSuggested(q.suggestion || '');
  box.appendChild(el('div', { class: 'clar-sug-main' }, [
    el('span', { class: 'clar-sug-tag', text: 'AI PROPOSES' }),
    el('span', { class: 'clar-sug-val', text: q.suggestion }),
  ]));
  if (q.reason) box.appendChild(el('div', { class: 'clar-sug-why', text: q.reason }));
  const use = el('button', { type: 'button', class: 'btn btn-ghost clar-sug-use', text: rtDraft[q.id] === q.suggestion ? '✓ Selected' : 'Use this' });
  use.addEventListener('click', () => rtEditors[q.id].setValue(q.suggestion));
  box.appendChild(use);
}

function syncRtAccept(f) {
  const cb = document.getElementById(rtCardId(f.key) + '-accept');
  if (cb) cb.checked = rtAccept.has(f.key);
}

function openRethinkModal(fz, mode) {
  return api(`/api/project/${projectId}/feasibility/rethink`).then(({ flaws }) => {
    rtFlaws = flaws || [];
    rtDraft = {}; rtAccept = new Set(rtFlaws.filter(f => f.accepted).map(f => f.key));
    Object.keys(rtEditors).forEach(k => delete rtEditors[k]);
    const slug = fz.verdict === 'GO' ? 'go' : fz.verdict === 'RETHINK' ? 'rethink' : 'changes';
    $('#rethink-kicker').className = 'modal-kicker ' + slug;
    $('#rethink-kicker').textContent = `Feasibility check · ${fz.verdict || ''}`;
    const n = rtFlaws.length;
    $('#rethink-title').textContent = n ? `Rethink & resolve — ${n} serious problem${n === 1 ? '' : 's'}` : 'No serious problems to resolve';
    $('#rethink-lead').textContent = 'For each problem, either change the answer(s) behind it — the AI has proposed a concrete change — or keep your plan and accept the risk. ' +
      'Accepted risks are recorded in the BRD risk register, and the same problem will not block you again unless the answers behind it change.';
    $('#rethink-accept-all').hidden = mode === 'review' && !rtFlaws.some(f => !f.accepted);

    const body = $('#rethink-body'); body.innerHTML = '';
    const shown = new Set();
    rtFlaws.forEach(f => {
      const card = el('div', { class: 'fm-item rt-flaw' }); card.id = rtCardId(f.key);
      card.appendChild(el('div', { class: 'fm-top' }, [
        el('span', { class: 'fm-sev ' + (f.severity === 'Critical' ? 'critical' : 'major'), text: (f.severity || '').toUpperCase() }),
        el('div', { class: 'fm-q', text: f.flaw }),
      ]));
      if (f.why) card.appendChild(el('div', { class: 'rt-why', text: f.why }));
      if (f.recommended) card.appendChild(el('div', { class: 'fm-suggest' }, [el('strong', { text: 'Recommended change: ' }), document.createTextNode(f.recommended)]));
      if ((f.ways_forward || []).length > 1) {
        const ul = el('ul', { class: 'rt-ways' });
        f.ways_forward.forEach(w => ul.appendChild(el('li', { text: w })));
        card.appendChild(el('div', { class: 'rt-ways-title', text: 'Ways forward' })); card.appendChild(ul);
      }
      if (!f.questions.length) {
        card.appendChild(el('div', { class: 'fm-shared', text: 'This is about the plan as a whole, not one answer. Either rework your idea/answers (use “Review all answers”), or accept the risk below.' }));
      }
      f.questions.forEach(q => { const first = !shown.has(q.id); shown.add(q.id); card.appendChild(buildRethinkQuestion(f, q, first)); });
      const lab = el('label', { class: 'rt-accept' });
      const cb = el('input', { type: 'checkbox' }); cb.id = rtCardId(f.key) + '-accept'; cb.checked = rtAccept.has(f.key);
      cb.addEventListener('change', () => {
        if (cb.checked) { rtAccept.add(f.key); f.questions.forEach(q => { delete rtDraft[q.id]; rtEditors[q.id] && rtEditors[q.id].setValue(''); }); }
        else rtAccept.delete(f.key);
        updateRethinkFooter();
      });
      lab.appendChild(cb); lab.appendChild(document.createTextNode(' Keep my plan — I understand and accept this risk'));
      card.appendChild(lab);
      body.appendChild(card);
    });
    updateRethinkFooter();
    rtReturnFocus = document.activeElement;
    $('#rethink-modal').hidden = false;
    document.body.classList.add('modal-open');
    body.scrollTop = 0;
    setTimeout(() => $('#rethink-close').focus(), 30);
    return new Promise(resolve => { rtResolve = resolve; });
  });
}

function closeRethinkModal(result) {
  $('#rethink-modal').hidden = true;
  document.body.classList.remove('modal-open');
  const resolve = rtResolve; rtResolve = null;
  if (rtReturnFocus && rtReturnFocus.focus) rtReturnFocus.focus();
  if (resolve) resolve(result);
}

async function submitRethink(acceptAll) {
  const btn = $('#rethink-apply'); btn.disabled = true;
  try {
    const accept = acceptAll ? rtFlaws.filter(f => !f.questions.some(q => q.id in rtDraft)).map(f => f.key) : [...rtAccept];
    const reopen = rtFlaws.filter(f => f.accepted && !accept.includes(f.key)).map(f => f.key);
    const data = await api(`/api/project/${projectId}/feasibility/rethink`, { method: 'POST', body: JSON.stringify({ changes: rtDraft, accept, reopen }) });
    mirrorQuestions(data.questions);
    if (lastFeasibility) { lastFeasibility.rethink = data.counts; showFeasibility(lastFeasibility); }
    closeRethinkModal(data.changed > 0 ? 'rerun' : 'continue');
  } catch (e) {
    alert('Could not save: ' + e.message);
    updateRethinkFooter();
  }
}

$('#rethink-close').addEventListener('click', () => closeRethinkModal('pause'));
$('#rethink-apply').addEventListener('click', () => submitRethink(false));
$('#rethink-accept-all').addEventListener('click', () => submitRethink(true));
$('#rethink-use-all').addEventListener('click', () => {
  rtFlaws.forEach(f => f.questions.forEach(q => { if (q.suggestion && rtEditors[q.id]) rtEditors[q.id].setValue(q.suggestion); }));
});
$('#rethink-review-all').addEventListener('click', () => {
  closeRethinkModal('pause');
  const review = $('#discovery-review');
  if (review) review.scrollIntoView({ behavior: 'smooth', block: 'start' });
});
$('#rethink-modal').addEventListener('mousedown', e => { if (e.target.id === 'rethink-modal') closeRethinkModal('pause'); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('#rethink-modal').hidden) closeRethinkModal('pause'); });

// ---- Clarifying questions popup ------------------------------------------------------------
// Asked after the feasibility check and BEFORE the Business Analyst writes the BRD. What used to be an
// "Open Questions" list inside the document is put to the person here; their answers go into the BRD.
// Resolves 'saved' (answers stored), 'skipped' (planning defaults used) or 'pause' (closed without choosing).
let clarDraft = {};
let clarResolve = null;
let clarReturnFocus = null;

const clarBoxId = (id) => 'clar-sug-' + String(id).replace(/[^\w-]/g, '_');
const clarEditors = {};   // item id -> { setValue(v), markSuggested(v) }
let clarSugg = {};        // item id -> { suggestion, reason }
let clarTimer = null;

// Option cards / free text for one question. onChange(value) gets the chosen answer ('' when cleared).
// Returns { el, api: { setValue, markSuggested } } — used by the clarifying-questions and the rethink popups.
function buildAnswerEditor(item, onChange, placeholder) {
  const wrap = el('div', { class: 'fm-edit' });
  const set = (v) => onChange((v || '').trim());
  if (!(item.options && item.options.length)) {
    const ta = el('textarea', { class: 'fm-edit-input', rows: '2', placeholder });
    ta.addEventListener('input', () => set(ta.value));
    wrap.appendChild(ta);
    return { el: wrap, api: { setValue: (v) => { ta.value = v; set(v); }, markSuggested: () => {} } };
  }
  const multi = !!item.multi_select;
  const allOptions = item.options.includes(OTHER_LABEL) ? item.options : [...item.options, OTHER_LABEL];
  const selected = new Set();
  const list = el('div', { class: 'df-options fm-options', role: multi ? 'group' : 'radiogroup' });
  const otherInput = el('input', { type: 'text', class: 'fm-edit-input', placeholder: 'Type your own answer…' });
  otherInput.hidden = true;
  const cards = new Map();
  const paint = () => {
    cards.forEach((cc, o) => { const on = selected.has(o); cc.classList.toggle('selected', on); cc.setAttribute('aria-checked', on ? 'true' : 'false'); });
    otherInput.hidden = !selected.has(OTHER_LABEL);
  };
  const compute = () => {
    const out = [];
    allOptions.forEach(opt => {
      if (!selected.has(opt)) return;
      if (opt === OTHER_LABEL) { if (otherInput.value.trim()) out.push(otherInput.value.trim()); } else out.push(opt);
    });
    set(out.join(' | '));
  };
  allOptions.forEach(opt => {
    const c = buildOptionCard(opt, false, multi ? 'checkbox' : 'radio', opt === OTHER_LABEL);
    cards.set(opt, c);
    c.addEventListener('click', () => {
      if (multi) { if (selected.has(opt)) selected.delete(opt); else selected.add(opt); }
      else { selected.clear(); selected.add(opt); }
      paint();
      if (!otherInput.hidden) otherInput.focus();
      compute();
    });
    list.appendChild(c);
  });
  otherInput.addEventListener('input', compute);
  wrap.appendChild(list); wrap.appendChild(otherInput);
  return { el: wrap, api: {
    setValue: (v) => {
      selected.clear(); otherInput.value = '';
      String(v || '').split('|').map(x => x.trim()).filter(Boolean).forEach(part => {
        if (cards.has(part)) selected.add(part); else { selected.add(OTHER_LABEL); otherInput.value = part; }
      });
      paint(); compute();
    },
    markSuggested: (v) => {
      const parts = String(v || '').split('|').map(x => x.trim());
      cards.forEach((cc, o) => cc.classList.toggle('suggested', parts.includes(o)));
    },
  } };
}

function buildClarEditor(item) {
  const ed = buildAnswerEditor(item, (v) => { if (v) clarDraft[item.id] = v; else delete clarDraft[item.id]; scheduleClarRefresh(); },
                               'Type your answer… (leave empty and the AI suggestion above is used)');
  clarEditors[item.id] = ed.api;
  return ed.el;
}

// Mirror what the server wrote onto the discovery questions, without marking the answers as "edited since the run".
function mirrorQuestions(serverQuestions) {
  (serverQuestions || []).forEach(sq => {
    const local = questions.find(x => x.id === sq.id);
    if (local) { local.answer = sq.answer; local.status = sq.status; }
    if (sq.answer) { dfAnswers[sq.id] = sq.answer; delete dfSkipped[sq.id]; }
  });
  updateDiscoveryStatus();
}

// The "AI suggests …" line under each question; "Use this" fills the answer with it.
function renderClarSuggestion(item) {
  const box = document.getElementById(clarBoxId(item.id));
  const sug = clarSugg[item.id];
  if (!box) return;
  box.innerHTML = '';
  clarEditors[item.id] && clarEditors[item.id].markSuggested(sug ? sug.suggestion : '');
  if (!sug) { box.hidden = true; return; }
  box.hidden = false;
  box.appendChild(el('div', { class: 'clar-sug-main' }, [
    el('span', { class: 'clar-sug-tag', text: 'AI SUGGESTS' }),
    el('span', { class: 'clar-sug-val', text: sug.suggestion }),
  ]));
  if (sug.reason) box.appendChild(el('div', { class: 'clar-sug-why', text: sug.reason }));
  const use = el('button', { type: 'button', class: 'btn btn-ghost clar-sug-use', text: clarDraft[item.id] === sug.suggestion ? '✓ Selected' : 'Use this' });
  use.addEventListener('click', () => { clarEditors[item.id].setValue(sug.suggestion); renderClarSuggestion(item); });
  box.appendChild(use);
}

let clarItems = [];
// When the person changes an answer, recommendations that depend on it are recalculated (debounced).
function scheduleClarRefresh() {
  clearTimeout(clarTimer);
  clarTimer = setTimeout(async () => {
    if ($('#clar-modal').hidden) return;
    try {
      const data = await api(`/api/project/${projectId}/clarifications/suggest`, { method: 'POST', body: JSON.stringify({ draft: clarDraft }) });
      clarSugg = data.suggestions || {};
      clarItems.forEach(renderClarSuggestion);
    } catch (e) { /* suggestions are advisory — keep the current ones */ }
  }, 600);
}

function openClarifyModal(items, suggestions) {
  clarDraft = {}; clarSugg = suggestions || {}; clarItems = items;
  Object.keys(clarEditors).forEach(k => delete clarEditors[k]);
  $('#clar-modal-lead').textContent = `${items.length} item${items.length === 1 ? '' : 's'} could not be settled from your answers, so the AI has recommended the best choice for each, ` +
    'based on everything else you told us. Use a suggestion, pick your own, or leave an item alone — anything left unanswered gets the suggested value, ' +
    'clearly labelled in the BRD as "Recommended by AI — please confirm". Suggestions update as you change other answers.';
  const body = $('#clar-modal-body');
  body.innerHTML = '';
  items.forEach(it => {
    const card = el('div', { class: 'fm-item' });
    card.appendChild(el('div', { class: 'fm-top' }, [
      el('span', { class: 'fm-sev major', text: it.kind === 'parameter' ? 'DECISION' : 'QUESTION' }),
      el('div', { class: 'fm-q', text: it.text }),
    ]));
    if (it.hint) card.appendChild(el('div', { class: 'fm-current', text: it.kind === 'parameter' ? 'Currently: ' + it.hint : it.hint }));
    const sugBox = el('div', { class: 'clar-sug' });
    sugBox.id = clarBoxId(it.id);
    card.appendChild(sugBox);
    card.appendChild(buildClarEditor(it));
    body.appendChild(card);
  });
  items.forEach(renderClarSuggestion);
  clarReturnFocus = document.activeElement;
  $('#clar-modal').hidden = false;
  document.body.classList.add('modal-open');
  body.scrollTop = 0;
  setTimeout(() => { const f = body.querySelector('button, input, textarea') || $('#clar-modal-close'); f.focus(); }, 30);
  return new Promise(resolve => { clarResolve = resolve; });
}

function closeClarModal(result) {
  $('#clar-modal').hidden = true;
  document.body.classList.remove('modal-open');
  const resolve = clarResolve; clarResolve = null;
  if (clarReturnFocus && clarReturnFocus.focus) clarReturnFocus.focus();
  if (resolve) resolve(result);
}

async function submitClarifications(items, useDraft) {
  // An empty answer tells the server to use the AI's recommendation for that item.
  const answers = items.map(it => ({ id: it.id, answer: useDraft ? (clarDraft[it.id] || '') : '' }));
  const data = await api(`/api/project/${projectId}/clarifications`, { method: 'POST', body: JSON.stringify({ answers }) });
  mirrorQuestions(data.questions);
  clarLastResult = data;
  return data;
}
let clarLastResult = null;

// Returns 'none' (nothing to ask), 'saved', 'skipped' or 'pause'.
async function askClarifications() {
  const { questions: items, suggestions } = await api(`/api/project/${projectId}/clarifications`);
  if (!items || !items.length) return 'none';
  const choice = await openClarifyModal(items, suggestions);
  if (choice === 'pause') return 'pause';
  await submitClarifications(items, choice === 'saved');
  return choice;
}

$('#clar-modal-close').addEventListener('click', () => closeClarModal('pause'));
$('#clar-modal-skip').addEventListener('click', () => closeClarModal('skipped'));
$('#clar-modal-save').addEventListener('click', () => closeClarModal('saved'));
$('#clar-modal').addEventListener('mousedown', e => { if (e.target.id === 'clar-modal') closeClarModal('pause'); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('#clar-modal').hidden) closeClarModal('pause'); });

let pendingQa = null;   // the validator's first result, held back until the auto-resolve rounds have finished

// Neutral placeholder while the handoff validation (and its automatic gap fixing) is still running.
function showQaPending() {
  lastHandoffStatus = null;
  const box = $('#qa-verdict');
  box.hidden = false;
  box.className = 'qa-verdict status-pending';
  box.innerHTML = 'HANDOFF STATUS: VALIDATING…' +
    '<div class="qa-pending-note">Checking the package and fixing any gaps automatically. The final status appears here when validation is complete.</div>';
  updateResolveButton();
}

function showQaVerdict(data) {
  const status = (data.output && data.output.final_handoff_status) || 'unknown';
  lastHandoffStatus = status;
  lastNotesCount = (data.consistency_notes || []).length;
  const box = $('#qa-verdict');
  box.hidden = false;
  box.className = `qa-verdict ${statusSlug(status)}`;

  const notes = data.consistency_notes || [];
  const notesHtml = notes.length ? '<ul>' + notes.map(n => `<li>${escapeHtml(n)}</li>`).join('') + '</ul>' : '';
  box.innerHTML = `HANDOFF STATUS: ${escapeHtml(status)}` + notesHtml;
  // NOTE: deliberately does not touch the Resolve button — see updateResolveButton().
  updateProjectHeader(); updateStepper(); updateSummary();
}

// "Resolve issues" is a manual fallback, offered ONLY once the automatic resolution has finished
// (never while the agents or the auto-resolve rounds are still running) and only if issues remain.
function updateResolveButton() {
  const stillIssues = !!lastHandoffStatus && lastHandoffStatus !== 'READY FOR DESIGN AGENT';
  $('#btn-resolve-issues').hidden = !(pipelineRanThisSession && stillIssues && runState !== 'running');
}

// ============================================================
// SHEET 04 — Artefacts (6-document package)
// ============================================================
let currentArtefacts = [];
let activeArtefactIndex = 0;

$('#btn-export').addEventListener('click', async () => {
  unlock('#panel-artefacts');
  const btn = $('#btn-export');
  btn.disabled = true; btn.textContent = 'Exporting…';
  try {
    const data = await api(`/api/project/${projectId}/export`, { method: 'POST' });
    renderArtefacts(data.artefacts);
  } catch (e) {
    alert('Export failed: ' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = 'Export 6-document package →';
  }
});


// ---- Send user stories to Jira / Azure DevOps ---------------------------------------------------
// The token is read from the field for each request and never stored; non-secret fields are remembered in this browser.
const BL_FIELDS = { jira: ['base_url', 'email', 'token', 'project'], ado: ['base_url', 'project', 'token'] };
let blTarget = 'jira';
let blBusy = false;
let blDefaults = null;

const blField = (t, k) => document.getElementById(`bl-${t}-${k}`);
function blCreds() {
  const c = {};
  BL_FIELDS[blTarget].forEach(k => { c[k] = (blField(blTarget, k).value || '').trim(); });
  return c;
}
function blRemember() {
  const saved = JSON.parse(localStorage.getItem('backlogFields') || '{}');
  Object.keys(BL_FIELDS).forEach(t => { saved[t] = saved[t] || {}; BL_FIELDS[t].filter(k => k !== 'token').forEach(k => { saved[t][k] = blField(t, k).value.trim(); }); });
  localStorage.setItem('backlogFields', JSON.stringify(saved));   // never the token
}
function blSetTarget(t) {
  blTarget = t;
  document.querySelectorAll('.bl-tab').forEach(b => { const on = b.dataset.target === t; b.classList.toggle('active', on); b.setAttribute('aria-selected', on ? 'true' : 'false'); });
  $('#bl-fields-jira').hidden = t !== 'jira';
  $('#bl-fields-ado').hidden = t !== 'ado';
  $('#bl-test-result').textContent = ''; $('#bl-result').hidden = true; $('#bl-progress').hidden = true;
  blRefreshPreview();
}
function blPlaceholderToken() {
  Object.keys(BL_FIELDS).forEach(t => {
    const has = blDefaults && blDefaults[t] && blDefaults[t].token_configured;
    blField(t, 'token').placeholder = has ? 'Using the token saved on the server — leave blank' : '';
  });
}
async function blRefreshPreview() {
  const box = $('#bl-preview'); box.textContent = '';
  try {
    const p = await api(`/api/project/${projectId}/integrations/${blTarget}/preview`, { method: 'POST', body: JSON.stringify({ creds: blCreds() }) });
    box.appendChild(el('div', { class: 'bl-count', text: `${p.epics} epics + ${p.stories} user stories ready · ${p.by_priority.High} High, ${p.by_priority.Medium} Medium, ${p.by_priority.Low} Low priority · ${p.dependencies} dependency links` }));
    if (p.already_pushed) box.appendChild(el('div', { class: 'bl-note', text: `${p.already_pushed} items were already sent to this project — they will be skipped, not duplicated.` }));
  } catch (e) { box.appendChild(el('div', { class: 'bl-note', text: e.message })); }
}
async function openBacklogModal() {
  if (!blDefaults) { try { blDefaults = await api('/api/integrations/config'); } catch (e) { blDefaults = {}; } }
  const saved = JSON.parse(localStorage.getItem('backlogFields') || '{}');
  Object.keys(BL_FIELDS).forEach(t => BL_FIELDS[t].filter(k => k !== 'token').forEach(k => {
    blField(t, k).value = (saved[t] && saved[t][k]) || (blDefaults[t] && blDefaults[t][k]) || '';
  }));
  blPlaceholderToken();
  $('#bl-result').hidden = true; $('#bl-progress').hidden = true; $('#bl-test-result').textContent = '';
  blField('jira', 'token').value = ''; blField('ado', 'token').value = '';
  $('#backlog-modal').hidden = false; document.body.classList.add('modal-open');
  blSetTarget(blTarget);
  setTimeout(() => $('.bl-tab.active').focus(), 30);
}
function closeBacklogModal() {
  if (blBusy) return;
  $('#backlog-modal').hidden = true; document.body.classList.remove('modal-open');
  blField('jira', 'token').value = ''; blField('ado', 'token').value = '';
}
function blShowResult(r) {
  const box = $('#bl-result'); box.hidden = false; box.innerHTML = '';
  const parts = [`${r.created} created`, `${r.updated} updated`, `${r.unchanged} already there`, `${r.dependency_links} dependency links`];
  box.appendChild(el('div', { class: 'bl-ok', text: `✓ Done in ${r.seconds}s — ${parts.join(' · ')}` }));
  (r.warnings || []).forEach(w => box.appendChild(el('div', { class: 'bl-note', text: 'ℹ ' + w })));
  if (r.failed.length) {
    box.appendChild(el('div', { class: 'bl-fail', text: `${r.failed.length} item(s) could not be sent — fix the cause and click Send again; the rest will not be duplicated:` }));
    r.failed.slice(0, 8).forEach(f => box.appendChild(el('div', { class: 'bl-fail-item', text: `${f.title}: ${f.error}` })));
  }
  const links = r.items.filter(i => i.url && i.status !== 'unchanged').slice(0, 12);
  if (links.length) {
    const ul = el('ul', { class: 'bl-links' });
    links.forEach(i => { const a = el('a', { href: i.url, target: '_blank', rel: 'noopener noreferrer', text: `${i.key} — ${i.title}` }); ul.appendChild(el('li', {}, [a])); });
    box.appendChild(ul);
    if (r.items.length > links.length) box.appendChild(el('div', { class: 'bl-note', text: `…and ${r.items.length - links.length} more in your backlog.` }));
  }
}
async function blPush() {
  if (blBusy) return;
  blBusy = true; const btn = $('#bl-push'); btn.disabled = true; btn.textContent = 'Sending…';
  $('#bl-result').hidden = true; $('#bl-progress').hidden = false; $('#bl-bar-fill').style.width = '4%'; $('#bl-progress-text').textContent = 'Connecting…';
  blRemember();
  try {
    const { push_id } = await api(`/api/project/${projectId}/integrations/${blTarget}/push`, { method: 'POST', body: JSON.stringify({ creds: blCreds(), options: { update_existing: $('#bl-update').checked } }) });
    for (;;) {
      await new Promise(r => setTimeout(r, 700));
      const st = await api(`/api/project/${projectId}/integrations/push/${push_id}`);
      $('#bl-progress-text').textContent = st.progress || '';
      const m = /(\d+)\/(\d+)/.exec(st.progress || ''); if (m) $('#bl-bar-fill').style.width = Math.max(4, Math.round(100 * m[1] / m[2])) + '%';
      if (st.status === 'done') { $('#bl-bar-fill').style.width = '100%'; blShowResult(st.result); break; }
      if (st.status === 'error') { $('#bl-result').hidden = false; $('#bl-result').innerHTML = ''; $('#bl-result').appendChild(el('div', { class: 'bl-fail', text: '✗ ' + st.error })); break; }
    }
  } catch (e) {
    $('#bl-result').hidden = false; $('#bl-result').innerHTML = ''; $('#bl-result').appendChild(el('div', { class: 'bl-fail', text: '✗ ' + e.message }));
  } finally {
    blBusy = false; btn.disabled = false; btn.textContent = 'Send to backlog →';
    blField('jira', 'token').value = ''; blField('ado', 'token').value = '';   // never keep it around
    blRefreshPreview();
  }
}
$('#btn-backlog').addEventListener('click', openBacklogModal);
$('#backlog-close').addEventListener('click', closeBacklogModal);
$('#bl-cancel').addEventListener('click', closeBacklogModal);
$('#bl-push').addEventListener('click', blPush);
$('#bl-update').addEventListener('change', () => {});
document.querySelectorAll('.bl-tab').forEach(b => b.addEventListener('click', () => blSetTarget(b.dataset.target)));
$('#bl-test').addEventListener('click', async () => {
  const out = $('#bl-test-result'); out.className = 'bl-status'; out.textContent = 'Checking…';
  try {
    const r = await api(`/api/project/${projectId}/integrations/${blTarget}/check`, { method: 'POST', body: JSON.stringify({ creds: blCreds() }) });
    out.className = 'bl-status ok';
    out.textContent = `✓ Connected${r.user ? ' as ' + r.user : ''} · project “${r.project}” · epics: ${r.epic_type || 'none'} · stories: ${r.story_type}${r.process ? ' (' + r.process + ' process)' : ''}`;
    (r.warnings || []).forEach(w => { out.textContent += ' · ℹ ' + w; });
    blRemember();
  } catch (e) { out.className = 'bl-status bad'; out.textContent = '✗ ' + e.message; }
});
$('#backlog-modal').addEventListener('mousedown', e => { if (e.target.id === 'backlog-modal') closeBacklogModal(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('#backlog-modal').hidden) closeBacklogModal(); });

$('#btn-resolve-issues').addEventListener('click', async () => {
  const btn = $('#btn-resolve-issues');
  btn.disabled = true; btn.textContent = 'Resolving…';
  try {
    const data = await api(`/api/project/${projectId}/resolve`, { method: 'POST' });
    if (!data.resolved) {
      alert(data.reason || 'Nothing to resolve.');
      return;
    }
    logLine(`↻ Resolved ${data.issues_addressed} issue(s) — re-ran: ${data.agents_rerun.join(', ')}`, true);
    showQaVerdict({ output: data.validation_output, consistency_notes: data.consistency_notes });
    if (data.agents) {
      data.agents.forEach((a, i) => { if (agentMeta[i]) logLine(`✓ ${agentMeta[i].label} — ${a.summary}`); });
    }
    if (data.artefacts && data.artefacts.length) {
      unlock('#panel-artefacts');
      renderArtefacts(data.artefacts);
    }
  } catch (e) {
    alert('Could not resolve issues: ' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = '⚙ Resolve issues →';
    updateResolveButton();
  }
});

function renderArtefacts(artefacts) {
  currentArtefacts = artefacts;
  activeArtefactIndex = 0;

  const tabs = $('#artefact-tabs');
  tabs.innerHTML = '';
  tabs.hidden = false;
  $('#artefact-controls').hidden = false;
  $('#doc-frame').hidden = false;

  artefacts.forEach((a, i) => {
    const tab = el('button', { type: 'button', role: 'tab', 'aria-selected': String(i === 0), class: 'tab-btn' + (i === 0 ? ' active' : ''), text: a.title.split('—')[0].trim() || a.type });
    tab.addEventListener('click', () => {
      activeArtefactIndex = i;
      document.querySelectorAll('#artefact-tabs .tab-btn').forEach(t => { t.classList.remove('active'); t.setAttribute('aria-selected', 'false'); });
      tab.classList.add('active'); tab.setAttribute('aria-selected', 'true');
      $('#doc-head-title').textContent = a.title || a.type;
      closeDlMenus();
      renderDoc(a.content_markdown);
    });
    tabs.appendChild(tab);
  });

  if (artefacts.length) { $('#doc-head-title').textContent = artefacts[0].title || artefacts[0].type; renderDoc(artefacts[0].content_markdown); }
  updateStepper(); updateSummary();
}

// Heading anchors so the table of contents and cross-reference links work inside the viewer.
// slugify() / the "-1, -2" duplicate rule must match _slug() / _headings() in src/export.py
// and the bookmark logic in export.js.
function slugify(text) {
  return String(text || '').replace(/[*`]/g, '').trim().toLowerCase().replace(/[^\p{L}\p{N}_\- ]/gu, '').replace(/ /g, '-');
}
function assignHeadingIds(viewer) {
  const seen = {};
  viewer.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach((h) => {
    const base = slugify(h.textContent);
    const n = seen[base] || 0;
    seen[base] = n + 1;
    h.id = n ? `${base}-${n}` : base;
  });
}
(function wireDocAnchors() {
  const viewer = document.getElementById('doc-viewer');
  if (!viewer) return;
  viewer.addEventListener('click', (e) => {
    const a = e.target.closest && e.target.closest('a[href^="#"]');
    if (!a) return;
    const target = viewer.querySelector('[id="' + decodeURIComponent(a.getAttribute('href').slice(1)).replace(/"/g, '') + '"]');
    if (!target) return;
    e.preventDefault();                       // keep the app's own #project=... hash intact
    target.scrollIntoView({ block: 'start', behavior: 'smooth' });
  });
})();

function renderDoc(markdown) {
  const viewer = $('#doc-viewer');
  viewer.innerHTML = window.marked ? marked.parse(markdown, { breaks: true, gfm: true }) : markdown;
  wrapTables(viewer);
  assignHeadingIds(viewer);
  renderMermaidBlocks(viewer);
  // Switching artifacts replaces this element's content but not the
  // element itself, so the browser keeps whatever scroll position was
  // left over from the PREVIOUS document — on a shorter new document
  // that can even leave the viewer scrolled past its own content.
  // Always land at the top of the newly-selected document.
  viewer.scrollTop = 0;
}

// ---- Downloads: Word (.docx) is the primary format; Markdown stays available -------------
// Runs an async export while showing progress on the button, and reports failures.
async function withBusyButton(btn, busyText, task) {
  const original = btn.innerHTML;
  btn.disabled = true; btn.textContent = busyText;
  try { await task((msg) => { btn.textContent = msg; }); }
  catch (e) { console.error(e); alert('Download failed: ' + (e && e.message ? e.message : e)); }
  finally { btn.disabled = false; btn.innerHTML = original; }
}

// ---- Download dropdown menus (per-document in the document header, "all" beside the tabs) ----
function closeDlMenus(except) {
  document.querySelectorAll('.dl-menu').forEach(m => {
    if (m === except) return;
    m.classList.remove('open');
    m.querySelector('.dl-pop').hidden = true;
    m.querySelector('.dl-trigger').setAttribute('aria-expanded', 'false');
  });
}
document.querySelectorAll('.dl-menu').forEach(menu => {
  const trigger = menu.querySelector('.dl-trigger'), pop = menu.querySelector('.dl-pop');
  trigger.addEventListener('click', (e) => {
    e.stopPropagation();
    const open = pop.hidden;
    closeDlMenus(menu);
    pop.hidden = !open; menu.classList.toggle('open', open);
    trigger.setAttribute('aria-expanded', String(open));
    if (open) { const first = pop.querySelector('.dl-item'); if (first && e.detail === 0) first.focus(); }
  });
  pop.addEventListener('click', (e) => e.stopPropagation());
});
document.addEventListener('click', () => closeDlMenus());
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDlMenus(); });

$('#btn-download-current').addEventListener('click', () => {
  const a = currentArtefacts[activeArtefactIndex];
  if (!a) return;
  closeDlMenus();
  withBusyButton($('#btn-download-current-menu'), 'Preparing Word file…', (progress) =>
    downloadDocx(`${a.type}.docx`, a.content_markdown, { title: a.title || a.type, onProgress: progress }));
});

$('#btn-download-current-md').addEventListener('click', () => {
  const a = currentArtefacts[activeArtefactIndex];
  closeDlMenus();
  if (a) downloadMarkdown(`${a.type}.md`, a.content_markdown);
});

// "Download all" -> ONE .zip containing every document (no repeated browser download prompts).
function packageStamp() { return projectId ? projectId.slice(0, 8) : 'package'; }

$('#btn-download-all').addEventListener('click', () => {
  if (!currentArtefacts.length) return;
  closeDlMenus();
  withBusyButton($('#btn-download-all-menu'), 'Preparing Word files…', (progress) =>
    downloadAllDocxZip(currentArtefacts, `specification-package-${packageStamp()}-word.zip`, progress));
});

$('#btn-download-all-md').addEventListener('click', () => {
  if (!currentArtefacts.length) return;
  closeDlMenus();
  withBusyButton($('#btn-download-all-menu'), 'Zipping…', () =>
    downloadAllMarkdownZip(currentArtefacts, `specification-package-${packageStamp()}-markdown.zip`));
});

// ============================================================
// Resume / reopen — restores the WHOLE process for a saved project: the idea, every question
// with its answer (editable), the agent run, and the generated documents.
// ============================================================
async function resumeProject(id) {
  let data;
  try {
    data = await api(`/api/project/${id}/session`);
  } catch (e) {
    alert('Could not open this project: ' + e.message);
    history.replaceState(null, '', location.pathname);
    location.reload();
    return;
  }
  projectId = data.project_id;
  questions = data.questions || [];
  dfAnswers = {}; dfSkipped = {};
  questions.forEach(q => {
    if (q.status === 'answered' && q.answer) dfAnswers[q.id] = q.answer;
    else if (q.status === 'skipped') dfSkipped[q.id] = true;
  });
  const conf = data.confidence != null ? ` (${Math.round(data.confidence * 100)}%)` : '';
  setTitleBlock({ projectId, domain: data.domain ? data.domain + conf : null });
  if (data.created_at && !isNaN(Date.parse(data.created_at))) $('#tb-date').textContent = new Date(data.created_at).toISOString().slice(0, 10);
  refreshDomainCount();
  $('#idea-input').value = data.business_idea || '';
  lockIntake();

  const artefacts = data.artefacts || [];
  hasGeneratedBefore = artefacts.length > 0;
  pipelineRanThisSession = false;
  if (data.agents_running) runState = 'external';

  if (questions.length) {
    unlock('#panel-discovery');
    const firstOpen = questions.findIndex(q => !dfAnswers[q.id] && !dfSkipped[q.id]);
    if (firstOpen >= 0 && !hasGeneratedBefore) showDiscoveryQuestion(firstOpen);   // carry on where they stopped
    else showDiscoveryReview();
  } else if (hasGeneratedBefore) {
    logLine('ℹ This project was saved before questions and answers were recorded, so only its documents can be shown.');
  }

  if (hasGeneratedBefore) await restoreGeneratedView(data, artefacts);
  if (data.agents_running) {
    unlock('#panel-agents');
    const note = $('#agent-note');
    note.textContent = 'The AI agents are still working on this project on the server. Reopen it in a few minutes to see the result.';
    note.hidden = false;
  }
  updateRunButton();
}

async function restoreGeneratedView(data, artefacts) {
  unlock('#panel-agents');
  await loadAgentMeta();
  drawSchematic();
  const log = data.agent_log || [];
  const finished = new Set(log.map(a => a.agent));
  agentMeta.forEach((m, i) => { if (finished.has(m.role) || !log.length) setNodeState(i, 'done'); });
  log.forEach(a => logLine(`✓ ${a.label || a.agent} — ${a.summary}`, true));
  if (!log.length) logLine('✓ Package generated in an earlier session.', true);
  $('#agents-status').textContent = `complete — ${log.length || agentMeta.length}/${agentMeta.length}`;
  if (data.feasibility) showFeasibility(data.feasibility);
  if (data.handoff_status) {
    showQaVerdict({ output: { final_handoff_status: data.handoff_status }, consistency_notes: data.consistency_notes || [] });
  }
  unlock('#panel-artefacts');
  renderArtefacts(artefacts);
}

// ============================================================
// Project screen: header, stepper, collapsible steps, result summary
// ============================================================
const STEP_PANELS = ['#panel-intake', '#panel-discovery', '#panel-agents', '#panel-artefacts'];
const isUnlocked = (sel) => !$(sel).classList.contains('is-locked');
const clip = (s, n) => (s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s);

function verdictClass(v) { return v === 'GO' ? 'status-ready' : v === 'RETHINK' ? 'status-not-ready' : 'status-warnings'; }

function updateProjectHeader() {
  const idea = ($('#idea-input').value || '').trim();
  const has = !!projectId;
  $('#tb-eyebrow').textContent = has ? 'PROJECT' : 'NEW PROJECT';
  $('#tb-title').textContent = has && idea ? idea : 'What do you want to build?';
  $('#tb-crumb').textContent = has && idea ? clip(idea, 60) : 'New project';
  $('#ph-meta').hidden = !has;
  const dom = $('#tb-domain').textContent;
  $('#ph-domain-chip').hidden = !has || !dom || dom === '—';
  if (dom && dom !== '—') $('#tb-domain').textContent = dom.replace(/_/g, ' ');
}

function updateStepper() {
  const steps = document.querySelectorAll('#stepper .step');
  steps.forEach((btn, i) => {
    const unlocked = i === 0 || isUnlocked(STEP_PANELS[i]);
    const nextUnlocked = i < 3 && isUnlocked(STEP_PANELS[i + 1]);
    let state = 'todo';
    if (unlocked) state = (i < 3 ? nextUnlocked : !!lastHandoffStatus) ? 'done' : 'active';
    btn.dataset.state = state;
    btn.disabled = !unlocked;
    btn.querySelector('.step-dot').textContent = state === 'done' ? '✓' : String(i + 1);
    btn.setAttribute('aria-current', state === 'active' ? 'step' : 'false');
  });
}

function updatePanelSummaries() {
  const idea = ($('#idea-input').value || '').trim();
  setPanelSummary('#panel-intake', idea ? clip(idea, 90) : '');
  if (questions.length) {
    const done = questions.filter(q => dfAnswers[q.id] || dfSkipped[q.id]).length;
    setPanelSummary('#panel-discovery', `${done} of ${questions.length} answered`);
  }
}
function setPanelSummary(sel, text) {
  const s = $(sel).querySelector('.panel-summary');
  if (s) s.textContent = text;
}

function setCollapsed(sel, collapsed) {
  const p = $(sel);
  p.classList.toggle('is-collapsed', collapsed);
  const head = p.querySelector('.panel-head');
  if (head) head.setAttribute('aria-expanded', String(!collapsed));
}

function updateSummary() {
  const box = $('#proj-summary');
  const docs = (typeof currentArtefacts !== 'undefined' ? currentArtefacts.length : 0);
  if (!docs) { box.hidden = true; return; }
  box.hidden = false;
  box.innerHTML = '';
  const f = lastFeasibility, c = (f && f.counts) || {};
  const answered = questions.filter(q => dfAnswers[q.id]).length, skipped = questions.filter(q => dfSkipped[q.id]).length;
  const tile = (cls, label, value, sub, target) => {
    const t = el('button', { type: 'button', class: `sum-tile ${cls}` }, [
      el('span', { class: 'sum-label', text: label }),
      el('span', { class: 'sum-value', text: value }),
      el('span', { class: 'sum-sub', text: sub }),
    ]);
    t.addEventListener('click', () => goToStep(target));
    box.appendChild(t);
  };
  if (f) tile(verdictClass(f.verdict), 'Feasibility', f.verdict || 'n/a',
    `${c.critical || 0} critical · ${c.major || 0} major · ${c.minor || 0} minor`, '#panel-agents');
  tile(lastHandoffStatus ? statusSlug(lastHandoffStatus) : 'status-unknown', 'Handoff status',
    lastHandoffStatus ? lastHandoffStatus.replace(/ FOR DESIGN AGENT/i, '') : '—',
    lastHandoffStatus ? (lastNotesCount ? `${lastNotesCount} consistency note${lastNotesCount === 1 ? '' : 's'}` : 'for the design agent') : 'not validated yet', '#panel-agents');
  tile('status-info', 'Documents', `${docs} / ${DASH_TOTAL_DOCS}`, 'Word · Markdown export', '#panel-artefacts');
  if (questions.length) tile('status-info', 'Discovery', `${answered} / ${questions.length}`, skipped ? `${skipped} skipped` : 'all answered', '#panel-discovery');
}

function goToStep(sel) {
  if (!isUnlocked(sel)) return;
  setCollapsed(sel, false);
  $(sel).scrollIntoView({ behavior: 'smooth', block: 'start' });
}

(function wireProjectScreen() {
  // collapsible panels
  STEP_PANELS.forEach(sel => {
    const panel = $(sel), head = panel.querySelector('.panel-head');
    head.classList.add('is-collapsible');
    head.setAttribute('role', 'button'); head.setAttribute('tabindex', '0'); head.setAttribute('aria-expanded', 'true');
    head.querySelector('.panel-title').after(el('span', { class: 'panel-summary' }));
    head.appendChild(el('span', { class: 'panel-caret', 'aria-hidden': 'true', text: '▾' }));
    const toggle = () => { if (!head.classList.contains('is-collapsible')) return; setCollapsed(sel, !panel.classList.contains('is-collapsed')); };
    head.addEventListener('click', toggle);
    head.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
  });

  // stepper navigation
  document.querySelectorAll('#stepper .step').forEach(btn => btn.addEventListener('click', () => goToStep(btn.dataset.target)));

  // when a step unlocks, fold the finished earlier steps away (they stay one click from reopening)
  const seen = new Set();
  const onPanelChange = () => {
    STEP_PANELS.forEach((sel, i) => {
      if (i > 0 && isUnlocked(sel) && !seen.has(sel)) {
        seen.add(sel);
        if (i - 1 <= 1) setCollapsed(STEP_PANELS[i - 1], true);   // fold Idea / Discovery, keep results open
      }
    });
    $('#panel-intake .panel-head').classList.toggle('is-collapsible', isUnlocked('#panel-discovery'));
    updatePanelSummaries(); updateStepper(); updateProjectHeader();
  };
  const obs = new MutationObserver(onPanelChange);
  STEP_PANELS.forEach(sel => obs.observe($(sel), { attributes: true, attributeFilter: ['class'] }));
  onPanelChange();
})();

// ============================================================
// Startup — runs last, once every function and constant above exists.
// The URL carries the open project (#project=<id>), so a refresh, a browser "reopen closed tab"
// or a bookmarked link lands back on the same project instead of an empty form.
// ============================================================
(function bootstrapView() {
  refreshDomainCount();
  const hashProjectId = (location.hash.match(/project=([\w-]+)/) || [])[1];
  if (hashProjectId) {
    showPipelineView();
    resumeProject(hashProjectId);
  } else if (sessionStorage.getItem('poc_view') === 'pipeline') {
    sessionStorage.removeItem('poc_view');
    showPipelineView();
    restoreIdeaDraft();
  } else {
    loadDashboard();
  }
})();
